from __future__ import annotations

import io
import os
import queue
import threading
import time

import keyboard
from pynput import mouse as pynput_mouse
import pyaudio
import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq
import discord_bot
import wave
from fish_audio_sdk import Session, TTSRequest
load_dotenv()

FISH_AUDIO_KEY = os.getenv("FISH_AUDIO_KEY")
FISH_VOICE_ID  = "3bed8e1329df4d7ebfedf0c40f7ca1d9"

_session_fish = Session(FISH_AUDIO_KEY)

# Esses valores são atualizados automaticamente com base no áudio gerado
_audio_sample_rate  = 44100
_audio_channels     = 1
_audio_sample_width = 2

cliente_groq     = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ──────────────────────────────────────────────
# CONFIGURAÇÕES
# ──────────────────────────────────────────────
# Formato PCM — tocado direto pelo pyaudio, sem precisar de pydub
SAMPLE_RATE  = 22050 
SAMPLE_WIDTH = 2       
CHANNELS     = 1       

CHUNK_AUDIO = 1024
TECLA_PTT   = "mb5"    
TAXA_AUDIO  = 16000 

# ──────────────────────────────────────────────
# EVENTOS DE CONTROLE
# ──────────────────────────────────────────────
falar_ativo     = threading.Event()
escutando_ativo = threading.Event()
TECLA_CALAR = "*"
parar_fala = threading.Event()

# ──────────────────────────────────────────────
# PYAUDIO INICIADO UMA SÓ VEZ
# ──────────────────────────────────────────────
_pa = pyaudio.PyAudio()

# Formato PCM igual ao do Cartesia — pyaudio toca direto, sem converter nada
SAMPLE_RATE  = 22050
SAMPLE_WIDTH = 2
CHANNELS     = 1

# ══════════════════════════════════════════════
#   TTS — GERAÇÃO E REPRODUÇÃO DE ÁUDIO
# ══════════════════════════════════════════════

def _gerar_audio_bytes(texto: str) -> bytes:
    """Gera áudio via Fish Audio, retorna PCM puro pronto pro pyaudio."""
    global _audio_sample_rate, _audio_channels, _audio_sample_width
    try:
        wav_bytes = b"".join(
            _session_fish.tts(TTSRequest(
                text=texto,
                reference_id=FISH_VOICE_ID,
                format="wav",
                latency="balanced",
                backend="s2-pro",
            ))
        )
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            _audio_sample_rate  = wf.getframerate()
            _audio_channels     = wf.getnchannels()
            _audio_sample_width = wf.getsampwidth()
            return wf.readframes(wf.getnframes())
    except Exception as e:
        print(f"[TTS] Erro Fish Audio: {e}")
        return b""


def _tocar_bytes(audio_bytes: bytes):
    """Toca PCM bruto com pyaudio usando os parâmetros do áudio gerado."""
    if not audio_bytes:
        return

    stream = _pa.open(
        format=_pa.get_format_from_width(_audio_sample_width),
        channels=_audio_channels,
        rate=_audio_sample_rate,
        output=True
    )

    try:
        for i in range(0, len(audio_bytes), CHUNK_AUDIO):
            if not falar_ativo.is_set() or parar_fala.is_set():
                break
            stream.write(audio_bytes[i:i + CHUNK_AUDIO])
    finally:
        stream.stop_stream()
        stream.close()


# ──────────────────────────────────────────────
# FALA NORMAL (texto completo de uma vez)
# ──────────────────────────────────────────────
def falar(texto: str):
    parar_fala.clear()
    falar_ativo.set()
    try:
        audio_bytes = _gerar_audio_bytes(texto)
        discord_bot.tocar_pcm_discord(audio_bytes, _audio_sample_rate, _audio_channels)
        _tocar_bytes(audio_bytes)
    except Exception as e:
        print(f"[TTS] Erro em falar(): {e}")
    finally:
        falar_ativo.clear()


# ──────────────────────────────────────────────
# FALA EM STREAMING
# ──────────────────────────────────────────────
def falar_stream(fila_frases: queue.Queue, callback_status):
    parar_fala.clear()
    fila_audio: queue.Queue = queue.Queue()

    def gerador():
        while True:
            if parar_fala.is_set():
                fila_audio.put(None)
                break
            frase = fila_frases.get()
            if frase is None:
                fila_audio.put(None)
                break
            try:
                audio_bytes = _gerar_audio_bytes(frase)
                fila_audio.put((frase, audio_bytes))
            except Exception as e:
                print(f"[TTS] Erro ao gerar frase: {e}")

    def tocador():
        falar_ativo.set()
        while True:
            item = fila_audio.get()
            if item is None:
                break
            if parar_fala.is_set():
                break
            frase, audio_bytes = item
            callback_status(frase)
            discord_bot.tocar_pcm_discord(audio_bytes, _audio_sample_rate, _audio_channels)
            _tocar_bytes(audio_bytes)
            time.sleep(0.03)
        falar_ativo.clear()

    t_gerador = threading.Thread(target=gerador, daemon=True)
    t_tocador = threading.Thread(target=tocador, daemon=True)
    t_gerador.start()
    t_tocador.start()
    t_gerador.join()
    t_tocador.join()


# ══════════════════════════════════════════════
#   TRANSCRIÇÃO — GROQ + WHISPER
# ══════════════════════════════════════════════

def _transcrever_audio(audio: sr.AudioData) -> str:
    try:
        buffer = io.BytesIO(audio.get_wav_data())
        buffer.name = "audio.wav"
        transcricao = cliente_groq.audio.transcriptions.create(
            file=buffer,
            model="whisper-large-v3-turbo",
            language="pt",
            prompt=(
                "Conversa com assistente pessoal chamada Emily. "
                "Vitor faz pedidos como: abre, fecha, move, copia, pesquisa, mostra, analisa. "
                "Termos comuns: VS Code, Holllow Knight, Palworld, Python, GitHub, Chrome, Discord, pasta, arquivo, "
                "Desktop, Downloads, terminal, código, função, erro, print, loop, variável, zé ruela, paiosa, cara, para, namoral, mano, tá ligado, Dying light, radiancia,"
                "Nightmare Grimm, Área de trabalho, véi, Claude."
            )
        )
        return transcricao.text.strip()
    except Exception as e:
        print(f"[VOZ] Erro na transcrição: {e}")
        return ""


# ══════════════════════════════════════════════
#   PRESS-TO-TALK
# ══════════════════════════════════════════════

_BOTOES_MOUSE = {
    "mb4":    pynput_mouse.Button.x1,
    "mb5":    pynput_mouse.Button.x2,
    "middle": pynput_mouse.Button.middle,
}

def ouvir_ptt(tecla: str = TECLA_PTT, callback_gravando=None) -> str:
    while falar_ativo.is_set():
        time.sleep(0.05)

    eh_mouse = tecla.lower() in _BOTOES_MOUSE

    # ── Espera o botão/tecla ser pressionado ──
    if eh_mouse:
        botao_alvo  = _BOTOES_MOUSE[tecla.lower()]
        pressionado = threading.Event()
        solto       = threading.Event()

        def ao_clicar(x, y, botao, pressed):
            if botao == botao_alvo:
                if pressed:
                    pressionado.set()
                else:
                    solto.set()

        listener = pynput_mouse.Listener(on_click=ao_clicar)
        listener.start()

        print(f"[PTT] Aguardando botão {tecla}...")
        pressionado.wait()
    else:
        print(f"[PTT] Aguardando tecla {tecla}...")
        keyboard.wait(tecla)

    if callback_gravando:
        callback_gravando()

    escutando_ativo.set()
    print("[PTT] Gravando...")

    frames = []
    stream = _pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=TAXA_AUDIO,
        input=True,
        frames_per_buffer=CHUNK_AUDIO
    )

    try:
        if eh_mouse:
            while not solto.is_set():
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
        else:
            while keyboard.is_pressed(tecla):
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
    finally:
        stream.stop_stream()
        stream.close()
        escutando_ativo.clear()
        if eh_mouse:
            listener.stop()

    if len(frames) < 5:
        print("[PTT] Gravação muito curta, ignorando...")
        return ""

    raw_data = b"".join(frames)
    audio    = sr.AudioData(raw_data, TAXA_AUDIO, 2)
    texto    = _transcrever_audio(audio)
    if texto:
        print(f"[PTT] Você disse: {texto}")
    return texto

def _calar_emily():
    if falar_ativo.is_set():
        parar_fala.set()
        falar_ativo.clear()
        print("[VOZ] Emily calada!")

keyboard.add_hotkey(TECLA_CALAR, _calar_emily)