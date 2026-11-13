import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
import threading

import pytest

from conftest import ROOT

spec = importlib.util.spec_from_file_location('studio_launcher', ROOT / 'studio/start.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.mark.parametrize('health,same_frontend,recognized', [
    ({'application':'md2doc-studio','status':'ok','local':True}, False, True),
    ({'status':'ok','local':True,'converter_version':'0.2.3'}, True, True),
    ({'status':'ok','local':True,'converter_version':'0.2.3'}, False, False),
    ({'status':'ok'}, False, False),
    ([], False, False),
])
@pytest.mark.parametrize('no_browser', [False, True])
def test_occupied_port_identification_and_browser(health, same_frontend, recognized, no_browser, monkeypatch):
    index = (ROOT / 'studio/frontend/build/index.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = json.dumps(health).encode() if self.path == '/api/health' else index if same_frontend else b'Another application'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opened = []
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: opened.append(url))
    args = ['start.py', '--port', str(server.server_port)] + (['--no-browser'] if no_browser else [])
    monkeypatch.setattr(sys, 'argv', args)
    try:
        assert launcher.main() == (0 if recognized else 2)
        assert opened == ([f'http://127.0.0.1:{server.server_port}'] if recognized and not no_browser else [])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
