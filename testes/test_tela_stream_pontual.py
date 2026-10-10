"""Captura pontual do Android não deve ligar o fluxo contínuo do Spectacle."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_duas_telas_pontuais_usam_um_quadro_sem_ligar_loop(monkeypatch):
    import tela_stream

    chamadas = []
    monkeypatch.setattr(tela_stream, "_garantir_loop", lambda:
                        (_ for _ in ()).throw(AssertionError("loop contínuo ligado")))
    monkeypatch.setattr(tela_stream, "_demandar", lambda:
                        (_ for _ in ()).throw(AssertionError("espectador artificial")))
    monkeypatch.setattr(tela_stream, "_capturar_uma_vez", lambda:
                        chamadas.append(1) or Image.new("RGB", (200, 100), "red"))
    monkeypatch.setattr(tela_stream, "_geometria", lambda: (
        {"left": 0, "top": 0, "width": 200, "height": 100},
        [{"left": 0, "top": 0, "width": 100, "height": 100},
         {"left": 100, "top": 0, "width": 100, "height": 100}],
    ))
    monkeypatch.setattr(tela_stream, "_ULTIMA", {
        "img": None, "w": 0, "h": 0, "ts": 0.0,
    })
    primeiro, idade1 = tela_stream.capturar_jpeg(1, unico=True)
    segundo, idade2 = tela_stream.capturar_jpeg(2, unico=True)
    assert primeiro.startswith(b"\xff\xd8") and segundo.startswith(b"\xff\xd8")
    assert idade1 < 2 and idade2 < 2
    assert chamadas == [1]
    assert tela_stream._thread is None or not tela_stream._thread.is_alive()


def test_inventario_de_monitores_nao_renova_captura(monkeypatch):
    import tela_stream

    monkeypatch.setattr(tela_stream, "_demandar", lambda:
                        (_ for _ in ()).throw(AssertionError("inventário acionou captura")))
    monkeypatch.setattr(tela_stream, "_geometria", lambda: (
        {"left": 0, "top": 0, "width": 100, "height": 100},
        [{"left": 0, "top": 0, "width": 100, "height": 100}],
    ))
    monkeypatch.setattr(tela_stream, "_nomes_kscreen", lambda: [])
    assert tela_stream.listar_monitores()[0]["indice"] == 1
