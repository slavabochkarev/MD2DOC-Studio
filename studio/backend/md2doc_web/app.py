from __future__ import annotations

import os
from pathlib import Path
import threading

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from md2doc import __version__
from md2doc.renderers.images import image_data
from md2doc.diagnostics.report import BuildError

from .repository import Repository, StudioError, safe_path, digest
from .jobs import JobRunner
from .preview import markdown_preview
from .windows_shell import open_in_default_application, reveal_in_explorer, choose_project_folder
from .editing import config_file, save_markdown, validate_yaml, save_yaml


class OpenRequest(BaseModel):
    path: str


class SettingsRequest(BaseModel):
    project: str
    revision: str
    patches: list[dict] = Field(default_factory=list)


class BuildRequest(BaseModel):
    project: str
    revision: str
    output: str | None = None
    strict: bool = False


class TextRequest(BaseModel):
    project: str
    path: str
    text: str
    revision: str
    file_revision: str


class YamlRequest(BaseModel):
    project: str
    kind: str
    text: str
    revision: str
    file_revision: str


def create_app(repo_root=None, cache=None):
    repo_root = Path(repo_root or Path(__file__).resolve().parents[3])
    cache = Path(cache or os.environ.get('MD2DOC_STUDIO_DATA', Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local/share')) / 'MD2DOCStudio'))
    repository = Repository(cache)
    runner = JobRunner(repo_root, repository)
    mutation_lock = threading.RLock()
    app = FastAPI(title='MD2DOC Studio', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.repository, app.state.runner = repository, runner

    @app.exception_handler(StudioError)
    async def studio_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'message': str(exc), 'diagnostics': exc.diagnostics})

    @app.exception_handler(OSError)
    async def io_error(request, exc):
        return JSONResponse(status_code=409, content={'message': f'Ошибка доступа к файлу: {exc}', 'diagnostics': []})

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        if host not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
            return JSONResponse(status_code=403, content={'message': 'Studio доступна только через localhost.'})
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return JSONResponse(status_code=403, content={'message': 'Запрос из другого сайта отклонён.'})
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse(status_code=403, content={'message': 'Запрос из другого сайта отклонён.'})
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    def idle():
        if runner.busy():
            raise StudioError('Дождитесь завершения или отмените формирование документа.', 409)

    @app.get('/api/health')
    def health():
        return {'application': 'md2doc-studio', 'status': 'ok', 'converter_version': __version__, 'local': True}

    @app.get('/api/session')
    def session():
        project = next(iter(repository.projects.values()), None)
        job = runner.state()
        if not project:
            return {'project': None, 'job': None}
        with project.lock:
            return {'project': project.dto(), 'job': job if job and job['project_id'] == project.id else None}

    @app.post('/api/project/open')
    def open_project(body: OpenRequest):
        with mutation_lock:
            idle()
            return repository.open(body.path).dto()

    @app.post('/api/project/choose')
    def choose_project(body: OpenRequest):
        idle()
        path = choose_project_folder(body.path)
        return {'path':path,'cancelled':path is None}

    @app.get('/api/project/{project_id}')
    def project_state(project_id: str):
        project = repository.get(project_id)
        with project.lock:
            return project.dto()

    @app.get('/api/markdown')
    def markdown(project: str, path: str):
        return markdown_preview(repository.get(project), path)

    @app.post('/api/text/markdown/preview')
    def markdown_draft(body: TextRequest):
        project = repository.get(body.project)
        with project.lock:
            return markdown_preview(project, body.path, body.text)

    @app.post('/api/text/markdown/save')
    def markdown_save(body: TextRequest):
        with mutation_lock:
            idle()
            return save_markdown(repository.get(body.project),body.path,body.text,body.revision,body.file_revision)

    @app.get('/api/text/config')
    def raw_config(project: str, kind: str):
        project = repository.get(project)
        with project.lock:
            return config_file(project,kind)

    @app.post('/api/text/yaml/validate')
    def yaml_validate(body: YamlRequest):
        with mutation_lock:
            idle()
            return validate_yaml(repository.get(body.project),body.kind,body.text,body.revision,body.file_revision)

    @app.post('/api/text/yaml/save')
    def yaml_save(body: YamlRequest):
        with mutation_lock:
            idle()
            return save_yaml(repository.get(body.project),body.kind,body.text,body.revision,body.file_revision)

    @app.get('/api/asset')
    def asset(project: str, path: str):
        resource = safe_path(repository.get(project).root, path)
        if resource.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.svg'):
            raise StudioError('Этот тип ресурса не поддерживается.', 422)
        try:
            stream, natural = image_data(resource)
            data = stream.getvalue()
            return Response(data, media_type='image/jpeg' if data.startswith(b'\xff\xd8') else 'image/png')
        except BuildError as exc:
            raise StudioError(str(exc), 422) from exc

    @app.post('/api/settings/preview')
    def preview(body: SettingsRequest):
        with mutation_lock:
            idle()
            project = repository.get(body.project)
            with project.lock, project.candidate(body.revision, body.patches) as (root, changes):
                outline, diagnostics = project.outline(root)
                return {'outline': outline, 'diagnostics': diagnostics}

    @app.post('/api/settings/save')
    def save(body: SettingsRequest):
        with mutation_lock:
            idle()
            project, backup = repository.get(body.project).save(body.revision, body.patches)
            return {'project': project, 'backup': backup}

    @app.post('/api/build', status_code=202)
    def build(body: BuildRequest):
        with mutation_lock:
            return runner.start(body.project, body.revision, body.output, body.strict)

    @app.get('/api/job')
    def job():
        return runner.state()

    @app.post('/api/job/cancel')
    def cancel():
        return runner.cancel()

    def artifact():
        data = runner.state()
        if not data or not data.get('artifact'):
            raise StudioError('Нет успешно сформированного документа.', 404)
        path = Path(data['artifact']['path'])
        if not path.is_file():
            raise StudioError('Готовый DOCX перемещён или удалён.', 404)
        if digest(path.read_bytes()) != data['artifact']['sha256']:
            raise StudioError('DOCX изменён вне Studio. Сформируйте его заново.', 409)
        return path

    @app.get('/api/result/download')
    def download():
        path = artifact()
        return FileResponse(path, filename=path.name, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    @app.post('/api/result/open')
    def open_result():
        path = artifact()
        return open_in_default_application(path)

    @app.post('/api/result/reveal')
    def reveal_result():
        path = artifact()
        return reveal_in_explorer(path)

    frontend = repo_root / 'studio/frontend/build'
    if frontend.is_dir():
        app.mount('/', StaticFiles(directory=frontend, html=True), name='frontend')
    return app
