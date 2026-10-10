"""Regressões do boot gráfico, ngrok e visualizador de logs."""
from __future__ import annotations

import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import emily_logs as logs  # noqa: E402
import servicos_runtime as servicos  # noqa: E402

falhas = []


def checar(nome, condicao, detalhe=""):
    print(f"[{'OK' if condicao else 'FALHOU'}] {nome}" +
          (f" -> {detalhe}" if detalhe and not condicao else ""))
    if not condicao:
        falhas.append(nome)


# O ambiente do .desktop pode não ter Snap nem diretórios do usuário.
env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
servicos.preparar_ambiente(env)
checar("PATH gráfico ganha diretório do Snap",
       "/var/lib/snapd/snap/bin" in env["PATH"].split(os.pathsep), env["PATH"])

ngrok = servicos.encontrar_executavel("ngrok", "EMILY_NGROK")
checar("ngrok é encontrado fora do PATH reduzido", bool(ngrok), str(ngrok))
if Path("/var/lib/snapd/snap/bin/ngrok").exists():
    checar("atalho do Snap não é resolvido para /usr/bin/snap",
           bool(ngrok and Path(ngrok).name == "ngrok"), str(ngrok))

# Override explícito deve vencer qualquer instalação global.
tmp = Path(tempfile.mkdtemp(prefix="emily_servicos_"))
fake = tmp / "ngrok-custom"
fake.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
fake.chmod(0o755)
os.environ["EMILY_NGROK_TESTE"] = str(fake)
checar("caminho explícito de ferramenta vence",
       servicos.encontrar_executavel("nao-existe", "EMILY_NGROK_TESTE") == str(fake))

# Falha imediata precisa ser observável, não DEVNULL. Isola as funções de rede.
orig_encontrar = servicos.encontrar_executavel
orig_porta = servicos._porta_pronta
orig_url = servicos._url_publica
try:
    servicos.encontrar_executavel = lambda *_: str(fake)
    servicos._porta_pronta = lambda *_: True
    servicos._url_publica = lambda *_: ""
    servicos._subir_ngrok(5000)
    estado = servicos.estado_ngrok()
    checar("término imediato do ngrok vira erro", estado["estado"] == "erro", str(estado))
    checar("código de saída do ngrok aparece", "7" in str(estado["erro"]), str(estado))
finally:
    servicos.encontrar_executavel = orig_encontrar
    servicos._porta_pronta = orig_porta
    servicos._url_publica = orig_url

# Um túnel que já existe deve ser reutilizado sem criar outro processo.
try:
    servicos._url_publica = lambda *_: "https://ja-ativo.ngrok.app"
    servicos._subir_ngrok(5000)
    estado = servicos.estado_ngrok()
    checar("túnel existente é reutilizado", estado["estado"] == "online", str(estado))
    checar("URL existente é exposta", estado["url"] == "https://ja-ativo.ngrok.app")
finally:
    servicos._url_publica = orig_url

# Arquivo de log: cauda limitada, segredos ocultos e limpeza segura.
log = tmp / "emily.log"
os.environ["EMILY_LOG_PATH"] = str(log)
log.write_text("antigo\nAPI_KEY=nao-mostrar\nAuthorization: Bearer secreto\nfim\n",
               encoding="utf-8")
lido = logs.ler(4096)
checar("leitura do log funciona", lido["ok"] and "fim" in lido["texto"])
checar("API key é ocultada", "nao-mostrar" not in lido["texto"], lido["texto"])
checar("Bearer é ocultado", "secreto" not in lido["texto"], lido["texto"])
checar("limpar log funciona", logs.limpar() and log.read_text(encoding="utf-8") == "")

# Contrato mínimo do frontend (pega IDs/funções renomeados sem atualizar ponte).
html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
css = (ROOT / "web" / "estilo.css").read_text(encoding="utf-8")
for trecho in ('id="btn-logs"', 'id="logs-fundo"', 'function abrirLogs()',
               "tenta('logs_ler')", '.logs-modal {', '.inicio-logs {'):
    checar(f"frontend contém {trecho}", trecho in html + js + css)

print()
if falhas:
    print(f"FALHOU: {len(falhas)} teste(s): {falhas}")
    raise SystemExit(1)
print("Tudo certo.")