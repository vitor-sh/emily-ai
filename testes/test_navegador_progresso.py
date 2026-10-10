"""Regressões: buscas por etapas e leitura após navegar para outra página."""

import sys
from pathlib import Path
import pytest

@pytest.fixture(autouse=True)
def revisao_isolada(monkeypatch):
    import politica_agente
    monkeypatch.setattr(politica_agente, "revisar_resposta", lambda p,t,m,r:
        {"continuar": "não carregou direito" in t, "texto": t})


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_busca_interna_com_todos_os_filtros_pede_pesquisa_por_etapas(monkeypatch):
    import ferramentas
    import navegador_interno

    abertos = []
    monkeypatch.setattr(navegador_interno, "abrir", lambda url: (
        abertos.append(url) or {"ok": True, "titulo": "Busca", "url": url}))
    longa = ("Resident Evil Shopping Estação Belo Horizonte sexta-feira "
             "2 de outubro 2026 ingresso preço")
    resultado = ferramentas._navegador_interno_abrir(longa)
    assert not resultado.ok
    assert "poucos termos" in resultado.texto
    assert abertos == []
    from urllib.parse import quote
    assert not ferramentas._navegador_interno_abrir(
        "https://www.bing.com/search?q=" + quote(longa)).ok
    assert abertos == []

    assert ferramentas._navegador_interno_abrir("Shopping Estação cinema").ok
    assert abertos == ["Shopping Estação cinema"]


def test_pedido_explicito_autoriza_abrir_navegador_interno(monkeypatch):
    import ferramentas
    import navegador_interno

    abertos = []
    monkeypatch.setattr(navegador_interno, "abrir", lambda endereco: (
        abertos.append(endereco) or {"ok": True, "titulo": "Busca", "url": endereco}))
    resultado = ferramentas.executar_estruturado(
        "navegador_interno_abrir", {"endereco": "Shopping Estação BH"},
        contexto={"pedido_explicito": True, "dono_confirmado": True,
                  "autonomia_experimental": False})
    assert resultado.ok
    assert abertos == ["Shopping Estação BH"]


def test_motor_permite_ler_nova_pagina_mas_barra_leitura_repetida(monkeypatch):
    import ferramentas
    import laco_ferramentas
    import llm

    def executar(nome, argumentos, contexto=None):
        return ferramentas.ResultadoFerramenta(
            texto=nome, ok=True, mudou=(nome == "navegador_interno_abrir"))

    monkeypatch.setattr(ferramentas, "executar_estruturado", executar)
    motor = laco_ferramentas.Motor(catalogo=[])

    def chamada(nome, numero, args="{}"):
        return llm.ChamadaFerramenta(id=str(numero), nome=nome, argumentos=args)

    assert not motor.executar([chamada("navegador_interno_ler", 1)])[0].repetida
    assert motor.executar([chamada("navegador_interno_ler", 2)])[0].repetida
    assert not motor.executar([chamada("navegador_interno_abrir", 3,
                                     '{"endereco":"https://example.com"}')])[0].repetida
    assert not motor.executar([chamada("navegador_interno_ler", 4)])[0].repetida


def test_motor_permite_esperar_e_rolar_novamente_apos_mudar_pagina(monkeypatch):
    import ferramentas
    import laco_ferramentas
    import llm

    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda *_a, **_kw:
                        ferramentas.ResultadoFerramenta("ok", ok=True, mudou=True))
    motor = laco_ferramentas.Motor(catalogo=[])

    def chamada(acao, numero):
        return llm.ChamadaFerramenta(
            str(numero), "navegador_interno_interagir",
            '{"acao":"' + acao + '","valor":"3","y":381}')

    assert not motor.executar([chamada("aguardar", 1)])[0].repetida
    assert not motor.executar([chamada("aguardar", 2)])[0].repetida
    assert not motor.executar([chamada("rolar", 3)])[0].repetida
    assert not motor.executar([chamada("rolar", 4)])[0].repetida


def test_resposta_parcial_nao_e_considerada_resultado_final():
    import modelo

    assert modelo._resposta_indica_tarefa_pendente(
        "Abri o site, só que ainda não consegui puxar a programação.")
    assert not modelo._resposta_indica_tarefa_pendente(
        "Conferi a programação e encontrei três sessões para sexta-feira.")


def test_clique_perto_do_limite_ganha_leitura_de_confirmacao(monkeypatch):
    import ferramentas
    import llm
    import modelo

    class Fluxo:
        def __init__(self, chamadas=(), texto=""):
            self.chamadas = list(chamadas)
            self._texto = texto
            self.preambulo = ""

        def quer_ferramenta(self):
            return bool(self.chamadas)

        def texto(self):
            return iter([self._texto])

    fluxos = iter([
        Fluxo([llm.ChamadaFerramenta("1", "navegador_interno_interagir",
                                     '{"acao":"clicar_texto","alvo":"02/10"}')]),
        Fluxo([llm.ChamadaFerramenta("2", "navegador_interno_ler", "{}")]),
        Fluxo(texto="Conferi a data de 02/10 e encontrei a sessão pedida."),
    ])
    chamadas = []
    monkeypatch.setattr(llm, "chamar_com_ferramentas", lambda *_a, **kw:
                        chamadas.append(kw) or next(fluxos))
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda *_a, **_kw:
                        ferramentas.ResultadoFerramenta("ok", ok=True, mudou=True))
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda *_a:
                        [{"role": "system", "content": "Teste"}])
    monkeypatch.setattr(modelo, "_emitir_fala", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "_resposta_deixa_objetivo_incompleto", lambda *_a: False)
    monkeypatch.setattr(modelo, "MAX_VOLTAS_FERRAMENTA", 2)
    anterior = list(modelo.historico)
    modelo.definir_historico([])
    try:
        resposta = modelo.conversar_com_ferramentas(
            "Use seu navegador para selecionar 02/10 e conferir a sessão", canal="web")
        assert resposta == "Conferi a data de 02/10 e encontrei a sessão pedida."
        assert len(chamadas) == 3
        assert not chamadas[1].get("proibir_ferramenta")
    finally:
        modelo.definir_historico(anterior)


@pytest.mark.parametrize("limite,pergunta", [(24, False), (2, True)])
def test_tarefa_nao_encerra_quando_modelo_admite_resultado_parcial(
        monkeypatch, limite, pergunta):
    import ferramentas
    import interface_web
    import llm
    import modelo

    class Fluxo:
        def __init__(self, chamadas=(), texto=""):
            self.chamadas = list(chamadas)
            self._texto = texto
            self.preambulo = ""

        def quer_ferramenta(self):
            return bool(self.chamadas)

        def texto(self):
            return iter([self._texto])

    respostas = iter([
        Fluxo([llm.ChamadaFerramenta("1", "navegador_interno_abrir",
                                     '{"endereco":"https://example.com"}')]),
        Fluxo(texto="Consegui entrar no cinema. O preço só aparece após abrir "
              "a sessão; essa última etapa não carregou direito."),
        Fluxo(texto="Conferi a página de ingressos: custa R$ 20 na sexta."),
    ])
    chamadas = []
    perguntas = []

    def chamar(mensagens, **_kw):
        chamadas.append(list(mensagens))
        return next(respostas)

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar)
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda *_a, **_kw:
                        ferramentas.ResultadoFerramenta("Site aberto", ok=True, mudou=True))
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda *_a: [
        {"role": "system", "content": "Teste"}])
    monkeypatch.setattr(modelo, "_emitir_fala", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_falar_aviso", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_registrar_memoria_unificada", lambda *_a, **_kw: None)
    monkeypatch.setattr(modelo, "_memoria_unificada_ativa", lambda: True)
    monkeypatch.setattr(modelo, "registrar_ferramenta_executada", lambda *_a: None)
    monkeypatch.setattr(modelo, "chamar_llm_simples", lambda prompt, **_kw:
                        "INCOMPLETO" if "não carregou direito" in prompt else "COMPLETO")
    monkeypatch.setattr(modelo, "MAX_VOLTAS_FERRAMENTA", limite)
    monkeypatch.setattr(interface_web, "perguntar_usuario_tarefa", lambda texto, tipo: (
        perguntas.append((texto, tipo)) or "Tente pelo site oficial"))
    anterior = list(modelo.historico)
    modelo.definir_historico([])
    try:
        resposta = modelo.conversar_com_ferramentas(
            "Abra o site e ache o preço do ingresso", canal="web")
        assert len(chamadas) == 3
        assert not perguntas  # O modelo pede esclarecimento pela ferramenta, sem pergunta automática.
        assert "Falta" in chamadas[2][-1]["content"] or "rascunho" in chamadas[2][-1]["content"]
        assert resposta == "Conferi a página de ingressos: custa R$ 20 na sexta."
    finally:
        modelo.definir_historico(anterior)
