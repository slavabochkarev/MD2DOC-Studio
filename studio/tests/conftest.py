from pathlib import Path
import os
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'studio/backend')]

from md2doc_web.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def project_copy(tmp_path):
    source = Path(os.environ.get('MD2DOC_STUDIO_TEST_PROJECT', ROOT / 'examples/minimal'))
    if not source.is_dir():
        pytest.skip('Configured test project is not available')
    target = tmp_path / 'project'
    shutil.copytree(source, target)
    return target


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(ROOT, tmp_path / 'cache')) as client:
        yield client


@pytest.fixture
def opened(client, project_copy):
    response = client.post('/api/project/open', json={'path': str(project_copy)})
    assert response.status_code == 200, response.text
    return response.json()


def settings(opened, path, value):
    return {'project': opened['id'], 'revision': opened['revision'], 'patches': [{'path': path, 'value': value}]}
