"""
publicar_discord.py — o livro de regras virando painel bonito no Discord.

O PROBLEMA DO TEXTO SECO
────────────────────────
`enviar_mensagem_discord` manda texto puro. Pra conversa é o certo. Pra um canal
de regras é péssimo: vira um paredão cinza que ninguém lê, sem hierarquia visual,
sem cor, e que a cada edição precisa ser reescrito inteiro à mão.

Embed resolve isso: título, cor na lateral, campos separados, rodapé. É o formato
que o Discord fez pra conteúdo fixo.

O ARQUIVO É A FONTE, O CANAL É A VITRINE
────────────────────────────────────────
O conteúdo vive em `regras_servidor.md` e não aqui. O Vitor edita o markdown, pede
pra ela publicar, e o canal reflete o arquivo.

Isso importa porque o mesmo texto tem dois consumidores: a Emily (que lê pra
atender no suporte e julgar o que é permitido) e a galera (que lê no canal).
Manter duas cópias garantiria que uma ficaria velha — e a que ficaria velha seria
justamente a que ela usa pra decidir.

A DECISÃO MAIS IMPORTANTE: EDITAR, NÃO REMANDAR
───────────────────────────────────────────────
Publicar de novo NÃO duplica. Os ids das mensagens ficam guardados, e republicar
edita as que já existem.

Sem isso, cada correção de vírgula nas regras deixaria uma cópia velha no canal, e
em pouco tempo teria três versões diferentes coexistindo — com a galera lendo a
primeira, que é a que fica no topo. O canal de regras é o único lugar do servidor
onde conteúdo desatualizado causa briga.

Efeito colateral bom: editar não notifica ninguém. Corrigir uma regra não avisa
sessenta pessoas.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
from emily_paths import arquivo_dados

ARQUIVO_ESTADO = str(arquivo_dados("publicacoes.json"))

# Limites do Discord. Estourar qualquer um faz a API recusar a mensagem inteira,
# então tudo é cortado antes de sair daqui.
MAX_TITULO = 250
MAX_DESCRICAO = 4000
MAX_CAMPOS = 25
MAX_NOME_CAMPO = 250
MAX_VALOR_CAMPO = 1000

# Cor por canal. Regras em roxo (a cor dela), guia em azul.
_CORES = {
    "regras": 0xB57EDC,
    "guia": 0x5DADE2,
    "outro": 0x9B59B6,
}


def _log(msg: str) -> None:
    print(f"[PUBLICAR] {msg}")


# ═════════════════════════════════════════════════════════════════
# LEITURA DO MARKDOWN
#
# Parser pequeno e tolerante. Não é markdown de verdade: é o subconjunto que o
# arquivo de regras usa, e nada mais. Um parser completo aqui seria resolver um
# problema que não temos.
# ═════════════════════════════════════════════════════════════════

_RE_CANAL = re.compile(r"<!--\s*canal:\s*(\w+)\s*-->", re.IGNORECASE)


def _tirar_comentarios(texto: str) -> str:
    """Remove comentário de HTML, menos as marcas de canal, que são instrução."""
    def guardar(m):
        return m.group(0) if _RE_CANAL.fullmatch(m.group(0).strip()) else ""
    return re.sub(r"<!--.*?-->", guardar, texto, flags=re.DOTALL)


def secoes(caminho: Optional[str] = None) -> List[dict]:
    """
    Lê o arquivo e devolve as seções, cada uma virando um embed.

    Estrutura: `##` abre seção, texto solto é descrição, `-` é lista, `###` é
    campo. A marca de canal vale pra seção seguinte.
    """
    if caminho is None:
        import suporte
        caminho = suporte.ARQUIVO_REGRAS
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            bruto = f.read()
    except OSError as e:
        _log(f"não consegui ler {caminho}: {e}")
        return []

    bruto = _tirar_comentarios(bruto)

    saida: List[dict] = []
    canal_atual = "outro"
    secao: Optional[dict] = None
    campo: Optional[dict] = None

    def fechar_campo():
        nonlocal campo
        if secao is not None and campo is not None:
            valor = "\n".join(campo["linhas"]).strip()
            if valor:
                secao["campos"].append((campo["nome"], valor))
        campo = None

    def fechar_secao():
        nonlocal secao
        fechar_campo()
        if secao is not None and (secao["descricao"].strip() or secao["campos"]):
            saida.append(secao)
        secao = None

    for linha in bruto.splitlines():
        marca = _RE_CANAL.search(linha)
        if marca:
            canal_atual = marca.group(1).lower()
            continue

        crua = linha.rstrip()
        limpa = crua.strip()

        if limpa.startswith("## "):
            fechar_secao()
            secao = {"titulo": limpa[3:].strip(), "descricao": "",
                     "campos": [], "canal": canal_atual}
            continue

        if limpa.startswith("### "):
            if secao is None:
                continue
            fechar_campo()
            campo = {"nome": limpa[4:].strip(), "linhas": []}
            continue

        if limpa.startswith("# "):
            continue   # o título do arquivo não vira embed

        if secao is None:
            continue

        if campo is not None:
            campo["linhas"].append(crua)
        else:
            secao["descricao"] += crua + "\n"

    fechar_secao()
    return saida


def secoes_do_canal(nome_canal: str, caminho: Optional[str] = None) -> List[dict]:
    return [s for s in secoes(caminho) if s.get("canal") == nome_canal]


# ═════════════════════════════════════════════════════════════════
# MONTAGEM DO EMBED
# ═════════════════════════════════════════════════════════════════

def _enfeitar(texto: str) -> str:
    """
    Ajustes visuais que o markdown do Discord entende.

    Bullet com `-` fica apertado no Discord; `•` respira. E linha vazia dupla
    dentro de embed vira espaço morto, então colapsa.
    """
    linhas = []
    for linha in texto.splitlines():
        limpa = linha.strip()
        if limpa.startswith("- "):
            linhas.append("• " + limpa[2:])
        else:
            linhas.append(limpa)
    junto = "\n".join(linhas)
    return re.sub(r"\n{3,}", "\n\n", junto).strip()


def montar(secao: dict, indice: int = 0, total: int = 0) -> dict:
    """Uma seção -> um dicionário de embed pronto pro discord.py."""
    cor = _CORES.get(secao.get("canal", "outro"), _CORES["outro"])
    embed = {
        "title": secao["titulo"][:MAX_TITULO],
        "description": _enfeitar(secao["descricao"])[:MAX_DESCRICAO],
        "color": cor,
        "fields": [],
    }
    for nome, valor in secao["campos"][:MAX_CAMPOS]:
        embed["fields"].append({
            "name": nome[:MAX_NOME_CAMPO],
            "value": _enfeitar(valor)[:MAX_VALOR_CAMPO],
            # Campo curto lado a lado fica bonito, mas quebra a leitura de regra.
            # Regra é pra ler em coluna, uma coisa por vez.
            "inline": False,
        })
    if total:
        embed["footer"] = {"text": f"{indice} de {total}"}
    return embed


# ═════════════════════════════════════════════════════════════════
# ESTADO DAS PUBLICAÇÕES
# ═════════════════════════════════════════════════════════════════

def _carregar() -> dict:
    if not os.path.exists(ARQUIVO_ESTADO):
        return {}
    try:
        with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _salvar(dados: dict) -> None:
    try:
        os.makedirs(os.path.dirname(ARQUIVO_ESTADO), exist_ok=True)
        tmp = ARQUIVO_ESTADO + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ARQUIVO_ESTADO)
    except OSError as e:
        _log(f"não consegui gravar o estado: {e}")


# ═════════════════════════════════════════════════════════════════
# PUBLICAR
# ═════════════════════════════════════════════════════════════════

def _bot():
    import discord_bot
    return discord_bot


def publicar(chave: str, canal_id: int, embeds: List[dict],
             timeout: float = 90.0) -> str:
    """
    Põe os embeds no canal, editando o que já estava lá.

    Síncrona: é chamada de dentro de uma ferramenta, e o modelo precisa do
    resultado pra contar o que aconteceu. O trabalho assíncrono acontece no loop
    do bot e esta função espera.
    """
    import asyncio
    import discord

    b = _bot()
    if not getattr(b, "_pronto", False) or getattr(b, "_loop", None) is None:
        return "O bot do Discord não está conectado, então não dá pra publicar."
    if not embeds:
        return "Não tinha nada pra publicar (o arquivo de regras está vazio?)."

    estado = _carregar()
    anterior = estado.get(chave, {})
    ids_antigos: List[int] = []
    if int(anterior.get("canal_id", 0) or 0) == int(canal_id):
        ids_antigos = [int(i) for i in anterior.get("mensagens", [])]

    async def _trabalhar() -> Tuple[int, int, int, List[int]]:
        canal = b._client.get_channel(int(canal_id))
        if canal is None:
            raise RuntimeError("não achei esse canal")

        editadas = criadas = apagadas = 0
        ids_novos: List[int] = []

        for i, dados in enumerate(embeds):
            embed = discord.Embed.from_dict(dados)
            if i < len(ids_antigos):
                try:
                    msg = await canal.fetch_message(ids_antigos[i])
                    await msg.edit(content=None, embed=embed)
                    ids_novos.append(msg.id)
                    editadas += 1
                    continue
                except Exception:
                    # Mensagem apagada à mão: cai pro caminho de criar. Não é erro.
                    pass
            msg = await canal.send(embed=embed)
            ids_novos.append(msg.id)
            criadas += 1

        # Sobrou mensagem de uma publicação maior: apaga o excedente, senão o
        # canal fica com seção que não existe mais no arquivo.
        for velho in ids_antigos[len(embeds):]:
            try:
                msg = await canal.fetch_message(velho)
                await msg.delete()
                apagadas += 1
            except Exception:
                pass

        return editadas, criadas, apagadas, ids_novos

    futuro = asyncio.run_coroutine_threadsafe(_trabalhar(), b._loop)
    try:
        editadas, criadas, apagadas, ids_novos = futuro.result(timeout=timeout)
    except Exception as e:
        return f"Não consegui publicar: {type(e).__name__}: {e}"

    estado[chave] = {
        "canal_id": int(canal_id),
        "mensagens": ids_novos,
        "quando": time.strftime("%d/%m/%Y %H:%M"),
    }
    _salvar(estado)

    partes = []
    if criadas:
        partes.append(f"{criadas} nova(s)")
    if editadas:
        partes.append(f"{editadas} atualizada(s)")
    if apagadas:
        partes.append(f"{apagadas} removida(s)")
    return (f"Publiquei em <#{canal_id}>: " + ", ".join(partes) + ". "
            f"Comente curto que ficou pronto.")


def resolver_canal(guild, nome_ou_id: str, criar: bool = False,
                   timeout: float = 45.0) -> Optional[int]:
    """
    Acha o canal por id, menção ou nome. Cria se pedirem e não existir.

    Aceita as três formas porque o modelo repassa o que a pessoa escreveu, e
    pessoa escreve "#regras", "regras" ou cola o id.
    """
    import asyncio
    import discord

    alvo = (nome_ou_id or "").strip()
    if not alvo:
        return None

    so_digitos = re.sub(r"\D", "", alvo)
    if so_digitos and len(so_digitos) >= 15:
        return int(so_digitos)

    limpo = alvo.lstrip("#").strip().lower()
    for canal in getattr(guild, "text_channels", []):
        if canal.name.lower() == limpo:
            return canal.id
    for canal in getattr(guild, "text_channels", []):
        if limpo in canal.name.lower():
            return canal.id

    if not criar:
        return None

    b = _bot()

    async def _criar():
        return await guild.create_text_channel(
            name=limpo[:90],
            topic="Canal mantido pela Emily a partir do arquivo de regras",
            reason="publicação de regras pela Emily")

    futuro = asyncio.run_coroutine_threadsafe(_criar(), b._loop)
    try:
        canal = futuro.result(timeout=timeout)
        _log(f"criei o canal #{canal.name}")
        return canal.id
    except Exception as e:
        _log(f"não consegui criar o canal: {e}")
        return None


def publicar_livro(servidor: str = "", canal_regras: str = "",
                   canal_guia: str = "", criar_canais: bool = False) -> str:
    """
    Publica o livro inteiro: guia num canal, regras no outro.

    Os dois canais são separados porque servem momentos diferentes. O guia é lido
    uma vez, por quem chegou. As regras são consultadas quando alguém pisa na
    bola. Num canal só, o guia enterra as regras — ou o contrário.
    """
    try:
        import discord_admin
        guild = discord_admin._resolver_servidor(servidor)
    except Exception as e:
        return f"Não consegui achar o servidor: {e}"

    todas = secoes()
    if not todas:
        import suporte
        return (f"O arquivo {suporte.ARQUIVO_REGRAS} está vazio ou não tem "
                f"seção nenhuma com '##'. Escreva o conteúdo antes de publicar.")

    relatos: List[str] = []
    for nome_canal, pedido, padrao in (
        ("guia", canal_guia, "comece-aqui"),
        ("regras", canal_regras, "regras"),
    ):
        do_canal = [s for s in todas if s.get("canal") == nome_canal]
        if not do_canal:
            continue

        canal_id = resolver_canal(guild, pedido or padrao, criar=criar_canais)
        if not canal_id:
            relatos.append(
                f"não achei o canal de {nome_canal} (procurei por "
                f"'{pedido or padrao}'). Diga qual é, ou peça pra eu criar.")
            continue

        total = len(do_canal)
        embeds = [montar(s, i + 1, total) for i, s in enumerate(do_canal)]
        relatos.append(f"{nome_canal}: " + publicar(nome_canal, canal_id, embeds))

    if not relatos:
        return ("O arquivo não tem seção marcada com '<!-- canal: regras -->' "
                "nem '<!-- canal: guia -->', então não soube onde publicar.")
    return "\n".join(relatos)


def enviar_embed(titulo: str, texto: str, canal: str = "", servidor: str = "",
                 cor: str = "", rodape: str = "") -> str:
    """Um embed solto, pra ela montar aviso bonito de qualquer coisa."""
    import asyncio
    import discord

    if not titulo.strip() and not texto.strip():
        return "Preciso de um título ou de um texto pra montar o embed."

    try:
        import discord_admin
        guild = discord_admin._resolver_servidor(servidor)
    except Exception as e:
        return f"Não consegui achar o servidor: {e}"

    canal_id = resolver_canal(guild, canal) if canal else 0
    if not canal_id:
        try:
            sessao = __import__("discord_admin").sessao()
            canal_id = int(sessao.get("canal_id") or 0)
        except Exception:
            canal_id = 0
    if not canal_id:
        return "Não soube em qual canal mandar. Diga o canal."

    valor_cor = _CORES["outro"]
    if cor:
        try:
            valor_cor = int(cor.lstrip("#"), 16)
        except ValueError:
            pass

    dados = {"title": titulo[:MAX_TITULO],
             "description": _enfeitar(texto)[:MAX_DESCRICAO],
             "color": valor_cor}
    if rodape:
        dados["footer"] = {"text": rodape[:200]}

    b = _bot()
    if not getattr(b, "_pronto", False) or getattr(b, "_loop", None) is None:
        return "O bot do Discord não está conectado."

    async def _mandar():
        alvo = b._client.get_channel(int(canal_id))
        if alvo is None:
            raise RuntimeError("canal não encontrado")
        await alvo.send(embed=discord.Embed.from_dict(dados))

    futuro = asyncio.run_coroutine_threadsafe(_mandar(), b._loop)
    try:
        futuro.result(timeout=45)
    except Exception as e:
        return f"Não consegui mandar: {type(e).__name__}: {e}"
    return f"Mandei o painel em <#{canal_id}>. Comente curto."


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  PUBLICAÇÃO DE REGRAS EM EMBED")
    print("=" * 66)

    todas = secoes()
    print(f"  seções lidas: {len(todas)}")
    por_canal: Dict[str, int] = {}
    for s in todas:
        por_canal[s["canal"]] = por_canal.get(s["canal"], 0) + 1
    for canal, quantas in sorted(por_canal.items()):
        print(f"    {canal}: {quantas} embed(s)")

    print("\n-- como cada embed vai ficar --")
    for s in todas:
        if s["canal"] == "nenhum":
            continue
        embed = montar(s, 1, len(todas))
        desc = embed["description"]
        print(f"\n  [{s['canal']}] {embed['title']}")
        print(f"    cor {hex(embed['color'])}, descrição {len(desc)} chars, "
              f"{len(embed['fields'])} campo(s)")
        primeira = desc.splitlines()[0] if desc else "(sem descrição)"
        print(f"    começa com: {primeira[:70]}")
        for campo in embed["fields"]:
            print(f"      • {campo['name']} ({len(campo['value'])} chars)")

    print("\n-- limites do Discord --")
    problemas = []
    for s in todas:
        embed = montar(s)
        if len(embed["description"]) >= MAX_DESCRICAO:
            problemas.append(f"{s['titulo']}: descrição no limite")
        if len(embed["fields"]) >= MAX_CAMPOS:
            problemas.append(f"{s['titulo']}: campos no limite")
        for campo in embed["fields"]:
            if len(campo["value"]) >= MAX_VALOR_CAMPO:
                problemas.append(f"{s['titulo']} / {campo['name']}: "
                                 f"valor no limite")
        total = (len(embed["title"]) + len(embed["description"])
                 + sum(len(c["name"]) + len(c["value"])
                       for c in embed["fields"]))
        if total > 5500:
            problemas.append(f"{s['titulo']}: {total} chars no embed "
                             f"(teto do Discord é 6000)")
    print("  " + ("\n  ".join(problemas) if problemas
                  else "tudo dentro dos limites"))

    print("\n-- seções internas (não publicadas) --")
    internas = [s["titulo"] for s in todas if s["canal"] == "nenhum"]
    print(f"  {internas or 'nenhuma'}")

    print("\n-- publicações já feitas --")
    estado = _carregar()
    if not estado:
        print("  (nenhuma ainda)")
    for chave, dados in estado.items():
        print(f"  {chave}: canal {dados.get('canal_id')}, "
              f"{len(dados.get('mensagens', []))} mensagens, "
              f"em {dados.get('quando')}")

    print("\n" + "=" * 66)
    print("Nada foi publicado: o diagnóstico só lê.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())
