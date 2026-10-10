"""Quedas durante o stream e retomada sem repetir ações do usuário."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def _pedaco(texto: str):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=texto, tool_calls=None), finish_reason=None)])


def test_stream_reconecta_antes_de_entregar_texto(monkeypatch):
    import llm

    def quebrado():
        yield _pedaco("Pe")
        raise ConnectionError("sem rede")

    eventos = []
    fluxo = llm.FluxoComFerramentas(quebrado())
    fluxo.configurar_reconexao(
        lambda: iter([_pedaco("Resposta completa")]),
        lambda tentativa, limite: eventos.append((tentativa, limite)))
    monkeypatch.setattr(llm, "_espera_backoff", lambda _i: 0)

    assert fluxo.quer_ferramenta() is False
    assert "".join(fluxo.texto()) == "Resposta completa"
    assert eventos == [(1, 3), (0, 3)]


def test_stream_nao_reexecuta_depois_de_entregar_texto(monkeypatch):
    import llm

    def quebrado():
        yield _pedaco("Começou")
        raise ConnectionError("sem rede")

    reaberturas = []
    fluxo = llm.FluxoComFerramentas(quebrado())
    fluxo.definir_limite_decisao_texto(1)
    fluxo.configurar_reconexao(lambda: reaberturas.append(True), limite=3)
    assert fluxo.quer_ferramenta() is False
    texto = fluxo.texto()
    assert next(texto) == "Começou"
    with pytest.raises(llm.ErroTransporte, match="stream interrompido"):
        next(texto)
    assert reaberturas == []


def test_ponto_persistido_e_ack_idempotente(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "conversas.json")
    conversas.recarregar()
    cid = conversas.criar("Criar arquivo")
    conversas.acrescentar(cid, "user", "Criar arquivo", requisicao_id="pedido-1")
    assert conversas.localizar_requisicao("pedido-1") == cid
    conversas.atualizar_turno_pendente(
        cid, passo="criar arquivo", situacao="Executando",
        conferir_acao=True)
    conversas.recarregar()  # simula outro processo/reabertura
    ponto = conversas.turno_pendente(cid)
    assert ponto["passo"] == "criar arquivo"
    assert ponto["conferir_acao"] is True
    assert len(conversas.abrir(cid)) == 1
    conversas.acrescentar(cid, "user", "Continue")
    assert "confirme o estado antes de repetir" in conversas.contexto_retomada(cid)
    conversas.acrescentar(cid, "emily", "Arquivo criado.")
    assert conversas.turno_pendente(cid) is None
    assert conversas.contexto_retomada(cid) == ""
    conversas.recarregar()


def test_conversa_casual_nao_mostra_wifi_ao_aguardar_resposta(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "casual.json")
    conversas.recarregar()
    cid = conversas.criar("Desabafo")
    conversas.acrescentar(cid, "user", "Conversei com uma amiga hoje")
    assert conversas.turno_pendente(cid) is not None  # mensagem recuperável
    assert conversas.turno_pendente_visivel(cid) is None
    assert next(c for c in conversas.listar() if c["id"] == cid)["pendente"] is False

    conversas.atualizar_turno_pendente(cid, passo="Abrindo o site", tarefa=True)
    assert conversas.turno_pendente_visivel(cid) is not None
    assert next(c for c in conversas.listar() if c["id"] == cid)["pendente"] is True
    conversas.acrescentar(cid, "emily", "Concluído")
    assert conversas.turno_pendente_visivel(cid) is None
    conversas.recarregar()


def test_regeneracao_interrompida_tambem_deixa_ponto_de_retomada(tmp_path, monkeypatch):
    import conversas

    monkeypatch.setattr(conversas, "ARQUIVO", tmp_path / "regeneracao.json")
    conversas.recarregar()
    cid = conversas.criar("Refaça")
    conversas.acrescentar(cid, "user", "Refaça")
    conversas.acrescentar(cid, "emily", "Primeira resposta")
    originais = conversas.abrir(cid)
    corte = conversas.truncar_para_regenerar(cid, 1)
    assert conversas.turno_pendente(cid)["passo"] == "Regenerando a resposta"
    assert conversas.restaurar_regeneracao_falha(
        cid, corte["indice_usuario"], corte["ramo"], originais)
    assert conversas.turno_pendente(cid) is None
    conversas.recarregar()


def test_erro_apos_acao_fica_incerto_em_vez_de_autorizar_retry(monkeypatch):
    import ferramentas

    def falhar():
        raise TimeoutError("ACK perdido")

    ferramenta = SimpleNamespace(
        nome="teste_mutacao", grupo="arquivo", somente_leitura=False,
        destrutiva=False, obrigatorios=[], executar=falhar)
    monkeypatch.setitem(ferramentas.CATALOGO, "teste_mutacao", ferramenta)
    monkeypatch.setattr(ferramentas, "_carregar_cloud_se_preciso", lambda **_k: None)
    resultado = ferramentas.executar_estruturado("teste_mutacao", {})
    assert resultado.ok is False
    assert resultado.erro == "resultado_incerto"
    assert "Confira o estado" in resultado.texto


def test_consulta_transitoria_reconecta_sem_duplicar_acao(monkeypatch):
    import ferramentas

    chamadas = []
    eventos = []

    def consultar():
        chamadas.append(True)
        if len(chamadas) < 3:
            raise TimeoutError("sem rede")
        return "Encontrado"

    ferramenta = SimpleNamespace(
        nome="teste_consulta", grupo="pesquisa", somente_leitura=True,
        destrutiva=False, obrigatorios=[], executar=consultar)
    monkeypatch.setitem(ferramentas.CATALOGO, "teste_consulta", ferramenta)
    monkeypatch.setattr(ferramentas, "_carregar_cloud_se_preciso", lambda **_k: None)
    monkeypatch.setattr(ferramentas.time, "sleep", lambda _segundos: None)
    resultado = ferramentas.executar_estruturado(
        "teste_consulta", {}, contexto={"on_reconexao":
            lambda tentativa, limite: eventos.append((tentativa, limite))})
    assert resultado.ok is True
    assert resultado.texto == "Encontrado"
    assert len(chamadas) == 3
    assert eventos == [(1, 3), (2, 3), (0, 3)]


def test_falha_do_modelo_mantem_pedido_e_mostra_erro(monkeypatch):
    import ferramentas
    import llm
    import modelo

    monkeypatch.setattr(llm, "chamar_com_ferramentas",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            llm.ErroTransporte("connection timeout")))
    monkeypatch.setattr(ferramentas, "esquemas_com_dominios", lambda *_a, **_k: [])
    monkeypatch.setattr(modelo, "_mensagens_para_turno", lambda _extra="": [])
    monkeypatch.setattr(modelo, "_promessa_pendente_consumir", lambda: "")
    eventos = []
    anterior = list(modelo.historico)
    try:
        modelo.historico.clear()
        resposta = modelo.conversar_com_ferramentas(
            "Olá, Emily", on_progresso=lambda fase, dados: eventos.append((fase, dados)))
        assert "não voltou" in resposta
        assert modelo.historico[0]["content"] == "Olá, Emily"
        assert modelo.historico[-1]["content"] == resposta
        assert any(fase == "erro_conexao" for fase, _ in eventos)
    finally:
        modelo.historico[:] = anterior


def test_voz_reconecta_antes_do_primeiro_audio(monkeypatch):
    import voz

    chamadas = []
    eventos = []

    def audio(_fluxo, _formato):
        chamadas.append(True)
        if len(chamadas) == 1:
            raise TimeoutError("sem áudio")
        yield b"\x01\x02"

    monkeypatch.setattr(voz, "_tentativas_tts", lambda: 2)
    monkeypatch.setattr(voz, "_pausa_retry_tts", lambda: 0)
    monkeypatch.setattr(voz, "_sessao_fish_da_thread", lambda: object())
    monkeypatch.setattr(voz, "_requisicao_fish", lambda *_a, **_k: object())
    monkeypatch.setattr(voz, "_abrir_tts_http", lambda *_a: object())
    monkeypatch.setattr(voz, "_iterar_pcm_da_fish", audio)
    monkeypatch.setattr(voz, "_aplicar_volume", lambda dados, _largura: dados)

    saida = list(voz.gerar_audio_stream(
        "Resposta", on_conexao=lambda fase, dados: eventos.append((fase, dados))))
    assert saida == [b"\x01\x02"]
    assert [fase for fase, _ in eventos] == ["reconectando", "reconectado"]
    assert len(chamadas) == 2
