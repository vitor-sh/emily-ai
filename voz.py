from __future__ import annotations

import io
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import tecla_ptt

import keyboard
from pynput import mouse as pynput_mouse
import pyaudio
import speech_recognition as sr
from dotenv import load_dotenv
from groq import Groq
import discord_bot
from fish_audio_sdk import Prosody, Session, TTSRequest, WebSocketSession

try:
    import audioop  # mul() pro volume; no 3.13+ pode vir de audioop-lts
except ImportError:  # pragma: no cover
    try:
        import audioop_lts as audioop  # type: ignore
    except ImportError:
        audioop = None

load_dotenv()

FISH_AUDIO_KEY = os.getenv('FISH_AUDIO_KEY')
# EmilyV2, a voz da conta do Vitor. O padrão do pacote público (1d5c6866…) NÃO
# existe nesta conta: o Fish responde 400 na síntese e 404 no get_model. O
# public-release/exportar.py troca esta linha pelo ID público na exportação.
FISH_VOICE_ID = os.getenv('FISH_VOICE_ID', '28d1575c848841de930786be8d1ca40d')
def _aplicar_timeout_fish(sessao):
    """Amarra um teto de tempo no cliente HTTP da Fish.

    O SDK nasce com ``httpx.Client(timeout=None)``: sem teto, um stall do
    servidor pendura a síntese pelo tempo que for — visto em produção:
    ``sintese=79.50s`` seguido de "fila de áudio secou por 68.29s". O timeout
    de LEITURA vale entre chunks do stream; gaps normais de síntese ficam em
    torno de 1–3s, então 15s só dispara em stall de verdade.
    """
    try:
        import httpx
        conexao = float(os.getenv("EMILY_TTS_TIMEOUT_CONEXAO", "6"))
        leitura = float(os.getenv("EMILY_TTS_TIMEOUT_LEITURA", "15"))
        sessao._sync_client.timeout = httpx.Timeout(
            connect=conexao, read=leitura, write=conexao, pool=conexao)
    except Exception as e:
        print(f"[TTS] não consegui aplicar timeout no cliente Fish: {e}")
    return sessao


_session_fish = (_aplicar_timeout_fish(Session(FISH_AUDIO_KEY))
                 if os.getenv("EMILY_PUBLIC_MODE") != "1" or FISH_AUDIO_KEY else None)
_sessao_fish_local = threading.local()

_audio_sample_rate = 44100
_audio_channels = 1
_audio_sample_width = 2

cliente_groq = None
_cliente_groq_lock = threading.Lock()


def _obter_cliente_groq():
    """A transcrição é opcional; ausência de chave não pode impedir o boot."""
    global cliente_groq
    if cliente_groq is None:
        with _cliente_groq_lock:
            if cliente_groq is None:
                chave = os.getenv('GROQ_API_KEY')
                if not chave:
                    raise RuntimeError('GROQ_API_KEY não configurada para transcrição')
                cliente_groq = Groq(api_key=chave)
    return cliente_groq

# --- Configurações de áudio ---
SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2
CHANNELS = 1

CHUNK_AUDIO = 1024
TECLA_PTT = tecla_ptt.PADRAO
TAXA_AUDIO = 16000

# --- Eventos de controle ---
# Silencia a SAÍDA DE ÁUDIO sem desligar o resto do fluxo.
#
# Existe porque pedido escrito merece resposta escrita: o Vitor digitava na
# interface e ela respondia por voz também, o que atrapalha quem está de
# headset jogando.
#
# Fica aqui, e não nos ~30 `voz.falar(...)` do main.py, porque este é o único
# ponto por onde TODOS passam — inclusive o `callback_falar` que vai pro
# automacao.py e pro agente_ui.py, que também falam por conta própria.
#
# E não afeta a call do Discord: a resposta de lá usa `gerar_audio_bytes`
# direto (resto_call._gerar_voz), não passa por falar()/falar_stream().
mudo = threading.Event()
falar_ativo = threading.Event()
escutando_ativo = threading.Event()
TECLA_CALAR = '*'
parar_fala = threading.Event()

# --- Instância PyAudio ---
_pa = None if os.getenv("EMILY_RUNTIME_CLOUD") == "1" else pyaudio.PyAudio()

SAMPLE_RATE = 22050
SAMPLE_WIDTH = 2
CHANNELS = 1

# --- Callback de áudio remoto (ex: discord) ---
_callback_falar_audio = None


def definir_callback_audio(callback):
    """Registra uma função pra receber o áudio gerado em cada fala."""
    global _callback_falar_audio
    _callback_falar_audio = callback


def _notificar_audio(texto: str, audio_bytes: bytes):
    """Chama o callback de áudio de forma segura, sem quebrar a fala local."""
    if _callback_falar_audio and audio_bytes:
        try:
            _callback_falar_audio(texto, audio_bytes)
        except Exception as e:
            print(f'[TTS] Erro ao notificar áudio remoto: {e}')


# ── VOLUME DA VOZ ─────────────────────────────────────────────────
# O Vitor achava a voz dela alta demais e não tinha como regular. O fator
# multiplica as amostras PCM 16-bit (audioop.mul, com clip nativo). Fica no
# _gerar_audio_bytes de propósito: é o único ponto por onde passa TODA saída
# de voz — alto-falante do PC, call do Discord e áudio pro celular.
_volume_lock = threading.Lock()
_volume: float = 1.0
_VOLUME_MIN, _VOLUME_MAX = 0.0, 1.5
# (fator lido, quando foi lido). O streaming aplica volume a cada pedaço do
# Fish (~20ms), então o arquivo de preferências não pode ser lido por pedaço:
# uma leitura por segundo, no máximo.
_volume_cache: tuple = (1.0, 0.0)


def _carregar_volume() -> None:
    global _volume, _volume_cache
    try:
        import preferencias
        _volume = _limitar_volume(preferencias.obter("volume_voz", 1.0))
    except Exception:
        _volume = 1.0
    _volume_cache = (_volume, time.monotonic())


def _limitar_volume(valor: float) -> float:
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        return 1.0
    return max(_VOLUME_MIN, min(_VOLUME_MAX, valor))


def definir_volume(fator: float) -> float:
    """Ajusta o volume da voz (0.0 = mudo, 1.0 = padrão, 1.5 = reforço)."""
    global _volume, _volume_cache
    fator = _limitar_volume(fator)
    with _volume_lock:
        _volume = fator
    _volume_cache = (fator, time.monotonic())
    try:
        import preferencias
        preferencias.definir(volume_voz=fator)
    except Exception:
        pass
    return fator


def volume_atual() -> float:
    if time.monotonic() - _volume_cache[1] >= 1.0:
        _reler_volume_do_disco()
    with _volume_lock:
        return _volume


def _reler_volume_do_disco() -> None:
    """Relê o volume configurado, no máximo uma vez por segundo.

    A interface grava em preferencias quando o slider se move; o TTS em
    streaming passa por aqui por pedaço de ~20ms, e abrir o arquivo a cada
    pedaço seria mais caro que a própria síntese. Se preferencias sumir, o
    cache é carimbado do mesmo jeito — senão toda chamada tentaria de novo.
    """
    global _volume, _volume_cache
    agora = time.monotonic()
    try:
        import preferencias
        novo = _limitar_volume(preferencias.obter("volume_voz", 1.0))
        with _volume_lock:
            _volume = novo
        _volume_cache = (novo, agora)
    except Exception:
        _volume_cache = (_volume, agora)


def _aplicar_volume(pcm: bytes, largura: int = None) -> bytes:
    """Multiplica as amostras pelo volume configurado.

    ``largura`` existe porque o caminho em streaming aplica volume a cada
    pedaço do Fish e não passou por ``_gerar_audio_bytes`` (o único lugar que
    atualizava ``_audio_sample_width``): sem o parâmetro, o ``audioop.mul``
    usaria a largura da fala anterior e o pedaço sairia com ruído.
    """
    if not pcm or audioop is None:
        return pcm
    if time.monotonic() - _volume_cache[1] >= 1.0:
        _reler_volume_do_disco()
    with _volume_lock:
        fator = _volume
    if abs(fator - 1.0) < 0.01:
        return pcm
    try:
        return audioop.mul(pcm, largura or _audio_sample_width, fator)
    except Exception as e:
        print(f'[TTS] volume falhou ({e}); tocando no volume original')
        return pcm


_carregar_volume()


def _sessao_fish_da_thread() -> Session:
    """Uma sessão Fish por worker; evita compartilhar stream gRPC concorrente."""
    sessao = getattr(_sessao_fish_local, "sessao", None)
    if sessao is None:
        sessao = _aplicar_timeout_fish(Session(FISH_AUDIO_KEY))
        _sessao_fish_local.sessao = sessao
    return sessao


def _tentativas_tts() -> int:
    return max(1, int(os.getenv("EMILY_TTS_TENTATIVAS", "2")))


def _pausa_retry_tts() -> float:
    return max(0.0, float(os.getenv("EMILY_TTS_PAUSA_RETRY", "0.8")))


def _float_env_limitado(nome: str, padrao: float,
                        minimo: float, maximo: float) -> float:
    try:
        valor = float(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        valor = padrao
    return max(minimo, min(maximo, valor))


# ── REQUEST DA FISH (um construtor só) ────────────────────────────
# Aqui é onde a latência de voz morava. O caminho antigo pedia WAV e esperava
# o ARQUIVO INTEIRO antes de devolver qualquer coisa: medido neste projeto, o
# primeiro byte só saía em ~0,9s e o arquivo fechava em ~2,4s para uma resposta
# média. Em PCM cru o primeiro byte sai em ~0,37s (medido duas vezes: 0,374s e
# 0,363s) e o total também cai, porque a Fish não precisa montar cabeçalho nem
# remuxar — e PCM cru é exatamente o que o pyaudio e o FFmpeg consomem, de modo
# que o WAV não agregava nada.
#
# O ``chunk_length`` é o tamanho do trecho de texto que a Fish processa por
# vez: quanto menor, mais cedo o primeiro pedaço chega. Fica configurável
# porque é o botão de troca entre latência e suavidade de prosódia.
_TAXA_SAIDA_PADRAO = 44100


def _taxa_saida() -> int:
    """Taxa pedida à Fish.

    Os dois destinos aceitam qualquer valor: o `_tocar_bytes` reamostra se o
    dispositivo recusar, e o ffmpeg da call converte pra 48kHz de todo jeito.
    Este número existe pra um dia baixar banda sem caçar usos espalhados.
    """
    return int(_float_env_limitado("EMILY_FISH_TAXA", _TAXA_SAIDA_PADRAO,
                                   8000, 48000))


def _latencia_fish() -> str:
    """'balanced' (~300ms até o primeiro áudio) contra 'normal' (~500ms).

    Numa conversa por voz a diferença aparece e a qualidade final é a mesma nos
    dois modos, então 'balanced' é o padrão. 'normal' fica como saída de
    emergência por env, para o caso de algum texto sair mal articulado.
    """
    modo = os.getenv("EMILY_FISH_LATENCIA", "balanced").strip().lower()
    return "normal" if modo == "normal" else "balanced"


def _formato_fish() -> str:
    """Formato pedido ao Fish. PCM por padrão — ver o comentário acima."""
    escolhido = os.getenv("EMILY_FISH_FORMATO", "pcm").strip().lower()
    return "wav" if escolhido == "wav" else "pcm"


def _backend_fish() -> str:
    """Seleciona o modelo gratuito explicitamente no HTTP e no WebSocket."""
    return os.getenv("EMILY_FISH_BACKEND", "s2.1-pro-free").strip() or "s2.1-pro-free"


def _erro_tts_permanente(erro):
    """402/autenticação não se recuperam repetindo a mesma solicitação."""
    status = getattr(erro, "status", None)
    if status is None:
        status = getattr(erro, "status_code", None)
    return status in (400, 401, 402, 403, 404, 422)


def _aviso_tts_permanente(erro):
    status = getattr(erro, "status", getattr(erro, "status_code", None))
    if status == 402:
        return ("Fish Audio recusou a síntese por cobrança/acesso (HTTP 402). "
                "Modelo selecionado: " + _backend_fish() + ". A resposta escrita continua disponível.")
    if status in (400, 404):
        return ("Fish Audio recusou a solicitação (HTTP " + str(status) + "). Confira se a voz "
                "(FISH_VOICE_ID) existe na conta dona da chave, além do modelo. "
                "A resposta escrita continua disponível.")
    return "Fish Audio recusou a solicitação. Confira chave, voz e modelo. A resposta escrita continua disponível."


def _tamanho_chunk_fish() -> int:
    """Trecho de texto que a Fish processa por vez (100–300, exigido por ela).

    Menor = primeiro áudio antes. 100 entrega o áudio completo em ~0,89s contra
    ~1,85s do padrão 200 (medido na mesma frase). Se a voz soar picotada,
    EMILY_FISH_CHUNK_LENGTH=200 volta ao comportamento antigo sem mexer no
    código.
    """
    return int(_float_env_limitado("EMILY_FISH_CHUNK_LENGTH", 100, 100, 300))


def _parametros_call(para_call: bool) -> dict:
    """Prosódia e tom extras da call; fora dela vale o padrão do Fish."""
    if not para_call:
        return {}
    return {
        "prosody": Prosody(
            speed=_float_env_limitado("EMILY_CALL_FISH_SPEED", 1.0, 0.5, 2.0),
            volume=_float_env_limitado(
                "EMILY_CALL_FISH_VOLUME", 0.0, -20.0, 20.0),
        ),
        "temperature": _float_env_limitado(
            "EMILY_CALL_FISH_TEMPERATURE", 0.7, 0.0, 1.0),
        "top_p": _float_env_limitado(
            "EMILY_CALL_FISH_TOP_P", 0.7, 0.0, 1.0),
    }


def _requisicao_fish(texto_fala: str, formato: str = None,
                     para_call: bool = False) -> TTSRequest:
    """Um construtor só de request: streaming e não-streaming não divergem.

    Fica num lugar só pra o caminho em streaming e o de uma vez só usarem
    exatamente a mesma voz, o mesmo modelo e o mesmo tom. O que não pode mudar
    entre eles é voz, taxa e modelo.
    """
    return TTSRequest(
        text=texto_fala,
        reference_id=FISH_VOICE_ID,
        format=formato or _formato_fish(),
        sample_rate=_taxa_saida(),
        # "balanced" (~300ms) em vez de "normal" (~500ms): aqui o que importa
        # é o tempo até o primeiro som, e a voz clonada é a mesma nos dois.
        latency=_latencia_fish(),
        chunk_length=_tamanho_chunk_fish(),
        **_parametros_call(para_call),
    )


def _abrir_tts_http(cliente, request: TTSRequest):
    """Abre o stream HTTP com backend explícito e aceita sessões falsas antigas."""
    try:
        return cliente.tts(request, backend=_backend_fish())
    except TypeError as erro:
        # Os doubles dos testes e versões antigas da SDK recebem só o request.
        if "backend" not in str(erro):
            raise
        if os.getenv("EMILY_PUBLIC_MODE") == "1" or _backend_fish() == "s2.1-pro-free":
            raise RuntimeError("Atualize fish-audio-sdk: esta versão não permite selecionar o modelo gratuito com segurança.") from None
        return cliente.tts(request)


# ── FORMATO DO ÁUDIO DA FISH ──────────────────────────────────────
# Medido contra a API real (08/09/2026): pedindo ``format='pcm'`` com
# ``sample_rate=44100`` a Fish devolve o áudio cru, s16le MONO a 44100, sem
# cabeçalho nenhum. O modo ``'wav'`` é exatamente o mesmo áudio com 44 bytes de
# header na frente — header esse que no modo streaming vem com o campo de
# tamanho inválido (nframes=2147483520), ou seja, nem dá pra confiar nele pra
# saber a duração.
#
# Como o PCM é o mesmo som sem o header, ele chega antes: no A/B com a mesma
# fala (10,4s de áudio sintetizado) o primeiro byte saiu em 0,37s no pcm contra
# 0,89s no wav, e o total em 2,15s contra 2,43s. O ganho vale pros três
# caminhos (alto-falante do PC, call do Discord e celular), porque todos
# consomem PCM cru no fim.
TAXA_PCM_FISH = 44100
CANAIS_PCM_FISH = 1
LARGURA_PCM_FISH = 2


def _parametros_do_header_wav(bruto: bytes):
    """``(taxa, canais, largura, início_do_áudio)`` do WAV, ou ``None``.

    Rede de segurança: pedimos PCM, então este caminho não deveria rodar. Se um
    dia a Fish voltar a mandar WAV (ou passar a ignorar o formato pedido), os
    parâmetros saem do próprio header em vez de saírem errados e a voz soar
    acelerada ou em câmera lenta.
    """
    if len(bruto) < 12 or bruto[:4] != b"RIFF" or bruto[8:12] != b"WAVE":
        return None
    taxa, canais, largura = TAXA_PCM_FISH, CANAIS_PCM_FISH, LARGURA_PCM_FISH
    posicao = 12
    while posicao + 8 <= len(bruto):
        bloco = bruto[posicao:posicao + 4]
        tamanho = int.from_bytes(bruto[posicao + 4:posicao + 8], "little")
        if bloco == b"data":
            return taxa, canais, largura, posicao + 8
        if bloco == b"fmt " and posicao + 24 <= len(bruto):
            canais = int.from_bytes(bruto[posicao + 10:posicao + 12], "little") or canais
            taxa = int.from_bytes(bruto[posicao + 12:posicao + 16], "little") or taxa
            bits = int.from_bytes(bruto[posicao + 22:posicao + 24], "little")
            largura = max(1, bits // 8) if bits else largura
        posicao += 8 + tamanho + (tamanho % 2)
    return None


def _pcm_da_resposta(bruto: bytes) -> tuple:
    """Resposta completa da Fish -> ``(pcm, taxa, canais, largura)``."""
    parametros = _parametros_do_header_wav(bruto)
    if parametros is None:
        return bruto, _taxa_saida(), CANAIS_PCM_FISH, LARGURA_PCM_FISH
    taxa, canais, largura, inicio = parametros
    return bruto[inicio:], taxa, canais, largura


class FormatoDaFala:
    """Onde o leitor do stream publica taxa/canais do áudio que chegou.

    O leitor roda numa thread e quem toca pode estar em outra (no Discord o
    áudio atravessa o FFmpeg do outro lado). São três números escritos de uma
    vez só, ANTES de o primeiro chunk de áudio ficar visível pro outro lado —
    não precisa de lock.
    """

    __slots__ = ("taxa", "canais", "largura")

    def __init__(self):
        self.taxa = _taxa_saida()
        self.canais = CANAIS_PCM_FISH
        self.largura = LARGURA_PCM_FISH


def _iterar_pcm_da_fish(fluxo: Iterator[bytes],
                        formato: FormatoDaFala) -> Iterator[bytes]:
    """Chunks PCM completos, sem header WAV nem meia amostra entre pacotes.

    Os limites de chunk HTTP/WebSocket não respeitam necessariamente limites de
    amostra. Em PCM16 mono, um pacote pode terminar com 1 byte da amostra e o
    seguinte trazer o outro. ``audioop`` e os players exigem frames inteiros, por
    isso mantemos esse rabo até a próxima chegada.
    """
    pendente = b""
    pcm_pendente = b""
    resolvido = False
    for pedaco in fluxo:
        dados = pedaco
        if not resolvido:
            pendente += pedaco
            # O header do WAV tem ao menos 44 bytes; espera antes de decidir.
            if pendente[:4] == b"RIFF" and len(pendente) < 44:
                continue
            parametros = _parametros_do_header_wav(pendente)
            resolvido = True
            if parametros is None:
                dados = pendente
            else:
                formato.taxa, formato.canais, formato.largura = parametros[:3]
                dados = pendente[parametros[3]:]
            pendente = b""

        if not dados:
            continue
        pcm_pendente += dados
        tamanho_frame = max(1, formato.canais * formato.largura)
        utilizavel = len(pcm_pendente) - (len(pcm_pendente) % tamanho_frame)
        if utilizavel:
            yield pcm_pendente[:utilizavel]
            pcm_pendente = pcm_pendente[utilizavel:]


def _gerar_audio_pacote(texto: str, sessao: Session = None,
                        para_call: bool = False):
    """Gera ``(pcm, taxa, canais, largura)`` sem depender de globals mutáveis.

    O stream da Fish pode engasgar no servidor (o modelo free sofre throttle
    em rajadas) e o SDK não tinha timeout — a chamada pendurava dezenas de
    segundos e a fila de áudio secava atrás dela. Cada tentativa agora é
    limitada pelos timeouts do cliente e, em falha, refaz com sessão nova
    antes de entregar vazio (a legenda continua íntegra no tocador).
    """
    # O modelo escreve com markdown rico no chat; o TTS não pode soletrar
    # os símbolos. limpar_para_tts tira a sintaxe markdown (e já tira
    # emojis e expande abreviações). Import local pra não criar ciclo.
    from modelo import limpar_para_tts
    texto_fala = limpar_para_tts(texto)
    total = _tentativas_tts()
    ultimo_erro = None
    for tentativa in range(1, total + 1):
        inicio = time.monotonic()
        try:
            cliente = sessao if sessao is not None else _session_fish
            request = _requisicao_fish(
                texto_fala, formato=_formato_fish(), para_call=para_call)
            bruto = b''.join(_abrir_tts_http(cliente, request))
            pcm, taxa, canais, largura = _pcm_da_resposta(bruto)
            pcm = _aplicar_volume(pcm, largura)
            duracao = len(pcm) / max(1, taxa * canais * largura)
            sintese = time.monotonic() - inicio
            sufixo = "" if tentativa == 1 else f" tentativa={tentativa}"
            print(f"[TTS-LATENCIA] sintese={sintese:.2f}s audio={duracao:.2f}s "
                  f"chars={len(texto_fala)}{sufixo}")
            return pcm, taxa, canais, largura
        except Exception as e:
            ultimo_erro = e
            gasto = time.monotonic() - inicio
            print(f"[TTS-RETRY] tentativa {tentativa}/{total} falhou após "
                  f"{gasto:.2f}s: {type(e).__name__}: {e}")
            if _erro_tts_permanente(e):
                print("[TTS] " + _aviso_tts_permanente(e))
                break
            if tentativa < total:
                if sessao is not None:
                    # A conexão pode ter ficado envenenada no meio do stream:
                    # descarta a sessão da thread e refaz do zero.
                    _sessao_fish_local.sessao = None
                    sessao = _sessao_fish_da_thread()
                time.sleep(_pausa_retry_tts())
    print(f'[TTS] Erro Fish Audio: {ultimo_erro}')
    return b'', _audio_sample_rate, _audio_channels, _audio_sample_width


def _gerar_audio_bytes(texto: str, para_call: bool = False) -> bytes:
    """Compatibilidade: gera PCM e atualiza os metadados públicos do módulo."""
    global _audio_sample_rate, _audio_channels, _audio_sample_width
    pcm, taxa, canais, largura = _gerar_audio_pacote(
        texto, para_call=para_call)
    _audio_sample_rate = taxa
    _audio_channels = canais
    _audio_sample_width = largura
    return pcm


# Blocos de ESCRITA no pyaudio. O CHUNK_AUDIO (1024) serve pra CAPTURA; como
# saída ele era minúsculo: 1024 bytes a 44,1 kHz/16-bit/mono são ~12ms por
# write, e essa enxurrada de writes curtos dá underrun no ALSA/PulseAudio do
# Linux — a voz sai engasgada e "robótica" mesmo com o áudio gerado perfeito
# (no Windows o WASAPI mascara com buffer maior; por isso a queixa apareceu
# na migração). ~90ms por write é o ponto feliz.
CHUNK_SAIDA_BYTES = 8192


def _resample_pcm16(dados: bytes, taxa_de: int, taxa_para: int) -> bytes:
    """Reamostragem linear de PCM 16-bit. Só usada quando o dispositivo de
    som recusa a taxa do WAV gerado — tocar na taxa errada desloca o pitch,
    que é O efeito "voz de robô" clássico."""
    if taxa_de == taxa_para or taxa_de <= 0 or taxa_para <= 0 or not dados:
        return dados
    import array as _array
    amostras = _array.array("h")
    amostras.frombytes(dados[: len(dados) - (len(dados) % 2)])
    total = int(len(amostras) * taxa_para / taxa_de)
    if total <= 0:
        return dados
    saida = _array.array("h", bytes(2 * total))
    passo = taxa_de / taxa_para
    fim = len(amostras) - 1
    for i in range(total):
        pos = i * passo
        i0 = int(pos)
        if i0 >= fim:
            saida[i] = amostras[fim]
            continue
        frac = pos - i0
        saida[i] = int(amostras[i0] * (1.0 - frac) + amostras[i0 + 1] * frac)
    return saida.tobytes()


def _tocar_bytes(audio_bytes: bytes):
    """Toca PCM bruto com pyaudio usando os parâmetros do áudio gerado."""
    if not audio_bytes:
        return

    # Alguns setups de ALSA no Linux só abrem a saída na taxa do hardware;
    # se a taxa do WAV for recusada, reamostra e abre numa taxa garantida
    # em vez de falhar (ou pior: abrir e soar deslocada).
    try:
        stream = _pa.open(
            format=_pa.get_format_from_width(_audio_sample_width),
            channels=_audio_channels,
            rate=_audio_sample_rate,
            output=True,
            frames_per_buffer=2048,
        )
    except OSError as e:
        fallback = 48000 if _audio_sample_rate != 48000 else 44100
        print(f"[TTS] Dispositivo recusou {_audio_sample_rate}Hz ({e}); "
              f"reamostrando pra {fallback}Hz.")
        audio_bytes = _resample_pcm16(audio_bytes, _audio_sample_rate, fallback)
        stream = _pa.open(
            format=_pa.get_format_from_width(_audio_sample_width),
            channels=_audio_channels,
            rate=fallback,
            output=True,
            frames_per_buffer=2048,
        )
    try:
        for i in range(0, len(audio_bytes), CHUNK_SAIDA_BYTES):
            if not falar_ativo.is_set() or parar_fala.is_set():
                break
            stream.write(audio_bytes[i:i + CHUNK_SAIDA_BYTES])
    finally:
        stream.stop_stream()
        stream.close()


_FIM_STREAM_PCM = object()


def gerar_audio_stream(texto: str, para_call: bool = False,
                       sessao: Session = None, on_conexao=None) -> Iterator[bytes]:
    """Entrega PCM conforme a Fish produz, com retry antes do primeiro áudio.

    Se a conexão cair depois que algum áudio já saiu, a função não repete a
    frase — repetir desde o começo seria muito pior que perder o final. Antes do
    primeiro chunk, respeita as mesmas tentativas do caminho de buffer completo.
    """
    global _audio_sample_rate, _audio_channels, _audio_sample_width
    from modelo import limpar_para_tts

    texto_fala = limpar_para_tts(texto)
    if not texto_fala:
        return
    ultimo_erro = None
    reconectando = False
    for tentativa in range(1, _tentativas_tts() + 1):
        inicio = time.monotonic()
        entregues = 0
        formato = FormatoDaFala()
        try:
            cliente = sessao if sessao is not None else _sessao_fish_da_thread()
            request = _requisicao_fish(
                texto_fala, formato=_formato_fish(), para_call=para_call)
            fluxo = _abrir_tts_http(cliente, request)
            for pedaco in _iterar_pcm_da_fish(fluxo, formato):
                if not pedaco or parar_fala.is_set():
                    continue
                pcm = _aplicar_volume(pedaco, formato.largura)
                _audio_sample_rate = formato.taxa
                _audio_channels = formato.canais
                _audio_sample_width = formato.largura
                entregues += len(pcm)
                if reconectando and on_conexao:
                    on_conexao("reconectado", {"servico": "voz"})
                    reconectando = False
                yield pcm
            if entregues:
                decorrido = time.monotonic() - inicio
                duracao = entregues / max(
                    1, formato.taxa * formato.canais * formato.largura)
                sufixo = "" if tentativa == 1 else f" tentativa={tentativa}"
                print(f"[TTS-LATENCIA] stream={decorrido:.2f}s "
                      f"audio={duracao:.2f}s chars={len(texto_fala)}{sufixo}")
                return
            raise RuntimeError("Fish encerrou sem produzir áudio")
        except Exception as erro:
            ultimo_erro = erro
            gasto = time.monotonic() - inicio
            if entregues:
                print(f"[TTS] stream interrompido após {gasto:.2f}s e "
                      f"{entregues} bytes: {type(erro).__name__}: {erro}")
                if on_conexao:
                    on_conexao("erro_conexao", {"servico": "voz",
                               "mensagem": "A fala foi interrompida; a resposta escrita continua no chat."})
                return
            print(f"[TTS-RETRY] tentativa {tentativa}/{_tentativas_tts()} "
                  f"falhou antes do áudio após {gasto:.2f}s: "
                  f"{type(erro).__name__}: {erro}")
            if _erro_tts_permanente(erro):
                aviso = _aviso_tts_permanente(erro)
                print("[TTS] " + aviso)
                if on_conexao:
                    on_conexao("erro_conexao", {"servico": "voz", "mensagem": aviso})
                return
            if tentativa < _tentativas_tts():
                reconectando = True
                if on_conexao:
                    on_conexao("reconectando", {"servico": "voz",
                               "tentativa": tentativa, "limite": _tentativas_tts()})
                if sessao is not None:
                    _sessao_fish_local.sessao = None
                    sessao = _sessao_fish_da_thread()
                time.sleep(_pausa_retry_tts())
    print(f"[TTS] Erro Fish Audio em streaming: {ultimo_erro}")


class _SaidaPCMIncremental:
    """Distribui cada chunk ao alto-falante e ao Discord sem bloquear a rede."""

    def __init__(self, texto: str = ""):
        self.texto = texto
        self._fila_local = queue.Queue()
        self._thread_local = None
        self._discord = None
        self._iniciada = False
        self._taxa = _taxa_saida()
        self._canais = CANAIS_PCM_FISH
        self._largura = LARGURA_PCM_FISH

    def _tocar_local(self):
        taxa_dispositivo = self._taxa
        try:
            stream = _pa.open(
                format=_pa.get_format_from_width(self._largura),
                channels=self._canais,
                rate=taxa_dispositivo,
                output=True,
                frames_per_buffer=2048,
            )
        except OSError as erro:
            taxa_dispositivo = 48000 if self._taxa != 48000 else 44100
            print(f"[TTS] Dispositivo recusou {self._taxa}Hz ({erro}); "
                  f"reamostrando stream pra {taxa_dispositivo}Hz.")
            try:
                stream = _pa.open(
                    format=_pa.get_format_from_width(self._largura),
                    channels=self._canais,
                    rate=taxa_dispositivo,
                    output=True,
                    frames_per_buffer=2048,
                )
            except Exception as segundo_erro:
                print(f"[TTS] Não consegui abrir saída local: {segundo_erro}")
                while self._fila_local.get() is not _FIM_STREAM_PCM:
                    pass
                return
        try:
            while True:
                pedaco = self._fila_local.get()
                if pedaco is _FIM_STREAM_PCM:
                    break
                if parar_fala.is_set():
                    continue
                if taxa_dispositivo != self._taxa:
                    pedaco = _resample_pcm16(
                        pedaco, self._taxa, taxa_dispositivo)
                stream.write(pedaco)
        finally:
            stream.stop_stream()
            stream.close()

    def _iniciar(self, taxa: int, canais: int, largura: int) -> None:
        if self._iniciada:
            return
        self._iniciada = True
        self._taxa, self._canais, self._largura = taxa, canais, largura
        try:
            self._discord = discord_bot.abrir_stream_pcm_discord(
                taxa, canais, self.texto)
        except AttributeError:
            self._discord = None
        self._thread_local = threading.Thread(
            target=self._tocar_local, daemon=True, name="emily-audio-stream")
        self._thread_local.start()

    def escrever(self, pedaco: bytes, taxa: int, canais: int,
                 largura: int = LARGURA_PCM_FISH) -> None:
        if not pedaco or parar_fala.is_set():
            return
        self._iniciar(taxa, canais, largura)
        self._fila_local.put(pedaco)
        if self._discord is not None:
            self._discord.escrever(pedaco)

    def fechar(self) -> None:
        if not self._iniciada:
            return
        self._fila_local.put(_FIM_STREAM_PCM)
        if self._discord is not None:
            self._discord.fechar(esperar=False)
        if self._thread_local is not None:
            self._thread_local.join()


def _falar_texto_incremental(texto: str, callback_status=None,
                             para_call: bool = False) -> bytes:
    """Sintetiza uma unidade e já a reproduz; devolve o PCM para callbacks."""
    saida = _SaidaPCMIncremental(texto)
    acumulado = bytearray()
    anunciou = False
    inicio = time.monotonic()
    try:
        for pedaco in gerar_audio_stream(texto, para_call=para_call):
            if not anunciou:
                anunciou = True
                print(f"[TTS-LATENCIA] primeiro_audio="
                      f"{time.monotonic() - inicio:.3f}s")
                if callback_status is not None:
                    callback_status(texto)
            acumulado.extend(pedaco)
            saida.escrever(
                pedaco, _audio_sample_rate, _audio_channels,
                _audio_sample_width)
    finally:
        saida.fechar()
    return bytes(acumulado)


def falar(texto: str):
    if mudo.is_set() or (os.getenv("EMILY_PUBLIC_MODE") == "1" and not FISH_AUDIO_KEY):
        # Pedido veio escrito: a resposta é escrita. Ver o comentário de `mudo`.
        return
    parar_fala.clear()
    falar_ativo.set()
    try:
        audio_bytes = _falar_texto_incremental(texto)
        if not audio_bytes:
            # Última rede de segurança: preserva o comportamento antigo caso o
            # servidor/SDK deixe de produzir chunks incrementais.
            audio_bytes = _gerar_audio_bytes(texto)
            if audio_bytes:
                discord_bot.tocar_pcm_discord(
                    audio_bytes, _audio_sample_rate, _audio_channels)
                _tocar_bytes(audio_bytes)
        _notificar_audio(texto, audio_bytes)
    except Exception as e:
        print(f'[TTS] Erro em falar(): {e}')
    finally:
        falar_ativo.clear()


def _falar_stream_prefetch(fila_frases: queue.Queue, callback_status):
    """Fallback legado: sintetiza frases completas em paralelo e toca em ordem."""
    # Dois workers são suficientes: enquanto o áudio N toca, N+1 e N+2 podem
    # ficar prontos. Mais que isso só aumentaria concorrência/rate limit sem
    # melhorar a continuidade perceptível. Configurável para diagnóstico.
    prefetch = max(1, min(3, int(os.getenv("EMILY_TTS_PREFETCH", "2"))))
    fila_audio = queue.Queue()
    executor = ThreadPoolExecutor(max_workers=prefetch,
                                  thread_name_prefix="fish-tts")

    def sintetizar(frase: str):
        return _gerar_audio_pacote(frase, _sessao_fish_da_thread())

    def gerador():
        while True:
            if parar_fala.is_set():
                fila_audio.put(None)
                return
            frase = fila_frases.get()
            if frase is None:
                fila_audio.put(None)
                return
            try:
                # A future entra na fila IMEDIATAMENTE, preservando a ordem. O
                # tocador espera a primeira; as seguintes sintetizam em paralelo
                # e normalmente já estão prontas quando o áudio atual termina.
                futuro = executor.submit(sintetizar, frase)
                fila_audio.put((frase, futuro))
            except Exception as e:
                print(f'[TTS] Erro ao agendar frase: {e}')

    def tocador():
        falar_ativo.set()
        tocou_alguma = False
        while True:
            item = fila_audio.get()
            if item is None:
                break
            if parar_fala.is_set():
                break
            frase, futuro = item
            try:
                esperando_desde = time.monotonic()
                audio_bytes, taxa, canais, largura = futuro.result()
                espera_pronta = time.monotonic() - esperando_desde
                if tocou_alguma and espera_pronta >= 0.12:
                    print(f"[TTS-LATENCIA] fila de áudio secou por "
                          f"{espera_pronta:.2f}s antes da próxima unidade")
            except Exception as e:
                print(f'[TTS] Erro ao obter frase pronta: {e}')
                continue
            if not audio_bytes:
                # Sem áudio, mas não esconda a resposta na interface. A legenda
                # deixa de estar sincronizada porque não há o que tocar, porém o
                # turno visual continua íntegro e a resposta final ainda corrige
                # markdown/quebras.
                callback_status(frase)
                continue
            # A legenda avança no instante em que o áudio desta unidade começa.
            callback_status(frase)
            global _audio_sample_rate, _audio_channels, _audio_sample_width
            _audio_sample_rate, _audio_channels, _audio_sample_width = taxa, canais, largura
            _notificar_audio(frase, audio_bytes)
            discord_bot.tocar_pcm_discord(audio_bytes, taxa, canais)
            _tocar_bytes(audio_bytes)
            tocou_alguma = True
        falar_ativo.clear()

    t_gerador = threading.Thread(target=gerador, daemon=True)
    t_tocador = threading.Thread(target=tocador, daemon=True)
    try:
        t_gerador.start()
        t_tocador.start()
        t_gerador.join()
        t_tocador.join()
    finally:
        executor.shutdown(wait=True, cancel_futures=parar_fala.is_set())


def _falar_stream_http_incremental(primeira: str, fila_frases: queue.Queue,
                                   callback_status, on_progresso=None) -> None:
    """Prefetch por frase, mas toca cada request desde o primeiro chunk PCM."""
    prefetch = max(1, min(3, int(os.getenv("EMILY_TTS_PREFETCH", "2"))))
    fila_streams = queue.Queue()
    executor = ThreadPoolExecutor(
        max_workers=prefetch, thread_name_prefix="fish-stream")

    def avisar(fase, dados):
        if on_progresso:
            try:
                on_progresso(fase, dados)
            except Exception as erro:
                print(f"[TTS] progresso visual indisponível: {type(erro).__name__}")

    def produzir(frase: str, fila_pcm: queue.Queue) -> None:
        produziu = False
        try:
            for pedaco in gerar_audio_stream(frase, on_conexao=avisar):
                produziu = True
                fila_pcm.put(pedaco)
            if not produziu and not parar_fala.is_set():
                # Se o servidor não entregou nenhum chunk após timeout/retries,
                # cai no modo completo antigo em vez de perder a fala.
                pcm, _taxa, _canais, _largura = _gerar_audio_pacote(
                    frase, _sessao_fish_da_thread())
                if pcm:
                    fila_pcm.put(pcm)
                    avisar("reconectado", {"servico": "voz"})
                else:
                    avisar("erro_conexao", {"servico": "voz",
                           "mensagem": "Não consegui gerar a fala; a resposta escrita continua no chat."})
        except Exception as erro:
            print(f"[TTS] erro no stream da frase: {type(erro).__name__}: {erro}")
        finally:
            fila_pcm.put(_FIM_STREAM_PCM)

    def agendar() -> None:
        frase = primeira
        while frase is not None and not parar_fala.is_set():
            original = str(frase).strip()
            if original:
                fila_pcm = queue.Queue()
                futuro = executor.submit(produzir, original, fila_pcm)
                # Entra imediatamente para o player esperar o PRIMEIRO chunk,
                # não a Future inteira. Requests seguintes já ficam em voo.
                fila_streams.put((original, fila_pcm, futuro))
            frase = fila_frases.get()
        fila_streams.put(None)

    saida = _SaidaPCMIncremental(str(primeira))
    gerador = threading.Thread(target=agendar, daemon=True,
                               name="fish-stream-agendador")
    falar_ativo.set()
    gerador.start()
    try:
        while True:
            item = fila_streams.get()
            if item is None or parar_fala.is_set():
                break
            frase, fila_pcm, futuro = item
            acumulado = bytearray()
            anunciou = False
            esperando_desde = time.monotonic()
            while True:
                pedaco = fila_pcm.get()
                if pedaco is _FIM_STREAM_PCM:
                    break
                if not pedaco or parar_fala.is_set():
                    continue
                if not anunciou:
                    anunciou = True
                    espera = time.monotonic() - esperando_desde
                    print(f"[TTS-LATENCIA] frase_primeiro_audio={espera:.3f}s")
                    try:
                        callback_status(frase)
                    except Exception as erro:
                        print(f"[TTS] callback de status falhou: {erro}")
                acumulado.extend(pedaco)
                saida.escrever(
                    pedaco, _audio_sample_rate, _audio_channels,
                    _audio_sample_width)
            try:
                futuro.result()
            except Exception:
                pass
            if acumulado:
                _notificar_audio(frase, bytes(acumulado))
            elif not anunciou:
                # O texto não pode desaparecer da interface porque o TTS falhou.
                try:
                    callback_status(frase)
                except Exception as erro:
                    print(f"[TTS] callback de status falhou sem áudio: {erro}")
    finally:
        saida.fechar()
        gerador.join(timeout=2)
        executor.shutdown(wait=True, cancel_futures=parar_fala.is_set())
        falar_ativo.clear()


def falar_stream(fila_frases: queue.Queue, callback_status, on_progresso=None):
    """Conecta as frases do LLM ao TTS e reproduz PCM na chegada.

    O padrão é HTTP incremental por frase: foi o transporte mais rápido no teste
    real e permite prefetch das próximas unidades. O WebSocket live da SDK 1.3
    continua disponível por ``EMILY_TTS_TRANSPORTE=websocket``, mas não é o
    padrão porque, sem ``FlushEvent``, o servidor medido esperou o gerador de
    texto terminar antes de liberar a primeira frase.
    """
    if mudo.is_set() or (os.getenv("EMILY_PUBLIC_MODE") == "1" and not FISH_AUDIO_KEY):
        # Muda, mas NÃO cega: o callback continua levando texto à interface.
        while True:
            frase = fila_frases.get()
            if frase is None:
                return
            if frase and frase.strip():
                try:
                    callback_status(frase)
                except Exception as e:
                    print(f'[TTS] callback de status falhou no modo mudo: {e}')
        return

    parar_fala.clear()
    # Só abre o socket depois da primeira frase. Além de evitar uma conexão
    # ociosa durante o primeiro token do LLM, um teste real mostrou que o socket
    # do endpoint legado pode ser encerrado pelo servidor se ficar vários
    # segundos sem receber TextEvent.
    primeira = fila_frases.get()
    if primeira is None:
        return

    transporte = os.getenv("EMILY_TTS_TRANSPORTE", "http").strip().lower()
    # Compatibilidade com a chave experimental criada durante a migração.
    ws_legado = os.getenv("EMILY_TTS_WEBSOCKET")
    if ws_legado is not None:
        transporte = (
            "websocket" if ws_legado.strip().lower() in {"1", "true", "sim", "on"}
            else "http"
        )

    if transporte in {"prefetch", "legacy", "legado"}:
        fallback = queue.Queue()
        fallback.put(primeira)
        while True:
            frase = fila_frases.get()
            fallback.put(frase)
            if frase is None:
                break
        _falar_stream_prefetch(fallback, callback_status)
        return

    if transporte not in {"websocket", "ws"}:
        _falar_stream_http_incremental(primeira, fila_frases, callback_status,
                                      on_progresso=on_progresso)
        return

    frases_enviadas = []
    restantes = queue.Queue()
    terminou = False

    def textos():
        nonlocal terminou
        atual = primeira
        from modelo import limpar_para_tts
        while atual is not None and not parar_fala.is_set():
            original = str(atual).strip()
            limpo = limpar_para_tts(original)
            if limpo:
                frases_enviadas.append(original)
                try:
                    callback_status(original)
                except Exception as erro:
                    print(f"[TTS] callback de status falhou: {erro}")
                yield limpo + " "
            atual = fila_frases.get()
        terminou = atual is None

    saida = _SaidaPCMIncremental(str(primeira))
    acumulado = bytearray()
    primeiro_audio = None
    sessao_ws = None
    falar_ativo.set()
    inicio = time.monotonic()
    try:
        base_url = os.getenv("EMILY_FISH_BASE_URL", "https://api.fish.audio")
        sessao_ws = WebSocketSession(FISH_AUDIO_KEY, base_url=base_url)
        request = _requisicao_fish("", formato="pcm")
        fluxo = sessao_ws.tts(request, textos(), backend=_backend_fish())
        formato = FormatoDaFala()
        for pedaco in _iterar_pcm_da_fish(fluxo, formato):
            if not pedaco or parar_fala.is_set():
                continue
            pcm = _aplicar_volume(pedaco, formato.largura)
            if primeiro_audio is None:
                primeiro_audio = time.monotonic() - inicio
                print(f"[TTS-LATENCIA] websocket_primeiro_audio="
                      f"{primeiro_audio:.3f}s")
            global _audio_sample_rate, _audio_channels, _audio_sample_width
            _audio_sample_rate = formato.taxa
            _audio_channels = formato.canais
            _audio_sample_width = formato.largura
            acumulado.extend(pcm)
            saida.escrever(pcm, formato.taxa, formato.canais, formato.largura)
        if not acumulado:
            raise RuntimeError("WebSocket Fish encerrou sem áudio")
        texto_total = " ".join(frases_enviadas).strip()
        _notificar_audio(texto_total, bytes(acumulado))
    except Exception as erro:
        print(f"[TTS] WebSocket indisponível ({type(erro).__name__}: {erro}); "
              "usando fallback HTTP por frase.")
        # Não repete uma resposta que já começou a tocar. O fallback só entra
        # quando nenhum chunk foi entregue.
        if not acumulado:
            if not frases_enviadas:
                restantes.put(primeira)
            for frase in frases_enviadas:
                restantes.put(frase)
            if not terminou:
                while True:
                    frase = fila_frases.get()
                    restantes.put(frase)
                    if frase is None:
                        break
            else:
                restantes.put(None)
            # ``textos`` já publicou as frases que chegaram a ser enviadas ao
            # socket. O fallback precisa sintetizá-las, mas não duplicar a
            # legenda/status visual.
            pular_callbacks = len(frases_enviadas)

            def callback_fallback(frase):
                nonlocal pular_callbacks
                if pular_callbacks:
                    pular_callbacks -= 1
                    return
                callback_status(frase)

            _falar_stream_prefetch(restantes, callback_fallback)
    finally:
        saida.fechar()
        if sessao_ws is not None:
            try:
                sessao_ws.close()
            except Exception:
                pass
        falar_ativo.clear()


def falar_na_call_stream(texto: str, cancelar_se=None):
    """TTS incremental da call; ``None`` pede fallback para o caminho legado."""
    if not texto or not texto.strip():
        return False
    handle = discord_bot.abrir_stream_pcm_discord(
        _taxa_saida(), CANAIS_PCM_FISH, texto)
    if handle is None:
        return False
    total = 0
    inicio = time.monotonic()
    try:
        for pedaco in gerar_audio_stream(texto, para_call=True):
            if cancelar_se is not None and cancelar_se():
                break
            if not pedaco:
                continue
            if total == 0:
                print(f"[CALL-LATENCIA] primeiro_audio_tts="
                      f"{time.monotonic() - inicio:.3f}s")
            total += len(pedaco)
            handle.escrever(pedaco)
    except Exception as erro:
        print(f"[CALL] TTS incremental falhou: {type(erro).__name__}: {erro}")
    tocou = handle.fechar(esperar=bool(total))
    if not total:
        return None
    return bool(tocou)


def _transcrever_audio(audio: sr.AudioData) -> str:
    try:
        import audio_preprocessing
        wav = audio_preprocessing.preprocess_audio(
            audio.get_raw_data(),
            sample_rate=audio.sample_rate,
            channels=1,
            sample_width=audio.sample_width,
            source="ptt",
        )
        if not wav:
            return ''
        buffer = io.BytesIO(wav)
        buffer.name = 'audio.wav'
        transcricao = _obter_cliente_groq().audio.transcriptions.create(
            file=buffer,
            model='whisper-large-v3-turbo',
            language='pt',
            prompt='Assistente pessoal Emily conversando com Vitor. Comandos comuns: abre, fecha, move, copia, pesquisa, mostra, analisa. Termos comuns: VS Code, Hollow Knight, Palworld, Python, GitHub, Chrome, Discord, pasta, arquivo, Desktop, Downloads, terminal, código, função, erro, print, loop, variável, zé ruela, paiosa, cara, para, namoral, mano, tá ligado, Dying Light, radiância, Nightmare Grimm, Área de trabalho, véi, Claude.',
        )
        return transcricao.text.strip()
    except Exception as e:
        print(f'[VOZ] Erro na transcrição: {e}')
        return ''


# Botões laterais (x1/x2) não existem no pynput do Linux. O botão do meio
# continua vindo do pynput, e o MB4/MB5 (PTT) passa a vir do evdev, que lê os
# eventos do kernel direto — sem root, desde que o usuário esteja no grupo
# `input` (sudo usermod -aG input $USER + relogar).
_BOTOES_MOUSE = {'middle': pynput_mouse.Button.middle}
# No Windows, pynput reconhece os dois botões laterais. Sem estes mapeamentos,
# o MB5 padrão chegava por engano em keyboard.wait('mb5').
if os.name == 'nt':
    _BOTOES_MOUSE.update({
        'mb4': pynput_mouse.Button.x1,
        'mb5': pynput_mouse.Button.x2,
    })

_EVDEV_BOTOES = {}
_aviso_evdev_dado: list = []  # imprime o aviso de permissão uma vez só
if os.name != 'nt':
    try:
        from evdev import ecodes as _ecodes_evdev
        # BTN_SIDE = botão de trás (x1/mb4); BTN_EXTRA = da frente (x2/mb5).
        _EVDEV_BOTOES = {
            'mb4': _ecodes_evdev.BTN_SIDE,
            'mb5': _ecodes_evdev.BTN_EXTRA,
        }
    except ImportError:
        print("[PTT] evdev não instalado — MB4/MB5 indisponíveis (pip install evdev)")


def _dispositivos_evdev(codigo: int | None = None, teclado: bool = False) -> list:
    """Abre dispositivos capazes de emitir a tecla/botão solicitado."""
    from evdev import InputDevice, list_devices, ecodes
    dispositivos = []
    for caminho in list_devices():
        try:
            dev = InputDevice(caminho)
        except (PermissionError, OSError):
            continue
        try:
            chaves = dev.capabilities(verbose=False).get(ecodes.EV_KEY, [])
            compativel = (codigo in chaves if codigo is not None else
                           any(1 <= c < ecodes.BTN_MOUSE or c >= 352 for c in chaves)) if teclado else (
                           codigo in chaves if codigo is not None else ecodes.BTN_MOUSE in chaves)
            if compativel:
                dispositivos.append(dev)
            else:
                dev.close()
        except Exception:
            dev.close()
    return dispositivos


def _mouses_evdev() -> list:
    return _dispositivos_evdev(teclado=False)


def _esperar_botao_evdev(codigo: int, cancelado=None, teclado: bool = False):
    """BLOQUEIA até o botão evdev ser pressionado. Devolve o dispositivo."""
    from evdev import ecodes
    from select import select
    mouses = _dispositivos_evdev(codigo, teclado=teclado)
    if not mouses:
        return None
    escolhido = None
    try:
        while True:
            if cancelado and cancelado():
                return None
            prontos, _, _ = select([d.fd for d in mouses], [], [], 0.1)
            for fd in prontos:
                dev = next(d for d in mouses if d.fd == fd)
                for evento in dev.read():
                    if (evento.type == ecodes.EV_KEY
                            and evento.code == codigo
                            and evento.value == 1):
                        escolhido = dev
                        return dev
    finally:
        # Mantém somente o mouse que iniciou a gravação; em troca de tecla
        # ou desconexão, fecha todos os descritores abertos.
        for d in mouses:
            if d is escolhido:
                continue
            try:
                d.close()
            except Exception:
                pass


def _botao_solto_evdev(dev, codigo: int) -> bool:
    """Consome os eventos do dispositivo; True quando o botão foi solto."""
    from evdev import ecodes
    from select import select
    prontos, _, _ = select([dev.fd], [], [], 0.02)
    if not prontos:
        return False
    for evento in dev.read():
        if evento.type == ecodes.EV_KEY and evento.code == codigo and evento.value == 0:
            return True
    return False


def _rotulo_tecla_fisica(nome: str) -> str:
    nome = str(nome or "").strip()
    nomes = {
        "space": "Espaço", "left alt": "Alt esquerdo", "right alt": "Alt direito",
        "left ctrl": "Ctrl esquerdo", "right ctrl": "Ctrl direito",
        "left shift": "Shift esquerdo", "right shift": "Shift direito",
        "left windows": "Windows esquerdo", "right windows": "Windows direito",
        "enter": "Enter", "tab": "Tab", "esc": "Esc", "escape": "Esc",
    }
    return nomes.get(nome.lower(), nome.upper() if len(nome) == 1 else nome.title())


def _nome_tecla_evdev(codigo: int) -> str:
    from evdev import ecodes
    chave = ecodes.KEY.get(codigo, f"KEY_{codigo}")
    if isinstance(chave, list):
        chave = chave[0]
    nomes = {
        "KEY_EQUAL": "= / +", "KEY_MINUS": "- / _",
        "KEY_KPPLUS": "Num +", "KEY_KPMINUS": "Num -",
        "KEY_KPASTERISK": "Num *", "KEY_KPSLASH": "Num /",
        "KEY_APOSTROPHE": "Acento / '", "KEY_GRAVE": "Crase / acento",
        "KEY_SEMICOLON": "; / :", "KEY_SLASH": "/ / ?",
        "KEY_BACKSLASH": "\\ / |", "KEY_LEFTBRACE": "[ / {",
        "KEY_RIGHTBRACE": "] / }", "KEY_COMMA": ", / <",
        "KEY_DOT": ". / >", "KEY_102ND": "< / >",
        "KEY_LEFTALT": "left alt", "KEY_RIGHTALT": "right alt",
        "KEY_LEFTCTRL": "left ctrl", "KEY_RIGHTCTRL": "right ctrl",
        "KEY_LEFTSHIFT": "left shift", "KEY_RIGHTSHIFT": "right shift",
        "KEY_LEFTMETA": "left windows", "KEY_RIGHTMETA": "right windows",
        "KEY_SPACE": "space", "KEY_ESC": "esc",
    }
    if chave in nomes:
        return nomes[chave]
    nome = chave.removeprefix("KEY_")
    if nome.startswith("KP"):
        return "Num " + nome[2:]
    return nome.replace("_", " ").lower()


def _codigo_legado_evdev(tecla: str) -> int | None:
    """Mantém atalhos salvos pela versão anterior operacionais no Fedora."""
    from evdev import ecodes
    especiais = {
        "space": "SPACE", "tab": "TAB", "enter": "ENTER",
        "backspace": "BACKSPACE", "delete": "DELETE", "insert": "INSERT",
        "home": "HOME", "end": "END", "pageup": "PAGEUP",
        "pagedown": "PAGEDOWN", "up": "UP", "down": "DOWN",
        "left": "LEFT", "right": "RIGHT",
    }
    nome = especiais.get(tecla, tecla.upper())
    return getattr(ecodes, f"KEY_{nome}", None)


def capturar_atalho_ptt(requisicao: str | None = None) -> dict:
    """Lê a próxima tecla/botão físico global e salva depois da soltura."""
    token = tecla_ptt.iniciar_captura(requisicao)
    if token is None:
        if tecla_ptt.requisicao_cancelada(requisicao):
            return {"ok": False, "cancelado": True}
        return {"ok": False, "erro": "A captura já está em andamento."}
    candidato = []
    solto = threading.Event()
    hook = None
    listener = None
    dispositivos = []
    modificadores = {"shift", "left shift", "right shift", "ctrl", "left ctrl", "right ctrl",
                    "alt", "left alt", "right alt", "alt gr", "windows", "left windows",
                    "right windows", "cmd", "command"}

    def tecla_evento(codigo, nome, tipo):
        if not isinstance(codigo, int) or codigo <= 0:
            return
        if tipo == "down" and (not candidato or
                (candidato[0][2] and str(nome).lower() not in modificadores)):
            entrada = (f"scan:{codigo}", _rotulo_tecla_fisica(nome),
                       str(nome).lower() in modificadores)
            if candidato:
                candidato[0] = entrada
            else:
                candidato.append(entrada)
        elif tipo == "up" and candidato and candidato[0][0] == f"scan:{codigo}":
            solto.set()

    def mouse_evento(_x, _y, botao, apertado):
        codigo = {pynput_mouse.Button.left: 272, pynput_mouse.Button.right: 273,
                  pynput_mouse.Button.middle: 274}
        if os.name == 'nt':
            codigo.update({pynput_mouse.Button.x1: 275, pynput_mouse.Button.x2: 276})
        numero = codigo.get(botao)
        if numero is None:
            return
        chave = f"mouse:{numero}"
        if apertado and not candidato:
            candidato.append((chave, tecla_ptt.rotulo(chave), False))
        elif not apertado and candidato and candidato[0][0] == chave:
            solto.set()

    try:
        if os.name == 'nt':
            hook = keyboard.hook(lambda e: tecla_evento(e.scan_code, e.name, e.event_type))
            listener = pynput_mouse.Listener(on_click=mouse_evento)
            listener.start()
        else:
            from evdev import ecodes
            from select import select
            dispositivos = _dispositivos_evdev(teclado=True) + _mouses_evdev()
            if not dispositivos:
                return {"ok": False, "erro": "Sem acesso aos dispositivos de teclado e mouse."}
        fim = time.monotonic() + 25
        while time.monotonic() < fim and not solto.is_set() and tecla_ptt.capturando(token):
            if dispositivos:
                prontos, _, _ = select([d.fd for d in dispositivos], [], [], 0.05)
                for fd in prontos:
                    dev = next(d for d in dispositivos if d.fd == fd)
                    for evento in dev.read():
                        if evento.type != ecodes.EV_KEY:
                            continue
                        if 1 <= evento.code < ecodes.BTN_MOUSE or evento.code >= 352:
                            tecla_evento(evento.code, _nome_tecla_evdev(evento.code),
                                         "down" if evento.value == 1 else "up" if evento.value == 0 else "repeat")
                            continue
                        if not 272 <= evento.code <= 279:
                            continue
                        chave = f"mouse:{evento.code}"
                        if evento.value == 1 and not candidato:
                            candidato.append((chave, tecla_ptt.rotulo(chave), False))
                        elif evento.value == 0 and candidato and candidato[0][0] == chave:
                            solto.set()
            else:
                solto.wait(0.05)
        if not tecla_ptt.capturando(token):
            return {"ok": False, "cancelado": True}
        if not solto.is_set():
            return {"ok": False, "erro": "Tempo esgotado. Pressione e solte uma tecla ou botão."}
        return tecla_ptt.definir_capturada(*candidato[0][:2])
    except (OSError, ImportError, ValueError) as exc:
        return {"ok": False, "erro": f"Captura indisponível: {exc}"}
    finally:
        if hook is not None:
            try:
                keyboard.unhook(hook)
            except (OSError, ValueError):
                pass
        if listener is not None:
            listener.stop()
        for dev in dispositivos:
            try:
                dev.close()
            except Exception:
                pass
        tecla_ptt.finalizar_captura(token)


def ouvir_ptt(tecla: str | None = None, callback_gravando=None) -> str:
    """
    Push-to-talk: BLOQUEIA esperando o botão, grava enquanto ele está
    apertado, e devolve a transcrição.

    Bloquear é de propósito. O rodar_emily() do main.py é um `while True`
    que chama isto e trata "" como "nada foi dito"; se a função voltasse
    logo, o laço giraria em vazio queimando CPU.

    No Linux, atalhos físicos e botões capturados vêm do evdev; no Windows,
    códigos físicos de teclado vêm do hook global da biblioteca keyboard.
    """
    while falar_ativo.is_set() or tecla_ptt.capturando():
        time.sleep(0.05)

    tecla_norm = tecla_ptt.normalizar(tecla) if tecla is not None else tecla_ptt.atual()
    if tecla_norm is None:
        return ""
    mudou = lambda: tecla_ptt.capturando() or (tecla is None and tecla_ptt.atual() != tecla_norm)
    codigo_evdev = _EVDEV_BOTOES.get(tecla_norm)
    if os.name != 'nt' and tecla_norm.startswith('mouse:'):
        codigo_evdev = int(tecla_norm.split(':', 1)[1])
    codigo_tecla_evdev = None
    if os.name != 'nt' and tecla_norm not in ('mb4', 'mb5', 'middle') and not tecla_norm.startswith('mouse:'):
        codigo_tecla_evdev = (int(tecla_norm.split(':', 1)[1]) if tecla_norm.startswith('scan:')
                               else _codigo_legado_evdev(tecla_norm))
    if os.name == 'nt' and tecla_norm.startswith('mouse:'):
        botao_mouse = {
            '272': pynput_mouse.Button.left,
            '273': pynput_mouse.Button.right,
            '274': pynput_mouse.Button.middle,
            '275': pynput_mouse.Button.x1,
            '276': pynput_mouse.Button.x2,
        }.get(tecla_norm.split(':', 1)[1])
    else:
        botao_mouse = _BOTOES_MOUSE.get(tecla_norm)
    eh_mouse = botao_mouse is not None
    tecla_escuta = int(tecla_norm.split(':', 1)[1]) if tecla_norm.startswith('scan:') else tecla_norm

    if tecla_norm in ('mb4', 'mb5') and codigo_evdev is None and not eh_mouse:
        print(f"[PTT] Botão {tecla_norm} indisponível neste sistema.")
        for _ in range(300):
            if mudou():
                return ""
            time.sleep(0.1)
        return ""
    if codigo_evdev is None and codigo_tecla_evdev is None and not eh_mouse and getattr(keyboard, '_escuta_ok', True) is False:
        print(f"[PTT] Escuta global da tecla {tecla_norm} indisponível.")
        for _ in range(300):
            if mudou():
                return ""
            time.sleep(0.1)
        return ""

    dispositivo = None
    listener = None
    pressionado = threading.Event()
    solto = threading.Event()

    # ── Espera o botão/tecla ser pressionado ──
    if codigo_evdev is not None or codigo_tecla_evdev is not None:
        codigo_alvo = codigo_evdev if codigo_evdev is not None else codigo_tecla_evdev
        print(f"[PTT] Aguardando {tecla_norm} (evdev)...")
        try:
            dispositivo = _esperar_botao_evdev(
                codigo_alvo, cancelado=mudou, teclado=codigo_tecla_evdev is not None)
        except OSError as exc:
            print(f"[PTT] Dispositivo indisponível: {exc}")
            time.sleep(0.3)
            return ""
        if mudou():
            if dispositivo is not None:
                dispositivo.close()
            return ""
        if dispositivo is None:
            if not _aviso_evdev_dado:
                _aviso_evdev_dado.append(True)
                print("[PTT] Sem acesso aos dispositivos de entrada (evdev).")
                print("[PTT] Corrige com: sudo usermod -aG input $USER (depois relogue)")
                print("[PTT] Enquanto isso, o PTT fica pausado — o chat digitado funciona normalmente.")
            for _ in range(300):
                if mudou():
                    return ""
                time.sleep(0.1)  # espaça tentativas sem atrasar troca de tecla
            return ""
        pressionado.set()
    elif eh_mouse:
        botao_alvo = botao_mouse

        def ao_clicar(x, y, botao, apertado):
            if botao == botao_alvo:
                if apertado:
                    pressionado.set()
                else:
                    solto.set()

        try:
            listener = pynput_mouse.Listener(on_click=ao_clicar)
            listener.start()
        except OSError as exc:
            print(f"[PTT] Escuta do mouse indisponível: {exc}")
            return ""

        print(f"[PTT] Aguardando botão {tecla_norm}...")
        while not pressionado.wait(timeout=0.1):
            if mudou():
                listener.stop()
                return ""
    else:
        print(f"[PTT] Aguardando tecla {tecla_norm}...")
        # Exige soltura antes de armar: salvar a nova tecla na própria janela
        # não deve iniciar uma gravação com o keydown daquele clique.
        try:
            while keyboard.is_pressed(tecla_escuta):
                if mudou():
                    return ""
                time.sleep(0.03)
            while not keyboard.is_pressed(tecla_escuta):
                if mudou():
                    return ""
                time.sleep(0.03)
        except (OSError, ValueError) as exc:
            print(f"[PTT] Tecla {tecla_norm} indisponível: {exc}")
            time.sleep(0.3)
            return ""

    # Uma fala espontânea pode ter começado ENQUANTO esta função estava
    # bloqueada esperando o MB5. A checagem do início (linha 1253) não cobre
    # essa corrida. Não abra o microfone por cima da própria Emily: descarte
    # este pressionamento e exija soltar/apertar de novo depois da fala.
    if falar_ativo.is_set():
        print("[PTT] Pressionamento ignorado: Emily começou a falar.")
        if listener:
            listener.stop()
        if dispositivo:
            try:
                dispositivo.close()
            except Exception:
                pass
        return ""

    frames = []
    stream = None
    try:
        if callback_gravando:
            callback_gravando()
        escutando_ativo.set()
        print("[PTT] Gravando...")
        stream = _pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=TAXA_AUDIO,
            input=True,
            frames_per_buffer=CHUNK_AUDIO
        )
        if codigo_evdev is not None or codigo_tecla_evdev is not None:
            while not _botao_solto_evdev(dispositivo, codigo_alvo):
                if mudou():
                    return ""
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
        elif eh_mouse:
            while not solto.is_set():
                if mudou():
                    return ""
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
        else:
            while keyboard.is_pressed(tecla_escuta):
                if mudou():
                    return ""
                data = stream.read(CHUNK_AUDIO, exception_on_overflow=False)
                frames.append(data)
    except OSError as exc:
        print(f"[PTT] Áudio ou dispositivo de entrada indisponível: {exc}")
        time.sleep(0.3)
        return ""
    finally:
        try:
            if stream is not None:
                try:
                    stream.stop_stream()
                finally:
                    stream.close()
        finally:
            escutando_ativo.clear()
            if listener:
                listener.stop()
            if dispositivo:
                try:
                    dispositivo.close()
                except Exception:
                    pass

    if len(frames) < 5:
        print("[PTT] Gravação muito curta, ignorando...")
        return ""

    raw_data = b"".join(frames)
    audio = sr.AudioData(raw_data, TAXA_AUDIO, 2)
    texto = _transcrever_audio(audio)
    if texto:
        print(f"[PTT] Você disse: {texto}")
    return texto


def _calar_emily():
    if falar_ativo.is_set():
        parar_fala.set()
        falar_ativo.clear()
        print('[VOZ] Emily calada!')


def gerar_audio_bytes(texto: str, para_call: bool = False) -> bytes:
    """Expõe a geração de áudio em bytes pro discord_bot usar na call."""
    return _gerar_audio_bytes(texto, para_call=para_call)


def gerar_audio_pacote(texto: str, para_call: bool = False):
    """Expõe PCM + formato usando uma sessão própria da thread atual."""
    return _gerar_audio_pacote(
        texto, _sessao_fish_da_thread(), para_call=para_call)


def segmentar_para_tts(texto: str, preservar_entonacao: bool = False) -> list[str]:
    """Divide texto pronto em unidades naturais iguais às usadas no chat/voz."""
    from modelo import (_AcumuladorDeFrases, eh_tag_fish,
                        tag_fish_persistente)

    fila = queue.Queue()
    acumulador = _AcumuladorDeFrases(fila)
    acumulador.adicionar(texto or "")
    acumulador.finalizar()
    partes = []
    while not fila.empty():
        parte = fila.get_nowait()
        if parte and parte.strip():
            partes.append(parte.strip())
    if not preservar_entonacao or len(partes) < 2:
        return partes

    # Cada segmento vira uma requisição Fish independente. Uma tag de tom no
    # primeiro request não existe no segundo, então carregamos o último tom
    # persistente adiante. Eventos pontuais como [pause]/[laughs] não repetem.
    saida = []
    ativa = ""
    for parte in partes:
        tags = re.findall(r"\[([^\]\r\n]{1,80})\]", parte)
        primeira = tags[0].strip() if tags else ""
        com_tom = parte
        if ativa and not (primeira and tag_fish_persistente(primeira)
                          and parte.lstrip().startswith(f"[{primeira}]")):
            com_tom = f"[{ativa}] {parte}"
        saida.append(com_tom)
        for tag in tags:
            if eh_tag_fish(tag) and tag_fish_persistente(tag):
                ativa = tag.strip()
    return saida


try:
    if os.getenv("EMILY_RUNTIME_CLOUD") != "1":
        keyboard.add_hotkey(TECLA_CALAR, _calar_emily)
except (ImportError, OSError, PermissionError) as e:
    # No Linux sem acesso a /dev/input (testes, container, sessão sem root), o
    # pacote keyboard lança durante o import. A voz continua funcional; perde-se
    # apenas o atalho global de interrupção.
    print(f"[VOZ] Atalho global de calar indisponível: {e}")
