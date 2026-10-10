"""Teste do conserto da hierarquia de cargos (cache velho da Emily).

Cenário do bug: o Vitor dá admin na Emily pela interface, o cache do
discord.py não atualiza, guild.me.top_role vira @everyone (posição 0) e a
Emily recusa atribuir QUALQUER cargo "por estar acima dela". O conserto
confirma com dado fresco da API antes de recusar.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import asyncio
import sys

import discord

import discord_admin


ok, falhou = [], []


def check(desc, cond):
    if cond:
        ok.append(desc)
    else:
        falhou.append(desc)


def _roda(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


discord_admin._executar = lambda coro, timeout=None: _roda(coro)


class Papel:
    def __init__(self, nome, posicao, pid=0):
        self.name = nome
        self.id = pid or abs(hash(nome)) % 10**9
        self.position = posicao
        self.managed = False


class Membro:
    def __init__(self, uid, roles, nome="Fulano"):
        self.id = uid
        self._roles = roles
        self.display_name = nome
        self.name = nome

    @property
    def roles(self):
        return self._roles

    @property
    def top_role(self):
        return max(self._roles, key=lambda r: r.position)


class ErroFake(discord.HTTPException):
    """HTTPException sem response real — só pra simular falha de API."""

    def __init__(self, texto="api caiu"):
        self.response = None
        self.status = 500
        self.code = 0
        self.text = texto
        self.__str__ = lambda: texto


class GuildFalsa:
    """
    cargos = o que fetch_roles() devolve (posição REAL da API).
    me/frescos = objetos cacheados (podem ter posição velha; só o ID vale).
    """

    def __init__(self):
        self.name = "Servidor Falso"
        self.default_role = Papel("@everyone", 0, pid=1)
        self.emily_real = Papel("emily", 10, pid=100)
        self.membro_real = Papel("Membro", 5, pid=200)
        self.emily_cache_velho = Papel("emily", 1, pid=100)  # posição velha!
        self.owner_id = 0
        self.me = Membro(1, [self.default_role])   # CACHE VELHO: só @everyone
        self.frescos = {1: Membro(1, [self.default_role, self.emily_real])}
        self.cargos = [self.default_role, self.emily_real, self.membro_real]
        self.chamadas_fetch = 0

    async def fetch_member(self, uid):
        self.chamadas_fetch += 1
        alvo = self.frescos.get(uid)
        if alvo is None:
            raise ErroFake("membro sumiu")
        return alvo

    async def fetch_roles(self):
        self.chamadas_fetch += 1
        return list(self.cargos)


guild = GuildFalsa()
membro_cargo = guild.membro_real

# ── 1. O BUG: cache velho diz "Membro acima de mim", dado fresco corrige ──
# Antes do conserto isso levantava ErroAdmin aqui embaixo.
try:
    discord_admin._exigir_hierarquia_cargo(guild, membro_cargo)
    check("cache velho NÃO recusa mais atribuição de cargo", True)
    check("o conserto consultou a API (fetch foi usado)",
          guild.chamadas_fetch >= 1)
except discord_admin.ErroAdmin as e:
    check("cache velho NÃO recusa mais atribuição de cargo", False)
    print("erro:", e)

# ── 2. O BURACO NOVO: cargo 'emily' cacheado com posição VELHA ──
# fetch_member sozinho NÃO resolve: Member.top_role lê a posição do objeto
# cacheado. Com a posição vindo de fetch_roles, a guarda enxerga a verdade.
guild5 = GuildFalsa()
guild5.me = Membro(1, [guild5.default_role, guild5.emily_cache_velho])
try:
    discord_admin._exigir_hierarquia_cargo(guild5, membro_cargo)
    check("posição velha no objeto cacheado não engana mais a guarda", True)
except discord_admin.ErroAdmin as e:
    check("posição velha no objeto cacheado não engana mais a guarda", False)
    print("erro:", e)

# ── 3. cache OK: passa direto, SEM chamada de API ──
guild2 = GuildFalsa()
guild2.me = Membro(1, [guild2.default_role, guild2.emily_real])
discord_admin._exigir_hierarquia_cargo(guild2, membro_cargo)
check("cache correto passa sem consultar API", guild2.chamadas_fetch == 0)

# ── 4. recusa REAL: dado fresco confirma que o cargo está acima ──
guild3 = GuildFalsa()
guild3.frescos = {1: Membro(1, [guild3.default_role, Papel("emily", 3, pid=100)])}
guild3.cargos = [guild3.default_role, Papel("emily", 3, pid=100),
                 Papel("Dono De Fato", 9, pid=300)]
cargo_alto = guild3.cargos[2]
try:
    discord_admin._exigir_hierarquia_cargo(guild3, cargo_alto)
    check("cargo acima de verdade é recusado", False)
except discord_admin.ErroAdmin as e:
    msg = str(e)
    check("cargo acima de verdade é recusado", "Arrasta" in msg)
    check("a recusa mostra as posições reais",
          "posição 9" in msg and "posição 3" in msg)

# ── 4b. EMPATE de posição (pos 1 vs pos 1, o caso do beta-tester) ──
# Antes recusava; agora tenta e deixa o Discord decidir.
guild_tie = GuildFalsa()
guild_tie.emily_real = Papel("emily", 5, pid=100)
guild_tie.cargos = [guild_tie.default_role, guild_tie.emily_real,
                    Papel("Membro", 5, pid=200)]
guild_tie.me = Membro(1, [guild_tie.default_role, guild_tie.emily_real])
try:
    discord_admin._exigir_hierarquia_cargo(guild_tie, guild_tie.cargos[2])
    check("empate de posição não é mais recusado às cegas", True)
except discord_admin.ErroAdmin as e:
    check("empate de posição não é mais recusado às cegas", False)
    print("erro:", e)

# ── 4c. cargo mais alto da Emily é o de INTEGRAÇÃO (managed) ──
guild_mg = GuildFalsa()
papel_bot = Papel("emily", 1, pid=100)
papel_bot.managed = True
guild_mg.emily_real = papel_bot
guild_mg.cargos = [guild_mg.default_role, papel_bot,
                   Papel("Membro", 6, pid=200)]
guild_mg.me = Membro(1, [guild_mg.default_role, papel_bot])
guild_mg.frescos = {1: guild_mg.me}
try:
    discord_admin._exigir_hierarquia_cargo(guild_mg, guild_mg.cargos[2])
    check("cargo acima com topo de integração é recusado", False)
except discord_admin.ErroAdmin as e:
    msg = str(e)
    check("cargo acima com topo de integração é recusado", True)
    check("a dica explica o cargo de integração e o arraste pro topo",
          "INTEGRAÇÃO" in msg and "TOPO" in msg)

# ── 5. API falhou: cai pro cache e recusa (comportamento seguro) ──
guild4 = GuildFalsa()


async def _quebra(uid):
    guild4.chamadas_fetch += 1
    raise ErroFake()

guild4.fetch_member = _quebra
try:
    discord_admin._exigir_hierarquia_cargo(guild4, membro_cargo)
    check("sem dado fresco, recusa conservadora (cache)", False)
except discord_admin.ErroAdmin:
    check("sem dado fresco, recusa conservadora (cache)", True)

# ── 5. travas que não dependem de hierarquia continuam ──
class Integrado:
    name = "Cargo de Bot"
    managed = True
    position = 99
    id = 42

try:
    discord_admin._exigir_hierarquia_cargo(guild, Integrado())
    check("cargo gerenciado por integração continua recusado", False)
except discord_admin.ErroAdmin:
    check("cargo gerenciado por integração continua recusado", True)

try:
    discord_admin._exigir_hierarquia_cargo(guild, guild.default_role)
    check("@everyone continua recusado", False)
except discord_admin.ErroAdmin:
    check("@everyone continua recusado", True)

# ── 6. hierarquia de MEMBRO com o mesmo conserto ──
membro_alvo = Membro(7, [Papel("membro comum", 1), membro_cargo])
try:
    discord_admin._exigir_hierarquia_membro(guild, membro_alvo)
    check("cache velho não impede mais dar cargo ao membro", True)
except discord_admin.ErroAdmin:
    check("cache velho não impede dar cargo ao membro", False)

guild6 = GuildFalsa()
guild6.frescos = {1: Membro(1, [guild6.default_role, Papel("emily", 2, pid=100)])}
donodefato = Membro(9, [Papel("grande", 50, pid=500)])
try:
    discord_admin._exigir_hierarquia_membro(guild6, donodefato)
    check("membro acima de verdade é recusado", False)
except discord_admin.ErroAdmin:
    check("membro acima de verdade é recusado", True)

dono = Membro(999, [Papel("x", 1)])
guild.owner_id = 999
try:
    discord_admin._exigir_hierarquia_membro(guild, dono)
    check("dono do servidor continua intocável", False)
except discord_admin.ErroAdmin:
    check("dono do servidor continua intocável", True)

# ── 8. ferramenta de diagnóstico ver_hierarquia ──
discord_admin.bot_pronto = lambda: True
discord_admin._pode_agir = lambda: None
discord_admin._cobrar_orcamento = lambda: None
discord_admin._resolver_servidor = lambda nome="": guild
discord_admin._resolver_cargo = lambda g, nome: g.cargos[2]

resp = discord_admin.ver_hierarquia("Membro")
check("ver_hierarquia mostra a posição real da emily",
      "posição 10" in resp and "emily" in resp)
check("ver_hierarquia dá veredito DÁ pro cargo abaixo", "DÁ" in resp)
check("ver_hierarquia lista a ordem completa", "Do topo pra baixo" in resp)

guild7 = GuildFalsa()
guild7.frescos = {1: Membro(1, [guild7.default_role,
                                Papel("emily", 3, pid=100)])}
guild7.cargos = [guild7.default_role, Papel("emily", 3, pid=100),
                 Papel("Dono De Fato", 9, pid=300)]
discord_admin._resolver_servidor = lambda nome="": guild7
resp = discord_admin.ver_hierarquia("Dono De Fato")
check("ver_hierarquia aponta NÃO dá pro cargo acima", "NÃO dá" in resp)

# Empate: ver_hierarquia explica que ela vai tentar mesmo assim
guild_tie2 = GuildFalsa()
guild_tie2.emily_real = Papel("emily", 5, pid=100)
guild_tie2.cargos = [guild_tie2.default_role, guild_tie2.emily_real,
                     Papel("Membro", 5, pid=200)]
discord_admin._resolver_servidor = lambda nome="": guild_tie2
resp = discord_admin.ver_hierarquia("Membro")
check("ver_hierarquia explica o empate", "EMPATADO" in resp)

# Cargo de integração como topo: ver_hierarquia dá o alerta certo
guild_mg2 = GuildFalsa()
papel_bot2 = Papel("emily", 1, pid=100)
papel_bot2.managed = True
guild_mg2.cargos = [guild_mg2.default_role, papel_bot2,
                    Papel("Membro", 6, pid=200)]
guild_mg2.me = Membro(1, [guild_mg2.default_role, papel_bot2])
guild_mg2.frescos = {1: guild_mg2.me}
discord_admin._resolver_servidor = lambda nome="": guild_mg2
resp = discord_admin.ver_hierarquia("Membro")
check("ver_hierarquia alerta sobre o cargo de integração",
      "ATENÇÃO" in resp and "INTEGRAÇÃO" in resp)

print(f"passaram {len(ok)}, falharam {len(falhou)}")
for f in falhou:
    print("FALHOU:", f)
sys.exit(1 if falhou else 0)
