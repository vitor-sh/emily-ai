#!/usr/bin/env python3
"""Gateway permanente entre o celular, a Emily desktop e o OmniRoute.

Portas:
  5000  entrada estável (LAN/Ngrok/celular)
  5001  servidor interno da Emily desktop (quando ela estiver aberta)
  20128 OmniRoute (upstream de LLM, nunca exposto pelo APK)

As rotas /llm/*, /cloud/* e /pc/* funcionam sem a Emily desktop. A Cloud usa
diretamente o mesmo SQLite/acervo local da interface do PC. As demais rotas são
encaminhadas para a porta 5001 e voltam com 503 quando a Emily está fechada.
"""

from __future__ import annotations

import hmac
import json
import atexit
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, request, stream_with_context, send_file

PASTA_SERVICO = Path(__file__).resolve().parent
if str(PASTA_SERVICO) not in sys.path:
    sys.path.insert(0, str(PASTA_SERVICO))

try:
    if os.name == "nt":
        from pc_control_windows import WindowsPCController as PCController
    else:
        from pc_control import PCController
except ImportError:  # import por caminho em testes/IDE
    PCController = None  # type: ignore[assignment,misc]

try:
    from browser_bridge import BrowserBridge, guardar_download_da_extensao
except ImportError:  # import por caminho em testes/IDE
    BrowserBridge = None  # type: ignore[assignment,misc]
    guardar_download_da_extensao = None  # type: ignore[assignment]

from android_push import salvar_token as salvar_push_token, enviar as enviar_push, enviar_dados as enviar_push_dados


APP = Flask(__name__)
PASTA_PROJETO = Path(__file__).resolve().parent.parent
if str(PASTA_PROJETO) not in sys.path:
    sys.path.insert(0, str(PASTA_PROJETO))
PASTA_ATUALIZACAO_ANDROID = Path.home() / ".local/share/emily/android-updates"
PASTA_ATUALIZACAO_WINDOWS_CODIGO = Path.home() / ".local/share/emily/windows-code-updates"
PASTA_ATUALIZACAO_WINDOWS = Path.home() / ".local/share/emily/windows-updates"
CAMINHO_ENV = PASTA_PROJETO / ".env"

PORTA = int(os.getenv("EMILY_GATEWAY_PORTA", "5000"))
EMILY_INTERNA = os.getenv("EMILY_BACKEND_URL", "http://127.0.0.1:5001").rstrip("/")
MAX_CORPO = int(os.getenv("EMILY_GATEWAY_MAX_CORPO", str(24 * 1024 * 1024)))

_sessao = requests.Session()
_env_lock = threading.RLock()
_env_mtime = -1
_env: dict[str, str] = {}
_pc_controller = None
_browser_bridge = None

_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host",
}


def _log(mensagem: str) -> None:
    print(f"[EMILY-GATEWAY] {mensagem}", flush=True)


def _ler_env() -> dict[str, str]:
    """Lê chave=valor simples e recarrega automaticamente após edição do .env."""
    global _env_mtime, _env
    try:
        mtime = CAMINHO_ENV.stat().st_mtime_ns
    except OSError:
        mtime = -1
    with _env_lock:
        if mtime == _env_mtime:
            return dict(_env)
        valores: dict[str, str] = {}
        try:
            for linha in CAMINHO_ENV.read_text(encoding="utf-8").splitlines():
                achado = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", linha.strip())
                if achado:
                    valor = achado.group(2).strip()
                    if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                        valor = valor[1:-1]
                    valores[achado.group(1)] = valor
        except OSError as exc:
            _log(f"não consegui ler {CAMINHO_ENV}: {exc}")
        # Os módulos independentes (Emily Cloud/S3) consultam os.getenv em
        # runtime. Espelhar o .env no processo mantém uma fonte de configuração
        # só e, principalmente, faz EMILY_CLOUD_DIR ser conhecido ANTES de o
        # core calcular BASE/DB/OBJECTS no import.
        os.environ.update(valores)
        _env = valores
        _env_mtime = mtime
        _log(f"configuração recarregada ({len(valores)} variáveis)")
        return dict(_env)


# Emily Cloud vive no MESMO acervo local da interface desktop (SQLite +
# objetos por SHA-256), mas as rotas são registradas também neste gateway
# permanente. Assim o celular continua vendo/alterando os mesmos arquivos
# quando a Emily desktop está fechada; não existe uma segunda cópia pra
# sincronizar nem risco de conflito entre dois bancos.
def _registrar_cloud_permanente() -> None:
    try:
        import sys as _sys
        _ler_env()  # precisa acontecer antes de importar emily_cloud.core
        if str(PASTA_PROJETO) not in _sys.path:
            _sys.path.insert(0, str(PASTA_PROJETO))
        from emily_cloud.routes import registrar as _registrar_rotas_cloud
        _registrar_rotas_cloud(APP)
        _log("Emily Cloud permanente registrada em /cloud/*")
    except Exception as exc:
        _log(f"Emily Cloud permanente indisponível: {exc}")


_registrar_cloud_permanente()


@APP.before_request
def _atualizar_config_antes_do_pedido():
    """Mantém token/S3/Cloud alinhados ao .env sem reiniciar o serviço."""
    _ler_env()


def _cfg(nome: str, padrao: str = "") -> str:
    return _ler_env().get(nome) or os.getenv(nome, padrao)


def _iniciar_controle_pc_permanente() -> None:
    """Sobe executor e WebSocket da extensão no mesmo processo permanente."""
    global _pc_controller, _browser_bridge
    if PCController is None:
        _log("executor estruturado do PC indisponível")
        return
    _pc_controller = PCController(
        token_provider=lambda: _cfg("EMILY_PONTE_TOKEN"),
        energia_habilitada=lambda: _cfg("EMILY_ENERGIA_HABILITADA", "0").strip() == "1",
    )
    if os.getenv("EMILY_BROWSER_PERMANENTE", "1").strip() == "0":
        _log("ponte permanente do navegador desativada por configuração")
        return
    if BrowserBridge is None:
        _log("ponte WebSocket do navegador indisponível")
        return
    try:
        _browser_bridge = BrowserBridge(
            token_provider=lambda: _cfg("EMILY_PONTE_TOKEN"),
            host="127.0.0.1",
            port=int(_cfg("EMILY_BROWSER_PORTA", "8765")),
            download_handler=guardar_download_da_extensao,
        )
        _browser_bridge.iniciar()
        _pc_controller.definir_browser_bridge(_browser_bridge)
        _log("ponte permanente do navegador em ws://127.0.0.1:8765 (autenticada)")
    except Exception as exc:
        _browser_bridge = None
        _log(f"ponte permanente do navegador indisponível: {exc}")


def _encerrar_controle_pc_permanente() -> None:
    if _browser_bridge is not None:
        try:
            _browser_bridge.encerrar()
        except Exception:
            pass


_iniciar_controle_pc_permanente()
atexit.register(_encerrar_controle_pc_permanente)


PROVEDORES_LLM = ("claude", "openai", "omniroute")


def _prefixo_provedor(provedor: str) -> str:
    return f"EMILY_PROVEDOR_{provedor.upper()}"


def _url_com_v1(base: str) -> str:
    """Normaliza bases OpenAI-compatible, aceitando configuração com ou sem /v1."""
    base = (base or "").rstrip("/")
    if not base:
        return base
    return base if base.endswith("/v1") else f"{base}/v1"


def _modelos_provedor(provedor: str) -> list[str]:
    prefixo = _prefixo_provedor(provedor)
    if provedor == 'claude':
        from limites_modelos import catalogo
        import llm
        configured=llm.PROVEDORES_CONFIG.get(provedor)
        live=catalogo(provedor) if configured and _url_com_v1(configured.base_url)==_url_com_v1(_cfg(f"{_prefixo_provedor(provedor)}_BASE")) else {}
        if live:return list(live)
    modelos = [m.strip() for m in _cfg(f"{prefixo}_MODELOS").split(",") if m.strip()]
    padrao = _cfg(f"{prefixo}_MODELO")
    if padrao and padrao not in modelos:
        modelos.insert(0, padrao)
    return modelos


def _modelos() -> list[str]:
    """Todos os modelos expostos ao celular, sem duplicar IDs."""
    vistos: set[str] = set()
    saida: list[str] = []
    for provedor in PROVEDORES_LLM:
        for modelo in _modelos_provedor(provedor):
            if modelo not in vistos:
                vistos.add(modelo)
                saida.append(modelo)
    return saida


def _config_provedor(provedor: str) -> dict[str, Any]:
    prefixo = _prefixo_provedor(provedor)
    modelos = _modelos_provedor(provedor)
    base = _url_com_v1(_cfg(f"{prefixo}_BASE"))
    chave = _cfg(f"{prefixo}_CHAVE")
    if os.name == "nt":
        from emily_remote import provedor_via_fedora, base_llm_fedora
        if provedor_via_fedora(provedor, base):
            try:
                base = base_llm_fedora()
                chave = _cfg("EMILY_PONTE_TOKEN")
            except RuntimeError as exc:
                _log(f"provedor '{provedor}': {exc}")
    return {
        "id": provedor,
        "nome": _cfg(f"{prefixo}_NOME", provedor.capitalize()),
        "base": base,
        "chave": chave,
        "padrao": _cfg(f"{prefixo}_MODELO"),
        "modelos": modelos,
    }


def _provedores_configurados() -> list[dict[str, Any]]:
    return [
        cfg for cfg in (_config_provedor(pid) for pid in PROVEDORES_LLM)
        if cfg["base"] and cfg["modelos"]
    ]


def _provedor_do_modelo(modelo: str) -> dict[str, Any] | None:
    for cfg in _provedores_configurados():
        if modelo in cfg["modelos"]:
            return cfg
    return None


_ponte_hollow_knight = None


def _iniciar_hollow_knight_permanente() -> None:
    """Mantém a companheira online sem depender da interface desktop."""
    global _ponte_hollow_knight
    if os.getenv("EMILY_HK_PERMANENTE", "1").strip() == "0":
        _log("ponte permanente do Hollow Knight desativada por configuração")
        return
    try:
        import sys as _sys

        _ler_env()
        if str(PASTA_PROJETO) not in _sys.path:
            _sys.path.insert(0, str(PASTA_PROJETO))
        from hollow_knight_emily.python.hollow_knight_permanente import (
            CerebroHollowKnightPermanente,
            FishAudioDireto,
            SaudeOmniRoute,
            gravador_catalogo,
            normalizador_modelo,
        )
        from hollow_knight_emily.python.hollow_knight_memoria import MemoriaHollowKnight
        from hollow_knight_emily.python.hollow_knight_ponte import PonteHollowKnight

        saude = SaudeOmniRoute(_cfg)
        fish = FishAudioDireto(_cfg)
        memoria = MemoriaHollowKnight()
        _ponte_hollow_knight = PonteHollowKnight(
            cerebro=CerebroHollowKnightPermanente(_cfg, saude, memoria=memoria),
            gerador_audio=fish.gerar_wav,
            gerador_audio_stream=fish.gerar_pcm_stream,
            normalizador_modelo=normalizador_modelo(_cfg),
            gravador_catalogo=gravador_catalogo(_cfg),
            pronto=saude.pronto,
            memoria=memoria,
            origem="gateway-permanente",
        )
        _ponte_hollow_knight.iniciar()
        _log("Hollow Knight permanente registrado em 127.0.0.1:57124")
    except Exception as exc:
        _ponte_hollow_knight = None
        _log(f"Hollow Knight permanente indisponível: {type(exc).__name__}: {exc}")


def _encerrar_hollow_knight_permanente() -> None:
    ponte = _ponte_hollow_knight
    if ponte is not None:
        try:
            ponte.encerrar()
        except Exception:
            pass


_iniciar_hollow_knight_permanente()
atexit.register(_encerrar_hollow_knight_permanente)


def _token_ok() -> bool:
    esperado = _cfg("EMILY_PONTE_TOKEN")
    if not esperado:
        return True
    recebido = request.headers.get("Authorization", "")
    return hmac.compare_digest(recebido, f"Bearer {esperado}")


def _exigir_token() -> Response | None:
    if _token_ok():
        return None
    return jsonify({"erro": "token inválido"}), 401


def _exigir_token_pc() -> Response | None:
    """Controle físico nunca fica aberto se o token não foi configurado."""
    if not _cfg("EMILY_PONTE_TOKEN"):
        return jsonify({"ok": False, "erro": "controle do PC desativado: configure EMILY_PONTE_TOKEN"}), 503
    return _exigir_token()


import music_gateway
music_gateway.register(APP, _exigir_token_pc)


@APP.route("/preferencias/sync", methods=["GET", "POST"])
def preferencias_sync():
    negado = _exigir_token_pc()
    if negado:
        return negado
    import preferencias
    if request.method == "POST":
        if request.content_length and request.content_length > 2 * 1024 * 1024:
            return jsonify({"ok": False, "erro": "preferências grandes demais"}), 413
        corpo = request.get_json(silent=True)
        if not isinstance(corpo, dict) or not isinstance(corpo.get("campos"), dict):
            return jsonify({"ok": False, "erro": "campos inválidos"}), 400
        preferencias.mesclar_sync(corpo["campos"])
    return jsonify({"ok": True, "campos": preferencias.exportar_sync()})


@APP.route("/discord/monitor-owner", methods=["GET", "POST"])
def discord_monitor_owner():
    """Dono único da escuta do chat do Discord entre os desktops."""
    negado = _exigir_token_pc()
    if negado:
        return negado
    import preferencias
    if request.method == "POST":
        corpo = request.get_json(silent=True)
        host = corpo.get("host") if isinstance(corpo, dict) else None
        if not isinstance(host, str) or (host and not re.fullmatch(
                r"[0-9a-fA-F-]{36}", host)):
            return jsonify({"ok": False, "erro": "identificador inválido"}), 400
        if not preferencias.definir(monitor_discord_host=host):
            return jsonify({"ok": False, "erro": "não consegui salvar o monitoramento"}), 500
    campo = preferencias.exportar_sync().get("monitor_discord_host")
    return jsonify({"ok": True, "host": campo["valor"] if campo else "",
                    "campo": campo})


@APP.get("/android/update")
def android_update():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_ANDROID / "latest.json").read_text(encoding="utf-8"))
        apk = PASTA_ATUALIZACAO_ANDROID / f"emily-{int(dados['version_code'])}.apk"
        if not apk.is_file() or apk.is_symlink() or apk.stat().st_size != dados["size"]:
            raise ValueError("APK publicado ausente ou incompleto")
        resposta = jsonify({"ok": True, "version_code": dados["version_code"],
                            "sha256": dados["sha256"], "size": dados["size"],
                            "apk_path": "/android/update/apk"})
    except (OSError, ValueError, KeyError, TypeError):
        resposta = jsonify({"ok": False, "erro": "nenhuma atualização Android publicada"})
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@APP.get("/windows/update")
def windows_update():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_WINDOWS / "latest.json").read_text(encoding="utf-8"))
        instalador = PASTA_ATUALIZACAO_WINDOWS / f"Emily-Setup-{dados['version']}.exe"
        if (not instalador.is_file() or instalador.is_symlink()
                or instalador.stat().st_size != int(dados["size"])):
            raise ValueError("instalador publicado ausente ou incompleto")
        resposta = jsonify({"ok": True, "version": dados["version"],
                            "size": dados["size"], "sha256": dados["sha256"]})
    except (OSError, ValueError, KeyError, TypeError):
        resposta = jsonify({"ok": False, "erro": "nenhuma atualização Windows publicada"})
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@APP.get("/windows/update/installer")
def windows_update_installer():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_WINDOWS / "latest.json").read_text(encoding="utf-8"))
        instalador = PASTA_ATUALIZACAO_WINDOWS / f"Emily-Setup-{dados['version']}.exe"
        if (not instalador.is_file() or instalador.is_symlink()
                or instalador.stat().st_size != int(dados["size"])):
            raise ValueError("instalador publicado ausente ou incompleto")
        return send_file(instalador, as_attachment=True, download_name=instalador.name)
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify({"ok": False, "erro": "instalador Windows indisponível"}), 404


@APP.get("/windows/code-update")
def windows_code_update():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_WINDOWS_CODIGO / "latest.json").read_text(encoding="utf-8"))
        versao = int(dados["version"])
        arquivo = PASTA_ATUALIZACAO_WINDOWS_CODIGO / f"Emily-Code-{versao}.zip"
        if (versao < 1 or not arquivo.is_file() or arquivo.is_symlink()
                or arquivo.stat().st_size != int(dados["size"])):
            raise ValueError("pacote de código ausente ou incompleto")
        resposta = jsonify({"ok": True, **dados})
    except (OSError, ValueError, KeyError, TypeError):
        resposta = jsonify({"ok": False, "erro": "nenhuma atualização de código Windows publicada"})
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@APP.get("/windows/code-update/archive")
def windows_code_update_archive():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_WINDOWS_CODIGO / "latest.json").read_text(encoding="utf-8"))
        arquivo = PASTA_ATUALIZACAO_WINDOWS_CODIGO / f"Emily-Code-{int(dados['version'])}.zip"
        if (not arquivo.is_file() or arquivo.is_symlink()
                or arquivo.stat().st_size != int(dados["size"])):
            raise ValueError("pacote de código ausente ou incompleto")
        resposta = send_file(arquivo, as_attachment=True, download_name=arquivo.name)
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify({"ok": False, "erro": "atualização de código indisponível"}), 404


@APP.post("/ollama/api/embed")
def ollama_embeddings_privados():
    """Embeddings do mesmo modelo do Fedora para a memória do notebook."""
    negado = _exigir_token_pc()
    if negado:
        return negado
    if request.content_length and request.content_length > 128 * 1024:
        return jsonify({"ok": False, "erro": "pedido de embedding grande demais"}), 413
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"ok": False, "erro": "JSON inválido"}), 400
    entradas = corpo.get("input")
    modelo = _cfg("EMILY_MEMORIA_MODELO_EMBEDDINGS", "embeddinggemma")
    if (corpo.get("model") != modelo or not isinstance(entradas, list)
            or not 1 <= len(entradas) <= 32
            or any(not isinstance(t, str) or not 1 <= len(t) <= 12000 for t in entradas)):
        return jsonify({"ok": False, "erro": "modelo ou textos inválidos"}), 400
    try:
        resposta = _sessao.post("http://127.0.0.1:11434/api/embed",
                               json={"model": modelo, "input": entradas,
                                     "truncate": True, "keep_alive": "30m"},
                               timeout=(2, 45))
        resposta.raise_for_status()
        return jsonify(resposta.json())
    except (requests.RequestException, ValueError):
        return jsonify({"ok": False, "erro": "Ollama do Fedora indisponível"}), 503


@APP.post("/android/push/register")
def android_push_register():
    negado = _exigir_token_pc()
    if negado:
        return negado
    if request.content_length and request.content_length > 8192:
        return jsonify({"ok": False, "erro": "pedido grande demais"}), 413
    dados = request.get_json(silent=True)
    try:
        salvar_push_token(dados.get("token") if isinstance(dados, dict) else None)
    except ValueError:
        return jsonify({"ok": False, "erro": "token FCM inválido"}), 400
    return jsonify({"ok": True})


@APP.post("/android/push/send")
def android_push_send():
    """Origem confiável no PC envia aviso à Emily mesmo com app/processo fechado."""
    negado = _exigir_token_pc()
    if negado:
        return negado
    if request.content_length and request.content_length > 8192:
        return jsonify({"ok": False, "erro": "pedido grande demais"}), 413
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"ok": False, "erro": "JSON inválido"}), 400
    titulo, texto = dados.get("titulo", "Emily"), dados.get("texto")
    if (not isinstance(titulo, str) or not isinstance(texto, str)
            or not 1 <= len(titulo.strip()) <= 100 or not 1 <= len(texto.strip()) <= 1000):
        return jsonify({"ok": False, "erro": "título ou texto inválido"}), 400
    try:
        resultado = enviar_push(titulo.strip(), texto.strip(),
                                credentials_file=_cfg("EMILY_FIREBASE_SERVICE_ACCOUNT"))
        return jsonify({"ok": True, "message_id": resultado.get("name", "")})
    except (RuntimeError, ImportError, OSError, ValueError) as erro:
        _log(f"push indisponível: {type(erro).__name__}: {erro}")
        return jsonify({"ok": False, "erro": "FCM indisponível ou não configurado"}), 503
    except requests.RequestException as erro:
        _log(f"FCM recusou envio: {type(erro).__name__}: {erro}")
        return jsonify({"ok": False, "erro": "FCM recusou o envio"}), 502


@APP.get("/android/update/apk")
def android_update_apk():
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        dados = json.loads((PASTA_ATUALIZACAO_ANDROID / "latest.json").read_text(encoding="utf-8"))
        apk = PASTA_ATUALIZACAO_ANDROID / f"emily-{int(dados['version_code'])}.apk"
        if not apk.is_file() or apk.is_symlink() or apk.stat().st_size != dados["size"]:
            raise ValueError("APK indisponível")
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify({"ok": False, "erro": "APK indisponível"}), 404
    resposta = send_file(apk, mimetype="application/vnd.android.package-archive",
                         as_attachment=True, download_name="emily-update.apk", conditional=True)
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


def _ip_rede() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return ""
    finally:
        sock.close()


def _emily_pronta() -> bool:
    try:
        resp = _sessao.get(f"{EMILY_INTERNA}/status", timeout=0.8)
        return bool(resp.ok and resp.json().get("emily_pronta"))
    except (requests.RequestException, ValueError):
        # A Emily pode estar ocupada atendendo uma ação longa e deixar /status
        # passar do timeout curto. Se a porta aceita TCP, o desktop está aberto;
        # não devemos mostrar "Fechada" só porque o worker HTTP está ocupado.
        try:
            host = requests.utils.urlparse(EMILY_INTERNA).hostname or "127.0.0.1"
            porta = requests.utils.urlparse(EMILY_INTERNA).port or 80
            with socket.create_connection((host, porta), timeout=0.35):
                return True
        except OSError:
            return False


def _achatar_messages(messages: Any) -> list[Any]:
    """Converte blocos Anthropic/OpenRouter no conteúdo aceito pelo OmniRoute."""
    saida: list[Any] = []
    for original in messages if isinstance(messages, list) else []:
        if not isinstance(original, dict):
            saida.append(original)
            continue
        msg = dict(original)
        conteudo = msg.get("content")
        if isinstance(conteudo, list):
            textos: list[str] = []
            imagens: list[dict[str, Any]] = []
            for bloco in conteudo:
                if not isinstance(bloco, dict):
                    continue
                if bloco.get("type") == "text":
                    textos.append(str(bloco.get("text", "")))
                elif bloco.get("type") == "image_url":
                    imagens.append({"type": "image_url", "image_url": bloco.get("image_url", {})})
            if imagens:
                prefixo = [{"type": "text", "text": "\n\n".join(textos)}] if textos else []
                msg["content"] = prefixo + imagens
            else:
                msg["content"] = "\n\n".join(textos)
        saida.append(msg)
    return saida


def _headers_provedor(chave: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if chave:
        headers["Authorization"] = f"Bearer {chave}"
    return headers


@APP.post("/llm/chat")
def llm_chat():
    negado = _exigir_token()
    if negado:
        return negado
    if request.content_length and request.content_length > MAX_CORPO:
        return jsonify({"erro": "pedido grande demais"}), 413
    corpo = request.get_json(silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"erro": "JSON inválido"}), 400
    corpo = dict(corpo)
    corpo["messages"] = _achatar_messages(corpo.get("messages"))
    quer_stream = bool(corpo.get("stream"))
    modelo = str(corpo.get("model") or _cfg(f"EMILY_PROVEDOR_{_cfg("EMILY_PROVEDOR_LLM").upper() or 'CLAUDE'}_MODELO"))
    provedor = _provedor_do_modelo(modelo)
    if provedor is None:
        return jsonify({"erro": "modelo não permitido pelo catálogo da Emily"}), 400
    corpo["model"] = modelo
    try:
        resp = _sessao.post(
            f"{provedor['base']}/chat/completions",
            headers=_headers_provedor(str(provedor["chave"])),
            json=corpo,
            stream=quer_stream,
            timeout=(5, 240),
        )
    except requests.RequestException as exc:
        return jsonify({
            "erro": f"provedor {provedor['nome']} indisponível: {type(exc).__name__}",
        }), 502
    if quer_stream:
        def gerar_stream():
            try:
                # 64 B evita o buffering perceptível de 1 KiB sem cair no custo de
                # um yield por byte; eventos SSE comuns ultrapassam esse tamanho.
                yield from resp.iter_content(chunk_size=64)
            finally:
                resp.close()

        resposta = Response(
            stream_with_context(gerar_stream()),
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", "text/event-stream"),
        )
        resposta.headers["Cache-Control"] = "no-cache, no-transform"
        resposta.headers["X-Accel-Buffering"] = "no"
        return resposta

    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("Content-Type", "application/json"))


@APP.post("/llm/v1/chat/completions")
def llm_chat_openai_compat():
    """O SDK OpenAI da Emily Windows fala com a mesma ponte do Android."""
    negado = _exigir_token_pc()
    if negado:
        return negado
    return llm_chat()


@APP.get("/llm/v1/models")
def llm_models_openai_compat():
    negado = _exigir_token_pc()
    if negado:
        return negado
    return jsonify({"object": "list", "data": [
        {"id": modelo, "object": "model"} for modelo in _modelos()]})


@APP.post("/llm/busca")
def llm_busca():
    negado = _exigir_token()
    if negado:
        return negado
    dados = request.get_json(silent=True) or {}
    consulta = str(dados.get("query") or "").strip()
    if not consulta:
        return jsonify({"erro": "query vazia"}), 400
    try:
        maximo = max(1, min(10, int(dados.get("max", 5))))
    except (TypeError, ValueError):
        maximo = 5
    chave = _cfg("BRAVE_API_KEY")
    if not chave:
        return jsonify({"erro": "BRAVE_API_KEY não configurada"}), 503
    try:
        resp = _sessao.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": consulta, "count": maximo, "country": "BR"},
            headers={"Accept": "application/json", "X-Subscription-Token": chave},
            timeout=(5, 20),
        )
        if not resp.ok:
            return jsonify({"erro": f"Brave respondeu {resp.status_code}"}), 502
        itens = (resp.json().get("web") or {}).get("results") or []
        resultados = [{
            "titulo": item.get("title") or item.get("url") or "",
            "url": item.get("url") or "",
            "resumo": item.get("description") or "",
        } for item in itens]
        return jsonify({"ok": True, "resultados": resultados})
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"erro": f"busca falhou: {type(exc).__name__}"}), 502


def _proxy_vivo() -> bool:
    cfg = _config_provedor("omniroute")
    if not cfg["base"]:
        return False
    try:
        resp = _sessao.get(
            f"{cfg['base']}/models",
            headers=_headers_provedor(str(cfg["chave"])),
            timeout=4,
        )
        # Qualquer resposta HTTP abaixo de 500 prova que o processo local está
        # vivo. 401/403 continuam sendo úteis no painel: o OmniRoute está online,
        # embora uma chamada real ainda exponha a credencial inválida.
        if resp.status_code < 500:
            return True
    except requests.RequestException:
        pass

    # /models pode devolver 5xx transitório quando uma conta interna do
    # OmniRoute está renovando sessão. Isso não significa que o processo local
    # parou. O painel mede a conexão com o OmniRoute; uma conexão TCP aceita na
    # base configurada é a prova adequada de que ele continua online.
    try:
        url = requests.utils.urlparse(str(cfg["base"]))
        host = url.hostname or "127.0.0.1"
        porta = url.port or (443 if url.scheme == "https" else 80)
        with socket.create_connection((host, porta), timeout=0.5):
            return True
    except OSError:
        return False


@APP.get("/llm/status")
def llm_status():
    negado = _exigir_token()
    if negado:
        return negado
    return jsonify({
        "ok": True,
        "gateway_vivo": True,
        "emily_pronta": _emily_pronta(),
        "proxy_vivo": _proxy_vivo(),
        "modelo_padrao": _cfg(f"EMILY_PROVEDOR_{_cfg("EMILY_PROVEDOR_LLM").upper() or 'CLAUDE'}_MODELO"),
        "modelos": _modelos(),
        "busca_ok": bool(_cfg("BRAVE_API_KEY")),
        "ip_rede": _ip_rede(),
    })


@APP.get("/pc/status")
def pc_status():
    negado = _exigir_token_pc()
    if negado:
        return negado
    if _pc_controller is None:
        return jsonify({"ok": False, "mensagem": "executor do PC indisponível"}), 503
    return jsonify(_pc_controller.executar("status", {}, turno_id="consulta-status"))


@APP.get("/gateway/endpoint")
def gateway_endpoint_atual():
    negado = _exigir_token_pc()
    if negado:
        return negado
    import gateway_endpoint
    atual = gateway_endpoint.obter()
    return jsonify({"ok": bool(atual["url"]), **atual})


@APP.post("/gateway/endpoint/push")
def gateway_endpoint_push():
    negado = _exigir_token_pc()
    if negado:
        return negado
    import gateway_endpoint
    atual = gateway_endpoint.obter()
    pedido = request.get_json(silent=True) or {}
    if (not isinstance(pedido, dict) or not atual["url"] or pedido.get("url") != atual["url"] or
            pedido.get("atualizado_em") != atual["atualizado_em"]):
        return jsonify({"ok": False, "erro": "endpoint alterado durante o envio"}), 409
    try:
        enviar_push_dados({"type": "gateway_endpoint", "url": atual["url"],
                          "updated_at": str(atual["atualizado_em"])},
                         credentials_file=_cfg("EMILY_FIREBASE_SERVICE_ACCOUNT"))
        return jsonify({"ok": True})
    except Exception as erro:  # Firebase ainda pode não estar configurado
        _log(f"push de endpoint indisponível: {type(erro).__name__}: {erro}")
        return jsonify({"ok": False, "erro": str(erro)}), 503


@APP.post("/gateway/endpoint/publish")
def gateway_endpoint_publish():
    negado = _exigir_token_pc()
    if negado:
        return negado
    if request.content_length and request.content_length > 8192:
        return jsonify({"ok": False, "erro": "pedido grande demais"}), 413
    import gateway_endpoint
    atual = gateway_endpoint.obter()
    pedido = request.get_json(silent=True) or {}
    if (not isinstance(pedido, dict) or not atual["url"] or pedido.get("url") != atual["url"] or
            pedido.get("atualizado_em") != atual["atualizado_em"]):
        return jsonify({"ok": False, "erro": "endpoint alterado durante a publicação"}), 409
    try:
        from firebase_endpoint import publicar
        publicar(atual["url"], atual["atualizado_em"], _cfg("EMILY_PONTE_TOKEN"),
                 _cfg("EMILY_FIREBASE_SERVICE_ACCOUNT"))
        return jsonify({"ok": True})
    except Exception as erro:
        _log(f"publicação do endpoint indisponível: {type(erro).__name__}: {erro}")
        return jsonify({"ok": False, "erro": "Firebase indisponível para o Windows"}), 503


@APP.post("/pc/action")
def pc_action():
    negado = _exigir_token_pc()
    if negado:
        return negado
    if _pc_controller is None:
        return jsonify({"ok": False, "mensagem": "executor do PC indisponível"}), 503
    if request.content_length and request.content_length > 32 * 1024:
        return jsonify({"ok": False, "mensagem": "pedido grande demais"}), 413
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"ok": False, "mensagem": "JSON inválido"}), 400
    acao = dados.get("action")
    args = dados.get("args", {})
    turno_id = dados.get("turn_id")
    if not isinstance(acao, str) or not isinstance(args, dict) or not isinstance(turno_id, str):
        return jsonify({"ok": False, "mensagem": "contrato de ação inválido"}), 400
    politica = {"irrestrito":True} if dados.get("unrestricted_mode") is True else {}
    inicio = time.monotonic()
    resposta = _pc_controller.executar(acao.strip(), args, turno_id=turno_id.strip(),**politica)
    _log(f"controle PC action={acao.strip()!r} ok={bool(resposta.get('ok'))} total_ms={(time.monotonic()-inicio)*1000:.0f}")
    return jsonify(resposta)


def _rotulo_modelo(modelo_id: str) -> str:
    texto = modelo_id.strip().split("/", 1)[-1].replace("-", " ")
    texto = re.sub(r"(\d)\s(\d)", r"\1.\2", texto)
    texto = re.sub(r"([A-Za-z]{2,})(\d)", r"\1 \2", texto)
    mapa = {"claude": "Claude", "sonnet": "Sonnet", "haiku": "Haiku", "opus": "Opus",
            "gpt": "GPT", "terra": "Terra", "luna": "Luna", "sol": "Sol"}
    return " ".join(mapa.get(p.lower(), p[:1].upper() + p[1:]) for p in texto.split()) or modelo_id


@APP.route("/llm/usage",methods=["GET"])
def model_usage():
    denied=_exigir_token()
    if denied:return denied
    import uso_codex
    return jsonify(uso_codex.desktop_usage())

@APP.post("/llm/context")
def model_context():
    denied=_exigir_token()
    if denied:return denied
    try:
        cfg=json.loads((Path.home()/'.config/emily-cloud-oracle/discord-host.json').read_text())
        response=requests.post(cfg['url']+'/admin/llm/context',headers={'Authorization':'Bearer '+cfg['key']},
                               json=request.get_json(),timeout=(5,600))
        return Response(response.content,status=response.status_code,content_type='application/json')
    except Exception:return jsonify(ok=False,error='Contexto indisponível; original preservado.'),503

@APP.get("/llm/provedores")
def llm_provedores():
    negado = _exigir_token()
    if negado:
        return negado
    provedores = []
    for cfg in _provedores_configurados():
        itens = [{
            "id": modelo,
            "nome": _rotulo_modelo(modelo),
            "sobre": cfg["nome"] if i == 0 else f"{cfg['nome']} · {i + 1}º",
        } for i, modelo in enumerate(cfg["modelos"])]
        provedores.append({
            "id": cfg["id"],
            "nome": cfg["nome"],
            "padrao": cfg["padrao"],
            "modelos": itens,
        })
    return jsonify({"ok": True, "provedores": provedores})


def _headers_upstream() -> dict[str, str]:
    return {k: v for k, v in request.headers if k.lower() not in _HOP_BY_HOP}


def _headers_resposta(resp: requests.Response) -> list[tuple[str, str]]:
    return [(k, v) for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP]


def _proxy_http(upstream: str, *, timeout_leitura: float = 310.0):
    """Proxy transparente com streaming, sem descompactar o corpo upstream."""
    url = upstream
    if request.query_string:
        url += "?" + request.query_string.decode("latin-1")
    corpo = request.get_data(cache=False)
    if len(corpo) > MAX_CORPO:
        return jsonify({"ok": False, "erro": "pedido grande demais"}), 413
    try:
        resp = _sessao.request(
            request.method, url, headers=_headers_upstream(), data=corpo,
            stream=True, allow_redirects=False, timeout=(1.5, timeout_leitura),
        )
    except requests.RequestException:
        return None

    def gerar():
        try:
            yield from resp.raw.stream(64 * 1024, decode_content=False)
        finally:
            resp.close()

    return Response(stream_with_context(gerar()), status=resp.status_code,
                    headers=_headers_resposta(resp))


@APP.route("/tela/<path:recurso>", methods=["GET", "POST", "DELETE", "OPTIONS"])
def proxy_tela_dedicada(recurso: str):
    """Tela moderna continua disponível sem a Emily desktop.

    Mantém compatibilidade com o APK antigo (/jpg) e permite ao APK novo usar
    MJPEG pelo mesmo endereço do gateway/Ngrok quando a LAN direta não existe.
    """
    if os.name == "nt":
        return _tela_windows(recurso)
    if not recurso.startswith("rtc/") and recurso not in {"stream", "jpg", "monitores", "estado",
                       "audio", "audio/estado"}:
        return proxy_emily(f"tela/{recurso}")
    timeout = 3700.0 if recurso.startswith("audio") else 3700.0
    resposta = _proxy_http(f"http://127.0.0.1:8790/tela/{recurso}", timeout_leitura=timeout)
    if resposta is not None:
        return resposta
    return jsonify({"ok": False, "erro": "serviço dedicado de tela indisponível"}), 503


def _tela_windows(recurso: str):
    negado = _exigir_token_pc()
    if negado:
        return negado
    try:
        from windows_screen import audio_pcm, capturar_jpeg, listar_monitores, quadros_mjpeg
        if recurso == "monitores":
            return jsonify({"ok": True, "monitores": listar_monitores()})
        if recurso == "estado":
            return jsonify({"ok": True, "ativo": True, "plataforma": "Windows"})
        if recurso == "jpg":
            monitor = int(request.args.get("monitor", 1))
            largura = max(320, min(int(request.args.get("largura", 1280)), 2560))
            qualidade = max(35, min(int(request.args.get("q", 72)), 90))
            resposta = Response(capturar_jpeg(monitor, largura, qualidade), mimetype="image/jpeg")
            resposta.headers["Cache-Control"] = "no-store"
            resposta.headers["X-Emily-Idade"] = "0"
            return resposta
        if recurso == "stream":
            monitor = int(request.args.get("monitor", 1))
            fps = int(request.args.get("fps", 4))
            if monitor not in {m["id"] for m in listar_monitores()}:
                raise ValueError("monitor inválido")
            return Response(stream_with_context(quadros_mjpeg(monitor, fps)),
                            mimetype="multipart/x-mixed-replace; boundary=frame")
        if recurso == "audio":
            return Response(stream_with_context(audio_pcm()),
                            mimetype="application/octet-stream",
                            headers={"Cache-Control": "no-store"})
        if recurso == "audio/estado":
            return jsonify({"ok": True, "plataforma": "Windows", "formato": "PCM S16LE 48000 Hz estéreo"})
    except (ValueError, OSError) as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 400
    return jsonify({"ok": False, "erro": "recurso de tela indisponível no Windows"}), 503


@APP.route("/", defaults={"caminho": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@APP.route("/<path:caminho>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def proxy_emily(caminho: str):
    """Encaminha todo recurso não-LLM para a Emily desktop na porta 5001."""
    resposta = _proxy_http(f"{EMILY_INTERNA}/{caminho}")
    if resposta is None:
        if caminho.startswith("chats/") or caminho == "memoria/sync":
            return _sync_sem_desktop(caminho)
        return jsonify({
            "ok": False,
            "emily_pronta": False,
            "erro": "Emily desktop está fechada; o cérebro Claude/GPT continua disponível em /llm/*",
        }), 503

    return resposta


def _sync_sem_desktop(caminho: str):
    """Mantém o mesmo acervo do desktop acessível quando sua janela fechou."""
    negado = _exigir_token_pc()
    if negado:
        return negado
    if str(PASTA_PROJETO) not in sys.path:
        sys.path.insert(0, str(PASTA_PROJETO))
    import conversas
    import memoria

    # O desktop e o gateway são processos distintos. Quando o desktop está
    # fechado, descartar o cache evita devolver uma fotografia antiga.
    conversas.recarregar()
    if caminho == "chats/delta" and request.method == "GET":
        try:
            desde = float(request.args.get("desde", 0))
        except (TypeError, ValueError):
            desde = 0.0
        return jsonify({"ok": True, "agora": time.time(),
                        "conversas": [c for c in conversas.listar()
                                      if c.get("mexida", 0) > desde],
                        "apagadas": [a for a in conversas.listar_apagadas()
                                     if a.get("quando", 0) > desde]})
    if caminho.startswith("chats/abrir/") and request.method == "GET":
        cid = caminho.removeprefix("chats/abrir/")
        meta = next((c for c in conversas.listar() if c.get("id") == cid), None)
        if meta is None:
            return jsonify({"ok": False, "erro": "conversa não encontrada"}), 404
        return jsonify({"ok": True, "id": cid, "titulo": meta["titulo"],
                        "criada": meta["criada"], "mexida": meta["mexida"],
                        "ramo": meta.get("ramo", 0),
                        "mensagens": conversas.abrir(cid)})
    if caminho == "chats/gravar" and request.method == "POST":
        corpo = request.get_json(silent=True) or {}
        try:
            ok = conversas.gravar_externa(
                cid=str(corpo.get("id") or "").strip(),
                titulo=str(corpo.get("titulo") or ""),
                criada=float(corpo.get("criada") or 0),
                mexida=float(corpo.get("mexida") or 0),
                mensagens=corpo.get("mensagens") or [],
                ramo=int(corpo.get("ramo") or 0),
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "erro": f"payload inválido: {exc}"}), 400
        return jsonify({"ok": ok, "pc_mais_novo": not ok})
    if caminho.startswith("chats/apagar/") and request.method == "DELETE":
        conversas.apagar(caminho.removeprefix("chats/apagar/"))
        return jsonify({"ok": True})
    if caminho == "memoria/sync" and request.method == "POST":
        corpo = request.get_json(silent=True) or {}
        try:
            estado = memoria.sincronizar_externa(
                fatos_externos=corpo.get("fatos") or [],
                apagados_externos=corpo.get("apagados") or {},
            )
        except (TypeError, ValueError, OSError) as exc:
            return jsonify({"ok": False, "erro": f"sync falhou: {exc}"}), 500
        return jsonify({"ok": True, "agora": time.time(), **estado})
    return jsonify({"ok": False, "erro": "rota de sincronização inválida"}), 404


if os.name == "nt":
    try:
        if str(PASTA_PROJETO) not in sys.path:
            sys.path.insert(0, str(PASTA_PROJETO))
        import sincronizacao_desktop
        sincronizacao_desktop.iniciar(habilitado=lambda: not _proxy_vivo())
    except Exception as exc:
        _log(f"sincronização em segundo plano indisponível: {exc}")


if __name__ == "__main__":
    _ler_env()
    _log(
        f"porta {PORTA}; Emily interna {EMILY_INTERNA}; "
        f"OmniRoute {_cfg('EMILY_PROVEDOR_OMNIROUTE_BASE')}"
    )
    APP.run(host="0.0.0.0", port=PORTA, debug=False, use_reloader=False, threaded=True)
