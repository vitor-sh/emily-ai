"""Invariantes estáticos do instalador permanente, sem executar systemd."""

from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def test_instalador_inclui_servico_de_tela_e_dependencias():
    instalar = (RAIZ / "emily-gateway-service" / "instalar.sh").read_text(encoding="utf-8")
    assert "tela-pc.service" in instalar
    assert 'systemctl --user enable --now tela-pc.service' in instalar
    assert 'import dbus, gi' in instalar
    assert 'gi.require_version("Gst", "1.0")' in instalar


def test_gateway_espera_sessao_grafica_e_instalador_reinicia_com_ambiente_atual():
    instalar = (RAIZ / "emily-gateway-service" / "instalar.sh").read_text(encoding="utf-8")
    unit = (RAIZ / "emily-gateway-service" / "emily-gateway.service").read_text(encoding="utf-8")
    assert "After=network-online.target graphical-session.target" in unit
    assert "systemctl --user import-environment DISPLAY WAYLAND_DISPLAY" in instalar
    assert "systemctl --user restart emily-gateway.service" in instalar


def test_servico_de_tela_exige_token_e_tem_endurecimento_basico():
    codigo = (RAIZ / "tela-pc-service" / "tela_pc_service.py").read_text(encoding="utf-8")
    unit = (RAIZ / "tela-pc-service" / "tela-pc.service").read_text(encoding="utf-8")
    assert "if not _TOKEN:\n        return False" in codigo
    assert "hmac.compare_digest" in codigo
    assert "NoNewPrivileges=true" in unit
    assert "PrivateTmp=true" in unit