"""
suporte.py — a Emily atendendo quem está com problema.

DUAS COISAS ESTE ARQUIVO FAZ
────────────────────────────
1. TODA mensagem no canal de suporte é atendimento. Sem menção, sem comando.
   É o que um canal de suporte quer dizer.
2. Fora do canal, ela percebe sinais de problema e OFERECE ajuda uma vez, sem
   insistir.

AS REGRAS SÃO ARQUIVO, NÃO PROMPT
─────────────────────────────────
As regras do servidor moram em `regras_servidor.md`, que o Vitor escreve e edita
quando quiser. Ela lê o arquivo. Não está embutido no código por um motivo
prático: regra muda, e regra que mora no código significa pedir alteração de
código pra trocar uma frase.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from emily_paths import arquivo_dados

ARQUIVO_REGRAS = str(arquivo_dados("regras_servidor.md"))
if os.name == "nt" and not os.path.exists(ARQUIVO_REGRAS):
    try:
        from shutil import copyfile
        os.makedirs(os.path.dirname(ARQUIVO_REGRAS), exist_ok=True)
        copyfile(os.path.join(BASE_DIR, "regras_servidor.md"), ARQUIVO_REGRAS)
    except OSError:
        pass

ATIVO = os.getenv("EMILY_SUPORTE", "1").strip() != "0"

# Quanto tempo a oferta de ajuda vale antes de poder ser repetida.
# Fora do canal de suporte, quanto tempo antes de oferecer ajuda de novo à mesma
# pessoa. Alto de propósito: oferecer ajuda duas vezes é insistência.
COOLDOWN_OFERTA = float(os.getenv("EMILY_SUPORTE_COOLDOWN", "1800"))

# Abre thread pra cada atendimento no canal de suporte?
USAR_THREAD = os.getenv("EMILY_SUPORTE_THREAD", "1").strip() != "0"

# Teto das regras no prompt.
#
# Generoso porque este texto é o que ela usa pra julgar o que é permitido, e
# cortar regra pela metade é pior que gastar token. Só entra no prompt de
# atendimento e no julgamento — não em toda mensagem do servidor.
MAX_REGRAS = int(os.getenv("EMILY_SUPORTE_MAX_REGRAS", "12000"))


def _log(msg: str) -> None:
    print(f"[SUPORTE] {msg}")


# ═════════════════════════════════════════════════════════════════
# SINAIS DE QUE ALGUÉM ESTÁ ENCRENCADO
#
# Usado só FORA do canal de suporte. Dentro dele, tudo é atendimento.
#
# A lista é de sintoma, não de palavra-chave de produto: quem está com problema
# descreve o que aconteceu com ele ("nao abre", "crashou", "me kickou"), não o
# nome técnico da causa.
# ═════════════════════════════════════════════════════════════════

_SINAIS = (
    r"n[ãa]o\s+(consigo|consegue|abre|abriu|entra|entrou|funciona|carrega|roda)",
    r"n[ãa]o\s+t[oô]\s+conseguindo",
    r"(deu|da|dá|tá dando|ta dando)\s+(erro|crash|tela preta|problema)",
    r"crash(ou|ando)?",
    r"(me\s+)?kickou",
    r"(travou|travando|congelou)",
    r"(caiu|caindo)\s+(do|no)\s+(servidor|server)",
    r"(outdated|incompatible|mismatch)",
    r"(falta|faltando)\s+mod",
    r"launcher\s+(n[ãa]o|deu|com)",
    r"como\s+(eu\s+)?(entro|instalo|baixo|atualizo)",
    r"alguem\s+(pode\s+)?(me\s+)?ajud",
    r"algu[ée]m\s+(pode\s+)?(me\s+)?ajud",
    r"pfvr?\s+ajud",
)

_RE_SINAIS = re.compile("|".join(_SINAIS), re.IGNORECASE)

_ultima_oferta: Dict[int, float] = {}


def parece_pedido_de_ajuda(texto: str) -> bool:
    """True se a mensagem soa como alguém com problema. Sem LLM, sem custo."""
    limpo = (texto or "").strip()
    if len(limpo) < 8:
        return False
    return bool(_RE_SINAIS.search(limpo))


# ═════════════════════════════════════════════════════════════════
# ACESSO AO BOT
# ═════════════════════════════════════════════════════════════════

def _bot():
    import discord_bot
    return discord_bot


def _config(chave: str, padrao=None):
    try:
        return (getattr(_bot(), "_config", {}) or {}).get(chave, padrao)
    except Exception:
        return padrao


def canal_suporte() -> int:
    return int(_config("canal_suporte_id", 0) or 0)


# ═════════════════════════════════════════════════════════════════
# AS REGRAS
# ═════════════════════════════════════════════════════════════════

_cache_regras: Optional[str] = None
_regras_mtime: float = 0.0


def regras() -> str:
    """
    As regras do servidor, do arquivo que o Vitor escreve.

    Recarrega quando o arquivo muda, comparando a data de modificação. Assim ele
    edita o markdown e a próxima resposta dela já sai com a regra nova, sem
    reiniciar nada.
    """
    global _cache_regras, _regras_mtime
    try:
        mtime = os.path.getmtime(ARQUIVO_REGRAS)
    except OSError:
        return ""
    if _cache_regras is not None and mtime == _regras_mtime:
        return _cache_regras
    try:
        with open(ARQUIVO_REGRAS, "r", encoding="utf-8") as f:
            bruto = f.read().strip()
        # Truncar em SILÊNCIO era um bug de verdade: o teto anterior era 4000 e o
        # livro de regras passou disso, então a última seção — que é justamente a
        # de notas internas, a que mais ajuda no diagnóstico — desaparecia do
        # prompt sem nenhum sinal. Regra que ela não vê é regra que não existe.
        if len(bruto) > MAX_REGRAS:
            _log(f"AVISO: as regras têm {len(bruto)} chars e o teto é "
                 f"{MAX_REGRAS}; cortei o fim. Enxugue o arquivo ou aumente "
                 f"EMILY_SUPORTE_MAX_REGRAS.")
            bruto = bruto[:MAX_REGRAS]
        _cache_regras = bruto
        _regras_mtime = mtime
        _log(f"regras carregadas ({len(_cache_regras)} chars, "
             f"~{len(_cache_regras) // 4} tokens)")
    except OSError as e:
        _log(f"não consegui ler as regras: {e}")
        return ""
    return _cache_regras


def tem_regras() -> bool:
    return bool(regras())


# ═════════════════════════════════════════════════════════════════
# A PERSONA DE ATENDIMENTO
# ═════════════════════════════════════════════════════════════════

_PERSONA = """
Você é a Emily, e agora está no canal de SUPORTE do servidor. Aqui você não é a
Emily zoeira do chat: é a Emily que resolve. Continua sendo você — informal, sem
frescura — mas com paciência e foco em desencalhar a pessoa.

COMO ATENDER
Vá direto ao que resolve. Uma ou duas frases por mensagem, no máximo três se
precisar listar passos. Nada de "olá! como posso ajudar?" — a pessoa já disse o
problema, responda o problema.
Se faltar informação pra resolver, pergunte UMA coisa só, a mais importante.
Não peça print de tudo, não peça log inteiro, não mande a pessoa reinstalar antes
de esgotar o simples.

USE AS REGRAS
As regras do servidor estão no seu prompt. Use pra julgar o que é permitido e
responder dúvida sobre regra.

QUANDO CHAMAR O VITOR
Quando for coisa que só ele faz: mexer em configuração do servidor, liberar
alguém banido, comprar coisa. Diga que vai chamar ele em vez de prometer que
resolve.

O QUE NÃO FAZER
Não invente causa. Não prometa prazo. Não peça pra pessoa mandar arquivo. Não
fale como bot de atendimento — sem "prezado", sem "estarei encaminhando", sem
numerar tudo.
""".strip()


def responder(texto: str, quem: str, historico: str = "") -> str:
    """
    Uma resposta de atendimento. String vazia = não vale responder.

    Roda em thread, então pode demorar: quem chama não está no loop do bot.
    """
    if not ATIVO:
        return ""
    try:
        import llm
        import modelo
    except Exception as e:
        _log(f"llm indisponível: {e}")
        return ""

    system = _PERSONA
    regras_texto = regras()
    if regras_texto:
        system += ("\n\nREGRAS DO SERVIDOR (escritas pelo Vitor; use pra julgar "
                   "o que é permitido e pra responder dúvida sobre regra)\n"
                   + regras_texto)
    else:
        system += ("\n\nAVISO: o Vitor ainda não escreveu as regras do servidor. "
                   "Se alguém perguntar sobre regra, diga que vai confirmar com "
                   "ele em vez de inventar.")

    try:
        import perfil_discord
        estilo = perfil_discord.bloco_de_estilo()
        if estilo:
            system += "\n\n" + estilo
    except Exception:
        pass

    prompt = f"{quem} escreveu no suporte: {texto}"
    if historico:
        prompt = f"Conversa até agora:\n{historico}\n\n{prompt}"

    try:
        bruto = llm.chamar_texto(prompt, rota_nome=modelo.ROTA_CONVERSA,
                                 system=system, max_tokens=400)
    except Exception as e:
        _log(f"não consegui responder: {type(e).__name__}: {e}")
        return ""
    return (bruto or "").strip()[:1800]


# ═════════════════════════════════════════════════════════════════
# ATENDIMENTO NO CANAL
# ═════════════════════════════════════════════════════════════════

def eh_canal_de_suporte(canal_id: int) -> bool:
    alvo = canal_suporte()
    if not alvo:
        return False
    if int(canal_id) == alvo:
        return True
    # Thread aberta dentro do canal de suporte também é suporte: sem isso, o
    # atendimento morreria assim que ela abrisse a thread pra organizar.
    try:
        b = _bot()
        canal = b._client.get_channel(int(canal_id))
        pai = getattr(canal, "parent_id", None)
        return pai is not None and int(pai) == alvo
    except Exception:
        return False


def atender(message, nome: str, historico: str = "") -> None:
    """
    Atende uma mensagem no canal de suporte. Chamado em thread pelo on_message.

    A thread do Discord é aberta na PRIMEIRA mensagem do atendimento e a resposta
    vai dentro dela. Isso mantém o canal legível quando três pessoas pedem ajuda
    ao mesmo tempo — sem thread, as três conversas se misturam e ninguém entende
    qual resposta é de quem.
    """
    if not ATIVO:
        return
    try:
        resposta = responder(getattr(message, "content", ""), nome, historico)
        if not resposta:
            return
        _enviar(message, resposta)
    except Exception as e:
        _log(f"atendimento falhou: {type(e).__name__}: {e}")


def _enviar(message, texto: str) -> None:
    import asyncio
    try:
        b = _bot()
        loop = b._loop
        if loop is None:
            return
    except Exception:
        return

    async def _mandar():
        try:
            canal = message.channel
            ja_na_thread = getattr(canal, "parent_id", None) is not None
            if USAR_THREAD and not ja_na_thread:
                try:
                    titulo = (getattr(message, "content", "") or "ajuda")
                    thread = await message.create_thread(
                        name=titulo.strip()[:60] or "ajuda",
                        auto_archive_duration=1440)
                    await thread.send(texto)
                    return
                except Exception as e:
                    # Sem permissão de criar thread, ou canal que não aceita:
                    # responde no canal mesmo. Perder o atendimento porque a
                    # organização falhou seria trocar o essencial pelo enfeite.
                    _log(f"não deu pra abrir thread ({e}); respondo no canal")
            await message.reply(texto)
        except Exception as e:
            _log(f"não consegui enviar: {e}")

    asyncio.run_coroutine_threadsafe(_mandar(), loop)


def talvez_oferecer_ajuda(message, nome: str) -> bool:
    """
    Fora do canal de suporte: percebe problema e oferece ajuda uma vez.

    Devolve True se ofereceu. O cooldown é por PESSOA e longo: alguém reclamando
    do jogo três vezes num desabafo não deve receber três ofertas de suporte.
    """
    if not ATIVO:
        return False
    texto = getattr(message, "content", "") or ""
    if not parece_pedido_de_ajuda(texto):
        return False

    autor_id = getattr(getattr(message, "author", None), "id", 0)
    agora = time.time()
    if agora - _ultima_oferta.get(autor_id, 0) < COOLDOWN_OFERTA:
        return False
    _ultima_oferta[autor_id] = agora

    threading.Thread(target=_oferecer, args=(message, nome, texto),
                     daemon=True).start()
    return True


def _oferecer(message, nome: str, texto: str) -> None:
    resposta = responder(texto, nome)
    if not resposta:
        return
    alvo = canal_suporte()
    if alvo and int(getattr(message.channel, "id", 0)) != alvo:
        resposta += f"\n-# se quiser, continua em <#{alvo}>"
    _enviar_simples(message, resposta)


def _enviar_simples(message, texto: str) -> None:
    """Responde no canal, sem abrir thread — aqui ela é convidada, não dona."""
    import asyncio
    try:
        loop = _bot()._loop
        if loop is None:
            return
    except Exception:
        return

    async def _mandar():
        try:
            await message.reply(texto[:1900])
        except Exception as e:
            _log(f"não consegui enviar: {e}")

    asyncio.run_coroutine_threadsafe(_mandar(), loop)


# ═════════════════════════════════════════════════════════════════
# MODELO DE REGRAS
# ═════════════════════════════════════════════════════════════════

_MODELO_REGRAS = """# Regras do servidor

<!-- Escreva as regras aqui, do jeito que você fala. A Emily lê este arquivo e
usa pra atender no suporte e pra julgar o que é permitido. Editar aqui já vale
na próxima resposta dela — não precisa reiniciar nada. -->

## No Discord

- (exemplo) sem divulgação de outro servidor sem falar com o Vitor antes
- (exemplo) conteúdo +18 não rola em canal nenhum
- (exemplo) zoeira é liberada, ataque pessoal de verdade não

## No Minecraft

- (exemplo) sem grief na base de ninguém
- (exemplo) sem roubar de baú alheio
- (exemplo) pedir op, item ou teleporte é só com o Vitor, pelo Discord

## Como entrar no servidor

- (exemplo) baixe o launcher no canal tal, abra e espere atualizar até o fim
- (exemplo) escolha o modpack tal
"""


def criar_modelo_de_regras() -> str:
    """Cria o arquivo de regras em branco, se ainda não existe."""
    if os.path.exists(ARQUIVO_REGRAS):
        return f"O arquivo de regras já existe em {ARQUIVO_REGRAS}"
    try:
        with open(ARQUIVO_REGRAS, "w", encoding="utf-8") as f:
            f.write(_MODELO_REGRAS)
    except OSError as e:
        return f"Não consegui criar o arquivo: {e}"
    return (f"Criei {ARQUIVO_REGRAS} com um modelo. Edite lá que eu já leio na "
            f"próxima vez.")


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  SUPORTE DA EMILY")
    print("=" * 66)
    print(f"  ativo:            {ATIVO}")
    print(f"  canal de suporte: {canal_suporte() or '(não configurado)'}")
    print(f"  abre thread:      {USAR_THREAD}")
    print(f"  arquivo de regras:{ARQUIVO_REGRAS}")
    print(f"  regras escritas:  {tem_regras()} "
          f"({len(regras())} chars)")

    print("\n-- detecção de pedido de ajuda (sem LLM) --")
    casos = [
        "nao consigo entrar no server",
        "deu erro no launcher",
        "crashou quando entrei",
        "alguem pode me ajudar",
        "como eu instalo o modpack",
        "me kickou do server",
        "faltando mod aqui",
        "bom dia galera",
        "kkkkk que engraçado",
        "vou jogar mais tarde",
        "o boss desse mod é dificil",
    ]
    for c in casos:
        marca = "AJUDA " if parece_pedido_de_ajuda(c) else "normal"
        print(f"  {marca} {c}")

    print("\n-- tamanho do prompt de atendimento --")
    system = _PERSONA + "\n" + regras()
    print(f"  {len(system)} chars (~{len(system) // 4} tokens por atendimento)")

    print("\n" + "=" * 66)
    print("Nada foi enviado: só leitura.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())
