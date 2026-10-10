"""Títulos de chats permanecem ligados ao chat certo e nunca viram ID do modelo."""

from types import SimpleNamespace

import conversas
import interface_web
import modelo


def _historico_temporario(monkeypatch, tmp_path):
    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(conversas, "_cache", None)
    monkeypatch.setattr(conversas, "_cache_id", None)


def _janela(cid):
    janela = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    janela._cid = cid
    janela._push = lambda *_args: None
    return janela


def test_titulo_usa_cid_original_ao_trocar_de_chat(monkeypatch, tmp_path):
    _historico_temporario(monkeypatch, tmp_path)
    primeira = "Crie uma pasta de documentos para o projeto"
    cid = conversas.criar(primeira)
    conversas.acrescentar(cid, "user", primeira)
    outro = conversas.criar("Outro assunto")
    conversas.acrescentar(outro, "user", "Outro assunto")
    janela = _janela(outro)
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda *_a, **_k: "Pasta do projeto")

    janela._titular(cid, primeira)

    titulos = {item["id"]: item["titulo"] for item in conversas.listar()}
    assert titulos[cid] == "Pasta do projeto"
    assert titulos[outro] == "Outro assunto"


def test_haiku_id_nao_vira_titulo_e_titulo_manual_fica(monkeypatch, tmp_path):
    _historico_temporario(monkeypatch, tmp_path)
    primeira = "Abra um site e crie um arquivo de texto"
    cid = conversas.criar(primeira)
    conversas.acrescentar(cid, "user", primeira)
    janela = _janela(cid)
    monkeypatch.setattr(modelo, "chamar_llm_simples",
                        lambda *_a, **_k: "claude-haiku-4-5-20251001")

    janela._titular(cid, primeira)
    assert next(c["titulo"] for c in conversas.listar() if c["id"] == cid) == primeira

    def renomear_durante_llm(*_a, **_k):
        conversas.renomear(cid, "Meu título")
        return "Arquivo e site"

    monkeypatch.setattr(modelo, "chamar_llm_simples", renomear_durante_llm)
    janela._titular(cid, primeira)
    assert next(c["titulo"] for c in conversas.listar() if c["id"] == cid) == "Meu título"


def test_titulo_antigo_com_id_e_recuperado_na_listagem(monkeypatch, tmp_path):
    _historico_temporario(monkeypatch, tmp_path)
    primeira = "Criar uma pasta e uma nota para mim"
    cid = conversas.criar(primeira)
    conversas.acrescentar(cid, "user", primeira)
    conversas.renomear(cid, "claude-haiku-4-5-20251001")
    api = interface_web.Api(SimpleNamespace())
    monkeypatch.setattr(api, "_demo_ativo", lambda: False)

    assert api.listar_conversas()[0]["titulo"] == primeira
    assert conversas.listar()[0]["titulo"] == primeira


def test_titulo_llm_so_e_solicitado_no_primeiro_envio(monkeypatch):
    chamadas = []

    class Thread:
        def __init__(self, target, args=(), **_kwargs):
            chamadas.append((target, args))

        def start(self):
            pass

    class Janela:
        _cid = None
        callback_texto = None

        def _registrar_na_conversa(self, _papel, _texto):
            self._cid = self._cid or "chat-novo"

        def _titular(self, *_args):
            pass

    monkeypatch.setattr(interface_web.threading, "Thread", Thread)
    api = interface_web.Api(Janela())
    monkeypatch.setattr(api, "_demo_ativo", lambda: False)

    assert api.enviar("Primeira pergunta", origem="ptt") == "chat-novo"
    assert api.enviar("Segunda pergunta", origem="ptt") == "chat-novo"
    assert len(chamadas) == 1
    assert chamadas[0][1] == ("chat-novo", "Primeira pergunta")
