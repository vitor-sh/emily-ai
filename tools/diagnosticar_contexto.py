"""Mostra a janela de contexto que o medidor usa para cada modelo e quanto demora.

Mede tambem a chamada de uso do Codex que hoje acompanha o medidor na mesma
resposta (uso_contexto), para ver se ela atrasa a atualizacao do circulo.
Uso: python3 tools/diagnosticar_contexto.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import contexto_chat  # noqa: E402
import llm  # noqa: E402

MODELOS = [m["id"] for m in llm.modelos_disponiveis()] or [llm.ROTAS["conversa"].modelo]
print(f"provedor ativo: {llm.TABELA_ATIVA} | modelos: {len(MODELOS)}")
for mid in MODELOS:
    inicio = time.perf_counter()
    estado = contexto_chat.display("diag", mid, [{"role": "user", "content": "oi"}])
    print(f"  {mid:26s} janela={estado['limit']:>8} util={estado['effective_limit']:>8} "
          f"verificado={estado['verified']!s:5s} {time.perf_counter() - inicio:5.2f}s  {estado['source'][:46]}")

try:
    import uso_codex
    inicio = time.perf_counter()
    resposta = uso_codex.desktop_usage()
    print(f"uso_codex.desktop_usage(): {time.perf_counter() - inicio:.2f}s "
          f"-> contas={len(resposta.get('accounts') or [])} erro={resposta.get('error')!r}")
except Exception as erro:  # noqa: BLE001 - diagnostico
    print(f"uso_codex falhou: {type(erro).__name__}: {erro}")
