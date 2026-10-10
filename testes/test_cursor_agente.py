"""Restauração do cursor sem modificar o desktop nos testes unitários."""
import struct
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cursor_agente as c


@pytest.fixture
def ambiente(monkeypatch, tmp_path):
    config = {"cursorTheme": "meu-tema", "cursorSize": "48"}
    calls = []
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    monkeypatch.setattr(c, "instalar_tema", lambda: None)
    monkeypatch.setattr(c, "_read", lambda key: config[key])
    monkeypatch.setattr(c.subprocess, "Popen", lambda *a, **k: None)
    def run(args):
        calls.append(args)
        if args[0] == "plasma-apply-cursortheme":
            config["cursorTheme"] = args[1]
            config["cursorSize"] = args[args.index("--size") + 1] if "--size" in args else "24"
        else:
            config[args[args.index("--key") + 1]] = ""
        return ""
    monkeypatch.setattr(c, "_run", run)
    return config, calls


def test_restaura_tema_tamanho_e_chamadas_repetidas(ambiente):
    config, calls = ambiente
    cursor = c.CursorAgente(True)
    cursor.ativar()
    cursor.ativar()
    assert config == {"cursorTheme": c.TEMA, "cursorSize": "48"}
    assert len(calls) == 1
    cursor.restaurar()
    cursor.restaurar()
    assert config == {"cursorTheme": "meu-tema", "cursorSize": "48"}
    assert len(calls) == 2


def test_restaura_configuracao_original_sem_tamanho_explicito(ambiente):
    config, _ = ambiente
    config["cursorSize"] = ""
    cursor = c.CursorAgente(True)
    cursor.ativar()
    cursor.restaurar()
    assert config == {"cursorTheme": "meu-tema", "cursorSize": ""}


def test_preserva_nova_escolha_da_pessoa(ambiente):
    config, _ = ambiente
    cursor = c.CursorAgente(True)
    cursor.ativar()
    config["cursorTheme"] = "novo-tema"
    cursor.restaurar()
    assert config["cursorTheme"] == "novo-tema"


def test_duas_sessoes_nao_sobrescrevem_original(ambiente):
    config, _ = ambiente
    first, second = c.CursorAgente(True), c.CursorAgente(True)
    first.ativar()
    second.ativar()
    second.restaurar()
    assert config["cursorTheme"] == c.TEMA
    first.restaurar()
    assert config["cursorTheme"] == "meu-tema"


def test_falha_ao_aplicar_libera_lock_e_restaura(ambiente, monkeypatch):
    config, _ = ambiente
    run = c._run
    def fail(args):
        if args[0] == "plasma-apply-cursortheme" and args[1] == c.TEMA:
            run(args)  # ferramenta pode falhar depois de gravar o KConfig
            raise RuntimeError("falha do compositor")
        return run(args)
    monkeypatch.setattr(c, "_run", fail)
    cursor = c.CursorAgente(True)
    cursor.ativar()
    assert cursor._lock_file is None
    assert config["cursorTheme"] == "meu-tema"


def test_recolorir_preserva_hotspot_duracao_e_alpha():
    header = struct.pack("<4sIII", b"Xcur", 16, 1, 1)
    toc = struct.pack("<III", 0xFFFD0002, 24, 28)
    chunk = struct.pack("<9I", 36, 0xFFFD0002, 24, 1, 2, 1, 1, 0, 50)
    original = header + toc + chunk + struct.pack("<2I", 0xffffffff, 0xff000000)
    tinted = c._colorir_xcursor(original)
    assert tinted[:64] == original[:64]
    assert struct.unpack_from("<2I", tinted, 64) == (0xffff8540, 0xff000000)


def test_nao_reinicia_sessao_antes_da_restauracao_final():
    import agente_ui
    from desktop_backend import BackendDesktopFalso
    attempts = []
    session = agente_ui.SessaoAgenteUI(
        backend=BackendDesktopFalso(),
        decisor=lambda *_: {"acao": "concluido", "mensagem": "OK"},
        verificar_resultado=False,
    )
    session.adicionar_ouvinte(lambda state: attempts.append(session.iniciar("Nova tarefa", em_thread=False))
                             if state["estado"] == "concluido" else None)
    from unittest.mock import patch
    with patch.object(agente_ui, "_contexto_fixo_padrao", return_value=""):
        assert session.iniciar("Primeira tarefa", em_thread=False)
    assert attempts == [False]
    assert session.aguardar(0)
