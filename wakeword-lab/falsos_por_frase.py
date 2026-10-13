"""Quais frases negativas disparam a wake word, isoladas, por modo e duração mínima.

Uso: .venv/bin/python falsos_por_frase.py
"""
import json, re
import numpy as np
from scipy.io import wavfile
from experimento_iscas import AQUI, SR
from varredura_limiar import candidatos, passa

d = json.load(open(AQUI / "work/wake-context-current.json"))
ruins = re.compile(r"emil|emily|noise|silence", re.I)
cont = {}
for r in d:
    if r["positive"] or ruins.search(r["text"]):
        continue
    sr, x = wavfile.read(AQUI / r["path"])
    if x.dtype != np.int16 or sr != SR:
        continue
    pad = np.zeros(int(.6 * SR), np.int16)
    cs = candidatos(np.concatenate([pad, x, pad]))
    t = r["text"].strip().lower()
    for modo, dur in (("continuo", .30), ("continuo", .34), ("rapido", .18), ("rapido", .30), ("rapido", .34)):
        k = (t, modo, dur)
        cont.setdefault(k, [0, 0])
        cont[k][1] += 1
        cont[k][0] += any(passa(c, .70, dur, modo) for c in cs)
frases = sorted({k[0] for k in cont})
print(f"{'frase':34s} {'cont.30':>8s} {'cont.34':>8s} {'rap.18':>7s} {'rap.30':>7s} {'rap.34':>7s}")
for f in frases:
    linha = [f"{cont[(f,m,dd)][0]}/{cont[(f,m,dd)][1]}" for m, dd in (("continuo",.30),("continuo",.34),("rapido",.18),("rapido",.30),("rapido",.34))]
    if any(not l.startswith("0/") for l in linha):
        print(f"{f[:34]:34s} " + " ".join(f"{l:>7s}" for l in linha))
print("frases negativas testadas:", len(frases))
