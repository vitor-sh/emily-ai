from __future__ import annotations

import json
import sys

import emily_remote
import llm


def test_so_omniroute_local_no_windows_usa_ponte():
    assert emily_remote.provedor_via_fedora(
        "openai", "http://localhost:20128/v1", windows=True)
    assert emily_remote.provedor_via_fedora(
        "omniroute", "http://127.0.0.1:20128/v1", windows=True)
    assert not emily_remote.provedor_via_fedora(
        "openai", "http://localhost:20128/v1", windows=False)
    assert not emily_remote.provedor_via_fedora(
        "claude", "http://localhost:20128/v1", windows=True)
    assert not emily_remote.provedor_via_fedora(
        "openai", "https://api.exemplo/v1", windows=True)


def test_ngrok_proprio_apenas_no_fedora(monkeypatch):
    monkeypatch.setattr(emily_remote.sys, "platform", "linux")
    monkeypatch.setattr(emily_remote.platform, "freedesktop_os_release",
                        lambda: {"ID": "fedora"})
    assert emily_remote.ambiente_fedora()
    monkeypatch.setattr(emily_remote.platform, "freedesktop_os_release",
                        lambda: {"ID": "ubuntu"})
    assert not emily_remote.ambiente_fedora()
    monkeypatch.setattr(emily_remote.sys, "platform", "win32")
    assert not emily_remote.ambiente_fedora()


def test_gateway_do_release_e_lido_do_pacote(monkeypatch, tmp_path):
    (tmp_path / "windows-release.json").write_text(json.dumps({
        "sync_url": "https://fedora.exemplo/"}), encoding="utf-8")
    monkeypatch.delenv("EMILY_SYNC_URL", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert emily_remote.gateway_fedora() == "https://fedora.exemplo"
    assert emily_remote.base_llm_fedora() == "https://fedora.exemplo/llm/v1"


def test_endpoint_do_windows_persistido_apos_consulta_autenticada(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    class Resposta:
        def raise_for_status(self): pass
        def json(self):
            return {"ok": True, "url": "https://novo.ngrok-free.dev", "atualizado_em": 10.5}
    class Sessao:
        def get(self, url, **kwargs):
            assert url == "https://antigo.ngrok-free.dev/gateway/endpoint"
            assert kwargs["headers"]["Authorization"] == "Bearer teste"
            return Resposta()
    assert emily_remote.sincronizar_endpoint_cliente(
        "https://antigo.ngrok-free.dev", "teste", Sessao())
    assert emily_remote.endpoint_cliente() == "https://novo.ngrok-free.dev"
    assert not emily_remote.sincronizar_endpoint_cliente(
        "https://antigo.ngrok-free.dev", "teste", Sessao())


def test_config_openai_do_windows_troca_chave_e_base(monkeypatch, tmp_path):
    arquivo = tmp_path / ".env"
    arquivo.write_text("\n".join([
        "# >>> provedor: openai",
        "EMILY_PROVEDOR_OPENAI_BASE=http://localhost:20128/v1",
        "EMILY_PROVEDOR_OPENAI_CHAVE=chave-local",
        "EMILY_PROVEDOR_OPENAI_MODELO=cx/gpt-5.6-terra",
        "# <<< provedor: openai",
    ]), encoding="utf-8")
    monkeypatch.setattr(emily_remote, "provedor_via_fedora",
                        lambda *_a, **_k: True)
    monkeypatch.setattr(emily_remote, "base_llm_fedora",
                        lambda: "https://fedora.exemplo/llm/v1")
    config = llm._parsear_secoes_provedor(str(arquivo))["openai"]
    assert config.base_url == "https://fedora.exemplo/llm/v1"
    assert config.env_chave == "EMILY_PONTE_TOKEN"
