"""Tipos e armazenamento thread-safe do protocolo Hollow Knight ↔ Emily."""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Iterable, Optional


VERSAO_PROTOCOLO = 1
MAX_EVENTOS_PENDENTES = 80
MAX_COMANDOS_PENDENTES = 30


@dataclass
class EventoJogo:
    id: str
    sessao_id: str
    cena_id: str
    tipo: str
    dados: dict
    criado_em: float = field(default_factory=time.time)

    @classmethod
    def de_json(cls, sessao_id: str, corpo: dict) -> "EventoJogo":
        tipo = str(corpo.get("tipo") or "").strip().lower()
        if not tipo or len(tipo) > 64:
            raise ValueError("tipo de evento inválido")
        dados = corpo.get("dados") or {}
        if not isinstance(dados, dict):
            raise ValueError("dados precisa ser objeto")
        return cls(
            id=str(corpo.get("id") or secrets.token_hex(8))[:80],
            sessao_id=sessao_id,
            cena_id=str(corpo.get("cena_id") or "")[:160],
            tipo=tipo,
            dados=dados,
            criado_em=float(corpo.get("criado_em") or time.time()),
        )


@dataclass
class ComandoJogo:
    sequencia: int
    sessao_id: str
    cena_id: str
    tipo: str
    dados: dict
    criado_em: float = field(default_factory=time.time)
    expira_em: float = 0.0

    def __post_init__(self) -> None:
        if not self.expira_em:
            self.expira_em = self.criado_em + 15.0

    def expirado(self, agora: Optional[float] = None) -> bool:
        return (agora or time.time()) >= self.expira_em

    def json(self) -> dict:
        return {
            "sequencia": self.sequencia,
            "sessao_id": self.sessao_id,
            "cena_id": self.cena_id,
            "tipo": self.tipo,
            "dados": self.dados,
            "criado_em": self.criado_em,
            "expira_em": self.expira_em,
        }


@dataclass
class SessaoJogo:
    id: str
    campanha_id: str
    versao_mod: str
    cena_id: str = ""
    criada_em: float = field(default_factory=time.time)
    ultimo_contato: float = field(default_factory=time.time)
    proxima_sequencia: int = 1
    eventos: Deque[EventoJogo] = field(
        default_factory=lambda: deque(maxlen=MAX_EVENTOS_PENDENTES)
    )
    comandos: Deque[ComandoJogo] = field(
        default_factory=lambda: deque(maxlen=MAX_COMANDOS_PENDENTES)
    )
    vistos: Deque[str] = field(default_factory=lambda: deque(maxlen=300))
    confirmada_ate: int = 0
    estado: dict = field(default_factory=dict)


class EstadoPonte:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessoes: Dict[str, SessaoJogo] = {}

    def criar_sessao(self, campanha_id: str, versao_mod: str) -> SessaoJogo:
        sessao = SessaoJogo(
            id=secrets.token_urlsafe(18),
            campanha_id=str(campanha_id or "save-desconhecido")[:120],
            versao_mod=str(versao_mod or "desconhecida")[:40],
        )
        with self._lock:
            self._sessoes[sessao.id] = sessao
            self._limpar_sessoes_antigas()
        return sessao

    def obter(self, sessao_id: str) -> Optional[SessaoJogo]:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if sessao:
                sessao.ultimo_contato = time.time()
            return sessao

    def atualizar_estado(self, sessao_id: str, dados: dict) -> Optional[SessaoJogo]:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if not sessao:
                return None
            sessao.estado.update(dict(dados or {}))
            sessao.ultimo_contato = time.time()
            return sessao

    def receber_eventos(
        self, sessao_id: str, eventos: Iterable[EventoJogo]
    ) -> list[EventoJogo]:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if not sessao:
                raise KeyError("sessão inexistente")
            aceitos = []
            vistos = set(sessao.vistos)
            for evento in eventos:
                if evento.id in vistos:
                    continue
                sessao.vistos.append(evento.id)
                vistos.add(evento.id)
                if evento.cena_id and sessao.cena_id and evento.cena_id != sessao.cena_id:
                    # Um retrato de inimigos da sala anterior não vale na nova.
                    sessao.estado.pop("combate", None)
                sessao.cena_id = evento.cena_id or sessao.cena_id
                if evento.tipo == "estado":
                    # O snapshot foi capturado antes de ser enviado. Configuração
                    # do menu chega separadamente e é sempre a fonte autoritativa.
                    sessao.estado.update({
                        k: v for k, v in evento.dados.items()
                        if k not in {"modo_fala", "modelo", "voz", "volume"}
                    })
                elif isinstance(evento.dados.get("combate"), dict):
                    # Dano pode chegar antes do próximo snapshot de 4 segundos.
                    sessao.estado["combate"] = evento.dados["combate"]
                # A localização autoritativa entra por qualquer evento: a Emily
                # precisa saber onde o Vitor está antes de comentar qualquer coisa.
                # O snapshot de `estado` chega a cada 4s, então isso evita que uma
                # troca de área espere o próximo retrato para ser percebida.
                dados_evento = evento.dados if isinstance(evento.dados, dict) else {}
                zona = str(dados_evento.get("zona") or "").strip()
                if zona:
                    sessao.estado["zona"] = zona
                    nome_zona = str(dados_evento.get("zona_nome") or "").strip()
                    if nome_zona:
                        sessao.estado["zona_nome"] = nome_zona
                if evento.cena_id:
                    sessao.estado["cena_atual"] = evento.cena_id
                sessao.eventos.append(evento)
                aceitos.append(evento)
            sessao.ultimo_contato = time.time()
            return aceitos

    def enfileirar_comando(
        self, sessao_id: str, tipo: str, dados: dict, *, cena_id: str = "",
        ttl: float = 15.0,
    ) -> ComandoJogo:
        with self._lock:
            sessao = self._sessoes[sessao_id]
            agora = time.time()
            comando = ComandoJogo(
                sequencia=sessao.proxima_sequencia,
                sessao_id=sessao.id,
                cena_id=cena_id or sessao.cena_id,
                tipo=tipo,
                dados=dict(dados),
                criado_em=agora,
                expira_em=agora + max(1.0, min(float(ttl), 120.0)),
            )
            sessao.proxima_sequencia += 1
            sessao.comandos.append(comando)
            return comando

    def comandos_desde(
        self, sessao_id: str, sequencia: int, cena_id: str = ""
    ) -> list[dict]:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if not sessao:
                raise KeyError("sessão inexistente")
            agora = time.time()
            validos = []
            mantidos = deque(maxlen=MAX_COMANDOS_PENDENTES)
            for comando in sessao.comandos:
                if comando.expirado(agora):
                    continue
                mantidos.append(comando)
                if comando.sequencia <= sequencia:
                    continue
                if (
                    cena_id and comando.cena_id
                    and comando.cena_id != "*"
                    and comando.cena_id != cena_id
                ):
                    continue
                validos.append(comando.json())
            sessao.comandos = mantidos
            return validos

    def tem_fala_pendente(self, sessao_id: str) -> bool:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if not sessao:
                return False
            agora = time.time()
            return any(
                comando.sequencia > sessao.confirmada_ate
                and not comando.expirado(agora)
                and comando.tipo in {"fala", "audio"}
                for comando in sessao.comandos
            )

    def confirmar(self, sessao_id: str, sequencia: int) -> None:
        with self._lock:
            sessao = self._sessoes.get(sessao_id)
            if not sessao:
                raise KeyError("sessão inexistente")
            sessao.confirmada_ate = max(sessao.confirmada_ate, int(sequencia))
            sessao.comandos = deque(
                (c for c in sessao.comandos if c.sequencia > sessao.confirmada_ate),
                maxlen=MAX_COMANDOS_PENDENTES,
            )

    def resumo(self) -> dict:
        with self._lock:
            return {
                "protocolo": VERSAO_PROTOCOLO,
                "sessoes": len(self._sessoes),
                "ativas": [
                    {
                        "id": s.id,
                        "campanha_id": s.campanha_id,
                        "cena_id": s.cena_id,
                        "ultimo_contato": s.ultimo_contato,
                        "eventos": len(s.eventos),
                        "comandos": len(s.comandos),
                    }
                    for s in self._sessoes.values()
                ],
            }

    def _limpar_sessoes_antigas(self) -> None:
        limite = time.time() - 6 * 3600
        antigas = [sid for sid, s in self._sessoes.items() if s.ultimo_contato < limite]
        for sid in antigas:
            self._sessoes.pop(sid, None)
