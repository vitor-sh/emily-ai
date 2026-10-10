#!/usr/bin/env python3
"""Ponte WebSocket local, autenticada e permanente para a extensão do navegador.

O socket escuta somente em loopback. A primeira mensagem de cada conexão precisa
ser ``{"tipo":"autenticar","token":"..."}``; só depois o cliente entra no
conjunto apto a receber comandos. Chamadas externas usam ``request_id`` e nunca
dependem da antiga variável global de "última resposta".
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hmac
import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Callable


class BrowserBridge:
    def __init__(
        self,
        *,
        token_provider: Callable[[], str],
        host: str = "127.0.0.1",
        port: int = 8765,
        download_handler: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._token_provider = token_provider
        self.host = host
        self.port = int(port)
        self._download_handler = download_handler
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._clients: set[Any] = set()
        self._clients_lock = threading.RLock()
        self._pending: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.RLock()
        self._started = threading.Event()
        self._start_error = ""

    def iniciar(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._started.clear()
        self._start_error = ""
        self._thread = threading.Thread(
            target=self._thread_main,
            daemon=True,
            name="EmilyBrowserBridge",
        )
        self._thread.start()
        self._started.wait(timeout=5.0)
        if self._start_error:
            raise RuntimeError(self._start_error)

    def encerrar(self) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        futuro = asyncio.run_coroutine_threadsafe(self._encerrar_async(), loop)
        try:
            futuro.result(timeout=4.0)
        except (TimeoutError, concurrent.futures.TimeoutError):
            pass
        loop.call_soon_threadsafe(loop.stop)

    def conectado(self) -> bool:
        with self._clients_lock:
            return bool(self._clients)

    def status(self) -> dict[str, Any]:
        with self._clients_lock:
            clientes = len(self._clients)
        return {
            "ok": True,
            "conectado": clientes > 0,
            "clientes": clientes,
            "host": self.host,
            "porta": self.port,
        }

    def executar(self, acao: str, *, timeout: float = 12.0, **parametros: Any) -> dict[str, Any]:
        if not isinstance(acao, str) or not acao.strip():
            return {"ok": False, "mensagem": "ação do navegador inválida"}
        loop = self._loop
        if loop is None or not loop.is_running() or not self.conectado():
            return {"ok": False, "mensagem": "extensão do navegador desconectada"}

        request_id = f"gw-{uuid.uuid4().hex}"
        resposta: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[request_id] = resposta
        comando = {"acao": acao.strip(), "request_id": request_id, **parametros}
        try:
            enviado = asyncio.run_coroutine_threadsafe(self._enviar(comando), loop).result(timeout=3.0)
            if not enviado:
                return {"ok": False, "mensagem": "extensão do navegador desconectada"}
            try:
                dados = resposta.get(timeout=max(0.2, min(float(timeout), 60.0)))
            except queue.Empty:
                return {"ok": False, "mensagem": f"a extensão não respondeu à ação {acao}"}
            if dados.get("tipo") == "erro":
                return {
                    "ok": False,
                    "mensagem": str(dados.get("mensagem") or "ação recusada pela extensão"),
                    "browser": dados,
                }
            return {"ok": True, "mensagem": "ação concluída no navegador", "browser": dados}
        except (TimeoutError, concurrent.futures.TimeoutError):
            return {"ok": False, "mensagem": "tempo esgotado ao falar com a extensão"}
        except Exception as exc:
            return {"ok": False, "mensagem": f"ponte do navegador falhou: {type(exc).__name__}"}
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _thread_main(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._iniciar_async())
            self._started.set()
            self._loop.run_forever()
        except Exception as exc:
            self._start_error = f"não consegui iniciar a ponte do navegador: {type(exc).__name__}: {exc}"
            self._started.set()
        finally:
            try:
                self._loop.run_until_complete(self._encerrar_async())
            except Exception:
                pass
            self._loop.close()

    async def _iniciar_async(self) -> None:
        import websockets

        self._server = await websockets.serve(
            self._handler,
            self.host,
            self.port,
            max_size=4 * 1024 * 1024,
            ping_interval=30,
            ping_timeout=20,
        )

    async def _encerrar_async(self) -> None:
        with self._clients_lock:
            clientes = list(self._clients)
            self._clients.clear()
        for websocket in clientes:
            try:
                await websocket.close(code=1001, reason="gateway encerrando")
            except Exception:
                pass
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _autenticar(self, websocket: Any) -> bool:
        esperado = str(self._token_provider() or "")
        if not esperado:
            await websocket.close(code=1008, reason="token do gateway não configurado")
            return False
        try:
            bruto = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            dados = json.loads(bruto)
        except Exception:
            await websocket.close(code=1008, reason="autenticação ausente")
            return False
        recebido = str(dados.get("token") or "") if isinstance(dados, dict) else ""
        if not isinstance(dados, dict) or dados.get("tipo") != "autenticar" or not hmac.compare_digest(recebido, esperado):
            await websocket.close(code=1008, reason="token inválido")
            return False
        await websocket.send(json.dumps({"tipo": "autenticado", "ok": True}, ensure_ascii=False))
        return True

    async def _handler(self, websocket: Any) -> None:
        if not await self._autenticar(websocket):
            return
        with self._clients_lock:
            self._clients.add(websocket)
        try:
            async for mensagem_raw in websocket:
                try:
                    dados = json.loads(mensagem_raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(dados, dict):
                    continue
                if dados.get("tipo") == "download_concluido":
                    await self._processar_download(websocket, dados)
                    continue
                request_id = str(dados.get("request_id") or "")
                if not request_id:
                    continue
                with self._pending_lock:
                    destino = self._pending.get(request_id)
                if destino is not None:
                    try:
                        destino.put_nowait(dados)
                    except queue.Full:
                        pass
        finally:
            with self._clients_lock:
                self._clients.discard(websocket)

    async def _processar_download(self, websocket: Any, dados: dict[str, Any]) -> None:
        evento_id = str(dados.get("evento_id") or "").strip()
        resultado: dict[str, Any] = {"ok": False, "erro": "integração de downloads indisponível"}
        if self._download_handler is not None:
            try:
                resultado = await asyncio.to_thread(self._download_handler, dados)
            except Exception as exc:
                resultado = {"ok": False, "erro": f"{type(exc).__name__}: {exc}"}
        await websocket.send(json.dumps({
            "tipo": "download_cloud_ack",
            "evento_id": evento_id,
            "ok": bool(resultado.get("ok")),
            "erro": str(resultado.get("erro") or ""),
            "item_id": str((resultado.get("item") or {}).get("id") or ""),
        }, ensure_ascii=False))

    async def _enviar(self, comando: dict[str, Any]) -> bool:
        with self._clients_lock:
            clientes = list(self._clients)
        if not clientes:
            return False
        payload = json.dumps(comando, ensure_ascii=False)
        enviados = 0
        for websocket in clientes:
            try:
                await websocket.send(payload)
                enviados += 1
            except Exception:
                with self._clients_lock:
                    self._clients.discard(websocket)
        return enviados > 0


def guardar_download_da_extensao(dados: dict[str, Any]) -> dict[str, Any]:
    """Importa somente evento com ID e arquivo concluído realmente existente."""
    evento_id = str(dados.get("evento_id") or "").strip()
    caminho = Path(str(dados.get("caminho") or "")).expanduser()
    if not evento_id:
        return {"ok": False, "erro": "evento de download sem ID"}
    if not caminho.is_file():
        return {"ok": False, "erro": "arquivo final do download não encontrado"}
    from emily_cloud.integration import guardar_download_evento

    return guardar_download_evento(
        str(caminho), evento_id, str(dados.get("url") or ""), "extensao_navegador_gateway",
    )