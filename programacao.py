"""Programação pelo chat: sessões persistentes, testes reais e aplicação reversível.

O diretório de trabalho é uma cópia; não é uma sandbox de segurança. Terminal,
USB e navegador continuam sujeitos à autorização do pedido e às políticas do PC.
"""
from __future__ import annotations
import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid

LOCK = threading.RLock()
STORE = (Path(os.environ['EMILY_DATA_DIR'])/'programacao' if os.getenv('EMILY_PROGRAMACAO_PREVIA')=='1' and os.getenv('EMILY_DATA_DIR') else Path.home()/'.local/share/emily/programacao')
EXT = {'.py', '.js', '.css', '.html', '.kt', '.kts', '.xml', '.json', '.svg', '.md', '.txt', '.toml', '.properties', '.gradle', '.sh', '.bat', '.png', '.jpg', '.jpeg', '.webp', '.jar', '.woff', '.woff2', '.ttf', '.ico', '.gif', '.avif'}
DIRS = {'web', 'static', 'img', 'assets', 'testes', 'tests', 'memoria_unificada', 'emily_cloud', 'emily-gateway-service', 'EmilyAPP2', 'EmilyMusic', 'src', 'app', 'components', 'lib', 'public', 'gradle'}
SKIP = {'build', 'dist', 'output', 'backups', 'node_modules', '__pycache__', '.git', '.gradle', '.venv', 'venv', 'logs'}
PRIVATE = {'local.properties', 'editor-layout.json', 'editor-draft.json', 'android-editor-draft.json', 'android-editor-code-draft.json', 'android-editor-phone-draft.json', 'memoria.json', 'preferencias.json', 'latest.json', 'google-services.json'}
PROTECTED = {'programacao.py', 'programacao_worker.py', 'programacao_deploy.py', 'emily_bootstrap.py', 'pyi_rhook_emily.py'}
BINARY = {'.png', '.jpg', '.jpeg', '.webp', '.jar', '.woff', '.woff2', '.ttf', '.ico', '.gif', '.avif'}
POLICY = """
Programação pelo chat (PC e Android): você pode corrigir a própria Emily ou outro projeto
quando o pedido autorizar. Abra ferramentas de programacao e use iniciar para criar uma cópia
persistente com código, testes e ambiente de trabalho. Não é necessário entrar no editor nem
no Emily Code. Use o modelo atual e raciocínio escolhido; combine livremente pesquisa,
terminal, navegador e agente visual quando forem úteis. Não encaminhe por palavras-chave.
Leia as instruções do projeto e o código antes de editar. Explique o plano e mantenha comentários
naturais com comentar, especialmente após encontrar algo, mudar abordagem ou durante testes.
No começo, antes da primeira ferramenta, escreva uma frase curta explicando por onde começa.
Use o preâmbulo ou comentario_progresso da mesma resposta com ferramentas; não precisa de outra chamada só para narrar.
Durante o trabalho comente apenas achados, obstáculos ou mudanças relevantes de plano,
não narre cada leitura nem cada comando. Comentários não são a resposta final.
A implementação pode ajustar componentes compartilhados e corrigir problemas diretamente
relacionados ao objetivo, sem exigir que o usuário liste cada arquivo. Se uma decisão mudar
significativamente o efeito solicitado, pergunte; uma recusa de ferramenta não significa incapacidade geral.
Editar/criar só muda a cópia. Executar pode rodar testes, servidores de prévia e scripts; resultados
pendentes exigem status, nunca repetir um comando por timeout. Comandos e USB atuam com o
usuário do PC; operações sérias ainda exigem confirmação pelos meios existentes.
Escolha a verificação pelo risco e pelo comportamento alterado. Para ajustes simples de
texto, ícone, cor ou espaçamento, uma conferência focada do resultado e da interação afetada
é suficiente; use a prévia quando ajudar. Para lógica, persistência, permissões ou integrações,
teste os fluxos afetados e as regressões pertinentes. Não rode a suíte completa nem repita
verificações já aprovadas na mesma revisão sem um risco concreto ainda pendente.
Ao retomar após interrupção, consulte status da sessão: testes_aprovados e conferencias_visuais
mostram evidência da revisão atual. Reutilize-a e siga para a etapa pendente; interrupção não
invalida um teste aprovado. Nova alteração ou mudança de ambiente/dados pode exigir repetir.
Executar reutiliza um teste idêntico aprovado na mesma revisão; reexecutar=true permite repetir
quando houver motivo concreto. Uma análise visual pode apontar defeitos: lê-la não significa aprovação.
Quando a conferência necessária já passou, aplique/publice e conclua; não invente testes extras.
Agrupe leituras relacionadas e comandos independentes numa mesma rodada quando adequado.
Use status com espera para processos ativos; não consulte repetidamente sem tempo de espera.
Teste o comportamento pedido na versão de código em preparação;
não conte echo, leitura, lint ou sintaxe como teste funcional. Se um teste falhar, leia a saída real antes de editar: dependência ausente não é defeito do código.
Antes do primeiro teste, consulte ambiente para conhecer pasta, runtimes, pacotes e prévia.
Comandos começam na raiz da cópia, inclusive quando executados por Python; use caminhos relativos.
O executor prepara jsdom tanto em testes quanto em comandos Node da Emily e passa EMILY_PREVIEW_URL
quando há prévia ativa. Abra previa/abrir se o teste visual precisar dela; não invente endereço.
Use finalidade=teste para conferências que contam como validação antes de aplicar. Um comando
exploratório não registra teste aprovado, mesmo se sair com 0. Espere a ponte da prévia iniciar,
navegue à tela certa e confira se o seletor existe antes de consultar estilos ou aguardar visibilidade.
Em falhas de ReferenceError num teste que extrai pedaços de JavaScript, confira as funções/globais
omitidas pelo próprio teste; não acrescente código de produção só para satisfazer um mock incompleto.
Não procure node_modules ou navegadores por varredura de todo o disco: ambiente mostra os caminhos.
Se rg retornar 1 sem correspondências, isso é resultado da busca, não falha de validação.
Corrija o problema identificado e rode novamente. Programas de prévia precisam ser encerrados ao terminar. Use navegador/tela para
verificar UI e USB para celular real quando conectado. Sem USB, compile, relate o limite e não
finja teste em aparelho. Não use force-stop nem desinstale a Emily; preserve assinatura, dados,
assistente e overlay. Não altere preferências, memórias, tokens ou rascunhos do usuário.
Para mudanças visuais web, use previa/abrir para visualizar a cópia no navegador sem aplicar.
Previa/capturar tira screenshots controlados dessa prévia, em telas e tamanhos escolhidos;
use ver_imagem para inspecioná-los. A prévia web usa dados de amostra e não a ponte real:
valida apresentação, não execução real de ferramentas. Para o Android use android/capturar.
Se o original mudar durante a tarefa, use comparar e atualizar: mescla trechos independentes,
preserva seu trabalho e deixa conflitos sobrepostos intactos. Use resolver com os hashes
retornados pela comparação e uma escolha explícita; o original não muda até aplicar.
Depois de atualizar/resolver, rode os testes novamente; nunca sobrescreva mudanças concorrentes.
Aplicar confere conflitos, valida sintaxe, exige teste na revisão atual e salva backup. A aplicação inicia automaticamente a publicação da Emily na Oracle/pacote PC.
Confirme status da publicação antes de concluir; se falhar, explique sem declarar sucesso. Python precisa
reiniciar para carregar; pergunte antes de reiniciar, nunca mate a instância que mantém a conversa.
Ao terminar diga o que mudou, evidências de testes, o que precisa reiniciar e limites não verificados.
"""


class BloqueioProgramacao(ValueError):
    def __init__(self, message, code, **details):
        super().__init__(message)
        self.diagnostic = dict(codigo=code, **details)


def digest(data): return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def root_source():
    import editor_interface
    root = editor_interface.destinos()[1]
    if root is None: raise ValueError('Projeto fonte não encontrado neste PC.')
    return Path(root).resolve()


def safe(root, name):
    if not isinstance(name, str) or not name or '\\' in name or len(name) > 500:
        raise ValueError('Caminho relativo inválido.')
    rel = Path(name)
    if rel.is_absolute() or any(p.startswith('.') or p in SKIP for p in rel.parts) or rel.name in PRIVATE | PROTECTED:
        raise ValueError('Arquivo privado, protegido ou fora do projeto.')
    if rel.suffix.lower() not in EXT and rel.name not in {'gradlew', 'requirements.txt', 'AGENTS.md'}:
        raise ValueError('Formato não suportado para edição.')
    dest = root / rel
    if not dest.resolve().is_relative_to(root.resolve()) or any(p.is_symlink() for p in [dest, *dest.parents] if p != root.parent):
        raise ValueError('Links externos não podem ser editados.')
    return dest


def files(root):
    result = []
    for base, dirs, names in os.walk(root):
        relative = Path(base).relative_to(root)
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith('.') and not (Path(base)/d).is_symlink()
                   and (relative.parts or d in DIRS)]
        for name in names:
            rel = (relative / name).as_posix()
            try: path = safe(root, rel)
            except ValueError: continue
            if path.is_file() and path.stat().st_size <= 8 * 1024 * 1024: result.append(rel)
    return sorted(result)


def load(sid):
    if not isinstance(sid, str) or not re.fullmatch('[a-f0-9]{32}', sid): raise ValueError('Sessão inválida.')
    folder = STORE / sid
    if not (folder / 'session.json').is_file(): raise ValueError('Sessão não encontrada; use listar para recuperar.')
    return folder, json.loads((folder / 'session.json').read_text())


def changed(folder, data):
    work = folder / 'workspace'
    hashes = {n: digest(safe(work, n).read_bytes()) for n in files(work)}
    # Ferramentas não apagam arquivos: uma remoção por terminal participa da revisão.
    return {n: hashes.get(n) for n in sorted(hashes.keys() | data['base'].keys()) if hashes.get(n) != data['base'].get(n)}


def revision(folder, data): return digest(json.dumps({'base': data['base'], 'changes': changed(folder, data)}, sort_keys=True).encode())


def python():
    if not getattr(sys, 'frozen', False): return sys.executable
    found = shutil.which('python3') or shutil.which('python')
    if not found: raise ValueError('Python instalado é necessário para executar testes e compilar neste PC.')
    return found


def start(objetivo, projeto=''):
    if not isinstance(objetivo, str) or not objetivo.strip() or len(objetivo) > 6000: raise ValueError('Informe o objetivo autorizado.')
    source = Path(projeto).expanduser().resolve() if projeto else root_source()
    if not source.is_dir(): raise ValueError('Pasta do projeto não encontrada.')
    sid = uuid.uuid4().hex; folder = STORE / sid; work = folder / 'workspace'
    work.mkdir(parents=True, mode=0o700)
    (folder / 'originals').mkdir(mode=0o700)
    base = {}; size = 0
    for name in files(source):
        src = safe(source, name); raw = src.read_bytes(); size += len(raw)
        if size > 300 * 1024 * 1024: raise ValueError('Projeto ultrapassa 300 MiB de fontes; escolha uma subpasta.')
        for root in (work, folder / 'originals'):
            dest = safe(root, name); dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw); os.chmod(dest, src.stat().st_mode & 0o777)
        base[name] = digest(raw)
    # Infraestrutura de runtime disponível para testes, protegida da aplicação.
    for name in PROTECTED:
        if (source/name).is_file(): shutil.copy2(source/name, work/name)
    # Apenas configuração local do SDK, não editável nem incluída na aplicação.
    local = source / 'EmilyAPP2/local.properties'
    if local.is_file() and (work / 'EmilyAPP2').is_dir():
        sdk = [line for line in local.read_text().splitlines() if line.startswith('sdk.dir=')]
        (work / 'EmilyAPP2/local.properties').write_text('\n'.join(sdk)+'\n')
    google = source/'EmilyAPP2/app/google-services.json'
    if google.is_file(): shutil.copy2(google, work/'EmilyAPP2/app/google-services.json')
    data = dict(id=sid, objetivo=objetivo, projeto=str(source), criado=time.time(), base=base, jobs=[], estado='preparando', eventos=[])
    save(folder / 'session.json', data)
    try: self_project = source == root_source()
    except ValueError: self_project = False
    return dict(ok=True, sessao=sid, projeto=str(source), projeto_emily=self_project, publicacao_automatica=self_project and os.getenv('EMILY_PROGRAMACAO_PREVIA')!='1', pasta=str(work), arquivos=len(base), mensagem='Cópia pronta. Leia AGENTS.md, implemente e execute testes aqui; o projeto original ainda não mudou.')


def event(folder, data, text, kind):
    data['eventos'].append(dict(texto=str(text)[:1200], categoria=kind, instante=time.time()))
    data['eventos'] = data['eventos'][-120:]
    save(folder / 'session.json', data)


def job_start(folder, data, command, purpose, android_compile=False, reexecutar=False):
    import terminal
    if not isinstance(command, str) or not command.strip() or len(command) > 16000: raise ValueError('Comando inválido.')
    if purpose != 'publicacao' and terminal.classificar(command) != terminal.LIVRE:
        raise BloqueioProgramacao('Comando exige confirmação. Use o terminal normal/remoto com a confirmação do usuário, sem contornar o portão.', 'confirmacao_terminal', precisa_confirmacao=True, proximo_meio='terminal com confirmação')
    current_revision = revision(folder, data)
    for jid in reversed(data['jobs']):
        job = json.loads((folder / f'{jid}.json').read_text())
        if not reexecutar and purpose == 'teste' and job['estado'] == 'concluido' and job['finalidade'] == purpose and job['comando'] == command and job['revisao'] == current_revision and bool(job.get('android_compilacao')) == bool(android_compile):
            return dict(status(folder, data, jid), reutilizado=True, mensagem='Este teste já passou na revisão atual. Evidência reutilizada; não foi executado de novo.')
        if job['estado'] in {'iniciando', 'executando'} and job['comando'] == command and job['finalidade'] == purpose:
            return status(folder, data, jid)
    jid = uuid.uuid4().hex
    job = dict(id=jid, estado='iniciando', comando=command, finalidade=purpose, pasta=data['projeto'] if purpose == 'publicacao' else str(folder / 'workspace'),
               revisao=current_revision, criado=time.time(), limite_segundos=1800, android_compilacao=android_compile)
    preview = data.get('previa')
    if purpose != 'publicacao' and preview and status(folder, data, preview['trabalho'])['estado'] in {'iniciando','executando'}:
        job['previa_url'] = preview['url']
    path = folder / f'{jid}.json'; save(path, job)
    worker = Path(__file__).with_name('programacao_worker.py')
    env=dict(os.environ)
    if 'LD_LIBRARY_PATH_ORIG' in env: env['LD_LIBRARY_PATH']=env.pop('LD_LIBRARY_PATH_ORIG')
    else: env.pop('LD_LIBRARY_PATH',None)
    env.pop('PYTHONHOME',None);env.pop('PYTHONPATH',None);env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    subprocess.Popen([python(), str(worker), str(path)], cwd=str(folder), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    data['jobs'].append(jid); event(folder, data, f'{purpose}: {command}', 'testes' if purpose == 'teste' else 'terminal')
    time.sleep(.15)
    return status(folder, data, jid)


def status(folder, data, jid=''):
    if jid:
        if jid not in data['jobs']: raise ValueError('Trabalho não pertence a esta sessão.')
        path = folder / f'{jid}.json'
        job = json.loads(path.read_text())
        if job['estado'] in {'iniciando','executando'} and time.time()-job['criado']>10:
            alive = False
            if job.get('worker_pid'):
                try:
                    os.kill(job['worker_pid'],0); alive=True
                    if os.name=='posix' and Path('/proc').is_dir():
                        alive=str(path).encode() in (Path('/proc')/str(job['worker_pid'])/'cmdline').read_bytes()
                except (OSError,ProcessLookupError): pass
            if not alive:
                job.update(estado='interrompido',erro='O executor terminou sem confirmar resultado (reinício/crash). A cópia e o progresso foram preservados. Confira efeitos/processos antes de retomar.')
                save(path,job)
        log = folder / f'{jid}.log'
        output = ''
        if log.is_file():
            with log.open('rb') as f:
                f.seek(max(0, log.stat().st_size - 12000)); output = f.read().decode('utf-8', errors='replace')
        return dict(ok=job['estado'] not in {'falhou', 'cancelado', 'interrompido'}, trabalho=jid, estado=job['estado'],
                    fase=job.get('fase'), ambiente=job.get('ambiente'), codigo_saida=job.get('codigo_saida'), saida=output, erro=job.get('erro'), diagnostico=job.get('diagnostico'),
                    mensagem='Consulte status para acompanhar; não repita execução.' if job['estado'] in {'iniciando', 'executando'} else 'Confira a saída e o comportamento antes de anunciar sucesso.')
    publication = status(folder,data,data['publicacao']) if data.get('publicacao') else None
    if publication and publication['estado'] not in {'iniciando','executando'}:
        data['estado'] = 'publicado' if publication['estado']=='concluido' else 'falha_publicacao'
        save(folder/'session.json',data)
    rev = revision(folder, data)
    validations = []
    for job_id in data['jobs']:
        job = json.loads((folder/f'{job_id}.json').read_text())
        if job['finalidade'] == 'teste' and job['estado'] == 'concluido' and job.get('revisao') == rev:
            validations.append(dict(trabalho=job_id, comando=job['comando'][:1000], codigo_saida=job.get('codigo_saida'), finalizado=job.get('finalizado'), android_compilacao=job.get('android_compilacao',False)))
    visual = [dict(v,analise=v['analise'][:1200],analise_resumida=len(v['analise'])>1200) for v in data.get('conferencias_visuais',[]) if v['revisao'] == rev]
    return dict(ok=True, previa=data.get('previa'), revisao_atual=rev, testes_aprovados=validations, conferencias_visuais=visual, publicacao=publication, sessao=data['id'], objetivo=data['objetivo'], projeto=data['projeto'], estado=data['estado'], pasta=str(folder/'workspace'),
                alterados=list(changed(folder, data)), trabalhos=data['jobs'], eventos=data['eventos'][-20:], aplicacao=data.get('aplicacao'))


def validate(name, raw):
    if Path(name).suffix in BINARY: return
    text = raw.decode('utf-8-sig')
    if name.endswith('.py'): ast.parse(text, filename=name)
    elif name.endswith('.json'): json.loads(text)
    elif name.endswith('.xml'):
        import xml.etree.ElementTree as ET
        ET.fromstring(text)
    elif name.endswith('.js'):
        node = shutil.which('node')
        if not node: raise ValueError('Node necessário para validar JavaScript.')
        result = subprocess.run([node, '--check', '-'], input=text, text=True, capture_output=True, timeout=20)
        if result.returncode: raise ValueError(result.stderr[-1800:])


def apply(folder, data):
    if data['estado']=='desfeito': raise ValueError('Sessão desfeita; inicie outra para novas mudanças.')
    if data.get('aplicacao'): return dict(ok=True, publicacao=status(folder,data,data['publicacao']) if data.get('publicacao') else None, **data['aplicacao'])
    changes = changed(folder, data)
    if not changes: raise ValueError('Nenhuma mudança preparada.')
    rev = revision(folder, data); tested = False
    for jid in data['jobs']:
        job = json.loads((folder / f'{jid}.json').read_text())
        if job['estado'] in {'iniciando', 'executando'}: raise ValueError('Encerre os processos de prévia e aguarde os testes antes de aplicar.')
        tested |= job['finalidade'] == 'teste' and job['estado'] == 'concluido' and job['revisao'] == rev
    if not tested: raise BloqueioProgramacao('Execute teste funcional com finalidade=teste na revisão atual antes de aplicar.', 'teste_da_revisao_pendente', precisa_confirmacao=False, proxima_ferramenta='programacao_executar')
    if any(n.endswith(('.kt','.kts','.xml')) and n.startswith('EmilyAPP2/') for n in changes):
        compiled = any((j:=json.loads((folder/f'{jid}.json').read_text())).get('android_compilacao') and j['estado']=='concluido' and j['revisao']==rev for jid in data['jobs'])
        if not compiled: raise ValueError('Use android com operacao=compilar para validar o Android nativo na revisão atual antes de aplicar.')
    source = Path(data['projeto']); writes = []
    for name in changes:
        original = safe(source, name); work = safe(folder/'workspace', name)
        if (digest(original.read_bytes()) if original.is_file() else None) != data['base'].get(name):
            raise BloqueioProgramacao('Conflito: outro processo alterou ' + name + '. Compare as três versões e atualize/resolva a cópia antes de testar novamente.', 'conflito_original', arquivo=name, precisa_confirmacao=False, proximas_ferramentas=['programacao_comparar','programacao_atualizar','programacao_resolver'])
        if changes[name] is not None: validate(name, work.read_bytes())
        writes.append((original, work.read_bytes() if changes[name] is not None else None))
    targets = []
    try: self_project = source == root_source()
    except ValueError: self_project = False
    if self_project:
        targets = [source/'dist/Emily/_internal', source/'emily-windows-instance', source.parent/'emily-windows-instance', source/'emily-linux-instance']
        for target in targets:
            if not (target/'web/index.html').is_file(): continue
            for name in changes:
                if name.startswith(('EmilyAPP2/', 'tests/', 'testes/')): continue
                writes.append((safe(target, name), safe(folder/'workspace',name).read_bytes() if changes[name] is not None else None))
    # Backup de cada destino (as cópias compiladas podem divergir da fonte).
    backup = folder / 'applied-backup'; backup.mkdir(exist_ok=True)
    journal = []
    for i, (path, raw) in enumerate(writes):
        before = path.read_bytes() if path.is_file() else None
        if before is not None: (backup/str(i)).write_bytes(before)
        journal.append(dict(path=str(path), before=i if before is not None else None, after=digest(raw) if raw is not None else None))
    save(folder/'apply-journal.json', journal)
    done = []
    try:
        for path, raw in writes:
            if raw is None: path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name+'.programacao.tmp'); temp.write_bytes(raw)
                os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o644); os.replace(temp,path)
            done.append(path)
    except BaseException:
        for item in journal[:len(done)]:
            path=Path(item['path'])
            if item['before'] is None: path.unlink(missing_ok=True)
            else: path.write_bytes((backup/str(item['before'])).read_bytes())
        raise
    result = dict(sessao=data['id'], arquivos=list(changes), backup=str(folder), reiniciar_pc=self_project and any(n.endswith('.py') and not n.startswith('EmilyAPP2/') for n in changes),
                  compilar_android=any(n.startswith('EmilyAPP2/') for n in changes), mensagem='Código aplicado e backup salvo. Confirme publicação e reinício antes de dizer que está ativo.')
    data.update(estado='aplicado', aplicacao=result); event(folder,data,'Alterações aplicadas após os testes.','codigo')
    if self_project and data.get('publicar_automaticamente', True) and os.getenv('EMILY_PROGRAMACAO_PREVIA')!='1':
        command = shlex.join([python(), str(Path(__file__).with_name('programacao_deploy.py')), str(folder/'session.json')]) if os.name == 'posix' else subprocess.list2cmdline([python(),str(Path(__file__).with_name('programacao_deploy.py')),str(folder/'session.json')])
        publication = job_start(folder,data,command,'publicacao')
        data['publicacao']=publication['trabalho'];data['estado']='publicando';save(folder/'session.json',data)
        result.update(publicacao=publication, mensagem='Código aplicado; publicação em andamento. Consulte status até concluir. Reiniciar o PC precisa da resposta do usuário.')
    return dict(ok=True, **result)



def android(folder, data, args):
    adb=shutil.which('adb') or str(Path(os.getenv('ANDROID_HOME',str(Path.home()/'Android/Sdk')))/'platform-tools/adb')
    operation=args.get('operacao'); work=folder/'workspace'
    if operation=='compilar':
        if not (work/'EmilyAPP2/gradlew').is_file(): raise ValueError('Projeto Android não está nesta sessão.')
        command='./gradlew :app:assembleDebug --no-daemon --max-workers=1' if os.name=='posix' else '.\\gradlew.bat :app:assembleDebug --no-daemon --max-workers=1'
        command=('cd EmilyAPP2 && '+command)
        return job_start(folder,data,command,'teste',android_compile=True)
    devices=subprocess.run([adb,'devices'],capture_output=True,text=True,timeout=10)
    available=[line.split()[0] for line in devices.stdout.splitlines()[1:] if line.endswith('\tdevice')]
    if operation=='dispositivos': return dict(ok=True,dispositivos=available,mensagem='Nenhum USB autorizado.' if not available else 'USB disponível.')
    serial=args.get('serial') or (available[0] if len(available)==1 else None)
    if serial not in available: raise ValueError('Conecte/desbloqueie o USB autorizado; especifique serial se houver vários.')
    command=[adb,'-s',serial]
    if operation=='instalar':
        rev=revision(folder,data)
        valid=any((j:=json.loads((folder/f'{jid}.json').read_text())).get('android_compilacao') and j['estado']=='concluido' and j['revisao']==rev for jid in data['jobs'])
        if not valid: raise ValueError('Compile a revisão atual com android/compilar antes de instalar para teste.')
        apk=work/'EmilyAPP2/app/build/outputs/apk/debug/app-debug.apk'
        if not apk.is_file(): raise ValueError('APK não encontrado.')
        apksigner=next(iter(sorted((Path(os.getenv('ANDROID_HOME',str(Path.home()/'Android/Sdk')))/'build-tools').glob('*/apksigner'),reverse=True)),None)
        if apksigner is None: raise ValueError('apksigner necessário para conferir a assinatura antes de instalar.')
        verify=subprocess.run([str(apksigner),'verify','--print-certs',str(apk)],capture_output=True,text=True,timeout=15,check=True)
        if 'Signer #1 certificate SHA-256 digest:' not in verify.stdout: raise ValueError('Assinatura do APK não validada.')
        # install -r recusa assinaturas diferentes sem remover a instalação ou os dados.
        command += ['install','-r',str(apk)]
    elif operation=='capturar':
        result=subprocess.run(command+['exec-out','screencap','-p'],capture_output=True,timeout=10)
        if result.returncode or not result.stdout.startswith(b'\x89PNG'): raise ValueError('Captura do celular falhou.')
        dest=folder/'captura.png';dest.write_bytes(result.stdout);os.chmod(dest,0o600)
        return dict(ok=True,arquivo='captura.png',caminho=str(dest),mensagem='Captura atual salva. Use ver_imagem com pergunta para analisar visualmente.')
    elif operation=='hierarquia':
        subprocess.run(command+['shell','uiautomator','dump','/data/local/tmp/emily-programacao.xml'],capture_output=True,timeout=10,check=True)
        command += ['shell','cat','/data/local/tmp/emily-programacao.xml']
    elif operation=='logs': command += ['logcat','-d','-t','120','-s','EmilyAgent','AndroidRuntime','System.err']
    elif operation=='tocar': command += ['shell','input','tap',str(int(args['x'])),str(int(args['y']))]
    elif operation=='arrastar': command += ['shell','input','swipe',str(int(args['x'])),str(int(args['y'])),str(int(args['x2'])),str(int(args['y2'])),'300']
    elif operation=='tecla':
        key=args.get('tecla')
        if key not in {'BACK','HOME','ENTER','TAB','DEL','APP_SWITCH'}: raise ValueError('Tecla não permitida.')
        command += ['shell','input','keyevent','KEYCODE_'+key]
    elif operation=='abrir': command += ['shell','am','start','-f','0x24000000','-n','com.example.emilyapp/.MainActivity']
    else: raise ValueError('Operação USB inválida.')
    result=subprocess.run(command,capture_output=True,text=True,timeout=60 if operation=='instalar' else 15)
    return dict(ok=result.returncode==0 and (operation!='instalar' or 'Success' in result.stdout),serial=serial,saida=result.stdout[-14000:],erro=result.stderr[-1500:],
                mensagem='Resultado real do USB; confira a tela e as permissões antes de concluir.')

def execute(operation, args=None, progress=None):
    args = dict(args or {})
    with LOCK:
        try:
            if operation == 'iniciar': return start(args.get('objetivo'), args.get('projeto',''))
            if operation == 'listar':
                STORE.mkdir(parents=True,exist_ok=True)
                sessions=[]
                for path in sorted(STORE.glob('*/session.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]:
                    d=json.loads(path.read_text()); sessions.append({k:d[k] for k in ('id','objetivo','estado','criado')})
                return dict(ok=True,sessoes=sessions)
            folder, data = load(args.get('sessao')); work=folder/'workspace'
            if operation == 'ambiente':
                from programacao_ambiente import inspecionar
                preview=data.get('previa')
                if preview and status(folder,data,preview['trabalho'])['estado'] not in {'iniciando','executando'}:preview=None
                return dict(ok=True,**inspecionar(work,python(),preview))
            if operation == 'status':
                jid=args.get('trabalho',''); wait=min(30,max(0,float(args.get('aguardar_segundos',15 if jid else 0))))
                deadline=time.monotonic()+wait
                result=status(folder,data,jid)
                while jid and result['estado'] in {'iniciando','executando'} and time.monotonic()<deadline:
                    time.sleep(.2); result=status(folder,data,jid)
                return result
            if operation in {'comparar','atualizar','resolver'}:
                import programacao_workspace as ws
                if operation == 'comparar': return dict(ok=True,arquivos=ws.compare(folder,data,sys.modules[__name__],args.get('arquivo','')))
                if operation == 'atualizar': return ws.refresh(folder,data,sys.modules[__name__])
                return ws.resolve(folder,data,sys.modules[__name__],args)
            if operation == 'previa':
                op=args.get('operacao','abrir')
                if op=='abrir':
                    argv=[python(),str(Path(__file__).with_name('programacao_preview.py')),str(work)]
                    command=shlex.join(argv) if os.name=='posix' else subprocess.list2cmdline(argv)
                    result=job_start(folder,data,command,'previa')
                    jid=result['trabalho'];deadline=time.monotonic()+5
                    url=''
                    while time.monotonic()<deadline:
                        state=status(folder,data,jid)
                        for line in state['saida'].splitlines():
                            try: url=json.loads(line).get('url','')
                            except (ValueError,AttributeError): continue
                            if url: break
                        if url or state['estado'] not in {'iniciando','executando'}: break
                        time.sleep(.1)
                    if not url: return dict(ok=False,trabalho=jid,diagnostico=state,mensagem='A prévia não iniciou; confira o diagnóstico antes de tentar outro meio.')
                    data['previa']={'url':url,'trabalho':jid};save(folder/'session.json',data)
                    return dict(ok=True,url=url,trabalho=jid,tipo='visual_com_dados_de_amostra',mensagem='Prévia da cópia. Use navegador/visual para interagir. Sem ponte com a instalação real; não confirma ações do backend. Encerre com cancelar antes de aplicar.')
                if op=='capturar':
                    import programacao_preview
                    preview=data.get('previa',{})
                    if not preview or status(folder,data,preview['trabalho'])['estado'] not in {'iniciando','executando'}: raise ValueError('Abra a prévia desta sessão antes de capturar.')
                    width=max(320,min(2560,int(args.get('largura',1200))));height=max(400,min(1600,int(args.get('altura',850))))
                    output=folder/('preview-'+uuid.uuid4().hex+'.png')
                    capture=programacao_preview.capture(preview['url'],output,width,height,args.get('tela',''))
                    capture['arquivo']=output.name
                    data.setdefault('capturas',{})[output.name]={'revisao':revision(folder,data),'sha256':digest(output.read_bytes())}
                    save(folder/'session.json',data)
                    return dict(ok=True,**capture,mensagem='Screenshot real da interface da cópia com dados de amostra. Use ver_imagem; o programa instalado não foi alterado.')
                raise ValueError('Operação de prévia inválida.')
            if operation == 'comentar':
                text=args.get('texto',''); category=args.get('categoria','codigo'); event(folder,data,text,category)
                if callable(progress): progress('fala', {'texto':text,'categoria':category})
                return dict(ok=True,mensagem='Comentário registrado.',texto=text)
            if operation == 'arquivos': return dict(ok=True,arquivos=files(work),pasta=str(work))
            if operation == 'ler':
                path=safe(work,args.get('arquivo')); text=path.read_text(encoding='utf-8-sig').splitlines()
                start_line=max(1,int(args.get('inicio',1))); end=min(len(text),int(args.get('fim',start_line+200)))
                return dict(ok=True,texto='\n'.join(f'{i+1}: {text[i]}' for i in range(start_line-1,end))[:35000],linhas=len(text))
            if operation == 'buscar':
                term=args.get('texto',''); matches=[]
                if not term: raise ValueError('Informe o texto literal.')
                for name in files(work):
                    if Path(name).suffix in BINARY: continue
                    for i,line in enumerate(safe(work,name).read_text(encoding='utf-8-sig',errors='replace').splitlines()):
                        if term in line: matches.append(f'{name}:{i+1}: {line[:300]}')
                        if len(matches)>=120: return dict(ok=True,resultados=matches,truncado=True)
                return dict(ok=True,resultados=matches)
            if operation in {'editar','criar'}:
                if data.get('aplicacao'): raise ValueError('Sessão já aplicada; inicie outra para novas mudanças.')
                path=safe(work,args.get('arquivo')); path.parent.mkdir(parents=True,exist_ok=True)
                if operation=='criar':
                    if path.exists(): raise ValueError('Arquivo existe; use editar.')
                    text=args.get('conteudo','')
                else:
                    text=path.read_text(encoding='utf-8-sig'); needle=args.get('buscar','')
                    if not needle or text.count(needle)!=1: raise ValueError('A substituição precisa corresponder a exatamente um trecho; releia o arquivo.')
                    text=text.replace(needle,args.get('substituir',''),1)
                if len(text.encode())>700000: raise ValueError('Arquivo grande demais.')
                path.write_text(text,encoding='utf-8'); event(folder,data,'Preparado '+args['arquivo'],'codigo')
                return dict(ok=True,mensagem='Alteração preparada na cópia, ainda não aplicada.',revisao=revision(folder,data))
            if operation == 'diff':
                chunks=[]
                for name in changed(folder,data):
                    if Path(name).suffix in BINARY: chunks.append('Recurso binário: '+name);continue
                    before=folder/'originals'/name; after=safe(work,name)
                    chunks.extend(difflib.unified_diff(before.read_text(errors='replace').splitlines(True) if before.exists() else [],after.read_text(errors='replace').splitlines(True) if after.exists() else [],fromfile=name,tofile=name))
                return dict(ok=True,diff=''.join(chunks)[:40000],revisao=revision(folder,data))
            if operation == 'executar':
                purpose=args.get('finalidade','comando')
                if purpose not in {'teste','comando','previa'}: raise ValueError('Finalidade inválida.')
                return job_start(folder,data,args.get('comando'),purpose,reexecutar=args.get('reexecutar') is True)
            if operation == 'cancelar':
                jid=args.get('trabalho')
                if jid not in data['jobs']: raise ValueError('Trabalho não encontrado.')
                path=folder/f'{jid}.json'; job=json.loads(path.read_text());job['cancelar']=True;save(path,job)
                return dict(ok=True,mensagem='Cancelamento solicitado; confira status.')
            if operation == 'android': return android(folder,data,args)
            if operation == 'ver_imagem':
                import base64, modelo
                name=args.get('arquivo');path=(folder/name).resolve()
                if not path.is_relative_to(folder.resolve()) or path.suffix not in {'.png','.jpg','.webp'} or path.stat().st_size>8*1024*1024: raise ValueError('Use a imagem capturada desta sessão.')
                capture=data.get('capturas',{}).get(name)
                if capture and capture['sha256']==digest(path.read_bytes()):
                    previous=next((v for v in reversed(data.get('conferencias_visuais',[])) if v['arquivo']==name and v['revisao']==capture['revisao'] and v['pergunta']==args.get('pergunta','')),None)
                    if previous: return dict(ok=True,analise=previous['analise'],reutilizado=True,mensagem='Esta mesma captura já foi analisada com a mesma pergunta.')
                analysis=modelo.analisar_tela_com_pergunta(base64.b64encode(path.read_bytes()).decode(),args.get('pergunta','Confira a interface e problemas visuais.'))
                if not analysis: raise ValueError('O modelo de visão não retornou análise; captura salva, mas validação visual pendente.')
                capture=data.get('capturas',{}).get(name)
                if capture and capture['sha256']==digest(path.read_bytes()):
                    data.setdefault('conferencias_visuais',[]).append(dict(arquivo=name,revisao=capture['revisao'],pergunta=args.get('pergunta',''),analise=analysis,instante=time.time()))
                    data['conferencias_visuais']=data['conferencias_visuais'][-30:]
                    save(folder/'session.json',data)
                return dict(ok=True,analise=analysis)
            if operation == 'aplicar': return apply(folder,data)
            if operation == 'publicar':
                if not data.get('aplicacao') or data['estado']=='desfeito': raise ValueError('Aplique e teste antes de publicar.')
                if Path(data['projeto'])!=root_source() or os.getenv('EMILY_PROGRAMACAO_PREVIA')=='1': raise ValueError('Projeto externo ou prévia não é publicado como atualização da Emily.')
                if data.get('publicacao'):
                    previous=status(folder,data,data['publicacao'])
                    if previous['estado'] in {'iniciando','executando','concluido'}: return previous
                journal=json.loads((folder/'apply-journal.json').read_text())
                if any((digest(Path(i['path']).read_bytes()) if Path(i['path']).exists() else None)!=i['after'] for i in journal): raise ValueError('Código mudou após aplicação; revalide antes de publicar.')
                argv=[python(),str(Path(__file__).with_name('programacao_deploy.py')),str(folder/'session.json')]
                publication=job_start(folder,data,shlex.join(argv) if os.name=='posix' else subprocess.list2cmdline(argv),'publicacao')
                data['publicacao']=publication['trabalho'];data['estado']='publicando';save(folder/'session.json',data)
                return publication
            if operation == 'desfazer':
                if data.get('publicacao') and status(folder,data,data['publicacao'])['estado'] in {'iniciando','executando'}: raise ValueError('Espere a publicação terminar antes de restaurar.')
                journal=json.loads((folder/'apply-journal.json').read_text())
                for item in journal:
                    path=Path(item['path'])
                    if (digest(path.read_bytes()) if path.exists() else None)!=item['after']: raise ValueError('Arquivo alterado depois da aplicação; não sobrescrevi: '+str(path))
                for item in journal:
                    path=Path(item['path'])
                    if item['before'] is None: path.unlink(missing_ok=True)
                    else: path.write_bytes((folder/'applied-backup'/str(item['before'])).read_bytes())
                data['estado']='desfeito';event(folder,data,'Aplicação desfeita preservando outras mudanças.','codigo')
                return dict(ok=True,mensagem='Arquivos restaurados. Versões publicadas precisam de nova publicação para reverter.')
            raise ValueError('Operação não disponível.')
        except Exception as exc:
            return dict(ok=False,mensagem=str(exc),erro=type(exc).__name__,operacao=operation,arquivo=args.get('arquivo'),sessao=args.get('sessao'),diagnostico=getattr(exc,'diagnostic',{}),original_alterado=False if operation in {'comparar','atualizar','resolver','previa'} else None)


S={'type':'string'}
I={'type':'integer'}
DEFINITIONS = [
 ('previa','Abre interface web da cópia em URL local, sem aplicar nem conectar ao backend real (dados de amostra). Captura screenshots controlados dessa própria prévia para ver_imagem; tela indica destino da navegação e largura/altura permitem conferir responsividade. Use cancelar pelo trabalho antes de aplicar. Para aplicativo real Android use android/capturar.',{'sessao':S,'operacao':{'type':'string','enum':['abrir','capturar']},'tela':S,'largura':I,'altura':I},['sessao','operacao']),
 ('comparar','Compara base, cópia da Emily e original atual. Mostra conflitos e hashes para resolver sem perder trabalho. Informe arquivo para ler as três versões.',{'sessao':S,'arquivo':S},['sessao']),
 ('atualizar','Atualiza a cópia com mudanças recentes do original. Mescla trechos independentes; preserva conflitos sobrepostos e salva backup. Nunca altera o original. Aguarde testes/cancele a prévia antes. Rode testes novamente.',{'sessao':S},['sessao']),
 ('resolver','Resolve um conflito SOMENTE na cópia após comparar. Hashes sha_original/sha_copia impedem sobrescrever alterações posteriores (ausente para arquivo inexistente). Manter cópia, usar original ou mesclar com conteúdo completo. Rode testes novamente antes de aplicar.',{'sessao':S,'arquivo':S,'escolha':{'type':'string','enum':['manter_copia','usar_original','mesclar']},'sha_original':S,'sha_copia':S,'conteudo':S},['sessao','arquivo','escolha','sha_original','sha_copia']),
 ('publicar','Retoma uma publicação automática que falhou, mantendo aplicação/testes verificados. Não repete publicação já concluída nem publica projetos externos. Consulte status pelo trabalho.',{'sessao':S},['sessao']),
 ('android','Compila APK da cópia e permite testar pelo USB real: dispositivos, compilar, instalar preservando assinatura/dados, abrir, captura, hierarquia, logs e interação. Não usa force-stop/uninstall. Compilar é obrigatório antes de aplicar alterações nativas.',{'sessao':S,'operacao':{'type':'string','enum':['dispositivos','compilar','instalar','abrir','capturar','hierarquia','logs','tocar','arrastar','tecla']},'serial':S,'x':I,'y':I,'x2':I,'y2':I,'tecla':S},['sessao','operacao']),
 ('ver_imagem','Analisa uma captura da sessão pelo modelo de visão para validar UI. Use arquivo retornado por android/capturar.',{'sessao':S,'arquivo':S,'pergunta':S},['sessao','arquivo','pergunta']),
 ('iniciar','Cria ambiente persistente para programar a Emily ou outro projeto. Vazio em projeto usa a fonte da Emily. Retorna sessão/pasta. Leia instruções, combine ferramentas e teste antes de aplicar.',{'objetivo':S,'projeto':S},['objetivo']),
 ('listar','Recupera sessões de programação e rascunhos após reinício.',{},[]),
 ('ambiente','Inspeciona o workspace sem executar testes nem instalar: pasta de execução, Python/pacotes, Node/npm, navegadores e prévia. Consulte antes de testar; não invente caminhos ou portas. Finalidade teste registra validação; comando não valida para aplicar.',{'sessao':S},['sessao']),
 ('arquivos','Lista fontes e testes da cópia de trabalho.',{'sessao':S},['sessao']),
 ('ler','Lê linhas do código preparado.',{'sessao':S,'arquivo':S,'inicio':I,'fim':I},['sessao','arquivo']),
 ('buscar','Busca texto literal no código e testes.',{'sessao':S,'texto':S},['sessao','texto']),
 ('editar','Substitui trecho exato único na cópia; não muda o programa ativo.',{'sessao':S,'arquivo':S,'buscar':S,'substituir':S},['sessao','arquivo','buscar','substituir']),
 ('criar','Cria novo arquivo de código/teste na cópia.',{'sessao':S,'arquivo':S,'conteudo':S},['sessao','arquivo','conteudo']),
 ('executar','Executa teste, comando ou servidor de prévia na cópia. Sobrevive a reinícios. Consulte status pelo trabalho; nunca repita execução pendente. Para teste funcional use finalidade=teste. USB/navegador podem ser usados pelos comandos e ferramentas existentes.',{'sessao':S,'comando':S,'finalidade':{'type':'string','enum':['teste','comando','previa']},'reexecutar':{'type':'boolean','description':'Repete teste aprovado na mesma revisão somente se há motivo concreto (ambiente/dados mudaram ou o usuário pediu repetir).'}},['sessao','comando','finalidade']),
 ('status','Consulta progresso, saída/código de saída real ou resumo da sessão.',{'sessao':S,'trabalho':S,'aguardar_segundos':I},['sessao']),
 ('cancelar','Encerra um processo de prévia/teste específico, sem interromper outros.',{'sessao':S,'trabalho':S},['sessao','trabalho']),
 ('diff','Confere alterações preparadas antes de aplicar.',{'sessao':S},['sessao']),
 ('aplicar','Aplica SOMENTE ao projeto original desta sessão após teste funcional na revisão atual, com backup e proteção de conflitos. Projetos de terceiros/testes NÃO alteram instalações da Emily e NÃO publicam nada. Somente se o projeto for a própria fonte da Emily atualiza suas instalações e inicia publicação automática; consulte status. Não reinicia a conversa.',{'sessao':S},['sessao']),
 ('desfazer','Restaura aplicação com backup; recusa sobrescrever mudanças posteriores.',{'sessao':S},['sessao']),
 ('comentar','Envia comentário natural de progresso no chat. Descreva achados, decisão ou próximo passo, sem anunciar sucesso sem evidência.',{'sessao':S,'texto':S,'categoria':{'type':'string','enum':['codigo','terminal','testes','web','tela','celular','pesquisa']}},['sessao','texto','categoria']),
]
