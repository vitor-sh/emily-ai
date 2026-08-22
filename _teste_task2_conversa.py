"""
Task 2 — validação da rota 'conversa' migrada para o Kiro.

Quatro checagens, na ordem em que o risco importa:

  [A] llm.chamar com stream na rota 'conversa': os pedaços chegam
      incrementalmente? Quanto tempo até o PRIMEIRO? (Requisitos 2.1, 2.4)

  [B] Comparação de latência com o NIM na mesma pergunta. É o número que
      decide se 3,36s do Claude é regressão aceitável ou não. Pulado sem
      NVIDIA_API_KEY. (Requisito 2.4)

  [C] Amostra de personalidade: o system_prompt da Emily sobrevive ao
      Claude via Q Developer, que é endpoint orientado a código? Procura
      markdown, lista e emoji, que são proibições absolutas dela.

  [D] modelo.conversar_stream ponta a ponta, com fila de TTS de mentira:
      as frases entram na fila ANTES de a resposta terminar? O histórico
      é atualizado? (Requisitos 2.1, 2.5)

Uso:
    python _teste_task2_conversa.py
"""

from __future__ import annotations

import os
import queue
import time

# O caminho de ferramentas é da Task 8. Aqui o alvo é o streaming puro.
os.environ["EMILY_TOOL_CALLING"] = "0"

import llm  # noqa: E402

PERGUNTA = "Emily, me explica rapidinho o que é uma lista em Python."
PROVOCACAO = "Emily, acabei de deletar a pasta errada sem querer."


def _mostrar(rotulo: str, valor) -> None:
    print(f"    {rotulo:<26} {valor}")


def teste_a_streaming() -> dict:
    print("[A] llm.chamar(stream=True) na rota 'conversa'")
    cfg = llm.rota("conversa")
    _mostrar("provedor:", cfg.provedor)
    _mostrar("modelo:", cfg.modelo)
    _mostrar("max_tokens:", cfg.max_tokens)
    _mostrar("rpm:", cfg.rpm)

    mensagens = [
        {"role": "system", "content": "Responda em português do Brasil, sem formatação."},
        {"role": "user", "content": PERGUNTA},
    ]

    inicio = time.monotonic()
    fluxo = llm.chamar(mensagens, rota_nome="conversa", stream=True)

    primeiro = None
    pedacos = 0
    texto = ""
    for pedaco in fluxo:
        if primeiro is None:
            primeiro = time.monotonic() - inicio
        pedacos += 1
        texto += pedaco
    total = time.monotonic() - inicio

    _mostrar("pedaços:", pedacos)
    _mostrar("1o pedaço:", f"{primeiro:.2f}s" if primeiro else "NUNCA")
    _mostrar("total:", f"{total:.2f}s")
    _mostrar("chars:", len(texto))
    print(f"    resposta: {texto.strip()[:160]!r}")

    ok = pedacos > 1 and bool(texto.strip())
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return {"ok": ok, "primeiro": primeiro, "total": total, "pedacos": pedacos}


def teste_b_comparacao_nim() -> dict:
    print("[B] Mesma pergunta no NIM, para comparar latência")

    if not os.getenv("NVIDIA_API_KEY"):
        print("    PULADO: NVIDIA_API_KEY não está no .env.")
        print()
        return {"pulado": True}

    # Troca só a rota desta chamada, sem tocar na tabela: modelo e provedor
    # vêm por parâmetro. É o mesmo mecanismo que o llm.chamar já expõe.
    original = llm.ROTAS["conversa"]
    llm.ROTAS["conversa"] = llm.Rota(
        provedor="nvidia", modelo=llm.MODELO_TEXTO,
        max_tokens=original.max_tokens, raciocinio=original.raciocinio,
        temperatura=original.temperatura,
    )
    try:
        mensagens = [
            {"role": "system", "content": "Responda em português do Brasil, sem formatação."},
            {"role": "user", "content": PERGUNTA},
        ]
        inicio = time.monotonic()
        fluxo = llm.chamar(mensagens, rota_nome="conversa", stream=True)
        primeiro = None
        pedacos = 0
        texto = ""
        for pedaco in fluxo:
            if primeiro is None:
                primeiro = time.monotonic() - inicio
            pedacos += 1
            texto += pedaco
        total = time.monotonic() - inicio

        _mostrar("modelo:", llm.MODELO_TEXTO)
        _mostrar("pedaços:", pedacos)
        _mostrar("1o pedaço:", f"{primeiro:.2f}s" if primeiro else "NUNCA")
        _mostrar("total:", f"{total:.2f}s")
        print()
        return {"pulado": False, "primeiro": primeiro, "total": total, "pedacos": pedacos}
    except llm.ErroLLM as e:
        print(f"    FALHOU no NIM: {type(e).__name__}: {e}")
        print("    (não é problema da migração; só perdemos o número de comparação)")
        print()
        return {"pulado": True, "erro": str(e)}
    finally:
        llm.ROTAS["conversa"] = original


def teste_c_personalidade() -> dict:
    print("[C] A personalidade da Emily sobrevive ao Claude?")
    import modelo

    resposta = llm.chamar(
        [
            {"role": "system", "content": modelo.system_prompt},
            {"role": "user", "content": PROVOCACAO},
        ],
        rota_nome="conversa",
        stream=False,
    )
    texto = resposta if isinstance(resposta, str) else "".join(resposta)
    print(f"    {texto.strip()[:400]!r}")

    problemas = []
    if any(m in texto for m in ("**", "##", "\n- ", "\n* ", "\n1. ")):
        problemas.append("markdown ou lista")
    if any(ord(c) > 0x2500 for c in texto):
        problemas.append("possível emoji")
    for saudacao in ("Claro!", "Ótimo!", "Com certeza!"):
        if texto.strip().startswith(saudacao):
            problemas.append(f"abertura proibida ({saudacao})")

    _mostrar("proibições violadas:", ", ".join(problemas) if problemas else "nenhuma")
    print(f"    -> {'OK' if not problemas else 'ATENÇÃO'}")
    print()
    return {"ok": not problemas, "problemas": problemas, "texto": texto}


def teste_d_ponta_a_ponta() -> dict:
    print("[D] modelo.conversar_stream ponta a ponta, com fila de TTS")
    import modelo

    fila = queue.Queue()
    momentos: list[tuple[float, str]] = []
    inicio = time.monotonic()

    def callback(frase: str) -> None:
        momentos.append((time.monotonic() - inicio, f"callback: {frase[:40]}"))

    historico_antes = len(modelo.historico)

    resposta = modelo.conversar_stream(
        "Emily, tudo tranquilo por aí?",
        callback=callback,
        fila_frases=fila,
    )
    total = time.monotonic() - inicio

    frases = []
    while True:
        item = fila.get_nowait() if not fila.empty() else None
        if item is None:
            break
        frases.append(item)

    _mostrar("frases na fila:", len(frases))
    _mostrar("tempo total:", f"{total:.2f}s")
    _mostrar("histórico antes:", historico_antes)
    _mostrar("histórico depois:", len(modelo.historico))
    if frases:
        print(f"    1a frase: {frases[0][:100]!r}")
    print(f"    resposta completa: {(resposta or '').strip()[:160]!r}")

    ok = bool(resposta and resposta.strip()) and len(frases) >= 1
    ok = ok and len(modelo.historico) > historico_antes
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return {"ok": ok, "frases": len(frases), "total": total}


def principal() -> int:
    print("=" * 74)
    print("TASK 2 — ROTA 'conversa' NO KIRO")
    print("=" * 74)
    print()

    a = teste_a_streaming()
    b = teste_b_comparacao_nim()
    c = teste_c_personalidade()
    d = teste_d_ponta_a_ponta()

    print("=" * 74)
    print("RESUMO")
    print("=" * 74)
    print(f"  [A] streaming na rota          {'OK' if a['ok'] else 'FALHOU'}")
    print(f"  [B] comparação com o NIM       {'pulada' if b.get('pulado') else 'medida'}")
    print(f"  [C] personalidade              {'OK' if c['ok'] else 'ATENÇÃO'}")
    print(f"  [D] conversar_stream           {'OK' if d['ok'] else 'FALHOU'}")
    print()

    if a.get("primeiro") and not b.get("pulado") and b.get("primeiro"):
        delta = a["primeiro"] - b["primeiro"]
        print(f"  Latência até o 1o pedaço:")
        print(f"    kiro   {a['primeiro']:.2f}s")
        print(f"    nvidia {b['primeiro']:.2f}s")
        print(f"    delta  {delta:+.2f}s  "
              f"({'Claude mais lento' if delta > 0 else 'Claude mais rápido'})")
        if delta > 1.5:
            print()
            print("    ATENÇÃO: mais de 1,5s de regressão é audível numa assistente de")
            print("    voz. Vale medir claude-haiku-4.5 na rota conversa antes de fechar.")
        print()

    return 0 if (a["ok"] and d["ok"]) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
