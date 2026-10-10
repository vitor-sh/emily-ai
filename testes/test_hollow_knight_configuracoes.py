import json
import re
import sys
import types
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def _headers(token="segredo"):
    return {"Authorization": f"Bearer {token}"}


def test_configuracao_de_sessao_normaliza_e_persiste_modelo(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    monkeypatch.setattr(
        modulo, "normalizar_modelo", lambda valor: "modelo-ok" if valor == "modelo-ok" else ""
    )
    ponte = modulo.PonteHollowKnight(token="segredo")
    cliente = ponte.app.test_client()
    resposta = cliente.post(
        "/v1/hollow-knight/sessao",
        headers=_headers(),
        json={
            "campanha_id": "slot-1",
            "configuracao": {
                "modo_fala": "tagarela",
                "modelo": "modelo-ok",
                "voz": False,
                "volume": 4,
            },
        },
    )
    assert resposta.status_code == 200
    sid = resposta.get_json()["sessao_id"]
    estado = ponte.estado.obter(sid).estado
    assert estado == {
        "modo_fala": "tagarela",
        "modelo": "modelo-ok",
        "voz": False,
        "volume": 2.0,
    }

    cliente.post(
        "/v1/hollow-knight/eventos",
        headers=_headers(),
        json={
            "sessao_id": sid,
            "configuracao": {
                "modo_fala": "inventado",
                "modelo": "modelo-inexistente",
                "voz": "não",
                "volume": -2,
            },
            "eventos": [],
        },
    )
    assert ponte.estado.obter(sid).estado == {
        "modo_fala": "normal",
        "modelo": "",
        "voz": True,
        "volume": 0.0,
    }


def test_cerebro_aplica_override_sem_mudar_rota_global(monkeypatch):
    from hollow_knight_emily.python.hollow_knight_cerebro import CerebroHollowKnight

    capturado = {}

    def chamar(_mensagens, **kwargs):
        capturado.update(kwargs)
        return '{"falar": true, "texto": "Oi.", "emocao": "neutra", "acao": "nenhuma"}'

    falso_modelo = types.SimpleNamespace(
        ROTA_AGENTE_JOGO="agente_jogo",
        _chamar_llm=chamar,
        _bloco_memoria_unificada=lambda *_a, **_k: "",
        _registrar_memoria_unificada=lambda *_a, **_k: None,
    )
    monkeypatch.setitem(sys.modules, "modelo", falso_modelo)
    evento = types.SimpleNamespace(tipo="area_nova", dados={}, cena_id="Town:1")
    sessao = types.SimpleNamespace(
        campanha_id="slot-1", estado={"modelo": "cx/gpt-5.6-luna"}
    )
    resposta = CerebroHollowKnight().responder(evento, sessao)
    assert resposta["texto"] == "Oi."
    assert capturado["rota"] == "agente_jogo"
    assert capturado["model"] == "cx/gpt-5.6-luna"


def test_worker_nao_gera_audio_quando_voz_esta_desligada(monkeypatch):
    from hollow_knight_emily.python import hollow_knight_ponte as modulo

    ponte = modulo.PonteHollowKnight(token="segredo")
    sessao = ponte.estado.criar_sessao("slot-1", "teste")
    ponte.estado.atualizar_estado(sessao.id, {"voz": False, "modo_fala": "normal"})
    evento = modulo.EventoJogo.de_json(
        sessao.id,
        {"id": "voz-0", "tipo": "morte", "cena_id": "Town:1", "dados": {}},
    )
    ponte.estado.receber_eventos(sessao.id, [evento])
    monkeypatch.setattr(
        ponte.cerebro,
        "responder",
        lambda *_a: {"texto": "Eu vi isso.", "emocao": "irritada", "acao": "nenhuma"},
    )
    chamadas = []
    monkeypatch.setattr(modulo, "gerar_wav_fish", lambda texto: chamadas.append(texto) or b"wav")
    ponte._fila.put(evento)
    import threading
    import time

    worker = threading.Thread(target=ponte._worker, daemon=True)
    worker.start()
    limite = time.time() + 1
    comandos = []
    while time.time() < limite and not comandos:
        comandos = ponte.estado.comandos_desde(sessao.id, 0, "Town:1")
        time.sleep(0.01)
    ponte._parar.set()
    worker.join(timeout=1)
    assert chamadas == []
    assert comandos[-1]["dados"]["audio_id"] == ""


def test_catalogo_serializa_somente_metadados_publicos(monkeypatch, tmp_path):
    from hollow_knight_emily.python import hollow_knight_modelos as modulo

    monkeypatch.setenv("EMILY_PROVEDOR_OPENAI_MODELO", "cx/gpt-5.6-terra")
    monkeypatch.setenv("EMILY_PROVEDOR_OPENAI_MODELOS", "cx/gpt-5.6-terra,cx/gpt-5.6-luna")
    monkeypatch.setenv("EMILY_PROVEDOR_OPENAI_CHAVE", "segredo-que-nao-deve-vazar")
    destino = tmp_path / "modelos.json"
    modulo.gravar_catalogo(destino)
    dados = json.loads(destino.read_text(encoding="utf-8"))
    assert dados["modelos"] == [
        {"id": "cx/gpt-5.6-terra", "nome": "GPT 5.6 Terra"},
        {"id": "cx/gpt-5.6-luna", "nome": "GPT 5.6 Luna"},
    ]
    assert dados["padrao"] == "cx/gpt-5.6-luna"
    assert modulo.normalizar_modelo("claude-sonnet-5") == ""
    assert "segredo-que-nao-deve-vazar" not in destino.read_text(encoding="utf-8")
    assert not any("chave" in chave.lower() or "url" in chave.lower() for chave in dados)


def test_menu_documenta_aplicacao_e_range_da_faisca_nao_regride():
    menu = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    fada = (RAIZ / "hollow_knight_emily/mod/EmilyFairyController.cs").read_text(encoding="utf-8")
    for nome in (
        "Quanto Emily comenta",
        "Cérebro no Hollow Knight",
        "Integração com a IA",
        "Voz da Emily",
        "Legendas",
        "HUD do vínculo",
        "Ataques automáticos",
        "Poderes ofensivos",
        "Poderes de suporte",
        "Sugestões de ação da IA",
    ):
        assert nome in menu
    assert menu.count("Aplicação:") >= 11
    alcance = float(re.search(r"SparkRange\s*=\s*([0-9.]+)f", fada).group(1))
    assert 5.5 <= alcance <= 7.0
    assert "NearbyEnemies(11f)" not in fada


def test_prompt_hollow_knight_inclui_personalidade_canonica_da_emily():
    import modelo
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    prompt = system_hollow_knight()
    assert modelo.EMILY_PERSONALIDADE in prompt
    assert "telemetria real" in prompt.lower()
    assert "não invente" in prompt.lower()


def test_mod_rastreia_marcos_reais_e_nao_nomeia_hazard_bruto():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    rastreador = (RAIZ / "hollow_knight_emily/mod/EmilyProgressTracker.cs").read_text(encoding="utf-8")
    assert "EmilyProgressTracker" in mod
    assert "hazard_tipo_bruto" in mod
    assert "origem_confirmada = _combat != null && _combat.SourceConfirmed(_pendingDamageAt)" in mod
    assert "ResolvePendingDamage" in mod
    assert "PlayerData.TakeHealth" in mod
    ponte = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    assert "_priorityEvents" in ponte
    assert "PriorityEventTypes" in ponte
    for campo in (
        "killedFalseKnight", "fireballLevel", "stationsOpened",
        "charmsOwned", "gotCharm_", "hasCityKey",
    ):
        assert campo in rastreador


def test_v045_amplia_volume_com_ganho_real_e_preserva_configuracao_existente():
    menu = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    settings = (RAIZ / "hollow_knight_emily/mod/EmilyGlobalSettings.cs").read_text(encoding="utf-8")
    bridge = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    assert '"125%"' in menu and '"150%"' in menu and '"200%"' in menu
    assert "Math.Min(200, Volume)" in settings
    assert "Math.Min(200, settings.Volume)" in bridge
    voice = (RAIZ / "hollow_knight_emily/mod/EmilyVoicePlayer.cs").read_text(encoding="utf-8")
    assert "ApplyGain" in voice
    assert "Math.Tanh" in voice


def test_v045_reduz_latencia_sem_remover_fila_retry_ou_confirmacao():
    bridge = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    intervalo = float(re.search(r"_nextPoll\s*=\s*Time\.unscaledTime\s*\+\s*([0-9.]+)f", bridge).group(1))
    assert intervalo <= 0.5
    assert "_nextPoll = 0f" in bridge
    assert "_priorityEvents" in bridge
    assert "foreach (var value in priorityBatch)" in bridge
    assert 'Post("/confirmar"' in bridge


def test_v045_mod_usa_hooks_reais_para_dialogo_boss_e_metricas_de_luta():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    dialogo = (RAIZ / "hollow_knight_emily/mod/EmilyDialogueTracker.cs").read_text(encoding="utf-8")
    boss = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")
    projeto = (RAIZ / "hollow_knight_emily/mod/EmilyCompanion.csproj").read_text(encoding="utf-8")
    assert "EmilyDialogueTracker" in mod and "EmilyBossTracker" in mod
    assert "On.DialogueBox.StartConversation" in dialogo
    assert "On.DialogueBox.SendConvEndEvent" in dialogo
    assert "Language.Language.Get" in dialogo
    assert '"npc_dialogo"' in dialogo
    assert "On.HealthManager.Hit" in boss
    assert "BossSceneController" in boss
    assert '"boss_encontrado"' in boss
    assert '"boss_luta"' in boss
    assert "hpBefore" in boss and "dano_causado" in boss
    assert "MMHOOK_Assembly-CSharp" in projeto


def test_v045_tagarela_tem_comentario_ocasional_e_prompt_proporcional_nao_generico():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    prompt = system_hollow_knight().lower()
    assert '"comentario_tagarela"' in mod
    assert "Random.Range" in mod
    assert "1 ou 2 frases" not in prompt
    assert "sem limite fixo" in prompt
    assert "proporcional" in prompt
    assert "genéric" in prompt
    assert "detalhe concreto" in prompt
    assert "npc" in prompt and "boss" in prompt


def test_v045_catalogo_de_boss_e_audio_tardio_sao_conservadores():
    boss = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")
    bridge = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    dialogo = (RAIZ / "hollow_knight_emily/mod/EmilyDialogueTracker.cs").read_text(encoding="utf-8")
    assert '{ "Fungus3_23", "Lorde Traidor" }' in boss
    assert '{ "Fungus3_40", "Marmu" }' in boss
    assert '{ "Abyss_19", "Receptáculo Quebrado" }' in boss
    assert '{ "Fungus3_23", "Receptáculo Quebrado" }' not in boss
    assert '{ "Fungus3_40", "Lorde Traidor" }' not in boss
    assert "IsDefeated" in boss and "PlayerData.instance.GetBool" in boss
    assert "HasBossContext" in boss
    assert "fala_sequencia" in bridge and "voz_prevista" in bridge
    assert "DialogueCooldown" in dialogo and "_lastEmitted" in dialogo
    assert "authoritative" in boss and "identidade_confirmada" in boss
    assert "unlockBossScene" in boss and "HasAuthoritativeBossMarker" in boss
    assert "_arenaEvaluated" in boss


def test_v046_dialogo_comenta_apenas_depois_da_conversa_encerrar():
    dialogo = (RAIZ / "hollow_knight_emily/mod/EmilyDialogueTracker.cs").read_text(encoding="utf-8")
    # SendConvEndEvent dispara no fim da digitacao de CADA pagina, entao o
    # encerramento real precisa vir de HideText/hidden + acceptingInput.
    assert "On.DialogueBox.HideText" in dialogo
    assert "DialogueEndDebounce" in dialogo
    assert "public void Tick()" in dialogo
    assert "IsConversationClosed" in dialogo
    assert "acceptingInput" in dialogo
    assert dialogo.count('_mod.Emit("npc_dialogo"') == 1
    trecho = dialogo[
        dialogo.index("private void EndConversation"):
        dialogo.index("private void MaybeEmitConversation")
    ]
    assert "_mod.Emit" not in trecho


def test_v046_emily_somente_funciona_com_vinculo_equipado():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    assert 'if (!Active && type != "charm_adquirido") return;' in mod
    assert "StopSpeech" in mod
    charm_update = mod[mod.index("private void CharmUpdate"):]
    charm_update = charm_update[:charm_update.index("private void ", 5)]
    assert "StopSpeech" in charm_update
    assert "if (Active && Input.GetKeyDown(KeyCode.F8))" in mod
    loaded = mod[mod.index("private void SaveLoaded"):mod.index("private void ResetSessionTracking")]
    assert "AutoEquip();" not in loaded
    bridge = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    assert "_deferredActivationEvent" in bridge
    update = bridge[bridge.index("public void Update"):bridge.index("private async Task<bool> CreateSession")]
    assert update.index("BindCampaign(campaignId);") < update.index("if (_deferredActivationEvent != null)")
    assert "if (_campaign != campaignId)" in update


def test_v046_legenda_acompanha_a_voz_e_nunca_sobrepoe_falas():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    bridge = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    hud = (RAIZ / "hollow_knight_emily/mod/EmilyHud.cs").read_text(encoding="utf-8")
    voz = (RAIZ / "hollow_knight_emily/mod/EmilyVoicePlayer.cs").read_text(encoding="utf-8")
    assert "OnVoice" in bridge
    assert "voz_prevista" in bridge
    assert "OnSpeech" in bridge
    # a reproducao saiu do cliente e passou a ser do player serializado
    assert "WavUtils.ToAudioClip" in voz
    assert "WavUtils.ToAudioClip" not in bridge
    assert "HideSpeech" in hud
    assert "TickSpeech" in mod
    assert "StartSpeech" in mod
    assert "MaxQueuedSpeech" in mod
    assert "VoiceWaitTimeout" in mod
    assert "EmilyVoicePlayer" in mod
    assert "StopSpeech" in mod
    assert "DropStaleSpeech" in mod
    assert "_speechEndsAt" in mod
    assert "if (!_settings.Voz && _currentSpeech.VoiceExpected)" in mod


def test_v046_prompt_proibe_narrar_a_fala_do_npc():
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    prompt = system_hollow_knight().lower()
    assert "nunca narre" in prompt
    assert "resuma" in prompt
    assert "conversa" in prompt


def test_v047_emily_espera_cutscene_dialogo_transicao_e_fast_travel():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    assert 'Version = "0.5.4"' in mod
    assert "private bool PodeFalarAgora()" in mod
    for membro in (
        "gm.IsCinematicScene()", "gm.IsStagTravelScene()", "gm.IsGameplayScene()",
        "gm.isPaused", "hero.transitionState", "hero.isHeroInPosition",
        "hero.acceptingInput", "cState.dead", "cState.hazardRespawning",
        "cState.transitioning", "_dialogue.EmDialogo",
    ):
        assert membro in mod
    # A fala espera o momento certo, mas não fica pendurada para sempre.
    assert "SpeechHoldLimit" in mod
    assert "PersistentSpeechHoldLimit" in mod
    # 0.4.8: fala iniciada nunca é cortada — o gate só decide se ela pode começar.
    assert "if (!_speechStarted && !PodeFalarAgora())" in mod
    assert "if (_voicePlayer == null || !_voicePlayer.IsPlaying) FinishSpeech();" in mod
    assert "SpeechInterruptDebounce" not in mod
    # A morte virou persistente para a reação sobreviver ao retorno ao banco.
    assert 'Emit("morte", new {' in mod
    assert "mortes_presenciadas = _save.MortesPresenciadas," in mod
    dialogo = (RAIZ / "hollow_knight_emily/mod/EmilyDialogueTracker.cs").read_text(encoding="utf-8")
    assert "public bool EmDialogo" in dialogo


def test_v047_audio_do_jogo_abaixa_so_enquanto_ela_fala():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    ducker = (RAIZ / "hollow_knight_emily/mod/EmilyAudioDucker.cs").read_text(encoding="utf-8")
    settings = (RAIZ / "hollow_knight_emily/mod/EmilyGlobalSettings.cs").read_text(encoding="utf-8")
    assert "_audioDucker.Tick" in mod
    assert "VozTocandoAgora" in mod
    assert "private float DuckDb()" in mod
    assert "EmilyAudioDucker" in mod
    # O mixer do próprio jogo guarda o parâmetro mestre de volume.
    assert 'Parametro = "MasterVolume"' in ducker
    assert "AudioListener" in ducker
    assert "Restaurar" in ducker
    assert "MenuAudioSlider" in ducker
    assert "Ducking" in settings
    assert 'Ducking = "leve"' in settings


def test_v047_prompt_proibe_relatorio_de_status():
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    prompt = system_hollow_knight().lower()
    assert "relatório de status" in prompt
    assert "nunca cite" in prompt
    assert "máscaras" in prompt


def test_v047_politica_de_frequencia_e_antiestatistica_estao_ligadas():
    politica = (RAIZ / "hollow_knight_emily/python/hollow_knight_politica.py").read_text(encoding="utf-8")
    cerebro = (RAIZ / "hollow_knight_emily/python/hollow_knight_cerebro.py").read_text(encoding="utf-8")
    ponte = (RAIZ / "hollow_knight_emily/python/hollow_knight_ponte.py").read_text(encoding="utf-8")
    boss = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")
    memoria = (RAIZ / "hollow_knight_emily/python/hollow_knight_memoria.py").read_text(encoding="utf-8")
    assert "LIMITE_AMBIENTE" in politica and "JANELA_AMBIENTE" in politica
    assert "parece_narracao_de_estatistica" in politica
    assert "CAMPOS_OCULTOS" in cerebro and "INSTRUCAO_SEM_ESTATISTICA" in cerebro
    assert "_reescrever_sem_estatisticas" in ponte
    assert ponte.count("proibir_estatisticas") >= 1
    assert "proibir_estatisticas" in cerebro
    # O rastreador de chefe deixou de comentar em cima da luta o tempo todo.
    # 0.5.0: intervalo e thresholds relaxados — o silêncio era o problema.
    assert "now - _lastCommentAt < 35f" in boss
    assert "_hitsWindow >= 5" in boss
    # A memória parou de escrever resumo de métricas para o modelo repetir.
    assert "observou " not in memoria
    assert "impactos em pouco tempo" in memoria


def test_v048_fala_iniciada_termina_e_so_a_fila_e_purgada():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    assert 'Version = "0.5.4"' in mod
    assert "Fala já iniciada passa adiante para verificar o fim do áudio" in mod
    assert "if (!_speechStarted && !PodeFalarAgora())" in mod
    assert "if (_voicePlayer == null || !_voicePlayer.IsPlaying) FinishSpeech();" in mod
    assert "SpeechInterruptDebounce" not in mod
    stale = mod[mod.index("private void DropStaleSpeech"):]
    stale = stale[:stale.index("private void DropOldestQueuedSpeech")]
    assert "_currentSpeech" not in stale
    assert "_speechQueue" in stale


def test_legenda_some_ao_fim_do_pcm_sem_cortar_a_voz():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    voice = (RAIZ / "hollow_knight_emily/mod/EmilyVoicePlayer.cs").read_text(encoding="utf-8")
    hud = (RAIZ / "hollow_knight_emily/mod/EmilyHud.cs").read_text(encoding="utf-8")
    assert "_received >= SampleRate * Channels ||" in voice
    assert "public bool SpeechAudible" in voice
    assert "!_stream.Completed || PlayedSamples < _stream.TotalSamples" in voice
    assert "PlayedSamples < total + folga" in voice
    trecho = mod[mod.index("if (_speechStarted)", mod.index("private void TickSpeech()")):]
    assert "_voicePlayer.SpeechAudible" in trecho
    assert trecho.index("_hud?.HideSpeech();") < trecho.index("_voicePlayer.IsPlaying) FinishSpeech();")
    assert "_canvas.AddComponent<EmilySpeechFollowVoice>()" in hud
    assert "if (Voice != null && !Voice.SpeechAudible) Hud?.HideSpeech();" in hud
    assert "_hud.ShowSpeech(item.Text," in mod


def test_v048_banco_sem_fala_propria_e_conversa_em_banco():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    politica = (RAIZ / "hollow_knight_emily/python/hollow_knight_politica.py").read_text(encoding="utf-8")
    # O rastreador de banco deixou de ser exceção do comentário espontâneo.
    chatter = mod[mod.index("private void MaybeChatter"):]
    chatter = chatter[:chatter.index("private static object AbilitySnapshot")]
    assert "!gameplay ||" in chatter or "!gameplay)" in chatter
    assert "atBench ||" not in chatter
    assert "atBench" in chatter
    assert '"banco": 0,' in politica
    assert '"dano": 5,' in politica


def test_v048_saudacao_e_localizacao_em_nome_legivel():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    locais = (RAIZ / "hollow_knight_emily/mod/EmilyLocations.cs").read_text(encoding="utf-8")
    cerebro = (RAIZ / "hollow_knight_emily/python/hollow_knight_cerebro.py").read_text(encoding="utf-8")
    protocolo = (RAIZ / "hollow_knight_emily/python/hollow_knight_protocolo.py").read_text(encoding="utf-8")
    assert 'Emit("boas_vindas"' in mod
    assert "_greetedCampaign" in mod
    assert 'zona_nome' in mod
    # A saudação vai pela fila prioritária do cliente: ela é o primeiro assunto
    # da sessão e não pode ficar atrás de telemetria acumulada.
    ponte_cliente = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    fila = ponte_cliente[ponte_cliente.index("PriorityEventTypes"):]
    assert '"boas_vindas"' in fila[:400]
    # Nomes legíveis de região, em vez da chave interna do mapa.
    assert "Encruzilhada Esquecida" in locais and "Caminho Verde" in locais
    assert "CROSSROADS" in locais and "GREEN_PATH" in locais
    assert "localizacao_atual" in cerebro
    assert "zona_nome" in protocolo


def test_v048_prompt_ensina_historia_area_e_dano_anormal():
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    prompt = system_hollow_knight().lower()
    assert "descobrindo hallownest junto" in prompt
    assert "teoria" in prompt
    assert "spoiler" in prompt
    assert "localizacao_atual" in prompt
    assert "anormal" in prompt
    assert "boas_vindas" in prompt


def test_v048_fala_enfileirada_confere_regiao_antes_de_comecar():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    item = (RAIZ / "hollow_knight_emily/mod/EmilySpeechItem.cs").read_text(encoding="utf-8")
    cliente = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")
    ponte = (RAIZ / "hollow_knight_emily/python/hollow_knight_ponte.py").read_text(encoding="utf-8")

    assert '"zona": zona_fala' in ponte
    assert '"validar_zona": validar_zona' in ponte
    assert 'public string Zone = "";' in item
    assert "public bool ValidateZone;" in item
    assert 'Zone = (string)data["zona"] ?? ""' in cliente
    assert 'ValidateZone = (bool?)data["validar_zona"] ?? false' in cliente
    assert "SpeechStillFitsCurrentZone" in mod
    assert "if (!_speechStarted && !SpeechStillFitsCurrentZone(_currentSpeech))" in mod
    guarda = mod[mod.index("private static bool SpeechStillFitsCurrentZone"):]
    guarda = guarda[:guarda.index("private void StartSpeech")]
    assert "!item.ValidateZone" in guarda
    assert "pd.mapZone.ToString()" in guarda


def test_v048_regiao_e_observada_antes_da_fala_e_nao_so_no_callback_de_cena():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    hero_update = mod[mod.index("private void HeroUpdate"):mod.index("private static string CurrentCampaignId")]
    scene_changed = mod[mod.index("private void SceneChanged"):mod.index("private int TakeDamage")]
    assert "ObserveCurrentZone(gm.sceneName);" in hero_update
    assert hero_update.index("ObserveCurrentZone(gm.sceneName);") < hero_update.index("TickSpeech();")
    assert "private void ObserveCurrentZone(string scene)" in scene_changed
    assert "if (zona == _zonaVista) return;" in scene_changed
    assert 'Emit("area_nova"' in scene_changed


def test_v049_fala_termina_pela_posicao_de_reproducao_e_nao_pela_fila_vazia():
    player = (RAIZ / "hollow_knight_emily/mod/EmilyVoicePlayer.cs").read_text(encoding="utf-8")

    is_playing = player[player.index("public bool IsPlaying"):]
    is_playing = is_playing[:is_playing.index("public float Play")]
    # O fim da fala é decidido pelo playhead e pelo total de amostras; a fila
    # esvaziada NÃO encerra mais a fala, porque o Unity lê o PCM adiantado.
    assert "_stream.Completed" in is_playing
    assert "_stream.TotalSamples" in is_playing
    assert "PlayedSamples < total + folga" in is_playing
    assert "_source.time" in player[player.index("private long PlayedSamples"):player.index("public bool IsPlaying")]
    assert "Drained" not in is_playing
    assert "Stalled" in is_playing
    stream = player[player.index("internal sealed class EmilyPcmStream"):]
    stream = stream[:stream.index("/// <summary>")]
    assert "public long TotalSamples" in stream
    assert "public bool Completed" in stream
    assert "public bool Stalled" in stream


def test_v049_panteao_anuncia_cada_chefe_e_menu_nao_e_lugar_de_boss():
    tracker = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")

    setup = tracker[tracker.index("private void BossSceneSetup"):]
    setup = setup[:setup.index("private void HealthHit")]
    # Panteões: a cena não muda entre chefes; troca de elenco reanuncia.
    assert "mudou" in setup
    assert "_bosses.Contains(b)" in setup
    assert "_encounterAnnounced = false" in setup
    # Arenas individuais de Godhome confirmadas nos dados do jogo. As cenas de
    # Panteão ficam fora do dicionário: lá quem nomeia o encontro é o chefe que
    # entra via BossSceneController.Setup.
    for arena in (
        "GG_God_Tamer", "GG_Lost_Kin", "GG_Failed_Champion",
        "GG_Soul_Master", "GG_Soul_Tyrant", "GG_Ghost_Markoth",
        "GG_Ghost_No_Eyes", "GG_Oblobbles", "GG_Painter", "GG_Nailmasters",
    ):
        assert f'{{ "{arena}",' in tracker
    for objeto in (
        "Vengefly King", "God Tamer", "Lost Kin", "Soul Tyrant",
        "Ghost Warrior Markoth", "Ghost Warrior No Eyes", "Absolute Radiance",
        "Paintmaster Sheo",
    ):
        assert objeto in tracker
    anuncio = tracker[tracker.index("private void AnnounceEncounter"):]
    anuncio = anuncio[:anuncio.index("private void StartFight")]
    # 0.5.1: o gate de pausa foi removido do anúncio (era o que deixava
    # a Emily muda no Panteão). O gate agora é apenas para comentários
    # de luta. O anúncio entra sem precisar esperar o intro acabar.
    assert "EmGameplayReal" not in anuncio
    assert 'chefe percebido:' in anuncio
    assert 'Emit("boss_encontrado"' in anuncio
    assert "persistente = true" in anuncio
    luta = tracker[tracker.index("private void StartFight"):]
    luta = luta[:luta.index("private void MaybeComment")]
    assert 'luta iniciada com:' in luta
    gate = tracker[tracker.index("private static bool EmGameplayReal"):]
    gate = gate[:gate.index("private static bool IsEmilySource")]
    assert "isPaused" in gate
    assert "IsGameplayScene" in gate


def test_v049_prompt_agrupa_eventos_e_proibe_reacao_de_jogo_bugado():
    from hollow_knight_emily.python.hollow_knight_cerebro import system_hollow_knight

    cerebro = (RAIZ / "hollow_knight_emily/python/hollow_knight_cerebro.py").read_text(encoding="utf-8")
    ponte = (RAIZ / "hollow_knight_emily/python/hollow_knight_ponte.py").read_text(encoding="utf-8")
    politica = (RAIZ / "hollow_knight_emily/python/hollow_knight_politica.py").read_text(encoding="utf-8")

    prompt = system_hollow_knight().lower()
    assert "eventos_multiplos" in cerebro
    assert "um único comentário" in prompt
    assert "nunca trate o jogo como bugado" in prompt
    assert "acontecimentos" in cerebro
    assert "_pistas_do_lote" in cerebro
    assert 'TIPO_LOTE = "eventos_multiplos"' in ponte
    assert "JANELA_LOTE" in ponte
    assert "EVENTOS_FORA_DO_LOTE" in ponte
    assert "_despejar_lote" in ponte
    assert '"boas_vindas", "morte", "chamou_emily"' in ponte
    assert "_deve_validar_zona" in ponte
    assert "eventos_multiplos" in politica


def test_versao_mod_atual():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    readme = (RAIZ / "hollow_knight_emily/README.md").read_text(encoding="utf-8")
    assert 'Version = "0.5.4"' in mod
    assert "0.5.4" in readme


def test_v050_boss_events_persistentes_gate_relaxado_e_mais_fala():
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")
    tracker = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")
    cliente = (RAIZ / "hollow_knight_emily/mod/EmilyBridgeClient.cs").read_text(encoding="utf-8")

    # Hold de fala comum subiu: a intro de chefe com title card ultrapassa 25s.
    assert "SpeechHoldLimit = 60f" in mod
    # Durante a luta, o gate relaxa: bloqueio momentâneo de input não cala.
    gate = mod[mod.index("private bool PodeFalarAgora()"):]
    gate = gate[:gate.index("private float DuckDb()")]
    assert "if (_boss != null && _boss.InFight) return true;" in gate
    # Tagarela conversa durante luta de chefe, com intervalo maior.
    chatter = mod[mod.index("private void MaybeChatter"):]
    chatter = chatter[:chatter.index("private static object AbilitySnapshot")]
    assert "var inFight = _boss != null && _boss.InFight;" in chatter
    assert "100f, 160f" in chatter
    # Eventos de chefe agora são persistentes (sobrevivem à intro/title card).
    for evento in ("boss_encontrado", "boss_iniciado", "boss_fase"):
        bloco = tracker[tracker.index(f'Emit("{evento}", new {{'):]
        bloco = bloco[:bloco.index("});")]
        assert "persistente = true" in bloco
    # boss_fase entrou na fila prioritária do bridge client.
    assert '"boss_fase", "morte",' in cliente
    # Comentário de combate: intervalo 35s, briga mínima 12s, padrões relaxados.
    assert "now - _lastCommentAt < 35f || now - _fightAt < 12f" in tracker
    assert "_hitsWindow >= 5 && noDamage >= 12f" in tracker
    assert '_hitsWindow >= 7 && _dealtWindow > 0' in tracker
    # Fallback de padrão: a luta já durou um tempo, mesmo sem padrão ela fala.
    assert 'else if (now - _fightAt >= 40f) pattern = "luta_continua";' in tracker


def test_v050_amuleto_imune_a_falso_positivo_e_progresso_filtrado():
    tracker = (RAIZ / "hollow_knight_emily/mod/EmilyProgressTracker.cs").read_text(encoding="utf-8")
    cerebro = (RAIZ / "hollow_knight_emily/python/hollow_knight_cerebro.py").read_text(encoding="utf-8")
    politica = (RAIZ / "hollow_knight_emily/python/hollow_knight_politica.py").read_text(encoding="utf-8")

    # Godhome/Panteões não dão amuleto; o contador interno oscilava sem
    # aquisição real e a Emily falava de amuleto inexistente.
    charms = tracker[tracker.index("private void EmitCharms"):]
    charms = charms[:charms.index("private static string CharmName")]
    assert 'StartsWith("GG_"' in charms
    # O fallback por CharmsOwned foi removido — só gotCharm_X novo é aquisição.
    assert "um novo amuleto" not in charms
    # A telemetria de progresso não chega mais ao modelo.
    assert '"progresso",' in cerebro
    # Cooldowns de chefe reduzidos (o silêncio era o problema).
    assert '"boss_luta": 50.0,' in politica
    assert '"boss_encontrado": 35.0,' in politica
    assert '"boss_fase": 30.0,' in politica
    assert '"boss_iniciado": 15.0,' in politica


def test_v0410_chefe_com_barra_de_vida_fases_e_luta_recente():
    tracker = (RAIZ / "hollow_knight_emily/mod/EmilyBossTracker.cs").read_text(encoding="utf-8")
    mod = (RAIZ / "hollow_knight_emily/mod/EmilyCompanionMod.cs").read_text(encoding="utf-8")

    # Vida do chefe medida nos HealthManager reais, em tempo real.
    assert "VidaChefeFrac" in tracker
    assert "_hpPeak" in tracker
    # Fases: thresholds de vida viram evento boss_fase com dica qualitativa.
    assert "VerificarEtapa" in tracker
    assert 'Emit("boss_fase"' in tracker
    assert "vida_chefe_frac" in tracker
    # A Radiância avisa a subida de plataformas na etapa final.
    radiancia = tracker[tracker.index("private void AnunciarEtapa"):]
    radiancia = radiancia[:radiancia.index("public string LutaRecente")]
    assert "subida de plataformas" in radiancia
    assert "Radiância" in radiancia
    # A morte carrega a luta que ela presenciou.
    assert "LutaRecente" in tracker
    morte = mod[mod.index('Emit("morte", new {'):]
    morte = morte[:morte.index("});")]
    assert "luta = _boss" in morte
    # O comentário de luta também sente a vida do chefe.
    luta = tracker[tracker.index('Emit("boss_luta", new {'):]
    luta = luta[:luta.index("});")]
    assert "vida_chefe_frac" in luta


def test_v0410_estado_limpo_e_reacoes_de_chefe_nunca_ficam_mudas():
    cerebro = (RAIZ / "hollow_knight_emily/python/hollow_knight_cerebro.py").read_text(encoding="utf-8")
    politica = (RAIZ / "hollow_knight_emily/python/hollow_knight_politica.py").read_text(encoding="utf-8")
    ponte = (RAIZ / "hollow_knight_emily/python/hollow_knight_ponte.py").read_text(encoding="utf-8")

    # O snapshot de estado chega ao modelo sem `pausado` (que mentia no
    # slow-motion da luta), sem em_gameplay e sem progresso numérico.
    assert "CAMPOS_OCULTOS_ESTADO" in cerebro
    assert '"pausado", "em_gameplay", "progresso",' in cerebro
    assert "_estado_para_ia" in cerebro
    assert '"estado_atual": self._estado_para_ia(sessao.estado),' in cerebro
    # Vida do chefe e contagem de mortes não chegam como número.
    assert '"mortes_presenciadas", "vida_chefe_frac",' in cerebro
    # Pistas qualitativas da luta, fase e morte com chefe.
    assert "o chefe tá no fim das forças" in cerebro
    assert "ele caiu lutando contra" in cerebro
    # Chefe, morte e marcos nunca ficam mudos quando o modelo vira painel.
    assert "EVENTOS_QUE_NAO_FICAM_MUTOS" in politica
    assert '"boss_iniciado", "boss_luta", "boss_fase", "morte", "quase_morte",' in politica
    assert "EVENTOS_QUE_NAO_FICAM_MUTOS" in ponte
    descarte = ponte[ponte.index("fala descartada por narração de"):]
    descarte = descarte[:descarte.index("if not texto or politica.repetido(texto):")]
    assert "politica.fallback(evento.tipo, evento.dados)" in descarte
    # boss_fase tem prioridade e cooldown próprios.
    assert '"boss_fase": 74,' in politica
    assert '"boss_fase": 30.0,' in politica
    assert '"boss_fase": f"Essa luta contra' in politica
