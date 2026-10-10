"""Sincronização S3 simulada e integração dos downloads produzidos pela Emily."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


RAIZ = str(Path(__file__).resolve().parents[1])


@pytest.fixture()
def modulos(monkeypatch, tmp_path):
    monkeypatch.setenv("EMILY_CLOUD_DIR", str(tmp_path / "cloud-integracoes"))
    monkeypatch.setenv("EMILY_CLOUD_S3_ATIVO", "1")
    monkeypatch.setenv("EMILY_CLOUD_S3_BUCKET", "bucket-teste")
    monkeypatch.setenv("EMILY_CLOUD_S3_PREFIX", "acervo")
    for nome in list(sys.modules):
        if nome == "emily_cloud" or nome.startswith("emily_cloud."):
            del sys.modules[nome]
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    importlib.invalidate_caches()
    core = importlib.import_module("emily_cloud.core")
    integracao = importlib.import_module("emily_cloud.integration")
    return core, integracao


class S3Falso:
    def __init__(self):
        self.uploads = []
        self.copias = []
        self.excluidos = []

    def upload_file(self, caminho, bucket, chave, ExtraArgs):
        self.uploads.append((Path(caminho).read_bytes(), bucket, chave, ExtraArgs))

    def copy_object(self, **kwargs):
        self.copias.append(kwargs)

    def generate_presigned_url(self, operacao, Params, ExpiresIn):
        return f"https://s3.invalid/{Params['Key']}?expira={ExpiresIn}"

    def delete_object(self, **kwargs):
        self.excluidos.append(kwargs)


def test_sincroniza_compartilha_e_revoga_sem_rede(modulos, monkeypatch, tmp_path):
    core, _ = modulos
    fonte = tmp_path / "relatorio.txt"
    fonte.write_text("conteúdo privado", encoding="utf-8")
    item = core.importar(str(fonte))
    cliente = S3Falso()
    monkeypatch.setattr(core, "_s3", lambda: (cliente, core._config_s3()))

    sync = core.sincronizar(item["id"])
    assert sync["ok"] is True
    assert sync["item"]["estado_sync"] == "sincronizado"
    assert cliente.uploads[0][0] == b"conte\xc3\xbado privado"
    assert cliente.uploads[0][1] == "bucket-teste"
    assert cliente.uploads[0][2] == f"acervo/objects/{item['hash']}"
    assert cliente.uploads[0][3] == {"ContentType": "text/plain"}

    share = core.compartilhar(item["id"], 2)
    assert share["ok"] is True
    assert share["url"].startswith("https://s3.invalid/acervo/shares/")
    assert cliente.copias[0]["CopySource"]["Key"] == sync["item"]["remote_key"]
    assert core.listar_compartilhamentos(item["id"])[0]["id"] == share["id"]

    assert core.revogar_compartilhamento(share["id"])
    assert cliente.excluidos[0]["Key"].startswith("acervo/shares/")


def test_download_local_preserva_original_e_guarda_origem(modulos, monkeypatch, tmp_path):
    core, integracao = modulos
    monkeypatch.setenv("EMILY_CLOUD_DOWNLOADS_MODO", "local")
    fonte = tmp_path / "episodio.mp4"
    fonte.write_bytes(b"video")

    resultado = integracao.guardar_download(
        str(fonte), "https://video.invalid/episodio", "teste_download")
    assert resultado["ok"] is True
    item = core.detalhes(resultado["item"]["id"])
    assert item["origem"] == "teste_download"
    assert item["url_origem"] == "https://video.invalid/episodio"
    assert fonte.read_bytes() == b"video"


def test_download_pode_ser_desligado(modulos, monkeypatch, tmp_path):
    core, integracao = modulos
    monkeypatch.setenv("EMILY_CLOUD_GUARDAR_DOWNLOADS", "0")
    fonte = tmp_path / "nao-guardar.bin"
    fonte.write_bytes(b"x")
    resultado = integracao.guardar_download(str(fonte))
    assert resultado["ignorado"] is True
    assert core.listar() == []


def test_evento_de_download_reenviado_e_idempotente(modulos, monkeypatch, tmp_path):
    core, integracao = modulos
    monkeypatch.setenv("EMILY_CLOUD_DOWNLOADS_MODO", "local")
    fonte = tmp_path / "download-extensao.bin"
    fonte.write_bytes(b"uma vez")

    primeiro = integracao.guardar_download_evento(
        str(fonte), "ext-download-42", "https://arquivo.invalid/a")
    segundo = integracao.guardar_download_evento(
        str(fonte), "ext-download-42", "https://arquivo.invalid/a")

    assert primeiro["item"]["id"] == segundo["item"]["id"]
    assert len(core.listar()) == 1
    assert core.detalhes(primeiro["item"]["id"])["metadados"]["evento_id"] == "ext-download-42"


def test_lote_importa_unicos_continua_erro_e_sincroniza(modulos, monkeypatch, tmp_path):
    core, _ = modulos
    service = importlib.import_module("emily_cloud.service")
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    sincronizados = []

    def sincronizar(item_id):
        sincronizados.append(item_id)
        return {"ok": True, "item": core.detalhes(item_id)}

    monkeypatch.setattr(core, "sincronizar", sincronizar)
    resultado = service.importar_e_sincronizar(
        [str(a), str(a), str(tmp_path / "ausente"), str(b)], sincronizar=True)

    assert resultado["importados"] == 2
    assert resultado["sincronizados"] == 2
    assert resultado["parcial"] is True
    assert len(resultado["erros"]) == 1
    assert len({i["id"] for i in resultado["itens"]}) == 2
    assert sincronizados == [i["id"] for i in resultado["itens"]]


def test_resolve_saida_final_do_ytdlp_e_fallback_temporal(modulos, tmp_path):
    _, integracao = modulos
    mp3 = tmp_path / "música pronta.mp3"
    mp3.write_bytes(b"mp3")
    assert integracao.arquivo_final_ytdlp(
        f"logs\n{mp3}\n", tmp_path, 0, (".mp3",)) == mp3

    video = tmp_path / "vídeo pronto.mp4"
    video.write_bytes(b"mp4")
    assert integracao.arquivo_final_ytdlp(
        "sem caminho", tmp_path, video.stat().st_mtime, (".mp4",)) == video
    assert integracao.arquivo_final_ytdlp(
        "sem caminho", tmp_path, video.stat().st_mtime + 10, (".mp4",)) is None