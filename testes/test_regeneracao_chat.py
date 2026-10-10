"""Regenerar a partir do histórico salvo sem ressuscitar a timeline antiga."""

from types import SimpleNamespace


def test_regenerar_resposta_antiga_apaga_cauda_e_rejeita_sync_antigo(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    try:
        cid = conversas.criar("Primeiro pedido")
        for papel, texto in (
            ("user", "Primeiro pedido"), ("emily", "Primeira resposta"),
            ("user", "Segundo pedido"), ("emily", "Segunda resposta"),
        ):
            conversas.acrescentar(cid, papel, texto)
        antes = conversas.abrir(cid)
        mexida_antiga = conversas.listar()[0]["mexida"]

        resultado = conversas.truncar_para_regenerar(cid, 1)
        assert resultado["pedido"] == "Primeiro pedido"
        assert [m["texto"] for m in conversas.abrir(cid)] == ["Primeiro pedido"]
        assert conversas.listar()[0]["mexida"] > mexida_antiga
        assert conversas.listar()[0]["ramo"] == 1
        assert not conversas.gravar_externa(cid, "Antiga", 1, mexida_antiga, antes)
        assert not conversas.gravar_externa(cid, "Antiga", 1, mexida_antiga + 10000,
                                           antes, ramo=0)

        conversas.acrescentar(cid, "emily", "Nova resposta")
        conversas.recarregar()  # fecha e abre o chat novamente
        assert [m["texto"] for m in conversas.abrir(cid)] == [
            "Primeiro pedido", "Nova resposta"]
        assert conversas.truncar_para_regenerar(cid, 1)["pedido"] == "Primeiro pedido"
    finally:
        conversas.recarregar()


def test_ramo_novo_vence_relogio_antigo(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    try:
        cid = conversas.criar("Oi")
        conversas.acrescentar(cid, "user", "Oi")
        # Outro aparelho estava com o relógio adiantado.
        assert conversas.gravar_externa(cid, "Oi", 1, 9999999999,
                                       [{"papel": "user", "texto": "Oi", "quando": 1}], ramo=0)
        assert conversas.gravar_externa(cid, "Oi", 1, 2,
                                       [{"papel": "user", "texto": "Oi", "quando": 1}], ramo=1)
        assert conversas.listar()[0]["ramo"] == 1
        assert conversas.listar()[0]["mexida"] > 9999999999
    finally:
        conversas.recarregar()


def test_api_regenerar_usa_pedido_salvo_e_contexto_correto(tmp_path, monkeypatch):
    import conversas
    import interface_web
    import modelo

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    cid = conversas.criar("A")
    for papel, texto in (("user", "A"), ("emily", "B"),
                         ("user", "C"), ("emily", "D")):
        conversas.acrescentar(cid, papel, texto)
    chamadas = []
    timers = []

    class TimerFalso:
        def __init__(self, _intervalo, callback):
            self.callback = callback
            timers.append(self)

        def start(self):
            pass

    monkeypatch.setattr(interface_web.threading, "Timer", TimerFalso)
    eventos = []
    def responder(texto):
        chamadas.append(texto)
        conversas.acrescentar(cid, "emily", "Nova D")

    janela = SimpleNamespace(
        callback_texto=responder, _push=lambda evento, dados: eventos.append((evento, dados)),
        _cid=cid, _falando=False, _resposta_emily="", _resposta_crua="",
        _falas_processo=[], _chamar_cb=lambda fn, texto: fn(texto),
    )
    anterior = list(modelo.historico)
    try:
        api = interface_web.Api(janela)
        resposta = api.regenerar(cid, 3)
        assert resposta["ok"] is True
        assert [m["texto"] for m in resposta["mensagens"]] == ["A", "B", "C"]
        assert modelo.historico == [
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "B"},
        ]
        assert not api.regenerar(cid, 1)["ok"]  # turno simultâneo bloqueado
        timers[0].callback()
        assert chamadas == ["C"]
        assert [m["texto"] for m in conversas.abrir(cid)] == ["A", "B", "C", "Nova D"]
        assert not eventos
    finally:
        modelo.definir_historico(anterior)
        conversas.recarregar()


def test_falha_na_regeneracao_restaura_timeline_e_avisa_interface(tmp_path, monkeypatch):
    import conversas
    import interface_web
    import modelo

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    cid = conversas.criar("A")
    for papel, texto in (("user", "A"), ("emily", "B"),
                         ("user", "C"), ("emily", "D")):
        conversas.acrescentar(cid, papel, texto)
    timers, eventos = [], []

    class TimerFalso:
        def __init__(self, _intervalo, callback):
            self.callback = callback
            timers.append(self)

        def start(self):
            pass

    monkeypatch.setattr(interface_web.threading, "Timer", TimerFalso)
    janela = SimpleNamespace(
        callback_texto=lambda _texto: None, _chamar_cb=lambda fn, texto: fn(texto),
        _push=lambda evento, dados: eventos.append((evento, dados)),
        _cid=cid, _falando=False, _resposta_emily="", _resposta_crua="", _falas_processo=[])
    anterior = list(modelo.historico)
    try:
        api = interface_web.Api(janela)
        assert api.regenerar(cid, 1)["ok"]
        timers[0].callback()
        assert [m["texto"] for m in conversas.abrir(cid)] == ["A", "B", "C", "D"]
        assert eventos[0][0] == "regeneracao_falhou"
        assert api._regenerando is False
    finally:
        modelo.definir_historico(anterior)
        conversas.recarregar()
