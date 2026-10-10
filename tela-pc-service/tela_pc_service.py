#!/usr/bin/env python3
"""
tela_pc_service.py — a tela do PC como um SERVIÇO, independente da Emily.

Por que este processo existe separado
─────────────────────────────────────
A versão anterior dessa função vivia dentro do servidor da Emily
(tela_stream.py + rotas /tela/* no servidor.py): só funcionava com a Emily
inteira de pé (LLM, bot do Discord, interface...) e ficava presa ao
spectacle, que entrega UM print por vez (~1 quadro por segundo, medido).

Este serviço usa o MESMO mecanismo que o OBS e os navegadores usam pra
compartilhar tela no Wayland: o portal org.freedesktop.portal.ScreenCast,
que entrega um nó do PipeWire — um fluxo de vídeo contínuo, não um print
de cada vez. Com GStreamer em cima, são dezenas de quadros por segundo.

E roda como serviço systemd --user: sobe com a sessão gráfica, não sabe
que a Emily existe. A Emily pode estar ligada ou desligada — tanto faz.

O QUE NÃO MUDA
──────────────
Portal e PipeWire continuam precisando de uma SESSÃO GRÁFICA ativa (o Vitor
logado no KDE). Isso é do Wayland, não é deste código.

A PRIMEIRA SESSÃO
─────────────────
Na primeira vez (ou se a permissão for revogada), o Start() abre o diálogo
do KDE pedindo pra compartilhar a tela. É a ÚNICA interação humana da vida
do serviço: a resposta volta com um restore_token, que é salvo em
~/.config/tela-pc-service/restore_token. Todas as sessões seguintes usam
esse token e o diálogo NÃO aparece mais — nem depois de reboot.
"""

from __future__ import annotations

import io
import re
import os
import signal
import struct
import subprocess
import sys
import threading
import time

# O gateway pede snapshots pontuais pelo mesmo módulo usado pela Emily desktop.
# Ele não abre uma sessão ScreenCast nem renova o espectador do MJPEG.
_RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ_PROJETO not in sys.path:
    sys.path.insert(0, _RAIZ_PROJETO)
from tela_monitors import authorized_sources, crop_pipeline
import tela_stream as captura_pontual  # noqa: E402

# ─────────────────────────────────────────────────────────────────
# Configuração
# ─────────────────────────────────────────────────────────────────

PORTA = int(os.getenv("TELA_PC_PORTA", "8790"))
# Mesmo token da Emily (o .env dela é a única fonte — o Vitor não cadastra
# senha nova em lugar nenhum).
_PASTA_ENV = "/home/Hiucksam/My Projects/Projeto Emily/minha-ia/.env"
_TOKEN = ""
try:
    with open(_PASTA_ENV, encoding="utf-8") as _f:
        for _linha in _f:
            _m = re.match(r"\s*EMILY_PONTE_TOKEN\s*=\s*(.+?)\s*$", _linha)
            if _m:
                _TOKEN = _m.group(1).strip().strip('"').strip("'")
                break
except OSError:
    pass

# Estado persistente (restore_token).
PASTA_CONFIG = os.path.expanduser("~/.config/tela-pc-service")
CAMINHO_TOKEN = os.path.join(PASTA_CONFIG, "restore_token")

FPS_ALVO = int(os.getenv("TELA_PC_FPS", "60"))
LARGURA_PADRAO = int(os.getenv("TELA_PC_LARGURA", "1280"))
QUALIDADE_JPEG = int(os.getenv("TELA_PC_QUALIDADE", "82"))
VIDA_SEM_ESPECTADOR = float(os.getenv("TELA_PC_VIDA", "45"))
VIDA_STREAM = float(os.getenv("TELA_PC_VIDA_STREAM", "3600"))

_PASTA_TMP = os.path.join(os.getenv("TMPDIR", "/tmp"), "tela-pc-service")
os.makedirs(_PASTA_TMP, exist_ok=True)
os.makedirs(PASTA_CONFIG, exist_ok=True)


def _log(msg: str) -> None:
    print(f"[TELA-PC] {msg}", flush=True)


def token_ok(header: str | None) -> bool:
    """Mesma semântica do _ponte_token_ok() da Emily."""
    if not _TOKEN:
        return False
    import hmac
    return hmac.compare_digest(header or "", f"Bearer {_TOKEN}")

# ─────────────────────────────────────────────────────────────────
# Lado D-Bus: portal ScreenCast
#
# O portal segue o padrão "Request": chamar o método devolve um caminho de
# objeto (ex.: /org/freedesktop/portal/desktop/request/SENDER/TOKEN) e a
# RESPOSTA DE VERDADE chega pelo sinal Response desse caminho. Assina-se o
# sinal ANTES de chamar, e espera-se num Event.
# ─────────────────────────────────────────────────────────────────

import dbus  # noqa: E402  (pacote python3-dbus do Fedora)
from dbus.mainloop.glib import DBusGMainLoop  # noqa: E402
from gi.repository import GLib  # noqa: E402

_BUS = None
_LOOP = None


def _iniciar_dbus() -> None:
    """Conecta ao bus da sessão e gira um MainLoop próprio em thread daemon."""
    global _BUS, _LOOP
    if _BUS is not None:
        return
    DBusGMainLoop(set_as_default=True)
    _BUS = dbus.SessionBus()
    _LOOP = GLib.MainLoop()
    threading.Thread(target=_LOOP.run, name="tela-pc-dbus", daemon=True).start()
    _log("sessão D-Bus conectada")


def _ler_token_salvo() -> str:
    try:
        with open(CAMINHO_TOKEN, encoding="utf-8") as f:
            t = f.read().strip()
        return t if t else ""
    except OSError:
        return ""


def _salvar_token(token: str) -> None:
    if not token:
        return
    with open(CAMINHO_TOKEN, "w", encoding="utf-8") as f:
        f.write(token)
    _log(f"restore_token salvo em {CAMINHO_TOKEN} (próximas sessões: sem diálogo)")


def _pedido_token() -> str:
    """Token único pro caminho do Request (tem que mudar a cada chamada)."""
    return f"emily_{int(time.time() * 1000):x}"


def _caminho_request(bus, token: str) -> str:
    """Caminho do Request ANTES de chamar — regra da especificação dos
    portais: /org/freedesktop/portal/desktop/request/SENDER/TOKEN, onde
    SENDER é o nome único do caller sem o ':' inicial e com '.'→'_',
    e TOKEN é o handle_token enviado nas opções."""
    remetente = bus.get_unique_name().lstrip(":").replace(".", "_")
    return f"/org/freedesktop/portal/desktop/request/{remetente}/{token}"


class RespostaPortal:
    """Espera o sinal Response do caminho de Request informado."""

    def __init__(self, bus, caminho: str) -> None:
        self._bus = bus
        self._evento = threading.Event()
        self._res = -1
        self._dados: dict = {}
        self._caminhos: set[str] = set()
        self.conectar_tambem(caminho)

    def _ao_responder(self, res, dados, **_kwargs) -> None:
        """Dispara no main loop daemon (thread tela-pc-dbus)."""
        if self._evento.is_set():
            return
        self._res = int(res)
        self._dados = dict(dados or {})
        self._evento.set()

    def conectar_tambem(self, caminho: str) -> None:
        """Assina o Response de mais um caminho (idempotente). Chamado
        antes do método disparar o sinal."""
        if caminho and caminho not in self._caminhos:
            self._caminhos.add(caminho)
            self._bus.add_signal_receiver(
                self._ao_responder,
                signal_name="Response",
                dbus_interface="org.freedesktop.portal.Request",
                path=caminho)

    def esperar(self, timeout: float = 120.0) -> tuple[int, dict]:
        ok = self._evento.wait(timeout)
        for caminho in self._caminhos:
            self._bus.remove_signal_receiver(
                self._ao_responder,
                signal_name="Response",
                dbus_interface="org.freedesktop.portal.Request",
                path=caminho)
        if not ok:
            raise RuntimeError(
                "o portal não respondeu a tempo — o diálogo ficou aberto na tela?")
        return self._res, self._dados


class PortalScreencast:
    """Uma sessão de screencast completa: permissão + fds do PipeWire."""

    def __init__(self) -> None:
        _iniciar_dbus()
        self.portal = _BUS.get_object(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        self.iface = "org.freedesktop.portal.ScreenCast"
        # Interface vinculada EXPLICITAMENTE: o objeto do portal exporta várias
        # interfaces (Screenshot, ScreenCast, RemoteDesktop...) e o getattr no
        # proxy cru resolvia errado — a chamada ia pro lugar errado.
        self.iface_obj = dbus.Interface(self.portal, self.iface)
        self.sessao: str = ""
        self.fd: int = -1          # fd do remote do PipeWire
        self.streams: list[dict] = []   # [{node, posicao?, tamanho?}, ...]

    def _opcoes(self, extra: dict, com_token_sessao: bool = False,
                token: str = ""):
        # Opções sempre como a{sv}: dbus.Dictionary com signature="sv" faz o
        # wrap em Variant automaticamente — nesta versão do dbus-python
        # (1.4+) o tipo dbus.Variant nem existe mais, e dict cru vira a{ss}
        # (o portal rejeita com InvalidArgs "(a{ss}) não equivale (a{sv})").
        opcoes = {"handle_token": dbus.String(token or _pedido_token())}
        if com_token_sessao:
            # OBRIGATÓRIO no CreateSession: sem session_handle_token o
            # xdg-desktop-portal 1.22 aborta com SIGABRT (assert
            # "session->token != NULL" em xdp-session.c:296) e derruba o
            # portal inteiro — medido com coredump.
            opcoes["session_handle_token"] = dbus.String(_pedido_token())
        for k, v in extra.items():
            opcoes[k] = v
        return dbus.Dictionary(opcoes, signature="sv")

    def _chamar_e_esperar(self, metodo, *args, token: str = "") -> tuple[int, dict]:
        # Assina o Response ANTES da chamada, no caminho determinístico
        # (nome único do caller + handle_token, regra da especificação) —
        # assim o sinal nunca é perdido numa corrida com o main loop.
        token = token or _pedido_token()
        resp = RespostaPortal(_BUS, _caminho_request(_BUS, token))
        retorno = getattr(self.iface_obj, metodo)(*args)
        resp.conectar_tambem(str(retorno))  # se o portal usar outro caminho
        return resp.esperar()

    def abrir(self) -> None:
        """Sessão inteira. Levanta RuntimeError com mensagem humana."""
        # 1. CreateSession — sessão nova sempre com token novo.
        token_cs = _pedido_token()
        res, dados = self._chamar_e_esperar(
            "CreateSession",
            self._opcoes({}, com_token_sessao=True, token=token_cs),
            token=token_cs)
        if res != 0:
            raise RuntimeError(f"CreateSession recusado (resposta {res})")
        self.sessao = str(dados.get("session_handle", ""))
        if not self.sessao:
            raise RuntimeError("portal não devolveu session_handle")
        _log(f"sessão criada: {self.sessao.rsplit('/', 1)[-1]}")

        # 2. SelectSources — monitores inteiros, múltiplos, persistente.
        token_salvo = _ler_token_salvo()
        opcoes_select = {
            "types": dbus.UInt32(1),            # 1 = MONITOR
            "multiple": dbus.Boolean(True),     # os monitores todos de uma vez
            "persist_mode": dbus.UInt32(2),     # 2 = persistente até revogar
            "cursor_mode": dbus.UInt32(1),      # 1 = cursor escondido
        }
        if token_salvo:
            opcoes_select["restore_token"] = dbus.String(token_salvo)
            _log("usando restore_token salvo (sem diálogo)")
        else:
            _log("*** PRIMEIRA SESSÃO: o KDE vai abrir o DIÁLOGO DE PERMISSÃO "
                 "na sua tela — escolha os monitores e confirme ***")
        token_ss = _pedido_token()
        res, dados = self._chamar_e_esperar(
            "SelectSources", dbus.ObjectPath(self.sessao),
            self._opcoes(opcoes_select, token=token_ss), token=token_ss)
        if res != 0:
            raise RuntimeError(
                f"escolha de telas negada/cancelada (resposta {res})")

        # 3. Start — dispara o diálogo SÓ se não havia token válido. O token
        # (novo ou reemitido) e a lista de streams vêm NA RESPOSTA do Start.
        token_st = _pedido_token()
        res, dados = self._chamar_e_esperar(
            "Start", dbus.ObjectPath(self.sessao),
            dbus.String(""), self._opcoes({}, token=token_st), token=token_st)
        if res != 0:
            raise RuntimeError(f"Start recusado (resposta {res})")

        novo_token = str(dados.get("restore_token", "") or "")
        if novo_token and novo_token != token_salvo:
            _salvar_token(novo_token)

        for item in (dados.get("streams", []) or []):
            node_id = int(item[0])
            atributos = dict(item[1] or {}) if len(item) > 1 else {}
            stream = {"node": node_id}
            try:
                pos = atributos.get("position")
                if pos is not None:
                    stream["posicao"] = (int(pos[0]), int(pos[1]))
                tam = atributos.get("size")
                if tam is not None:
                    stream["tamanho"] = (int(tam[0]), int(tam[1]))
            except Exception:  # noqa: BLE001
                pass
            self.streams.append(stream)
        _log(f"streams autorizados: {self.streams}")
        if not self.streams:
            raise RuntimeError("o portal não devolveu nenhum stream")

        # 4. OpenPipeWireRemote — o fd de onde nascem as pipelines.
        fd_bruto = self.iface_obj.OpenPipeWireRemote(
            dbus.ObjectPath(self.sessao), self._opcoes({}))
        # dbus-python devolve UnixFd; o inteiro do fd é o que o pipewiresrc quer
        self.fd = fd_bruto.take() if hasattr(fd_bruto, "take") else int(fd_bruto)
        _log(f"remote do PipeWire aberto (fd {self.fd})")

    def fechar(self) -> None:
        """Encerra a sessão do portal (o token salvo continua válido)."""
        if not self.sessao:
            return
        try:
            sessao = _BUS.get_object("org.freedesktop.portal.Desktop", self.sessao)
            sessao.Close(dbus_interface="org.freedesktop.portal.Session")
            _log("sessão do portal fechada")
        except Exception as e:  # noqa: BLE001
            _log(f"fechar sessão: {e}")
        self.sessao = ""
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
# ─────────────────────────────────────────────────────────────────
# GStreamer: uma pipeline por monitor
# ─────────────────────────────────────────────────────────────────

import gi  # noqa: E402
gi.require_version("Gst", "1.0")  # noqa: E402
from gi.repository import Gst  # noqa: E402

Gst.init([])


class PipelineMonitor:
    """pipewiresrc do node do portal → JPEG → appsink (sempre o mais recente)."""

    def __init__(self, indice: int, fd: int, node: int,
                 tamanho: tuple[int, int] | None = None, crop: str = ""):

        self.indice = indice
        self.trava = threading.Lock()
        self.novo_frame = threading.Condition(self.trava)
        self.frame = b""
        self.ts = 0.0
        self.total = 0
        self.ultimo_hash = None
        self.t0 = time.time()
        self.erro = ""

        origem_w, origem_h = tamanho or (16, 9)
        origem_w = max(1, int(origem_w))
        origem_h = max(1, int(origem_h))
        altura_alvo = max(2, round(LARGURA_PADRAO * origem_h / origem_w))
        # I420 exige dimensões pares.
        altura_alvo += altura_alvo % 2
        desc = (
            f"pipewiresrc fd={fd} path={node} keepalive-time=1000 ! "
            f"{crop}videoconvert ! videoscale n-threads=2 ! videorate ! "
            f"video/x-raw,format=I420,width={LARGURA_PADRAO},height={altura_alvo},"
            f"pixel-aspect-ratio=1/1,framerate={FPS_ALVO}/1 ! "
            f"jpegenc quality={QUALIDADE_JPEG} ! "
            "appsink name=saida emit-signals=true max-buffers=1 drop=true"
        )
        self.pipeline = Gst.parse_launch(desc)
        self.appsink = self.pipeline.get_by_name("saida")
        self.appsink.connect("new-sample", self._nova_amostra)

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._erro_gst)

    def _erro_gst(self, _bus, msg):
        erro, _debug = msg.parse_error()
        self.erro = erro.message or ""
        with self.novo_frame:
            self.novo_frame.notify_all()
        _log(f"pipeline M{self.indice}: erro GStreamer: {self.erro[:160]}")

    def _nova_amostra(self, sink):
        amostra = sink.emit("pull-sample")
        if amostra is None:
            return Gst.FlowReturn.ERROR
        buf = amostra.get_buffer()
        ok, mapa = buf.map(Gst.MapFlags.READ)
        if ok:
            # [:mapa.size]: mapa.data pode incluir padding além do payload
            # válido (o Android decodifica JPEG mesmo com lixo no fim, mas o
            # hash de dedupe mudaria a cada quadro e mataria a economia).
            jpeg = bytes(mapa.data)[:mapa.size]
            with self.novo_frame:
                self.frame = jpeg
                self.total += 1
                # Dedupe por CONTEÚDO: o videorate repete o último quadro pra
                # bater no framerate-alvo (60). Repetição idêntica NÃO avança
                # self.ts nem acorda os espectadores — tela parada custa zero
                # rede; tela mudando entrega até o teto de fps real.
                hash_atual = hash(jpeg)
                if hash_atual != self.ultimo_hash:
                    self.ultimo_hash = hash_atual
                    self.ts = time.time()
                    self.novo_frame.notify_all()
            buf.unmap(mapa)
        return Gst.FlowReturn.OK

    def iniciar(self) -> None:
        self.pipeline.set_state(Gst.State.PLAYING)

    def parar(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        with self.novo_frame:
            self.novo_frame.notify_all()

    def ultimo(self) -> tuple[bytes, float]:
        with self.trava:
            return self.frame, self.ts

    def esperar_novo(self, depois_de: float, timeout: float = 2.0) -> tuple[bytes, float]:
        """Espera o appsink produzir um frame posterior, sem polling."""
        with self.novo_frame:
            self.novo_frame.wait_for(
                lambda: self.ts > depois_de or bool(self.erro), timeout=timeout)
            return self.frame, self.ts

    def fps(self) -> float:
        decorrido = time.time() - self.t0
        return self.total / decorrido if decorrido > 0.5 else 0.0


def _nome_estado(estado) -> str:
    """Nome do Gst.State nesta binding (Gst.element_state_get_name não existe)."""
    try:
        return Gst.Element.state_get_name(estado)
    except Exception:  # noqa: BLE001
        return str(estado)


class Gerenciador:
    """Liga/desliga portal + pipelines conforme a demanda de espectadores."""

    def __init__(self) -> None:
        self.trava = threading.RLock()
        self.portal: PortalScreencast | None = None
        self.pipelines: dict[int, PipelineMonitor] = {}
        self.rodando = False
        self.erro = ""
        self.ultima_demanda = 0.0
        self._vigia: threading.Thread | None = None
        self._parar_vigia = threading.Event()

    def demandar(self, monitor: int = 1) -> None:
        with self.trava:
            self.ultima_demanda = time.time()
            if not self.rodando:
                self._ligar(monitor)
            elif monitor not in self.pipelines:
                self._ligar_pipeline(monitor)

    def batimento(self) -> None:
        """Mantém a captura acordada sem reverter uma troca de monitor."""
        with self.trava:
            self.ultima_demanda = time.time()

    def _streams_ordenados(self) -> list[dict]:
        if self.portal is None:
            return []
        return authorized_sources(self.portal.streams)

    def _ligar_pipeline(self, monitor: int) -> PipelineMonitor | None:
        """Liga somente o monitor assistido; evita codificar dois JPEGs a 15fps."""
        if monitor in self.pipelines:
            return self.pipelines[monitor]
        streams = self._streams_ordenados()
        if monitor < 1 or monitor > len(streams) or self.portal is None:
            raise ValueError("Monitor não autorizado ou inexistente")
        # O app exibe um monitor por vez. Ao trocar, encerra a codificação
        # anterior imediatamente em vez de manter duas jpegenc disputando CPU.
        for indice, antiga in list(self.pipelines.items()):
            try:
                antiga.parar()
            finally:
                self.pipelines.pop(indice, None)
            _log(f"pipeline M{indice} parada (troca para M{monitor})")
        s = streams[monitor - 1]
        pm = PipelineMonitor(monitor, self.portal.fd, s["node"], s.get("tamanho"), crop_pipeline(s))
        pm.iniciar()
        self.pipelines[monitor] = pm
        _ok, estado, _pend = pm.pipeline.get_state(2 * Gst.SECOND)
        _log(f"pipeline M{monitor} no ar (node {s['node']}, estado "
             f"{_nome_estado(estado)})")
        return pm

    def _ligar(self, monitor: int = 1) -> None:
        try:
            portal = PortalScreencast()
            portal.abrir()
            self.portal = portal
            if monitor > 0:
                self._ligar_pipeline(monitor)
            self.rodando = True
            self.erro = ""
            if self._vigia is None or not self._vigia.is_alive():
                self._parar_vigia.clear()
                self._vigia = threading.Thread(
                    target=self._vigiar, name="tela-pc-vigia", daemon=True)
                self._vigia.start()
        except Exception as e:  # noqa: BLE001
            self.erro = f"{type(e).__name__}: {e}"
            _log(f"FALHA ao ligar: {self.erro}")
            self._desligar()
            if 'portal' in locals() and portal is not self.portal:
                portal.fechar()
            raise

    def _desligar(self) -> None:
        """Para pipelines e fecha a sessão do portal. CHAMAR COM self.trava
        NAS MÃOS (só o vigia chama). O restore_token salvo continua válido —
        a próxima sessão sobe sem diálogo."""
        for pm in self.pipelines.values():
            try:
                pm.parar()
            except Exception:  # noqa: BLE001
                pass
        self.pipelines.clear()
        if self.portal is not None:
            self.portal.fechar()
            self.portal = None
        self.rodando = False
        _log("captura desligada (ninguém assistindo)")

    def desligar(self) -> None:
        """Desligamento público/idempotente usado pelo SIGTERM do systemd."""
        with self.trava:
            self._parar_vigia.set()
            if self.rodando or self.portal is not None or self.pipelines:
                self._desligar()

    def _vigiar(self) -> None:
        """Vigia de ociosidade: se ninguém marcar demanda (streams vivos
        marcam a cada quadro) por VIDA_SEM_ESPECTADOR, desliga tudo."""
        batidas = 0
        while not self._parar_vigia.wait(2.0):
            with self.trava:
                if not self.rodando:
                    continue
                # Batimento de diagnóstico a cada ~30s (15 ciclos de 2s).
                batidas += 1
                if batidas % 15 == 0:
                    resumo = ", ".join(
                        f"M{pm.indice}={pm.total}q/{pm.fps():.1f}fps"
                        f"/est:{_nome_estado(pm.pipeline.get_state(0)[1])}"
                        for pm in self.pipelines.values())
                    _log(f"batimento: {resumo or 'sem pipelines'}")
                if time.time() - self.ultima_demanda < VIDA_SEM_ESPECTADOR:
                    continue
                self._desligar()
# ─────────────────────────────────────────────────────────────────
# HTTP: MJPEG stream + diagnóstico
# ─────────────────────────────────────────────────────────────────

from flask import Flask, Response, jsonify, request  # noqa: E402

app = Flask(__name__)
GER = Gerenciador()


@app.route("/")
def saude():
    if not _TOKEN:
        return jsonify({"erro": "EMILY_PONTE_TOKEN não configurado"}), 503
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    return jsonify({
        "ok": True,
        "servico": "tela-pc",
        "fps_alvo": FPS_ALVO,
        "largura": LARGURA_PADRAO,
        "rodando": GER.rodando,
        "audio": bool(_dispositivo_monitor()),
    })


@app.route("/tela/monitores")
def tela_monitores():
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    try:
        with GER.trava:
            if not GER.rodando:
                GER._ligar(0)
            GER.batimento()
            monitores = [{"indice": i, "nome": stream.get("nome", f"Monitor {i}"),
                          "largura": stream.get("tamanho", (0, 0))[0],
                          "altura": stream.get("tamanho", (0, 0))[1]}
                         for i, stream in enumerate(GER._streams_ordenados(), 1)]
        return jsonify({"ok": True, "monitores": monitores})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "erro": str(e)[:200]}), 500


@app.route("/tela/estado")
def tela_estado():
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    with GER.trava:
        pipelines = {f"M{i}": {
            "fps": round(pm.fps(), 1),
            "total": pm.total,
            "idade": round(time.time() - pm.ts, 1) if pm.ts else None,
            "erro": pm.erro or None,
        } for i, pm in sorted(GER.pipelines.items())}
    return jsonify({
        "ok": True,
        "rodando": GER.rodando,
        "erro": GER.erro or None,
        "token_configurado": bool(_TOKEN),
        "pipelines": pipelines,
    })


@app.route("/tela/stream")
def tela_stream():
    """MJPEG contínuo: multipart/x-mixed-replace, 1 parte por quadro."""
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    try:
        monitor = int(request.args.get("monitor", "1"))
        GER.demandar(monitor)
    except (ValueError, TypeError) as exc:
        return jsonify(ok=False, erro=str(exc)), 400

    def gerar():
        try:
            GER.trava.acquire()
            pm = GER.pipelines.get(monitor)
            limite = time.time() + VIDA_STREAM
        finally:
            GER.trava.release()
        if pm is None:
            # Pipeline ainda subindo (o portal pode ter aberto agora): espera.
            t_limite = time.time() + 10.0
            while time.time() < t_limite:
                GER.trava.acquire()
                pm = GER.pipelines.get(monitor)
                GER.trava.release()
                if pm is not None:
                    break
                time.sleep(0.25)
            if pm is None:
                # Pipeline ainda não existe: manda o quadro de erro e fecha.
                yield _mjpeg_uma_parte(_jpeg_erro(
                    "nenhuma pipeline pra este monitor — o PC autorizou?"))
                return
        # Espera o pipewiresrc negociar e chegar em PLAYING (até 15s).
        t_negociando = time.time() + 15.0
        while time.time() < t_negociando:
            if pm.erro:
                break
            estado = pm.pipeline.get_state(0)[1]
            if estado == Gst.State.PLAYING:
                break
            if estado == Gst.State.NULL:
                return
            time.sleep(0.1)
        ultimo_ts = 0.0
        ultimo_envio = 0.0
        while time.time() < limite:
            GER.batimento()
            if pm.erro:
                yield _mjpeg_uma_parte(_jpeg_erro(f"pipeline: {pm.erro}"))
                return
            if pm.pipeline.get_state(0)[1] == Gst.State.NULL:
                return
            frame, ts = pm.esperar_novo(ultimo_ts)
            # Entrega cada quadro produzido pelo appsink UMA vez. Antes o loop
            # repetia o mesmo JPEG a cada 30 ms; o Android descartava repetidos,
            # mas a rede carregava até o dobro do necessário.
            if frame and (ts > ultimo_ts or time.time() - ultimo_envio >= 5):
                ultimo_ts = ts
                ultimo_envio = time.time()
                yield _mjpeg_uma_parte(frame)
                # Espectador vivo: adia o vigia de ociosidade (e religa a
                # captura se o vigia derrubou no meio da conexão).
                GER.batimento()
        # Conexao encerra; o cliente reconecta e o vigia reabre se preciso.

    return Response(gerar(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/tela/jpg")
def tela_jpg():
    """Snapshot do pipeline moderno, compatível com APKs antigos.

    O APK anterior consulta um JPEG a cada ~1,15 s. Esta rota não transforma
    isso em 15 fps, mas evita o GET 503 quando a Emily desktop está fechada.
    O APK novo usa /tela/stream e recebe o MJPEG contínuo.
    """
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    try:
        monitor = max(1, int(request.args.get("monitor", "1")))
    except (TypeError, ValueError):
        monitor = 1
    if request.args.get("unico") == "1":
        try:
            frame, idade = captura_pontual.capturar_jpeg(monitor=monitor, unico=True)
            resposta = Response(frame, mimetype="image/jpeg")
            resposta.headers["X-Emily-Idade"] = f"{idade:.2f}"
            resposta.headers["X-Emily-Fonte"] = "captura-pontual"
            resposta.headers["Cache-Control"] = "no-store"
            return resposta
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            return jsonify({"erro": f"captura pontual falhou: {type(exc).__name__}: {exc}"}), 503
    try:
        GER.demandar(monitor)
        limite = time.time() + 20.0
        pm = None
        frame = None
        ts = 0.0
        while time.time() < limite:
            with GER.trava:
                pm = GER.pipelines.get(monitor)
            if pm is not None:
                frame, ts = pm.ultimo()
                if frame:
                    break
                if pm.erro:
                    return jsonify({"erro": f"pipeline: {pm.erro}"}), 503
            time.sleep(0.1)
        if not frame:
            return jsonify({"erro": "captura ainda não produziu quadro"}), 503
        resposta = Response(frame, mimetype="image/jpeg")
        resposta.headers["X-Emily-Idade"] = f"{max(0.0, time.time() - ts):.2f}"
        resposta.headers["X-Emily-Fonte"] = "tela-pc-service"
        resposta.headers["Cache-Control"] = "no-store"
        return resposta
    except Exception as exc:  # noqa: BLE001
        return jsonify({"erro": f"snapshot falhou: {type(exc).__name__}: {exc}"}), 500


@app.route("/tela/audio")
def tela_audio():
    """Som do PC como PCM cru (S16LE 48 kHz estéreo), stream contínuo.

    O cliente toca direto num AudioTrack (sem decodificador). Formato
    anunciado nos headers X-Audio-* pra o app validar antes de tocar.
    """
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    dispositivo = _dispositivo_monitor()
    if not dispositivo:
        return jsonify({"erro": "nenhuma saída de som padrão no PC"}), 503

    def gerar():
        cliente = None
        try:
            cliente = AudioCliente(dispositivo)
            # Cabeçalho textual único com o formato (o app valida/toca).
            yield (
                f"EMILY-AUDIO {AudioCliente.TAXA} {AudioCliente.CANAIS} 16\n".encode()
            )
            while True:
                dados = cliente.amostra()
                if not dados:
                    break
                yield dados
        except GeneratorExit:
            pass
        finally:
            if cliente is not None:
                cliente.parar()

    resposta = Response(gerar(), mimetype="application/octet-stream")
    resposta.headers["X-Audio-Taxa"] = str(AudioCliente.TAXA)
    resposta.headers["X-Audio-Canais"] = str(AudioCliente.CANAIS)
    resposta.headers["X-Audio-Bits"] = "16"
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.route("/tela/audio/estado")
def tela_audio_estado():
    """Diagnóstico: há saída de som padrão? (sem abrir captura)."""
    if not token_ok(request.headers.get("Authorization")):
        return jsonify({"erro": "token inválido"}), 401
    dispositivo = _dispositivo_monitor()
    return jsonify({"ok": True, "dispositivo": dispositivo or None,
                    "disponivel": bool(dispositivo)})


# mss é só pra geometria aqui (o kscreen-doctor dos nomes é opcional).
import mss  # noqa: E402

def _jpeg_erro(texto: str) -> bytes:
    """Quadro preto com o erro escrito — o cliente vê o motivo direto."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 200), (10, 10, 10))
    d = ImageDraw.Draw(img)
    d.text((20, 80), texto[:90], fill=(220, 120, 90))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=60)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────
# ÁUDIO — o som do PC junto com a tela
#
# O portal ScreenCast entrega só VÍDEO; o som vem do PipeWire direto:
# capturamos o "monitor" da saída padrão (o mesmo fluxo que o OBS usa
# pra gravar o áudio do sistema). Cada espectador de áudio tem a própria
# captura: pull-sample BLOQUEIA até o próximo chunk, então o ritmo é o
# do consumidor e nenhum sample é descartado (zero glitch).
# ─────────────────────────────────────────────────────────────────

_SINK_CACHE = (0.0, "")


def _dispositivo_monitor() -> str:
    """Device "<sink>.monitor" da saída de som padrão (cache de 5s)."""
    global _SINK_CACHE
    if time.time() - _SINK_CACHE[0] < 5.0:
        return _SINK_CACHE[1]
    nome = ""
    try:
        _r = subprocess.run(["pactl", "get-default-sink"],
                            capture_output=True, text=True, timeout=3)
        nome = (_r.stdout or "").strip()
    except Exception:  # noqa: BLE001
        nome = ""
    dispositivo = f"{nome}.monitor" if nome else ""
    _SINK_CACHE = (time.time(), dispositivo)
    return dispositivo


class AudioCliente:
    """Captura PCM do monitor da saída padrão (S16LE 48 kHz estéreo)."""

    TAXA = 48000
    CANAIS = 2

    def __init__(self, dispositivo: str):
        self.pipeline = Gst.parse_launch(
            f'pulsesrc device="{dispositivo}" ! audioconvert ! audioresample ! '
            'audio/x-raw,format=S16LE,layout=interleaved,'
            f'rate={self.TAXA},channels={self.CANAIS} ! '
            'appsink name=som emit-signals=false sync=false max-bytes=0'
        )
        self.appsink = self.pipeline.get_by_name("som")
        self.pipeline.set_state(Gst.State.PLAYING)

    def amostra(self, timeout_s: float = 5.0):
        """Espera (bloqueante) o próximo chunk de PCM. None = parou/timeout."""
        fim = time.time() + timeout_s
        while time.time() < fim:
            if self.pipeline.get_state(0)[1] == Gst.State.NULL:
                return None
            amostra = self.appsink.emit("pull-sample")
            if amostra is None:
                return None
            buf = amostra.get_buffer()
            ok, mapa = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                # [:mapa.size] ESSENCIAL: mapa.data pode incluir padding além
                # do payload válido. Um byte a mais desalinia os samples 16-bit
                # e vira chiado contínuo no AudioTrack (bug do "chiado de TV").
                return bytes(mapa.data[:mapa.size])
            finally:
                buf.unmap(mapa)
        return None

    def parar(self) -> None:
        try:
            self.pipeline.set_state(Gst.State.NULL)
        except Exception:  # noqa: BLE001
            pass


def _monitores_humana() -> list[dict]:
    """Lista na ordem humana (mesma lógica do tela_stream.py da Emily)."""
    with mss.mss() as sct:
        mons = list(sct.monitors)
    virtual, reais = mons[0], mons[1:]
    lista = []
    for m in reais:
        lista.append({"left": m["left"], "top": m["top"],
                      "largura": m["width"], "altura": m["height"]})
    lista.sort(key=lambda x: (x["left"], x["top"]))
    for i, item in enumerate(lista, 1):
        item["indice"] = i
        item["nome"] = f"Monitor {i}"
    return lista


# WebRTC fica isolado do pipeline MJPEG para o fallback legado continuar
# disponível mesmo se algum plugin moderno estiver ausente.
from tela_webrtc import GerenciadorWebRtc  # noqa: E402

from tela_mobile_rtc import MobileRtcManager, ice_config
MOBILE_RTC = MobileRtcManager(GER, _dispositivo_monitor)

@app.route("/tela/rtc/config")
def mobile_rtc_config():
    if not token_ok(request.headers.get("Authorization")):
        return jsonify(erro="token inválido"), 401
    return jsonify(ok=True, **ice_config())

@app.route("/tela/rtc/sessions", methods=["POST"])
def mobile_rtc_start():
    if not token_ok(request.headers.get("Authorization")):
        return jsonify(erro="token inválido"), 401
    try:
        return jsonify(MOBILE_RTC.start(request.get_json(silent=True) or {}))
    except (ValueError, TypeError):
        return jsonify(ok=False, erro="Parâmetros de transmissão inválidos"), 400
    except Exception as exc:
        _log(f"WebRTC Android: {exc}")
        return jsonify(ok=False, erro="Não foi possível iniciar o vídeo do PC"), 503

@app.route("/tela/rtc/sessions/<session_id>", methods=["POST", "DELETE"])
def mobile_rtc_session(session_id):
    if not token_ok(request.headers.get("Authorization")):
        return jsonify(erro="token inválido"), 401
    result = MOBILE_RTC.stop(session_id) if request.method == 'DELETE' else MOBILE_RTC.heartbeat(session_id)
    return jsonify(result)

WEBRTC = GerenciadorWebRtc(PortalScreencast, _dispositivo_monitor, _log)


def _controle_local_ok() -> bool:
    """Start/stop levam o token da TV e nunca são expostos pelo gateway/LAN."""
    remoto = request.remote_addr or ""
    return remoto in {"127.0.0.1", "::1"} and token_ok(request.headers.get("Authorization"))


@app.post("/tela/webrtc/start")
def tela_webrtc_start():
    if not _controle_local_ok():
        return jsonify({"ok": False, "erro": "controle local não autorizado"}), 403
    dados = request.get_json(silent=True) or {}
    try:
        resultado = WEBRTC.iniciar(
            tv_ip=str(dados.get("tv_ip", "")).strip(),
            tv_token=str(dados.get("tv_token", "")).strip(),
            preset=str(dados.get("preset", "1080p60")),
            monitor=max(1, int(dados.get("monitor", 1))),
            audio=bool(dados.get("audio", True)),
        )
        return jsonify(resultado)
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "erro": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        _log(f"WebRTC: falha ao iniciar: {exc}")
        return jsonify({"ok": False, "erro": str(exc)}), 503


@app.get("/tela/webrtc/status")
def tela_webrtc_status():
    if not _controle_local_ok():
        return jsonify({"ok": False, "erro": "controle local não autorizado"}), 403
    return jsonify(WEBRTC.status())


@app.post("/tela/webrtc/stop")
def tela_webrtc_stop():
    if not _controle_local_ok():
        return jsonify({"ok": False, "erro": "controle local não autorizado"}), 403
    return jsonify(WEBRTC.parar())


def _mjpeg_uma_parte(jpeg: bytes) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
        + jpeg + b"\r\n"
    )




def main() -> None:
    _log(f"serviço de tela na porta {PORTA} "
         f"(token {'CONFIGURADO' if _TOKEN else 'ABERTO — defina EMILY_PONTE_TOKEN'})")
    _iniciar_dbus()

    def _terminar(_sig, _quadro):
        _log("encerrando...")
        try:
            WEBRTC.parar()
            GER.desligar()
        finally:
            sys.exit(0)

    signal.signal(signal.SIGTERM, _terminar)
    signal.signal(signal.SIGINT, _terminar)

    # Sobe escutando na rede local toda (o celular acessa pelo IP do PC).
    app.run(host="0.0.0.0", port=PORTA, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
