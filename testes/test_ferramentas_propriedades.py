"""
Properties 8 e 9 do design — tool calling no formato OpenAI.

Os testes de testes_manuais/_teste_fluxo.py e _teste_laco.py cobrem cenários ESCOLHIDOS. Aqui
o hypothesis gera preâmbulo arbitrário, incluindo os casos que ninguém pensa
em escrever à mão: string vazia, só quebra de linha, exatamente 80 caracteres,
texto com acento e emoji, muitos pedaços minúsculos.

Property 8: para QUALQUER preâmbulo seguido de um chunk final com tool_calls
            completos, as chamadas obtidas são exatamente as emitidas, e o
            texto entregue ao TTS é exatamente o preâmbulo.

Property 9: para QUALQUER stream sem tool_calls, zero ferramentas são
            executadas e o texto é a concatenação exata dos deltas.

Rodar:
    python -m pytest testes/test_ferramentas_propriedades.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm  # noqa: E402


# ═════════════════════════════════════════════════════════════════
# CONSTRUTORES DE CHUNK NO FORMATO DO GATEWAY
# ═════════════════════════════════════════════════════════════════

def chunk_texto(texto: str):
    d = SimpleNamespace(content=texto, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=None)])


def chunk_ferramentas(tools):
    """UM chunk com a lista completa — é assim que o gateway emite."""
    tool_calls = [
        SimpleNamespace(
            index=i, id=tid, type="function",
            function=SimpleNamespace(name=nome, arguments=args),
        )
        for i, (tid, nome, args) in enumerate(tools)
    ]
    d = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=None)])


def chunk_fim(motivo: str):
    d = SimpleNamespace(content=None, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=d, finish_reason=motivo)])


def consumir(fluxo) -> tuple[str, list]:
    """
    Consome como o laço do modelo.py faz — e a releitura de .chamadas no fim
    NÃO é opcional, é o que salva o caso do gateway.
    """
    if fluxo.quer_ferramenta():
        return fluxo.preambulo, fluxo.chamadas
    texto = "".join(fluxo.texto())
    return texto, fluxo.chamadas


# ═════════════════════════════════════════════════════════════════
# ESTRATÉGIAS
# ═════════════════════════════════════════════════════════════════

# Pedaços de texto como o modelo emite: curtos, com acento, com espaço,
# ocasionalmente vazios.
_pedaco = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=40,
)
_pedacos = st.lists(_pedaco, max_size=12)

_nome_ferramenta = st.sampled_from([
    "ver_tela", "abrir_site", "abrir_pasta", "traduzir_tela", "pesquisar",
])
_args = st.sampled_from(['{}', '{"nome":"downloads"}', '{"consulta":"preço rtx"}'])
_ferramentas = st.lists(
    st.tuples(st.text(min_size=1, max_size=8), _nome_ferramenta, _args),
    min_size=1, max_size=3,
)


# ═════════════════════════════════════════════════════════════════
# Property 8: ferramenta no fim do stream é executada
# Validates: Requirements 8.1, 8.2, 8.3
# ═════════════════════════════════════════════════════════════════

@settings(max_examples=300, deadline=None)
@given(pedacos=_pedacos, tools=_ferramentas)
def test_property8_ferramenta_no_fim_sempre_executada(pedacos, tools):
    chunks = [chunk_texto(p) for p in pedacos]
    chunks.append(chunk_ferramentas(tools))
    chunks.append(chunk_fim("tool_calls"))

    texto, chamadas = consumir(llm.FluxoComFerramentas(iter(chunks)))

    # As ferramentas obtidas são exatamente as emitidas, na ordem.
    assert [c.nome for c in chamadas] == [nome for _, nome, _ in tools]
    assert [c.argumentos for c in chamadas] == [args for _, _, args in tools]

    # E o texto entregue é exatamente o preâmbulo, sem perda nem duplicação.
    assert texto == "".join(pedacos)


@settings(max_examples=200, deadline=None)
@given(pedacos=_pedacos, tools=_ferramentas)
def test_property8_argumentos_nao_sao_concatenados_duas_vezes(pedacos, tools):
    """
    Regressão específica do formato do gateway.

    O acumulador de argumentos do FluxoComFerramentas foi escrito para o NIM,
    que manda os argumentos FATIADOS (`alvo["args"] += fn.arguments`). O
    gateway manda completos de uma vez. Se algum dia o mesmo chunk for
    processado duas vezes, o JSON viraria '{}{}'  e o args() devolveria {}
    silenciosamente — falha caladíssima.
    """
    chunks = [chunk_texto(p) for p in pedacos]
    chunks.append(chunk_ferramentas(tools))
    chunks.append(chunk_fim("tool_calls"))

    _, chamadas = consumir(llm.FluxoComFerramentas(iter(chunks)))

    for chamada, (_, _, args_originais) in zip(chamadas, tools):
        assert chamada.argumentos == args_originais
        # E o parse tem que funcionar, não devolver {} por JSON torto.
        if args_originais != "{}":
            assert chamada.args() != {}, f"argumentos ilegíveis: {chamada.argumentos!r}"


@settings(max_examples=100, deadline=None)
@given(tools=_ferramentas)
def test_property8_sem_preambulo_decide_ferramenta_na_hora(tools):
    """Sem texto nenhum antes, a decisão é imediata e o preâmbulo é vazio."""
    chunks = [chunk_ferramentas(tools), chunk_fim("tool_calls")]
    fluxo = llm.FluxoComFerramentas(iter(chunks))

    assert fluxo.quer_ferramenta() is True
    assert fluxo.preambulo == ""
    assert len(fluxo.chamadas) == len(tools)


@settings(max_examples=100, deadline=None)
@given(espacos=st.lists(st.sampled_from(["\n", " ", "\t", "\r\n", "  "]),
                        min_size=1, max_size=6),
       tools=_ferramentas)
def test_property8_whitespace_nao_atrapalha_a_decisao(espacos, tools):
    """
    Espaço em branco não decide nada.

    Modelo em streaming costuma abrir a resposta com um "\\n" sozinho, e uma
    versão anterior desta camada derrubava a decisão inteira por causa disso.
    """
    chunks = [chunk_texto(e) for e in espacos]
    chunks.append(chunk_ferramentas(tools))
    chunks.append(chunk_fim("tool_calls"))

    fluxo = llm.FluxoComFerramentas(iter(chunks))
    assert fluxo.quer_ferramenta() is True
    assert len(fluxo.chamadas) == len(tools)


@settings(max_examples=150, deadline=None)
@given(tamanho=st.integers(min_value=0, max_value=300), tools=_ferramentas)
def test_property8_qualquer_tamanho_de_preambulo(tamanho, tools):
    """
    Varre a janela de decisão de 80 chars por inteiro, incluindo as bordas.

    Abaixo de 80 a camada decide "ferramenta" e o preâmbulo sai por
    .preambulo; acima, decide "texto" e a ferramenta só aparece na releitura
    de .chamadas. As DUAS saídas têm que entregar o mesmo resultado.
    """
    preambulo = "a" * tamanho
    chunks = [chunk_texto(preambulo)] if preambulo else []
    chunks.append(chunk_ferramentas(tools))
    chunks.append(chunk_fim("tool_calls"))

    texto, chamadas = consumir(llm.FluxoComFerramentas(iter(chunks)))

    assert texto == preambulo
    assert len(chamadas) == len(tools)


# ═════════════════════════════════════════════════════════════════
# Property 9: texto puro não inventa ferramenta
# Validates: Requirements 8.4
# ═════════════════════════════════════════════════════════════════

@settings(max_examples=300, deadline=None)
@given(pedacos=_pedacos)
def test_property9_texto_puro_executa_zero_ferramentas(pedacos):
    chunks = [chunk_texto(p) for p in pedacos]
    chunks.append(chunk_fim("stop"))

    texto, chamadas = consumir(llm.FluxoComFerramentas(iter(chunks)))

    assert chamadas == []
    assert texto == "".join(pedacos)


@settings(max_examples=100, deadline=None)
@given(pedacos=st.lists(_pedaco, min_size=1, max_size=20))
def test_property9_nada_do_texto_e_perdido(pedacos):
    """
    O texto entregue ao TTS é a concatenação EXATA dos deltas.

    Importa porque o buffer de decisão é consumido antes do resto do stream:
    se .texto() esquecesse de devolver o que já foi lido na decisão, a Emily
    engoliria o começo da própria frase.
    """
    chunks = [chunk_texto(p) for p in pedacos] + [chunk_fim("stop")]
    fluxo = llm.FluxoComFerramentas(iter(chunks))

    assert fluxo.quer_ferramenta() is False
    assert "".join(fluxo.texto()) == "".join(pedacos)
