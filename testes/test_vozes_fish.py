"""Catálogo de vozes do Fish: escolha, padrões e paridade PC/Android."""
import re
from pathlib import Path

import pytest

import preferencias
import vozes_fish

RAIZ = Path(__file__).resolve().parents[1]
ANDROID = RAIZ / "EmilyAPP2/app/src/main/java/com/example/emilyapp/VozesFish.kt"
PADRAO = "28d1575c848841de930786be8d1ca40d"


@pytest.fixture
def prefs(tmp_path, monkeypatch):
    """Preferências isoladas: nada do usuário é lido nem gravado."""
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    monkeypatch.setattr(preferencias, "_cache", None)
    monkeypatch.setattr(preferencias, "_cache_id", None)
    monkeypatch.setattr(preferencias, "_arquivo_revisoes", lambda: tmp_path / "rev.json")
    return preferencias


def test_sem_escolha_vale_a_voz_do_ambiente(prefs):
    assert vozes_fish.id_atual(PADRAO) == PADRAO
    assert vozes_fish.chave_atual(PADRAO) == "emily"
    # Um FISH_VOICE_ID que não está no catálogo continua sendo respeitado.
    assert vozes_fish.id_atual("abc") == "abc"


@pytest.mark.parametrize("chave,voz_id", [("emily", PADRAO),
                                          ("voz1", "24522123b5804bf691a8450d9187f03e"),
                                          ("voz2", "ba6bc3c80bc3400895f77f8f18b21a2c")])
def test_escolha_vale_na_proxima_fala(prefs, chave, voz_id):
    assert vozes_fish.definir(chave) is True
    assert vozes_fish.id_atual("qualquer") == voz_id
    assert vozes_fish.chave_atual() == chave


def test_chave_invalida_nao_grava_nada(prefs):
    assert vozes_fish.definir("voz9") is False
    assert vozes_fish.definir("") is False
    assert vozes_fish.id_atual(PADRAO) == PADRAO


def test_preferencia_corrompida_cai_no_padrao(prefs):
    prefs.definir(voz_fish="lixo")
    assert vozes_fish.id_atual(PADRAO) == PADRAO


def test_voz_fish_sincroniza_entre_pcs(prefs):
    assert "voz_fish" in prefs.SINCRONIZAVEIS


def test_requisicao_do_fish_usa_a_voz_escolhida(prefs, monkeypatch):
    import ast
    ns = {"os": __import__("os"), "FISH_VOICE_ID": PADRAO}
    arvore = ast.parse((RAIZ / "voz.py").read_text())
    corpo = [n for n in arvore.body if isinstance(n, ast.FunctionDef) and n.name == "_voz_fish_atual"]
    exec(compile(ast.Module(body=corpo, type_ignores=[]), "voz.py", "exec"), ns)
    assert ns["_voz_fish_atual"]() == PADRAO
    vozes_fish.definir("voz2")
    assert ns["_voz_fish_atual"]() == "ba6bc3c80bc3400895f77f8f18b21a2c"


def test_ids_do_catalogo_sao_ids_do_fish():
    for v in vozes_fish.catalogo():
        assert re.fullmatch(r"[0-9a-f]{32}", v["id"]), v
    assert len({v["chave"] for v in vozes_fish.catalogo()}) == len(vozes_fish.VOZES)


def test_catalogo_do_android_e_igual_ao_do_pc():
    if not ANDROID.exists():
        pytest.skip("app Android fora da árvore")
    texto = ANDROID.read_text()
    android = re.findall(r'Voz\("([a-z0-9]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([0-9a-f]{32})"\)', texto)
    assert android == [(c, n, d, i) for c, n, d, i in vozes_fish.VOZES]
    # A mesma chave de preferência nos dois lados.
    assert 'KEY = "voz_fish"' in texto
