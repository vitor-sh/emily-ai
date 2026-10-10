"""Agente visual contínuo, seguro, testável e multiplataforma da Emily.

O estado mutável vive em :class:`SessaoAgenteUI`. As funções no fim do arquivo
preservam o contrato legado usado por ``main.py``, ``automacao.py`` e
``ferramentas.py``.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import unicodedata
from collections import deque
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional
from cursor_agente import CursorAgente

from desktop_backend import (
    BackendDesktop,
    ErroBackendDesktop,
    navegador_padrao_linux,
    selecionar_backend_desktop,
)


IMG_W = 1280
IMG_H = 720
MAX_PASSOS = max(1, int(os.getenv("EMILY_AGENTE_UI_MAX_PASSOS", "100")))
MAX_PASSOS_SEM_DECISAO = max(1, int(os.getenv("EMILY_AGENTE_UI_MAX_SEM_DECISAO", "3")))
TIMEOUT_SESSAO = max(5.0, float(os.getenv("EMILY_AGENTE_UI_TIMEOUT", "900")))
TIMEOUT_SEM_PROGRESSO = max(5.0, float(os.getenv("EMILY_AGENTE_UI_TIMEOUT_PROGRESSO", "180")))
INTERVALO_PASSOS = max(0.0, float(os.getenv("EMILY_AGENTE_UI_INTERVALO", "1.5")))
TIMEOUT_CONFIRMACAO_DESTRUTIVA = max(
    5.0, float(os.getenv("EMILY_AGENTE_UI_TIMEOUT_CONFIRMACAO", "120"))
)
MAX_HISTORICO = 12
MAX_CONTEXTOS = 5
MAX_TROCAS_JANELA = max(1, int(os.getenv("EMILY_AGENTE_UI_MAX_TROCAS_JANELA", "2")))

ESTADOS_FINAIS = {"concluido", "erro", "cancelado", "limite", "watchdog"}


@dataclass
class EstadoAgenteUI:
    estado: str = "parado"
    objetivo: str = ""
    action_id: str = ""  # vazio: tarefa iniciada no desktop
    passo: int = 0
    max_passos: int = MAX_PASSOS
    mensagem: str = ""
    ultima_acao: str = ""
    erro: str = ""
    iniciado_em: Optional[float] = None
    atualizado_em: float = field(default_factory=time.time)
    finalizado_em: Optional[float] = None
    backend: dict[str, Any] = field(default_factory=dict)
    historico: list[str] = field(default_factory=list)
    tempos: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def ativo(self) -> bool:
        return self.estado not in ({"parado"} | ESTADOS_FINAIS)

    def como_dict(self) -> dict[str, Any]:
        dados = asdict(self)
        dados["ativo"] = self.ativo
        return dados


DecisorUI = Callable[[Any, str, list[str], list[str], str], Optional[dict]]
VerificadorResultadoUI = Callable[[Any, str, list[str], Optional[Any]], Optional[dict]]
OuvinteEstado = Callable[[dict[str, Any]], None]


def _decisor_padrao(
    imagem: Any,
    objetivo: str,
    historico: list[str],
    contexto_telas: list[str],
    contexto_fixo: str,
    catalogo_ferramentas: Optional[list] = None,
    resultados_ferramentas: Optional[list] = None,
) -> Optional[dict]:
    import modelo
    return modelo.decidir_proxima_acao_ui(
        imagem, objetivo, historico, contexto_telas,
        contexto_fixo=contexto_fixo,
        catalogo_ferramentas=catalogo_ferramentas,
        resultados_ferramentas=resultados_ferramentas,
    )


def _verificador_resultado_padrao(
    imagem_atual: Any, objetivo: str, historico: list[str], imagem_anterior: Optional[Any],
) -> Optional[dict]:
    import modelo
    return modelo.verificar_resultado_ui(imagem_atual, objetivo, historico, imagem_anterior)


def _contexto_fixo_padrao() -> str:
    partes = []
    try:
        import modelo
        personalidade = (modelo.EMILY_PERSONALIDADE or "").strip()
        if personalidade:
            partes.append(
                "[IDENTIDADE E PERSONALIDADE DA EMILY — use apenas nas mensagens finais]\n"
                + personalidade
            )
    except Exception:
        pass
    try:
        import memoria
        memoria_txt = (memoria.formatar_para_prompt() or "").strip()
        if memoria_txt:
            partes.append("[CONTEXTO DO USUÁRIO]\n" + memoria_txt)
    except Exception:
        pass
    return "\n\n".join(partes)


class SessaoAgenteUI:
    """Uma execução do agente com estado, sincronização e dependências próprias."""

    def __init__(
        self,
        backend: Optional[BackendDesktop] = None,
        decisor: Optional[DecisorUI] = None,
        callback_falar: Optional[Callable[[str], None]] = None,
        callback_estado: Optional[OuvinteEstado] = None,
        max_passos: int = MAX_PASSOS,
        timeout_total: float = TIMEOUT_SESSAO,
        timeout_sem_progresso: float = TIMEOUT_SEM_PROGRESSO,
        intervalo_passos: float = INTERVALO_PASSOS,
        relogio: Callable[[], float] = time.monotonic,
        verificar_cliques: Optional[bool] = None,
        verificar_resultado: Optional[bool] = None,
        verificador_resultado: Optional[VerificadorResultadoUI] = None,
        timeout_confirmacao_destrutiva: float = TIMEOUT_CONFIRMACAO_DESTRUTIVA,
        renovar_limites: Optional[bool] = None,
    ) -> None:
        self.backend = backend or selecionar_backend_desktop()
        self._cursor = CursorAgente(type(self.backend).__name__ == "BackendKDEWayland")
        self.decisor = decisor or _decisor_padrao
        self.renovar_limites = (decisor is None and os.getenv("EMILY_AGENTE_UI_RENOVAR_LIMITES", "1") != "0") if renovar_limites is None else renovar_limites
        self.callback_falar = callback_falar
        self.max_passos = max(1, int(max_passos))
        self.timeout_total = max(0.01, float(timeout_total))
        self.timeout_sem_progresso = max(0.01, float(timeout_sem_progresso))
        self.intervalo_passos = max(0.0, float(intervalo_passos))
        self._relogio = relogio
        if verificar_cliques is None:
            verificar_cliques = os.getenv("EMILY_AGENTE_UI_VERIFICAR_CLIQUES", "1").strip() != "0"
        self.verificar_cliques = bool(verificar_cliques)
        # Testes/integrações com decisor injetado escolhem explicitamente a
        # auditoria; a sessão real sempre a usa.
        self.verificar_resultado = (decisor is None) if verificar_resultado is None else bool(verificar_resultado)
        self.verificador_resultado = verificador_resultado or _verificador_resultado_padrao
        self.timeout_confirmacao_destrutiva = max(0.01, float(timeout_confirmacao_destrutiva))

        self._lock = threading.RLock()
        self._cancelar = threading.Event()
        self._executar = threading.Event()
        self._executar.set()
        self._finalizou = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mensagens: queue.Queue[str] = queue.Queue()
        self._confirmacao_destrutiva_evento = threading.Event()
        self._confirmacao_destrutiva_resposta: Optional[bool] = None
        self._confirmacao_destrutiva_descricao = ""
        self._pergunta_evento = threading.Event()
        self._pergunta_descricao = ""
        self._pergunta_resposta = ""
        self._dominios_ferramentas: set[str] = set()
        self._resultados_ferramentas: deque[str] = deque(maxlen=6)
        self._espera_inicio = 0.0
        self._espera_nivel = 0
        self._orcamento_tempo = self.timeout_total
        self._progresso_tempo = 0
        self._progresso_passos = 0
        self._falhas_operacionais = 0
        self._aguarda_progresso_visual = False
        self._destrutivas_negadas: set[str] = set()
        self._ouvintes: list[OuvinteEstado] = []
        if callback_estado:
            self._ouvintes.append(callback_estado)

        self._historico: deque[str] = deque(maxlen=MAX_HISTORICO)
        self._contexto_telas: deque[str] = deque(maxlen=MAX_CONTEXTOS)
        self._assinatura_anterior = ""
        self._ultimo_tipo_assinatura = ""
        self._repeticoes = 0
        self._trocas_janela = 0
        self._apps_lancados: set[str] = set()
        self._foco_pendente = False
        self._inicio_mono = 0.0
        self._ultimo_progresso = 0.0
        self._contexto_fixo = ""
        self._imagem_antes_ultima_acao: Optional[Any] = None
        self._verificacoes_finais_recusadas = 0
        self.estado = EstadoAgenteUI(max_passos=self.max_passos)

    # ── observabilidade ──────────────────────────────────────────

    def adicionar_ouvinte(self, callback: OuvinteEstado) -> None:
        if not callback:
            return
        with self._lock:
            if callback not in self._ouvintes:
                self._ouvintes.append(callback)

    def remover_ouvinte(self, callback: OuvinteEstado) -> None:
        with self._lock:
            if callback in self._ouvintes:
                self._ouvintes.remove(callback)

    def retrato(self) -> dict[str, Any]:
        with self._lock:
            if not self.estado.backend:
                try:
                    self.estado.backend = self.backend.capacidades().como_dict()
                except Exception as exc:  # noqa: BLE001
                    self.estado.backend = {
                        "nome": type(self.backend).__name__,
                        "captura": False,
                        "entrada": False,
                        "janelas": False,
                        "motivo_indisponivel": str(exc),
                    }
            self.estado.historico = list(self._historico)
            dados = self.estado.como_dict()
            dados["tipo_pergunta"] = "duvida" if self._pergunta_descricao else "confirmacao" if self._confirmacao_destrutiva_descricao else ""
            return dados

    @contextmanager
    def _medir(self, fase: str):
        """Tempos agregados da sessão; não guarda imagens, comandos ou prompts.

        execução inclui verificações de clique; suas fases internas são detalhadas
        separadamente. Portanto os totais das fases não devem ser somados.
        """
        inicio = time.perf_counter()
        try:
            yield
        finally:
            duracao = time.perf_counter() - inicio
            with self._lock:
                dado = self.estado.tempos.setdefault(fase, {
                    "chamadas": 0, "total_s": 0.0, "ultima_s": 0.0,
                })
                dado["chamadas"] += 1
                dado["total_s"] += duracao
                dado["ultima_s"] = duracao

    def _pausa_apos_acao(self, decisao: dict, sucesso: bool) -> float:
        # Menos espera só para entrada local simples e ferramentas concluídas.
        # Enter/Tab/atalhos podem navegar, trocar foco ou iniciar carregamentos.
        # Nesses casos conservamos a pausa original, inclusive após falhas.
        if sucesso:
            tipo = str(decisao.get("acao") or "").strip().lower()
            if tipo in {"digitar", "digitar_unicode", "apagar_tudo"}:
                return min(self.intervalo_passos, 0.15)
            if tipo == "ferramenta":
                # O catálogo já descreve o efeito, sem inferir pela frase humana.
                # Ferramentas de leitura não abrem/trocam janelas. Comandos livres
                # podem iniciar apps; conservar sua pausa é o lado seguro.
                import ferramentas
                ferramenta = ferramentas.CATALOGO.get(str(decisao.get("ferramenta") or decisao.get("nome") or ""))
                if ferramenta and ferramenta.somente_leitura:
                    return min(self.intervalo_passos, 0.15)
            if tipo == "pressionar" and str(decisao.get("texto") or "").lower() in {"backspace", "delete", "left", "right", "home", "end"}:
                return min(self.intervalo_passos, 0.15)
            if tipo == "esperar":
                return 0.0  # já esperou explicitamente; não duplicar a espera
        return self.intervalo_passos

    def _publicar(self) -> None:
        retrato = self.retrato()
        with self._lock:
            ouvintes = list(self._ouvintes)
        for callback in ouvintes:
            try:
                callback(retrato)
            except Exception as exc:  # noqa: BLE001
                print(f"[AGENTE_UI] ouvinte de estado falhou: {exc}")

    def _mudar_estado(self, estado: str, mensagem: str = "", erro: str = "") -> None:
        with self._lock:
            self.estado.estado = estado
            self.estado.mensagem = mensagem
            self.estado.erro = erro
            self.estado.atualizado_em = time.time()
            if estado in ESTADOS_FINAIS:
                self.estado.finalizado_em = self.estado.atualizado_em
            if estado in ESTADOS_FINAIS or estado in {"parado", "pausado", "cancelando", "aguardando_confirmacao"}:
                self._cursor.restaurar()
            elif not self._cancelar.is_set() and self._executar.is_set():
                self._cursor.ativar()
        self._publicar()

    def _registrar(self, texto: str, progresso: bool = False) -> None:
        texto = str(texto).strip()
        if not texto:
            return
        with self._lock:
            self._historico.append(texto)
            if progresso:
                self._ultimo_progresso = self._relogio()
                self._progresso_tempo += 1
                self._progresso_passos += 1

    def _falar(self, texto: str) -> None:
        if not texto:
            return
        if self.callback_falar:
            try:
                self.callback_falar(texto)
                return
            except Exception as exc:  # noqa: BLE001
                print(f"[AGENTE_UI] callback de fala falhou: {exc}")
        print(f"[AGENTE_UI] {texto}")

    # ── ciclo de vida ────────────────────────────────────────────

    def iniciar(self, objetivo: str, em_thread: bool = True, action_id: str = "") -> bool:
        objetivo = (objetivo or "").strip()
        if not objetivo:
            raise ValueError("objetivo vazio")
        with self._lock:
            # Um callback pode pedir nova sessão ao receber o estado final,
            # antes de o finally anterior restaurar o cursor/fechar o backend.
            if self.estado.ativo or (self.estado.estado in ESTADOS_FINAIS and not self._finalizou.is_set()):
                return False
            capacidades = self.backend.capacidades()
            if not capacidades.captura or not capacidades.entrada:
                motivo = capacidades.motivo_indisponivel or "backend desktop incompleto"
                self.estado.backend = capacidades.como_dict()
                self._mudar_estado("erro", motivo, motivo)
                self._finalizou.set()
                return False
            self._cancelar.clear()
            self._executar.set()
            self._finalizou.clear()
            self._historico.clear()
            self._contexto_telas.clear()
            self._imagem_antes_ultima_acao = None
            self._verificacoes_finais_recusadas = 0
            self._confirmacao_destrutiva_evento.clear()
            self._confirmacao_destrutiva_resposta = None
            self._confirmacao_destrutiva_descricao = ""
            self._pergunta_evento.clear()
            self._pergunta_descricao = ""
            self._pergunta_resposta = ""
            self._dominios_ferramentas.clear()
            self._resultados_ferramentas.clear()
            self._espera_nivel = 0
            self._orcamento_tempo = self.timeout_total
            self._progresso_tempo = self._progresso_passos = 0
            self._falhas_operacionais = 0
            self._aguarda_progresso_visual = False
            self._destrutivas_negadas.clear()
            while True:
                try:
                    self._mensagens.get_nowait()
                except queue.Empty:
                    break
            self._assinatura_anterior = ""
            self._ultimo_tipo_assinatura = ""
            self._repeticoes = 0
            self._trocas_janela = 0
            self._apps_lancados.clear()
            self._foco_pendente = False
            self._inicio_mono = self._relogio()
            self._ultimo_progresso = self._inicio_mono
            self._contexto_fixo = _contexto_fixo_padrao()
            self.estado = EstadoAgenteUI(
                estado="iniciando",
                objetivo=objetivo,
                action_id=action_id,
                max_passos=self.max_passos,
                iniciado_em=time.time(),
                backend=capacidades.como_dict(),
            )
        self._publicar()
        if em_thread:
            self._thread = threading.Thread(
                target=self.executar,
                name="emily-agente-ui",
                daemon=True,
            )
            self._thread.start()
        else:
            self.executar()
        return True

    def executar(self) -> dict[str, Any]:
        try:
            self._mudar_estado("rodando", "Analisando a tela")
            for passo in self._passos():
                with self._lock:
                    self.estado.passo = passo
                motivo_watchdog = self._motivo_watchdog()
                if motivo_watchdog:
                    if not self._orientar_apos_limite(motivo_watchdog):
                        self._encerrar_watchdog(motivo_watchdog)
                        break
                if not self._aguardar_retomada():
                    self._encerrar_cancelada()
                    break
                self._consumir_mensagens()

                self._mudar_estado("capturando", f"Capturando a tela ({passo}/{self.max_passos})")
                try:
                    with self._medir("captura"):
                        imagem = self.backend.capturar_tela_com_grade()
                except Exception as exc:  # noqa: BLE001
                    self._encerrar_erro(f"Não consegui capturar a tela: {exc}")
                    break
                if self._aguarda_progresso_visual:
                    if imagem != self._imagem_antes_ultima_acao:
                        self._registrar("PROGRESSO VISUAL: a captura mudou após a ação; conferir o conteúdo.", progresso=True)
                    self._aguarda_progresso_visual = False
                if self._cancelar.is_set():
                    self._encerrar_cancelada()
                    break
                if not self._aguardar_retomada():
                    self._encerrar_cancelada()
                    break

                self._mudar_estado("decidindo", f"Decidindo o passo {passo}")
                decisao = self._decidir(imagem)
                if self._cancelar.is_set():
                    self._encerrar_cancelada()
                    break
                if not self._aguardar_retomada():
                    self._encerrar_cancelada()
                    break
                motivo_watchdog = self._motivo_watchdog()
                if motivo_watchdog:
                    if not self._orientar_apos_limite(motivo_watchdog):
                        self._encerrar_watchdog(motivo_watchdog)
                        break
                    # A resposta pode mudar o objetivo: descarte a decisão antiga.
                    continue
                if not decisao:
                    if self._falhas_decisao_consecutivas() >= MAX_PASSOS_SEM_DECISAO:
                        self._encerrar_erro("O modelo não devolveu uma decisão válida.")
                        break
                    continue

                tipo = str(decisao.get("acao") or "").strip().lower()
                if tipo == "concluido":
                    if self.verificar_resultado:
                        with self._medir("auditoria_final"):
                            confirmado, detalhe = self._auditar_conclusao()
                        if not confirmado:
                            self._verificacoes_finais_recusadas += 1
                            self._registrar(
                                f"AUDITORIA FINAL: resultado não comprovado — {detalhe}. "
                                "Continue a tarefa ou informe que não foi possível confirmar."
                            )
                            if self._verificacoes_finais_recusadas >= 3:
                                if self.renovar_limites and self._orientar_apos_limite(
                                    "Não consegui comprovar a conclusão após três verificações: " + detalhe):
                                    self._verificacoes_finais_recusadas = 0
                                    continue
                                self._encerrar_erro(
                                    "Não consegui confirmar na tela que a tarefa foi concluída: "
                                    + detalhe
                                )
                                break
                            continue
                    mensagem = str(decisao.get("mensagem") or "Pronto, terminei!")
                    self._mudar_estado("concluido", mensagem)
                    self._falar(mensagem)
                    break
                if tipo == "erro":
                    self._encerrar_erro(str(decisao.get("mensagem") or "Não consegui continuar."))
                    break

                assinatura = self._assinatura_acao(decisao)
                if self._eh_repeticao_bloqueada(assinatura, decisao, passo):
                    self._falhas_operacionais += 1
                    continue

                descricao = str(decisao.get("descricao") or tipo)
                with self._lock:
                    self.estado.ultima_acao = descricao
                self._mudar_estado("executando", descricao)
                with self._medir("execucao"):
                    sucesso, detalhe = self._executar_acao(decisao)
                if sucesso:
                    self._falhas_operacionais = 0
                    acao_util = tipo not in {"esperar", "mover_mouse"}
                    progresso = acao_util and (not self.renovar_limites or tipo == "ferramenta")
                    self._registrar(f"Passo {passo}: OK — {descricao}", progresso=progresso)
                    if acao_util:
                        self._imagem_antes_ultima_acao = imagem
                        self._aguarda_progresso_visual = self.renovar_limites and tipo != "ferramenta"
                        self._verificacoes_finais_recusadas = 0
                    if tipo in {"trocar_janela", "abrir_app", "clicar_tarefa", "ativar_janela"}:
                        self._contexto_telas.append(f"Passo {passo}: {descricao}")
                else:
                    self._falhas_operacionais += 1
                    mensagem_falha = detalhe or descricao
                    self._registrar(
                        f"Passo {passo}: FALHA em {tipo} — {mensagem_falha}. "
                        "Tente uma abordagem diferente.",
                    )
                    # A falha operacional precisa aparecer no painel enquanto o
                    # agente decide a alternativa; antes ela existia somente no
                    # histórico enviado ao modelo e parecia que nada acontecia.
                    with self._lock:
                        self.estado.mensagem = f"Falha ao executar {tipo}"
                        self.estado.erro = mensagem_falha
                        self.estado.atualizado_em = time.time()
                self._publicar()
                pausa = self._pausa_apos_acao(decisao, sucesso)
                if pausa and not self.backend.esperar(pausa, self._cancelar):
                    self._encerrar_cancelada()
                    break
            else:
                if self._cancelar.is_set():
                    self._encerrar_cancelada()
                else:
                    mensagem = f"Atingi o limite de {self.estado.max_passos} passos sem concluir."
                    self._mudar_estado("limite", mensagem, mensagem)
                    self._falar(mensagem)
        except Exception as exc:  # noqa: BLE001
            self._encerrar_erro(f"Falha inesperada no agente: {type(exc).__name__}: {exc}")
        finally:
            self._cursor.restaurar()
            try:
                self.backend.fechar()
            except Exception:
                pass
            self._finalizou.set()
        return self.retrato()

    def pausar(self) -> bool:
        with self._lock:
            if not self.estado.ativo or not self._executar.is_set():
                return False
            self._executar.clear()
            self._iniciar_espera()
        self._mudar_estado("pausado", "Agente pausado")
        return True

    def retomar(self) -> bool:
        with self._lock:
            if not self.estado.ativo or self._executar.is_set():
                return False
            # O tempo pausado não conta como ausência de progresso.
            self._terminar_espera()
            self._executar.set()
        self._mudar_estado("rodando", "Continuando")
        return True

    def cancelar(self) -> bool:
        with self._lock:
            if not self.estado.ativo:
                return False
            self._cancelar.set()
            self._executar.set()
        self._mudar_estado("cancelando", "Cancelando o agente")
        return True

    def aguardar(self, timeout: Optional[float] = None) -> bool:
        return self._finalizou.wait(timeout)

    def enviar_mensagem(self, mensagem: str) -> bool:
        mensagem = (mensagem or "").strip()
        if not mensagem or not self.retrato()["ativo"]:
            return False
        with self._lock:
            if self._pergunta_descricao:
                self._pergunta_resposta = mensagem
                self._pergunta_evento.set()
                return True
            confirmacao_pendente = bool(self._confirmacao_destrutiva_descricao)
        if confirmacao_pendente:
            resposta = self._ler_confirmacao_explicita(mensagem)
            if resposta is None:
                self._registrar(
                    "CONFIRMAÇÃO DESTRUTIVA AMBÍGUA: responda exatamente 'sim, confirmo' "
                    "ou 'não, cancelar'."
                )
                self._mudar_estado(
                    "aguardando_confirmacao",
                    "Resposta ambígua. Diga 'sim, confirmo' ou 'não, cancelar'.",
                )
                return True
            with self._lock:
                self._confirmacao_destrutiva_resposta = resposta
                self._confirmacao_destrutiva_evento.set()
            return True
        self._mensagens.put(mensagem)
        return True

    # ── watchdog e decisão ───────────────────────────────────────

    def _aguardar_retomada(self) -> bool:
        while not self._executar.wait(0.1):
            if self._cancelar.is_set():
                return False
        return not self._cancelar.is_set()

    def _motivo_watchdog(self) -> str:
        if self._espera_nivel:
            return ""
        agora = self._relogio()
        if agora - self._ultimo_progresso > self.timeout_sem_progresso:
            return f"Sem progresso por mais de {self.timeout_sem_progresso:.0f}s"
        if self._falhas_operacionais >= 5:
            return "Cinco ações falharam consecutivamente; preciso mudar a abordagem"
        if agora - self._inicio_mono > self._orcamento_tempo:
            if self.renovar_limites and self._progresso_tempo > 0 and self._falhas_operacionais < 3:
                self._orcamento_tempo = agora - self._inicio_mono + self.timeout_total
                self._progresso_tempo = 0
                self._registrar("TEMPO RENOVADO: houve progresso; continuando a mesma tarefa.")
            else:
                return f"Tempo total excedeu {self._orcamento_tempo:.0f}s sem progresso suficiente"
        return ""

    def _iniciar_espera(self) -> None:
        with self._lock:
            if self._espera_nivel == 0:
                self._espera_inicio = self._relogio()
            self._espera_nivel += 1

    def _terminar_espera(self) -> None:
        with self._lock:
            if self._espera_nivel <= 0:
                return
            self._espera_nivel -= 1
            if self._espera_nivel == 0:
                duracao = max(0.0, self._relogio() - self._espera_inicio)
                self._inicio_mono += duracao
                self._ultimo_progresso += duracao

    def _passos(self):
        passo = 0
        while not self._cancelar.is_set():
            if passo >= self.estado.max_passos:
                if not self.renovar_limites:
                    return
                if not (self._progresso_passos > 0 and self._falhas_operacionais < 3):
                    if not self._orientar_apos_limite("Cheguei ao checkpoint de passos sem progresso suficiente"):
                        return
                with self._lock:
                    self.estado.max_passos += self.max_passos
                    self._progresso_passos = 0
                self._registrar("PASSOS RENOVADOS: continuando a tarefa existente, sem reiniciá-la.")
            passo += 1
            yield passo

    def _orientar_apos_limite(self, motivo: str) -> bool:
        if not self.renovar_limites or self._cancelar.is_set():
            return False
        ok, resposta = self._perguntar_vitor(
            motivo + ". Quer que eu continue tentando? Pode responder sim ou orientar outra abordagem.", "problema")
        if not ok or self._ler_confirmacao_explicita(resposta) is False:
            return False
        self._inicio_mono = self._ultimo_progresso = self._relogio()
        self._orcamento_tempo = self.timeout_total
        self._falhas_operacionais = 0
        self._registrar("ORIENTAÇÃO NO CHECKPOINT: " + resposta)
        self._mensagens.put(resposta)
        return True

    def _encerrar_watchdog(self, motivo: str) -> None:
        self._mudar_estado("watchdog", motivo, motivo)
        self._falar(f"Parei por segurança: {motivo}.")

    def _encerrar_cancelada(self) -> None:
        self._mudar_estado("cancelado", "Cancelado pelo usuário")

    def _encerrar_erro(self, mensagem: str) -> None:
        self._mudar_estado("erro", mensagem, mensagem)
        self._falar(mensagem)

    def _consumir_mensagens(self) -> None:
        while True:
            try:
                mensagem = self._mensagens.get_nowait()
            except queue.Empty:
                return
            self._registrar(
                f"INSTRUÇÃO AO VIVO DO USUÁRIO: {mensagem}. Ajuste o próximo passo imediatamente.",
                progresso=True,
            )

    @staticmethod
    def _texto_normalizado(texto: Any) -> str:
        texto = unicodedata.normalize("NFKD", str(texto or "").strip().lower())
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        return " ".join("".join(c if c.isalnum() else " " for c in texto).split())

    def _nome_app_decidido(self, nome: str) -> str:
        """Corrige navegador presumido pelo modelo, respeitando pedido explícito."""
        chave = self._texto_normalizado(nome)
        nomes = {
            "chrome": ("chrome", "google chrome"),
            "edge": ("edge", "microsoft edge"),
            "firefox": ("firefox",),
            "brave": ("brave", "brave browser"),
        }
        familia = next((f for f, aliases in nomes.items() if chave in aliases), "")
        if not familia:
            return nome
        objetivo = self._texto_normalizado(self.estado.objetivo)
        if any(alias in objetivo.split(" ") for alias in nomes[familia]):
            return nome
        padrao, _ = navegador_padrao_linux()
        return "navegador padrão" if padrao and padrao.casefold() != familia else nome

    @classmethod
    def _ler_confirmacao_explicita(cls, mensagem: str) -> Optional[bool]:
        """Aceita somente respostas inequívocas; texto ambíguo nunca libera a ação."""
        texto = cls._texto_normalizado(mensagem)
        positivas = {
            "sim", "sim confirmo", "confirmo", "pode confirmar", "pode executar",
            "pode prosseguir", "autorizo", "eu autorizo", "sim pode",
        }
        negativas = {
            "nao", "nao cancelar", "cancelar", "cancela", "nao confirmo",
            "nao execute", "nao pode", "pare", "parar",
        }
        if texto in positivas:
            return True
        if texto in negativas:
            return False
        return None

    def _decidir(self, imagem: Any) -> Optional[dict]:
        for tentativa in range(1, 4):
            try:
                extras = {}
                if self.decisor is _decisor_padrao:
                    from agente_ui_catalogo import catalogo
                    extras["catalogo_ferramentas"] = (
                        [] if isinstance(imagem, (list, tuple)) and len(imagem) > 1
                        else catalogo(self._dominios_ferramentas)
                    )
                    extras["resultados_ferramentas"] = list(self._resultados_ferramentas)
                fase = "modelo_verificacao" if isinstance(imagem, (list, tuple)) and len(imagem) > 1 else "modelo_decisao"
                with self._medir(fase):
                    decisao = self.decisor(
                        imagem,
                        self.estado.objetivo,
                        (list(self._resultados_ferramentas) if not extras else []) + list(self._historico),
                        list(self._contexto_telas),
                        self._contexto_fixo,
                        **extras,
                    )
            except Exception as exc:  # noqa: BLE001
                decisao = None
                print(f"[AGENTE_UI] decisão falhou ({tentativa}/3): {exc}")
            if isinstance(decisao, dict) and decisao.get("acao"):
                return decisao
            if tentativa < 3 and not self.backend.esperar(0.05, self._cancelar):
                return None
        self._registrar("FALHA: modelo não retornou JSON de ação válido")
        return None

    def _falhas_decisao_consecutivas(self) -> int:
        total = 0
        for item in reversed(self._historico):
            if item.startswith("FALHA: modelo"):
                total += 1
            else:
                break
        return total

    def _auditar_conclusao(self) -> tuple[bool, str]:
        self._mudar_estado("verificando", "Conferindo se a tarefa terminou de verdade")
        try:
            imagem_atual = self.backend.capturar_tela()
            resultado = self.verificador_resultado(
                imagem_atual, self.estado.objetivo, list(self._resultados_ferramentas) + list(self._historico),
                self._imagem_antes_ultima_acao,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"falha na verificação visual: {exc}"
        if self._cancelar.is_set():
            return False, "verificação cancelada"
        if not isinstance(resultado, dict):
            return False, "verificador não devolveu um resultado válido"
        try:
            confianca = float(resultado.get("confianca", 0))
        except (TypeError, ValueError):
            confianca = 0.0
        evidencia = str(resultado.get("evidencia") or "").strip()
        if resultado.get("concluido") is True and confianca >= 0.8 and len(evidencia) >= 12:
            rotulo = "RESULTADO CONFIRMADO POR FERRAMENTA" if resultado.get("fonte") == "ferramenta" else "RESULTADO VISÍVEL CONFIRMADO"
            self._registrar(f"{rotulo}: {evidencia}", progresso=True)
            return True, evidencia
        detalhe = str(resultado.get("proximo_passo") or evidencia or "sem evidência suficiente").strip()
        return False, detalhe

    @staticmethod
    def _assinatura_acao(decisao: dict) -> str:
        campos = {
            "acao": decisao.get("acao"),
            "celula": str(decisao.get("celula") or "").upper(),
            "offset_x": decisao.get("offset_x"),
            "offset_y": decisao.get("offset_y"),
            "x": decisao.get("x"),
            "y": decisao.get("y"),
            "texto": decisao.get("texto"),
            "direcao": decisao.get("direcao"),
            "ferramenta": decisao.get("ferramenta") or decisao.get("nome"),
            "argumentos": decisao.get("argumentos"),
        }
        return json.dumps(campos, ensure_ascii=False, sort_keys=True, default=str)

    def _eh_repeticao_bloqueada(self, assinatura: str, decisao: dict, passo: int) -> bool:
        # Pausar ou posicionar o cursor não torna um terceiro clique no mesmo
        # alvo mais confiável. Preserve a assinatura através dessas ações.
        tipo = str(decisao.get("acao") or "").lower()
        if (tipo in {"esperar", "mover_mouse"}
                and self._ultimo_tipo_assinatura in {
                    "clicar", "clicar_celula", "clicar_tarefa", "clicar_direito", "duplo_clique",
                }):
            return False
        if assinatura == self._assinatura_anterior:
            self._repeticoes += 1
        else:
            self._assinatura_anterior = assinatura
            self._ultimo_tipo_assinatura = tipo
            self._repeticoes = 1
            return False
        if self._repeticoes < 3:
            return False
        tipo = str(decisao.get("acao") or "ação")
        self._registrar(
            f"Passo {passo}: ⚠️ LOOP DETECTADO — ANTI-LOOP: a mesma ação estrutural "
            f"'{tipo}' foi pedida "
            f"{self._repeticoes} vezes. Não a execute novamente; avance ou tente outra abordagem.",
        )
        self._publicar()
        return True

    # ── tradução de ações ────────────────────────────────────────

    @staticmethod
    def _coordenada_grade(
        celula: str, offset_x: Any = 50, offset_y: Any = 50,
    ) -> tuple[Optional[float], Optional[float]]:
        """Converte célula + offsets em proporções normalizadas da saída (0–1)."""
        celula = str(celula or "").strip().upper()
        if len(celula) < 2 or celula[0] not in "ABCDEFGHIJ" or not celula[1:].isdigit():
            return None, None
        coluna = ord(celula[0]) - ord("A")
        linha = int(celula[1:])
        if not 0 <= linha <= 9:
            return None, None
        try:
            proporcao_x = min(100.0, max(0.0, float(offset_x))) / 100.0
            proporcao_y = min(100.0, max(0.0, float(offset_y))) / 100.0
        except (TypeError, ValueError):
            return None, None
        return (
            (coluna + proporcao_x) / 10.0,
            (linha + proporcao_y) / 10.0,
        )

    def _coordenadas(self, decisao: dict) -> tuple[Optional[int], Optional[int]]:
        proporcao_x, proporcao_y = self._coordenada_grade(
            decisao.get("celula", ""),
            decisao.get("offset_x", 50),
            decisao.get("offset_y", 50),
        )
        geometria = self.backend.geometria()
        esquerda = int(geometria.get("left", 0))
        topo = int(geometria.get("top", 0))
        largura = max(1, int(geometria["width"]))
        altura = max(1, int(geometria["height"]))

        if proporcao_x is not None and proporcao_y is not None:
            # A grade é normalizada, portanto independe do tamanho em pixels do
            # PNG e funciona igualmente em 16:9, 5:4 e saídas escaladas. O clamp
            # é necessário porque J9 + offset 100 representa a borda externa.
            # O epsilon só neutraliza resíduos binários como 0.35*1440 =
            # 503.99999999999994; não arredonda posições genuinamente fracionárias.
            rx = esquerda + min(largura - 1, max(0, int(proporcao_x * largura + 1e-9)))
            ry = topo + min(altura - 1, max(0, int(proporcao_y * altura + 1e-9)))
            return rx, ry

        if "x" in decisao and "y" in decisao:
            try:
                x, y = int(decisao["x"]), int(decisao["y"])
            except (TypeError, ValueError):
                return None, None
            # Compatibilidade com respostas legadas em coordenadas 1280x720.
            rx = esquerda + min(largura - 1, max(0, int(x * largura / IMG_W)))
            ry = topo + min(altura - 1, max(0, int(y * altura / IMG_H)))
            return rx, ry
        return None, None

    @staticmethod
    def _tem_offsets_finos(decisao: dict) -> bool:
        """No modo verificado, centro implícito de célula não é preciso o bastante."""
        return (
            ("offset_x" in decisao and "offset_y" in decisao)
            or ("x" in decisao and "y" in decisao)
        )

    @classmethod
    def _eh_acao_destrutiva(cls, decisao: dict) -> bool:
        """Reconhece a confirmação final destrutiva mesmo se a flag for omitida."""
        if decisao.get("destrutiva") is True:
            return True
        descricao = cls._texto_normalizado(
            " ".join(str(decisao.get(campo) or "") for campo in ("descricao", "texto"))
        )
        termos_finais = (
            "confirmar desinstalacao", "desinstalar agora", "confirmar exclusao",
            "excluir permanentemente", "apagar permanentemente", "remover definitivamente",
            "excluir definitivamente", "apagar definitivamente", "esvaziar lixeira",
            "formatar disco", "deletar conta", "excluir conta definitivamente",
        )
        return any(termo in descricao for termo in termos_finais)

    def _autorizar_acao_destrutiva(self, decisao: dict) -> tuple[bool, str]:
        if not self._eh_acao_destrutiva(decisao):
            return True, ""

        descricao = str(decisao.get("descricao") or decisao.get("texto") or "ação destrutiva").strip()
        chave = self._texto_normalizado(descricao)
        if chave in self._destrutivas_negadas:
            return False, "ação destrutiva já negada pelo usuário nesta sessão"

        with self._lock:
            self._confirmacao_destrutiva_descricao = descricao
            self._confirmacao_destrutiva_resposta = None
            self._confirmacao_destrutiva_evento.clear()
        pergunta = (
            f"A ação '{descricao}' pode apagar ou remover dados. "
            "Confirma a execução? Responda 'sim, confirmo' ou 'não, cancelar'."
        )
        self._registrar(f"CONFIRMAÇÃO HUMANA NECESSÁRIA: {descricao}")
        self._mudar_estado("aguardando_confirmacao", pergunta)
        self._falar(pergunta)

        detalhe = ""
        limite = time.monotonic() + self.timeout_confirmacao_destrutiva
        while not self._confirmacao_destrutiva_evento.wait(0.1):
            if self._cancelar.is_set():
                detalhe = "cancelada enquanto aguardava confirmação humana"
                break
            if time.monotonic() >= limite:
                detalhe = "confirmação humana expirou; ação destrutiva cancelada"
                break
        else:
            with self._lock:
                resposta = self._confirmacao_destrutiva_resposta
            if resposta is True:
                self._registrar(f"AÇÃO DESTRUTIVA AUTORIZADA explicitamente: {descricao}")
            else:
                detalhe = "ação destrutiva negada pelo usuário"
                self._destrutivas_negadas.add(chave)

        with self._lock:
            self._confirmacao_destrutiva_descricao = ""
            self._confirmacao_destrutiva_resposta = None
            self._confirmacao_destrutiva_evento.clear()
        if not detalhe and not self._cancelar.is_set():
            self._mudar_estado("executando", "Executando a ação autorizada")
        return not detalhe, detalhe

    def _clicar_com_verificacao(
        self,
        decisao: dict,
        x: int,
        y: int,
        *,
        botao: str = "left",
        cliques: int = 1,
    ) -> tuple[bool, str]:
        """Aponta, observa novamente e só então libera o clique real."""
        destrutiva = self._eh_acao_destrutiva(decisao)
        if (self.verificar_cliques or destrutiva) and not self._tem_offsets_finos(decisao):
            return False, (
                "clique recusado: faltam offset_x e offset_y para apontar o centro "
                "exato do elemento"
            )
        autorizado, detalhe = self._autorizar_acao_destrutiva(decisao)
        if not autorizado:
            return False, detalhe
        # O fluxo de voz pausa a sessão antes de encaminhar a resposta do usuário.
        # Mesmo autorizada, a ação não pode se aproveitar da corrida entre
        # enviar_mensagem() e retomar(): nenhum movimento ocorre enquanto pausada.
        if not self._aguardar_retomada():
            return False, "cancelada antes de executar a ação destrutiva autorizada"
        if not self.verificar_cliques:
            self.backend.mover(x, y, 0.2)
            self.backend.clicar(x, y, botao=botao, cliques=cliques)
            return True, ""

        descricao = str(decisao.get("descricao") or "elemento solicitado").strip()
        alvo_x, alvo_y = int(x), int(y)
        geometria_original = self.backend.geometria()
        for tentativa in range(1, 3):
            self.backend.mover(alvo_x, alvo_y, 0.25)
            if not self.backend.esperar(0.18, self._cancelar):
                return False, "cancelada antes da verificação visual do clique"
            with self._medir("captura_verificacao"):
                imagens = self.backend.capturar_tela_para_verificacao(alvo_x, alvo_y)
            if self.backend.geometria() != geometria_original:
                return False, "monitor ou resolução mudou durante a verificação; clique cancelado"
            instrucao = (
                f"VERIFICAÇÃO DE CLIQUE {tentativa}/2: o cursor e o marcador magenta "
                f"estão no ponto proposto para '{descricao}'. A primeira imagem é a "
                "tela geral e a segunda é um zoom do alvo. Confirme somente se o centro "
                "do marcador estiver dentro do elemento descrito."
            )
            self._historico.append(instrucao)
            self._mudar_estado("verificando", f"Conferindo o alvo: {descricao}")
            verificacao = self._decidir(imagens)
            if self._cancelar.is_set():
                return False, "cancelada durante a verificação visual do clique"
            if not verificacao:
                return False, "modelo não devolveu confirmação visual válida"

            tipo_verificacao = str(verificacao.get("acao") or "").strip().lower()
            if tipo_verificacao == "confirmar_clique":
                confere = verificacao.get("alvo_confere") is True
                try:
                    confianca = float(verificacao.get("confianca", 0))
                except (TypeError, ValueError):
                    confianca = 0.0
                if not confere or confianca < 0.75:
                    return False, (
                        f"modelo não confirmou o alvo com segurança "
                        f"(confiança {confianca:.2f})"
                    )
                if self.backend.geometria() != geometria_original:
                    return False, "monitor ou resolução mudou antes do clique; clique cancelado"
                self.backend.clicar(alvo_x, alvo_y, botao=botao, cliques=cliques)
                self._historico.append(
                    f"ALVO CONFIRMADO visualmente para '{descricao}' "
                    f"(confiança {confianca:.2f})."
                )
                return True, ""

            if tipo_verificacao in {"clicar", "clicar_celula", "clicar_direito", "duplo_clique"}:
                if not self._tem_offsets_finos(verificacao):
                    return False, "relocalização recusada: offsets finos ausentes"
                novo_x, novo_y = self._coordenadas(verificacao)
                if novo_x is None or novo_y is None:
                    return False, "relocalização visual devolveu coordenadas inválidas"
                alvo_x, alvo_y = novo_x, novo_y
                self._historico.append(
                    f"RELOCALIZAÇÃO: o primeiro ponto não cobria '{descricao}'; "
                    "uma nova posição será verificada antes do clique."
                )
                continue

            if tipo_verificacao == "ajustar_clique_zoom":
                try:
                    novo_x, novo_y = self.backend.coordenada_no_zoom(
                        float(verificacao["zoom_x"]), float(verificacao["zoom_y"]),
                    )
                except (KeyError, TypeError, ValueError, ErroBackendDesktop) as exc:
                    return False, f"ajuste pelo zoom inválido: {exc}"
                alvo_x, alvo_y = novo_x, novo_y
                self._historico.append(
                    f"AJUSTE PELO ZOOM: centro de '{descricao}' relocalizado; "
                    "verificando novamente antes do clique."
                )
                continue

            motivo = str(verificacao.get("mensagem") or verificacao.get("descricao") or "")
            return False, f"alvo visual não confirmado{': ' + motivo if motivo else ''}"

        return False, "alvo não confirmado após a relocalização; clique cancelado"

    def _executar_acao(self, decisao: dict) -> tuple[bool, str]:
        tipo = str(decisao.get("acao") or "").strip().lower()
        texto = str(decisao.get("texto") or "")
        x, y = self._coordenadas(decisao)
        precisa_xy = {"clicar", "clicar_celula", "clicar_tarefa", "clicar_direito",
                      "duplo_clique", "mover_mouse"}
        if tipo in precisa_xy and (x is None or y is None):
            return False, "coordenadas ausentes ou inválidas"
        try:
            if self._foco_pendente and tipo in {"digitar", "digitar_unicode", "pressionar", "apagar_tudo", "atalho"}:
                if x is not None and y is not None:
                    ok, detalhe = self._clicar_com_verificacao(decisao, x, y)
                    if not ok:
                        return False, detalhe
                    self._foco_pendente = False
                else:
                    return False, "Foco anterior não confirmado. Localize/clique na janela pretendida ou ative-a antes de enviar teclado; não envie atalhos para outra janela."
            if tipo in {"clicar", "clicar_celula"}:
                resultado = self._clicar_com_verificacao(decisao, x, y)
                if resultado[0]:
                    self._foco_pendente = False
                return resultado
            elif tipo == "clicar_direito":
                return self._clicar_com_verificacao(decisao, x, y, botao="right")
            elif tipo == "duplo_clique":
                return self._clicar_com_verificacao(decisao, x, y, cliques=2)
            elif tipo == "mover_mouse":
                self.backend.mover(x, y, 0.3)
            elif tipo == "digitar" or tipo == "digitar_unicode":
                if x is not None and y is not None:
                    ok, detalhe = self._clicar_com_verificacao(decisao, x, y)
                    if not ok:
                        return False, detalhe
                self.backend.digitar(texto, 0.04)
            elif tipo == "pressionar":
                self.backend.pressionar(texto, int(decisao.get("vezes", 1)))
            elif tipo == "apagar_tudo":
                self.backend.atalho(("ctrl", "a"))
                self.backend.pressionar("backspace")
            elif tipo == "atalho":
                teclas = tuple(t.strip() for t in texto.split("+") if t.strip())
                if not teclas:
                    return False, "atalho vazio"
                if tuple(t.lower() for t in teclas) == ("alt", "tab"):
                    if self._trocas_janela >= MAX_TROCAS_JANELA:
                        return False, (
                            "limite de alternâncias de janela atingido; use ativar_janela, "
                            "clicar_tarefa ou clique diretamente no aplicativo já visível"
                        )
                    self._trocas_janela += 1
                self.backend.atalho(teclas)
            elif tipo == "rolar":
                if x is not None and y is not None:
                    self.backend.mover(x, y, 0.1)
                direcao = str(decisao.get("direcao") or "baixo").lower()
                self.backend.rolar(15 if direcao == "cima" else -15)
            elif tipo == "esperar":
                ok = self.backend.esperar(float(decisao.get("tempo", 1.5)), self._cancelar)
                return ok, "cancelada durante a espera" if not ok else ""
            elif tipo == "trocar_janela":
                if self._trocas_janela >= MAX_TROCAS_JANELA:
                    return False, (
                        "limite de alternâncias de janela atingido; use ativar_janela, "
                        "clicar_tarefa ou clique diretamente no aplicativo já visível"
                    )
                self._trocas_janela += 1
                self.backend.atalho(("alt", "tab"))
            elif tipo in {"minimizar", "maximizar"}:
                self.backend.atalho(("win", "down" if tipo == "minimizar" else "up"))
            elif tipo == "ativar_janela":
                nome = self._nome_app_decidido(texto or str(decisao.get("descricao") or ""))
                if not self.backend.ativar_janela(nome):
                    self._foco_pendente = True
                    return False, f"Não confirmei o foco da janela '{nome}'. Não abri outra janela. Use a captura para localizar/clicar na janela existente antes de digitar."
                self._foco_pendente = False
            elif tipo == "abrir_app":
                nome = self._nome_app_decidido(texto)
                if not self.backend.ativar_janela(nome):
                    chave = nome.casefold().strip()
                    if chave in self._apps_lancados:
                        return False, f"'{nome}' já recebeu um pedido de abertura nesta tarefa. Não abri outra janela; verifique a tela e clique na existente."
                    if not self.backend.abrir_app(nome):
                        return False, f"não consegui abrir '{nome}'"
                    self._apps_lancados.add(chave)
                    self._foco_pendente = True
                else:
                    self._foco_pendente = False
            elif tipo == "clicar_tarefa":
                # A ação aponta para um ícone que o modelo viu na captura.
                # Tentar abrir_app antes fazia o clique nunca acontecer quando
                # o launcher aceitava o pedido, mesmo sem trazer a janela.
                resultado = self._clicar_com_verificacao(decisao, x, y)
                if resultado[0]:
                    self._foco_pendente = False
                return resultado
            elif tipo == "confirmar_clique":
                return False, "confirmar_clique só é válido durante a verificação de um alvo pendente"
            elif tipo == "ferramenta":
                return self._executar_ferramenta(decisao)
            else:
                return False, f"ação desconhecida: {tipo}"
            return True, ""
        except ErroBackendDesktop as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {exc}"

    def _perguntar_vitor(self, pergunta: str, tipo: str = "duvida") -> tuple[bool, str]:
        with self._lock:
            self._pergunta_descricao = pergunta
            self._pergunta_resposta = ""
            self._pergunta_evento.clear()
        self._iniciar_espera()
        try:
            self._mudar_estado("aguardando_confirmacao", pergunta)
            self._falar(pergunta)
            def externa():
                return self._pergunta_resposta if self._pergunta_evento.is_set() else None
            import interface_web
            resposta = interface_web.perguntar_usuario_tarefa(
                pergunta, tipo, cancelar=self._cancelar, resposta_externa=externa)
            if resposta.startswith("Não consegui abrir a pergunta"):
                # O celular envia a resposta ao mesmo agente pela ponte.
                limite = time.monotonic() + 600
                while not self._pergunta_evento.wait(.1):
                    if self._cancelar.is_set():
                        return False, "Pergunta cancelada"
                    if time.monotonic() >= limite:
                        return False, "Não recebi resposta; não vou presumir autorização."
                resposta = self._pergunta_resposta
            if self._cancelar.is_set() or resposta.startswith(("O Vitor não respondeu", "Pergunta cancelada")):
                return False, resposta
            return bool(resposta.strip()), resposta
        finally:
            with self._lock:
                self._pergunta_descricao = ""
            self._terminar_espera()
            if not self._cancelar.is_set() and self._executar.is_set():
                self._mudar_estado("rodando", "Continuando com sua resposta")

    def _executar_ferramenta(self, decisao: dict) -> tuple[bool, str]:
        nome = str(decisao.get("ferramenta") or decisao.get("nome") or "").strip()
        argumentos = decisao.get("argumentos") or {}
        if not nome or not isinstance(argumentos, dict):
            return False, "nome/argumentos de ferramenta inválidos"
        if nome == "abrir_app":
            return self._executar_acao({"acao": "abrir_app", "texto": str(argumentos.get("nome") or "")})
        import ferramentas
        from agente_ui_catalogo import EXCLUIDAS
        if nome in EXCLUIDAS:
            return False, "Já existe uma sessão visual ativa; use as ferramentas dentro desta tarefa."
        self._iniciar_espera()
        try:
            if nome == "abrir_ferramentas":
                dominio = str(argumentos.get("dominio") or "")
                if dominio not in ferramentas.GRUPOS_SOB_DEMANDA:
                    return False, "Domínio desconhecido; use um domínio do catálogo."
                self._dominios_ferramentas.add(dominio)
                ferramentas.esquemas(grupos=[dominio])
                ok, texto = True, "Ferramentas carregadas: " + dominio + ". Use os novos parâmetros do catálogo."
            elif nome in {"perguntar_usuario_tarefa", "code_perguntar"}:
                pergunta = str(argumentos.get("pergunta") or "").strip()
                if not pergunta:
                    return False, "Pergunta vazia"
                ok, texto = self._perguntar_vitor(pergunta, str(argumentos.get("tipo") or "duvida"))
                texto = "Resposta do usuário: " + texto if ok else texto
            else:
                f = ferramentas.CATALOGO.get(nome)
                if f and f.destrutiva:
                    autorizado, motivo = self._autorizar_acao_destrutiva({
                        "destrutiva": True, "descricao": f"{nome}: {json.dumps(argumentos, ensure_ascii=False)}"})
                    if not autorizado:
                        return False, motivo
                args = dict(argumentos)
                if nome == "executar_terminal":
                    # Só o executor pode ligar confirmação depois da resposta
                    # humana. Nunca confiar nessa flag vinda do modelo.
                    args.pop("autorizacao_direta", None)
                    args["confirmado"] = False
                resultado = ferramentas.executar_estruturado(
                    nome, args, contexto={"pedido_explicito": True, "dono_confirmado": True,
                                        **({"cancelar_terminal_evento": self._cancelar} if nome == "executar_terminal" else {})})
                if nome == "executar_terminal" and not resultado.ok:
                    import terminal
                    comando = str(args.get("comando") or "")
                    if comando and terminal.classificar(comando) == terminal.CONFIRMAR:
                        autorizado, motivo = self._autorizar_acao_destrutiva({
                            "destrutiva": True, "descricao": "Executar este comando: " + comando})
                        if autorizado and not self._cancelar.is_set():
                            args["confirmado"] = True
                            resultado = ferramentas.executar_estruturado(
                                nome, args, contexto={"pedido_explicito": True, "dono_confirmado": True,
                                                    "cancelar_terminal_evento": self._cancelar})
                        else:
                            return False, motivo
                ok, texto = bool(resultado.ok), str(resultado.texto or resultado.erro or "")
            # Guardar o conteúdo, não apenas "OK". Ele pode conter o caminho,
            # fontes da pesquisa, dependências ou instruções de continuação.
            if len(texto) > 6000:
                texto = texto[:4500] + "\n[saída abreviada]\n" + texto[-1500:]
            self._resultados_ferramentas.append(
                f"RESULTADO DA FERRAMENTA {nome} ({'OK' if ok else 'FALHA'}):\n{texto}")
            self._registrar(f"FERRAMENTA {nome}: {texto[:1600]}")
            return ok, texto
        finally:
            self._terminar_espera()


# ═════════════════════════════════════════════════════════════════
# API PÚBLICA LEGADA
# ═════════════════════════════════════════════════════════════════

_lock_global = threading.RLock()
_sessao_atual: SessaoAgenteUI = SessaoAgenteUI()
_ouvintes_globais: list[OuvinteEstado] = []
_callback_falar_global: Optional[Callable[[str], None]] = None


def _nova_sessao(callback_falar=None, backend: Optional[BackendDesktop] = None,
                 decisor: Optional[DecisorUI] = None) -> SessaoAgenteUI:
    sessao = SessaoAgenteUI(
        backend=backend,
        decisor=decisor,
        callback_falar=callback_falar or _callback_falar_global,
    )
    for callback in _ouvintes_globais:
        sessao.adicionar_ouvinte(callback)
    return sessao


def definir_sessao_agente_ui(sessao: SessaoAgenteUI) -> None:
    """Injeção explícita para testes e integrações avançadas."""
    global _sessao_atual
    with _lock_global:
        _sessao_atual = sessao
        for callback in _ouvintes_globais:
            sessao.adicionar_ouvinte(callback)


def definir_callback_falar(callback: Optional[Callable[[str], None]]) -> None:
    """Define a fala padrão das próximas sessões e atualiza a sessão atual."""
    global _callback_falar_global
    with _lock_global:
        _callback_falar_global = callback
        _sessao_atual.callback_falar = callback


def sessao_agente_ui() -> SessaoAgenteUI:
    with _lock_global:
        return _sessao_atual


def iniciar_agente_ui(objetivo: str, callback_falar=None, *, action_id: str = "") -> str:
    global _sessao_atual
    objetivo = (objetivo or "").strip()
    if not objetivo:
        return "Me diz o que você quer que eu faça na tela, Vitor!"
    with _lock_global:
        if _sessao_atual.retrato()["ativo"]:
            return "Já tô fazendo outra coisa na tela, Vitor! Me fala pra parar primeiro."
        _sessao_atual = _nova_sessao(callback_falar=callback_falar)
        iniciou = _sessao_atual.iniciar(objetivo, em_thread=True, action_id=action_id)
        if not iniciou:
            erro = _sessao_atual.retrato().get("erro") or "automação de desktop indisponível"
            return f"Não consigo controlar a tela agora: {erro}"
    try:
        import modelo
        modelo.registrar_acao_no_historico(f"Iniciou agente de UI com objetivo: {objetivo}")
        # O recibo da ponte não pode aguardar outra inferência após iniciar os cliques.
        if action_id:
            return "Pedido recebido pelo agente visual; acompanhe o estado para saber o resultado."
        return modelo.gerar_frase_acao("agente_ui_iniciando", objetivo) or "Vou fazer isso na tela!"
    except Exception:
        return "Vou fazer isso na tela!"


def pausar_agente_ui() -> str:
    return ("Pausei! Me fala 'continua o que tava fazendo na tela' quando quiser."
            if sessao_agente_ui().pausar()
            else "Não tô rodando ou já tô pausada, Vitor!")


def retomar_agente_ui() -> str:
    return ("Continuando!" if sessao_agente_ui().retomar()
            else "Não tem nada pausado agora, Vitor!")


def continuar_agente_ui() -> str:
    return retomar_agente_ui()


def parar_agente_ui() -> str:
    return ("Parando o que eu tava fazendo na tela!" if sessao_agente_ui().cancelar()
            else "Não tô fazendo nada na tela agora, Vitor!")


def estado_agente_ui() -> dict[str, Any]:
    return sessao_agente_ui().retrato()


def status_agente_ui() -> str:
    estado = estado_agente_ui()
    if not estado["ativo"]:
        return "Agente de UI: parado"
    rotulo = "pausado" if estado["estado"] == "pausado" else "rodando"
    return f"Agente de UI {rotulo}: {estado['objetivo']}"


def enviar_mensagem_ao_vivo(mensagem: str) -> bool:
    return sessao_agente_ui().enviar_mensagem(mensagem)


def adicionar_ouvinte_agente_ui(callback: OuvinteEstado) -> None:
    with _lock_global:
        if callback not in _ouvintes_globais:
            _ouvintes_globais.append(callback)
        _sessao_atual.adicionar_ouvinte(callback)


def remover_ouvinte_agente_ui(callback: OuvinteEstado) -> None:
    with _lock_global:
        if callback in _ouvintes_globais:
            _ouvintes_globais.remove(callback)
        _sessao_atual.remover_ouvinte(callback)


__all__ = [
    "EstadoAgenteUI", "SessaoAgenteUI", "adicionar_ouvinte_agente_ui",
    "continuar_agente_ui", "definir_callback_falar", "definir_sessao_agente_ui",
    "enviar_mensagem_ao_vivo",
    "estado_agente_ui", "iniciar_agente_ui", "parar_agente_ui", "pausar_agente_ui",
    "remover_ouvinte_agente_ui", "retomar_agente_ui", "sessao_agente_ui",
    "status_agente_ui",
]
