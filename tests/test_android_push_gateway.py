"""Registro autenticado de dispositivo e envio seguro pelo gateway."""
import importlib.util
from pathlib import Path


def test_push_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("EMILY_HK_PERMANENTE", "0")
    monkeypatch.setenv("EMILY_BROWSER_PERMANENTE", "0")
    path = Path(__file__).resolve().parents[1] / "emily-gateway-service/emily_gateway.py"
    spec = importlib.util.spec_from_file_location("gateway_push_test", path)
    gateway = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway)
    monkeypatch.setattr(gateway, "_cfg", lambda key, default="": {
        "EMILY_PONTE_TOKEN": "secret", "EMILY_FIREBASE_SERVICE_ACCOUNT": "/private/key.json"
    }.get(key, default))
    client = gateway.APP.test_client()
    token = "a" * 100
    for endpoint in ("register", "send"):
        assert client.post(f"/android/push/{endpoint}", json={}).status_code == 401
    auth = {"Authorization": "Bearer secret"}
    assert client.post("/android/push/register", json={"token": "bad"}, headers=auth).status_code == 400
    import android_push
    monkeypatch.setattr(gateway, "salvar_push_token", lambda value: android_push.salvar_token(value, tmp_path / "token.json"))
    assert client.post("/android/push/register", json={"token": token}, headers=auth).json["ok"]
    assert android_push.ler_token(tmp_path / "token.json") == token
    assert (tmp_path / "token.json").stat().st_mode & 0o777 == 0o600
    assert client.post("/android/push/send", json={"texto": ""}, headers=auth).status_code == 400
    sent = []
    monkeypatch.setattr(gateway, "enviar_push", lambda title, text, **kw: (
        sent.append((title, text, kw)) or {"name": "projects/emilyapp-dfd24/messages/123"}))
    response = client.post("/android/push/send", json={"titulo": "Oi", "texto": "Pronto"}, headers=auth)
    assert response.json["ok"] and sent == [("Oi", "Pronto", {"credentials_file": "/private/key.json"})]
    monkeypatch.setattr(gateway, "enviar_push", lambda *args, **kw: (_ for _ in ()).throw(RuntimeError("missing")))
    assert client.post("/android/push/send", json={"texto": "Oi"}, headers=auth).status_code == 503
    monkeypatch.setattr(gateway, "_cfg", lambda key, default="": "")
    assert client.post("/android/push/register", json={"token": token}, headers=auth).status_code == 503


def test_push_requires_registered_device_and_credentials(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "emily-gateway-service"))
    import android_push
    import pytest
    with pytest.raises(RuntimeError, match="celular"):
        android_push.enviar("Oi", "Mensagem", caminho=tmp_path / "missing.json")
    android_push.salvar_token("a" * 100, tmp_path / "token.json")
    with pytest.raises(RuntimeError, match="EMILY_FIREBASE_SERVICE_ACCOUNT"):
        android_push.enviar("Oi", "Mensagem", caminho=tmp_path / "token.json")