"""Retenção local de artefatos publicados e instaladores temporários inativos."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

ROOT = Path(__file__).resolve().parent


def retention(folder, pattern, current, keep=2):
    candidates = []
    if not folder.is_dir(): return []
    for path in folder.iterdir():
        match = re.fullmatch(pattern, path.name)
        if match and not path.is_symlink():
            number = int(match[1])
            if number <= current: candidates.append((number, path))
    candidates.sort(reverse=True)
    preserved = {p for _, p in candidates[:keep]}
    return [p for number, p in candidates if p not in preserved and number != current]


def verified(path, metadata):
    if path.is_symlink() or not path.is_file(): raise ValueError(f'Artefato atual ausente: {path}')
    if path.stat().st_size != metadata['size']: raise ValueError(f'Tamanho inválido: {path}')
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest != metadata['sha256']: raise ValueError(f'Hash inválido: {path}')


def build_candidates(home=Path.home(), root=ROOT):
    result = []
    android = home/'.local/share/emily/android-updates'
    code = home/'.local/share/emily/windows-code-updates'
    for folder, field, template, pattern in [
        (android, 'version_code', 'emily-{}.apk', r'emily-(\d+)\.apk'),
        (code, 'version', 'Emily-Code-{}.zip', r'Emily-Code-(\d+)\.zip')]:
        if not (folder/'latest.json').is_file(): continue
        metadata = json.loads((folder/'latest.json').read_text())
        current = int(metadata[field]); verified(folder/template.format(current), metadata)
        result.extend(retention(folder, pattern, current))
    music = root/'EmilyMusic'
    if (music/'version.properties').is_file():
        current = int((music/'version.properties').read_text())
        release = music/'output/releases'/f'0.1.{current}'
        metadata = json.loads((release/'update.json').read_text())
        if metadata['version_code'] != current: raise ValueError('Versão Music não confere')
        verified(release/f'EmilyMusic-0.1.{current}.apk', metadata)
        result.extend(retention(release.parent, r'0\.1\.(\d+)', current))
    return result


def active_paths():
    paths = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            if process.stat().st_uid != os.getuid(): continue
            for file in ['maps', 'cmdline', 'environ']:
                try: paths.append((process/file).read_bytes().decode(errors='replace'))
                except FileNotFoundError: pass
            for link in [process/'cwd', process/'exe', *list((process/'fd').iterdir())]:
                try: paths.append(os.readlink(link))
                except FileNotFoundError: pass
        except FileNotFoundError: pass  # processo terminou
        # Sem acesso a um processo do usuário, não arrisque limpar seu runtime.
        except PermissionError: raise RuntimeError('Processo inacessível; limpeza de runtimes adiada.')
    return '\n'.join(paths)


def runtime_candidates(home=Path.home(), now=None, usage=None):
    folder = home/'.cache/codex-runtimes'
    if not folder.is_dir(): return []
    now = time.time() if now is None else now
    unknown = False
    if usage is None:
        try: usage = active_paths()
        except RuntimeError: usage = ''; unknown = True
    def safe(path):
        if not unknown: return True
        # Downloads abandonados, sem payload extraído, não são um runtime.
        items=list(path.iterdir());payload=path/'payload'
        return (all(p.name in {'payload','node-runtime.tar.xz'} and not p.is_symlink() for p in items)
                and payload.is_dir() and not any(payload.iterdir())
                and all(now-p.stat().st_mtime > 7*86400 for p in items))
    return [p for p in folder.iterdir() if re.fullmatch(r'codex-runtime-install-[A-Za-z0-9]+', p.name)
            and p.is_dir() and not p.is_symlink() and now-p.stat().st_mtime > 7*86400
            and str(p) not in usage and safe(p)]


def clean(apply=False, runtimes=False):
    candidates = build_candidates()
    if runtimes:
        try: candidates += runtime_candidates()
        except RuntimeError as exc: print(exc)
    log = []
    for path in candidates:
        print(('Removendo: ' if apply else 'Descartável: ') + str(path))
        if apply:
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()
        log.append(str(path))
    return log


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--runtimes', action='store_true')
    args = parser.parse_args()
    clean(args.apply, args.runtimes)
