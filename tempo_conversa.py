"""
tempo_conversa.py — quando cada fala aconteceu e quanto tempo se passou desde a última.

Contexto PASSIVO, igual à hora e à temperatura: a Emily usa para se situar (a conversa
de agora continua a anterior? faz horas que não falamos?) e não comenta isso sem motivo.

Um módulo só para o PC (chat e voz), a memória unificada e o Discord, para o corte de
"passou muito tempo" ser o mesmo em todo lugar. O Android tem o espelho em
ConversationClock.kt, com o mesmo limite.
"""

from __future__ import annotations

import datetime
import time
from typing import Iterable, Optional

# Acima disso a mensagem nova deixa de ser continuação direta da anterior.
LIMITE_CONTINUIDADE_S = 30 * 60

_DIAS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")
_fuso_cache = None


def fuso():
    """Belo Horizonte, fixo: a hora que ela sabe é a do Vitor mesmo que o PC esteja com o fuso errado."""
    global _fuso_cache
    if _fuso_cache is None:
        try:
            from zoneinfo import ZoneInfo
            _fuso_cache = ZoneInfo("America/Sao_Paulo")
        except Exception:  # noqa: BLE001 - sem tzdata (Windows): UTC-3 fixo, correto desde 2019
            _fuso_cache = datetime.timezone(datetime.timedelta(hours=-3))
    return _fuso_cache


def _dt(ts: float) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(float(ts), fuso())


def rotulo(ts: float, agora: Optional[float] = None) -> str:
    """'14:05' (hoje), 'ontem 22:40', 'seg 12/10 09:10' (mais antigo)."""
    agora = time.time() if agora is None else agora
    d, hoje = _dt(ts), _dt(agora)
    hora = f"{d.hour:02d}:{d.minute:02d}"
    dias = (hoje.date() - d.date()).days
    if dias == 0:
        return hora
    if dias == 1:
        return f"ontem {hora}"
    return f"{_DIAS[d.weekday()]} {d.day:02d}/{d.month:02d} {hora}"


def duracao(segundos: float) -> str:
    """'agora há pouco', '25 min', '3 h', '2 dias'. Sem o 'há': quem usa decide a frase."""
    s = max(0.0, float(segundos))
    if s < 120:
        return "menos de 2 min"
    if s < 3600:
        return f"{round(s / 60)} min"
    if s < 86400:
        h = s / 3600
        return f"{round(h)} h" if h >= 10 else f"{h:.1f} h".replace(".", ",").replace(",0", "")
    return f"{round(s / 86400)} dia" + ("s" if round(s / 86400) != 1 else "")


def passou_muito_tempo(ultimo_ts: float, agora: Optional[float] = None,
                       limite: float = LIMITE_CONTINUIDADE_S) -> bool:
    agora = time.time() if agora is None else agora
    return bool(ultimo_ts) and agora - float(ultimo_ts) >= limite


def bloco_continuidade(ultimo_ts: float, agora: Optional[float] = None,
                       limite: float = LIMITE_CONTINUIDADE_S) -> str:
    """Texto para o system prompt. Vazio quando a conversa está em andamento."""
    if not ultimo_ts:
        return ""
    agora = time.time() if agora is None else agora
    if not passou_muito_tempo(ultimo_ts, agora, limite):
        return ""
    return (
        f"\n\nÚLTIMA CONVERSA COM O VITOR: {rotulo(ultimo_ts, agora)} "
        f"(faz {duracao(agora - ultimo_ts)}). Isso é contexto interno: não cite o horário nem o "
        "tempo sem motivo. Como faz um tempo, NÃO trate a mensagem de agora como continuação "
        "direta da anterior: o assunto pode ter mudado e o que estava em andamento pode ter se "
        "resolvido. Volte ao assunto antigo só se ele voltar a ele ou se ainda estiver claramente "
        "pendente."
    )


def ultimo_timestamp(timestamps: Iterable[float]) -> float:
    valores = [float(t) for t in timestamps if t]
    return max(valores) if valores else 0.0
