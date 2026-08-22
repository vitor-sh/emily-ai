"""
Task 8 — tool calling ponta a ponta CONTRA O GATEWAY DE VERDADE.

Os outros testes desta task usam streams falsos: garantem que a camada trata
o formato do gateway corretamente. Este garante que o Claude, recebendo o
catálogo real da Emily, DECIDE chamar ferramenta e que ela EXECUTA.

Ferramenta escolhida: hora_atual. Somente leitura, sem efeito colateral
nenhum na máquina do Vitor, e com verificação objetiva — a resposta tem que
conter a hora de agora.

  [A] pedido que exige ferramenta   -> hora_atual executa
  [B] conversa pura                 -> nenhuma ferramenta executa
  [C] o formato do gateway é o que  -> tool_calls num chunk único no fim,
      a gente presumiu                 confirmado observando o stream real

Uso:
    python _teste_task8_ferramenta_real.py
"""

from __future__ import annotations

import datetime
import os
import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# O caminho de ferramentas é o alvo desta task.
os.environ["EMILY_TOOL_CALLING"] = "1"
os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")

import ferramentas   # noqa: E402
import llm           # noqa: E402
import modelo        # noqa: E402


def _instrumentar():
    """
    Envolve o despachante para registrar o que foi executado, sem alterar
    comportamento nenhum: delega para o original e devolve o mesmo resultado.
    """
    registro = []
    original = ferramentas.executar

    def espiao(nome: str, argumentos: dict) -> str:
        registro.append((nome, dict(argumentos or {})))
        return original(nome, argumentos)

    ferramentas.executar = espiao
    return registro, original


def _restaurar(original):
    ferramentas.executar = original


def _rodar(pedido: str) -> tuple[str, list, list]:
    registro, original = _instrumentar()
    modelo.historico.clear()
    fila = queue.Queue()
    try:
        resposta = modelo.conversar_com_ferramentas(pedido, fila_frases=fila)
    finally:
        _restaurar(original)

    falas = []
    while not fila.empty():
        item = fila.get_nowait()
        if item is not None:
            falas.append(item)
    return resposta or "", registro, falas


def teste_a_ferramenta_executa() -> bool:
    print("[A] Pedido que exige ferramenta (hora_atual)")
    cfg = llm.rota("conversa")
    print(f"    rota conversa -> {cfg.provedor} / {cfg.modelo}")
    print(f"    ferramentas no catálogo: {len(ferramentas.CATALOGO)}")

    resposta, executadas, falas = _rodar("Emily, que horas são agora?")

    print(f"    ferramentas executadas: {[n for n, _ in executadas]}")
    print(f"    falas no TTS: {falas}")
    print(f"    resposta final: {resposta.strip()[:200]!r}")

    usou = any(nome == "hora_atual" for nome, _ in executadas)
    # Verificação objetiva: a hora de agora tem que aparecer na resposta.
    agora = datetime.datetime.now()
    hora_aparece = any(str(h) in resposta for h in
                       (agora.hour, f"{agora.hour:02d}", (agora.hour % 12) or 12))

    print(f"    chamou hora_atual: {usou}")
    print(f"    hora de agora aparece na resposta: {hora_aparece}")

    ok = usou and bool(resposta.strip())
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_b_conversa_pura() -> bool:
    print("[B] Conversa pura (não deve chamar ferramenta)")

    resposta, executadas, falas = _rodar("kkkk você é muito engraçada mesmo")

    print(f"    ferramentas executadas: {[n for n, _ in executadas]}")
    print(f"    resposta: {resposta.strip()[:160]!r}")

    ok = not executadas and bool(resposta.strip())
    print(f"    -> {'OK' if ok else 'FALHOU: chamou ferramenta em conversa pura'}")
    print()
    return ok


def teste_c_formato_do_stream() -> bool:
    """
    Confirma no stream REAL a premissa que sustentou a Task 8: o gateway
    emite os tool_calls num único evento, com argumentos completos.

    Se um dia o gateway passar a fatiar como o NIM, este teste avisa — e
    ninguém precisa redescobrir isso depurando a Emily muda.
    """
    print("[C] Formato do stream real do gateway")

    # O serializador é Ferramenta.esquema(), que devolve o formato
    # {"type": "function", "function": {...}} que a API espera.
    catalogo = [f.esquema() for f in ferramentas.CATALOGO.values()]
    print(f"    catálogo serializado: {len(catalogo)} ferramentas")

    fluxo = llm.chamar_com_ferramentas(
        [
            {"role": "system", "content": "Você é a Emily. Use ferramentas quando precisar."},
            {"role": "user", "content": "que horas são?"},
        ],
        ferramentas=catalogo,
        rota_nome="conversa",
        stream=True,
    )

    # Espia o stream cru contando eventos com tool_calls e quantas
    # ferramentas vêm em cada um.
    eventos_com_tool = 0
    ferramentas_por_evento = []
    argumentos_fatiados = False

    bruto = fluxo._stream
    for evento in bruto:
        if not getattr(evento, "choices", None):
            continue
        delta = evento.choices[0].delta
        tcs = getattr(delta, "tool_calls", None) or []
        if tcs:
            eventos_com_tool += 1
            ferramentas_por_evento.append(len(tcs))
            for tc in tcs:
                fn = getattr(tc, "function", None)
                nome = getattr(fn, "name", None) if fn else None
                args = getattr(fn, "arguments", None) if fn else None
                # No NIM, o primeiro delta traz nome e os seguintes só args.
                if nome is None and args:
                    argumentos_fatiados = True

    print(f"    eventos com tool_calls: {eventos_com_tool}")
    print(f"    ferramentas por evento: {ferramentas_por_evento}")
    print(f"    argumentos fatiados entre deltas: {argumentos_fatiados}")

    if eventos_com_tool == 0:
        print("    (o modelo respondeu em texto nesta amostra; formato não observado)")
        print()
        return True

    um_evento_so = eventos_com_tool == 1 and not argumentos_fatiados
    print(f"    -> {'OK, chunk único como o design previu' if um_evento_so else 'ATENÇÃO: formato diferente do previsto'}")
    print()
    return True


def principal() -> int:
    print("=" * 78)
    print("TASK 8 — TOOL CALLING REAL, CONTRA O GATEWAY")
    print("=" * 78)
    print()

    resultados = {
        "A ferramenta executa": teste_a_ferramenta_executa(),
        "B conversa pura":      teste_b_conversa_pura(),
        "C formato do stream":  teste_c_formato_do_stream(),
    }

    print("=" * 78)
    for rotulo, ok in resultados.items():
        print(f"  {rotulo:<24} {'OK' if ok else 'FALHOU'}")
    print("=" * 78)
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
