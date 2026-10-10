"""Terminal remoto autenticado: trabalhos idempotentes, saída limitada e confirmação."""
import os
import select
import codecs
import secrets
import signal
import subprocess
import threading
import time
import shlex
from pathlib import Path

import terminal as politica


class TerminalRemoto:
    def __init__(self, home):
        self.home = Path(home)
        self.lock = threading.RLock()
        self.jobs = {}
        self.requests = {}
        self.confirmations = {}

    @staticmethod
    def erro(message):
        return {"ok": False, "mensagem": message}

    def _exclusao_pessoal(self, command, cwd):
        """Dispensa só rm/unlink/rmdir literais em dados pessoais, nunca scripts ou proteções."""
        if any(c in command for c in '\n;&|<>`$*?[]{}'):
            return False
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if not parts or parts[0] not in {'rm', '/bin/rm', '/usr/bin/rm', 'unlink', '/usr/bin/unlink', 'rmdir', '/usr/bin/rmdir'}:
            return False
        targets=[]; options=True
        for part in parts[1:]:
            if options and part=='--':
                options=False;continue
            if options and part.startswith('-'):
                if part.startswith('--') or not set(part[1:]) <= set('rfRidvP'):
                    return False
                continue
            targets.append(part)
        if not targets:
            return False
        for target in targets:
            path=Path(target).expanduser()
            path=(cwd/path if not path.is_absolute() else path).resolve()
            try:
                relative=path.relative_to(self.home)
            except ValueError:
                return False
            if path==self.home or not relative.parts:
                return False
            # Inclui credenciais, inicialização da sessão e bancos/configurações das aplicações.
            if any(p.startswith('.') and p not in {'.cache'} for p in relative.parts):
                return False
            if relative.parts[:2] in {('.local','share'),('.local','bin')}:
                return False
            if any(p.lower().endswith(('.pem','.key','.keystore','.p12','.pfx')) for p in relative.parts):
                return False
        return True

    def iniciar(self, args, turno, *, confirmado=None, irrestrito=False):
        command = args.get("comando", "")
        key = args.get("request_id", "")
        if not isinstance(command, str) or not command.strip() or len(command) > 16000 or '\0' in command:
            return self.erro("Comando inválido.")
        if not isinstance(key, str) or not 8 <= len(key) <= 100:
            return self.erro("request_id obrigatório para evitar execução duplicada.")
        try:
            cwd = Path(args.get("pasta") or self.home).expanduser().resolve(strict=True)
            if not cwd.is_dir():
                return self.erro("A pasta de trabalho não existe.")
        except (OSError, TypeError):
            return self.erro("A pasta de trabalho não existe.")
        sensitive = args.get('sensivel', False)
        if not isinstance(sensitive, bool):
            return self.erro('sensivel precisa ser booleano.')
        signature = (command, str(cwd), sensitive, turno)
        with self.lock:
            now = time.monotonic()
            for ident, job in list(self.jobs.items()):
                if job['estado'] != 'executando' and now - job['created'] > 3600:
                    self.jobs.pop(ident)
            self.requests = {k: v for k, v in self.requests.items() if v[1] in self.jobs or v[1] in self.confirmations}
            self.confirmations = {k: v for k, v in self.confirmations.items() if v['expires'] > now}
            if key in self.requests:
                previous, ident = self.requests[key]
                if previous != signature:
                    return self.erro("Este identificador já pertence a outro comando/turno.")
                if ident in self.jobs:
                    return self.status(ident)
                if ident in self.confirmations:
                    return self._pedido(ident)
            level = politica.classificar(command)
            if level == politica.BLOQUEADO:
                return self.erro("A política do PC bloqueou uma operação irreversível. Não executada.")
            try:
                parsed=shlex.split(command)
            except ValueError:
                parsed=[]
            if parsed and Path(parsed[0]).name in {'rm','unlink','rmdir'}:
                level=politica.CONFIRMAR
            pessoal_autorizado = irrestrito is True and self._exclusao_pessoal(command,cwd)
            if (level == politica.CONFIRMAR or sensitive) and confirmado is None and not pessoal_autorizado:
                if len(self.confirmations) >= 128:
                    return self.erro('Há confirmações demais pendentes; aguarde expirarem.')
                ident = secrets.token_urlsafe(24)
                self.confirmations[ident] = dict(args=dict(args), signature=signature, expires=now+90, turno=turno)
                self.requests[key] = (signature, ident)
                return self._pedido(ident)
            if sum(j['estado'] == 'executando' for j in self.jobs.values()) >= 4 or len(self.jobs) >= 128:
                return self.erro("Há trabalhos demais no terminal. Consulte ou cancele os pendentes.")
            ident = secrets.token_urlsafe(24)
            job = dict(job_id=ident, estado='executando', codigo_saida=None, stdout='', stderr='', saida_truncada=False,
                       created=now, process=None, cancel=False, cwd=str(cwd))
            self.jobs[ident] = job
            self.requests[key] = (signature, ident)
            thread = threading.Thread(target=self._run, args=(job, command, cwd), daemon=True, name='pc-terminal')
            thread.start()
        # Comandos curtos já retornam seu resultado; os longos continuam sem ocupar a conexão.
        thread.join(0.5)
        return self.status(ident)

    def _pedido(self, ident):
        pending = self.confirmations[ident]
        return dict(ok=False, requer_confirmacao=True, confirmation_id=ident,
                    confirmacao_expira_em_segundos=90, comando=pending['args']['comando'],
                    mensagem="Este comando altera algo sensível. Explique o efeito e peça confirmação em uma nova mensagem.")

    def confirmar(self, args, turno):
        ident = args.get('confirmation_id', '')
        with self.lock:
            # Uma retransmissão da confirmação devolve o mesmo trabalho, sem repetir o comando.
            request_key = 'confirm:' + str(ident)
            previous = self.requests.get(request_key)
            if previous:
                return self.status(previous[1]) if previous[0][-1] == turno else self.erro('Confirmação já utilizada.')
            pending = self.confirmations.get(ident)
            if not pending or pending['expires'] <= time.monotonic():
                return self.erro('Confirmação inexistente ou expirada.')
            if not turno or pending['turno'] == turno:
                return self.erro('É necessária uma nova resposta do usuário.')
            self.confirmations.pop(ident)
            if args.get('confirmar') is not True:
                return dict(ok=True, estado='cancelado', mensagem='Comando cancelado sem execução.')
            original = dict(pending['args'], request_id=request_key)
            return self.iniciar(original, turno, confirmado=ident)

    def status(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if not job:
                return self.erro('Trabalho de terminal não encontrado.')
            state = job['estado']
            return {**{k: job[k] for k in ('job_id','estado','codigo_saida','stdout','stderr','saida_truncada')},
                    'ok': state in ('executando','concluido'),
                    'concluido': state != 'executando',
                    'mensagem': 'Comando ainda executando; consulte terminal_status. Não anuncie conclusão.' if state == 'executando'
                    else ('Comando concluído com código de saída zero; verifique a saída para confirmar o efeito solicitado.' if state == 'concluido'
                          else 'Comando cancelado.' if state == 'cancelado' else 'Comando falhou; confira a saída e o código retornado.')}

    def cancelar(self, ident):
        with self.lock:
            job = self.jobs.get(ident)
            if not job:
                return self.erro('Trabalho de terminal não encontrado.')
            job['cancel'] = True
            process = job['process']
            if process and process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        result = self.status(ident)
        result['ok'] = True  # O pedido de cancelamento foi aceito; resultado do comando é separado.
        if result['estado'] == 'executando':
            result['mensagem'] = 'Cancelamento solicitado; consulte o estado para confirmar a parada.'
        return result

    def _read(self, job, stream, field):
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        ended_at = None
        try:
            while True:
                process = job['process']
                if process is not None and process.poll() is not None:
                    ended_at = ended_at or time.monotonic()
                    if time.monotonic() - ended_at > 1:
                        break
                ready, _, _ = select.select([stream], [], [], 0.1)
                if not ready:
                    continue
                raw = os.read(stream.fileno(), 4096)
                chunk = decoder.decode(raw, final=not raw)
                with self.lock:
                    room = max(0, 16000 - len(job[field]))
                    job[field] += chunk[:room]
                    job['saida_truncada'] |= len(chunk) > room
                if not raw:
                    break
        finally:
            stream.close()

    def _run(self, job, command, cwd):
        try:
            env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
            process = subprocess.Popen(['/bin/bash', '-c', command], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            with self.lock:
                job['process'] = process
            readers = [threading.Thread(target=self._read, args=(job, stream, name), daemon=True)
                       for stream, name in ((process.stdout, 'stdout'), (process.stderr, 'stderr'))]
            for reader in readers:
                reader.start()
            cancel_at = None
            while process.poll() is None:
                if job['cancel'] or time.monotonic() - job['created'] > 3600:
                    job['cancel'] = True
                    if cancel_at is None:
                        cancel_at = time.monotonic()
                    try:
                        os.killpg(process.pid, signal.SIGKILL if time.monotonic()-cancel_at > 2 else signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                time.sleep(0.05)
            # Descendentes que conservam o pipe aberto não bloqueiam o resultado do trabalho.
            for reader in readers:
                reader.join(1.5)
            with self.lock:
                job['codigo_saida'] = process.returncode
                job['estado'] = 'cancelado' if job['cancel'] else 'concluido' if process.returncode == 0 else 'falhou'
        except Exception as exc:
            with self.lock:
                job['estado'] = 'falhou'
                job['stderr'] = type(exc).__name__
