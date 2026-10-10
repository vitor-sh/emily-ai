"""Regressões do streaming da call (LLM → voz sem esperar o JSON fechar).

Cobre o _ParserRespostaCall: frases só saem depois de "responder": true, a
aspa de fechamento corta o valor antes do resto do JSON virar fala, e o
escape pela metade não derruba o parse. Também trava a REGRA INVIOLÁVEL do
prompt: chamada pelo nome = resposta obrigatória (o bug real foi
"Não, Emily, o foda é que eu tô espirrando muito" devolvendo "não era comigo").
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent


# ── _ParserRespostaCall ─────────────────────────────────────────────

def _parser():
    import modelo
    decisoes, frases = [], []
    p = modelo._ParserRespostaCall(decisoes.append, frases.append)
    return p, decisoes, frases


def _alimentar_json(parser, texto, tamanho=7):
    """Simula o stream real: o JSON chega em pedaços pequenos."""
    for i in range(0, len(texto), tamanho):
        parser.alimentar(texto[i:i + tamanho])
    parser.finalizar()


def test_parser_solta_frase_depois_do_true_e_nao_antes():
    p, decisoes, frases = _parser()
    j = json.dumps({"responder": True,
                    "resposta": "Poxa, que rubbish, vai descansar um pouco. "
                                "E me manda um print do erro depois."})
    _alimentar_json(p, j)
    assert decisoes == [True]
    assert frases, "nenhuma frase saiu no stream"
    # A frase só sai depois da decisão true; e o texto todo veio.
    assert "Poxa" in " ".join(frases)


def test_parser_decisao_false_nao_fala_nada():
    p, decisoes, frases = _parser()
    j = json.dumps({"responder": False,
                    "resposta": "",
                    "detalhe_texto": "x"})
    _alimentar_json(p, j)
    assert decisoes == [False]
    assert frases == []


def test_parser_aspa_fecha_valor_e_resto_do_json_nao_vira_fala():
    p, decisoes, frases = _parser()
    j = ('{"responder": true, "resposta": "Frase completa com corpo suficiente '
         'pra fechar sozinha. Segunda frase curta.", "detalhe_texto": "isto aqui '
         'não pode virar fala de jeito nenhum"}')
    _alimentar_json(p, j)
    junto = " ".join(frases)
    assert "detalhe_texto" not in junto
    assert "isto aqui" not in junto
    assert junto.strip().startswith("Frase completa")


def test_parser_escapando_aspas_no_meio_da_frase():
    p, decisoes, frases = _parser()
    resposta = 'Frase com aspas internas do "servidor" e mais texto. Segunda!'
    j = json.dumps({"responder": True, "resposta": resposta})
    _alimentar_json(p, j)
    junto = " ".join(frases)
    assert 'servidor' in junto
    assert junto.count('Frase') == 1  # não duplicou o começo


def test_parser_teto_de_frases():
    p, decisoes, frases = _parser()
    resposta = " ".join(f"Frase numero {i} do teste com corpo bom pra fechar." for i in range(9))
    j = json.dumps({"responder": True, "resposta": resposta})
    _alimentar_json(p, j, tamanho=13)
    assert len(frases) <= p.MAX_FRASES


def test_parser_json_cortado_no_meio_ainda_fala_o_que_tem():
    p, decisoes, frases = _parser()
    pedaco = '{"responder": true, "resposta": "Poxa, espirrar muito é ruim mesmo, vai tomar um chá'
    _alimentar_json(p, pedaco)  # sem fechar o JSON
    assert decisoes == [True]
    assert frases  # o rabo parcial saiu como fala — silêncio custa mais


def test_parser_escape_pela_metade_nao_levanta():
    p, decisoes, frases = _parser()
    j = '{"responder": true, "resposta": "Frase com acento pela metade: cafe\\u00e'
    _alimentar_json(p, j)
    # Não explode; e o que decodificou até ali saiu no finalizar.
    assert decisoes == [True]


# ── REGRA INVIOLÁVEL do nome no prompt da call ─────────────────────

def test_prompt_da_call_exige_resposta_quando_chamada_pelo_nome():
    fonte = (RAIZ / "modelo.py").read_text(encoding="utf-8")
    assert "REGRA INVIOLÁVEL DO SEU NOME" in fonte
    # O bug real: vocativo no meio da frase ("Não, Emily, ...") era lido
    # como "não era comigo". O prompt agora cita esse caso explicitamente.
    assert "'Não, Emily, ...'" in fonte
    # ... e o ramo de modo conversa tem a exceção simétrica.
    assert "Mencionar seu nome em " in fonte
    assert "terceira pessoa não é um chamado" in fonte


def test_responder_na_call_aceita_callbacks_de_streaming():
    fonte = (RAIZ / "modelo.py").read_text(encoding="utf-8")
    assert "ao_decidir=None, ao_frase=None" in fonte
    assert "stream=True" in fonte


def test_pensar_na_call_repassa_callbacks():
    fonte = (RAIZ / "discord_bot.py").read_text(encoding="utf-8")
    assert "ao_decidir=ao_decidir, ao_frase=ao_frase" in fonte


def test_resto_call_tem_planejador_de_fala_incremental():
    fonte = (RAIZ / "resto_call.py").read_text(encoding="utf-8")
    assert "_PlanejadorFalaCall" in fonte
    # fallback: se nada tocou no stream, o caminho antigo roda.
    assert "ok = _falar_na_call(fala)" in fonte
