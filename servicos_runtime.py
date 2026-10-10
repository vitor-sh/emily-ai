"""Ambiente e processos auxiliares usados pela Emily no desktop.

Atalhos .desktop não carregam .bashrc/.profile. Por isso ferramentas instaladas
em ~/.local/bin, ~/bin ou pelo Snap podem existir no Konsole e "sumir" quando a
Emily abre pelo menu. Este módulo normaliza o PATH e inicializa o ngrok com
diagnóstico, sem bloquear o restante do boot.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, Optional

_lock = threading.RLock()
_processo_ngrok: Optional[subprocess.Popen] = None
_estado_ngrok: Dict[str, object] = {
    "estado": "parado", "url": "", "erro": "", "executavel": "", "pid": 0,
}


def caminhos_executaveis() -> list[str]:
    home = Path.home()
    return [
        str(home / ".local" / "bin"), str(home / "bin"),
        "/usr/local/bin", "/usr/bin", "/bin",
        "/var/lib/snapd/snap/bin", "/snap/bin",
        "/usr/local/sbin", "/usr/sbin", "/sbin",
    ]


def preparar_ambiente(ambiente: Optional[dict] = None) -> dict:
    """Completa PATH sem apagar entradas personalizadas já existentes."""
    alvo = os.environ if ambiente is None else ambiente
    atuais = [p for p in str(alvo.get("PATH", "")).split(os.pathsep) if p]
    vistos = set(atuais)
    for pasta in caminhos_executaveis():
        if pasta not in vistos and os.path.isdir(pasta):
            atuais.append(pasta)
            vistos.add(pasta)
    alvo["PATH"] = os.pathsep.join(atuais)
    alvo.setdefault("HOME", str(Path.home()))
    return alvo


def encontrar_executavel(nome: str, variavel: str = "") -> Optional[str]:
    """Resolve executável por env, PATH normalizado e locais desktop comuns."""
    preparar_ambiente()
    candidatos = []
    if variavel and os.environ.get(variavel):
        candidatos.append(os.path.expandvars(os.path.expanduser(os.environ[variavel])))
    achado = shutil.which(nome)
    if achado:
        candidatos.append(achado)
    candidatos.extend(str(Path(p) / nome) for p in caminhos_executaveis())
    for candidato in candidatos:
        try:
            caminho = Path(candidato).expanduser()
            if caminho.is_file() and os.access(caminho, os.X_OK):
                # Não resolve o último symlink: atalhos do Snap dependem do
                # argv[0] ser "ngrok". Resolver .../snap/bin/ngrok para
                # /usr/bin/snap faria o despacho perder o nome do aplicativo.
                return str(caminho.absolute())
        except OSError:
            continue
    return None


def _alterar_estado(**dados) -> None:
    with _lock:
        _estado_ngrok.update(dados)


def estado_ngrok() -> dict:
    with _lock:
        estado = dict(_estado_ngrok)
        processo = _processo_ngrok
    if processo is not None and processo.poll() is not None and estado["estado"] == "online":
        estado.update(estado="erro", url="",
                      erro=f"ngrok encerrou com código {processo.returncode}")
        _alterar_estado(estado=estado["estado"], url="", erro=estado["erro"])
    try:
        from emily_remote import ambiente_fedora
        if ambiente_fedora() and estado["estado"] == "online" and not _url_publica(5000):
            estado.update(estado="erro", url="", erro="túnel interno desconectado")
            _alterar_estado(estado="erro", url="", erro=estado["erro"])
    except Exception:
        pass
    return estado


def _url_publica(porta: Optional[int] = None) -> str:
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resp:
            dados = json.loads(resp.read().decode("utf-8", errors="replace"))
        tuneis = dados.get("tunnels") or []
        if porta is not None:
            sufixos = (f":{porta}", f"/{porta}")
            tuneis = [t for t in tuneis if str(
                (t.get("config") or {}).get("addr") or "").rstrip("/").endswith(sufixos)]
        https = next((t for t in tuneis if t.get("proto") == "https"), None)
        escolhido = https or (tuneis[0] if tuneis else {})
        encontrado = str(escolhido.get("public_url") or "")
        if encontrado == "https://default.internal":
            from gateway_endpoint import obter
            return obter()["url"]
        return encontrado
    except Exception:
        return ""


def _porta_pronta(porta: int, teto: float = 12.0) -> bool:
    fim = time.monotonic() + teto
    while time.monotonic() < fim:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=.4):
                return True
        except OSError:
            time.sleep(.25)
    return False


def _ler_saida(processo: subprocess.Popen) -> None:
    try:
        for linha in processo.stdout or ():
            texto = linha.rstrip()
            if texto:
                print(f"[NGROK] {texto}")
    except Exception as e:
        print(f"[NGROK] não consegui acompanhar a saída: {e}")


def _subir_ngrok(porta: int) -> None:
    global _processo_ngrok
    existente = _url_publica(porta)
    if existente:
        with _lock:
            _processo_ngrok = None  # túnel externo; não vigiar processo antigo
        _alterar_estado(estado="online", url=existente, erro="")
        print(f"[NGROK] reutilizando túnel já ativo: {existente}")
        return

    from emily_remote import ambiente_fedora
    if ambiente_fedora():
        try:
            subprocess.run(["systemctl", "--user", "start", "emily-ngrok.service"],
                           check=True, timeout=8)
            for _ in range(32):
                publico = _url_publica(porta)
                if publico:
                    _alterar_estado(estado="online", url=publico, erro="")
                    print(f"[NGROK] URL pública: {publico}")
                    return
                time.sleep(.25)
            raise RuntimeError("serviço iniciou sem publicar o endpoint")
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
                RuntimeError) as exc:
            _alterar_estado(estado="erro", erro=str(exc))
            print(f"[NGROK] serviço Fedora indisponível: {exc}")
            return

    executavel = encontrar_executavel("ngrok", "EMILY_NGROK")
    if not executavel:
        erro = ("ngrok não encontrado. O atalho usa PATH não interativo; "
                "instale-o ou defina EMILY_NGROK com o caminho completo.")
        _alterar_estado(estado="erro", erro=erro)
        print(f"[NGROK] {erro}")
        return
    _alterar_estado(executavel=executavel)

    if not _porta_pronta(porta):
        erro = f"servidor local não respondeu na porta {porta}; túnel não iniciado"
        _alterar_estado(estado="erro", erro=erro)
        print(f"[NGROK] {erro}")
        return

    ambiente = preparar_ambiente(dict(os.environ))
    try:
        opcoes = {
            "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL, "text": True, "encoding": "utf-8",
            "errors": "replace", "bufsize": 1, "env": ambiente,
        }
        if os.name == "nt":
            opcoes["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            opcoes["start_new_session"] = True
        comando = [executavel, "http", str(porta), "--log", "stdout",
                   "--log-format", "logfmt", "--log-level", "info"]
        processo = subprocess.Popen(comando, **opcoes)
        with _lock:
            _processo_ngrok = processo
        _alterar_estado(estado="iniciando", pid=processo.pid, erro="")
        print(f"[NGROK] iniciado: {executavel} http {porta} (pid {processo.pid})")
        threading.Thread(target=_ler_saida, args=(processo,), daemon=True,
                         name="ngrok-saida").start()
    except Exception as e:
        _alterar_estado(estado="erro", erro=str(e))
        print(f"[NGROK] falha ao iniciar {executavel}: {type(e).__name__}: {e}")
        return

    for _ in range(40):
        if processo.poll() is not None:
            erro = f"processo encerrou com código {processo.returncode}"
            _alterar_estado(estado="erro", erro=erro)
            print(f"[NGROK] {erro}; veja as linhas anteriores do log")
            return
        url = _url_publica(porta)
        if url:
            _alterar_estado(estado="online", url=url, erro="")
            print(f"[NGROK] URL pública: {url}")
            return
        time.sleep(.5)
    erro = "processo está rodando, mas a API local não publicou uma URL em 20s"
    _alterar_estado(estado="erro", erro=erro)
    print(f"[NGROK] {erro}")


def iniciar_ngrok(porta: int = 5000) -> bool:
    """Agenda ngrok em background; nunca segura a inicialização da Emily."""
    global _processo_ngrok
    from gateway_endpoint import modo_oracle
    if modo_oracle(): return False
    with _lock:
        if (_estado_ngrok["estado"] in ("aguardando", "iniciando", "online")
                and (_processo_ngrok is None or _processo_ngrok.poll() is None)):
            return False
        _estado_ngrok.update(estado="aguardando", url="", erro="", pid=0)
    threading.Thread(target=_subir_ngrok, args=(porta,), daemon=True,
                     name="ngrok-inicializador").start()
    return True


def reiniciar_ngrok(porta: int = 5000) -> bool:
    """Reinicia somente o processo criado pela Emily; não mata ngrok externo."""
    global _processo_ngrok
    from gateway_endpoint import modo_oracle
    if modo_oracle(): return False
    from emily_remote import ambiente_fedora
    if ambiente_fedora():
        try:
            subprocess.run(["systemctl", "--user", "restart", "emily-ngrok.service"],
                           check=True, timeout=10)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
        _alterar_estado(estado="parado", url="", erro="", pid=0)
        return iniciar_ngrok(porta)
    with _lock:
        processo = _processo_ngrok
        _processo_ngrok = None
        _estado_ngrok.update(estado="parado", url="", erro="", pid=0)
    if processo is not None and processo.poll() is None:
        try:
            processo.terminate()
            processo.wait(timeout=3)
        except subprocess.TimeoutExpired:
            processo.kill()
        except OSError:
            pass
    print("[NGROK] nova tentativa solicitada pela interface")
    return iniciar_ngrok(porta)
