"""Ponte do navegador: autenticação, correlação e ACK sem abrir sockets reais."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import queue
import sys
from pathlib import Path

import pytest


RAIZ = Path(__file__).resolve().parents[1]
CAMINHO = RAIZ / "emily-gateway-service" / "browser_bridge.py"


@pytest.fixture()
def modulo():
    spec = importlib.util.spec_from_file_location("browser_bridge_teste", CAMINHO)
    carregado = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = carregado
    spec.loader.exec_module(carregado)
    return carregado


class WebSocketFalso:
    def __init__(self, recebidas=()):
        self.recebidas = list(recebidas)
        self.enviadas: list[dict] = []
        self.fechamentos: list[tuple[int, str]] = []

    async def recv(self):
        if not self.recebidas:
            raise RuntimeError("sem mensagem")
        return self.recebidas.pop(0)

    async def send(self, payload):
        self.enviadas.append(json.loads(payload))

    async def close(self, *, code, reason):
        self.fechamentos.append((code, reason))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.recebidas:
            raise StopAsyncIteration
        return self.recebidas.pop(0)


def test_autenticacao_exige_primeira_mensagem_com_token(modulo):
    bridge = modulo.BrowserBridge(token_provider=lambda: "segredo")

    invalido = WebSocketFalso([json.dumps({"tipo": "autenticar", "token": "errado"})])
    assert asyncio.run(bridge._autenticar(invalido)) is False
    assert invalido.enviadas == []
    assert invalido.fechamentos == [(1008, "token inválido")]

    valido = WebSocketFalso([json.dumps({"tipo": "autenticar", "token": "segredo"})])
    assert asyncio.run(bridge._autenticar(valido)) is True
    assert valido.enviadas == [{"tipo": "autenticado", "ok": True}]
    assert valido.fechamentos == []


def test_handler_correlaciona_resposta_pelo_request_id(modulo):
    bridge = modulo.BrowserBridge(token_provider=lambda: "segredo")
    destino = queue.Queue(maxsize=1)
    bridge._pending["gw-certo"] = destino
    websocket = WebSocketFalso([
        json.dumps({"tipo": "autenticar", "token": "segredo"}),
        json.dumps({"tipo": "ok", "request_id": "gw-ignorado", "valor": 1}),
        json.dumps({"tipo": "ok", "request_id": "gw-certo", "valor": 2}),
    ])

    asyncio.run(bridge._handler(websocket))

    assert destino.get_nowait()["valor"] == 2
    assert bridge.conectado() is False


def test_download_recebe_ack_com_mesmo_evento(modulo):
    recebidos = []

    def importar(dados):
        recebidos.append(dados)
        return {"ok": True, "item": {"id": "item-42"}}

    bridge = modulo.BrowserBridge(token_provider=lambda: "segredo", download_handler=importar)
    websocket = WebSocketFalso()
    evento = {"tipo": "download_concluido", "evento_id": "ext-7", "caminho": "/tmp/a.pdf"}

    asyncio.run(bridge._processar_download(websocket, evento))

    assert recebidos == [evento]
    assert websocket.enviadas == [{
        "tipo": "download_cloud_ack",
        "evento_id": "ext-7",
        "ok": True,
        "erro": "",
        "item_id": "item-42",
    }]