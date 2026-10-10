"""Confere os parâmetros escolhidos na resolução NATIVA do Silero (blocos de 32 ms, 31,25 por s),
que é a usada pelo WakeSpeechContext do app, e não nos frames de 20 ms do protótipo."""
import math
import os
import pickle
from pathlib import Path

import numpy as np

FPS = 512 / 16000
corp = pickle.load(open(Path(os.environ["TMPDIR"]) / "ajuste_silero.pkl", "rb"))


def blocos(ps, entra, fica):
    em, out = False, np.zeros(len(ps), bool)
    for i, p in enumerate(ps):
        em = p >= entra or (em and p >= fica)
        out[i] = em
    return out


def decide(voz, c, tail, minimo=.18, antes_max=.65):
    fps = 1 / FPS
    ini = max(c["inicio0"], c["inicio"] - .45) if c["prefixo"] else c["inicio"]
    fim_ant = int(math.floor((ini - .12) * fps)) - 1
    quieto_max = math.ceil(.36 * fps)
    conta = quieto = 0
    for k in range(min(len(voz) - 1, fim_ant), max(-1, fim_ant - math.ceil(2 * fps)), -1):
        if voz[k]: conta += 1; quieto = 0
        else: quieto += 1
        if quieto >= quieto_max: break
    if conta / fps > antes_max: return False
    ia = max(0, int(math.ceil((c["fim"] + tail) * fps))); ib = min(len(voz), int(math.floor((c["fim"] + .60) * fps)))
    return not (ib > ia and voz[ia:ib].sum() / fps >= minimo - 1e-6)


def rodar(entra, fica, tail):
    fl = {id(a): blocos(a["ps"], entra, fica) for g in corp.values() for a in g}
    ch = sum(any(decide(fl[id(a)], c, tail) for c in a["cands"]) for a in corp["clipes"])
    se = sum(decide(fl[id(a)], c, tail) for a in corp["sessoes"] for c in a["cands"])
    fa = sum(decide(fl[id(a)], c, tail) for a in corp["falsos"] for c in a["cands"])
    return ch, se, fa


print(f"clipes={len(corp['clipes'])}   (energia atual: chamadas=447 sessões=684 falsos=23)")
print(f"{'entra':>5s} {'fica':>5s} {'tail':>5s} | {'chamadas':>9s} {'sessões':>8s} {'falsos':>7s}")
for entra, fica in ((.70, .50), (.60, .45), (.50, .35)):
    for tail in (.12, .20, .30, .40):
        ch, se, fa = rodar(entra, fica, tail)
        print(f"{entra:5.2f} {fica:5.2f} {tail:5.2f} | {ch:9d} {se:8d} {fa:7d}")
