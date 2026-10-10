"""Chamada real com vozes de fundo MAIS BAIXAS (você perto do celular, os outros longe).

Compara o contexto atual (energia) com o Silero já calibrado (entra .70 / fica .50, cauda +.30 s)
e com a variante que perdoa fala de fundo ao menos K vezes mais baixa que o nome.
Só entram no placar as chamadas que o Vosk já reconhece como candidato isolado.
"""
import glob
import math
import os
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from ajuste_silero import flags_silero
from experimento_iscas import clipes_negativos, conversa_sintetica
from replay_sessoes import SR, VadEnergia, candidatos, silero

AQUI = Path(__file__).resolve().parent
rng = np.random.default_rng(31)
F20 = 320


def rms20(x):
    q = x[: len(x) // F20 * F20].reshape(-1, F20).astype(np.float64)
    return np.sqrt((q ** 2).mean(1)) + 1e-9


def decide(voz, nivel, c, tail, K):
    ini = max(c["inicio0"], c["inicio"] - .45) if c["prefixo"] else c["inicio"]
    a, b = int(c["inicio"] * 50), max(int(c["fim"] * 50), int(c["inicio"] * 50) + 1)
    nome = nivel[a:b]
    nome_rms = float(np.sqrt((nome ** 2).mean())) if len(nome) else 1.0

    def fundo_ok(t0, t1):
        if K is None: return False
        ia, ib = max(0, int(math.ceil(t0 * 50))), min(len(voz), int(math.floor(t1 * 50)))
        sel = nivel[ia:ib][voz[ia:ib]] if ib > ia else np.array([])
        if not len(sel): return True
        return nome_rms / float(np.sqrt((sel ** 2).mean())) >= K

    fim_ant = int(math.floor((ini - .12) * 50)) - 1
    cont = quieto = 0
    for k in range(min(len(voz) - 1, fim_ant), max(-1, fim_ant - 100), -1):
        if voz[k]: cont += 1; quieto = 0
        else: quieto += 1
        if quieto >= 18: break
    if cont / 50 > .65 and not fundo_ok(ini - 2.0, ini - .12): return False
    ia, ib = max(0, int(math.ceil((c["fim"] + tail) * 50))), min(len(voz), int(math.floor((c["fim"] + .60) * 50)))
    if ib > ia and voz[ia:ib].sum() / 50 >= .18 - 1e-6 and not fundo_ok(c["fim"] + tail, c["fim"] + .60): return False
    return True


def avaliar(x):
    cands = candidatos(x)
    if not cands: return 0, {}
    e = VadEnergia(); fe = np.array([e.frame(x[i:i + F20]) for i in range(0, len(x) - F20 + 1, F20)])
    ps = silero(x); fs = flags_silero(ps, len(fe), .70, .50); nv = rms20(x)
    pol = {"P0 atual": (fe, .12, None), "P1 silero": (fs, .30, None), "P2 K=2": (fs, .30, 2.0), "P2 K=3": (fs, .30, 3.0), "P2 K=5": (fs, .30, 5.0)}
    return len(cands), {k: [c["inicio"] for c in cands if decide(f, nv, c, t, K)] for k, (f, t, K) in pol.items()}


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    clipes = clipes_negativos()
    chamadas = sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*/emily_0[0-9]*.wav"))); rng.shuffle(chamadas); chamadas = chamadas[:n]
    nomes = ["P0 atual", "P1 silero", "P2 K=2", "P2 K=3", "P2 K=5"]
    print(f"{'nível da chamada':18s} {'Vosk vê':>8s} " + " ".join(f"{k:>10s}" for k in nomes), flush=True)
    for db in (12, 16, 20, 24):
        vistos = 0; ok = {k: 0 for k in nomes}
        for f in chamadas:
            _, clip = wavfile.read(f)
            base = conversa_sintetica(clipes, 7 / 60, 3).astype(float)
            ref = np.sqrt((base ** 2).mean()); c = clip.astype(float)
            c = c / (np.sqrt((c ** 2).mean()) + 1e-9) * ref * 10 ** (db / 20)
            pos = int(rng.uniform(1.5, 3.5) * SR); m = base.copy(); m[pos:pos + len(c)] += c[: len(m) - pos]
            m = m / max(1, np.abs(m).max() / 30000); x = m.astype(np.int16)
            t0, t1 = pos / SR, (pos + len(c)) / SR
            nc, acc = avaliar(x)
            if not nc: continue
            vistos += 1
            for k in nomes: ok[k] += any(t0 - .4 <= t <= t1 + .2 for t in acc.get(k, []))
        print(f"vozes +{db:2d} dB        {vistos:4d}/{len(chamadas):<3d} " + " ".join(f"{ok[k]:4d}/{vistos:<4d}"[:10].rjust(10) for k in nomes), flush=True)
