"""Fluxos reais de arquivo e seleção da autenticação Linux, sem elevar privilégios."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def test_pasta_e_txt_com_conteudo_pelas_ferramentas(monkeypatch, tmp_path, capsys):
    import automacao
    import ferramentas

    monkeypatch.setattr(automacao, "_registrar_undo", lambda entrada: None)
    contexto = {"pedido_explicito": True, "dono_confirmado": True}

    pasta = ferramentas.executar_estruturado(
        "criar_pasta", {"nome": "Anotações", "dentro_de": str(tmp_path)},
        contexto=contexto,
    )
    caminho_pasta = tmp_path / "Anotações"
    assert pasta.ok and caminho_pasta.is_dir()
    assert str(caminho_pasta) in pasta.texto

    arquivo = ferramentas.executar_estruturado(
        "criar_arquivo_txt",
        {"nome": "ideias", "dentro_de": str(caminho_pasta),
         "conteudo": "Primeira linha\nSegunda linha\n"},
        contexto=contexto,
    )
    assert arquivo.ok
    assert (caminho_pasta / "ideias.txt").read_text(encoding="utf-8") == (
        "Primeira linha\nSegunda linha\n"
    )
    assert str(caminho_pasta / "ideias.txt") in arquivo.texto
    assert "Primeira linha" not in capsys.readouterr().out

    repetido = ferramentas.executar_estruturado(
        "criar_arquivo_txt",
        {"nome": "ideias", "dentro_de": str(caminho_pasta), "conteudo": "outro"},
        contexto=contexto,
    )
    assert not repetido.ok
    assert (caminho_pasta / "ideias.txt").read_text(encoding="utf-8") == (
        "Primeira linha\nSegunda linha\n"
    )


def test_nome_com_caminho_nao_escapa_da_pasta(monkeypatch, tmp_path):
    import automacao
    import ferramentas

    monkeypatch.setattr(automacao, "_registrar_undo", lambda entrada: None)
    resultado = ferramentas.executar_estruturado(
        "criar_arquivo_txt",
        {"nome": "../fora", "dentro_de": str(tmp_path), "conteudo": "não criar"},
        contexto={"pedido_explicito": True, "dono_confirmado": True},
    )
    assert not resultado.ok
    assert not (tmp_path.parent / "fora.txt").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="pastas XDG do Linux")
def test_local_padrao_e_pasta_inexistente(monkeypatch, tmp_path):
    import automacao
    import platform_compat

    monkeypatch.setattr(platform_compat, "get_special_folders",
                        lambda: {"desktop": tmp_path})
    assert automacao._descobrir_pasta_especial("Desktop") == tmp_path
    monkeypatch.setattr(automacao, "PASTA_MAP", {"desktop": [tmp_path]})
    assert automacao._resolver_destino_criar("") == tmp_path
    assert automacao._resolver_destino_criar(str(tmp_path / "nao-existe")) is None


@pytest.mark.skipif(sys.platform != "linux", reason="terminal Linux")
def test_linux_recusa_powershell_antes_de_rodar(monkeypatch):
    import terminal

    chamadas = []
    monkeypatch.setattr(terminal, "_rodar_shell", lambda *args: chamadas.append(args))
    texto, ok = terminal.executar("New-Item -ItemType Directory -Path ~/Teste")
    assert terminal._E_LINUX and not ok
    assert "Linux" in texto
    assert chamadas == []


@pytest.mark.skipif(sys.platform != "linux", reason="terminal Linux")
def test_terminal_linux_executa_bash_de_verdade():
    import terminal

    assert terminal._E_LINUX
    assert terminal.executar("printf linux") == ("linux", True)


@pytest.mark.skipif(sys.platform != "linux", reason="autenticação do Linux")
def test_comando_administrativo_simples_usa_pkexec(monkeypatch):
    import terminal

    monkeypatch.setattr(
        terminal.shutil, "which",
        lambda nome: f"/usr/bin/{Path(nome).name}",
    )
    assert terminal._preparar_linux("sudo dnf remove exemplo") == (
        ["/usr/bin/pkexec", "/usr/bin/dnf", "remove", "exemplo"], None,
    )
    assert terminal._preparar_linux("dnf install exemplo") == (
        ["/usr/bin/pkexec", "/usr/bin/dnf", "install", "exemplo"], None,
    )
    assert terminal.classificar("dnf -y install exemplo") == terminal.CONFIRMAR
    assert terminal._preparar_linux("systemctl status exemplo") == (
        [terminal._SHELL, "-c", "systemctl status exemplo"], None,
    )
    argv, erro = terminal._preparar_linux("sudo bash -c 'echo algo'")
    assert argv is None and "sem encadear" in erro
    argv, erro = terminal._preparar_linux("sudo dnf remove exemplo; echo feito")
    assert argv is None and "sem encadear" in erro


def test_bloqueio_de_desligamento_windows_permanece(monkeypatch):
    import terminal

    monkeypatch.setattr(terminal, "_E_LINUX", False)
    assert terminal.classificar("shutdown /s /t 0") == terminal.BLOQUEADO
    assert terminal.classificar("Stop-Computer") == terminal.BLOQUEADO
