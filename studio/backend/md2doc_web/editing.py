"""Project-scoped text buffers; validation always uses the existing MD2DOC gate."""
from contextlib import contextmanager
from pathlib import Path
import tempfile

from md2doc.config.validation import load_config, ConfigError
from md2doc.diagnostics.delivery import verify_delivery

from .repository import StudioError, Project, safe_path, digest, snapshot_copy, assert_snapshot_current, EXCLUDED_DIRS


def source_path(project, relative):
    path = safe_path(project.root, relative)
    if path.suffix.lower() != '.md' or path in project.paths.values() or any(p in EXCLUDED_DIRS for p in path.relative_to(project.root).parts):
        raise StudioError('Редактировать можно только Markdown-файлы текущего проекта.', 403)
    if not path.is_file():
        raise StudioError('Файл отсутствует. Создание файлов в этом редакторе не предусмотрено.', 404)
    return path


def decode(data):
    try:
        return data.decode('utf-8-sig').replace('\r\n','\n')
    except UnicodeError as exc:
        raise StudioError('Редактор поддерживает UTF-8. Файл не изменён.', 422) from exc


def encode(text, original):
    if '\x00' in text:
        raise StudioError('Нулевой символ недопустим в текстовом файле.', 422)
    normalized = text.replace('\r\n','\n')
    if b'\r\n' in original:
        normalized = normalized.replace('\n','\r\n')
    try:
        return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'') + normalized.encode('utf-8')
    except UnicodeError as exc:
        raise StudioError('Текст содержит некорректный Unicode. Файл не изменён.',422) from exc


def config_file(project, kind):
    if kind not in ('document','styles','metadata'):
        raise StudioError('Неизвестная конфигурация.', 422)
    # Paths were resolved from the actual manifest, not hard-coded filenames.
    path = project.paths[kind]
    data = path.read_bytes()
    return {'kind':kind,'path':path.relative_to(project.root).as_posix(),'text':decode(data),'file_revision':digest(data)}


def save_markdown(project, relative, text, revision, file_revision):
    with project.lock:
        project.assert_current(revision)
        path = source_path(project, relative)
        original = path.read_bytes()
        if digest(original) != file_revision:
            raise StudioError('Markdown изменён вне Studio. Черновик сохранён в редакторе; перечитайте файл перед повторной записью.', 409)
        data = encode(text, original)
        backup = project.commit({'markdown':(path,original,data)}) if original != data else None
        return {'project':project.dto(),'backup':backup,'file_revision':digest(data)}


@contextmanager
def yaml_candidate(project, kind, text, revision, file_revision):
    with project.lock:
        project.assert_current(revision)
        if kind not in project.paths:
            raise StudioError('Неизвестная конфигурация.', 422)
        original = project.originals[kind]
        if digest(original) != file_revision:
            raise StudioError('Версия YAML устарела. Ваш черновик не записан.', 409)
        data = encode(text, original)  # Save the user's text verbatim, including comments/extensions.
        with tempfile.TemporaryDirectory(prefix='yaml-', dir=project.cache/'work') as temporary:
            root = Path(temporary)/'project'
            root.mkdir()
            fingerprints = snapshot_copy(project.root, root)
            target = root/project.paths[kind].relative_to(project.root)
            target.write_bytes(data)
            try:
                # Check reference containment BEFORE the validator can follow changed links.
                candidate = Project(root, project.cache)
                if candidate.configs['document']['schema_version'] != project.configs['document']['schema_version']:
                    raise StudioError('Смена версии схемы требует отдельной миграции проекта.', 422)
                report, headings, code = verify_delivery(root, input_only=True)
            except StudioError as exc:
                raise StudioError(str(exc).replace(str(root),str(project.root)),exc.status,exc.diagnostics) from exc
            except ConfigError as exc:
                raise StudioError(str(exc).replace(str(root),str(project.root)),422) from exc
            if code:
                raise StudioError('YAML или проект не прошёл проверку MD2DOC. Файлы не изменены.',422,candidate.diagnostics(report,root))
            assert_snapshot_current(project.root,fingerprints)
            yield candidate, data, candidate.diagnostics(report,root)


def validate_yaml(project, kind, text, revision, file_revision):
    with yaml_candidate(project,kind,text,revision,file_revision) as (candidate,data,diagnostics):
        outline, more = candidate.outline()
        return {'valid':True,'diagnostics':diagnostics,'outline':outline,'styles':candidate.configs['styles']}


def save_yaml(project, kind, text, revision, file_revision):
    with yaml_candidate(project,kind,text,revision,file_revision) as (candidate,data,diagnostics):
        project.assert_current(revision)
        original = project.originals[kind]
        backup = project.commit({kind:(project.paths[kind],original,data)}) if original != data else None
        project.reload()  # Follow new styles/metadata references only after a validated commit.
        return {'project':project.dto(),'backup':backup,'file':config_file(project,kind)}
