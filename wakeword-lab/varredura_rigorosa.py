"""Duração mínima mais alta (opção 'ativação menos sensível'), conf 0,70. Mesmo corpus do varredura_limiar.py.
Uso: .venv/bin/python varredura_rigorosa.py
"""
import glob
import numpy as np
from scipy.io import wavfile
from experimento_iscas import AQUI, clipes_negativos, conversa_sintetica
from varredura_limiar import candidatos, passa

clipes = []
for d in sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*"))):
    for f in sorted(glob.glob(d + "/*.wav")):
        sr, x = wavfile.read(f)
        pad = np.zeros(int(.6 * sr), np.int16)
        clipes.append(candidatos(np.concatenate([pad, x, pad])))
neg = clipes_negativos()
falsos = {"babel3": candidatos(conversa_sintetica(neg, 8, 3)), "babel5": candidatos(conversa_sintetica(neg, 8, 5))}
print(f"{'modo':9s} {'dur':>5s} {'recall':>12s} {'babel3':>7s} {'babel5':>7s}")
for modo, durs in (("continuo", (.34, .38, .42)), ("rapido", (.34, .38, .42))):
    for dur in durs:
        ok = sum(any(passa(c, .70, dur, modo) for c in cs) for cs in clipes)
        print(f"{modo:9s} {dur:5.2f} {ok:4d}/{len(clipes)} {ok/len(clipes)*100:4.1f}% "
              f"{sum(passa(c,.70,dur,modo) for c in falsos['babel3']):7d} {sum(passa(c,.70,dur,modo) for c in falsos['babel5']):7d}", flush=True)
