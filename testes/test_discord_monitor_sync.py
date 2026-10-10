"""Persistência e propriedade exclusiva da escuta do Discord."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import discord_monitor
import preferencias


def _isolado(monkeypatch, tmp_path):
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "preferencias.json")
    preferencias.recarregar()
    monkeypatch.setattr(discord_monitor, "_ID_FILE", tmp_path / "id.txt")
    monkeypatch.setattr(discord_monitor, "_id_cache", None)
    evento = threading.Event()
    monkeypatch.setitem(sys.modules, "discord_bot", SimpleNamespace(
        _escuta_discord_ativa=evento))
    return evento


def test_desligar_discord_persiste_mesmo_sendo_valor_padrao(monkeypatch, tmp_path):
    evento = _isolado(monkeypatch, tmp_path)
    try:
        assert discord_monitor.selecionar(False)
        assert preferencias.exportar_sync()["monitor_discord_host"]["valor"] == ""
        preferencias.recarregar()
        assert not discord_monitor.aplicar()
        assert not evento.is_set()
        assert discord_monitor.selecionar(True)
        assert evento.is_set()
        preferencias.recarregar()
        assert discord_monitor.host_ativo() == discord_monitor.identificador_local()
    finally:
        preferencias.recarregar()


def test_windows_so_ativa_depois_de_confirmacao_do_gateway(monkeypatch, tmp_path):
    evento = _isolado(monkeypatch, tmp_path)
    monkeypatch.setattr(discord_monitor, "_windows", lambda: True)
    dono = {"host": ""}

    def gateway(metodo, *, host=None):
        if metodo == "POST":
            dono["host"] = host
        return {"ok": True, "host": dono["host"],
                "campo": {"valor": dono["host"], "quando": time.time()}}

    monkeypatch.setattr(discord_monitor, "_gateway", gateway)
    try:
        assert discord_monitor.selecionar(True)
        assert evento.is_set() and discord_monitor.pode_responder()
        dono["host"] = "11111111-1111-4111-8111-111111111111"
        assert not discord_monitor.pode_responder()
        assert discord_monitor.selecionar(False)
        assert not evento.is_set()
    finally:
        preferencias.recarregar()


def test_dono_do_gateway_vence_relogio_local_adiantado(monkeypatch, tmp_path):
    _isolado(monkeypatch, tmp_path)
    try:
        preferencias.mesclar_sync({"monitor_discord_host": {
            "valor": "11111111-1111-4111-8111-111111111111",
            "quando": time.time() + 300,
        }})
        remoto = {"valor": "22222222-2222-4222-8222-222222222222",
                  "quando": time.time()}
        preferencias.mesclar_sync({"monitor_discord_host": remoto}, forcar=True)
        assert preferencias.obter("monitor_discord_host") == remoto["valor"]
        assert preferencias.exportar_sync()["monitor_discord_host"] == remoto
    finally:
        preferencias.recarregar()


def test_gateway_so_aceita_dono_autenticado(monkeypatch, tmp_path):
    _isolado(monkeypatch, tmp_path)
    monkeypatch.setenv("EMILY_HK_PERMANENTE", "0")
    monkeypatch.setenv("EMILY_BROWSER_PERMANENTE", "0")
    caminho = Path(__file__).resolve().parents[1] / "emily-gateway-service" / "emily_gateway.py"
    spec = importlib.util.spec_from_file_location("emily_gateway_monitor_teste", caminho)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    monkeypatch.setattr(modulo, "_cfg", lambda nome, padrao="":
                        "segredo" if nome == "EMILY_PONTE_TOKEN" else padrao)
    modulo.APP.testing = True
    cliente = modulo.APP.test_client()
    cab = {"Authorization": "Bearer segredo"}
    try:
        assert cliente.get("/discord/monitor-owner").status_code == 401
        assert cliente.post("/discord/monitor-owner", headers=cab,
                            json={"host": "invalido"}).status_code == 400
        host = "22222222-2222-4222-8222-222222222222"
        resposta = cliente.post("/discord/monitor-owner", headers=cab,
                                json={"host": host})
        assert resposta.status_code == 200
        assert resposta.get_json()["campo"]["valor"] == host
        assert cliente.get("/discord/monitor-owner", headers=cab).get_json()["host"] == host
        assert cliente.post("/discord/monitor-owner", headers=cab,
                            json={"host": ""}).get_json()["host"] == ""
        preferencias.recarregar()
        assert preferencias.obter("monitor_discord_host") == ""
    finally:
        preferencias.recarregar()
