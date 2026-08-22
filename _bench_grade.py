"""
_bench_grade.py — precisão de localização na grade 10x10 do agente de UI.

Por que esta medição existe
───────────────────────────
O agente de UI não descreve a tela, ele APONTA um lugar dela. Errar a célula
é clicar no lugar errado na máquina do Vitor. O comentário do llm.py registra
que essa foi exatamente a diferença que definiu o modelo atual:

    meta/llama-3.2-90b-vision-instruct   12/12 acertos
    nvidia/nemotron-nano-12b-v2-vl        7/12 acertos
    (o nemotron acerta a linha e escorrega na horizontal)

Metodologia, e por que ela é melhor que usar a tela real
────────────────────────────────────────────────────────
Com a tela real, o gabarito é o que a gente ACHA que está em cada célula. Aqui
o alvo é DESENHADO numa célula escolhida por nós, então o gabarito é exato.
A grade é aplicada pela mesma função que o agente usa em produção
(visao._desenhar_grade), sobre imagem 1280x720, para a medição valer para o
caminho real.

Mede três coisas separadas, porque elas falham separado: célula exata, linha
correta e coluna correta.

Uso:
    python _bench_grade.py
    python _bench_grade.py --amostras 12
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm     # noqa: E402
import visao   # noqa: E402

LETRAS = "ABCDEFGHIJ"

# Alvos espalhados pela tela de propósito: cantos, bordas e centro. Modelo de
# visão erra mais nas bordas e na horizontal, então concentrar tudo no meio
# daria um número bonito e mentiroso.
ALVOS = [
    "A0", "J0", "A9", "J9",     # quatro cantos
    "E4", "F5",                 # centro
    "C1", "H2",                 # topo
    "B7", "G8",                 # base
    "A5", "J4",                 # bordas laterais
]

CANDIDATOS = [
    ("nvidia", llm.MODELO_VISAO_AGENTE, "atual (NIM)"),
    ("kiro", llm.MODELO_KIRO_AGENTE_UI, "candidato"),
    ("kiro", llm.MODELO_KIRO_CONVERSA, "alternativa mais barata"),
]

PERGUNTA = (
    "Esta imagem tem uma grade 10x10 desenhada, com colunas rotuladas de A a J "
    "e linhas de 0 a 9. Cada célula tem um rótulo amarelo tipo A0, B5, J9.\n\n"
    "Existe um grande círculo MAGENTA sólido na imagem.\n\n"
    "Em qual célula da grade está o centro do círculo magenta? "
    "Responda APENAS com o rótulo da célula, tipo E4. Nada mais."
)


def _imagem_com_alvo(celula: str) -> str:
    """Desenha um círculo magenta no centro da célula informada, com a grade."""
    from PIL import Image, ImageDraw

    col = LETRAS.index(celula[0])
    lin = int(celula[1])

    largura, altura = visao.GRADE_W, visao.GRADE_H
    lc = largura / visao.GRADE_COLS
    ac = altura / visao.GRADE_LINHAS

    # Fundo com textura leve: fundo liso é mais fácil que tela de verdade, e
    # o objetivo é medir o caminho real, não facilitar.
    img = Image.new("RGB", (largura, altura), (38, 40, 48))
    d = ImageDraw.Draw(img)
    for x in range(0, largura, 40):
        d.line([(x, 0), (x, altura)], fill=(46, 48, 58), width=1)
    for y in range(0, altura, 40):
        d.line([(0, y), (largura, y)], fill=(46, 48, 58), width=1)

    cx = col * lc + lc / 2
    cy = lin * ac + ac / 2
    raio = min(lc, ac) * 0.38
    d.ellipse([(cx - raio, cy - raio), (cx + raio, cy + raio)],
              fill=(230, 0, 200), outline=(255, 255, 255), width=3)

    # A grade vai por cima, pela MESMA função que o agente usa em produção.
    img = visao._desenhar_grade(img)

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def _extrair_celula(texto: str) -> str | None:
    """Pega o primeiro rótulo de célula válido da resposta."""
    achado = re.search(r"\b([A-J])\s*([0-9])\b", texto.upper())
    return f"{achado.group(1)}{achado.group(2)}" if achado else None


def _perguntar(provedor: str, modelo: str, imagem: str) -> tuple[str | None, float, str]:
    rota_original = llm.ROTAS["agente_ui"]
    llm.ROTAS["agente_ui"] = llm.Rota(
        provedor=provedor,
        modelo=modelo,
        max_tokens=64,
        raciocinio=(llm.RACIOCINIO_DESLIGADO if provedor == "kiro"
                    else llm.RACIOCINIO_NORMAL),
        temperatura=0.0,
        rpm=rota_original.rpm,
    )
    try:
        inicio = time.monotonic()
        resposta = llm.chamar(
            [{"role": "user", "content": PERGUNTA, "images": [imagem]}],
            rota_nome="agente_ui",
            stream=False,
        )
        decorrido = time.monotonic() - inicio
        texto = resposta if isinstance(resposta, str) else "".join(resposta)
        return _extrair_celula(texto), decorrido, texto.strip()
    except llm.ErroLLM as e:
        return None, 0.0, f"ERRO: {type(e).__name__}: {e}"
    finally:
        llm.ROTAS["agente_ui"] = rota_original


def principal() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--amostras", type=int, default=len(ALVOS))
    args = parser.parse_args()

    alvos = ALVOS[:args.amostras]

    print("=" * 84)
    print("BENCHMARK DE GRADE 10x10 — precisão de localização do agente de UI")
    print("=" * 84)
    print(f"grade: {visao.GRADE_COLS}x{visao.GRADE_LINHAS} sobre {visao.GRADE_W}x{visao.GRADE_H}")
    print(f"amostras: {len(alvos)}  ({', '.join(alvos)})")
    print()
    print("Histórico registrado no llm.py, mesma metodologia:")
    print("  meta/llama-3.2-90b-vision-instruct   12/12")
    print("  nvidia/nemotron-nano-12b-v2-vl        7/12  (erra a coluna)")
    print()

    imagens = {alvo: _imagem_com_alvo(alvo) for alvo in alvos}
    resumo = []

    for provedor, modelo, rotulo in CANDIDATOS:
        print(f"── {modelo}  ({provedor}, {rotulo})")
        exatos = linhas_ok = colunas_ok = ilegiveis = 0
        latencias = []

        for alvo in alvos:
            celula, decorrido, cru = _perguntar(provedor, modelo, imagens[alvo])
            if celula is None:
                ilegiveis += 1
                print(f"    alvo {alvo}  ->  ??      ilegível: {cru[:70]!r}")
                continue

            latencias.append(decorrido)
            exato = celula == alvo
            linha_ok = celula[1] == alvo[1]
            coluna_ok = celula[0] == alvo[0]
            exatos += int(exato)
            linhas_ok += int(linha_ok)
            colunas_ok += int(coluna_ok)

            marca = "ok  " if exato else ("~col" if linha_ok else ("~lin" if coluna_ok else "ERRO"))
            print(f"    alvo {alvo}  ->  {celula}    {marca}  ({decorrido:.2f}s)")

        media = sum(latencias) / len(latencias) if latencias else 0.0
        total = len(alvos)
        print(f"    exatos: {exatos}/{total}   linha: {linhas_ok}/{total}   "
              f"coluna: {colunas_ok}/{total}   ilegíveis: {ilegiveis}   "
              f"latência média: {media:.2f}s")
        print()

        resumo.append({
            "modelo": modelo, "provedor": provedor, "rotulo": rotulo,
            "exatos": exatos, "linha": linhas_ok, "coluna": colunas_ok,
            "ilegiveis": ilegiveis, "latencia": media, "total": total,
        })

    print("=" * 84)
    print("TABELA (formato do bloco de comentário do llm.py)")
    print("=" * 84)
    print()
    print(f"  {'modelo':<38} {'exatos':>7} {'linha':>7} {'coluna':>7} {'latência':>9}")
    for r in resumo:
        print(f"  {r['modelo']:<38} {r['exatos']:>3}/{r['total']:<3} "
              f"{r['linha']:>3}/{r['total']:<3} {r['coluna']:>3}/{r['total']:<3} "
              f"{r['latencia']:>8.2f}s")
    print()

    atual = next((r for r in resumo if r["provedor"] == "nvidia"), None)
    candidato = next((r for r in resumo
                      if r["provedor"] == "kiro" and r["modelo"] == llm.MODELO_KIRO_AGENTE_UI), None)

    if atual and candidato:
        print("DECISÃO (Requisitos 7.5 e 7.6):")
        print(f"  atual      {atual['modelo']}: {atual['exatos']}/{atual['total']} exatos")
        print(f"  candidato  {candidato['modelo']}: {candidato['exatos']}/{candidato['total']} exatos")
        print()
        if candidato["exatos"] >= atual["exatos"]:
            print("  -> MIGRAR: o candidato empata ou supera o atual.")
        else:
            print("  -> NÃO MIGRAR: a rota agente_ui deve FICAR no provedor atual,")
            print("     com o motivo e estes números registrados em comentário.")
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
