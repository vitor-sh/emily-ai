"""
_teste_roteamento_admin.py — pedidos de administração SEM menção.

Antes, só menção ou reply abriam o caminho com ferramenta no servidor. Um
"cria um canal tal" solto no chat caía na participação espontânea (sem
ferramenta nenhuma) e a Emily respondia "tô fazendo!" sem fazer nada — mentira
por arquitetura. Este teste cobre o roteamento novo:

  1. quem tem acesso de admin e manda um pedido SEM marcar ela -> roteia pro
     laço de ferramentas (mesma fila das menções);
  2. quem NÃO tem acesso -> segue na conversa como sempre (sem virar recusa
     de permissão pra quem nem falou com ela);
  3. conversa comum -> nunca roteia;
  4. o bloco novo precisa existir DENTRO do on_message, entre o ramo de
     menção e a participação espontânea.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import inspect
import sys
from types import SimpleNamespace

import discord_bot

falhas = []


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    resultado = "OK" if condicao else "FALHOU"
    print(f"[{resultado}] {nome}" + (f" -> {detalhe}" if not condicao else ""))
    if not condicao:
        falhas.append(nome)


ID_DONO = 111
ID_COMUM = 222
ID_STAFF = 333

CONFIG_TESTE = {
    "usuario_id": ID_DONO,
    "cargos_admin": ["staff"],
    "coadmins_id": [],
    "admin_por_permissao_discord": True,
    "permitir_admin": True,
}

_cargo_staff = SimpleNamespace(id=777, name="staff")


def membro_fake(uid: int, cargo_staff: bool = False, admin_discord: bool = False):
    perms = None
    if admin_discord:
        perms = SimpleNamespace(administrator=True, manage_guild=False)
    return SimpleNamespace(
        id=uid,
        roles=[_cargo_staff] if cargo_staff else [],
        guild_permissions=perms,
    )


def mensagem_fake(autor, guild=SimpleNamespace(id=1)):
    return SimpleNamespace(author=autor, guild=guild)


_config_original = dict(discord_bot._config)
try:
    discord_bot._config = CONFIG_TESTE
    roteia = discord_bot._deve_rotear_admin_sem_mencao

    print("== quem tem acesso, sem menção ==")
    checar("dono: 'cria um canal de memes' roteia",
           roteia("cria um canal de memes", mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'apaga o canal de spam' roteia",
           roteia("apaga o canal de spam", mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'da o cargo de mod pro bisqui' roteia",
           roteia("da o cargo de mod pro bisqui",
                  mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'o server tá on' roteia (pergunta vira ferramenta)",
           roteia("o server tá on", mensagem_fake(membro_fake(ID_DONO))))
    checar("cargo autorizado: 'limpa o chat do canal de spam' roteia",
           roteia("limpa o chat do canal de spam",
                  mensagem_fake(membro_fake(ID_STAFF, cargo_staff=True))))
    checar("admin do Discord: 'cria uma categoria de voz' roteia",
           roteia("cria uma categoria de voz",
                  mensagem_fake(membro_fake(444, admin_discord=True))))

    print("\n== quem não tem acesso, mesmo pedido ==")
    checar("membro comum: 'cria um canal de memes' NÃO roteia",
           not roteia("cria um canal de memes",
                      mensagem_fake(membro_fake(ID_COMUM))))

    print("\n== conversa comum nunca roteia ==")
    checar("dono: 'bom dia galera' não roteia",
           not roteia("bom dia galera", mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'kkkk mano que isso' não roteia",
           not roteia("kkkk mano que isso",
                      mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'como funciona canal de voz no discord?' não roteia",
           not roteia("como funciona canal de voz no discord?",
                      mensagem_fake(membro_fake(ID_DONO))))
    checar("dono: 'vc acha que eu devia criar um canal novo?' não roteia",
           not roteia("vc acha que eu devia criar um canal novo?",
                      mensagem_fake(membro_fake(ID_DONO))))

    print("\n== casos de borda ==")
    checar("pergunta de capacidade roteia (resposta honesta, sem forçar ação)",
           roteia("vc pode banir pessoas?", mensagem_fake(membro_fake(ID_DONO))))
    checar("texto vazio não roteia",
           not roteia("", mensagem_fake(membro_fake(ID_DONO))))
    checar("direct não roteia (tem caminho próprio)",
           not roteia("cria um canal",
                      mensagem_fake(membro_fake(ID_DONO), guild=None)))

    discord_bot._config["permitir_admin"] = False
    checar("permitir_admin=False desliga o roteamento",
           not roteia("cria um canal de memes",
                      mensagem_fake(membro_fake(ID_DONO))))
    discord_bot._config["permitir_admin"] = True

    print("\n== o bloco novo vive no on_message, no lugar certo ==")
    fonte = inspect.getsource(discord_bot.on_message)
    pos_novo = fonte.find("_deve_rotear_admin_sem_mencao")
    pos_mencao = fonte.find("MENÇÃO DIRETA ou REPLY NA EMILY")
    pos_espontanea = fonte.find("PARTICIPAÇÃO ESPONTÂNEA")
    checar("on_message chama o roteamento novo", pos_novo > 0)
    checar("o roteamento vem DEPOIS do ramo de menção",
           pos_novo > pos_mencao > 0)
    checar("o roteamento vem ANTES da participação espontânea",
           pos_espontanea > pos_novo > 0)
finally:
    discord_bot._config = _config_original

print()
if falhas:
    print(f"FALHOU: {len(falhas)} teste(s): {falhas}")
    sys.exit(1)
print("Tudo certo.")
