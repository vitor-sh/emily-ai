"""Endereço público do gateway Fedora, editável pela interface da Emily.

O drop-in do systemd sobrevive à reinstalação da unit principal. Nenhum texto
digitado vira shell: a URL é validada e passada como argumento do ngrok.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import urlopen


CONFIG = Path.home() / ".config/emily/gateway-endpoint.json"
DROP_IN = Path.home() / ".config/systemd/user/emily-ngrok.service.d/endpoint.conf"
NGROK = "/var/lib/snapd/snap/bin/ngrok"
ENDPOINT_INTERNO = "https://default.internal"


def validar_url(valor: str) -> str:
    url = str(valor or "").strip().rstrip("/")
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        porta = parts.port
    except ValueError as exc:
        raise ValueError("URL do ngrok inválida.") from exc
    if (len(url) > 250 or parts.scheme != "https" or not host or
            porta is not None or parts.username or parts.password or
            parts.path or parts.query or parts.fragment or
            not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", host) or
            not host.endswith((".ngrok-free.dev", ".ngrok-free.app", ".ngrok.app"))):
        raise ValueError("Use uma URL HTTPS do ngrok, sem caminho, porta ou parâmetros.")
    return f"https://{host}"


def _gravar_atomico(destino: Path, texto: str, modo: int = 0o600) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(dir=destino.parent, prefix=".endpoint-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            arquivo.write(texto)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.chmod(temporario, modo)
        os.replace(temporario, destino)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def obter() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict): raise ValueError("Configuração inválida")
        if data.get("modo") == "oracle":
            url = data.get("url", "")
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.hostname or parts.path != "/bridge" or parts.query or parts.fragment: raise ValueError("Ponte inválida")
            return {"url": url, "atualizado_em": float(data.get("atualizado_em", 0)), "modo": "oracle"}
        return {"url": validar_url(data.get("url", "")),
                "atualizado_em": float(data.get("atualizado_em", 0))}
    except (OSError, ValueError, TypeError, KeyError):
        return {"url": "", "atualizado_em": 0}


def modo_oracle() -> bool:
    return obter().get("modo") == "oracle"


def _tunel_interno_ativo() -> bool:
    try:
        with urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resposta:
            data = json.load(resposta)
        return any(t.get("public_url", "").rstrip("/") == ENDPOINT_INTERNO
                   for t in data.get("tunnels", []))
    except (OSError, ValueError, TypeError):
        return False


def _rota_publica_ativa(url: str) -> bool:
    try:
        with urlopen(f"{url}/pc/status", timeout=5) as resposta:
            dados = json.load(resposta)
            return isinstance(dados, dict) and "ok" in dados
    except HTTPError as exc:
        if exc.code != 401:
            return False
        try:
            dados = json.load(exc)
            return dados.get("erro") == "token inválido"
        except (ValueError, TypeError):
            return False
    except (OSError, ValueError, TypeError):
        return False


def estado() -> dict:
    data = obter()
    url = data["url"]
    try:
        proc = subprocess.run(["systemctl", "--user", "is-active", "emily-oracle-link.service" if data.get("modo") == "oracle" else "emily-ngrok.service"],
                              capture_output=True, text=True, timeout=3)
        servico = proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        servico = "indisponível"
    chave_firebase = Path.home() / ".config/emily/firebase-service-account.json"
    token_android = Path.home() / ".local/share/emily/android-push-token.json"
    return {"url": url, "atualizado_em": data["atualizado_em"],
            "servico": servico, "tunel_online": servico == "active" if data.get("modo") == "oracle" else bool(url and _tunel_interno_ativo() and _rota_publica_ativa(url)),
            "modo": data.get("modo", "ngrok"),
            "firebase_configurado": chave_firebase.is_file(),
            "celular_registrado": token_android.is_file()}


def _salvar_e_avisar(url: str, mensagem: str) -> dict:
    novo = {"url": url, "atualizado_em": time.time()}
    _gravar_atomico(CONFIG, json.dumps(novo, ensure_ascii=False) + "\n")
    try:
        from emily_gateway_service_push import publicar_endpoint_firebase
        windows = publicar_endpoint_firebase(url, novo["atualizado_em"])
    except Exception as exc:
        windows = f"Windows pendente: {type(exc).__name__}: {exc}"
    try:
        from emily_gateway_service_push import avisar_troca_endpoint
        push = avisar_troca_endpoint(url, novo["atualizado_em"])
    except Exception as exc:  # push opcional não invalida o endpoint já ativo
        push = f"Android remoto pendente: {type(exc).__name__}: {exc}"
    return {"ok": True, "mensagem": mensagem, "push": push,
            "windows": windows, **estado()}


def alterar(url: str) -> dict:
    if modo_oracle(): return {"ok": False, "mensagem": "A conexão Oracle é automática. Use o pareamento por código.", **estado()}
    url = validar_url(url)
    atual = obter()
    if atual["url"] == url and _tunel_interno_ativo() and _rota_publica_ativa(url):
        return _salvar_e_avisar(url, "Endpoint confirmado; endereço reenviado aos dispositivos.")
    dropin = ("[Service]\nExecStart=\n"
              f"ExecStart={NGROK} http 5000 --url {ENDPOINT_INTERNO} "
              "--log stdout --log-format logfmt --log-level info\n")
    _gravar_atomico(DROP_IN, dropin, 0o644)
    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, timeout=10)
        subprocess.run(["systemctl", "--user", "restart", "emily-ngrok.service"],
                       check=True, timeout=10)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "mensagem": f"Não consegui reiniciar o túnel: {type(exc).__name__}",
                **estado()}
    for _ in range(12):
        if _tunel_interno_ativo() and _rota_publica_ativa(url):
            return _salvar_e_avisar(url, "Novo endpoint conectado ao gateway.")
        time.sleep(1)
    return {"ok": False, "mensagem":
            "Endereço anterior mantido. O túnel interno iniciou, mas o novo endereço público não encaminha ao gateway. "
            "No painel ngrok, encaminhe o Cloud Endpoint para https://default.internal.", **estado()}
