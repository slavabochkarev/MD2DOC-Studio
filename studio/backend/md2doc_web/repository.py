from __future__ import annotations

from contextlib import contextmanager
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid

from ruamel.yaml import YAML
from ruamel.yaml.tokens import CommentToken

from md2doc.config.validation import load_config, ConfigError
from md2doc.core.project_loader import load_project
from md2doc.core.structure_builder import build_structure
from md2doc.core.heading_numbering import walk_blocks
from md2doc.core.style_resolver import StyleResolver
from md2doc.config.heading_numbering import level_options, merge_options
from md2doc.core.markdown_parser import substitute
from md2doc.diagnostics.report import BuildReport, BuildError
from md2doc.diagnostics.delivery import verify_delivery


class StudioError(Exception):
    def __init__(self, message, status=400, diagnostics=None):
        super().__init__(message)
        self.status = status
        self.diagnostics = diagnostics or []


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or '\\' in relative or Path(relative).is_absolute():
        raise StudioError('Ожидается относительный путь внутри проекта.')
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise StudioError('Путь выходит за пределы проекта.', 403)
    return target


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.studio-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


# Editable paths only. Types/ranges are validated by the existing md2doc validator.
FONT = r'(family|size|color|bold|italic|underline|strike|case|character_spacing)'
PARAGRAPH = r'(alignment|first_line|indent_left|indent_right|space_before|space_after|widow_control|keep_with_next|keep_together|page_break_before|line_spacing\.(mode|value))'
NUMBER = r'(enabled|display|format|template|start|restart|reset|number_text_separator)'
STYLE_PATHS = re.compile(
    rf'^(page\.(paper|orientation|margins\.(top|bottom|left|right)|header_distance|footer_distance|mirror_margins)'
    rf'|font\.{FONT}|paragraph\.{PARAGRAPH}'
    rf'|headings\.h[1-6]\.(font\.{FONT}|paragraph\.{PARAGRAPH})'
    rf'|heading_numbering\.(enabled|separator|number_text_separator|levels\.h[1-6]\.{NUMBER})'
    r'|lists\.(max_depth|ordered_start|indent_per_level|hanging|space_before|space_after|bullet_markers|ordered_formats)'
    r'|tables\.(width|alignment|border\.(style|width|color)|header_fill|repeat_header|allow_row_split|banded_rows\.(enabled|odd|even)|cell_padding\.(top|bottom|left|right))'
    r'|images\.(max_width|alignment|space_before|space_after|caption\.(enabled|style|position|template)|numbering\.(enabled|scope|start))'
    r'|headers_footers\.(header_text|footer_text|different_first_page|first_page\.(header_text|footer_text|show_page_number)|page_number\.(visible|position|start|format))'
    r'|breaks\.(soft_line_break|table_pagination|code_long_lines|hyphenation\.(enabled|language|consecutive_limit)))$'
)


def apply_patches(configs, patches):
    for patch in patches:
        path, op = patch.get('path', ''), patch.get('op', 'set')
        if not isinstance(path, str):
            raise StudioError('Путь настройки должен быть строкой.', 422)
        parts = path.split('.')
        if parts[0] == 'styles' and STYLE_PATHS.fullmatch('.'.join(parts[1:])):
            if parts[1] == 'heading_numbering' and configs['document']['schema_version'] != '0.2':
                raise StudioError('Нативная нумерация доступна только в схеме 0.2.', 422)
        elif path == 'document.defaults.numbering.enabled' and op == 'set':
            pass
        else:
            raise StudioError(f'Изменение этого поля не разрешено: {path}', 422)
        if op not in ('set', 'remove'):
            raise StudioError('Неизвестная операция настройки.', 422)
        if op == 'remove' and not path.startswith(('styles.headings.', 'styles.heading_numbering.')):
            raise StudioError('Удалять можно только необязательные переопределения.', 422)
        target = configs[parts[0]]
        for key in parts[1:-1]:
            if key not in target:
                if op == 'remove':
                    target = None
                    break
                target[key] = {}
            if not isinstance(target[key], dict):
                raise StudioError(f'Некорректный объект в {path}', 422)
            target = target[key]
        if target is not None:
            if op == 'remove':
                target.pop(parts[-1], None)
            else:
                target[parts[-1]] = deepcopy(patch.get('value'))


def yaml_comments(text):
    """Count real lexical comments; hashes inside scalar strings are not comments."""
    parser = YAML(typ='rt')
    parser.version = (1, 1)
    result, seen, retained = Counter(), set(), []
    def collect(value):
        if isinstance(value, CommentToken) and id(value) not in seen:
            seen.add(id(value))
            retained.append(value)
            result.update(line.strip() for line in value.value.splitlines() if line.strip().startswith('#'))
        elif isinstance(value, (list, tuple)):
            for entry in value:
                collect(entry)
    for token in parser.scan(text):
        collect(getattr(token, 'comment', None))
    return result


def serialize(original: bytes, rt_document, patches, section):
    text = original.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in text else '\n'
    try:
        json_data = json.loads(text) if text.lstrip().startswith('{') else None
    except ValueError:
        json_data = None
    if isinstance(json_data, dict):
        # JSON-compatible YAML: preserve data, ordering and the user's JSON syntax.
        data = json_data
        apply_patches({section: data, 'document': {'schema_version': '0.2'}} if section != 'document' else {'document': data}, patches)
        result = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    else:
        yaml = YAML(typ='rt')
        yaml.version = (1, 1)
        yaml.preserve_quotes = True
        node = yaml.compose(text)
        # ruamel stores comments after a root flow mapping on StreamEndToken,
        # but does not attach them to the loaded map. Preserve that exact tail.
        tail = text[node.end_mark.index:] if node.flow_style else ''
        document = yaml.load(text[:node.end_mark.index] if tail else text)
        wrapped = {section: document}
        if section != 'document':
            wrapped['document'] = {'schema_version': '0.2'}
        apply_patches(wrapped, patches)
        stream = io.StringIO()
        # Do not add a YAML version directive to existing files.
        yaml.version = None
        yaml.dump(document, stream)
        result = stream.getvalue()
        if tail:
            result = result.rstrip('\r\n') + tail
    if yaml_comments(text) - yaml_comments(result):
        raise StudioError('Визуальная запись могла бы удалить комментарий YAML. Файл не изменён; перенесите комментарий явно в редакторе YAML.',422)
    result = result.replace('\r\n', '\n').replace('\n', newline)
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + result.encode('utf-8')


EXCLUDED_DIRS = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'}


def assert_snapshot_current(root: Path, fingerprints):
    current_files = set()
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        if any((Path(current) / name).is_symlink() or (Path(current) / name).is_junction() for name in dirs):
            raise StudioError('Каталоги проекта изменились во время чтения.', 409)
        current_files.update(Path(current) / name for name in files)
    if current_files != set(fingerprints) or any(source.is_symlink() or not source.is_file() or digest(source.read_bytes()) != expected for source, expected in fingerprints.items()):
        raise StudioError('Проект изменился во время чтения или формирования. Повторите действие.', 409)


def snapshot_copy(root: Path, destination: Path):
    """Capture inputs, including unlisted content and resources; never fix the project."""
    excluded = EXCLUDED_DIRS
    fingerprints = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        current = Path(current)
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in dirs:
            folder = current / name
            if folder.is_symlink() or folder.is_junction():
                raise StudioError(f'Для снимка проекта нужны обычные каталоги, без junction/symlink: {folder}', 422)
            (destination / folder.relative_to(root)).mkdir(parents=True, exist_ok=True)
        for name in files:
            source = current / name
            if source.is_symlink():
                raise StudioError(f'Символическая ссылка не поддерживается оболочкой: {source}', 422)
            data = source.read_bytes()
            relative = source.relative_to(root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            fingerprints[source] = digest(data)
    assert_snapshot_current(root, fingerprints)
    return fingerprints


class Project:
    def __init__(self, root, cache):
        self.root = Path(root).expanduser().resolve()
        self.cache = cache
        self.id = uuid.uuid4().hex
        self.lock = threading.RLock()
        if not self.root.is_dir() or not (self.root / 'document.yaml').is_file():
            raise StudioError('В выбранном каталоге нет document.yaml.', 422)
        self.configs = {}
        self.paths = {}
        self.originals = {}
        self.hashes = {}
        self.reload()

    def reload(self):
        try:
            main = safe_path(self.root, 'document.yaml')
            main_bytes = main.read_bytes()
            manifest = load_config(main)
            if not isinstance(manifest, dict):
                raise StudioError('document.yaml должен содержать объект.', 422)
            if manifest.get('schema_version') not in ('0.1', '0.2'):
                raise StudioError('Поддерживаются схемы MD2DOC 0.1 и 0.2.', 422)
            paths = {'document': main, **{key: safe_path(self.root, manifest.get(key, '')) for key in ('styles', 'metadata')}}
            if len(set(paths.values())) != 3 or any(p.suffix.lower() == '.md' for p in paths.values()):
                raise StudioError('Три файла конфигурации должны быть разными и не совпадать с Markdown.', 422)
            originals = {key: path.read_bytes() for key, path in paths.items()}
            configs = {key: load_config(path) for key, path in paths.items()}
            if originals['document'] != main_bytes or any(path.read_bytes() != originals[key] for key, path in paths.items()):
                raise StudioError('Конфигурация изменилась во время чтения. Откройте проект повторно.', 409)
            if any(not isinstance(value, dict) for value in configs.values()):
                raise StudioError('Каждый файл конфигурации должен содержать объект.', 422)
            self.paths, self.configs = paths, configs
            self.originals = originals
            self.hashes = {key: digest(data) for key, data in self.originals.items()}
        except (ConfigError, OSError, UnicodeError) as exc:
            raise StudioError(str(exc), 422) from exc

    @property
    def revision(self):
        return digest(json.dumps(self.hashes, sort_keys=True).encode())

    def assert_current(self, revision):
        if revision != self.revision or any(not path.is_file() or digest(path.read_bytes()) != self.hashes[key] for key, path in self.paths.items()):
            raise StudioError('YAML изменён извне или в другом окне. Перечитайте проект перед сохранением; ваши изменения не записаны.', 409)

    def diagnostics(self, report, snapshot=None):
        items = []
        for severity, collection in [('error', report.errors), ('warning', report.warnings)]:
            for entry in collection:
                data = {**asdict(entry), 'severity': severity}
                source = data.get('source')
                if source:
                    try:
                        data['source'] = Path(source).resolve().relative_to(snapshot or self.root).as_posix()
                    except ValueError:
                        data['source'] = source
                context = data.get('context') or ''
                for kind in ('styles', 'metadata'):
                    if context.startswith(kind + '.'):
                        data['source'] = self.paths[kind].relative_to(self.root).as_posix()
                items.append(data)
        return items

    def outline(self, root=None):
        report = BuildReport(str(root or self.root))
        try:
            model = build_structure(load_project(root or self.root, report), report)
            result = []
            for element in model.walk():
                for block in walk_blocks(element.blocks):
                    if block.kind == 'heading':
                        result.append({'level': int(block.attrs['tag'][1:]), 'text': ''.join(i.text for i in block.inlines), 'number': block.heading_number.text if block.heading_number else element.number if block.structural else '', 'source': element.source.relative_to(root or self.root).as_posix()})
            return result, self.diagnostics(report, root)
        except BuildError:
            return [], self.diagnostics(report, root)
        except (OSError, ValueError, KeyError, RecursionError) as exc:
            return [], [{'code': 'PROJECT', 'severity': 'error', 'message': str(exc), 'source': 'document.yaml'}]

    def dto(self):
        outline, diagnostics = self.outline()
        effective = deepcopy(self.configs)
        try:
            resolver = StyleResolver(self.configs['styles'])
            effective['styles']['headings'] = {f'h{i}': resolver.resolve(functional=f'h{i}') for i in range(1, 7)}
            base = {k: v for k, v in self.configs['document']['defaults']['numbering'].items() if k != 'scope'}
            if base.get('format') == 'decimal':
                base.setdefault('template', '{path}')
            numbering = merge_options(base, self.configs['styles'].get('heading_numbering', {}))
            numbering = merge_options(numbering, self.configs['document']['defaults'].get('heading_numbering', {}))
            effective['styles']['heading_numbering'] = {'enabled': numbering.get('enabled', True), 'separator': numbering.get('separator', '.'), 'levels': {f'h{i}': level_options(numbering, i) for i in range(1, 7)}}
        except (KeyError, ValueError, TypeError):
            pass
        def nodes(elements, active=True):
            result = []
            for node in elements:
                if not isinstance(node, dict):
                    continue
                entry = deepcopy(node)
                entry['active'] = active and node.get('enabled', True)
                try:
                    source = safe_path(self.root, node.get('source', ''))
                    entry['exists'] = source.is_file()
                    text = source.read_text(encoding='utf-8-sig') if source.is_file() else ''
                except (StudioError, OSError, UnicodeError):
                    entry['exists'], text = False, ''
                heading = node.get('heading') or {}
                entry['label'] = heading.get('text') if heading.get('from') == 'yaml' else next((re.sub(r'^\s*#{1,6}\s+', '', line) for line in text.splitlines() if re.match(r'^\s*#{1,6}\s+', line)), node.get('id', 'Без названия'))
                try:
                    entry['label'] = substitute(str(entry['label'] or node.get('id', 'Без названия')), self.configs['metadata'])
                except KeyError:
                    pass
                entry['children'] = nodes(node.get('children', []), entry['active'])
                result.append(entry)
            return result
        files = []
        for current, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = [x for x in dirs if x not in {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache'} and not (Path(current) / x).is_symlink() and not (Path(current) / x).is_junction()]
            for name in sorted(names):
                path = Path(current) / name
                if not path.is_symlink():
                    files.append({'path': path.relative_to(self.root).as_posix(), 'kind': path.suffix.lower(), 'size': path.stat().st_size})
        overrides = sum(bool(node.get('numbering') or node.get('heading_numbering')) for node in self._walk())
        return {'id': self.id, 'root': str(self.root), 'title': self.configs['metadata'].get('title', self.root.name), 'schema': self.configs['document']['schema_version'], 'revision': self.revision, 'configs': self.configs, 'effective': effective, 'config_paths': {key: path.relative_to(self.root).as_posix() for key, path in self.paths.items()}, 'nodes': nodes(self.configs['document'].get('elements', [])), 'files': files, 'outline': outline, 'diagnostics': diagnostics, 'numbering_overrides': overrides}

    def _walk(self, elements=None):
        for node in self.configs['document'].get('elements', []) if elements is None else elements:
            if isinstance(node, dict):
                yield node
                yield from self._walk(node.get('children', []))

    @contextmanager
    def candidate(self, revision, patches):
        self.assert_current(revision)
        configs = deepcopy(self.configs)
        apply_patches(configs, patches)
        grouped = {kind: [p for p in patches if p['path'].startswith(kind + '.')] for kind in ('document', 'styles', 'metadata')}
        changed = {kind: serialize(self.originals[kind], self.configs[kind], group, kind) for kind, group in grouped.items() if group}
        with tempfile.TemporaryDirectory(prefix='settings-', dir=self.cache / 'work') as temporary:
            root = Path(temporary) / 'project'
            root.mkdir()
            fingerprints = snapshot_copy(self.root, root)
            for kind, data in changed.items():
                relative = self.paths[kind].relative_to(self.root)
                target = root / relative
                target.write_bytes(data)
                if load_config(target) != configs[kind]:
                    raise StudioError('Сериализация изменила другие значения YAML. Запись отменена.', 422)
            report, headings, code = verify_delivery(root, input_only=True)
            if code:
                raise StudioError('Настройки или проект не прошли проверку MD2DOC.', 422, self.diagnostics(report, root))
            assert_snapshot_current(self.root, fingerprints)
            yield root, changed

    def save(self, revision, patches):
        with self.lock:
            if not patches:
                self.assert_current(revision)
                return self.dto(), None
            with self.candidate(revision, patches) as (root, changed):
                self.assert_current(revision)
                backup = self.commit({kind:(self.paths[kind],self.originals[kind],data) for kind,data in changed.items()})
                self.reload()
                return self.dto(), backup

    def commit(self, changes):
        """Back up exact bytes and journal the same atomic writes for all editors."""
        txn = uuid.uuid4().hex
        backup = self.cache / 'backups' / digest(str(self.root).encode())[:16] / txn
        backup.mkdir(parents=True)
        entries = []
        for kind,(target,original,data) in changes.items():
            saved = backup / (kind + '.original')
            atomic_write(saved, original)
            entries.append({'target':str(target),'backup':str(saved),'before':digest(original),'after':digest(data),'kind':kind})
        journal = self.cache / 'transactions' / (txn + '.json')
        info = {'root':str(self.root),'status':'pending','entries':entries}
        write_json(journal, info)
        try:
            for entry in entries:
                if digest(Path(entry['target']).read_bytes()) != entry['before']:
                    raise StudioError('Файл изменился перед записью. Ваш черновик не сохранён.', 409)
                atomic_write(Path(entry['target']), changes[entry['kind']][2])
            info['status'] = 'committed'
            write_json(journal, info)
        except Exception:
            recover_journal(journal)
            raise
        return str(backup)


def recover_journal(journal: Path):
    info = json.loads(journal.read_text(encoding='utf-8'))
    if info['status'] != 'pending':
        return
    root = Path(info['root']).resolve()
    for entry in info['entries']:
        target = Path(entry['target']).resolve()
        is_markdown = entry.get('kind') == 'markdown'
        if not target.is_relative_to(root) or (target.suffix.lower() == '.md') != is_markdown:
            raise StudioError('Некорректный журнал восстановления.', 409)
        current = digest(target.read_bytes()) if target.is_file() else None
        if current not in (entry['before'], entry['after']):
            raise StudioError(f'Конфликт восстановления. Сохранена резервная копия: {entry["backup"]}', 409)
        if digest(Path(entry['backup']).read_bytes()) != entry['before']:
            raise StudioError('Резервная копия повреждена; автоматическое восстановление отменено.', 409)
    for entry in info['entries']:
        target = Path(entry['target'])
        if digest(target.read_bytes()) == entry['after']:
            atomic_write(target, Path(entry['backup']).read_bytes())
    info['status'] = 'rolled_back'
    write_json(journal, info)


class Repository:
    def __init__(self, cache):
        self.cache = Path(cache).resolve()
        for folder in ['work', 'backups', 'transactions']:
            (self.cache / folder).mkdir(parents=True, exist_ok=True)
        self.projects = {}
        self.lock = threading.RLock()

    def open(self, root):
        with self.lock:
            canonical = Path(root).expanduser().resolve()
            if self.cache.is_relative_to(canonical):
                raise StudioError('Служебный каталог Studio не должен находиться внутри проекта.', 422)
            for journal in (self.cache / 'transactions').glob('*.json'):
                info = json.loads(journal.read_text(encoding='utf-8'))
                if Path(info['root']).resolve() == canonical:
                    recover_journal(journal)
            project = Project(canonical, self.cache)
            self.projects = {project.id: project}
            return project

    def get(self, project_id):
        if project_id not in self.projects:
            raise StudioError('Проект не открыт или был переключён. Откройте его заново.', 404)
        return self.projects[project_id]
