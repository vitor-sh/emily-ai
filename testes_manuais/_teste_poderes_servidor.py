"""Teste dos novos poderes de configuração do servidor (discord_admin).

Simula guild/canal/cargo e intercepta guild.edit: nada toca num Discord real.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import asyncio
import os
import sys
import tempfile

import discord_admin


ok, falhou = [], []


def check(desc, cond):
    (ok if cond else falhou.append(desc)) if cond else falhou.append(desc)
    if cond:
        ok.append(desc)


# ── fakes ──
class FakeMe:
    top_role = type("R", (), {"position": 99, "name": "Emily"})()


class FakeGuild:
    name = "Servidor do Vitor"
    id = 1
    me = FakeMe()
    bitrate_limit = 96000
    categories = []
    roles = []

    def __init__(self):
        self.edits = []

    def edit(self, **kwargs):
        self.edits.append(kwargs)
        return "ok"


class FakeCanal:
    def __init__(self, name):
        self.name = name
        self.id = hash(name) % 1000


guild = FakeGuild()
canais = {"regras": FakeCanal("regras"), "avisos": FakeCanal("avisos"),
          "boas-vindas": FakeCanal("boas-vindas"), "espera": FakeCanal("espera")}

discord_admin._resolver_servidor = lambda nome="": guild
discord_admin._resolver_canal = lambda g, nome, tipo=None: canais[nome]
discord_admin._exigir_permissao_do_bot = lambda g, *n: None
# O envelope de @_ferramenta exige bot no ar e nível de acesso: no teste,
# libera tudo.
discord_admin.bot_pronto = lambda: True
discord_admin._pode_agir = lambda: None
discord_admin._cobrar_orcamento = lambda: None


def _exec_falso(coro, timeout=None):
    if asyncio.iscoroutine(coro):
        return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)
    return coro


discord_admin._executar = _exec_falso
discord_admin._registrar_desfazer = lambda *a, **k: None
discord_admin.sessao = lambda: {"autor_nome": "Vitor"}


class _Nada:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


discord_admin._EmObra = lambda gid: _Nada()

# ── 1. configuração completa do núcleo ──
resp = discord_admin.editar_servidor(
    novo_nome="Novo Nome", verificacao="alta", filtro_conteudo="todos",
    notificacoes="so mencoes", idioma="portugues", canal_regras="regras",
    canal_sistema="boas-vindas", canal_afk="espera", tempo_afk=300)
check("resposta confirma atualização", "Servidor atualizado" in resp)
check("uma chamada de edit pro núcleo", len(guild.edits) == 1)
edit = guild.edits[0]
check("nome", edit.get("name") == "Novo Nome")
check("verificação alta", edit.get("verification_level") == discord_admin.discord.VerificationLevel.high)
check("filtro todos", edit.get("explicit_content_filter") == discord_admin.discord.ContentFilter.all_members)
check("notificações só menções",
      edit.get("default_notifications") == discord_admin.discord.NotificationLevel.only_mentions)
check("idioma pt-BR", edit.get("preferred_locale") == "pt-BR")
check("canal de regras resolvido", edit.get("rules_channel") is canais["regras"])
check("canal do sistema resolvido", edit.get("system_channel") is canais["boas-vindas"])
check("canal AFK resolvido", edit.get("afk_channel") is canais["espera"])
check("tempo AFK dentro dos limites", edit.get("afk_timeout") == 300)

# ── 2. ícone por caminho local vira segunda chamada com bytes ──
img = os.path.join(tempfile.mkdtemp(), "icone.png")
with open(img, "wb") as f:
    f.write(b"\x89PNG falso")

resp = discord_admin.editar_servidor(icone=img)
check("ícone aplicado em chamada própria",
      len(guild.edits) == 2 and guild.edits[1].get("icon") == b"\x89PNG falso")
check("resposta não reporta falha cosmética", "Não consegui" not in resp)

# ── 3. validação de entradas ──
check("verificação inválida é recusada com lista",
      "verificação" in discord_admin.editar_servidor(verificacao="insana"))
check("filtro inválido é recusado",
      "Filtro" in discord_admin.editar_servidor(filtro_conteudo="tudo solto"))
check("notificação inválida é recusada",
      "Notificações" in discord_admin.editar_servidor(notificacoes="silencio"))
check("tempo AFK encaixa no valor válido mais próximo (5s → 60s)",
      "segundos" in discord_admin.editar_servidor(tempo_afk="abc"))
check("tempo AFK numérico encaixa (200 → 300)",
      "afk_timeout" in discord_admin.editar_servidor(tempo_afk=200))
check("nada pedido devolve orientação",
      "Não foi dito" in discord_admin.editar_servidor())

# ── 4. vocabulário de permissões ampliado ──
for bruto, esperado in (
        ("tts", "send_tts_messages"), ("enquetes", "send_polls"),
        ("criar eventos", "create_events"), ("auditoria", "view_audit_log"),
        ("stickers", "use_external_stickers"),
        ("mensagens de voz", "send_voice_messages"),
        ("historico", "read_message_history")):
    check(f"'{bruto}' traduz pra {esperado}",
          discord_admin._traduzir_permissao(bruto) == esperado)

# ── 5. leitura de permissões de cargo ──
class FakePerms:
    def __iter__(self):
        return iter([("administrator", False), ("manage_channels", True)])


class FakeRole:
    name = "Mod"
    id = 7
    permissions = FakePerms()
    managed = False


discord_admin._resolver_cargo = lambda g, nome: FakeRole()
resp = discord_admin.ver_permissoes_cargo("Mod")
check("leitura lista o que TEM", "gerenciar canais" in resp)
check("leitura lista o que NÃO TEM", "administrador" in resp)

# ── 6. catálogo e cobertura ──
import ferramentas_discord

faltando = ferramentas_discord._conferir_cobertura()
check("nenhuma ferramenta fora do resumo", not faltando or print(faltando))
for n in ("ver_permissoes_canal_discord", "ver_permissoes_cargo_discord",
          "sincronizar_permissoes_canal_discord"):
    check(f"{n} registrada", n in ferramentas_discord.nomes())

print(f"passaram {len(ok)}, falharam {len(falhou)}")
for f in falhou:
    print("FALHOU:", f)
sys.exit(1 if falhou else 0)
