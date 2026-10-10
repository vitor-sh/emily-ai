from __future__ import annotations

import json
from types import SimpleNamespace

import emily_remote
import firebase_endpoint
import windows_update


def test_registro_publico_assinado_rejeita_adulteracao():
    registro = firebase_endpoint.criar_registro("https://emily.ngrok-free.dev", 1234567890.25, "segredo")
    assert firebase_endpoint.validar_registro(registro, "segredo") == (
        "https://emily.ngrok-free.dev", 1234567890.25)
    assert firebase_endpoint.validar_registro(registro, "outro-token") is None
    assert firebase_endpoint.validar_registro({**registro, "url": "https://falso.ngrok-free.dev"}, "segredo") is None
    assert firebase_endpoint.validar_registro({**registro, "atualizado_em": "1234567891.250000"}, "segredo") is None


def test_windows_recupera_endpoint_assinado_sem_depender_do_antigo(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("EMILY_PONTE_TOKEN", "segredo")
    monkeypatch.setenv("EMILY_FIREBASE_DATABASE_URL", "https://teste.firebaseio.com")
    registro = firebase_endpoint.criar_registro("https://novo.ngrok-free.dev", 1234567890.25, "segredo")

    class Resposta:
        def raise_for_status(self): pass
        def json(self): return registro

    class Sessao:
        def get(self, url, **kwargs):
            assert url == "https://teste.firebaseio.com/gateway_endpoint.json"
            assert "headers" not in kwargs  # leitura pública, sem token do gateway
            return Resposta()

    assert emily_remote.sincronizar_endpoint_firebase(sessao=Sessao())
    assert emily_remote.endpoint_cliente() == "https://novo.ngrok-free.dev"
    assert not emily_remote.sincronizar_endpoint_firebase(sessao=Sessao())

    caminho = tmp_path / "Emily" / "gateway-client.json"
    assert json.loads(caminho.read_text())["atualizado_em"] == 1234567890.25


def test_resposta_antiga_nao_reverte_endpoint_do_windows(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    caminho = tmp_path / "Emily" / "gateway-client.json"
    caminho.parent.mkdir(parents=True)
    caminho.write_text(json.dumps({"url": "https://novo.ngrok-free.dev",
                                  "atualizado_em": 20}), encoding="utf-8")

    class Resposta:
        def raise_for_status(self): pass
        def json(self): return {"ok": True, "url": "https://antigo.ngrok-free.dev",
                                "atualizado_em": 10}

    class Sessao:
        def get(self, *_args, **_kwargs): return Resposta()

    assert not emily_remote.sincronizar_endpoint_cliente(
        "https://antigo.ngrok-free.dev", "segredo", Sessao())
    assert emily_remote.endpoint_cliente() == "https://novo.ngrok-free.dev"


def test_feed_windows_usa_descoberta_do_firebase(monkeypatch, tmp_path):
    (tmp_path / "windows-release.json").write_text(json.dumps({
        "version": "1.0.2", "sync_url": "https://antigo.ngrok-free.dev",
        "update_url": "https://antigo.ngrok-free.dev/windows/update"}), encoding="utf-8")
    monkeypatch.setattr(windows_update.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(windows_update, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(emily_remote, "gateway_fedora", lambda: "https://novo.ngrok-free.dev")
    cfg = windows_update._config()
    assert cfg["sync_url"] == "https://novo.ngrok-free.dev"
    assert cfg["update_url"] == "https://novo.ngrok-free.dev/windows/update"
