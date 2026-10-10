"""Atraso para detectar o FIM da fala com ruído de fundo: detector atual do app x Silero.

Cada cenário é uma frase de 2 a 4 s (clipes pessoais colados, com pausas curtas) seguida de
5 s com o ruído ainda tocando. Mede, em ms, o tempo entre o fim real da fala e o instante
em que o detector manda parar a gravação, e quantas vezes ele cortou a fala antes da hora.

A: porte fiel do AdaptiveVoiceActivityDetector (amplitude máxima a cada 100 ms, como o
   MediaRecorder.getMaxAmplitude do app).
B: Silero com histerese (entra em p>=ENTRA, fica enquanto p>=SAI) e silêncio final de FIM_MS.

Uso: .venv/bin/python experimento_fim_de_fala.py [frases_por_cenario]
"""
import glob
import sys
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter

from replay_sessoes import SR, silero

AQUI = Path(__file__).resolve().parent
rng = np.random.default_rng(5)
ENTRA, SAI = 0.6, 0.45
FIM_MS = int(__import__("os").environ.get("FIM_MS", "700"))


class DetectorAtual:
    """AdaptiveVoiceActivityDetector.kt com a config padrão do fluxo conversacional."""

    def __init__(self):
        self.silencio, self.silencio_longo, self.longo_apos, self.sem_fala = 950, 1250, 3000, 6000
        self.min_onset, self.min_cont, self.hits_req = 650, 380, 2
        self.ruido = 180.0
        self.hits = 0; self.baixo = 10 ** 9; self.pico_on = 0
        self.ultima_voz = 0; self.ultima_confiante = 0; self.primeira = 0
        self.jan_ini = 0; self.c_baixo = 10 ** 9; self.c_pico = 0
        self.detectou = False

    def _on(self): return min(max(self.min_onset, int(self.ruido * 1.7 + 180)), 2400)
    def _co(self): return min(max(self.min_cont, int(self.ruido * 1.45 + 100)), 1500)

    def _piso(self, a):
        self.ruido += (a - self.ruido) * (0.22 if a < self.ruido else 0.04)
        self.ruido = min(max(self.ruido, 80.0), 1600.0)

    def _reset_cont(self, t):
        self.jan_ini = t; self.c_baixo = 10 ** 9; self.c_pico = 0

    def observar(self, a, t):
        a = max(a, 0)
        if not self.detectou:
            on = self._on(); forte = a >= int(on * 3.0)
            if a >= on:
                self.hits += 1; self.baixo = min(self.baixo, a); self.pico_on = max(self.pico_on, a)
                var = self.pico_on - self.baixo >= max(120, on // 8)
                if forte or (self.hits >= self.hits_req and var):
                    self.detectou = True
                    self.primeira = self.ultima_voz = self.ultima_confiante = t
                    self._reset_cont(t)
            else:
                self.hits = 0; self.baixo = 10 ** 9; self.pico_on = 0; self._piso(a)
            return (not self.detectou) and t >= self.sem_fala
        on = self._on()
        if a >= self._co():
            if t - self.jan_ini > 300: self._reset_cont(t)
            self.c_baixo = min(self.c_baixo, a); self.c_pico = max(self.c_pico, a)
            var = self.c_pico - self.c_baixo >= max(120, on // 8)
            if a >= on and var:
                self.ultima_confiante = self.ultima_voz = t; self._reset_cont(t)
            elif t - self.ultima_confiante <= 300:
                self.ultima_voz = t
        else:
            self._piso(a); self._reset_cont(t)
        limite = self.silencio_longo if self.ultima_confiante - self.primeira >= self.longo_apos else self.silencio
        return t - self.ultima_voz >= limite


def fim_atual(x):
    d = DetectorAtual()
    for k in range(0, len(x) - 1599, 1600):
        if d.observar(int(np.abs(x[k:k + 1600]).max()), (k + 1600) * 1000 // SR):
            return (k + 1600) * 1000 / SR
    return None


def fim_silero(x):
    p = silero(x); em = False; viu = False; ult = 0.0
    for i, v in enumerate(p):
        t = (i + 1) * 512 * 1000 / SR
        em = v >= ENTRA or (em and v >= SAI)
        if em: viu = True; ult = t
        if viu and t - ult >= FIM_MS: return t
    return None


def ruido(tipo, n, amp_rms):
    t = np.arange(n) / SR
    if tipo == "ventilador":
        b, a = butter(2, [60, 400], 'bandpass', fs=SR); x = lfilter(b, a, rng.normal(size=n)) * 3 + 0.6 * np.sin(2 * np.pi * 120 * t)
    elif tipo == "obra":
        x = rng.normal(size=n) * (0.5 + 0.5 * np.sin(2 * np.pi * 9 * t) ** 2) + 0.4 * np.sin(2 * np.pi * 900 * t)
    elif tipo == "batida":
        x = np.zeros(n)
        for s in np.arange(0.2, n / SR, 0.7):
            k = int(s * SR); L = int(0.03 * SR)
            if k + L < n: x[k:k + L] += rng.normal(size=L) * np.exp(-np.arange(L) / (0.006 * SR))
    else:
        b, a = butter(2, [1500, 6500], 'bandpass', fs=SR); x = lfilter(b, a, rng.normal(size=n))
    return x / (np.sqrt((x ** 2).mean()) + 1e-9) * amp_rms


def frase(clipes):
    partes = []
    for _ in range(int(rng.integers(3, 6))):
        partes.append(clipes[rng.integers(len(clipes))].astype(float))
        partes.append(np.zeros(int(rng.uniform(.10, .30) * SR)))
    return np.concatenate(partes[:-1])


if __name__ == "__main__":
    n_frases = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    arqs = sorted(glob.glob(str(AQUI.parent / "amostras_pessoas/vitor_cel_*/emily_0[0-9]*.wav")))
    clipes = [wavfile.read(f)[1] for f in rng.choice(arqs, 80, replace=False)]
    print(f"{'ruído':11s} {'SNR':>5s} | {'ATUAL atraso (p50/p90) ms':>27s} {'corta':>6s} {'trava':>6s} | {'SILERO atraso (p50/p90) ms':>28s} {'corta':>6s} {'trava':>6s}", flush=True)
    for tipo in ("nenhum", "ventilador", "obra", "batida", "chiado"):
        for snr in ((None,) if tipo == "nenhum" else (20, 10, 5)):
            res = {"A": [], "B": []}; corte = {"A": 0, "B": 0}; trava = {"A": 0, "B": 0}
            for _ in range(n_frases):
                f = frase(clipes); rms_f = np.sqrt((f[np.abs(f) > 500] ** 2).mean())
                total = int(.6 * SR) + len(f) + 5 * SR
                x = np.zeros(total); x[int(.6 * SR):int(.6 * SR) + len(f)] = f
                fim_real = (int(.6 * SR) + len(f)) * 1000 / SR
                if snr is not None:
                    x = x + ruido(tipo, total, rms_f / 10 ** (snr / 20))
                x = np.clip(x, -32000, 32000).astype(np.int16)
                for k, fn in (("A", fim_atual), ("B", fim_silero)):
                    t = fn(x)
                    if t is None: trava[k] += 1
                    elif t < fim_real - 50: corte[k] += 1
                    else: res[k].append(t - fim_real)
            def fmt(k):
                v = res[k]
                return f"{np.percentile(v,50):6.0f}/{np.percentile(v,90):6.0f}" if v else "     -/     -"
            print(f"{tipo:11s} {('-' if snr is None else '+%d' % snr):>5s} | {fmt('A'):>27s} {corte['A']:6d} {trava['A']:6d} | {fmt('B'):>28s} {corte['B']:6d} {trava['B']:6d}", flush=True)
