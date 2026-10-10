"""Escolhe o ambiente validado da release; reversões preservam bibliotecas."""
import os
from pathlib import Path

ROOT = Path('/home/ubuntu/emily-runtime-cloud')

def launch():
    release = (ROOT/'current').resolve()
    selected = release/'.runtime-venv'
    venv = Path(selected.read_text().strip()) if selected.exists() else ROOT/'.venv'
    if venv != ROOT/'.venv' and venv.parent != ROOT/'venvs':
        raise RuntimeError('Ambiente da release inválido')
    python = venv/'bin/python'
    os.chdir(release)
    os.execv(str(python), [str(python), '-u', str(release/'cloud_runtime_server.py')])

if __name__ == '__main__': launch()
