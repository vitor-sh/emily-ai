"""Teste rápido das melhorias de resolução de membro no discord_admin.

Não conecta no Discord: usa objetos fake com os atributos que
_candidatos_membro/_ambiguos leem (display_name, name, global_name).
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import sys

import discord_admin


class MembroFake:
    def __init__(self, name, display_name=None, global_name=None):
        self.name = name
        self.display_name = display_name or name
        self.global_name = global_name


class GuildFake:
    def __init__(self, membros):
        self.members = membros
        self.name = "Servidor do Vitor"


ok = []
falhou = []


def check(descricao, condicao):
    (ok if condicao else falhou).append(descricao)


g = GuildFake([
    MembroFake("joao.silva", display_name="Jhow", global_name="João Silva"),
    MembroFake("maria", display_name="Maria"),
    MembroFake("maria_clara", display_name="Mah"),
    MembroFake("ze"),
])

# 1. nick do servidor que não bate com o username
c = discord_admin._candidatos_membro(g, "jhow")
check("acha pelo apelido do servidor ('Jhow')",
      c and c[0][1].name == "joao.silva")

# 2. nome global com acento
c = discord_admin._candidatos_membro(g, "joao silva")
check("acha pelo nome global acentuado",
      c and c[0][1].name == "joao.silva")

# 3. username mesmo com apelido diferente
c = discord_admin._candidatos_membro(g, "maria_clara")
check("acha pelo username com underline",
      c and c[0][1].name == "maria_clara")

# 4. ninguém
c = discord_admin._candidatos_membro(g, "fulano impossivel")
check("ninguém bate → lista vazia", not c)

# 5. ambiguidade real: dois matches NÃO exatos colados
g3 = GuildFake([MembroFake("maria_clara"), MembroFake("mariana")])
c = discord_admin._candidatos_membro(g3, "maria")
check("'maria' com dois aproximados é ambíguo", discord_admin._ambiguos(c))

# 5b. nome exato presente não é ambíguo — acerto exato ganha
c = discord_admin._candidatos_membro(g, "maria")
check("'maria' exato vence aproximados", not discord_admin._ambiguos(c))

# 7. _resolver_membro com único candidato
m = discord_admin._resolver_membro(g, "ze")
check("resolve 'ze' direto", m.name == "ze")

# 8. _resolver_membro ambíguo levanta erro pedindo confirmação
try:
    discord_admin._resolver_membro(g3, "maria")
    check("ambíguo deveria levantar ErroAdmin", False)
except discord_admin.ErroAdmin as e:
    check("ambíguo levanta ErroAdmin com 'pergunte'",
          "pergunte" in str(e).lower() or "NÃO escolha" in str(e))

# 9. inexistente levanta erro
try:
    discord_admin._resolver_membro(g, "fulano impossivel")
    check("inexistente deveria levantar ErroAdmin", False)
except discord_admin.ErroAdmin as e:
    check("inexistente levanta ErroAdmin explicando", "Não achei" in str(e))

# 10. limites novos
import inspect
fonte = inspect.getsource(discord_admin)
check("limpar_mensagens aceita até 5000", "5000" in fonte)
check("apagar_mensagem aceita até 1000", "min(int(quantidade or 1), 1000)"
      in fonte)
check("varredura profunda de histórico", "limite_busca" in fonte)
check("apagamento em lotes de 100", "delete_messages(lote)" in fonte)
check("limite de cargos por lote é 25",
      discord_admin.MAX_CARGOS_POR_LOTE == 25)

print(f"passaram {len(ok)}, falharam {len(falhou)}")
for f in falhou:
    print("FALHOU:", f)
sys.exit(1 if falhou else 0)
