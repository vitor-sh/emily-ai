"""Garantias de isolamento do Modo Demo público."""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def sessao_limpa():
    import modo_demo

    modo_demo.encerrar()
    yield
    modo_demo.encerrar()


def _janela_falsa():
    return SimpleNamespace(
        _ultimo_status=("aguardando", ""),
        _cid="conversa-real-sentinela",
        _avatar="",
        _resposta_emily="",
        _resposta_crua="",
        _falas_processo=[],
        _janela=SimpleNamespace(
            create_file_dialog=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("diálogo real não pode abrir na demo")),
        ),
        _push=lambda *_a, **_k: None,
    )


def test_ciclo_da_api_congela_e_restaura_contexto_real():
    import interface_web
    import modelo
    import modo_demo

    janela = _janela_falsa()
    api = interface_web.Api(janela)
    historico_real = [
        {"role": "user", "content": "SENTINELA PESSOAL"},
        {"role": "assistant", "content": "RESPOSTA PESSOAL"},
    ]
    anterior = copy.deepcopy(modelo.historico)
    try:
        modelo.definir_historico(copy.deepcopy(historico_real))
        iniciado = api.iniciar_demo()

        assert iniciado["ok"] is True
        assert iniciado["ativo"] is True
        assert iniciado["nome"] == "Visitante"
        assert janela._cid is None
        assert modelo.historico == []

        workspace = Path(iniciado["workspace"])
        assert workspace.is_dir()
        assert (workspace / "src" / "tasks.py").is_file()

        cid_demo = api.nova_conversa()
        janela._cid = cid_demo
        janela._registrar_na_conversa = lambda papel, texto: setattr(
            janela, "_cid", modo_demo.acrescentar_conversa(janela._cid, papel, texto))
        janela._registrar_na_conversa("user", "mensagem só da demo")
        modelo.historico.append({"role": "user", "content": "turno-demo"})

        encerrado = api.encerrar_demo()
        assert encerrado["ok"] is True
        assert encerrado["ativo"] is False
        assert janela._cid == "conversa-real-sentinela"
        assert modelo.historico == historico_real
        assert not workspace.exists()
    finally:
        modelo.definir_historico(anterior)


def test_dados_ficticios_mutam_sem_tocar_sentinelas_reais(tmp_path):
    import modo_demo

    conversa_real = tmp_path / "conversas.json"
    memoria_real = tmp_path / "memoria.json"
    playlist_real = tmp_path / "playlists.json"
    sentinelas = {
        conversa_real: b'{"segredo":"chat real"}',
        memoria_real: b'{"segredo":"memoria real"}',
        playlist_real: b'{"segredo":"playlist real"}',
    }
    for caminho, conteudo in sentinelas.items():
        caminho.write_bytes(conteudo)

    estado = modo_demo.iniciar("NOME REAL QUE NÃO PODE ENTRAR")
    assert estado["nome"] == "Visitante"
    workspace = Path(estado["workspace"])
    cid = modo_demo.criar_conversa("Conversa efêmera")
    modo_demo.acrescentar_conversa(cid, "user", "não persista")
    modo_demo.playlist_criar("Temporária")
    modo_demo.playlist_adicionar(
        {"video_id": "aaaaaaaaaaa", "titulo": "Faixa fictícia", "thumb": ""})
    pasta = modo_demo.cloud_criar_pasta("Pasta efêmera")["item"]
    assert modo_demo.cloud_renomear(pasta["id"], "Pasta alterada")["ok"]

    anexo = modo_demo.cloud_anexar("demo-roteiro")
    assert anexo is not None
    caminho_anexo = Path(anexo["caminho"]).resolve()
    assert caminho_anexo.is_relative_to(workspace.resolve())
    assert caminho_anexo.read_text(encoding="utf-8").startswith("# Roteiro")

    modo_demo.encerrar()
    assert not workspace.exists()
    for caminho, conteudo in sentinelas.items():
        assert caminho.read_bytes() == conteudo


def test_emily_code_fica_no_workspace_e_bloqueia_execucao(tmp_path):
    import emily_code
    import modo_demo

    arquivo_real = tmp_path / "projeto-real.py"
    arquivo_real.write_text("SEGREDO_REAL = True\n", encoding="utf-8")
    workspace = Path(modo_demo.iniciar("Visitante")["workspace"])

    assert emily_code.projeto_raiz().resolve() == workspace.resolve()
    assert "criado/atualizado" in emily_code.escrever_arquivo(
        "src/novo.py", "VALOR_DEMO = 1\n")
    assert (workspace / "src" / "novo.py").read_text(encoding="utf-8") == "VALOR_DEMO = 1\n"
    assert "fora do projeto" in emily_code.escrever_arquivo(
        "../escape.py", "nao pode")

    bloqueio = emily_code.executar("executar_comando", comando="touch invadiu.txt")
    assert "bloqueada" in bloqueio.lower()
    assert not (tmp_path / "invadiu.txt").exists()
    assert arquivo_real.read_text(encoding="utf-8") == "SEGREDO_REAL = True\n"

    emily_code._fazer_backup("src/tasks.py", workspace / "src" / "tasks.py")
    backups = emily_code._pasta_backups().resolve()
    assert backups.is_relative_to(workspace.resolve())
    assert list(backups.iterdir())


def test_catalogo_e_execucao_forjada_respeitam_allowlist():
    import ferramentas
    import modo_demo

    modo_demo.iniciar("Visitante")
    nomes = {
        esquema["function"]["name"]
        for esquema in ferramentas.esquemas()
    }
    assert "code_editar_arquivo" in nomes
    assert "code_executar_comando" not in nomes
    assert "procurar_no_pc" not in nomes
    assert "hora_atual" not in nomes
    assert ferramentas.esquemas_por_nome(["procurar_no_pc", "hora_atual"]) == []

    forjada = ferramentas.executar_estruturado(
        "procurar_no_pc", {"nome": "arquivo-segredo"})
    assert forjada.ok is False
    assert forjada.mudou is False
    assert forjada.erro == "bloqueada_modo_demo"


def test_api_intercepta_acoes_reais_e_entrega_estado_neutro(monkeypatch):
    import interface_web
    import modo_demo

    modo_demo.iniciar("Visitante")
    api = interface_web.Api(_janela_falsa())

    assert api.escolher_arquivos() == []
    assert api.salvar_colado("YWJj") is None
    assert api.cloud_exportar("qualquer")["demo"] is True
    assert api.cloud_abrir("qualquer")["ok"] is False
    assert api.listar_repos_github() == []
    assert api.listar_memoria() == []
    assert api.memoria_unificada_listar() == []
    assert api.estado_modelo()["provedor"] == "demo"
    assert api.perfil()["nome"] == "Visitante"
    assert api.estado_perfil()["personalidade_extra"] == ""
    sistema = api.sistema()
    assert sistema["demo"] is True
    assert sistema["hora"] == "14:32"
    assert sistema["data"] == "terça, 12/08"


def test_iniciar_demo_cancela_agente_visual_ativo(monkeypatch):
    import agente_ui
    import interface_web

    janela = _janela_falsa()
    janela._ultimo_status = ("aguardando", "")
    api = interface_web.Api(janela)
    cancelamentos = []

    monkeypatch.setattr(
        agente_ui, "estado_agente_ui",
        lambda: {"ativo": True, "estado": "executando"},
    )
    monkeypatch.setattr(
        agente_ui, "parar_agente_ui",
        lambda: cancelamentos.append(True) or "Parando.",
    )

    resultado = api.iniciar_demo()

    assert resultado["ok"] is True
    assert cancelamentos == [True]


def test_envio_forjado_de_anexo_real_e_bloqueado(tmp_path):
    import threading

    import interface_web
    import modo_demo

    real = tmp_path / "segredo-real.txt"
    real.write_text("SEGREDO PESSOAL", encoding="utf-8")
    chamadas = []
    terminou = threading.Event()
    janela = _janela_falsa()

    def callback_arquivos(caminhos, texto):
        chamadas.append((caminhos, texto))
        terminou.set()

    janela.callback_arquivos = callback_arquivos
    janela._registrar_na_conversa = lambda *_a, **_k: None
    janela._chamar_cb = lambda fn, *args: fn(*args)
    janela._titular = lambda *_a, **_k: None
    api = interface_web.Api(janela)
    modo_demo.iniciar("Visitante")

    assert api.enviar_arquivos([str(real)], "leia") is None
    assert chamadas == []
    assert real.read_text(encoding="utf-8") == "SEGREDO PESSOAL"

    anexo_demo = modo_demo.cloud_anexar("demo-roteiro")
    assert anexo_demo is not None
    cid = modo_demo.criar_conversa("Anexo permitido")
    janela._cid = cid
    assert api.enviar_arquivos([anexo_demo["caminho"]], "resuma") == cid
    assert terminou.wait(2.0)
    assert chamadas == [([anexo_demo["caminho"]], "resuma")]
    assert api.estado_demo()["turnos_ativos"] == 0


def test_memoria_e_promessa_reais_nao_entram_nem_sao_consumidas(monkeypatch):
    import modelo
    import modo_demo

    promessa_real = "SENTINELA DE PROMESSA PESSOAL"
    anterior = modelo._promessa_pendente
    try:
        modelo._promessa_pendente = promessa_real
        modo_demo.iniciar("Visitante")
        monkeypatch.setattr(
            modelo.mem_module, "formatar_para_prompt",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("memória antiga não pode ser consultada")))

        mensagens = modelo._mensagens_para_turno()
        system = mensagens[0]["content"]
        assert promessa_real not in system
        assert "Belo Horizonte" not in system
        assert modelo._promessa_pendente_consumir() is None
        assert modelo._promessa_pendente == promessa_real
    finally:
        modelo._promessa_pendente = anterior


def test_empacotadores_e_atualizador_incluem_modo_demo():
    raiz = Path(__file__).resolve().parents[1]
    windows = (raiz / "build_emily.py").read_text(encoding="utf-8")
    linux = (raiz / "build_emily_linux.py").read_text(encoding="utf-8")
    atualizador = (raiz / "atualizador_emily.py").read_text(encoding="utf-8")

    assert '"modo_demo"' in windows
    assert "_e_modulo_interno" in linux and "os.listdir" in linux
    assert "_modulo_interno(nome)" in atualizador
    assert (raiz / "modo_demo.py").is_file()


def test_editor_substitui_demo_publico_e_preserva_isolamento_legado():
    raiz = Path(__file__).resolve().parents[1]
    html = (raiz / "web" / "index.html").read_text(encoding="utf-8")
    js = (raiz / "web" / "app.js").read_text(encoding="utf-8")
    cloud_js = (raiz / "web" / "cloud.js").read_text(encoding="utf-8")
    css = (raiz / "web" / "estilo.css").read_text(encoding="utf-8")

    assert 'id="btn-editor"' in html
    assert 'id="editor-toolbar"' in html
    assert 'id="btn-demo"' not in html
    assert "estado_demo" in js and "iniciar_demo" in js and "encerrar_demo" in js
    assert "localStorage.setItem('emily_demo'" not in js
    assert "body.modo-demo" in css
    assert "'#btn-add'" in js
    assert "it.desabilitado" in js and ".popover-item.desabilitado" in css
    assert "bloqueioExterno" in cloud_js
    assert "Sincronizar', ...bloqueioExterno" in cloud_js
    assert "Criar link temporário', ...bloqueioExterno" in cloud_js