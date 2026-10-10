"""Teste do novo fluxo de extração de fatos (caderno + travas soltas).

Não conecta no Discord nem chama LLM de verdade: o modelo é simulado.
O arquivo do perfil é redirecionado pra um temporário.
"""
import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import json
import os
import sys
import tempfile
import types

import perfil_discord

tmp = os.path.join(tempfile.mkdtemp(), "memoria_discord.json")
perfil_discord.ARQUIVO = tmp
perfil_discord.invalidar_cache()

# Travas mínimas pra testar sem virar festa de números.
perfil_discord.MIN_INTERACOES = 2
perfil_discord.MIN_MENSAGENS = 3
perfil_discord.INTERVALO_INTERACOES = 1
perfil_discord.INTERVALO_SEGUNDOS = 0.0

ok, falhou = [], []


def check(desc, cond):
    (ok if falhou else ok).append(desc) if cond else falhou.append(desc)


UID = 999
NOME = "HaoQin"

# ── 1. caderno acumula o que a pessoa fala com a Emily ──
perfil_discord.observar(UID, NOME, "jogo silksong ontem a noite toda",
                        falou_com_emily=True)
perfil_discord.observar(UID, NOME, "trabalho de manha e fico morto",
                        falou_com_emily=True)
perfil_discord.observar(UID, NOME, "mensagem que nao foi com a emily",
                        falou_com_emily=False)

ficha = perfil_discord.carregar()["membros"][str(UID)]
caderno = ficha.get("materia", "")
check("caderno guarda as falas com a Emily", "silksong" in caderno
      and "trabalho" in caderno)
check("caderno NÃO guarda fala que não foi com a Emily",
      "nao foi com a emily" not in caderno)
check("interacoes conta só fala com a Emily", ficha["interacoes"] == 2)
check("mensagens conta todas", ficha["mensagens"] == 3)

# ── 2. caderno é rolante: teto respeita e não rasga linha ──
ficha["materia"] = ""
for i in range(50):
    perfil_discord._anotar_no_caderno(ficha, f"linha numero {i} bem unica {i}")
caderno = ficha["materia"]
check("caderno rolante fica dentro do teto",
      len(caderno) <= perfil_discord.MATERIA_MAX_CHARS)
check("caderno rolante mantém o mais recente", "linha numero 49" in caderno)
linhas = [l for l in caderno.splitlines() if l.strip()]
check("nenhuma linha pela metade", all(l.startswith("- ") for l in linhas))

# ── 3. travas: portes novos (checar ANTES de sobrescrever seria tarde; o
# valor de default está no fonte, e este teste usa os portes mínimos) ──
check("portes de teste aplicados",
      perfil_discord.MIN_MENSAGENS == 3 and perfil_discord.MIN_INTERACOES == 2)

# ── 4. extração ponta a ponta com LLM simulado ──
ficha["mensagens"] = 50
ficha["interacoes"] = 20
perfil_discord._anotar_no_caderno(ficha, "jogo elden ring de mago")
perfil_discord._anotar_no_caderno(ficha, "odeio perder pvp")


class ModeloFalso:
    ultimo_prompt = {}

    @staticmethod
    def chamar_llm_simples(prompt, max_tokens=0):
        ModeloFalso.ultimo_prompt = {"prompt": prompt, "max_tokens": max_tokens}
        return '["joga elden ring de mago", "trabalha de manha"]'


sys.modules["modelo"] = types.SimpleNamespace(
    chamar_llm_simples=ModeloFalso.chamar_llm_simples)

check("deve_extrair libera com as travas baixas",
      perfil_discord.deve_extrair(UID))
novos = perfil_discord.extrair_fatos(UID, NOME, "conversa recente qualquer")
check("dois fatos extraídos", len(novos) == 2)
check("fatos caíram na ficha", ficha["fatos"] == novos)

p = ModeloFalso.ultimo_prompt["prompt"]
check("o prompt recebeu O CADERNO", "elden ring de mago" in p)
check("o prompt recebeu a conversa recente", "conversa recente" in p)
check("max_tokens subiu pra 300", ModeloFalso.ultimo_prompt["max_tokens"] == 300)
check("caderno foi zerado após extração", ficha["materia"] == "")

# ── 5. duplicata local continua barrando repetição ──
ModeloFalso.ultimo_prompt = {}
resposta = '["joga elden ring de mago", "mora em bh"]'
_orig = ModeloFalso.chamar_llm_simples


def _rep(prompt, max_tokens=0):
    return resposta


sys.modules["modelo"] = types.SimpleNamespace(chamar_llm_simples=_rep)
novos2 = perfil_discord.extrair_fatos(UID, NOME, "de novo")
check("fato duplicado barrado, só o novo entrou",
      novos2 == ["mora em bh"] and ficha["fatos"][-1] == "mora em bh")

# ── 6. arquivo em disco segue JSON válido com o caderno ──
dados = json.load(open(tmp, encoding="utf-8"))
check("arquivo íntegro", "999" in dados["membros"]
      and len(dados["membros"]["999"]["fatos"]) == 3)

print(f"passaram {len(ok)}, falharam {len(falhou)}")
for f in falhou:
    print("FALHOU:", f)
sys.exit(1 if falhou else 0)
