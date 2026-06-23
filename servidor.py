"""
servidor.py — Controle remoto da Emily via celular

Como usar:
1. Rode a Emily normalmente
2. O servidor inicia automaticamente junto com ela (via main.py)
3. Execute o ngrok: ngrok http 5000
4. Acesse a URL do ngrok no celular

A função processar_texto_digitado() do main.py é injetada aqui
pelo próprio main.py na hora de iniciar o servidor.
"""

import io
import os
import queue
import threading
import time
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# Essa função é injetada pelo main.py quando o servidor sobe
# Ela aponta para processar_texto_digitado do main.py
_callback_processar = None

# Buffer circular simples: cada item é (timestamp, texto, audio_bytes)
# Guarda as últimas falas da Emily pra serem consumidas pelo celular.
MAX_FALAS_NA_FILA = 50
_falas: queue.Queue = queue.Queue(maxsize=MAX_FALAS_NA_FILA)

def definir_callback(fn):
    """Chamado pelo main.py para conectar o servidor à Emily."""
    global _callback_processar
    _callback_processar = fn


@app.route("/fala")
def obter_fala():
    """
    Long-polling: o celular fica esperando a próxima fala da Emily.
    Retorna o áudio em WAV base64 + o texto falado.
    """
    try:
        item = _falas.get(timeout=25)
        _, texto, audio_bytes = item
        import base64
        wav_bytes = _pack_wav_atual(audio_bytes)
        return jsonify({
            "ok": True,
            "texto": texto,
            "audio": base64.b64encode(wav_bytes).decode("utf-8"),
        })
    except queue.Empty:
        return jsonify({"ok": False, "mensagem": "nenhuma fala nova"}), 204


def _pack_wav(pcm_bytes: bytes, sample_rate: int = 22050, sample_width: int = 2, channels: int = 1) -> bytes:
    """Envolve o PCM bruto da Emily em um WAV válido (44 bytes de header)."""
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


def _pack_wav_atual(pcm_bytes: bytes) -> bytes:
    """Envolve o PCM usando os parâmetros de taxa atuais da Emily."""
    import voz as _voz
    return _pack_wav(
        pcm_bytes,
        sample_rate=_voz._audio_sample_rate,
        sample_width=_voz._audio_sample_width,
        channels=_voz._audio_channels,
    )


def receber_fala(texto: str, audio_bytes: bytes) -> None:
    """Recebe o áudio da Emily e coloca na fila pro celular consumir."""
    if not audio_bytes:
        return

    try:
        # Se a fila estiver cheia, descarta a fala mais antiga
        if _falas.full():
            try:
                _falas.get_nowait()
            except queue.Empty:
                pass
        _falas.put_nowait((time.time(), texto, audio_bytes))
    except queue.Full:
        pass


# ─────────────────────────────────────────────────────────────────
# STREAM DE TELA (MJPEG)
# ─────────────────────────────────────────────────────────────────

# Resolução do stream (0.0 a 1.0 da tela). Menor = mais leve/rápido.
_STREAM_QUALIDADE   = 60   # qualidade JPEG (0-100)
_STREAM_FPS_MAX     = 10   # frames por segundo máximos
_STREAM_ESCALA      = 0.5  # 50% da resolução real da tela

# Flag global para ligar/desligar o stream sob demanda
_stream_ativo = False
_stream_lock  = threading.Lock()


def _gerar_frames():
    """
    Gerador MJPEG: captura a tela com mss, comprime em JPEG e
    entrega frame a frame enquanto houver um cliente conectado.
    """
    import mss
    import mss.tools
    from PIL import Image

    global _stream_ativo

    intervalo = 1.0 / _STREAM_FPS_MAX

    with mss.mss() as sct:
        monitor = sct.monitors[1]  # monitor principal

        while True:
            with _stream_lock:
                if not _stream_ativo:
                    break

            t_ini = time.time()

            try:
                # Captura a tela
                frame_bruto = sct.grab(monitor)

                # Converte para imagem PIL e redimensiona
                img = Image.frombytes("RGB", frame_bruto.size, frame_bruto.bgra, "raw", "BGRX")

                if _STREAM_ESCALA != 1.0:
                    nova_largura  = int(img.width  * _STREAM_ESCALA)
                    nova_altura   = int(img.height * _STREAM_ESCALA)
                    img = img.resize((nova_largura, nova_altura), Image.LANCZOS)

                # Comprime em JPEG
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=_STREAM_QUALIDADE, optimize=True)
                jpeg_bytes = buf.getvalue()

                # Envia o frame no formato multipart/x-mixed-replace
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg_bytes)).encode() + b"\r\n"
                    b"\r\n" + jpeg_bytes + b"\r\n"
                )
            except Exception:
                break

            # Controla FPS
            tempo_gasto = time.time() - t_ini
            espera = intervalo - tempo_gasto
            if espera > 0:
                time.sleep(espera)


# ─────────────────────────────────────────────────────────────────
# ROTAS
# ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve a interface do celular."""
    return app.send_static_file("index.html")


@app.route("/comando", methods=["POST"])
def receber_comando():
    """
    Recebe um comando do celular e repassa pra Emily processar.
    Espera JSON: { "texto": "abre o discord" }
    """
    dados = request.get_json(silent=True)

    if not dados or "texto" not in dados:
        return jsonify({"ok": False, "erro": "Manda o campo 'texto' no JSON."}), 400

    texto = dados["texto"].strip()

    if not texto:
        return jsonify({"ok": False, "erro": "Texto vazio."}), 400

    if _callback_processar is None:
        return jsonify({"ok": False, "erro": "Emily ainda não iniciou. Tenta em alguns segundos."}), 503

    # Processa em thread separada pra não travar a resposta HTTP
    # (alguns comandos demoram, tipo abrir jogos grandes)
    threading.Thread(
        target=_callback_processar,
        args=(texto,),
        daemon=True
    ).start()

    return jsonify({"ok": True, "mensagem": f'Comando recebido: "{texto}"'})


@app.route("/stream")
def stream_tela():
    """
    Endpoint MJPEG: retorna a tela do PC como vídeo ao vivo.
    Basta apontar uma <img src="/stream"> no HTML para funcionar.

    Query params opcionais:
      ?q=hq  — qualidade alta (padrão): JPEG 60, escala 50%
      ?q=lq  — qualidade baixa (mais fluido): JPEG 40, escala 35%
    """
    global _stream_ativo, _STREAM_QUALIDADE, _STREAM_ESCALA

    # Ajusta parâmetros conforme ?q=
    modo = request.args.get("q", "hq").lower()
    if modo == "lq":
        _STREAM_QUALIDADE = 40
        _STREAM_ESCALA    = 0.35
    else:  # hq (padrão)
        _STREAM_QUALIDADE = 60
        _STREAM_ESCALA    = 0.5

    with _stream_lock:
        _stream_ativo = True

    def gerar_e_fechar():
        try:
            yield from _gerar_frames()
        finally:
            # Quando o cliente desconecta, desliga o stream
            global _stream_ativo
            with _stream_lock:
                _stream_ativo = False

    return Response(
        gerar_e_fechar(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # desativa buffer do nginx/ngrok
        }
    )


@app.route("/stream/parar", methods=["POST"])
def parar_stream():
    """Para o stream de tela (economiza CPU quando não está assistindo)."""
    global _stream_ativo
    with _stream_lock:
        _stream_ativo = False
    return jsonify({"ok": True, "mensagem": "Stream encerrado."})


@app.route("/status")
def status():
    """Rota simples pra checar se o servidor tá vivo."""
    pronto = _callback_processar is not None
    return jsonify({
        "ok": True,
        "emily_pronta": pronto,
        "mensagem": "Emily online!" if pronto else "Aguardando Emily iniciar..."
    })


# ─────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────

def iniciar_servidor(porta=5000):
    """
    Inicia o servidor Flask em background.
    Chamado pelo main.py numa thread separada.
    """
    import os
    import logging

    # Silencia os logs do Flask no terminal da Emily
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    print(f"[SERVIDOR] Rodando na porta {porta}. Acesse: http://localhost:{porta}")
    print(f"[SERVIDOR] Para controle remoto, rode: ngrok http {porta}")

    # use_reloader=False é importante pra não criar thread duplicada
    app.run(host="0.0.0.0", port=porta, debug=False, use_reloader=False)