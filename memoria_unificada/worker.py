"""Processamento confiável e assíncrono dos lotes de extração."""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .armazenamento import ArmazenamentoMemoria
from .config import ConfigMemoria, carregar_config
from .extracao import ExtratorMemoria
from .journal import JournalMemoria, LoteExtracao


class ProcessadorLote:
    """Executa uma extração e confirma o checkpoint somente ao final."""

    def __init__(
        self,
        journal: JournalMemoria,
        armazenamento: ArmazenamentoMemoria,
        extrator: ExtratorMemoria,
        max_tentativas: int = 3,
    ):
        self.journal = journal
        self.armazenamento = armazenamento
        self.extrator = extrator
        self.max_tentativas = max(1, int(max_tentativas))

    def processar(self, lote_id: str) -> bool:
        """Retorna True quando concluiu; False em falha recuperável/esgotada."""

        if not self.journal.marcar_processando(lote_id, self.max_tentativas):
            lote = self.journal.obter_lote(lote_id)
            return bool(lote and lote.status == "completed")
        try:
            lote = self.journal.obter_lote(lote_id)
            if lote is None:
                raise KeyError(f"lote não encontrado: {lote_id}")
            fatos = self.extrator.extrair(lote)
            ids = []
            for fato in fatos:
                # IDs determinísticos tornam retry seguro se o processo morrer
                # entre este upsert e o checkpoint marcar_concluido().
                self.armazenamento.salvar(fato)
                ids.append(fato.id)
            self.journal.marcar_concluido(lote_id, ids)
            return True
        except Exception as erro:  # noqa: BLE001 - fronteira do worker
            try:
                self.journal.marcar_falha(
                    lote_id, f"{type(erro).__name__}: {erro}")
            except Exception as erro_checkpoint:  # noqa: BLE001
                print(
                    f"[MEMORIA-UNIFICADA] lote {lote_id}: falha '{erro}' e "
                    f"checkpoint também falhou: {erro_checkpoint}"
                )
            else:
                print(f"[MEMORIA-UNIFICADA] lote {lote_id} falhou: {erro}")
            return False

    def pode_tentar_novamente(self, lote_id: str) -> bool:
        lote = self.journal.obter_lote(lote_id)
        return bool(
            lote and lote.status in {"pending", "failed"}
            and lote.tentativas < self.max_tentativas
        )


class WorkerExtracao:
    """Fila limitada; lotes continuam persistidos quando não couberem nela."""

    _PARAR = object()

    def __init__(
        self,
        processador: ProcessadorLote,
        fila_maxima: int = 100,
        nome: str = "emily-memoria-extracao",
    ):
        self.processador = processador
        self._fila: queue.Queue = queue.Queue(maxsize=max(1, int(fila_maxima)))
        self._nome = nome
        self._thread: Optional[threading.Thread] = None
        self._parando = threading.Event()
        self._ids_na_fila = set()
        self._lock_ids = threading.Lock()

    @property
    def ativo(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def iniciar(self, recuperar: bool = True) -> None:
        if self.ativo:
            return
        self._parando.clear()
        self.processador.journal.recuperar_interrompidos()
        self._thread = threading.Thread(
            target=self._rodar, name=self._nome, daemon=True)
        self._thread.start()
        if recuperar:
            self._recolher_persistidos()

    def _recolher_persistidos(self) -> None:
        """Preenche vagas da fila com lotes persistidos que ficaram de fora."""

        if self._parando.is_set():
            return
        for lote in self.processador.journal.listar_lotes_recuperaveis():
            if lote.tentativas >= self.processador.max_tentativas:
                continue
            if not self.enfileirar(lote.id):
                break

    def enfileirar(self, lote_id: str) -> bool:
        identificador = str(lote_id or "").strip()
        if not identificador or self._parando.is_set():
            return False
        with self._lock_ids:
            if identificador in self._ids_na_fila:
                return True
            try:
                self._fila.put_nowait(identificador)
            except queue.Full:
                return False
            self._ids_na_fila.add(identificador)
            return True

    def _rodar(self) -> None:
        while True:
            item = self._fila.get()
            try:
                if item is self._PARAR:
                    return
                lote_id = str(item)
                with self._lock_ids:
                    self._ids_na_fila.discard(lote_id)
                concluiu = self.processador.processar(lote_id)
                if not concluiu and self.processador.pode_tentar_novamente(lote_id):
                    self.enfileirar(lote_id)
            finally:
                # Recolhe ANTES do task_done: assim aguardar() nunca observa
                # unfinished_tasks=0 no intervalo entre terminar este lote e
                # descobrir outro que havia ficado fora da fila cheia.
                if item is not self._PARAR and not self._parando.is_set():
                    self._recolher_persistidos()
                self._fila.task_done()

    def aguardar(self, timeout: Optional[float] = None) -> None:
        """Espera todos os itens atuais, inclusive retries re-enfileirados."""

        if timeout is None:
            self._fila.join()
            return
        fim = time.monotonic() + max(0.0, float(timeout))
        # Queue não oferece join(timeout), mas expõe a mesma Condition usada
        # internamente por join(); aguardar nela evita polling e mantém task_done.
        with self._fila.all_tasks_done:
            while self._fila.unfinished_tasks:
                restante = fim - time.monotonic()
                if restante <= 0:
                    raise TimeoutError("worker da memória não esvaziou a fila no prazo")
                self._fila.all_tasks_done.wait(restante)

    def _descartar_fila_em_memoria(self) -> None:
        """Tira só da RAM; os lotes continuam pending/failed no SQLite."""

        while True:
            try:
                item = self._fila.get_nowait()
            except queue.Empty:
                return
            try:
                if item is not self._PARAR:
                    with self._lock_ids:
                        self._ids_na_fila.discard(str(item))
            finally:
                self._fila.task_done()

    def encerrar(self, aguardar: bool = True, timeout: float = 10.0) -> None:
        if not self.ativo:
            return
        timeout = max(0.1, float(timeout))
        inicio = time.monotonic()
        erro_espera = None
        if aguardar:
            try:
                self.aguardar(timeout=timeout)
            except TimeoutError as erro:
                erro_espera = erro
        self._parando.set()
        if not aguardar or erro_espera is not None:
            self._descartar_fila_em_memoria()
        try:
            self._fila.put_nowait(self._PARAR)
        except queue.Full:  # defensivo: descarte acima normalmente abre espaço
            self._descartar_fila_em_memoria()
            self._fila.put_nowait(self._PARAR)
        restante = max(0.1, timeout - (time.monotonic() - inicio))
        self._thread.join(timeout=restante)
        if self._thread.is_alive():
            raise TimeoutError("worker da memória não encerrou no prazo")
        self._thread = None
        if erro_espera is not None:
            raise erro_espera


def criar_worker_padrao(
    journal: JournalMemoria,
    armazenamento: ArmazenamentoMemoria,
    config: Optional[ConfigMemoria] = None,
    extrator: Optional[ExtratorMemoria] = None,
) -> WorkerExtracao:
    cfg = config or carregar_config()
    processador = ProcessadorLote(
        journal, armazenamento, extrator or ExtratorMemoria(),
        max_tentativas=cfg.tentativas_extracao,
    )
    return WorkerExtracao(processador, fila_maxima=cfg.fila_maxima)


__all__ = ["ProcessadorLote", "WorkerExtracao", "criar_worker_padrao"]