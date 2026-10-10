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
import re
import threading
import time
import uuid
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# A nuvem possui autenticação obrigatória própria e trabalha só com IDs.
try:
    from emily_cloud.routes import registrar as _registrar_rotas_cloud
    _registrar_rotas_cloud(app)
except Exception as _erro_cloud:
    print(f"[EMILY-CLOUD] rotas remotas indisponíveis: {_erro_cloud}")

# Essa função é injetada pelo main.py quando o servidor sobe
# Ela aponta para processar_texto_digitado do main.py
_callback_processar = None
_visual_monitor_lock = threading.RLock()
_visual_monitor_action_id = ""
_visual_monitor_instance_id = uuid.uuid4().hex

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


@app.route("/pc/visual-monitor", methods=["POST"])
def visual_monitor():
    """Ponte local autenticada para ações visuais iniciadas pelo Android."""
    if not _ponte_token_ok():
        return jsonify({"ok": False, "mensagem": "token inválido"}), 401
    if _callback_processar is None:
        return jsonify({"ok": False, "mensagem": "Emily desktop ainda não está pronta"}), 503
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "mensagem": "pedido inválido"}), 400
    operation = str(data.get("operation") or "")
    if operation not in {"status", "start", "message", "cancel"}:
        return jsonify({"ok": False, "mensagem": "operação inválida"}), 400
    import agente_ui
    global _visual_monitor_action_id
    with _visual_monitor_lock:
        state = agente_ui.estado_agente_ui()
        if operation == "status":
            return jsonify({"ok": True, "action_id": _visual_monitor_action_id,
                            "instance_id": _visual_monitor_instance_id, "estado": state})
        action_id = str(data.get("action_id") or "").strip()
        if not re.fullmatch(r"[a-f0-9-]{8,80}", action_id):
            return jsonify({"ok": False, "mensagem": "identificador inválido"}), 400
        if operation == "cancel":
            if action_id != _visual_monitor_action_id:
                return jsonify({"ok": False, "mensagem": "ação visual não encontrada"}), 409
            if state.get("ativo"):
                agente_ui.parar_agente_ui()
            return jsonify({"ok": True, "action_id": action_id,
                            "instance_id": _visual_monitor_instance_id,
                            "estado": agente_ui.estado_agente_ui()})
        if operation == "message":
            message = str(data.get("message") or "").strip()
            if action_id != _visual_monitor_action_id or not state.get("ativo") or not message or len(message) > 800:
                return jsonify({"ok": False, "mensagem": "tarefa visual não está ativa"}), 409
            accepted = agente_ui.enviar_mensagem_ao_vivo(message)
            return jsonify({"ok": bool(accepted), "action_id": action_id,
                            "instance_id": _visual_monitor_instance_id,
                            "estado": agente_ui.estado_agente_ui()})
        objective = str(data.get("objective") or "").strip()
        if not objective or len(objective) > 800:
            return jsonify({"ok": False, "mensagem": "objetivo inválido"}), 400
        if action_id == _visual_monitor_action_id:
            return jsonify({"ok": True, "action_id": action_id, "estado": state,
                            "instance_id": _visual_monitor_instance_id,
                            "mensagem": "tarefa já recebida"})
        if state.get("ativo"):
            return jsonify({"ok": False, "mensagem": "a Emily já está usando o agente visual",
                            "estado": state}), 409
        result = agente_ui.iniciar_agente_ui(objective)
        state = agente_ui.estado_agente_ui()
        if state.get("objetivo") != objective or not state.get("ativo"):
            return jsonify({"ok": False, "mensagem": result, "estado": state}), 503
        _visual_monitor_action_id = action_id
        return jsonify({"ok": True, "action_id": action_id, "mensagem": result,
                        "instance_id": _visual_monitor_instance_id, "estado": state})


# ─────────────────────────────────────────────────────────────────
# UPLOAD DE ARQUIVOS / IMAGENS
# ─────────────────────────────────────────────────────────────────

# Pasta onde os uploads ficam salvos temporariamente
from emily_paths import arquivo_dados as _arquivo_dados
_UPLOAD_DIR = str(_arquivo_dados("uploads_emily"))

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
# PONTE PARA A EMILY DO CELULAR (cérebro Claude + busca web)
#
# O celular não alcança o proxy Kiro (localhost:20128) nem a chave da
# Brave que ficam aqui no PC. Essas rotas deixam o app usar o MESMO
# Claude da Emily do PC: o celular conversa com este servidor (rede
# local ou Ngrok) e daqui o pedido é repassado pra dentro.
#
#   POST /llm/chat   → repassa um pedido OpenAI-compatível pro proxy
#   POST /llm/busca  → busca web real (Brave Search API), com fontes
#   GET  /llm/status → vivo? modelos? busca pronta? (painel do app)
#
# Opcional: defina EMILY_PONTE_TOKEN no .env pra exigir
# Authorization: Bearer <token> nessas rotas (recomendado com Ngrok).
# Sem a variável, as rotas ficam abertas (confiança da rede local).
# ─────────────────────────────────────────────────────────────────

import re as _re_ponte
import requests as _requests
from requests.adapters import HTTPAdapter as _HTTPAdapter


# Uma conversa do modo agente faz várias chamadas seguidas ao mesmo proxy.
# requests.post() avulso criava uma conexão TCP/TLS nova em cada rodada; a
# Session mantém o pool vivo e elimina esse custo entre decisão, ferramenta e
# resposta final. O adapter também deixa folga para Android, PC e rotinas em
# background usarem a ponte ao mesmo tempo.
_PONTE_HTTP = _requests.Session()
_PONTE_HTTP.mount("http://", _HTTPAdapter(pool_connections=8, pool_maxsize=16))
_PONTE_HTTP.mount("https://", _HTTPAdapter(pool_connections=8, pool_maxsize=16))


def _carregar_env_ponte():
    """Lê o .env daqui do PC sem depender do dotenv (chave=valor simples)."""
    valores = {}
    caminho_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(caminho_env, "r", encoding="utf-8") as _f:
            for _linha in _f:
                _m = _re_ponte.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", _linha.strip())
                if _m:
                    valores[_m.group(1)] = _m.group(2).strip()
    except OSError:
        pass
    return valores


_ENV_PONTE = _carregar_env_ponte()

_PONTE_CLAUDE_BASE = (_ENV_PONTE.get("EMILY_PROVEDOR_CLAUDE_BASE") or os.getenv("EMILY_PROVEDOR_CLAUDE_BASE", "")).rstrip("/")
_PONTE_CLAUDE_CHAVE = _ENV_PONTE.get("EMILY_PROVEDOR_CLAUDE_CHAVE") or os.getenv("EMILY_PROVEDOR_CLAUDE_CHAVE", "")
_PONTE_MODELO_PADRAO = _ENV_PONTE.get("EMILY_PROVEDOR_CLAUDE_MODELO") or os.getenv("EMILY_PROVEDOR_CLAUDE_MODELO", "")
_PONTE_MODELOS = [m.strip() for m in (_ENV_PONTE.get("EMILY_PROVEDOR_CLAUDE_MODELOS") or os.getenv("EMILY_PROVEDOR_CLAUDE_MODELOS", "")).split(",") if m.strip()]
if _PONTE_MODELO_PADRAO and _PONTE_MODELO_PADRAO not in _PONTE_MODELOS:
    _PONTE_MODELOS.insert(0, _PONTE_MODELO_PADRAO)
_PONTE_BRAVE_KEY = _ENV_PONTE.get("BRAVE_API_KEY") or os.getenv("BRAVE_API_KEY", "")
_PONTE_TOKEN = _ENV_PONTE.get("EMILY_PONTE_TOKEN") or os.getenv("EMILY_PONTE_TOKEN", "")

import socket as _socket_ponte


def _ip_da_rede_ponte() -> str:
    """IP LAN do PC (o celular usa pra achar o tela-pc.service na porta 8790
    sem depender da URL local salva — resolve IP velho de DHCP). UDP 'connect'
    não envia pacote: só escolhe a rota padrão e devolve a origem dela."""
    _s = _socket_ponte.socket(_socket_ponte.AF_INET, _socket_ponte.SOCK_DGRAM)
    try:
        _s.connect(("8.8.8.8", 80))
        return _s.getsockname()[0]
    except Exception:
        return ""
    finally:
        _s.close()


_PONTE_IP_REDE = _ip_da_rede_ponte()


def _ponte_token_ok():
    """Se EMILY_PONTE_TOKEN estiver definido, exige Bearer igual."""
    if not _PONTE_TOKEN:
        return True
    return request.headers.get("Authorization", "") == f"Bearer {_PONTE_TOKEN}"


def _achatar_messages_ponte(messages):
    """
    O celular manda conteúdo em blocos (estilo OpenRouter/Anthropic, com
    cache_control). O proxy Kiro fala OpenAI puro, então achata: blocos de
    texto viram uma string única e blocos de imagem (image_url) são
    preservados no formato que o endpoint OpenAI-compatible espera.
    """
    saida = []
    for msg in messages:
        if not isinstance(msg, dict):
            saida.append(msg)
            continue
        conteudo = msg.get("content")
        if isinstance(conteudo, list):
            textos = []
            imagens = []
            for bloco in conteudo:
                if not isinstance(bloco, dict):
                    continue
                if bloco.get("type") == "text":
                    textos.append(bloco.get("text", ""))
                elif bloco.get("type") == "image_url":
                    imagens.append({"type": "image_url", "image_url": bloco.get("image_url", {})})
            msg = dict(msg)
            if imagens:
                novo = [{"type": "text", "text": "\n\n".join(textos)}] if textos else []
                msg["content"] = novo + imagens
            else:
                msg["content"] = "\n\n".join(textos)
        saida.append(msg)
    return saida


def _preparar_cache_ponte(body):
    """Preserva cache_control só para upstream explicitamente compatível.

    O proxy Kiro atual fala OpenAI-compatible e não documenta esse campo. O
    padrão seguro segue achatando; um proxy compatível pode ser habilitado com
    EMILY_PONTE_PROMPT_CACHE=1 sem mudar o contrato do Android.
    """
    habilitado = (_ENV_PONTE.get("EMILY_PONTE_PROMPT_CACHE") or
                  os.getenv("EMILY_PONTE_PROMPT_CACHE", "0")).strip() == "1"
    if not habilitado:
        body["messages"] = _achatar_messages_ponte(body.get("messages") or [])
        for ferramenta in body.get("tools") or []:
            if isinstance(ferramenta, dict):
                ferramenta.pop("cache_control", None)
    return habilitado


@app.route("/llm/chat", methods=["POST"])
def ponte_llm_chat():
    """Repassa um pedido de chat (formato OpenAI) pro proxy Claude do PC."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    if not _PONTE_CLAUDE_BASE or not _PONTE_CLAUDE_CHAVE:
        return jsonify({"erro": "provedor claude não configurado no .env do PC"}), 503
    corpo = request.get_json(silent=True) or {}
    cache_solicitado = _preparar_cache_ponte(corpo)
    pedido_stream = bool(corpo.pop("stream", False))
    inicio = time.monotonic()

    if not pedido_stream:
        try:
            resp = _PONTE_HTTP.post(
                f"{_PONTE_CLAUDE_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {_PONTE_CLAUDE_CHAVE}"},
                json=corpo,
                timeout=180,
            )
        except Exception as e:
            return jsonify({"erro": f"proxy Kiro indisponível: {e}"}), 502
        duracao_ms = int((time.monotonic() - inicio) * 1000)
        try:
            uso = (resp.json().get("usage") or {}) if resp.ok else {}
        except Exception:
            uso = {}
        detalhes = uso.get("prompt_tokens_details") or {}
        cache_lidos = detalhes.get("cached_tokens") or uso.get("cache_read_input_tokens") or 0
        cache_criados = uso.get("cache_creation_input_tokens") or 0
        print(
            f"[PONTE-LLM] {corpo.get('model', '?')} respondeu em {duracao_ms}ms "
            f"(status={resp.status_code}, mensagens={len(corpo.get('messages') or [])}, "
            f"ferramentas={len(corpo.get('tools') or [])}, cache_solicitado={int(cache_solicitado)}, "
            f"cache_lidos={cache_lidos}, cache_criados={cache_criados})"
        )
        return (
            resp.text,
            resp.status_code,
            {
                "Content-Type": "application/json",
                "Server-Timing": f"upstream;dur={duracao_ms}",
                "X-Emily-Upstream-Ms": str(duracao_ms),
            },
        )

    # ── Streaming: retransmite o SSE cru do upstream, token a token. ────────
    # NÃO chama resp.json() nem parseia nada: cada linha ("data: {...}" e
    # "data: [DONE]") sai aqui na hora que chega — quem monta a resposta final
    # é o parser do celular (PonteClaudeClient.chatCompletionStream). Erro de
    # HTTP antes de abrir o fluxo volta como JSON de erro normal, que o
    # cliente já sabe tratar.
    try:
        resp = _PONTE_HTTP.post(
            f"{_PONTE_CLAUDE_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {_PONTE_CLAUDE_CHAVE}",
                "Accept": "text/event-stream",
            },
            json=corpo,
            stream=True,
            timeout=(10, 300),   # 10s pra abrir a conexão; leitura fica solta por evento
        )
    except Exception as e:
        return jsonify({"erro": f"proxy Kiro indisponível: {e}"}), 502
    if resp.status_code != 200:
        detalhe = resp.text[:300]
        resp.close()
        return jsonify({"erro": f"proxy Kiro respondeu {resp.status_code}: {detalhe}"}), 502
    resp.encoding = "utf-8"   # iter_lines(decode_unicode=True) sem adivinhar codec

    def _retransmitir():
        try:
            for linha in resp.iter_lines(chunk_size=1, decode_unicode=True):
                if linha is None:
                    continue
                # O Android já fala SSE: a linha sai crua (com o "data:" e o
                # "[DONE]") — um \n por linha mantém o framing que ele espera.
                yield f"{linha}\n"
            print(
                f"[PONTE-LLM] {corpo.get('model', '?')} stream completo em "
                f"{int((time.monotonic() - inicio) * 1000)}ms "
                f"(mensagens={len(corpo.get('messages') or [])}, "
                f"ferramentas={len(corpo.get('tools') or [])}, "
                f"cache_solicitado={int(cache_solicitado)})"
            )
        finally:
            resp.close()

    return Response(
        _retransmitir(),
        status=200,
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache",
            # Proxies (ngrok incluso) às vezes bufferizam SSE; isso pede flush.
            "X-Accel-Buffering": "no",
            "X-Emily-Upstream-Ms": str(int((time.monotonic() - inicio) * 1000)),
        },
    )


@app.route("/llm/busca", methods=["POST"])
def ponte_llm_busca():
    """Busca web real (Brave Search API) usando a chave daqui do PC."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True) or {}
    consulta = (dados.get("query") or "").strip()
    try:
        max_resultados = max(1, min(10, int(dados.get("max", 5))))
    except (TypeError, ValueError):
        max_resultados = 5
    if not consulta:
        return jsonify({"erro": "query vazia"}), 400
    if not _PONTE_BRAVE_KEY:
        return jsonify({"erro": "BRAVE_API_KEY não configurada no .env do PC"}), 503
    try:
        resp = _requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": consulta, "count": max_resultados, "country": "BR"},
            headers={"Accept": "application/json", "X-Subscription-Token": _PONTE_BRAVE_KEY},
            timeout=15,
        )
        if not resp.ok:
            return jsonify({"erro": f"Brave {resp.status_code}: {resp.text[:200]}"}), 502
        resultados = []
        for item in (resp.json().get("web") or {}).get("results") or []:
            resultados.append({
                "titulo": item.get("title") or item.get("url") or "",
                "url": item.get("url") or "",
                "resumo": item.get("description") or "",
            })
        return jsonify({"ok": True, "resultados": resultados})
    except Exception as e:
        return jsonify({"erro": f"busca falhou: {e}"}), 502


@app.route("/llm/status")
def ponte_llm_status():
    """Status do cérebro remoto — usado no painel de configurações do app."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    proxy_vivo = False
    if _PONTE_CLAUDE_BASE and _PONTE_CLAUDE_CHAVE:
        try:
            _r = _requests.get(
                f"{_PONTE_CLAUDE_BASE}/models",
                headers={"Authorization": f"Bearer {_PONTE_CLAUDE_CHAVE}"},
                timeout=4,
            )
            proxy_vivo = _r.status_code < 500  # respondeu (mesmo 401/404) = tem coisa viva lá
        except Exception:
            proxy_vivo = False
    return jsonify({
        "ok": True,
        "emily_pronta": _callback_processar is not None,
        "proxy_vivo": proxy_vivo,
        "modelo_padrao": _PONTE_MODELO_PADRAO,
        "modelos": _PONTE_MODELOS,
        "busca_ok": bool(_PONTE_BRAVE_KEY),
        # O celular cacheia isso pra achar o tela-pc.service (porta 8790)
        # direto, mesmo com a Emily desligada depois.
        "ip_rede": _PONTE_IP_REDE,
    })

# ────────────────────────────────────────────────────────────────
# PROVEDORES PRA PONTE — o celular vê o MESMO catálogo que o PC
#
# A Emily do celular hoje fala com o provedor "Anthropic e OpenAI" (seção
# [provedor: claude] no .env: proxy local que serve Claude E GPT). Esta rota
# expõe nome de exibição, modelo padrão e a lista de EMILY_PROVEDOR_CLAUDE_MODELOS
# com rótulos legíveis — a mesma fonte que o seletor da interface do PC usa.
# O /llm/chat já repassa o campo "model" cru pro proxy, então o app pode
# escolher qualquer modelo da lista sem mais nenhuma mudança aqui.
# ────────────────────────────────────────────────────────────────

def _rotulo_modelo_ponte(modelo_id: str) -> str:
    """ID técnico -> rótulo legível. Mesma ideia do _nome_limpo_modelo do
    llm.py, enxuta pros formatos que o .env do Vitor tem (kr/claude-4.5,
    antigravity/claude-4-6, cx/gpt-5.6-terra...)."""
    texto = (modelo_id or "").strip()
    if "/" in texto:
        texto = texto.split("/", 1)[1]
    texto = texto.replace("-", " ")
    # número-hifen-numero -> ponto (4.5, 5.6, 4.6)
    texto = _re_ponte.sub(r"(\d)\s(\d)", r"\1.\2", texto)
    # letras coladas em número -> espaço (gpt 5.6)
    texto = _re_ponte.sub(r"([A-Za-z]{2,})(\d)", r"\1 \2", texto)
    mapa = {
        "claude": "Claude", "sonnet": "Sonnet", "haiku": "Haiku", "opus": "Opus",
        "gpt": "GPT", "terra": "Terra", "luna": "Luna", "sol": "Sol",
    }
    partes = []
    for tok in texto.split():
        partes.append(mapa.get(tok.lower(), tok[:1].upper() + tok[1:] if tok else tok))
    return " ".join(partes) or (modelo_id or "")


@app.route("/llm/provedores")
def ponte_llm_provedores():
    """Catálogo de provedores/modelos pro seletor do celular."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    modelos = []
    for i, mid in enumerate(_PONTE_MODELOS):
        mid = mid.strip()
        if not mid:
            continue
        modelos.append({
            "id": mid,
            "nome": _rotulo_modelo_ponte(mid),
            # Mesma semântica da interface do PC: 1º = padrão, demais numerados.
            "sobre": "Anthropic e OpenAI" if i == 0 else f"Anthropic e OpenAI · {i + 1}º",
        })
    return jsonify({
        "ok": True,
        "provedores": [
            {
                "id": "claude",
                "nome": _ENV_PONTE.get("EMILY_PROVEDOR_CLAUDE_NOME") or "Anthropic e OpenAI",
                "padrao": _PONTE_MODELO_PADRAO,
                "modelos": modelos,
            }
        ],
    })


# ────────────────────────────────────────────────────────────────
# SINCRONIZAÇÃO DE CHATS (celular ↔ PC)


# ────────────────────────────────────────────────────────────────
# SINCRONIZAÇÃO DE CHATS (celular ↔ PC)
#
# O celular puxa/empurra conversas por aqui; tudo passa pelo módulo
# conversas.py — o MESMO arquivo (~/.emily_conversas.json) que a interface
# do PC usa. Chats criados de qualquer lado aparecem nos dois.
#
#   GET    /chats/delta?desde=<seg>  → metadados mexidos desde [desde] + apagadas
#   GET    /chats/abrir/<id>         → conversa completa (mensagens)
#   POST   /chats/gravar             → upsert de conversa inteira (LWW no PC)
#   DELETE /chats/apagar/<id>        → apaga (e registra tombstone)
# ────────────────────────────────────────────────────────────────

import conversas as _conversas
import memoria as _memoria


@app.route("/chats/delta")
def chats_delta():
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    try:
        desde = float(request.args.get("desde", 0))
    except (TypeError, ValueError):
        desde = 0.0
    conversas = [c for c in _conversas.listar() if c.get("mexida", 0) > desde]
    apagadas = [a for a in _conversas.listar_apagadas() if a.get("quando", 0) > desde]
    return jsonify({
        "ok": True,
        "agora": time.time(),
        "conversas": conversas,
        "apagadas": apagadas,
    })


@app.route("/chats/abrir/<cid>")
def chats_abrir(cid):
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    meta = next((c for c in _conversas.listar() if c.get("id") == cid), None)
    if meta is None:
        return jsonify({"ok": False, "erro": "conversa não encontrada"}), 404
    return jsonify({
        "ok": True,
        "id": cid,
        "titulo": meta["titulo"],
        "criada": meta["criada"],
        "mexida": meta["mexida"],
        "ramo": meta.get("ramo", 0),
        "mensagens": _conversas.abrir(cid),
    })


@app.route("/chats/gravar", methods=["POST"])
def chats_gravar():
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    corpo = request.get_json(silent=True) or {}
    try:
        ok = _conversas.gravar_externa(
            cid=str(corpo.get("id") or "").strip(),
            titulo=str(corpo.get("titulo") or ""),
            criada=float(corpo.get("criada") or 0),
            mexida=float(corpo.get("mexida") or 0),
            mensagens=corpo.get("mensagens") or [],
            ramo=int(corpo.get("ramo") or 0),
        )
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "erro": f"payload inválido: {e}"}), 400
    return jsonify({"ok": ok, "pc_mais_novo": not ok})


@app.route("/chats/apagar/<cid>", methods=["DELETE"])
def chats_apagar(cid):
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    _conversas.apagar(cid)   # idempotente: apagar o que não existe não é erro
    return jsonify({"ok": True})


# ────────────────────────────────────────────────────────────────
# SINCRONIZAÇÃO DE MEMÓRIA (fatos sobre o Vitor, celular ↔ PC)
#
# Uma chamada só resolve as duas direções: o celular manda o estado dele,
# o PC une tudo em memoria.py (união por hash + tombstones) e devolve o
# estado final — que o celular assume por inteiro.
# ────────────────────────────────────────────────────────────────

@app.route("/memoria/sync", methods=["POST"])
def memoria_sync():
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    corpo = request.get_json(silent=True) or {}
    try:
        estado = _memoria.sincronizar_externa(
            fatos_externos=corpo.get("fatos") or [],
            apagados_externos=corpo.get("apagados") or {},
        )
    except Exception as e:
        return jsonify({"ok": False, "erro": f"sync falhou: {e}"}), 500
    return jsonify({"ok": True, "agora": time.time(), **estado})


# ──────────────────────────────────────────────────────────
# MODO REMOTO (botão do chat: o comando vai pro dispositivo oposto)
#
#   PC → celular: a interface enfileira via /remota/para_celular e o celular
#                  executa com as ferramentas dele (polling /android/acao).
#   celular → PC: POST /remota/para_pc roda o turno completo da Emily do PC
#                  (processar_texto_digitado) e captura a resposta do turno.
# O texto e a resposta ficam registrados na conversa aberta (conversas.py),
# então aparecem no histórico dos dois lados (chats já sincronizados).
# ───────────────────────────────────────────────────────────────

_remota_lock = threading.Lock()
_remota_resposta = {"texto": "", "ts": 0.0}   # resposta capturada do turno (celular → PC)
_pendentes_celular = {}                       # id → {evento, texto} (PC → celular)
_remota_cb_inicio = None                      # main.py: zera o acumulador de frases
_remota_cb_fim = None                         # main.py: entrega o texto capturado


def definir_callbacks_remota(inicio_fn, fim_fn):
    """main.py registra como o servidor avisa início/fim de um turno remoto."""
    global _remota_cb_inicio, _remota_cb_fim
    _remota_cb_inicio = inicio_fn
    _remota_cb_fim = fim_fn


def entregar_resposta_remota(texto: str) -> None:
    """main.py entrega o texto da resposta capturada do turno."""
    with _remota_lock:
        _remota_resposta["texto"] = texto
        _remota_resposta["ts"] = time.time()


def enviar_comando_remoto_ao_celular(texto: str, timeout: float = 300.0):
    """PC → celular: enfileira a ação e espera a resposta. Devolve (ok, texto).

    300s e não menos: a Emily do celular pode rodar um laço de ferramentas com
    várias chamadas de LLM — minutos são normais. Com 150s o PC dava timeout e
    descartava o pendente antes de a resposta chegar.
    """
    import uuid as _uuid
    rid = _uuid.uuid4().hex[:12]
    ev = threading.Event()
    with _remota_lock:
        _pendentes_celular[rid] = {"evento": ev, "texto": ""}
    enviar_acao_android("comando_remoto", {"texto": texto, "id": rid})
    if not ev.wait(timeout):
        with _remota_lock:
            _pendentes_celular.pop(rid, None)
        return False, "O celular não respondeu a tempo (app aberto e conectado?)."
    with _remota_lock:
        item = _pendentes_celular.pop(rid, None)
    return True, (item or {}).get("texto", "Feito!")


@app.route("/remota/para_celular", methods=["POST"])
def remota_para_celular():
    """Enfileira um comando pro celular executar (teste via curl; a interface
    chama enviar_comando_remoto_ao_celular direto — mesmo processo)."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True) or {}
    texto = str(dados.get("texto") or "").strip()
    if not texto:
        return jsonify({"ok": False, "erro": "texto vazio"}), 400
    enviar_acao_android("comando_remoto", {"texto": texto})
    return jsonify({"ok": True})


_callback_resposta_remota = None


def definir_callback_resposta_remota(fn):
    """main.py registra como mostrar a resposta que o celular devolveu.
    (No fluxo atual a entrega é feita pelo waiter de enviar_comando_
    remoto_ao_celular; o callback fica como caminho alternativo.)"""
    global _callback_resposta_remota
    _callback_resposta_remota = fn


_callback_progresso_remota = None


def definir_callback_progresso_remota(fn):
    """main.py registra a janela: os passos das ferramentas do CELULAR
    (reportados via /remota/progresso durante um comando remoto) aparecem
    no painel de progresso da interface — a mesma animação de tool calling
    que os turnos locais já mostram."""
    global _callback_progresso_remota
    _callback_progresso_remota = fn


@app.route("/remota/progresso", methods=["POST"])
def remota_progresso():
    """O celular reporta um passo da execução remota (ferramenta, resultado
    ou fim) e o PC retransmite pro painel de progresso da interface."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True) or {}
    fase = str(dados.get("fase") or "").strip()
    if not fase:
        return jsonify({"ok": False, "erro": "fase vazia"}), 400
    conteudo = dados.get("dados") or {}
    fn = _callback_progresso_remota
    if fn is not None:
        try:
            fn(fase, conteudo)
        except Exception as e:  # noqa: BLE001
            print(f"[REMOTA] progresso do celular falhou: {e}")
    return jsonify({"ok": True})


@app.route("/remota/resposta", methods=["POST"])
def remota_resposta():
    """O celular entrega a resposta do comando que o PC mandou executar lá."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True) or {}
    rid = str(dados.get("id") or "")
    texto = str(dados.get("texto") or "")
    with _remota_lock:
        item = _pendentes_celular.get(rid)
        if item is not None:
            item["texto"] = texto
            item["evento"].set()
    return jsonify({"ok": True})


@app.route("/remota/para_pc", methods=["POST"])
def remota_para_pc():
    """
    Celular → PC (modo remoto): roda o turno completo da Emily daqui e devolve
    o texto da resposta. Demora: é o processamento de verdade (ferramentas,
    LLM, automação), por isso timeout longo no cliente.
    """
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    dados = request.get_json(silent=True) or {}
    texto = str(dados.get("texto") or "").strip()
    if not texto:
        return jsonify({"ok": False, "erro": "texto vazio"}), 400
    if _callback_processar is None:
        return jsonify({"ok": False, "erro": "Emily do PC ainda não iniciou."}), 503

    with _remota_lock:
        _remota_resposta["texto"] = ""
        _remota_resposta["ts"] = 0.0
    if _remota_cb_inicio:
        _remota_cb_inicio()
    _callback_processar(texto)   # turno completo, síncrono (thread do Flask)
    if _remota_cb_fim:
        _remota_cb_fim()
    with _remota_lock:
        resposta = _remota_resposta["texto"]
    if not resposta:
        resposta = "NÃO consegui capturar a resposta da Emily do PC (turno sem fala?)."
    return jsonify({"ok": True, "texto": resposta})

# ─────────────────────────────────────────────────────────────────
# TELA DO PC PRO CELULAR (botão 🖥 do chat: ver o monitor pelo app)
# ─────────────────────────────────────────────────────────────────

@app.route("/tela/monitores")
def tela_monitores():
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    try:
        import tela_stream
        return jsonify({"ok": True, "monitores": tela_stream.listar_monitores()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)[:200]}), 500


@app.route("/tela/jpg")
def tela_jpg():
    """Um quadro do monitor pedido. Cadência real: ~1 fps (Wayland)."""
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    try:
        import tela_stream
        monitor = int(request.args.get("monitor", "1"))
        largura = min(1600, max(320, int(request.args.get("largura", "960"))))
        qualidade = min(90, max(35, int(request.args.get("q", "62"))))
        jpeg, idade = tela_stream.capturar_jpeg(
            monitor, largura, qualidade,
            unico=request.args.get("unico") == "1",
        )
        resp = Response(jpeg, mimetype="image/jpeg")
        resp.headers["X-Emily-Idade"] = f"{idade:.1f}"
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except ValueError as e:
        return jsonify({"ok": False, "erro": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False,
                        "erro": f"não consegui capturar a tela: {e}"}), 500


@app.route("/tela/estado")
def tela_estado():
    if not _ponte_token_ok():
        return jsonify({"erro": "token inválido"}), 401
    try:
        import tela_stream
        return jsonify({"ok": True, **tela_stream.estado()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)[:200]}), 500


# ─────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────

def iniciar_servidor(porta=None):
    """
    Inicia o servidor Flask em background.
    Chamado pelo main.py numa thread separada.
    """
    import os
    import logging

    # Silencia os logs do Flask no terminal da Emily
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    # A porta pública 5000 agora pertence ao emily-gateway.service. Ele mantém
    # /llm/* vivo com a Emily fechada e encaminha o restante pra esta porta
    # interna. Loopback impede acesso direto que contorne o gateway.
    if porta is None:
        porta = int(os.getenv("EMILY_BACKEND_PORTA", "5001"))
    print(f"[SERVIDOR] Backend interno na porta {porta} (gateway público: 5000)")

    # use_reloader=False é importante pra não criar thread duplicada
    app.run(host="127.0.0.1", port=porta, debug=False, use_reloader=False)


@app.post("/internal/cloud/tool")
def cloud_tool():
    import hmac
    expected = os.getenv("EMILY_CLOUD_RPC_KEY", "")
    supplied = request.headers.get("X-Emily-Cloud-Key", "")
    if not _ponte_token_ok() or not expected or not hmac.compare_digest(expected, supplied):
        return jsonify(erro="Não autorizado"), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("argumentos", {}), dict):
        return jsonify(erro="Pedido inválido"), 400
    from ferramentas import executar_estruturado
    from dataclasses import asdict
    return jsonify(asdict(executar_estruturado(str(data.get("nome", "")), data.get("argumentos", {}), data.get("contexto") or {})))
