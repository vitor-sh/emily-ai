"""Regressões do clipboard, drag-and-drop e upload da interface web."""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path
from types import SimpleNamespace


def _api():
    import interface_web

    janela = SimpleNamespace(_janela=None)
    return interface_web.Api(janela)


def test_salvar_colado_preserva_nome_extensao_e_bytes():
    api = _api()
    dados = b"conteudo do clipboard"
    anexo = api.salvar_colado(
        base64.b64encode(dados).decode("ascii"),
        "notas importantes.txt",
        "text/plain",
    )

    assert anexo is not None
    assert anexo["nome"] == "notas importantes.txt"
    assert anexo["mime"] == "text/plain"
    assert anexo["tamanho"] == len(dados)
    assert Path(anexo["caminho"]).suffix == ".txt"
    assert Path(anexo["caminho"]).read_bytes() == dados


def test_salvar_colado_rejeita_base64_invalido_e_payload_acima_do_limite(monkeypatch):
    import interface_web

    api = _api()
    assert api.salvar_colado("isto nao e base64", "quebrado.txt", "text/plain") is None

    monkeypatch.setattr(interface_web, "_ANEXO_MAX_BYTES", 3)
    grande = base64.b64encode(b"quatro").decode("ascii")
    assert api.salvar_colado(grande, "grande.txt", "text/plain") is None


def test_salvar_colado_antigo_sem_nome_continua_sendo_png():
    api = _api()

    anexo = api.salvar_colado(base64.b64encode(b"png").decode("ascii"))

    assert anexo is not None
    assert anexo["nome"] == "colado.png"
    assert Path(anexo["caminho"]).suffix == ".png"


def test_colar_imagem_nativa_le_clipboard_wayland(monkeypatch):
    import interface_web

    dados = b"imagem do plasma"
    processo = SimpleNamespace(
        stdout=SimpleNamespace(read=lambda _limite: dados),
        wait=lambda timeout: 0,
        kill=lambda: None,
    )
    monkeypatch.setattr(interface_web.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("shutil.which", lambda nome: "/usr/bin/wl-paste" if nome == "wl-paste" else None)
    monkeypatch.setattr(
        interface_web.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=b"text/plain\nimage/png\n"),
    )
    monkeypatch.setattr(interface_web.subprocess, "Popen", lambda *_a, **_k: processo)

    resultado = _api().colar_imagem_nativa()

    assert resultado["ok"] is True
    assert resultado["anexo"]["nome"] == "imagem-colada.png"
    assert resultado["anexo"]["mime"] == "image/png"
    assert Path(resultado["anexo"]["caminho"]).read_bytes() == dados


def test_colar_imagem_nativa_ignora_clipboard_sem_imagem(monkeypatch):
    import interface_web

    monkeypatch.setattr(interface_web.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr("shutil.which", lambda nome: "/usr/bin/wl-paste" if nome == "wl-paste" else None)
    monkeypatch.setattr(
        interface_web.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=b"text/plain\ntext/html\n"),
    )

    assert _api().colar_imagem_nativa() == {"ok": False, "erro": "sem_imagem"}


def test_colar_imagem_nativa_interrompe_payload_acima_do_limite(monkeypatch):
    import interface_web

    estado = {"matou": False}
    processo = SimpleNamespace(
        stdout=SimpleNamespace(read=lambda limite: b"x" * limite),
        wait=lambda timeout: 0,
        kill=lambda: estado.__setitem__("matou", True),
    )
    monkeypatch.setattr(interface_web.sys, "platform", "linux")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(interface_web, "_ANEXO_MAX_BYTES", 3)
    monkeypatch.setattr("shutil.which", lambda nome: "/usr/bin/wl-paste" if nome == "wl-paste" else None)
    monkeypatch.setattr(
        interface_web.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=b"image/png\n"),
    )
    monkeypatch.setattr(interface_web.subprocess, "Popen", lambda *_a, **_k: processo)

    assert _api().colar_imagem_nativa() == {"ok": False, "erro": "arquivo_grande"}
    assert estado["matou"] is True


def test_colar_imagem_nativa_le_bitmap_do_windows(monkeypatch):
    import interface_web
    from PIL import Image, ImageGrab

    imagem = Image.new("RGB", (2, 2), color=(12, 34, 56))
    monkeypatch.setattr(interface_web.sys, "platform", "win32")
    monkeypatch.setattr(ImageGrab, "grabclipboard", lambda: imagem)

    resultado = _api().colar_imagem_nativa()

    assert resultado["ok"] is True
    assert resultado["anexo"]["nome"] == "imagem-colada.png"
    assert resultado["anexo"]["mime"] == "image/png"
    dados = Path(resultado["anexo"]["caminho"]).read_bytes()
    carregada = Image.open(io.BytesIO(dados))
    assert carregada.size == (2, 2)


def test_resolver_arrastados_aceita_caminho_e_file_uri(tmp_path):
    arquivo = tmp_path / "arquivo com espaço.md"
    arquivo.write_text("oi", encoding="utf-8")
    api = _api()

    anexos = api.resolver_arrastados([str(arquivo), arquivo.as_uri(), str(arquivo)])

    assert len(anexos) == 1
    assert anexos[0]["caminho"] == str(arquivo.resolve())
    assert anexos[0]["nome"] == arquivo.name
    assert anexos[0]["tamanho"] == 2


def test_escolher_arquivos_descreve_validos_e_avisa_sobre_grande(tmp_path, monkeypatch):
    import interface_web

    pequeno = tmp_path / "foto.png"
    pequeno.write_bytes(b"png")
    grande = tmp_path / "video.mp4"
    grande.write_bytes(b"12345")
    janela_nativa = SimpleNamespace(
        create_file_dialog=lambda *_a, **_k: [str(pequeno), str(grande)]
    )
    api = interface_web.Api(SimpleNamespace(_janela=janela_nativa))
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(OPEN_DIALOG="abrir"))
    monkeypatch.setattr(interface_web, "_ANEXO_MAX_BYTES", 4)

    anexos = api.escolher_arquivos()

    assert anexos[0]["caminho"] == str(pequeno.resolve())
    assert anexos[0]["nome"] == "foto.png"
    assert anexos[1] == {
        "nome": "video.mp4",
        "tamanho": 5,
        "erro": "arquivo_grande",
    }


def test_escolher_arquivos_aceita_retorno_unico_como_string(tmp_path, monkeypatch):
    import interface_web

    arquivo = tmp_path / "unico.txt"
    arquivo.write_text("ok", encoding="utf-8")
    janela_nativa = SimpleNamespace(
        create_file_dialog=lambda *_a, **_k: str(arquivo)
    )
    api = interface_web.Api(SimpleNamespace(_janela=janela_nativa))
    monkeypatch.setitem(sys.modules, "webview", SimpleNamespace(OPEN_DIALOG="abrir"))

    anexos = api.escolher_arquivos()

    assert len(anexos) == 1
    assert anexos[0]["caminho"] == str(arquivo.resolve())


def test_javascript_nao_sequestra_texto_e_transporta_bytes_de_arquivos():
    raiz = Path(__file__).resolve().parent.parent
    js = (raiz / "web" / "app.js").read_text(encoding="utf-8")
    html = (raiz / "web" / "index.html").read_text(encoding="utf-8")

    bloco_paste = js.split("document.addEventListener('paste'", 1)[1].split(
        "document.addEventListener('dragover'", 1
    )[0]
    assert "const alvoEditavel" in bloco_paste
    assert "const parecemCaminhos" in bloco_paste
    assert "entrada.setRangeText(texto" in bloco_paste
    assert "anexarArquivosWeb(arquivos, 'do clipboard', anunciaImagem)" in bloco_paste
    assert "anexarImagemClipboardNativo()" in bloco_paste
    assert "anexarImagensClipboardApi()" in bloco_paste
    assert "anexarImagensDoHtmlClipboard(htmlClipboard)" in bloco_paste
    assert "const htmlTemImagem" in bloco_paste
    assert "const anunciaImagem" in bloco_paste
    assert "!arquivos.length && !itens.length && !tipos.length" in bloco_paste
    bloco_vazio = bloco_paste.split("if (!arquivos.length && !itens.length && !tipos.length)", 1)[1]
    bloco_vazio = bloco_vazio.split("const tipoUris", 1)[0]
    assert "e.preventDefault()" not in bloco_vazio
    assert "colar_imagem_nativa" in js
    assert "salvar_colado', b64, arquivo.name" in js
    assert "anexarArquivosWeb(arquivos,'arrastado',true)" in js.replace(' ', '')
    assert "chat-anexo-arquivo" in js
    assert "mensagemComAnexos(texto, anexos)" in js
    assert "Ctrl+V cola texto, imagens e arquivos" in html


def test_conversa_com_anexos_usa_rota_do_modelo_selecionado(tmp_path, monkeypatch):
    import modelo
    from PIL import Image

    imagem = tmp_path / "token.png"
    Image.new("RGB", (3, 2), color=(12, 34, 56)).save(imagem, format="PNG")
    chamada = {}
    laço = {}

    def chamar_falso(mensagens, **kwargs):
        chamada["mensagens"] = mensagens
        chamada["kwargs"] = kwargs
        return "O token exibido é EMILY-7429."

    def conversar_falso(mensagem, **kwargs):
        laço["mensagem"] = mensagem
        laço["kwargs"] = kwargs
        return "Li o token."

    class ThreadFalsa:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(modelo, "_chamar_llm", chamar_falso)
    monkeypatch.setattr(modelo, "conversar_com_ferramentas", conversar_falso)
    monkeypatch.setattr(modelo.threading, "Thread", ThreadFalsa)
    monkeypatch.setattr(modelo.mem_module, "formatar_para_prompt", lambda _mem: "")
    monkeypatch.setattr(modelo, "historico", [])

    resposta = modelo.conversar_com_anexos("Leia o token", [str(imagem)])

    assert resposta == "Li o token."
    assert chamada["kwargs"]["rota"] == modelo.ROTA_CONVERSA
    assert chamada["kwargs"]["vision"] is True
    conteudo = chamada["mensagens"][-1]["content"]
    parte_imagem = next(parte for parte in conteudo if parte.get("type") == "image_url")
    assert parte_imagem["image_url"]["url"].startswith("data:image/png;base64,")
    assert "EMILY-7429" in laço["mensagem"]
    assert laço["kwargs"]["mensagem_classificacao"] == "Leia o token"


def test_imagem_com_token_entra_no_laco_e_configura_tv(tmp_path, monkeypatch):
    import copy
    import ferramentas
    import llm
    import modelo
    from PIL import Image

    imagem = tmp_path / "token-tv.png"
    Image.new("RGB", (3, 2), color=(20, 30, 40)).save(imagem, format="PNG")
    token = "EMILY-7429-ABCDEFGHIJKLMNOPQRSTUV"
    executadas = []
    chamadas_llm = []

    class FluxoFerramenta:
        preambulo = ""
        chamadas = [llm.ChamadaFerramenta(
            id="tv-1",
            nome="configurar_emily_tv",
            argumentos='{"token": "' + token + '"}',
        )]

        def quer_ferramenta(self):
            return True

    class FluxoTexto:
        chamadas = []
        preambulo = ""

        def quer_ferramenta(self):
            return False

        def texto(self):
            return iter(["Pronto, configurei o app da TV."])

    def chamar_com_ferramentas(mensagens, **kwargs):
        chamadas_llm.append((copy.deepcopy(mensagens), dict(kwargs)))
        return FluxoFerramenta() if len(chamadas_llm) == 1 else FluxoTexto()

    def executar(nome, argumentos, contexto=None):
        executadas.append((nome, dict(argumentos), dict(contexto or {})))
        return ferramentas.ResultadoFerramenta(
            "App companheiro configurado em TV Sala", ok=True, mudou=True)

    monkeypatch.setattr(
        modelo, "_chamar_llm",
        lambda *_a, **_k: f"O token mostrado pelo app Emily TV é {token}.",
    )
    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar_com_ferramentas)
    monkeypatch.setattr(ferramentas, "executar_estruturado", executar)
    monkeypatch.setattr(
        ferramentas, "esquemas_com_dominios",
        lambda *_a, **_k: [ferramentas.CATALOGO["configurar_emily_tv"].esquema()],
    )
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: None)
    monkeypatch.setattr(modelo, "_resposta_deixa_objetivo_incompleto", lambda *_: False)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_k: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "_envelhecer_dominios", lambda: None)

    historico_original = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_anexos(
            "Configura esse token na TV", [str(imagem)])
    finally:
        modelo.historico[:] = historico_original

    assert resposta == "Pronto, configurei o app da TV."
    assert len(executadas) == 1
    nome, argumentos, contexto = executadas[0]
    assert nome == "configurar_emily_tv" and argumentos == {"token": token}
    assert contexto["pedido_explicito"] is False
    assert callable(contexto["autorizar_pedido"])
    assert contexto["permitir_pergunta_interativa"] is True
    assert contexto["dono_confirmado"] is True
    assert callable(contexto["on_reconexao"])
    assert token in chamadas_llm[0][0][-1]["content"]


def test_conversa_com_anexos_rejeita_png_com_bytes_invalidos(tmp_path, monkeypatch):
    import modelo

    imagem = tmp_path / "quebrada.png"
    imagem.write_bytes(b"isto nao e uma imagem")
    monkeypatch.setattr(modelo, "historico", [])

    try:
        modelo.conversar_com_anexos("Leia", [str(imagem)])
    except ValueError as erro:
        assert "corrompida" in str(erro)
        assert "quebrada.png" in str(erro)
    else:
        raise AssertionError("imagem inválida deveria ser rejeitada antes da API")


def test_payload_anthropic_recebe_bloco_de_imagem_base64_valido():
    import llm
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(90, 80, 70)).save(buffer, format="PNG")
    dados = base64.b64encode(buffer.getvalue()).decode("ascii")
    canonicas = llm.normalizar_mensagens([{
        "role": "user",
        "content": [
            {"type": "text", "text": "Leia"},
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{dados}",
            }},
        ],
    }])
    provedor = llm.ProvedorAnthropic(
        nome="teste", base_url="https://relay.example", env_chave="CHAVE_TESTE"
    )

    _system, mensagens = provedor._montar(canonicas)

    bloco = next(b for b in mensagens[0]["content"] if b["type"] == "image")
    assert bloco["source"]["type"] == "base64"
    assert bloco["source"]["media_type"] == "image/png"
    assert base64.b64decode(bloco["source"]["data"]) == buffer.getvalue()


def test_provedor_hibrido_desvia_imagem_para_anthropic_e_texto_para_openai(monkeypatch):
    import llm

    provedor = llm.ProvedorOpenAIComVisaoAnthropic(
        nome="relay", base_url="https://relay.example/v1",
        env_chave="CHAVE_TESTE", timeout=30,
    )
    chamadas = []

    def chamar_anthropic(**kwargs):
        chamadas.append(("anthropic", kwargs))
        return "vi a imagem"

    def chamar_openai(self, **kwargs):
        chamadas.append(("openai", kwargs))
        return "li o texto"

    monkeypatch.setattr(provedor._visao_anthropic, "chamar", chamar_anthropic)
    monkeypatch.setattr(llm.ProvedorOpenAI, "chamar", chamar_openai)

    comum = dict(
        modelo="claude-sonnet", max_tokens=100, temperatura=0.2,
        raciocinio=llm.RACIOCINIO_DESLIGADO, stream=False,
        ferramentas=None, obrigar_ferramenta=False, proibir_ferramenta=False,
    )
    assert provedor.chamar(
        mensagens=[llm.Mensagem("user", "leia", [("image/png", "YWJj")])],
        **comum,
    ) == "vi a imagem"
    assert chamadas[-1][0] == "anthropic"

    assert provedor.chamar(
        mensagens=[llm.Mensagem("user", "oi")], **comum,
    ) == "li o texto"
    assert chamadas[-1][0] == "openai"
    assert provedor._visao_anthropic.base_url == "https://relay.example"


def test_fechar_pools_invalida_cliente_visual_do_provedor_hibrido(monkeypatch):
    import llm

    provedor = llm.ProvedorOpenAIComVisaoAnthropic(
        nome="relay", base_url="https://relay.example/v1",
        env_chave="CHAVE_TESTE", timeout=30,
    )
    provedor._cliente = object()
    provedor._pool_do_cliente = object()
    provedor._visao_anthropic._cliente = object()
    provedor._visao_anthropic._pool_do_cliente = object()
    monkeypatch.setattr(llm, "PROVEDORES", {"relay": provedor})
    monkeypatch.setattr(llm, "_POOL_HTTP", {})

    llm.fechar_pools_http()

    assert provedor._cliente is None
    assert provedor._pool_do_cliente is None
    assert provedor._visao_anthropic._cliente is None
    assert provedor._visao_anthropic._pool_do_cliente is None

def test_editor_clipboard_and_uri_images_use_native_compatibility(monkeypatch,tmp_path):
    from PIL import Image
    api=_api();api._j._editor_active=True;api._demo_ativo=lambda:False
    path=tmp_path/'imagem de referência.png';Image.new('RGB',(80,60),'orange').save(path)
    monkeypatch.setattr(api,'colar_imagem_nativa',lambda:{'ok':True,'anexo':{'caminho':str(path)}})
    native=api.editor_ai_clipboard()
    assert native['ok'] and native['images'][0]['data'].startswith('data:image/webp;base64,')
    assert native['images'][0]['width']==80
    uri=api.editor_ai_arquivos([path.as_uri()],False)
    assert uri['images'][0]['data']==native['images'][0]['data']
    assert api.editor_ai_arquivos(['file:///arquivo-inexistente.png'])['images']==[]
    api._j._editor_active=False
    assert not api.editor_ai_clipboard()['ok']


def test_editor_image_picker_and_bad_file_do_not_navigate(monkeypatch,tmp_path):
    import webview
    from PIL import Image
    api=_api();api._j._editor_active=True;api._demo_ativo=lambda:False
    path=tmp_path/'ref.png';Image.new('RGB',(32,32),'green').save(path)
    api._j._janela=SimpleNamespace(create_file_dialog=lambda *a,**kw:[str(path)])
    result=api.editor_ai_arquivos([],True)
    assert result['ok'] and result['images'][0]['name']=='ref.png'
    path.write_text('not an image')
    result=api.editor_ai_arquivos([str(path)],False)
    assert result['ok'] and not result['images'] and result['errors']
