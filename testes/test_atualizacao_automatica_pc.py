"""A atualização automática reutiliza o atualizador manual apenas no primeiro boot."""

from pathlib import Path
from types import SimpleNamespace
import re

import atualizador_emily
import interface_web


RAIZ = Path(__file__).resolve().parent.parent


def _api():
    return interface_web.Api(SimpleNamespace())


def test_boot_so_oferece_atualizacao_no_pacote_com_origem_e_mudancas(monkeypatch):
    api = _api()
    estados = [
        {"em_pacote": False, "origem_ok": True, "quantos": 3},
        {"em_pacote": True, "origem_ok": False, "quantos": 3},
        {"em_pacote": True, "origem_ok": True, "quantos": 0},
        {"em_pacote": True, "origem_ok": True, "quantos": 3},
    ]
    for estado in estados:
        api._atualizacao_auto_consultada = False
        monkeypatch.setattr(api, "emily_atualizacao_estado", lambda e=estado: dict(e))
        assert api.emily_atualizacao_inicio()["verificar"] is (estado is estados[-1])
        assert api.emily_atualizacao_inicio() == {"verificar": False}


def test_aplicacao_automatica_usa_o_mesmo_preflight_backup_e_reinicio(monkeypatch):
    chamadas = []
    monkeypatch.setattr(atualizador_emily, "aplicar_atualizacao",
                        lambda: chamadas.append("aplicar") or "OK Atualização aplicada: 1 arquivo(s).")
    api = _api()
    assert api.emily_atualizar_aplicar().startswith("OK Atualização aplicada:")
    assert chamadas == ["aplicar"]


def test_nao_aplica_nem_desfaz_enquanto_outra_atualizacao_esta_em_andamento(monkeypatch):
    monkeypatch.setattr(atualizador_emily, "aplicar_atualizacao",
                        lambda: (_ for _ in ()).throw(AssertionError("aplicação concorrente")))
    monkeypatch.setattr(atualizador_emily, "desfazer_atualizacao",
                        lambda: (_ for _ in ()).throw(AssertionError("reversão concorrente")))
    api = _api()
    interface_web._trava_atualizacao.acquire()
    try:
        assert "Aguarde" in api.emily_atualizar_aplicar()
        assert "Aguarde" in api.emily_atualizar_desfazer()
    finally:
        interface_web._trava_atualizacao.release()


def test_falha_de_validacao_nao_agenda_reinicio_e_libera_a_trava(monkeypatch):
    chamadas = []
    def falhar():
        chamadas.append("falhou")
        raise RuntimeError("preflight indisponível")

    monkeypatch.setattr(atualizador_emily, "aplicar_atualizacao", falhar)
    api = _api()
    assert "preflight indisponível" in api.emily_atualizar_aplicar()
    assert "preflight indisponível" in api.emily_atualizar_aplicar()
    assert chamadas == ["falhou", "falhou"]


def test_tela_de_boot_e_cache_incluem_atualizacao_automatica():
    js = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
    css = (RAIZ / "web" / "estilo.css").read_text(encoding="utf-8")
    assert "checarAtualizacaoAoAbrir();" in js
    assert "emily_atualizacao_inicio" in js
    assert "emily_atualizar_aplicar', { teto: 240000 }" in js
    assert 'id="atualizacao-fundo"' in html
    assert re.search(r'app\.js\?v=[^"\s]+', html)
    assert re.search(r'estilo\.css\?v=[^"\s]+', html)
    assert "prefers-reduced-motion" in css
