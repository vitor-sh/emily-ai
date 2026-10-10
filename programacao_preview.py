"""Prévia visual da cópia web, sem ponte para a Emily instalada."""
import argparse
import functools
import http.server
import json
import os
import sys
from pathlib import Path
import shutil
from urllib.parse import unquote, urlsplit


def capture(url, output, width=1200, height=850, screen=''):
    bundled=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))/'playwright-browsers'
    if bundled.is_dir(): os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(bundled)
    from playwright.sync_api import sync_playwright
    candidates = sorted((Path.home()/'.cache/ms-playwright').glob('chromium-*/chrome-linux64/chrome'))
    executable = shutil.which('chromium') or shutil.which('google-chrome') or (str(candidates[-1]) if candidates else None)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, **({'executable_path':executable} if executable else {}))
        try:
            page = browser.new_page(viewport={'width':width, 'height':height}, service_workers='block')
            origin=urlsplit(url)
            page.context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url)[:2]==origin[:2] else route.abort())
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url, wait_until='networkidle', timeout=20000)
            page.wait_for_function('window.pywebview && window.pywebview.api', timeout=10000)
            if screen:
                page.evaluate('(screen) => { if (typeof irPara !== "function") throw new Error("Navegação indisponível"); irPara(screen); }', screen)
            page.wait_for_timeout(500)
            page.screenshot(path=str(output), full_page=True)
            return {'arquivo':str(output), 'erros_javascript':errors, 'largura':width, 'altura':height}
        finally:
            browser.close()


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        relative = unquote(urlsplit(self.path).path).lstrip('/') or 'index.html'
        rel = Path(relative)
        root = Path(self.directory)
        if rel.is_absolute() or any(part.startswith('.') for part in rel.parts):
            return self.send_error(403)
        path = root / rel  # apenas recursos públicos
        if not path.is_file():
            path = root / 'web' / rel
        allowed = {'web','img','assets','static'}
        if (not path.is_file() or not path.resolve().is_relative_to(root.resolve()) or
            path.relative_to(root).parts[0] not in allowed or path.is_symlink() or
            any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(root))):
            return self.send_error(404)
        self.path = '/' + path.relative_to(root).as_posix()
        return super().do_GET()
    do_HEAD = do_GET
    def list_directory(self, path):
        self.send_error(403)
    def log_message(self, *args):
        pass


def serve(workspace):
    if not (workspace/'web/index.html').is_file():
        raise ValueError('Esta sessão não contém web/index.html. Use executar para iniciar o servidor do projeto.')
    server = http.server.ThreadingHTTPServer(('127.0.0.1',0), functools.partial(Handler,directory=str(workspace)))
    print(json.dumps({'url':f'http://127.0.0.1:{server.server_port}/',
        'tipo':'visual_com_dados_de_amostra','ponte_real':False}),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    args=argparse.ArgumentParser();args.add_argument('workspace');options=args.parse_args()
    serve(Path(options.workspace).resolve())
