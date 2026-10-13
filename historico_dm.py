"""
historico_dm.py — a memória de conversa das DMs.

Por que existe
──────────────
O Vitor pediu que a Emily guardasse o histórico do que conversa com cada
pessoa no direct, do mesmo jeito que o chat dela no PC guarda conversa: fica
salvo, e quando ela vai responder alguém ela abre e lembra do que já rolou
com aquela pessoa. Sem isso, cada DM começava do zero — ela esquecia a
pessoa no dia seguinte.

Privacidade (decisão do Vitor, mantida): o conteúdo das DMs NÃO aparece na
interface nem entra no histórico de conversas dele. Fica num arquivo próprio
na pasta dele (~/.emily_dm_historico.json), igual às outras memórias dela
(preferências, perfil do Discord) — dado dela, não compartilhado.

Formato: {"usuarios": {"<id>": {"nome": str, "atualizado_em": float,
"mensagens": [{"quem": "pessoa"|"emily", "texto": str, "quando": float}]}}}
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict

ARQUIVO = Path(os.getenv("EMILY_ARQUIVO_DM_HISTORICO",
                         str(Path.home() / ".emily_dm_historico.json")))

# Teto de mensagens por pessoa e de pessoas guardadas. A janela que entra no
# prompt é menor que isso; o resto fica de reserva de contexto antigo.
LIMITE_POR_USUARIO = 200
TETO_USUARIOS = 80
LIMITE_PADRAO_NO_PROMPT = 40

# RLock e não Lock: adicionar() segura o lock e carregar() pega de novo.
_lock = threading.RLock()
_cache: Dict[str, dict] = {}
_carregado = False


def _log(msg: str) -> None:
    print(f"[DM-HISTORICO] {msg}")


def carregar() -> dict:
    global _cache, _carregado
    with _lock:
        if _carregado:
            return _cache
        dados: dict = {"usuarios": {}}
        try:
            if ARQUIVO.exists():
                lido = json.loads(ARQUIVO.read_text(encoding="utf-8"))
                if isinstance(lido, dict) and isinstance(lido.get("usuarios"), dict):
                    dados["usuarios"] = lido["usuarios"]
        except (json.JSONDecodeError, OSError, ValueError) as e:
            # Histórico corrompido não pode impedir a Emily de responder DM.
            _log(f"não consegui ler ({e}); começando do zero")
        _cache = dados
        _carregado = True
        return _cache


def _salvar() -> None:
    """Gravação atômica: tmp + os.replace, mesmo cuidado do preferencias."""
    tmp = ARQUIVO.with_suffix(".tmp")
    try:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ARQUIVO)
    except OSError as e:
        _log(f"não consegui gravar: {e}")


def _podar(dados: dict) -> None:
    usuarios = dados.get("usuarios", {})
    for ficha in usuarios.values():
        msgs = ficha.get("mensagens", [])
        if len(msgs) > LIMITE_POR_USUARIO:
            ficha["mensagens"] = msgs[-LIMITE_POR_USUARIO:]
    if len(usuarios) > TETO_USUARIOS:
        ordenados = sorted(usuarios.items(),
                           key=lambda kv: kv[1].get("atualizado_em", 0),
                           reverse=True)
        dados["usuarios"] = dict(ordenados[:TETO_USUARIOS])


def adicionar(user_id: int, nome: str, quem: str, texto: str) -> None:
    """Guarda uma fala. quem: 'pessoa' ou 'emily'."""
    texto = (texto or "").strip()
    if not texto:
        return
    with _lock:
        dados = carregar()
        ficha = dados["usuarios"].setdefault(
            str(int(user_id)),
            {"nome": nome or "alguém", "atualizado_em": 0, "mensagens": []})
        if nome:
            ficha["nome"] = nome
        ficha["mensagens"].append({
            "quem": "emily" if quem == "emily" else "pessoa",
            "texto": texto[:2000],
            "quando": time.time(),
        })
        ficha["atualizado_em"] = time.time()
        _podar(dados)
        _salvar()


def formatar(user_id: int, limite: int = LIMITE_PADRAO_NO_PROMPT) -> str:
    """
    As últimas `limite` mensagens da conversa com essa pessoa, da mais antiga
    pra mais recente — o formato de janela de contexto que a Emily já sabe
    ler ('Emily (você)' são as falas DELA). Vazio se nunca conversaram.
    """
    with _lock:
        ficha = carregar()["usuarios"].get(str(int(user_id)))
    if not ficha:
        return ""
    msgs = ficha.get("mensagens", [])[-max(1, int(limite)):]
    import tempo_conversa
    linhas = []
    anterior = 0.0
    for m in msgs:
        quem = ("Emily (você)" if m.get("quem") == "emily"
                else (ficha.get("nome") or "a pessoa"))
        quando = float(m.get("quando") or 0)
        hora = ""
        if quando:
            # Pausa longa: a fala de depois não responde à de antes.
            if anterior and quando - anterior >= tempo_conversa.LIMITE_CONTINUIDADE_S:
                linhas.append(f"--- {tempo_conversa.duracao(quando - anterior)} depois ---")
            anterior = quando
            hora = f"[{tempo_conversa.rotulo(quando)}] "
        linhas.append(f"{hora}{quem}: {m.get('texto', '')}")
    if anterior and time.time() - anterior >= tempo_conversa.LIMITE_CONTINUIDADE_S:
        linhas.append(f"--- {tempo_conversa.duracao(time.time() - anterior)} depois (agora) ---")
    return "\n".join(linhas)
