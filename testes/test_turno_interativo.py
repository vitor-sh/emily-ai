"""Um segundo envio no chat deve entrar no turno ativo sem abrir outra LLM."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_duas_mensagens_rapidas_sao_processadas_em_serie():
    import interface_web
    import modelo

    iniciou = threading.Event()
    continuar = threading.Event()
    terminou = threading.Event()
    chamadas = []
    simultaneas = [0, 0]

    def callback(texto):
        simultaneas[0] += 1
        simultaneas[1] = max(simultaneas)
        chamadas.append(texto)
        if len(chamadas) == 1:
            iniciou.set()
            assert continuar.wait(3)
        simultaneas[0] -= 1
        if len(chamadas) == 2:
            terminou.set()

    class Janela:
        _cid = "conversa-teste"

        def __init__(self):
            self.registradas = []
            self.callback_texto = callback

        def _registrar_na_conversa(self, papel, texto):
            self.registradas.append((papel, texto))

        def _push(self, *_):
            pass

        def _chamar_cb(self, cb, texto):
            cb(texto)

        def _titular(self, *_):
            pass

    janela = Janela()
    api = interface_web.Api(janela)
    try:
        assert api.enviar("Abra o site", origem="teste") == janela._cid
        assert iniciou.wait(3)
        assert api.enviar("Veja também o preço de sexta", origem="teste") == janela._cid
        assert chamadas == ["Abra o site"]
        continuar.set()
        assert terminou.wait(3)
        assert chamadas == ["Abra o site", "Veja também o preço de sexta"]
        assert simultaneas[1] == 1
        assert janela.registradas == [("user", "Abra o site"),
                                      ("user", "Veja também o preço de sexta")]
    finally:
        continuar.set()
        modelo.web_turno_liberar(janela._cid)


def test_pergunta_de_tarefa_espera_resposta_e_retoma():
    import interface_web

    chegou = threading.Event()
    eventos = []

    class Janela:
        _janela = object()
        _visivel = True
        _cid = "conversa-teste"

        def _push(self, nome, dados):
            eventos.append((nome, dados))
            chegou.set()

        def _registrar_na_conversa(self, *_):
            pass

        def add_mensagem_usuario(self, *_):
            pass

    anterior = interface_web._api_registrada
    janela = Janela()
    interface_web._api_registrada = SimpleNamespace(_j=janela)
    resposta = []
    thread = threading.Thread(target=lambda: resposta.append(
        interface_web.perguntar_usuario_tarefa("Faça login e me avise", "login")))
    try:
        thread.start()
        assert chegou.wait(3)
        assert thread.is_alive()
        nome, dados = eventos[0]
        assert nome == "pergunta_usuario" and dados["tipo"] == "login"
        assert interface_web.Api.responder_pergunta_usuario(
            SimpleNamespace(_j=janela), dados["id"], "Já entrei")
        thread.join(3)
        assert resposta == ["Já entrei"]
        assert eventos[-1] == ("pergunta_usuario_fim", {"id": dados["id"]})
    finally:
        interface_web._api_registrada = anterior


def test_mensagem_interativa_so_entra_na_thread_dona():
    import modelo

    cid = "turno-isolado"
    assert modelo.web_turno_receber(cid, "pedido inicial") == "novo"
    modelo.web_turno_vincular(cid)
    try:
        assert modelo.web_turno_cid() == cid
        outra_thread = []
        thread = threading.Thread(target=lambda: outra_thread.append(modelo.web_turno_cid()))
        thread.start()
        thread.join(3)
        assert outra_thread == [""]
        assert modelo.web_turno_receber(cid, "instrução nova") == "adicionada"
        assert modelo.web_turno_drenar(cid) == ["instrução nova"]
    finally:
        modelo.web_turno_liberar(cid)
