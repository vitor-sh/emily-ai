"""O snapshot do gateway não deve acionar o ScreenCast contínuo."""

import importlib.util
from pathlib import Path


def test_snapshot_pontual_na_rota_do_servico(monkeypatch):
    base = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(base / "tela-pc-service"))
    spec = importlib.util.spec_from_file_location(
        "tela_pc_service_pontual_test", base / "tela-pc-service" / "tela_pc_service.py"
    )
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    monkeypatch.setattr(service, "token_ok", lambda _: True)
    monkeypatch.setattr(service.GER, "demandar", lambda _: (_ for _ in ()).throw(
        AssertionError("snapshot abriu ScreenCast contínuo")
    ))
    calls = []
    monkeypatch.setattr(service.captura_pontual, "capturar_jpeg", lambda **kwargs:
                        (calls.append(kwargs) or (b"\xff\xd8imagem", 0.5)))

    response = service.app.test_client().get("/tela/jpg?monitor=2&unico=1")
    assert response.status_code == 200
    assert response.data == b"\xff\xd8imagem"
    assert response.headers["X-Emily-Fonte"] == "captura-pontual"
    assert calls == [{"monitor": 2, "unico": True}]
