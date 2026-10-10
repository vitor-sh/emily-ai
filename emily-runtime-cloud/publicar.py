"""Publicação atômica do código local, com ensaio, saúde e reversão."""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import time
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
REMOTE = '/home/ubuntu/emily-runtime-cloud'
SSH = ['ssh', '-4', '-o', 'IPQoS=none', '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3', '-i', str(Path.home()/'.ssh/emily-oracle-ed25519'),
       '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'ubuntu@163.176.97.174']
PRIVATE = Path.home()/'.config/emily-cloud-oracle'

def sources(root=ROOT):
    files = [p for p in root.glob('*.py') if not p.name.startswith(('_teste', 'test_'))]
    for package in ('memoria_unificada', 'emily_cloud'):
        files += list((root/package).rglob('*.py'))
    files += [p for p in (root/'assets/audio').glob('*') if p.is_file()]
    files += list((root/'assets/programacao-node').glob('*.json'))
    files += list((root/'emily-relay').glob('*.py'))
    files += [root/'emily-runtime-cloud/requirements.txt', root/'emily-runtime-cloud/activate.py', root/'emily-runtime-cloud/launch.py']
    return sorted(p for p in files if '__pycache__' not in p.parts)

def configuration():
    values = dotenv_values(ROOT/'.env')
    allowed = {'BRAVE_API_KEY', 'GROQ_API_KEY', 'FISH_AUDIO_KEY', 'FISH_VOICE_ID',
               'OPENAI_API_KEY', 'OMNIROUTE_API_KEY', 'CLAUDE_API_KEY'}
    selected = {k: str(v) for k, v in values.items() if v is not None and
                (k in allowed or k.startswith(('EMILY_PROVEDOR_', 'EMILY_MODELO_', 'EMILY_LLM_', 'EMILY_AUDIO_', 'EMILY_MEMORIA_')))}
    for provider in ('OPENAI', 'OMNIROUTE'):
        selected[f'EMILY_PROVEDOR_{provider}_BASE'] = 'http://127.0.0.1:20128/v1'
        reference = selected.get(f'EMILY_PROVEDOR_{provider}_CHAVE')
        if reference and values.get(reference): selected[reference] = str(values[reference])
    selected.update(EMILY_RUNTIME_CLOUD='1', PYNPUT_BACKEND='dummy',
        EMILY_PROVEDOR_LLM=str(values.get('EMILY_PROVEDOR_LLM') or 'openai'),
        EMILY_DATA_DIR=REMOTE+'/data', TZ='America/Sao_Paulo',
        EMILY_ARQUIVO_DM_HISTORICO=REMOTE+'/data/dm-history.json',
        EMILY_ARQUIVO_DISCORD='/home/ubuntu/.config/emily-runtime-cloud/discord.json',
        EMILY_ARQUIVO_PREFERENCIAS='/home/ubuntu/.config/emily-runtime-cloud/preferences.json',
        EMILY_CONFIG_FILE='/home/ubuntu/.config/emily-runtime-cloud/providers.env',
        EMILY_RELAY_CONFIG='/home/ubuntu/.config/emily-relay/config.json',
        EMILY_MEMORIA_UNIFICADA='1', EMILY_MEMORIA_PASTA=REMOTE+'/data/memoria_unificada',
        EMILY_OLLAMA_URL='http://127.0.0.1:11434')
    # dotenv e systemd aceitam estas strings; não executar o arquivo como shell.
    sections = []
    providers = sorted({k.split('_')[2].lower() for k in selected if k.startswith('EMILY_PROVEDOR_') and k != 'EMILY_PROVEDOR_LLM'})
    for provider in providers:
        sections.append('# >>> provedor: '+provider+'\n')
        for key in sorted(k for k in selected if k.startswith('EMILY_PROVEDOR_'+provider.upper()+'_')):
            sections.append(key+'='+json.dumps(selected.pop(key), ensure_ascii=False)+'\n')
        sections.append('# <<< provedor: '+provider+'\n')
    return (''.join(sections)+''.join(k+'='+json.dumps(v, ensure_ascii=False)+'\n' for k, v in sorted(selected.items()))).encode()

def snapshot():
    items = [(str(p.relative_to(ROOT)), p.read_bytes()) for p in sources()]
    items.append(('providers.env', configuration()))
    # Configuração editável deve acompanhar o código, sem transportar estado de DMs.
    items.append(('discord.json', (Path.home()/'.emily_discord.json').read_bytes()))
    prefs = json.loads((Path.home()/'.emily_preferencias.json').read_text())
    items.append(('preferences-input.json', json.dumps({k: v for k, v in prefs.items()
        if k in {'nome', 'modelo', 'provedor', 'raciocinio', 'personalidade_extra', 'modelo_discord',
                 'audio_preprocess_denoise', 'audio_preprocess_normalize', 'audio_preprocess_vad', 'volume_voz'}}).encode()))
    h = hashlib.sha256()
    for name, data in items:
        if name.endswith('.py'):
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                ast.parse(data, filename=name)
        h.update(name.encode()+b'\0'+data+b'\0')
    return h.hexdigest()[:20], items

def publish():
    release, items = snapshot()
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    import fcntl
    with (PRIVATE/'runtime-publish.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = PRIVATE/'runtime-published.txt'
        if state.exists() and state.read_text().strip() == release: return release
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary)/'source.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for name, data in items:
                    info = tarfile.TarInfo(name); info.size = len(data); info.mode = 0o600
                    tar.addfile(info, io.BytesIO(data))
            archive.chmod(0o600)
            with archive.open('rb') as stream:
                subprocess.run(SSH+['umask 077; cat > '+REMOTE+'/incoming-'+release+'.tar.gz'],
                    stdin=stream, check=True, timeout=240)
            script = (ROOT/'emily-runtime-cloud/activate.py').read_bytes()
            command = 'umask 077; cat > '+REMOTE+'/activate.py'
            subprocess.run(SSH+[command], input=script, check=True, timeout=30)
            result = subprocess.run(SSH+[REMOTE+'/.venv/bin/python '+REMOTE+'/activate.py '+release],
                capture_output=True, text=True, timeout=600)
            if result.returncode:
                print('Publicação recusada; versão anterior preservada. Consulte o diagnóstico privado na Oracle.', flush=True)
                raise RuntimeError('Ensaio ou verificação de saúde falhou')
            state.write_text(release+'\n'); state.chmod(0o600)
            print('Oracle: código '+release+' aplicado; pesquisa e Discord verificados.', flush=True)
            return release

def watch():
    last = None; changed = 0; retry_at = 0
    while True:
        try:
            digest, _ = snapshot()
            if digest != last:
                last, changed = digest, time.monotonic()
            if time.monotonic()-changed >= 15 and time.monotonic() >= retry_at:
                publish()
                retry_at = time.monotonic()+30
        except Exception as error:
            print('Atualização da Oracle adiada: '+type(error).__name__, flush=True)
            retry_at = time.monotonic()+60
        time.sleep(5)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args()
    watch() if args.watch else publish()
