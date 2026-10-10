"""Gateway móvel: catálogo, roteamento e estados sem rede real."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import requests


RAIZ = Path(__file__).resolve().parents[1]
CAMINHO = RAIZ / "emily-gateway-service" / "emily_gateway.py"


@pytest.fixture()
def gateway(monkeypatch):
    spec = importlib.util.spec_from_file_location("emily_gateway_teste", CAMINHO)
    modulo = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("EMILY_HK_PERMANENTE", "0")
    monkeypatch.setenv("EMILY_BROWSER_PERMANENTE", "0")
    assert spec and spec.loader
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    valores = {
        "EMILY_PONTE_TOKEN": "segredo",
        "EMILY_PROVEDOR_CLAUDE_BASE": "https://claude.exemplo/v1",
        "EMILY_PROVEDOR_CLAUDE_CHAVE": "chave-claude",
        "EMILY_PROVEDOR_CLAUDE_NOME": "Anthropic",
        "EMILY_PROVEDOR_CLAUDE_MODELO": "claude-sonnet-5",
        "EMILY_PROVEDOR_CLAUDE_MODELOS": "claude-sonnet-5,claude-haiku-4.5",
        "EMILY_PROVEDOR_OPENAI_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE": "chave-openai",
        "EMILY_PROVEDOR_OPENAI_NOME": "OpenAI",
        "EMILY_PROVEDOR_OPENAI_MODELO": "cx/gpt-5.6-terra",
        "EMILY_PROVEDOR_OPENAI_MODELOS": "cx/gpt-5.6-terra,cx/gpt-5.6-luna,cx/gpt-5.6-sol",
        "EMILY_PROVEDOR_OMNIROUTE_BASE": "http://127.0.0.1:20128/v1",
        "EMILY_PROVEDOR_OMNIROUTE_CHAVE": "chave-omni",
        "EMILY_PROVEDOR_OMNIROUTE_NOME": "OmniRoute (local)",
        "EMILY_PROVEDOR_OMNIROUTE_MODELO": "kr/claude-sonnet-4.5",
        "EMILY_PROVEDOR_OMNIROUTE_MODELOS": "kr/claude-sonnet-4.5,kr/claude-haiku-4.5",
    }
    monkeypatch.setattr(modulo, "_cfg", lambda nome, padrao="": valores.get(nome, padrao))
    modulo.APP.testing = True
    return modulo, modulo.APP.test_client()


def _headers():
    return {"Authorization": "Bearer segredo"}


def test_endpoint_publico_exige_token(gateway, monkeypatch):
    _, cliente = gateway
    import gateway_endpoint
    monkeypatch.setattr(gateway_endpoint, "obter", lambda: {
        "url": "https://exemplo.ngrok-free.dev", "atualizado_em": 42.5})
    assert cliente.get("/gateway/endpoint").status_code == 401
    resposta = cliente.get("/gateway/endpoint", headers=_headers()).get_json()
    assert resposta == {"ok": True, "url": "https://exemplo.ngrok-free.dev", "atualizado_em": 42.5}
    assert cliente.post("/gateway/endpoint/push", json={}).status_code == 401
    invalido = cliente.post("/gateway/endpoint/push", headers=_headers(), json={"url": "outro"})
    assert invalido.status_code == 409


def test_publicacao_endpoint_firebase_exige_token_e_versao_atual(gateway, monkeypatch):
    _, cliente = gateway
    import gateway_endpoint
    import firebase_endpoint
    monkeypatch.setattr(gateway_endpoint, "obter", lambda: {
        "url": "https://exemplo.ngrok-free.dev", "atualizado_em": 42.5})
    chamadas = []
    monkeypatch.setattr(firebase_endpoint, "publicar", lambda *args: chamadas.append(args))
    corpo = {"url": "https://exemplo.ngrok-free.dev", "atualizado_em": 42.5}
    assert cliente.post("/gateway/endpoint/publish", json=corpo).status_code == 401
    assert cliente.post("/gateway/endpoint/publish", headers=_headers(),
                        json={**corpo, "atualizado_em": 41}).status_code == 409
    resposta = cliente.post("/gateway/endpoint/publish", headers=_headers(), json=corpo)
    assert resposta.status_code == 200
    assert chamadas == [("https://exemplo.ngrok-free.dev", 42.5, "segredo", "")]


def test_sync_persistente_funciona_sem_janela_desktop(gateway, monkeypatch, tmp_path):
    modulo, cliente = gateway
    import conversas
    import memoria

    monkeypatch.setattr(modulo, "_proxy_http", lambda *_a, **_k: None)
    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    monkeypatch.setattr(memoria, "ARQUIVO", str(tmp_path / "memoria.json"))
    assert memoria.listar_fatos() == []
    conversas.recarregar()
    try:
        sem_token = cliente.get("/chats/delta")
        assert sem_token.status_code == 401
        criado = cliente.post("/chats/gravar", headers=_headers(), json={
            "id": "chat-no-notebook", "titulo": "Teste", "criada": 1,
            "mexida": 2, "mensagens": [{"papel": "user", "texto": "oi", "quando": 2}],
        })
        assert criado.get_json()["ok"] is True
        delta = cliente.get("/chats/delta", headers=_headers()).get_json()
        assert delta["conversas"][0]["id"] == "chat-no-notebook"
        aberto = cliente.get("/chats/abrir/chat-no-notebook", headers=_headers()).get_json()
        assert aberto["mensagens"][0]["texto"] == "oi"
        novo_ramo = cliente.post("/chats/gravar", headers=_headers(), json={
            "id": "chat-no-notebook", "titulo": "Teste", "criada": 1,
            "mexida": 1, "ramo": 1,
            "mensagens": [{"papel": "user", "texto": "oi", "quando": 2},
                          {"papel": "assistant", "texto": "nova resposta", "quando": 3}],
        }).get_json()
        assert novo_ramo["ok"] is True
        assert cliente.get("/chats/abrir/chat-no-notebook", headers=_headers()).get_json()["ramo"] == 1
        obsoleto = cliente.post("/chats/gravar", headers=_headers(), json={
            "id": "chat-no-notebook", "titulo": "Teste", "criada": 1,
            "mexida": 9999999999, "ramo": 0,
            "mensagens": [{"papel": "assistant", "texto": "resposta antiga", "quando": 3}],
        }).get_json()
        assert obsoleto["pc_mais_novo"] is True
        assert cliente.delete("/chats/apagar/chat-no-notebook", headers=_headers()).get_json()["ok"]
        antigo = cliente.post("/chats/gravar", headers=_headers(), json={
            "id": "chat-no-notebook", "titulo": "Teste", "criada": 1,
            "mexida": 2, "mensagens": [{"papel": "user", "texto": "oi", "quando": 2}],
        }).get_json()
        assert antigo["pc_mais_novo"] is True
        assert cliente.get("/chats/abrir/chat-no-notebook", headers=_headers()).status_code == 404
        mem = cliente.post("/memoria/sync", headers=_headers(), json={
            "fatos": [{"texto": "Gosta de café", "local_novo": True}], "apagados": {},
        }).get_json()
        assert mem["fatos"] == ["Gosta de café"]
        assert (tmp_path / "memoria.json").is_file()
    finally:
        conversas.recarregar()


def test_preferencias_sincronizam_com_token(gateway, monkeypatch, tmp_path):
    _, cliente = gateway
    import preferencias
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    try:
        assert cliente.get("/preferencias/sync").status_code == 401
        resposta = cliente.post("/preferencias/sync", headers=_headers(), json={
            "campos": {"nome": {"valor": "Notebook", "quando": __import__("time").time()}}})
        assert resposta.status_code == 200
        assert resposta.get_json()["campos"]["nome"]["valor"] == "Notebook"
    finally:
        preferencias.recarregar()


def test_publicacao_windows_valida_manifesto_e_entrega_instalador(gateway, monkeypatch, tmp_path):
    modulo, cliente = gateway
    from publicar_windows import publicar
    origem = tmp_path / "novo.exe"
    origem.write_bytes(b"MZ" + b"pacote" * 12)
    pasta = tmp_path / "updates"
    publicar(origem, "1.2.3", pasta)
    monkeypatch.setattr(modulo, "PASTA_ATUALIZACAO_WINDOWS", pasta)
    assert cliente.get("/windows/update").status_code == 401
    manifesto = cliente.get("/windows/update", headers=_headers()).get_json()
    assert manifesto["version"] == "1.2.3"
    assert manifesto["size"] == origem.stat().st_size
    resposta = cliente.get("/windows/update/installer", headers=_headers())
    assert resposta.data == origem.read_bytes()


def test_embeddings_do_notebook_exigem_token_e_modelo_do_fedora(gateway, monkeypatch):
    modulo, cliente = gateway
    class Ollama:
        def raise_for_status(self):
            pass
        def json(self):
            return {"embeddings": [[0.2, 0.8]]}
    chamadas = []
    monkeypatch.setattr(modulo._sessao, "post", lambda url, **kw: chamadas.append((url, kw)) or Ollama())
    corpo = {"model": "embeddinggemma", "input": ["fato do usuário"]}
    assert cliente.post("/ollama/api/embed", json=corpo).status_code == 401
    errado = {**corpo, "model": "outro-modelo"}
    assert cliente.post("/ollama/api/embed", headers=_headers(), json=errado).status_code == 400
    resposta = cliente.post("/ollama/api/embed", headers=_headers(), json=corpo)
    assert resposta.get_json()["embeddings"] == [[0.2, 0.8]]
    assert chamadas[0][0] == "http://127.0.0.1:11434/api/embed"


def test_tela_windows_responde_contrato_do_android(gateway, monkeypatch):
    modulo, _cliente = gateway
    import windows_screen
    monkeypatch.setattr(windows_screen, "listar_monitores", lambda: [
        {"id": 1, "indice": 1, "nome": "Monitor 1", "largura": 1920, "altura": 1080}])
    chamadas = []
    monkeypatch.setattr(windows_screen, "capturar_jpeg", lambda *args: chamadas.append(args) or b"\xff\xd8jpeg")
    with modulo.APP.test_request_context("/tela/monitores",
                                        headers=_headers()):
        resposta = modulo._tela_windows("monitores")
        assert resposta.get_json()["monitores"][0]["indice"] == 1
    with modulo.APP.test_request_context("/tela/jpg?monitor=1&largura=960&q=62",
                                        headers=_headers()):
        resposta = modulo._tela_windows("jpg")
        assert resposta.data.startswith(b"\xff\xd8")
        assert chamadas == [(1, 960, 62)]


def test_catalogo_expoe_claude_openai_e_omniroute(gateway):
    _, cliente = gateway
    resposta = cliente.get("/llm/provedores", headers=_headers())
    assert resposta.status_code == 200
    provedores = resposta.get_json()["provedores"]
    assert [p["id"] for p in provedores] == ["claude", "openai", "omniroute"]
    assert [m["nome"] for m in provedores[1]["modelos"]] == [
        "GPT 5.6 Terra", "GPT 5.6 Luna", "GPT 5.6 Sol",
    ]


def test_chat_encaminha_terra_para_openai_local(gateway, monkeypatch):
    modulo, cliente = gateway
    chamadas = []

    class Resposta:
        content = b'{"choices":[{"message":{"content":"ok"}}]}'
        status_code = 200
        headers = {"Content-Type": "application/json"}

    def postar(url, **kwargs):
        chamadas.append((url, kwargs))
        return Resposta()

    monkeypatch.setattr(modulo._sessao, "post", postar)
    resposta = cliente.post("/llm/chat", headers=_headers(), json={
        "model": "cx/gpt-5.6-terra",
        "messages": [{"role": "user", "content": "oi"}],
        "tools": [{"type": "function", "function": {"name": "eco"}}],
        "tool_choice": "auto",
    })
    assert resposta.status_code == 200
    url, pedido = chamadas[0]
    assert url == "http://127.0.0.1:20128/v1/chat/completions"
    assert pedido["headers"]["Authorization"] == "Bearer chave-openai"
    assert pedido["json"]["tools"][0]["function"]["name"] == "eco"


def test_rota_openai_do_windows_exige_token_e_preserva_modelo(gateway, monkeypatch):
    modulo, cliente = gateway
    chamadas = []

    class Resposta:
        content = b'{"choices":[{"message":{"content":"funcionou"}}]}'
        status_code = 200
        headers = {"Content-Type": "application/json"}

    monkeypatch.setattr(modulo._sessao, "post",
                        lambda url, **kw: chamadas.append((url, kw)) or Resposta())
    corpo = {"model": "cx/gpt-5.6-terra",
             "messages": [{"role": "user", "content": "oi"}]}
    assert cliente.post("/llm/v1/chat/completions", json=corpo).status_code == 401
    resposta = cliente.post("/llm/v1/chat/completions", headers=_headers(), json=corpo)
    assert resposta.status_code == 200
    assert resposta.get_json()["choices"][0]["message"]["content"] == "funcionou"
    assert chamadas[0][0] == "http://127.0.0.1:20128/v1/chat/completions"
    assert cliente.get("/llm/v1/models", headers=_headers()).get_json()["object"] == "list"


def test_chat_acrescenta_v1_quando_base_do_claude_vem_so_com_host(gateway, monkeypatch):
    modulo, cliente = gateway
    chamadas = []

    class Resposta:
        content = b'{"choices":[{"message":{"content":"ok"}}]}'
        status_code = 200
        headers = {"Content-Type": "application/json"}

    monkeypatch.setattr(
        modulo._sessao,
        "post",
        lambda url, **kwargs: chamadas.append((url, kwargs)) or Resposta(),
    )
    resposta = cliente.post("/llm/chat", headers=_headers(), json={
        "model": "claude-sonnet-5",
        "messages": [{"role": "user", "content": "oi"}],
    })
    assert resposta.status_code == 200
    assert chamadas[0][0] == "https://claude.exemplo/v1/chat/completions"


def test_chat_stream_preserva_sse_e_nao_bufferiza(gateway, monkeypatch):
    modulo, cliente = gateway
    chamadas = []

    class Resposta:
        status_code = 200
        headers = {"Content-Type": "text/event-stream"}
        fechado = False

        def iter_content(self, chunk_size):
            assert chunk_size == 64
            yield b'data: {"choices":[{"delta":{"content":"Oi"}}]}\n\n'
            yield b"data: [DONE]\n\n"

        def close(self):
            self.fechado = True

    resposta_upstream = Resposta()

    def postar(url, **kwargs):
        chamadas.append((url, kwargs))
        return resposta_upstream

    monkeypatch.setattr(modulo._sessao, "post", postar)
    resposta = cliente.post("/llm/chat", headers=_headers(), json={
        "model": "kr/claude-sonnet-4.5",
        "messages": [{"role": "user", "content": "oi"}],
        "stream": True,
    })

    assert resposta.status_code == 200
    assert resposta.mimetype == "text/event-stream"
    assert resposta.headers["X-Accel-Buffering"] == "no"
    assert chamadas[0][1]["json"]["stream"] is True
    assert chamadas[0][1]["stream"] is True
    assert b"data: [DONE]" in resposta.data
    assert resposta_upstream.fechado is True


def test_saude_omniroute_usa_secao_local_e_aceita_401_como_processo_vivo(gateway, monkeypatch):
    modulo, _ = gateway
    chamadas = []

    class Resposta:
        status_code = 401

    def obter(url, **kwargs):
        chamadas.append((url, kwargs))
        return Resposta()

    monkeypatch.setattr(modulo._sessao, "get", obter)
    assert modulo._proxy_vivo() is True
    assert chamadas[0][0] == "http://127.0.0.1:20128/v1/models"


def test_saude_omniroute_nao_vira_offline_em_erro_transitorio_com_porta_aberta(gateway, monkeypatch):
    modulo, _ = gateway

    class Resposta:
        status_code = 503

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(modulo._sessao, "get", lambda *args, **kwargs: Resposta())
    monkeypatch.setattr(modulo.socket, "create_connection", lambda *args, **kwargs: Conexao())
    assert modulo._proxy_vivo() is True


def test_emily_aberta_nao_vira_fechada_quando_status_estoura_timeout(gateway, monkeypatch):
    modulo, _ = gateway
    monkeypatch.setattr(
        modulo._sessao,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(requests.ReadTimeout()),
    )

    class Conexao:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(modulo.socket, "create_connection", lambda *args, **kwargs: Conexao())
    assert modulo._emily_pronta() is True


def test_controle_pc_exige_token_e_encaminha_contrato_estruturado(gateway, monkeypatch):
    modulo, cliente = gateway
    chamadas = []

    class ControladorFalso:
        def executar(self, acao, args, *, turno_id):
            chamadas.append((acao, args, turno_id))
            return {"ok": True, "mensagem": "feito"}

    monkeypatch.setattr(modulo, "_pc_controller", ControladorFalso())

    sem_token = cliente.post("/pc/action", json={
        "action": "abrir_app", "args": {"nome": "Firefox"}, "turn_id": "t1",
    })
    assert sem_token.status_code == 401

    resposta = cliente.post("/pc/action", headers=_headers(), json={
        "action": "abrir_app", "args": {"nome": "Firefox"}, "turn_id": "t1",
    })
    assert resposta.status_code == 200
    assert resposta.get_json()["mensagem"] == "feito"
    assert chamadas == [("abrir_app", {"nome": "Firefox"}, "t1")]


def test_controle_pc_recusa_contrato_invalido(gateway):
    _, cliente = gateway
    resposta = cliente.post("/pc/action", headers=_headers(), json={
        "action": "abrir_app", "args": "Firefox", "turn_id": "t1",
    })
    assert resposta.status_code == 400


def test_gateway_publica_codigo_windows_autenticado(gateway, monkeypatch, tmp_path):
    import hashlib
    import json
    modulo, cliente = gateway
    monkeypatch.setattr(modulo, "PASTA_ATUALIZACAO_WINDOWS_CODIGO", tmp_path)
    pacote = b"PK" + b"codigo da Emily" * 4
    (tmp_path / "Emily-Code-1.zip").write_bytes(pacote)
    (tmp_path / "latest.json").write_text(json.dumps({
        "version": 1, "installer": "1.0.2", "size": len(pacote),
        "sha256": hashlib.sha256(pacote).hexdigest(), "files": {"main.py": "a" * 64},
    }), encoding="utf-8")
    assert cliente.get("/windows/code-update").status_code == 401
    manifesto = cliente.get("/windows/code-update", headers=_headers())
    assert manifesto.get_json()["version"] == 1
    assert manifesto.headers["Cache-Control"] == "no-store"
    download = cliente.get("/windows/code-update/archive", headers=_headers())
    assert download.data == pacote


def test_modo_irrestrito_vem_do_envelope_autenticado_nao_dos_argumentos(gateway,monkeypatch):
    modulo,client=gateway
    calls=[]
    class Controller:
        def executar(self,action,args,*,turno_id,irrestrito=False):
            calls.append(irrestrito)
            return {'ok':True}
    monkeypatch.setattr(modulo,'_pc_controller',Controller())
    payload={'action':'terminal_iniciar','args':{'irrestrito':True,'unrestricted_mode':True},'turn_id':'t1'}
    assert client.post('/pc/action',json={**payload,'unrestricted_mode':True}).status_code==401
    for value in [False,'true',True]:
        assert client.post('/pc/action',headers=_headers(),json={**payload,'unrestricted_mode':value}).status_code==200
    assert calls==[False,False,True]
