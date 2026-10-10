"""Lista os IDs de modelo que o OmniRoute (Oracle) expõe, sem imprimir a chave.

Lê EMILY_PROVEDOR_OMNIROUTE_BASE/CHAVE do .env do projeto e consulta /v1/models.
Uso: python3 tools/listar_modelos_omniroute.py [--local] [prefixo]   (ex.: kr/)

--secao NOME usa EMILY_PROVEDOR_<NOME>_BASE/CHAVE (padrão: OMNIROUTE).
--local consulta o OmniRoute do PC (127.0.0.1:20128) com a chave guardada no
backup de antes da migração (~/.config/emily-cloud-oracle/.env.before-cloud).
"""
import json
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
LOCAL = "--local" in args
args = [a for a in args if a != "--local"]
SECAO = "OMNIROUTE"
if "--secao" in args:
    i = args.index("--secao")
    SECAO = args[i + 1].upper()
    del args[i:i + 2]
env = dotenv_values(Path.home() / ".config/emily-cloud-oracle/.env.before-cloud" if LOCAL
                    else RAIZ / ".env")
base = (env.get(f"EMILY_PROVEDOR_{SECAO}_BASE") or "").rstrip("/")
# Igual a llm._url_com_v1: a base pode vir com ou sem /v1.
if base and not base.endswith("/v1"):
    base += "/v1"
chave = env.get(f"EMILY_PROVEDOR_{SECAO}_CHAVE") or ""
if not base or not chave:
    sys.exit(f"EMILY_PROVEDOR_{SECAO}_BASE/CHAVE ausentes no .env")

pedido = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {chave}"})
with urllib.request.urlopen(pedido, timeout=20) as resposta:
    dados = json.load(resposta)

prefixo = args[0] if args else ""
ids = sorted(m.get("id", "") for m in dados.get("data", []) if m.get("id", "").startswith(prefixo))
for i in ids:
    print(i)
print(f"-- {len(ids)} modelos", file=sys.stderr)
