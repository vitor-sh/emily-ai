"""Rotas de atualização: não devem expor APK sem token nem sem publicação completa."""
import importlib.util
import json
from pathlib import Path


def test_android_update_auth_and_publication(tmp_path, monkeypatch):
    monkeypatch.setenv("EMILY_HK_PERMANENTE", "0")
    monkeypatch.setenv("EMILY_BROWSER_PERMANENTE", "0")
    source = Path(__file__).resolve().parents[1] / "emily-gateway-service/emily_gateway.py"
    spec = importlib.util.spec_from_file_location("gateway_update_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PASTA_ATUALIZACAO_ANDROID", tmp_path)
    monkeypatch.setattr(module, "_cfg", lambda key, default="": "secret" if key == "EMILY_PONTE_TOKEN" else default)
    client = module.APP.test_client()
    for path in ("/android/update", "/android/update/apk"):
        assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer secret"}
    assert client.get("/android/update", headers=headers).json["ok"] is False
    assert client.get("/android/update/apk", headers=headers).status_code == 404
    (tmp_path / "emily-2.apk").write_bytes(b"test apk")
    (tmp_path / "latest.json").write_text(json.dumps({"version_code": 2, "sha256": "a" * 64, "size": 8}))
    assert client.get("/android/update", headers=headers).json["version_code"] == 2
    assert client.get("/android/update/apk", headers=headers).data == b"test apk"
    (tmp_path / "emily-2.apk").write_bytes(b"partial")
    assert client.get("/android/update", headers=headers).json["ok"] is False
    monkeypatch.setattr(module, "_cfg", lambda key, default="": "")
    assert client.get("/android/update", headers=headers).status_code == 503
    assert client.get("/android/update/apk", headers=headers).status_code == 503