from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import uuid

from md2doc.core.builder import protected_output
from md2doc.diagnostics.report import BuildError

from .repository import StudioError, atomic_write, digest, snapshot_copy, assert_snapshot_current


class JobRunner:
    """One current job, using the unchanged CLI and delivery verification tool."""
    def __init__(self, repo_root, repository):
        self.repo_root = Path(repo_root)
        self.repository = repository
        self.lock = threading.RLock()
        self.cancel_event = threading.Event()
        self.current = None

    def busy(self):
        with self.lock:
            return bool(self.current and self.current['status'] in ('queued', 'snapshot', 'input', 'build', 'delivery', 'publishing'))

    def state(self):
        with self.lock:
            if not self.current:
                return None
            data = dict(self.current)
            data['elapsed'] = round(time.monotonic() - data.pop('_started'), 2) if 'finished_elapsed' not in data else data.pop('finished_elapsed')
            data.pop('_started', None)
            return data

    def update(self, **fields):
        with self.lock:
            self.current.update(fields)

    def start(self, project_id, revision, output=None, strict=False):
        with self.lock:
            if self.busy():
                raise StudioError('Формирование документа уже выполняется.', 409)
            project = self.repository.get(project_id)
            project.assert_current(revision)
            _, diagnostics = project.outline()
            if any(d['severity'] == 'error' for d in diagnostics):
                raise StudioError('Сначала исправьте ошибки проекта.', 422, diagnostics)
            requested = Path(output).expanduser() if output else project.root / project.configs['document']['build']['output_dir'] / project.configs['document']['build']['output_name']
            if not requested.is_absolute():
                raise StudioError('Для результата нужен абсолютный путь.', 422)
            try:
                target = protected_output(requested, project.root, SimpleNamespace(manifest=project.configs['document']))
            except BuildError as exc:
                raise StudioError(str(exc), 422) from exc
            previous = self.current.get('artifact') if self.current and self.current['project_id'] == project_id else None
            self.cancel_event.clear()
            self.current = {'id': uuid.uuid4().hex, 'project_id': project_id, 'status': 'queued', 'strict': strict, 'target': str(target), 'diagnostics': [], 'artifact': previous, '_started': time.monotonic()}
            threading.Thread(target=self._run, args=(project, revision, target, strict), daemon=True).start()
            return self.state()

    def cancel(self):
        with self.lock:
            if self.current and self.current['status'] == 'publishing':
                raise StudioError('Результат уже публикуется; дождитесь завершения.', 409)
            if self.busy():
                self.cancel_event.set()
            return self.state()

    def _command(self, argv):
        if self.cancel_event.is_set():
            raise InterruptedError('Формирование отменено.')
        env = os.environ.copy()
        env['PYTHONPATH'] = str(self.repo_root / 'src')
        env['PYTHONIOENCODING'] = 'utf-8'
        env.pop('PYTHONSTARTUP', None)
        process = subprocess.Popen([sys.executable, *map(str, argv)], cwd=self.repo_root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        deadline = time.monotonic() + 300
        while True:
            try:
                stdout, stderr = process.communicate(timeout=.2)
                return process.returncode, stdout.decode('utf-8', 'replace')[-16000:], stderr.decode('utf-8', 'replace')[-16000:]
            except subprocess.TimeoutExpired:
                if self.cancel_event.is_set() or time.monotonic() > deadline:
                    process.terminate()
                    try:
                        process.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                    if self.cancel_event.is_set():
                        raise InterruptedError('Формирование отменено.')
                    raise StudioError('Превышено время выполнения конвертера (300 с).', 500)

    def _read_report(self, path, code, stdout, stderr, project, snapshot, expected, phase):
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise StudioError(f'Конвертер не вернул корректный отчёт. Exit={code}. {stderr or stdout}', 500)
        diagnostics = []
        for severity, collection in [('error', report.get('errors', [])), ('warning', report.get('warnings', []))]:
            for entry in collection:
                entry = dict(entry)
                if entry.get('source'):
                    try:
                        entry['source'] = Path(entry['source']).resolve().relative_to(snapshot).as_posix()
                    except ValueError:
                        if Path(entry['source']).name == 'document.docx':
                            entry['source'] = self.current['target']
                context = entry.get('context') or ''
                for kind in ('styles', 'metadata'):
                    if context.startswith(kind + '.'):
                        entry['source'] = project.paths[kind].relative_to(project.root).as_posix()
                diagnostics.append({**entry, 'severity': severity, 'phase': phase})
        with self.lock:
            known = self.current['diagnostics']
            for entry in diagnostics:
                if not any(all(old.get(k) == entry.get(k) for k in ('code', 'message', 'source', 'context', 'severity')) for old in known):
                    known.append(entry)
        if code or report.get('status') != expected:
            raise StudioError(f'{phase}: проверка не пройдена.', 422)
        return report

    def _run(self, project, revision, target, strict):
        try:
            with tempfile.TemporaryDirectory(prefix='build-', dir=self.repository.cache / 'work') as temporary:
                work = Path(temporary)
                snapshot = work / 'project'
                snapshot.mkdir()
                self.update(status='snapshot')
                with project.lock:
                    project.assert_current(revision)
                    fingerprints = snapshot_copy(project.root, snapshot)
                    project.assert_current(revision)
                artifacts = work / 'artifacts'
                artifacts.mkdir()
                docx = artifacts / 'document.docx'
                verifier = self.repo_root / 'tools/verify_delivery'
                extra = ['--strict'] if strict else []
                self.update(status='input')
                report_path = artifacts / 'input.json'
                result = self._command([verifier, snapshot, '--input-only', '--json', report_path, *extra])
                self._read_report(report_path, *result, project, snapshot, 'validated', 'Проверка проекта')
                self.update(status='build')
                result = self._command(['-m', 'md2doc', 'build', snapshot, '--output', docx, '--verbose', *extra])
                build_report = self._read_report(artifacts / 'build-report.json', *result, project, snapshot, 'success', 'Формирование DOCX')
                self.update(status='delivery')
                report_path = artifacts / 'delivery.json'
                result = self._command([verifier, snapshot, '--output', docx, '--json', report_path, *extra])
                self._read_report(report_path, *result, project, snapshot, 'verified', 'Проверка DOCX')
                data = docx.read_bytes()
                project.assert_current(revision)
                assert_snapshot_current(project.root, fingerprints)
                with self.lock:
                    if self.cancel_event.is_set():
                        raise InterruptedError('Формирование отменено.')
                    self.current['status'] = 'publishing'
                    # Cross-volume staging is copied into a temporary beside the final
                    # target. The existing result is replaced only after both gates.
                    atomic_write(target, data)
                    status = 'warning' if any(d['severity'] == 'warning' for d in self.current['diagnostics']) else 'success'
                    self.current.update(status=status, artifact={'path': str(target), 'name': target.name, 'sha256': digest(data), 'revision': revision}, counters={key: build_report.get(key, 0) for key in ('processed_files', 'sections', 'tables', 'images')})
        except InterruptedError as exc:
            self.update(status='cancelled', message=str(exc))
        except (StudioError, OSError, ValueError) as exc:
            with self.lock:
                if not any(d['severity'] == 'error' for d in self.current['diagnostics']):
                    self.current['diagnostics'].append({'code': 'STUDIO_BUILD', 'severity': 'error', 'message': str(exc), 'source': str(target)})
                self.current.update(status='failed', message=str(exc))
        except Exception as exc:
            self.update(status='failed', message=str(exc), diagnostics=[{'code': 'STUDIO_INTERNAL', 'severity': 'error', 'message': f'{type(exc).__name__}: {exc}'}])
        finally:
            with self.lock:
                self.current['finished_elapsed'] = round(time.monotonic() - self.current['_started'], 2)
