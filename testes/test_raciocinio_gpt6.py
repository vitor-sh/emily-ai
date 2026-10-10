"""Compatibilidade dos níveis de raciocínio exibidos na Emily."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm  # noqa: E402


def test_niveis_gpt6_sao_especificos_do_modelo():
    assert [n["id"] for n in llm.niveis_raciocinio("cx/gpt-6-luna")] == [
        "desligado", "baixo", "medio", "alto", "extra_alto", "maximo",
    ]
    assert "desligado" not in [n["id"] for n in llm.niveis_raciocinio("cx/gpt-6-astra")]
    assert "desligado" not in [n["id"] for n in llm.niveis_raciocinio("cx/gpt-6.1-sol")]
    assert [n["id"] for n in llm.niveis_raciocinio("claude-sonnet-5")] == [
        "baixo", "medio", "alto",
    ]
    assert llm.PARAMS_RACIOCINIO["extra_alto"]["reasoning_effort"] == "xhigh"
    assert llm.PARAMS_RACIOCINIO["maximo"]["reasoning_effort"] == "max"
    assert llm._params_validos("openai", "cx/gpt-6-astra", "desligado") == {
        "reasoning_effort": "low",
    }


def test_chamada_gpt6_com_raciocinio_nao_envia_temperatura(monkeypatch):
    enviados = []

    def criar(**corpo):
        enviados.append(corpo)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="OK"), finish_reason="stop")])

    cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=criar)))
    provedor = llm.ProvedorOpenAI("teste", "http://example.invalid/v1", "CHAVE_FALSA")
    monkeypatch.setattr(provedor, "_obter_cliente", lambda: cliente)
    mensagem = [llm.Mensagem(papel="user", texto="Oi")]
    assert provedor.chamar(mensagem, "cx/gpt-6-sol", 128, 0.7, "alto", False) == "OK"
    assert enviados[-1]["reasoning_effort"] == "high"
    assert "temperature" not in enviados[-1]
    assert provedor.chamar(mensagem, "cx/gpt-6-luna", 128, 0.7, "desligado", False) == "OK"
    assert enviados[-1]["temperature"] == 0.7
    assert provedor.chamar(mensagem, "modelo-antigo", 128, 0.7, "alto", False) == "OK"
    assert enviados[-1]["temperature"] == 0.7


def test_astra_nao_guarda_none_ao_trocar_modelo(monkeypatch):
    rota = llm.Rota(provedor="openai", modelo="cx/gpt-6-luna", max_tokens=100,
                    raciocinio="desligado", temperatura=0.5, rpm=10)
    monkeypatch.setattr(llm, "ROTAS", {"conversa": rota})
    assert llm.definir_modelo_conversa("cx/gpt-6-astra")
    assert rota.raciocinio == "baixo"
    assert llm.definir_raciocinio_conversa("desligado")
    assert rota.raciocinio == "baixo"


def test_composer_mostra_niveis_do_modelo_vivo(monkeypatch):
    import interface_web
    import preferencias

    rota = llm.Rota(provedor="openai", modelo="cx/gpt-6-luna", max_tokens=100,
                    raciocinio="maximo", temperatura=0.5, rpm=10)
    monkeypatch.setattr(llm, "ROTAS", {"conversa": rota})
    monkeypatch.setattr(llm, "TABELA_ATIVA", "openai")
    monkeypatch.setattr(preferencias, "obter", lambda chave: {
        "provedor": "openai", "modelo": "cx/gpt-6-luna", "raciocinio": "baixo",
    }.get(chave))
    api = object.__new__(interface_web.Api)
    estado = api.estado_modelo()
    assert estado["raciocinio"] == "maximo"
    assert [nivel["id"] for nivel in estado["niveis"]][-2:] == ["extra_alto", "maximo"]


def test_composer_salva_maximo_e_recusa_none_no_astra(monkeypatch):
    import interface_web
    import preferencias

    rota = llm.Rota(provedor="openai", modelo="cx/gpt-6-luna", max_tokens=100,
                    raciocinio="medio", temperatura=0.5, rpm=10)
    monkeypatch.setattr(llm, "ROTAS", {"conversa": rota})
    gravacoes = []
    monkeypatch.setattr(preferencias, "definir", lambda **dados: gravacoes.append(dados))
    api = object.__new__(interface_web.Api)
    assert api.definir_raciocinio("maximo")
    assert rota.raciocinio == "maximo"
    assert gravacoes[-1] == {"raciocinio": "maximo"}
    rota.modelo = "cx/gpt-6-astra"
    assert not api.definir_raciocinio("desligado")
    assert gravacoes[-1] == {"raciocinio": "maximo"}
