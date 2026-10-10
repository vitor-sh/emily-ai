"""Sessões H.264/Opus para o Android, compartilhando um único portal do PC."""
from __future__ import annotations
import gi
gi.require_version("GstVideo", "1.0")
from gi.repository import GstVideo
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import re
import threading
import time
from urllib.parse import quote
from tela_monitors import crop_pipeline
from tela_webrtc import Gst, GstSdp, GstWebRTC, Perfil, descricao_pipeline


def ice_config(config=None):
    if config is None:
        path = Path.home()/'.config/tela-pc-service/turn.json'
        config = json.loads(path.read_text()) if path.exists() else {}
    if not config.get('secret'):
        return {'ice_servers': []}
    username = f"{int(time.time()) + 3600}:{secrets.token_hex(8)}"
    password = base64.b64encode(hmac.new(config['secret'].encode(), username.encode(), hashlib.sha1).digest()).decode()
    host = config['host']
    return {'ice_servers': [{'urls': [f'stun:{host}:3478']},
                            {'urls': [f'turn:{host}:3478?transport=udp', f'turn:{host}:3478?transport=tcp'],
                             'username': username, 'credential': password}]}


class MobileSession:
    def __init__(self, manager, offer, monitor, quality, audio):
        self.manager = manager
        self.id = secrets.token_hex(16)
        self.last_seen = time.monotonic()
        self.created = self.last_seen
        self.pipeline = None
        self.webrtc = None
        self.error = ''
        self.closed = False
        self.lock = threading.RLock()
        self.ice_ready = threading.Event()
        self.bus = None
        self.offer = offer
        self.monitor = monitor
        self.quality = quality
        self.audio = audio

    def start(self):
        # Serializa aquisição do portal; nenhum cliente fecha o portal de outro.
        ger = self.manager.capture
        with ger.trava:
            if not ger.rodando:
                ger._ligar(0)
            streams = ger._streams_ordenados()
            if not 1 <= self.monitor <= len(streams):
                raise ValueError('Monitor não autorizado ou inexistente')
            ger.batimento()
            stream = streams[self.monitor-1]
            ow, oh = stream.get('tamanho', (1920, 1080))
            max_width, max_height = (1920,1080) if self.quality == 'alta' else (1280,720)
            scale = max(1, ow/max_width, oh/max_height)
            width = max(2, int(ow/scale)//2*2)
            height = max(2, int(oh/scale)//2*2)
            fps = 60 if self.quality == 'alta' else 30
            bitrate = 8_000_000 if self.quality == 'alta' else 4_000_000
            preset = Perfil('mobile', width, height, fps, bitrate)
            self.encoder, desc = descricao_pipeline(ger.portal.fd, stream['node'], preset,
                                                    self.manager.audio_device() if self.audio else '')
            # Camera + slices paralelos evita o custo excessivo do modo screen
            # em vídeo/movimento; a taxa e o perfil continuam próprios para tela.
            desc = desc.replace('usage-type=screen','usage-type=camera',1).replace('multi-thread=0','multi-thread=4 slice-mode=auto',1)
            desc = desc.replace('videorate drop-only=true','videorate name=mobile_rate drop-only=true',1)
            desc = desc.replace('! queue leaky=downstream', '! identity name=mobile_raw ! '+crop_pipeline(stream)+'queue leaky=downstream',1)
            desc = desc.replace('! '+self.encoder+' ', '! identity name=mobile_in ! '+self.encoder+' name=mobile_encoder ',1)
            desc = desc.replace('! h264parse', '! identity name=mobile_out ! h264parse',1)
            h264 = re.search(r'^a=rtpmap:(\d+) H264/90000', self.offer, re.M | re.I)
            opus = re.search(r'^a=rtpmap:(\d+) opus/48000', self.offer, re.M | re.I)
            if not h264: raise ValueError('H.264 não oferecido pelo celular')
            payload = int(h264.group(1))
            if not 96 <= payload <= 127: raise ValueError('Payload H.264 inválido')
            desc = desc.replace('pt=96', f'pt={payload}').replace('payload=96', f'payload={payload}')
            if self.audio and opus:
                audio_payload = int(opus.group(1))
                if not 96 <= audio_payload <= 127: raise ValueError('Payload Opus inválido')
                desc = desc.replace('pt=111', f'pt={audio_payload}').replace('payload=111', f'payload={audio_payload}')
            # 4.2 é o teto negociado, não o nível mínimo do SPS. Em 720p o
            # encoder produz um nível menor; GStreamer exige caps idênticos.
            desc = desc.replace('clock-rate=90000 ! webrtc.',
                'clock-rate=90000 ! capssetter caps="application/x-rtp,level-asymmetry-allowed=(string)1,profile-level-id=(string)42c02a" ! webrtc.',1)
            self.pipeline = Gst.parse_launch(desc)
            # O relógio deve avançar mesmo quando a tela não muda.
            self.pipeline.use_clock(Gst.SystemClock.obtain())
        self.frames_raw = 0
        self.frames_in = 0
        self.frames_out = 0
        for name,field in [('mobile_raw','frames_raw'),('mobile_in','frames_in'),('mobile_out','frames_out')]:
            element = self.pipeline.get_by_name(name)
            if element:
                def count(_pad,_info,field=field):
                    setattr(self,field,getattr(self,field)+1)
                    return Gst.PadProbeReturn.OK
                element.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER,count)
        self.webrtc = self.pipeline.get_by_name('webrtc')
        cfg = ice_config()
        for server in cfg['ice_servers']:
            for url in server['urls']:
                if url.startswith('stun:'):
                    self.webrtc.set_property('stun-server', url.replace('stun:', 'stun://', 1))
                elif url.startswith('turn:'):
                    auth = quote(server['username'], safe='')+':'+quote(server['credential'], safe='')
                    uri = url.replace('turn:', 'turn://'+auth+'@', 1)
                    # webrtcbin accepts transport=tcp on add-turn-server.
                    self.webrtc.emit('add-turn-server', uri)
        self.webrtc.connect('notify::ice-gathering-state', self._ice_changed)
        self.webrtc.connect('notify::connection-state', lambda *_: self.keyframe())
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect('message::error', self._on_error)
        self.pipeline.set_state(Gst.State.PLAYING)
        _, msg = GstSdp.SDPMessage.new()
        if GstSdp.sdp_message_parse_buffer(self.offer.encode(), msg) != GstSdp.SDPResult.OK:
            raise ValueError('Oferta SDP inválida')
        remote = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.OFFER, msg)
        promise = Gst.Promise.new()
        self.webrtc.emit('set-remote-description', remote, promise)
        if promise.wait() != Gst.PromiseResult.REPLIED:
            raise RuntimeError('Falha aplicando oferta')
        reply = promise.get_reply()
        if reply and reply.has_field('error'):
            raise RuntimeError('Oferta incompatível com o PC: '+str(reply.get_value('error')))
        self.pipeline.set_state(Gst.State.PLAYING)
        # Espera os caps dos dois fluxos. Responder antes de pulsesrc negociar
        # podia marcar áudio como inativo mesmo com vídeo funcionando.
        until = time.monotonic()+5
        pads = [self.webrtc.get_static_pad('sink_0')]
        if self.audio and self.manager.audio_device():
            pads.append(self.webrtc.get_static_pad('sink_1'))
        while time.monotonic()<until and not self.error:
            if all(pad is not None and pad.get_current_caps() is not None for pad in pads): break
            time.sleep(.02)
        if self.error: raise RuntimeError(self.error)
        promise = Gst.Promise.new()
        self.webrtc.emit('create-answer', None, promise)
        if promise.wait() != Gst.PromiseResult.REPLIED:
            raise RuntimeError('Falha criando resposta')
        answer_reply = promise.get_reply()
        answer = answer_reply.get_value('answer')
        if answer is None:
            raise RuntimeError('Não foi possível negociar H.264')
        local = Gst.Promise.new()
        self.webrtc.emit('set-local-description', answer, local)
        local.interrupt()
        self._ice_changed(None, None)
        if not self.ice_ready.wait(20):
            raise RuntimeError('Tempo esgotado preparando a conexão de vídeo')
        if self.error:
            raise RuntimeError(self.error)
        local_description = self.webrtc.get_property('local-description')
        if re.search(r'^m=video 0 ',local_description.sdp.as_text(),re.M):
            raise RuntimeError('O celular e o PC não negociaram um formato de vídeo compatível')

        return {'ok': True, 'session_id': self.id, 'type': 'answer',
                'sdp': local_description.sdp.as_text(),
                'width': width, 'height': height, 'fps': fps, 'encoder': self.encoder}

    def keyframe(self):
        # Em telas paradas há poucos quadros. GOP contado em quadros não basta:
        # envia uma imagem completa após conectar e periodicamente para recuperação.
        with self.lock:
            if self.closed or not self.pipeline or not self.webrtc: return
            if self.webrtc.get_property('connection-state') != GstWebRTC.WebRTCPeerConnectionState.CONNECTED: return
            encoder = self.pipeline.get_by_name('mobile_encoder')
            if encoder:
                encoder.get_static_pad('src').send_event(
                    GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0))

    def _ice_changed(self, *_):
        if self.webrtc and self.webrtc.get_property('ice-gathering-state') == GstWebRTC.WebRTCICEGatheringState.COMPLETE:
            self.ice_ready.set()

    def _on_error(self, _bus, message):
        error, _debug = message.parse_error()
        self.error = error.message
        self.ice_ready.set()

    def heartbeat(self):
        with self.lock:
            self.last_seen = time.monotonic()
            state = self.webrtc.get_property('connection-state').value_nick if self.webrtc else 'closed'
            return {'ok': not bool(self.error), 'state': state, 'error': self.error or None,
                    'raw_frames':self.frames_raw,'source_frames':self.frames_in,'encoded_frames':self.frames_out,
                    'rate_in':self.pipeline.get_by_name('mobile_rate').get_property('in') if self.pipeline else 0,
                    'rate_drop':self.pipeline.get_by_name('mobile_rate').get_property('drop') if self.pipeline else 0}

    def close(self):
        with self.lock:
            if self.closed: return
            self.closed = True
            pipeline, self.pipeline = self.pipeline, None
            self.webrtc = None
        if pipeline:
            pipeline.set_state(Gst.State.NULL)
        if self.bus:
            self.bus.remove_signal_watch()
            self.bus = None
        self.ice_ready.set()


class MobileRtcManager:
    def __init__(self, capture, audio_device):
        self.capture = capture
        self.audio_device = audio_device
        self.sessions = {}
        self.lock = threading.RLock()
        threading.Thread(target=self._watch, daemon=True, name='mobile-rtc-watch').start()

    def start(self, body):
        offer = body.get('sdp', '')
        if not isinstance(offer, str) or not 10 < len(offer) < 128*1024:
            raise ValueError('Oferta SDP inválida')
        monitor = int(body.get('monitor', 1))
        quality = body.get('quality', 'alta')
        if quality not in ('alta', 'equilibrada'): raise ValueError('Qualidade inválida')
        with self.lock:
            if len(self.sessions) >= 4: raise ValueError('Limite de transmissões atingido')
            session = MobileSession(self, offer, monitor, quality, bool(body.get('audio', True)))
            self.sessions[session.id] = session
        try:
            return session.start()
        except Exception:
            self.stop(session.id)
            raise

    def stop(self, session_id):
        with self.lock:
            session = self.sessions.pop(session_id, None)
        if session: session.close()
        return {'ok': True}

    def heartbeat(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
        return session.heartbeat() if session else {'ok': False, 'state': 'closed'}

    def _watch(self):
        while True:
            time.sleep(2)
            with self.lock: sessions = list(self.sessions.values())
            for session in sessions:
                if time.monotonic() - session.last_seen > 40 or session.error:
                    self.stop(session.id)
                else:
                    self.capture.batimento()
                    session.keyframe()

