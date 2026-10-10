"""
Pré-processamento compartilhado de todo áudio enviado ao Whisper.

Contrato público
----------------
``preprocess_audio`` recebe PCM cru (ou WAV) e devolve WAV PCM S16LE mono/16 kHz,
pronto para ``Groq.audio.transcriptions.create``. ``preprocess_audio_detailed``
devolve o mesmo áudio junto das métricas e é o caminho usado pelos diagnósticos.

O desenho evita uma armadilha de latência: abrir um processo FFmpeg por filtro
custou ~0,5–0,7 s nesta máquina. Padronização, RNNoise e loudnorm rodam numa só
passagem. ``abench`` só é ligado no diagnóstico opt-in, porque ele escreve uma
linha por frame e não deve penalizar fala real. O Silero roda depois, diretamente
por ONNX Runtime, sem PyTorch/TorchAudio.

Falha degradável é requisito. RNNoise, loudnorm ou Silero indisponíveis nunca
deixam a Emily surda: a etapa falha, é registrada, e o último áudio válido segue.
Somente um VAD que RODOU com sucesso e não encontrou fala devolve áudio vazio.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


TARGET_RATE = 16000
TARGET_CHANNELS = 1
TARGET_WIDTH = 2


def _asset_path(nome: str) -> Path:
    """Funciona no fonte e no PyInstaller onedir (_internal/assets/audio)."""
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return raiz / "assets" / "audio" / nome


SILERO_MODEL = _asset_path("silero_vad.onnx")
RNNOISE_MODEL = _asset_path("rnnoise_bd.rnnn")


def _bool_env(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() not in ("0", "false", "nao", "não", "off")


def _preferencia_bool(chave: str, env: str, padrao: bool) -> bool:
    if os.getenv(env) is not None:
        return _bool_env(env, padrao)
    try:
        import preferencias
        return bool(preferencias.obter(chave, padrao))
    except Exception:
        return padrao


def _float_env(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


def _int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


@dataclass(frozen=True)
class AudioPreprocessingConfig:
    denoise: bool = True
    normalize: bool = True
    vad: bool = True
    loudness_i: float = -20.0
    loudness_lra: float = 7.0
    true_peak: float = -2.0
    vad_threshold: float = 0.50
    vad_min_speech_ms: int = 180
    vad_min_silence_ms: int = 300
    vad_speech_pad_ms: int = 120

    @classmethod
    def current(cls) -> "AudioPreprocessingConfig":
        """Flags mudam em runtime pela interface, sem reiniciar a Emily."""
        return cls(
            denoise=_preferencia_bool(
                "audio_preprocess_denoise", "EMILY_AUDIO_DENOISE", True),
            normalize=_preferencia_bool(
                "audio_preprocess_normalize", "EMILY_AUDIO_NORMALIZE", True),
            vad=_preferencia_bool(
                "audio_preprocess_vad", "EMILY_AUDIO_VAD", True),
            loudness_i=_float_env("EMILY_AUDIO_LOUDNESS_I", -20.0),
            loudness_lra=_float_env("EMILY_AUDIO_LOUDNESS_LRA", 7.0),
            true_peak=_float_env("EMILY_AUDIO_TRUE_PEAK", -2.0),
            vad_threshold=_float_env("EMILY_AUDIO_VAD_THRESHOLD", 0.50),
            vad_min_speech_ms=_int_env("EMILY_AUDIO_VAD_MIN_SPEECH_MS", 180),
            vad_min_silence_ms=_int_env("EMILY_AUDIO_VAD_MIN_SILENCE_MS", 300),
            vad_speech_pad_ms=_int_env("EMILY_AUDIO_VAD_PAD_MS", 120),
        )


@dataclass
class PreprocessResult:
    wav: bytes
    source: str
    input_duration_s: float
    output_duration_s: float
    timings_ms: Dict[str, float] = field(default_factory=dict)
    enabled: Dict[str, bool] = field(default_factory=dict)
    applied: List[str] = field(default_factory=list)
    skipped: Dict[str, str] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    speech_segments: List[Tuple[int, int]] = field(default_factory=list)
    discarded_reason: str = ""


def _wav_info(dados: bytes) -> Tuple[int, int, int, int]:
    with wave.open(io.BytesIO(dados), "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()


def _duration_wav(dados: bytes) -> float:
    if not dados:
        return 0.0
    try:
        taxa, _canais, _largura, quadros = _wav_info(dados)
        return quadros / taxa if taxa else 0.0
    except Exception:
        return 0.0


def _raw_duration(dados: bytes, taxa: int, canais: int, largura: int) -> float:
    divisor = max(1, int(taxa) * int(canais) * int(largura))
    return len(dados or b"") / divisor


def _is_wav(dados: bytes) -> bool:
    return len(dados or b"") >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WAVE"


def _pcm_to_wav(pcm: bytes, taxa: int, canais: int, largura: int) -> bytes:
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(canais)
        w.setsampwidth(largura)
        w.setframerate(taxa)
        w.writeframes(pcm)
    return saida.getvalue()


def _canonicalize_wav(dados: bytes) -> bytes:
    """Regrava o cabeçalho WAV; FFmpeg em pipe usa tamanho sentinela 0x7fffffff."""
    with wave.open(io.BytesIO(dados), "rb") as w:
        taxa = w.getframerate()
        canais = w.getnchannels()
        largura = w.getsampwidth()
        pcm = w.readframes(w.getnframes())
    return _pcm_to_wav(pcm, taxa, canais, largura)


def _decode_pcm(dados: bytes, largura: int) -> np.ndarray:
    """Converte PCM inteiro comum para int16; cobre os formatos aceitos por WAV."""
    if largura == 1:
        return ((np.frombuffer(dados, dtype=np.uint8).astype(np.int16) - 128) << 8)
    if largura == 2:
        tamanho = len(dados) - (len(dados) % 2)
        return np.frombuffer(dados[:tamanho], dtype="<i2").copy()
    if largura == 3:
        tamanho = len(dados) - (len(dados) % 3)
        b = np.frombuffer(dados[:tamanho], dtype=np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        v = np.where(v & 0x800000, v - 0x1000000, v)
        return (v >> 8).astype(np.int16)
    if largura == 4:
        tamanho = len(dados) - (len(dados) % 4)
        return (np.frombuffer(dados[:tamanho], dtype="<i4") >> 16).astype(np.int16)
    raise ValueError(f"largura PCM não suportada: {largura}")


def _standardize_python(
    raw_audio: bytes, sample_rate: int, channels: int, sample_width: int,
) -> bytes:
    """Fallback sem FFmpeg. Mantém a transcrição disponível em instalação mínima."""
    if _is_wav(raw_audio):
        with wave.open(io.BytesIO(raw_audio), "rb") as w:
            sample_rate = w.getframerate()
            channels = w.getnchannels()
            sample_width = w.getsampwidth()
            raw_audio = w.readframes(w.getnframes())
    amostras = _decode_pcm(raw_audio, sample_width)
    if channels > 1:
        resto = amostras.size % channels
        if resto:
            amostras = amostras[:-resto]
        if amostras.size:
            amostras = amostras.reshape(-1, channels).astype(np.int32).mean(
                axis=1).astype(np.int16)
    if sample_rate != TARGET_RATE and amostras.size:
        quantidade = max(1, round(amostras.size * TARGET_RATE / sample_rate))
        origem = np.arange(amostras.size, dtype=np.float64)
        destino = np.linspace(0, amostras.size - 1, quantidade)
        amostras = np.interp(destino, origem, amostras).astype(np.int16)
    return _pcm_to_wav(amostras.astype("<i2", copy=False).tobytes(),
                       TARGET_RATE, TARGET_CHANNELS, TARGET_WIDTH)


_RE_ABENCH = re.compile(
    r"Parsed_abench_(\d+).*?\bt:([0-9.]+)\s+avg:", re.IGNORECASE)


def _parse_abench(stderr: str, etapas: Sequence[str]) -> Dict[str, float]:
    por_id: Dict[str, float] = {}
    ordem: List[str] = []
    for id_filtro, valor in _RE_ABENCH.findall(stderr or ""):
        if id_filtro not in por_id:
            por_id[id_filtro] = 0.0
            ordem.append(id_filtro)
        por_id[id_filtro] += float(valor) * 1000.0
    return {etapa: por_id[id_filtro]
            for etapa, id_filtro in zip(etapas, ordem)}


def _ffmpeg_path() -> Optional[str]:
    configurado = os.getenv("EMILY_FFMPEG", "").strip()
    return configurado or shutil.which("ffmpeg")


def _run_ffmpeg(
    raw_audio: bytes,
    sample_rate: int,
    channels: int,
    sample_width: int,
    config: AudioPreprocessingConfig,
) -> Tuple[bytes, Dict[str, float], List[str], Dict[str, str], Dict[str, str]]:
    """Padroniza e filtra em uma única inicialização do FFmpeg."""
    # PTT já nasce exatamente no formato do Whisper. Quando o usuário desliga as
    # três melhorias para comparação A/B, não faz sentido pagar um processo só
    # para copiar os mesmos bytes.
    if (not config.denoise and not config.normalize
            and not _is_wav(raw_audio) and sample_rate == TARGET_RATE
            and channels == TARGET_CHANNELS and sample_width == TARGET_WIDTH):
        inicio = time.perf_counter()
        wav = _pcm_to_wav(raw_audio, TARGET_RATE, TARGET_CHANNELS, TARGET_WIDTH)
        return wav, {"standardize": (time.perf_counter() - inicio) * 1000}, \
            ["standardize"], {"denoise": "desligado", "normalize": "desligado"}, {}

    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        inicio = time.perf_counter()
        wav = _standardize_python(raw_audio, sample_rate, channels, sample_width)
        puladas = {}
        if config.denoise:
            puladas["denoise"] = "ffmpeg indisponível"
        if config.normalize:
            puladas["normalize"] = "ffmpeg indisponível"
        return wav, {"standardize": (time.perf_counter() - inicio) * 1000}, \
            ["standardize"], puladas, {}

    medir_filtros = _bool_env("EMILY_AUDIO_DETAILED_TIMINGS", False)
    cmd = [ffmpeg, "-hide_banner", "-loglevel",
           "info" if medir_filtros else "error"]
    if _is_wav(raw_audio):
        cmd += ["-i", "pipe:0"]
    else:
        formatos = {1: "u8", 2: "s16le", 3: "s24le", 4: "s32le"}
        formato = formatos.get(sample_width)
        if not formato:
            raise ValueError(f"largura PCM não suportada: {sample_width}")
        cmd += ["-f", formato, "-ar", str(sample_rate), "-ac", str(channels),
                "-i", "pipe:0"]

    filtros: List[str] = []
    etapas_medidas: List[str] = []
    applied: List[str] = []
    skipped: Dict[str, str] = {}

    def adicionar_filtro(nome: str, filtro: str) -> None:
        if medir_filtros:
            filtros.extend(("abench=start", filtro, "abench=stop"))
            etapas_medidas.append(nome)
        else:
            filtros.append(filtro)

    # O teste A/B com áudio real da call favoreceu esta ordem: ao preservar 48 kHz
    # até o RNNoise uma frase mudou e a confiança caiu; padronizando antes, o texto
    # ficou idêntico ao original e a confiança melhorou. A saída já nasce no
    # formato nativo que o Whisper usaria internamente.
    adicionar_filtro(
        "standardize", "aformat=sample_rates=16000:channel_layouts=mono")
    applied.append("standardize")

    if config.denoise:
        if RNNOISE_MODEL.is_file():
            modelo = str(RNNOISE_MODEL).replace("\\", "/").replace(":", "\\:")
            adicionar_filtro("denoise", f"arnndn=m='{modelo}'")
            applied.append("denoise")
        else:
            skipped["denoise"] = f"modelo ausente: {RNNOISE_MODEL}"
    else:
        skipped["denoise"] = "desligado"

    if config.normalize:
        adicionar_filtro(
            "normalize",
            (f"loudnorm=I={config.loudness_i}:LRA={config.loudness_lra}:"
             f"TP={config.true_peak}:linear=true"),
        )
        applied.append("normalize")
    else:
        skipped["normalize"] = "desligado"

    cmd += ["-af", ",".join(filtros), "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"]
    duracao = (_duration_wav(raw_audio) if _is_wav(raw_audio)
               else _raw_duration(raw_audio, sample_rate, channels, sample_width))
    timeout = max(10.0, min(90.0, duracao * 3.0 + 8.0))
    inicio = time.perf_counter()
    try:
        proc = subprocess.run(cmd, input=raw_audio, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout,
                              check=False)
    except Exception as exc:
        wav = _standardize_python(raw_audio, sample_rate, channels, sample_width)
        return wav, {"ffmpeg": (time.perf_counter() - inicio) * 1000}, \
            ["standardize"], skipped, {"ffmpeg": f"{type(exc).__name__}: {exc}"}

    total_ms = (time.perf_counter() - inicio) * 1000
    stderr = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0 or not proc.stdout:
        wav = _standardize_python(raw_audio, sample_rate, channels, sample_width)
        detalhe = " ".join(stderr.strip().split())[-600:]
        return wav, {"ffmpeg": total_ms}, ["standardize"], skipped, {
            "ffmpeg": detalhe or f"código {proc.returncode}"}

    tempos = _parse_abench(stderr, etapas_medidas) if medir_filtros else {}
    tempos["ffmpeg"] = total_ms
    filtros_ativos = [n for n in ("denoise", "normalize") if n in applied]
    if not medir_filtros:
        # Sem abench, o dado honesto é o custo da cadeia. Quando há um único
        # filtro opcional ativo, ele também representa exatamente aquela etapa.
        tempos["filter_chain"] = total_ms
        if len(filtros_ativos) == 1:
            tempos[filtros_ativos[0]] = total_ms
    try:
        wav = _canonicalize_wav(proc.stdout)
    except Exception as exc:
        wav = _standardize_python(raw_audio, sample_rate, channels, sample_width)
        return wav, {"ffmpeg": total_ms}, ["standardize"], skipped, {
            "ffmpeg_saida": f"{type(exc).__name__}: {exc}"}
    return wav, tempos, applied, skipped, {}


_vad_session = None
_vad_session_lock = threading.Lock()
_warmup_started = False
_warmup_lock = threading.Lock()


def _silero_session():
    global _vad_session
    with _vad_session_lock:
        if _vad_session is not None:
            return _vad_session
        if not SILERO_MODEL.is_file():
            raise FileNotFoundError(f"modelo Silero ausente: {SILERO_MODEL}")
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        _vad_session = ort.InferenceSession(
            str(SILERO_MODEL), sess_options=opts,
            providers=["CPUExecutionProvider"])
        return _vad_session


def _warmup() -> None:
    """Carrega ONNX e aquece caches do FFmpeg fora da primeira fala real."""
    try:
        config = AudioPreprocessingConfig.current()
        if config.vad and SILERO_MODEL.is_file():
            _silero_probabilities(np.zeros(512, dtype=np.float32))
        if (config.denoise or config.normalize) and _ffmpeg_path():
            # 100 ms bastam para carregar executável, filtro e modelo nas páginas
            # do SO. O resultado é descartado; não há rede nem microfone aqui.
            _run_ffmpeg(
                b"\0" * (TARGET_RATE * 2 // 10), TARGET_RATE, 1, 2,
                AudioPreprocessingConfig(
                    denoise=config.denoise, normalize=config.normalize, vad=False,
                    loudness_i=config.loudness_i,
                    loudness_lra=config.loudness_lra,
                    true_peak=config.true_peak,
                ),
            )
        print("[AUDIO-PRE] aquecimento concluído")
    except Exception as exc:
        # Warmup é otimização, nunca requisito para transcrever.
        print(f"[AUDIO-PRE] aquecimento ignorado: {type(exc).__name__}: {exc}")


def warmup_async() -> None:
    """Dispara o aquecimento uma vez, sem atrasar a inicialização da Emily."""
    global _warmup_started
    with _warmup_lock:
        if _warmup_started:
            return
        _warmup_started = True
    threading.Thread(target=_warmup, name="audio-pre-warmup", daemon=True).start()


def _silero_probabilities(audio: np.ndarray) -> List[float]:
    """Port mínimo do OnnxWrapper oficial, sem a dependência em torch."""
    sessao = _silero_session()
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros((1, 64), dtype=np.float32)
    probs: List[float] = []
    janela = 512
    if audio.size % janela:
        audio = np.pad(audio, (0, janela - audio.size % janela))
    for inicio in range(0, audio.size, janela):
        chunk = audio[inicio:inicio + janela].reshape(1, -1)
        entrada = np.concatenate((context, chunk), axis=1).astype(np.float32,
                                                                  copy=False)
        saida, state = sessao.run(None, {
            "input": entrada,
            "state": state,
            "sr": np.array(TARGET_RATE, dtype=np.int64),
        })
        probs.append(float(np.asarray(saida).reshape(-1)[0]))
        context = entrada[:, -64:]
    return probs


def _speech_segments(
    probs: Sequence[float], total_samples: int,
    config: AudioPreprocessingConfig,
) -> List[Tuple[int, int]]:
    janela = 512
    minimo = round(TARGET_RATE * config.vad_min_speech_ms / 1000)
    silencio = round(TARGET_RATE * config.vad_min_silence_ms / 1000)
    pad = round(TARGET_RATE * config.vad_speech_pad_ms / 1000)
    negativo = max(0.01, config.vad_threshold - 0.15)
    segmentos: List[Tuple[int, int]] = []
    ativo = False
    inicio_fala = 0
    inicio_silencio: Optional[int] = None

    for indice, prob in enumerate(probs):
        posicao = indice * janela
        if prob >= config.vad_threshold:
            if not ativo:
                ativo = True
                inicio_fala = posicao
            inicio_silencio = None
            continue
        if ativo and prob < negativo:
            if inicio_silencio is None:
                inicio_silencio = posicao
            if posicao - inicio_silencio >= silencio:
                fim = min(total_samples, inicio_silencio + janela)
                if fim - inicio_fala >= minimo:
                    segmentos.append((inicio_fala, fim))
                ativo = False
                inicio_silencio = None

    if ativo:
        fim = total_samples
        if fim - inicio_fala >= minimo:
            segmentos.append((inicio_fala, fim))

    # Padding e união seguem a intenção do collect_chunks oficial, preservando
    # começo/fim de fonema sem duplicar áreas quando dois segmentos se encostam.
    expandidos: List[Tuple[int, int]] = []
    for inicio, fim in segmentos:
        inicio = max(0, inicio - pad)
        fim = min(total_samples, fim + pad)
        if expandidos and inicio <= expandidos[-1][1]:
            expandidos[-1] = (expandidos[-1][0], max(expandidos[-1][1], fim))
        else:
            expandidos.append((inicio, fim))
    return expandidos


def _apply_vad(wav_bytes: bytes, config: AudioPreprocessingConfig):
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Silero recebeu áudio fora de mono/16k/S16")
        pcm = w.readframes(w.getnframes())
    amostras_i16 = np.frombuffer(pcm, dtype="<i2")
    if amostras_i16.size == 0:
        return b"", []
    audio = amostras_i16.astype(np.float32) / 32768.0
    segmentos = _speech_segments(_silero_probabilities(audio), audio.size, config)
    if not segmentos:
        return b"", []
    # 80 ms entre trechos impede a última palavra de um segmento de colar na
    # primeira do seguinte depois que um silêncio longo é removido.
    separador = np.zeros(round(TARGET_RATE * 0.08), dtype=np.int16)
    partes: List[np.ndarray] = []
    for indice, (inicio, fim) in enumerate(segmentos):
        if indice:
            partes.append(separador)
        partes.append(amostras_i16[inicio:fim])
    saida = np.concatenate(partes) if partes else np.empty(0, dtype=np.int16)
    return _pcm_to_wav(saida.astype("<i2", copy=False).tobytes(), 16000, 1, 2), segmentos


def _fmt_ms(valor: Optional[float]) -> str:
    return "-" if valor is None else f"{valor:.1f}ms"


def _log_result(result: PreprocessResult) -> None:
    t = result.timings_ms
    estado = "descartado=" + result.discarded_reason if result.discarded_reason else "ok"
    extras = []
    if result.skipped:
        extras.append("skip=" + ",".join(sorted(result.skipped)))
    if result.errors:
        extras.append("erros=" + ",".join(sorted(result.errors)))
    print(
        f"[AUDIO-PRE] fonte={result.source} {estado} "
        f"audio={result.input_duration_s:.2f}s->{result.output_duration_s:.2f}s "
        f"padronizar={_fmt_ms(t.get('standardize'))} "
        f"rnnoise={_fmt_ms(t.get('denoise'))} "
        f"loudnorm={_fmt_ms(t.get('normalize'))} "
        f"filtros={_fmt_ms(t.get('filter_chain'))} "
        f"ffmpeg={_fmt_ms(t.get('ffmpeg'))} vad={_fmt_ms(t.get('vad'))} "
        f"total={_fmt_ms(t.get('total'))} {' '.join(extras)}".rstrip()
    )


def preprocess_audio_detailed(
    raw_audio: bytes,
    *,
    sample_rate: int = TARGET_RATE,
    channels: int = 1,
    sample_width: int = 2,
    source: str = "audio",
    config: Optional[AudioPreprocessingConfig] = None,
) -> PreprocessResult:
    config = config or AudioPreprocessingConfig.current()
    inicio_total = time.perf_counter()
    entrada = bytes(raw_audio or b"")
    duracao_entrada = (_duration_wav(entrada) if _is_wav(entrada)
                       else _raw_duration(entrada, sample_rate, channels, sample_width))
    result = PreprocessResult(
        wav=b"", source=source, input_duration_s=duracao_entrada,
        output_duration_s=0.0,
        enabled={"denoise": config.denoise, "normalize": config.normalize,
                 "vad": config.vad},
    )
    if not entrada:
        result.discarded_reason = "audio_vazio"
        result.timings_ms["total"] = (time.perf_counter() - inicio_total) * 1000
        _log_result(result)
        return result

    # Na call, o loudnorm antes do VAD amplificava ruídos quase silenciosos até
    # parecerem fala. Detectamos voz no áudio já limpo, mas ainda sem ganho;
    # somente o trecho aceito recebe loudnorm antes de ir ao Whisper.
    normalizar_depois = (source == "discord_call" and config.vad
                        and config.normalize)
    config_primeira_passagem = (replace(config, normalize=False)
                                if normalizar_depois else config)
    try:
        wav, tempos, aplicadas, puladas, erros = _run_ffmpeg(
            entrada, sample_rate, channels, sample_width,
            config_primeira_passagem)
        result.wav = wav
        result.timings_ms.update(tempos)
        result.applied.extend(aplicadas)
        result.skipped.update(puladas)
        result.errors.update(erros)
    except Exception as exc:
        inicio_fallback = time.perf_counter()
        try:
            result.wav = _standardize_python(
                entrada, sample_rate, channels, sample_width)
            result.applied.append("standardize")
            result.timings_ms["standardize"] = (
                time.perf_counter() - inicio_fallback) * 1000
        except Exception as fallback_exc:
            result.errors["standardize"] = (
                f"{type(exc).__name__}: {exc}; fallback: "
                f"{type(fallback_exc).__name__}: {fallback_exc}")

    if result.wav and config.vad:
        inicio_vad = time.perf_counter()
        try:
            result.wav, result.speech_segments = _apply_vad(result.wav, config)
            result.timings_ms["vad"] = (time.perf_counter() - inicio_vad) * 1000
            result.applied.append("vad")
            if not result.wav:
                result.discarded_reason = "sem_fala_silero"
        except Exception as exc:
            result.timings_ms["vad"] = (time.perf_counter() - inicio_vad) * 1000
            result.errors["vad"] = f"{type(exc).__name__}: {exc}"
            result.skipped["vad"] = "falhou; áudio anterior preservado"
    elif not config.vad:
        result.skipped["vad"] = "desligado"

    if normalizar_depois and not result.wav:
        result.skipped["normalize"] = "sem fala para normalizar"
    if result.wav and normalizar_depois:
        try:
            normalizado, tempos, aplicadas, _puladas, erros = _run_ffmpeg(
                result.wav, TARGET_RATE, TARGET_CHANNELS, TARGET_WIDTH,
                replace(config, denoise=False, vad=False))
            if "normalize" in aplicadas and not erros:
                result.wav = normalizado
                result.applied.append("normalize")
                result.skipped.pop("normalize", None)
                result.timings_ms["normalize"] = tempos.get(
                    "normalize", tempos.get("ffmpeg", 0.0))
                result.timings_ms["ffmpeg"] = (
                    result.timings_ms.get("ffmpeg", 0.0) +
                    tempos.get("ffmpeg", 0.0))
            else:
                result.skipped["normalize"] = "falhou; áudio sem ganho preservado"
                result.errors.update(erros)
        except Exception as exc:
            result.skipped["normalize"] = "falhou; áudio sem ganho preservado"
            result.errors["normalize"] = f"{type(exc).__name__}: {exc}"

    result.output_duration_s = _duration_wav(result.wav)
    result.timings_ms["total"] = (time.perf_counter() - inicio_total) * 1000
    _log_result(result)
    return result


def preprocess_audio(
    raw_audio: bytes,
    *,
    sample_rate: int = TARGET_RATE,
    channels: int = 1,
    sample_width: int = 2,
    source: str = "audio",
    config: Optional[AudioPreprocessingConfig] = None,
) -> bytes:
    return preprocess_audio_detailed(
        raw_audio, sample_rate=sample_rate, channels=channels,
        sample_width=sample_width, source=source, config=config).wav


def status() -> dict:
    """Diagnóstico leve para interface/log, sem carregar o modelo ONNX."""
    config = AudioPreprocessingConfig.current()
    return {
        "denoise": config.denoise,
        "normalize": config.normalize,
        "vad": config.vad,
        "ffmpeg": bool(_ffmpeg_path()),
        "rnnoise_model": RNNOISE_MODEL.is_file(),
        "silero_model": SILERO_MODEL.is_file(),
    }
