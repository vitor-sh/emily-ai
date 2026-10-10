"""Fachada isolada para registrar trocas e agendar extrações."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .config import ConfigMemoria, carregar_config
from .journal import JournalMemoria, LoteExtracao
from .modelos import EventoMemoria
from .worker import ProcessadorLote, WorkerExtracao


@dataclass(frozen=True)
class ResultadoRegistro:
    eventos: Tuple[EventoMemoria, ...]
    eventos_novos: int
    lote_id: str = ""
    enfileirado: bool = False


def _id_evento_deterministico(
    owner_user_id: str,
    canal: str,
    external_id: str,
    papel: str,
    texto: str,
) -> str:
    base = "\x1f".join((owner_user_id, canal, external_id, papel, texto))
    return "evt_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:28]


class ServicoMemoria:
    """Registra eventos sempre; extração pode ser síncrona ou por worker."""

    def __init__(
        self,
        journal: JournalMemoria,
        processador: ProcessadorLote,
        config: Optional[ConfigMemoria] = None,
        worker: Optional[WorkerExtracao] = None,
    ):
        self.config = config or carregar_config()
        self.journal = journal
        self.processador = processador
        self.worker = worker

    def iniciar(self) -> None:
        if self.worker is not None:
            self.worker.iniciar(recuperar=True)

    def encerrar(self, aguardar: bool = True, timeout: float = 10.0) -> None:
        if self.worker is not None:
            self.worker.encerrar(aguardar=aguardar, timeout=timeout)

    def registrar_evento(
        self,
        evento: EventoMemoria,
        forcar_extracao: bool = False,
    ) -> ResultadoRegistro:
        salvo, criou = self.journal.adicionar(evento)
        lote = self._criar_lote_se_pronto(
            salvo.owner_user_id,
            salvo.privacy_scope,
            salvo.memory_pool,
            forcar=forcar_extracao,
        ) if criou else None
        enfileirado = self._despachar(lote) if lote else False
        return ResultadoRegistro(
            eventos=(salvo,), eventos_novos=int(criou),
            lote_id=lote.id if lote else "", enfileirado=enfileirado,
        )

    def registrar_troca(
        self,
        owner_user_id: str,
        usuario: str,
        assistant: str,
        canal: str,
        conversa_id: str = "",
        external_id: str = "",
        privacy_scope: str = "owner_private",
        memory_pool: str = "general",
        timestamp: Optional[float] = None,
        forcar_extracao: bool = False,
    ) -> ResultadoRegistro:
        """Guarda os dois lados; texto vazio é simplesmente omitido."""

        agora = float(timestamp if timestamp is not None else time.time())
        brutos = (("user", usuario, 0.0), ("assistant", assistant, 0.000001))
        eventos: List[EventoMemoria] = []
        novos = 0
        for papel, texto, deslocamento in brutos:
            limpo = str(texto or "").strip()
            if not limpo:
                continue
            externo = f"{external_id}:{papel}" if external_id else ""
            evento_id = (
                _id_evento_deterministico(
                    owner_user_id, canal, externo, papel, limpo)
                if externo else None
            )
            kwargs = {"id": evento_id} if evento_id else {}
            evento = EventoMemoria(
                owner_user_id=owner_user_id,
                papel=papel,
                texto=limpo,
                canal=canal,
                timestamp=agora + deslocamento,
                conversa_id=conversa_id,
                external_id=externo,
                privacy_scope=privacy_scope,
                memory_pool=memory_pool,
                **kwargs,
            )
            salvo, criou = self.journal.adicionar(evento)
            eventos.append(salvo)
            novos += int(criou)

        lote = None
        if novos and eventos:
            lote = self._criar_lote_se_pronto(
                owner_user_id, privacy_scope, memory_pool,
                forcar=forcar_extracao,
            )
        enfileirado = self._despachar(lote) if lote else False
        return ResultadoRegistro(
            eventos=tuple(eventos), eventos_novos=novos,
            lote_id=lote.id if lote else "", enfileirado=enfileirado,
        )

    def _criar_lote_se_pronto(
        self,
        owner_user_id: str,
        privacy_scope: str,
        memory_pool: str,
        forcar: bool,
    ) -> Optional[LoteExtracao]:
        quantidade = self.journal.contar_nao_processados(
            owner_user_id, privacy_scope, memory_pool)
        if not forcar and quantidade < self.config.eventos_por_extracao:
            return None
        return self.journal.criar_lote(
            owner_user_id=owner_user_id,
            privacy_scope=privacy_scope,
            memory_pool=memory_pool,
            max_eventos=self.config.max_eventos_por_lote,
            max_chars=self.config.max_chars_por_lote,
            # O limiar decide QUANDO disparar. O teto de caracteres pode fazer o
            # lote conter menos eventos, sem deixar uma fala gigante bloquear tudo.
            minimo_eventos=1,
        )

    def _despachar(self, lote: Optional[LoteExtracao]) -> bool:
        if lote is None:
            return False
        if self.worker is not None and self.worker.ativo:
            return self.worker.enfileirar(lote.id)
        return False

    def processar_agora(self, lote_id: str) -> bool:
        return self.processador.processar(lote_id)

    def flush_grupo(
        self,
        owner_user_id: str,
        privacy_scope: str = "owner_private",
        memory_pool: str = "general",
    ) -> List[str]:
        """Cria/processa todos os lotes restantes; útil no fim de sessão/migração."""

        lotes = []
        while self.journal.contar_nao_processados(
            owner_user_id, privacy_scope, memory_pool
        ):
            lote = self._criar_lote_se_pronto(
                owner_user_id, privacy_scope, memory_pool, forcar=True)
            if lote is None:
                break
            lotes.append(lote.id)
            if self.worker is not None and self.worker.ativo:
                if not self.worker.enfileirar(lote.id):
                    break
            else:
                self.processador.processar(lote.id)
        if self.worker is not None and self.worker.ativo:
            self.worker.aguardar()
        return lotes


__all__ = ["ResultadoRegistro", "ServicoMemoria"]