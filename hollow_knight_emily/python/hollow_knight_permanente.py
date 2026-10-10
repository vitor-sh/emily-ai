"""Backend leve da ponte de Hollow Knight para o serviço permanente.

Não importa ``modelo.py`` nem ``voz.py``: esses módulos inicializam a aplicação
desktop, dispositivos de áudio e várias integrações. Aqui o gateway fala
diretamente com a conexão OpenAI configurada e a API REST da FishAudio usando
apenas o ``.env`` principal, portanto funciona com a interface fechada.
"""

from __future__ import annotations

import json
import io
import re
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Callable

import requests

from .hollow_knight_cerebro import CerebroHollowKnight, SYSTEM_HOLLOW_KNIGHT


Cfg = Callable[[str, str], str]


def _modelo_padrao(cfg: Cfg) -> str:
    modelos = _lista_modelos(cfg)
    luna = next((modelo for modelo in modelos if modelo.lower().endswith("gpt-5.6-luna")), "")
    return luna or cfg("EMILY_PROVEDOR_OPENAI_MODELO", "").strip() or (modelos[0] if modelos else "")


def _lista_modelos(cfg: Cfg) -> list[str]:
    modelos = [
        item.strip()
        for item in cfg("EMILY_PROVEDOR_OPENAI_MODELOS", "").split(",")
        if item.strip()
    ]
    padrao = cfg("EMILY_PROVEDOR_OPENAI_MODELO", "").strip()
    if padrao and padrao not in modelos:
        modelos.insert(0, padrao)
    return list(dict.fromkeys(modelos))


def normalizador_modelo(cfg: Cfg) -> Callable[[object], str]:
    def normalizar(valor: object) -> str:
        pedido = str(valor or "").strip()
        return pedido if pedido and pedido in set(_lista_modelos(cfg)) else ""

    return normalizar


def gravador_catalogo(cfg: Cfg) -> Callable[..., dict]:
    def gravar(*destinos: Path) -> dict:
        modelos = _lista_modelos(cfg)
        catalogo = {
            "provedor": "openai",
            "nome_provedor": cfg("EMILY_PROVEDOR_OPENAI_NOME", "OpenAI"),
            "padrao": _modelo_padrao(cfg),
            "modelos": [
                {"id": modelo, "nome": _rotulo_modelo(modelo)} for modelo in modelos
            ],
        }
        conteudo = json.dumps(catalogo, ensure_ascii=False, indent=2) + "\n"
        for destino in destinos:
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(conteudo, encoding="utf-8")
            except OSError as erro:
                print(f"[HOLLOW-KNIGHT-PERMANENTE] catálogo não gravado em {destino}: {erro}")
        return catalogo

    return gravar


def _rotulo_modelo(modelo_id: str) -> str:
    texto = modelo_id.strip().split("/", 1)[-1].replace("-", " ")
    texto = re.sub(r"(\d)\s(\d)", r"\1.\2", texto)
    mapa = {
        "claude": "Claude", "sonnet": "Sonnet", "haiku": "Haiku",
        "opus": "Opus", "gpt": "GPT", "terra": "Terra", "luna": "Luna",
        "sol": "Sol",
    }
    return " ".join(
        mapa.get(parte.lower(), parte[:1].upper() + parte[1:])
        for parte in texto.split()
    ) or modelo_id


class SaudeOmniRoute:
    """Verifica o upstream com cache para não martelar ``/models``."""

    def __init__(self, cfg: Cfg, sessao: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._sessao = sessao or requests.Session()
        self._lock = threading.Lock()
        self._quando = 0.0
        self._valor = False

    def pronto(self, forcar: bool = False) -> bool:
        agora = time.monotonic()
        with self._lock:
            ttl_padrao = "8" if self._valor else "2"
            ttl = max(0.5, float(self._cfg("EMILY_HK_SAUDE_TTL", ttl_padrao)))
            if not forcar and agora - self._quando < ttl:
                return self._valor
        base = self._cfg("EMILY_PROVEDOR_OPENAI_BASE", "").rstrip("/")
        chave = self._cfg("EMILY_PROVEDOR_OPENAI_CHAVE", "")
        valor = False
        if base and chave:
            try:
                resposta = self._sessao.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {chave}"},
                    # A DLL usa teto total de 8s. Reserva margem para serializar
                    # a resposta mesmo quando /models paga o aquecimento inicial.
                    timeout=(1.5, 5.5),
                )
                # Alguns upstreams OpenAI-compatible implementam chat/completions
                # mas não expõem GET /models (404). Não derrubar todas as sessões
                # por uma rota opcional; erro real da geração segue observável.
                valor = resposta.ok or resposta.status_code == 404
            except requests.RequestException:
                valor = False
        with self._lock:
            self._quando = agora
            self._valor = valor
        return valor

    def invalidar(self) -> None:
        with self._lock:
            self._quando = 0.0
            self._valor = False


class CerebroHollowKnightPermanente:
    def __init__(
        self,
        cfg: Cfg,
        saude: SaudeOmniRoute,
        sessao: requests.Session | None = None,
        *,
        memoria=None,
    ) -> None:
        self._cfg = cfg
        self._saude = saude
        self._memoria = memoria
        self._sessao = sessao or requests.Session()
        self._historico = {}

    def responder(self, evento, sessao, *, proibir_estatisticas: bool = False) -> dict:
        historico = self._historico.setdefault(
            getattr(sessao, "id", sessao.campanha_id), deque(maxlen=18))
        recentes = "\n".join(f"- {x}" for x in list(historico)[-8:]) or "nenhuma"
        contexto = {
            "evento": evento.tipo,
            "dados": CerebroHollowKnight._dados_para_ia(evento.tipo, evento.dados),
            "cena": evento.cena_id,
            "campanha": sessao.campanha_id,
            "localizacao_atual": {
                "zona": str(sessao.estado.get("zona") or ""),
                "nome": str(sessao.estado.get("zona_nome") or ""),
                "cena": str(sessao.estado.get("cena_atual") or evento.cena_id or ""),
            },
            "estado_atual": CerebroHollowKnight._estado_para_ia(sessao.estado),
            "falas_recentes": recentes,
        }
        if self._memoria is not None:
            contexto["memoria_da_campanha"] = self._memoria.contexto(
                sessao.campanha_id,
                evento,
                str(sessao.estado.get("modo_fala") or "normal"),
            )
        modelo = str(sessao.estado.get("modelo") or "").strip()
        permitidos = _lista_modelos(self._cfg)
        if not modelo or modelo not in permitidos:
            modelo = _modelo_padrao(self._cfg)
        base = self._cfg("EMILY_PROVEDOR_OPENAI_BASE", "").rstrip("/")
        chave = self._cfg("EMILY_PROVEDOR_OPENAI_CHAVE", "")
        if not base or not chave or not modelo:
            raise RuntimeError("OpenAI não configurada para Hollow Knight no .env")
        try:
            resposta = self._sessao.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {chave}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": modelo,
                    "messages": [
                        {"role": "system", "content": SYSTEM_HOLLOW_KNIGHT + (
                            "\nNão inclua números nem enumere atributos; comente a situação concreta."
                            if proibir_estatisticas else "")},
                        {
                            "role": "user",
                            "content": json.dumps(
                                contexto, ensure_ascii=False, default=str
                            ),
                        },
                    ],
                    "max_tokens": 520,
                    "reasoning_effort": "low",
                    "stream": False,
                },
                timeout=(5.0, float(self._cfg("EMILY_HK_LLM_TIMEOUT", "90"))),
            )
            resposta.raise_for_status()
            corpo = resposta.json()
        except (requests.RequestException, ValueError) as erro:
            self._saude.invalidar()
            raise RuntimeError(f"OpenAI indisponível: {type(erro).__name__}") from erro
        bruto = str(
            (((corpo.get("choices") or [{}])[0].get("message") or {}).get("content"))
            or ""
        )
        dados = self._extrair_json(bruto)
        texto = str(dados.get("texto") or "").strip()
        if not dados.get("falar", bool(texto)) or not texto:
            return {
                "falar": False, "texto": "", "emocao": "neutra",
                "acao": "nenhuma",
            }
        dados["texto"] = texto[:2000]
        dados["emocao"] = str(dados.get("emocao") or "neutra").lower()
        dados["acao"] = str(dados.get("acao") or "nenhuma").lower()
        historico.append(dados["texto"])
        return dados

    @staticmethod
    def _extrair_json(texto: str) -> dict:
        limpo = texto.strip().removeprefix("```json").removeprefix("```")
        limpo = limpo.removesuffix("```").strip()
        try:
            valor = json.loads(limpo)
            return valor if isinstance(valor, dict) else {}
        except json.JSONDecodeError:
            achado = re.search(r"\{.*\}", limpo, re.S)
            if not achado:
                return {}
            try:
                valor = json.loads(achado.group(0))
                return valor if isinstance(valor, dict) else {}
            except json.JSONDecodeError:
                return {}


class FishAudioDireto:
    """TTS REST oficial, sem abrir dispositivo de áudio no processo systemd."""

    def __init__(self, cfg: Cfg, sessao: requests.Session | None = None) -> None:
        self._cfg = cfg
        self._sessao = sessao or requests.Session()

    def gerar_wav(self, texto: str) -> bytes:
        texto = _limpar_para_tts(texto)
        chave = self._cfg("FISH_AUDIO_KEY", "")
        if not texto or not chave:
            return b""
        base = self._cfg("EMILY_FISH_BASE_URL", "https://api.fish.audio").rstrip("/")
        voz = self._cfg(
            "EMILY_FISH_VOICE_ID", "1d5c6866f45a44a3aa8df65061908ab2"
        )
        modelo = self._cfg("EMILY_FISH_MODELO_TTS", "s2.1-pro-free")
        tentativas = max(1, int(self._cfg("EMILY_TTS_TENTATIVAS", "2")))
        ultimo_erro: Exception | None = None
        for tentativa in range(1, tentativas + 1):
            try:
                resposta = self._sessao.post(
                    f"{base}/v1/tts",
                    headers={
                        "Authorization": f"Bearer {chave}",
                        "Content-Type": "application/json",
                        "model": modelo,
                    },
                    json={
                        "text": texto,
                        "reference_id": voz,
                        "format": "wav",
                        "sample_rate": 44100,
                        "latency": "balanced",
                        "temperature": 0.7,
                        "top_p": 0.7,
                    },
                    timeout=(
                        float(self._cfg("EMILY_TTS_TIMEOUT_CONEXAO", "6")),
                        float(self._cfg("EMILY_TTS_TIMEOUT_LEITURA", "30")),
                    ),
                )
                resposta.raise_for_status()
                wav = resposta.content
                if len(wav) <= 44 or not wav.startswith(b"RIFF") or wav[8:12] != b"WAVE":
                    raise ValueError("FishAudio não retornou WAV válido")
                return _normalizar_wav_streaming(wav)
            except (requests.RequestException, ValueError) as erro:
                ultimo_erro = erro
                if tentativa < tentativas:
                    time.sleep(max(0.0, float(self._cfg("EMILY_TTS_PAUSA_RETRY", "0.8"))))
        print(
            "[HOLLOW-KNIGHT-PERMANENTE] FishAudio indisponível: "
            f"{type(ultimo_erro).__name__}: {ultimo_erro}"
        )
        return b""

    def gerar_pcm_stream(self, texto: str):
        """Entrega PCM s16le incremental sem importar o desktop da Emily.

        Repete a chamada apenas se ela falhar antes do primeiro byte. Depois que
        o Unity já começou a tocar, repetir a requisição faria o começo da frase
        sair duas vezes.
        """
        texto = _limpar_para_tts(texto)
        chave = self._cfg("FISH_AUDIO_KEY", "")
        if not texto or not chave:
            return
        base = self._cfg(
            "EMILY_FISH_BASE_URL", "https://api.fish.audio").rstrip("/")
        voz = self._cfg(
            "EMILY_FISH_VOICE_ID", "1d5c6866f45a44a3aa8df65061908ab2")
        modelo = self._cfg("EMILY_FISH_MODELO_TTS", "s2.1-pro-free")
        tentativas = max(1, int(self._cfg("EMILY_TTS_TENTATIVAS", "2")))
        ultimo_erro: Exception | None = None
        for tentativa in range(1, tentativas + 1):
            entregou = False
            resposta = None
            try:
                resposta = self._sessao.post(
                    f"{base}/v1/tts",
                    headers={
                        "Authorization": f"Bearer {chave}",
                        "Content-Type": "application/json",
                        "model": modelo,
                    },
                    json={
                        "text": texto,
                        "reference_id": voz,
                        "format": "pcm",
                        "sample_rate": 44100,
                        "latency": "balanced",
                        "chunk_length": 100,
                        "temperature": 0.7,
                        "top_p": 0.7,
                    },
                    stream=True,
                    timeout=(
                        float(self._cfg("EMILY_TTS_TIMEOUT_CONEXAO", "6")),
                        float(self._cfg("EMILY_TTS_TIMEOUT_LEITURA", "30")),
                    ),
                )
                resposta.raise_for_status()
                for pedaco in resposta.iter_content(chunk_size=8192):
                    if not pedaco:
                        continue
                    entregou = True
                    yield pedaco
                if entregou:
                    return
                raise ValueError("FishAudio encerrou sem retornar PCM")
            except (requests.RequestException, ValueError) as erro:
                ultimo_erro = erro
                if entregou:
                    print(
                        "[HOLLOW-KNIGHT-PERMANENTE] stream FishAudio "
                        f"interrompido: {type(erro).__name__}: {erro}"
                    )
                    return
                if tentativa < tentativas:
                    time.sleep(max(0.0, float(self._cfg(
                        "EMILY_TTS_PAUSA_RETRY", "0.8"))))
            finally:
                if resposta is not None:
                    try:
                        resposta.close()
                    except (AttributeError, requests.RequestException):
                        pass
        print(
            "[HOLLOW-KNIGHT-PERMANENTE] FishAudio PCM indisponível: "
            f"{type(ultimo_erro).__name__}: {ultimo_erro}"
        )


def _limpar_para_tts(texto: str) -> str:
    texto = str(texto or "").strip()
    texto = re.sub(r"```.*?```", " ", texto, flags=re.S)
    texto = re.sub(r"[*_~`#>]", "", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto[:420].strip()


def _normalizar_wav_streaming(conteudo: bytes) -> bytes:
    """Regrava o WAV da Fish com os tamanhos reais no cabeçalho.

    A resposta HTTP pode usar um tamanho sentinela no chunk ``data`` porque é
    produzida como stream. ``wave.readframes`` lê até o EOF corretamente, mas o
    Unity/WavLib pode confiar no número anunciado e interpretar horas de áudio.
    Reempacotar evita isso sem recodificar nem alterar as amostras.
    """
    try:
        with wave.open(io.BytesIO(conteudo), "rb") as origem:
            canais = origem.getnchannels()
            largura = origem.getsampwidth()
            taxa = origem.getframerate()
            pcm = origem.readframes(origem.getnframes())
    except (EOFError, wave.Error) as erro:
        raise ValueError(f"WAV FishAudio inválido: {erro}") from erro
    if not pcm or canais <= 0 or largura <= 0 or taxa <= 0:
        raise ValueError("WAV FishAudio sem amostras válidas")
    saida = io.BytesIO()
    with wave.open(saida, "wb") as destino:
        destino.setnchannels(canais)
        destino.setsampwidth(largura)
        destino.setframerate(taxa)
        destino.writeframes(pcm)
    return saida.getvalue()
