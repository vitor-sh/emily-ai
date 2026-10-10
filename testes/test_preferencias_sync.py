from __future__ import annotations

import time

import preferencias
import sincronizacao_desktop


def test_preferencia_mais_recente_vence_por_campo(monkeypatch, tmp_path):
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "preferencias.json")
    preferencias.recarregar()
    try:
        preferencias.definir(nome="No Fedora", avatar_usuario="data:image/png;base64,AA")
        local = preferencias.exportar_sync()
        novo = local["nome"]["quando"] + 1
        alterados = preferencias.mesclar_sync({
            "nome": {"valor": "No Windows", "quando": novo},
            "avatar_usuario": {"valor": "data:image/png;base64,BB",
                               "quando": local["avatar_usuario"]["quando"] - 1},
            "emily_code_projeto": {"valor": "C:\\outro", "quando": novo},
        })
        assert alterados == ["nome"]
        assert preferencias.obter("nome") == "No Windows"
        assert preferencias.obter("avatar_usuario").endswith("AA")
        assert "emily_code_projeto" not in preferencias.exportar_sync()
        preferencias.recarregar()
        assert preferencias.obter("nome") == "No Windows"
    finally:
        preferencias.recarregar()


def test_preferencias_escritas_por_outro_processo_recarregam(monkeypatch, tmp_path):
    caminho = tmp_path / "preferencias.json"
    monkeypatch.setattr(preferencias, "ARQUIVO", caminho)
    preferencias.recarregar()
    try:
        preferencias.definir(nome="Antes")
        assert preferencias.obter("nome") == "Antes"
        caminho.write_text('{"nome":"Depois"}', encoding="utf-8")
        assert preferencias.obter("nome") == "Depois"
    finally:
        preferencias.recarregar()


def test_sync_nao_publica_padroes_como_se_fossem_escolhas(monkeypatch, tmp_path):
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "preferencias.json")
    preferencias.recarregar()
    try:
        preferencias.mesclar_sync({"nome": {"valor": "Do Fedora", "quando": time.time()}})
        assert preferencias.exportar_sync().keys() == {"nome"}
        preferencias.definir(avatar_usuario="data:image/png;base64,AA")
        assert preferencias.exportar_sync().keys() == {"nome", "avatar_usuario"}
    finally:
        preferencias.recarregar()


def test_preferencias_viajam_nos_dois_sentidos_sem_ptt(monkeypatch, tmp_path):
    windows = tmp_path / "windows.json"
    fedora = tmp_path / "fedora.json"
    monkeypatch.setattr(sincronizacao_desktop, "_config",
                        lambda: ("https://gateway.exemplo", "token"))

    def escolher(caminho):
        monkeypatch.setattr(preferencias, "ARQUIVO", caminho)
        preferencias.recarregar()

    def pedido(_sessao, metodo, url, _token, **kw):
        assert url.endswith("/preferencias/sync")
        escolher(fedora)
        try:
            if metodo == "POST":
                preferencias.mesclar_sync(kw["json"]["campos"])
            return {"ok": True, "campos": preferencias.exportar_sync()}
        finally:
            escolher(windows)

    monkeypatch.setattr(sincronizacao_desktop, "_pedido", pedido)
    try:
        escolher(fedora)
        preferencias.definir(nome="Fedora", volume_voz=0.5)
        escolher(windows)
        preferencias.definir(nome="Windows", tecla_ptt="f9")
        assert sincronizacao_desktop.sincronizar_preferencias_uma_vez(object())
        escolher(fedora)
        assert preferencias.obter("nome") == "Windows"
        escolher(windows)
        assert preferencias.obter("volume_voz") == 0.5
        assert preferencias.obter("tecla_ptt") == "f9"
        escolher(fedora)
        preferencias.definir(nome="Fedora recente")
        escolher(windows)
        assert sincronizacao_desktop.sincronizar_preferencias_uma_vez(object())
        assert preferencias.obter("nome") == "Fedora recente"
        assert preferencias.obter("tecla_ptt") == "f9"
        assert "tecla_ptt" not in preferencias.exportar_sync()
    finally:
        preferencias.recarregar()
