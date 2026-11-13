from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import time
from zipfile import ZipFile

import pytest
from md2doc.config.validation import load_config
from md2doc_web import repository as storage
from md2doc_web.repository import digest
from conftest import ROOT, settings


def hashes(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in root.rglob('*') if p.is_file()}


def wait_job(client):
    end = time.monotonic() + 90
    while time.monotonic() < end:
        state = client.get('/api/job').json()
        if state['status'] in ('success', 'warning', 'failed', 'cancelled'):
            return state
        time.sleep(.05)
    pytest.fail('Build did not finish in 90 seconds')


def test_real_open_and_markdown(client, opened, project_copy):
    assert opened['schema'] == '0.2'
    assert opened['nodes'] and opened['outline'] and opened['files']
    assert opened['configs']['styles']['font']['family']
    source = next(f['path'] for f in opened['files'] if f['kind'] == '.md')
    response = client.get('/api/markdown', params={'project': opened['id'], 'path': source})
    assert response.status_code == 200, response.text
    assert response.json()['text'] == (project_copy / source).read_text(encoding='utf-8-sig')
    assert response.json()['html']


def test_ecoburo_save_build_delivery(client, opened, project_copy):
    before = hashes(project_copy)
    styles = project_copy / opened['config_paths']['styles']
    # Extension fields are legitimate schema extensions and must survive.
    content = json.loads(styles.read_text(encoding='utf-8-sig'))
    content['x-studio-test'] = {'unknown': ['keep', 17, True]}
    styles.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    opened = client.post('/api/project/open', json={'path': str(project_copy)}).json()
    payload = settings(opened, 'styles.font.size', 13)
    payload['patches'] += [{'path': 'styles.page.margins.left', 'value': '25mm'}]
    preview = client.post('/api/settings/preview', json=payload)
    assert preview.status_code == 200, preview.text
    assert load_config(styles)['font']['size'] == 14
    response = client.post('/api/settings/save', json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert Path(data['backup']).is_dir()
    assert load_config(styles)['x-studio-test'] == content['x-studio-test']
    assert load_config(styles)['font']['size'] == 13
    after = hashes(project_copy)
    assert all(after[p] == h for p, h in before.items() if p != opened['config_paths']['styles'])
    result = project_copy.parent / 'result.docx'
    result.write_bytes(b'old result')
    response = client.post('/api/build', json={'project': opened['id'], 'revision': data['project']['revision'], 'output': str(result)})
    assert response.status_code == 202, response.text
    state = wait_job(client)
    assert state['status'] in ('success', 'warning'), state
    assert state['artifact']['sha256'] == digest(result.read_bytes())
    with ZipFile(result) as archive:
        xml = archive.read('word/styles.xml').decode()
        assert 'w:val="26"' in xml  # 13 pt in half-points, not just a successful HTTP response.
        assert archive.read('word/document.xml')
    downloaded = client.get('/api/result/download')
    assert downloaded.content == result.read_bytes()
    assert hashes(project_copy) == after
    # Strict mode rejects the x-* warning and leaves the previous verified file.
    old = result.read_bytes()
    client.post('/api/build', json={'project': opened['id'], 'revision': data['project']['revision'], 'output': str(result), 'strict': True})
    failed = wait_job(client)
    assert failed['status'] == 'failed'
    assert result.read_bytes() == old
    assert failed['artifact']['sha256'] == digest(old)
    result.write_bytes(b'externally changed')
    assert client.get('/api/result/download').status_code == 409


@pytest.mark.parametrize('path,value', [('styles.font.size', -1), ('styles.page.paper', 'A0'), ('styles.heading_numbering.levels.h2.template', '{bad}'), ('document.elements', []), ('metadata.title', 'overwritten')])
def test_invalid_patch_does_not_write(client, opened, project_copy, path, value):
    before = hashes(project_copy)
    response = client.post('/api/settings/save', json=settings(opened, path, value))
    assert response.status_code == 422, response.text
    assert hashes(project_copy) == before


def test_external_conflict(client, opened, project_copy):
    styles = project_copy / opened['config_paths']['styles']
    styles.write_bytes(styles.read_bytes() + b'\n')
    before = hashes(project_copy)
    response = client.post('/api/settings/save', json=settings(opened, 'styles.font.size', 13))
    assert response.status_code == 409
    assert hashes(project_copy) == before


def test_roundtrip_yaml_comments_order_bom_crlf():
    original = '\ufeff# user comment\r\nschema_version: "0.2"\r\nfont:\r\n  family: "Times New Roman" # chosen font\r\n  size: 14\r\nx-private:\r\n  literal: "yes"\r\n  list: [1, 2, 3]\r\n'.encode('utf-8')
    result = storage.serialize(original, None, [{'path': 'styles.font.size', 'value': 13}], 'styles')
    assert result.startswith(b'\xef\xbb\xbf')
    assert b'# user comment\r\n' in result and b'# chosen font\r\n' in result
    assert b'family: "Times New Roman"' in result and b'literal: "yes"' in result
    assert result.index(b'font:') < result.index(b'x-private:')
    assert b'\n' not in result.replace(b'\r\n', b'')
    assert b'size: 13' in result


def test_multi_file_transaction_rollback(client, opened, project_copy, monkeypatch):
    before = hashes(project_copy)
    real = storage.atomic_write
    calls = 0
    def failing(path, data):
        nonlocal calls
        if Path(path).parent == project_copy:
            calls += 1
            if calls == 2:
                raise OSError('simulated failed second write')
        return real(path, data)
    monkeypatch.setattr(storage, 'atomic_write', failing)
    payload = settings(opened, 'styles.font.size', 13)
    payload['patches'].append({'path': 'document.defaults.numbering.enabled', 'value': False})
    response = client.post('/api/settings/save', json=payload)
    assert response.status_code == 409, response.text
    assert hashes(project_copy) == before
    journals = list(client.app.state.repository.cache.glob('transactions/*.json'))
    assert json.loads(journals[0].read_text())['status'] == 'rolled_back'


def test_origin_path_and_markdown_safety(client, opened, project_copy):
    assert client.post('/api/project/open', json={'path': str(project_copy)}, headers={'Origin': 'https://evil.test'}).status_code == 403
    assert client.get('/api/health', headers={'Host': 'evil.test'}).status_code == 403
    assert client.get('/api/markdown', params={'project': opened['id'], 'path': '../secret.md'}).status_code == 403
    test = project_copy / 'preview-safety.md'
    test.write_text('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n![remote](https://evil.test/a.png)\n', encoding='utf-8')
    html = client.get('/api/markdown', params={'project': opened['id'], 'path': test.name}).json()['html']
    assert '<script' not in html and 'href="javascript:' not in html
    assert '<img' not in html


def test_output_guard_and_no_automatic_open(client, opened, project_copy, monkeypatch):
    called = []
    monkeypatch.setattr('md2doc_web.app.open_in_default_application', lambda path: called.append(path))
    for path in [project_copy / 'README.md', project_copy / 'document.docx']:
        response = client.post('/api/build', json={'project': opened['id'], 'revision': opened['revision'], 'output': str(path)})
        assert response.status_code == 422
    assert not called


def test_doc1_copy_build(client, tmp_path):
    import shutil
    source = os.environ.get('MD2DOC_DOC1_PROJECT')
    if not source or not Path(source).is_dir():
        pytest.skip('Local doc1 project is not available')
    root = tmp_path / 'doc1-copy'
    shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git','.venv','node_modules','__pycache__','.pytest_cache'))
    response = client.post('/api/project/open', json={'path': str(root)})
    assert response.status_code == 200, response.text
    data = response.json()
    before = hashes(root)
    target = tmp_path / 'doc1.docx'
    response = client.post('/api/build', json={'project': data['id'], 'revision': data['revision'], 'output': str(target)})
    assert response.status_code == 202, response.text
    state = wait_job(client)
    assert state['status'] in ('success','warning'), state
    assert target.is_file() and hashes(root) == before


def test_schema_01_custom_config_paths(client, tmp_path):
    import shutil
    root = tmp_path / 'legacy'
    (root / 'config').mkdir(parents=True)
    (root / 'content').mkdir()
    (root / 'output').mkdir()
    for kind in ('styles', 'metadata'):
        shutil.copyfile(ROOT / 'tests/fixtures' / (kind + '.yaml'), root / 'config' / (kind + '.yaml'))
    manifest = {'schema_version':'0.1','id':'legacy','language':'ru-RU','metadata':'config/metadata.yaml','styles':'config/styles.yaml','build':{'output_dir':'output','output_name':'legacy.docx'},'defaults':{'numbering':{'enabled':True,'format':'decimal','scope':'siblings'},'style':{'body':'body'}},'elements':[{'id':'intro','type':'chapter','source':'content/intro.md','heading':{'from':'markdown','level':1}}]}
    (root / 'document.yaml').write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'content/intro.md').write_text('# Legacy\n\nRead-only body', encoding='utf-8')
    opened = client.post('/api/project/open', json={'path':str(root)}).json()
    assert opened['schema'] == '0.1' and opened['outline'], opened['diagnostics']
    before = hashes(root)
    rejected = client.post('/api/settings/save', json=settings(opened,'styles.heading_numbering.enabled',False))
    assert rejected.status_code == 422 and hashes(root) == before
    saved = client.post('/api/settings/save',json=settings(opened,'styles.font.size',12))
    assert saved.status_code == 200, saved.text
    assert load_config(root/'config/styles.yaml')['font']['size'] == 12
    assert load_config(root/'document.yaml') == manifest
    target = tmp_path/'legacy.docx'
    client.post('/api/build',json={'project':opened['id'],'revision':saved.json()['project']['revision'],'output':str(target)})
    assert wait_job(client)['status'] in ('success','warning')
    assert (root/'content/intro.md').read_text() == '# Legacy\n\nRead-only body'


def test_cancel_and_delivery_failure_preserve_result(client, opened, project_copy, monkeypatch):
    runner = client.app.state.runner
    result = project_copy.parent/'preserved.docx'
    result.write_bytes(b'previous result')
    original = runner._command
    def cancelled(argv):
        runner.cancel_event.set()
        return original(argv)
    monkeypatch.setattr(runner,'_command',cancelled)
    payload = {'project':opened['id'],'revision':opened['revision'],'output':str(result)}
    client.post('/api/build',json=payload)
    assert wait_job(client)['status'] == 'cancelled'
    assert result.read_bytes() == b'previous result'

    def failed_delivery(argv):
        if '--output' in argv and '--json' in argv:
            report = Path(argv[argv.index('--json')+1])
            report.write_text(json.dumps({'status':'failed','errors':[{'code':'TEST_DELIVERY','message':'simulated delivery rejection'}]}),encoding='utf-8')
            return 1,'',''
        return original(argv)
    monkeypatch.setattr(runner,'_command',failed_delivery)
    client.post('/api/build',json=payload)
    state = wait_job(client)
    assert state['status'] == 'failed' and any(d['code']=='TEST_DELIVERY' for d in state['diagnostics'])
    assert result.read_bytes() == b'previous result'


def test_change_during_build_never_publishes(client, opened, project_copy, monkeypatch):
    runner = client.app.state.runner
    original = runner._command
    result = project_copy.parent / 'stable.docx'
    result.write_bytes(b'keep old output')
    def changed_after_verification(argv):
        value = original(argv)
        if '--output' in argv and '--json' in argv:
            (project_copy / 'new-content.md').write_text('# Added while building', encoding='utf-8')
        return value
    monkeypatch.setattr(runner, '_command', changed_after_verification)
    client.post('/api/build', json={'project':opened['id'],'revision':opened['revision'],'output':str(result)})
    state = wait_job(client)
    assert state['status'] == 'failed' and 'изменился' in state['message']
    assert result.read_bytes() == b'keep old output'


def test_session_and_explicit_result_actions(client, opened, project_copy, monkeypatch):
    state = client.get('/api/session').json()
    assert state['project']['id'] == opened['id'] and state['job'] is None
    target = project_copy.parent / 'verified.docx'
    target.write_bytes(b'checked artifact')
    runner = client.app.state.runner
    runner.current = {'project_id':opened['id'],'status':'success','artifact':{'path':str(target),'sha256':digest(target.read_bytes())},'_started':time.monotonic()}
    called=[]
    monkeypatch.setattr('md2doc_web.app.open_in_default_application',lambda value: (called.append(str(value)) or {'opened':True,'path':str(value)}))
    assert client.get('/api/result/download').content == b'checked artifact'
    assert not called
    assert client.post('/api/result/open',json={}).status_code == 200
    assert called == [str(target)]
