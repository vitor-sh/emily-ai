from __future__ import annotations

import asyncio
import io
import json
import threading
import time
from pathlib import Path
from typing import Optional
from discord.ext import voice_recv

import discord

APELIDOS_MEMBROS = {
    731604438212673638: "comedor de Marcio Augusto",
    764277113444368434: "Bisqui",
    1014239583677988964: "Pior jogador de Elden Ring",
    843189524480655380: "Sempre se acha o protagonista, é ignorante pra krl, completamente irritante, pode xingar com tudo que tem, usa todo seu arsenal de palavrão que eu te ensei",
}

_CONFIG_PATH = Path.home() / ".emily_discord.json"

_CONFIG_PADRAO = {
    "token":          "COLE_SEU_TOKEN_AQUI",
    "canal_texto_id": 0,
    "canal_voz_id":   0,
    "prefixo":        "",
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
_emily_em_call_ativa: bool = False  # True quando Emily entrou por pedido de alguém


# ─── JANELA DE CONTEXTO ───
_JANELA_CONTEXTO        = 15
_COOLDOWN_CONTEXTO      = 30
_historico_janela:       dict = {}
_ultimo_contexto_canal:  dict = {}

# ─── FILA DE MENÇÕES ───
import queue
_fila_mencoes: dict = {}        # canal_id -> Queue
_fila_workers: dict = {}        # canal_id -> thread ativa
_DELAY_ENTRE_RESPOSTAS = 4      # segundos entre uma resposta e outra


def _criar_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states     = True
    intents.members          = True
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

    await _client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="escutando o Vitor"
        ),
        status=discord.Status.online
    )


@_client.event
async def on_message(message: discord.Message):
    if message.author == _client.user:
        return

    if not _escuta_discord_ativa.is_set():
        return

    if not _callback_texto:
        return

    prefixo_comando = _config.get("prefixo_comando", "?")
    texto = message.content.strip()
    canal = message.channel

    if not texto:
        return

    # ─── ACUMULA JANELA DE CONTEXTO ───
    if canal.id not in _historico_janela:
        _historico_janela[canal.id] = []

    nome_exibido = APELIDOS_MEMBROS.get(message.author.id, message.author.display_name)

    # Extrai imagens se tiver — await direto pois já estamos numa coroutine
    imagens_b64 = []
    if message.attachments:
        imagens_b64 = await _extrair_imagens_mensagem(message)

    _historico_janela[canal.id].append({
        "nome":    nome_exibido,
        "texto":   texto,
        "message": message,
        "user_id": message.author.id,
        "imagens": imagens_b64,
    })

    if len(_historico_janela[canal.id]) > _JANELA_CONTEXTO:
        _historico_janela[canal.id].pop(0)

    # ─── COMANDO DIRETO (com prefixo) ───
    if texto.startswith(prefixo_comando):
        texto_sem_prefixo = texto[len(prefixo_comando):].strip()
        if not texto_sem_prefixo:
            return
        print(f"[Discord] Comando de {message.author.name}: '{texto_sem_prefixo}'")
        threading.Thread(
            target=_callback_texto,
            args=(texto_sem_prefixo, message.author.id, message.author.display_name),
            daemon=True
        ).start()
        return

    # ─── MENÇÃO DIRETA ou REPLY NA EMILY ───
    bot_mencionado = _client.user in message.mentions
    reply_na_emily = (
        message.reference is not None
        and message.reference.resolved is not None
        and isinstance(message.reference.resolved, discord.Message)
        and message.reference.resolved.author == _client.user
    )

    if bot_mencionado or reply_na_emily:
        texto_limpo = texto.replace(f"<@{_client.user.id}>", "").strip()
        if not texto_limpo:
            texto_limpo = texto

        janela = _historico_janela.get(canal.id, [])
        historico_fmt = "\n".join(
             f"{item['nome']}: {item['texto']}" for item in janela
         ) if janela else ""

        print(f"[Discord] Emily mencionada por {message.author.display_name}: '{texto_limpo[:60]}'")
        _enfileirar_mencao(canal.id, texto_limpo, nome_exibido, message, historico_fmt)
        return

    # ─── PARTICIPAÇÃO ESPONTÂNEA ───
    if len(texto) < 2:
        return

    print(f"[Discord] Mensagem de {nome_exibido} no #{canal.name}: '{texto[:60]}'")
    threading.Thread(
        target=_avaliar_e_responder_contexto,
        args=(canal.id, texto, nome_exibido, message, False, ""),
        daemon=True,
    ).start()
    
async def _extrair_imagens_mensagem(message: discord.Message) -> list:
    """Baixa os anexos de imagem da mensagem e retorna lista de dicts com base64 e media_type."""
    import base64
    import aiohttp

    _TIPOS = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".webp": "image/webp",
    }

    imagens = []
    for anexo in message.attachments:
        ext = next((e for e in _TIPOS if anexo.filename.lower().endswith(e)), None)
        if not ext:
            continue
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(anexo.url) as resp:
                    dados = await resp.read()
                    imagens.append({
                        "data":       base64.b64encode(dados).decode("utf-8"),
                        "media_type": _TIPOS[ext],
                    })
                    print(f"[Discord] Imagem capturada: {anexo.filename} ({_TIPOS[ext]})")
        except Exception as e:
            print(f"[Discord] Erro ao baixar imagem {anexo.filename}: {e}")
    return imagens


# ─────────────────────────────────────────────────────────────────
# AVALIAÇÃO DE CONTEXTO EM TEMPO REAL
# ─────────────────────────────────────────────────────────────────

def _contexto_memoria() -> str:
    """Retorna um bloco de texto com os fatos da memória do Vitor, para injetar no contexto."""
    try:
        import memoria as _mem
        return _mem.formatar_para_prompt()
    except Exception:
        return ""


def _avaliar_e_responder_contexto(
    canal_id: int,
    ultima_msg: str,
    nome_autor: str,
    message_original,
    ignorar_cooldown: bool = False,
    historico_externo: str = "",
):
    import modelo as modelo_module

    agora = time.time()

    if ignorar_cooldown:
        pass
    else:
        if agora - _ultimo_contexto_canal.get(canal_id, 0) < _COOLDOWN_CONTEXTO:
            return
        
    
    # ─── PEDIDO PRA SAIR DA CALL ───
    if _emily_em_call_ativa and _voice_client and _voice_client.is_connected():
        t = modelo_module._normalizar_texto(ultima_msg)
        if any(g in t for g in ("sai da call", "sai call", "sai do canal", "desconecta", "tchau call", "deixa a call")):
            async def _sair():
                global _emily_em_call_ativa
                _emily_em_call_ativa = False
                if _voice_client and _voice_client.is_connected():
                    await _voice_client.disconnect()
                await message_original.reply("saí!")
            if _loop:
                asyncio.run_coroutine_threadsafe(_sair(), _loop)
            return

    # ─── SE EMILY TÁ NA CALL ───
    if _emily_em_call_ativa and _voice_client and _voice_client.is_connected():
        # Verifica se o autor tá na mesma call
        autor_id = message_original.author.id
        canal_voz_autor = _membro_em_call(autor_id)

        if canal_voz_autor and canal_voz_autor.id == _voice_client.channel.id:
            # Autor tá na call — responde por lá
            janela = _historico_janela.get(canal_id, [])
            historico_fmt = historico_externo or ("\n".join(
                f"{item['nome']}: {item['texto']}" for item in janela[:-1]
            ) if len(janela) > 1 else "")

            imagens = janela[-1].get("imagens", []) if janela else []
            resultado = modelo_module.avaliar_contexto_canal(historico_fmt, ultima_msg, nome_autor, imagens)

            if not resultado.get("responder"):
                return

            resposta = resultado.get("resposta", "").strip()
            if not resposta:
                return

            _ultimo_contexto_canal[canal_id] = time.time()
            print(f"[Discord] Respondendo na call pra {nome_autor}")
            asyncio.run_coroutine_threadsafe(
                _entrar_falar_e_sair(_voice_client.channel, resposta), _loop
            )
            return
        else:
            # Autor não tá na call — avisa pra entrar
            _ultimo_contexto_canal[canal_id] = time.time()

            async def _avisar():
                try:
                    await message_original.reply(
                        f"tô na call agora, entra lá se quiser falar comigo"
                    )
                except Exception as e:
                    print(f"[Discord] Erro ao avisar call: {e}")

            if _loop:
                asyncio.run_coroutine_threadsafe(_avisar(), _loop)
            return

    # ─── SE ALGUÉM PEDE PRA ENTRAR NA CALL ───
    if modelo_module.pede_para_entrar_call(ultima_msg):
        canal_voz = _membro_em_call(message_original.author.id)
        if canal_voz:
            async def _entrar_e_confirmar():
                global _emily_em_call_ativa
                sucesso = await _conectar_voz(canal_voz.id)
                if sucesso:
                    _emily_em_call_ativa = True
                    import voz as voz_module
                    audio = voz_module.gerar_audio_bytes("Oi, cheguei!")
                    if audio:
                        await _tocar_pcm_async(audio, 44100, 1)
            if _loop:
                asyncio.run_coroutine_threadsafe(_entrar_e_confirmar(), _loop)
            return
        else:
            # Pediu pra entrar mas não tá em nenhum canal
            async def _sem_canal():
                await message_original.reply("entra num canal de voz primeiro")
            if _loop:
                asyncio.run_coroutine_threadsafe(_sem_canal(), _loop)
            return

    # ─── FLUXO NORMAL DE CHAT ───
    janela = _historico_janela.get(canal_id, [])

    if historico_externo:
        historico_fmt = historico_externo
    else:
        historico_fmt = "\n".join(
            f"{item['nome']}: {item['texto']}" for item in janela[:-1]
        ) if len(janela) > 1 else ""

    # ── Injeta memória do Vitor no contexto para o modelo ter personalização ──
    ctx_mem = _contexto_memoria()
    if ctx_mem:
        historico_fmt = f"{ctx_mem}\n\n---\n{historico_fmt}" if historico_fmt else ctx_mem

    imagens = janela[-1].get("imagens", []) if janela else []
    resultado = modelo_module.avaliar_contexto_canal(historico_fmt, ultima_msg, nome_autor, imagens)

    if not resultado.get("responder"):
        return

    resposta = resultado.get("resposta", "").strip()
    if not resposta:
        return

    _ultimo_contexto_canal[canal_id] = time.time()
    print(f"[Discord] Entrando na conversa — mencionando: {resultado.get('mencionar', '')}")

    partes = modelo_module.quebrar_resposta_discord(resposta)

    async def _enviar():
        try:
            await message_original.reply(partes[0])
            for parte in partes[1:]:
                await asyncio.sleep(2.5)
                await message_original.channel.send(parte)
        except Exception as e:
            print(f"[Discord] Erro ao entrar na conversa: {e}")

    if _loop:
        asyncio.run_coroutine_threadsafe(_enviar(), _loop)
        

def _worker_fila_mencoes(canal_id: int):
    while True:
        try:
            item = _fila_mencoes[canal_id].get(timeout=30)
        except queue.Empty:
            _fila_workers[canal_id] = None  # marca como inativo sem remover a chave
            break

        ultima_msg, nome_autor, message_original, historico_externo = item

        _avaliar_e_responder_contexto(
            canal_id=canal_id,
            ultima_msg=ultima_msg,
            nome_autor=nome_autor,
            message_original=message_original,
            ignorar_cooldown=True,
            historico_externo=historico_externo,
        )

        time.sleep(_DELAY_ENTRE_RESPOSTAS)
        

def _enfileirar_mencao(canal_id: int, ultima_msg: str, nome_autor: str, message_original, historico_externo: str = ""):
    if canal_id not in _fila_mencoes:
        _fila_mencoes[canal_id] = queue.Queue()

    _fila_mencoes[canal_id].put((ultima_msg, nome_autor, message_original, historico_externo))

    worker_atual = _fila_workers.get(canal_id)
    if worker_atual is None or not worker_atual.is_alive():
        t = threading.Thread(
            target=_worker_fila_mencoes,
            args=(canal_id,),
            daemon=True,
        )
        t.start()
        _fila_workers[canal_id] = t
        print(f"[Discord] Worker de fila iniciado para canal {canal_id}")
        


# ─────────────────────────────────────────────────────────────────
# VOZ NA CALL
# ─────────────────────────────────────────────────────────────────

def _membro_em_call(user_id: int) -> Optional[discord.VoiceChannel]:
    for guild in _client.guilds:
        member = guild.get_member(user_id)
        if member and member.voice and member.voice.channel:
            return member.voice.channel
    return None


async def _entrar_falar_e_sair(canal_voz: discord.VoiceChannel, texto: str) -> None:
    global _voice_client
    import voz as voz_module

    try:
        if _voice_client and _voice_client.is_connected():
            if _voice_client.channel.id != canal_voz.id:
                await _voice_client.move_to(canal_voz)
        else:
            _voice_client = await canal_voz.connect()

        # Espera terminar qualquer áudio anterior
        while _voice_client.is_playing():
            await asyncio.sleep(0.1)

        audio_bytes = voz_module.gerar_audio_bytes(texto)
        if not audio_bytes:
            print("[Discord] gerar_audio_bytes retornou vazio!")
            return

        print(f"[Discord] Tocando áudio na call — {len(audio_bytes)} bytes")

        source = discord.FFmpegPCMAudio(
            io.BytesIO(audio_bytes),
            pipe=True,
            before_options="-f s16le -ar 44100 -ac 1",
            options="-vn"
        )
        _voice_client.play(source)

        while _voice_client.is_playing():
            await asyncio.sleep(0.3)

    except Exception as e:
        print(f"[Discord] Erro ao falar na call: {e}")
    finally:
        if not _emily_em_call_ativa:
            if _voice_client and _voice_client.is_connected():
                await asyncio.sleep(5.0)
                await _voice_client.disconnect()
                _voice_client = None
                print("[Discord] Emily saiu da call após responder.")


def responder_em_call(user_id: int, texto: str) -> bool:
    if not _pronto or not _loop:
        return False
    canal = _membro_em_call(user_id)
    if not canal:
        return False
    print(f"[Discord] Respondendo na call de {canal.name} para o usuário {user_id}")
    asyncio.run_coroutine_threadsafe(
        _entrar_falar_e_sair(canal, texto), _loop
    )
    return True


async def _buscar_historico_canal(canal: discord.TextChannel, limite: int = 100) -> str:
    try:
        mensagens = []
        async for msg in canal.history(limit=limite, oldest_first=False):
            if msg.author == _client.user:
                nome = "Emily"
            else:
                nome = APELIDOS_MEMBROS.get(msg.author.id, msg.author.display_name)
            mensagens.append(f"{nome}: {msg.content}")
        mensagens.reverse()
        return "\n".join(mensagens)
    except Exception as e:
        print(f"[Discord] Erro ao buscar histórico do canal: {e}")
        return ""


# ─────────────────────────────────────────────────────────────────
# STATUS AUTOMÁTICO
# ─────────────────────────────────────────────────────────────────

_STATUS_MAP = {
    "aguardando": {
        "activity": discord.Activity(type=discord.ActivityType.listening, name="o Vitor 👂"),
        "status":   discord.Status.online,
    },
    "ouvindo": {
        "activity": discord.Activity(type=discord.ActivityType.listening, name="o Vitor falar 🎙️"),
        "status":   discord.Status.online,
    },
    "falando": {
        "activity": discord.Activity(type=discord.ActivityType.playing, name="respondendo o Vitor 💬"),
        "status":   discord.Status.online,
    },
    "gravando": {
        "activity": discord.Activity(type=discord.ActivityType.listening, name="gravando 🔴"),
        "status":   discord.Status.do_not_disturb,
    },
    "gerando": {
        "activity": discord.Activity(type=discord.ActivityType.playing, name="gerando imagem 🎨"),
        "status":   discord.Status.idle,
    },
    "ocupada": {
        "activity": discord.Activity(type=discord.ActivityType.playing, name="processando... ⚙️"),
        "status":   discord.Status.do_not_disturb,
    },
}

_JOGOS_CONHECIDOS = [
    "hollow knight", "minecraft", "valorant", "league of legends", "lol",
    "fortnite", "gta", "cs2", "csgo", "counter-strike", "roblox",
    "dark souls", "elden ring", "terraria", "stardew", "among us",
]


async def _atualizar_status_async(estado: str, detalhe: str = "") -> None:
    if not _pronto:
        return

    if detalhe:
        detalhe_lower = detalhe.lower()
        for jogo in _JOGOS_CONHECIDOS:
            if jogo in detalhe_lower:
                nome_jogo = jogo.title()
                await _client.change_presence(
                    activity=discord.Game(name=nome_jogo),
                    status=discord.Status.online
                )
                return

    presenca = _STATUS_MAP.get(estado, _STATUS_MAP["aguardando"])

    try:
        await _client.change_presence(
            activity=presenca["activity"],
            status=presenca["status"]
        )
    except Exception as e:
        print(f"[Discord] Erro ao atualizar status: {e}")


def atualizar_status_discord(estado: str, detalhe: str = "") -> None:
    if not _pronto or not _loop:
        return
    asyncio.run_coroutine_threadsafe(
        _atualizar_status_async(estado, detalhe), _loop
    )


# ─────────────────────────────────────────────────────────────────
# FUNÇÕES PÚBLICAS
# ─────────────────────────────────────────────────────────────────

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


def entrar_em_call(nome_canal: str, nome_servidor: str = "") -> str:
    if not _pronto or not _loop:
        return "O bot do Discord ainda não conectou, Vitor!"

    canal_norm    = nome_canal.lower().strip()
    servidor_norm = nome_servidor.lower().strip()
    canal_encontrado: Optional[discord.VoiceChannel] = None

    for guild in _client.guilds:
        if servidor_norm and servidor_norm not in guild.name.lower():
            continue
        for canal in guild.voice_channels:
            if canal_norm in canal.name.lower() or canal.name.lower() in canal_norm:
                canal_encontrado = canal
                break
        if canal_encontrado:
            break

    if not canal_encontrado:
        disponiveis = [
            f"'{c.name}' ({g.name})"
            for g in _client.guilds
            for c in g.voice_channels
        ]
        sugestao = f" Canais disponíveis: {', '.join(disponiveis[:6])}" if disponiveis else ""
        return f"Não achei o canal '{nome_canal}', Vitor!{sugestao}"

    future = asyncio.run_coroutine_threadsafe(
        _conectar_voz(canal_encontrado.id), _loop
    )
    try:
        sucesso = future.result(timeout=10)
        if sucesso:
            return f"Entrei no '{canal_encontrado.name}' lá no {canal_encontrado.guild.name}!"
        return f"Não consegui entrar no '{canal_encontrado.name}', Vitor."
    except Exception as e:
        return f"Deu erro ao entrar na call: {e}"


def sair_da_call() -> str:
    if not _pronto or not _loop:
        return "Bot não conectado!"
    if not _voice_client or not _voice_client.is_connected():
        return "Não tô em nenhuma call agora, Vitor!"
    desconectar_voz()
    return "Saí da call!"


def listar_calls() -> str:
    if not _pronto:
        return "Bot ainda não conectou, Vitor!"
    if not _client.guilds:
        return "Não tô em nenhum servidor ainda!"

    linhas = []
    for guild in _client.guilds:
        canais = [c.name for c in guild.voice_channels]
        if canais:
            linhas.append(f"• {guild.name}: {', '.join(canais)}")

    return ("Canais de voz disponíveis:\n" + "\n".join(linhas)) if linhas else "Nenhum canal de voz encontrado!"


# ─────────────────────────────────────────────────────────────────
# VOZ — EVENTOS
# ─────────────────────────────────────────────────────────────────

@_client.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    global _emily_em_call_ativa
    usuario_id = _config.get("usuario_id", 0)

    # Comportamento original — segue o Vitor
    if usuario_id and member.id == usuario_id:
        if after.channel is not None:
            print(f"[Discord] Vitor entrou no canal '{after.channel.name}', conectando Emily...")
            await _conectar_voz(after.channel.id)
        elif before.channel is not None and after.channel is None:
            if _voice_client and _voice_client.is_connected():
                await _voice_client.disconnect()
                _emily_em_call_ativa = False
                print("[Discord] Vitor saiu da call, Emily desconectada.")
        return

    # Se alguém saiu do canal onde Emily tá
    if (before.channel is not None
            and _voice_client and _voice_client.is_connected()
            and before.channel.id == _voice_client.channel.id):

        # Conta quantos membros humanos ainda tão no canal
        humanos_restantes = [
            m for m in before.channel.members
            if not m.bot
        ]
        if not humanos_restantes:
            print("[Discord] Canal ficou vazio, Emily saindo...")
            await _voice_client.disconnect()
            _emily_em_call_ativa = False


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


# ─────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────

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