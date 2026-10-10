"""Calibra o contexto acústico da wake word com fala medida pelo Silero.

Para cada combinação de parâmetros mede, sobre os mesmos candidatos do Vosk:
  chamadas  : quantos dos 610 clipes pessoais ainda disparam (quanto MAIOR, melhor)
  sessões   : acionamentos nas 6 gravações em que o usuário chama a Emily (MAIOR = menos chamadas perdidas)
  falsos    : acionamentos em 2 x 10 min de conversa sintética de 3 e 5 vozes, sem chamada (MENOR, melhor)

Uso: .venv/bin/python ajuste_silero.py [--refazer]
"""
import glob
import itertools
import os
import pickle
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from experimento_iscas import clipes_negativos, conversa_sintetica
from replay_sessoes import SR, VadEnergia, candidatos, silero

AQUI = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("TMPDIR", "/tmp")) / "ajuste_silero.pkl"
F20 = 320


def preparar(x):
    x = x.astype(np.int16)
    e = VadEnergia()
    ef = np.array([e.frame(x[i:i + F20]) for i in range(0, len(x) - F20 + 1, F20)])
    return dict(cands=candidatos(x), ps=silero(x).astype(np.float32), ef=ef, n20=len(ef))


def montar():
    corp = {"clipes": [], "sessoes": [], "falsos": []}
    for f in sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*/emily_0[0-9]*.wav"))):
        sr, c = wavfile.read(f)
        pad = np.zeros(int(.6 * sr), np.int16)
        corp["clipes"].append(preparar(np.concatenate([pad, c, pad])))
    print("clipes ok", len(corp["clipes"]), flush=True)
    for f in sorted(glob.glob(str(Path(os.environ.get("TMPDIR", "/tmp")) / "voz/sessao_*.wav"))):
        corp["sessoes"].append(preparar(wavfile.read(f)[1]))
    print("sessões ok", len(corp["sessoes"]), flush=True)
    neg = clipes_negativos()
    for vozes in (3, 5):
        corp["falsos"].append(preparar(conversa_sintetica(neg, 10, vozes)))
    print("falsos ok", flush=True)
    return corp


def flags_silero(ps, n20, entra, fica):
    em = False
    blocos = np.zeros(len(ps), bool)
    for i, p in enumerate(ps):
        em = (p >= entra) or (em and p >= fica)
        blocos[i] = em
    idx = ((np.arange(n20) + 1) * F20) // 512 - 1
    ok = (idx >= 0) & (idx < len(blocos))
    f = np.zeros(n20, bool)
    f[ok] = blocos[idx[ok]]
    return f


def decide(voz, c, a0, minimo, antes_max):
    ini = max(c["inicio0"], c["inicio"] - .45) if c["prefixo"] else c["inicio"]
    fim_ant = int(np.floor((ini - .12) * 50)) - 1
    conta = quieto = 0
    for k in range(min(len(voz) - 1, fim_ant), max(-1, fim_ant - 100), -1):
        if voz[k]:
            conta += 1; quieto = 0
        else:
            quieto += 1
        if quieto >= 18:
            break
    if conta / 50 > antes_max:
        return False
    ia, ib = max(0, int(np.ceil((c["fim"] + a0) * 50))), min(len(voz), int(np.floor((c["fim"] + .60) * 50)))
    if ib > ia and voz[ia:ib].sum() / 50 >= minimo - 1e-6:
        return False
    return True


def contar(corp, flagger, a0, minimo, antes_max):
    r = {}
    r["chamadas"] = sum(any(decide(flagger(a), c, a0, minimo, antes_max) for c in a["cands"]) for a in corp["clipes"])
    r["sessoes"] = sum(decide(flagger(a), c, a0, minimo, antes_max) for a in corp["sessoes"] for c in a["cands"])
    r["falsos"] = sum(decide(flagger(a), c, a0, minimo, antes_max) for a in corp["falsos"] for c in a["cands"])
    return r


if __name__ == "__main__":
    if "--refazer" in sys.argv or not CACHE.exists():
        corp = montar(); pickle.dump(corp, open(CACHE, "wb"))
    else:
        corp = pickle.load(open(CACHE, "rb"))
    total = len(corp["clipes"])
    base = contar(corp, lambda a: a["ef"], .12, .18, .65)
    print(f"\nclipes={total}  | P0 atual (VAD de energia): chamadas={base['chamadas']} sessões={base['sessoes']} falsos={base['falsos']}\n", flush=True)
    linhas = []
    for entra, fica in [(.5, .35), (.5, .5), (.6, .45), (.7, .5)]:
        cache = {}
        def fl(a, e=entra, f=fica):
            k = id(a)
            if k not in cache:
                cache[k] = flags_silero(a["ps"], a["n20"], e, f)
            return cache[k]
        for a0, minimo, antes in itertools.product((.12, .20, .30), (.18, .26, .36), (.65, .90)):
            r = contar(corp, fl, a0, minimo, antes)
            linhas.append((entra, fica, a0, minimo, antes, r))
    print(f"{'entra':>5s} {'fica':>5s} {'após_ini':>8s} {'após_min':>8s} {'antes':>6s} | {'chamadas':>9s} {'sessões':>8s} {'falsos':>7s}")
    for entra, fica, a0, minimo, antes, r in sorted(linhas, key=lambda t: (-t[5]["chamadas"] - t[5]["sessoes"] * 0.2 + 3 * t[5]["falsos"])):
        print(f"{entra:5.2f} {fica:5.2f} {a0:8.2f} {minimo:8.2f} {antes:6.2f} | {r['chamadas']:9d} {r['sessoes']:8d} {r['falsos']:7d}", flush=True)
