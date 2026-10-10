"""Endereço da ponte Fedora usada por recursos locais no Windows."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time
from urllib.parse import urlsplit

import requests

_ultima_consulta_firebase = 0.0


def _arquivo_endpoint_cliente() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData/Local")
    return base / "Emily" / "gateway-client.json"


def endpoint_cliente() -> str:
    try:
        dados = json.loads(_arquivo_endpoint_cliente().read_text(encoding="utf-8"))
        from gateway_endpoint import validar_url
        return validar_url(dados.get("url", ""))
    except (OSError, ValueError, TypeError):
        return ""


def _salvar_endpoint_cliente(url: str, timestamp: float) -> bool:
    from gateway_endpoint import validar_url
    nova = validar_url(url)
    caminho = _arquivo_endpoint_cliente()
    try:
        anterior = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        anterior = {}
    try:
        anterior_ts = float(anterior.get("atualizado_em", 0))
    except (TypeError, ValueError):
        anterior_ts = 0
    if anterior_ts >= timestamp:
        return False
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=caminho.parent,
                                     prefix=".gateway-", delete=False) as temporario:
        json.dump({"url": nova, "atualizado_em": timestamp}, temporario)
        nome = temporario.name
    os.replace(nome, caminho)
    return True


def _token_gateway() -> str:
    if os.getenv("EMILY_PUBLIC_MODE") == "1":
        return ""
    token = os.getenv("EMILY_PONTE_TOKEN", "").strip()
    if token:
        return token
    try:
        from dotenv import dotenv_values
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        for caminho in (base / ".env", base / "_internal" / ".env"):
            if caminho.is_file():
                token = str(dotenv_values(caminho).get("EMILY_PONTE_TOKEN") or "").strip()
                if token:
                    return token
    except ImportError:
        pass
    return ""


def sincronizar_endpoint_firebase(*, sessao=None) -> bool:
    """Busca a URL assinada no Firebase sem depender do domínio ngrok anterior."""
    token = _token_gateway()
    if not token:
        return False
    try:
        from firebase_endpoint import consultar
        registro = consultar(token, sessao=sessao)
        return bool(registro and _salvar_endpoint_cliente(*registro))
    except (requests.RequestException, OSError, ValueError, TypeError, RuntimeError):
        return False


def _sincronizar_firebase_se_hora() -> None:
    global _ultima_consulta_firebase
    agora = time.monotonic()
    if agora - _ultima_consulta_firebase < 300:
        return
    _ultima_consulta_firebase = agora
    sincronizar_endpoint_firebase()


def sincronizar_endpoint_cliente(base: str, token: str,
                                sessao: requests.Session | None = None) -> bool:
    """Atualiza a URL persistida enquanto uma rota conhecida ainda responde."""
    if not base or not token:
        return False
    try:
        alvo = sessao or requests
        # A sincronização desktop aceita uma Session com o protocolo request();
        # não exigir .get() só para consultar o endpoint.
        resposta = alvo.request(
            "GET", base.rstrip("/") + "/gateway/endpoint",
            headers={"Authorization": f"Bearer {token}"}, timeout=(3, 6))
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados.get("ok"):
            return False
        from gateway_endpoint import validar_url
        nova = validar_url(dados.get("url", ""))
        timestamp = float(dados.get("atualizado_em", 0))
        return _salvar_endpoint_cliente(nova, timestamp)
    except Exception as erro:  # noqa: BLE001
        # Consulta auxiliar: não pode derrubar a sincronização de chats ou
        # preferências por um erro próprio do endpoint/cliente HTTP.
        print(f"[GATEWAY] não consultei o endpoint remoto: {type(erro).__name__}")
        return False


def ambiente_fedora() -> bool:
    """O túnel ngrok próprio desta instalação só roda no host Fedora."""
    if os.getenv("EMILY_PUBLIC_MODE") == "1":
        return False
    if sys.platform != "linux":
        return False
    try:
        return platform.freedesktop_os_release().get("ID", "").lower() == "fedora"
    except OSError:
        return False


def gateway_fedora() -> str:
    if os.getenv("EMILY_PUBLIC_MODE") == "1":
        return ""
    if os.name == "nt":
        _sincronizar_firebase_se_hora()
        salvo = endpoint_cliente()
        if salvo:
            return salvo
    configurada = os.getenv("EMILY_SYNC_URL", "").strip().rstrip("/")
    if configurada:
        return configurada
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    try:
        return str(json.loads((base / "windows-release.json").read_text(
            encoding="utf-8")).get("sync_url") or "").strip().rstrip("/")
    except (OSError, ValueError):
        return ""


def provedor_via_fedora(provedor: str, base_url: str,
                       *, windows: bool | None = None) -> bool:
    """Só bases de loopback do OmniRoute mudam de destino no Windows."""
    if windows is None:
        windows = os.name == "nt"
    host = urlsplit(base_url).hostname
    return bool(windows and provedor in {"openai", "omniroute"}
                and host in {"localhost", "127.0.0.1", "::1"})


def base_llm_fedora() -> str:
    origem = gateway_fedora()
    if not origem.startswith("https://"):
        raise RuntimeError("gateway Fedora HTTPS não configurado para modelos OmniRoute")
    return origem + "/llm/v1"
