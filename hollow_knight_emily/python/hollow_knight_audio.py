"""Conversão do TTS da Emily para WAV consumível pelo Unity."""

from __future__ import annotations

import io
import wave


def empacotar_wav(
    pcm: bytes, *, taxa: int = 44100, canais: int = 1, largura: int = 2
) -> bytes:
    if not pcm:
        return b""
    if taxa <= 0 or canais <= 0 or largura not in (1, 2, 3, 4):
        raise ValueError("formato de áudio inválido")
    saida = io.BytesIO()
    with wave.open(saida, "wb") as arquivo:
        arquivo.setnchannels(canais)
        arquivo.setsampwidth(largura)
        arquivo.setframerate(taxa)
        arquivo.writeframes(pcm)
    return saida.getvalue()


def gerar_wav_fish(texto: str) -> bytes:
    """Gera voz sem reproduzi-la no desktop nem enviá-la ao Discord/celular."""
    texto = str(texto or "").strip()
    if not texto:
        return b""
    import voz

    pcm, taxa, canais, largura = voz.gerar_audio_pacote(texto)
    return empacotar_wav(
        pcm, taxa=int(taxa), canais=int(canais), largura=int(largura)
    )


def gerar_pcm_fish(texto: str):
    """Entrega PCM s16le conforme a Fish sintetiza, sem tocar no desktop."""
    texto = str(texto or "").strip()
    if not texto:
        return
    import voz

    yield from voz.gerar_audio_stream(texto)
