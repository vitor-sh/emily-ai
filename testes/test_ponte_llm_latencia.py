"""Regressões das otimizações de latência da ponte usada pelo Android."""

from __future__ import annotations

import ast
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent


def test_ponte_reutiliza_pool_http_e_expoe_tempo_do_upstream():
    fonte = (RAIZ / "servidor.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)

    assert "_PONTE_HTTP = _requests.Session()" in fonte
    assert '_PONTE_HTTP.mount("http://"' in fonte
    assert '_PONTE_HTTP.mount("https://"' in fonte
    assert "resp = _PONTE_HTTP.post(" in fonte
    assert '"Server-Timing": f"upstream;dur={duracao_ms}"' in fonte
    assert '"X-Emily-Upstream-Ms": str(duracao_ms)' in fonte

    funcao = next(
        no for no in arvore.body
        if isinstance(no, ast.FunctionDef) and no.name == "ponte_llm_chat"
    )
    chamada_post = next(
        no for no in ast.walk(funcao)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and no.func.attr == "post"
    )
    assert ast.unparse(chamada_post.func.value) == "_PONTE_HTTP"


def test_ponte_continua_com_timeout_e_autenticacao_do_proxy():
    fonte = (RAIZ / "servidor.py").read_text(encoding="utf-8")
    assert 'headers={"Authorization": f"Bearer {_PONTE_CLAUDE_CHAVE}"}' in fonte
    assert "timeout=180" in fonte