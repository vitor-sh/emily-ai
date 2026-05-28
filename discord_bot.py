from __future__ import annotations

import asyncio
import io
import json
import threading
from pathlib import Path
from typing import Optional

import discord

_CONFIG_PATH = Path.home() / ".emily_discord.json"

_CONFIG_PADRAO = {
    "token":          "COLE_SEU_TOKEN_AQUI",
    "canal_texto_id": 0,
    "canal_voz_id":   0,
    "prefixo":        "🤖 Emily: ",
    "prefixo_comando": "?",
    "enviar_texto":   True
}

_SAMPLE_RATE = 22050
_CHANNELS    = 1

def _carregar_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Discord] Erro ao ler config: {e}")
    _CONFIG_PATH.write_text(
        json.dumps(_CONFIG_PADRAO, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[Discord] Config criada em {_CONFIG_PATH}")
    return dict(_CONFIG_PADRAO)

_loop:         Optional[asyncio.AbstractEventLoop] = None
_canal_texto:  Optional[discord.TextChannel]       = None
_voice_client: Optional[discord.VoiceClient]       = None
_config:       dict = {}
_pronto:       bool = False

_callback_texto:       Optional[callable] = None
_escuta_discord_ativa: threading.Event   = threading.Event()


def _criar_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states     = True
    return discord.Client(intents=intents)

_client = _criar_client()


@_client.event
async def on_ready():
    global _canal_texto, _pronto

    canal_texto_id = _config.get("canal_texto_id", 0)
    if canal_texto_id:
        _canal_texto = _client.get_channel(canal_texto_id)

    _pronto = True
    print(f"[Discord] Bot conectado como '{_client.user}'")

    _escuta_discord_ativa.set()
    print("[Discord] Escuta de texto ativada automaticamente") 


@_client.event
async def on_message(message: discord.Message):
    if message.author == _client.user:
        return

    if not _escuta_discord_ativa.is_set():
        return

    if not _callback_texto:
        return

    prefixo_comando = _config.get("prefixo_comando", "?")

    # Checa se a mensagem começa com o prefixo
    if not message.content.startswith(prefixo_comando):
        return

    # Remove o prefixo e manda o resto pra Emily
    texto = message.content[len(prefixo_comando):].strip()

    if not texto:
        return

    print(f"[Discord] Comando de {message.author.name}: '{texto}'")
    threading.Thread(target=_callback_texto, args=(texto, message.author.id, message.author.display_name), daemon=True).start()

@_client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    usuario_id = _config.get("usuario_id", 0)
    if not usuario_id or member.id != usuario_id:
        return  # ignora qualquer pessoa que não seja o Vitor

    # Vitor entrou ou trocou de canal
    if after.channel is not None:
        print(f"[Discord] Vitor entrou no canal '{after.channel.name}', conectando Emily...")
        await _conectar_voz(after.channel.id)

    # Vitor saiu de todos os canais
    elif before.channel is not None and after.channel is None:
        if _voice_client and _voice_client.is_connected():
            await _voice_client.disconnect()
            print("[Discord] Vitor saiu da call, Emily desconectada.")


async def _conectar_voz(canal_id: int) -> bool:
    global _voice_client
    canal = _client.get_channel(canal_id)
    if not canal or not isinstance(canal, discord.VoiceChannel):
        print(f"[Discord] Canal de voz {canal_id} não encontrado!")
        return False
    try:
        if _voice_client and _voice_client.is_connected():
            if _voice_client.channel.id == canal_id:
                return True
            await _voice_client.move_to(canal)
        else:
            _voice_client = await canal.connect()
        print(f"[Discord] Entrou no canal de voz: '{canal.name}'")
        return True
    except Exception as e:
        print(f"[Discord] Erro ao entrar no canal de voz: {e}")
        return False


async def _tocar_pcm_async(audio_bytes: bytes, sample_rate: int = 22050, channels: int = 1) -> None:
    global _voice_client

    if not audio_bytes:
        return

    if not _voice_client or not _voice_client.is_connected():
        canal_voz_id = _config.get("canal_voz_id", 0)
        if not canal_voz_id or not await _conectar_voz(canal_voz_id):
            return

    while _voice_client.is_playing():
        await asyncio.sleep(0.05)

    try:
        source = discord.FFmpegPCMAudio(
            io.BytesIO(audio_bytes),
            pipe=True,
            before_options=f"-f s16le -ar {sample_rate} -ac {channels}",
            options="-vn"
        )
        _voice_client.play(source)
    except Exception as e:
        print(f"[Discord] Erro ao tocar PCM: {e}")


async def _enviar_texto_async(texto: str) -> None:
    if not _canal_texto:
        return
    prefixo  = _config.get("prefixo", "")
    mensagem = f"{prefixo}{texto}"
    while mensagem:
        parte, mensagem = mensagem[:2000], mensagem[2000:]
        await _canal_texto.send(parte)


# ─────────────────────────────────────────────
# FUNÇÕES PÚBLICAS
# ─────────────────────────────────────────────

def tocar_pcm_discord(audio_bytes: bytes, sample_rate: int = 22050, channels: int = 1) -> None:
    if not _pronto or not _loop or not audio_bytes:
        return
    asyncio.run_coroutine_threadsafe(
        _tocar_pcm_async(audio_bytes, sample_rate, channels), _loop
    )


def enviar_texto_discord(texto: str) -> None:
    if not _pronto or not _loop or not _config.get("enviar_texto", True):
        return
    asyncio.run_coroutine_threadsafe(_enviar_texto_async(texto), _loop)


def definir_callback_texto(fn) -> None:
    global _callback_texto
    _callback_texto = fn


def ativar_escuta_discord() -> None:
    _escuta_discord_ativa.set()
    print("[Discord] Escuta de texto ativada!")


def desativar_escuta_discord() -> None:
    _escuta_discord_ativa.clear()
    print("[Discord] Escuta de texto desativada!")


def desconectar_voz() -> None:
    if not _pronto or not _loop:
        return

    async def _desconectar():
        global _voice_client
        if _voice_client and _voice_client.is_connected():
            await _voice_client.disconnect()
            print("[Discord] Bot desconectado do canal de voz.")

    future = asyncio.run_coroutine_threadsafe(_desconectar(), _loop)
    try:
        future.result(timeout=5)
    except Exception as e:
        print(f"[Discord] Erro ao desconectar: {e}")


def inicializar() -> None:
    global _config

    _config = _carregar_config()
    token   = _config.get("token", "")

    if not token or token == "COLE_SEU_TOKEN_AQUI":
        print(f"[Discord] Configure o token em: {_CONFIG_PATH}")
        return

    def _rodar():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        try:
            _loop.run_until_complete(_client.start(token))
        except Exception as e:
            print(f"[Discord] Bot encerrado: {e}")

    threading.Thread(target=_rodar, daemon=True).start()
    print("[Discord] Bot iniciando em background...")