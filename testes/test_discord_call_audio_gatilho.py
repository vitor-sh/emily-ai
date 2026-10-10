"""Ruído, variantes do nome e menção em terceira pessoa na call."""

from __future__ import annotations

import sys
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def test_variantes_reconheciveis_sem_aproximar_palavras_comuns():
    import resto_call

    for frase in ("Emily, me ajuda?", "Ei, Emilly, você ouviu?",
                  "e mily você tá aí?", "Emil, consegue ver?",
                  "Hémily, vem cá", "Não, Emily, eu falei contigo"):
        assert resto_call.chamada_direta(frase), frase
    for frase in ("chegou um email", "a família está aqui",
                  "a Emília entrou", "o Emílio falou", "dez milhões",
                  "a Emily entrou na call", "fala da Emily", "Emily é incrível",
                  "a Emily fica quieta"):
        assert not resto_call.chamada_direta(frase), frase
    assert resto_call.chamaram_ela("a Emily entrou na call")
    assert resto_call.remover_vocativo_inicial(
        "Ei, Emilly, o que você acha?") == "o que voce acha"
    assert resto_call.remover_vocativo_inicial(
        "a Emily entrou na call") == "a Emily entrou na call"


def test_vocativo_nao_transforma_opiniao_em_pesquisa():
    import classificacao_ferramentas as cf
    import resto_call

    opiniao = resto_call.remover_vocativo_inicial(
        "Emilly, o que você acha desse jogo?")
    assert cf.classificar(opiniao).politica == cf.SEM_FERRAMENTA
    pesquisa = resto_call.remover_vocativo_inicial(
        "Emily, pesquisa as notícias desse jogo")
    assert cf.classificar(pesquisa, acao_explicita=True).politica == (
        cf.FERRAMENTA_OBRIGATORIA)


def test_mencao_sobre_ela_nao_dispara_resposta_nem_silencio():
    import resto_call

    assert not resto_call._comando_de_silencio("a Emily fica quieta")
    ligado_antes = resto_call._est.ligado
    silenciada_antes = resto_call._est.silenciada
    mudo_antes = resto_call._est.mudo_ate
    resto_call._limpar_lote()
    resto_call._esvaziar_fila()
    resto_call._est.ligado = True
    resto_call._est.silenciada = False
    resto_call._est.mudo_ate = 0.0
    resto_call._est.conversa.clear()
    agora = time.monotonic()
    turno = SimpleNamespace(texto="a Emily entrou na call", user_id=123,
                            nome="Pessoa", inicio=agora, fim=agora)
    try:
        resto_call._ao_ouvir_turno(turno)
        assert not resto_call._lote
        turno.texto = "Ei, Emilly, você tá aí?"
        resto_call._ao_ouvir_turno(turno)
        assert len(resto_call._lote) == 1
    finally:
        resto_call._limpar_lote()
        resto_call._est.ligado = ligado_antes
        resto_call._est.silenciada = silenciada_antes
        resto_call._est.mudo_ate = mudo_antes


def test_call_valida_voz_antes_de_amplificar_ruido(monkeypatch):
    import audio_preprocessing as ap

    chamadas = []
    wav = ap._pcm_to_wav(b"\0\0" * 16000, 16000, 1, 2)

    def ffmpeg(dados, taxa, canais, largura, config):
        chamadas.append((config.denoise, config.normalize, config.vad))
        aplicadas = ["standardize"]
        if config.denoise:
            aplicadas.append("denoise")
        if config.normalize:
            aplicadas.append("normalize")
        return wav, {"ffmpeg": 1.0}, aplicadas, {}, {}

    monkeypatch.setattr(ap, "_run_ffmpeg", ffmpeg)
    monkeypatch.setattr(ap, "_apply_vad", lambda dados, config: (b"", []))
    config = ap.AudioPreprocessingConfig()
    resultado = ap.preprocess_audio_detailed(
        b"\0\0" * (48000 * 2), sample_rate=48000, channels=2,
        source="discord_call", config=config)
    assert resultado.discarded_reason == "sem_fala_silero"
    assert chamadas == [(True, False, True)]

    monkeypatch.setattr(ap, "_apply_vad", lambda dados, config:
                        (dados, [(0, 12000)]))
    chamadas.clear()
    resultado = ap.preprocess_audio_detailed(
        b"\0\0" * (48000 * 2), sample_rate=48000, channels=2,
        source="discord_call", config=config)
    assert chamadas == [(True, False, True), (False, True, False)]
    assert "normalize" in resultado.applied


def test_gravacao_real_da_call_continua_com_fala_apos_filtro():
    import numpy as np
    import audio_preprocessing as ap
    import escuta_call

    caminho = RAIZ / "prova_call" / "111757_hiucksam.wav"
    if not caminho.is_file():
        pytest.skip("gravação de diagnóstico da call indisponível")
    with wave.open(str(caminho), "rb") as arquivo:
        pcm = arquivo.readframes(arquivo.getnframes())
    resultado = ap.preprocess_audio_detailed(
        pcm, sample_rate=48000, channels=2, source="discord_call",
        config=ap.AudioPreprocessingConfig())
    assert not resultado.discarded_reason
    assert resultado.output_duration_s > 3.0
    assert "vad" in resultado.applied
    assert "normalize" in resultado.applied
    baixo = (np.frombuffer(pcm, dtype="<i2").astype(np.float32) * 0.1)
    pcm_baixo = baixo.astype("<i2").tobytes()
    assert escuta_call._energia(pcm_baixo) < escuta_call.RMS_MINIMO
    assert escuta_call._energia_de_turno(pcm_baixo) > escuta_call.RMS_MINIMO
    resultado_baixo = ap.preprocess_audio_detailed(
        pcm_baixo, sample_rate=48000, channels=2, source="discord_call",
        config=ap.AudioPreprocessingConfig())
    assert not resultado_baixo.discarded_reason
    assert resultado_baixo.output_duration_s > 3.0


def test_ruido_acima_do_rms_minimo_nao_chega_ao_whisper():
    import numpy as np
    import audio_preprocessing as ap

    rng = np.random.default_rng(7)
    ruido = rng.normal(0, 700, 48000).clip(-32768, 32767).astype("<i2")
    pcm = np.repeat(ruido[:, None], 2, axis=1).astype("<i2").tobytes()
    resultado = ap.preprocess_audio_detailed(
        pcm, sample_rate=48000, channels=2, source="discord_call",
        config=ap.AudioPreprocessingConfig())
    assert resultado.discarded_reason == "sem_fala_silero"
    assert "normalize" not in resultado.applied


def test_fala_breve_baixa_nao_some_na_media_das_pausas():
    import numpy as np
    import escuta_call

    amostras = np.zeros((48000, 2), dtype="<i2")
    amostras[15000:27000, :] = 350  # 250 ms acima do ruído, numa fala de 1 s
    pcm = amostras.tobytes()
    assert escuta_call._energia(pcm) < escuta_call.RMS_MINIMO
    assert escuta_call._energia_de_turno(pcm) > escuta_call.RMS_MINIMO
