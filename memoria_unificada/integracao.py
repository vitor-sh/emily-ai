"""Ponte entre a Emily operacional e a memória unificada.

Liga/desliga por EMILY_MEMORIA_UNIFICADA. Nunca levanta exceção para o chamador:
a memória é melhoria, não dependência. Sem a camada vetorial, preserva o journal
e a conversa recente; falhas gerais pausam a ponte brevemente e têm retry.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional, Tuple

from .armazenamento import ArmazenamentoMemoria, ErroArmazenamentoMemoria
from .config import ConfigMemoria, carregar_config
from .embeddings import ProvedorEmbeddings, criar_provedor_embeddings
from .extracao import ExtratorMemoria
from .journal import JournalMemoria
from .recuperacao import RecuperadorMemoria
from .servico import ServicoMemoria
from .worker import ProcessadorLote, WorkerExtracao


_MAX_FALHAS_CONSECUTIVAS = 3
_PAUSA_APOS_FALHAS_SEGUNDOS = 30.0
_RETRY_CAMADA_VETORIAL_SEGUNDOS = 60.0


class _ArmazenamentoIndisponivel:
    """Camada 3 vazia enquanto Chroma/embeddings não podem ser abertos."""

    def buscar(self, *_args, **_kwargs):
        return []

    def listar(self, *_args, **_kwargs):
        return []


def dono_id() -> str:
    """Identidade canônica do dono da Emily na memória unificada."""
    return os.getenv("EMILY_MEMORIA_DONO_ID", "vitor").strip() or "vitor"


def id_discord(user_id: int) -> str:
    """Namespace de memória de outra pessoa do Discord, isolado por ID."""
    return f"discord:{int(user_id)}"


class PonteMemoria:
    """Fachada preguiçosa e à prova de falha para os fluxos da Emily.

    A construção dos componentes acontece no primeiro uso real (nada é aberto
    no import, nem quando a flag está desligada). Toda operação devolve um
    padrão seguro em caso de erro — nunca propaga exceção para a conversa.
    """

    def __init__(
        self,
        config: Optional[ConfigMemoria] = None,
        provedor_embeddings: Optional[ProvedorEmbeddings] = None,
        chamar_extracao: Optional[Callable[..., str]] = None,
        cliente=None,
    ):
        self._config_explicita = config is not None
        self.config = config or carregar_config()
        self._provedor_embeddings = provedor_embeddings
        self._chamar_extracao = chamar_extracao
        self._cliente = cliente
        self._servico: Optional[ServicoMemoria] = None
        self._recuperador: Optional[RecuperadorMemoria] = None
        self._lock = threading.Lock()
        self._falhas_consecutivas = 0
        self._desativada_por_erro = False
        self._suspensa_ate = 0.0
        self._modo_degradado = False
        self._retry_vetorial_em = 0.0
        self._ultimo_erro = ""

    @property
    def ativa(self) -> bool:
        self._reativar_circuito_se_hora()
        return self.config.habilitada and not self._desativada_por_erro

    def _reativar_circuito_se_hora(self) -> None:
        if self._desativada_por_erro and time.monotonic() >= self._suspensa_ate:
            self._desativada_por_erro = False
            self._falhas_consecutivas = 0
            print("[MEMORIA-UNIFICADA] pausa encerrada; tentando novamente.")

    def _componentes_degradados(self, journal: JournalMemoria):
        armazenamento = _ArmazenamentoIndisponivel()
        extrator = ExtratorMemoria(chamar_llm=self._chamar_extracao)
        processador = ProcessadorLote(
            journal, armazenamento, extrator,
            max_tentativas=self.config.tentativas_extracao)
        # Sem worker: eventos continuam no journal e lotes ficam pending até a
        # camada vetorial voltar. Nada é descartado nem enviado em loop.
        servico = ServicoMemoria(journal, processador, self.config, worker=None)
        recuperador = RecuperadorMemoria(journal, armazenamento, self.config)
        return servico, recuperador

    def _componentes_completos(self, journal: JournalMemoria):
        provedor = self._provedor_embeddings or criar_provedor_embeddings(self.config)
        armazenamento = ArmazenamentoMemoria(
            self.config, provedor, cliente=self._cliente)
        extrator = ExtratorMemoria(chamar_llm=self._chamar_extracao)
        processador = ProcessadorLote(
            journal, armazenamento, extrator,
            max_tentativas=self.config.tentativas_extracao)
        worker = WorkerExtracao(processador, fila_maxima=self.config.fila_maxima)
        worker.iniciar(recuperar=True)
        servico = ServicoMemoria(journal, processador, self.config, worker)
        recuperador = RecuperadorMemoria(journal, armazenamento, self.config)
        return servico, recuperador

    # ── infraestrutura ────────────────────────────────────────────────
    def _pronta(self) -> Optional[Tuple[ServicoMemoria, RecuperadorMemoria]]:
        if not self.ativa:
            return None
        if self._servico is not None and not self._modo_degradado:
            return self._servico, self._recuperador
        if (self._servico is not None and self._modo_degradado
                and time.monotonic() < self._retry_vetorial_em):
            return self._servico, self._recuperador
        with self._lock:
            if self._servico is not None and not self._modo_degradado:
                return self._servico, self._recuperador
            if (self._servico is not None and self._modo_degradado
                    and time.monotonic() < self._retry_vetorial_em):
                return self._servico, self._recuperador
            try:
                journal = (self._servico.journal if self._servico is not None
                           else JournalMemoria(self.config))
                self._servico, self._recuperador = self._componentes_completos(journal)
                self._modo_degradado = False
                self._ultimo_erro = ""
                self._falhas_consecutivas = 0
                print(f"[MEMORIA-UNIFICADA] ativa ({self.config.pasta_dados})")
                return self._servico, self._recuperador
            except ErroArmazenamentoMemoria as erro:
                # Journal e recuperação recente não dependem do Chroma. Mantê-los
                # vivos evita perder conversas por uma dependência ausente/falha
                # temporária da camada vetorial.
                try:
                    journal = (self._servico.journal if self._servico is not None
                               else JournalMemoria(self.config))
                    if self._servico is None:
                        self._servico, self._recuperador = self._componentes_degradados(journal)
                    self._modo_degradado = True
                    self._ultimo_erro = f"{type(erro).__name__}: {erro}"
                    self._retry_vetorial_em = (
                        time.monotonic() + _RETRY_CAMADA_VETORIAL_SEGUNDOS)
                    print("[MEMORIA-UNIFICADA] modo parcial: journal ativo, "
                          f"camada vetorial indisponível ({erro})")
                    return self._servico, self._recuperador
                except Exception as erro_journal:  # noqa: BLE001
                    self._anotar_falha(erro_journal)
                    return None
            except Exception as erro:  # noqa: BLE001 - fronteira da ponte
                self._anotar_falha(erro)
                return None

    def _anotar_falha(self, erro: Exception) -> None:
        self._falhas_consecutivas += 1
        self._ultimo_erro = f"{type(erro).__name__}: {erro}"
        print(f"[MEMORIA-UNIFICADA] falha "
              f"({self._falhas_consecutivas}/{_MAX_FALHAS_CONSECUTIVAS}): "
              f"{type(erro).__name__}: {erro}")
        if self._falhas_consecutivas >= _MAX_FALHAS_CONSECUTIVAS:
            self._desativada_por_erro = True
            self._suspensa_ate = time.monotonic() + _PAUSA_APOS_FALHAS_SEGUNDOS
            print("[MEMORIA-UNIFICADA] pausada por 30s após erros; "
                  "vai tentar novamente automaticamente.")

    def _executar(self, acao: Callable, padrao):
        """Roda `acao(servico, recuperador)` engolindo erro com padrão seguro."""
        if not self.ativa:
            return padrao
        try:
            componentes = self._pronta()
            if componentes is None:
                return padrao
            resultado = acao(*componentes)
            self._falhas_consecutivas = 0
            return resultado
        except Exception as erro:  # noqa: BLE001 - fronteira da ponte
            self._anotar_falha(erro)
            return padrao

    # ── API usada pelos fluxos da Emily ───────────────────────────────
    def registrar_troca(
        self,
        owner_user_id: str,
        canal: str,
        mensagem_usuario: str,
        resposta: str,
        *,
        conversa_id: str = "",
        external_id: str = "",
        memory_pool: str = "general",
        timestamp: Optional[float] = None,
    ) -> None:
        usuario = str(mensagem_usuario or "").strip()
        dela = str(resposta or "").strip()
        if not usuario and not dela:
            return

        def acao(servico: ServicoMemoria, _recuperador):
            return servico.registrar_troca(
                owner_user_id=owner_user_id,
                usuario=usuario,
                assistant=dela,
                canal=canal,
                conversa_id=conversa_id,
                external_id=external_id,
                memory_pool=memory_pool,
                timestamp=timestamp,
            )

        self._executar(acao, None)

    def bloco_contexto(
        self,
        owner_user_id: str,
        consulta: str,
        *,
        memory_pool: str = "general",
    ) -> str:
        """Bloco pronto para o system prompt; "" quando não há nada."""
        if not str(consulta or "").strip():
            return ""

        def acao(_servico: ServicoMemoria, recuperador: RecuperadorMemoria):
            # O pool de código lê o geral também; o contrário não — fatos
            # técnicos só sobem pra geral quando promovidos pela extração.
            pools = ("general", "code") if memory_pool == "code" else ("general",)
            contexto = recuperador.contexto_completo(
                owner_user_id, consulta, pools=pools)
            return contexto.para_prompt()

        return self._executar(acao, "")

    def encerrar(self, aguardar: bool = False, timeout: float = 5.0) -> None:
        if self._servico is None:
            return
        try:
            self._servico.encerrar(aguardar=aguardar, timeout=timeout)
        except Exception as erro:  # noqa: BLE001
            print(f"[MEMORIA-UNIFICADA] encerrar: {erro}")

    def estado(self) -> dict:
        self._reativar_circuito_se_hora()
        return {
            "ativa": self.ativa,
            "flag": self.config.habilitada,
            "desativada_por_erro": self._desativada_por_erro,
            "falhas_consecutivas": self._falhas_consecutivas,
            "iniciada": self._servico is not None,
            "modo_degradado": self._modo_degradado,
            "ultimo_erro": self._ultimo_erro,
            "reativar_em_segundos": max(
                0, round(self._suspensa_ate - time.monotonic()))
                if self._desativada_por_erro else 0,
        }


# ── Singleton do processo ─────────────────────────────────────────────
_ponte: Optional[PonteMemoria] = None
_ponte_lock = threading.Lock()


def ponte() -> PonteMemoria:
    global _ponte
    with _ponte_lock:
        if _ponte is None:
            _ponte = PonteMemoria()
        elif (not _ponte._config_explicita and _ponte._servico is None
              and not _ponte._desativada_por_erro):
            # A interface pode consultar o estado antes de outro módulo carregar
            # o .env. Enquanto a infraestrutura ainda não abriu, atualizar a
            # configuração é seguro e evita congelar um falso "flag desligada"
            # pelo resto da sessão.
            atual = carregar_config()
            if atual != _ponte.config:
                _ponte.config = atual
        return _ponte


def ponte_ativa() -> bool:
    return ponte().ativa


def ponte_completa() -> bool:
    """True só quando a memória pode substituir integralmente a legada."""

    p = ponte()
    if not p.ativa:
        return False
    # A primeira consulta precisa descobrir se Chroma realmente abre. Sem isso,
    # a ponte pareceria completa até a primeira operação e retiraria cedo demais
    # o fallback da memória antiga.
    componentes = p._pronta()
    return componentes is not None and p.ativa and not p._modo_degradado


def _reset_para_testes(nova: Optional[PonteMemoria] = None) -> None:
    global _ponte
    with _ponte_lock:
        if _ponte is not None:
            _ponte.encerrar(aguardar=False, timeout=1.0)
        _ponte = nova


__all__ = [
    "PonteMemoria",
    "dono_id",
    "id_discord",
    "ponte",
    "ponte_ativa",
    "ponte_completa",
]
