"""Recuperação em três camadas: sempre presente, recente buscável e longo prazo."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .armazenamento import ArmazenamentoMemoria
from .config import ConfigMemoria, carregar_config
from .journal import JournalMemoria, normalizar_busca
from .modelos import EventoMemoria, FatoMemoria


def _extrair_termos(consulta: str, minimo_letras: int = 3, limite: int = 12) -> List[str]:
    """Termos significativos da mensagem: tokens alfanuméricos de 3+ letras."""
    limpo = normalizar_busca(consulta)
    termos = []
    for palavra in re.findall(r"[a-z0-9]+", limpo):
        if len(palavra) >= minimo_letras and palavra not in termos:
            termos.append(palavra)
        if len(termos) >= limite:
            break
    return termos


def _idade_horas(timestamp: float, agora: float) -> float:
    return max(0.0, (agora - float(timestamp)) / 3600.0)


def _recencia(timestamp: float, agora: float, meia_vida_horas: float) -> float:
    """Decaimento exponencial: 1.0 agora, 0.5 na meia-vida, tende a 0."""

    return 0.5 ** (_idade_horas(timestamp, agora) / max(1e-9, meia_vida_horas))


def _normalizar_titulo(texto: str, tamanho: int = 180) -> str:
    limpo = " ".join(str(texto or "").split())
    if len(limpo) <= tamanho:
        return limpo
    return limpo[:tamanho - 1].rstrip(" ,.;:") + "…"


@dataclass(frozen=True)
class Lembrete:
    evento: EventoMemoria
    score: float


@dataclass(frozen=True)
class FatoPontuado:
    fato: FatoMemoria
    relevancia: float
    recencia: float
    score: float


__all__ = ["FatoPontuado", "Lembrete"]


@dataclass(frozen=True)
class ContextoMemoria:
    """Tudo que entra no prompt, já pontuado e cortado pelo orçamento."""

    trocas: Tuple[EventoMemoria, ...] = ()
    lembretes: Tuple[Lembrete, ...] = ()
    fatos: Tuple[FatoPontuado, ...] = ()
    compromissos: Tuple[FatoMemoria, ...] = ()
    diagnosticos: Dict[str, object] = field(default_factory=dict)

    def para_prompt(self) -> str:
        """Blocos determinísticos; vazia quando não há nada a lembrar."""
        blocos: List[str] = []
        if self.fatos:
            linhas = []
            for pontuado in self.fatos:
                etiqueta = ""
                if pontuado.fato.canal_origem and pontuado.fato.canal_origem != "unknown":
                    etiqueta = f" ({pontuado.fato.canal_origem})"
                linhas.append(f"- {pontuado.fato.texto}{etiqueta}")
            blocos.append("MEMÓRIA RELEVANTE:\n" + "\n".join(linhas))
        if self.compromissos:
            linhas = [f"- {fato.texto}" for fato in self.compromissos]
            blocos.append("COMPROMISSOS ATIVOS SUAS (cumpra ou corrija):\n" + "\n".join(linhas))
        if self.trocas:
            import tempo_conversa as tc
            agora = time.time()
            linhas = []
            for evento in self.trocas:
                autor = "Você" if evento.papel == "assistant" else "Usuário"
                linhas.append(f"[{tc.rotulo(evento.timestamp, agora)}] {autor}: {_normalizar_titulo(evento.texto)}")
            blocos.append("CONVERSA RECENTE (de qualquer canal; os horários são só para você se situar, "
                          "não os cite sem motivo):\n" + "\n".join(linhas))
        if self.lembretes:
            linhas = []
            for lembrete in self.lembretes:
                autor = "Você" if lembrete.evento.papel == "assistant" else "Usuário"
                horas = _idade_horas(lembrete.evento.timestamp, time.time())
                linhas.append(
                    f"[{_normalizar_titulo(lembrete.evento.texto, 140)}] "
                    f"({autor}, há {horas:.0f}h)"
                )
            blocos.append("LEMBRETES DO HISTÓRICO RECENTE:\n" + "\n".join(linhas))
        texto = "\n\n".join(blocos)
        # Faz muito tempo desde a última fala registrada: a mensagem de agora não é
        # continuação direta dela. Vem da memória (não do histórico da janela) porque
        # é ela que sobrevive a reinício e atravessa PC, celular e Discord.
        if texto and self.trocas:
            import tempo_conversa as tc
            texto += tc.bloco_continuidade(tc.ultimo_timestamp(e.timestamp for e in self.trocas))
        return texto


class RecuperadorMemoria:
    """Consulta as três camadas e monta o contexto de memória do turno."""

    def __init__(
        self,
        journal: JournalMemoria,
        armazenamento: ArmazenamentoMemoria,
        config: Optional[ConfigMemoria] = None,
    ):
        self.config = config or carregar_config()
        self.journal = journal
        self.armazenamento = armazenamento

    # ── Camada 3: fatos de longo prazo ────────────────────────────────
    def _reranquear_fatos(
        self,
        owner_user_id: str,
        encontrados: Sequence,
        agora: float,
    ) -> Tuple[List[FatoPontuado], List[FatoMemoria]]:
        """Score = w_rel*relevância + w_imp*importância + w_rec*recência."""
        cfg = self.config
        pontuados: List[FatoPontuado] = []
        compromissos: List[FatoMemoria] = []
        # "Emily" sozinha não deve ocupar vaga de fato do Vitor: compromissos
        # (fala só dela, tópico commitment) ganham bloco próprio e saem daqui.
        for item in encontrados:
            fato = item.fato
            if fato.owner_user_id != owner_user_id:
                continue
            if fato.topico == "commitment" and fato.evidence_role == "assistant":
                compromissos.append(fato)
                continue
            relevancia = max(0.0, min(1.0, float(item.relevancia)))
            recencia = _recencia(fato.atualizado_em, agora, cfg.meia_vida_horas)
            importancia = max(1, min(10, int(fato.importancia))) / 10.0
            score = (
                cfg.peso_relevancia * relevancia
                + cfg.peso_importancia * importancia
                + cfg.peso_recencia * recencia
            )
            if score < cfg.min_score_fato:
                continue
            pontuados.append(FatoPontuado(
                fato=fato, relevancia=relevancia, recencia=recencia, score=score))
        pontuados.sort(key=lambda p: (-p.score, -p.fato.importancia, p.fato.id))
        # Diversidade: no máximo N por tópico, senão cinco variações de
        # "prefere Python" comem o orçamento inteiro.
        por_topico: Dict[str, int] = {}
        diversificados: List[FatoPontuado] = []
        for pontuado in pontuados:
            chave = pontuado.fato.topico or "sem_topico"
            if por_topico.get(chave, 0) >= cfg.max_por_topico:
                continue
            por_topico[chave] = por_topico.get(chave, 0) + 1
            diversificados.append(pontuado)
        # Orçamento de caracteres, fatos inteiros apenas.
        dentro: List[FatoPontuado] = []
        usado = 0
        for pontuado in diversificados:
            custo = len(pontuado.fato.texto) + 3
            if dentro and usado + custo > cfg.orcamento_prompt:
                continue
            dentro.append(pontuado)
            usado += custo
        compromissos.sort(key=lambda f: (-f.importancia, -f.atualizado_em, f.id))
        return dentro, compromissos[:4]

    def buscar_fatos(
        self,
        owner_user_id: str,
        consulta: str,
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
        agora: Optional[float] = None,
    ) -> Tuple[List[FatoPontuado], List[FatoMemoria]]:
        """Camada 3: busca semântica + rerank. (fatos, compromissos)"""

        dono = str(owner_user_id or "").strip()
        if not dono:
            raise ValueError("owner_user_id é obrigatório na recuperação")
        texto = str(consulta or "").strip()
        if not texto:
            return [], []
        agora = float(agora if agora is not None else time.time())
        encontrados = self.armazenamento.buscar(
            dono, texto, limite=self.config.candidatos_semanticos,
            privacy_scopes=privacy_scopes, pools=pools)
        return self._reranquear_fatos(dono, encontrados, agora)

    def contexto_completo(
        self,
        owner_user_id: str,
        consulta: str,
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
        agora: Optional[float] = None,
    ) -> ContextoMemoria:
        """As três camadas de uma vez, prontas para virar prompt."""
        dono = str(owner_user_id or "").strip()
        if not dono:
            raise ValueError("owner_user_id é obrigatório na recuperação")
        consulta_limpa = str(consulta or "").strip()
        agora = float(agora if agora is not None else time.time())
        cfg = self.config

        # Camada 1: últimas trocas de QUALQUER canal, sempre carregadas.
        trocas = tuple(self.journal.listar_recentes(
            dono, limite=cfg.eventos_recentes,
            privacy_scopes=privacy_scopes, pools=pools))

        # Camada 2: busca textual na janela recente, pontuada localmente.
        lembretes: List[Lembrete] = []
        termos = _extrair_termos(consulta_limpa)
        if termos:
            desde = agora - cfg.janela_recente_horas * 3600.0
            achados = self.journal.buscar_texto(
                dono, termos, limite=12, privacy_scopes=privacy_scopes,
                pools=pools, desde=desde, ate=agora)
            ids_das_trocas = {evento.id for evento in trocas}
            for evento, fracao in achados:
                if evento.id in ids_das_trocas:
                    continue  # já está na camada 1; lembrete seria eco
                score = (
                    0.7 * fracao
                    + 0.3 * _recencia(evento.timestamp, agora, cfg.meia_vida_horas)
                )
                lembretes.append(Lembrete(evento=evento, score=score))
            lembretes.sort(key=lambda l: (-l.score, l.evento.id))
            lembretes = lembretes[:4]

        # Camada 3: fatos reranqueados; compromissos vão pro bloco próprio.
        fatos_pontuados, compromissos = self.buscar_fatos(
            dono, consulta_limpa, privacy_scopes=privacy_scopes, pools=pools,
            agora=agora)
        ids_compromissos = {fato.id for fato in compromissos}
        fatos_finais = tuple(
            p for p in fatos_pontuados if p.fato.id not in ids_compromissos)

        return ContextoMemoria(
            trocas=trocas,
            lembretes=tuple(lembretes),
            fatos=fatos_finais,
            compromissos=tuple(compromissos),
            diagnosticos={
                "termos": tuple(termos),
                "agora": agora,
                "candidatos_semanticos": len(fatos_pontuados),
            },
        )


__all__ = ["ContextoMemoria", "FatoPontuado", "Lembrete", "RecuperadorMemoria"]
