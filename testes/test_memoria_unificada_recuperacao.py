"""Fase 3: recuperação em três camadas (sem rede, embeddings controlados)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Sequence

import pytest

from memoria_unificada import (
    ArmazenamentoMemoria,
    ConfigMemoria,
    EventoMemoria,
    FatoMemoria,
    JournalMemoria,
    RecuperadorMemoria,
)
from memoria_unificada.journal import normalizar_busca
from memoria_unificada.recuperacao import _extrair_termos


class EmbeddingsControlados:
    """Vetores por chave exata; consulta precisa estar no mapa."""

    identificador = "fake:mapa-v1"

    def __init__(self, mapa: Dict[str, Sequence[float]]):
        self._mapa = {chave: [float(v) for v in vetor] for chave, vetor in mapa.items()}

    def gerar(self, textos: Sequence[str]) -> List[List[float]]:
        saida = []
        for texto in textos:
            chave = texto.strip()
            # Consultas usam a chave exata ("python"); fatos consultam o mapa
            # normalizado para casar independente de maiúsculas.
            vetor = self._mapa.get(chave) or self._mapa.get(normalizar_busca(chave))
            if vetor is None:
                raise AssertionError(f"texto sem vetor planejado: {chave!r}")
            saida.append(list(vetor))
        return saida


DIA = 86400.0
HORA = 3600.0
AGORA = 1_800_000_000.0


def _config(tmp_path: Path, **mudancas) -> ConfigMemoria:
    dados = {
        "pasta_dados": tmp_path / "dados",
        "nome_colecao": "emily_fase3",
        "provedor_embeddings": "ollama",
        "modelo_embeddings": "fake",
        "orcamento_prompt": 2000,
    }
    dados.update(mudancas)
    return ConfigMemoria(**dados)


def _fato(
    fato_id: str,
    texto: str,
    *,
    dono: str = "vitor",
    importancia: int = 8,
    topico: str = "preferencia",
    canal: str = "web",
    atualizado_em: float = AGORA,
    evidence_role: str = "user",
) -> FatoMemoria:
    return FatoMemoria(
        id=fato_id,
        owner_user_id=dono,
        texto=texto,
        importancia=importancia,
        canal_origem=canal,
        criado_em=atualizado_em,
        atualizado_em=atualizado_em,
        sujeito="Emily" if evidence_role == "assistant" else "Vitor",
        topico=topico,
        confianca=0.95,
        evidence_role=evidence_role,
    )


def _troca(
    evento_id: str,
    texto: str,
    *,
    papel: str = "user",
    dono: str = "vitor",
    canal: str = "web",
    timestamp: float = AGORA,
    pool: str = "general",
) -> EventoMemoria:
    return EventoMemoria(
        id=evento_id,
        owner_user_id=dono,
        papel=papel,
        texto=texto,
        canal=canal,
        timestamp=timestamp,
        privacy_scope="owner_private",
        memory_pool=pool,
    )


def _infra(tmp_path: Path, mapa: Dict[str, Sequence[float]], **cfg_mudancas):
    config = _config(tmp_path, **cfg_mudancas)
    journal = JournalMemoria(config)
    storage = ArmazenamentoMemoria(config, EmbeddingsControlados(mapa))
    recuperador = RecuperadorMemoria(journal, storage, config)
    return config, journal, storage, recuperador


# ═════════════════════════════════════════════════════════════════
# CAMADA 3 — pontuação de fatos
# ═════════════════════════════════════════════════════════════════

def test_fato_recente_vence_relevancia_quando_pontuacao_soma(tmp_path):
    # A: relevância 1.0, antigo (30 dias), importância média.
    # B: relevância 0.9, recente (1 hora), importância máxima.
    # Com os pesos padrão, B vence na soma ponderada.
    mapa = {
        "python": [1.0, 0.0, 0.0],
        "Vitor prefere programar em Python": [1.0, 0.0, 0.0],
        "Vitor escolheu Python como linguagem principal": [0.9, 0.435889894354067, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato(
        "fato-a", "Vitor prefere programar em Python",
        importancia=8, atualizado_em=AGORA - 30 * DIA))
    storage.salvar(_fato(
        "fato-b", "Vitor escolheu Python como linguagem principal",
        importancia=10, topico="decision", atualizado_em=AGORA - HORA))

    contexto = recuperador.contexto_completo("vitor", "python", agora=AGORA)

    assert [p.fato.id for p in contexto.fatos] == ["fato-b", "fato-a"]


def test_relevancia_vence_quando_idades_sao_equivalentes(tmp_path):
    # Mesma idade, mesma importância: quem é mais relevante vem primeiro.
    mapa = {
        "python": [1.0, 0.0, 0.0],
        "Vitor prefere programar em Python": [1.0, 0.0, 0.0],
        "Vitor já mexeu em Python uma vez": [0.5, 0.8660254037844386, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato(
        "forte", "Vitor prefere programar em Python", atualizado_em=AGORA - DIA))
    storage.salvar(_fato(
        "fraco", "Vitor já mexeu em Python uma vez", atualizado_em=AGORA - DIA))

    contexto = recuperador.contexto_completo("vitor", "python", agora=AGORA)

    assert [p.fato.id for p in contexto.fatos] == ["forte", "fraco"]


def test_importancia_desempata_relevancias_iguais(tmp_path):
    mapa = {
        "spotify": [1.0, 0.0, 0.0],
        "Vitor ouve música no Spotify todo dia": [1.0, 0.0, 0.0],
        "Vitor abriu o Spotify uma vez": [1.0, 0.0, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato(
        "forte", "Vitor ouve música no Spotify todo dia",
        importancia=10, topico="preferencia"))
    storage.salvar(_fato(
        "fraco", "Vitor abriu o Spotify uma vez", importancia=3, topico="musica"))

    contexto = recuperador.contexto_completo("vitor", "spotify", agora=AGORA)

    assert [p.fato.id for p in contexto.fatos] == ["forte", "fraco"]


def test_diversidade_limita_por_topico(tmp_path):
    # Três fatos do mesmo tópico, todos mais fortes que o fato de outro tópico.
    # Sem diversidade, os três comeriam as vagas; com ela, o terceiro sai.
    mapa = {
        "python": [1.0, 0.0, 0.0],
        "Vitor usa Python diariamente": [1.0, 0.0, 0.0],
        "Vitor ensina Python pra amigos": [0.95, 0.31224989991992003, 0.0],
        "Vitor estuda Python aos fins de semana": [0.9, 0.435889894354067, 0.0],
        "Vitor curte música ao programar": [0.85, 0.5267826876426397, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato("p1", "Vitor usa Python diariamente", topico="python"))
    storage.salvar(_fato("p2", "Vitor ensina Python pra amigos", topico="python"))
    storage.salvar(_fato("p3", "Vitor estuda Python aos fins de semana", topico="python"))
    storage.salvar(_fato("m1", "Vitor curte música ao programar", topico="musica"))

    contexto = recuperador.contexto_completo("vitor", "python", agora=AGORA)

    ids = [p.fato.id for p in contexto.fatos]
    assert ids == ["p1", "p2", "m1"]


def test_orcamento_limita_quantos_fatos_entram(tmp_path):
    textos = [f"memoria item numero {indice} com texto longo" for indice in range(6)]
    mapa = {"memoria": [1.0, 0.0, 0.0]}
    mapa.update({texto: [1.0, 0.0, 0.0] for texto in textos})
    _, _, storage, recuperador = _infra(
        tmp_path, mapa, orcamento_prompt=120)
    for indice, texto in enumerate(textos):
        storage.salvar(_fato(
            f"f{indice}", texto,
            importancia=10 - indice, topico=f"topico-{indice}"))

    contexto = recuperador.contexto_completo("vitor", "memoria", agora=AGORA)

    assert 1 <= len(contexto.fatos) < 6
    prompt = contexto.para_prompt()
    assert len(prompt) <= 180  # teto + cabeçalho fixo do bloco
    assert "memoria item numero 0" in prompt


def test_fatos_superseded_e_forgotten_nao_sao_recuperados(tmp_path):
    mapa = {
        "curso": [1.0, 0.0, 0.0],
        "Vitor cursa História": [1.0, 0.0, 0.0],
        "Vitor cursa Ciência da Computação": [1.0, 0.0, 0.0],
        "Vitor odeia faculdade": [1.0, 0.0, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    antigo = storage.salvar(_fato(
        "antigo", "Vitor cursa História", topico="biografia"))
    storage.salvar(_fato(
        "novo", "Vitor cursa Ciência da Computação", topico="biografia"))
    esquecido = storage.salvar(_fato(
        "esquecido", "Vitor odeia faculdade", topico="opiniao"))
    storage.superseder("vitor", antigo.id, _fato(
        "novo-ref", "Vitor cursa Ciência da Computação", topico="biografia"))
    storage.esquecer("vitor", esquecido.id)

    contexto = recuperador.contexto_completo("vitor", "curso", agora=AGORA)

    ids = {p.fato.id for p in contexto.fatos}
    assert "novo" in ids
    assert "antigo" not in ids
    assert "esquecido" not in ids


def test_fato_de_outro_dono_nunca_aparece(tmp_path):
    mapa = {
        "segredo": [1.0, 0.0, 0.0],
        "Segredo do terceiro": [1.0, 0.0, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato(
        "alheio", "Segredo do terceiro", dono="discord:7"))

    contexto = recuperador.contexto_completo("vitor", "segredo", agora=AGORA)

    assert contexto.fatos == ()
    assert contexto.para_prompt() == ""


def test_compromisso_da_emily_vai_para_bloco_proprio(tmp_path):
    mapa = {
        "emojis": [1.0, 0.0, 0.0],
        "Emily prometeu não responder com emojis": [1.0, 0.0, 0.0],
    }
    _, _, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato(
        "comp", "Emily prometeu não responder com emojis",
        topico="commitment", evidence_role="assistant", importancia=7))

    contexto = recuperador.contexto_completo("vitor", "emojis", agora=AGORA)

    assert contexto.fatos == ()
    assert len(contexto.compromissos) == 1
    prompt = contexto.para_prompt()
    assert "COMPROMISSOS ATIVOS" in prompt
    assert "não responder com emojis" in prompt


def test_score_minimo_descarta_fato_fraco(tmp_path):
    # Irrelevante (0.1), pouco importante (2) e velho: score abaixo do piso.
    mapa = {
        "clima": [1.0, 0.0, 0.0],
        "Vitor comentou sobre o clima uma vez": [0.1, 0.99498743710662, 0.0],
    }
    _, _, storage, recuperador = _infra(
        tmp_path, mapa, min_score_fato=0.30)
    storage.salvar(_fato(
        "fraco", "Vitor comentou sobre o clima uma vez",
        importancia=2, topico="casual", atualizado_em=AGORA - 60 * DIA))

    contexto = recuperador.contexto_completo("vitor", "clima", agora=AGORA)

    assert contexto.fatos == ()


# ═════════════════════════════════════════════════════════════════
# CAMADAS 1 e 2 — conversa recente e lembretes
# ═════════════════════════════════════════════════════════════════

def test_camada1_ultimas_trocas_de_qualquer_canal(tmp_path):
    _, journal, _, recuperador = _infra(tmp_path, {})
    journal.adicionar(_troca("t1", "boa noite no chat", canal="web",
                             timestamp=AGORA - 3 * HORA))
    journal.adicionar(_troca("t2", "eae no discord", canal="discord",
                             timestamp=AGORA - 2 * HORA))
    journal.adicionar(_troca("t3", "resposta dela no discord", papel="assistant",
                             canal="discord", timestamp=AGORA - HORA))
    journal.adicionar(_troca("t4", "falei na voz", canal="voz",
                             timestamp=AGORA - 30 * 60))

    contexto = recuperador.contexto_completo("vitor", "", agora=AGORA)

    assert [e.id for e in contexto.trocas] == ["t1", "t2", "t3", "t4"]
    assert {e.canal for e in contexto.trocas} == {"web", "discord", "voz"}
    prompt = contexto.para_prompt()
    assert "CONVERSA RECENTE" in prompt
    assert "Você: resposta dela no discord" in prompt
    assert "Usuário: falei na voz" in prompt
    assert "Vitor:" not in prompt


def test_camada1_limita_ultimas_e_mantem_ordem_cronologica(tmp_path):
    _, journal, _, recuperador = _infra(tmp_path, {}, eventos_recentes=3)
    for indice in range(5):
        journal.adicionar(_troca(
            f"t{indice}", f"mensagem {indice}", timestamp=AGORA - (5 - indice) * HORA))

    contexto = recuperador.contexto_completo("vitor", "", agora=AGORA)

    assert [e.id for e in contexto.trocas] == ["t2", "t3", "t4"]


def test_camada2_lembrete_cruza_por_palavra_chave_sem_acento(tmp_path):
    # eventos_recentes=1 e um evento mais novo ocupam a camada 1, empurrando o
    # alvo da consulta para a camada 2 (senão o dedup camada1×2 o removeria).
    _, journal, _, recuperador = _infra(tmp_path, {}, eventos_recentes=1)
    journal.adicionar(_troca(
        "recente1", "oi agora mesmo", timestamp=AGORA - 60))
    journal.adicionar(_troca(
        "lem", "ontem a gente conversou sobre a memória unificada do journal",
        timestamp=AGORA - 5 * HORA))

    contexto = recuperador.contexto_completo(
        "vitor", "lembra da memória unificada?", agora=AGORA)

    assert [e.id for e in contexto.trocas] == ["recente1"]
    assert [l.evento.id for l in contexto.lembretes] == ["lem"]
    prompt = contexto.para_prompt()
    assert "LEMBRETES DO HISTÓRICO RECENTE" in prompt
    assert "memória unificada do journal" in prompt


def test_camada2_respeita_janela_temporal(tmp_path):
    _, journal, _, recuperador = _infra(
        tmp_path, {}, janela_recente_horas=48, eventos_recentes=1)
    journal.adicionar(_troca(
        "recente1", "mensagem mais nova de agora", timestamp=AGORA - 60))
    journal.adicionar(_troca(
        "recente", "conversamos sobre python semana passada também",
        timestamp=AGORA - 10 * HORA))
    journal.adicionar(_troca(
        "antigo", "python apareceu numa conversa bem antiga",
        timestamp=AGORA - 100 * HORA))

    contexto = recuperador.contexto_completo(
        "vitor", "aquela conversa sobre python", agora=AGORA)

    assert [e.id for e in contexto.trocas] == ["recente1"]
    assert [l.evento.id for l in contexto.lembretes] == ["recente"]


def test_evento_da_camada1_nao_duplica_como_lembrete(tmp_path):
    _, journal, _, recuperador = _infra(tmp_path, {})
    journal.adicionar(_troca(
        "duplo", "conversa sobre python e memória agora mesmo",
        timestamp=AGORA - HORA))

    contexto = recuperador.contexto_completo(
        "vitor", "python e memória", agora=AGORA)

    assert [e.id for e in contexto.trocas] == ["duplo"]
    assert contexto.lembretes == ()


def test_busca_texto_pontua_por_fracasao_de_termos(tmp_path):
    _, journal, _, _ = _infra(tmp_path, {})
    journal.adicionar(_troca(
        "ambos", "assunto python e memória juntos", timestamp=AGORA - HORA))
    journal.adicionar(_troca(
        "so_um", "só python aqui", timestamp=AGORA - HORA))

    achados = journal.buscar_texto("vitor", ("python", "memoria"), limite=10)

    por_id = {evento.id: fracao for evento, fracao in achados}
    assert por_id["ambos"] == 1.0
    assert por_id["so_um"] == 0.5
    assert achados[0][0].id == "ambos"


def test_extrair_termos_descarta_curtas_e_duplicados():
    termos = _extrair_termos("oi! A memória da memória, é?? Vitor")

    assert termos == ["memoria", "vitor"]


# ═════════════════════════════════════════════════════════════════
# CONTRATO GERAL
# ═════════════════════════════════════════════════════════════════

def test_consulta_vazia_retorna_apenas_camada1(tmp_path):
    _, journal, _, recuperador = _infra(tmp_path, {})
    journal.adicionar(_troca("t1", "oi", timestamp=AGORA - HORA))

    contexto = recuperador.contexto_completo("vitor", "", agora=AGORA)

    assert len(contexto.trocas) == 1
    assert contexto.lembretes == ()
    assert contexto.fatos == ()
    assert contexto.compromissos == ()
    assert "CONVERSA RECENTE" in contexto.para_prompt()


def test_dono_e_obrigatorio_na_recuperacao(tmp_path):
    _, _, _, recuperador = _infra(tmp_path, {})

    with pytest.raises(ValueError, match="owner_user_id"):
        recuperador.contexto_completo("", "qualquer coisa")


def test_para_prompt_e_deterministico(tmp_path):
    mapa = {
        "python": [1.0, 0.0, 0.0],
        "Vitor prefere Python": [1.0, 0.0, 0.0],
    }
    _, journal, storage, recuperador = _infra(tmp_path, mapa)
    storage.salvar(_fato("f1", "Vitor prefere Python", topico="python"))
    journal.adicionar(_troca("t1", "falei de python agora", timestamp=AGORA))

    primeiro = recuperador.contexto_completo("vitor", "python", agora=AGORA)
    segundo = recuperador.contexto_completo("vitor", "python", agora=AGORA)

    assert primeiro.para_prompt() == segundo.para_prompt()
    assert primeiro.para_prompt().startswith("MEMÓRIA RELEVANTE:")


def test_normalizar_busca_remove_acentos_e_caixa():
    assert normalizar_busca("  Programação   e   MÉMORIA  ") == "programacao e memoria"
