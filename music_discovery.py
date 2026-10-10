"""Captura explícita de música no PC; não altera a escuta de comandos."""
import io
import json
import os
import select
import subprocess
import threading
import time
import wave

_lock = threading.Lock()
_cancel = threading.Event()
_state = {"fase": "aguardando"}
_state_lock = threading.Lock()


def state():
    with _state_lock:
        return json.loads(json.dumps(_state))


def update(**values):
    global _state
    with _state_lock:
        _state = values


def cancel():
    _cancel.set()
    return True


def capture(source, seconds):
    import pyaudio
    pa = pyaudio.PyAudio()
    stream = None
    try:
        index = None
        if source == "sistema":
            if os.name != "nt":
                # O monitor do sink padrão captura o som sem depender do microfone.
                sink = subprocess.check_output(["pactl", "get-default-sink"], timeout=4, text=True).strip()
                proc = subprocess.Popen(["parec", "--device=" + sink + ".monitor", "--format=s16le", "--rate=16000", "--channels=1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                try:
                    chunks = []
                    deadline = time.monotonic() + seconds + 8
                    captured = 0
                    total = seconds * 16000 * 2
                    while captured < total:
                        if _cancel.is_set(): raise InterruptedError()
                        while not select.select([proc.stdout], [], [], 0.2)[0]:
                            if _cancel.is_set(): raise InterruptedError()
                            if time.monotonic() > deadline:
                                raise RuntimeError("O áudio do sistema não respondeu a tempo")
                        chunk = os.read(proc.stdout.fileno(), min(2048, total-captured))
                        if not chunk: raise RuntimeError("Captura do áudio do sistema indisponível")
                        chunks.append(chunk)
                        captured += len(chunk)
                        update(fase="ouvindo", fonte=source, segundos=captured//32000, total=seconds)
                    return b"".join(chunks)
                finally:
                    proc.terminate()
                    try: proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill(); proc.wait()
            raise RuntimeError("Captura do sistema no Windows ainda indisponível; escolha microfone")
        stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        chunks = []
        for n in range(seconds * 16000 // 1024):
            if _cancel.is_set(): raise InterruptedError()
            chunks.append(stream.read(1024, exception_on_overflow=False))
            update(fase="ouvindo", fonte=source, segundos=round(n * 1024 / 16000), total=seconds)
        return b"".join(chunks)
    finally:
        if stream:
            stream.stop_stream(); stream.close()
        pa.terminate()


def identify(fonte="sistema", segundos=12, audd=False):
    if fonte not in ("sistema", "microfone"):
        return {"ok": False, "mensagem": "Escolha sistema ou microfone"}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "mensagem": "Uma identificação já está em andamento"}
    _cancel.clear()
    try:
        update(fase="ouvindo", fonte=fonte, segundos=0, total=12 if int(segundos) <= 12 else 24)
        from interface_web import _api_registrada
        if _api_registrada:
            _api_registrada.music_identify_window()
        pcm = capture(fonte, state()["total"])
        if _cancel.is_set(): raise InterruptedError()
        update(fase="identificando")
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setparams((1, 2, 16000, 0, "NONE", "not compressed")); w.writeframes(pcm)
        import requests
        response = requests.post("http://127.0.0.1:5000/music/identify", params={"audd": "1" if audd else "0"},
                                 headers={"Authorization": "Bearer " + os.getenv("EMILY_PONTE_TOKEN", "")}, data=wav.getvalue(), timeout=(5, 95))
        response.raise_for_status()
        result = response.json()
        if _cancel.is_set(): raise InterruptedError()
        update(fase="resultado", **result)
        return result
    except InterruptedError:
        update(fase="cancelado", mensagem="Identificação cancelada")
        return {"ok": False, "mensagem": "Identificação cancelada"}
    except Exception as error:
        update(fase="erro", mensagem="Não consegui identificar: " + str(error)[:200])
        return {"ok": False, "mensagem": state()["mensagem"]}
    finally:
        _lock.release()
