from __future__ import annotations

import io
import os
import queue
import threading
import time
import base64
import asyncio

import keyboard
from pynput import mouse as pynput_mouse
import pyaudio
import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq
import discord_bot
import wave
from fish_audio_sdk import Session, TTSRequest

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

load_dotenv()

FISH_AUDIO_KEY = os.getenv('FISH_AUDIO_KEY')
FISH_VOICE_ID = '28d1575c848841de930786be8d1ca40d'

_session_fish = Session(FISH_AUDIO_KEY)

_audio_sample_rate = 44100
_audio_channels = 1
_audio_sample_width = 2

cliente_groq = Groq(api_key=os.getenv('GROQ_API_KEY'))

# --- Configurações de áudio ---
SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2
CHANNELS = 1

CHUNK_AUDIO = 1024
TECLA_PTT = 'mb5'
TAXA_AUDIO = 16000

# --- Eventos de controle ---
# Silencia a SAÍDA DE ÁUDIO sem desligar o resto do fluxo.
#
# Existe porque pedido escrito merece resposta escrita: o Vitor digitava na
# interface e ela respondia por voz também, o que atrapalha quem está de
# headset jogando.
#
# Fica aqui, e não nos ~30 `voz.falar(...)` do main.py, porque este é o único
# ponto por onde TODOS passam — inclusive o `callback_falar` que vai pro
# automacao.py e pro agente_ui.py, que também falam por conta própria.
#
# E não afeta a call do Discord: a resposta de lá usa `gerar_audio_bytes`
# direto (resto_call._gerar_voz), não passa por falar()/falar_stream().
mudo = threading.Event()
falar_ativo = threading.Event()
escutando_ativo = threading.Event()
TECLA_CALAR = '*'
parar_fala = threading.Event()

# --- Instância PyAudio ---
_pa = pyaudio.PyAudio()

SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2
CHANNELS = 1

# --- Callback de áudio remoto (ex: discord) ---
_callback_falar_audio = None


def definir_callback_audio(callback):
    """Registra uma função pra receber o áudio gerado em cada fala."""
    global _callback_falar_audio
    _callback_falar_audio = callback


def _notificar_audio(texto: str, audio_bytes: bytes):
    """Chama o callback de áudio de forma segura, sem quebrar a fala local."""
    if _callback_falar_audio and audio_bytes:
        try:
            _callback_falar_audio(texto, audio_bytes)
        except Exception as e:
            print(f'[TTS] Erro ao notificar áudio remoto: {e}')


def _gerar_audio_bytes(texto: str) -> bytes:
    """Gera áudio via Fish Audio, retorna PCM puro pronto pro pyaudio."""
    try:
        wav_bytes = b''.join(
            _session_fish.tts(TTSRequest(
                text=texto,
                reference_id=FISH_VOICE_ID,
                format='wav',
                latency='balanced',
                streaming_model='s2.1-pro-free',
            ))
        )
        with wave.open(io.BytesIO(wav_bytes)) as wf:
            global _audio_sample_rate, _audio_channels, _audio_sample_width
            _audio_sample_rate = wf.getframerate()
            _audio_channels = wf.getnchannels()
            _audio_sample_width = wf.getsampwidth()
            return wf.readframes(wf.getnframes())
    except Exception as e:
        print(f'[TTS] Erro Fish Audio: {e}')
        return b''


def _tocar_bytes(audio_bytes: bytes):
    """Toca PCM bruto com pyaudio usando os parâmetros do áudio gerado."""
    if not audio_bytes:
        return

    stream = _pa.open(
        format=_pa.get_format_from_width(_audio_sample_width),
        channels=_audio_channels,
        rate=_audio_sample_rate,
        output=True,
    )
    try:
        for i in range(0, len(audio_bytes), CHUNK_AUDIO):
            if not falar_ativo.is_set() or parar_fala.is_set():
                break
            stream.write(audio_bytes[i:i + CHUNK_AUDIO])
    finally:
        stream.stop_stream()
        stream.close()


def falar(texto: str):
    if mudo.is_set():
        # Pedido veio escrito: a resposta é escrita. Ver o comentário de `mudo`.
        return
    parar_fala.clear()
    falar_ativo.set()
    try:
        audio_bytes = _gerar_audio_bytes(texto)
        _notificar_audio(texto, audio_bytes)
        discord_bot.tocar_pcm_discord(audio_bytes, _audio_sample_rate, _audio_channels)
        _tocar_bytes(audio_bytes)
    except Exception as e:
        print(f'[TTS] Erro em falar(): {e}')
    finally:
        falar_ativo.clear()


def falar_stream(fila_frases: queue.Queue, callback_status):
    if mudo.is_set():
        # Muda, mas NÃO cega: o callback_status continua sendo chamado frase por
        # frase, e é ele que leva o texto pro chat da interface. Sem isso, calar
        # a voz calaria a resposta inteira.
        while True:
            frase = fila_frases.get()
            if frase is None:
                return
            if frase and frase.strip():
                try:
                    callback_status(frase)
                except Exception as e:
                    print(f'[TTS] callback de status falhou no modo mudo: {e}')
        return

    parar_fala.clear()
    fila_audio = queue.Queue()

    def gerador():
        while True:
            if parar_fala.is_set():
                fila_audio.put(None)
                return
            frase = fila_frases.get()
            if frase is None:
                fila_audio.put(None)
                return
            try:
                audio_bytes = _gerar_audio_bytes(frase)
                fila_audio.put((frase, audio_bytes))
            except Exception as e:
                print(f'[TTS] Erro ao gerar frase: {e}')

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
            _notificar_audio(frase, audio_bytes)
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


def _transcrever_audio(audio: sr.AudioData) -> str:
    try:
        buffer = io.BytesIO(audio.get_wav_data())
        buffer.name = 'audio.wav'
        transcricao = cliente_groq.audio.transcriptions.create(
            file=buffer,
            model='whisper-large-v3-turbo',
            language='pt',
            prompt='Assistente pessoal Emily conversando com Vitor. Comandos comuns: abre, fecha, move, copia, pesquisa, mostra, analisa. Termos comuns: VS Code, Hollow Knight, Palworld, Python, GitHub, Chrome, Discord, pasta, arquivo, Desktop, Downloads, terminal, código, função, erro, print, loop, variável, zé ruela, paiosa, cara, para, namoral, mano, tá ligado, Dying Light, radiância, Nightmare Grimm, Área de trabalho, véi, Claude.',
        )
        return transcricao.text.strip()
    except Exception as e:
        print(f'[VOZ] Erro na transcrição: {e}')
        return ''


_BOTOES_MOUSE = {
    'mb4': pynput_mouse.Button.x1,
    'mb5': pynput_mouse.Button.x2,
    'middle': pynput_mouse.Button.middle,
}


# --- Sistema de Escuta Proativa (Gemini Live API) ---
_transcricoes_live = queue.Queue()
_enviar_frame_live = queue.Queue() # Usado pelo visao.py pra injetar frames de vídeo
_loop_live_ativo = threading.Event()
_live_session = None

def _loop_live_async():
    asyncio.run(_iniciar_sessao_live())

async def _iniciar_sessao_live():
    global _live_session
    if not genai:
        print("[VOZ] pacote google-genai ausente. Não é possível usar o Gemini Live.")
        return

    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("EMILY_LIVE_LOCATION", "us-central1")
    if not project_id:
        print("[VOZ] GOOGLE_CLOUD_PROJECT ausente. Live API desabilitada.")
        return

    client = genai.Client(vertexai=True, project=project_id, location=location)
    # Usa o modelo recomendado de áudio/live com proactivity
    model = os.getenv("EMILY_LIVE_MODEL", "gemini-live-2.5-flash-preview-native-audio-09-2025") 

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        proactivity=types.ProactivityConfig(proactive_audio=True),
        # Habilita a transcrição do áudio de entrada no ServerContent
        # (no SDK genai pode vir em ferramentas ou como campo direto dependendo da versão, 
        # normalmente suportado via kwargs ou diretamente no schema)
    )
    
    # Sistema de instrução da Live API
    system_instruction = (
        "Só responda quando o Vitor claramente estiver falando com você, "
        "pedindo sua opinião, fazendo uma pergunta direta, ou pedindo ajuda. "
        "Ignore conversas com outras pessoas, calls, ou quando ele estiver falando sozinho/pensando alto.\n\n"
        "Durante os modos de observação de tela (modo jogo ou assistir_tela), você "
        "TAMBÉM pode comentar espontaneamente, mesmo sem o Vitor falar, quando algo "
        "visualmente relevante e notável acontecer (evento importante no jogo, morte, "
        "item raro, mudança marcante de cena). Não comente mudanças triviais ou "
        "repetitivas — seja seletiva, como um amigo assistindo do lado, não um "
        "narrador constante."
    )

    try:
        # Algumas versões do SDK exigem system_instruction separadamente
        config.system_instruction = types.Content(parts=[types.Part.from_text(text=system_instruction)])
    except Exception:
        pass
        
    # Força o campo input_audio_transcription para garantir que o STT venha,
    # mesmo se o dataclass estrito não o expuser diretamente, usamos o model_dump/hack se preciso, 
    # mas o SDK mais recente (0.1/1.74) normalmente aceita kwargs em LiveConnectConfig
    # O user explicou: "habilite input_audio_transcription na LiveConnectConfig da sessão"
    
    try:
        config.input_audio_transcription = types.AudioTranscriptionConfig()
    except Exception:
        pass
        
    # Ativa também a transcrição da fala da PRÓPRIA Live API para pegar reações espontâneas
    # O SDK google-genai atual não tem suporte a output_audio_transcription na LiveConnectConfig.
    # O atributo não existe no dataclass, por isso causou erro.
        
    print("[VOZ] Conectando ao Gemini Live (Vertex AI)...")
    try:
        async with client.aio.live.connect(model=model, config=config) as session:
            _live_session = session
            _loop_live_ativo.set()
            print("[VOZ] Gemini Live conectado! Escuta contínua ativada.")

            async def enviar_audio():
                stream = _pa.open(format=pyaudio.paInt16, channels=1, rate=TAXA_AUDIO, input=True, frames_per_buffer=1024)
                try:
                    while _loop_live_ativo.is_set():
                        # Se a Emily estiver falando, pausa a escuta temporariamente para não se ouvir (echo cancellation simples)
                        if falar_ativo.is_set() or mudo.is_set():
                            await asyncio.sleep(0.1)
                            continue

                        data = stream.read(1024, exception_on_overflow=False)
                        # Envia audio
                        try:
                            await session.send(input={"data": data, "mime_type": "audio/pcm;rate=16000"})
                        except:
                            pass
                        
                        # Verifica se tem frame de vídeo na fila
                        try:
                            while not _enviar_frame_live.empty():
                                frame_b64 = _enviar_frame_live.get_nowait()
                                frame_bytes = base64.b64decode(frame_b64)
                                await session.send(input={"data": frame_bytes, "mime_type": "image/jpeg"})
                                
                            # Limpa frames velhos se a fila crescer demais
                            if _enviar_frame_live.qsize() > 5:
                                while _enviar_frame_live.qsize() > 2:
                                    try:
                                        _enviar_frame_live.get_nowait()
                                    except:
                                        pass
                        except Exception:
                            pass
                        
                        await asyncio.sleep(0.001)
                finally:
                    stream.stop_stream()
                    stream.close()
                    
            async def nudges_periodicos():
                # Loop para enviar turnos de avaliação artificial quando a tela está sendo assistida.
                # A API só avalia o contexto de imagens acumuladas quando entra um turno (VAD ou Text).
                import main # Precisamos ler os eventos globais do main.py
                while _loop_live_ativo.is_set():
                    await asyncio.sleep(10) # 10s é um intervalo seguro pra não engolir tokens à toa
                    
                    if main.modo_jogo_ativo.is_set() or main.modo_assistir_tela_ativo.is_set():
                        print("[VIDEO] verificação automática disparada (nudge de texto)")
                        try:
                            # Dispara um turno de texto proativo pra forçar a leitura do buffer de vídeo.
                            # O texto do nudge nunca é dito e não fica no contexto pra ela.
                            nudge_text = "[verificação automática] Observe os frames recentes da tela. Se algo visualmente relevante e notável aconteceu desde a última verificação, comente brevemente. Se nada de interessante mudou, não diga nada."
                            await session.send(input=nudge_text)
                        except Exception as e:
                            print(f"[VIDEO] falha no nudge: {e}")

            async def receber_respostas():
                while _loop_live_ativo.is_set():
                    try:
                        tem_transcricao = False
                        tem_resposta_modelo = False
                        ja_enviou_neste_turno = False
                        transcricao_texto = ""
                        
                        async for response in session.receive():
                            try:
                                if hasattr(response, "server_content") and response.server_content:
                                    sc = response.server_content
                                    
                                    if getattr(sc, "interrupted", False):
                                        print("[VOZ] Fala interrompida")
                                    
                                    if hasattr(sc, "input_audio_transcription") and sc.input_audio_transcription:
                                        transcricao_texto = sc.input_audio_transcription.text
                                        tem_transcricao = True
                                        print(f"  -> [DEBUG] Recebeu input_audio_transcription: '{transcricao_texto}'")
                                        
                                    if hasattr(sc, "output_audio_transcription") and sc.output_audio_transcription:
                                        # Transcrição da própria Live API (reação espontânea)
                                        out_texto = sc.output_audio_transcription.text
                                        if out_texto and out_texto.strip() and not transcricao_texto:
                                            # Transcrição da Live API *sem* fala do Vitor
                                            print(f"  -> [DEBUG] REAÇÃO ESPONTÂNEA DETECTADA: '{out_texto}'")
                                            _transcricoes_live.put(f"[Situação notada na tela, sem fala do Vitor]: {out_texto.strip()}. Reaja com sua personalidade, curto.")
                                            ja_enviou_neste_turno = True
                                    
                                    # Fallback genérico caso o SDK tenha nomeado de outra forma
                                    if not transcricao_texto and not ja_enviou_neste_turno:
                                        try:
                                            d = sc.model_dump()
                                            for k, v in d.items():
                                                if "transcription" in k.lower() or "input" in k.lower():
                                                    if isinstance(v, dict) and "text" in v:
                                                        transcricao_texto = v["text"]
                                                        tem_transcricao = True
                                                        print(f"  -> [DEBUG] Recebeu transcrição (fallback de dicionário): '{transcricao_texto}'")
                                                        break
                                        except:
                                            pass
                                            
                                    if hasattr(sc, "model_turn") and sc.model_turn:
                                        tem_resposta_modelo = True
                                        
                                        # OTIMIZAÇÃO DE LATÊNCIA:
                                        # Não espera o turno inteiro (turn_complete) pra encaminhar a transcrição pro cérebro.
                                        # Se chegou o primeiro pedaço de resposta, a Live API já decidiu que a fala era com ela.
                                        # Despacha imediatamente!
                                        if not ja_enviou_neste_turno and transcricao_texto and transcricao_texto.strip():
                                            print(f"  -> [DEBUG] Primeiro chunk de resposta detectado. Despachando a transcrição de imediato para cortar latência!")
                                            _transcricoes_live.put(transcricao_texto.strip())
                                            ja_enviou_neste_turno = True
                                    
                                    if getattr(sc, "turn_complete", False):
                                        print(f"  -> [DEBUG] Recebeu turn_complete=True. (Teve transcrição? {tem_transcricao} | Teve resposta? {tem_resposta_modelo})")
                                        
                                        if tem_transcricao and not tem_resposta_modelo:
                                            print(f"  -> [DEBUG] Silêncio proposital da Live API. Descartando transcrição: '{transcricao_texto}'")
                                        elif not ja_enviou_neste_turno and tem_resposta_modelo and transcricao_texto and transcricao_texto.strip():
                                            print(f"  -> [DEBUG] Despachando transcrição no turn_complete (fallback de latência).")
                                            _transcricoes_live.put(transcricao_texto.strip())
                                            ja_enviou_neste_turno = True
                                            
                                        # Reseta para o próximo turno
                                        tem_transcricao = False
                                        tem_resposta_modelo = False
                                        ja_enviou_neste_turno = False
                                        transcricao_texto = ""

                            except Exception as e:
                                print(f"[VOZ] Erro ao parsear Live API response: {e}")
                        
                        print("[VOZ] Turno concluído, voltando a escutar...")
                    except Exception as loop_e:
                        print(f"[VOZ] Erro no turno de resposta: {loop_e}")
                        await asyncio.sleep(1)
            
            await asyncio.gather(enviar_audio(), nudges_periodicos(), receber_respostas())
    except Exception as e:
        print(f"[VOZ] Falha na conexão Live: {e}")
        _loop_live_ativo.clear()

def iniciar_escuta_proativa():
    t = threading.Thread(target=_loop_live_async, daemon=True)
    t.start()
    
# Inicia automaticamente
iniciar_escuta_proativa()

def ouvir_ptt(tecla: str = TECLA_PTT, callback_gravando=None) -> str:
    """
    Nova implementação: usa o stream contínuo da Live API de forma primária.
    Retorna o texto da fila de transcrição.
    O PTT original via teclado serve apenas como fallback de emergência
    (quando o usuário aperta o botão, capturamos normalmente e mandamos pro Whisper Local/Groq).
    """
    
    # 1. Checa a fila do Live API constantemente (sem bloquear 100%)
    # Como a interface é chamada num while True pelo main.py, nós podemos esperar
    # tanto pela fila quanto por uma tecla.
    
    # Vamos esperar 1 segundo por vez
    start = time.time()
    while time.time() - start < 0.5:
        if not _transcricoes_live.empty():
            return _transcricoes_live.get()
        time.sleep(0.1)

    while falar_ativo.is_set():
        time.sleep(0.05)
        
    eh_mouse = tecla.lower() in _BOTOES_MOUSE

    # Verifica se a tecla PTT foi pressionada manualmente (Fallback de emergência)
    apertou_tecla = False
    
    if eh_mouse:
        botao_alvo = _BOTOES_MOUSE[tecla.lower()]
        # Checa rapidinho se o botão tá pressionado. 
        # A API do pynput listener é baseada em evento. Aqui usaremos um listener momentâneo ou ignoraremos.
        # Pra não bloquear o loop principal (que precisa ler _transcricoes_live),
        # Vamos apenas pular se não for rápido, ou reusar o while True.
    else:
        if keyboard.is_pressed(tecla):
            apertou_tecla = True
            
    if apertou_tecla:
        if callback_gravando:
            callback_gravando()

        escutando_ativo.set()
        print('[PTT-Fallback] Gravando manual...')

        frames = []
        stream = _pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=TAXA_AUDIO,
            input=True,
            frames_per_buffer=CHUNK_AUDIO,
        )
        try:
            while keyboard.is_pressed(tecla):
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
        finally:
            stream.stop_stream()
            stream.close()
            escutando_ativo.clear()

        if len(frames) < 5:
            return ''

        raw_data = b''.join(frames)
        audio = sr.AudioData(raw_data, TAXA_AUDIO, 2)
        texto = _transcrever_audio(audio)
        if texto:
            print(f'[PTT-Fallback] Você disse: {texto}')
        return texto

    return ""


def _calar_emily():
    if falar_ativo.is_set():
        parar_fala.set()
        falar_ativo.clear()
        print('[VOZ] Emily calada!')


def gerar_audio_bytes(texto: str) -> bytes:
    """Expõe a geração de áudio em bytes pro discord_bot usar na call."""
    return _gerar_audio_bytes(texto)


keyboard.add_hotkey(TECLA_CALAR, _calar_emily)
