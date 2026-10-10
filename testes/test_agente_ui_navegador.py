"""Regressões da abertura de navegadores e troca de janelas do agente visual."""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import agente_ui  # noqa: E402
import desktop_backend  # noqa: E402


def test_brave_flatpak_e_navegador_padrao_sem_executavel_nativo(monkeypatch):
    monkeypatch.setattr(desktop_backend.platform, "system", lambda: "Linux")
    monkeypatch.setattr(desktop_backend.shutil, "which", lambda nome:
                        "/usr/bin/" + nome if nome in {"xdg-settings", "flatpak"} else None)

    def rodar(argv, **_):
        if argv[:3] == ["xdg-settings", "get", "default-web-browser"]:
            return SimpleNamespace(returncode=0, stdout="com.brave.Browser.desktop\n")
        if argv[:2] == ["flatpak", "info"]:
            return SimpleNamespace(returncode=0 if argv[2] == "com.brave.Browser" else 1)
        raise AssertionError(argv)

    monkeypatch.setattr(desktop_backend.subprocess, "run", rodar)
    chamados = []
    monkeypatch.setattr(desktop_backend, "_iniciar_app", lambda argv:
                        chamados.append(tuple(argv)) or True)
    assert desktop_backend.navegador_padrao_linux() == (
        "Brave", "com.brave.Browser.desktop")
    assert desktop_backend._abrir_app_portatil("navegador padrão")
    assert desktop_backend._abrir_app_portatil("brave")
    assert chamados == [
        ("flatpak", "run", "com.brave.Browser"),
        ("flatpak", "run", "com.brave.Browser"),
    ]
    assert not desktop_backend._abrir_app_portatil("chrome")


def test_app_linux_instalado_so_com_atalho_desktop(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop_backend.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path))
    pasta = tmp_path / "applications"
    pasta.mkdir()
    (pasta / "org.exemplo.Editor.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Editor Exemplo\nExec=editor-exemplo\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(desktop_backend.shutil, "which", lambda nome:
                        "/usr/bin/gtk-launch" if nome == "gtk-launch" else None)
    chamados = []
    monkeypatch.setattr(desktop_backend, "_iniciar_app", lambda argv:
                        chamados.append(tuple(argv)) or True)
    assert desktop_backend._abrir_app_portatil("Editor Exemplo")
    assert chamados == [("gtk-launch", "org.exemplo.Editor")]


def test_abrir_app_direto_reutiliza_resolvedor_do_agente_visual(monkeypatch):
    import automacao

    chamados = []
    monkeypatch.setattr(desktop_backend, "_abrir_app_portatil", lambda nome:
                        chamados.append(nome) or True)
    assert automacao._abrir_app_linux("brave")
    assert chamados == ["brave"]


def test_launcher_nao_relata_sucesso_quando_processo_falha_logo(monkeypatch):
    class ProcessoFalho:
        def wait(self, timeout):
            assert timeout == 1.5
            return 1

    monkeypatch.setattr(desktop_backend.subprocess, "Popen", lambda *_a, **_k:
                        ProcessoFalho())
    assert not desktop_backend._iniciar_app(("brave-browser",))


def test_clique_no_icone_visivel_nao_e_substituido_por_launcher(monkeypatch):
    monkeypatch.setattr(agente_ui, "_contexto_fixo_padrao", lambda: "")
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "clicar_tarefa", "celula": "B9", "offset_x": 50,
         "offset_y": 50, "texto": "Brave", "descricao": "Abrir ícone visível"},
        {"acao": "concluido", "mensagem": "feito"},
    ])
    sessao = agente_ui.SessaoAgenteUI(
        backend=backend, decisor=lambda *_: next(decisoes),
        intervalo_passos=0, verificar_cliques=False,
    )
    assert sessao.iniciar("abra o Brave pela barra", em_thread=False)
    assert any(acao[0] == "clicar" for acao in backend.acoes)
    assert not any(acao[0] in {"ativar_janela", "abrir_app"} for acao in backend.acoes)


def test_falha_ao_abrir_app_pode_ser_recuperada_por_clique_na_tela(monkeypatch):
    monkeypatch.setattr(agente_ui, "_contexto_fixo_padrao", lambda: "")

    class BackendSemJanela(desktop_backend.BackendDesktopFalso):
        def ativar_janela(self, nome):
            self._registrar("ativar_janela", nome)
            return False

        def abrir_app(self, nome):
            self._registrar("abrir_app", nome)
            return False

    backend = BackendSemJanela()
    decisoes = iter([
        {"acao": "abrir_app", "texto": "Brave", "descricao": "Abrir Brave"},
        {"acao": "clicar_tarefa", "celula": "B9", "offset_x": 50,
         "offset_y": 50, "descricao": "Ícone do Brave visível na barra"},
        {"acao": "concluido", "mensagem": "janela aberta"},
    ])
    historicos = []

    def decidir(_imagem, _objetivo, historico, *_):
        historicos.append(list(historico))
        return next(decisoes)

    sessao = agente_ui.SessaoAgenteUI(
        backend=backend, decisor=decidir, intervalo_passos=0,
        verificar_cliques=False,
    )
    assert sessao.iniciar("abra o Brave", em_thread=False)
    assert sessao.retrato()["estado"] == "concluido"
    assert any("FALHA em abrir_app" in linha for linha in historicos[1])
    assert sum(acao[0] == "clicar" for acao in backend.acoes) == 1


def test_navegador_presumido_pelo_modelo_vira_padrao_sem_trocar_pedido_explicito(monkeypatch):
    monkeypatch.setattr(agente_ui, "_contexto_fixo_padrao", lambda: "")
    monkeypatch.setattr(agente_ui, "navegador_padrao_linux",
                        lambda: ("Brave", "com.brave.Browser.desktop"))
    for objetivo, esperado in [
        ("Abre um vídeo no YouTube", "navegador padrão"),
        ("Abre o Chrome", "chrome"),
    ]:
        backend = desktop_backend.BackendDesktopFalso()
        decisoes = iter([
            {"acao": "abrir_app", "texto": "chrome"},
            {"acao": "concluido", "mensagem": "feito"},
        ])
        sessao = agente_ui.SessaoAgenteUI(
            backend=backend, decisor=lambda *_: next(decisoes),
            intervalo_passos=0, verificar_cliques=False,
        )
        assert sessao.iniciar(objetivo, em_thread=False)
        assert ("ativar_janela", (esperado,), {}) in backend.acoes


def test_kwin_ativa_janela_por_identidade_e_limpa_script_temporario(monkeypatch):
    backend = desktop_backend.BackendKDEWayland(
        spectacle="/usr/bin/spectacle", ydotool="/usr/bin/ydotool")
    backend.busctl = "/usr/bin/busctl"
    vistos = []

    class Receptor:
        nome = "org.emily.Teste"
        caminho = "/org/emily/Teste"
        interface = "org.emily.Teste"

        def nova_espera(self, _token):
            self.evento = threading.Event()
            self.dados = []
            return self.evento, self.dados

        def remover_espera(self, _token):
            pass

    receptor = Receptor()
    monkeypatch.setattr(backend, "_receptor_cursor_kwin", lambda: receptor)

    def rodar(argv, **_):
        if "loadScript" in argv:
            vistos.append(Path(argv[-2]))
            codigo = vistos[-1].read_text(encoding="utf-8")
            assert "workspace.stackingOrder" in codigo
            assert "workspace.activeWindow=melhor" in codigo
            assert 'var termo="brave"' in codigo
        if "start" in argv:
            receptor.dados.append((1, 0))
            receptor.evento.set()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(backend, "_rodar", rodar)
    assert backend.ativar_janela("Brave Browser")
    assert vistos and not vistos[0].exists()


def test_prompt_visual_recebe_ambiente_real_e_estrategia_de_recuperacao(monkeypatch):
    import modelo

    monkeypatch.setattr(desktop_backend, "descrever_ambiente_desktop",
                        lambda: "Sistema: Linux KDE Wayland. Navegador padrão: Brave.")
    vistos = []
    monkeypatch.setattr(modelo.llm, "chamar", lambda mensagens, **_:
                        vistos.append(mensagens[0]["content"]) or
                        '{"acao":"concluido","mensagem":"feito"}')
    decisao = modelo.decidir_proxima_acao_ui(
        "imagem-de-teste", "abra um vídeo no YouTube", [], [], "")
    assert decisao["acao"] == "concluido"
    prompt = vistos[0]
    assert "Navegador padrão: Brave" in prompt
    assert "não presuma chrome" in prompt.lower()
    assert "clique no ícone visível do painel" in prompt
    assert "youtube.com" in prompt


def test_falha_de_foco_nunca_abre_outra_janela(monkeypatch):
    monkeypatch.setattr(agente_ui, '_contexto_fixo_padrao', lambda: '')
    backend = desktop_backend.BackendDesktopFalso()
    monkeypatch.setattr(backend, 'ativar_janela', lambda _: False)
    launched = []
    monkeypatch.setattr(backend, 'abrir_app', lambda name: launched.append(name) or True)
    session = agente_ui.SessaoAgenteUI(backend=backend)
    ok, _ = session._executar_acao({'acao': 'ativar_janela', 'texto': 'Brave'})
    assert not ok and not launched
    assert session._executar_acao({'acao': 'abrir_app', 'texto': 'Brave'})[0]
    assert not session._executar_acao({'acao': 'abrir_app', 'texto': 'Brave'})[0]
    assert len(launched) == 1
    assert not session._executar_acao({'acao':'atalho','texto':'alt+f4'})[0]
