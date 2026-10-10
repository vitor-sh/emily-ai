"""Exercita a rolagem real com mensagens e mudanças tardias de layout."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def test_chat_acompanha_mensagem_e_resposta_mesmo_longe_do_fim():
    js = (Path(__file__).resolve().parent.parent / 'web/app.js').read_text()
    trecho = js[js.index('function ligarFluxo()'):js.index('function fontesDaResposta(')]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('''<style>
          #fluxo { height:300px; overflow:auto; }
          #fluxo-in { padding:8px; }
          .msg { min-height:90px; }
          </style><div id="fluxo"><div id="fluxo-in"></div></div><button id="ir-fim"></button>''')
        page.evaluate('''() => {
          window.$ = s => document.querySelector(s);
          window.ESTADO = {tela:'chat'};
          window.irPara = () => {};
          window._marcarMensagemEstruturada = () => {};
          window.acoesDaMsg = () => {};
        }''')
        page.add_script_tag(content=trecho)
        page.evaluate('''() => {
          ligarFluxo();
          for(let i=0;i<20;i++) novaMsg('emily','Histórico '+i);
        }''')
        page.wait_for_timeout(80)
        page.evaluate("$('#fluxo').scrollTop=0")
        page.evaluate("novaMsg('user','Mensagem recebida por voz')")
        page.wait_for_function("$('#fluxo').scrollHeight - $('#fluxo').scrollTop - $('#fluxo').clientHeight < 2")
        # Crescimento maior que o limite antigo de 240px não perde o seguimento.
        page.evaluate('''() => {
          novaMsg('emily','<div id="resposta" style="height:900px">Resposta longa</div>');
          rolarSePerto();
        }''')
        page.wait_for_function("$('#fluxo').scrollHeight - $('#fluxo').scrollTop - $('#fluxo').clientHeight < 2")
        # Sem outro evento do modelo: simula imagem carregando depois.
        page.evaluate("$('#resposta').style.height='1700px'")
        page.wait_for_function("$('#fluxo').scrollHeight - $('#fluxo').scrollTop - $('#fluxo').clientHeight < 2")
        page.wait_for_timeout(100)  # conclui os frames do último layout
        # Pode reler normalmente quando não há mensagens/layout novos.
        page.evaluate("$('#fluxo').scrollTop=0")
        page.wait_for_timeout(100)
        assert page.evaluate("$('#fluxo').scrollTop") == 0
        browser.close()
