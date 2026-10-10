"""Testes não herdam a conexão privada de produção do computador."""
import pytest

@pytest.fixture(autouse=True)
def isolate_cloud_host(monkeypatch, tmp_path):
    import cloud_runtime_client
    monkeypatch.setattr(cloud_runtime_client, 'CONFIG', tmp_path/'cloud-host.json')
