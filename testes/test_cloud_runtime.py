"""Contratos da nuvem: autenticação, isolamento de ferramentas e publicação."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import threading

import cloud_runtime_client as client
import cloud_runtime_server as server

def app(monkeypatch, tmp_path):
    config = tmp_path/'config.json'
    config.write_text(json.dumps({'upload_key': 'private-test-key'}))
    monkeypatch.setenv('EMILY_RELAY_CONFIG', str(config))
    return server.create_app().test_client()

def test_runtime_rejects_auth_and_arbitrary_rpc(monkeypatch, tmp_path):
    http = app(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, 'discord_bot', SimpleNamespace())
    assert http.post('/search', json={'query': 'Ubuntu'}).status_code == 401
    assert http.post('/discord/rpc', headers={'Authorization':'Bearer private-test-key'},
        json={'method':'__import__', 'args':{}}).status_code == 400
    assert http.post('/search', headers={'Authorization':'Bearer private-test-key'}, json=[]).status_code == 400

def test_research_format_and_key_stay_server_side(monkeypatch, tmp_path):
    import pesquisa
    http = app(monkeypatch, tmp_path)
    calls = []
    class Response:
        ok = True
        def json(self): return {'web':{'results':[{'title':'Ubuntu','url':'https://ubuntu.com','description':'Fonte oficial'}]}}
        def close(self): calls.append('closed')
    def brave(url, **kw):
        calls.append(kw['params']); return Response()
    monkeypatch.setattr(pesquisa, 'BRAVE_API_KEY', 'secret')
    monkeypatch.setattr(pesquisa, '_brave_get', brave)
    result = http.post('/search', headers={'Authorization':'Bearer private-test-key'}, json={'query':'Ubuntu','max':999})
    assert result.status_code == 200
    assert calls == [{'q':'Ubuntu','count':10,'country':'BR'}, 'closed']
    assert result.json['resultados'][0]['url'] == 'https://ubuntu.com'
    assert 'secret' not in result.get_data(as_text=True)

def test_desktop_tools_never_execute_on_oracle():
    assert client.ferramenta_local_na_nuvem(SimpleNamespace(grupo='discord', nome='criar_canais'))
    assert client.ferramenta_local_na_nuvem(SimpleNamespace(grupo='geral', nome='pesquisar_internet'))
    for name in ('executar_terminal', 'abrir_app', 'ver_tela', 'criar_arquivo_txt'):
        assert not client.ferramenta_local_na_nuvem(SimpleNamespace(grupo='geral', nome=name))

def test_discord_proxy_preserves_arguments(monkeypatch):
    monkeypatch.delenv('EMILY_RUNTIME_CLOUD', raising=False)
    monkeypatch.setattr(client, 'hospedado_na_oracle', lambda:True)
    calls = []
    monkeypatch.setattr(client, 'rpc', lambda method,args:calls.append((method,args)) or 'remoto')
    def entrar_em_call(nome_canal, nome_servidor=''): raise AssertionError('Não executar local')
    namespace = {'entrar_em_call':entrar_em_call}
    client.instalar_proxy(namespace)
    assert namespace['entrar_em_call']('Geral') == 'remoto'
    assert calls == [('entrar_em_call', {'nome_canal':'Geral','nome_servidor':''})]

def test_call_resume_only_once_and_keeps_requested_channel(monkeypatch, tmp_path):
    import asyncio
    state = tmp_path/'state.json';state.write_text('{"channel_id":123}')
    monkeypatch.setattr(server, 'STATE', state)
    monkeypatch.setattr(server, '_resume_attempted', False)
    calls = []
    async def connect(channel): calls.append(channel);return True
    monkeypatch.setitem(sys.modules, 'discord_bot', SimpleNamespace(_conectar_voz=connect))
    async def run(): await server.retomar_call();await server.retomar_call()
    asyncio.run(run())
    assert calls == [123]

def test_publisher_does_not_bundle_private_or_user_state():
    source = Path(__file__).resolve().parents[1]/'emily-runtime-cloud/publicar.py'
    spec = importlib.util.spec_from_file_location('runtime_publish', source)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    names = [str(p.relative_to(module.ROOT)) for p in module.sources()]
    assert 'cloud_runtime_server.py' in names
    assert 'memoria_unificada/journal.py' in names
    assert 'assets/audio/silero_vad.onnx' in names
    assert '.env' not in names and 'memoria_discord.json' not in names
    assert not any('__pycache__' in n or n.endswith('.sqlite3') for n in names)


def test_llm_accepts_quoted_provider_config(tmp_path):
    import llm
    config = tmp_path/'providers.env'
    config.write_text('# >>> provedor: openai\nEMILY_PROVEDOR_OPENAI_BASE="http://127.0.0.1:20128/v1"\nEMILY_PROVEDOR_OPENAI_CHAVE="OPENAI_API_KEY"\nEMILY_PROVEDOR_OPENAI_MODELO="cx/gpt-6-luna"\nEMILY_PROVEDOR_OPENAI_TIPO="openai"\n# <<< provedor: openai\n')
    result = llm._parsear_secoes_provedor(str(config))['openai']
    assert result.tipo == 'openai'
    assert result.base_url == 'http://127.0.0.1:20128/v1'
    assert result.env_chave == 'OPENAI_API_KEY'
