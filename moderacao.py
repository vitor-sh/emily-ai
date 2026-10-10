"""
moderacao.py — a Emily olhando o servidor sem virar carrasco.

A REGRA QUE DEFINE ESTE ARQUIVO
───────────────────────────────
Ela NUNCA pune sozinha. Não bane, não expulsa, não castiga por conta própria.

Isso não é falta de capacidade: as ferramentas de banir e castigar já existem no
discord_admin e funcionam. É escolha, e o motivo é o custo assimétrico do erro.

Um falso negativo custa uma mensagem ruim ficando no ar por alguns minutos até
alguém ver. Um falso positivo custa um membro banido por causa de uma piada
interpretada errado — e a confiança de todos os outros, que passam a medir o que
escrevem perto dela. O segundo é muito mais caro e não tem desfazer que resolva.

Então a saída dela é a de uma pessoa que está na sala:
  • coisa escancarada (spam em rajada, pornografia, golpe) → ela AVISA o membro
    ali, no canal, pra ele saber que aquilo vai dar problema
  • coisa que precisa de julgamento → ela chama o Vitor no privado
  • reincidência → ela SUGERE a punição ao Vitor, com o histórico na mão

DUAS CAMADAS, E A PRIMEIRA É DE GRAÇA
─────────────────────────────────────
Passar toda mensagem do servidor por um modelo seria caro e lento — e a
esmagadora maioria das mensagens não tem nada de errado.

Então a primeira camada é heurística local: contagem, repetição, proporção de
maiúsculas, padrão de link, convite de outro servidor. Custa microssegundos e
zero token, e recusa a maior parte do tráfego sem consultar ninguém.

A LLM só entra no que a heurística já achou estranho. É ela que evita o desastre
clássico do filtro de palavra: "esse boss é um câncer" não é ofensa a ninguém, e
nenhuma regex sabe disso.

SOBRE ANEXO DE IMAGEM
─────────────────────
Pornografia em anexo não dá pra pegar por texto. A Emily tem visão, então dá pra
olhar — mas olhar toda imagem do servidor é um custo recorrente considerável.

O meio-termo: só imagens em canal NÃO marcado como NSFW, com teto diário, e nunca
de quem já é conhecido do servidor. A lógica é que o problema real é gente nova
despejando conteúdo, não o pessoal de casa mandando meme.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple
from emily_paths import arquivo_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = str(arquivo_dados("moderacao.json"))

# Mestre. Com 0 ela para de olhar e volta a só moderar quando pedirem.
ATIVO = os.getenv("EMILY_MODERACAO", "1").strip() != "0"

# ── flood ──
FLOOD_MENSAGENS = int(os.getenv("EMILY_MOD_FLOOD_MSGS", "6"))
FLOOD_SEGUNDOS = float(os.getenv("EMILY_MOD_FLOOD_SEG", "8"))

# ── repetição ──
REPETICAO_VEZES = int(os.getenv("EMILY_MOD_REPETICAO", "3"))
REPETICAO_JANELA = float(os.getenv("EMILY_MOD_REPETICAO_SEG", "60"))

# ── maiúsculas ──
CAPS_MINIMO_CHARS = 25
CAPS_PROPORCAO = 0.75

# ── menções ──
MAX_MENCOES = int(os.getenv("EMILY_MOD_MENCOES", "6"))

# Não avisa a mesma pessoa de novo antes disso.
COOLDOWN_AVISO = float(os.getenv("EMILY_MOD_COOLDOWN", "300"))

# Teto de julgamentos por LLM por hora. Trava de custo: um servidor sob ataque de
# spam dispararia a heurística centenas de vezes, e sem teto isso viraria
# centenas de chamadas de modelo.
MAX_JULGAMENTOS_POR_HORA = int(os.getenv("EMILY_MOD_MAX_HORA", "20"))

# ── imagens ──
CHECAR_IMAGENS = os.getenv("EMILY_MOD_IMAGENS", "1").strip() != "0"
MAX_IMAGENS_POR_DIA = int(os.getenv("EMILY_MOD_MAX_IMAGENS", "30"))
# Quem já tem esse tanto de mensagem no servidor não tem imagem checada.
MENSAGENS_PRA_SER_DE_CASA = 60

# Avisos óbvios antes dela sugerir punição ao Vitor.
REINCIDENCIA_PRA_SUGERIR = 3


def _log(msg: str) -> None:
    print(f"[MOD] {msg}")


# ═════════════════════════════════════════════════════════════════
# PADRÕES LOCAIS
#
# Curtos e específicos de propósito. Cada linha aqui é uma chance de falso
# positivo, então só entra o que é quase sempre problema de verdade — e mesmo
# esses só LEVANTAM SUSPEITA: quem decide é a LLM depois.
# ═════════════════════════════════════════════════════════════════

_RE_CONVITE = re.compile(
    r"(discord\.(gg|com/invite)/|discordapp\.com/invite/)", re.IGNORECASE)

# Golpe de Nitro/Steam é o spam mais comum em servidor de jogo, e o formato é
# sempre o mesmo: promessa de item grátis + link.
_RE_GOLPE = re.compile(
    r"(free\s*nitro|nitro\s*gr[áa]tis|steam\s*gift|free\s*gift|"
    r"claim\s*your|airdrop|@everyone.*http|http.*@everyone)", re.IGNORECASE)

_RE_LINK = re.compile(r"https?://\S+", re.IGNORECASE)

# Encurtadores: legítimos existem, mas em spam são a regra.
_RE_ENCURTADOR = re.compile(
    r"https?://(bit\.ly|tinyurl|goo\.gl|t\.co|is\.gd|cutt\.ly|shorturl)",
    re.IGNORECASE)

# Sites adultos conhecidos. Lista curta: o objetivo é pegar o link óbvio, não
# manter um índice da internet.
_RE_ADULTO_LINK = re.compile(
    r"(pornhub|xvideos|xnxx|redtube|onlyfans|xhamster|brazzers|"
    r"chaturbate|stripchat)", re.IGNORECASE)

_RE_MENCAO = re.compile(r"<@!?\d+>")


# ═════════════════════════════════════════════════════════════════
# ESTADO
# ═════════════════════════════════════════════════════════════════

_dados: Optional[dict] = None
_lock = threading.Lock()

# Histórico recente por pessoa, só em memória: serve pra detectar flood, e flood
# é sempre coisa dos últimos segundos. Não faz sentido persistir.
_recentes: Dict[int, Deque[Tuple[float, str]]] = {}

_julgamentos: Deque[float] = deque()
_imagens_do_dia: Dict[str, int] = {}


def _padrao() -> dict:
    return {
        "ocorrencias": {},   # user_id -> [{quando, tipo, gravidade, texto}]
        "ultimo_aviso": {},  # user_id -> timestamp
    }


def carregar() -> dict:
    global _dados
    if _dados is not None:
        return _dados
    if not os.path.exists(ARQUIVO):
        _dados = _padrao()
        return _dados
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            lidos = json.load(f)
        base = _padrao()
        base.update({k: v for k, v in lidos.items() if k in base})
        _dados = base
    except (json.JSONDecodeError, OSError) as e:
        _log(f"arquivo ilegível ({e}); começando do zero")
        _dados = _padrao()
    return _dados


def salvar() -> None:
    dados = carregar()
    try:
        os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
        tmp = ARQUIVO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ARQUIVO)
    except OSError as e:
        _log(f"não consegui gravar: {e}")


# ═════════════════════════════════════════════════════════════════
# CAMADA 1: A SUSPEITA LOCAL
# ═════════════════════════════════════════════════════════════════

def _proporcao_caps(texto: str) -> float:
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < CAPS_MINIMO_CHARS:
        return 0.0
    return sum(1 for c in letras if c.isupper()) / len(letras)


def levantar_suspeita(user_id: int, texto: str, *, tem_anexo: bool = False,
                      mencoes: int = 0) -> List[str]:
    """
    Os motivos de suspeita desta mensagem. Lista vazia = nada a ver aqui.

    Pública porque é testável sem Discord nenhum, e é a camada que mais precisa
    ser testada: ela roda em TODA mensagem do servidor.
    """
    motivos: List[str] = []
    agora = time.time()
    limpo = (texto or "").strip()

    # ── flood e repetição ──
    fila = _recentes.setdefault(int(user_id), deque(maxlen=20))
    fila.append((agora, limpo.lower()))
    recentes = [(t, m) for t, m in fila if agora - t <= FLOOD_SEGUNDOS]
    if len(recentes) >= FLOOD_MENSAGENS:
        motivos.append(f"mandou {len(recentes)} mensagens em "
                       f"{FLOOD_SEGUNDOS:.0f} segundos")

    if limpo:
        iguais = [m for t, m in fila
                  if agora - t <= REPETICAO_JANELA and m == limpo.lower()]
        if len(iguais) >= REPETICAO_VEZES:
            motivos.append(f"repetiu a mesma mensagem {len(iguais)} vezes")

    # ── conteúdo ──
    if _RE_GOLPE.search(limpo):
        motivos.append("texto com cara de golpe de item grátis")
    if _RE_ADULTO_LINK.search(limpo):
        motivos.append("link de site adulto")
    if _RE_CONVITE.search(limpo):
        motivos.append("convite pra outro servidor de Discord")
    if _RE_ENCURTADOR.search(limpo):
        motivos.append("link encurtado, que esconde o destino")
    if _proporcao_caps(limpo) >= CAPS_PROPORCAO:
        motivos.append("mensagem longa toda em maiúsculas")
    if mencoes >= MAX_MENCOES:
        motivos.append(f"marcou {mencoes} pessoas de uma vez")

    return motivos


# ═════════════════════════════════════════════════════════════════
# CAMADA 2: O JULGAMENTO
# ═════════════════════════════════════════════════════════════════

_PROMPT_JUIZ = """
Você é a Emily, e faz parte da moderação de um servidor de Discord de amigos que
gira em torno de um servidor de Minecraft. O clima é informal: xingamento entre
amigos, zoeira pesada e humor ácido são NORMAIS aqui e não são problema.

Uma checagem automática levantou suspeita sobre a mensagem abaixo. Sua tarefa é
decidir se é problema de verdade.

O QUE É PROBLEMA DE VERDADE
- spam em rajada, mesma mensagem repetida, flood
- divulgação de outro servidor sem combinar
- golpe: nitro grátis, gift card, link enganoso
- conteúdo sexual explícito
- ataque pessoal sério: ameaça real, racismo, homofobia, ataque à família
- vazar dado pessoal de alguém

O QUE NÃO É PROBLEMA
- xingamento entre amigos, "vai tomar no cu", "seu bosta", zoeira
- reclamar do servidor, do mod, do jogo, de você
- palavrão solto, ironia, sarcasmo, humor de mau gosto entre conhecidos
- caps por empolgação
- link normal de youtube, imagem, meme

Responda SÓ com um JSON, sem mais nada:
{"gravidade": "obvio" | "duvidoso" | "nada",
 "motivo": "uma frase curta explicando",
 "aviso": "o que você diria pra pessoa no chat, uma frase, minúsculo, seu jeito"}

"obvio"    = escancarado, qualquer pessoa concordaria. Você avisa no chat.
"duvidoso" = pode ser problema, mas precisa de julgamento humano. Só o Vitor sabe.
"nada"     = falso alarme. Use SEM MEDO: a maioria dos casos é isso.
""".strip()


def _pode_julgar() -> bool:
    agora = time.time()
    while _julgamentos and agora - _julgamentos[0] > 3600:
        _julgamentos.popleft()
    return len(_julgamentos) < MAX_JULGAMENTOS_POR_HORA


def julgar(texto: str, motivos: List[str], quem: str,
           historico: str = "") -> Optional[dict]:
    """
    Pede o veredito ao modelo. None quando não deu pra julgar.

    Erro de LLM devolve None, e None significa NÃO FAZER NADA. Falhar pro lado
    de não agir é a única escolha defensável aqui: agir sem julgamento é
    exatamente o que este arquivo existe pra evitar.
    """
    if not _pode_julgar():
        _log("teto de julgamentos por hora batido")
        return None
    try:
        import llm
        import modelo
    except Exception as e:
        _log(f"llm indisponível: {e}")
        return None

    _julgamentos.append(time.time())

    prompt = (f"Quem mandou: {quem}\n"
              f"Por que foi marcada: {'; '.join(motivos)}\n"
              f"A mensagem: {texto[:600]}")
    if historico:
        prompt += f"\n\nHistórico dessa pessoa: {historico}"

    try:
        bruto = llm.chamar_texto(prompt, rota_nome=modelo.ROTA_CLASSIFICADOR,
                                 system=_PROMPT_JUIZ, max_tokens=250)
    except Exception as e:
        _log(f"julgamento falhou: {type(e).__name__}: {e}")
        return None

    return _ler_veredito(bruto)


def _ler_veredito(bruto: str) -> Optional[dict]:
    """
    Extrai o JSON da resposta.

    Tolerante a cerca de markdown e a texto em volta, porque modelo às vezes
    responde ```json apesar da instrução. Se não achar JSON válido, devolve None
    — e None não faz nada, que é o lado seguro.
    """
    if not bruto:
        return None
    texto = bruto.strip()
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        dados = json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return None
    gravidade = str(dados.get("gravidade", "")).strip().lower()
    if gravidade not in ("obvio", "duvidoso", "nada"):
        return None
    return {
        "gravidade": gravidade,
        "motivo": str(dados.get("motivo", ""))[:300],
        "aviso": str(dados.get("aviso", ""))[:300],
    }


# ═════════════════════════════════════════════════════════════════
# IMAGENS
# ═════════════════════════════════════════════════════════════════

_PROMPT_IMAGEM = """
Você está checando se uma imagem postada num servidor de Discord de amigos tem
conteúdo sexual explícito ou nudez.

Responda SÓ com um JSON:
{"adulto": true|false, "motivo": "uma frase curta"}

Marque true SÓ para nudez ou ato sexual explícito. Não marque para: meme,
personagem de anime vestido, roupa de banho, print de jogo, foto normal de
pessoa, humor de duplo sentido sem imagem explícita.
""".strip()


def _teto_de_imagens() -> bool:
    hoje = time.strftime("%Y-%m-%d")
    for chave in list(_imagens_do_dia):
        if chave < hoje:
            del _imagens_do_dia[chave]
    return _imagens_do_dia.get(hoje, 0) < MAX_IMAGENS_POR_DIA


def checar_imagem(imagens: List[dict], canal_nsfw: bool,
                  mensagens_da_pessoa: int) -> Optional[dict]:
    """
    Olha os anexos e diz se tem conteúdo adulto.

    As três recusas antes de gastar visão são o que torna isso viável: canal já
    marcado como NSFW não é problema (é pra isso que existe), gente de casa
    manda meme e não pornografia, e o teto diário impede que um dia ruim vire
    uma conta ruim.
    """
    if not CHECAR_IMAGENS or not imagens:
        return None
    if canal_nsfw:
        return None
    if mensagens_da_pessoa >= MENSAGENS_PRA_SER_DE_CASA:
        return None
    if not _teto_de_imagens():
        _log("teto de imagens do dia batido")
        return None

    try:
        import llm
        import modelo
    except Exception:
        return None

    primeira = imagens[0]
    dado = primeira.get("data")
    tipo = primeira.get("media_type", "image/png")
    if not dado:
        return None

    hoje = time.strftime("%Y-%m-%d")
    _imagens_do_dia[hoje] = _imagens_do_dia.get(hoje, 0) + 1

    mensagens = [
        {"role": "system", "content": _PROMPT_IMAGEM},
        {"role": "user", "content": [
            {"type": "text", "text": "Essa imagem tem conteúdo adulto?"},
            {"type": "image_url",
             "image_url": {"url": f"data:{tipo};base64,{dado}"}},
        ]},
    ]
    try:
        bruto = llm.chamar(mensagens, rota_nome=modelo.ROTA_VISAO_GMI,
                           max_tokens=150, stream=False)
        if not isinstance(bruto, str):
            bruto = "".join(bruto)
    except Exception as e:
        _log(f"checagem de imagem falhou: {type(e).__name__}: {e}")
        return None

    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        return None
    try:
        dados = json.loads(bruto[inicio:fim + 1])
    except json.JSONDecodeError:
        return None
    if not dados.get("adulto"):
        return None
    return {"gravidade": "obvio",
            "motivo": f"imagem adulta: {str(dados.get('motivo', ''))[:200]}",
            "aviso": "isso aí não pode aqui, vou ter que avisar o vitor"}


# ═════════════════════════════════════════════════════════════════
# REGISTRO E REINCIDÊNCIA
# ═════════════════════════════════════════════════════════════════

def registrar(user_id: int, nome: str, tipo: str, gravidade: str,
              texto: str) -> int:
    """Guarda a ocorrência. Devolve quantas óbvias essa pessoa já tem."""
    chave = str(int(user_id))
    with _lock:
        dados = carregar()
        lista = dados["ocorrencias"].setdefault(chave, [])
        lista.append({
            "quando": time.time(), "nome": nome, "tipo": tipo,
            "gravidade": gravidade, "texto": (texto or "")[:200],
        })
        # Guarda as 20 últimas por pessoa: histórico serve pra ver padrão, não
        # pra ser um dossiê permanente.
        del lista[:-20]
        salvar()
        return sum(1 for o in lista if o.get("gravidade") == "obvio")


def historico_de(user_id: int) -> str:
    """Resumo em texto do que essa pessoa já fez. Vai pro prompt do juiz."""
    lista = carregar()["ocorrencias"].get(str(int(user_id)), [])
    if not lista:
        return ""
    obvias = sum(1 for o in lista if o.get("gravidade") == "obvio")
    ultimos = "; ".join(o.get("tipo", "") for o in lista[-3:])
    return (f"{len(lista)} ocorrências registradas ({obvias} escancaradas). "
            f"Últimas: {ultimos}")


def _pode_avisar(user_id: int) -> bool:
    ultimo = float(carregar()["ultimo_aviso"].get(str(int(user_id)), 0))
    return time.time() - ultimo >= COOLDOWN_AVISO


def _marcar_aviso(user_id: int) -> None:
    with _lock:
        carregar()["ultimo_aviso"][str(int(user_id))] = time.time()
        salvar()


# ═════════════════════════════════════════════════════════════════
# O CAMINHO COMPLETO
# ═════════════════════════════════════════════════════════════════

def analisar(message, nome: str, imagens: Optional[List[dict]] = None) -> None:
    """
    Ponto de entrada, chamado pelo on_message em thread separada.

    Nada aqui pode levantar exceção pra fora: uma falha na moderação não pode
    impedir a Emily de responder a mensagem normalmente.
    """
    if not ATIVO:
        return
    try:
        _analisar(message, nome, imagens or [])
    except Exception as e:
        _log(f"análise falhou: {type(e).__name__}: {e}")


def _isento(message) -> bool:
    """
    Quem não é olhado: bots, o dono, co-admins e quem já modera o servidor.

    Quem tem permissão de moderar não precisa de aviso da Emily sobre o que pode
    postar — e ela avisando um admin sobre a própria mensagem seria constrangedor
    e inútil.
    """
    autor = getattr(message, "author", None)
    if autor is None or getattr(autor, "bot", False):
        return True
    try:
        import discord_admin
        nivel = discord_admin.nivel_do_membro(autor)
        if nivel != discord_admin.NIVEL_NENHUM:
            return True
    except Exception:
        pass
    try:
        perm = getattr(autor, "guild_permissions", None)
        if perm is not None and (perm.administrator or perm.manage_messages
                                 or perm.moderate_members):
            return True
    except Exception:
        pass
    return False


def _analisar(message, nome: str, imagens: List[dict]) -> None:
    autor = message.author
    if _isento(message):
        return

    texto = (getattr(message, "content", "") or "").strip()
    mencoes = len(_RE_MENCAO.findall(texto))

    veredito = None
    tipo = ""

    motivos = levantar_suspeita(autor.id, texto, tem_anexo=bool(imagens),
                                mencoes=mencoes)
    if motivos:
        tipo = motivos[0]
        veredito = julgar(texto, motivos, nome, historico_de(autor.id))

    # Imagem é caminho separado: uma imagem adulta não levanta suspeita nenhuma
    # no texto, então nunca chegaria ao juiz pelo caminho de cima.
    if veredito is None and imagens:
        canal_nsfw = bool(getattr(getattr(message, "channel", None),
                                  "nsfw", False))
        vistas = _mensagens_da_pessoa(autor.id)
        veredito = checar_imagem(imagens, canal_nsfw, vistas)
        if veredito:
            tipo = "imagem adulta"

    if not veredito or veredito["gravidade"] == "nada":
        return

    quantas = registrar(autor.id, nome, tipo, veredito["gravidade"], texto)
    _log(f"{nome}: {veredito['gravidade']} — {veredito['motivo']}")

    if veredito["gravidade"] == "obvio":
        if _pode_avisar(autor.id):
            _marcar_aviso(autor.id)
            _avisar_no_chat(message, veredito["aviso"] or
                            "isso aí não rola aqui, ó")
        _avisar_o_dono(message, nome, veredito, quantas)
        return

    # Duvidoso: o membro não é avisado. Se ela avisasse no "duvidoso", o aviso
    # em si já seria uma acusação pública de algo que ela não tem certeza.
    _avisar_o_dono(message, nome, veredito, quantas)


def _mensagens_da_pessoa(user_id: int) -> int:
    try:
        import perfil_discord
        ficha = perfil_discord._ficha(user_id)
        return int((ficha or {}).get("mensagens", 0))
    except Exception:
        return 0


def _avisar_no_chat(message, aviso: str) -> None:
    """Ela fala com a pessoa, no canal, respondendo a mensagem."""
    import asyncio
    try:
        import discord_bot
        loop = discord_bot._loop
        if loop is None:
            return
    except Exception:
        return

    async def _enviar():
        try:
            await message.reply(aviso[:400])
        except Exception as e:
            _log(f"não consegui avisar no chat: {e}")

    asyncio.run_coroutine_threadsafe(_enviar(), loop)


def _avisar_o_dono(message, nome: str, veredito: dict, quantas: int) -> None:
    """
    Manda o caso no privado do Vitor.

    No privado, e não num canal de log: canal de log ninguém lê, e o ponto aqui é
    ele SABER. E fica fora do canal público porque metade dos casos é duvidoso, e
    duvidoso exposto em canal é acusação.
    """
    import asyncio
    try:
        import discord_bot
        loop = discord_bot._loop
        dono_id = int((discord_bot._config or {}).get("usuario_id", 0) or 0)
        if loop is None or not dono_id:
            return
    except Exception:
        return

    canal = getattr(getattr(message, "channel", None), "name", "?")
    link = getattr(message, "jump_url", "")
    marca = "escancarado" if veredito["gravidade"] == "obvio" else "na dúvida"

    linhas = [
        f"**moderação** ({marca}) — {nome} em #{canal}",
        f"{veredito['motivo']}",
        f"> {(getattr(message, 'content', '') or '(sem texto)')[:300]}",
    ]
    if veredito["gravidade"] == "obvio":
        linhas.append("já avisei a pessoa no chat.")
    if quantas >= REINCIDENCIA_PRA_SUGERIR:
        linhas.append(f"⚠️ é a {quantas}ª vez escancarada dessa pessoa. "
                      f"acho que já passou de aviso — quer que eu castigue?")
    if link:
        linhas.append(link)

    async def _enviar():
        try:
            usuario = await discord_bot._client.fetch_user(dono_id)
            await usuario.send("\n".join(linhas)[:1900])
        except Exception as e:
            _log(f"não consegui avisar o dono: {e}")

    asyncio.run_coroutine_threadsafe(_enviar(), loop)


def resumo(limite: int = 10) -> str:
    """O que ela viu ultimamente. Resposta de ferramenta."""
    dados = carregar()["ocorrencias"]
    if not dados:
        return "Não registrei nada de errado no servidor até agora."

    todas = []
    for chave, lista in dados.items():
        for o in lista:
            todas.append((o.get("quando", 0), chave, o))
    todas.sort(key=lambda t: -t[0])

    linhas = [f"{len(todas)} ocorrências registradas. As mais recentes:"]
    for quando, _chave, o in todas[:limite]:
        data = time.strftime("%d/%m %H:%M", time.localtime(quando))
        linhas.append(f"- {data} {o.get('nome', '?')}: {o.get('tipo', '?')} "
                      f"({o.get('gravidade')})")

    reincidentes = [(chave, sum(1 for o in lista
                                if o.get("gravidade") == "obvio"))
                    for chave, lista in dados.items()]
    reincidentes = [(c, n) for c, n in reincidentes
                    if n >= REINCIDENCIA_PRA_SUGERIR]
    if reincidentes:
        nomes = []
        for chave, n in reincidentes:
            lista = dados[chave]
            nomes.append(f"{lista[-1].get('nome', chave)} ({n}x)")
        linhas.append("Reincidentes: " + ", ".join(nomes))
    return "\n".join(linhas)


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  MODERAÇÃO DA EMILY")
    print("=" * 66)
    print(f"  ativa:              {ATIVO}")
    print(f"  arquivo:            {os.path.exists(ARQUIVO)}")
    print(f"  flood:              {FLOOD_MENSAGENS} msgs em "
          f"{FLOOD_SEGUNDOS:.0f}s")
    print(f"  repetição:          {REPETICAO_VEZES}x em "
          f"{REPETICAO_JANELA:.0f}s")
    print(f"  cooldown de aviso:  {COOLDOWN_AVISO:.0f}s")
    print(f"  teto de julgamento: {MAX_JULGAMENTOS_POR_HORA}/hora")
    print(f"  checa imagem:       {CHECAR_IMAGENS} "
          f"(teto {MAX_IMAGENS_POR_DIA}/dia)")

    print("\n-- camada 1: o que levanta suspeita (sem LLM, sem custo) --")
    casos = [
        ("conversa normal", "kkkk esse boss é um câncer mesmo"),
        ("xingamento entre amigos", "vai tomar no cu seu bosta kkkkk"),
        ("caps por empolgação", "GENTE OLHA ISSO"),
        ("caps longo", "GENTE OLHA ISSO AQUI AGORA MESMO POR FAVOR TODOS VEJAM"),
        ("golpe de nitro", "free nitro aqui gente https://bit.ly/xxx"),
        ("convite pra outro server", "entra no meu discord.gg/abcdef"),
        ("link adulto", "olha esse pornhub.com/xxx"),
        ("link normal", "vejam https://youtube.com/watch?v=abc"),
        ("encurtador", "clica aqui https://bit.ly/abc"),
    ]
    for rotulo, texto in casos:
        motivos = levantar_suspeita(999000 + len(rotulo), texto)
        marca = "SUSPEITO" if motivos else "passou   "
        print(f"  {marca} {rotulo:26} {motivos or ''}")

    print("\n-- flood: 6 mensagens seguidas da mesma pessoa --")
    for i in range(6):
        motivos = levantar_suspeita(777, f"mensagem {i}")
    print(f"  na 6ª: {motivos}")

    print("\n-- repetição: mesma mensagem 3 vezes --")
    for _ in range(3):
        motivos = levantar_suspeita(888, "compra seguidores aqui")
    print(f"  na 3ª: {motivos}")

    print("\n-- camada 2: leitura do veredito --")
    exemplos = [
        '{"gravidade":"nada","motivo":"zoeira entre amigos","aviso":""}',
        '```json\n{"gravidade":"obvio","motivo":"golpe","aviso":"para"}\n```',
        'sei la nao consegui decidir',
        '{"gravidade":"talvez","motivo":"x","aviso":"y"}',
    ]
    for e in exemplos:
        print(f"  {e[:52]:54} -> {_ler_veredito(e)}")

    print("\n-- histórico registrado --")
    print("  " + resumo().replace("\n", "\n  "))

    print("\n" + "=" * 66)
    print("Nada foi enviado e ninguém foi avisado: o diagnóstico só lê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())
