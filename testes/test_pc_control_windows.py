"""O contrato Android usa ações Windows, sem chamar utilitários do Fedora."""

from __future__ import annotations

import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parents[1] / "emily-gateway-service"
sys.path.insert(0, str(PASTA))

from pc_control import Aplicativo  # noqa: E402
from pc_control_windows import WindowsPCController  # noqa: E402
from windows_screen import _pcm16  # noqa: E402


def test_abre_app_atalho_e_arquivo_sem_shell(monkeypatch, tmp_path):
    controlador = WindowsPCController(home=tmp_path)
    atalho = tmp_path / "Brave.lnk"
    atalho.write_bytes(b"link")
    aberto = []
    monkeypatch.setattr(controlador, "_apps", lambda: [Aplicativo("Brave", "Brave", atalho)])
    monkeypatch.setattr(controlador, "_iniciar_arquivo", aberto.append)
    assert controlador.executar("abrir_app", {"nome": "Brave"}, turno_id="1")["ok"]
    arquivo = tmp_path / "nota.txt"
    arquivo.write_text("olá", encoding="utf-8")
    assert controlador.executar("abrir_arquivo", {"caminho": str(arquivo)}, turno_id="1")["ok"]
    assert aberto == [str(atalho), str(arquivo)]


def test_site_usa_navegador_padrao_e_valida_url(monkeypatch, tmp_path):
    controlador = WindowsPCController(home=tmp_path)
    urls = []
    monkeypatch.setattr("pc_control_windows.webbrowser.open", lambda url: urls.append(url) or True)
    assert controlador.executar("abrir_site", {"url": "https://youtube.com/watch?v=1"}, turno_id="1")["ok"]
    assert urls == ["https://youtube.com/watch?v=1"]
    assert not controlador.executar("abrir_site", {"url": "file:///etc/passwd"}, turno_id="1")["ok"]


def test_audio_pcm_entrega_estereo_16_bits_sem_amostras():
    vazio = _pcm16([], 4800)
    assert len(vazio) == 4800 * 2 * 2
    assert set(vazio) == {0}
