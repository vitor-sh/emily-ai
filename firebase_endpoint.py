"""Descoberta da URL do gateway pelo Realtime Database do Firebase.

O registro é público para leitura e contém apenas a URL. A assinatura HMAC
impede que um registro adulterado redirecione o Windows e exponha o token do
gateway a um servidor falso. Só o servidor Fedora escreve com a conta Admin.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re

import requests


# A instância é fixa por projeto; a URL ngrok publicada nela pode mudar.
DATABASE_URL = "https://emily-assistente-default-rtdb.firebaseio.com"
SCOPES = (
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/firebase.database",
)


def _url_registro() -> str:
    base = (os.getenv("EMILY_FIREBASE_DATABASE_URL") or DATABASE_URL).strip().rstrip("/")
    if not base.startswith("https://"):
        raise RuntimeError("Realtime Database da Emily não configurado")
    return base + "/gateway_endpoint.json"


def criar_registro(url: str, atualizado_em: float, token: str) -> dict[str, str]:
    from gateway_endpoint import validar_url

    url = validar_url(url)
    if not token:
        raise ValueError("token do gateway ausente")
    if not math.isfinite(float(atualizado_em)) or float(atualizado_em) <= 0:
        raise ValueError("data de atualização inválida")
    instante = f"{float(atualizado_em):.6f}"
    assinatura = hmac.new(token.encode("utf-8"),
                          f"{url}\n{instante}".encode("utf-8"), hashlib.sha256).hexdigest()
    return {"url": url, "atualizado_em": instante, "assinatura": assinatura}


def validar_registro(registro: object, token: str) -> tuple[str, float] | None:
    if not isinstance(registro, dict) or not token:
        return None
    try:
        url = registro["url"]
        instante = registro["atualizado_em"]
        assinatura = registro["assinatura"]
        if not isinstance(instante, str) or not re.fullmatch(r"\d{10,}\.\d{6}", instante):
            return None
        if not isinstance(assinatura, str) or not re.fullmatch(r"[0-9a-f]{64}", assinatura):
            return None
        esperado = criar_registro(url, float(instante), token)
        if esperado["atualizado_em"] != instante or not hmac.compare_digest(
                esperado["assinatura"], assinatura):
            return None
        return esperado["url"], float(instante)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def consultar(token: str, *, sessao=None) -> tuple[str, float] | None:
    resposta = (sessao or requests).get(_url_registro(), timeout=(3, 6))
    resposta.raise_for_status()
    return validar_registro(resposta.json(), token)


def publicar(url: str, atualizado_em: float, token: str, credencial: str,
             *, sessao=None) -> None:
    """Escreve só depois de autenticar a conta Admin; clientes têm write=false."""
    if not credencial:
        raise RuntimeError("credencial Firebase ausente")
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    credenciais = service_account.Credentials.from_service_account_file(
        credencial, scopes=SCOPES)
    if credenciais.project_id != "emily-assistente":
        raise RuntimeError("credencial Firebase pertence a outro projeto")
    resposta = (sessao or AuthorizedSession(credenciais)).put(
        _url_registro(), json=criar_registro(url, atualizado_em, token), timeout=(3, 10))
    resposta.raise_for_status()
