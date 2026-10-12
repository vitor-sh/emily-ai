"""Credencial recusada num provedor não pode calar a Emily se outro da cadeia responde.

Caso real (12/10/2026): o OmniRoute respondia 401 porque a conta Kiro de trás
perdeu a credencial, e a rota inteira abortava mesmo com o Claude externo de
reserva funcionando.
"""
from types import SimpleNamespace

import pytest

import llm


class ProvedorFalso:
    suporta_ferramentas = True

    def __init__(self, resultado):
        self.resultado = resultado
        self.chamadas = []

    def chamar(self, **kwargs):
        self.chamadas.append(kwargs["modelo"])
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


@pytest.fixture
def cadeia(monkeypatch):
    """Rota 'a_teste:m1' com reservas a_teste:m2 e b_teste:m3."""
    def montar(a, b):
        monkeypatch.setitem(llm.PROVEDORES, "a_teste", a)
        monkeypatch.setitem(llm.PROVEDORES, "b_teste", b)
        monkeypatch.setattr(llm, "limitador_de", lambda *_a: SimpleNamespace(adquirir=lambda timeout=0: True))
        monkeypatch.setattr(llm, "rota", lambda nome: llm.Rota(
            provedor="a_teste", modelo="m1", tentativas=3,
            fallbacks=(("a_teste", "m2"), ("b_teste", "m3"))))
        monkeypatch.setattr(llm.time, "sleep", lambda *_a: None)
    return montar


def test_credencial_recusada_cai_para_o_proximo_provedor(cadeia):
    a = ProvedorFalso(llm.ErroConfiguracao("provedor 'a_teste' recusou a credencial (401)."))
    b = ProvedorFalso("oi, tudo bem!")
    cadeia(a, b)
    assert llm.chamar([{"role": "user", "content": "oi"}], rota_nome="conversa") == "oi, tudo bem!"
    # Sem retry e sem tentar m2 do mesmo provedor: ele falharia igual.
    assert a.chamadas == ["m1"]
    assert b.chamadas == ["m3"]


def test_sem_outro_provedor_o_erro_original_sobe_intacto(cadeia):
    a = ProvedorFalso(llm.ErroConfiguracao("provedor 'a_teste' recusou a credencial (401)."))
    b = ProvedorFalso(llm.ErroConfiguracao("provedor 'b_teste' recusou a credencial (401)."))
    cadeia(a, b)
    with pytest.raises(llm.ErroConfiguracao, match="b_teste"):
        llm.chamar([{"role": "user", "content": "oi"}], rota_nome="conversa")
    assert a.chamadas == ["m1"] and b.chamadas == ["m3"]


def test_provedor_unico_mantem_o_comportamento_antigo(monkeypatch):
    a = ProvedorFalso(llm.ErroConfiguracao("sem chave"))
    monkeypatch.setitem(llm.PROVEDORES, "a_teste", a)
    monkeypatch.setattr(llm, "limitador_de", lambda *_a: SimpleNamespace(adquirir=lambda timeout=0: True))
    monkeypatch.setattr(llm, "rota", lambda nome: llm.Rota(
        provedor="a_teste", modelo="m1", tentativas=3, fallbacks=(("a_teste", "m2"),)))
    with pytest.raises(llm.ErroConfiguracao, match="sem chave"):
        llm.chamar([{"role": "user", "content": "oi"}], rota_nome="conversa")
    assert a.chamadas == ["m1"]


def test_erro_de_transporte_continua_tentando_do_mesmo_jeito(cadeia):
    a = ProvedorFalso(llm.ErroTransporte("500"))
    b = ProvedorFalso("ok")
    cadeia(a, b)
    assert llm.chamar([{"role": "user", "content": "oi"}], rota_nome="conversa") == "ok"
    # 3 tentativas no primário e 2 no degrau seguinte do mesmo provedor
    # (max(2, tentativas - 2)), só então o outro provedor. Nada disso mudou.
    assert a.chamadas == ["m1", "m1", "m1", "m2", "m2"]
    assert b.chamadas == ["m3"]


def test_401_do_omniroute_diz_qual_conta_esta_sem_credencial():
    provedor = object.__new__(llm.ProvedorOpenAI)
    provedor.nome = "omniroute"

    class Erro(Exception):
        status_code = 401

    with pytest.raises(llm.ErroConfiguracao) as info:
        provedor._tratar_erro(
            Erro("Error code: 401 - {'error': {'message': 'No active credentials for provider: kiro.'}}"),
            "kr/claude-sonnet-5.5", [])
    texto = str(info.value)
    assert "kiro" in texto and "painel do OmniRoute" in texto
    assert "Confira a credencial do provedor nas configurações" not in texto


def test_401_comum_continua_pedindo_para_conferir_a_chave():
    provedor = object.__new__(llm.ProvedorOpenAI)
    provedor.nome = "openai"

    class Erro(Exception):
        status_code = 401

    with pytest.raises(llm.ErroConfiguracao, match="Confira a credencial do provedor"):
        provedor._tratar_erro(Erro("Incorrect API key"), "gpt-x", [])
