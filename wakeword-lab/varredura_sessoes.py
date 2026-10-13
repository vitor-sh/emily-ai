"""Chamadas reais dentro das 6 sessões longas gravadas pelo Vitor: quantas passam por duração mínima.
As sessões têm a palavra dita no meio da rotina (não clipe isolado), o caso mais próximo do Modo Rápido.
Uso: .venv/bin/python varredura_sessoes.py
"""
import glob, os
from pathlib import Path
from scipy.io import wavfile
from varredura_limiar import candidatos, passa

tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "voz"
cands = {Path(f).stem: candidatos(wavfile.read(f)[1]) for f in sorted(glob.glob(str(tmp / "sessao_*.wav")))}
durs = sorted(c["dur"] for cs in cands.values() for c in cs if c["conf"] >= .70)
print("candidatos 'emily' nas sessões:", len(durs), "| duração p5/p10/p25/mediana:",
      [round(durs[int(len(durs) * q)], 2) for q in (.05, .10, .25, .5)] if durs else "-")
for modo, ds in (("continuo", (.30, .34, .38)), ("rapido", (.18, .30, .34, .38))):
    for d in ds:
        print(f"{modo:9s} {d:.2f} aceitos={sum(passa(c, .70, d, modo) for cs in cands.values() for c in cs)}", flush=True)
