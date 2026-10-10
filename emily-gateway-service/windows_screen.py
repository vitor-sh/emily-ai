"""Captura de tela pontual/MJPEG do Windows para o contrato Android."""

from __future__ import annotations

import io
import time

import mss
import numpy as np
from PIL import Image


def listar_monitores() -> list[dict]:
    with mss.mss() as captura:
        return [{"id": i, "indice": i, "nome": f"Monitor {i}",
                 "monitor": i, "largura": m["width"], "altura": m["height"],
                 "x": m["left"], "y": m["top"]}
                for i, m in enumerate(captura.monitors[1:], 1)]


def capturar_jpeg(monitor: int = 1, largura_max: int = 1280, qualidade: int = 72) -> bytes:
    with mss.mss() as captura:
        if not 1 <= monitor < len(captura.monitors):
            raise ValueError("monitor inválido")
        tela = captura.grab(captura.monitors[monitor])
    imagem = Image.frombytes("RGB", tela.size, tela.rgb)
    if imagem.width > largura_max:
        altura = max(1, round(imagem.height * largura_max / imagem.width))
        imagem = imagem.resize((largura_max, altura), Image.Resampling.LANCZOS)
    saida = io.BytesIO()
    imagem.save(saida, format="JPEG", quality=qualidade, optimize=True)
    return saida.getvalue()


def quadros_mjpeg(monitor: int = 1, fps: int = 4):
    intervalo = 1 / max(1, min(fps, 15))
    while True:
        imagem = capturar_jpeg(monitor)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
               + str(len(imagem)).encode() + b"\r\n\r\n" + imagem + b"\r\n")
        time.sleep(intervalo)


def _pcm16(amostras, quadros: int = 4800) -> bytes:
    matriz = np.asarray(amostras, dtype=np.float32)
    if matriz.size == 0:
        matriz = np.zeros((quadros, 2), dtype=np.float32)
    if matriz.ndim == 1:
        matriz = np.repeat(matriz[:, None], 2, axis=1)
    if matriz.shape[1] == 1:
        matriz = np.repeat(matriz, 2, axis=1)
    matriz = matriz[:, :2]
    return (np.clip(matriz, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def audio_pcm():
    """Loopback WASAPI do alto-falante padrão, PCM estéreo 48 kHz."""
    import soundcard as sc

    alto_falante = sc.default_speaker()
    dispositivo = sc.get_microphone(alto_falante.id, include_loopback=True)
    yield b"EMILY-AUDIO 48000 2 16\n"
    quadros = 4800
    intervalo = quadros / 48000
    with dispositivo.recorder(samplerate=48000, channels=2, blocksize=quadros) as gravador:
        proximo = time.monotonic()
        while True:
            amostras = gravador.record(numframes=quadros)
            yield _pcm16(amostras, quadros)
            proximo += intervalo
            pausa = proximo - time.monotonic()
            if pausa > 0:
                time.sleep(pausa)
            elif pausa < -intervalo:
                proximo = time.monotonic()
