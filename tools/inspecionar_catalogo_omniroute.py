"""Mostra janela de contexto e níveis de raciocínio que o OmniRoute publica por modelo.

Não imprime chave nem conteúdo de conversa. Sem argumentos, usa os modelos da
seção omniroute do .env; com ids, mostra só esses.
Uso: python3 tools/inspecionar_catalogo_omniroute.py [id ...] [--secao NOME] [--bruto]
"""
import json
import sys
import urllib.request
from pathlib import Path

from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
BRUTO = "--bruto" in args
args = [a for a in args if a != "--bruto"]
SECAO = "OMNIROUTE"
if "--secao" in args:
    i = args.index("--secao")
    SECAO = args[i + 1].upper()
    del args[i:i + 2]
env = dotenv_values(RAIZ / ".env")
base = (env.get(f"EMILY_PROVEDOR_{SECAO}_BASE") or "").rstrip("/")
if base and not base.endswith("/v1"):
    base += "/v1"
chave = env.get(f"EMILY_PROVEDOR_{SECAO}_CHAVE") or ""
if not base or not chave:
    sys.exit("base/chave ausentes")
ids = args or [m.strip() for m in (env.get(f"EMILY_PROVEDOR_{SECAO}_MODELOS") or "").split(",") if m.strip()]
pedido = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {chave}"})
with urllib.request.urlopen(pedido, timeout=20) as r:
    catalogo = {m["id"]: m for m in json.load(r).get("data", [])}
for mid in ids:
    m = catalogo.get(mid)
    if m is None:
        print(f"{mid:26s} NÃO ESTÁ NO CATÁLOGO")
        continue
    if BRUTO:
        print(mid, json.dumps(m, ensure_ascii=False)[:1200])
        continue
    cap = m.get("capabilities") or {}
    print(f"{mid:26s} contexto={m.get('context_length')} "
          f"niveis={cap.get('effort_tiers')} vision={cap.get('vision')} "
          f"tools={cap.get('tool_calling')} thinking={cap.get('thinking')}")
