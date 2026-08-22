"""
Task 4 — a falha de gateway é audível e específica?

Valida o caminho inteiro da má notícia, de ponta a ponta:

    gateway.ErroGateway(motivo)
      -> ProvedorKiro traduz em llm.ErroConfiguracao (preservando a causa)
      -> chamar() NÃO repete (é a classe que o retry ignora)
      -> conversar_stream põe a frase ESPECÍFICA na fila do TTS

Cenários:
  [A] credencial expirada        -> "o login do Kiro expirou"
  [B] porta tomada por outro     -> "tem outra coisa usando a porta"
  [C] pasta do gateway ausente   -> "a pasta do meu gateway não tá aqui"
  [D] falha que NÃO é de gateway -> frase genérica de sempre
  [E] o retry não repete         -> provedor acionado exatamente uma vez
  [F] gateway de verdade no ar   -> conversa normal continua funcionando

Nenhum cenário de A a E toca a rede: a falha é injetada em
gateway.garantir. O [F] usa o gateway real.

Uso:
    python _teste_task4_falha_audivel.py
"""

from __future__ import annotations

import os
import queue
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ["EMILY_TOOL_CALLING"] = "0"   # o caminho de ferramentas é da Task 8

import gateway   # noqa: E402
import llm       # noqa: E402
import modelo    # noqa: E402


def _falar_falha(motivo: str, detalhe: str = "detalhe qualquer") -> tuple[str, list]:
    """
    Injeta uma falha de gateway e devolve (frase falada, chamadas ao provedor).

    Substitui garantir() por uma função que sempre levanta, e conta quantas
    vezes o provedor chegou a ser acionado — é assim que se prova que o
    retry não está repetindo.
    """
    acionamentos = []

    original_garantir = gateway.garantir
    provedor = llm.PROVEDORES["kiro"]
    original_chamar = type(provedor).chamar

    def garantir_falso():
        raise gateway.ErroGateway(motivo, detalhe)

    def chamar_contado(self, **kwargs):
        acionamentos.append(1)
        return original_chamar(self, **kwargs)

    gateway.garantir = garantir_falso
    type(provedor).chamar = chamar_contado

    fila = queue.Queue()
    try:
        modelo.conversar_stream(
            "Emily, tá tudo certo?",
            callback=lambda _f: None,
            fila_frases=fila,
        )
    finally:
        gateway.garantir = original_garantir
        type(provedor).chamar = original_chamar

    frases = []
    while not fila.empty():
        item = fila.get_nowait()
        if item is not None:
            frases.append(item)

    return (frases[0] if frases else ""), acionamentos


def cenario(rotulo: str, motivo: str, trecho_esperado: str) -> bool:
    print(f"[{rotulo}] motivo '{motivo}'")
    frase, acionamentos = _falar_falha(motivo)
    print(f"    frase falada:  {frase!r}")
    print(f"    provedor acionado: {len(acionamentos)}x")

    ok_frase = trecho_esperado.lower() in frase.lower()
    ok_uma_vez = len(acionamentos) <= 1
    ok_sem_markdown = not any(m in frase for m in ("**", "##", "- ", "`"))
    ok_sem_emoji = all(ord(c) < 0x2500 for c in frase)

    print(f"    contém {trecho_esperado!r}: {ok_frase}")
    print(f"    sem markdown/emoji:      {ok_sem_markdown and ok_sem_emoji}")
    print(f"    -> {'OK' if (ok_frase and ok_uma_vez and ok_sem_markdown and ok_sem_emoji) else 'FALHOU'}")
    print()
    return ok_frase and ok_uma_vez and ok_sem_markdown and ok_sem_emoji


def cenario_generico() -> bool:
    """Falha que não é de gateway deve manter a frase genérica de sempre."""
    print("[D] falha que não é de gateway")

    provedor = llm.PROVEDORES["kiro"]
    original_chamar = type(provedor).chamar

    def chamar_que_quebra(self, **kwargs):
        raise llm.ErroTransporte("timeout do endpoint, nada a ver com gateway")

    type(provedor).chamar = chamar_que_quebra
    fila = queue.Queue()
    try:
        modelo.conversar_stream("Emily, e ai?", callback=lambda _f: None, fila_frases=fila)
    finally:
        type(provedor).chamar = original_chamar

    frases = []
    while not fila.empty():
        item = fila.get_nowait()
        if item is not None:
            frases.append(item)

    frase = frases[0] if frases else ""
    print(f"    frase falada: {frase!r}")
    ok = frase == modelo.FRASE_FALHA_GENERICA
    print(f"    -> {'OK, usou a genérica' if ok else 'FALHOU'}")
    print()
    return ok


def cenario_gateway_real() -> bool:
    """Com o gateway de verdade, a conversa tem que funcionar normalmente."""
    print("[F] gateway real no ar, conversa normal")
    fila = queue.Queue()
    try:
        resposta = modelo.conversar_stream(
            "Emily, responde curtinho: tá tudo funcionando?",
            callback=lambda _f: None,
            fila_frases=fila,
        )
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False

    print(f"    resposta: {(resposta or '').strip()[:140]!r}")
    ok = bool(resposta and resposta.strip())
    ok = ok and resposta.strip() != modelo.FRASE_FALHA_GENERICA
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def cenario_porta_ocupada_de_verdade() -> bool:
    """
    Sabotagem real: abre um socket ouvindo na porta do gateway.

    Os testes de propriedade dublam o `_porta_ocupada`, então este é o único
    lugar onde a detecção é exercitada de ponta a ponta — socket real,
    classificação real, frase real. O socket aceita conexão e não responde
    nada, que é exatamente o caso ruim: a porta parece viva mas quem está
    lá não é o gateway.
    """
    import socket
    import threading

    print("[G] sabotagem real: porta 8000 tomada por outro programa")

    # Derruba um gateway nosso, se houver, para a porta ficar livre.
    gateway.derrubar()
    if gateway.esta_no_ar():
        print("    PULADO: tem um gateway no ar que não é nosso (suba/derrube à mão).")
        print()
        return True

    # O impostor tem que ser REALISTA, e a primeira versão deste teste não
    # era — o que gerou um falso negativo instrutivo:
    #
    #   - com SO_REUSEADDR, o Windows PERMITE dois sockets na mesma porta
    #     (diferente do Linux), então o uvicorn conseguia subir junto;
    #   - com listen(1) e sem nunca chamar accept(), o backlog enchia com a
    #     conexão do health check e a sondagem seguinte era recusada, então
    #     _porta_ocupada() devolvia False.
    #
    # Programa de verdade que ocupa porta aceita conexão. Então: sem
    # SO_REUSEADDR, backlog folgado, e uma thread drenando o accept.
    impostor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    parar = threading.Event()

    def drenar():
        """Aceita e descarta conexões, como qualquer servidor faria."""
        while not parar.is_set():
            try:
                conexao, _ = impostor.accept()
                conexao.close()
            except OSError:
                return

    try:
        impostor.bind(("127.0.0.1", 8000))
        impostor.listen(16)
        impostor.settimeout(0.5)
        threading.Thread(target=drenar, daemon=True).start()
        print("    socket impostor ouvindo em 127.0.0.1:8000 (aceitando conexões)")

        gateway._ultimo_ok = 0.0   # invalida o cache de TTL
        try:
            gateway.garantir()
        except gateway.ErroGateway as e:
            print(f"    motivo:        {e.motivo}")
            print(f"    frase falada:  {e.frase()!r}")
            ok = e.motivo == gateway.MOTIVO_PORTA_OCUPADA
            print(f"    -> {'OK' if ok else 'FALHOU: motivo errado'}")
            print()
            return ok
        else:
            print("    -> FALHOU: garantir() não levantou exceção")
            print()
            return False
    except OSError as e:
        print(f"    PULADO: não consegui tomar a porta ({e})")
        print()
        return True
    finally:
        parar.set()
        impostor.close()
        gateway._ultimo_ok = 0.0


def principal() -> int:
    print("=" * 74)
    print("TASK 4 — FALHA DE GATEWAY AUDÍVEL E ESPECÍFICA")
    print("=" * 74)
    print()

    resultados = [
        cenario("A", gateway.MOTIVO_CREDENCIAL, "login do Kiro"),
        cenario("B", gateway.MOTIVO_PORTA_OCUPADA, "porta"),
        cenario("C", gateway.MOTIVO_SEM_PASTA, "pasta"),
        cenario_generico(),
    ]

    print("[E] o retry não repete falha de gateway")
    _, acionamentos = _falar_falha(gateway.MOTIVO_CREDENCIAL)
    ok_retry = len(acionamentos) <= 1
    print(f"    provedor acionado {len(acionamentos)}x (esperado: no máximo 1)")
    print(f"    -> {'OK' if ok_retry else 'FALHOU: o retry está insistindo'}")
    print()
    resultados.append(ok_retry)

    resultados.append(cenario_gateway_real())
    resultados.append(cenario_porta_ocupada_de_verdade())

    print("=" * 74)
    rotulos = ["A credencial", "B porta ocupada", "C pasta ausente",
               "D genérica", "E sem retry", "F gateway real",
               "G porta real"]
    for rotulo, ok in zip(rotulos, resultados):
        print(f"  {rotulo:<18} {'OK' if ok else 'FALHOU'}")
    print("=" * 74)
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
