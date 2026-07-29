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

import base64
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

# Fila de ações destinadas ao Android via Tasker.
# Cada item é um dict: { "acao": str, "dados": dict }
MAX_ACOES_ANDROID = 50
_fila_acoes_android: queue.Queue = queue.Queue(maxsize=MAX_ACOES_ANDROID)

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
# UPLOAD DE ARQUIVOS / IMAGENS
# ─────────────────────────────────────────────────────────────────

# Pasta onde os uploads ficam salvos temporariamente
_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads_emily")

def _garantir_pasta_upload():
    os.makedirs(_UPLOAD_DIR, exist_ok=True)


@app.route("/upload", methods=["POST"])
def upload_arquivo():
    """
    Recebe arquivos (imagens, documentos, etc.) enviados pelo celular.

    Aceita duas formas:
      1. multipart/form-data  — campo 'arquivo' com o arquivo binário
                                campo 'texto' (opcional) com mensagem adicional
      2. application/json     — { "nome": "foto.png", "dados": "<base64>",
                                   "tipo": "image/png", "texto": "opcional" }

    Salva o arquivo em uploads_emily/ e repassa o texto + caminho à Emily.
    """
    _garantir_pasta_upload()

    nome_arquivo  = None
    caminho_final = None
    texto_extra   = ""

    # ── Forma 1: multipart/form-data ──
    if request.content_type and "multipart/form-data" in request.content_type:
        arquivo = request.files.get("arquivo")
        texto_extra = request.form.get("texto", "").strip()

        if not arquivo or arquivo.filename == "":
            return jsonify({"ok": False, "erro": "Nenhum arquivo enviado."}), 400

        # Sanitiza o nome do arquivo
        nome_base  = os.path.basename(arquivo.filename)
        nome_seguro = f"{int(time.time())}_{nome_base}"
        caminho_final = os.path.join(_UPLOAD_DIR, nome_seguro)
        arquivo.save(caminho_final)
        nome_arquivo = nome_base

    # ── Forma 2: JSON com base64 ──
    elif request.content_type and "application/json" in request.content_type:
        dados = request.get_json(silent=True)
        if not dados or "dados" not in dados:
            return jsonify({"ok": False, "erro": "Campos 'nome' e 'dados' são obrigatórios."}), 400

        nome_arquivo  = dados.get("nome", f"arquivo_{int(time.time())}")
        dados_b64     = dados.get("dados", "")
        texto_extra   = dados.get("texto", "").strip()

        # Remove prefixo data URI se houver (ex: "data:image/png;base64,...")
        if "," in dados_b64:
            dados_b64 = dados_b64.split(",", 1)[1]

        try:
            conteudo_bytes = base64.b64decode(dados_b64)
        except Exception:
            return jsonify({"ok": False, "erro": "Base64 inválido."}), 400

        nome_seguro   = f"{int(time.time())}_{os.path.basename(nome_arquivo)}"
        caminho_final = os.path.join(_UPLOAD_DIR, nome_seguro)
        with open(caminho_final, "wb") as f:
            f.write(conteudo_bytes)

    else:
        return jsonify({"ok": False, "erro": "Content-Type não suportado. Use multipart/form-data ou application/json."}), 415

    if _callback_processar is None:
        return jsonify({"ok": False, "erro": "Emily ainda não iniciou. Tenta em alguns segundos."}), 503

    # Monta a mensagem que será passada à Emily
    if texto_extra:
        mensagem = f"[Arquivo recebido: {nome_arquivo}] {texto_extra} — caminho: {caminho_final}"
    else:
        mensagem = f"[Arquivo recebido: {nome_arquivo}] — caminho: {caminho_final}"

    threading.Thread(
        target=_callback_processar,
        args=(mensagem,),
        daemon=True
    ).start()

    return jsonify({
        "ok": True,
        "mensagem": f'Arquivo "{nome_arquivo}" recebido com sucesso.',
        "caminho": caminho_final,
    })


# ─────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM TASKER (ANDROID)
# ─────────────────────────────────────────────────────────────────

def enviar_acao_android(acao: str, dados: dict) -> None:
    """
    Coloca uma ação na fila pra o Tasker buscar via polling em /android/acao.
    Chamada por outros módulos da Emily quando quiser pedir algo ao Android.

    Exemplo:
        enviar_acao_android("notificar", {"titulo": "Emily", "texto": "Pronto!"})
    """
    item = {"acao": acao, "dados": dados}
    try:
        # Se a fila estiver cheia, descarta a ação mais antiga
        if _fila_acoes_android.full():
            try:
                _fila_acoes_android.get_nowait()
            except queue.Empty:
                pass
        _fila_acoes_android.put_nowait(item)
    except queue.Full:
        pass


@app.route("/android/acao")
def android_proxima_acao():
    """
    Polling do Tasker: retorna a próxima ação pendente pra executar no Android.
    Se não houver nada na fila, retorna 204 (sem conteúdo).

    Resposta esperada:
        { "acao": "notificar", "dados": { "titulo": "...", "texto": "..." } }
    """
    try:
        item = _fila_acoes_android.get_nowait()
        return jsonify(item)
    except queue.Empty:
        return ("", 204)


@app.route("/android/evento", methods=["POST"])
def android_receber_evento():
    """
    Recebe eventos do Android enviados pelo Tasker.
    Espera JSON: { "tipo": "notificacao" | "bateria", "dados": { ... } }

    Tipos suportados:
      - notificacao: { "app": "WhatsApp", "titulo": "Fulano", "texto": "oi" }
      - bateria:     { "nivel": 42 }
    """
    dados = request.get_json(silent=True)

    if not dados or "tipo" not in dados:
        return jsonify({"ok": False, "erro": "Manda os campos 'tipo' e 'dados' no JSON."}), 400

    tipo = dados.get("tipo", "").strip()
    info = dados.get("dados", {})

    if _callback_processar is None:
        return jsonify({"ok": False, "erro": "Emily ainda não iniciou. Tenta em alguns segundos."}), 503

    # Formata a mensagem em português conforme o tipo do evento
    if tipo == "notificacao":
        app_nome = info.get("app", "Aplicativo desconhecido")
        titulo   = info.get("titulo", "")
        texto    = info.get("texto", "")
        if titulo and texto:
            mensagem = f"[Android] Notificação de {app_nome}: {titulo} disse: {texto}"
        elif texto:
            mensagem = f"[Android] Notificação de {app_nome}: {texto}"
        else:
            mensagem = f"[Android] Nova notificação de {app_nome}."

    elif tipo == "bateria":
        nivel = info.get("nivel", "?")
        mensagem = f"[Android] Nível de bateria do celular: {nivel}%"

    else:
        mensagem = f"[Android] Evento desconhecido '{tipo}': {info}"

    # Processa em thread separada pra não travar a resposta HTTP
    threading.Thread(
        target=_callback_processar,
        args=(mensagem,),
        daemon=True
    ).start()

    return jsonify({"ok": True, "mensagem": f"Evento '{tipo}' recebido."})


@app.route("/android/status")
def android_status():
    """Confirma que o servidor está pronto pra se comunicar com o Tasker."""
    return jsonify({
        "ok": True,
        "tasker_pronto": True,
        "acoes_pendentes": _fila_acoes_android.qsize(),
        "mensagem": "Servidor Emily pronto para integração com Tasker."
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