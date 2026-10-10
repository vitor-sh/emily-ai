"""Roda NA ORACLE: mede quanto o gateway do PC demora para responder /pc/status pelo túnel.

Usa a mesma URL e o mesmo token que o relay usa (config do relay), sem imprimir o token.
Uso (na VM): python3 medir_status_pc_relay.py [vezes]
"""
import json
import sys
import time
from pathlib import Path

import requests

cfg = json.loads((Path.home() / ".config/emily-relay/config.json").read_text())
url = cfg["pc_url"].rstrip("/") + "/pc/status"
vezes = int(sys.argv[1]) if len(sys.argv) > 1 else 8
tempos = []
for i in range(vezes):
    inicio = time.perf_counter()
    try:
        r = requests.get(url, headers={"Authorization": "Bearer " + cfg["pc_token"]}, timeout=(5, 20))
        dur = time.perf_counter() - inicio
        print(f"{i + 1}: HTTP {r.status_code} em {dur:.2f}s")
        tempos.append(dur)
    except requests.RequestException as erro:
        print(f"{i + 1}: FALHOU em {time.perf_counter() - inicio:.2f}s ({type(erro).__name__})")
    time.sleep(1)
if tempos:
    tempos.sort()
    print(f"mediana {tempos[len(tempos) // 2]:.2f}s, máximo {tempos[-1]:.2f}s; "
          f"acima de 2 s (o limite do relay para ações): {sum(t > 2 for t in tempos)}/{len(tempos)}; "
          f"acima de 3 s (limite do /connection/status): {sum(t > 3 for t in tempos)}/{len(tempos)}")
