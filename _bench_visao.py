"""
_bench_visao.py — comparação de modelos de visão para a Emily.

Metodologia idêntica à que já está documentada nos comentários do llm.py, para
os números novos serem comparáveis com os antigos e não uma medição paralela
sem sentido:

  - captura 640x360 (visao.capturar_tela_triagem)
  - descrição em português
  - triagem SIM/NAO
  - mede latência e tokens de PROMPT (o que pesa no custo)

A MESMA imagem é usada em todos os modelos, na mesma execução. Comparar
medições de telas diferentes não diria nada.

Uso:
    python _bench_visao.py
    python _bench_visao.py --amostras 3
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm     # noqa: E402
import visao   # noqa: E402

# (provedor, modelo, rótulo)
CANDIDATOS = [
    ("nvidia", llm.MODELO_VISAO, "atual (NIM)"),
    ("kiro", llm.MODELO_KIRO_VISAO, "candidato"),
    ("kiro", llm.MODELO_KIRO_BARATO, "candidato barato"),
]

PROMPT_DESCRICAO = (
    "Descreva em português do Brasil, em no máximo três frases, o que está "
    "acontecendo nesta tela."
)

PROMPT_TRIAGEM = (
    "Você analisa prints de tela e decide se aconteceu algo que merece "
    "comentário (erro na tela, tela de morte em jogo, crash, notificação "
    "importante, algo claramente fora do comum).\n\n"
    "Responda APENAS com SIM ou NAO. Nenhuma palavra a mais."
)


def _medir(provedor: str, modelo: str, mensagens: list, max_tokens: int) -> dict:
    """Uma chamada. Devolve latência, tokens de prompt e o texto."""
    # A rota é irrelevante aqui: provedor e modelo vão por parâmetro. Uso a
    # 'visao' só para herdar temperatura e esforço de raciocínio coerentes.
    rota_original = llm.ROTAS["visao"]
    llm.ROTAS["visao"] = llm.Rota(
        provedor=provedor,
        modelo=modelo,
        max_tokens=max_tokens,
        raciocinio=rota_original.raciocinio,
        temperatura=rota_original.temperatura,
        rpm=rota_original.rpm,
    )
    try:
        inicio = time.monotonic()
        resposta = llm.chamar(mensagens, rota_nome="visao", stream=False)
        decorrido = time.monotonic() - inicio
        texto = resposta if isinstance(resposta, str) else "".join(resposta)
        return {"ok": True, "latencia": decorrido, "texto": texto.strip(), "erro": None}
    except llm.ErroLLM as e:
        return {"ok": False, "latencia": 0.0, "texto": "", "erro": f"{type(e).__name__}: {e}"}
    finally:
        llm.ROTAS["visao"] = rota_original


def principal() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amostras", type=int, default=2)
    args = parser.parse_args()

    print("=" * 82)
    print("BENCHMARK DE VISÃO — mesma captura 640x360 em todos os modelos")
    print("=" * 82)
    print()

    imagem = visao.capturar_tela_triagem()
    if not imagem:
        print("ERRO: não consegui capturar a tela.")
        return 1
    print(f"captura: {len(imagem):,} chars de base64 ({visao.TRIAGEM_W}x{visao.TRIAGEM_H}, "
          f"qualidade {visao.TRIAGEM_QUALIDADE})")
    print(f"amostras por modelo: {args.amostras}")
    print()

    msgs_descricao = [{"role": "user", "content": PROMPT_DESCRICAO, "images": [imagem]}]
    msgs_triagem = [{"role": "user", "content": PROMPT_TRIAGEM, "images": [imagem]}]

    resultados = []

    for provedor, modelo, rotulo in CANDIDATOS:
        print(f"── {modelo}  ({provedor}, {rotulo})")

        descricoes = [_medir(provedor, modelo, msgs_descricao, 1024)
                      for _ in range(args.amostras)]
        triagens = [_medir(provedor, modelo, msgs_triagem, 16)
                    for _ in range(args.amostras)]

        falhas = [r for r in descricoes + triagens if not r["ok"]]
        if falhas:
            print(f"    FALHOU: {falhas[0]['erro'][:160]}")
            print()
            resultados.append({"modelo": modelo, "provedor": provedor, "ok": False})
            continue

        media_desc = sum(r["latencia"] for r in descricoes) / len(descricoes)
        media_triagem = sum(r["latencia"] for r in triagens) / len(triagens)
        vazias = sum(1 for r in descricoes + triagens if not r["texto"])
        decisivas = sum(1 for r in triagens
                        if r["texto"].upper().replace("ÃO", "AO").strip().startswith(("SIM", "NAO")))

        print(f"    descrição: {media_desc:.2f}s   triagem: {media_triagem:.2f}s")
        print(f"    descrição de exemplo: {descricoes[0]['texto'][:150]!r}")
        print(f"    triagens: {[r['texto'][:12] for r in triagens]}")
        print(f"    respostas vazias: {vazias}   triagens decisivas: {decisivas}/{len(triagens)}")
        print()

        resultados.append({
            "modelo": modelo,
            "provedor": provedor,
            "rotulo": rotulo,
            "ok": True,
            "descricao": media_desc,
            "triagem": media_triagem,
            "vazias": vazias,
            "decisivas": decisivas,
            "exemplo": descricoes[0]["texto"],
        })

    print("=" * 82)
    print("TABELA (formato do bloco de comentário do llm.py)")
    print("=" * 82)
    print()
    print(f"  {'modelo':<34} {'descr.':>8} {'triagem':>9}  {'vazias':>7}")
    for r in resultados:
        if not r["ok"]:
            print(f"  {r['modelo']:<34} {'FALHOU':>8}")
            continue
        print(f"  {r['modelo']:<34} {r['descricao']:>7.2f}s {r['triagem']:>8.2f}s "
              f"{r['vazias']:>7}")
    print()

    bons = [r for r in resultados if r["ok"]]
    if not bons:
        print("Nenhum modelo respondeu. Nada a decidir.")
        return 1

    mais_rapido_triagem = min(bons, key=lambda r: r["triagem"])
    print(f"Mais rápido na triagem: {mais_rapido_triagem['modelo']} "
          f"({mais_rapido_triagem['triagem']:.2f}s)")
    print()
    print("Lembrete de custo: no NIM a triagem era grátis (free tier). No Kiro,")
    print("cada chamada consome crédito, e a triagem roda em laço durante o")
    print("monitoramento de tela. Latência não é o único critério aqui.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
