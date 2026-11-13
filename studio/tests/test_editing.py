from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import time
from zipfile import ZipFile

from lxml import etree
import pytest
import yaml

from md2doc.config.validation import load_config
from md2doc_web.repository import digest, StudioError
from test_studio import hashes, wait_job
from conftest import ROOT


def raw(client, project, kind):
    response=client.get('/api/text/config',params={'project':project['id'],'kind':kind})
    assert response.status_code==200,response.text
    return response.json()


def payload(project, file, text):
    return {'project':project['id'],'kind':file['kind'],'revision':project['revision'],'file_revision':file['file_revision'],'text':text}


def md(client, project, path):
    response=client.get('/api/markdown',params={'project':project['id'],'path':path})
    assert response.status_code==200,response.text
    return response.json()


def md_payload(project, file, text):
    return {'project':project['id'],'revision':project['revision'],'path':file['path'],'file_revision':file['file_revision'],'text':text}


def test_markdown_preview_save_backup_and_conflict(client,opened,project_copy):
    path=next(f['path'] for f in opened['files'] if f['kind']=='.md')
    target=project_copy/path
    target.write_bytes(b'\xef\xbb\xbf'+target.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\n','\r\n').encode())
    before=hashes(project_copy)
    file=md(client,opened,path)
    draft=file['text']+'\n\nТекст приёмки **Markdown**.\n'
    response=client.post('/api/text/markdown/preview',json=md_payload(opened,file,draft))
    assert response.status_code==200,response.text
    assert '<strong>Markdown</strong>' in response.json()['html']
    assert hashes(project_copy)==before
    response=client.post('/api/text/markdown/save',json=md_payload(opened,file,draft))
    assert response.status_code==200,response.text
    result=response.json()
    assert (Path(result['backup'])/'markdown.original').read_bytes().startswith(b'\xef\xbb\xbf')
    data=target.read_bytes()
    assert data.startswith(b'\xef\xbb\xbf') and b'\n' not in data.replace(b'\r\n',b'')
    assert all(hashes(project_copy)[p]==h for p,h in before.items() if p!=path)
    target.write_bytes(data+b'\r\nExternal change\r\n')
    expected=target.read_bytes()
    conflict=client.post('/api/text/markdown/save',json={**md_payload(result['project'],file,draft+'another'), 'file_revision':result['file_revision']})
    assert conflict.status_code==409 and target.read_bytes()==expected


@pytest.mark.parametrize('path',['../outside.md','styles.yaml','.git/secret.md','document.yaml'])
def test_markdown_edit_scope(client,opened,project_copy,path):
    before=hashes(project_copy)
    response=client.post('/api/text/markdown/save',json={'project':opened['id'],'revision':opened['revision'],'path':path,'text':'overwrite','file_revision':'bad'})
    assert response.status_code==403,response.text
    assert hashes(project_copy)==before


def test_yaml_verbatim_comments_visual_roundtrip(client,opened,project_copy):
    original=raw(client,opened,'styles')
    styles=deepcopy(opened['configs']['styles'])
    styles['font']['size']=13
    styles['x-client-extension']={'unknown':[17,'yes',True]}
    text='# Комментарий клиента\n'+yaml.safe_dump(styles,allow_unicode=True,sort_keys=False)+'# Последняя строка\n'
    before=hashes(project_copy)
    data=payload(opened,original,text)
    validate=client.post('/api/text/yaml/validate',json=data)
    assert validate.status_code==200,validate.text
    assert hashes(project_copy)==before
    saved=client.post('/api/text/yaml/save',json=data)
    assert saved.status_code==200,saved.text
    project=saved.json()['project']
    path=project_copy/project['config_paths']['styles']
    assert path.read_text(encoding='utf-8-sig')==text
    assert project['configs']['styles']['font']['size']==13
    # Visual forms use the raw editor's new baseline, and retain comments/extensions.
    response=client.post('/api/settings/save',json={'project':project['id'],'revision':project['revision'],'patches':[{'path':'styles.font.size','value':12}]})
    assert response.status_code==200,response.text
    assert '# Комментарий клиента' in path.read_text(encoding='utf-8-sig') and '# Последняя строка' in path.read_text(encoding='utf-8-sig')
    assert load_config(path)['x-client-extension']==styles['x-client-extension']
    assert load_config(path)['font']['size']==12
    assert all(hashes(project_copy)[p]==h for p,h in before.items() if p!=original['path'])


@pytest.mark.parametrize('replacement',['font: [not closed', 'font:\n  size: -5\n', 'unknown_field: true\n', 'x-a: &anchor value\nx-b: *anchor\n'])
def test_invalid_yaml_never_writes(client,opened,project_copy,replacement):
    file=raw(client,opened,'styles')
    before=hashes(project_copy)
    response=client.post('/api/text/yaml/save',json=payload(opened,file,replacement))
    assert response.status_code==422,response.text
    assert hashes(project_copy)==before


def test_manifest_updates_actual_references_and_rejects_escape(client,opened,project_copy):
    folder=project_copy/'custom config'
    folder.mkdir()
    shutil.copyfile(project_copy/opened['config_paths']['styles'],folder/'Оформление.yml')
    shutil.copyfile(project_copy/opened['config_paths']['metadata'],folder/'Данные.yml')
    document=deepcopy(opened['configs']['document'])
    document.update(styles='custom config/Оформление.yml',metadata='custom config/Данные.yml')
    file=raw(client,opened,'document')
    saved=client.post('/api/text/yaml/save',json=payload(opened,file,'# Ссылки клиента\n'+yaml.safe_dump(document,allow_unicode=True,sort_keys=False)))
    assert saved.status_code==200,saved.text
    project=saved.json()['project']
    assert raw(client,project,'styles')['path']=='custom config/Оформление.yml'
    metadata=raw(client,project,'metadata')
    text=metadata['text'].replace(project['configs']['metadata']['title'],'Заголовок после редактирования')
    result=client.post('/api/text/yaml/save',json=payload(project,metadata,text))
    assert result.status_code==200,result.text
    project=result.json()['project']
    assert project['configs']['metadata']['title']=='Заголовок после редактирования'
    before=hashes(project_copy)
    file=raw(client,project,'document')
    document['styles']='../outside.yml'
    rejected=client.post('/api/text/yaml/save',json=payload(project,file,json.dumps(document)))
    assert rejected.status_code in (403,422) and hashes(project_copy)==before


def test_yaml_external_conflict(client,opened,project_copy):
    file=raw(client,opened,'metadata')
    target=project_copy/file['path']
    target.write_bytes(target.read_bytes()+b'\n# External edit\n')
    expected=target.read_bytes()
    response=client.post('/api/text/yaml/save',json=payload(opened,file,file['text']+'\n# Browser edit\n'))
    assert response.status_code==409 and target.read_bytes()==expected


def test_raw_yaml_preserves_bom_crlf(client,opened,project_copy):
    path=project_copy/opened['config_paths']['styles']
    path.write_bytes(b'\xef\xbb\xbf'+path.read_text(encoding='utf-8-sig').replace('\r\n','\n').replace('\n','\r\n').encode())
    project=client.post('/api/project/open',json={'path':str(project_copy)}).json()
    file=raw(client,project,'styles')
    response=client.post('/api/text/yaml/save',json=payload(project,file,file['text']+'\n# Keep BOM and CRLF\n'))
    assert response.status_code==200,response.text
    data=path.read_bytes()
    assert data.startswith(b'\xef\xbb\xbf') and b'\n' not in data.replace(b'\r\n',b'')
    assert b'# Keep BOM and CRLF\r\n' in data


def test_flow_yaml_trailing_comments_survive_visual_save(client,opened,project_copy):
    file=raw(client,opened,'styles')
    response=client.post('/api/text/yaml/save',json=payload(opened,file,file['text']+'\n# Client trailing comment\n# Another comment\n'))
    assert response.status_code==200,response.text
    project=response.json()['project']
    response=client.post('/api/settings/save',json={'project':project['id'],'revision':project['revision'],'patches':[{'path':'styles.headers_footers.header_text','value':'Updated header'}]})
    assert response.status_code==200,response.text
    text=(project_copy/file['path']).read_text(encoding='utf-8-sig')
    assert text.endswith('# Client trailing comment\n# Another comment\n')
    assert load_config(project_copy/file['path'])['headers_footers']['header_text']=='Updated header'


def test_markdown_write_rollback(client,opened,project_copy,monkeypatch):
    from md2doc_web import repository
    path=next(f['path'] for f in opened['files'] if f['kind']=='.md')
    file=md(client,opened,path)
    original=(project_copy/path).read_bytes()
    real=repository.atomic_write
    interrupted=False
    def fail_after_write(target,data):
        nonlocal interrupted
        real(target,data)
        if target==project_copy/path and not interrupted:
            interrupted=True
            raise OSError('simulated interruption after Markdown replace')
    monkeypatch.setattr(repository,'atomic_write',fail_after_write)
    response=client.post('/api/text/markdown/save',json=md_payload(opened,file,file['text']+'\nchanged'))
    assert response.status_code==409,response.text
    assert (project_copy/path).read_bytes()==original


@pytest.mark.parametrize('source',[ROOT/'examples/minimal',os.environ.get('MD2DOC_DOC1_PROJECT')])
def test_edit_build_h1_h6_and_headers(client,tmp_path,source):
    if not source or not Path(source).is_dir():pytest.skip('Optional external test project unavailable')
    root=tmp_path/'real-project'
    shutil.copytree(source,root,ignore=shutil.ignore_patterns('.git','.venv','node_modules','__pycache__','.pytest_cache'))
    response=client.post('/api/project/open',json={'path':str(root)})
    assert response.status_code==200,response.text
    project=response.json()
    native = project['schema']=='0.2'
    chapter=next(n for n in project['nodes'] if n['type']=='chapter' and n['active'])
    file=md(client,project,chapter['source'])
    text=file['text']+'\n\n'+'\n\n'.join('#'*level+' Уровень '+str(level)+' приёмка' for level in range(2,7))+'\n'
    response=client.post('/api/text/markdown/save',json=md_payload(project,file,text))
    assert response.status_code==200,response.text
    project=response.json()['project']
    styles=deepcopy(project['configs']['styles'])
    if native:
        styles['heading_numbering']={'enabled':True,'separator':'.','levels':{f'h{i}':{'enabled':True,'display':True,'format':'decimal','template':'{path}'} for i in range(1,7)}}
    styles['headers_footers'].update(header_text='Верхний колонтитул приёмки',footer_text='Нижний колонтитул',different_first_page=True,first_page={'header_text':'Первая страница приёмки','footer_text':'Первый нижний','show_page_number':True})
    styles['headers_footers']['page_number'].update(visible=True,position='header_right')
    styles['page']['header_distance']='12mm'
    file=raw(client,project,'styles')
    response=client.post('/api/text/yaml/save',json=payload(project,file,'# После редактирования\n'+yaml.safe_dump(styles,allow_unicode=True,sort_keys=False)))
    assert response.status_code==200,response.text
    project=response.json()['project']
    h6=next(n for n in project['outline'] if n['text']=='Уровень 6 приёмка')
    assert h6['level']==6
    if native: assert h6['number']
    before=hashes(root)
    output=tmp_path/'edited.docx'
    response=client.post('/api/build',json={'project':project['id'],'revision':project['revision'],'output':str(output)})
    assert response.status_code==202,response.text
    state=wait_job(client)
    assert state['status'] in ('success','warning'),state
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    with ZipFile(output) as archive:
        headers=[etree.fromstring(archive.read(name)) for name in archive.namelist() if name.startswith('word/header') and name.endswith('.xml')]
        alltext=' '.join(''.join(h.itertext()) for h in headers)
        assert 'Верхний колонтитул приёмки' in alltext and 'Первая страница приёмки' in alltext
        assert any(h.xpath('//w:instrText[contains(text(),"PAGE")]',namespaces=ns) for h in headers)
        numbering=etree.fromstring(archive.read('word/numbering.xml'))
        if native: assert numbering.xpath('//w:lvl[@w:ilvl="5"]',namespaces=ns)
        document=etree.fromstring(archive.read('word/document.xml'))
        if native: assert document.xpath('//w:p[w:r/w:t="Уровень 6 приёмка"]/w:pPr/w:numPr/w:ilvl[@w:val="5"]',namespaces=ns)
        assert document.xpath('//w:pgMar/@w:header',namespaces=ns)==['680']
    assert hashes(root)==before


def test_shell_error_is_visible_and_keeps_download(client,opened,project_copy,monkeypatch):
    output=project_copy.parent/'result.docx';output.write_bytes(b'artifact')
    client.app.state.runner.current={'project_id':opened['id'],'status':'success','_started':time.monotonic(),'artifact':{'path':str(output),'sha256':digest(output.read_bytes())}}
    def fail(path):raise StudioError('Windows 1155: нет ассоциации DOCX',502,[{'code':'WINDOWS_SHELL','severity':'error','message':'Windows 1155'}])
    monkeypatch.setattr('md2doc_web.app.open_in_default_application',fail)
    response=client.post('/api/result/open',json={})
    assert response.status_code==502 and response.json()['diagnostics'][0]['code']=='WINDOWS_SHELL'
    assert client.get('/api/result/download').content==b'artifact'
    selected=[]
    monkeypatch.setattr('md2doc_web.app.reveal_in_explorer',lambda p:(selected.append(str(p)) or {'opened':True,'selected':True}))
    assert client.post('/api/result/reveal',json={}).json()['selected'] is True
    assert selected==[str(output)]
