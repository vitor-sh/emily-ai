"""Ensaia uma release privada e só então substitui os processos da nuvem."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
import requests
from dotenv import dotenv_values

ROOT = Path('/home/ubuntu/emily-runtime-cloud')
CONFIG = Path('/home/ubuntu/.config/emily-runtime-cloud')

def activate(release):
    if not re.fullmatch('[0-9a-f]{20}', release): raise ValueError('Release inválida')
    folder = ROOT/'releases'/release
    folder.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ROOT/f'incoming-{release}.tar.gz') as tar:
        tar.extractall(folder, filter='data')
    log = ROOT/'data'/'last-deploy.log'
    env = dict(os.environ)
    env.update({k: v for k, v in dotenv_values(folder/'providers.env').items() if v is not None})
    env['EMILY_CONFIG_FILE'] = str(folder/'providers.env')
    with log.open('w') as output:
        requirements = folder/'emily-runtime-cloud/requirements.txt'
        dependency_hash = hashlib.sha256(requirements.read_bytes()).hexdigest()
        original = ROOT/'requirements.txt'
        if original.exists() and hashlib.sha256(original.read_bytes()).hexdigest() == dependency_hash:
            venv = ROOT/'.venv'
        else:
            venv = ROOT/'venvs'/dependency_hash
            if not (venv/'ready').exists():
                subprocess.run(['/usr/bin/python3', '-m', 'venv', str(venv)], check=True, stdout=output, stderr=subprocess.STDOUT)
                subprocess.run([str(venv/'bin/pip'), 'install', '-r', str(requirements)],
                    check=True, stdout=output, stderr=subprocess.STDOUT, timeout=360)
                (venv/'ready').touch()
        (folder/'.runtime-venv').write_text(str(venv))
        for source in folder.rglob('*.py'): ast.parse(source.read_bytes(), filename=str(source))
        # Dependências ausentes ou incompatíveis impedem trocar uma versão funcionando.
        result = subprocess.run([str(venv/'bin/python'), str(folder/'cloud_runtime_server.py'), '--preflight'],
            cwd=folder, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=100)
        if result.returncode: raise RuntimeError('Preflight falhou')
    log.chmod(0o600)
    previous = (ROOT/'current').resolve() if (ROOT/'current').exists() else None
    old_private = {name: (CONFIG/name).read_bytes() if (CONFIG/name).exists() else None
                   for name in ('providers.env', 'discord.json', 'preferences.json')}
    previous_relay = Path('/home/ubuntu/emily-relay/relay.py').read_bytes()
    def switch(target):
        link = ROOT/'.current-next'; link.unlink(missing_ok=True); link.symlink_to(target)
        os.replace(link, ROOT/'current')
    try:
        for name in ('providers.env', 'discord.json'):
            tmp = CONFIG/(name+'.tmp'); tmp.write_bytes((folder/name).read_bytes()); tmp.chmod(0o600)
            os.replace(tmp, CONFIG/name)
        prefs = json.loads((CONFIG/'preferences.json').read_text()) if (CONFIG/'preferences.json').exists() else {}
        prefs.update(json.loads((folder/'preferences-input.json').read_text()))
        tmp = CONFIG/'preferences.json.tmp'; tmp.write_text(json.dumps(prefs, ensure_ascii=False)); tmp.chmod(0o600)
        os.replace(tmp, CONFIG/'preferences.json')
        switch(folder)
        shutil.copyfile(folder/'emily-relay/relay.py', '/home/ubuntu/emily-relay/relay.py')
        subprocess.run(['sudo', 'systemctl', 'restart', 'emily-cloud.service', 'emily-relay.service'], check=True)
        key = json.loads(Path('/home/ubuntu/.config/emily-relay/config.json').read_text())['upload_key']
        for _ in range(45):
            try:
                result = requests.get('http://127.0.0.1:15100/health', headers={'Authorization':'Bearer '+key}, timeout=3)
                if result.ok and result.json().get('discord_online') and result.json().get('release') == release: break
            except requests.RequestException: pass
            time.sleep(2)
        else: raise RuntimeError('Discord não conectou após atualizar')
        (ROOT/f'incoming-{release}.tar.gz').unlink(missing_ok=True)
        print('Release aplicada e bot conectado.')
    except Exception:
        if previous:
            switch(previous)
            for name, data in old_private.items():
                if data is not None: (CONFIG/name).write_bytes(data)
            Path('/home/ubuntu/emily-relay/relay.py').write_bytes(previous_relay)
            subprocess.run(['sudo', 'systemctl', 'restart', 'emily-cloud.service', 'emily-relay.service'], check=False)
        raise

if __name__ == '__main__': activate(sys.argv[1])
