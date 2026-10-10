"""Chamada real no meio de várias vozes: o que a regra de nível relativo ganha e custa.

Políticas comparadas (todas sobre os candidatos que o avaliador do app já aceitaria):
  P0  contexto atual (VAD de energia)
  P1  contexto com fala medida pelo Silero, sem exceção
  P2  igual P1, mas fala de fundo MAIS BAIXA que o nome (razão >= K) não veta a chamada

Falsos positivos: 10 min de conversa sintética (3 e 5 vozes) sem nenhuma chamada.
Recall: chamadas pessoais reais coladas no meio da conversa com nível +d dB sobre as vozes,
e em silêncio (deve ficar igual ao atual).

Uso: .venv/bin/python experimento_multidao.py [trials_por_nivel]
"""
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from experimento_iscas import clipes_negativos, conversa_sintetica
from replay_sessoes import SR, VadEnergia, candidatos, silero

AQUI = Path(__file__).resolve().parent
rng = np.random.default_rng(23)
F20 = 320


def rms20(x):
    q = x[: len(x) // F20 * F20].reshape(-1, F20).astype(np.float64)
    return np.sqrt((q ** 2).mean(1)) + 1e-9


def flags_energia(x):
    v = VadEnergia()
    return np.array([v.frame(x[i:i + F20]) for i in range(0, len(x) - F20 + 1, F20)])


def flags_silero(x, entrada=0.5, continua=0.35):
    ps = silero(x)
    em_fala = False
    blocos = np.zeros(len(ps), bool)
    for i, p in enumerate(ps):          # histerese: entra com p>=.5, sai abaixo de .35
        em_fala = (p >= entrada) or (em_fala and p >= continua)
        blocos[i] = em_fala
    n = len(x) // F20
    f = np.zeros(n, bool)
    for k in range(n):                   # causal: só blocos já concluídos no fim do frame
        b = ((k + 1) * F20) // 512 - 1
        f[k] = blocos[b] if 0 <= b < len(blocos) else False
    return f


def decidir(flags, nivel, c, K=None):
    """Regras do WakeSpeechContext sobre flags de 20 ms. K=None: sem exceção de nível."""
    ini = c["inicio"] if not c["prefixo"] else max(c["inicio"] - .45, 0)
    nome = nivel[int(c["inicio"] * 50):max(int(c["fim"] * 50), int(c["inicio"] * 50) + 1)]
    nivel_nome = float(np.sqrt((nome ** 2).mean())) if len(nome) else 1.0

    def nivel_fala(a, b):
        ia, ib = max(0, int(np.ceil(a * 50))), min(len(flags), int(np.floor(b * 50)))
        sel = nivel[ia:ib][flags[ia:ib]] if ib > ia else np.array([])
        return float(np.sqrt((sel ** 2).mean())) if len(sel) else 0.0

    def fundo_ignoravel(nv):
        return K is not None and nv > 0 and nivel_nome / nv >= K

    fim_ant = int(np.floor((ini - .12) * 50)) - 1
    cont = quieto = 0
    for k in range(min(len(flags) - 1, fim_ant), max(-1, fim_ant - 100), -1):
        if flags[k]: cont += 1; quieto = 0
        else: quieto += 1
        if quieto >= 18: break
    if cont / 50 > .65 and not fundo_ignoravel(nivel_fala(ini - 2.0, ini - .12)):
        return False
    a, b = max(0, int(np.ceil((c["fim"] + .12) * 50))), min(len(flags), int(np.floor((c["fim"] + .60) * 50)))
    if b > a and flags[a:b].sum() / 50 >= .18 - 1e-6 and not fundo_ignoravel(nivel_fala(c["fim"] + .12, c["fim"] + .60)):
        return False
    return True


POLITICAS = [("P0 atual", None, False), ("P1 silero", None, True)] + [(f"P2 K={k}", k, True) for k in (1.5, 2.0, 3.0)]


def avaliar(x):
    """Aceitos por política: {nome: [inicio,...]} e total de candidatos do Vosk."""
    cands = candidatos(x)
    fe, fs, nv = flags_energia(x), flags_silero(x), rms20(x)
    saida = {}
    for nome, K, usa_silero in POLITICAS:
        saida[nome] = [c["inicio"] for c in cands if decidir(fs if usa_silero else fe, nv, c, K)]
    return len(cands), saida


def mix_com_chamada(babel, clip, db_sobre_vozes):
    """Cola `clip` no meio de um trecho de conversa com nível +db sobre a fala das vozes."""
    n = len(babel)
    pos = int(rng.uniform(1.5, 4.0) * SR)
    voz = babel[np.abs(babel) > 0]
    ref = np.sqrt((babel.astype(float) ** 2).mean())
    c = clip.astype(float)
    c = c / (np.sqrt((c ** 2).mean()) + 1e-9) * ref * 10 ** (db_sobre_vozes / 20)
    # a chamada substitui as vozes naquele trecho? Não: soma, como no ambiente real
    m = babel.astype(float).copy()
    m[pos:pos + len(c)] += c[: n - pos]
    pico = np.abs(m).max()
    if pico > 32000:
        m *= 32000 / pico
    return m.astype(np.int16), pos / SR, (pos + len(c)) / SR


if __name__ == "__main__":
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    clipes = clipes_negativos()
    nomes = [p[0] for p in POLITICAS]

    if os.environ.get("SO_RECALL") != "1":
        print("== FALSOS POSITIVOS (10 min de conversa sem nenhuma chamada) ==", flush=True)
        print(f"{'vozes':6s} {'cand.Vosk':>9s} " + " ".join(f"{n:>10s}" for n in nomes), flush=True)
        for vozes in (3, 5):
            x = conversa_sintetica(clipes, 10, vozes)
            n, acc = avaliar(x)
            print(f"{vozes:<6d} {n:9d} " + " ".join(f"{len(acc[k]):10d}" for k in nomes), flush=True)

    print("\n== CHAMADAS REAIS (recall) ==", flush=True)
    print(f"{'cenário':22s} " + " ".join(f"{n:>10s}" for n in nomes), flush=True)
    chamadas = sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*/emily_0[0-9]*.wav")))
    rng.shuffle(chamadas)
    chamadas = chamadas[:trials]
    niveis = [int(v) for v in os.environ.get("NIVEIS", "0,4,8,12").split(",") if v]
    cenarios = ([("silêncio", None)] if os.environ.get("SILENCIO", "1") == "1" else []) + [(f"vozes +{d} dB", d) for d in niveis]
    for nome_cen, d in cenarios:
        ok = {k: 0 for k in nomes}
        for f in chamadas:
            _, clip = wavfile.read(f)
            if d is None:
                x = np.concatenate([np.zeros(int(.6 * SR), np.int16), clip, np.zeros(int(.8 * SR), np.int16)])
                t0, t1 = .6, .6 + len(clip) / SR
            else:
                base = conversa_sintetica(clipes, 7 / 60, 4)
                x, t0, t1 = mix_com_chamada(base, clip, d)
            _, acc = avaliar(x)
            for k in nomes:
                ok[k] += any(t0 - .4 <= t <= t1 + .2 for t in acc[k])
        print(f"{nome_cen:22s} " + " ".join(f"{ok[k]:4d}/{len(chamadas):<4d}{ok[k]/len(chamadas)*100:3.0f}%"[:10].rjust(10) for k in nomes), flush=True)
