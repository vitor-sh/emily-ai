"""API HTTP da Cloud: autenticação, upload e streaming, sem rede real."""

from __future__ import annotations

import importlib
import io
import sys
import zipfile
from pathlib import Path

import pytest
from flask import Flask


RAIZ = str(Path(__file__).resolve().parents[1])


@pytest.fixture()
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("EMILY_CLOUD_DIR", str(tmp_path / "cloud-http"))
    monkeypatch.setenv("EMILY_PONTE_TOKEN", "segredo-de-teste")
    for nome in list(sys.modules):
        if nome == "emily_cloud" or nome.startswith("emily_cloud."):
            del sys.modules[nome]
    if RAIZ not in sys.path:
        sys.path.insert(0, RAIZ)
    importlib.invalidate_caches()
    rotas = importlib.import_module("emily_cloud.routes")
    app = Flask(__name__)
    rotas.registrar(app)
    app.testing = True
    return app.test_client(), {"Authorization": "Bearer segredo-de-teste"}


def test_cloud_exige_token(api):
    cliente, headers = api
    assert cliente.get("/cloud/status").status_code == 401
    assert cliente.get("/cloud/status", headers={"Authorization": "Bearer errado"}).status_code == 401
    resposta = cliente.get("/cloud/status", headers=headers)
    assert resposta.status_code == 200
    assert resposta.get_json()["ok"] is True


def test_cloud_remota_fica_desativada_sem_token(api, monkeypatch):
    cliente, _ = api
    monkeypatch.delenv("EMILY_PONTE_TOKEN", raising=False)
    resposta = cliente.get("/cloud/status")
    assert resposta.status_code == 503
    assert "desativada" in resposta.get_json()["erro"]


def test_upload_em_partes_listagem_e_range(api):
    cliente, headers = api
    conteudo = b"0123456789abcdefghijklmnopqrstuvwxyz"
    inicio = cliente.post("/cloud/uploads", headers=headers, json={
        "nome": "amostra.bin", "tamanho": len(conteudo),
    })
    assert inicio.status_code == 200
    upload_id = inicio.get_json()["upload_id"]
    for numero, parte in enumerate((conteudo[:13], conteudo[13:])):
        resposta = cliente.put(
            f"/cloud/uploads/{upload_id}/parts/{numero}",
            headers={**headers, "Content-Type": "application/octet-stream"}, data=parte,
        )
        assert resposta.status_code == 200
    fim = cliente.post(f"/cloud/uploads/{upload_id}/complete", headers=headers)
    assert fim.status_code == 200
    item = fim.get_json()["item"]

    lista = cliente.get("/cloud/items", headers=headers).get_json()
    assert [i["nome"] for i in lista["itens"]] == ["amostra.bin"]
    assert lista["itens"][0]["content_url"] == f"/cloud/content/{item['id']}"
    assert lista["itens"][0]["preview_url"] == ""

    completo = cliente.get(f"/cloud/content/{item['id']}", headers=headers)
    assert completo.status_code == 200
    assert completo.data == conteudo
    assert completo.headers["Accept-Ranges"] == "bytes"
    assert "filename*=UTF-8''amostra.bin" in completo.headers["Content-Disposition"]

    faixa = cliente.get(
        f"/cloud/content/{item['id']}", headers={**headers, "Range": "bytes=5-11"})
    assert faixa.status_code == 206
    assert faixa.data == conteudo[5:12]
    assert faixa.headers["Content-Range"] == f"bytes 5-11/{len(conteudo)}"

    sufixo = cliente.get(
        f"/cloud/content/{item['id']}", headers={**headers, "Range": "bytes=-4"})
    assert sufixo.status_code == 206
    assert sufixo.data == conteudo[-4:]

    invalida = cliente.get(
        f"/cloud/content/{item['id']}", headers={**headers, "Range": "bytes=100-200"})
    assert invalida.status_code == 416


def test_upload_recusa_tamanho_final_incorreto(api):
    cliente, headers = api
    inicio = cliente.post("/cloud/uploads", headers=headers,
                          json={"nome": "quebrado.txt", "tamanho": 20}).get_json()
    cliente.put(f"/cloud/uploads/{inicio['upload_id']}/parts/0", headers=headers, data=b"curto")
    fim = cliente.post(f"/cloud/uploads/{inicio['upload_id']}/complete", headers=headers)
    assert fim.status_code == 400
    assert fim.get_json()["ok"] is False


def test_upload_recusa_lacuna_entre_partes(api):
    cliente, headers = api
    inicio = cliente.post("/cloud/uploads", headers=headers,
                          json={"nome": "lacuna.bin", "tamanho": 6}).get_json()
    cliente.put(f"/cloud/uploads/{inicio['upload_id']}/parts/1",
                headers=headers, data=b"abcdef")
    fim = cliente.post(f"/cloud/uploads/{inicio['upload_id']}/complete", headers=headers)
    assert fim.status_code == 400
    assert "partes ausentes" in fim.get_json()["erro"]


def test_upload_aceita_arquivo_vazio(api):
    cliente, headers = api
    inicio = cliente.post("/cloud/uploads", headers=headers,
                          json={"nome": "vazio.txt", "tamanho": 0}).get_json()
    fim = cliente.post(f"/cloud/uploads/{inicio['upload_id']}/complete", headers=headers)
    assert fim.status_code == 200
    item_id = fim.get_json()["item"]["id"]
    assert cliente.get(f"/cloud/content/{item_id}", headers=headers).data == b""


def test_rotas_mobile_crud_texto_exportacao_e_importacao_por_caminho(api, tmp_path):
    cliente, headers = api
    pasta = cliente.post("/cloud/folders", headers=headers, json={"nome": "Celular"})
    assert pasta.status_code == 200
    pasta_id = pasta.get_json()["item"]["id"]

    fonte = tmp_path / "nota do pc.txt"
    fonte.write_text("conteúdo compartilhado entre PC e celular", encoding="utf-8")
    importado = cliente.post("/cloud/import-paths", headers=headers, json={
        "caminhos": [str(fonte)], "parent_id": pasta_id,
    })
    assert importado.status_code == 200
    item = importado.get_json()["itens"][0]
    item_id = item["id"]

    texto = cliente.get(f"/cloud/items/{item_id}/texto?limite=200", headers=headers)
    assert texto.status_code == 200
    assert texto.get_json()["texto"] == "conteúdo compartilhado entre PC e celular"

    editado = cliente.patch(f"/cloud/items/{item_id}", headers=headers, json={
        "nome": "renomeada.txt", "favorito": True, "parent_id": None,
    })
    assert editado.status_code == 200
    assert editado.get_json()["item"]["nome"] == "renomeada.txt"
    assert editado.get_json()["item"]["favorito"] is True
    assert editado.get_json()["item"]["parent_id"] is None

    destino = tmp_path / "exportado"
    exportado = cliente.post(f"/cloud/items/{item_id}/exportar", headers=headers,
                             json={"destino": str(destino)})
    assert exportado.status_code == 200
    assert (destino / "renomeada.txt").read_text(encoding="utf-8") == texto.get_json()["texto"]

    assert cliente.delete(f"/cloud/items/{item_id}", headers=headers).status_code == 200
    assert cliente.post(f"/cloud/items/{item_id}/restaurar", headers=headers).status_code == 200
    assert cliente.delete(f"/cloud/items/{item_id}", headers=headers).status_code == 200
    definitivo = cliente.delete(f"/cloud/items/{item_id}?permanente=1", headers=headers)
    assert definitivo.status_code == 200
    assert definitivo.get_json()["permanente"] is True


def test_rotas_de_links_usam_o_mesmo_catalogo_de_compartilhamentos(api, monkeypatch):
    cliente, headers = api
    rotas = importlib.import_module("emily_cloud.routes")
    agora = 2_000_000_000.0
    monkeypatch.setattr(rotas.time, "time", lambda: agora)
    monkeypatch.setattr(rotas.core, "listar_compartilhamentos", lambda item_id="": [{
        "id": "share_teste", "item_id": item_id or "arquivo_1", "nome": "foto.jpg",
        "url": "https://exemplo.invalid/foto", "expira_em": agora + 60,
        "revogado_em": None,
    }])
    revogados = []
    monkeypatch.setattr(rotas.core, "revogar_compartilhamento",
                        lambda share_id: revogados.append(share_id) or True)

    lista = cliente.get("/cloud/shares?item_id=arquivo_1", headers=headers)
    assert lista.status_code == 200
    assert lista.get_json()["links"][0]["ativo"] is True
    assert cliente.delete("/cloud/shares/share_teste", headers=headers).status_code == 200
    assert revogados == ["share_teste"]


def _upload_bytes(cliente, headers, nome, conteudo):
    inicio = cliente.post("/cloud/uploads", headers=headers,
                          json={"nome": nome, "tamanho": len(conteudo)}).get_json()
    if conteudo:
        assert cliente.put(f"/cloud/uploads/{inicio['upload_id']}/parts/0",
                           headers={**headers, "Content-Type": "application/octet-stream"},
                           data=conteudo).status_code == 200
    fim = cliente.post(f"/cloud/uploads/{inicio['upload_id']}/complete", headers=headers)
    assert fim.status_code == 200
    return fim.get_json()["item"]


def test_viewer_assinado_streama_sem_expor_token(api):
    cliente, headers = api
    item = _upload_bytes(cliente, headers, "filme.mp4", b"0123456789")
    viewer = cliente.get(f"/cloud/items/{item['id']}/viewer", headers=headers)
    assert viewer.status_code == 200
    caminho = viewer.get_json()["caminho"]
    resposta = cliente.get(caminho, headers={"Range": "bytes=2-5"})
    assert resposta.status_code == 206
    assert resposta.data == b"2345"


def test_zip_lista_e_extrai_selecao_para_mesmo_catalogo(api):
    cliente, headers = api
    bruto = io.BytesIO()
    with zipfile.ZipFile(bruto, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("docs/leia.txt", "olá do zip")
        z.writestr("docs/ignorar.txt", "não extrair")
        z.writestr("foto.bin", b"foto")
    item = _upload_bytes(cliente, headers, "pacote.zip", bruto.getvalue())

    lista = cliente.get(f"/cloud/items/{item['id']}/archive", headers=headers)
    assert lista.status_code == 200
    assert {e["caminho"] for e in lista.get_json()["entradas"]} == {
        "docs/leia.txt", "docs/ignorar.txt", "foto.bin"}

    extracao = cliente.post(f"/cloud/items/{item['id']}/extract", headers=headers,
                            json={"entradas": ["docs/leia.txt"]})
    assert extracao.status_code == 200
    pasta_id = extracao.get_json()["item"]["id"]
    filhos = cliente.get(f"/cloud/items?parent={pasta_id}", headers=headers).get_json()["itens"]
    assert [f["nome"] for f in filhos] == ["docs"]
    netos = cliente.get(f"/cloud/items?parent={filhos[0]['id']}", headers=headers).get_json()["itens"]
    assert [n["nome"] for n in netos] == ["leia.txt"]


def test_zip_recusa_path_traversal(api):
    cliente, headers = api
    bruto = io.BytesIO()
    with zipfile.ZipFile(bruto, "w") as z:
        z.writestr("../fora.txt", "perigo")
    item = _upload_bytes(cliente, headers, "malicioso.zip", bruto.getvalue())
    resposta = cliente.get(f"/cloud/items/{item['id']}/archive", headers=headers)
    assert resposta.status_code == 400
    assert "inseguro" in resposta.get_json()["erro"]


def test_assinatura_viewer_nao_habilita_cloud_sem_token(api, monkeypatch):
    cliente, headers = api
    item = _upload_bytes(cliente, headers, "privado.txt", b"segredo")
    viewer = cliente.get(f"/cloud/items/{item['id']}/viewer", headers=headers).get_json()
    monkeypatch.delenv("EMILY_PONTE_TOKEN", raising=False)
    assert cliente.get(viewer["caminho"]).status_code == 503


def test_rotas_pausam_enquanto_armazenamento_esta_migrando(api, monkeypatch):
    cliente, headers = api
    rotas = importlib.import_module("emily_cloud.routes")
    monkeypatch.setattr(rotas.location, "migracao_ativa", lambda: True)
    resposta = cliente.get("/cloud/status", headers=headers)
    assert resposta.status_code == 503
    assert resposta.headers["Retry-After"] == "5"