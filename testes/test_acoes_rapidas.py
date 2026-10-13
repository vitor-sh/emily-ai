"""Ações rápidas: atalhos literais e resposta direta sem segunda volta do modelo."""
from types import SimpleNamespace

import pytest

import comandos_rapidos as fast
import politica_agente
from ferramentas import ResultadoFerramenta


@pytest.mark.parametrize("texto,esperado", [
    ("luz azul", ("controlar_luz", {"acao": "cor", "cor": "azul"})),
    ("Emily, deixa a luz roxa", ("controlar_luz", {"acao": "cor", "cor": "roxo"})),
    ("muda a luz pra verde", ("controlar_luz", {"acao": "cor", "cor": "verde"})),
    ("luz quente", ("controlar_luz", {"acao": "cor", "cor": "quente"})),
    ("luz no 40", ("controlar_luz", {"acao": "brilho", "brilho": 40})),
    ("brilho da luz em 70%", ("controlar_luz", {"acao": "brilho", "brilho": 70})),
    ("liga o ventilador", ("controlar_tomada", {"acao": "ligar", "aparelho": "ventilador"})),
    ("desliga a air fryer", ("controlar_tomada", {"acao": "desligar", "aparelho": "air fryer"})),
    ("desliga a airfryer por favor", ("controlar_tomada", {"acao": "desligar", "aparelho": "air fryer"})),
])
def test_atalhos_novos(texto, esperado):
    assert fast.parse(texto) == esperado


@pytest.mark.parametrize("texto", [
    "liga o PC", "desliga o PC", "desliga a TV", "liga a tomada", "luz no 400", "luz no 0",
    "não liga o ventilador", "liga o ventilador depois", "liga o ventilador e a luz",
    "a luz azul é bonita?", "luz cor de burro", "desliga a música",
])
def test_atalhos_nao_pegam_pedidos_fora_da_lista(texto):
    assert fast.parse(texto) is None


def _e(nome, ok=True, texto="Feito.", **kw):
    return SimpleNamespace(nome=nome, resultado=ResultadoFerramenta(texto=texto, ok=ok), **kw)


def test_resposta_direta_para_uma_acao_rapida_que_deu_certo():
    assert politica_agente.resposta_direta([_e("controlar_luz", texto="Lâmpada ligada em azul.")]) == "Lâmpada ligada em azul."


@pytest.mark.parametrize("execucoes", [
    [_e("controlar_luz", ok=False, texto="A lâmpada não respondeu.")],     # falha: modelo explica
    [_e("controlar_luz"), _e("controlar_tomada")],                           # duas ações
    [_e("pesquisar_internet", texto="resultados...")],                       # não é ação rápida
    [_e("controlar_luz", repetida=True)],                                    # repetição barrada
    [_e("controlar_luz", texto="  ")],                                       # sem frase
    [],
])
def test_sem_resposta_direta_fora_do_caso_simples(execucoes):
    assert politica_agente.resposta_direta(execucoes) == ""


def test_escalonar_dominio_nao_conta_como_acao():
    assert politica_agente.resposta_direta(
        [_e("abrir_ferramentas", escalonou=True), _e("controlar_tomada", texto="Tomada ligada (ventilador).")]
    ) == "Tomada ligada (ventilador)."


def test_casa_entra_no_catalogo_rapido_da_voz():
    import orquestrador_voz as ov
    assert {"controlar_luz", "controlar_tomada", "casa_estado"} <= set(ov.nomes_ferramentas_rapidas())
