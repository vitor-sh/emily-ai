"""Bot público opcional: texto em canais explicitamente escolhidos, sem tools."""
import asyncio
import threading
import time


def mensagem_permitida(message, canais, usuario):
    return (message.guild is not None and not message.author.bot
            and message.channel.id in canais and usuario is not None
            and usuario in message.mentions and bool(message.content.strip()))


def iniciar(config, responder=None):
    import discord
    if responder is None:
        from llm import chamar_texto
        responder = lambda texto: chamar_texto(texto, system="Você é Emily, uma assistente amigável. Responda em português, de forma breve. Você está conversando por texto no Discord e não executa ações neste canal.", max_tokens=500)
    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    # Menções ao bot incluem conteúdo sem exigir o intent privilegiado.
    client = discord.Client(intents=intents)
    canais = {int(c) for c in config['canais']}
    trava = asyncio.Lock()
    ultimo = {}

    @client.event
    async def on_message(message):
        if not mensagem_permitida(message, canais, client.user):
            return
        agora = time.monotonic()
        if trava.locked() or agora - ultimo.get(message.author.id, 0) < 5:
            return
        # Cache pequeno, sem persistir dados de membros.
        if len(ultimo) > 1000:
            ultimo.clear()
        ultimo[message.author.id] = agora
        async with trava:
            try:
                texto = message.content.replace(f'<@{client.user.id}>', '').replace(f'<@!{client.user.id}>', '').strip()
                if not texto:
                    return
                async with message.channel.typing():
                    resposta = await asyncio.to_thread(responder, texto[:4000])
                if resposta:
                    await message.channel.send(str(resposta)[:1900], allowed_mentions=discord.AllowedMentions.none())
            except Exception:
                print('[Discord público] Não consegui responder. Confira conexão e permissões; credenciais não são exibidas.')

    def executar():
        try:
            client.run(config['token'], log_handler=None)
        except Exception:
            print('[Discord público] Bot indisponível. Confira token e convite ao servidor.')
    threading.Thread(target=executar, daemon=True, name='discord-publico').start()
    return client
