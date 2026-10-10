"""Emissor WebRTC LAN do serviço de tela do PC.

O módulo recebe um portal PipeWire já abstraído pelo serviço principal, codifica
H.264 + Opus e negocia diretamente com o Emily TV. Não abre porta nova e não
passa pelo gateway remoto.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GstWebRTC", "1.0")
from gi.repository import Gst, GstSdp, GstWebRTC  # noqa: E402

Gst.init([])


@dataclass(frozen=True)
class Perfil:
    nome: str
    largura: int
    altura: int
    fps: int
    bitrate: int


PERFIS = {
    "1080p60": Perfil("1080p60", 1920, 1080, 60, 12_000_000),
    "1080p30": Perfil("1080p30", 1920, 1080, 30, 8_000_000),
    "720p60": Perfil("720p60", 1280, 720, 60, 7_000_000),
    "720p30": Perfil("720p30", 1280, 720, 30, 4_000_000),
}


def perfil(nome: str | None) -> Perfil:
    return PERFIS.get((nome or "").lower(), PERFIS["1080p60"])


def _tem_elemento(nome: str) -> bool:
    return Gst.ElementFactory.find(nome) is not None


def encoder_h264(p: Perfil) -> tuple[str, str]:
    """Escolhe hardware quando disponível; OpenH264 é o fallback validado."""
    gop = max(30, p.fps * 2)
    if _tem_elemento("vah264lpenc"):
        return "vah264lpenc", (
            f"vah264lpenc bitrate={p.bitrate // 1000} key-int-max={gop} "
            "rate-control=cbr ! video/x-h264,profile=constrained-baseline"
        )
    if _tem_elemento("vah264enc"):
        return "vah264enc", (
            f"vah264enc bitrate={p.bitrate // 1000} key-int-max={gop} "
            "rate-control=cbr ! video/x-h264,profile=constrained-baseline"
        )
    if _tem_elemento("vaapih264enc"):
        return "vaapih264enc", (
            f"vaapih264enc bitrate={p.bitrate // 1000} keyframe-period={gop} "
            "rate-control=cbr ! video/x-h264,profile=constrained-baseline"
        )
    if _tem_elemento("nvh264enc"):
        return "nvh264enc", (
            f"nvh264enc bitrate={p.bitrate // 1000} gop-size={gop} preset=low-latency-hq "
            "rc-mode=cbr ! video/x-h264,profile=constrained-baseline"
        )
    if _tem_elemento("x264enc"):
        return "x264enc", (
            f"x264enc bitrate={p.bitrate // 1000} key-int-max={gop} speed-preset=ultrafast "
            "tune=zerolatency byte-stream=true ! video/x-h264,profile=constrained-baseline"
        )
    if _tem_elemento("openh264enc"):
        return "openh264enc", (
            f"openh264enc bitrate={p.bitrate} max-bitrate={p.bitrate} rate-control=bitrate "
            f"complexity=low usage-type=screen enable-frame-skip=true gop-size={gop} multi-thread=0 "
            "! video/x-h264,profile=constrained-baseline"
        )
    raise RuntimeError("nenhum encoder H.264 GStreamer disponível")


def descricao_pipeline(fd: int, node: int, p: Perfil, audio_device: str = "") -> tuple[str, str]:
    encoder_nome, encoder = encoder_h264(p)
    video = (
        f"pipewiresrc fd={int(fd)} path={int(node)} keepalive-time=1000 do-timestamp=true ! "
        "queue leaky=downstream max-size-buffers=2 ! videoconvert n-threads=4 ! "
        "videoscale n-threads=4 ! videorate drop-only=true ! "
        f"video/x-raw,format=I420,width={p.largura},height={p.altura},framerate={p.fps}/1 ! "
        f"{encoder} ! h264parse config-interval=-1 ! rtph264pay pt=96 config-interval=-1 "
        "aggregate-mode=zero-latency ! "
        "application/x-rtp,media=video,encoding-name=H264,payload=96,clock-rate=90000 ! webrtc. "
    )
    audio = ""
    if audio_device and _tem_elemento("pulsesrc") and _tem_elemento("opusenc"):
        escaped = audio_device.replace('\\', '\\\\').replace('"', '\\"')
        audio = (
            f'pulsesrc device="{escaped}" do-timestamp=true buffer-time=40000 latency-time=10000 ! '
            "queue leaky=downstream max-size-time=100000000 ! audioconvert ! audioresample ! "
            "audio/x-raw,rate=48000,channels=2 ! opusenc bitrate=128000 frame-size=10 "
            "inband-fec=true audio-type=restricted-lowdelay ! rtpopuspay pt=111 ! "
            "application/x-rtp,media=audio,encoding-name=OPUS,payload=111,clock-rate=48000 ! webrtc. "
        )
    return encoder_nome, "webrtcbin name=webrtc bundle-policy=max-bundle " + video + audio


class TvApi:
    def __init__(self, host: str, token: str, timeout: float = 12.0):
        self.base = f"http://{host}:8765"
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=raw,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(detail) from exc
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "resposta inválida da TV"))
        return result


class SessaoWebRtc:
    def __init__(self, portal_factory: Callable[[], object], tv_ip: str, tv_token: str,
                 preset: str, monitor: int, audio_device: str, log: Callable[[str], None]):
        self.portal_factory = portal_factory
        self.api = TvApi(tv_ip, tv_token)
        self.perfil = perfil(preset)
        self.monitor = max(1, int(monitor))
        self.audio_device = audio_device
        self.log = log
        self.portal = None
        self.pipeline = None
        self.webrtc = None
        self.session_id = ""
        self.encoder = ""
        self.estado = "novo"
        self.erro = ""
        self.iniciada_em = 0.0
        self._pronto = threading.Event()
        self._oferta_enviada = False
        self._trava = threading.RLock()

    def iniciar(self, timeout: float = 35.0) -> dict:
        try:
            with self._trava:
                if self.pipeline is not None:
                    return self.status()
                self.estado = "abrindo_portal"
                self.portal = self.portal_factory()
                self.portal.abrir()
                streams = sorted(self.portal.streams,
                                 key=lambda s: s.get("posicao", (9_999_999, 9_999_999)))
                if self.monitor > len(streams):
                    raise RuntimeError(
                        f"monitor {self.monitor} não existe; disponíveis: {len(streams)}")
                stream = streams[self.monitor - 1]
                self.encoder, desc = descricao_pipeline(
                    self.portal.fd, stream["node"], self.perfil, self.audio_device)
                criada = self.api.request("POST", "/v1/screen/sessions", {
                    "source": "Emily PC",
                    "preset": self.perfil.nome,
                    "audio": bool(self.audio_device),
                })
                self.session_id = criada["session_id"]
                self.pipeline = Gst.parse_launch(desc)
                self.webrtc = self.pipeline.get_by_name("webrtc")
                self.webrtc.connect("on-negotiation-needed", self._negociar)
                self.webrtc.connect("notify::ice-gathering-state", self._ice_mudou)
                bus = self.pipeline.get_bus()
                bus.add_signal_watch()
                bus.connect("message::error", self._erro_gst)
                self.estado = "negociando"
                self.pipeline.set_state(Gst.State.PLAYING)
                self.iniciada_em = time.time()
        except Exception:
            self.parar("falha_inicializacao")
            raise
        if not self._pronto.wait(timeout):
            self.parar("timeout_negociacao")
            raise RuntimeError("timeout negociando WebRTC com a TV")
        if self.erro:
            erro = self.erro
            self.parar("erro")
            raise RuntimeError(erro)
        return self.status()

    def _negociar(self, _elemento) -> None:
        promise = Gst.Promise.new_with_change_func(self._oferta_criada, None, None)
        self.webrtc.emit("create-offer", None, promise)

    def _oferta_criada(self, promise, _user_data, _notify) -> None:
        try:
            reply = promise.get_reply()
            offer = reply.get_value("offer")
            local = Gst.Promise.new()
            self.webrtc.emit("set-local-description", offer, local)
            local.interrupt()
            self.estado = "coletando_ice"
            self._enviar_oferta_se_pronta()
        except Exception as exc:  # noqa: BLE001
            self._falhar(f"criar oferta: {exc}")

    def _ice_mudou(self, _elemento, _param) -> None:
        self._enviar_oferta_se_pronta()

    def _enviar_oferta_se_pronta(self) -> None:
        with self._trava:
            if self._oferta_enviada or self.webrtc is None:
                return
            estado = self.webrtc.get_property("ice-gathering-state")
            if estado != GstWebRTC.WebRTCICEGatheringState.COMPLETE:
                return
            local = self.webrtc.get_property("local-description")
            if local is None:
                return
            self._oferta_enviada = True
        try:
            resposta = self.api.request("POST", f"/v1/screen/sessions/{self.session_id}/offer", {
                "type": "offer", "sdp": local.sdp.as_text(),
            })
            resultado, mensagem = GstSdp.SDPMessage.new()
            if resultado != GstSdp.SDPResult.OK:
                raise RuntimeError(f"não criou SDPMessage: {resultado}")
            parse = GstSdp.sdp_message_parse_buffer(resposta["sdp"].encode("utf-8"), mensagem)
            if parse != GstSdp.SDPResult.OK:
                raise RuntimeError(f"answer SDP inválido: {parse}")
            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, mensagem)
            promise = Gst.Promise.new()
            self.webrtc.emit("set-remote-description", answer, promise)
            promise.interrupt()
            self.estado = "conectando"
            threading.Thread(target=self._confirmar_conexao, name="tela-pc-webrtc-state", daemon=True).start()
        except Exception as exc:  # noqa: BLE001
            self._falhar(f"sinalização: {exc}")

    def _confirmar_conexao(self) -> None:
        limite = time.time() + 12.0
        while time.time() < limite and not self.erro and self.webrtc is not None:
            state = self.webrtc.get_property("connection-state")
            nome = getattr(state, "value_nick", str(state)).lower()
            self.estado = nome
            if nome == "connected":
                self._pronto.set()
                return
            if nome in {"failed", "closed"}:
                self._falhar(f"conexão WebRTC: {nome}")
                return
            time.sleep(0.2)
        self._falhar("conexão WebRTC não ficou pronta")

    def _erro_gst(self, _bus, message) -> None:
        erro, debug = message.parse_error()
        self._falhar(f"GStreamer: {erro.message}" + (f" ({debug[:240]})" if debug else ""))

    def _falhar(self, mensagem: str) -> None:
        self.erro = mensagem
        self.estado = "erro"
        self.log(mensagem)
        self._pronto.set()

    def status(self) -> dict:
        return {
            "ok": not bool(self.erro),
            "estado": self.estado,
            "erro": self.erro or None,
            "session_id": self.session_id or None,
            "preset": self.perfil.nome,
            "monitor": self.monitor,
            "encoder": self.encoder or None,
            "audio": bool(self.audio_device),
            "segundos": round(time.time() - self.iniciada_em, 1) if self.iniciada_em else 0.0,
        }

    def parar(self, motivo: str = "local_stop") -> None:
        with self._trava:
            session_id, self.session_id = self.session_id, ""
            pipeline, self.pipeline = self.pipeline, None
            portal, self.portal = self.portal, None
            self.webrtc = None
            self.estado = "parado"
        if pipeline is not None:
            try:
                pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        if portal is not None:
            try:
                portal.fechar()
            except Exception:
                pass
        if session_id:
            try:
                self.api.request("DELETE", f"/v1/screen/sessions/{session_id}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"encerrar sessão na TV: {exc}")
        self.log(f"sessão WebRTC encerrada ({motivo})")


class GerenciadorWebRtc:
    def __init__(self, portal_factory: Callable[[], object], audio_device: Callable[[], str],
                 log: Callable[[str], None]):
        self.portal_factory = portal_factory
        self.audio_device = audio_device
        self.log = log
        self.trava = threading.RLock()
        self.sessao: Optional[SessaoWebRtc] = None

    def iniciar(self, tv_ip: str, tv_token: str, preset: str = "1080p60",
                monitor: int = 1, audio: bool = True) -> dict:
        if not tv_ip or not tv_token:
            raise ValueError("tv_ip e tv_token são obrigatórios")
        with self.trava:
            if self.sessao is not None:
                self.sessao.parar("substituida")
            sessao = SessaoWebRtc(
                self.portal_factory, tv_ip, tv_token, preset, monitor,
                self.audio_device() if audio else "", self.log,
            )
            self.sessao = sessao
        try:
            return sessao.iniciar()
        except Exception:
            with self.trava:
                if self.sessao is sessao:
                    self.sessao = None
            raise

    def status(self) -> dict:
        with self.trava:
            return self.sessao.status() if self.sessao else {
                "ok": True, "estado": "parado", "session_id": None,
            }

    def parar(self) -> dict:
        with self.trava:
            sessao, self.sessao = self.sessao, None
        if sessao is not None:
            sessao.parar()
        return {"ok": True, "estado": "parado"}