"""Atalho PTT configurável sem sincronizar hardware entre computadores."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import preferencias
import tecla_ptt


def test_tecla_ptt_valida_e_permanece_local(monkeypatch, tmp_path):
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    try:
        assert tecla_ptt.estado()["tecla"] == "mb5"
        assert tecla_ptt.definir("F9")["ok"] is True
        assert tecla_ptt.atual() == "f9"
        assert "tecla_ptt" not in preferencias.exportar_sync()
        assert tecla_ptt.definir("ctrl+f9")["ok"] is False
        assert tecla_ptt.atual() == "f9"
        assert tecla_ptt.definir("mb4")["rotulo"] == "Botão lateral 1"
        preferencias.recarregar()
        assert tecla_ptt.atual() == "mb4"
    finally:
        preferencias.recarregar()


def test_ptt_esperando_tecla_reconfigura_sem_reiniciar(monkeypatch, tmp_path):
    import voz

    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    tecla_ptt.definir("f9")
    escutando = threading.Event()
    gravou = threading.Event()
    resultado = []

    def esperar(codigo, cancelado=None, teclado=False):
        assert codigo == 67  # KEY_F9 no evdev
        assert teclado
        escutando.set()
        while not cancelado():
            threading.Event().wait(0.01)
        return None

    monkeypatch.setattr(voz, "_esperar_botao_evdev", esperar)
    monkeypatch.setattr(voz._pa, "open", lambda **_k: gravou.set())
    falar_antes = voz.falar_ativo.is_set()
    voz.falar_ativo.clear()
    try:
        thread = threading.Thread(target=lambda: resultado.append(voz.ouvir_ptt()))
        thread.start()
        assert escutando.wait(2)
        tecla_ptt.definir("f10")
        thread.join(2)
        assert not thread.is_alive()
        assert resultado == [""]
        assert not gravou.is_set()
    finally:
        if falar_antes:
            voz.falar_ativo.set()
        preferencias.recarregar()


def test_api_ptt_expoe_preferencia_local(monkeypatch, tmp_path):
    import interface_web

    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    try:
        api = interface_web.Api(object())
        assert api.ptt_tecla_estado()["tecla"] == "mb5"
        assert api.ptt_tecla_definir("space")["rotulo"] == "Espaço"
        assert api.ptt_tecla_estado()["tecla"] == "space"
    finally:
        preferencias.recarregar()


def test_falha_ao_abrir_microfone_nao_prende_estado_ptt(monkeypatch, tmp_path):
    import voz

    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    tecla_ptt.definir("f9")

    fechado = threading.Event()
    class Dispositivo:
        def close(self):
            fechado.set()
    monkeypatch.setattr(voz, "_esperar_botao_evdev", lambda *_a, **_k: Dispositivo())

    def sem_microfone(**_kwargs):
        raise OSError("microfone desconectado")

    monkeypatch.setattr(voz._pa, "open", sem_microfone)
    voz.escutando_ativo.clear()
    try:
        assert voz.ouvir_ptt() == ""
        assert not voz.escutando_ativo.is_set()
        assert fechado.is_set()
    finally:
        preferencias.recarregar()


@pytest.mark.parametrize("eventos,esperado,rotulo", [
    ([(13, "down"), (13, "up")], "scan:13", "= / +"),
    ([(12, "down"), (12, "up")], "scan:12", "- / _"),
    ([(56, "down"), (56, "up")], "scan:56", "Alt esquerdo"),
    ([(15, "down"), (15, "up")], "scan:15", "Tab"),
    ([(2, "down"), (2, "up")], "scan:2", "1"),
    ([(40, "down"), (40, "up")], "scan:40", "Acento / '"),
    ([(42, "down"), (13, "down"),
      (13, "up")], "scan:13", "= / +"),
])
def test_captura_tecla_fisica_aceita_simbolos_modificadores_e_numeros(
        monkeypatch, tmp_path, eventos, esperado, rotulo):
    import voz
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    from evdev import ecodes
    class Dispositivo:
        fd = 1234
        fechado = False
        def read(self):
            lote = [SimpleNamespace(type=ecodes.EV_KEY, code=codigo,
                    value=1 if tipo == "down" else 0) for codigo, tipo in eventos]
            eventos.clear()
            return lote
        def close(self):
            self.fechado = True
    dev = Dispositivo()
    monkeypatch.setattr(voz, "_dispositivos_evdev", lambda **_k: [dev])
    monkeypatch.setattr(voz, "_mouses_evdev", lambda: [])
    import select
    monkeypatch.setattr(select, "select", lambda *_a: ([dev.fd], [], []))
    try:
        estado = voz.capturar_atalho_ptt()
        assert estado["ok"] is True
        assert estado["tecla"] == esperado
        assert estado["rotulo"] == rotulo
        assert dev.fechado
        assert not tecla_ptt.capturando()
        assert "tecla_ptt" not in preferencias.exportar_sync()
        assert "tecla_ptt_rotulo" not in preferencias.exportar_sync()
    finally:
        preferencias.recarregar()


def test_codigo_fisico_aciona_ptt_e_reconfiguracao(monkeypatch, tmp_path):
    import voz
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    tecla_ptt.definir_capturada("scan:13", "+")
    visto = threading.Event()
    argumentos = []
    def esperar(codigo, cancelado=None, teclado=False):
        argumentos.append((codigo, teclado))
        visto.set()
        while not cancelado():
            threading.Event().wait(0.01)
        return None
    monkeypatch.setattr(voz, "_esperar_botao_evdev", esperar)
    resultado = []
    try:
        thread = threading.Thread(target=lambda: resultado.append(voz.ouvir_ptt()))
        thread.start()
        assert visto.wait(2)
        tecla_ptt.definir_capturada("scan:56", "Alt")
        thread.join(2)
        assert resultado == [""]
        assert argumentos == [(13, True)]
    finally:
        preferencias.recarregar()


def test_captura_windows_usa_scan_code_e_aceita_alt_e_simbolos(monkeypatch, tmp_path):
    import voz
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    monkeypatch.setattr(voz, "os", SimpleNamespace(name="nt"))
    class Listener:
        def __init__(self, **_kwargs):
            pass
        def start(self):
            pass
        def stop(self):
            pass
    monkeypatch.setattr(voz.pynput_mouse, "Listener", Listener)
    def hook(callback):
        for codigo, nome, tipo in [(42, "shift", "down"), (13, "+", "down"),
                                    (13, "+", "up")]:
            callback(SimpleNamespace(scan_code=codigo, name=nome, event_type=tipo))
        return object()
    monkeypatch.setattr(voz.keyboard, "hook", hook)
    monkeypatch.setattr(voz.keyboard, "unhook", lambda _h: None)
    try:
        resultado = voz.capturar_atalho_ptt()
        assert resultado["tecla"] == "scan:13"
        assert resultado["rotulo"] == "+"
    finally:
        preferencias.recarregar()


@pytest.mark.parametrize("codigo,rotulo", [
    (272, "Botão esquerdo"), (273, "Botão direito"),
    (274, "Botão do meio"), (275, "Botão lateral 1"), (276, "Botão lateral 2")])
def test_captura_mouse_fedora_sem_opcoes_fixas(monkeypatch, tmp_path, codigo, rotulo):
    import voz
    from evdev import ecodes
    import select
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    class Dispositivo:
        fd = 4321
        def read(self):
            return [SimpleNamespace(type=ecodes.EV_KEY, code=codigo, value=v)
                    for v in (1, 0)]
        def close(self):
            pass
    dev = Dispositivo()
    monkeypatch.setattr(voz, "_dispositivos_evdev", lambda **_k: [])
    monkeypatch.setattr(voz, "_mouses_evdev", lambda: [dev])
    monkeypatch.setattr(select, "select", lambda *_a: ([dev.fd], [], []))
    try:
        resultado = voz.capturar_atalho_ptt()
        assert resultado["tecla"] == f"mouse:{codigo}"
        assert resultado["rotulo"] == rotulo
    finally:
        preferencias.recarregar()


def test_codigo_fisico_windows_eh_usado_para_ativar_ptt(monkeypatch, tmp_path):
    import voz
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    monkeypatch.setattr(voz, "os", SimpleNamespace(name="nt"))
    tecla_ptt.definir_capturada("scan:13", "+")
    argumentos = []
    class Teclado:
        def is_pressed(self, codigo):
            argumentos.append(codigo)
            return len(argumentos) >= 2
    monkeypatch.setattr(voz, "keyboard", Teclado())
    monkeypatch.setattr(voz._pa, "open", lambda **_k: (_ for _ in ()).throw(OSError("sem mic")))
    try:
        assert voz.ouvir_ptt() == ""
        assert argumentos == [13, 13]
    finally:
        preferencias.recarregar()


def test_cancelamento_antes_da_captura_nao_salva_nem_afeta_proxima():
    import voz
    tecla_ptt.cancelar_captura("ptt-cancelado-antes")
    assert voz.capturar_atalho_ptt("ptt-cancelado-antes") == {
        "ok": False, "cancelado": True}
    token = tecla_ptt.iniciar_captura("ptt-seguinte")
    assert token is not None
    tecla_ptt.finalizar_captura(token)
    assert not tecla_ptt.capturando()


def test_fim_de_captura_antiga_nao_cancela_nova():
    antigo = tecla_ptt.iniciar_captura("ptt-antigo")
    assert antigo is not None
    tecla_ptt.cancelar_captura("ptt-antigo")
    novo = tecla_ptt.iniciar_captura("ptt-novo")
    assert novo is not None
    tecla_ptt.finalizar_captura(antigo)
    assert tecla_ptt.capturando(novo)
    tecla_ptt.finalizar_captura(novo)
