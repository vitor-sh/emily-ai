"""Regressões do isolamento entre sessões do Emily Code."""

import json
import threading

import emily_code


def _isolado(tmp_path, monkeypatch):
    arquivo = tmp_path / "code-conversas.json"
    monkeypatch.setattr(emily_code, "_ARQUIVO_CONVERSAS", arquivo)
    monkeypatch.setattr(emily_code, "_conversa_atual", None)
    monkeypatch.setattr(emily_code, "_contexto_conversa", threading.local())
    return arquivo


def test_novo_reaproveita_rascunho_vazio(tmp_path, monkeypatch):
    arquivo = _isolado(tmp_path, monkeypatch)

    primeiro = emily_code.code_criar_conversa("")
    segundo = emily_code.code_criar_conversa("")

    assert segundo == primeiro
    assert len(json.loads(arquivo.read_text(encoding="utf-8"))["conversas"]) == 1


def test_carregamento_remove_ids_e_rascunhos_duplicados(tmp_path, monkeypatch):
    arquivo = _isolado(tmp_path, monkeypatch)
    arquivo.write_text(json.dumps({
        "ativa": "b",
        "conversas": [
            {"id": "a", "titulo": "Conversa de código", "mensagens": [], "mexida": 1},
            {"id": "b", "titulo": "Conversa de código", "mensagens": [], "mexida": 2},
            {"id": "b", "titulo": "duplicada", "mensagens": [], "mexida": 3},
            {"id": "c", "titulo": "Com conteúdo", "mensagens": [{"papel": "user", "texto": "oi"}]},
        ],
    }), encoding="utf-8")

    lista = emily_code.code_listar_conversas()

    assert {c["id"] for c in lista} == {"b", "c"}
    assert sum(c["ativa"] for c in lista) == 1


def test_apagar_ativa_persiste_a_proxima_valida(tmp_path, monkeypatch):
    arquivo = _isolado(tmp_path, monkeypatch)
    antiga = emily_code.code_criar_conversa("antiga")
    emily_code.code_acrescentar(antiga, "user", "conteúdo")
    atual = emily_code.code_criar_conversa("atual")

    assert emily_code.code_apagar_conversa(atual)

    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    assert dados["ativa"] == antiga
    assert emily_code.code_conversa_atual() == antiga


def test_contexto_da_thread_nao_muda_com_selecao_global(tmp_path, monkeypatch):
    _isolado(tmp_path, monkeypatch)
    origem = emily_code.code_criar_conversa("origem")
    emily_code._atualizar_conversa(origem, projeto="/origem")
    outra = emily_code.code_criar_conversa("outra")
    emily_code._atualizar_conversa(outra, projeto="/outra")

    with emily_code.code_contexto_conversa(origem):
        assert emily_code.code_conversa_atual() == origem
        assert emily_code._conversa_atual_dict()["projeto"] == "/origem"
        emily_code.code_definir_conversa_atual(outra)
        assert emily_code.code_conversa_atual() == origem

    assert emily_code.code_conversa_atual() == outra