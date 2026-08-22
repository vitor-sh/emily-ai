"""
Task 5 — medição dos orçamentos curtos ANTES de migrar (Requisitos 5.2 e 5.3).

Por que isso é medido e não presumido
─────────────────────────────────────
O GLM-5.2 devolvia SIM/NAO em 8 a 16 tokens com RACIOCINIO_DESLIGADO. O
Claude é mais verboso por natureza, e resposta vazia por orçamento estourado
é um sintoma que JÁ derrubou a triagem neste projeto — está documentado nos
comentários do llm.py, junto do caso em que o modelo gastou todo o
max_tokens pensando e o texto nunca começou.

Os três orçamentos curtos que a Emily usa de verdade:

  max_tokens=8   _llm_confirma_visao (rota classificador)
  max_tokens=10  deduplicação semântica do memoria.py (rota extracao)
  max_tokens=16  default da rota classificador

Se qualquer combinação devolver vazio, o Requisito 5.3 manda aumentar o
orçamento da rota ou endurecer a instrução — e registrar a medição.

Uso:
    python _teste_task5_orcamento_curto.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm  # noqa: E402

AMOSTRAS = 3

# Prompt real do _llm_confirma_visao, copiado do modelo.py.
PROMPT_VISAO = [
    {
        "role": "system",
        "content": (
            "Você decide se uma mensagem pede para ver ou analisar a tela do usuário.\n"
            "Responda APENAS com SIM ou NAO, sem mais nada."
        ),
    },
    {
        "role": "user",
        "content": 'Mensagem: "Emily, olha minha tela e vê o que tá errado"\n\n'
                   "Essa mensagem pede para ver ou analisar a tela?",
    },
]

# Caso negativo: a resposta certa é NAO.
PROMPT_VISAO_NEGATIVO = [
    {
        "role": "system",
        "content": (
            "Você decide se uma mensagem pede para ver ou analisar a tela do usuário.\n"
            "Responda APENAS com SIM ou NAO, sem mais nada."
        ),
    },
    {
        "role": "user",
        "content": 'Mensagem: "Emily, me conta uma piada"\n\n'
                   "Essa mensagem pede para ver ou analisar a tela?",
    },
]

# Prompt real da deduplicação semântica do memoria.py.
PROMPT_DEDUP = [
    {
        "role": "user",
        "content": (
            "Estes dois fatos dizem a mesma coisa?\n\n"
            'Fato A: "O Vitor gosta de jogar Elden Ring"\n'
            'Fato B: "O Vitor curte Elden Ring"\n\n'
            "Responda SOMENTE com: SIM ou NÃO"
        ),
    },
]

CASOS = [
    ("visao positivo (espera SIM)", PROMPT_VISAO, "SIM", 8),
    ("visao negativo (espera NAO)", PROMPT_VISAO_NEGATIVO, "NAO", 8),
    ("dedup memoria (espera SIM)", PROMPT_DEDUP, "SIM", 10),
    ("visao positivo, orçamento da rota", PROMPT_VISAO, "SIM", 16),
]

MODELOS = [
    llm.MODELO_KIRO_BARATO,     # candidato das rotas baratas
    llm.MODELO_KIRO_CONVERSA,   # comparação
]


def medir(modelo: str, mensagens: list, max_tokens: int) -> list[dict]:
    """Roda N amostras e devolve o que cada uma respondeu."""
    resultados = []
    for _ in range(AMOSTRAS):
        try:
            # rota 'conversa' já está no kiro; o que importa aqui é o par
            # (modelo, max_tokens), então sobrescrevo os dois por parâmetro.
            resposta = llm.chamar(
                mensagens,
                rota_nome="conversa",
                modelo=modelo,
                max_tokens=max_tokens,
                temperatura=0.0,
                stream=False,
            )
            texto = resposta if isinstance(resposta, str) else "".join(resposta)
            resultados.append({"texto": texto, "erro": None})
        except llm.ErroLLM as e:
            resultados.append({"texto": "", "erro": f"{type(e).__name__}: {e}"})
    return resultados


def principal() -> int:
    print("=" * 78)
    print("TASK 5 — ORÇAMENTOS CURTOS NO CLAUDE (medição, não suposição)")
    print("=" * 78)
    print(f"amostras por combinação: {AMOSTRAS}")
    print()

    problemas: list[str] = []

    for modelo in MODELOS:
        print(f"── modelo: {modelo} " + "─" * (60 - len(modelo)))
        print()
        for rotulo, mensagens, esperado, max_tokens in CASOS:
            resultados = medir(modelo, mensagens, max_tokens)

            vazias = sum(1 for r in resultados if not r["texto"].strip())
            erros = sum(1 for r in resultados if r["erro"])
            acertos = sum(
                1 for r in resultados
                if esperado in r["texto"].upper().replace("ÃO", "AO")
            )

            print(f"  {rotulo}  (max_tokens={max_tokens})")
            for i, r in enumerate(resultados, 1):
                if r["erro"]:
                    print(f"    {i}. ERRO: {r['erro'][:110]}")
                else:
                    print(f"    {i}. {r['texto'].strip()[:70]!r}")
            print(f"    vazias: {vazias}/{AMOSTRAS}   "
                  f"erros: {erros}/{AMOSTRAS}   "
                  f"decisão correta: {acertos}/{AMOSTRAS}")

            if vazias:
                problemas.append(
                    f"{modelo} / {rotulo} / max_tokens={max_tokens}: "
                    f"{vazias} de {AMOSTRAS} respostas VAZIAS"
                )
            if erros:
                problemas.append(
                    f"{modelo} / {rotulo} / max_tokens={max_tokens}: "
                    f"{erros} de {AMOSTRAS} com ERRO"
                )
            if acertos < AMOSTRAS and not vazias and not erros:
                problemas.append(
                    f"{modelo} / {rotulo} / max_tokens={max_tokens}: "
                    f"decisão errada em {AMOSTRAS - acertos} de {AMOSTRAS}"
                )
            print()

    print("=" * 78)
    print("CONCLUSÃO")
    print("=" * 78)
    if not problemas:
        print("Nenhum problema. Os orçamentos curtos de 8, 10 e 16 tokens")
        print("sobrevivem no Claude, e a decisão SIM/NAO sai correta.")
        print("As rotas podem ser migradas sem mexer no max_tokens.")
        return 0

    print("Problemas encontrados:")
    for p in problemas:
        print(f"  - {p}")
    print()
    print("Requisito 5.3: aumentar o max_tokens da rota ou endurecer a")
    print("instrução de formato, e registrar a medição em comentário.")
    return 1


if __name__ == "__main__":
    raise SystemExit(principal())
