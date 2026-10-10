"""Executor externo de testes: sobrevive ao fechamento/reinício da interface."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def run(path):
    job = json.loads(path.read_text())
    job['worker_pid'] = os.getpid()
    save(path, job)
    env = dict(os.environ)
    # O processo herda ferramentas/SDK, sem exportar credenciais de provedores.
    for key in list(env):
        if any(part in key.upper() for part in ('TOKEN', 'PASSWORD', 'SECRET', 'API_KEY')):
            env.pop(key)
    if 'LD_LIBRARY_PATH_ORIG' in env: env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    else: env.pop('LD_LIBRARY_PATH', None)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env.pop('EMILY_OVERRIDE_DIR', None)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    if job.get('previa_url'): env['EMILY_PREVIEW_URL'] = job['previa_url']
    browsers=Path(__file__).parent/'playwright-browsers'
    if browsers.is_dir():env['PLAYWRIGHT_BROWSERS_PATH']=str(browsers)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONPYCACHEPREFIX'] = str(path.parent/'python-cache'/job['id'])
    if job.get('finalidade') != 'publicacao':
        data = path.parent / 'dados-teste'; data.mkdir(exist_ok=True)
        env.update(EMILY_PROGRAMACAO_PREVIA='1', EMILY_BACKEND_PORTA='0', EMILY_DATA_DIR=str(data), EMILY_ARQUIVO_PREFERENCIAS=str(data/'preferencias.json'),
                   EMILY_ARQUIVO_CONVERSAS=str(data/'conversas.json'), EMILY_CONFIG_FILE=str(data/'config-vazia.env'),
                   EMILY_ARQUIVO_CODE_CONVERSAS=str(data/'code-conversas.json'), XDG_DATA_HOME=str(data/'xdg'))
    log = path.with_suffix('.log')
    try:
        with log.open('wb') as out:
            os.chmod(log, 0o600)
            job['fase']='preparando_ambiente';save(path,job)
            from programacao_ambiente import preparar_node
            preparar_node(job, path, env, out)
            shell = ['bash', '-c'] if os.name == 'posix' else ['powershell', '-NoProfile', '-Command']
            proc = subprocess.Popen(shell + [job['comando']], cwd=job['pasta'], env=env,
                                    stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
            job.update(pid=proc.pid, estado='executando', fase='executando', iniciado=time.time(), ambiente={'pasta':job['pasta'],'python_worker':sys.executable,'previa_url':env.get('EMILY_PREVIEW_URL'),'node_path':env.get('NODE_PATH')})
            save(path, job)
            deadline = time.monotonic() + job.get('limite_segundos', 1800)
            while proc.poll() is None:
                latest = json.loads(path.read_text())
                if latest.get('cancelar') or time.monotonic() >= deadline or log.stat().st_size > 16 * 1024 * 1024:
                    if os.name == 'posix': os.killpg(proc.pid, signal.SIGTERM)
                    else: proc.terminate()
                    try: proc.wait(5)
                    except subprocess.TimeoutExpired:
                        if os.name == 'posix': os.killpg(proc.pid, signal.SIGKILL)
                        else: proc.kill()
                        proc.wait()
                    job['interrompido'] = True
                    job['motivo_interrupcao'] = 'cancelamento_solicitado' if latest.get('cancelar') else 'tempo_processo' if time.monotonic() >= deadline else 'saida_excessiva'
                    break
                time.sleep(.2)
            job.update(codigo_saida=proc.returncode,
                       estado=('cancelado' if job.get('motivo_interrupcao') == 'cancelamento_solicitado' else 'interrompido') if job.get('interrompido') else 'concluido' if proc.returncode == 0 else 'falhou')
    except Exception as exc:
        job.update(estado='falhou', erro=str(exc))
    if job.get('estado') in {'falhou','interrompido'}:
        tail = log.read_bytes()[-6000:].decode('utf-8',errors='replace') if log.exists() else ''
        from programacao_ambiente import diagnosticar
        job['diagnostico'] = diagnosticar(tail+'\n'+job.get('erro',''),job)
    job['fase']='encerrado'
    job['finalizado'] = time.time()
    save(path, job)


if __name__ == '__main__':
    run(Path(sys.argv[1]))
