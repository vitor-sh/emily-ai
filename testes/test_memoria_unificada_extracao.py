"""Fase 2: journal, extração estruturada, retries e worker (tudo offline)."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path

import pytest
import llm

from memoria_unificada import (
    ArmazenamentoMemoria,
    ConfigMemoria,
    ErroExtracao,
    EventoMemoria,
    ExtratorMemoria,
    FatoMemoria,
    JournalMemoria,
    ProcessadorLote,
    ServicoMemoria,
    WorkerExtracao,
)


class EmbeddingsFake:
    identificador = "fake:fase2"

    def gerar(self, textos):
        saida = []
        for texto in textos:
            base = [1.0, 0.2, 0.1]
            if "python" in texto.lower():
                base[1] += 1
            norma = math.sqrt(sum(v * v for v in base))
            saida.append([v / norma for v in base])
        return saida


def _config(tmp_path: Path, **mudancas) -> ConfigMemoria:
    dados = {
        "pasta_dados": tmp_path / "dados",
        "nome_colecao": "emily_fase2",
        "provedor_embeddings": "ollama",
        "modelo_embeddings": "fake",
        "eventos_por_extracao": 4,
        "max_eventos_por_lote": 10,
        "max_chars_por_lote": 5000,
        "tentativas_extracao": 3,
        "fila_maxima": 10,
    }
    dados.update(mudancas)
    return ConfigMemoria(**dados)


def _evento(
    evento_id: str,
    papel: str,
    texto: str,
    *,
    dono: str = "vitor",
    canal: str = "web",
    pool: str = "general",
    privacidade: str = "owner_private",
    external_id: str = "",
    timestamp: float = 1000.0,
) -> EventoMemoria:
    return EventoMemoria(
        id=evento_id,
        owner_user_id=dono,
        papel=papel,
        texto=texto,
        canal=canal,
        conversa_id="chat-1",
        external_id=external_id,
        privacy_scope=privacidade,
        memory_pool=pool,
        timestamp=timestamp,
    )


def _infra(tmp_path, chamar_llm, **config_mudancas):
    config = _config(tmp_path, **config_mudancas)
    journal = JournalMemoria(config)
    storage = ArmazenamentoMemoria(config, EmbeddingsFake())
    extrator = ExtratorMemoria(chamar_llm=chamar_llm)
    processador = ProcessadorLote(
        journal, storage, extrator, max_tentativas=config.tentativas_extracao)
    return config, journal, storage, extrator, processador


def _resposta(*fatos):
    return json.dumps({"facts": list(fatos)}, ensure_ascii=False)


def _fato_json(
    texto="Vitor prefere Python",
    ids=("u1",),
    topico="strong_preference",
    sujeito="Vitor",
    importancia=8,
    confianca=0.95,
):
    return {
        "text": texto,
        "importance": importancia,
        "entities": ["Vitor", "Python"],
        "subject": sujeito,
        "topic": topico,
        "confidence": confianca,
        "source_event_ids": list(ids),
    }


def test_journal_append_only_idempotente_e_persistente(tmp_path):
    config = _config(tmp_path)
    journal = JournalMemoria(config)
    evento = _evento("evt-1", "user", "Eu prefiro Python", external_id="msg-10")

    salvo, criou = journal.adicionar(evento)
    repetido, criou_de_novo = journal.adicionar(evento)
    reaberto = JournalMemoria(config)

    assert criou is True
    assert criou_de_novo is False
    assert repetido == salvo == evento
    assert reaberto.listar_recentes("vitor") == [evento]


def test_rota_de_extracao_e_dedicada_ao_haiku():
    rota = llm.rota("memoria_extracao")

    assert rota.provedor == llm.PROVEDOR_ROTAS
    assert "haiku" in rota.modelo.lower()
    assert rota.raciocinio == llm.RACIOCINIO_DESLIGADO
    assert rota.temperatura == 0.0
    # Dedicada de verdade: trocar o cérebro (rota 'conversa') não pode
    # arrastar a extração de memória junto.
    assert rota.modelo != llm.rota("conversa").modelo or (
        llm.rota("conversa").modelo == llm.MODELO_ROTAS_RAPIDO
    )


def test_journal_recusa_id_ou_external_id_com_outro_conteudo(tmp_path):
    journal = JournalMemoria(_config(tmp_path))
    journal.adicionar(_evento("evt-1", "user", "texto A", external_id="ext-1"))

    with pytest.raises(ValueError, match="outro conteúdo"):
        journal.adicionar(_evento("evt-1", "user", "texto B"))
    with pytest.raises(ValueError, match="outro conteúdo"):
        journal.adicionar(_evento("evt-2", "user", "texto B", external_id="ext-1"))

    assert [e.texto for e in journal.listar_recentes("vitor")] == ["texto A"]


def test_journal_isola_dono_privacidade_e_pool(tmp_path):
    journal = JournalMemoria(_config(tmp_path))
    journal.adicionar_varios([
        _evento("v-geral", "user", "geral"),
        _evento("v-code", "user", "code", pool="code"),
        _evento("v-publico", "user", "público", privacidade="public"),
        _evento("terceiro", "user", "segredo", dono="discord:7"),
    ])

    assert [e.id for e in journal.listar_recentes(
        "vitor", privacy_scopes=("owner_private",), pools=("general",)
    )] == ["v-geral"]
    assert {e.id for e in journal.listar_recentes("vitor")} == {
        "v-geral", "v-code", "v-publico"
    }
    assert [e.id for e in journal.listar_recentes("discord:7")] == ["terceiro"]


def test_lote_e_homogeneo_limitado_e_eventos_ficam_imutaveis(tmp_path):
    journal = JournalMemoria(_config(tmp_path))
    eventos = [
        _evento(f"e{i}", "user" if i % 2 == 0 else "assistant", "x" * 10,
                timestamp=1000 + i)
        for i in range(5)
    ]
    journal.adicionar_varios(eventos)
    journal.adicionar(_evento("outro-pool", "user", "não misturar", pool="code"))

    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 25)

    assert lote is not None
    assert [e.id for e in lote.eventos] == ["e0", "e1"]
    assert {e.memory_pool for e in lote.eventos} == {"general"}
    assert journal.contar_nao_processados("vitor", "owner_private", "general") == 3
    assert journal.listar_recentes("vitor", pools=("general",)) == eventos


def test_extrator_usa_rota_haiku_e_calcula_evidencia_localmente(tmp_path):
    chamadas = []

    def llm_fake(**kwargs):
        chamadas.append(kwargs)
        return _resposta(_fato_json(ids=("u1", "a1")))

    _, journal, _, extrator, _ = _infra(tmp_path, llm_fake)
    journal.adicionar_varios([
        _evento("u1", "user", "Eu realmente prefiro Python"),
        _evento("a1", "assistant", "Beleza, vou lembrar disso", timestamp=1001),
    ])
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    fatos = extrator.extrair(lote)

    assert len(fatos) == 1
    assert fatos[0].evidence_role == "mixed"
    assert fatos[0].eventos_origem_ids == ("u1", "a1")
    assert fatos[0].privacy_scope == lote.privacy_scope
    assert chamadas[0]["rota_nome"] == "memoria_extracao"
    assert chamadas[0]["max_tokens"] == 900
    assert "não confiáveis" in chamadas[0]["prompt"]


def test_extrator_descarta_alucinacao_isolada_da_emily(tmp_path):
    resposta = _resposta(_fato_json(
        texto="Vitor mora em Marte", ids=("a1",), topico="biography"))
    _, journal, _, extrator, _ = _infra(tmp_path, lambda **_: resposta)
    journal.adicionar(_evento("a1", "assistant", "Você mora em Marte"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    assert extrator.extrair(lote) == []


def test_extrator_aceita_compromisso_da_emily_com_confianca_limitada(tmp_path):
    resposta = _resposta(_fato_json(
        texto="Emily prometeu não responder com emojis",
        ids=("a1",), topico="commitment", sujeito="Emily", confianca=0.99))
    _, journal, _, extrator, _ = _infra(tmp_path, lambda **_: resposta)
    journal.adicionar(_evento(
        "a1", "assistant", "Eu prometo que não vou responder com emojis"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    fatos = extrator.extrair(lote)

    assert len(fatos) == 1
    assert fatos[0].evidence_role == "assistant"
    assert fatos[0].confianca == 0.6


@pytest.mark.parametrize("alteracao", [
    {"source_event_ids": ["inventado"]},
    {"importance": 99},
    {"confidence": -1},
    {"topic": "assunto_inventado"},
    {"text": ""},
])
def test_extrator_descarta_fato_estruturalmente_invalido(tmp_path, alteracao):
    bruto = _fato_json()
    bruto.update(alteracao)
    _, journal, _, extrator, _ = _infra(
        tmp_path, lambda **_: _resposta(bruto))
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    assert extrator.extrair(lote) == []


def test_extrator_recusa_json_malformado(tmp_path):
    _, journal, _, extrator, _ = _infra(tmp_path, lambda **_: "não é json")
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    with pytest.raises(ErroExtracao):
        extrator.extrair(lote)


def test_code_promove_so_topicos_tecnicos_importantes(tmp_path):
    resposta = _resposta(
        _fato_json(
            texto="Vitor decidiu usar SQLite no journal",
            ids=("u1",), topico="architecture_decision"),
        _fato_json(
            texto="Emily leu o arquivo main.py",
            ids=("u1",), topico="file_read"),
    )
    _, journal, _, extrator, _ = _infra(tmp_path, lambda **_: resposta)
    journal.adicionar(_evento(
        "u1", "user", "Vamos usar SQLite no journal", pool="code"))
    lote = journal.criar_lote("vitor", "owner_private", "code", 10, 5000)

    fatos = extrator.extrair(lote)

    assert [f.topico for f in fatos] == ["architecture_decision"]
    assert fatos[0].memory_pool == "code"


def test_retry_gera_mesmo_id_e_nao_duplica_fato(tmp_path):
    chamadas = {"n": 0}

    def llm_instavel(**_):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("falha temporária")
        return _resposta(_fato_json())

    config, journal, storage, _, processador = _infra(tmp_path, llm_instavel)
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    assert processador.processar(lote.id) is False
    assert journal.obter_lote(lote.id).status == "failed"
    assert processador.processar(lote.id) is True
    concluido = journal.obter_lote(lote.id)

    assert concluido.status == "completed"
    assert concluido.tentativas == 2
    assert len(concluido.fatos_gerados_ids) == 1
    assert storage.contar("vitor") == 1


def test_id_do_fato_nao_muda_quando_llm_reformula_no_retry(tmp_path):
    respostas = iter([
        _resposta(_fato_json(texto="Vitor prefere Python")),
        _resposta(_fato_json(texto="Python é a linguagem preferida de Vitor")),
    ])
    _, journal, _, extrator, _ = _infra(
        tmp_path, lambda **_: next(respostas))
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    primeiro = extrator.extrair(lote)[0]
    reformulado = extrator.extrair(lote)[0]

    assert primeiro.texto != reformulado.texto
    assert primeiro.id == reformulado.id


def test_lote_vazio_de_fatos_tambem_e_concluido(tmp_path):
    _, journal, storage, _, processador = _infra(
        tmp_path, lambda **_: _resposta())
    journal.adicionar(_evento("u1", "user", "oi"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)

    assert processador.processar(lote.id) is True
    assert journal.obter_lote(lote.id).status == "completed"
    assert storage.contar("vitor") == 0


def test_servico_registra_os_dois_lados_e_external_id_e_idempotente(tmp_path):
    config, journal, storage, _, processador = _infra(
        tmp_path, lambda **_: _resposta(_fato_json(ids=())) ,
        eventos_por_extracao=10,
    )
    servico = ServicoMemoria(journal, processador, config)

    primeiro = servico.registrar_troca(
        "vitor", "Eu prefiro Python", "Vou lembrar",
        canal="web", conversa_id="chat-1", external_id="turno-1",
        timestamp=1000,
    )
    repetido = servico.registrar_troca(
        "vitor", "Eu prefiro Python", "Vou lembrar",
        canal="web", conversa_id="chat-1", external_id="turno-1",
        timestamp=1000,
    )

    assert primeiro.eventos_novos == 2
    assert repetido.eventos_novos == 0
    assert [e.papel for e in journal.listar_recentes("vitor")] == [
        "user", "assistant"
    ]
    assert storage.contar("vitor") == 0


def test_retry_de_external_id_preserva_timestamp_original(tmp_path):
    config, journal, _, _, processador = _infra(
        tmp_path, lambda **_: _resposta(), eventos_por_extracao=10)
    servico = ServicoMemoria(journal, processador, config)

    primeiro = servico.registrar_troca(
        "vitor", "Mensagem", "Resposta", "discord",
        external_id="discord-msg-1", timestamp=1000,
    )
    repetido = servico.registrar_troca(
        "vitor", "Mensagem", "Resposta", "discord",
        external_id="discord-msg-1", timestamp=9000,
    )

    assert primeiro.eventos_novos == 2
    assert repetido.eventos_novos == 0
    assert [e.timestamp for e in journal.listar_recentes("vitor")] == [
        1000.0, 1000.000001
    ]


def test_servico_dispara_no_limiar_e_flush_processa_resto(tmp_path):
    def llm_fake(**kwargs):
        ids = [linha.split("]", 1)[0][1:]
               for linha in kwargs["prompt"].splitlines() if linha.startswith("[")]
        return _resposta(_fato_json(ids=(ids[0],)))

    config, journal, storage, _, processador = _infra(
        tmp_path, llm_fake, eventos_por_extracao=4)
    servico = ServicoMemoria(journal, processador, config)

    um = servico.registrar_troca(
        "vitor", "Prefiro Python", "Anotado", "web", timestamp=1000)
    dois = servico.registrar_troca(
        "vitor", "É forte mesmo", "Entendi", "web", timestamp=1001)

    assert um.lote_id == ""
    assert dois.lote_id
    assert servico.processar_agora(dois.lote_id) is True
    assert storage.contar("vitor") == 1

    servico.registrar_troca(
        "vitor", "Outro detalhe", "Certo", "web", timestamp=1002)
    lotes = servico.flush_grupo("vitor")
    assert len(lotes) == 1
    assert journal.contar_nao_processados("vitor", "owner_private", "general") == 0


def test_worker_retenta_falha_e_encerra_com_flush(tmp_path):
    chamadas = {"n": 0}

    def llm_fake(**_):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("primeira falha")
        return _resposta(_fato_json())

    config, journal, storage, _, processador = _infra(tmp_path, llm_fake)
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)
    worker = WorkerExtracao(processador, fila_maxima=3)

    worker.iniciar(recuperar=False)
    assert worker.enfileirar(lote.id) is True
    assert worker.enfileirar(lote.id) is True
    worker.aguardar()
    worker.encerrar()

    assert chamadas["n"] == 2
    assert journal.obter_lote(lote.id).status == "completed"
    assert storage.contar("vitor") == 1
    assert worker.ativo is False


def test_worker_recupera_lote_interrompido_no_restart(tmp_path):
    config, journal, storage, _, processador = _infra(
        tmp_path, lambda **_: _resposta(_fato_json()))
    journal.adicionar(_evento("u1", "user", "Eu prefiro Python"))
    lote = journal.criar_lote("vitor", "owner_private", "general", 10, 5000)
    assert journal.marcar_processando(lote.id, 3)

    worker = WorkerExtracao(processador)
    worker.iniciar(recuperar=True)
    worker.aguardar()
    worker.encerrar()

    recuperado = journal.obter_lote(lote.id)
    assert recuperado.status == "completed"
    assert recuperado.tentativas == 2
    assert storage.contar("vitor") == 1


def test_worker_recolhe_lote_que_nao_coube_na_fila(tmp_path):
    iniciou = threading.Event()
    liberar = threading.Event()

    def llm_lento(**_):
        iniciou.set()
        liberar.wait(timeout=5)
        return _resposta()

    config, journal, _, _, processador = _infra(tmp_path, llm_lento)
    lotes = []
    for indice in range(3):
        journal.adicionar(_evento(
            f"fila-{indice}", "user", f"mensagem {indice}", timestamp=1000 + indice))
        lotes.append(journal.criar_lote(
            "vitor", "owner_private", "general", 1, 5000))

    worker = WorkerExtracao(processador, fila_maxima=1)
    worker.iniciar(recuperar=False)
    assert worker.enfileirar(lotes[0].id) is True
    assert iniciou.wait(timeout=2)
    assert worker.enfileirar(lotes[1].id) is True
    assert worker.enfileirar(lotes[2].id) is False
    liberar.set()
    worker.aguardar(timeout=5)
    worker.encerrar(timeout=2)

    assert [journal.obter_lote(lote.id).status for lote in lotes] == [
        "completed", "completed", "completed",
    ]


def test_journal_suporta_escritas_concorrentes(tmp_path):
    journal = JournalMemoria(_config(tmp_path))
    barreira = threading.Barrier(12)
    erros = []

    def gravar(indice):
        try:
            barreira.wait(timeout=5)
            journal.adicionar(_evento(
                f"c{indice}", "user", f"mensagem {indice}", timestamp=1000 + indice))
        except Exception as erro:  # pragma: no cover - coletado para assert
            erros.append(erro)

    threads = [threading.Thread(target=gravar, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert erros == []
    assert len(journal.listar_recentes("vitor", limite=20)) == 12