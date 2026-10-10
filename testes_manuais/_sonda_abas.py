"""Sonda rápida: abre a janela e testa as abas de memória nas configurações.
Escreve o veredito em _sonda_abas.txt. Precisa de janela gráfica.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import os
import threading
import time

os.environ.setdefault("EMILY_EXTRACT_FACTS", "0")
import interface_web as W

LOG = open("testes_manuais/_sonda_abas.txt", "w", encoding="utf-8")


def diz(*a):
    print(*a, file=LOG, flush=True)


j = W.JanelaEmily(callback_texto=lambda t: None)

falhas = []


def check(rot, valor, esperado=True):
    bom = (valor == esperado) if not callable(esperado) else esperado(valor)
    diz(f"  {'OK   ' if bom else 'FALHA'} {rot}: {valor!r}")
    if not bom:
        falhas.append(rot)


def sonda():
    for _ in range(80):
        if j._pronta.is_set():
            break
        time.sleep(0.25)
    if not j._pronta.is_set():
        diz("PONTE NAO SUBIU")
        LOG.close()
        os._exit(3)
    q = j._janela.evaluate_js

    q("irPara('config')"); time.sleep(1.2)
    check("as duas abas de memória existem",
          q('document.querySelectorAll(".mem-aba").length'), 2)
    check("aba 'Você' começa ativa e pessoas oculta",
          q('(function(){var v=document.querySelector("#cfg-mem");'
            'var p=document.querySelector("#cfg-mem-pessoas");'
            'return !v.hidden && p.hidden;})()'))
    n_cartoes = q('document.querySelectorAll("#cfg-mem-pessoas .pessoa").length')
    check("pessoas só entram quando a aba abre", n_cartoes, lambda v: int(v) == 0)

    q('document.querySelector(\'.mem-aba[data-mem="pessoas"]\').click()')
    time.sleep(0.5)
    check("troca pra pessoas esconde a lista do Vitor",
          q('(function(){var v=document.querySelector("#cfg-mem");'
            'var p=document.querySelector("#cfg-mem-pessoas");'
            'return v.hidden && !p.hidden;})()'))
    n_cartoes = q('document.querySelectorAll("#cfg-mem-pessoas .pessoa").length')
    diz(f"  info: {n_cartoes} cartão(ões) de pessoa renderizado(s)")
    if int(n_cartoes) > 0:
        q('document.querySelector(".pessoa-cab").click()'); time.sleep(0.3)
        check("clicar na pessoa abre a ficha",
              q('!document.querySelector(".pessoa-corpo").hidden'))
        check("ficha tem campo pra ensinar fato",
              q('!!document.querySelector(".pessoa-corpo .add-fato input")'))

    check("zero erros no console",
          q('window.__erros === undefined || window.__erros.length === 0'))

    diz(f"falhas: {falhas}")
    LOG.close()
    os._exit(1 if falhas else 0)


threading.Thread(target=sonda, daemon=True).start()
j.iniciar()
