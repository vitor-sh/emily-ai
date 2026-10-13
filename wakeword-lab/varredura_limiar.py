"""Varredura de limiar de confiança e duração mínima da wake word (gramática atual).

Decodifica cada áudio UMA vez guardando conf/duração/palavras seguintes de cada
candidato, e aplica os limiares depois. Recall: 610 clipes pessoais. Falsos:
conversa sintética de 3 e 5 vozes (8 min cada) + conversa real gravada.
Dois modos do app: contínuo (nome isolado) e rápido (nome no início, com comando).
Uso: .venv/bin/python varredura_limiar.py
"""
import glob
import json
from pathlib import Path

import numpy as np
import vosk
from scipy.io import wavfile

from experimento_iscas import AQUI, MODELO, SR, clipes_negativos, conversa_sintetica

GRAMATICA = ["emily", "hey emily", "[unk]"]


def candidatos(x):
    rec = vosk.KaldiRecognizer(MODELO, SR, json.dumps(GRAMATICA))
    rec.SetWords(True)
    saida = []

    def tratar(res):
        p = res.get("result", [])
        if not p:
            return
        i = 1 if p[0]["word"].lower() == "hey" else 0
        if len(p) <= i or p[i]["word"].lower() != "emily":
            return
        n = p[i]
        saida.append(dict(conf=n["conf"], dur=n["end"] - n["start"], resto=len(p) - i - 1, total=len(p)))

    for k in range(0, len(x), 3200):
        if rec.AcceptWaveform(x[k:k + 3200].tobytes()):
            tratar(json.loads(rec.Result()))
    tratar(json.loads(rec.FinalResult()))
    return saida


def passa(c, conf, dur, modo):
    if c["conf"] < conf or c["dur"] < dur:
        return False
    return c["resto"] == 0 and c["total"] <= 3 if modo == "continuo" else True


if __name__ == "__main__":
    clipes = []
    for d in sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*"))):
        for f in sorted(glob.glob(d + "/*.wav")):
            sr, x = wavfile.read(f)
            pad = np.zeros(int(.6 * sr), np.int16)
            clipes.append(candidatos(np.concatenate([pad, x, pad])))
    neg = clipes_negativos()
    falsos = {"babel3": candidatos(conversa_sintetica(neg, 8, 3)),
              "babel5": candidatos(conversa_sintetica(neg, 8, 5)),
              "real": [c for f in glob.glob(str(AQUI / "work/wake-context-private/conversation*.wav"))
                       for c in candidatos(wavfile.read(f)[1])]}
    print(f"{'modo':9s} {'conf':>5s} {'dur':>5s} {'recall':>12s} {'babel3':>7s} {'babel5':>7s} {'real':>5s}")
    for modo, durs in (("continuo", (.30, .34, .38)), ("rapido", (.18, .24, .30, .34))):
        for conf in (.70, .75, .80, .85, .90):
            for dur in durs:
                ok = sum(any(passa(c, conf, dur, modo) for c in cs) for cs in clipes)
                fp = {k: sum(passa(c, conf, dur, modo) for c in v) for k, v in falsos.items()}
                print(f"{modo:9s} {conf:5.2f} {dur:5.2f} {ok:4d}/{len(clipes)} {ok/len(clipes)*100:4.1f}% "
                      f"{fp['babel3']:7d} {fp['babel5']:7d} {fp['real']:5d}", flush=True)
