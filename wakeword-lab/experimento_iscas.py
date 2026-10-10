"""Gramática com palavras-isca: quantos falsos positivos some e quantas chamadas reais se perdem.

Recall   : 610 clipes pessoais ("Emily" dita pelo usuário em 5 cômodos) + 6 sessões longas.
Falsos   : conversa de várias pessoas sintetizada (3 a 5 vozes pt-BR sobrepostas) + a conversa real
           gravada (conversation*.wav). Os candidatos são os que o avaliador do app aceitaria.

Uso: .venv/bin/python experimento_iscas.py
"""
import glob
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import vosk
from scipy.io import wavfile

AQUI = Path(__file__).resolve().parent
SR = 16_000
vosk.SetLogLevel(-1)
MODELO = vosk.Model(str(AQUI.parent / "EmilyAPP2/app/src/main/assets/model-en-us"))
rng = np.random.default_rng(11)

ISCAS = {
    "nomes": ["amelia", "emilia", "emma", "emil", "amy", "milly", "millie", "lily"],
    "sons": ["family", "really", "mommy", "many", "money", "enemy", "email", "mean", "me", "may", "maybe"],
}
GRAMATICAS = {
    "atual": ["emily", "hey emily", "[unk]"],
    "iscas-nomes": ["emily", "hey emily", "[unk]"] + ISCAS["nomes"],
    "iscas-nomes+sons": ["emily", "hey emily", "[unk]"] + ISCAS["nomes"] + ISCAS["sons"],
}


def aceitos(x: np.ndarray, gramatica: list[str]) -> list[dict]:
    """Candidatos que o WakeWordCandidateEvaluator aceitaria (nome isolado, conf>=.70, >=180 ms)."""
    rec = vosk.KaldiRecognizer(MODELO, SR, json.dumps(gramatica))
    rec.SetWords(True)
    saida = []

    def tratar(res):
        p = res.get("result", [])
        if not p or len(p) > 3:
            return
        i = 1 if p[0]["word"].lower() == "hey" else 0
        if len(p) != i + 1 or p[i]["word"].lower() != "emily":
            return
        n = p[i]
        if n["conf"] >= .70 and n["end"] - n["start"] >= .18:
            saida.append(dict(inicio=n["start"], conf=n["conf"]))

    for k in range(0, len(x), 3200):
        if rec.AcceptWaveform(x[k:k + 3200].tobytes()):
            tratar(json.loads(rec.Result()))
    tratar(json.loads(rec.FinalResult()))
    return saida


def clipes_negativos() -> list[np.ndarray]:
    d = json.load(open(AQUI / "work/wake-context-current.json"))
    ruins = re.compile(r"emil|emily|noise|silence", re.I)
    saida = []
    for r in d:
        if r["positive"] or ruins.search(r["text"]):
            continue
        sr, x = wavfile.read(AQUI / r["path"])
        if x.dtype != np.int16:
            continue
        if sr != SR:
            continue
        saida.append(x.astype(np.float64))
    return saida


def conversa_sintetica(clipes, minutos: float, vozes: int) -> np.ndarray:
    """Mistura `vozes` fluxos independentes de frases, ganhos e pausas aleatórios."""
    n = int(minutos * 60 * SR)
    mix = np.zeros(n)
    for _ in range(vozes):
        pos = int(rng.uniform(0, 2) * SR)
        ganho = 10 ** (rng.uniform(-9, 0) / 20)
        while pos < n:
            c = clipes[rng.integers(len(clipes))] * ganho
            fim = min(n, pos + len(c))
            mix[pos:fim] += c[: fim - pos]
            pos = fim + int(rng.uniform(0.2, 1.8) * SR)
    pico = np.abs(mix).max()
    return (mix / pico * 12000).astype(np.int16)


def recall_clipes(gramatica) -> tuple[int, int]:
    ok = tot = 0
    for d in sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*"))):
        for f in sorted(glob.glob(d + "/*.wav")):
            sr, x = wavfile.read(f)
            pad = np.zeros(int(.6 * sr), np.int16)
            tot += 1
            ok += bool(aceitos(np.concatenate([pad, x, pad]), gramatica))
    return ok, tot


if __name__ == "__main__":
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "voz"
    sessoes = sorted(glob.glob(str(tmp / "sessao_*.wav")))
    clipes = clipes_negativos()
    print(f"clipes negativos limpos: {len(clipes)} ({sum(len(c) for c in clipes)/SR:.0f} s)")
    babel = {v: conversa_sintetica(clipes, 8, v) for v in (3, 5)}
    reais = [wavfile.read(f)[1] for f in glob.glob(str(AQUI / "work/wake-context-private/conversation*.wav"))]
    print(f"{'gramática':20s} {'clipes':>11s} {'sessões':>9s} {'babel3':>7s} {'babel5':>7s} {'conversa real':>14s}")
    for nome, g in GRAMATICAS.items():
        ok, tot = recall_clipes(g)
        ses = sum(len(aceitos(wavfile.read(f)[1], g)) for f in sessoes)
        b3 = len(aceitos(babel[3], g)); b5 = len(aceitos(babel[5], g))
        cr = sum(len(aceitos(x, g)) for x in reais)
        print(f"{nome:20s} {ok:4d}/{tot:<4d}{ok/tot*100:4.0f}% {ses:9d} {b3:7d} {b5:7d} {cr:14d}", flush=True)
