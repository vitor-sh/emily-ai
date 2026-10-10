"""Regressões da autonomia experimental e do portão mecânico de segurança."""

from __future__ import annotations

import sys
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _ctx(*, pedido=False, autonomia=True, dono=True):
    return {
        "pedido_explicito": pedido,
        "autonomia_experimental": autonomia,
        "dono_confirmado": dono,
    }


def test_preferencia_e_toggle_aparecem_nas_duas_interfaces():
    import preferencias

    assert preferencias._PADROES["autonomia_experimental"] is False
    web = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    backend = (RAIZ / "interface_web.py").read_text(encoding="utf-8")
    qt = (RAIZ / "interface.py").read_text(encoding="utf-8")
    assert "Autonomia experimental" in web
    assert 'qual == "autonomia_experimental"' in backend
    assert "_toggle_autonomia_experimental" in qt


def test_toggle_web_persiste_sem_reiniciar(monkeypatch, tmp_path):
    import interface_web
    import preferencias

    arquivo_real = preferencias.ARQUIVO
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs.json")
    preferencias.recarregar()
    api = object.__new__(interface_web.Api)

    try:
        assert api.set_toggle("autonomia_experimental", True) is True
        preferencias.recarregar()
        assert preferencias.obter("autonomia_experimental", False) is True
        assert api.estado_automacao()["autonomia_experimental"] is True
        assert api.set_toggle("autonomia_experimental", False) is True
        preferencias.recarregar()
        assert preferencias.obter("autonomia_experimental", True) is False
    finally:
        preferencias.ARQUIVO = arquivo_real
        preferencias.recarregar()


def test_sem_pedido_so_allowlist_de_baixo_impacto_passa():
    import ferramentas

    original = ferramentas.CATALOGO["abrir_app"]
    chamadas = []
    ferramentas.CATALOGO["abrir_app"] = ferramentas.Ferramenta(
        nome="abrir_app", descricao="teste", propriedades={}, obrigatorios=[],
        executar=lambda: chamadas.append("abriu") or "abriu",
    )
    try:
        permitido = ferramentas.executar_estruturado(
            "abrir_app", {}, contexto=_ctx())
        bloqueado = ferramentas.executar_estruturado(
            "abrir_app", {}, contexto=_ctx(autonomia=False))
    finally:
        ferramentas.CATALOGO["abrir_app"] = original
        ferramentas._historico_iniciativas.clear()

    assert permitido.ok is True
    assert bloqueado.erro == "iniciativa_nao_autorizada"
    assert chamadas == ["abriu"]


def test_destrutiva_nunca_nasce_de_inferencia():
    import ferramentas

    original = ferramentas.CATALOGO["deletar_arquivo"]
    chamadas = []
    ferramentas.CATALOGO["deletar_arquivo"] = ferramentas.Ferramenta(
        nome="deletar_arquivo", descricao="teste", propriedades={},
        obrigatorios=[], destrutiva=True,
        executar=lambda: chamadas.append("apagou") or "apagou",
    )
    try:
        resultado = ferramentas.executar_estruturado(
            "deletar_arquivo", {}, contexto=_ctx())
    finally:
        ferramentas.CATALOGO["deletar_arquivo"] = original

    assert resultado.erro == "iniciativa_nao_autorizada"
    assert chamadas == []


def test_terminal_confirmavel_recebe_autorizacao_direta_do_dono(monkeypatch):
    import ferramentas
    import terminal

    recebido = {}

    def executar(comando, confirmado=False, entrada="", autorizacao_direta=False):
        recebido.update(comando=comando, confirmado=confirmado,
                        autorizacao_direta=autorizacao_direta)
        return "feito", True

    monkeypatch.setattr(terminal, "executar", executar)
    resultado = ferramentas.executar_estruturado(
        "executar_terminal", {"comando": "dnf install pacote"},
        contexto=_ctx(pedido=True))

    assert resultado.ok is True
    assert recebido["autorizacao_direta"] is True


def test_terminal_bloqueado_continua_bloqueado_com_autorizacao_direta():
    import terminal

    texto, ok = terminal.executar(
        "sudo mkfs.ext4 /dev/sda1", autorizacao_direta=True)
    assert ok is False
    assert "bloqueado" in texto.lower()


def test_desligamento_exige_autorizacao_da_acao(monkeypatch):
    import terminal

    chamadas = []
    monkeypatch.setattr(
        terminal, "_rodar_shell",
        lambda comando, entrada="": chamadas.append(comando) or ("ok", True),
    )
    terminal.descartar_pendente()
    texto, ok = terminal.executar("shutdown -h +30")
    assert ok is False and "confirm" in texto.lower()
    assert chamadas == []
    assert terminal.executar("shutdown -h +30", confirmado=True) == ("ok", True)
    assert chamadas == ["shutdown -h +30"]


def test_terminal_confirmavel_pula_so_o_vaivem_com_autorizacao_direta(monkeypatch):
    import terminal

    rodou = []
    monkeypatch.setattr(
        terminal, "_rodar_shell",
        lambda comando, entrada="": rodou.append((comando, entrada)) or ("ok", True),
    )
    texto, ok = terminal.executar(
        "dnf install pacote", autorizacao_direta=True)
    assert (texto, ok) == ("ok", True)
    assert rodou == [("dnf install pacote", "")]


def test_desfazer_prioriza_ultima_iniciativa_simples(monkeypatch):
    import ferramentas

    ferramentas._historico_iniciativas.clear()
    inversas = []
    monkeypatch.setattr(
        ferramentas, "_automacao",
        lambda acao, **campos: inversas.append((acao, campos)) or "fechado",
    )
    ferramentas._registrar_iniciativa_desfazivel(
        "abrir_app", {"nome": "Brave"})

    resposta = ferramentas._desfazer()

    assert inversas == [("fechar_app", {"alvo": "Brave"})]
    assert "abertura de 'Brave'" in resposta


def test_site_espontaneo_pode_ser_desfeito_fechando_a_aba(monkeypatch):
    import ferramentas

    ferramentas._historico_iniciativas.clear()
    inversas = []
    monkeypatch.setattr(
        ferramentas, "_automacao",
        lambda acao, **campos: inversas.append((acao, campos)) or "fechada",
    )
    ferramentas._registrar_iniciativa_desfazivel(
        "abrir_site", {"site": "youtube.com"})
    resposta = ferramentas._desfazer()
    assert inversas == [("fechar_aba", {})]
    assert "aba aberta" in resposta


def test_acao_simples_explicita_tambem_fica_desfazivel(monkeypatch):
    import ferramentas

    original = ferramentas.CATALOGO["abrir_app"]
    ferramentas._historico_iniciativas.clear()
    inversas = []
    monkeypatch.setattr(
        ferramentas, "_automacao",
        lambda acao, **campos: inversas.append((acao, campos)) or "fechado",
    )
    ferramentas.CATALOGO["abrir_app"] = ferramentas.Ferramenta(
        nome="abrir_app", descricao="teste", propriedades={
            "nome": {"type": "string"}}, obrigatorios=["nome"],
        executar=lambda nome: f"abriu {nome}",
    )
    try:
        resultado = ferramentas.executar_estruturado(
            "abrir_app", {"nome": "Brave"}, contexto=_ctx(pedido=True))
        resposta = ferramentas._desfazer()
    finally:
        ferramentas.CATALOGO["abrir_app"] = original
        ferramentas._historico_iniciativas.clear()

    assert resultado.ok and resultado.mudou
    assert inversas == [("fechar_app", {"alvo": "Brave"})]
    assert "abertura de 'Brave'" in resposta


def test_dono_no_discord_pula_confirmacao_so_com_autonomia_direta():
    import discord_admin

    discord_admin.definir_sessao(
        nivel=discord_admin.NIVEL_DONO, autor_id=1, autor_nome="Vitor",
        guild_id=2, canal_id=3, origem="discord", autonomia_direta=True)
    try:
        assert discord_admin._confirmar_ou_executar(
            "apagar teste", lambda: "executou") == "executou"
    finally:
        discord_admin.limpar_sessao()


def test_terceiro_e_dono_sem_toggle_continuam_confirmando():
    import discord_admin

    for nivel, direta in (
        (discord_admin.NIVEL_TOTAL, True),
        (discord_admin.NIVEL_DONO, False),
    ):
        executou = []
        discord_admin.definir_sessao(
            nivel=nivel, autor_id=9, autor_nome="Pessoa", guild_id=2,
            canal_id=3, origem="discord", autonomia_direta=direta)
        try:
            resposta = discord_admin._confirmar_ou_executar(
                "apagar teste", lambda: executou.append(True) or "executou")
        finally:
            discord_admin.cancelar_pendente(3, 9)
            discord_admin.limpar_sessao()
        assert "precisa de confirmação" in resposta
        assert executou == []


def test_mutacao_explicita_invalida_undo_de_iniciativa_antiga():
    import ferramentas

    original = ferramentas.CATALOGO.get("t_mutacao_explicita")
    ferramentas._historico_iniciativas.clear()
    ferramentas._registrar_iniciativa_desfazivel(
        "abrir_app", {"nome": "Brave"})
    ferramentas.CATALOGO["t_mutacao_explicita"] = ferramentas.Ferramenta(
        nome="t_mutacao_explicita", descricao="teste", propriedades={},
        obrigatorios=[], executar=lambda: "mudou",
    )
    try:
        resultado = ferramentas.executar_estruturado(
            "t_mutacao_explicita", {}, contexto=_ctx(pedido=True))
    finally:
        if original is None:
            ferramentas.CATALOGO.pop("t_mutacao_explicita", None)
        else:
            ferramentas.CATALOGO["t_mutacao_explicita"] = original

    assert resultado.ok and resultado.mudou
    assert ferramentas._historico_iniciativas == []


def test_prompt_experimental_distingue_iniciativa_de_destrutiva(monkeypatch):
    import modelo

    monkeypatch.setattr(modelo, "autonomia_experimental_ativa", lambda: True)
    bloco = modelo._bloco_autonomia_experimental()
    assert "iniciativa prática de baixo impacto" in bloco
    assert "exigem um pedido explícito" in bloco
    assert "sem pedir uma segunda confirmação" in bloco


def test_desfazer_e_detectado_como_pedido_explicito():
    import modelo

    assert modelo._parece_pedido_de_acao("desfaz isso") is True
    assert modelo._parece_pedido_de_acao("reverte a última ação") is True
