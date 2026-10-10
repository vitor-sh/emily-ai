#!/usr/bin/env python3
"""Snapshot consistente: pausa OmniRoute, copia dados+segredos, retoma se estava ativo."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent


def compose(*args):
    return subprocess.check_output(['docker', 'compose', *args], cwd=ROOT, text=True).strip()


def backup():
    if not (ROOT / '.env').is_file():
        raise RuntimeError('Falta .env; execute preparar.py no servidor.')
    container = compose('ps', '-a', '-q', 'omniroute')
    if not container or '\n' in container:
        raise RuntimeError('Container OmniRoute não encontrado ou ambíguo.')
    running = json.loads(subprocess.check_output(
        ['docker', 'inspect', '--format', '{{json .State.Running}}', container], text=True))
    folder = ROOT / 'backups'
    folder.mkdir(mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    name = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    target = folder / f'omniroute-{name}.tar.gz'
    try:
        if running:
            compose('stop', 'omniroute')
        with tempfile.TemporaryDirectory(prefix='omniroute-backup-') as tmp:
            data = Path(tmp) / 'data'
            subprocess.run(['docker', 'cp', f'{container}:/app/data', str(data)], check=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as out, tarfile.open(fileobj=out, mode='w:gz') as archive:
                archive.add(data, arcname='data')
                archive.add(ROOT / '.env', arcname='.env')
                archive.add(ROOT / 'compose.yaml', arcname='compose.yaml')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if running:
            compose('start', 'omniroute')
    print(f'Backup privado criado: {target.name}')


if __name__ == '__main__':
    backup()
