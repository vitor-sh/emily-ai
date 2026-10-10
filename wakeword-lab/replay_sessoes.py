"""Repete a decisão de wake word do app (Vosk + avaliador + contexto) em gravações longas.

Mede quantos acionamentos o app teria nas sessões de ambiente e extrai, de cada
um, os sinais que podem separar chamada real de falso positivo.

Uso: .venv/bin/python replay_sessoes.py caminho1.wav [caminho2.wav ...]
(WAV 16 kHz mono; converta antes com ffmpeg.)
"""
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import vosk
from scipy.io import wavfile

SR = 16_000
GRAMATICA = '["emily", "hey emily", "[unk]"]'
vosk.SetLogLevel(-1)
MODELO = vosk.Model(str(Path(__file__).resolve().parent.parent / "EmilyAPP2/app/src/main/assets/model-en-us"))
_SILERO = ort.InferenceSession(str(Path(__file__).resolve().parent.parent / "assets/audio/silero_vad.onnx"))


def silero(x: np.ndarray) -> np.ndarray:
    """Probabilidade de fala por bloco de 32 ms."""
    st = np.zeros((2, 1, 128), np.float32)
    ctx = np.zeros((1, 64), np.float32)
    a = x.astype(np.float32) / 32768
    saida = []
    for i in range(0, len(a) - 511, 512):
        entrada = np.concatenate((ctx, a[i:i + 512][None]), 1).astype(np.float32)
        p, st = _SILERO.run(None, {"input": entrada, "state": st, "sr": np.array(SR, np.int64)})
        saida.append(float(p[0, 0]))
        ctx = entrada[:, -64:]
    return np.array(saida)


class VadEnergia:
    """Porte do AdaptivePcmVoiceActivityDetector + a regra de piso do WakeSpeechContext."""

    def __init__(self):
        self.obs = 0; self.nf = 0.0; self.cons = 0
        self.energias = np.zeros(75); self.n = 0; self.i = 0

    def frame(self, f: np.ndarray) -> bool:
        rms = float(np.sqrt((f.astype(np.float64) ** 2).mean())); pico = int(np.abs(f).max())
        minrms, onset = 320.0, 2
        limiar = max(minrms, self.nf * 2.6 + 90.0)
        if self.obs < 8:
            if pico >= 850 and rms >= minrms * 1.8:
                self.cons += 1
                voz = self.cons >= onset
            else:
                self.nf = rms if self.obs == 0 else (self.nf * self.obs + rms) / (self.obs + 1)
                self.obs += 1; self.cons = 0; voz = False
        else:
            bruto = pico >= 650 and (rms >= limiar or rms >= max(minrms * 1.8, self.nf * 1.8))
            if bruto:
                self.cons += 1
            else:
                self.cons = 0
                self.nf += (rms - self.nf) * (0.12 if rms < self.nf else 0.025)
            voz = bruto and self.cons >= onset
        self.energias[self.i % 75] = rms; self.i += 1; self.n = min(self.n + 1, 75)
        piso = np.sort(self.energias[:self.n])[self.n // 5]
        return bool(voz and (self.n < 8 or rms >= max(1.0, piso * 1.7)))


def candidatos(x: np.ndarray):
    """Palavras 'emily' aceitas pelo avaliador, com tempos absolutos do stream."""
    rec = vosk.KaldiRecognizer(MODELO, SR, GRAMATICA)
    rec.SetWords(True)
    achados = []
    def tratar(res):
        palavras = res.get("result", [])
        if not palavras or len(palavras) > 3:
            return
        prefixo = palavras[0]["word"].lower() == "hey"
        i = 1 if prefixo else 0
        if len(palavras) != i + 1 or palavras[i]["word"].lower() != "emily":
            return
        nome = palavras[i]
        if nome["conf"] >= 0.70 and nome["end"] - nome["start"] >= 0.18:
            achados.append(dict(inicio=nome["start"], inicio0=palavras[0]["start"], fim=nome["end"], conf=nome["conf"], prefixo=prefixo,
                                palavras=[(w["word"], round(w["conf"], 2)) for w in palavras]))
    for i in range(0, len(x), 3200):
        if rec.AcceptWaveform(x[i:i + 3200].tobytes()):
            tratar(json.loads(rec.Result()))
    tratar(json.loads(rec.FinalResult()))
    return achados


def contexto(voz: np.ndarray, c: dict):
    """Decisão do WakeSpeechContext sobre flags de 20 ms."""
    def seg(a, b):
        ia, ib = max(0, int(np.ceil(a * 50))), min(len(voz), int(np.floor(b * 50)))
        return voz[ia:ib].sum() / 50 if ib > ia else 0.0
    inicio = c["inicio"] if not c["prefixo"] else max(c["inicio"] - .45, 0)
    # fala contínua imediatamente antes do nome (sem lacuna > 360 ms), janela de 2 s
    fim_ant = int(np.floor((inicio - .12) * 50)) - 1
    conta = quieto = 0
    for k in range(min(len(voz) - 1, fim_ant), max(-1, fim_ant - 100), -1):
        if voz[k]: conta += 1; quieto = 0
        else: quieto += 1
        if quieto >= 18: break
    if conta / 50 > .65: return "SPEECH_BEFORE_CALL"
    if seg(c["fim"] + .12, c["fim"] + .60) >= .18 - 1e-6: return "SPEECH_AFTER_CALL"
    return "ACCEPT"


def analisar(caminho: str):
    r, x = wavfile.read(caminho)
    assert r == SR and x.ndim == 1, "use WAV 16 kHz mono"
    x = x.astype(np.int16)
    vad = VadEnergia()
    voz = np.array([vad.frame(x[i:i + 320]) for i in range(0, len(x) - 319, 320)])
    ps = silero(x)
    lista = candidatos(x)
    saida = []
    for c in lista:
        dec = contexto(voz, c)
        a, b = int(c["inicio"] * SR), int(c["fim"] * SR)
        rms_nome = float(np.sqrt((x[a:b].astype(float) ** 2).mean())) if b > a else 0.0
        ja, jb = max(0, a - 6 * SR), a
        rms_amb = float(np.sqrt((x[ja:jb].astype(float) ** 2).mean())) if jb > ja else 0.0
        i0, i1 = max(0, int(c["inicio"] * 31.25) - 188), int(c["inicio"] * 31.25)
        saida.append(dict(c, decisao=dec, rms_nome=rms_nome, rms_amb=rms_amb,
                          fala_ambiente=float((ps[i0:i1] > .5).mean()) if i1 > i0 else 0.0))
    return len(x) / SR, saida


if __name__ == "__main__":
    tot_s = tot_c = tot_a = 0
    for caminho in sys.argv[1:]:
        dur, ev = analisar(caminho)
        aceitos = [e for e in ev if e["decisao"] == "ACCEPT"]
        tot_s += dur; tot_c += len(ev); tot_a += len(aceitos)
        print(f"{Path(caminho).name:24s} {dur:6.0f}s  candidatos={len(ev):3d}  aceitos={len(aceitos):3d}")
        for e in aceitos:
            print(f"   t={e['inicio']:7.1f}s conf={e['conf']:.2f} dur={e['fim']-e['inicio']:.2f}s "
                  f"nome/amb={e['rms_nome']/max(1,e['rms_amb']):4.1f}x fala_amb={e['fala_ambiente']*100:3.0f}% {e['palavras']}")
    print(f"\nTOTAL {tot_s/60:.1f} min, candidatos={tot_c}, aceitos={tot_a}  ({tot_a/(tot_s/3600):.1f} por hora)")
