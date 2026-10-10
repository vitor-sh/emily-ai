"""Contratos da ponte WebView, painel e seleção operacional do agente visual."""

from __future__ import annotations

import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def test_backend_kde_exige_socket_real_do_ydotoold(monkeypatch, tmp_path):
    import desktop_backend

    caminho = tmp_path / "ydotool.sock"
    monkeypatch.setenv("YDOTOOL_SOCKET", str(caminho))
    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")

    indisponivel = backend.capacidades()
    assert indisponivel.captura is True
    assert indisponivel.entrada is False
    assert "socket ausente" in indisponivel.motivo_indisponivel

    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        servidor.bind(str(caminho))
        disponivel = backend.capacidades()
    finally:
        servidor.close()

    assert disponivel.entrada is True
    assert disponivel.motivo_indisponivel == ""


def test_estado_parado_ja_expoe_capacidades_do_backend():
    import agente_ui
    import desktop_backend

    sessao = agente_ui.SessaoAgenteUI(
        backend=desktop_backend.BackendDesktopFalso(),
        decisor=lambda *_: {"acao": "concluido"},
    )

    estado = sessao.retrato()
    assert estado["estado"] == "parado"
    assert estado["backend"]["nome"] == "falso"
    assert estado["backend"]["entrada"] is True


def test_backend_kde_rolagem_envia_dois_eixos(monkeypatch):
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    chamadas = []
    monkeypatch.setattr(backend, "_exigir_entrada", lambda: "/usr/bin/ydotool")
    monkeypatch.setattr(backend, "_rodar", lambda args, timeout=12.0: chamadas.append(tuple(args)))

    backend.rolar(-15)

    assert chamadas == [(
        "/usr/bin/ydotool", "mousemove", "--wheel", "--", "0", "-15",
    )]


def test_grade_kde_preserva_proporcao_e_usa_png_em_monitor_5_por_4():
    import base64
    from io import BytesIO

    from PIL import Image
    import desktop_backend

    imagem = Image.new("RGB", (1280, 1024), "black")
    codificada = desktop_backend._imagem_para_grade_base64(imagem)
    processada = Image.open(BytesIO(base64.b64decode(codificada)))

    assert base64.b64decode(codificada).startswith(b"\x89PNG\r\n\x1a\n")
    assert processada.size == (1280, 1024)


def test_backend_kde_captura_limpa_via_spectacle_sem_grade(monkeypatch):
    import base64
    import subprocess
    from io import BytesIO

    from PIL import Image
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    chamadas = []

    def rodar(args, timeout=12.0):
        chamadas.append((tuple(args), timeout))
        caminho = args[args.index("-o") + 1]
        Image.new("RGB", (1600, 900), (18, 90, 170)).save(caminho, "PNG")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(backend, "_rodar", rodar)
    monkeypatch.setattr(
        backend, "_geometria_saida_ativa",
        lambda: {"left": 0, "top": 0, "width": 1600, "height": 900},
    )

    codificada = backend.capturar_tela()
    dados = base64.b64decode(codificada)
    processada = Image.open(BytesIO(dados)).convert("RGB")

    assert dados.startswith(b"\xff\xd8\xff")
    assert processada.size == (1280, 720)
    assert processada.getpixel((640, 360))[2] > 150
    assert chamadas[0][0][1:7] == ("-b", "-n", "-m", "-d", "0", "-o")
    assert "-p" not in chamadas[0][0]


def test_visao_usa_backend_kde_no_wayland_em_vez_do_mss_preto(monkeypatch):
    import desktop_backend
    import visao

    class BackendKDEFalso(desktop_backend.BackendKDEWayland):
        def __init__(self):
            pass

        def capturar_tela(self):
            return "captura-limpa-spectacle"

    monkeypatch.setattr(
        desktop_backend, "selecionar_backend_desktop", lambda: BackendKDEFalso())
    monkeypatch.setattr(
        visao, "_capturar_tela_mss",
        lambda: (_ for _ in ()).throw(AssertionError("mss não pode ser usado no Wayland")),
    )

    assert visao.capturar_tela() == "captura-limpa-spectacle"


def test_backend_kde_converte_saida_escalada_para_geometria_logica():
    import desktop_backend

    saida = {
        "size": {"width": 1920, "height": 1080},
        "scale": 1.25,
        "rotation": 1,
    }

    assert desktop_backend.BackendKDEWayland._dimensao_logica_saida(saida) == (1536, 864)


def test_backend_kde_grade_reduzida_mantem_coordenadas_logicas_do_monitor_escalado(monkeypatch):
    import base64
    import subprocess
    from io import BytesIO

    from PIL import Image
    import agente_ui
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")

    def captura(args, timeout=12.0):
        Image.new("RGB", (1920, 1080), "blue").save(args[args.index("-o") + 1])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(backend, "_rodar", captura)
    monkeypatch.setattr(backend, "_geometria_saida_ativa", lambda: {
        "left": 1536, "top": 0, "width": 1536, "height": 864,
    })
    imagem = Image.open(BytesIO(base64.b64decode(backend.capturar_tela_com_grade())))
    sessao = agente_ui.SessaoAgenteUI(backend=backend, decisor=lambda *_: {"acao": "concluido"})

    assert imagem.size == (1280, 720)  # reduzida para o modelo, não para o KWin
    assert backend.geometria() == {"left": 1536, "top": 0, "width": 1536, "height": 864}
    assert sessao._coordenadas({"celula": "F5", "offset_x": 0, "offset_y": 0}) == (2304, 432)


def test_backend_kde_usa_offset_e_tamanho_da_saida_ativa(monkeypatch):
    import subprocess
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    backend.kscreen_doctor = "/usr/bin/kscreen-doctor"
    backend.busctl = "/usr/bin/busctl"
    dados = {
        "outputs": [
            {"name": "HDMI-A-2", "enabled": True, "connected": True, "priority": 1,
             "pos": {"x": 0, "y": 0}, "size": {"width": 1920, "height": 1080},
             "scale": 1.25, "rotation": 1},
            {"name": "DP-1", "enabled": True, "connected": True, "priority": 2,
             "pos": {"x": 1536, "y": 0}, "size": {"width": 1280, "height": 1024},
             "scale": 1, "rotation": 1},
        ],
    }

    def rodar(args, timeout=12.0):
        stdout = 's "DP-1"\n' if "activeOutputName" in args else __import__("json").dumps(dados)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(backend, "_rodar", rodar)

    assert backend._geometria_saida_ativa() == {
        "left": 1536, "top": 0, "width": 1280, "height": 1024,
    }


def test_backend_kde_move_em_malha_fechada_sem_absolute(monkeypatch):
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    posicoes = iter([(1904, 13), (1916, 25), (1923, 32)])
    chamadas = []
    monkeypatch.setattr(backend, "_exigir_entrada", lambda: "/usr/bin/ydotool")
    monkeypatch.setattr(backend, "_posicao_cursor_kwin", lambda: next(posicoes))
    monkeypatch.setattr(backend, "_rodar", lambda args, timeout=12.0: chamadas.append(tuple(args)))
    monkeypatch.setattr(desktop_backend.time, "sleep", lambda _tempo: None)

    backend.mover(1924, 33)

    assert chamadas == [
        ("/usr/bin/ydotool", "mousemove", "--", "10", "10"),
        ("/usr/bin/ydotool", "mousemove", "--", "4", "4"),
    ]
    assert not any("--absolute" in chamada for chamada in chamadas)


def test_backend_kde_corrige_desvio_de_tres_pixels_antes_do_clique(monkeypatch):
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    posicoes = iter([(0, 0), (97, 100), (99, 100)])
    chamadas = []
    monkeypatch.setattr(backend, "_exigir_entrada", lambda: "/usr/bin/ydotool")
    monkeypatch.setattr(backend, "_posicao_cursor_kwin", lambda: next(posicoes))
    monkeypatch.setattr(backend, "_rodar", lambda args, timeout=12.0: chamadas.append(tuple(args)))
    monkeypatch.setattr(desktop_backend.time, "sleep", lambda _tempo: None)

    backend.mover(100, 100)

    assert chamadas == [
        ("/usr/bin/ydotool", "mousemove", "--", "50", "50"),
        ("/usr/bin/ydotool", "mousemove", "--", "2", "0"),
    ]


def test_backend_kde_cancela_clique_se_cursor_nao_alcancar_alvo(monkeypatch):
    import desktop_backend

    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    chamadas = []
    monkeypatch.setattr(backend, "_exigir_entrada", lambda: "/usr/bin/ydotool")
    monkeypatch.setattr(backend, "_posicao_cursor_kwin", lambda: (0, 0))
    monkeypatch.setattr(backend, "_rodar", lambda args, timeout=12.0: chamadas.append(tuple(args)))
    monkeypatch.setattr(desktop_backend.time, "sleep", lambda _tempo: None)

    with pytest.raises(desktop_backend.ErroBackendDesktop, match="Clique cancelado"):
        backend.clicar(500, 300)

    assert not any("click" in chamada for chamada in chamadas)


def test_api_web_controla_sessao_e_devolve_estado(monkeypatch):
    import agente_ui
    import interface_web

    estado = {
        "estado": "parado", "objetivo": "", "passo": 0, "max_passos": 50,
        "mensagem": "", "ultima_acao": "", "erro": "", "iniciado_em": None,
        "atualizado_em": 1.0, "finalizado_em": None, "ativo": False,
        "backend": {"nome": "falso", "captura": True, "entrada": True,
                    "janelas": True, "motivo_indisponivel": ""},
        "historico": [],
    }
    mensagens = []

    class SessaoFalsa:
        def pausar(self):
            estado.update(estado="pausado", mensagem="Agente pausado", ativo=True)
            return True

        def retomar(self):
            estado.update(estado="rodando", mensagem="Continuando", ativo=True)
            return True

        def cancelar(self):
            estado.update(estado="cancelando", mensagem="Cancelando", ativo=True)
            return True

    sessao = SessaoFalsa()

    def iniciar(objetivo, callback_falar=None):
        estado.update(
            estado="rodando", objetivo=objetivo, mensagem="Analisando a tela",
            iniciado_em=2.0, atualizado_em=2.0, ativo=True,
        )
        return "Vou fazer isso na tela!"

    monkeypatch.setattr(agente_ui, "estado_agente_ui", lambda: dict(estado))
    monkeypatch.setattr(agente_ui, "sessao_agente_ui", lambda: sessao)
    monkeypatch.setattr(agente_ui, "iniciar_agente_ui", iniciar)
    monkeypatch.setattr(
        agente_ui, "enviar_mensagem_ao_vivo",
        lambda texto: mensagens.append(texto) is None,
    )

    api = interface_web.Api(SimpleNamespace())
    inicio = api.agente_ui_iniciar("configurar o programa")
    assert inicio["ok"] is True
    assert inicio["estado"]["objetivo"] == "configurar o programa"

    assert api.agente_ui_pausar()["estado"]["estado"] == "pausado"
    assert api.agente_ui_retomar()["estado"]["estado"] == "rodando"
    envio = api.agente_ui_mensagem("use a opção avançada")
    assert envio["ok"] is True
    assert mensagens == ["use a opção avançada"]
    assert api.agente_ui_cancelar()["estado"]["estado"] == "cancelando"


def test_janela_publica_estado_do_agente_pelo_push():
    import interface_web

    eventos = []
    janela = interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    janela._push = lambda evento, dados: eventos.append((evento, dados))
    estado = {"estado": "executando", "passo": 3, "ativo": True}

    janela._publicar_estado_agente_ui(estado)

    assert eventos == [("agente_ui", estado)]


def test_politica_prioriza_meio_que_conclui_tarefa_inteira():
    import ferramentas
    import modelo

    terminal = ferramentas.CATALOGO["executar_terminal"].descricao
    visual = ferramentas.CATALOGO["executar_na_tela"].descricao

    assert "concluído INTEIRO por comando" in terminal
    assert "instalador gráfico" in terminal
    assert "configurar algo dentro de um programa" in visual
    assert "opção MAIS CONFIÁVEL" in visual
    assert "Se o terminal só faria metade" in modelo._INSTRUCOES_FERRAMENTAS
