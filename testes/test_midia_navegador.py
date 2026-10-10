"""Testes locais do catálogo e baixador de mídia (sem rede e sem download real)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ferramentas  # noqa: E402
import midia_navegador as midia  # noqa: E402
import navegador  # noqa: E402


def test_novas_ferramentas_estao_no_catalogo():
    nomes = {
        "listar_midias_da_aba",
        "ver_qualidades_da_midia",
        "baixar_midia_da_aba",
        "status_download_midia",
    }
    assert nomes <= set(ferramentas.CATALOGO)
    assert ferramentas.CATALOGO["baixar_midia_da_aba"].obrigatorios == ["indice", "formato"]
    assert ferramentas.CATALOGO["listar_midias_da_aba"].somente_leitura is True
    assert ferramentas.CATALOGO["status_download_midia"].somente_leitura is True


@pytest.mark.parametrize("url", [
    "blob:https://site.example/123",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "http://localhost/video.mp4",
])
def test_validador_recusa_esquemas_e_hosts_locais(url):
    with pytest.raises(ValueError):
        midia._validar_url(url)


def test_validador_recusa_ip_privado(monkeypatch):
    monkeypatch.setattr(midia.socket, "getaddrinfo", lambda *_: [
        (2, 1, 6, "", ("192.168.1.9", 443)),
    ])
    with pytest.raises(ValueError, match="rede local"):
        midia._validar_url("https://exemplo.invalid/video.mp4")


def test_validador_aceita_ip_publico(monkeypatch):
    monkeypatch.setattr(midia.socket, "getaddrinfo", lambda *_: [
        (2, 1, 6, "", ("93.184.216.34", 443)),
    ])
    assert midia._validar_url("https://example.com/video.mp4") == "https://example.com/video.mp4"


def test_selecao_de_formato_e_qualidade():
    seletor, pp, merge = midia._formato_ytdlp("audio", "melhor")
    assert seletor == "bestaudio/best"
    assert pp[0]["key"] == "FFmpegExtractAudio"
    assert pp[0]["preferredcodec"] == "mp3"
    assert merge is None

    seletor, pp, merge = midia._formato_ytdlp("video", "1080p")
    assert "height<=1080" in seletor
    assert pp == []
    assert merge == "mp4"

    _, pp, _ = midia._formato_ytdlp("audio", "320kbps")
    assert pp[0]["preferredquality"] == "320"


def test_erro_de_login_pode_acionar_sessao_mas_erro_comum_nao():
    assert midia._parece_exigir_sessao(RuntimeError("Sign in to confirm your age"))
    assert midia._parece_exigir_sessao(RuntimeError("HTTP Error 403: Forbidden"))
    assert not midia._parece_exigir_sessao(RuntimeError("format is not available"))


def test_cabecalhos_usam_contexto_do_frame_sem_desligar_tls():
    assert midia._cabecalhos_http("https://player.example/embed/42?token=x") == {
        "Referer": "https://player.example/embed/42?token=x",
        "Origin": "https://player.example",
    }
    assert midia._cabecalhos_http("blob:https://player.example/id") == {}
    assert "nocheckcertificate" not in midia._opcoes_base()


def test_catalogo_estavel_por_indice(monkeypatch):
    resposta = {
        "tipo": "ok",
        "url": "https://example.com/pagina",
        "titulo": "Página",
        "navegador": "Chromium",
        "itens": [{"url": "https://cdn.example/a.mp4"}, {"url": "https://cdn.example/b.mp4"}],
    }
    monkeypatch.setattr(navegador, "enviar_comando_com_id", lambda *a, **k: resposta)
    assert navegador.descobrir_midias()["tipo"] == "ok"
    assert navegador.midia_do_catalogo(1)["url"].endswith("a.mp4")
    assert navegador.midia_do_catalogo("2")["url"].endswith("b.mp4")
    assert navegador.midia_do_catalogo(0) is None
    assert navegador.midia_do_catalogo(3) is None
    assert navegador.metadados_catalogo_midias()["url"] == "https://example.com/pagina"


def test_descoberta_forca_aba_visivel(monkeypatch):
    recebido = {}
    def falso(acao, **kwargs):
        recebido.update(kwargs)
        return {"tipo": "ok", "itens": []}
    monkeypatch.setattr(navegador, "enviar_comando_com_id", falso)
    navegador.descobrir_midias()
    assert recebido["bastidor"] is False


def test_mapeamento_formulario_global_para_frame(monkeypatch):
    chamadas = []
    respostas = iter([
        {"tipo": "ok", "formularios": [
            {"indice": 0, "indice_local": 1, "frame_id": 7},
        ]},
        {"tipo": "ok", "ok": True},
    ])
    monkeypatch.setattr(navegador, "enviar_comando_com_id",
                        lambda acao, **kwargs: (chamadas.append((acao, kwargs)), next(respostas))[1])
    navegador.ler_formularios()
    navegador.submeter_formulario(0)
    assert chamadas[1][1]["frame_id"] == 7
    assert chamadas[1][1]["indice"] == 1


class _YoutubeDLFalso:
    ultima_opcao = None

    def __init__(self, opcoes):
        type(self).ultima_opcao = opcoes

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, url, download=False):
        assert download is True
        hook = self.ultima_opcao["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100,
              "filename": "/tmp/video.webm", "speed": 10, "eta": 5})
        hook({"status": "finished", "filename": "/tmp/video.webm"})
        return {"title": "Vídeo teste", "id": "abc", "ext": "webm"}

    def prepare_filename(self, _info):
        return "/tmp/video.webm"


class _YoutubeDLFallbackFalso(_YoutubeDLFalso):
    chamadas = []

    def extract_info(self, url, download=False):
        type(self).chamadas.append(url)
        if len(type(self).chamadas) < 3:
            raise RuntimeError("URL temporária expirou")
        return super().extract_info(url, download)


def test_job_assincrono_sem_download_real(monkeypatch, tmp_path):
    monkeypatch.setattr(midia, "_validar_url", lambda u: u)
    monkeypatch.setattr(midia, "_downloads", lambda: tmp_path)
    monkeypatch.setattr(midia, "_navegador_cookies", lambda _="": None)
    monkeypatch.setattr(midia, "_importar_ytdlp", lambda: type("Y", (), {"YoutubeDL": _YoutubeDLFalso}))
    job = midia.iniciar_download("https://example.com/v", "video", "720p",
                                referer="https://example.com/pagina")
    limite = time.time() + 2
    atual = midia.status(job["id"])
    while atual["estado"] not in ("concluido", "erro") and time.time() < limite:
        time.sleep(0.01)
        atual = midia.status(job["id"])
    assert atual["estado"] == "concluido"
    assert atual["percentual"] == 100.0
    assert _YoutubeDLFalso.ultima_opcao["http_headers"]["Referer"].endswith("/pagina")
    assert _YoutubeDLFalso.ultima_opcao["http_headers"]["Origin"] == "https://example.com"
    assert "height<=720" in _YoutubeDLFalso.ultima_opcao["format"]


def test_job_tenta_player_iframe_antes_da_pagina_externa(monkeypatch, tmp_path):
    _YoutubeDLFallbackFalso.chamadas = []
    monkeypatch.setattr(midia, "_validar_url", lambda u: u)
    monkeypatch.setattr(midia, "_downloads", lambda: tmp_path)
    monkeypatch.setattr(midia, "_navegador_cookies", lambda _="": None)
    monkeypatch.setattr(
        midia, "_importar_ytdlp",
        lambda: type("Y", (), {"YoutubeDL": _YoutubeDLFallbackFalso}),
    )
    job = midia.iniciar_download(
        "https://cdn.example/master.m3u8?token=curto",
        "video",
        "melhor",
        referer="https://player.example/embed/episodio-1",
        pagina="https://anime.example/episodio-1",
    )
    limite = time.time() + 2
    atual = midia.status(job["id"])
    while atual["estado"] not in ("concluido", "erro") and time.time() < limite:
        time.sleep(0.01)
        atual = midia.status(job["id"])
    assert atual["estado"] == "concluido"
    assert _YoutubeDLFallbackFalso.chamadas == [
        "https://cdn.example/master.m3u8?token=curto",
        "https://player.example/embed/episodio-1",
        "https://anime.example/episodio-1",
    ]


def test_websocket_confirma_download_cloud_depois_de_importar(monkeypatch, tmp_path):
    import asyncio
    import json
    import emily_cloud.integration as integracao

    arquivo = tmp_path / "extensao.zip"
    arquivo.write_bytes(b"zip")
    recebidos = []
    monkeypatch.setattr(integracao, "guardar_download_evento", lambda *args: (
        recebidos.append(args) or {"ok": True, "item": {"id": "item-ack"}}))

    class WebSocketFalso:
        remote_address = ("127.0.0.1", 1234)

        def __init__(self):
            self.enviados = []
            self._mensagens = [json.dumps({
                "tipo": "download_concluido", "evento_id": "ext-1",
                "caminho": str(arquivo), "url": "https://a.invalid/x",
            })]

        def __aiter__(self):
            self._iter = iter(self._mensagens)
            return self

        async def __anext__(self):
            try:
                return next(self._iter)
            except StopIteration:
                raise StopAsyncIteration

        async def send(self, mensagem):
            self.enviados.append(json.loads(mensagem))

    ws = WebSocketFalso()
    asyncio.run(navegador._handler(ws))
    ack = next(m for m in ws.enviados if m.get("tipo") == "download_cloud_ack")
    assert ack == {
        "tipo": "download_cloud_ack", "evento_id": "ext-1", "ok": True,
        "erro": "", "item_id": "item-ack",
    }
    assert recebidos[0][0:3] == (str(arquivo), "ext-1", "https://a.invalid/x")


def test_ferramenta_encaminha_referer_do_iframe(monkeypatch, tmp_path):
    item = {
        "url": "https://cdn.example/master.m3u8",
        "referer": "https://player.example/embed/1",
    }
    recebido = {}
    monkeypatch.setattr(navegador, "_ultimo_catalogo_midias", [item])
    monkeypatch.setattr(navegador, "_metadados_catalogo_midias", {
        "url": "https://anime.example/episodio",
        "navegador": "Chromium",
    })
    monkeypatch.setattr(midia, "iniciar_download", lambda *args, **kwargs: (
        recebido.update(args=args, kwargs=kwargs) or {
            "id": "job1", "pasta": str(tmp_path), "formato": "video", "qualidade": "melhor",
        }
    ))
    resultado = ferramentas._baixar_midia_aba(1, "video", "melhor")
    assert resultado.ok is True
    assert recebido["kwargs"]["referer"] == "https://player.example/embed/1"
    assert recebido["kwargs"]["pagina"] == "https://anime.example/episodio"


def test_drm_recusado_antes_do_download(monkeypatch):
    monkeypatch.setattr(navegador, "_ultimo_catalogo_midias", [{
        "url": "https://example.com/protegido", "drm": True,
    }])
    resultado = ferramentas._baixar_midia_aba(1, "video", "1080p")
    assert isinstance(resultado, ferramentas.ResultadoFerramenta)
    assert resultado.ok is False
    assert "DRM" in resultado.texto


def test_javascript_encaminha_frame_explicito(monkeypatch):
    monkeypatch.setattr(ferramentas, "_exige_extensao", lambda: navegador)
    recebido = {}
    def falso(codigo, timeout=15.0, frame_id=None):
        recebido.update(codigo=codigo, frame_id=frame_id)
        return {"tipo": "ok", "resultado": "certo", "frame_id": frame_id}
    monkeypatch.setattr(navegador, "executar_js_com_id", falso)
    texto = ferramentas._executar_javascript_pagina("return 1", 7)
    assert recebido == {"codigo": "return 1", "frame_id": 7}
    assert "frame 7" in texto
