"""Testes puros do emissor WebRTC; não abrem portal, áudio nem rede."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tela-pc-service"))

import tela_webrtc as rtc  # noqa: E402


def test_perfis_adaptativos_fixos():
    assert list(rtc.PERFIS) == ["1080p60", "1080p30", "720p60", "720p30"]
    assert rtc.perfil("720P30").largura == 1280
    assert rtc.perfil("inexistente").nome == "1080p60"


def test_encoder_instalado_e_pipeline_h264_opus():
    p = rtc.PERFIS["1080p60"]
    encoder, desc = rtc.descricao_pipeline(10, 42, p, "sink.monitor")
    assert encoder in {"vah264lpenc", "vah264enc", "vaapih264enc", "nvh264enc", "x264enc", "openh264enc"}
    assert "rtph264pay pt=96" in desc
    assert "rtpopuspay pt=111" in desc
    assert "webrtcbin name=webrtc" in desc
    assert "width=1920,height=1080,framerate=60/1" in desc
    # O payloader anuncia dinamicamente os parâmetros H.264 reais. Fixar estes
    # valores quebra a negociação com OpenH264 no GStreamer 1.28/Fedora 44.
    assert "packetization-mode=" not in desc
    assert "profile-level-id=" not in desc


def test_pipeline_sem_audio_nao_inclui_opus():
    _, desc = rtc.descricao_pipeline(10, 42, rtc.PERFIS["720p30"], "")
    assert "rtph264pay" in desc
    assert "opusenc" not in desc


def test_gerenciador_valida_credenciais_antes_do_portal():
    abriu = []
    ger = rtc.GerenciadorWebRtc(lambda: abriu.append(True), lambda: "", lambda _m: None)
    try:
        ger.iniciar("", "")
    except ValueError as exc:
        assert "obrigatórios" in str(exc)
    else:
        raise AssertionError("credenciais vazias deveriam falhar")
    assert abriu == []


def test_sessao_limpa_portal_e_tv_quando_pipeline_falha(monkeypatch):
    class PortalFalso:
        fd = 10
        streams = [{"node": 42, "posicao": (0, 0)}]

        def __init__(self):
            self.fechado = False

        def abrir(self):
            pass

        def fechar(self):
            self.fechado = True

    portal = PortalFalso()
    chamadas = []
    sessao = rtc.SessaoWebRtc(
        lambda: portal, "192.168.0.20", "token", "720p30", 1, "", lambda _m: None)

    def request(method, path, body=None):
        chamadas.append((method, path, body))
        if method == "POST":
            return {"ok": True, "session_id": "sessao-teste"}
        return {"ok": True}

    monkeypatch.setattr(sessao.api, "request", request)
    monkeypatch.setattr(rtc.Gst, "parse_launch",
                        lambda _desc: (_ for _ in ()).throw(RuntimeError("pipeline inválido")))

    try:
        sessao.iniciar()
    except RuntimeError as exc:
        assert "pipeline inválido" in str(exc)
    else:
        raise AssertionError("a falha do pipeline deveria ser propagada")

    assert portal.fechado is True
    assert ("DELETE", "/v1/screen/sessions/sessao-teste", None) in chamadas
    assert sessao.status()["estado"] == "parado"