"""Regressões dos limites de contexto que afetam o tempo de prefill do chat."""

from __future__ import annotations

import ast
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent


def _padrao_env(nome_variavel: str) -> int:
    arvore = ast.parse((RAIZ / "modelo.py").read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Assign):
            continue
        if not any(isinstance(alvo, ast.Name) and alvo.id == nome_variavel for alvo in no.targets):
            continue
        chamada_int = no.value
        chamada_getenv = chamada_int.args[0]
        return int(ast.literal_eval(chamada_getenv.args[1]))
    raise AssertionError(f"constante {nome_variavel} não encontrada")


def test_defaults_de_contexto_nao_reintroduzem_prefill_excessivo():
    # Continuam amplos para conversa recente e configuráveis via .env, mas não
    # podem voltar aos antigos 600 itens / 120k tokens por acidente.
    assert 20 <= _padrao_env("MAX_HISTORICO_MENSAGENS") <= 100
    assert 8_000 <= _padrao_env("ORCAMENTO_TOKENS_HISTORICO") <= 24_000