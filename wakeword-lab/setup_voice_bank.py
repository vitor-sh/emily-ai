"""Dedicated generator environment; never install into the wakeword/Emily env."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys


def run(command,root,env):
    with (root/'setup.log').open('a') as log:
        with subprocess.Popen([str(x) for x in command],cwd=root,env=env,stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as p:
            tail=[]
            for line in p.stdout:
                print(line,end='',flush=True)
                log.write(line);log.flush()
                tail=(tail+[line])[-25:]
            code=p.wait()
        if code:
            raise RuntimeError(f'Falha na preparação ({code}). Log: {root / "setup.log"}\n'+''.join(tail))


def generator_environment(source):
    env = source.copy()
    # Keep the NVIDIA driver paths that Colab injects. Only remove known old training libs/stubs.
    paths = []
    for path in env.get('LD_LIBRARY_PATH','').split(':'):
        if not path or '.training-venv/' in path or path.endswith('/stubs'):
            continue
        paths.append(path)
    for path in ['/usr/lib64-nvidia','/usr/local/nvidia/lib64','/usr/local/nvidia/lib']:
        if Path(path).is_dir() and path not in paths:
            paths.append(path)
    if paths:
        env['LD_LIBRARY_PATH'] = ':'.join(paths)
    else:
        env.pop('LD_LIBRARY_PATH',None)
    env['OMP_NUM_THREADS']='2';env['OPENBLAS_NUM_THREADS']='2'
    env['HF_HUB_DISABLE_TELEMETRY']='1'
    return env


def setup(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    env=generator_environment(os.environ)
    for executable in ['ffmpeg','sox']:
        if not shutil.which(executable):
            if not str(root).startswith('/content/'):
                raise RuntimeError('Este preparador é para Colab; falta '+executable)
            run(['apt-get','update','-qq'],root,env)
            run(['apt-get','install','-y','-qq',executable],root,env)
    python=root/'.voicegen-venv/bin/python'
    if not python.exists():
        old=Path('/content/emily-wakeword/.training-venv/bin/python')
        if old.is_file():
            run([old,'-m','venv',python.parent.parent],root,env)
        else:
            bootstrap=root/'.bootstrap'
            uv=bootstrap/'bin/uv'
            if not uv.is_file():
                run([sys.executable,'-m','pip','install','--target',bootstrap,'uv==0.8.22'],root,env)
            env['UV_PYTHON_INSTALL_DIR']=str(root/'.managed-python')
            env['UV_CACHE_DIR']=str(root/'.uv-cache');env['UV_NATIVE_TLS']='true'
            run([uv,'venv','--managed-python','--python','3.11','--seed',python.parent.parent],root,env)
    if shutil.disk_usage(root).free<20*1024**3:
        raise RuntimeError('Menos de 20 GiB livres no Colab. Não iniciar downloads dos modelos.')
    signature=hashlib.sha256((root/'requirements-voice-pilot.txt').read_bytes()+b'torch2.6.0+cu124').hexdigest()
    ready=root/'.dependencies-ready'
    if ready.exists() and ready.read_text()!=signature:
        raise RuntimeError('Dependências alteradas; use outra pasta isolada.')
    if not ready.exists():
        run([python,'-m','pip','install','torch==2.6.0','torchaudio==2.6.0',
             '--index-url','https://download.pytorch.org/whl/cu124'],root,env)
        run([python,'-m','pip','install','-r',root/'requirements-voice-pilot.txt'],root,env)
        run([python,'-m','pip','check'],root,env)
        ready.write_text(signature)
    run([python,'-m','unittest','test_voice_bank_pilot'],root,env)
    try:
        run([python,root/'voice_gpu_probe.py'],root,env)
    except RuntimeError as error:
        raise RuntimeError('A GPU não inicializou no ambiente do gerador. Isso não prova que a T4 '
                           'não foi selecionada. O diagnóstico acima identifica driver, visibilidade '
                           'e erro real do PyTorch; preserve esta sessão e seus arquivos.') from error
    run([python,'-c','from qwen_tts import Qwen3TTSModel; import whisper; '
         'print("Bibliotecas do gerador carregadas.")'],root,env)
    return str(python),env
