"""Teste do fluxo público com perfis temporários e um provedor HTTP local."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

import emily_primeiro_inicio as inicio


@pytest.fixture
def provedor():
    chamadas = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def responder(self, dados, status=200):
            bruto = json.dumps(dados).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(bruto)))
            self.end_headers()
            self.wfile.write(bruto)
        def do_GET(self):
            chamadas.append(("GET", self.path, self.headers.get("Authorization")))
            self.responder({"data": [{"id": "modelo-teste"}, {"id": "modelo-teste"}]})
        def do_POST(self):
            dados = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            chamadas.append(("POST", self.path, self.headers.get("Authorization"), dados))
            if self.headers.get("Authorization") != "Bearer chave-de-teste":
                self.responder({"error": "não devolver chave na mensagem"}, 401)
            else:
                self.responder({"choices": [{"message": {"role": "assistant", "content": "oi"}}]})
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{servidor.server_port}/v1", chamadas
    servidor.shutdown()
    servidor.server_close()
    thread.join(timeout=2)


def dados(base="http://127.0.0.1:12345/v1"):
    return {"nome": "Ana", "provedor": "custom", "base": base,
            "modelo": "modelo-teste", "chave": "chave-de-teste"}


def test_http_configuracao_persistencia_e_reabertura(tmp_path, provedor):
    base, chamadas = provedor
    api = inicio.ApiPrimeiroInicio(tmp_path / "perfil")
    cfg = dados(base)
    assert api.modelos(cfg) == {"ok": True, "modelos": ["modelo-teste"]}
    tested = api.testar(cfg)
    assert tested["ok"]
    assert api.concluir(cfg, tested["recibo"], True)["ok"]
    assert inicio.carregar(tmp_path / "perfil")["nome"] == "Ana"
    estado = inicio.ApiPrimeiroInicio(tmp_path / "perfil").estado()
    assert estado["tem_chave"] and "chave-de-teste" not in json.dumps(estado)
    assert chamadas[1][1] == "/v1/chat/completions"
    assert chamadas[1][3]["model"] == "modelo-teste"
    if os.name != "nt":
        assert (tmp_path / "perfil" / "configuracao.json").stat().st_mode & 0o777 == 0o600


def test_api_invalida_nao_salva_nem_vaza_segredo(tmp_path, provedor):
    base, _ = provedor
    api = inicio.ApiPrimeiroInicio(tmp_path)
    cfg = dados(base)
    cfg["chave"] = "chave-errada"
    resposta = api.testar(cfg)
    assert not resposta["ok"] and "chave-errada" not in json.dumps(resposta)
    assert not (tmp_path / "configuracao.json").exists()


@pytest.mark.parametrize("mutacao", ["modelo", "chave", "base"])
def test_config_mudou_precisa_testar_novamente(tmp_path, mutacao):
    api = inicio.ApiPrimeiroInicio(tmp_path, request=lambda *_: {"choices": [{"message": {"content": "oi"}}]})
    cfg = dados()
    recibo = api.testar(cfg)["recibo"]
    cfg[mutacao] += "-outro"
    assert not api.concluir(cfg, recibo, True)["ok"]
    assert not (tmp_path / "configuracao.json").exists()


def test_nao_conclui_sem_consentimento_ou_teste(tmp_path):
    api = inicio.ApiPrimeiroInicio(tmp_path, request=lambda *_: {"choices": [{"message": {"content": "oi"}}]})
    assert not api.concluir(dados(), "inventado", True)["ok"]
    recibo = api.testar(dados())["recibo"]
    assert not api.concluir(dados(), recibo, False)["ok"]
    assert not (tmp_path / "configuracao.json").exists()


@pytest.mark.parametrize("base", ["http://servidor.exemplo/v1", "https://usuario:senha@exemplo.com", "https://exemplo.com?token=123", "https://exemplo.com/#segredo"])
def test_destinos_que_podem_expor_credenciais_sao_recusados(base):
    with pytest.raises(inicio.ErroConfiguracao):
        inicio.normalizar(dados(base))


def test_cancelamento_config_corrompida_e_link(tmp_path):
    arquivo = tmp_path / "configuracao.json"
    arquivo.write_text("{quebrado")
    api = inicio.ApiPrimeiroInicio(tmp_path)
    assert api.estado()["refazer"]
    assert arquivo.read_text() == "{quebrado" and inicio.carregar(tmp_path) is None
    fora = tmp_path / "fora.json"
    fora.write_text("NAO_ALTERAR")
    arquivo.unlink()
    arquivo.symlink_to(fora)
    with pytest.raises(inicio.ErroConfiguracao):
        inicio._gravar(tmp_path, arquivo.name, "novo")
    assert fora.read_text() == "NAO_ALTERAR"


@pytest.mark.parametrize("campo", ["nome", "modelo", "chave", "base", "provedor"])
def test_configuracao_malformada_nao_e_aceita(campo):
    cfg = dados()
    cfg[campo] = ["conteúdo inválido"]
    with pytest.raises(inicio.ErroConfiguracao):
        inicio.normalizar(cfg)


def test_manter_chave_so_no_mesmo_destino(tmp_path):
    api = inicio.ApiPrimeiroInicio(tmp_path, request=lambda *_: {"choices": [{"message": {"content": "oi"}}]})
    cfg = dados()
    api.concluir(cfg, api.testar(cfg)["recibo"], True)
    novo = inicio.ApiPrimeiroInicio(tmp_path)
    sem_chave = {**cfg, "chave": "", "manter_chave": True}
    assert novo._config(sem_chave)["chave"] == cfg["chave"]
    sem_chave["base"] = "https://outro.exemplo/v1"
    with pytest.raises(inicio.ErroConfiguracao):
        novo._config(sem_chave)


def test_perfil_publico_llm_real_sem_env_pessoal(tmp_path, provedor):
    base, _ = provedor
    raiz = Path(__file__).resolve().parents[1]
    script = '''
import os
from pathlib import Path
from emily_primeiro_inicio import aplicar
cfg = {"nome":"Ana", "provedor":"custom", "modelo":"modelo-teste", "base":os.environ["TEST_API_BASE"], "chave":"chave-de-teste"}
aplicar(Path(os.environ["TEST_PROFILE"]), cfg)
import emily_bootstrap
emily_bootstrap._carregar_ambiente()
import llm, emily_remote, memoria
from memoria_unificada.config import carregar_config
assert llm.TABELA_ATIVA == "publico"
assert set(llm.PROVEDORES) == {"publico"}
assert llm.rota("classificador").provedor == "publico"
assert llm.rota("code_revisor").modelo == "modelo-teste"
assert llm.chamar([{"role":"user", "content":"oi"}], rota_nome="conversa", max_tokens=8) == "oi"
assert memoria.carregar_memoria()["nome_usuario"] == "Ana"
assert not emily_remote._token_gateway() and not emily_remote.gateway_fedora()
assert Path(os.environ["EMILY_DATA_DIR"]).parent == Path(os.environ["TEST_PROFILE"])
assert os.environ["GROQ_API_KEY"] == ""
assert not carregar_config().habilitada
assert carregar_config().pasta_dados == Path(os.environ["EMILY_DATA_DIR"]) / "memoria_unificada"
print("Perfil público e roteamento conferidos")
'''
    env = {**os.environ, "PYTHONPATH": str(raiz), "TEST_PROFILE": str(tmp_path / "publico"),
           "TEST_API_BASE": base, "HOME": str(tmp_path / "casa"), "XDG_CONFIG_HOME": str(tmp_path / "casa/config"),
           "XDG_DATA_HOME": str(tmp_path / "casa/dados")}
    resultado = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert resultado.returncode == 0, resultado.stderr[-1500:]
    assert "Perfil público e roteamento conferidos" in resultado.stdout


@pytest.mark.parametrize("tamanho", [(1080, 760), (560, 700), (390, 844)])
def test_interface_fluxo_real_rolagem_e_responsividade(tmp_path, provedor, tamanho):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler
    from playwright.sync_api import sync_playwright
    base, _ = provedor
    raiz = Path(__file__).resolve().parents[1]
    class Assets(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), partial(Assets, directory=str(raiz / "web")))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    api = inicio.ApiPrimeiroInicio(tmp_path / "perfil", request=lambda cfg, *args: {"data": [{"id":"whisper-large-v3-turbo"}]} if cfg["base"].startswith("https://api.groq") else inicio._request(cfg, *args), audio_fish=lambda cfg: b"ID3amostra", verificar_discord=lambda cfg: None)
    capturas = raiz / "public-release/output/primeiro-inicio"
    capturas.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": tamanho[0], "height": tamanho[1]})
            erros = []
            page.on("pageerror", lambda e: erros.append(str(e)))
            page.expose_function("ponteTeste", lambda metodo, argumentos: getattr(api, metodo)(*argumentos))
            page.add_init_script('''window.pywebview = {api: Object.fromEntries(['estado','modelos','testar','concluir','ajuda','abrir','testar_voz','testar_microfone','testar_discord'].map(nome => [nome, (...args) => window.ponteTeste(nome, args)]))};''')
            page.goto(f"http://127.0.0.1:{http.server_port}/primeiro-inicio.html")
            page.wait_for_function("!document.getElementById('next').disabled")
            page.locator("#name").fill("Marina de Souza")
            assert page.locator("#name").input_value() == "Marina de Souza"
            page.screenshot(path=str(capturas / f"boas-vindas-{tamanho[0]}.png"), full_page=True, animations="disabled")
            page.locator("#next").click()
            page.locator('[data-provider="custom"]').click()
            page.locator("#base").fill(base)
            page.locator("#key").fill("chave-errada")
            page.locator("#model").fill("modelo-teste")
            page.locator("#test").click()
            page.locator("#connection-message.error").wait_for()
            assert page.locator("#next").is_disabled()
            page.locator("#key").fill("chave-de-teste")
            page.locator("#load-models").click()
            page.wait_for_function("document.querySelectorAll('#model-options option').length === 1")
            page.locator("#test").click()
            page.locator("#connection-message.ok").wait_for()
            assert page.locator("#next").is_enabled()
            page.locator("#model").fill("mudou-o-modelo")
            assert page.locator("#next").is_disabled()
            page.locator("#model").fill("modelo-teste")
            page.locator("#test").click()
            page.locator("#connection-message.ok").wait_for()
            page.screenshot(path=str(capturas / f"conexao-{tamanho[0]}.png"), full_page=True, animations="disabled")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#next").click()
            assert page.locator("#review-user").inner_text() == "Marina de Souza"
            assert page.locator("#next").is_disabled()
            page.screenshot(path=str(capturas / f"revisao-{tamanho[0]}.png"), full_page=True, animations="disabled")
            for prefixo, campo, valor in [('voice', 'key', 'fish-teste'), ('mic', 'key', 'groq-teste'), ('discord', 'token', 'bot-teste')]:
                page.locator(f"#{prefixo}-enabled").check()
                page.locator(f"#{prefixo}-{campo}").fill(valor)
                if prefixo == 'discord':
                    page.locator('#discord-channels').fill('123456789012345678')
                page.locator(f"#{prefixo}-test").click()
                page.locator(f"#{prefixo}-message.ok").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator('#voice-enabled').scroll_into_view_if_needed()
            page.screenshot(path=str(capturas / f"voz-{tamanho[0]}.png"), full_page=True, animations="disabled")
            page.locator("#consent").check()
            page.locator("#next").click()
            page.locator("#page-done").wait_for(state="visible")
            assert inicio.carregar(tmp_path / "perfil")["nome"] == "Marina de Souza"
            assert page.evaluate("localStorage.length") == 0
            assert not erros
            browser.close()
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=2)


def test_fechamento_do_assistente_nao_inicia_runtime(monkeypatch, tmp_path):
    import emily_public
    monkeypatch.setattr(inicio, "pasta_perfil", lambda: tmp_path)
    monkeypatch.setattr(inicio, "configurar", lambda _: False)
    monkeypatch.setattr(inicio, "aplicar", lambda *_: pytest.fail("Não aplicar configuração cancelada"))
    emily_public.iniciar()


def test_integracoes_validacao_persistencia_e_isolamento(tmp_path, monkeypatch):
    chamadas = []
    def request(cfg, *args):
        chamadas.append((cfg, args))
        return {"data": [{"id": "whisper-large-v3-turbo"}]} if args[0] == 'GET' else {"choices": [{"message": {"content": "oi"}}]}
    api = inicio.ApiPrimeiroInicio(tmp_path, request=request, audio_fish=lambda cfg: b'ID3amostra', verificar_discord=lambda cfg: None)
    cfg = dados()
    cfg['voz'] = {'ativa': True, 'chave': 'fish-teste'}
    cfg['microfone'] = {'ativo': True, 'chave': 'groq-teste'}
    cfg['discord'] = {'ativo': True, 'token': 'bot-teste', 'canais': '123456789012345678'}
    recibo = api.testar(cfg)['recibo']
    assert not api.concluir(cfg, recibo, True)['ok']
    assert api.testar_voz(cfg)['audio']
    assert api.testar_microfone(cfg)['ok']
    assert api.testar_discord(cfg)['ok']
    assert api.concluir(cfg, recibo, True)['ok']
    salvo = inicio.carregar(tmp_path)
    assert salvo['voz']['id'] == inicio.VOZ_EMILY
    assert salvo['voz']['modelo'] == 's2.1-pro-free'
    assert salvo['discord']['canais'] == ['123456789012345678']
    estado = json.dumps(inicio.ApiPrimeiroInicio(tmp_path).estado())
    assert all(chave not in estado for chave in ('fish-teste', 'groq-teste', 'bot-teste'))
    for chave in ('FISH_AUDIO_KEY','GROQ_API_KEY','EMILY_PUBLIC_MICROFONE','EMILY_FISH_BACKEND','FISH_VOICE_ID','EMILY_FISH_BASE_URL'):
        monkeypatch.setenv(chave, 'não-herdar')
    inicio.aplicar(tmp_path, salvo)
    assert os.environ['FISH_AUDIO_KEY'] == 'fish-teste'
    assert os.environ['GROQ_API_KEY'] == 'groq-teste'
    assert os.environ['EMILY_PUBLIC_MICROFONE'] == '1'
    assert os.environ['EMILY_FISH_BACKEND'] == 's2.1-pro-free'
    assert 'fish-teste' not in (tmp_path / 'provedor.env').read_text()
    cfg['voz']['chave'] = 'outra-chave'
    assert not api.concluir(cfg, recibo, True)['ok']
    cfg['voz'] = {'ativa': False}
    cfg['microfone'] = {'ativo': False}
    cfg['discord'] = {'ativo': False}
    assert api.concluir(cfg, recibo, True)['ok']
    inicio.aplicar(tmp_path, inicio.carregar(tmp_path))
    assert not os.environ['FISH_AUDIO_KEY'] and not os.environ['GROQ_API_KEY']
    assert os.environ['EMILY_PUBLIC_MICROFONE'] == '0'


@pytest.mark.parametrize('campo,valor', [('voz', {'ativa':True,'chave':'x','id':'errado'}), ('microfone', {'ativo':True,'chave':'x\ny'}), ('discord', {'ativo':True,'token':'x','canais':'0'}), ('discord', {'ativo':True,'token':'x','canais':'١٢٣٤٥٦٧٨٩١٢٣٤٥٦٧٨٩٠'})])
def test_integracoes_rejeitam_campos_invalidos(campo, valor):
    cfg = dados(); cfg[campo] = valor
    with pytest.raises(inicio.ErroConfiguracao):
        inicio.normalizar(cfg)


def test_fish_transporte_gratuito_sem_redirect_e_erros_seguros(monkeypatch):
    import requests
    class Response:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def iter_content(self, _): return iter([b'ID3audio'])
    class Session:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def post(self, url, **kwargs):
            assert self.trust_env is False
            assert url == 'https://api.fish.audio/v1/tts'
            assert kwargs['headers']['model'] == 's2.1-pro-free'
            assert kwargs['json']['reference_id'] == inicio.VOZ_EMILY
            assert kwargs['allow_redirects'] is False
            return Response()
    monkeypatch.setattr(requests, 'Session', Session)
    cfg = inicio.normalizar_voz({'ativa':True,'chave':'segredo-teste'})
    assert inicio._audio_fish(cfg) == b'ID3audio'
    Response.status_code = 401
    with pytest.raises(inicio.ErroConfiguracao) as erro:
        inicio._audio_fish(cfg)
    assert 'segredo-teste' not in str(erro.value)


def test_discord_apenas_mencoes_em_canais_autorizados():
    from types import SimpleNamespace as N
    from emily_discord_publico import mensagem_permitida
    usuario = object()
    m = N(guild=object(), author=N(bot=False), channel=N(id=12), mentions=[usuario], content='oi')
    assert mensagem_permitida(m, {12}, usuario)
    assert not mensagem_permitida(m, {13}, usuario)
    m.guild = None
    assert not mensagem_permitida(m, {12}, usuario)
    m.guild = object(); m.mentions = []
    assert not mensagem_permitida(m, {12}, usuario)
    m.mentions = [usuario]; m.author.bot = True
    assert not mensagem_permitida(m, {12}, usuario)


def test_sdk_antiga_nao_cai_em_modelo_pago_publico(monkeypatch):
    import ast
    import types
    raiz = Path(__file__).resolve().parents[1]
    arvore = ast.parse((raiz / 'voz.py').read_text())
    funcoes = [n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name in ('_backend_fish', '_abrir_tts_http')]
    ns = {'os':os, 'TTSRequest':object}
    exec(compile(ast.Module(body=funcoes, type_ignores=[]), 'voz.py', 'exec'), ns)
    chamadas = []
    def antigo(request, **kwargs):
        chamadas.append(kwargs)
        if kwargs: raise TypeError("unexpected keyword argument 'backend'")
        return 'modelo-default'
    monkeypatch.setenv('EMILY_PUBLIC_MODE','1')
    monkeypatch.setenv('EMILY_FISH_BACKEND', 's2.1-pro-free')
    with pytest.raises(RuntimeError):
        ns['_abrir_tts_http'](types.SimpleNamespace(tts=antigo), object())
    assert chamadas == [{'backend':'s2.1-pro-free'}]
    monkeypatch.delenv('EMILY_PUBLIC_MODE')
    with pytest.raises(RuntimeError):
        ns['_abrir_tts_http'](types.SimpleNamespace(tts=antigo), object())
    monkeypatch.setenv('EMILY_FISH_BACKEND', 'speech-1.5')
    assert ns['_abrir_tts_http'](types.SimpleNamespace(tts=antigo), object()) == 'modelo-default'


def test_bot_publico_responde_sem_mencoes_e_sem_outros_canais(monkeypatch):
    import asyncio
    from types import SimpleNamespace as N
    import emily_discord_publico as bot
    usuario = N(id=100)
    class Client:
        def __init__(self, **_): self.user = usuario; self.events = {}; self.token = None
        def event(self, fn): self.events[fn.__name__] = fn; return fn
        def run(self, token, **_): self.token = token
    class Intents:
        @staticmethod
        def none(): return N()
    fake = N(Client=Client, Intents=Intents, AllowedMentions=N(none=lambda: 'sem-mencoes'))
    monkeypatch.setitem(sys.modules, 'discord', fake)
    class Thread:
        def __init__(self, target, **_): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(bot, 'threading', N(Thread=Thread))
    enviadas = []
    class Typing:
        async def __aenter__(self): pass
        async def __aexit__(self, *_): pass
    class Channel:
        id = 12
        def typing(self): return Typing()
        async def send(self, texto, **opcoes): enviadas.append((texto, opcoes))
    client = bot.iniciar({'token':'token-de-bot','canais':['12']}, responder=lambda texto: 'Resposta para '+texto)
    assert client.token == 'token-de-bot'
    message = N(guild=object(), author=N(id=7, bot=False), channel=Channel(), mentions=[usuario], content='<@100> oi')
    async def executar():
        await client.events['on_message'](message)
        message.channel.id = 13
        await client.events['on_message'](message)
    asyncio.run(executar())
    assert enviadas == [('Resposta para oi', {'allowed_mentions':'sem-mencoes'})]


def test_perfil_com_todas_credenciais_longas_pode_reabrir(tmp_path):
    cfg = dados()
    cfg['chave'] = 'x' * 4096
    cfg['voz'] = {'ativa':True, 'chave':'f' * 4096}
    cfg['microfone'] = {'ativo':True, 'chave':'g' * 4096}
    cfg['discord'] = {'ativo':True, 'token':'d' * 4096, 'canais':['123456789012345678']}
    cfg = inicio.normalizar(cfg)
    inicio._gravar(tmp_path, 'configuracao.json', json.dumps({**cfg, 'concluido':True}))
    assert inicio.carregar(tmp_path) == cfg
