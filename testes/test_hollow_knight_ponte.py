import time


def _headers(token="segredo"):
    return {"Authorization": f"Bearer {token}"}


def test_audio_stream_entrega_chunk_antes_do_fim_e_preserva_wav_legado():
    import threading
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    fluxo = modulo._AudioEmFluxo(taxa=44100, canais=1, largura=2)
    audio_id = "stream-teste"
    with ponte._audios_lock:
        ponte._audios_stream[audio_id] = fluxo

    liberar_final = threading.Event()

    def produzir():
        fluxo.adicionar(b"\x01\x02" * 100)
        liberar_final.wait(timeout=2)
        fluxo.adicionar(b"\x03\x04" * 100)
        fluxo.finalizar()

    worker = threading.Thread(target=produzir, daemon=True)
    worker.start()
    cliente = ponte.app.test_client()
    resposta = cliente.get(
        f"/v1/hollow-knight/audio-stream/{audio_id}",
        headers=_headers(), buffered=False,
    )
    primeiro = next(iter(resposta.response))

    assert primeiro == b"\x01\x02" * 100
    assert not fluxo._concluido

    liberar_final.set()
    restante = b"".join(resposta.response)
    worker.join(timeout=1)
    assert restante == b"\x03\x04" * 100

    legado = cliente.get(
        f"/v1/hollow-knight/audio/{audio_id}", headers=_headers())
    assert legado.status_code == 200
    assert legado.data.startswith(b"RIFF")
    assert legado.data[8:12] == b"WAVE"


def test_audio_wav_aguarda_fallback_apos_stream_vazio():
    import threading
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    fluxo = modulo._AudioEmFluxo()
    fluxo.finalizar()
    audio_id = "fallback-atrasado"
    with ponte._audios_lock:
        ponte._audios_stream[audio_id] = fluxo

    wav = modulo.empacotar_wav(b"\x00\x00" * 100)

    def publicar():
        time.sleep(0.08)
        with ponte._audios_lock:
            ponte._audios[audio_id] = (time.time(), wav)

    threading.Thread(target=publicar, daemon=True).start()
    resposta = ponte.app.test_client().get(
        f"/v1/hollow-knight/audio/{audio_id}", headers=_headers())

    assert resposta.status_code == 200
    assert resposta.data == wav


def test_api_exige_token_e_cria_sessao():
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    ponte = PonteHollowKnight(token="segredo")
    cliente = ponte.app.test_client()
    assert cliente.get("/v1/hollow-knight/status").status_code == 401
    resposta = cliente.post(
        "/v1/hollow-knight/sessao",
        headers=_headers(),
        json={"campanha_id": "slot-1", "versao_mod": "0.1.0"},
    )
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["protocolo"] == 1
    assert dados["sessao_id"]


def test_servidor_aceita_porta_efemera(monkeypatch, tmp_path):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    monkeypatch.setattr(modulo, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(modulo, "TOKEN_NO_MOD", tmp_path / "mod/token.txt")
    ponte = modulo.PonteHollowKnight(token="segredo")
    ponte.iniciar(porta=0)
    try:
        assert ponte._servidor.server_port > 0
    finally:
        ponte.encerrar()


def test_evento_duplicado_e_comando_de_cena_antiga_sao_descartados(monkeypatch):
    from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

    ponte = PonteHollowKnight(token="segredo")
    cliente = ponte.app.test_client()
    sid = cliente.post(
        "/v1/hollow-knight/sessao", headers=_headers(), json={}
    ).get_json()["sessao_id"]
    evento = {
        "id": "e-1", "cena_id": "Tutorial_01:1", "tipo": "chamou_emily",
        "dados": {"pergunta": "o que acha daqui?"},
    }
    corpo = {"sessao_id": sid, "eventos": [evento, evento]}
    resposta = cliente.post(
        "/v1/hollow-knight/eventos", headers=_headers(), json=corpo
    ).get_json()
    assert resposta["aceitos"] == 1

    ponte.estado.enfileirar_comando(
        sid, "fala", {"texto": "antiga"}, cena_id="Tutorial_01:1"
    )
    ponte.estado.receber_eventos(
        sid,
        [
            __import__(
                "hollow_knight_emily.python.hollow_knight_protocolo",
                fromlist=["EventoJogo"],
            ).EventoJogo.de_json(
                sid, {"id": "e-2", "cena_id": "Town:2", "tipo": "estado", "dados": {}}
            )
        ],
    )
    comandos = cliente.get(
        f"/v1/hollow-knight/comandos?sessao_id={sid}&desde=0&cena_id=Town:2",
        headers=_headers(),
    ).get_json()["comandos"]
    assert all(c.get("cena_id") != "Tutorial_01:1" for c in comandos)


def test_worker_usa_fallback_e_entrega_fala_sem_tts(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    monkeypatch.setattr(ponte.cerebro, "responder", lambda *_a: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(modulo, "gerar_wav_fish", lambda _texto: b"")
    sessao = ponte.estado.criar_sessao("slot-1", "teste")
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "m1", "tipo": "morte", "cena_id": "Crossroads:4", "dados": {}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._thread_worker = __import__("threading").Thread(target=ponte._worker, daemon=True)
    ponte._thread_worker.start()
    ponte._fila.put(evento)
    limite = time.time() + 2
    comandos = []
    while time.time() < limite and not comandos:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Crossroads:4")
        time.sleep(0.01)
    ponte._parar.set()
    ponte._thread_worker.join(timeout=1)
    assert comandos and comandos[-1]["tipo"] == "fala"
    assert comandos[-1]["dados"]["texto"]


def test_worker_entrega_marco_persistente_mesmo_apos_troca_de_cena(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "teste")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "boss-1", "tipo": "boss_derrotado", "cena_id": "Boss:1",
         "dados": {"nome": "Falso Cavaleiro", "persistente": True}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte.estado.receber_eventos(sessao.id, [
        modulo.EventoJogo.de_json(
            sessao.id,
            {"id": "estado-2", "tipo": "estado", "cena_id": "Reward:2", "dados": {}},
        )
    ])
    monkeypatch.setattr(
        ponte.cerebro, "responder",
        lambda *_a: {"falar": False, "texto": "", "emocao": "neutra", "acao": "nenhuma"},
    )
    ponte._fila.put(evento)
    import threading
    worker = threading.Thread(target=ponte._worker, daemon=True)
    worker.start()
    limite = time.time() + 1
    comandos = []
    while time.time() < limite and not comandos:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Reward:2")
        time.sleep(0.01)
    ponte._parar.set()
    worker.join(timeout=1)
    assert comandos
    assert "Falso Cavaleiro" in comandos[-1]["dados"]["texto"]
    assert comandos[-1]["cena_id"] == "*"
    assert ponte.estado.comandos_desde(sessao.id, 0, "OutraSala:3")


def test_marco_persistente_usa_fila_prioritaria():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    ponte.JANELA_LOTE = 0  # 0.4.9: teste legado, sem janela de lote
    sessao = ponte.estado.criar_sessao("slot-1", "teste")
    ponte.estado.atualizar_estado(sessao.id, {"modo_fala": "tagarela"})
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "magia-1", "tipo": "magia_adquirida", "cena_id": "Temple:1",
         "dados": {"nome": "Espírito Vingativo", "persistente": True}},
    )
    assert ponte._agendar(evento)
    assert ponte._fila.empty()
    assert ponte._fila_prioritaria.get_nowait() is evento


def test_empacotar_wav_preserva_formato():
    import io
    import wave
    from hollow_knight_emily.python.hollow_knight_audio import empacotar_wav

    wav = empacotar_wav(b"\x00\x00" * 100, taxa=22050, canais=1, largura=2)
    with wave.open(io.BytesIO(wav), "rb") as arquivo:
        assert arquivo.getframerate() == 22050
        assert arquivo.getnchannels() == 1
        assert arquivo.getsampwidth() == 2
        assert arquivo.getnframes() == 100


def test_audio_hollow_knight_usa_api_publica_sem_reproduzir(monkeypatch):
    import sys
    import types
    from hollow_knight_emily.python import hollow_knight_audio

    modulo_voz = types.SimpleNamespace(
        gerar_audio_pacote=lambda texto: (b"\x00\x00" * 20, 16000, 1, 2)
    )
    monkeypatch.setitem(sys.modules, "voz", modulo_voz)
    wav = hollow_knight_audio.gerar_wav_fish("teste")
    assert wav.startswith(b"RIFF")
    assert len(wav) > 44


def test_gravacao_de_token_restringe_permissao(monkeypatch, tmp_path):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    monkeypatch.setattr(modulo, "RUNTIME", tmp_path / "runtime")
    monkeypatch.setattr(modulo, "TOKEN_NO_MOD", tmp_path / "mod/token.txt")
    ponte = modulo.PonteHollowKnight(token="segredo")
    ponte._gravar_token()
    assert (tmp_path / "runtime/token.txt").read_text() == "segredo"
    assert (tmp_path / "mod/token.txt").read_text() == "segredo"
    assert (tmp_path / "runtime/token.txt").stat().st_mode & 0o077 == 0


def test_ponte_reutiliza_token_instalado(monkeypatch, tmp_path):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "token.txt").write_text("token-estavel", encoding="utf-8")
    monkeypatch.setattr(modulo, "RUNTIME", runtime)
    monkeypatch.setattr(modulo, "TOKEN_NO_MOD", tmp_path / "mod/token.txt")
    monkeypatch.delenv("EMILY_HK_TOKEN", raising=False)
    assert modulo.PonteHollowKnight().token == "token-estavel"


def test_main_nao_disputa_porta_quando_servico_externo_esta_ativo(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    monkeypatch.setattr(modulo, "_PONTE", None)
    monkeypatch.setattr(modulo, "servico_externo_ativo", lambda: True)
    assert modulo.iniciar() is None
    assert modulo._PONTE is None


def test_servico_permanente_aceita_rotacao_local_de_token(monkeypatch, tmp_path):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    token_mod = tmp_path / "mod/token.txt"
    token_mod.parent.mkdir()
    (runtime / "token.txt").write_text("token-antigo", encoding="utf-8")
    token_mod.write_text("token-antigo", encoding="utf-8")
    monkeypatch.setattr(modulo, "RUNTIME", runtime)
    monkeypatch.setattr(modulo, "TOKEN_NO_MOD", token_mod)
    monkeypatch.delenv("EMILY_HK_TOKEN", raising=False)
    ponte = modulo.PonteHollowKnight(token="token-antigo")
    token_mod.write_text("token-novo-da-compilada", encoding="utf-8")
    cliente = ponte.app.test_client()
    resposta = cliente.get(
        "/v1/hollow-knight/status",
        headers={"Authorization": "Bearer token-novo-da-compilada"},
    )
    assert resposta.status_code == 200


def test_v045_worker_entrega_texto_antes_do_tts_terminar(monkeypatch):
    import threading
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    iniciou_tts = threading.Event()
    liberar_tts = threading.Event()

    def tts_lento(_texto):
        iniciou_tts.set()
        liberar_tts.wait(timeout=2)
        return b"RIFF" + b"\x00" * 80

    ponte = modulo.PonteHollowKnight(token="segredo", gerador_audio=tts_lento)
    ponte.JANELA_LOTE = 0  # 0.4.9: teste legado, sem janela de lote
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.5")
    ponte.estado.atualizar_estado(sessao.id, {"voz": True, "modo_fala": "normal"})
    monkeypatch.setattr(
        ponte.cerebro, "responder",
        lambda *_a: {"falar": True, "texto": "Vi isso agora.", "emocao": "curiosa", "acao": "nenhuma"},
    )
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "rapido-1", "tipo": "boss_encontrado", "cena_id": "Arena:1",
         "dados": {"nome": "Hornet"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    limite = time.time() + 1
    comandos = []
    while time.time() < limite and not comandos:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:1")
        time.sleep(0.01)
    assert comandos and comandos[0]["tipo"] == "fala"
    assert comandos[0]["dados"]["texto"] == "Vi isso agora."
    assert comandos[0]["dados"]["audio_id"] == ""
    assert iniciou_tts.wait(timeout=1)
    liberar_tts.set()
    limite = time.time() + 1
    while time.time() < limite:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:1")
        if any(c["tipo"] == "audio" for c in comandos):
            break
        time.sleep(0.01)
    ponte.encerrar()
    assert any(c["tipo"] == "audio" for c in comandos)
    audio = next(c for c in comandos if c["tipo"] == "audio")
    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert audio["dados"]["fala_sequencia"] == fala["sequencia"]


def test_v045_banco_npc_e_boss_usam_fila_prioritaria_real():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    # 0.4.8: sentar em banco deixou de gerar fala própria, então o representante
    # de evento urgente passou a ser quase_morte.
    for numero, tipo in enumerate(("quase_morte", "npc_dialogo", "boss_encontrado", "boss_luta"), 1):
        ponte = modulo.PonteHollowKnight(token="segredo")
        ponte.JANELA_LOTE = 0  # 0.4.9: teste legado, sem janela de lote
        sessao = ponte.estado.criar_sessao("slot-1", "0.4.5")
        ponte.estado.atualizar_estado(sessao.id, {"modo_fala": "normal"})
        dados = {"prioridade": 76} if tipo == "boss_luta" else {}
        evento = modulo.EventoJogo.de_json(
            sessao.id,
            {"id": f"prio-{numero}", "tipo": tipo, "cena_id": "Arena:1", "dados": dados},
        )
        assert ponte._agendar(evento)
        assert ponte._fila.empty()
        assert ponte._fila_prioritaria.get_nowait() is evento


def test_v046_ponte_marca_voz_prevista_e_confirma_audio_vazio():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo", gerador_audio=lambda _texto: b"")
    ponte.JANELA_LOTE = 0  # 0.4.9: teste legado, sem janela de lote
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.6")
    ponte.estado.atualizar_estado(sessao.id, {"voz": True, "modo_fala": "normal"})
    ponte.cerebro.responder = lambda *_a: {
        "falar": True, "texto": "Comentario curto.", "emocao": "curiosa", "acao": "nenhuma",
    }
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v046-voz-1", "tipo": "boss_encontrado", "cena_id": "Arena:1",
         "dados": {"nome": "Hornet"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    limite = time.time() + 3
    comandos = []
    while time.time() < limite:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:1")
        if any(c["tipo"] == "audio" for c in comandos):
            break
        time.sleep(0.01)
    ponte.encerrar()
    fala = next(c for c in comandos if c["tipo"] == "fala")
    audio = next(c for c in comandos if c["tipo"] == "audio")
    assert fala["dados"]["voz_prevista"] is True
    assert audio["dados"]["audio_id"] == ""
    assert audio["dados"]["fala_sequencia"] == fala["sequencia"]


def test_v046_ponte_sem_voz_nao_reserva_audio():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo", gerador_audio=lambda _t: b"")
    ponte.JANELA_LOTE = 0  # 0.4.9: teste legado, sem janela de lote
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.6")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    ponte.cerebro.responder = lambda *_a: {
        "falar": True, "texto": "So legenda.", "emocao": "neutra", "acao": "nenhuma",
    }
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v046-mudo-1", "tipo": "boss_encontrado", "cena_id": "Arena:2",
         "dados": {"nome": "Hornet"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    limite = time.time() + 2
    comandos = []
    while time.time() < limite:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:2")
        if any(c["tipo"] == "fala" for c in comandos):
            break
        time.sleep(0.01)
    time.sleep(0.4)
    comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:2")
    ponte.encerrar()
    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert fala["dados"]["voz_prevista"] is False
    assert not any(c["tipo"] == "audio" for c in comandos)


def test_v046_tagarela_nao_empilha_enquanto_emily_ainda_fala():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.6")
    ponte.estado.atualizar_estado(sessao.id, {"modo_fala": "tagarela"})
    ponte.estado.enfileirar_comando(sessao.id, "fala", {"texto": "ocupada"}, cena_id="Arena:1")
    pendente = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v046-tag-1", "tipo": "comentario_tagarela", "cena_id": "Arena:1",
         "dados": {"zona": "TOWN", "prioridade": 18}},
    )
    assert not ponte._agendar(pendente)
    ponte.estado.confirmar(sessao.id, 1)
    assert ponte._agendar(pendente)


def _esperar_fala(ponte, sid, cena, limite=3.0):
    prazo = time.time() + limite
    while time.time() < prazo:
        comandos = ponte.estado.comandos_desde(sid, 0, cena)
        if any(c["tipo"] == "fala" for c in comandos):
            return comandos
        time.sleep(0.01)
    return ponte.estado.comandos_desde(sid, 0, cena)


def test_v047_ponte_reescreve_fala_que_vira_relatorio_de_status(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.7")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    chamadas = []

    def responder(_evento, _sessao, **kwargs):
        estrito = bool(kwargs.get("proibir_estatisticas"))
        chamadas.append(estrito)
        if estrito:
            return {"falar": True, "texto": "Tá voando nessa luta, hein.",
                    "emocao": "animada", "acao": "nenhuma"}
        return {"falar": True, "texto": "Você está com 7 máscaras e deu 5 golpes.",
                "emocao": "neutra", "acao": "nenhuma"}

    monkeypatch.setattr(ponte.cerebro, "responder", responder)
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v047-stat-1", "tipo": "boss_luta", "cena_id": "Arena:9",
         "dados": {"nome": "Hornet", "padrao": "sequencia_sem_dano",
                   "golpes_desde_comentario": 8, "segundos_sem_dano": 24}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    comandos = _esperar_fala(ponte, sessao.id, "Arena:9")
    ponte.encerrar()
    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert fala["dados"]["texto"] == "Tá voando nessa luta, hein."
    assert chamadas == [False, True]


def test_v047_ponte_prefere_silencio_a_entregar_relatorio(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.7")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    monkeypatch.setattr(
        ponte.cerebro, "responder",
        lambda *_a, **_k: {"falar": True, "texto": "Levou 3 impactos em 90 segundos.",
                           "emocao": "neutra", "acao": "nenhuma"},
    )
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v047-stat-2", "tipo": "observacao", "cena_id": "Arena:10",
         "dados": {"prioridade": 34, "padrao": "danos_repetidos"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    limite = time.time() + 1.5
    while time.time() < limite:
        if ponte.estado.comandos_desde(sessao.id, 0, "Arena:10"):
            break
        time.sleep(0.01)
    comandos = ponte.estado.comandos_desde(sessao.id, 0, "Arena:10")
    ponte.encerrar()
    # Sem observação com fallback próprio e com o modelo insistindo no painel,
    # ela fica quieta em vez de narrar números.
    assert not any(c["tipo"] == "fala" for c in comandos)


def test_v047_contexto_do_cerebro_nao_leva_numeros_de_painel():
    import json as _json
    from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight

    limpo = CerebroHollowKnight._dados_para_ia("boss_luta", {
        "nome": "Hornet", "padrao": "sequencia_sem_dano",
        "golpes_total": 12, "dano_recebido": 3, "segundos_sem_dano": 24,
        "vida_atual": 4, "vida_maxima": 9, "geo": 1200, "alma": 88,
    })
    for campo in ("golpes_total", "dano_recebido", "segundos_sem_dano",
                  "vida_atual", "vida_maxima", "geo", "alma"):
        assert campo not in limpo
    assert limpo["nome"] == "Hornet"
    assert limpo["como_o_vitor_esta"] == [
        "vida baixa", "faz um bom tempo que ele não toma dano",
    ]
    assert not __import__("re").search(r"\d", _json.dumps(limpo, ensure_ascii=False))


def test_v048_localizacao_atual_vem_de_qualquer_evento():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.8")
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v048-loc-1", "tipo": "area_nova", "cena_id": "Fungus1_04:7",
         "dados": {"zona": "GREEN_PATH", "zona_nome": "Caminho Verde"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    estado = ponte.estado.obter(sessao.id).estado
    # Sem esperar o snapshot de `estado`: a troca de área é percebida na hora.
    assert estado["zona"] == "GREEN_PATH"
    assert estado["zona_nome"] == "Caminho Verde"
    assert estado["cena_atual"] == "Fungus1_04:7"

    troca = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v048-loc-2", "tipo": "area_nova", "cena_id": "Crossroads_04:8",
         "dados": {"zona": "CROSSROADS", "zona_nome": "Encruzilhada Esquecida"}},
    )
    ponte.estado.receber_eventos(sessao.id, [troca])
    estado = ponte.estado.obter(sessao.id).estado
    assert estado["zona_nome"] == "Encruzilhada Esquecida"
    assert estado["cena_atual"] == "Crossroads_04:8"


def test_v048_cerebro_recebe_localizacao_atual(monkeypatch):
    import json as _json
    import sys
    import types as _types
    from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight

    capturado = {}

    def chamar(mensagens, **kwargs):
        capturado["mensagens"] = mensagens
        return '{"falar": true, "texto": "Opa, voltou.", "emocao": "animada", "acao": "nenhuma"}'

    falso_modelo = _types.SimpleNamespace(ROTA_AGENTE_JOGO="agente_jogo", _chamar_llm=chamar)
    monkeypatch.setitem(sys.modules, "modelo", falso_modelo)
    evento = _types.SimpleNamespace(tipo="comentario_tagarela", dados={}, cena_id="Town:3")
    sessao = _types.SimpleNamespace(
        campanha_id="slot-1",
        estado={"modelo": "", "zona": "TOWN", "zona_nome": "Boca do Rei", "cena_atual": "Town:3"},
    )
    CerebroHollowKnight().responder(evento, sessao)
    contexto = _json.loads(capturado["mensagens"][1]["content"])
    assert contexto["localizacao_atual"] == {
        "zona": "TOWN", "nome": "Boca do Rei", "cena": "Town:3",
    }


def test_v048_saudacao_e_entregue_ate_com_a_emily_silenciosa():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.8")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "muda"})
    monkeypatch_responder = {
        "falar": True, "texto": "Opa, voltou. Vamos ver no que dá hoje.",
        "emocao": "animada", "acao": "nenhuma",
    }
    ponte.cerebro.responder = lambda *_a, **_k: monkeypatch_responder
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v048-bv-1", "tipo": "boas_vindas", "cena_id": "Town:1",
         "dados": {"zona": "TOWN", "zona_nome": "Boca do Rei", "persistente": True}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    comandos = _esperar_fala(ponte, sessao.id, "Town:1")
    ponte.encerrar()
    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert "voltou" in fala["dados"]["texto"]
    assert fala["cena_id"] == "*"


def test_v048_comando_de_fala_carrega_zona_para_validacao_final_no_mod():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.8")
    ponte.estado.atualizar_estado(sessao.id, {
        "voz": False, "modo_fala": "normal",
        "zona": "GREEN_PATH", "zona_nome": "Caminho Verde",
    })
    ponte.cerebro.responder = lambda *_a, **_k: {
        "falar": True, "texto": "Esse lugar mudou completamente o clima.",
        "emocao": "curiosa", "acao": "nenhuma",
    }
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v048-zona-fala", "tipo": "area_nova", "cena_id": "Fungus1_04:7",
         "dados": {"zona": "GREEN_PATH", "zona_nome": "Caminho Verde"}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    comandos = _esperar_fala(ponte, sessao.id, "Fungus1_04:7")
    ponte.encerrar()

    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert fala["dados"]["zona"] == "GREEN_PATH"
    assert fala["dados"]["validar_zona"]
    assert not fala["dados"]["persistente"]


def test_v048_somente_eventos_realmente_independentes_sobrevivem_a_outra_regiao():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    assert {"boas_vindas", "morte", "charm_adquirido", "chamou_emily"} == set(
        modulo.PonteHollowKnight.EVENTOS_INDEPENDENTES_DE_ZONA
    )


def test_v049_dois_eventos_proximos_viram_uma_unica_fala():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    ponte.JANELA_LOTE = 0.15
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.9")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    recebidos = []

    def responder(evento, _sessao, **_kw):
        recebidos.append(evento)
        return {
            "falar": True,
            "texto": "Amuleto novo saindo direto dessa conversa? Boa escolha.",
            "emocao": "curiosa", "acao": "nenhuma",
        }

    ponte.cerebro.responder = responder
    charm = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v049-charm", "tipo": "charm_adquirido", "cena_id": "Town:2",
         "dados": {"charm": "Fragilidade Empoderada"}},
    )
    npc = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v049-npc", "tipo": "npc_dialogo", "cena_id": "Town:2",
         "dados": {"nome": "Sly", "zona": "TOWN"}},
    )
    ponte.estado.receber_eventos(sessao.id, [charm, npc])
    assert ponte._agendar(charm)
    assert ponte._agendar(npc)
    ponte._iniciar_workers()
    comandos = _esperar_fala(ponte, sessao.id, "Town:2", limite=5.0)
    ponte.encerrar()

    falas = [c for c in comandos if c["tipo"] == "fala"]
    assert len(falas) == 1
    assert len(recebidos) == 1
    assert recebidos[0].tipo == "eventos_multiplos"
    tipos = {item["tipo"] for item in recebidos[0].dados["resumo"]}
    assert tipos == {"charm_adquirido", "npc_dialogo"}


def test_v049_morte_nao_espera_a_janela_do_lote():
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    # Janela gigante de propósito: se a morte dependesse dela, travava aqui.
    ponte.JANELA_LOTE = 30.0
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.9")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    morte = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v049-morte", "tipo": "morte", "cena_id": "Crossroads_01:1",
         "dados": {"persistente": True}},
    )
    ponte.estado.receber_eventos(sessao.id, [morte])
    assert ponte._agendar(morte)
    assert ponte._fila_prioritaria.get_nowait() is morte
    with ponte._lotes_lock:
        assert not ponte._lotes


def test_v049_fallback_do_lote_herda_o_evento_mais_importante():
    from hollow_knight_emily.python.hollow_knight_politica import PoliticaComentarios

    politica = PoliticaComentarios()
    texto = politica.fallback("eventos_multiplos", {"resumo": [
        {"tipo": "npc_dialogo", "dados": {"nome": "Sly"}},
        {"tipo": "boss_encontrado",
         "dados": {"nome": "Nosk", "identidade_confirmada": True}},
    ]})
    assert "Nosk" in texto


def test_v049_dados_para_ia_do_lote_esconde_numeros_do_painel():
    import json as _json
    from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight

    dados = CerebroHollowKnight._dados_para_ia("eventos_multiplos", {
        "resumo": [
            {"tipo": "dano", "dados": {"dano": 3, "vida_atual": 2, "vida_maxima": 5}},
            {"tipo": "area_nova", "dados": {"zona": "GREEN_PATH"}},
        ],
        "zona": "GREEN_PATH",
    })
    assert len(dados["acontecimentos"]) == 2
    serializado = _json.dumps(dados, ensure_ascii=False)
    for campo in ("vida_maxima", "vida_atual", '"dano":'):
        # "tipo": "dano" segue presente (é o acontecimento); o campo numérico
        # "dano": 3 é que não pode vazar para o modelo.
        assert campo not in serializado
    assert dados["como_o_vitor_esta"] == [
        "vida baixa", "levou um golpe pesado de uma vez",
    ]


def test_v0410_boss_nao_fica_mudo_quando_modelo_insiste_no_painel(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    ponte.JANELA_LOTE = 0  # sem janela de lote neste teste
    sessao = ponte.estado.criar_sessao("slot-1", "0.4.10")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    # O modelo insiste no relatório até na reescrita: antes disso deixava o
    # chefe totalmente sem reação (caso da Radiância no Panteão).
    monkeypatch.setattr(
        ponte.cerebro, "responder",
        lambda *_a, **_k: {
            "falar": True,
            "texto": "Ele está com 2280 de vida e você deu 12 golpes em 90 segundos.",
            "emocao": "neutra", "acao": "nenhuma",
        },
    )
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "v0410-boss-1", "tipo": "boss_encontrado", "cena_id": "GG_Radiance:3",
         "dados": {"nome": "Radiância Absoluta", "identidade_confirmada": True}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    ponte._iniciar_workers()
    assert ponte._agendar(evento)
    comandos = _esperar_fala(ponte, sessao.id, "GG_Radiance:3")
    ponte.encerrar()

    fala = next(c for c in comandos if c["tipo"] == "fala")
    assert "Radiância Absoluta" in fala["dados"]["texto"]


def test_v0410_pistas_de_fase_e_morte_com_luta():
    from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight

    fase = CerebroHollowKnight._qualitativos("boss_fase", {
        "vida_chefe_frac": 0.2,
        "dica": "a arena virou uma subida de plataformas",
    })
    assert "o chefe tá no fim das forças" in fase
    assert "a arena virou uma subida de plataformas" in fase

    morte = CerebroHollowKnight._qualitativos("morte", {"luta": "Radiância Absoluta"})
    assert "ele caiu lutando contra Radiância Absoluta" in morte

    # O snapshot de estado não leva pausado/em_gameplay/progresso/vida:
    # pausado mentia no slow-motion da luta e virava "tu tava no menu".
    estado = CerebroHollowKnight._estado_para_ia({
        "pausado": True, "em_gameplay": False, "progresso": {"a": 1},
        "vida_atual": 3, "zona": "TOWN", "modo_fala": "normal",
    })
    for campo in ("pausado", "em_gameplay", "progresso", "vida_atual"):
        assert campo not in estado
    assert estado["zona"] == "TOWN"


def test_v0410_politica_aceita_fase_de_chefe():
    from hollow_knight_emily.python.hollow_knight_politica import (
        EVENTOS_QUE_NAO_FICAM_MUTOS,
        PoliticaComentarios,
    )

    assert "boss_fase" in EVENTOS_QUE_NAO_FICAM_MUTOS
    politica = PoliticaComentarios(relogio=lambda: 1000.0)
    assert politica.deve_responder(
        "boss_fase", {"nome": "Hornet", "identidade_confirmada": True}, "normal")
    texto = politica.fallback(
        "boss_fase", {"nome": "Hornet", "identidade_confirmada": True})
    assert "Hornet" in texto
