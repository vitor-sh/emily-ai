"""Varre confiança e duração mínima do nome sobre os candidatos já calculados (cache do ajuste_silero).

Parâmetros do contexto fixos nos melhores valores do ajuste: Silero entra .70 / fica .50,
cauda após o nome a partir de +.30 s, mínimo .18 s, fala anterior máxima .65 s.
"""
import os
import pickle
from pathlib import Path

from ajuste_silero import decide, flags_silero

corp = pickle.load(open(Path(os.environ["TMPDIR"]) / "ajuste_silero.pkl", "rb"))
for g in corp.values():
    for a in g:
        a["fl"] = flags_silero(a["ps"], a["n20"], .70, .50)


def contar(conf_min, dur_min):
    def ok(c):
        return c["conf"] >= conf_min and c["fim"] - c["inicio"] >= dur_min
    ch = sum(any(ok(c) and decide(a["fl"], c, .30, .18, .65) for c in a["cands"]) for a in corp["clipes"])
    se = sum(ok(c) and decide(a["fl"], c, .30, .18, .65) for a in corp["sessoes"] for c in a["cands"])
    fa = sum(ok(c) and decide(a["fl"], c, .30, .18, .65) for a in corp["falsos"] for c in a["cands"])
    return ch, se, fa


print(f"clipes={len(corp['clipes'])}")
print(f"{'conf_min':>8s} {'dur_min':>8s} | {'chamadas':>9s} {'sessões':>8s} {'falsos':>7s}")
for conf in (.70, .80, .90, .95, .99):
    for dur in (.18, .24, .30, .36):
        ch, se, fa = contar(conf, dur)
        print(f"{conf:8.2f} {dur:8.2f} | {ch:9d} {se:8d} {fa:7d}")
