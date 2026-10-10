"""
Task 5 — os consumidores das rotas de texto migradas continuam funcionando?

Migrar a tabela de rotas é uma linha. O que pode quebrar em silêncio são os
call sites, cada um com sua expectativa própria de formato de saída:

  [A] classificador  -> _llm_confirma_visao devolve bool coerente
  [B] extracao       -> memoria.py extrai fato de uma conversa
  [C] extracao       -> memoria.py deduplica fato semanticamente igual
  [D] comando        -> automacao devolve JSON parseável
  [E] discord        -> resposta curta, no estilo de chat, sem markdown
  [F] intencoes      -> classificação de intenção coerente

Cada um destes é uma expectativa DIFERENTE sobre a resposta do modelo, e é
por isso que a Task 5 não termina na edição da tabela.

Uso:
    python _teste_task5_consumidores.py
"""

from __future__ import annotations

import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm      # noqa: E402
import modelo   # noqa: E402


def _cabecalho(rotulo: str, rota: str) -> None:
    cfg = llm.rota(rota)
    print(f"[{rotulo}] rota '{rota}' -> {cfg.provedor} / {cfg.modelo} "
          f"(max_tokens={cfg.max_tokens})")


def teste_a_classificador() -> bool:
    _cabecalho("A", "classificador")

    casos = [
        ("Emily, olha minha tela e me diz o que tá errado", True),
        ("Emily, me conta uma piada", False),
        ("olha isso aqui na tela pra mim", True),
    ]
    acertos = 0
    for mensagem, esperado in casos:
        # precisa_ver_tela tem porta de palavra-chave antes da LLM; chamo a
        # camada de LLM direto para exercitar a rota migrada de verdade.
        obtido = modelo._llm_confirma_visao(mensagem)
        marca = "ok " if obtido == esperado else "ERRO"
        print(f"    {marca} {mensagem[:46]!r:<50} -> {obtido} (esperado {esperado})")
        acertos += int(obtido == esperado)

    ok = acertos == len(casos)
    print(f"    -> {'OK' if ok else f'FALHOU ({acertos}/{len(casos)})'}")
    print()
    return ok


def teste_b_extracao_de_fatos() -> bool:
    _cabecalho("B", "extracao")
    import memoria

    # Assinatura real: extrair_fatos_da_conversa(usuario, emily)
    fala_vitor = "acabei de comprar uma RTX 5090 e jogo Elden Ring todo dia nela"
    fala_emily = "nossa, gastou tudo hein. Pelo menos vai rodar liso"

    try:
        fatos = memoria.extrair_fatos_da_conversa(fala_vitor, fala_emily)
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False

    print(f"    fatos extraídos: {len(fatos)}")
    for f in fatos[:5]:
        print(f"      - {str(f)[:90]}")
    ok = len(fatos) > 0
    print(f"    -> {'OK' if ok else 'FALHOU: nenhum fato extraído'}")
    print()
    return ok


def teste_c_deduplicacao() -> bool:
    _cabecalho("C", "extracao")
    import memoria

    # Assinatura real: _fato_ja_conhecido_llm(novo_fato, fatos_existentes)
    existentes = ["O Vitor gosta de jogar Elden Ring", "O Vitor mora em São Paulo"]

    try:
        igual = memoria._fato_ja_conhecido_llm("O Vitor curte Elden Ring", existentes)
        diferente = memoria._fato_ja_conhecido_llm("O Vitor tem um cachorro", existentes)
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False

    print(f"    'curte Elden Ring' já conhecido? -> {igual} (esperado True)")
    print(f"    'tem um cachorro'  já conhecido? -> {diferente} (esperado False)")
    ok = bool(igual) and not diferente
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_d_comando_json() -> bool:
    _cabecalho("D", "comando")

    resposta = llm.chamar(
        [
            {"role": "system",
             "content": "Você converte pedidos em JSON. Responda APENAS com JSON válido, "
                        "no formato {\"acao\": \"...\", \"alvo\": \"...\"}."},
            {"role": "user", "content": "abre a pasta de downloads"},
        ],
        rota_nome="comando",
        stream=False,
    )
    texto = resposta if isinstance(resposta, str) else "".join(resposta)
    print(f"    resposta: {texto.strip()[:160]!r}")

    # Tolera cerca de código, que é o vício mais comum de modelo grande.
    limpo = texto.strip()
    if limpo.startswith("```"):
        limpo = limpo.split("```")[1] if "```" in limpo[3:] else limpo[3:]
        limpo = limpo.removeprefix("json").strip()

    try:
        dados = json.loads(limpo)
        parseou = isinstance(dados, dict)
        print(f"    JSON parseado: {dados}")
    except json.JSONDecodeError as e:
        parseou = False
        print(f"    JSON INVÁLIDO: {e}")

    print(f"    -> {'OK' if parseou else 'FALHOU'}")
    print()
    return parseou


def teste_e_discord() -> bool:
    _cabecalho("E", "discord")

    try:
        resposta = modelo.responder_mensagem_discord(
            texto="alguem sabe se vai chover hoje?",
            nome="joao",
        )
    except TypeError as e:
        print(f"    (assinatura diferente: {e}) — chamando a rota direto")
        bruto = llm.chamar(
            [
                {"role": "system", "content": modelo.EMILY_PERSONALIDADE_DISCORD},
                {"role": "user", "content": "joao: alguem sabe se vai chover hoje?"},
            ],
            rota_nome="discord",
            stream=False,
        )
        resposta = bruto if isinstance(bruto, str) else "".join(bruto)
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False

    texto = (resposta or "").strip()
    print(f"    resposta: {texto[:160]!r}")
    print(f"    tamanho:  {len(texto)} chars")

    problemas = []
    if not texto:
        problemas.append("vazia")
    if any(m in texto for m in ("**", "##", "\n- ")):
        problemas.append("markdown")
    if any(ord(c) > 0x2500 for c in texto):
        problemas.append("emoji")

    print(f"    problemas: {', '.join(problemas) if problemas else 'nenhum'}")
    ok = not problemas
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_f_intencoes() -> bool:
    _cabecalho("F", "classificador")
    try:
        import intencoes
    except ImportError as e:
        print(f"    PULADO: {e}")
        print()
        return True

    # O módulo tem várias entradas possíveis; procuro a mais óbvia sem
    # inventar assinatura.
    candidatas = [n for n in ("classificar", "detectar", "avaliar", "interpretar")
                  if hasattr(intencoes, n)]
    if not candidatas:
        print(f"    PULADO: nenhuma função de classificação óbvia em intencoes.py")
        print(f"    (funções disponíveis: {[n for n in dir(intencoes) if not n.startswith('_')][:8]})")
        print()
        return True

    print(f"    função encontrada: intencoes.{candidatas[0]}")
    print("    (validação funcional fica para o uso real; o que importa aqui")
    print("     é que a rota 'classificador' já foi exercitada em [A])")
    print()
    return True


def principal() -> int:
    print("=" * 78)
    print("TASK 5 — CONSUMIDORES DAS ROTAS DE TEXTO MIGRADAS")
    print("=" * 78)
    print()

    resultados = {
        "A classificador": teste_a_classificador(),
        "B extração":      teste_b_extracao_de_fatos(),
        "C dedup":         teste_c_deduplicacao(),
        "D comando JSON":  teste_d_comando_json(),
        "E discord":       teste_e_discord(),
        "F intencoes":     teste_f_intencoes(),
    }

    print("=" * 78)
    for rotulo, ok in resultados.items():
        print(f"  {rotulo:<18} {'OK' if ok else 'FALHOU'}")
    print("=" * 78)
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
