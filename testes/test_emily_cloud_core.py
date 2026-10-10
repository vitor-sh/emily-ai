"""Núcleo local da Emily Cloud: sem rede e isolado do acervo real."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


RAIZ = str(Path(__file__).resolve().parents[1])


@pytest.fixture()
def cloud(monkeypatch, tmp_path):
    monkeypatch.setenv("EMILY_CLOUD_DIR", str(tmp_path / "cloud"))
    monkeypatch.setenv("EMILY_CLOUD_LOCATION_FILE", str(tmp_path / "config" / "cloud-location.json"))
    for nome in list(sys.modules):
        if nome == "emily_cloud" or nome.startswith("emily_cloud."):
            del sys.modules[nome]
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    importlib.invalidate_caches()
    modulo = importlib.import_module("emily_cloud")
    yield modulo


def test_importa_deduplica_e_preserva_original(cloud, tmp_path):
    fonte = tmp_path / "foto.txt"
    fonte.write_text("mesmos bytes", encoding="utf-8")
    primeiro = cloud.importar(str(fonte))
    segundo = cloud.importar(str(fonte))

    assert primeiro["hash"] == segundo["hash"]
    assert primeiro["nome"] == "foto.txt"
    assert segundo["nome"] == "foto (2).txt"
    assert fonte.read_text(encoding="utf-8") == "mesmos bytes"
    estado = cloud.status()
    assert estado["arquivos"] == 2
    assert estado["bytes_logicos"] == 2 * estado["bytes_fisicos"]
    assert estado["deduplicado"] == estado["bytes_fisicos"]


def test_pastas_movimento_ciclo_e_busca(cloud, tmp_path):
    origem = tmp_path / "pack"
    origem.mkdir()
    (origem / "mods").mkdir()
    (origem / "mods" / "bonito.jar").write_bytes(b"jar")
    pasta = cloud.importar(str(origem))
    mods = cloud.listar(pasta["id"])[0]
    arquivo = cloud.buscar("bonito")[0]

    assert mods["tipo"] == "pasta"
    assert arquivo["parent_id"] == mods["id"]
    with pytest.raises(ValueError, match="dentro dela mesma"):
        cloud.mover(pasta["id"], mods["id"])


def test_lixeira_restaura_e_exclui_objeto_sem_quebrar_duplicata(cloud, tmp_path):
    fonte = tmp_path / "igual.bin"
    fonte.write_bytes(b"123456")
    a = cloud.importar(str(fonte))
    b = cloud.importar(str(fonte))
    objeto = cloud.caminho_conteudo(a["id"])

    cloud.mover_para_lixeira(a["id"])
    assert cloud.listar(filtro="lixeira")[0]["id"] == a["id"]
    cloud.restaurar(a["id"])
    assert cloud.detalhes(a["id"])["apagado_em"] is None

    cloud.mover_para_lixeira(a["id"])
    assert cloud.excluir_definitivamente(a["id"])
    assert objeto.exists()  # b ainda referencia os mesmos bytes
    cloud.mover_para_lixeira(b["id"])
    cloud.excluir_definitivamente(b["id"])
    assert not objeto.exists()


def test_exclusao_definitiva_de_pasta_remove_arvore(cloud, tmp_path):
    origem = tmp_path / "arvore"
    (origem / "sub").mkdir(parents=True)
    (origem / "sub" / "folha.txt").write_text("folha", encoding="utf-8")
    pasta = cloud.importar(str(origem))
    objeto = cloud.caminho_conteudo(cloud.buscar("folha")[0]["id"])
    cloud.mover_para_lixeira(pasta["id"])

    assert cloud.excluir_definitivamente(pasta["id"])
    assert cloud.buscar("folha") == []
    assert not objeto.exists()


def test_exporta_arquivo_e_arvore(cloud, tmp_path):
    origem = tmp_path / "docs"
    origem.mkdir()
    (origem / "leia.txt").write_text("olá", encoding="utf-8")
    pasta = cloud.importar(str(origem))
    destino = tmp_path / "saida"

    resultado = cloud.exportar(pasta["id"], str(destino))
    assert resultado["itens"] == 1
    assert (destino / "docs" / "leia.txt").read_text(encoding="utf-8") == "olá"


def test_recusa_link_simbolico(cloud, tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    link = tmp_path / "atalho.txt"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("sistema sem suporte/permissão para symlink")
    with pytest.raises(ValueError, match="simbólico"):
        cloud.importar(str(link))


def test_migra_acervo_com_integridade_e_reconfigura_processo(cloud, tmp_path, monkeypatch):
    fonte = tmp_path / "migrar.txt"
    fonte.write_text("conteúdo preservado", encoding="utf-8")
    item = cloud.importar(str(fonte))
    origem = cloud.core.BASE
    destino = tmp_path / "outro-disco" / "Emily Cloud"

    monkeypatch.delenv("EMILY_CLOUD_DIR", raising=False)
    cloud.location.salvar(origem)
    resultado = cloud.storage.migrar(str(destino))

    assert resultado["ok"] is True
    assert cloud.core.BASE == destino.absolute()
    assert cloud.location.pasta_ativa() == destino.absolute()
    assert cloud.caminho_conteudo(item["id"]).read_text(encoding="utf-8") == "conteúdo preservado"
    assert not origem.exists()


def test_migracao_falha_sem_perder_origem(cloud, tmp_path, monkeypatch):
    fonte = tmp_path / "rollback.txt"
    fonte.write_text("fica aqui", encoding="utf-8")
    item = cloud.importar(str(fonte))
    origem = cloud.core.BASE
    destino = tmp_path / "destino-com-falha"
    monkeypatch.delenv("EMILY_CLOUD_DIR", raising=False)
    cloud.location.salvar(origem)
    monkeypatch.setattr(cloud.storage, "_validar_objetos",
                        lambda _: (_ for _ in ()).throw(RuntimeError("falha simulada")))

    with pytest.raises(RuntimeError, match="falha simulada"):
        cloud.storage.migrar(str(destino))
    assert cloud.core.BASE == origem
    assert cloud.location.disponivel(origem)
    assert cloud.caminho_conteudo(item["id"]).read_text(encoding="utf-8") == "fica aqui"
    assert not destino.exists()


def test_video_recebe_thumbnail_real_quando_ffmpeg_disponivel(cloud, tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg não instalado")
    video = tmp_path / "capa.mp4"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=0xC96442:s=320x180:d=2",
        "-pix_fmt", "yuv420p", str(video),
    ], check=True, timeout=30)
    item = cloud.importar(str(video))
    preview = cloud.caminho_preview(item["id"])
    assert preview is not None
    assert preview.suffix == ".webp"
    assert preview.stat().st_size > 0


def test_nao_recria_no_ssd_quando_armazenamento_configurado_some(cloud, tmp_path, monkeypatch):
    destino = tmp_path / "hd-removivel" / "Emily Cloud"
    destino.mkdir(parents=True)
    monkeypatch.delenv("EMILY_CLOUD_DIR", raising=False)
    cloud.location.salvar(destino)
    shutil.rmtree(destino.parent)
    anterior = cloud.core.BASE
    with pytest.raises(FileNotFoundError, match="não está disponível"):
        cloud.core.reconfigurar_base(destino, garantir=True)
    assert cloud.core.BASE == anterior
    assert not destino.exists()


def test_troca_para_novo_armazenamento_quando_anterior_esta_offline(cloud, tmp_path, monkeypatch):
    antigo = tmp_path / "hd-removivel" / "Emily Cloud"
    antigo.mkdir(parents=True)
    monkeypatch.delenv("EMILY_CLOUD_DIR", raising=False)
    cloud.location.salvar(antigo)
    cloud.core.reconfigurar_base(antigo, garantir=True)
    dados_antigos = cloud.location.dados_salvos()
    shutil.rmtree(antigo.parent)
    novo = tmp_path / "ssd-atual" / "Emily Cloud"

    plano = cloud.storage.planejar(str(novo))
    assert plano["modo"] == "novo"
    assert plano["origem_disponivel"] is False
    assert plano["bytes_migrar"] == 0

    with pytest.raises(FileNotFoundError, match="Escolha novamente"):
        cloud.storage.migrar(str(novo))
    assert cloud.location.dados_salvos() == dados_antigos
    assert not novo.exists()

    resultado = cloud.storage.migrar(str(novo), permitir_novo=True)
    assert resultado["ok"] is True
    assert resultado["modo"] == "novo"
    assert cloud.core.BASE == novo.absolute()
    assert cloud.location.pasta_ativa() == novo.absolute()
    assert cloud.status()["itens"] == 0
    assert not antigo.exists()