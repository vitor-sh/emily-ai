"""
controle_tv.py — A Emily do PC controlando Android TV pelo mesmo protocolo do app.

Espelho direto do TvController.kt do celular (EmilyAPP2): mesmas teclas, mesmo
mapa de apps, mesma sintonia de canal ("TV ao vivo" + dígitos, sem OK no final),
mesmos canais mapeados (globo 12, record 27). É INDEPENDENTE do celular: quem
fala com a TV é este processo, com o próprio certificado de cliente — parear no
celular não pareia aqui, e vice-versa.

Biblioteca: androidtvremote2 (Android TV Remote protocol v2 — as portas 6466 de
comandos e 6467 de pareamento, TLS com certificado de cliente).

Persistência: tvs_salvas.json na pasta da Emily (mesmo padrão do memoria.json).
Cada TV guarda nome, ip, tipo e se já está pareada — tudo editável na aba TV
das Configurações, porque detectar marca/modelo pela rede nem sempre dá certo
e o Vitor sabe melhor o que é a TV dele.

Ferramentas de alto nível (as que a Emily vê) ficam no ferramentas.py; este
módulo é a mão que executa. A interface (interface.py) usa as funções de
dispositivo direto.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
from emily_paths import arquivo_dados

BASE_DIR = Path(__file__).resolve().parent
ARQUIVO = arquivo_dados("tvs_salvas.json")
# IP legado que existia antes da lista (igual ao celular: tv_ip do prefs).
LEGADO_TV_IP = BASE_DIR / "tv_ip.txt"
COMPANION_PORT = 8765
COMPANION_TIMEOUT = 8.0
COMPANION_DISCOVERY_PORT = 8766
COMPANION_TOKEN_LENGTH = 48
TELA_PC_URL = "http://127.0.0.1:8790"

# Um par de certificados de CLIENTE serve pra todas as TVs: cada TV autoriza o
# mesmo cliente no pareamento dela. Ficam junto do resto dos dados da Emily.
CERT_DIR = arquivo_dados("certificados_tv")
CERTFILE = CERT_DIR / "emily_tv_client.pem"
KEYFILE = CERT_DIR / "emily_tv_client.key"

CLIENT_NAME = "Emily"

# ─── Mapas espelhados do TvController.kt ─────────────────────────
# Teclas que a Emily usa. Chave em minúsculo; o valor é o nome do enum
# RemoteKeyCode que a biblioteca aceita em send_key_command.
TECLAS: Dict[str, str] = {
    "power": "KEYCODE_POWER",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "volume_mute": "KEYCODE_MUTE",
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "menu": "KEYCODE_MENU",
    "settings": "KEYCODE_SETTINGS",
    "playpause": "KEYCODE_MEDIA_PLAY_PAUSE",
    "play": "KEYCODE_MEDIA_PLAY",
    "pause": "KEYCODE_MEDIA_PAUSE",
    "stop": "KEYCODE_MEDIA_STOP",
    "forward": "KEYCODE_MEDIA_FAST_FORWARD",
    "rewind": "KEYCODE_MEDIA_REWIND",
    "next": "KEYCODE_MEDIA_NEXT",
    "previous": "KEYCODE_MEDIA_PREVIOUS",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "ok": "KEYCODE_DPAD_CENTER",
    "channel_up": "KEYCODE_CHANNEL_UP",
    "channel_down": "KEYCODE_CHANNEL_DOWN",
    "tv_input": "KEYCODE_TV_INPUT",
}

# Apelidos em português que o Vitor fala ("aumenta o volume da TV").
APELIDOS_TECLA: Dict[str, str] = {
    "ligar": "power", "desligar": "power",
    "aumentar_volume": "volume_up", "diminuir_volume": "volume_down",
    "mudo": "volume_mute", "silenciar": "volume_mute",
    "voltar": "back", "inicio": "home",
    "configuracoes": "settings", "config": "settings",
    "play_pause": "playpause", "pausar": "pause", "tocar": "play",
    "cima": "up", "baixo": "down", "esquerda": "left", "direita": "right",
    "entrar": "ok", "confirmar": "ok",
    "canal_acima": "channel_up", "canal_abaixo": "channel_down",
}

# Apps da TV por nome amigável. Igual ao celular: deep link http(s) ou
# "market://launch?id=..." — a biblioteca completa o prefixo market sozinha
# quando o valor não tem scheme (ver send_launch_app_command dela).
APPS_TV: Dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "netflix": "https://www.netflix.com/title",
    "prime video": "https://app.primevideo.com",
    "prime": "https://app.primevideo.com",
    "amazon prime": "https://app.primevideo.com",
    "disney": "https://www.disneyplus.com",
    "disney plus": "https://www.disneyplus.com",
    "max": "https://play.hbomax.com",
    "hbo max": "https://play.hbomax.com",
    "spotify": "com.spotify.tv.android",
    "globoplay": "com.globo.globotv",
}

# Canais abertos mapeados (mesma tabela do celular) e o app de TV ao vivo da TCL.
CANAIS: Dict[str, str] = {"globo": "12", "record": "27"}
APP_TV_AO_VIVO = "com.tcl.tv"  # a biblioteca vira market://launch?id=...


def _link_busca(app: str, query: str) -> Optional[str]:
    """Busca dentro de app, via deep link de resultados (igual ao celular)."""
    from urllib.parse import quote_plus
    a = (app or "").strip().lower()
    q = quote_plus(query)
    if a in ("youtube", "you tube"):
        return f"https://www.youtube.com/results?search_query={q}"
    if a == "netflix":
        return f"https://www.netflix.com/search?q={q}"
    return None


# ═════════════════════════════════════════════════════════════════
# LOOP ASYNC DEDICADO
#
# A biblioteca é async; a Emily é um app de threads. Um único worker roda um
# loop asyncio pra sempre e as chamadas sync enfileiram coroutines nele —
# mesmo desenho do "controllerScope + Dispatchers.IO" do celular.
# ═════════════════════════════════════════════════════════════════

_lock = threading.RLock()
_executor: Optional[ThreadPoolExecutor] = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_pronto = threading.Event()

_remotes: Dict[str, Any] = {}        # ip -> AndroidTVRemote conectado
_dispositivo_ativo: Dict[str, Any] = {}
_precisa_parear = threading.Event()  # a TV recusou o certificado (parear de novo)
_ultimo_applink_em = 0.0             # janela do app de TV aberto (igual ao celular)
TV_APP_WINDOW_S = 45.0

_pareando: Dict[str, Any] = {"remote": None, "dispositivo": None}

TAG = "[CONTROLE-TV]"


def _log(msg: str) -> None:
    print(f"{TAG} {msg}")


def _rodar_loop() -> None:
    global _loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    with _lock:
        _loop = loop
    _loop_pronto.set()
    try:
        loop.run_forever()
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _garantir_loop() -> asyncio.AbstractEventLoop:
    global _executor
    with _lock:
        if _loop_pronto.is_set() and _loop is not None and not _loop.is_closed():
            return _loop
        if _executor is None:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="emily-tv")
            _executor.submit(_rodar_loop)
    _loop_pronto.wait(timeout=10)
    if _loop is None or _loop.is_closed():
        raise RuntimeError("loop asyncio da TV não subiu")
    return _loop


def _submit(coro, timeout: float = 20.0):
    """Roda uma coroutine no loop dedicado e ESPERA o resultado (sync)."""
    loop = _garantir_loop()
    futuro = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return futuro.result(timeout=timeout)
    except Exception:
        futuro.cancel()
        raise


def _encerrar() -> None:
    """Desliga conexões e o loop. Chamado no atexit (e nos testes)."""
    global _executor, _loop
    with _lock:
        for remote in list(_remotes.values()):
            try:
                remote.disconnect()
            except Exception:
                pass
        _remotes.clear()
        _dispositivo_ativo.clear()
        loop = _loop
        executor = _executor
    if loop is not None:
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
    if executor is not None:
        executor.shutdown(wait=False)
    with _lock:
        _executor = None
        _loop = None
        _loop_pronto.clear()


atexit.register(_encerrar)


# ═════════════════════════════════════════════════════════════════
# CATÁLOGO DE DISPOSITIVOS (tvs_salvas.json)
# ═════════════════════════════════════════════════════════════════

def _ler_catalogo() -> List[Dict[str, Any]]:
    """Lê o arquivo; migra o IP legado (tv_ip.txt) na primeira vez, igual ao celular."""
    with _lock:
        if ARQUIVO.exists():
            try:
                dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
                if isinstance(dados, list):
                    return [d for d in dados if isinstance(d, dict) and d.get("ip")]
            except Exception as e:
                _log(f"catálogo corrompido ({e}); recomeçando vazio")
        try:
            if LEGADO_TV_IP.exists():
                ip = LEGADO_TV_IP.read_text(encoding="utf-8").strip()
                if ip:
                    _log(f"migrando IP legado {ip} pra lista de dispositivos")
                    return [{"id": uuid.uuid4().hex[:8], "nome": "TV da Sala",
                             "ip": ip, "tipo": "", "pareada": False}]
        except Exception as e:
            _log(f"legado ilegível: {e}")
    return []


def _escrever_catalogo(dispositivos: List[Dict[str, Any]]) -> None:
    with _lock:
        ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
        tmp = ARQUIVO.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dispositivos, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(ARQUIVO)


def _restaurar_dispositivo_ativo(
        dispositivos: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Restaura em memória a TV marcada como ativa no catálogo persistente.

    A conexão Android TV continua sob demanda; aqui só restauramos identidade,
    IP e token do Companion. Assim as rotas HTTP locais (apps/WebRTC) funcionam
    logo após iniciar a Emily, sem exigir um clique prévio na aba TV.
    """
    with _lock:
        if _dispositivo_ativo:
            return dict(_dispositivo_ativo)
        catalogo = dispositivos if dispositivos is not None else _ler_catalogo()
        salvo = next((d for d in catalogo if d.get("ativa")), None)
        if salvo:
            _dispositivo_ativo.update(salvo)
            return dict(_dispositivo_ativo)
    return None


def _persistir_dispositivo_ativo(id_dispositivo: str) -> None:
    """Mantém uma única TV ativa no JSON para restaurá-la no próximo início."""
    dispositivos = _ler_catalogo()
    mudou = False
    for dispositivo in dispositivos:
        ativa = dispositivo.get("id") == id_dispositivo
        if dispositivo.get("ativa") != ativa:
            dispositivo["ativa"] = ativa
            mudou = True
    if mudou:
        _escrever_catalogo(dispositivos)


def listar_dispositivos() -> List[Dict[str, Any]]:
    dispositivos = _ler_catalogo()
    ativo = (_restaurar_dispositivo_ativo(dispositivos) or {}).get("id")
    for d in dispositivos:
        d["ativa"] = d.get("id") == ativo
    return dispositivos


def dispositivo_ativo() -> Optional[Dict[str, Any]]:
    """Snapshot público da TV ativa para integrações locais (Cloud/player)."""
    return _restaurar_dispositivo_ativo()


def _achar_dispositivo(id_ou_ip: str) -> Optional[Dict[str, Any]]:
    for d in _ler_catalogo():
        if d.get("id") == id_ou_ip or d.get("ip") == id_ou_ip:
            return d
    return None


def salvar_dispositivo(nome: str, ip: str, tipo: str = "") -> Dict[str, Any]:
    """Cria ou atualiza (por IP) um dispositivo. IP vazio ou inválido rejeita."""
    ip = (ip or "").strip()
    if not ip or len(ip.split(".")) != 4:
        raise ValueError(f"IP inválido: '{ip}'")
    nome = (nome or "").strip() or f"TV {ip}"
    tipo = (tipo or "").strip()
    dispositivos = _ler_catalogo()
    for d in dispositivos:
        if d.get("ip") == ip:
            if nome: d["nome"] = nome
            if tipo: d["tipo"] = tipo
            _escrever_catalogo(dispositivos)
            return d
    novo = {"id": uuid.uuid4().hex[:8], "nome": nome, "ip": ip,
            "tipo": tipo, "pareada": False}
    dispositivos.append(novo)
    _escrever_catalogo(dispositivos)
    _log(f"dispositivo salvo: {nome} ({ip})")
    return novo


def editar_dispositivo(id_dispositivo: str, nome: str = "",
                       ip: str = "", tipo: str = "") -> Dict[str, Any]:
    dispositivos = _ler_catalogo()
    for d in dispositivos:
        if d.get("id") == id_dispositivo:
            if nome.strip(): d["nome"] = nome.strip()
            if tipo.strip(): d["tipo"] = tipo.strip()
            ip_novo = ip.strip()
            if ip_novo:
                if len(ip_novo.split(".")) != 4:
                    raise ValueError(f"IP inválido: '{ip_novo}'")
                d["ip"] = ip_novo
            _escrever_catalogo(dispositivos)
            return d
    raise ValueError("dispositivo não encontrado")


def remover_dispositivo(id_dispositivo: str) -> str:
    dispositivos = _ler_catalogo()
    restantes = [d for d in dispositivos if d.get("id") != id_dispositivo]
    if len(restantes) == len(dispositivos):
        return "ERRO: dispositivo não encontrado"
    _escrever_catalogo(restantes)
    with _lock:
        if _dispositivo_ativo.get("id") == id_dispositivo:
            _dispositivo_ativo.clear()
    return "OK"


def _marcar_pareada(ip: str, pareada: bool, tipo: str = "") -> None:
    """Anota no catálogo o resultado real do pareamento/conexão."""
    dispositivos = _ler_catalogo()
    mudou = False
    for d in dispositivos:
        if d.get("ip") == ip:
            if d.get("pareada") != pareada:
                d["pareada"] = pareada
                mudou = True
            if tipo and not d.get("tipo"):
                d["tipo"] = tipo
                mudou = True
    if mudou:
        _escrever_catalogo(dispositivos)


# ═════════════════════════════════════════════════════════════════
# CONEXÃO
# ═════════════════════════════════════════════════════════════════

def _nova_tv(ip: str):
    from androidtvremote2 import AndroidTVRemote
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    return AndroidTVRemote(
        client_name=CLIENT_NAME, certfile=str(CERTFILE), keyfile=str(KEYFILE),
        host=ip,
    )


async def _nova_tv_async(ip: str):
    """Constrói o AndroidTVRemote DENTRO do loop dedicado.

    O __init__ da lib faz `asyncio.get_running_loop()` (androidtv_remote.py:95)
    — chamado na thread da interface (sem loop rodando) isso levanta
    "RuntimeError: no running event loop", o erro que quebrava o pareamento
    pelo PC enquanto o celular funcionava. Aqui o construtor roda na thread
    do loop, onde o get_running_loop devolve o loop certo."""
    return _nova_tv(ip)


async def _conectar_async(ip: str):
    """Conecta (ou devolve a conexão viva). Levanta InvalidAuth se a TV
    não conhece este certificado — aí é pareamento, não erro."""
    remote = _nova_tv(ip)
    await remote.async_generate_cert_if_missing()
    await remote.async_connect()
    remote.keep_reconnecting(invalid_auth_callback=_precisa_parear.set)
    return remote


def _garantir_conectado(dispositivo: Dict[str, Any]):
    """Mesmo papel do garantirConexaoSync do celular: reusa a viva ou conecta."""
    from androidtvremote2.exceptions import InvalidAuth
    ip = dispositivo["ip"]
    with _lock:
        remote = _remotes.get(ip)
        if remote is not None:
            _dispositivo_ativo.clear()
            _dispositivo_ativo.update(dispositivo)
            return remote
    _precisa_parear.clear()
    try:
        remote = _submit(_conectar_async(ip), timeout=15.0)
    except InvalidAuth:
        _precisa_parear.set()
        raise
    except Exception as e:
        raise ConnectionError(f"não conectei na TV {ip}: {e}") from e
    with _lock:
        _remotes[ip] = remote
        _dispositivo_ativo.clear()
        _dispositivo_ativo.update(dispositivo)
    _marcar_pareada(ip, True)
    return remote


def conectar_dispositivo(id_dispositivo: str) -> Dict[str, Any]:
    """Conecta num dispositivo da lista e o torna o ativo (o clique do card)."""
    dispositivo = _achar_dispositivo(id_dispositivo)
    if not dispositivo:
        return {"ok": False, "mensagem": "ERRO: dispositivo não encontrado"}
    try:
        _garantir_conectado(dispositivo)
    except Exception as e:
        if _precisa_parear.is_set():
            return {"ok": False, "precisa_parear": True, "dispositivo": dispositivo,
                    "mensagem": ("Esta TV ainda não pareou com a Emily do PC. "
                                 "Use 'Parear na TV' e digite o código que "
                                 "aparece na tela dela.")}
        return {"ok": False, "mensagem": f"ERRO: {e}"}
    _persistir_dispositivo_ativo(dispositivo["id"])
    return {"ok": True, "dispositivo": dispositivo,
            "mensagem": f"Conectada em {dispositivo['nome']} ({dispositivo['ip']})"}


# ═════════════════════════════════════════════════════════════════
# PAREAMENTO (fluxo igual ao celular: inicia → código na TV → conclui)
# ═════════════════════════════════════════════════════════════════

def iniciar_pareamento(id_dispositivo: str) -> Dict[str, Any]:
    """Manda a TV mostrar o código. Quem digita é o Vitor (concluir_pareamento)."""
    dispositivo = _achar_dispositivo(id_dispositivo)
    if not dispositivo:
        return {"ok": False, "mensagem": "ERRO: dispositivo não encontrado"}
    try:
        remote = _submit(_nova_tv_async(dispositivo["ip"]), timeout=15.0)
        _submit(remote.async_generate_cert_if_missing(), timeout=15.0)
        _submit(remote.async_start_pairing(), timeout=20.0)
    except Exception as e:
        nome_erro = type(e).__name__
        if "CannotConnect" in nome_erro or isinstance(e, OSError):
            return {"ok": False,
                    "mensagem": f"ERRO: TV não respondeu ({e}). Confere o IP e se ela está ligada."}
        return {"ok": False, "mensagem": f"ERRO: {e}"}
    _pareando["remote"] = remote
    _pareando["dispositivo"] = dispositivo
    return {"ok": True, "dispositivo": dispositivo,
            "mensagem": "A TV deve estar mostrando o código agora. Digite ele pra concluir."}


def concluir_pareamento(codigo: str) -> Dict[str, Any]:
    remote = _pareando.get("remote")
    dispositivo = _pareando.get("dispositivo")
    if remote is None:
        return {"ok": False, "mensagem": "ERRO: nenhum pareamento em andamento. Comece de novo."}
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return {"ok": False, "mensagem": "ERRO: código vazio"}
    try:
        _submit(remote.async_finish_pairing(codigo), timeout=20.0)
    except Exception as e:
        _pareando.update({"remote": None, "dispositivo": None})
        try:
            remote.disconnect()
        except Exception:
            pass
        nome_erro = type(e).__name__
        if "InvalidAuth" in nome_erro:
            return {"ok": False, "mensagem": "ERRO: código incorreto ou recusado na TV."}
        if "ConnectionClosed" in nome_erro:
            return {"ok": False, "mensagem": "ERRO: pareamento cancelado na TV."}
        return {"ok": False, "mensagem": f"ERRO: {e}"}
    try:
        remote.disconnect()
    except Exception:
        pass
    _pareando.update({"remote": None, "dispositivo": None})
    _marcar_pareada(dispositivo["ip"], True)
    try:
        conectar_dispositivo(dispositivo["id"])
    except Exception as e:
        _log(f"pós-pareamento: conexão imediata falhou ({e}); o watchdog resolve")
    return {"ok": True, "dispositivo": dispositivo,
            "mensagem": f"Pareada com {dispositivo['nome']}!"}


def _companion_token() -> str:
    dispositivo = _restaurar_dispositivo_ativo()
    return str(dispositivo.get("companion_token", "")).strip() if dispositivo else ""


class CompanionAuthError(RuntimeError):
    """O app Emily TV respondeu, mas recusou a credencial apresentada."""


class CompanionUnavailableError(RuntimeError):
    """O servidor local do app Emily TV não pôde ser alcançado."""


def _normalizar_token_companion(token: str) -> str:
    """Remove apenas espaçamento visual e canonicaliza o hexadecimal."""
    return "".join(str(token or "").split()).lower()


def _token_companion_valido(token: str) -> bool:
    return (len(token) == COMPANION_TOKEN_LENGTH and
            all(c in "0123456789abcdef" for c in token))


def _detalhe_http_companion(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        return str(payload.get("error") or payload.get("message") or exc)
    except Exception:
        return str(exc)


def _companion_request_para(dispositivo: Dict[str, Any], token: str, method: str,
                            path: str, body: Optional[Dict[str, Any]] = None):
    """Executa uma chamada com credenciais explícitas e devolve (JSON, IP usado).

    A configuração do token usa esta variante para testar a credencial candidata
    antes de gravá-la. Assim, uma leitura errada de OCR nunca substitui um token
    válido nem é anunciada como configuração concluída.
    """
    def executar(ip: str) -> Dict[str, Any]:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else (
            b"" if method == "POST" else None)
        request = urllib.request.Request(
            f"http://{ip}:{COMPANION_PORT}{path}", method=method,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                     "Content-Type": "application/json; charset=utf-8"},
            data=raw,
        )
        with urllib.request.urlopen(request, timeout=COMPANION_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))

    ip_original = str(dispositivo.get("ip", "")).strip()
    try:
        data = executar(ip_original)
        ip_usado = ip_original
    except urllib.error.HTTPError as exc:
        detalhe = _detalhe_http_companion(exc)
        if exc.code in (401, 403) or detalhe.lower() == "unauthorized":
            raise CompanionAuthError("token recusado pelo app Emily TV") from exc
        raise RuntimeError(detalhe) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        novo_ip = _descobrir_companion_lan()
        if not novo_ip:
            raise CompanionUnavailableError(
                f"app Emily TV indisponível em {ip_original}:{COMPANION_PORT}"
            ) from exc
        try:
            data = executar(novo_ip)
            ip_usado = novo_ip
        except urllib.error.HTTPError as retry:
            detalhe = _detalhe_http_companion(retry)
            if retry.code in (401, 403) or detalhe.lower() == "unauthorized":
                raise CompanionAuthError("token recusado pelo app Emily TV") from retry
            raise RuntimeError(detalhe) from retry
        except (urllib.error.URLError, TimeoutError, OSError) as retry:
            raise CompanionUnavailableError(
                f"Emily TV descoberta em {novo_ip}, mas não respondeu na porta {COMPANION_PORT}"
            ) from retry
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "resposta inválida do app Emily TV"))
    return data, ip_usado


def salvar_token_companion(token: str, alvo: str = "") -> Dict[str, Any]:
    """Valida na TV e só então associa o token exibido pelo app Emily TV."""
    dispositivos = _ler_catalogo()
    normalizado = (alvo or "").strip().lower()
    dispositivo = (next((d for d in dispositivos if d["id"] == alvo or d["ip"] == alvo or
                         d["nome"].lower() == normalizado), None) if alvo else
                   (next((d for d in dispositivos
                          if d.get("id") == _dispositivo_ativo.get("id")), None)
                    if _dispositivo_ativo else
                    (dispositivos[0] if len(dispositivos) == 1 else None)))
    if not dispositivo:
        return {"ok": False, "mensagem": "ERRO: selecione/conecte uma TV primeiro"}
    token = _normalizar_token_companion(token)
    if not _token_companion_valido(token):
        return {
            "ok": False,
            "mensagem": ("ERRO: token do Emily TV inválido. Ele deve ter exatamente "
                         "48 caracteres hexadecimais (somente 0-9 e a-f). Confira o "
                         "token exibido na TV; nenhum dado foi salvo."),
        }
    try:
        health, ip_autenticado = _companion_request_para(
            dispositivo, token, "GET", "/v1/health")
    except CompanionAuthError:
        return {
            "ok": False,
            "mensagem": ("ERRO: a TV recusou esse token. Confira os 48 caracteres "
                         "mostrados pelo app Emily TV; nenhum dado foi salvo."),
        }
    except CompanionUnavailableError as exc:
        return {
            "ok": False,
            "mensagem": (f"ERRO: {exc}. Deixe o app Emily TV aberto ou ativo na "
                         "mesma rede do PC e tente novamente; nenhum dado foi salvo."),
        }
    except Exception as exc:
        return {"ok": False,
                "mensagem": f"ERRO: não consegui validar o token na TV: {exc}"}
    if health.get("service") not in (None, "", "Emily TV Companion"):
        return {"ok": False,
                "mensagem": "ERRO: o endereço respondeu, mas não é o app Emily TV"}
    id_dispositivo = dispositivo["id"]
    for salvo in dispositivos:
        if salvo.get("id") == id_dispositivo:
            salvo["companion_token"] = token
            salvo["ip"] = ip_autenticado
            dispositivo = salvo
            break
    _escrever_catalogo(dispositivos)
    if _dispositivo_ativo.get("id") == dispositivo["id"]:
        _dispositivo_ativo.update(dispositivo)
    return {"ok": True,
            "mensagem": (f"App companheiro configurado e autenticado em "
                         f"{dispositivo['nome']}")}


def _companion_request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    dispositivo = _restaurar_dispositivo_ativo()
    if not dispositivo:
        raise RuntimeError("nenhuma TV ativa; use conectar_tv primeiro")
    token = _companion_token()
    if not token:
        raise RuntimeError("token do app Emily TV não configurado")
    try:
        data, ip_usado = _companion_request_para(dispositivo, token, method, path, body)
    except CompanionAuthError as exc:
        raise RuntimeError("token do app Emily TV recusado; configure o token atual mostrado na TV") from exc
    except CompanionUnavailableError as exc:
        raise RuntimeError(str(exc)) from exc
    if ip_usado != dispositivo.get("ip"):
        dispositivos = _ler_catalogo()
        for salvo in dispositivos:
            if salvo.get("id") == dispositivo.get("id"):
                salvo["ip"] = ip_usado
        _escrever_catalogo(dispositivos)
        _dispositivo_ativo["ip"] = ip_usado
    return data


def _token_ponte_local() -> str:
    """Mesmo segredo já usado pelo tela-pc.service; nunca é enviado à TV."""
    valor = str(__import__("os").environ.get("EMILY_PONTE_TOKEN", "")).strip()
    if valor:
        return valor
    try:
        for linha in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
            if linha.strip().startswith("EMILY_PONTE_TOKEN="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def _tela_pc_request(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else (
        b"" if method == "POST" else None)
    token = _token_ponte_local()
    headers = {"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(TELA_PC_URL + path, method=method, headers=headers, data=raw)
    try:
        with urllib.request.urlopen(request, timeout=45.0) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("erro", str(exc))
        except Exception:
            detail = str(exc)
        raise RuntimeError(detail) from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("erro") or data.get("error") or "falha no serviço de tela")
    return data


def compartilhar_tela_pc(preset: str = "1080p60", monitor: int = 1,
                         audio: bool = True) -> Dict[str, Any]:
    dispositivo = _restaurar_dispositivo_ativo()
    if not dispositivo:
        return {"ok": False, "mensagem": "ERRO: nenhuma TV ativa; use conectar_tv primeiro"}
    token = _companion_token()
    if not token:
        return {"ok": False, "mensagem": "ERRO: token do app Emily TV não configurado"}
    try:
        capacidades = _companion_request("GET", "/v1/screen/capabilities")
        if int(capacidades.get("protocol_version", 0)) < 1:
            raise RuntimeError("Emily TV não oferece WebRTC local")
        resultado = _tela_pc_request("POST", "/tela/webrtc/start", {
            "tv_ip": dispositivo["ip"], "tv_token": token, "preset": preset,
            "monitor": max(1, int(monitor)), "audio": bool(audio),
        })
        resultado["mensagem"] = (
            f"Tela do PC compartilhada em {resultado.get('preset', preset)} "
            f"via {resultado.get('encoder', 'H.264')}."
        )
        return resultado
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}"}


def parar_compartilhamento_tela() -> Dict[str, Any]:
    try:
        resultado = _tela_pc_request("POST", "/tela/webrtc/stop")
        resultado["mensagem"] = "Compartilhamento de tela encerrado."
        return resultado
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}"}


def status_compartilhamento_tela() -> Dict[str, Any]:
    try:
        return _tela_pc_request("GET", "/tela/webrtc/status")
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}"}


def _descobrir_companion_lan() -> Optional[str]:
    """Localiza a Emily TV por broadcast; não transmite token nem outras credenciais."""
    import socket
    probe = b"EMILY_TV_DISCOVER_V1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(1.5)
        sock.sendto(probe, ("255.255.255.255", COMPANION_DISCOVERY_PORT))
        raw, address = sock.recvfrom(1024)
        response = json.loads(raw.decode("utf-8"))
        return address[0] if response.get("service") == "Emily TV Companion" else None
    except Exception:
        return None
    finally:
        sock.close()


def listar_apps_instalados(incluir_sistema: bool = True) -> Dict[str, Any]:
    try:
        return _companion_request("GET", "/v1/apps?include_system=" +
                                  ("true" if incluir_sistema else "false"))
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}", "apps": []}


def abrir_app_instalado(nome_ou_pacote: str) -> Dict[str, Any]:
    if not (nome_ou_pacote or "").strip():
        return {"ok": False, "mensagem": "ERRO: nome do app vazio"}
    try:
        alvo = urllib.parse.quote(nome_ou_pacote.strip(), safe="")
        return _companion_request("POST", f"/v1/apps/{alvo}/launch")
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}"}


def tocar_video_cloud(url: str, titulo: str = "", cloud_token: str = "",
                      posicao_segundos: int = 0, velocidade: float = 1.0) -> Dict[str, Any]:
    """Abre o player cinematográfico do Emily TV com um stream autenticado da Cloud."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "mensagem": "ERRO: URL de vídeo inválida"}
    params = urllib.parse.urlencode({
        "url": url,
        "title": titulo or "Emily Cloud",
        "cloud_token": cloud_token or "",
        "position": max(0, int(posicao_segundos or 0)),
        "speed": max(0.25, min(2.0, float(velocidade or 1.0))),
        "autoplay": "true",
    })
    try:
        health = _companion_request("GET", "/v1/health")
        if int(health.get("version", 1)) < 3:
            return {"ok": False, "mensagem":
                    f"ERRO: Emily TV desatualizado (API v{health.get('version', 1)}); "
                    "instale o APK 1.2.0-cloud ou mais novo"}
        return _companion_request("POST", f"/v1/cloud/play?{params}")
    except Exception as exc:
        return {"ok": False, "mensagem": f"ERRO: {exc}"}


def resetar_pareamento() -> Dict[str, Any]:
    remote = _pareando.get("remote")
    dispositivo = _pareando.get("dispositivo")
    if remote is None:
        return {"ok": False,
                "mensagem": "ERRO: nenhum pareamento em andamento. Comece de novo."}
    codigo = (codigo or "").strip().upper()
    if not codigo:
        return {"ok": False, "mensagem": "ERRO: código vazio"}
    try:
        _submit(remote.async_finish_pairing(codigo), timeout=20.0)
    except Exception as e:
        _pareando.update({"remote": None, "dispositivo": None})
        try:
            remote.disconnect()
        except Exception:
            pass
        nome_erro = type(e).__name__
        if "InvalidAuth" in nome_erro:
            return {"ok": False, "mensagem": "ERRO: código incorreto ou recusado na TV."}
        if "ConnectionClosed" in nome_erro:
            return {"ok": False, "mensagem": "ERRO: pareamento cancelado na TV."}
        return {"ok": False, "mensagem": f"ERRO: {e}"}
    try:
        remote.disconnect()
    except Exception:
        pass
    _pareando.update({"remote": None, "dispositivo": None})
    _marcar_pareada(dispositivo["ip"], True)
    # Já deixa conectada, pra o próximo comando sair na hora (como o celular faz).
    try:
        conectar_dispositivo(dispositivo["id"])
    except Exception as e:
        _log(f"pós-pareamento: conexão imediata falhou ({e}); o watchdog resolve")
    return {"ok": True, "dispositivo": dispositivo,
            "mensagem": f"Pareada com {dispositivo['nome']}!"}


# ═════════════════════════════════════════════════════════════════
# COMANDOS
# ═════════════════════════════════════════════════════════════════

def _tv_ativa_ou_erro() -> Any:
    """Remote ativo; levanta erro AMIGÁVEL se nenhuma TV conectada."""
    with _lock:
        dispositivo = dict(_dispositivo_ativo)
    if not dispositivo:
        raise RuntimeError("nenhuma TV conectada — conecte num dispositivo salvo primeiro")
    return _garantir_conectado(dispositivo)


def enviar_tecla(tecla: str, texto: str = "") -> str:
    """Manda uma tecla (por nome amigável, KEYCODE_… ou TEXT:frase)."""
    try:
        remote = _tv_ativa_ou_erro()
    except Exception as e:
        return f"ERRO: {e}"
    chave = (tecla or "").strip().lower().replace(" ", "_")
    if texto.strip():
        return digitar_texto(texto)
    if chave.startswith("text:"):
        return digitar_texto(chave[5:])
    nome = TECLAS.get(chave) or APELIDOS_TECLA.get(chave) or chave.upper()
    if not nome.startswith("KEYCODE_"):
        nome = f"KEYCODE_{nome}"
    try:
        remote.send_key_command(nome)
        return f"OK: {nome} enviado na TV"
    except ValueError:
        return (f"ERRO: tecla desconhecida: '{tecla}' "
                f"(válidas: {', '.join(sorted(TECLAS))})")
    except Exception as e:
        return f"ERRO: {e}"


def _digitar_canal(remote, numero: str) -> None:
    """Dígitos do canal com o mesmo ritmo do celular (300ms, sem OK no final)."""
    for digito in numero:
        remote.send_key_command(f"KEYCODE_{digito}")
        time.sleep(0.3)


def sintonizar_canal(canal: str) -> str:
    """Espelho do enviarCanal do celular: abre 'TV ao vivo' (só se não abriu
    há pouco) e digita o número — aceita nome (globo/record) ou número."""
    nome_canal = (canal or "").strip().lower()
    numero = CANAIS.get(nome_canal) or "".join(c for c in nome_canal if c.isdigit())
    if not numero:
        return (f"ERRO: canal desconhecido: '{canal}'. Diga o número direto "
                f"ou um desses: {', '.join(sorted(CANAIS))}")
    try:
        remote = _tv_ativa_ou_erro()
    except Exception as e:
        return f"ERRO: {e}"
    try:
        global _ultimo_applink_em
        ja_aberto = (time.monotonic() - _ultimo_applink_em) < TV_APP_WINDOW_S
        if not ja_aberto:
            remote.send_launch_app_command(APP_TV_AO_VIVO)
            time.sleep(2.2)  # cold-start do app de TV, igual ao celular
        _ultimo_applink_em = time.monotonic()
        _digitar_canal(remote, numero)
        return f"OK: sintonizei o canal {numero}"
    except Exception as e:
        return f"ERRO: {e}"


def abrir_app(nome_app: str) -> str:
    """Abre app na TV pelo nome (mesma tabela do celular)."""
    link = APPS_TV.get((nome_app or "").strip().lower())
    if not link:
        return (f"ERRO: app de TV desconhecido: '{nome_app}'. "
                f"Conheço: {', '.join(sorted(APPS_TV))}.")
    try:
        remote = _tv_ativa_ou_erro()
    except Exception as e:
        return f"ERRO: {e}"
    try:
        remote.send_launch_app_command(link)
        return f"OK: abri {nome_app} na TV"
    except Exception as e:
        return f"ERRO: {e}"


def buscar_no_app(app: str, query: str) -> str:
    """Busca conteúdo dentro de um app da TV (YouTube/Netflix)."""
    if not (query or "").strip():
        return "ERRO: busca vazia"
    link = _link_busca(app, query)
    if not link:
        return f"ERRO: busca não suportada no app: '{app}' (use youtube ou netflix)"
    try:
        remote = _tv_ativa_ou_erro()
    except Exception as e:
        return f"ERRO: {e}"
    try:
        remote.send_launch_app_command(link)
        return f"OK: busquei '{query}' no {app} da TV"
    except Exception as e:
        return f"ERRO: {e}"


def digitar_texto(texto: str) -> str:
    """Digita texto num campo da TV (busca do YouTube, login, etc.)."""
    if not (texto or "").strip():
        return "ERRO: texto vazio"
    try:
        remote = _tv_ativa_ou_erro()
    except Exception as e:
        return f"ERRO: {e}"
    try:
        remote.send_text(texto)
        return f"OK: digitei '{texto}' na TV"
    except Exception as e:
        return f"ERRO: {e}"


def status_tv() -> str:
    """Diagnóstico: dispositivos salvos, ativa, e estado da conexão."""
    dispositivos = listar_dispositivos()
    if not dispositivos:
        return ("Nenhuma TV salva. Adicione o IP dela na aba TV das "
                "Configurações (ou me peça pra salvar).")
    linhas = [f"{len(dispositivos)} TV(s) salva(s):"]
    for d in dispositivos:
        marca = " ← ativa" if d.get("ativa") else ""
        tipo = f" · {d['tipo']}" if d.get("tipo") else ""
        pareada = "pareada" if d.get("pareada") else "não pareada"
        linhas.append(f"- {d['nome']} · {d['ip']}{tipo} · {pareada}{marca}")
    with _lock:
        ativo = dict(_dispositivo_ativo)
    if not ativo:
        linhas.append("Nenhuma conectada agora — clique num dispositivo ou me peça.")
        return "\n".join(linhas)
    if _precisa_parear.is_set():
        linhas.append("A TV recusou o certificado — precisa parear de novo.")
        return "\n".join(linhas)
    remote = _remotes.get(ativo.get("ip"))
    if remote is None:
        linhas.append(f"A ativa é {ativo['nome']}, mas a conexão caiu; "
                      "reconecto sozinha no próximo comando.")
        return "\n".join(linhas)
    try:
        em_ligado = remote.is_on
        app_atual = remote.current_app
        volume = remote.volume_info
    except Exception:
        em_ligado, app_atual, volume = None, None, None
    linha = f"Conectada em {ativo['nome']}: "
    linha += ("ligada" if em_ligado else
              ("desligada" if em_ligado is False else "estado desconhecido"))
    if app_atual:
        linha += f" · app em foco: {app_atual}"
    if volume:
        mudo = " (mudo)" if volume.get("muted") else ""
        linha += f" · volume {volume.get('level')}/{volume.get('max')}{mudo}"
    linhas.append(linha)
    return "\n".join(linhas)


def encerrar() -> None:
    """Encerramento explícito (mesmo efeito do atexit; útil nos testes)."""
    _encerrar()






