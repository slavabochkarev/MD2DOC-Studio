"""Run the local Studio. The converter and projects remain separate."""
import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'studio/backend')]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def is_running_studio(url, frontend):
    """Identify our service before reusing a port; never stop another process."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url + '/api/health', timeout=1) as response:
            health = json.loads(response.read(65537))
        if not isinstance(health, dict) or health.get('status') != 'ok' or health.get('local') is not True:
            return False
        if health.get('application') == 'md2doc-studio':
            return True
        # Compatibility with the first Studio server, already left running.
        # Its generic health fields alone are insufficient identification.
        if set(health) != {'status', 'local', 'converter_version'}:
            return False
        expected = frontend.read_bytes()
        with opener.open(url + '/', timeout=1) as response:
            return response.read(len(expected) + 1) == expected
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description='MD2DOC Studio — localhost')
    parser.add_argument('--port', type=int, default=8731)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    frontend = ROOT / 'studio/frontend/build/index.html'
    if not frontend.is_file():
        raise SystemExit('Frontend not built. Run studio/Setup-Studio.ps1 -RebuildFrontend first.')
    if not 1024 <= args.port <= 65535:
        raise SystemExit('Choose a port between 1024 and 65535.')
    url = f'http://127.0.0.1:{args.port}'
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', args.port))
        except OSError:
            if is_running_studio(url, frontend):
                print(f'MD2DOC Studio is already running: {url}', flush=True)
                if not args.no_browser:
                    webbrowser.open(url)
                return 0
            print(f'Port {args.port} is occupied by another application or an unavailable server.\n'
                  f'Choose another port: .\\studio\\Start-Studio.ps1 -Port {args.port + 1 if args.port < 65535 else 8731}', file=sys.stderr)
            return 2
    print(f'MD2DOC Studio: {url}\nStop: Ctrl+C. Microsoft Word is not started automatically.', flush=True)
    if not args.no_browser:
        def open_when_ready():
            for _ in range(100):
                try:
                    with urlopen(url + '/api/health', timeout=.5) as response:
                        if response.status == 200:
                            webbrowser.open(url)
                            return
                except OSError:
                    time.sleep(.1)
        threading.Thread(target=open_when_ready, daemon=True).start()
    import uvicorn
    from md2doc_web.app import create_app
    uvicorn.run(create_app(ROOT), host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    raise SystemExit(main())
