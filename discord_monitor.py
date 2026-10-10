"""Escolhe qual desktop pode acompanhar o chat do Discord.

O gateway Fedora guarda a escolha. O Windows confere o dono antes de responder
a cada mensagem, para uma troca de PC não produzir duas respostas.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import requests

from emily_paths import arquivo_dados
import preferencias

_ID_FILE = arquivo_dados("discord-monitor-host-id.txt")
_id_cache: str | None = None


def _windows() -> bool:
    return os.name == "nt"


def identificador_local() -> str:
    global _id_cache
    if _id_cache:
        return _id_cache
    try:
        valor = _ID_FILE.read_text(encoding="ascii").strip()
        uuid.UUID(valor)
    except (OSError, ValueError, AttributeError):
        valor = str(uuid.uuid4())
        _ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = _ID_FILE.with_suffix(".tmp")
        temp.write_text(valor, encoding="ascii")
        os.replace(temp, _ID_FILE)
    _id_cache = valor
    return valor


def preparar_legado() -> None:
    """Preserva a escuta automática antiga no Fedora só na primeira migração."""
    if _windows() or "monitor_discord_host" in preferencias.exportar_sync():
        return
    preferencias.definir(monitor_discord_host=identificador_local())


def host_ativo() -> str:
    return str(preferencias.obter("monitor_discord_host") or "")


def aplicar() -> bool:
    """Aplica a escolha sincronizada no processo atual."""
    import discord_bot
    if os.getenv("EMILY_RUNTIME_CLOUD") == "1":
        ativo = bool(preferencias.obter("discord_cloud_escuta", True))
        discord_bot._escuta_discord_ativa.set() if ativo else discord_bot._escuta_discord_ativa.clear()
        return ativo
    ativo = host_ativo() == identificador_local()
    if ativo:
        discord_bot._escuta_discord_ativa.set()
    else:
        discord_bot._escuta_discord_ativa.clear()
    return ativo


def _gateway(metodo: str, *, host: str | None = None) -> dict:
    from sincronizacao_desktop import _config, _pedido
    base, token = _config()
    if not base or not token:
        raise RuntimeError("gateway de sincronização não configurado")
    kw = {"json": {"host": host}} if host is not None else {}
    return _pedido(requests.Session(), metodo, base + "/discord/monitor-owner", token,
                   timeout=(2, 4) if metodo == "GET" else (3, 8), **kw)


def selecionar(ligado: bool) -> bool:
    """Muda a escolha. No Windows só confirma após o gateway aceitar."""
    from cloud_runtime_client import hospedado_na_oracle, rpc
    if hospedado_na_oracle() and os.getenv("EMILY_RUNTIME_CLOUD") != "1":
        return bool(rpc("monitor", {"ligado": bool(ligado)}))
    meu_id = identificador_local()
    destino = meu_id if ligado else ""
    if _windows():
        try:
            resposta = _gateway("POST", host=destino)
            campo = resposta.get("campo")
            if not isinstance(campo, dict) or campo.get("valor") != destino:
                return False
            preferencias.mesclar_sync({"monitor_discord_host": campo}, forcar=True)
            return aplicar() == ligado
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as exc:
            print(f"[DISCORD-MONITOR] troca de PC adiada: {type(exc).__name__}: {exc}")
            return False
    if not preferencias.definir(monitor_discord_host=destino):
        return False
    return aplicar() == ligado


def pode_responder() -> bool:
    """Confere o dono atual antes de uma resposta no Discord."""
    if os.getenv("EMILY_RUNTIME_CLOUD") == "1":
        return bool(preferencias.obter("discord_cloud_escuta", True))
    from cloud_runtime_client import hospedado_na_oracle
    if hospedado_na_oracle():
        return False
    if host_ativo() != identificador_local():
        return False
    if not _windows():
        return True
    try:
        return _gateway("GET").get("host") == identificador_local()
    except (requests.RequestException, RuntimeError, ValueError, TypeError):
        # Sem confirmação do gateway, o Windows não arrisca resposta duplicada.
        return False
