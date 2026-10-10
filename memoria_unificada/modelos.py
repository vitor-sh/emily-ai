"""Tipos canônicos compartilhados por armazenamento, extração e recuperação."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Optional, Tuple


STATUS_VALIDOS = frozenset({"active", "superseded", "forgotten"})
PRIVACIDADES_VALIDAS = frozenset({"owner_private", "public"})
POOLS_VALIDOS = frozenset({"general", "code"})
EVIDENCIAS_VALIDAS = frozenset({"user", "assistant", "mixed", "tool"})
PAPEIS_EVENTO_VALIDOS = frozenset({"user", "assistant", "tool", "system"})


def _texto_obrigatorio(valor: str, campo: str) -> str:
    limpo = str(valor or "").strip()
    if not limpo:
        raise ValueError(f"{campo} não pode ser vazio")
    return limpo


def _tupla_textos(valores: Iterable[str]) -> Tuple[str, ...]:
    vistos = set()
    saida = []
    for valor in valores or ():
        limpo = str(valor or "").strip()
        if limpo and limpo not in vistos:
            vistos.add(limpo)
            saida.append(limpo)
    return tuple(saida)


@dataclass(frozen=True)
class EventoMemoria:
    """Uma fala/ação bruta. A persistência do journal entra na Fase 2."""

    owner_user_id: str
    papel: str
    texto: str
    canal: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    conversa_id: str = ""
    external_id: str = ""
    privacy_scope: str = "owner_private"
    memory_pool: str = "general"

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _texto_obrigatorio(
            self.owner_user_id, "owner_user_id"))
        object.__setattr__(self, "texto", _texto_obrigatorio(self.texto, "texto"))
        object.__setattr__(self, "canal", _texto_obrigatorio(self.canal, "canal"))
        if self.papel not in PAPEIS_EVENTO_VALIDOS:
            raise ValueError(f"papel de evento inválido: {self.papel}")
        if self.privacy_scope not in PRIVACIDADES_VALIDAS:
            raise ValueError(f"privacidade inválida: {self.privacy_scope}")
        if self.memory_pool not in POOLS_VALIDOS:
            raise ValueError(f"pool inválido: {self.memory_pool}")


@dataclass(frozen=True)
class FatoMemoria:
    """Fato consolidado e indexável na memória de longo prazo."""

    owner_user_id: str
    texto: str
    importancia: int
    canal_origem: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    criado_em: float = field(default_factory=time.time)
    atualizado_em: float = field(default_factory=time.time)
    entidades: Tuple[str, ...] = ()
    conversa_origem_id: str = ""
    eventos_origem_ids: Tuple[str, ...] = ()
    sujeito: str = ""
    topico: str = ""
    status: str = "active"
    superseded_by: str = ""
    confianca: float = 1.0
    evidence_role: str = "user"
    privacy_scope: str = "owner_private"
    memory_pool: str = "general"

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_user_id", _texto_obrigatorio(
            self.owner_user_id, "owner_user_id"))
        object.__setattr__(self, "texto", _texto_obrigatorio(self.texto, "texto"))
        object.__setattr__(self, "canal_origem", _texto_obrigatorio(
            self.canal_origem, "canal_origem"))
        object.__setattr__(self, "entidades", _tupla_textos(self.entidades))
        object.__setattr__(self, "eventos_origem_ids", _tupla_textos(
            self.eventos_origem_ids))
        if not 1 <= int(self.importancia) <= 10:
            raise ValueError("importancia deve estar entre 1 e 10")
        if not 0.0 <= float(self.confianca) <= 1.0:
            raise ValueError("confianca deve estar entre 0 e 1")
        if self.status not in STATUS_VALIDOS:
            raise ValueError(f"status inválido: {self.status}")
        if self.evidence_role not in EVIDENCIAS_VALIDAS:
            raise ValueError(f"evidência inválida: {self.evidence_role}")
        if self.privacy_scope not in PRIVACIDADES_VALIDAS:
            raise ValueError(f"privacidade inválida: {self.privacy_scope}")
        if self.memory_pool not in POOLS_VALIDOS:
            raise ValueError(f"pool inválido: {self.memory_pool}")

    def com_estado(self, status: str, superseded_by: str = "") -> "FatoMemoria":
        return replace(
            self,
            status=status,
            superseded_by=str(superseded_by or "").strip(),
            atualizado_em=time.time(),
        )

    def para_metadata(self) -> Dict[str, Any]:
        """Converte coleções para JSON porque metadata do Chroma é escalar."""

        return {
            "owner_user_id": self.owner_user_id,
            "importance": int(self.importancia),
            "created_at": float(self.criado_em),
            "updated_at": float(self.atualizado_em),
            "entities_json": json.dumps(self.entidades, ensure_ascii=False),
            "source_channel": self.canal_origem,
            "source_conversation_id": self.conversa_origem_id,
            "source_event_ids_json": json.dumps(self.eventos_origem_ids),
            "subject": self.sujeito,
            "topic": self.topico,
            "status": self.status,
            "superseded_by": self.superseded_by,
            "confidence": float(self.confianca),
            "evidence_role": self.evidence_role,
            "privacy_scope": self.privacy_scope,
            "memory_pool": self.memory_pool,
        }

    @classmethod
    def de_registro(cls, id_fato: str, texto: str, metadata: Dict[str, Any]) -> "FatoMemoria":
        def _json_tupla(chave: str) -> Tuple[str, ...]:
            try:
                valor = json.loads(str(metadata.get(chave) or "[]"))
                return _tupla_textos(valor if isinstance(valor, list) else ())
            except (json.JSONDecodeError, TypeError):
                return ()

        return cls(
            id=id_fato,
            owner_user_id=str(metadata.get("owner_user_id") or ""),
            texto=texto,
            importancia=int(metadata.get("importance", 1)),
            criado_em=float(metadata.get("created_at", 0.0)),
            atualizado_em=float(metadata.get("updated_at", 0.0)),
            entidades=_json_tupla("entities_json"),
            canal_origem=str(metadata.get("source_channel") or "unknown"),
            conversa_origem_id=str(metadata.get("source_conversation_id") or ""),
            eventos_origem_ids=_json_tupla("source_event_ids_json"),
            sujeito=str(metadata.get("subject") or ""),
            topico=str(metadata.get("topic") or ""),
            status=str(metadata.get("status") or "active"),
            superseded_by=str(metadata.get("superseded_by") or ""),
            confianca=float(metadata.get("confidence", 1.0)),
            evidence_role=str(metadata.get("evidence_role") or "user"),
            privacy_scope=str(metadata.get("privacy_scope") or "owner_private"),
            memory_pool=str(metadata.get("memory_pool") or "general"),
        )


@dataclass(frozen=True)
class MemoriaEncontrada:
    fato: FatoMemoria
    distancia: float
    relevancia: float