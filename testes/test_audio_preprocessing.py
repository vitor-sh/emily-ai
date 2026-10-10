"""Regressões do pipeline compartilhado que prepara áudio para o Whisper."""

from __future__ import annotations

import io
import math
import struct
import sys
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _pcm_seno(taxa: int, canais: int, segundos: float = 1.0,
              amplitude: int = 5000) -> bytes:
    saida = bytearray()
    for i in range(round(taxa * segundos)):
        valor = int(amplitude * math.sin(2 * math.pi * 220 * i / taxa))
        saida.extend(struct.pack("<h", valor) * canais)
    return bytes(saida)


def _wav(pcm: bytes, taxa: int = 16000, canais: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(canais)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return buf.getvalue()


def _info(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        return (w.getframerate(), w.getnchannels(), w.getsampwidth(),
                w.getnframes())


def _config(**mudancas):
    import audio_preprocessing as ap

    base = dict(denoise=False, normalize=False, vad=False)
    base.update(mudancas)
    return ap.AudioPreprocessingConfig(**base)


def test_padroniza_pcm_discord_para_wav_mono_16k():
    import audio_preprocessing as ap

    pcm = _pcm_seno(48000, 2, 0.5)
    resultado = ap.preprocess_audio_detailed(
        pcm, sample_rate=48000, channels=2, sample_width=2,
        source="teste_call", config=_config())

    assert not resultado.errors
    assert _info(resultado.wav) == (16000, 1, 2, 8000)
    assert resultado.input_duration_s == pytest.approx(0.5, abs=0.01)
    assert resultado.output_duration_s == pytest.approx(0.5, abs=0.01)


def test_ptt_ja_padronizado_nao_abre_ffmpeg_com_filtros_desligados(monkeypatch):
    import audio_preprocessing as ap

    monkeypatch.setattr(
        ap.subprocess, "run",
        lambda *_a, **_k: pytest.fail("não deveria abrir FFmpeg"),
    )
    pcm = _pcm_seno(16000, 1, 0.25)
    resultado = ap.preprocess_audio_detailed(
        pcm, sample_rate=16000, channels=1, sample_width=2,
        source="ptt", config=_config())

    assert _info(resultado.wav) == (16000, 1, 2, 4000)
    assert resultado.timings_ms["total"] < 100


def test_rnnoise_e_loudnorm_rodam_na_mesma_passagem_ffmpeg(monkeypatch, tmp_path):
    import audio_preprocessing as ap

    capturado = {}
    saida = _wav(_pcm_seno(16000, 1, 0.2))

    def rodar(cmd, **kwargs):
        capturado["cmd"] = list(cmd)
        return SimpleNamespace(returncode=0, stdout=saida, stderr=b"")

    monkeypatch.setattr(ap.subprocess, "run", rodar)
    monkeypatch.setattr(ap, "_ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    modelo = tmp_path / "modelo.rnnn"
    modelo.write_text("modelo de teste", encoding="utf-8")
    monkeypatch.setattr(ap, "RNNOISE_MODEL", modelo)
    resultado = ap.preprocess_audio_detailed(
        _pcm_seno(16000, 1, 0.2), sample_rate=16000, channels=1,
        config=_config(denoise=True, normalize=True))

    filtro = capturado["cmd"][capturado["cmd"].index("-af") + 1]
    assert "arnndn=" in filtro
    assert "loudnorm=" in filtro
    assert capturado["cmd"].count("-i") == 1
    assert resultado.applied == ["standardize", "denoise", "normalize"]


def test_silero_real_descarta_silencio():
    import audio_preprocessing as ap

    if not ap.SILERO_MODEL.is_file():
        pytest.skip("modelo Silero não está no checkout")
    resultado = ap.preprocess_audio_detailed(
        b"\0" * (16000 * 2), sample_rate=16000, channels=1,
        config=_config(vad=True))

    assert resultado.wav == b""
    assert resultado.discarded_reason == "sem_fala_silero"
    assert not resultado.errors


def test_vad_recorta_e_separa_dois_segmentos(monkeypatch):
    import audio_preprocessing as ap

    # 3 segundos: fala, silêncio, fala. Probabilidades são injetadas para testar
    # somente a remontagem, sem fingir que uma senoide é voz humana para o modelo.
    total = 16000 * 3
    pcm = np.full(total, 1200, dtype="<i2").tobytes()
    probs = ([0.9] * 20 + [0.0] * 25 + [0.9] * 20
             + [0.0] * 29)
    monkeypatch.setattr(ap, "_silero_probabilities", lambda _a: probs)

    resultado = ap.preprocess_audio_detailed(
        pcm, sample_rate=16000, channels=1,
        config=_config(vad=True, vad_speech_pad_ms=0,
                       vad_min_silence_ms=200))

    assert len(resultado.speech_segments) == 2
    assert resultado.output_duration_s < resultado.input_duration_s
    with wave.open(io.BytesIO(resultado.wav), "rb") as w:
        recortado = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    assert np.count_nonzero(recortado == 0) >= round(16000 * 0.08)


def test_falha_do_silero_preserva_audio_anterior(monkeypatch):
    import audio_preprocessing as ap

    monkeypatch.setattr(
        ap, "_apply_vad",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("onnx falhou")),
    )
    resultado = ap.preprocess_audio_detailed(
        _pcm_seno(16000, 1, 0.2), sample_rate=16000, channels=1,
        config=_config(vad=True))

    assert resultado.wav
    assert "vad" in resultado.errors
    assert resultado.discarded_reason == ""


def test_configuracao_invalida_no_env_cai_no_padrao(monkeypatch):
    import audio_preprocessing as ap

    monkeypatch.setenv("EMILY_AUDIO_VAD_THRESHOLD", "não-é-número")
    monkeypatch.setenv("EMILY_AUDIO_VAD_PAD_MS", "quebrado")
    config = ap.AudioPreprocessingConfig.current()
    assert config.vad_threshold == 0.5
    assert config.vad_speech_pad_ms == 120


def test_flags_persistem_e_aparecem_nas_duas_interfaces(monkeypatch, tmp_path):
    import interface_web
    import preferencias

    arquivo_real = preferencias.ARQUIVO
    monkeypatch.setattr(preferencias, "ARQUIVO", tmp_path / "prefs_audio.json")
    preferencias.recarregar()
    api = object.__new__(interface_web.Api)
    chaves = ("audio_preprocess_denoise", "audio_preprocess_normalize",
              "audio_preprocess_vad")
    try:
        for chave in chaves:
            assert preferencias._PADROES[chave] is True
            assert api.set_toggle(chave, False) is True
        preferencias.recarregar()
        estado = api.estado_automacao()
        assert all(estado[chave] is False for chave in chaves)
    finally:
        preferencias.ARQUIVO = arquivo_real
        preferencias.recarregar()

    web = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
    qt = (RAIZ / "interface.py").read_text(encoding="utf-8")
    assert "Redução de ruído (RNNoise)" in web and "Silero VAD" in web
    assert "_toggle_audio_preprocess" in qt


def test_ptt_preprocessa_antes_do_upload_groq(monkeypatch):
    import audio_preprocessing
    import speech_recognition as sr
    import voz

    visto = {}
    wav_limpo = _wav(_pcm_seno(16000, 1, 0.1))

    def preprocessar(raw, **kwargs):
        visto["pre"] = (raw, kwargs)
        return wav_limpo

    class Transcricoes:
        @staticmethod
        def create(**kwargs):
            visto["upload"] = kwargs["file"].getvalue()
            return SimpleNamespace(text="teste certo")

    monkeypatch.setattr(audio_preprocessing, "preprocess_audio", preprocessar)
    monkeypatch.setattr(
        voz, "cliente_groq",
        SimpleNamespace(audio=SimpleNamespace(transcriptions=Transcricoes())),
    )
    audio = sr.AudioData(b"\x01\x00" * 100, 16000, 2)

    assert voz._transcrever_audio(audio) == "teste certo"
    assert visto["pre"][1]["source"] == "ptt"
    assert visto["upload"] == wav_limpo


def test_cliente_groq_e_criado_apenas_ao_transcrever(monkeypatch):
    import voz

    monkeypatch.setattr(voz, "cliente_groq", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        voz._obter_cliente_groq()

    cliente = object()
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    monkeypatch.setattr(voz, "Groq", lambda *, api_key: cliente if api_key == "chave-de-teste" else None)
    assert voz._obter_cliente_groq() is cliente
    assert voz._obter_cliente_groq() is cliente


def test_call_preprocessa_antes_do_upload_groq(monkeypatch):
    import audio_preprocessing
    import escuta_call

    visto = {}
    wav_limpo = _wav(_pcm_seno(16000, 1, 0.1))

    def preprocessar(raw, **kwargs):
        visto["pre"] = (raw, kwargs)
        return wav_limpo

    class Resposta:
        text = "fala da call"

        @staticmethod
        def model_dump():
            return {"segments": []}

    class Transcricoes:
        @staticmethod
        def create(**kwargs):
            visto["upload"] = kwargs["file"].getvalue()
            return Resposta()

    monkeypatch.setattr(audio_preprocessing, "preprocess_audio", preprocessar)
    monkeypatch.setattr(
        escuta_call, "_groq",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(transcriptions=Transcricoes())),
    )

    assert escuta_call.transcrever(b"pcm do discord") == "fala da call"
    assert visto["pre"][1] == {
        "sample_rate": 48000, "channels": 2, "sample_width": 2,
        "source": "discord_call",
    }
    assert visto["upload"] == wav_limpo


def test_modelos_entram_nos_dois_builds():
    linux = (RAIZ / "build_emily_linux.py").read_text(encoding="utf-8")
    windows = (RAIZ / "build_emily.py").read_text(encoding="utf-8")
    requirements = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    atualizador = (RAIZ / "atualizador_emily.py").read_text(encoding="utf-8")
    assert '("assets", "assets")' in linux
    assert '("assets",            "assets")' in windows
    assert "onnxruntime==1.29.0" in requirements
    assert '_ASSETS = ("web", "static", "img", "assets")' in atualizador
    assert (RAIZ / "assets" / "audio" / "silero_vad.onnx").is_file()
    assert (RAIZ / "assets" / "audio" / "rnnoise_bd.rnnn").is_file()


def test_aquecimento_assincrono_e_disparado_nos_dois_fluxos():
    main = (RAIZ / "main.py").read_text(encoding="utf-8")
    call = (RAIZ / "escuta_call.py").read_text(encoding="utf-8")
    assert "audio_preprocessing.warmup_async()" in main
    assert "audio_preprocessing.warmup_async()" in call
