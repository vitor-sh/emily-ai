"""Inventário e desinstalação remota de aplicativos Fedora; sem shell e com alvos reais."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import threading
import time
import unicodedata

ADMIN_HELPER = '/usr/local/libexec/emily-app-uninstall'
PACKAGE_LOCK = threading.Lock()


class RemovalError(RuntimeError):
    def __init__(self, message, code='execucao_recusada'):
        super().__init__(message)
        self.code = code


def admin_command(kind, target, preview=False):
    # O gateway tem NoNewPrivileges=true. O gerenciador systemd do usuário
    # inicia um worker separado; apenas o helper root fixo passa pelo polkit.
    # Não mudar a proteção do gateway nem liberar Python/shell como root.
    command = ['/usr/bin/systemd-run', '--user', '--wait', '--pipe', '--collect',
               '--quiet', '--service-type=exec', '--property=NoNewPrivileges=false',
               '--property=RuntimeMaxSec=600', '--property=TimeoutStopSec=15',
               '/usr/bin/pkexec', '--disable-internal-agent', ADMIN_HELPER, kind, target]
    if preview:
        command.append('--preview')
    return command


def normalize(value):
    value = unicodedata.normalize('NFKD', value)
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in value if not unicodedata.combining(c)).lower()).split())


def output(command, timeout=15):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        # O helper retorna JSON também na falha; avisos do DNF no stderr não
        # devem esconder o diagnóstico da transação.
        try:
            structured = json.loads(result.stdout)
            message = structured.get('mensagem') if isinstance(structured,dict) else None
        except (ValueError,TypeError):
            message = None
        message = message or result.stderr or result.stdout or 'Comando recusado'
        code = 'execucao_recusada'
        if 'pkexec must be setuid root' in message:
            code = 'executor_sem_elevacao'
        elif any(word in message.lower() for word in ('not authorized','not authorised','authorization failed')):
            code = 'permissao_administrativa'
        elif 'failed to connect to bus' in message.lower():
            code = 'gerenciador_usuario_indisponivel'
        raise RemovalError(message[-1600:],code)
    return result.stdout


class PCApps:
    def __init__(self, home=None, runner=output):
        self.home = Path(home or Path.home())
        self.run = runner
        self.lock = threading.RLock()
        self.jobs = {}
        self.events = {}
        self.requests = {}
        self.confirmations = {}
        self.cache = None

    @staticmethod
    def error(message, **data):
        return dict(ok=False, mensagem=message, **data)

    def inventory(self, refresh=False):
        with self.lock:
            if not refresh and self.cache and time.monotonic() - self.cache[0] < 20:
                return self.cache[1]
        apps = []
        def add(kind, target, name, **extra):
            ident = kind + ':' + target
            apps.append(dict(id=ident, nome=name, tipo=kind, alvo=target, **extra))
        warnings = []
        try:
            for line in self.run(['flatpak', 'list', '--app', '--columns=application,name,installation']).splitlines():
                parts = line.split('\t')
                if len(parts) == 3 and parts[2] in ('user','system'):
                    add('flatpak-' + parts[2], parts[0], parts[1])
        except (OSError, RuntimeError, subprocess.SubprocessError):
            warnings.append('Não consegui consultar os Flatpaks.')
        desktops = sorted(Path('/usr/share/applications').glob('*.desktop'))
        try:
            import rpm
            database=rpm.TransactionSet()
            packages={}
            for desktop in desktops:
                owners=list(database.dbMatch('basenames',str(desktop)))
                if not owners:continue
                name=re.search(r'^Name=(.+)$',desktop.read_text(errors='replace'),re.M)
                if name:
                    for header in owners:packages.setdefault(header['name'],[]).append(name.group(1))
            for package,names in sorted(packages.items()):
                add('rpm', package, names[0], aliases=[*names, package.replace('-unofficial','').replace('-',' ')])
        except (ImportError, OSError, RuntimeError, subprocess.SubprocessError):
            warnings.append('Não consegui consultar os aplicativos RPM.')
        # Manifestos Steam de todas as bibliotecas; runtimes compartilhados ficam fora.
        roots = {self.home / '.local/share/Steam', self.home / '.steam/steam'}
        for root in list(roots):
            config = root / 'steamapps/libraryfolders.vdf'
            if config.is_file():
                roots.update(Path(p.replace('\\\\','\\')) for p in re.findall(r'"path"\s*"([^"]+)"', config.read_text(errors='replace')))
        seen = set()
        for root in sorted(roots):
            steamapps = (root / 'steamapps').resolve()
            if steamapps in seen:
                continue
            seen.add(steamapps)
            for manifest in steamapps.glob('appmanifest_*.acf'):
                try:
                    data = dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"', manifest.read_text(errors='replace')))
                except OSError:
                    continue
                appid, name = data.get('appid',''), data.get('name','')
                folder = data.get('installdir','')
                if not appid.isdigit() or manifest.name != f'appmanifest_{appid}.acf' or not name:
                    continue
                if name.lower().startswith(('steam', 'proton')) or not folder or Path(folder).name != folder or folder in ('.','..'):
                    continue
                game = steamapps / 'common' / folder
                if not game.is_dir() or game.is_symlink() or game.resolve().parent != (steamapps/'common').resolve():
                    continue
                library_id = hashlib.sha256(str(steamapps).encode()).hexdigest()[:10]
                add('steam', appid + ':' + library_id, name, appid=appid, manifesto=str(manifest), pasta=str(game), biblioteca=str(root))
        # AppImages pessoais com lançador explícito: nunca adivinhar diretórios de aplicativos.
        for desktop in (self.home / '.local/share/applications').glob('*.desktop'):
            try:
                text=desktop.read_text(errors='replace')
                line=re.search(r'^Exec=(.+)$',text,re.M);name=re.search(r'^Name=(.+)$',text,re.M)
                command=shlex.split(line.group(1)) if line else []
                path=Path(command[0]).expanduser() if command else None
                if path and path.is_absolute() and path.suffix.lower()=='.appimage' and path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.home.resolve()):
                    add('appimage',str(path.resolve()),name.group(1) if name else path.stem, lancador=str(desktop))
            except (OSError,ValueError):
                continue
        self.inventory_warnings = warnings
        unique = {app['id']:app for app in apps}
        value = sorted(unique.values(),key=lambda a:a['nome'].lower())
        with self.lock:
            self.cache = (time.monotonic(), value)
        return value

    @staticmethod
    def public(app):
        return {k:app[k] for k in ('id','nome','tipo','biblioteca') if k in app}

    def find(self, name='', ident='', refresh=False):
        apps = self.inventory(refresh)
        if ident:
            exact = [a for a in apps if a['id']==ident]
        else:
            query=normalize(name)
            exact=[a for a in apps if query and query in [normalize(x) for x in [a['nome'],a['alvo'],*a.get('aliases',[])]]]
        if len(exact)==1:
            return exact[0], None
        if len(exact)>1:
            return None, self.error('Há mais de uma instalação com esse nome. Escolha o identificador/localização.', precisa_escolha=True, candidatos=[self.public(a) for a in exact])
        query=normalize(name)
        ranked=sorted(apps,key=lambda a:difflib.SequenceMatcher(None,query,normalize(a['nome'])).ratio(),reverse=True)
        candidates=[a for a in ranked if query and (query in normalize(a['nome']) or difflib.SequenceMatcher(None,query,normalize(a['nome'])).ratio()>=.35)][:6]
        return None,self.error('Não encontrei esse aplicativo instalado. Não removi nada. Confira os nomes parecidos.', precisa_escolha=True, candidatos=[self.public(a) for a in candidates])

    def list(self,args):
        name=args.get('nome','')
        if not isinstance(name,str) or len(name)>200:
            return self.error('Nome inválido.')
        if name:
            app,error=self.find(name)
            return error or dict(ok=True,mensagem='Aplicativo encontrado.',aplicativo=self.public(app))
        apps=self.inventory()
        return dict(ok=True,mensagem='Aplicativos e jogos instalados.',aplicativos=[self.public(a) for a in apps],avisos=getattr(self,'inventory_warnings',[]))

    def remove(self,args,turn,unrestricted=False):
        name,ident,key=args.get('nome',''),args.get('id',''),args.get('request_id','')
        if not all(isinstance(x,str) for x in (name,ident,key)) or len(name)>200 or len(ident)>1000 or not 8<=len(key)<=100:
            return self.error('Nome, identificador ou request_id inválido.')
        signature=(name,ident,turn)
        with self.lock:
            self.confirmations={k:v for k,v in self.confirmations.items() if v["expira"]>time.monotonic()}
            for jid,job in list(self.jobs.items()):
                if job['estado']!='executando' and time.monotonic()-job['criado']>3600:
                    self.jobs.pop(jid)
                    self.events.pop(jid,None)
            self.requests={k:v for k,v in self.requests.items() if v[1] in self.jobs or v[1] in self.confirmations}
            if key in self.requests:
                previous,jid=self.requests[key]
                if previous!=signature:
                    return self.error('request_id já usado por outro pedido.')
                if jid in self.jobs:
                    return self.status(jid)
                return self.confirmations[jid]['resposta']
            app,error=self.find(name,ident)
            if error:
                return error
            if len(self.jobs)>=128 or len(self.confirmations)>=128:
                return self.error("Há trabalhos demais; aguarde os anteriores terminarem/expirarem.")
            if not unrestricted:
                cid=secrets.token_urlsafe(24)
                result=dict(ok=False,requer_confirmacao=True,confirmation_id=cid,aplicativo=self.public(app),mensagem=f"Confirma desinstalar {app['nome']}? Responda naturalmente em uma nova mensagem.")
                self.confirmations[cid]=dict(app=app,turn=turn,expira=time.monotonic()+90,resposta=result)
                self.requests[key]=(signature,cid)
                return result
            return self._start(app,key,signature)

    def confirm(self,args,turn):
        cid=args.get('confirmation_id','')
        if not isinstance(cid,str):return self.error('Confirmação inválida.')
        with self.lock:
            key='confirm:'+cid
            if key in self.requests:
                previous,jid=self.requests[key]
                return self.status(jid) if previous[-1]==turn else self.error('Confirmação já utilizada.')
            pending=self.confirmations.get(cid)
            if not pending or pending['expira']<time.monotonic() or pending['turn']==turn:
                return self.error('É necessária uma nova resposta para uma confirmação válida.')
            if not isinstance(args.get('confirmar'),bool):
                return self.error('Informe confirmar=true ou false; a confirmação continua pendente.')
            if args.get('confirmar') is not True:
                self.confirmations.pop(cid,None)
                return dict(ok=True,mensagem='Desinstalação cancelada.',estado='cancelado')
            app,error=self.find(ident=pending['app']['id'],refresh=True)
            if error:return error
            self.confirmations.pop(cid,None)
            return self._start(app,key,('',app['id'],turn))

    def _start(self,app,key,signature):
        for jid,job in self.jobs.items():
            if job['estado']=='executando' and job['aplicativo']['id']==app['id']:
                self.requests[key]=(signature,jid)
                return self.status(jid)
        if sum(j['estado']=='executando' for j in self.jobs.values())>=2:
            return self.error('Já há duas desinstalações em andamento; acompanhe os trabalhos existentes.')
        jid=secrets.token_urlsafe(24)
        self.jobs[jid]=dict(ok=True,job_id=jid,estado='executando',concluido=False,aplicativo=self.public(app),mensagem=f"Desinstalando {app['nome']}.",criado=time.monotonic())
        self.requests[key]=(signature,jid)
        self.events[jid]=threading.Event()
        threading.Thread(target=self._worker,args=(jid,dict(app)),daemon=True,name='pc-app-uninstall').start()
        return self.status(jid)

    def status(self,jid,wait=0):
        with self.lock:
            event=self.events.get(jid)
        if event and wait:
            event.wait(min(20,max(0,wait)))
        with self.lock:
            job=self.jobs.get(jid)
            return {k:v for k,v in job.items() if k!='criado'} if job else self.error('Trabalho de desinstalação não encontrado.')

    def _worker(self,jid,app):
        try:
            kind,target=app['tipo'],app['alvo']
            if kind in ('rpm','flatpak-system'):
                # Timeout de transação longo só no worker; a chamada do celular já retornou.
                with PACKAGE_LOCK:
                    raw=self.run(admin_command(kind,target),timeout=620)
                result=json.loads(raw)
                if not result.get('ok'):raise RuntimeError(result.get('mensagem','Falha na desinstalação.'))
            elif kind=='flatpak-user':
                with PACKAGE_LOCK:
                    self.run(['flatpak','uninstall','--user','--noninteractive','--',target],timeout=600)
            elif kind=='steam':
                self._remove_steam(app)
            elif kind=='appimage':
                path=Path(target)
                if path.is_symlink() or not path.resolve().is_relative_to(self.home.resolve()):
                    raise RuntimeError('O caminho do AppImage mudou; nada foi removido.')
                path.unlink()
                Path(app['lancador']).unlink(missing_ok=True)
            else:
                raise RuntimeError('Este formato não tem desinstalador integrado.')
            remaining=self.inventory(refresh=True)
            warnings=getattr(self,'inventory_warnings',[])
            if (kind=='rpm' and any('RPM' in w for w in warnings)) or (kind.startswith('flatpak') and any('Flatpak' in w for w in warnings)):
                raise RuntimeError('Não consegui conferir o inventário após a remoção; resultado não confirmado.')
            if any(a['id']==app['id'] for a in remaining):raise RuntimeError('O aplicativo ainda consta instalado após a tentativa; não confirmado.')
            final=dict(ok=True,estado='concluido',concluido=True,mensagem=f"Desinstalei {app['nome']}. Não solicitei apagar configurações ou saves externos à instalação.")
        except Exception as error:
            code = getattr(error,'code','falha_desinstalacao')
            if isinstance(error,subprocess.TimeoutExpired):
                code = 'tempo_esgotado'
            final=dict(ok=False,estado='falhou',concluido=True,codigo_erro=code,
                       mensagem=f"Não consegui desinstalar {app['nome']}: {str(error)[-1800:]}")
        with self.lock:
            self.jobs[jid].update(final)
            self.cache=None
            self.events[jid].set()

    def _stop_steam(self):
        # Não interromper jogos em uso nem remover conteúdo enquanto o Steam altera manifestos.
        steam=[]
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if proc.stat().st_uid!=os.getuid():continue
                env=(proc/'environ').read_bytes().split(b'\0')
                if any(x.startswith(b'SteamAppId=') and x not in (b'SteamAppId=0',b'SteamAppId=') for x in env):
                    raise RuntimeError('Há um jogo Steam em execução. Feche o jogo para concluir a desinstalação.')
                if (proc/'comm').read_text().strip()=='steam':steam.append(proc)
            except (OSError,PermissionError):continue
        if steam:
            self.run(['steam','-shutdown'],timeout=15)
            deadline=time.monotonic()+15
            while any(p.exists() for p in steam) and time.monotonic()<deadline:time.sleep(.2)
            if any(p.exists() for p in steam):raise RuntimeError('Steam não encerrou; nenhum arquivo do jogo foi removido.')
    def _remove_steam(self,app):
        self._stop_steam()
        manifest=Path(app['manifesto']);game=Path(app['pasta'])
        if game.is_symlink() or game.resolve().parent!=(manifest.parent/'common').resolve():
            raise RuntimeError('O diretório do jogo mudou; remoção cancelada.')
        current=dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"',manifest.read_text(errors='replace')))
        if current.get('appid')!=app['appid'] or current.get('installdir')!=game.name:
            raise RuntimeError('O manifesto mudou; consulte os jogos novamente.')
        for other in manifest.parent.glob('appmanifest_*.acf'):
            if other==manifest:continue
            data=dict(re.findall(r'"([^"\n]+)"\s*"([^"\n]*)"',other.read_text(errors='replace')))
            if data.get('installdir')==game.name:
                raise RuntimeError('Esta pasta é compartilhada por outra instalação Steam; nada foi removido.')
        shutil.rmtree(game)
        manifest.unlink()
        # Saves, userdata, compatdata e runtimes compartilhados ficam intactos.
