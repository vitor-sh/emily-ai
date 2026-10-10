from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Optional
from discord.ext import voice_recv

import discord
import classificacao_ferramentas as cf

APELIDOS_MEMBROS = {
    731604438212673638: "comedor de Marcio Augusto",
    764277113444368434: "Bisqui",
    1014239583677988964: "Pior jogador de Elden Ring",
    843189524480655380 : "Sempre se acha o protagonista, é ignorante pra krl, completamente irritante, pode xingar com tudo que tem, usa todo seu arsenal de palavrão que eu te ensinei",
}

_CONFIG_PATH = Path(os.getenv("EMILY_ARQUIVO_DISCORD", str(Path.home() / ".emily_discord.json")))

_CONFIG_PADRAO = {
    "token":          "COLE_SEU_TOKEN_AQUI",
    "canal_texto_id": 0,
    "canal_voz_id":   0,
    "prefixo":        "",
    "prefixo_comando": "?",
    "enviar_texto":   True,

    # ── A autonomia dela: iniciativa, moderação, ponte e suporte ──
    #
    # Todos os canais nascem em 0, e 0 significa DESLIGADO. É de propósito: uma
    # Emily que começa comentando sozinha em canal escolhido por chute seria
    # pior que uma calada. O Vitor liga o que quiser preenchendo o id.

    # Onde ela fala por iniciativa própria (sentiu falta de alguém, marcos).
    # Vazio cai pro canal_texto_id.
    "canal_avisos_id": 0,

    # Onde ela recebe quem entra no servidor. Vazio cai pro canal de avisos.
    "canal_boas_vindas_id": 0,

    # Canal de suporte: ali TODA mensagem é atendimento, sem precisar marcar ela.
    "canal_suporte_id": 0,

    # ── Administração do servidor pela Emily ──
    #
    # usuario_id é o ID do Vitor no Discord. Já era lido pelo
    # on_voice_state_update, mas nunca esteve no padrão, então quem criasse a
    # config nova ficava com 0 e a Emily não reconhecia o dono.
    "usuario_id":     0,

    # Cargos que podem mandar a Emily mexer no servidor. Aceita nome ou ID.
    # Ex: ["mod", "staff", 123456789012345678]
    "cargos_admin":   [],

    # Co-admins: IDs de quem é admin de fato junto com o Vitor. Ganham o mesmo
    # poder que ele — sem orçamento de ações, sem justificativa no servidor de
    # Minecraft, podem conceder permissão de poder. Só não pegam as ações
    # irreversíveis do painel (apagar mundo, apagar mods, reinstalar), que
    # continuam do dono.
    #
    # É lista de ID, não de cargo, porque cargo se distribui: qualquer um com
    # "gerenciar cargos" poderia se dar o poder. ID só entra aqui.
    "coadmins_id":    [1002746415216345119],  # Comuna

    # Nomes que só o Vitor pode usar. Quem não for ele e aparecer com um desses
    # é marcado como impostor no contexto do modelo. Isso não muda permissão
    # nenhuma (permissão é por usuario_id), muda o que a Emily acredita.
    "nomes_do_dono":  ["vitor", "hiucksam", "vitorsh"],

    # Quem já é administrador ou gerencia o servidor no Discord conta como
    # autorizado. Ligado por padrão: quem já pode fazer tudo à mão não ganha
    # poder novo pedindo pra Emily.
    "admin_por_permissao_discord": True,

    # Desliga a administração por completo, deixando só a conversa.
    "permitir_admin": True,

    # Mostra no chat o que ela está fazendo enquanto faz: "digitando..." na
    # hora e um painel de passos, em subtexto cinza, que só aparece quando uma
    # ferramenta de verdade roda. Ver progresso_discord.py.
    "mostrar_progresso": True,

    # ── Ouvir e responder na call de voz ──
    #
    # Ligado por padrão, e essa escolha tem contexto: a função é pra call
    # privada com amigos próximos, onde escutar sempre é o comportamento
    # desejado. Num servidor aberto isso seria outra conversa.
    #
    # ouvir_call transcreve tudo que se fala (ver escuta_call.py). É o que
    # permite perguntar depois "o que rolou na call?".
    "ouvir_call": True,

    # responder_call é o passo seguinte: falar quando chamarem o nome dela.
    # Separado de propósito — dá pra deixar ela ouvindo e calada, que é o
    # estado útil quando alguém quer o resumo mas não quer ela participando.
    "responder_call": True,

    # Responder DIRECT (DM): qualquer pessoa que mandar mensagem no direct do
    # bot recebe resposta, como se tivesse marcado ela — com debounce de
    # alguns segundos pra juntar rajadas de mensagens, memória por usuário e
    # só as ferramentas simples. O CONTEÚDO das conversas de direct nunca vai
    # pro terminal, pro histórico ou pra janela de contexto: é privado por
    # construção (ver _dm_receber).
    "responder_dm": True,
}

_SAMPLE_RATE = 22050
_CHANNELS    = 1

def _carregar_config() -> dict:
    if os.getenv("EMILY_PUBLIC_MODE") == "1" and not _CONFIG_PATH.exists():
        return {**_CONFIG_PADRAO, "coadmins_id": [], "nomes_do_dono": [],
                "permitir_admin": False, "ouvir_call": False,
                "responder_call": False, "responder_dm": False}
    if _CONFIG_PATH.exists():
        try:
            salva = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            # Completa as chaves que não existiam quando essa config foi
            # criada. Sem isso, config antiga entra sem as chaves de
            # administração e cada leitura precisaria de um .get com padrão
            # espalhado pelo arquivo.
            faltando = {k: v for k, v in _CONFIG_PADRAO.items() if k not in salva}
            if faltando:
                salva.update(faltando)
                try:
                    _CONFIG_PATH.write_text(
                        json.dumps(salva, ensure_ascii=False, indent=2),
                        encoding="utf-8")
                    print(f"[Discord] Config atualizada com: "
                          f"{', '.join(faltando)}")
                except OSError as e:
                    print(f"[Discord] Não consegui gravar a config nova: {e}")
            return salva
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


# ─────────────────────────────────────────────────────────────────
# JANELA DE CONTEXTO
#
# Aqui vivia o defeito que fazia a Emily confundir quem falou o quê. Três
# problemas somados, todos observados no servidor:
#
# 1. As mensagens DELA não entravam na janela. O on_message retornava logo no
#    começo quando o autor era ela, então o contexto tinha só as falas dos
#    outros, com as respostas dela faltando no meio. Sem as próprias falas ela
#    não consegue saber a quem alguém estava respondendo — medido: alguém
#    mandou "@emily morra", ela respondeu, e no turno seguinte ela achou que o
#    "morra" tinha sido dirigido ao Vitor.
#
# 2. Não havia marcação de reply nem de menção. "morra" e "morra pro Vitor"
#    chegavam iguais ao modelo.
#
# 3. A janela era de 15 mensagens e começava VAZIA a cada boot. Primeira
#    mensagem num canal = zero contexto, e ela respondia no escuro.
#
# O tamanho subiu porque o custo é baixo (é texto de chat, curto) e o benefício
# é direto: conversa de servidor tem várias pessoas falando ao mesmo tempo, e
# 15 linhas somem em segundos numa conversa animada.
# ─────────────────────────────────────────────────────────────────

_JANELA_CONTEXTO = int(os.getenv("EMILY_JANELA_DISCORD", "40"))

# Abaixo disso a janela é considerada "fria" e vale buscar o histórico real do
# canal no Discord antes de responder.
_MIN_CONTEXTO_FRIO = 8

_COOLDOWN_CONTEXTO      = 30
_historico_janela:       dict = {}
_ultimo_contexto_canal:  dict = {}

# Canais cujo histórico já foi puxado nesta sessão.
_contexto_preenchido: set = set()


# ─────────────────────────────────────────────────────────────────
# IDENTIDADE: O DONO É UM ID, NUNCA UM NOME
#
# Falha real observada no servidor: um membro trocou o apelido pra "Vitor" e a
# Emily passou a tratar ele como o dono nos julgamentos.
#
# O importante de entender é ONDE estava o furo. O portão de permissão sempre
# foi por ID (nivel_do_membro compara membro.id com usuario_id), então ninguém
# ganhou permissão de dono. O que vazou foi o NOME dentro do prompt: o juiz de
# justificativa recebia "QUEM PEDIU: Vitor" e concluiu o resto sozinho, e o
# system prompt dizia "quem está pedindo é Vitor, que tem cargo autorizado".
# Ou seja, o modelo foi convencido por um nome que ele não tinha como conferir.
#
# A correção tem duas metades, e as duas são necessárias:
#   1. Aqui: nome de quem NÃO é o dono nunca chega ao prompt parecendo o dono.
#   2. No modelo.py: o prompt diz que identidade vem de ID, e o juiz sabe por
#      construção que quem chega até ele não é o dono.
# ─────────────────────────────────────────────────────────────────

def _nomes_protegidos() -> set:
    """Nomes que só o dono pode usar sem ser marcado como impostor."""
    import modelo as modelo_module
    nomes = {"vitor"}
    for extra in (_config.get("nomes_do_dono") or []):
        n = modelo_module._normalizar_texto(str(extra))
        if n:
            nomes.add(n)
    return nomes


def _e_impostor_do_dono(autor) -> bool:
    """Alguém que não é o dono se apresentando com o nome dele."""
    dono_id = int(_config.get("usuario_id", 0) or 0)
    autor_id = getattr(autor, "id", 0)
    if not dono_id or autor_id == dono_id:
        return False
    if _client.user is not None and autor_id == _client.user.id:
        return False

    import modelo as modelo_module
    protegidos = _nomes_protegidos()
    for bruto in (getattr(autor, "display_name", ""), getattr(autor, "name", "")):
        alvo = modelo_module._normalizar_texto(str(bruto or ""))
        if not alvo:
            continue
        for nome in protegidos:
            if nome and (nome == alvo or nome in alvo.split() or nome in alvo):
                return True
    return False


def _nome_de(autor) -> str:
    """
    Nome que vai pro prompt. Apelido fixo por ID ganha do apelido do Discord.

    Impostor recebe uma etiqueta em vez de ter o nome escondido: assim a Emily
    não só deixa de acreditar, como consegue chamar a pessoa na cara dura, que
    é o que ela faria de qualquer forma.
    """
    if _client.user is not None and getattr(autor, "id", None) == _client.user.id:
        return "Emily"

    impostor = _e_impostor_do_dono(autor)

    try:
        import perfil_discord
        conhecido = perfil_discord.nome_de(autor.id)
        if conhecido and not impostor and perfil_discord._normalizar(conhecido) not in _nomes_protegidos():
            return conhecido
    except Exception:
        pass

    fixo = APELIDOS_MEMBROS.get(getattr(autor, "id", 0))
    if fixo and not impostor:
        return fixo

    nome = (getattr(autor, "display_name", None)
            or getattr(autor, "name", None) or "alguém")

    if impostor:
        return (f"{nome} (SE PASSANDO PELO VITOR — não é ele, "
                f"id {getattr(autor, 'id', 0)})")
    return nome


def _ids_por_apelido(apelido: str) -> set[int]:
    """Todos os IDs com nick EXATO; o chamador decide se há ambiguidade."""
    import perfil_discord
    chave = perfil_discord._normalizar(apelido)
    if not chave:
        return set()
    candidatos = {}
    for guild in _client.guilds:
        for membro in guild.members:
            if not getattr(membro, "bot", False):
                candidatos[membro.id] = membro
    if _voice_client and _voice_client.is_connected():
        for membro in _voice_client.channel.members:
            if not getattr(membro, "bot", False):
                candidatos[membro.id] = membro
    iguais = {uid for uid, membro in candidatos.items()
              if chave in {perfil_discord._normalizar(getattr(membro, "name", "")),
                           perfil_discord._normalizar(getattr(membro, "display_name", ""))}}
    return iguais


def _e_reply_na_emily(message) -> bool:
    """A mensagem é um reply direto numa fala dela?"""
    try:
        ref = getattr(message, "reference", None)
        if ref is None or ref.resolved is None:
            return False
        if not isinstance(ref.resolved, discord.Message):
            return False
        return ref.resolved.author == _client.user
    except Exception:
        return False


def _alvo_do_reply(message) -> str:
    """Nome de quem a mensagem está respondendo, se for um reply."""
    try:
        ref = getattr(message, "reference", None)
        if ref is None:
            return ""
        alvo = getattr(ref, "resolved", None)
        if alvo is None or not isinstance(alvo, discord.Message):
            return ""
        return _nome_de(alvo.author)
    except Exception:
        return ""


def _registrar_na_janela(canal_id: int, *, nome: str, texto: str,
                         message=None, user_id: int = 0, imagens=None,
                         eh_emily: bool = False, respondendo_a: str = "",
                         mencionou_emily: bool = False) -> None:
    if canal_id not in _historico_janela:
        _historico_janela[canal_id] = []
    _historico_janela[canal_id].append({
        "nome":            nome,
        "texto":           texto,
        "message":         message,
        "user_id":         user_id,
        "imagens":         imagens or [],
        "eh_emily":        eh_emily,
        "respondendo_a":   respondendo_a,
        "mencionou_emily": mencionou_emily,
    })
    if len(_historico_janela[canal_id]) > _JANELA_CONTEXTO:
        _historico_janela[canal_id].pop(0)


class ErroJournalStub(Exception):
    pass


def _memoria_dono(eh_dono: bool, user_id: int) -> str:
    """Namespace de memória unificada para quem está falando agora."""
    if eh_dono:
        try:
            import memoria_unificada
            return memoria_unificada.dono_id()
        except Exception:  # noqa: BLE001
            return "vitor"
    return f"discord:{int(user_id)}"


def _formatar_janela(canal_id: int, excluir_ultima: bool = False) -> str:

    """
    Transcreve a janela num formato em que dá pra saber quem falou com quem.

    O rótulo "Emily (você)" e as marcas de reply e menção são o que permite ao
    modelo distinguir "morra" dito a ela de "morra" dito a outra pessoa. Antes
    era só "Nome: texto", e essa informação simplesmente não existia.
    """
    janela = _historico_janela.get(canal_id, [])
    if excluir_ultima:
        janela = janela[:-1]
    if not janela:
        return ""

    linhas = []
    for item in janela:
        marcas = []
        alvo = item.get("respondendo_a")
        if alvo:
            marcas.append(f"respondendo a {alvo}")
        if item.get("mencionou_emily") and not item.get("eh_emily"):
            marcas.append("falou direto com você")
        rotulo = "Emily (você)" if item.get("eh_emily") else item.get("nome", "alguém")
        sufixo = f" [{', '.join(marcas)}]" if marcas else ""
        linhas.append(f"{rotulo}{sufixo}: {item.get('texto', '')}")
    return "\n".join(linhas)


async def _garantir_contexto(canal) -> None:
    """
    Preenche a janela com o histórico real do canal, uma vez por canal.

    Existe porque a janela nasce vazia a cada boot da Emily: sem isso, a
    primeira mensagem de um canal era respondida sem contexto nenhum, e é
    justamente aí que ela mais se perde.
    """
    if canal.id in _contexto_preenchido:
        return
    _contexto_preenchido.add(canal.id)

    if len(_historico_janela.get(canal.id, [])) >= _MIN_CONTEXTO_FRIO:
        return

    try:
        recentes = [m async for m in canal.history(limit=_JANELA_CONTEXTO)]
    except Exception as e:
        print(f"[Discord] Não consegui puxar o histórico de #{canal.name}: {e}")
        return

    recentes.reverse()
    ja_vistas = {
        getattr(i.get("message"), "id", None)
        for i in _historico_janela.get(canal.id, [])
    }
    anteriores = _historico_janela.pop(canal.id, [])

    for msg in recentes:
        if msg.id in ja_vistas:
            continue
        conteudo = (msg.content or "").strip()
        if not conteudo:
            continue
        _registrar_na_janela(
            canal.id,
            nome=_nome_de(msg.author),
            texto=conteudo,
            message=msg,
            user_id=msg.author.id,
            eh_emily=(_client.user is not None and msg.author.id == _client.user.id),
            respondendo_a=_alvo_do_reply(msg),
            mencionou_emily=bool(_client.user in msg.mentions),
        )

    for item in anteriores:
        _historico_janela.setdefault(canal.id, []).append(item)
    if len(_historico_janela.get(canal.id, [])) > _JANELA_CONTEXTO:
        _historico_janela[canal.id] = \
            _historico_janela[canal.id][-_JANELA_CONTEXTO:]

    print(f"[Discord] Contexto de #{canal.name} preenchido com "
          f"{len(_historico_janela.get(canal.id, []))} mensagens do histórico")

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

    import discord_monitor
    ativo = discord_monitor.aplicar()
    print(f"[Discord] Escuta de texto {'ativada' if ativo else 'desativada'} ({'Oracle' if os.getenv('EMILY_RUNTIME_CLOUD') == '1' else 'PC'})")

    await _client.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening,
            name="hackeando o governo russo.."
        ),
        status=discord.Status.online
    )

    _ligar_autonomia()
    if os.getenv("EMILY_RUNTIME_CLOUD") == "1":
        from cloud_runtime_server import retomar_call
        await retomar_call()


def _ligar_autonomia() -> None:
    """
    Sobe o relógio, a iniciativa e a ponte com o jogo.

    Aqui e não no import do módulo: tudo isso precisa do bot conectado pra
    conseguir falar, e o on_ready é o primeiro instante em que isso é verdade.
    Ligar antes faria as primeiras tarefas dispararem no vazio.

    Cada peça sobe protegida individualmente. Se a ponte com o Minecraft falhar,
    os lembretes continuam funcionando — o oposto (um try só, englobando tudo)
    faria uma falha boba derrubar a autonomia inteira em silêncio.
    """
    try:
        import agenda
        agenda.ligar()
    except Exception as e:
        print(f"[Discord] relógio não subiu: {type(e).__name__}: {e}")

    for modulo in ("vida_discord",):
        try:
            __import__(modulo).ligar()
        except Exception as e:
            print(f"[Discord] {modulo} não subiu: {type(e).__name__}: {e}")

    try:
        import suporte
        if suporte.ATIVO and not suporte.tem_regras():
            print("[Discord] AVISO: as regras do servidor não estão escritas. "
                  "Peça pra Emily criar o arquivo de regras, ou crie "
                  "regras_servidor.md na mão — sem elas o suporte responde no "
                  "escuro sobre o que é permitido.")
    except Exception:
        pass


@_client.event
async def on_member_join(member: discord.Member):
    """Alguém entrou. A recepção é dela, não um template."""
    try:
        import vida_discord
        threading.Thread(target=vida_discord.entrou, args=(member,),
                         daemon=True).start()
    except Exception as e:
        print(f"[Discord] boas-vindas falharam: {type(e).__name__}: {e}")


@_client.event
async def on_member_remove(member: discord.Member):
    """Alguém saiu. Ela só comenta se conhecia a pessoa."""
    try:
        import vida_discord
        threading.Thread(target=vida_discord.saiu, args=(member,),
                         daemon=True).start()
    except Exception as e:
        print(f"[Discord] despedida falhou: {type(e).__name__}: {e}")


@_client.event
async def on_message(message: discord.Message):
    texto = message.content.strip()
    canal = message.channel

    # ─── AS FALAS DELA TAMBÉM ENTRAM NO CONTEXTO ───
    #
    # Antes essa checagem era só `return`, e era o maior furo de contexto do
    # bot: a Emily nunca via as próprias respostas. Numa conversa de servidor
    # isso é fatal, porque sem a fala dela no meio não há como saber a quem
    # cada pessoa estava respondendo.
    if message.author == _client.user:
        if texto:
            _registrar_na_janela(
                canal.id, nome="Emily", texto=texto, message=message,
                user_id=message.author.id, eh_emily=True,
                respondendo_a=_alvo_do_reply(message),
            )
        return

    # ─── DIRECT (DM): conversa privada 1:1 ───
    #
    # Vem ANTES de qualquer fluxo do servidor de propósito: o direct é um
    # canal com regras próprias (privacidade absoluta, debounce de rajada,
    # ferramentas simples) e NENHUMA mensagem daqui pode vazar pra janela de
    # contexto do servidor, pra moderação, pro perfil público — lugar
    # nenhum que o Vitor possa ler depois. Nem o terminal recebe o conteúdo:
    # só quem escreveu e quantas mensagens há na leva.
    if message.guild is None:
        _dm_receber(message)
        return

    if not _escuta_discord_ativa.is_set():
        return

    # A escolha de PC pode mudar entre dois ciclos de sincronização. Confere
    # o gateway antes de responder para evitar duas Emilys no mesmo canal.
    import discord_monitor
    if not await asyncio.to_thread(discord_monitor.pode_responder):
        return

    if not _callback_texto:
        return

    prefixo_comando = _config.get("prefixo_comando", "?")

    if not texto:
        return

    # ─── CONFIRMAÇÃO DE AÇÃO DESTRUTIVA ───
    #
    # Vem antes de tudo de propósito. Se a Emily perguntou "é pra apagar
    # mesmo?", o "sim" que chega em seguida é resposta àquilo, não mensagem
    # nova pra ela comentar. Sem essa checagem aqui, o "sim" cairia na
    # participação espontânea e a ação nunca aconteceria.
    if _tratar_resposta_de_confirmacao(message, texto):
        return

    # ─── CONTEXTO FRIO: BUSCA O HISTÓRICO REAL DO CANAL ───
    #
    # Roda antes de registrar a mensagem atual, e só uma vez por canal por
    # sessão. É o que evita responder no escuro logo depois de ligar a Emily.
    await _garantir_contexto(canal)

    # ─── ACUMULA JANELA DE CONTEXTO ───
    #
    # Passa por _nome_de e não pelo display_name cru: é o único ponto por onde
    # o nome entra no contexto, na sessão do painel e no juiz, então é aqui que
    # a etiqueta de impostor precisa ser aplicada.
    nome_exibido = _nome_de(message.author)

    # Extrai imagens se tiver — await direto pois já estamos numa coroutine
    imagens_b64 = []
    if message.attachments:
        imagens_b64 = await _extrair_imagens_mensagem(message)

    falou_com_emily = bool(_client.user in message.mentions) or _e_reply_na_emily(message)

    _registrar_na_janela(
        canal.id,
        nome=nome_exibido,
        texto=texto,
        message=message,
        user_id=message.author.id,
        imagens=imagens_b64,
        respondendo_a=_alvo_do_reply(message),
        mencionou_emily=bool(_client.user in message.mentions),
    )

    # ─── PERFIL DO SERVIDOR ───
    #
    # Custo zero por mensagem: só incrementa contadores em memória, sem LLM e
    # sem I/O (o disco é tocado a cada 25 observações). É daqui que sai tanto o
    # "quem é quem" quanto o jeito de escrever do servidor.
    try:
        import perfil_discord
        perfil_discord.observar(
            message.author.id, message.author.display_name, texto,
            falou_com_emily=falou_com_emily,
            eh_bot=bool(getattr(message.author, "bot", False)),
        )
        if message.author.id == int(_config.get("usuario_id", 0) or 0):
            perfil_discord.aprender_associacao_explicitada(texto)
            perfil_discord.aprender_fato_explicitado_pelo_dono(texto)
        elif perfil_discord.deve_extrair(message.author.id):
            # Aprende mesmo se Emily não responder; nunca inclui conversa de
            # outras pessoas nem mensagens privadas de outra DM no caderno.
            perfil_discord.extrair_em_segundo_plano(
                message.author.id, nome_exibido, texto)
    except Exception as e:
        print(f"[Discord] Perfil não pôde observar a mensagem: {e}")

    # ─── MODERAÇÃO ───
    #
    # Em thread, e ANTES de qualquer ramificação de resposta: ela precisa olhar
    # TODA mensagem, inclusive as que não são pra ela. A camada barata recusa
    # quase tudo sem custo, e a análise nunca atrasa a resposta porque não está
    # no caminho dela.
    try:
        import moderacao
        if moderacao.ATIVO:
            threading.Thread(
                target=moderacao.analisar,
                args=(message, nome_exibido, imagens_b64),
                daemon=True).start()
    except Exception as e:
        print(f"[Discord] moderação não rodou: {type(e).__name__}: {e}")

    # ─── CANAL DE SUPORTE ───
    #
    # Ali toda mensagem é atendimento, sem precisar marcar ela — é o que "canal de
    # suporte" quer dizer. Retorna em seguida: o atendimento JÁ é a resposta, e
    # deixar seguir pro fluxo normal faria ela responder duas vezes, uma como
    # atendente e outra como ela mesma.
    try:
        import suporte
        if suporte.ATIVO and suporte.eh_canal_de_suporte(canal.id):
            threading.Thread(
                target=suporte.atender,
                args=(message, nome_exibido, _formatar_janela(canal.id)),
                daemon=True).start()
            return
    except Exception as e:
        print(f"[Discord] suporte não atendeu: {type(e).__name__}: {e}")

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
    reply_na_emily = _e_reply_na_emily(message)

    if bot_mencionado or reply_na_emily:
        texto_limpo = texto.replace(f"<@{_client.user.id}>", "").strip()
        if not texto_limpo:
            texto_limpo = texto

        historico_fmt = _formatar_janela(canal.id)

        print(f"[Discord] Emily mencionada por {message.author.display_name}: '{texto_limpo[:60]}'")
        _enfileirar_mencao(canal.id, texto_limpo, nome_exibido, message, historico_fmt)
        return

    # ─── PEDIDO DE ADMINISTRAÇÃO SEM MENÇÃO ───
    #
    # Pra quem tem acesso de admin, a mensagem não precisa mais vir marcada:
    # pedido de administração detectado entra na MESMA fila das menções e roda
    # com ferramenta na mesa. Era aqui que ela "prometia" ação sem poder cumprir
    # — o caminho de conversa não tem ferramenta nenhuma, e o texto de "tô
    # criando!" saía vazio. Ver _deve_rotear_admin_sem_mencao.
    try:
        if _deve_rotear_admin_sem_mencao(texto, message):
            print(f"[Discord] Pedido de admin sem menção de {nome_exibido}: "
                  f"'{texto[:60]}'")
            _enfileirar_mencao(canal.id, texto, nome_exibido, message,
                               _formatar_janela(canal.id))
            return
    except Exception as e:
        print(f"[Discord] roteamento de admin sem menção falhou: "
              f"{type(e).__name__}: {e}")

    # ─── ALGUÉM ENCRENCADO FORA DO CANAL DE SUPORTE ───
    #
    # Vem antes da participação espontânea de propósito. Quem escreveu "nao
    # consigo entrar" precisa de ajuda, não de comentário — e as duas coisas
    # respondendo à mesma mensagem seria ela falando duas vezes.
    try:
        import suporte
        if suporte.talvez_oferecer_ajuda(message, nome_exibido):
            return
    except Exception as e:
        print(f"[Discord] oferta de ajuda falhou: {type(e).__name__}: {e}")

    # ─── PARTICIPAÇÃO ESPONTÂNEA ───
    if len(texto) < 2:
        return

    print(f"[Discord] Mensagem de {nome_exibido} no #{canal.name}: '{texto[:60]}'")
    threading.Thread(
        target=_avaliar_e_responder_contexto,
        args=(canal.id, texto, nome_exibido, message, False, ""),
        daemon=True,
    ).start()
    
# ─────────────────────────────────────────────────────────────────
# ADMINISTRAÇÃO DO SERVIDOR
#
# A Emily conversa desde sempre; isso aqui é o que a deixa MEXER no servidor
# a pedido de quem tem permissão. Fica neste arquivo porque só aqui existe o
# objeto Member de verdade — e nível de acesso não pode sair de nada que o
# modelo tenha lido.
# ─────────────────────────────────────────────────────────────────

def _responder_no_canal(message: discord.Message, texto: str,
                        quebrar: bool = True) -> None:
    """Responde no chat a partir de uma thread, quebrando como pessoa digitando."""
    import modelo as modelo_module
    texto = modelo_module.remover_tags_fish(texto)
    if not texto or not texto.strip() or not _loop:
        return

    partes = (modelo_module.quebrar_resposta_discord(texto)
              if quebrar else [texto[:2000]])

    async def _enviar():
        try:
            await message.reply(partes[0])
            for parte in partes[1:]:
                await asyncio.sleep(2.0)
                await message.channel.send(parte)
        except Exception as e:
            print(f"[Discord] Erro ao responder: {e}")

    asyncio.run_coroutine_threadsafe(_enviar(), _loop)


def _tratar_resposta_de_confirmacao(message: discord.Message, texto: str) -> bool:
    """
    True se essa mensagem foi resposta a uma confirmação pendente.

    Devolve False quando não dá pra saber se é sim ou não: aí a mensagem segue
    o fluxo normal e a pendência continua esperando. Errar pra "não entendi" é
    barato; errar pra "entendi que sim" apaga canal de verdade.
    """
    import discord_admin

    if message.guild is None:
        return False

    pendente = discord_admin.tem_confirmacao_pendente(
        message.channel.id, message.author.id)
    if not pendente:
        return False

    decisao = discord_admin.ler_confirmacao(texto)
    if decisao is None:
        print(f"[Discord] '{texto[:40]}' não é sim nem não; pendência mantida.")
        return False

    threading.Thread(
        target=_resolver_confirmacao,
        args=(message, decisao, pendente),
        daemon=True,
    ).start()
    return True


def _resolver_confirmacao(message: discord.Message, confirmou: bool,
                          descricao: str) -> None:
    import discord_admin
    import modelo as modelo_module

    canal_id = message.channel.id
    autor_id = message.author.id
    nome = APELIDOS_MEMBROS.get(autor_id, message.author.display_name)

    if not confirmou:
        discord_admin.cancelar_pendente(canal_id, autor_id)
        print(f"[Discord] {nome} cancelou: {descricao}")
        frase = modelo_module.falar_discord(
            f"{nome} pediu pra você {descricao}, você perguntou se era pra "
            f"fazer mesmo e ele desistiu. Reaja a ele ter desistido.",
            ("belezaa, deixei quieto entao", "ok, nao fiz nada",
             "ata, cancelado entao", "blz, nem toquei"),
        )
        _responder_no_canal(message, frase, quebrar=False)
        return

    print(f"[Discord] {nome} confirmou: {descricao}")
    descricao_real, relatorio = discord_admin.executar_pendente(canal_id, autor_id)
    if descricao_real is None:
        frase = modelo_module.falar_discord(
            "Alguém confirmou uma ação mas ela já tinha expirado ou sumido. "
            "Avise que não tem mais nada pendente e é pra pedir de novo.",
            ("acho que expirou, pede de novo ai",
             "nao tenho mais nada pendente aqui, manda de novo"),
        )
        _responder_no_canal(message, frase, quebrar=False)
        return

    frase = modelo_module.falar_discord(
        f"{nome} confirmou e você acabou de {descricao_real}. "
        f"Resultado técnico, só pra você saber o que aconteceu (não repita "
        f"isso literalmente): {relatorio[:600]}. "
        f"Comente que fez, do seu jeito, curto.",
        ("pronto, feito", "ta feito", "fiz, ta ai", "pronto, apagado"),
    )
    _responder_no_canal(message, frase, quebrar=False)


def _nivel_de_acesso(message: discord.Message) -> str:
    import discord_admin
    return discord_admin.nivel_do_membro(message.author, _config)


# ─────────────────────────────────────────────────────────────────
# CALL x CHAT
#
# Quando a Emily está numa call, a resposta padrão dela sai por voz. Isso é o
# certo pra conversa e é ERRADO pra duas coisas: comando de administração (o
# resultado é lista de canal e nome de cargo, que ninguém quer ouvir falado) e
# pedido explícito de resposta escrita.
# ─────────────────────────────────────────────────────────────────

# Frases inequívocas de "sai da call". Nenhuma delas colide com verbo de
# moderação, então podem casar em qualquer posição da mensagem.
_FRASES_SAIR_DA_CALL = (
    "sai da call", "sai call", "sai do canal", "sai da voz", "sai dai",
    "tchau call", "deixa a call", "deixa a chamada", "pode sair da call",
    "sai da chamada", "se desconecta", "desconecta da call",
    "desconecta da voz", "pode se desconectar",
)

# "desconecta" solto é ambíguo: pode ser "sai da call" ou "desconecta o alemão".
# Sem trava, "desconecta o alemao da call" fazia a EMILY sair — o verbo casava
# por substring e a ramificação de saída respondia antes de qualquer outra coisa.
#
# A trava é a ausência de COMPLEMENTO: se depois de tirar o verbo, os
# enfeites e o nome dela não sobra palavra nenhuma, o pedido é sobre ela.
# Contar palavras não serve — medido, "desconecta o alemao" tem três palavras e
# passava como pedido de saída.
_ENFEITES = {
    "emily", "emy", "em", "ai", "ae", "entao", "ent", "então",
    "por", "favor", "pf", "pfv", "plis", "please", "pls", "plz",
    "vai", "logo", "agora", "ja", "ja", "pode", "podes", "da", "de", "do",
    "la", "dai", "call", "voz", "canal", "chamada", "obg", "vlw", "e",
    "o", "a", "os", "as", "se", "te", "me",
}


def _pedido_para_sair_da_call(texto: str, message: discord.Message) -> bool:
    import modelo as modelo_module

    t = modelo_module._normalizar_texto(texto or "")
    if not t:
        return False

    # Se a mensagem aponta pra outra pessoa, não é pedido pra ela sair.
    outros_mencionados = [
        m for m in getattr(message, "mentions", []) if m.id != _client.user.id
    ]
    if outros_mencionados:
        return False

    if any(frase in t for frase in _FRASES_SAIR_DA_CALL):
        return True

    palavras = t.split()
    if any(p in ("desconecta", "desconectar", "desconecte") for p in palavras):
        sobrou = [
            p for p in palavras
            if p not in _ENFEITES
            and p not in ("desconecta", "desconectar", "desconecte")
        ]
        # Sobrou complemento (nome de alguém) => é pedido de desconectar OUTRO.
        return not sobrou
    return False


# Pedido explícito de resposta escrita, mesmo estando ela na call.
_FRASES_RESPONDER_NO_CHAT = (
    "no chat", "pelo chat", "aqui no chat", "por escrito", "escrito",
    "por texto", "em texto", "no texto",
    "manda no chat", "manda aqui", "escreve ai", "escreve aqui", "escreva",
    "responde aqui", "responde no chat", "responda no chat", "digita",
    "digite", "manda escrito", "fala aqui no chat", "poe no chat",
    "cola no chat", "manda por mensagem", "me manda mensagem",
)


def _pediu_resposta_no_chat(texto: str) -> bool:
    import modelo as modelo_module
    t = modelo_module._normalizar_texto(texto or "")
    return bool(t) and any(frase in t for frase in _FRASES_RESPONDER_NO_CHAT)


def _deve_rotear_admin_sem_mencao(texto: str, message: discord.Message) -> bool:
    """
    Mensagem SEM menção vale o caminho com ferramenta?

    Antes, só menção ou reply abriam o laço de administração. Um "cria um canal
    tal" solto no chat caía na participação espontânea — que não tem ferramenta
    nenhuma — e ela RESPONDIA como se fosse fazer, porque o modelo do caminho de
    conversa não sabe que promessa ali não tem como ser cumprida. Era mentira
    por arquitetura, não por escolha dela.

    Agora quem tem acesso de administração (dono, coadmin ou cargo autorizado)
    não precisa marcar: a frase que parece pedido de administração entra na
    MESMA fila das menções e roda com ferramenta na mesa. Se na verdade era só
    conversa ou pergunta de capacidade, o laço responde conversando — lá ela
    sabe o que pode fazer, então a resposta sai honesta.

    Quem NÃO tem acesso segue no fluxo de sempre: recusar permissão pra quem
    nem falou com ela seria só barulho (e "o server tá on?" de visitante não
    pode virar aviso de permissão).

    Detector local, sem rede e sem LLM; falso positivo é barato porque o laço
    decide sozinho se executa ou só conversa.
    """
    import discord_admin

    if not texto or message.guild is None:
        return False
    if not _config.get("permitir_admin", True):
        return False
    if not discord_admin.parece_pedido_de_admin(texto):
        return False
    return _nivel_de_acesso(message) != discord_admin.NIVEL_NENHUM


def _tentar_pedido_de_admin(
    canal_id: int,
    texto: str,
    nome_autor: str,
    message: discord.Message,
    historico_externo: str = "",
    autor_na_call: bool = False,
) -> bool:
    """
    Se a mensagem é pedido de administração, resolve aqui e devolve True.

    False significa "não era pedido de admin" — a mensagem segue pelo caminho
    de conversa normal, que continua intocado. Essa separação é o que permite
    adicionar a capacidade nova sem mexer no comportamento que já funcionava.
    """
    import discord_admin
    import modelo as modelo_module

    if message.guild is None:
        return False
    if not _config.get("permitir_admin", True):
        return False

    # Cobrança de promessa tem prioridade sobre a heurística.
    #
    # Isso existe por um caso real: a Emily prometeu criar cargos e não criou; a
    # cobrança foi "perfeito kkkkkkk, vai lá ent", que não tem verbo nem
    # substantivo de servidor e portanto NÃO é reconhecida como pedido de
    # administração. Sem esta checagem, a cobrança caía na conversa comum, que
    # não tem ferramenta na mesa, e ela prometia de novo.
    # Chegar nesta função significa que a pessoa falou DIRETO com ela, mas não
    # que pediu administração. A pendência tem prioridade; sem pendência, o
    # detector amplo abaixo separa assunto administrativo de conversa antes de
    # enviar o catálogo. A cobrança continua usando o critério estrito.
    pendencia = discord_admin.consumir_promessa(canal_id, message.author.id)

    pendente = pendencia["pedido"] if pendencia else ""
    tipo_pendencia = pendencia["tipo"] if pendencia else discord_admin.TIPO_PROMESSA

    # Ordem de verdade (critério estrito), separada de "vale rotear pra cá".
    # Usada abaixo pra decidir se este caminho REALMENTE assume a mensagem ou
    # devolve ela pro fluxo normal.
    era_ordem = discord_admin.parece_ordem_de_admin(texto, dirigido_a_ela=True)
    era_pedido_admin = discord_admin.parece_pedido_de_admin(
        texto, dirigido_a_ela=True)

    # Menção direta não transforma conversa em administração. Antes toda fala
    # dirigida pagava o catálogo e podia cair na cobrança obrigatória; agora só
    # assunto do domínio ou pendência real entra no laço pesado.
    if not pendencia and not era_pedido_admin:
        print(f"[CLASSIFICACAO-FERRAMENTA] canal=discord "
              f"politica={cf.SEM_FERRAMENTA} motivo=mencao_conversacional "
              f"texto={texto[:80]!r}")
        return False

    if bool(pendente) or era_ordem:
        classificacao_admin = cf.ClassificacaoFerramenta(
            cf.FERRAMENTA_OBRIGATORIA,
            "continuacao_pendente" if pendente else "ordem_administrativa_explicita",
        )
    elif discord_admin.parece_pergunta_de_capacidade(texto):
        classificacao_admin = cf.ClassificacaoFerramenta(
            cf.FERRAMENTA_OPCIONAL, "pergunta_de_capacidade_administrativa")
    else:
        # Estado do Minecraft/servidor e outras consultas factuais do domínio
        # precisam ser verificadas, não respondidas de cabeça.
        classificacao_admin = cf.ClassificacaoFerramenta(
            cf.FERRAMENTA_OBRIGATORIA, "consulta_factual_administrativa")

    nivel = _nivel_de_acesso(message)
    if pendencia:
        print(f"[Discord] Pendência de {nome_autor} ({tipo_pendencia}): "
              f"'{pendente[:60]}' — voltando pro caminho com ferramenta.")
    print(f"[Discord] Pedido de admin de {nome_autor} (nível {nivel}): "
          f"'{texto[:70]}'")

    # Membro sem permissão só é barrado quando de fato MANDOU algo. Pergunta
    # solta ("vc consegue banir?") volta pro fluxo normal, que já sabe explicar
    # as capacidades dela e responde por voz se for o caso.
    if nivel == discord_admin.NIVEL_NENHUM and not era_ordem:
        return False

    _ultimo_contexto_canal[canal_id] = time.time()

    # Sem permissão não gasta o laço de ferramentas: uma frase na voz dela
    # explicando que não rola resolve, e sai bem mais barato.
    if nivel == discord_admin.NIVEL_NENHUM:
        frase = modelo_module.falar_discord(
            f"{nome_autor} pediu pra você mexer no servidor "
            f"('{texto[:120]}'), mas ele não tem permissão pra isso — só o "
            f"Vitor e quem tem cargo autorizado podem. Recuse do seu jeito, "
            f"sem ser educada demais.",
            ("nao, tu nao tem permissao pra isso",
             "so o vitor manda em mim nisso ai",
             "nem vem, tu nao pode pedir isso"),
        )
        _responder_no_canal(message, frase, quebrar=False)
        return True

    janela = _historico_janela.get(canal_id, [])
    imagens = janela[-1].get("imagens", []) if janela else []
    historico_fmt = historico_externo or ("\n".join(
        f"{item['nome']}: {item['texto']}" for item in janela[:-1]
    ) if len(janela) > 1 else "")

    discord_admin.definir_sessao(
        nivel=nivel,
        autor_id=message.author.id,
        autor_nome=nome_autor,
        guild_id=message.guild.id,
        canal_id=canal_id,
        origem="discord",
        autonomia_direta=bool(
            nivel == discord_admin.NIVEL_DONO
            and era_ordem
            and modelo_module.autonomia_experimental_ativa()
        ),
    )

    # Namespace de memória unificada: o dono lê/escreve a memória dele; terceiros
    # têm a ficha própria isolada por ID (nunca a memória do Vitor).
    dono_memoria = _memoria_dono(eh_dono, message.author.id)

    # Sessão do painel de Minecraft. Note que o critério de dono aqui é OUTRO:
    # no Discord, cargo autorizado dá nível total; no servidor de Minecraft só o
    # Vitor é dono, porque as travas irreversíveis são dele. Cargo de Discord
    # não vira poder de apagar mundo.
    #
    # Co-admin vai num campo separado, e não como eh_dono, porque os dois
    # significam coisas diferentes lá: eh_dono libera até o irreversível,
    # coadmin só dispensa a justificativa.
    painel = None
    if _config.get("mostrar_progresso", True):
        try:
            import progresso_discord
            painel = progresso_discord.criar(message, _loop)
        except Exception as e:
            print(f"[Discord] painel de progresso indisponível: {e}")

    try:
        resultado = modelo_module.responder_discord_com_ferramentas(
            mensagem=texto,
            nome_autor=nome_autor,
            dono_user_id=dono_memoria,
            historico_canal=historico_fmt,
            nome_servidor=message.guild.name,
            nome_canal=getattr(message.channel, "name", ""),
            nivel=nivel,
            eh_dono=(nivel == discord_admin.NIVEL_DONO),
            imagens=imagens,
            pedido_pendente=pendente,
            tipo_pendencia=tipo_pendencia,
            # Estrito, não amplo: o roteamento até aqui é permissivo de
            # propósito (pra ela saber o que pode fazer), mas COBRAR ferramenta
            # de uma pergunta como "você consegue banir?" faria ela banir
            # alguém em vez de responder.
            parece_acao=bool(pendente) or era_ordem,
            politica_ferramenta=classificacao_admin.politica,
            motivo_classificacao=classificacao_admin.motivo,
            em_call=bool(_emily_em_call_ativa and _voice_client
                         and _voice_client.is_connected()),
            contexto_membros=_contexto_de_quem_esta_falando(canal_id),
            on_progresso=(painel.evento if painel else None),
        )
    finally:
        discord_admin.limpar_sessao()
        if painel is not None:
            # No finally junto com as sessões: se o laço estourar exceção, o
            # painel não pode ficar com um passo eternamente "rodando" nem
            # deixar o "digitando..." ligado pra sempre.
            painel.finalizar()

    # Registra ou limpa a promessa conforme a ação aconteceu ou não.
    #
    # Uma pendência de confirmação (ação destrutiva esperando "sim") NÃO conta
    # como promessa não cumprida: ali ela fez a coisa certa ao não executar, e
    # tratar como promessa faria a resposta "sim" ser cobrada como se ela
    # tivesse enrolado.
    aguardando_confirmacao = discord_admin.tem_confirmacao_pendente(
        canal_id, message.author.id) is not None

    perguntou = resultado.texto.rstrip().endswith(("?", "?!"))

    # Conversa comum de quem está NA CALL volta pro fluxo normal, pra resposta
    # sair por voz. Fora desse caso a resposta do laço é usada como está —
    # gerar de novo pelo caminho de conversa seria pagar duas chamadas pela
    # mesma mensagem.
    if not (resultado.agiu or aguardando_confirmacao or perguntou) \
            and autor_na_call:
        print(f"[Discord] '{texto[:50]}' era conversa e {nome_autor} está na "
              f"call; devolvendo pro fluxo de voz.")
        return False

    if aguardando_confirmacao:
        discord_admin.limpar_promessa(canal_id, message.author.id)
    elif (perguntou and nivel != discord_admin.NIVEL_NENHUM
          and (bool(pendente) or era_ordem)):
        # Ela pediu esclarecimento. A resposta que vier ("de texto, sobre
        # memes") não parece pedido de administração nenhum, então sem guardar
        # o pedido aqui a conversa morreria e o canal nunca seria criado.
        # Guarda o pedido ORIGINAL, não a pergunta dela.
        discord_admin.registrar_promessa(
            canal_id, message.author.id, pendente or texto,
            tipo=discord_admin.TIPO_PERGUNTA)
    elif resultado.agiu:
        discord_admin.limpar_promessa(canal_id, message.author.id)
    elif (nivel != discord_admin.NIVEL_NENHUM
          and (bool(pendente) or era_ordem)
          and getattr(resultado, "promessa_sem_acao", False)):
        discord_admin.registrar_promessa(
            canal_id, message.author.id, pendente or texto,
            tipo=discord_admin.TIPO_PROMESSA)

    if not resultado.texto:
        return False

    _responder_no_canal(message, resultado.texto)
    return True


async def _extrair_imagens_mensagem(message: discord.Message) -> list:
    """
    Baixa os anexos de imagem da mensagem e retorna lista de dicts com base64,
    media_type, caminho local e a URL original.

    O caminho local existe porque as ferramentas de administração (ícone do
    servidor, banner, emoji) precisam dos BYTES da imagem. A URL de anexo do
    Discord hoje é assinada (?ex=...&is=...&hm=...) e a versão pelada — que o
    modelo às vezes repassa de cabeça — devolve 404. Com o arquivo já salvo em
    disco, a ferramenta lê direto e essa classe de erro inteira some.
    """
    import base64
    import re as _re

    _TIPOS = {
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif":  "image/gif",
        ".webp": "image/webp",
    }

    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "uploads_emily", "discord")
    imagens = []
    for anexo in message.attachments:
        tipo_conteudo = str(getattr(anexo, "content_type", "") or "")
        ext = next((e for e in _TIPOS if anexo.filename.lower().endswith(e)), None)
        if not ext and tipo_conteudo.startswith("image/"):
            # Anexo de imagem com extensão fora da tabela (ex.: .jfif).
            ext = ".png"
        if not ext:
            continue

        dados = None
        try:
            # read() vai pela URL assinada que a API deu pra ESTE anexo — é a
            # forma que nunca dá 404. O download cru fica de reserva.
            dados = await anexo.read()
        except Exception as e:
            print(f"[Discord] read() falhou pra {anexo.filename} ({e}); "
                  f"tentando baixar direto.")
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(anexo.url) as resp:
                        if resp.status == 200:
                            dados = await resp.read()
            except Exception as e2:
                print(f"[Discord] Erro ao baixar imagem {anexo.filename}: {e2}")

        if not dados:
            continue

        item = {
            "data":       base64.b64encode(dados).decode("utf-8"),
            "media_type": (tipo_conteudo if tipo_conteudo.startswith("image/")
                           else _TIPOS[ext]),
            "nome":       anexo.filename,
            "url":        anexo.url,
        }

        # Guarda em disco pra as ferramentas de admin usarem o arquivo pronto.
        try:
            os.makedirs(pasta, exist_ok=True)
            seguro = _re.sub(r"[^A-Za-z0-9._-]", "_", anexo.filename) or "imagem"
            caminho = os.path.join(pasta, f"{int(time.time() * 1000)}_{seguro}")
            with open(caminho, "wb") as f:
                f.write(dados)
            item["caminho"] = caminho
        except OSError as e:
            print(f"[Discord] Não salvei o anexo em disco: {e}")

        imagens.append(item)
        print(f"[Discord] Imagem capturada: {anexo.filename} "
              f"({item['media_type']}) -> {item.get('caminho') or 'só memória'}")
    return imagens


# ─────────────────────────────────────────────────────────────────
# AVALIAÇÃO DE CONTEXTO EM TEMPO REAL
# ─────────────────────────────────────────────────────────────────

def _ids_na_janela(canal_id: int) -> list:
    """IDs de quem apareceu na conversa recente, sem repetir e sem a Emily."""
    vistos, saida = set(), []
    for item in reversed(_historico_janela.get(canal_id, [])):
        if item.get("eh_emily"):
            continue
        uid = item.get("user_id") or 0
        if uid and uid not in vistos:
            vistos.add(uid)
            saida.append(uid)
    return saida


def _contexto_de_quem_esta_falando(canal_id: int) -> str:
    """
    Fatos dos membros presentes na conversa, no máximo três pessoas.

    O dono fica de fora porque a memória dele já entra por outro caminho
    (memoria.py) e duplicar o mesmo fato em dois blocos do prompt é pagar duas
    vezes pela mesma informação.
    """
    try:
        import perfil_discord
        dono = int(_config.get("usuario_id", 0) or 0)
        return perfil_discord.contexto_de_membros(
            _ids_na_janela(canal_id), excluir=[dono] if dono else None)
    except Exception as e:
        print(f"[Discord] Contexto de membros indisponível: {e}")
        return ""


def _talvez_aprender_sobre(canal_id: int, message) -> None:
    """
    Dispara a extração de fatos se — e só se — as travas do perfil aprovarem.

    Chamado depois de responder, nunca antes: aprender sobre alguém não pode
    atrasar a resposta. E deve_extrair() recusa de graça na maioria das vezes,
    então isso é barato mesmo sendo chamado a cada interação.
    """
    try:
        import perfil_discord
        autor = message.author
        dono = int(_config.get("usuario_id", 0) or 0)
        if getattr(autor, "bot", False):
            return
        if not perfil_discord.deve_extrair(autor.id, eh_dono=(autor.id == dono)):
            return

        transcricao = (getattr(message, "content", "") or "").strip()
        if not transcricao:
            return
        nome = _nome_de(autor)
        print(f"[Discord] Travas do perfil liberaram: aprendendo sobre {nome}")
        perfil_discord.extrair_em_segundo_plano(autor.id, nome, transcricao)
    except Exception as e:
        print(f"[Discord] Falha ao tentar aprender sobre o membro: {e}")


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
    permitir_admin: bool = False,
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
        if _pedido_para_sair_da_call(ultima_msg, message_original):
            async def _sair():
                global _emily_em_call_ativa
                _emily_em_call_ativa = False
                if _voice_client and _voice_client.is_connected():
                    _desligar_escuta_de_call()
                    await _voice_client.disconnect()
                await message_original.reply("saí!")
            if _loop:
                asyncio.run_coroutine_threadsafe(_sair(), _loop)
            return

    # ─── PEDIDO DE ADMINISTRAÇÃO DO SERVIDOR ───
    #
    # Vem ANTES das ramificações de call, e a posição é o conserto de um bug
    # real: com a checagem depois, estando a Emily numa call, TODO pedido de
    # administração era engolido pela ramificação de voz e respondido pelo
    # avaliar_contexto_canal, que não tem ferramenta na mesa. Resultado: ela
    # falava na call em vez de criar o canal.
    #
    # Administração é sempre respondida por TEXTO, mesmo com ela na call. O
    # resultado dessas ações é nome de canal, lista de cargo e confirmação de
    # deleção — coisa pra ler, não pra ouvir.
    #
    # Só entra aqui com permitir_admin, que vem exclusivamente do worker de
    # menções: mensagem solta no canal continua caindo na participação
    # espontânea, que não tem ferramenta nenhuma.
    # Precisa ser calculado ANTES do bloco de administração: ele usa isso pra
    # decidir se conversa comum volta pro fluxo de voz.
    autor_na_call = False
    if _emily_em_call_ativa and _voice_client and _voice_client.is_connected():
        canal_voz_autor = _membro_em_call(message_original.author.id)
        autor_na_call = bool(canal_voz_autor
                             and canal_voz_autor.id == _voice_client.channel.id)

    if permitir_admin:
        try:
            if _tentar_pedido_de_admin(
                canal_id, ultima_msg, nome_autor, message_original,
                historico_externo,
                autor_na_call=autor_na_call and not _pediu_resposta_no_chat(ultima_msg),
            ):
                return
        except Exception as e:
            print(f"[Discord] Falha no caminho de administração: "
                  f"{type(e).__name__}: {e}")

    # ─── ONDE A RESPOSTA SAI: CALL OU CHAT ───
    #
    # Regra, na ordem:
    #   - administração e pedido explícito de resposta escrita: chat (acima)
    #   - quem está NA MESMA call que ela: voz, como sempre foi
    #   - quem está fora da call: chat, resposta normal
    #
    # A última parte mudou: antes ela respondia "tô na call agora, entra lá se
    # quiser falar comigo" pra quem estava fora, o que na prática ignorava a
    # pessoa. Agora ela conversa por escrito com quem está fora e por voz com
    # quem está dentro, ao mesmo tempo.
    if autor_na_call and _pediu_resposta_no_chat(ultima_msg):
        print(f"[Discord] {nome_autor} está na call mas pediu resposta escrita.")
        autor_na_call = False

    if autor_na_call:
        janela = _historico_janela.get(canal_id, [])
        historico_fmt = historico_externo or _formatar_janela(
            canal_id, excluir_ultima=True)

        imagens = janela[-1].get("imagens", []) if janela else []
        resultado = modelo_module.avaliar_contexto_canal(
            historico_fmt, ultima_msg, nome_autor, imagens,
            contexto_membros=_contexto_de_quem_esta_falando(canal_id),
            para_call=True)

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
        _talvez_aprender_sobre(canal_id, message_original)
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
                    audio = voz_module.gerar_audio_bytes(
                        "Oi, cheguei!", para_call=True)
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

    historico_fmt = historico_externo or _formatar_janela(
        canal_id, excluir_ultima=True)

    # ── Injeta memória do Vitor no contexto para o modelo ter personalização ──
    ctx_mem = _contexto_memoria()
    if ctx_mem:
        historico_fmt = f"{ctx_mem}\n\n---\n{historico_fmt}" if historico_fmt else ctx_mem

    imagens = janela[-1].get("imagens", []) if janela else []
    resultado = modelo_module.avaliar_contexto_canal(
        historico_fmt, ultima_msg, nome_autor, imagens,
        contexto_membros=_contexto_de_quem_esta_falando(canal_id))

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

    _talvez_aprender_sobre(canal_id, message_original)


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
            # Só quem chama a Emily de propósito (menção ou reply) consegue
            # mandar ela mexer no servidor.
            permitir_admin=True,
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
# PONTE DE CHAT — a Emily local mexendo no Discord a pedido do Vitor
#
# As ferramentas (ler_chat_discord, mandar_mensagem_discord,
# responder_mensagem_discord, mandar_dm_discord, ver_canais_discord) vivem no
# ferramentas.py, mas só aqui existe o client vivo. Todas são síncronas e
# seguras pra chamar da thread do laço de ferramentas: despacham pra dentro
# do loop do bot com run_coroutine_threadsafe e esperam o resultado.
# ─────────────────────────────────────────────────────────────────

def _pronto_discord() -> Optional[str]:
    """Erro legível quando não dá pra mexer no Discord agora. None = pode."""
    if not _pronto or _loop is None or _client.user is None:
        return ("O Discord não está conectado agora. Confere se o bot está "
                "ligado e tenta de novo daqui a pouco.")
    return None


def _nome_usuario(u) -> str:
    """Nome de exibição de um User OU Member (User às vezes não tem)."""
    return (getattr(u, "display_name", None)
            or getattr(u, "name", None) or f"id {getattr(u, 'id', '?')}")


def _achar_canal(servidor: str = "", canal: str = ""):
    """Resolve (canal, erro) por nome. Nunca chuta: sem match claro, devolve
    erro com as opções pra a Emily (ou o Vitor) escolher."""
    alvo = (canal or "").strip().lstrip("#").lower()
    serv_alvo = (servidor or "").strip().lower()
    guilds = list(_client.guilds)
    if serv_alvo:
        casadas = [g for g in guilds if serv_alvo in g.name.lower()]
        if not casadas:
            return None, (f"Não achei servidor parecido com '{servidor}'. "
                          "Servidores que eu vejo: "
                          + ", ".join(g.name for g in guilds))
        guilds = casadas
    if not guilds:
        return None, "Não estou em nenhum servidor."
    if not alvo:
        if len(guilds) == 1:
            geral = next((c for c in guilds[0].text_channels
                          if c.permissions_for(guilds[0].me).send_messages),
                         None)
            if geral:
                return geral, ""
        return None, ("Me diz em qual canal: "
                      + ", ".join("#" + c.name
                                  for g in guilds for c in g.text_channels[:12])
                      + "…")
    exatas, parecidas = [], []
    for g in guilds:
        for c in g.text_channels:
            if c.name.lower() == alvo:
                exatas.append(c)
            elif alvo in c.name.lower():
                parecidas.append(c)
    achado = exatas or parecidas
    if not achado:
        return None, (f"Não achei canal '{canal}'"
                      + (f" no servidor '{servidor}'" if serv_alvo else "")
                      + ". Canais que eu vejo: "
                      + ", ".join("#" + c.name
                                  for g in guilds
                                  for c in g.text_channels[:15]) + "…")
    return achado[0], ""


def ver_canais(servidor: str = "") -> str:
    """Lista servidores e canais de texto, pra a Emily se localizar."""
    erro = _pronto_discord()
    if erro:
        return erro
    serv_alvo = (servidor or "").strip().lower()
    guilds = [g for g in _client.guilds
              if not serv_alvo or serv_alvo in g.name.lower()]
    if serv_alvo and not guilds:
        return (f"Não achei servidor parecido com '{servidor}'. "
                "Servidores que eu vejo: "
                + ", ".join(g.name for g in _client.guilds))
    partes = []
    for g in guilds:
        nomes = [c.name for c in g.text_channels]
        partes.append(f"{g.name}: " + ", ".join("#" + c for c in nomes[:20])
                      + ("…" if len(nomes) > 20 else ""))
    return "\n".join(partes) or "Não vi canais de texto."


async def _ler_chat_async(canal, quantidade: int) -> str:
    msgs = [m async for m in canal.history(
        limit=min(max(int(quantidade or 20), 1), 50))]
    msgs.reverse()
    if not msgs:
        return f"#{canal.name} está sem mensagens recentes."
    linhas = []
    for m in msgs:
        nome = APELIDOS_MEMBROS.get(m.author.id, _nome_usuario(m.author))
        linhas.append(f"{nome}: {m.content.strip() or '(anexo sem texto)'}")
    return (f"Últimas {len(linhas)} mensagens em #{canal.name} "
            f"({canal.guild.name}), da mais antiga pra mais recente:\n"
            + "\n".join(linhas))


def ler_chat_discord(canal: str = "", servidor: str = "",
                     quantidade: int = 20) -> str:
    erro = _pronto_discord()
    if erro:
        return erro
    ch, erro_canal = _achar_canal(servidor, canal)
    if ch is None:
        return erro_canal
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _ler_chat_async(ch, quantidade), _loop)
        return fut.result(timeout=40)
    except Exception as e:  # noqa: BLE001
        return f"Não consegui ler o chat: {type(e).__name__}: {e}"


async def _enviar_mensagem_async(canal, texto: str) -> str:
    limpo = texto.strip()
    pedacos = [limpo[i:i + 1900] for i in range(0, len(limpo), 1900)]
    for p in pedacos:
        await canal.send(p)
        await asyncio.sleep(0.8)
    return f"Mandei em #{canal.name} ({canal.guild.name})."


def mandar_mensagem_discord(canal: str, mensagem: str,
                            servidor: str = "") -> str:
    erro = _pronto_discord()
    if erro:
        return erro
    if not (mensagem or "").strip():
        return "A mensagem veio vazia."
    ch, erro_canal = _achar_canal(servidor, canal)
    if ch is None:
        return erro_canal
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _enviar_mensagem_async(ch, mensagem), _loop)
        return fut.result(timeout=30)
    except discord.Forbidden:
        return f"Sem permissão pra falar em #{ch.name} ({ch.guild.name})."
    except Exception as e:  # noqa: BLE001
        return f"Não consegui mandar: {type(e).__name__}: {e}"


async def _responder_autor_async(canal, autor: str, texto: str) -> str:
    alvo = (autor or "").strip().lower()
    ultima = None
    nome_achado = ""
    async for m in canal.history(limit=100):
        if m.author.id == _client.user.id:
            continue
        nome = APELIDOS_MEMBROS.get(m.author.id, _nome_usuario(m.author))
        if alvo in nome.lower():
            ultima = m
            nome_achado = nome
            break
    if ultima is None:
        return (f"Não achei mensagem recente de '{autor}' em #{canal.name} "
                f"(olhei as últimas 100).")
    await ultima.reply(texto[:1900])
    return f"Respondi {nome_achado} em #{canal.name}."


def responder_mensagem_discord(autor: str, resposta: str,
                               canal: str = "", servidor: str = "") -> str:
    erro = _pronto_discord()
    if erro:
        return erro
    if not (resposta or "").strip():
        return "A resposta veio vazia."
    ch, erro_canal = _achar_canal(servidor, canal)
    if ch is None:
        return erro_canal
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _responder_autor_async(ch, autor, resposta), _loop)
        return fut.result(timeout=40)
    except Exception as e:  # noqa: BLE001
        return f"Não consegui responder: {type(e).__name__}: {e}"


def _procurar_pessoas(nome: str) -> list:
    """
    Pessoas conhecidas do bot cujo nome/apelido casa com a busca.

    Um BOT não tem 'lista de amigos' (isso é de conta de usuário): o mais
    próximo é a união de quem compartilha servidor com ele (membros, com o
    intent de membros ligado) e quem já mandou DM (fica no cache de
    usuários). É essa união que a busca cobre.
    """
    alvo = (nome or "").strip().lower()
    if not alvo:
        return []
    achados: dict = {}
    for guild in _client.guilds:
        for m in guild.members:
            if getattr(m, "bot", False):
                continue
            nomes = {str(getattr(m, "display_name", "") or "").lower(),
                     str(getattr(m, "name", "") or "").lower()}
            if any(alvo in n for n in nomes if n):
                achados[m.id] = m
    for u in list(_client.users):
        if getattr(u, "bot", False) or u.id in achados:
            continue
        if alvo in _nome_usuario(u).lower():
            achados[u.id] = u
    return list(achados.values())


async def _mandar_dm_async(user, texto: str) -> str:
    limpo = texto.strip()
    pedacos = [limpo[i:i + 1900] for i in range(0, len(limpo), 1900)]
    for p in pedacos:
        await user.send(p)
        await asyncio.sleep(0.8)
    return f"Mandei no direct de {_nome_usuario(user)}."


def mandar_dm_discord(pessoa: str, mensagem: str,
                      nome_exato: str = "") -> str:
    erro = _pronto_discord()
    if erro:
        return erro
    if not (mensagem or "").strip():
        return "A mensagem veio vazia."
    candidatas = _procurar_pessoas(pessoa)
    alvo_exato = (nome_exato or "").strip().lower()
    if alvo_exato:
        candidatas = [c for c in candidatas
                      if _nome_usuario(c).lower() == alvo_exato
                      or str(getattr(c, "name", "")).lower() == alvo_exato]
        if not candidatas:
            return (f"Confirmei '{nome_exato}', mas já não achei ninguém com "
                    "esse nick exato. Pede pro Vitor conferir a grafia.")
    if not candidatas:
        return (f"Não achei ninguém parecido com '{pessoa}'. Eu enxergo quem "
                "compartilha servidor comigo e quem já me mandou direct.")
    if len(candidatas) > 1:
        lista = "\n".join(f"- {_nome_usuario(c)} "
                          f"(@{getattr(c, 'name', '?')})"
                          for c in candidatas[:8])
        return ("Achei mais de uma pessoa com esse nome:\n" + lista +
                "\nPergunta pro Vitor qual é a certa (o nick exato) e chama "
                "de novo passando nome_exato.")
    alvo = candidatas[0]
    try:
        fut = asyncio.run_coroutine_threadsafe(
            _mandar_dm_async(alvo, mensagem), _loop)
        return fut.result(timeout=30)
    except discord.Forbidden:
        return (f"Achei {_nome_usuario(alvo)}, mas a pessoa não aceita "
                "mensagem direta do bot (privacidade do Discord dela).")
    except Exception as e:  # noqa: BLE001
        return f"Não consegui mandar o direct: {type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────────
# DIRECT (DM) — a conversa privada 1:1
#
# Qualquer pessoa que mandar DM pro bot recebe resposta, como se tivesse
# marcado ela. Três regras que o Vitor fixou:
#   1. DEBOUNCE: mensagem nova reinicia um timer de alguns segundos; quando
#      ele expira, a leva inteira vai pro modelo de uma vez (senão uma pessoa
#      que digita em três pedaços receberia três respostas picadas).
#   2. PRIVACIDADE TOTAL: o conteúdo não vai pro terminal, pro histórico,
#      pra janela de contexto do servidor, pra moderação, pra lugar nenhum
#      que o Vitor possa ler. O prompt da DM reza a mesma coisa pra ela.
#   3. MEMÓRIA POR USUÁRIO: a mesma ficha de fatos do perfil_discord alimenta
#      o direct, e o que rolar lá também alimenta a ficha.
# ─────────────────────────────────────────────────────────────────

_DM_ESPERA_SEGUNDOS = float(os.getenv("EMILY_DM_ESPERA", "4"))
_dm_pendentes: dict = {}   # user_id -> {"msgs": [...], "ultima": msg, "timer": Timer}
_dm_lock = threading.Lock()


def _dm_autorizado(autor) -> bool:
    """
    DM só de quem compartilha servidor com o bot. O dono passa sempre
    (verificado por ID, não por nome). Discord não expõe 'lista de amigos'
    pra bot: servidor em comum é a fronteira de confiança que existe.
    """
    uid = autor.id
    dono = int(_config.get("usuario_id", 0) or 0)
    if dono and uid == dono:
        return True
    for guild in _client.guilds:
        if guild.get_member(uid):
            return True
    return False


def _dm_receber(message) -> None:
    """Recebe uma DM e agenda a resposta com debounce."""
    autor = message.author
    if getattr(autor, "bot", False):
        return
    if not _config.get("responder_dm", True):
        return
    texto = message.content.strip()
    if not texto:
        return
    if not _dm_autorizado(autor):
        # Não é do círculo (sem servidor em comum): nem o nome vai pro log.
        print("[Discord] DM ignorada: remetente sem servidor em comum.")
        return
    uid = autor.id
    with _dm_lock:
        pend = _dm_pendentes.setdefault(
            uid, {"msgs": [], "ultima": None, "timer": None})
        pend["msgs"].append(texto)
        pend["ultima"] = message
        if pend["timer"] is not None:
            pend["timer"].cancel()
        timer = threading.Timer(_DM_ESPERA_SEGUNDOS, _dm_responder,
                                args=(uid,))
        timer.daemon = True
        pend["timer"] = timer
    uid = autor.id
    dono = int(_config.get("usuario_id", 0) or 0)
    eh_dono = bool(dono) and uid == dono
    # PRIVACIDADE: pro terminal vai só quem escreveu e o tamanho da leva.
    print(f"[Discord] DM de {getattr(autor, 'name', uid)} "
          f"({'DONO confirmado por ID' if eh_dono else 'contato'}"
          f"{'' if eh_dono or not dono else f' (dono é {dono})'}"
          f", {len(pend['msgs'])} na leva, respondendo em "
          f"{_DM_ESPERA_SEGUNDOS:.0f}s)")
    timer.start()


def _dm_responder(uid: int) -> None:
    """O timer venceu: a leva acumulada vai pro modelo e a resposta volta."""
    with _dm_lock:
        pend = _dm_pendentes.pop(uid, None)
    if not pend or not pend["msgs"]:
        return
    mensagens = list(pend["msgs"])
    message = pend["ultima"]
    autor = message.author
    nome = _nome_usuario(autor)
    dono = int(_config.get("usuario_id", 0) or 0)
    eh_dono = bool(dono) and uid == dono
    try:
        contexto = ""
        if eh_dono:
            # O Vitor usa a memória dele de sempre (memoria.py), não ficha
            # de perfil — é a mesma memória que entra nas conversas no PC.
            try:
                import memoria as _mem
                contexto = _mem.formatar_para_prompt()
            except Exception:
                contexto = ""
        else:
            try:
                import perfil_discord
                fatos = perfil_discord.fatos_de(uid)
                if fatos:
                    contexto = ("O que você já sabe dessa pessoa (da sua "
                                "memória de usuários):\n- "
                                + "\n- ".join(fatos[:6]))
            except Exception:
                pass

        # Histórico de conversa com essa pessoa (o mesmo mecanismo de
        # "abrir e lembrar" dos chats dela, só que privado da interface).
        historico_txt = ""
        try:
            import historico_dm
            historico_txt = historico_dm.formatar(uid)
        except Exception:
            pass

        import modelo
        resposta = modelo.responder_dm_discord(
            mensagens=mensagens, nome=nome, user_id=uid,
            contexto_membros=contexto, eh_dono=eh_dono,
            historico_dm_txt=historico_txt)
        resposta = (resposta or "").strip()
        if resposta:
            _dm_enviar(message, resposta)

        # Guarda a troca no histórico da DM (as falas dele e as suas).
        try:
            import historico_dm
            for m in mensagens:
                historico_dm.adicionar(uid, nome, "pessoa", m)
            if resposta:
                historico_dm.adicionar(uid, nome, "emily", resposta)
        except Exception as e:
            print(f"[Discord] histórico de DM não salvou: {e}")

        # Aprender sobre a pessoa, com as mesmas travas do servidor. O Vitor
        # NÃO vira ficha de perfil: ele já tem a memória dele (memoria.py).
        if not eh_dono:
            try:
                import perfil_discord
                perfil_discord.observar(uid, autor.display_name, " ".join(mensagens),
                                        falou_com_emily=True, eh_bot=False)
                if perfil_discord.deve_extrair(uid):
                    perfil_discord.extrair_em_segundo_plano(
                        uid, nome, "\n".join(mensagens))
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        print(f"[Discord] DM não respondida: {type(e).__name__}: {e}")


def _dm_enviar(message, texto: str) -> None:
    """Responde no direct, quebrado como pessoa digitando."""
    import modelo as modelo_module
    texto = modelo_module.remover_tags_fish(texto)
    if not texto or not _loop:
        return
    partes = modelo_module.quebrar_resposta_discord(texto)

    async def _enviar():
        try:
            for p in partes:
                await message.channel.send(p)
                await asyncio.sleep(1.2)
        except discord.Forbidden:
            print("[Discord] DM: a pessoa não aceita mensagem do bot.")
        except Exception as e:
            print(f"[Discord] Erro ao responder DM: {e}")

    asyncio.run_coroutine_threadsafe(_enviar(), _loop)


# ─────────────────────────────────────────────────────────────────
# VOZ NA CALL
# ─────────────────────────────────────────────────────────────────

def _membro_em_call(user_id: int) -> Optional[discord.VoiceChannel]:
    for guild in _client.guilds:
        member = guild.get_member(user_id)
        if member and member.voice and member.voice.channel:
            return member.voice.channel
    return None


# ─────────────────────────────────────────────────────────────────
# OUVIR A CALL
#
# Todo caminho que entra em call passa pelo _conectar_ouvindo, e a razão é uma
# linha só: `canal.connect()` devolve um VoiceClient comum, que ENVIA áudio e
# não recebe nada. É por isso que ela falava na call e nunca ouviu — a conexão
# nunca foi capaz de receber, independente do resto do código estar certo.
#
# `cls=voice_recv.VoiceRecvClient` troca isso. Ele herda de VoiceClient, então
# tudo que já funcionava (play, move_to, disconnect) continua igual.
#
# Isso ainda não é suficiente: o voice_recv 0.5.3 decifra só a camada de
# transporte e não aplica o DAVE, a criptografia ponta a ponta que o Discord
# passou a exigir em toda call. Sem o patch_dave, o que chega no decoder Opus é
# payload ainda cifrado — o "gibberish audio" que aparece nas tentativas
# anteriores. O patch é aplicado dentro do escuta_call.comecar_a_ouvir.
# ─────────────────────────────────────────────────────────────────

async def _conectar_ouvindo(canal: discord.VoiceChannel):
    """
    Conecta num canal de voz por um cliente capaz de RECEBER áudio.

    Antes de tentar conectar, adota a conexão que já existe naquela guild. Isso
    conserta um erro observado no log: "Already connected to a voice channel".
    Acontece quando a variável _voice_client daqui perde o sincronismo com a
    realidade — ela fica None (ou aponta pra um cliente velho) enquanto o
    discord.py ainda tem uma conexão de pé. Sem adotar, as duas tentativas de
    connect() falham, a função devolve False, e a Emily fica fora da call estando
    dentro dela.
    """
    # Adota a conexão que o discord.py já tem naquela guild, se ela existe e
    # está viva. Move de canal se preciso.
    ja_conectado = canal.guild.voice_client
    if ja_conectado is not None and ja_conectado.is_connected():
        if ja_conectado.channel and ja_conectado.channel.id != canal.id:
            await ja_conectado.move_to(canal)
        print(f"[Discord] Adotei a conexão de voz que já existia em "
              f"'{canal.guild.name}'.")
        return ja_conectado

    # Conexão MEIA-MORTA: guild.voice_client existe mas não está is_connected(),
    # ou o connect() abaixo vai estourar "Already connected" porque o discord.py
    # ainda guarda um websocket de voz pendurado que a checagem acima não pegou.
    # Nos dois casos, a única saída é forçar a desconexão antes de tentar de
    # novo — sem isso, connect() falha para sempre e a Emily fica trancada fora
    # da call estando "dentro" dela. Foi exatamente o loop de "Already connected
    # to a voice channel" no log.
    #
    # MAS antes de matar, espera e olha de novo. O cliente foi criado com
    # reconnect=True, então um is_connected() falso neste instante pode ser uma
    # reconexão ACONTECENDO, não uma conexão morta — e disconnect(force=True)
    # em cima dela derruba a call na frente de todo mundo. É o "desconecta
    # sozinha do nada": a conexão daria um solavanco de meio segundo, o código
    # viu caído, e forçou a saída de uma sessão que ficaria boa sozinha.
    #
    # A espera depois do disconnect NÃO é enfeite: o Discord leva alguns segundos
    # pra derrubar a sessão de voz do lado do servidor, e reconectar antes disso
    # é o que produzia o TimeoutError no handshake do connect. Meio segundo era
    # curto demais.
    if ja_conectado is not None:
        for _ in range(6):
            await asyncio.sleep(0.5)
            if ja_conectado.is_connected():
                print(f"[Discord] A conexão que parecia meia-morta se recuperou "
                      f"sozinha em '{canal.guild.name}'; adotando ela.")
                if ja_conectado.channel and ja_conectado.channel.id != canal.id:
                    await ja_conectado.move_to(canal)
                return ja_conectado
        try:
            await ja_conectado.disconnect(force=True)
            print(f"[Discord] Limpei uma conexão de voz meia-morta em "
                  f"'{canal.guild.name}' antes de reconectar.")
            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"[Discord] Falha ao limpar conexão meia-morta (seguindo "
                  f"assim mesmo): {type(e).__name__}: {e}")

    # timeout explícito e generoso: o handshake de voz com DAVE é mais lento que
    # o de uma call comum, e o padrão de alguns builds do voice_recv é curto
    # demais — foi o que gerava "TimeoutError" seco no log.
    _TIMEOUT_VOZ = float(os.getenv("EMILY_CALL_CONNECT_TIMEOUT", "30"))

    async def _conectar_ouvindo_real():
        """Conecta por um cliente que RECEBE áudio, tentando mais de uma vez.

        NÃO cai pro cliente comum à toa. Isso é o conserto do bug reportado:
        quando o VoiceRecvClient dava TimeoutError, o código caía pro
        canal.connect() comum — que NUNCA recebe áudio. A partir daí
        is_listening() ficava 'não' pra sempre, o vigia reanexava em loop sem
        nunca consertar (não há o que reanexar num cliente que não escuta), e a
        Emily ficava surda a call inteira. Melhor tentar de novo o cliente certo
        do que entrar com um cliente que garantidamente não ouve.
        """
        ultimo_erro = None
        for tentativa in range(1, 4):
            try:
                return await canal.connect(
                    cls=voice_recv.VoiceRecvClient,
                    timeout=_TIMEOUT_VOZ,
                    reconnect=True,
                )
            except discord.ClientException as e:
                # "Already connected": limpa o que sobrou e tenta de novo.
                if "already connected" not in str(e).lower():
                    raise
                print(f"[Discord] '{e}' na tentativa {tentativa}; forçando "
                      f"desconexão e tentando de novo.")
                preso = canal.guild.voice_client
                if preso is not None:
                    try:
                        await preso.disconnect(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(2.0)
                ultimo_erro = e
            except (asyncio.TimeoutError, TimeoutError) as e:
                print(f"[Discord] handshake de voz expirou na tentativa "
                      f"{tentativa} de 3; tentando de novo em 2s.")
                # Limpa qualquer conexão parcial que o connect deixou pra trás
                # antes de repetir, senão a próxima tentativa bate em "Already
                # connected".
                preso = canal.guild.voice_client
                if preso is not None:
                    try:
                        await preso.disconnect(force=True)
                    except Exception:
                        pass
                await asyncio.sleep(2.0)
                ultimo_erro = e
        # Esgotou as tentativas do cliente que ouve. Levanta pra quem chamou
        # decidir — NÃO cai pro cliente mudo aqui.
        raise ultimo_erro or discord.ClientException(
            "não consegui conectar recebendo áudio")

    # Config pedindo pra NÃO ouvir: aí sim o cliente comum é o certo.
    if not _config.get("ouvir_call", True):
        return await canal.connect(timeout=_TIMEOUT_VOZ, reconnect=True)

    try:
        return await _conectar_ouvindo_real()
    except Exception as e:
        # Última linha: se nem tentando três vezes o cliente que ouve subiu,
        # entra com o comum pra pelo menos poder FALAR. Ela perde a audição,
        # não a voz — e isso fica gritado no log, não escondido, porque escuta
        # morta é o bug mais difícil de perceber.
        print("=" * 70)
        print(f"[Discord] NÃO consegui conectar recebendo áudio depois de 3 "
              f"tentativas ({type(e).__name__}: {e}). Entrando SÓ pra falar — "
              f"a Emily vai ficar SURDA nesta call.")
        print("=" * 70)
        return await canal.connect(timeout=_TIMEOUT_VOZ, reconnect=True)




def _quem_esta_na_call() -> str:
    """Nomes de quem está na call agora, pro contexto do modelo."""
    if not _voice_client or not _voice_client.is_connected():
        return ""
    nomes = [_nome_de(m) for m in _voice_client.channel.members if not m.bot]
    return ", ".join(nomes)


class _FontePCMTempoReal(discord.AudioSource):
    """Entrega 20 ms por leitura sem bloquear o relógio do player do Discord.

    O AudioPlayer tenta compensar leituras lentas disparando quadros acumulados
    rapidamente. O FFmpeg pode bloquear esperando o próximo chunk do Fish;
    portanto lemos o FFmpeg em outra thread e entregamos silêncio de 20 ms
    enquanto ele não tem áudio. Não esperamos bufferizar a primeira fala.
    """

    _SILENCIO = bytes(3840)  # PCM16 estéreo, 48 kHz, 20 ms (discord.py)

    def __init__(self, fonte: discord.AudioSource):
        self._fonte = fonte
        self._quadros = queue.Queue(maxsize=250)
        self._terminou = threading.Event()
        self._fechada = threading.Event()
        self._leitora = threading.Thread(
            target=self._ler_ffmpeg, daemon=True, name="discord-pcm-ffmpeg")
        self._leitora.start()

    def _ler_ffmpeg(self) -> None:
        try:
            while not self._fechada.is_set():
                quadro = self._fonte.read()
                if not quadro:
                    break
                while not self._fechada.is_set():
                    try:
                        self._quadros.put(quadro, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except Exception as erro:
            if not self._fechada.is_set():
                print(f"[Discord] FFmpeg parou de ler PCM: {erro}")
        finally:
            self._terminou.set()

    def read(self) -> bytes:
        try:
            return self._quadros.get_nowait()
        except queue.Empty:
            if self._terminou.is_set() or self._fechada.is_set():
                # EOF pode chegar entre get_nowait e a consulta do evento.
                # Confira a fila novamente para preservar o ultimo quadro.
                try:
                    return self._quadros.get_nowait()
                except queue.Empty:
                    return b""
            return self._SILENCIO

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        if not self._fechada.is_set():
            self._fechada.set()
            limpar = getattr(self._fonte, "cleanup", None)
            if limpar is not None:
                limpar()


async def _tocar_na_call_async(pcm: bytes, taxa: int, canais: int) -> bool:
    if not pcm or not _voice_client or not _voice_client.is_connected():
        return False

    esperou = 0.0
    while _voice_client.is_playing() and esperou < 30.0:
        await asyncio.sleep(0.05)
        esperou += 0.05

    acabou = asyncio.Event()

    def _fim(erro):
        if erro:
            print(f"[Discord] Erro no fim do áudio da call: {erro}")
        # O after do discord.py roda em outra thread, então não dá pra tocar o
        # Event direto.
        try:
            _loop.call_soon_threadsafe(acabou.set)
        except RuntimeError:
            pass

    try:
        fonte = _FontePCMTempoReal(discord.FFmpegPCMAudio(
            io.BytesIO(pcm),
            pipe=True,
            before_options=f"-f s16le -ar {taxa} -ac {canais}",
            options="-vn",
        ))
        _voice_client.play(fonte, after=_fim)
    except Exception as e:
        print(f"[Discord] Erro ao tocar na call: {type(e).__name__}: {e}")
        return False

    await acabou.wait()
    return True


def tocar_na_call_bloqueando(pcm: bytes, taxa: int = 44100,
                             canais: int = 1) -> bool:
    """
    Toca na call e só volta quando o áudio terminou.

    Bloquear é requisito, não descuido: o anti-eco do resto_call fecha a janela
    de mudo quando esta função retorna. Se ela voltasse na hora de começar a
    tocar, a janela fecharia no início da fala e a própria voz dela, voltando
    pelo microfone de alguém, seria tratada como fala nova.
    """
    if not _pronto or not _loop or not pcm:
        return False
    futuro = asyncio.run_coroutine_threadsafe(
        _tocar_na_call_async(pcm, taxa, canais), _loop)
    try:
        # O teto é o dobro do que uma resposta de call pode durar. Sem teto, um
        # after que não dispara travaria a thread de resposta pra sempre e ela
        # ficaria muda até reiniciar.
        return bool(futuro.result(timeout=120))
    except Exception as e:
        print(f"[Discord] Falha ao tocar na call: {type(e).__name__}: {e}")
        return False


def _pensar_na_call(user_id: int, nome: str, fala: str, transcricao: str,
                    modo_conversa: bool = False, quem_na_call: str = "",
                    ao_decidir=None, ao_frase=None) -> dict:
    """
    A resposta dela pra uma fala da call, COM as ferramentas na mesa.

    POR QUE O CAMINHO DE CALL PRECISA DE FERRAMENTA
    ───────────────────────────────────────────────
    Antes ela respondia de cabeça, e o resultado apareceu no primeiro uso real:
    perguntaram se o servidor de Minecraft estava ligado e ela disse que ia
    verificar. Nunca verificou, porque não tinha como — e como numa call não
    existe um segundo turno pra ela voltar com a resposta, "vou verificar" é
    apenas uma forma bonita de não responder.

    Aqui ela usa o MESMO laço de ferramentas do chat de texto, então "o servidor
    tá on?" é respondido consultando o servidor.

    IDENTIDADE E PERMISSÃO
    ──────────────────────
    O user_id vem do mapa de SSRC do Discord, não de nada que a pessoa tenha
    dito. É a mesma qualidade de identidade que uma mensagem de texto tem, então
    o nível de acesso pode ser calculado do jeito normal, pelo Member real. Isso
    importa: sem isso, qualquer um numa call poderia pedir pra ela banir alguém.

    Devolve {"responder", "resposta", "detalhe_texto"} pro resto_call.
    """
    import discord_admin
    import modelo as modelo_module

    vazio = {"responder": False, "resposta": "", "detalhe_texto": ""}

    if not _voice_client or not _voice_client.is_connected():
        return vazio

    canal_voz = _voice_client.channel
    guild = canal_voz.guild
    membro = guild.get_member(user_id) if guild else None
    if membro is not None and (getattr(membro, "display_name", None)
                              or getattr(membro, "name", None)):
        nome = _nome_de(membro)
    dono = int(_config.get("usuario_id", 0) or 0)
    eh_dono = bool(dono) and user_id == dono

    # O perfil das pessoas importa na conversa comum também, não só quando uma
    # ferramenta é usada. Este bloco é local/cacheado e não adiciona chamada de
    # modelo ao caminho rápido.
    contexto_membros = ""
    try:
        import perfil_discord
        ids = [m.id for m in canal_voz.members if not m.bot]
        contexto_membros = perfil_discord.contexto_de_membros(
            ids, excluir=[dono] if dono else None)
    except Exception as e:
        print(f"[Discord] Contexto de membros da call indisponível: {e}")

    if membro is None:
        # Sem Member não há como saber o nível de acesso, e chutar seria dar
        # poder a quem não tem. Cai no caminho sem ferramenta, que só conversa.
        print(f"[Discord] Não achei o membro {user_id} na guild; respondendo "
              f"na call sem ferramenta.")
        return modelo_module.responder_na_call(
            transcricao=transcricao, ultima_fala=fala, nome_autor=nome,
            contexto_membros=contexto_membros,
            modo_conversa=modo_conversa, quem_esta_na_call=quem_na_call,
            dono_user_id=_memoria_dono(eh_dono, user_id),
            nome_quem_falou=nome,
            ao_decidir=ao_decidir, ao_frase=ao_frase)

    # ── CAMINHO RÁPIDO PARA CONVERSA ──
    #
    # A grande maioria do que se fala numa call é conversa: zoeira, papo,
    # reação. Nada disso precisa de ferramenta. Mandar tudo pelo laço de
    # ferramentas (responder_discord_com_ferramentas) é o que fazia a Emily
    # demorar MUITO mais pra responder na call que no chat normal: o catálogo
    # inteiro vai no prompt a cada fala, a chamada é sem streaming, e ainda pode
    # dar mais de uma volta.
    #
    # Então: só entra no caminho pesado quando a fala É de fato pedido de
    # administração, pesquisa/informação atual, ou ação útil do PC pedida pelo
    # dono confirmado por ID. Conversa comum vai pelo responder_na_call, que é UMA
    # chamada leve e rápida, o mesmo caminho de antes de existir tool calling na
    # call.
    #
    # Isso não perde capacidade: "o servidor tá on?", "pesquisa isso", "abre o
    # navegador" (quando for o dono) e "bane o fulano" continuam caindo no caminho
    # com ferramenta. Só a conversa é que para de pagar o custo dela.
    import resto_call
    fala_para_classificacao = resto_call.remover_vocativo_inicial(fala)
    pede_ferramenta_util = modelo_module.fala_pede_ferramenta_na_call(
        fala_para_classificacao, eh_dono=eh_dono)
    pedido_admin_explicito = discord_admin.parece_ordem_de_admin(
        fala, dirigido_a_ela=True)
    pedido_admin_amplo = discord_admin.parece_pedido_de_admin(
        fala, dirigido_a_ela=True)
    classificacao = cf.classificar(
        fala_para_classificacao,
        acao_explicita=bool(
            pede_ferramenta_util or pedido_admin_explicito),
        # A call já tem iniciativa espontânea própria e sem ferramenta. Não
        # mandar desabafo/conversa ao catálogo pesado evita latência e ações por
        # inferência de uma transcrição ruidosa.
        permitir_iniciativa=False,
    )
    if pedido_admin_amplo and classificacao.proibe_ferramenta:
        if discord_admin.parece_pergunta_de_capacidade(fala):
            classificacao = cf.ClassificacaoFerramenta(
                cf.FERRAMENTA_OPCIONAL,
                "pergunta_de_capacidade_administrativa",
            )
        else:
            classificacao = cf.ClassificacaoFerramenta(
                cf.FERRAMENTA_OBRIGATORIA,
                "consulta_factual_administrativa",
            )
    precisa_ferramenta = bool(
        pedido_admin_amplo or classificacao.permite_ferramenta)
    print(f"[CLASSIFICACAO-FERRAMENTA] canal=discord_call "
          f"politica={classificacao.politica} motivo={classificacao.motivo} "
          f"admin_amplo={pedido_admin_amplo} texto={fala[:80]!r}")
    if not precisa_ferramenta:
        print(f"[Discord] Call: '{fala[:50]}' é conversa; caminho rápido "
              f"(sem ferramenta).")
        return modelo_module.responder_na_call(
            transcricao=transcricao, ultima_fala=fala, nome_autor=nome,
            contexto_membros=contexto_membros,
            modo_conversa=modo_conversa, quem_esta_na_call=quem_na_call,
            dono_user_id=_memoria_dono(eh_dono, user_id),
            nome_quem_falou=nome,
            ao_decidir=ao_decidir, ao_frase=ao_frase)

    nivel = discord_admin.nivel_do_membro(membro, _config)


    # origem="discord", NÃO uma origem nova de call. Isso é deliberado e é a
    # parte mais importante desta função.
    #
    # No discord_admin, só a origem 'discord' exige confirmação de ação
    # destrutiva. Uma origem "call" inventada aqui cairia no ramo sem
    # confirmação — e ação destrutiva pedida por voz, sem trava, é o pior lugar
    # possível pra não ter trava: qualquer um numa call, uma transcrição errada
    # de "apaga o canal", e não há mensagem escrita pra alguém revisar depois.
    #
    # Com 'discord', terceiros continuam precisando da confirmação escrita. A
    # exceção experimental abaixo só existe para o dono CONFIRMADO PELO ID e só
    # quando esta fala é uma ordem explícita. Conversa casual/transcrição incerta
    # não seta autonomia_direta e portanto não executa destrutivo nenhum.
    discord_admin.definir_sessao(
        nivel=nivel,
        autor_id=user_id,
        autor_nome=nome,
        guild_id=guild.id,
        canal_id=canal_voz.id,
        origem="discord",
        autonomia_direta=bool(
            eh_dono and pedido_admin_explicito
            and modelo_module.autonomia_experimental_ativa()
        ),
    )

    try:
        resultado = modelo_module.responder_discord_com_ferramentas(
            mensagem=fala,
            nome_autor=nome,
            historico_canal=transcricao,
            nome_servidor=guild.name,
            nome_canal=canal_voz.name,
            nivel=nivel,
            eh_dono=(nivel == discord_admin.NIVEL_DONO),
            # Pesquisa/ação útil explicitamente roteada precisa chamar ferramenta
            # de verdade. Administração mantém a política antiga: o próprio laço
            # decide se executa, para uma frase jogada não virar ação destrutiva.
            parece_acao=classificacao.exige_ferramenta,
            politica_ferramenta=classificacao.politica,
            motivo_classificacao=classificacao.motivo,
            contexto_membros=contexto_membros,
            falada_na_call=True,
            dono_user_id=_memoria_dono(
                nivel == discord_admin.NIVEL_DONO, user_id),
        )
    except Exception as e:
        print(f"[Discord] Laço de ferramentas falhou na call: "
              f"{type(e).__name__}: {e}")
        return vazio
    finally:
        discord_admin.limpar_sessao()

    bruto = (getattr(resultado, "texto", "") or "").strip()

    # O portão de "era comigo ou sobre mim?" mora no prompt e volta por esta
    # palavra. Ficou no mesmo turno de propósito: perguntar antes, em outra
    # chamada, dobraria a espera de todo mundo pra filtrar um caso raro.
    if not bruto or "NADA_A_DIZER" in bruto.upper():
        return vazio

    fala_limpa, resto = modelo_module.encurtar_para_call(
        modelo_module.limpar_para_tts(bruto))
    resto = modelo_module.remover_tags_fish(resto)
    if not fala_limpa:
        return vazio

    if getattr(resultado, "agiu", False):
        print(f"[Discord] Na call, executei ferramenta pra {nome}: "
              f"'{fala_limpa[:50]}'")

    return {"responder": True, "resposta": fala_limpa, "detalhe_texto": resto}


async def _reconectar_voz_async() -> None:
    """
    Sai da call e entra de novo, pra consertar uma recepção que não volta.

    Existe porque reanexar o sink não resolve tudo. O SocketReader do discord.py
    é criado uma vez, dentro do VoiceConnectionState, e num disconnect com
    limpeza a thread dele morre de vez. Depois disso, qualquer callback que eu
    registre nele é registrado num morto — e nenhuma quantidade de reanexo muda
    isso. Só reconectar cria um VoiceConnectionState novo.

    É agressivo (a Emily sai e volta na call, todo mundo vê), então quem chama é
    o vigia do escuta_call, e só depois de as tentativas baratas falharem.
    """
    global _voice_client

    if not _voice_client or not _voice_client.is_connected():
        return

    canal = _voice_client.channel
    print(f"[Discord] Reconectando a voz em '{canal.name}' pra recuperar a "
          f"escuta...")

    _desligar_escuta_de_call()
    try:
        await _voice_client.disconnect(force=True)
    except Exception as e:
        print(f"[Discord] Erro ao desconectar pra reconectar: {e}")
    _voice_client = None

    # O Discord não gosta de reentrada imediata no mesmo canal.
    await asyncio.sleep(2.0)

    try:
        _voice_client = await _conectar_ouvindo(canal)
    except Exception as e:
        print(f"[Discord] Não consegui voltar pra call: {type(e).__name__}: {e}")
        return

    await _ligar_escuta_de_call()


def _pedir_reconexao_de_voz() -> None:
    """Ponte de thread: o vigia do escuta_call roda fora do loop do asyncio."""
    if not _pronto or not _loop:
        return
    asyncio.run_coroutine_threadsafe(_reconectar_voz_async(), _loop)


async def _ligar_escuta_de_call() -> None:
    """Começa a ouvir (e talvez responder) na call em que ela já está."""
    if not _config.get("ouvir_call", True):
        return
    if not _voice_client or not _voice_client.is_connected():
        return
    try:
        import escuta_call
        import resto_call
    except Exception as e:
        # Grita, com traceback. Um erro de import aqui deixa ela COMPLETAMENTE
        # surda, e o sintoma é ausência de log — o tipo de falha mais difícil de
        # investigar, porque não parece falha, parece que ninguém falou.
        # Uma linha discreta no meio de um terminal cheio não serve.
        import traceback
        print("=" * 70)
        print("[Discord] A ESCUTA DE CALL NÃO SUBIU — ela vai ficar SURDA.")
        print(f"          {type(e).__name__}: {e}")
        traceback.print_exc()
        print("=" * 70)
        return

    try:
        resto_call.definir_saidas(
            tocar=tocar_na_call_bloqueando,
            tocar_stream=lambda texto, cancelar_se=None: __import__(
                "voz").falar_na_call_stream(texto, cancelar_se=cancelar_se),
            mandar_texto=enviar_texto_discord,
            quem_na_call=_quem_esta_na_call,
            pensar=_pensar_na_call,
            pensar_espontaneo=lambda transcricao, quem: __import__(
                "modelo").iniciativa_na_call(transcricao, quem),
        )
        escuta_call.definir_reconexao(_pedir_reconexao_de_voz)
        escuta_call.observar(_coletar_estilo_vitor_na_call)
        escuta_call.observar(_aprender_com_call)
        # Cada entrada em call é uma conversa nova: linha aberta de call
        # anterior nem transcrição velha podem fazer ela responder alguém do nada.
        resto_call.zerar_conversa()
        escuta_call.zerar_historico()

        recado = await escuta_call.comecar_a_ouvir(_voice_client)
        print(f"[Discord] {recado}")
        if not escuta_call.pretendo_ouvir():
            print("=" * 70)
            print("[Discord] ELA ENTROU NA CALL MAS NÃO ESTÁ OUVINDO. Motivo "
                  "acima.")
            print("=" * 70)

        # pretendo_ouvir() e não escutando(): o segundo responde "a recepção está
        # de pé AGORA", e uma recepção momentaneamente caída é conserto do vigia
        # do escuta_call, que vem em segundos. Gatear a resposta nisso deixaria
        # ela muda mesmo depois do áudio voltar.
        if _config.get("responder_call", True) and escuta_call.pretendo_ouvir():
            print(f"[Discord] {resto_call.ligar()}")
    except Exception as e:
        import traceback
        print("=" * 70)
        print(f"[Discord] ERRO AO LIGAR A ESCUTA DA CALL — ela vai ficar surda: "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        print("=" * 70)


def _coletar_estilo_vitor_na_call(turno) -> None:
    """Somente fala atribuída ao ID configurado, nunca nomes/apelidos."""
    dono = int(_config.get("usuario_id", 0) or 0)
    if dono and turno.user_id == dono:
        import estilo_vitor
        estilo_vitor.coletar(turno.texto, "fala", "call", autor_id=str(dono))
        import perfil_discord
        perfil_discord.aprender_associacao_explicitada(turno.texto)
        perfil_discord.aprender_fato_explicitado_pelo_dono(turno.texto)


def _aprender_com_call(turno) -> None:
    """Observa cada turno transcrito por ID, mesmo quando Emily não responde."""
    dono = int(_config.get("usuario_id", 0) or 0)
    if not turno.texto or not turno.user_id or turno.user_id == dono:
        return
    import perfil_discord
    membro = None
    if _voice_client and _voice_client.is_connected():
        membro = _voice_client.channel.guild.get_member(turno.user_id)
    if membro is not None and membro.bot:
        return
    nome = (membro.display_name if membro is not None else turno.nome)
    # A fala é matéria da ficha independentemente do gatilho de resposta;
    # só uma chamada à Emily conta como interação para o limiar de extração.
    import resto_call
    perfil_discord.observar(
        turno.user_id, nome, turno.texto,
        falou_com_emily=resto_call.chamada_direta(turno.texto),
        origem="call",
    )
    if perfil_discord.deve_extrair(turno.user_id):
        perfil_discord.extrair_em_segundo_plano(
            turno.user_id, nome, turno.texto)


def _desligar_escuta_de_call() -> None:
    """Chamado em todo caminho que sai da call. Nunca levanta."""
    try:
        import escuta_call
        import resto_call
        resto_call.desligar()
        resto_call.zerar_conversa()
        escuta_call.parar_de_ouvir(_voice_client)
    except Exception as e:
        print(f"[Discord] Erro ao desligar a escuta da call: "
              f"{type(e).__name__}: {e}")


async def _entrar_falar_e_sair(canal_voz: discord.VoiceChannel, texto: str) -> None:
    global _voice_client
    import voz as voz_module

    try:
        if _voice_client and _voice_client.is_connected():
            if _voice_client.channel.id != canal_voz.id:
                await _voice_client.move_to(canal_voz)
        else:
            _voice_client = await _conectar_ouvindo(canal_voz)

        # Espera terminar qualquer áudio anterior
        while _voice_client.is_playing():
            await asyncio.sleep(0.1)

        audio_bytes = voz_module.gerar_audio_bytes(texto, para_call=True)
        if not audio_bytes:
            print("[Discord] gerar_audio_bytes retornou vazio!")
            return

        print(f"[Discord] Tocando áudio na call — {len(audio_bytes)} bytes")

        import modelo as modelo_module
        _avisar_anti_eco(
            audio_bytes, 44100, 1, modelo_module.remover_tags_fish(texto))

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
                _desligar_escuta_de_call()
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
        "activity": discord.Activity(type=discord.ActivityType.listening, name="vendo anime enquanto o vitor programa"),
        "status":   discord.Status.online,
    },
    "ouvindo": {
        "activity": discord.Activity(type=discord.ActivityType.listening, name="hackeando o governo russo.."),
        "status":   discord.Status.online,
    },
    "falando": {
        "activity": discord.Activity(type=discord.ActivityType.playing, name="jogando gta 6"),
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

def _avisar_anti_eco(audio_bytes: bytes, taxa: int, canais: int,
                     texto: str = "") -> None:
    """
    Diz ao anti-eco que a voz que vai sair agora é dela.

    Vale pra toda fala que NÃO nasce no resto_call: o "oi, cheguei" e a resposta
    de quem falou com ela pelo chat estando na call. Sem isso, essa voz volta
    pelo microfone de alguém e ela responde a si mesma.
    """
    try:
        import resto_call
        # ligada(), não respondendo(): estando calada ela ainda fala por outros
        # caminhos, e essa voz ecoa do mesmo jeito.
        if not resto_call.ligada():
            return
        segundos = len(audio_bytes) / float(max(1, taxa * canais * 2))
        resto_call.silenciar_por(segundos, texto)
    except Exception:
        pass


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

    _avisar_anti_eco(audio_bytes, sample_rate, channels)

    try:
        source = _FontePCMTempoReal(discord.FFmpegPCMAudio(
            io.BytesIO(audio_bytes),
            pipe=True,
            before_options=f"-f s16le -ar {sample_rate} -ac {channels}",
            options="-vn",
        ))
        _voice_client.play(source)
    except Exception as e:
        print(f"[Discord] Erro ao tocar PCM: {e}")


class _PipePCMDiscord:
    """Arquivo bloqueante alimentado enquanto o Fish ainda sintetiza.

    O ``FFmpegPCMAudio(pipe=True)`` lê este objeto numa thread própria. ``read``
    espera novos pedaços em vez de devolver EOF quando a fila fica vazia; assim
    o Discord começa a transmitir no primeiro chunk da Fish sem encerrar o
    processo entre uma chegada e outra.
    """

    def __init__(self):
        self._fila = queue.Queue()
        self._pendente = bytearray()
        self._fechado = False
        self._aceitando = True

    def write(self, dados: bytes) -> None:
        if dados and self._aceitando:
            self._fila.put(bytes(dados))

    def close(self) -> None:
        if self._aceitando:
            self._aceitando = False
            self._fila.put(None)

    def read(self, tamanho: int = -1) -> bytes:
        alvo = tamanho if tamanho and tamanho > 0 else 8192
        if not self._pendente and not self._fechado:
            pedaco = self._fila.get()
            if pedaco is None:
                self._fechado = True
            else:
                self._pendente.extend(pedaco)
        # Depois do primeiro pedaço, agrega apenas o que JÁ chegou. Nunca espera
        # completar BLOCKSIZE: essa espera somaria latência ao primeiro som.
        while len(self._pendente) < alvo and not self._fechado:
            try:
                pedaco = self._fila.get_nowait()
            except queue.Empty:
                break
            if pedaco is None:
                self._fechado = True
                break
            self._pendente.extend(pedaco)
        if not self._pendente:
            return b""
        quantidade = min(alvo, len(self._pendente))
        saida = bytes(self._pendente[:quantidade])
        del self._pendente[:quantidade]
        return saida


async def _tocar_stream_pcm_async(pipe: _PipePCMDiscord, sample_rate: int,
                                  channels: int, texto: str = "") -> bool:
    """Liga um pipe PCM ao FFmpeg e só termina depois do último chunk."""
    global _voice_client
    if not _voice_client or not _voice_client.is_connected():
        canal_voz_id = _config.get("canal_voz_id", 0)
        if not canal_voz_id or not await _conectar_voz(canal_voz_id):
            pipe.close()
            return False

    while _voice_client.is_playing():
        await asyncio.sleep(0.05)

    acabou = asyncio.Event()

    def _fim(erro):
        if erro:
            print(f"[Discord] Erro no fim do stream PCM: {erro}")
        try:
            _loop.call_soon_threadsafe(acabou.set)
        except RuntimeError:
            pass

    try:
        fonte = _FontePCMTempoReal(discord.FFmpegPCMAudio(
            pipe,
            pipe=True,
            before_options=f"-f s16le -ar {sample_rate} -ac {channels}",
            options="-vn",
        ))
        _voice_client.play(fonte, after=_fim)
        await acabou.wait()
        return True
    except Exception as e:
        pipe.close()
        print(f"[Discord] Erro ao tocar stream PCM: {type(e).__name__}: {e}")
        return False


class StreamPCMDiscord:
    """Handle thread-safe de uma fala incremental no canal de voz."""

    def __init__(self, sample_rate: int, channels: int, texto: str = ""):
        self._pipe = _PipePCMDiscord()
        self._sample_rate = max(1, int(sample_rate))
        self._channels = max(1, int(channels))
        self._texto = texto
        self._total = 0
        self._futuro = asyncio.run_coroutine_threadsafe(
            _tocar_stream_pcm_async(
                self._pipe, self._sample_rate, self._channels, texto),
            _loop,
        )

    def escrever(self, dados: bytes) -> None:
        if not dados:
            return
        self._total += len(dados)
        try:
            import resto_call
            if resto_call.ligada():
                duracao = self._total / float(
                    self._sample_rate * self._channels * 2)
                resto_call.silenciar_por(duracao, self._texto)
        except Exception:
            pass
        self._pipe.write(dados)

    def fechar(self, esperar: bool = False) -> bool:
        self._pipe.close()
        if not esperar:
            return True
        try:
            return bool(self._futuro.result(timeout=120))
        except Exception as e:
            print(f"[Discord] Falha ao fechar stream PCM: {type(e).__name__}: {e}")
            return False


def abrir_stream_pcm_discord(sample_rate: int = 44100, channels: int = 1,
                             texto: str = ""):
    """Abre uma fala incremental; ``None`` quando o bot não está disponível."""
    if not _pronto or not _loop:
        return None
    try:
        return StreamPCMDiscord(sample_rate, channels, texto)
    except Exception as e:
        print(f"[Discord] Não consegui abrir stream PCM: {type(e).__name__}: {e}")
        return None


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


def ativar_escuta_discord() -> bool:
    import discord_monitor
    ativo = discord_monitor.selecionar(True)
    print("[Discord] Escuta de texto ativada!" if ativo else
          "[Discord] Não consegui transferir a escuta para este PC.")
    return ativo


def desativar_escuta_discord() -> bool:
    import discord_monitor
    desligado = discord_monitor.selecionar(False)
    print("[Discord] Escuta de texto desativada!" if desligado else
          "[Discord] Não consegui desligar a escuta sincronizada.")
    return desligado


def escuta_ativa() -> bool:
    """True se a Emily está acompanhando/respondendo o chat do Discord agora.
    Fonte da verdade pra o toggle da interface refletir o estado real."""
    return _escuta_discord_ativa.is_set()


def desconectar_voz() -> None:
    if not _pronto or not _loop:
        return

    async def _desconectar():
        global _voice_client
        if _voice_client and _voice_client.is_connected():
            _desligar_escuta_de_call()
            await _voice_client.disconnect()
            _voice_client = None
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
    if os.getenv("EMILY_RUNTIME_CLOUD") == "1" and _client.user and member.id == _client.user.id:
        from cloud_runtime_server import registrar_estado_voz
        registrar_estado_voz(after.channel)
    global _emily_em_call_ativa
    usuario_id = _config.get("usuario_id", 0)

    # Comportamento original — segue o Vitor
    if usuario_id and member.id == usuario_id:
        if after.channel is not None:
            print(f"[Discord] Vitor entrou no canal '{after.channel.name}', conectando Emily...")
            await _conectar_voz(after.channel.id)
        elif before.channel is not None and after.channel is None:
            if _voice_client and _voice_client.is_connected():
                _desligar_escuta_de_call()
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
            _desligar_escuta_de_call()
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
                await _ligar_escuta_de_call()
                return True
            await _voice_client.move_to(canal)
        else:
            _voice_client = await _conectar_ouvindo(canal)
        print(f"[Discord] Entrou no canal de voz: '{canal.name}'")
        await _ligar_escuta_de_call()
        return True
    except Exception as e:
        print(f"[Discord] Erro ao entrar no canal de voz: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────

def inicializar() -> None:
    global _config

    from cloud_runtime_client import hospedado_na_oracle
    if hospedado_na_oracle() and os.getenv("EMILY_RUNTIME_CLOUD") != "1":
        print("[Discord] Bot hospedado na Oracle; controle remoto disponível.")
        return
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


from cloud_runtime_client import instalar_proxy as _instalar_proxy_oracle
_instalar_proxy_oracle(globals())
