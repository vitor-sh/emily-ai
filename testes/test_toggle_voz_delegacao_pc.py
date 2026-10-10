"""O toggle do PTT local não altera chat escrito nem Android."""

import ast
from pathlib import Path
from types import SimpleNamespace

import preferencias
from interface_web import Api


RAIZ = Path(__file__).resolve().parent.parent


def _funcoes_main(*nomes):
    arvore = ast.parse((RAIZ / "main.py").read_text(encoding="utf-8"))
    funcoes = [no for no in arvore.body
               if isinstance(no, ast.FunctionDef) and no.name in nomes]
    assert len(funcoes) == len(nomes)
    return compile(ast.fix_missing_locations(ast.Module(body=funcoes, type_ignores=[])),
                   "<main-ptt>", "exec")


def test_preferencia_persiste_e_pode_mudar_sem_reiniciar(tmp_path, monkeypatch):
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    try:
        api = Api.__new__(Api)
        assert preferencias.obter("voz_delegacao_rapida") is True
        assert api.estado_automacao()["voz_delegacao_rapida"] is True
        assert api.set_toggle("voz_delegacao_rapida", False) is True
        assert api.estado_automacao()["voz_delegacao_rapida"] is False
        preferencias.recarregar()
        assert preferencias.obter("voz_delegacao_rapida") is False
        assert api.set_toggle("voz_delegacao_rapida", True) is True
        preferencias.recarregar()
        assert preferencias.obter("voz_delegacao_rapida") is True
    finally:
        preferencias.recarregar()


def test_turno_ptt_escolhe_modelo_selecionado_com_todas_as_ferramentas():
    chamadas = []
    estado = {"rapido": True}
    ambiente = {
        "preferencias": SimpleNamespace(obter=lambda chave, padrao: estado["rapido"]),
        "_executar_turno_voz_rapido": lambda texto: chamadas.append(("rapido", texto)) or "Luna",
        "_executar_turno_com_ferramentas": lambda texto, canal: (
            chamadas.append(("completo", texto, canal)) or "Selecionado"),
    }
    exec(_funcoes_main("_voz_delegacao_rapida_ativa", "_executar_turno_voz_pc"), ambiente)
    turno = ambiente["_executar_turno_voz_pc"]
    assert turno("oi") == "Luna"
    estado["rapido"] = False
    assert turno("abre a página") == "Selecionado"
    estado["rapido"] = True
    assert turno("voltei") == "Luna"
    assert chamadas == [("rapido", "oi"), ("completo", "abre a página", "voz"),
                        ("rapido", "voltei")]


def test_monitor_de_delegacao_nao_fala_quando_toggle_desligado():
    livre = SimpleNamespace(is_set=lambda: False)
    estado = {"rapido": False}
    ambiente = {
        "_voz_delegacao_rapida_ativa": lambda: estado["rapido"],
        "emily_ocupada": livre,
        "voz": SimpleNamespace(falar_ativo=livre, escutando_ativo=livre),
    }
    exec(_funcoes_main("_pc_livre_para_aviso_delegacao"), ambiente)
    assert not ambiente["_pc_livre_para_aviso_delegacao"]()
    estado["rapido"] = True
    assert ambiente["_pc_livre_para_aviso_delegacao"]()


def test_toggle_so_aparece_nas_configuracoes_do_pc():
    js = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    assert "linhaChave('voz_delegacao_rapida'" in js
    assert "a.voz_delegacao_rapida ?? true" in js
    assert "voz_delegacao_rapida" not in (RAIZ / "EmilyAPP2" / "app" / "build.gradle.kts").read_text()