"""
Task 1 — sonda de disponibilidade real dos modelos.

Por que este script existe
──────────────────────────
O /v1/models da conta não listou 'claude-sonnet-5' nem 'claude-opus-5', mas o
painel do Kiro IDE mostra os dois. O ModelResolver do gateway é pass-through de
propósito ("gateway, not gatekeeper"): nome fora do cache é repassado e quem
decide é a Kiro API. E o llm.py já registra o inverso disso — modelo listado que
devolve 404 na chamada real.

Ou seja: a lista não decide nada. A chamada decide.

Cada sondagem gasta 2 tokens de saída. É o teste mais barato possível que
produz resposta definitiva.

Uso:
    python _teste_gateway_sonda.py
"""

from __future__ import annotations

import os
import time

from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000")
CHAVE = os.getenv("KIRO_PROXY_API_KEY")

# Ordem importa: primeiro o que o spec pediu, depois o melhor substituto de
# cada família conforme o /v1/models da conta.
CANDIDATOS = [
    ("claude-sonnet-5", "spec: rotas de conversa/texto/visão"),
    ("claude-opus-5", "spec: rota agente_ui"),
    ("claude-opus-4.8", "visto no painel do Kiro IDE"),
    ("claude-sonnet-4.6", "substituto listado na conta"),
    ("claude-opus-4.7", "substituto listado na conta"),
    ("claude-haiku-4.5", "rotas baratas (classificador, triagem_visual)"),
]


def sondar(cliente, modelo: str) -> tuple[bool, str, float]:
    """Uma chamada mínima. Devolve (funcionou, detalhe, segundos)."""
    inicio = time.monotonic()
    try:
        resposta = cliente.chat.completions.create(
            model=modelo,
            messages=[{"role": "user", "content": "Responda apenas com a palavra OK."}],
            max_tokens=8,
            stream=False,
        )
    except Exception as e:
        decorrido = time.monotonic() - inicio
        texto = str(e)
        # Enxuga a mensagem: o corpo de erro do gateway é verboso.
        if len(texto) > 220:
            texto = texto[:220] + "..."
        return False, texto, decorrido

    decorrido = time.monotonic() - inicio
    try:
        conteudo = (resposta.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        return False, "resposta sem choices utilizável", decorrido

    if not conteudo:
        motivo = getattr(resposta.choices[0], "finish_reason", "?")
        return False, f"conteúdo vazio (finish_reason={motivo})", decorrido

    return True, conteudo[:60], decorrido


def principal() -> int:
    from openai import OpenAI

    if not CHAVE:
        print("ERRO: KIRO_PROXY_API_KEY não está no .env. Rode _setup_gateway_env.py.")
        return 1

    cliente = OpenAI(base_url=f"{URL}/v1", api_key=CHAVE, timeout=120.0)

    print("=" * 74)
    print("TASK 1 — SONDA DE DISPONIBILIDADE REAL (2 tokens por modelo)")
    print("=" * 74)
    print()

    funcionaram: list[str] = []

    for modelo, papel in CANDIDATOS:
        print(f"  {modelo}")
        print(f"    papel: {papel}")
        ok, detalhe, segundos = sondar(cliente, modelo)
        if ok:
            funcionaram.append(modelo)
            print(f"    FUNCIONA  ({segundos:.2f}s)  resposta={detalhe!r}")
        else:
            print(f"    falhou    ({segundos:.2f}s)  {detalhe}")
        print()

    print("=" * 74)
    print("RESUMO")
    print("=" * 74)
    if funcionaram:
        print("Modelos que responderam de verdade:")
        for m in funcionaram:
            print(f"  - {m}")
    else:
        print("Nenhum candidato respondeu. Verifique credencial e log do gateway.")
        return 1

    print()
    tem_sonnet5 = "claude-sonnet-5" in funcionaram
    tem_opus5 = "claude-opus-5" in funcionaram
    if tem_sonnet5 and tem_opus5:
        print("Os dois IDs do spec funcionam mesmo fora do /v1/models.")
        print("A divisão de modelos aprovada segue sem alteração.")
    else:
        print("Os IDs do spec NÃO funcionam nesta conta pelo gateway.")
        print("Substitutos sugeridos, pela família equivalente mais alta que respondeu:")
        melhor_sonnet = next((m for m in ("claude-sonnet-4.6", "claude-sonnet-4.5")
                              if m in funcionaram), None)
        melhor_opus = next((m for m in ("claude-opus-4.8", "claude-opus-4.7", "claude-opus-4.6")
                            if m in funcionaram), None)
        print(f"  conversa/texto/visão -> {melhor_sonnet or 'nenhum'}")
        print(f"  agente_ui            -> {melhor_opus or 'nenhum'}")
        print(f"  rotas baratas        -> {'claude-haiku-4.5' if 'claude-haiku-4.5' in funcionaram else 'nenhum'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
