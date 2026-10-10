"""Teste funcional dos métodos de memória de pessoas (interface_web.Api).

Não toca no memoria_discord.json real: ARQUIVO do perfil_discord é
redirecionado pra um temporário. Não abre janela nem servidor: a Api é
instanciada sem __init__ (só testamos os métodos de memória).
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import json
import os
import tempfile

import perfil_discord

tmp = os.path.join(tempfile.mkdtemp(), "memoria_discord.json")
perfil_discord.ARQUIVO = tmp
if hasattr(perfil_discord, "invalidar_cache"):
    perfil_discord.invalidar_cache()

import interface_web

api = object.__new__(interface_web.Api)
ok, falhou = [], []


def check(desc, cond):
    (ok if cond else falhou).append(desc)


# 1. lista vazia no começo
vazia = api.listar_pessoas_discord()
check("lista vazia quando não há ninguém", vazia == [])

# 2. ensinar um fato
resp = api.add_fato_pessoa("123", "HaoQin", "joga elden ring de mago")
check("add_fato_pessoa confirma", "guardei" in resp.lower())
resp2 = api.add_fato_pessoa("123", "HaoQin", "joga elden ring de mago")
check("duplicado é recusado", "já sabia" in resp2.lower())

# 3. listar devolve a ficha certa
pessoas = api.listar_pessoas_discord()
check("uma pessoa na lista", len(pessoas) == 1)
p = pessoas[0]
check("ficha tem id/nome/fatos",
      p["id"] == "123" and p["nome"] == "HaoQin"
      and p["fatos"] == ["joga elden ring de mago"])
check("contadores zerados presentes",
      p["mensagens"] == 0 and p["interacoes"] == 0)

# 4. esquecer
resp3 = api.del_fato_pessoa("123", "elden ring")
check("del_fato_pessoa esquece", "esqueci" in resp3.lower())
check("fatos ficou vazio", api.listar_pessoas_discord()[0]["fatos"] == [])

# 5. segunda pessoa entra na lista e a ordenação prefere quem tem fatos
api.add_fato_pessoa("456", "Maria", "gosta de jujutsu kaisen")
api.add_fato_pessoa("123", "HaoQin", "mora longe")
ordem = [x["id"] for x in api.listar_pessoas_discord()]
check("lista ordenada com fatos primeiro", ordem == ["123", "456"])

# 6. arquivo no disco é json válido com a estrutura esperada
dados = json.load(open(tmp, encoding="utf-8"))
check("estrutura do arquivo ok",
      "membros" in dados and "123" in dados["membros"]
      and dados["membros"]["123"]["fatos"])

print(f"passaram {len(ok)}, falharam {len(falhou)}")
for f in falhou:
    print("FALHOU:", f)
import sys
sys.exit(1 if falhou else 0)
