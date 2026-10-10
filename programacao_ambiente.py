"""Dependências de testes da Emily, compartilhadas sem alterar a cópia de fontes."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


def preparar_node(job, job_path, env, out):
    if job.get('finalidade') not in {'teste','comando'} or not re.search(r'\bnode(?:\.exe)?(?:[\s\"\']|$)', job['comando']):
        return
    assets = Path(__file__).parent / 'assets/programacao-node'
    # Só o ambiente da Emily usa esse conjunto. Projetos externos mantêm o
    # próprio manifesto e as próprias dependências.
    if not (Path(job['pasta']) / 'testes/test_waiting_indicator.js').is_file():
        return
    lock = (assets / 'package-lock.json').read_bytes()
    runtime = job_path.parent.parent / '_runtime-node' / hashlib.sha256(lock).hexdigest()[:16]
    ready = runtime / '.ready'
    if ready.exists() and not (runtime/'node_modules/jsdom/package.json').is_file():ready.unlink()
    if not ready.is_file():
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise RuntimeError('Os testes JavaScript precisam de Node.js/npm. Instale o runtime; o código não foi aplicado.')
        runtime.parent.mkdir(parents=True, exist_ok=True)
        guard = runtime.with_suffix('.lock')
        deadline = time.monotonic() + 150
        owned = False
        while True:
            try:
                guard.mkdir()
                owned = True
                break
            except FileExistsError:
                if ready.is_file(): break
                if time.time()-guard.stat().st_mtime > 180:
                    try: guard.rmdir()
                    except OSError: pass
                if time.monotonic() > deadline:
                    raise RuntimeError('A preparação das dependências continua ocupada; consulte o trabalho antes de repetir o teste.')
                time.sleep(.2)
        if not ready.is_file():
            try:
                with tempfile.TemporaryDirectory(dir=runtime.parent, prefix='preparando-') as temporary:
                    staging = Path(temporary)
                    for name in ('package.json', 'package-lock.json'):
                        shutil.copy2(assets/name, staging/name)
                    out.write('Preparando dependências dos testes JavaScript…\n'.encode()); out.flush()
                    subprocess.run([npm, 'ci', '--ignore-scripts', '--no-audit', '--no-fund'],
                                   cwd=staging, env=env, stdout=out, stderr=subprocess.STDOUT,
                                   timeout=120, check=True)
                    (staging/'.ready').write_text('Dependências do lockfile instaladas.\n')
                    if runtime.exists(): shutil.rmtree(runtime)
                    shutil.copytree(staging, runtime)
            finally:
                if owned: guard.rmdir()
        elif owned:
            guard.rmdir()
    modules = str(runtime/'node_modules')
    env['NODE_PATH'] = modules + (os.pathsep+env['NODE_PATH'] if env.get('NODE_PATH') else '')


def inspecionar(workspace, python_bin, preview=None):
    """Diagnóstico somente leitura; não importa o app nem lê suas credenciais."""
    import json
    script="import importlib.util,json,sys; print(json.dumps({'executavel':sys.executable,'versao':sys.version.split()[0],'pacotes':{name:importlib.util.find_spec(name) is not None for name in ['pytest','playwright','PIL','tiktoken']}}))"
    try:
        result=subprocess.run([python_bin,'-c',script],capture_output=True,text=True,timeout=10)
        py=json.loads(result.stdout) if result.returncode==0 else {'executavel':python_bin,'disponivel':False}
    except (OSError,ValueError,subprocess.TimeoutExpired):py={'executavel':python_bin,'disponivel':False}
    caches=[Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH',Path.home()/'.cache/ms-playwright')),Path(__file__).resolve().parent/'playwright-browsers']
    candidates=sorted(p for cache in caches for pattern in ('chromium-*/chrome-linux64/chrome','chromium-*/chrome-linux/chrome','chromium-*/chrome-win/chrome.exe') for p in cache.glob(pattern) if p.is_file())
    browser=shutil.which('chromium') or shutil.which('google-chrome') or (str(candidates[-1]) if candidates else None)
    return {'pasta':str(workspace),'python':py,
            'node':shutil.which('node'),'npm':shutil.which('npm.cmd' if os.name=='nt' else 'npm'),
            'navegador':browser,
            'previa':preview,'variaveis':['EMILY_PREVIEW_URL'] if preview else [],
            'orientacao':'A pasta é a raiz da cópia. Use python -m pytest com arquivos relativos. Node recebe jsdom automaticamente em testes/comandos da Emily. Teste visual precisa de previa/abrir; sem prévia não existe EMILY_PREVIEW_URL. Se a falha for no mock/selector do teste, corrija o teste pelo comportamento real, sem mascarar defeitos da aplicação.'}


def diagnosticar(text,job):
    code=job.get('codigo_saida')
    category=job.get('motivo_interrupcao') or ('teste_falhou' if job.get('finalidade')=='teste' else 'comando_falhou')
    advice='Leia a saída real; não atribua falha de execução à autorização humana.'
    if any(x in text for x in ('Cannot find module','ModuleNotFoundError','Executable doesn\'t exist','No module named')):
        category='dependencia_ausente';advice='Confira ambiente e a dependência informada antes de editar código. O executor prepara jsdom da Emily automaticamente; outros projetos usam seu manifesto.'
    elif 'EMILY_PREVIEW_URL' in text and 'KeyError' in text:
        category='previa_ausente';advice='Abra previa/abrir nesta sessão e consulte ambiente. O endereço ativo é injetado tanto em comando quanto em teste; não invente a porta.'
    elif 'Timeout' in text and any(x in text for x in ('wait_for_selector','locator','Locator','wait_for_function')):
        category='espera_da_interface';advice='Confira se a ponte iniciou, qual tela está aberta, o seletor real e o estado visível/oculto. Não aumente o timeout sem investigar a condição que não foi satisfeita.'
    elif 'ReferenceError' in text:
        category='referencia_javascript';advice='Confira a pilha. Se o teste executa só recortes de app.js, verifique funções/globais omitidas pelo harness antes de alterar a aplicação. Se a referência falha na prévia real, trate como defeito da aplicação.'
    elif code==1 and re.match(r'^\s*rg\s',job.get('comando','')) and not text.strip():
        category='busca_sem_correspondencias';advice='rg retornou 1 porque não encontrou resultados. Isso não prova falha do aplicativo nem equivale a teste funcional aprovado.'
    return {'categoria':category,'precisa_confirmacao':False,'codigo_saida':code,'orientacao':advice}
