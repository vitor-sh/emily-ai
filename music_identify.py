"""Reconhecimento sob demanda. Áudio só vive na memória desta requisição."""
from __future__ import annotations

import asyncio
import io
import os
import json
import subprocess
import sys
from pathlib import Path
import wave
from urllib.parse import quote, urlparse

MAX_BYTES = 3 * 1024 * 1024


def safe_url(value):
    value = str(value or "")[:2048]
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username else ""


def normalize(data, provider):
    if not isinstance(data, dict):
        return None
    track = data.get("track") if provider == "shazam" else data.get("result")
    if not isinstance(track, dict):
        return None
    title = str(track.get("title") or "").strip()[:250]
    artist = str((track.get("subtitle") if provider == "shazam" else track.get("artist")) or "").strip()[:250]
    if not title or not artist:
        return None
    images = track.get("images") if isinstance(track.get("images"), dict) else {}
    apple = track.get("apple_music") if isinstance(track.get("apple_music"), dict) else {}
    artwork = apple.get("artwork") if isinstance(apple.get("artwork"), dict) else {}
    image = (images.get("coverarthq") or images.get("coverart")) if provider == "shazam" else str(artwork.get("url") or "").replace("{w}", "300").replace("{h}", "300")
    return {"titulo": title, "artista": artist, "capa": safe_url(image),
            "fonte": provider, "url": safe_url(track.get("url") or track.get("song_link")),
            "consulta": f"{artist} {title}",
            "youtube": "https://www.youtube.com/results?search_query=" + quote(f"{artist} {title}")}


def windows(raw):
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("A gravação deve ter até 3 MiB.")
    with wave.open(io.BytesIO(raw), "rb") as audio:
        rate, channels, width = audio.getframerate(), audio.getnchannels(), audio.getsampwidth()
        frames = audio.getnframes()
        if width != 2 or channels not in (1, 2) or not 8000 <= rate <= 48000 or not 2 <= frames / rate <= 25:
            raise ValueError("Use WAV PCM de 2 a 25 segundos.")
        pcm = audio.readframes(frames)
        if len(pcm) != frames * channels * width:
            raise ValueError("Gravação incompleta.")
        if not any(pcm):
            raise ValueError("Não recebi som. Confira o microfone ou a permissão de captura interna.")
    # Duas janelas distintas; uma assinatura muito longa piora o Shazam.
    result = []
    step = rate * 12 * channels * width
    for start in range(0, len(pcm), step):
        chunk = pcm[start:start + step]
        if len(chunk) < rate * 2 * channels * width:
            break
        out = io.BytesIO()
        with wave.open(out, "wb") as audio:
            audio.setparams((channels, width, rate, 0, "NONE", "not compressed"))
            audio.writeframes(chunk)
        result.append(out.getvalue())
    return result[:2]


async def _shazam(clips):
    from shazamio import Shazam
    from shazamio.client import HTTPClient
    from aiohttp_retry import ExponentialRetry
    client = Shazam(segment_duration_seconds=12, http_client=HTTPClient(retry_options=ExponentialRetry(attempts=1)))
    for clip in clips:
        match = normalize(await asyncio.wait_for(client.recognize(clip), 22), "shazam")
        if match:
            return match
    return None


def recognize(raw, allow_audd=False):
    clips = windows(raw)
    if os.getenv('EMILY_MUSIC_WORKER') != '1':
        python = Path(os.getenv('EMILY_MUSIC_PYTHON', str(Path.home()/'.local/share/emily/music-recognition-venv/bin/python')))
        if not python.is_file():
            return {'ok': False, 'estado': 'erro', 'mensagem': 'Ambiente de reconhecimento não instalado no servidor.'}
        env = dict(os.environ, EMILY_MUSIC_WORKER='1')
        try:
            process = subprocess.run([str(python), str(Path(__file__).resolve()), 'audd' if allow_audd else 'shazam'],
                input=raw, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=85, env=env)
            if process.returncode:
                return {'ok': False, 'estado': 'erro', 'mensagem': 'O serviço de reconhecimento falhou; tente novamente.'}
            return json.loads(process.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return {'ok': False, 'estado': 'erro', 'mensagem': 'O reconhecimento não respondeu a tempo.'}
    errors = []
    try:
        match = asyncio.run(_shazam(clips))
        if match:
            return {"ok": True, "musica": match}
    except Exception as error:
        errors.append("Shazam indisponível: " + type(error).__name__)
    token = os.getenv("EMILY_AUDD_TOKEN", "").strip()
    # Nunca usa crédito pago sem uma escolha explícita da chamada.
    if allow_audd and token:
        import requests
        try:
            for clip in clips[:1]:
                response = requests.post("https://api.audd.io/", data={"api_token": token, "return": "apple_music"},
                                         files={"file": ("music.wav", clip, "audio/wav")}, timeout=(6, 22))
                response.raise_for_status()
                data = response.json()
                if data.get("status") != "success":
                    raise ValueError("AudD recusou a consulta")
                match = normalize(data, "audd")
                if match:
                    return {"ok": True, "musica": match}
        except Exception as error:
            errors.append("AudD indisponível: " + type(error).__name__)
    return {"ok": False, "estado": "erro" if errors else "nao_encontrada",
            "mensagem": "; ".join(errors) if errors else "Não encontrei uma correspondência. Tente outro trecho, com menos conversa por cima.",
            "audd_configurado": bool(token)}


if __name__ == '__main__':
    print(json.dumps(recognize(sys.stdin.buffer.read(MAX_BYTES + 1), sys.argv[-1] == 'audd'), ensure_ascii=False))
