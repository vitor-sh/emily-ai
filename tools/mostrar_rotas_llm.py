"""Mostra o provedor/modelo efetivo de cada rota da Emily e o que o seletor oferece.

Só lê a configuração (carrega llm.py). Não faz chamadas aos modelos.
Uso: python3 tools/mostrar_rotas_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import llm  # noqa: E402

print(f"tabela ativa: {llm.TABELA_ATIVA} | conversa: "
      f"{llm.ROTAS['conversa'].provedor}/{llm.ROTAS['conversa'].modelo}")
print("seletor:")
for p in llm.listar_provedores():
    print(f"  {p['id']} ({p['nome']}): " + ", ".join(m["id"] for m in p["modelos"]))
print("rotas:")
for nome in sorted(set(llm.ROTAS) | set(llm.TABELAS[llm.TABELA_PADRAO])):
    r = llm.rota(nome)
    fbs = ", ".join(f"{a}:{b}" for a, b in r.fallbacks) or "-"
    print(f"  {nome:22s} {r.provedor}/{r.modelo:24s} fallbacks: {fbs}")
