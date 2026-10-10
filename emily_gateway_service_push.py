"""Solicita ao gateway local o envio privado da URL atual via Firebase."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def _pedir(caminho: str, url: str, atualizado_em: float) -> None:
    token = os.getenv("EMILY_PONTE_TOKEN", "").strip()
    if not token:
        raise RuntimeError("token do gateway indisponível neste processo")
    pedido = Request(
        "http://127.0.0.1:5000/gateway/endpoint/" + caminho,
        data=json.dumps({"url": url, "atualizado_em": atualizado_em}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urlopen(pedido, timeout=20) as resposta:
            dados = json.load(resposta)
    except HTTPError as exc:
        try:
            dados = json.load(exc)
        except (ValueError, TypeError):
            dados = {}
        raise RuntimeError(str(dados.get("erro") or f"gateway retornou HTTP {exc.code}")) from exc
    if not dados.get("ok"):
        raise RuntimeError(str(dados.get("erro") or "envio Firebase não confirmado"))


def avisar_troca_endpoint(url: str, atualizado_em: float) -> str:
    _pedir("push", url, atualizado_em)
    return "Aviso de troca enviado ao Android."


def publicar_endpoint_firebase(url: str, atualizado_em: float) -> str:
    _pedir("publish", url, atualizado_em)
    return "Endereço publicado para o Windows."
