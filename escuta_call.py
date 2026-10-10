"""
escuta_call.py — a Emily ouvindo a call e entendendo quem disse o quê.

O QUE ESTE ARQUIVO RESOLVE
──────────────────────────
Transformar um fluxo contínuo de pacotes UDP de seis pessoas ao mesmo tempo em
frases atribuídas a cada uma. Só isso. Ele não decide nada e não responde nada —
quem faz isso é o resto_call.py, que se pendura aqui como observador.

A separação existe porque as duas coisas quebram de formas diferentes: aqui os
problemas são de áudio (pacote perdido, turno cortado, silêncio virando texto), e
lá são de conversa (responder na hora errada, responder a si mesma). Misturar
faria cada bug parecer o outro.

A DIVISÃO DE TRABALHO ENTRE DISCORD E SILERO VAD
────────────────────────────────────────────────
O cliente do Discord continua sendo a fonte para descobrir quando um TURNO começa
e termina: a presença dos pacotes e a lacuna de ~700 ms são mais adequadas a isso
do que rodar um detector na thread de rede.

O Silero VAD entra depois que o turno já foi fechado, no módulo compartilhado de
pré-processamento. A função dele não é remontar a conversa: é cortar silêncio
residual dentro do trecho e impedir que ruído sem fala chegue ao Whisper. Assim o
sink segue barato (~50 chamadas/s por pessoa), e o trabalho de CPU fica nos workers.

Passou de ~700 ms sem pacote daquela pessoa? O turno de fala acabou. Depois dele,
RNNoise, loudnorm e Silero são aplicados antes do upload ao Groq.

Sobra um filtro de energia (RMS) por cima, e esse não é redundante: serve pra
descartar o clique de teclado e o "ãh" de 200 ms que o Discord transmite mas não
vale mandar pra transcrição.

POR QUE TRANSCREVER TUDO É BARATO E ISSO MUDA O PROJETO
──────────────────────────────────────────────────────
A intuição de que "seis pessoas é informação demais" vale pra LLM e não vale pra
transcrição. O Groq roda whisper-large-v3-turbo a mais de 160x tempo real por
cerca de US$ 0,04 a hora de áudio. Uma call de duas horas com seis pessoas tem
perto de uma hora de fala real: alguns centavos.

Então ela ouve tudo. O pré-processamento leve fica antes do Whisper; já a decisão
cara de responder ou ignorar continua DEPOIS da transcrição, com a frase inteira
na mão, em vez de tentar inferir intenção por 300 ms de espectrograma.

O efeito colateral é o melhor pedaço: quando ela responde, responde sabendo do que
a call estava falando, e não só a frase que a chamou.

O CUIDADO COM O MÍNIMO DE 10 SEGUNDOS
─────────────────────────────────────
O Groq cobra no mínimo 10 segundos por requisição. Um turno de 1 segundo custa
como 10. Isso não muda a arquitetura (o total continua irrisório), mas é a razão de
existir um piso de duração: mandar dezenas de fragmentos de 300 ms seria pagar
dezenas de vezes por nada.
"""

from __future__ import annotations

import io
import os
import queue
import re
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional

from dotenv import load_dotenv

# A chave do Groq vive no .env. Sem esta linha o módulo funcionava sozinho no
# diagnóstico e reportava "chave ausente" mesmo com ela configurada — porque quem
# carregava o .env era só quem importava o enxada ou o llm antes.
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── audioop e o Python 3.13 ──────────────────────────────────────
#
# O `audioop` faz conversão de PCM em C e é perfeito pro que precisamos, mas foi
# removido no Python 3.13. Como este projeto vai rodar por anos, o fallback em
# numpy existe pra o dia da atualização não virar uma manhã de depuração.
#
# O caminho do audioop continua sendo o preferido enquanto existir: é mais rápido
# e já está testado em produção aqui.
try:
    import audioop as _ap

    def _para_mono(pcm: bytes) -> bytes:
        return _ap.tomono(pcm, LARGURA, 0.5, 0.5)

    def _reamostrar(pcm: bytes, de: int, para: int) -> bytes:
        convertido, _ = _ap.ratecv(pcm, LARGURA, 1, de, para, None)
        return convertido

    def _energia(pcm: bytes) -> int:
        try:
            return _ap.rms(pcm, LARGURA)
        except Exception:
            return 0

    _MOTOR_AUDIO = "audioop"
except ImportError:  # pragma: no cover - só no 3.13+
    import numpy as _np

    def _para_mono(pcm: bytes) -> bytes:
        amostras = _np.frombuffer(pcm, dtype=_np.int16)
        if amostras.size % 2:
            amostras = amostras[:-1]
        pares = amostras.reshape(-1, 2).astype(_np.int32)
        return pares.mean(axis=1).astype(_np.int16).tobytes()

    def _reamostrar(pcm: bytes, de: int, para: int) -> bytes:
        amostras = _np.frombuffer(pcm, dtype=_np.int16)
        if amostras.size == 0:
            return b""
        quantas = int(amostras.size * para / de)
        indices = _np.linspace(0, amostras.size - 1, quantas)
        return _np.interp(indices, _np.arange(amostras.size),
                          amostras).astype(_np.int16).tobytes()

    def _energia(pcm: bytes) -> int:
        amostras = _np.frombuffer(pcm, dtype=_np.int16)
        if amostras.size == 0:
            return 0
        return int(_np.sqrt(_np.mean(amostras.astype(_np.float64) ** 2)))

    _MOTOR_AUDIO = "numpy"

# Mestre. Com 0 ela volta a só falar na call, sem ouvir.
ATIVO = os.getenv("EMILY_ESCUTA_CALL", "1").strip() != "0"

# ── formato que o Discord entrega ────────────────────────────────
TAXA_DISCORD = 48000
CANAIS_DISCORD = 2
LARGURA = 2

# ── formato que mandamos pra transcrição ─────────────────────────
#
# 16 kHz mono é o que o Whisper usa internamente. Converter aqui corta o tamanho
# do upload por seis sem perder nada de qualidade — o modelo faria essa mesma
# redução do outro lado.
TAXA_ENVIO = 16000

# Silêncio que fecha um turno de fala.
#
# 700 ms é o meio que funciona: abaixo de ~500 ela corta frase no meio de uma
# pausa pra respirar, acima de ~1000 duas falas separadas viram uma só e a
# resposta atrasa.
GAP_MS = int(os.getenv("EMILY_CALL_GAP_MS", "700"))

# Turno menor que isso não vai pra transcrição: é clique, tosse ou "ãh".
MIN_MS = int(os.getenv("EMILY_CALL_MIN_MS", "400"))

# Turno maior que isso é fechado à força, mesmo a pessoa continuando a falar.
# Sem esse teto, alguém contando uma história de cinco minutos só seria
# transcrito no fim dela.
MAX_MS = int(os.getenv("EMILY_CALL_MAX_MS", "25000"))

# Energia média mínima pra valer transcrição. Descarta ruído de fundo que o
# Discord transmite quando o limiar dele é generoso.
RMS_MINIMO = int(os.getenv("EMILY_CALL_RMS", "220"))

# Com só dois workers, uma requisição lenta do Whisper segura as falas que
# chegaram depois, mesmo que sejam de outra pessoa chamando a Emily. Quatro
# permitem absorver rajadas de uma call movimentada sem alterar a escuta, o
# áudio, o contexto nem a janela de resposta. Configurável para contas com
# limites de requisição menores.
TRABALHADORES = int(os.getenv("EMILY_CALL_WORKERS", "4"))

# Tamanho da janela guardada em memória. Guardar mais não aumenta o prompt
# automaticamente: resto_call escolhe apenas a fatia recente necessária.
JANELA_TURNOS = max(20, int(os.getenv("EMILY_CALL_JANELA_TURNOS", "80")))

# ═════════════════════════════════════════════════════════════════
# A DICA DE VOCABULÁRIO — E POR QUE O FORMATO DELA IMPORTA TANTO
#
# O prompt do Whisper não é instrução, é VIÉS DE DECODIFICAÇÃO: ele entra como
# se fosse texto que veio antes do áudio, e o modelo continua de onde parou. A
# consequência é que, quando o áudio não dá pra entender, o decodificador
# continua a coisa mais previsível que tem à mão — o próprio prompt.
#
# A versão anterior desta constante era uma LISTA:
#
#     "Nomes: Emily, Vitor, Comuna, Ryan, HaoQin. Termos: servidor, modpack..."
#
# Lista é o pior formato possível pra isso, porque a continuação mais provável
# de "Nomes: Emily, Vitor," é "Comuna, Ryan, HaoQin". E foi exatamente o que
# apareceu no terminal, num momento em que o Vitor não tinha falado nada
# parecido:
#
#     [CALL] hiucksam: Nomes, Vitor, Comuna, Ryan, HaoQin.
#
# Não era alucinação genérica do Whisper: era esta constante voltando.
#
# A versão de agora é PROSA, escrita no formato do que se espera ouvir numa call
# desse grupo. Os nomes continuam presentes (sem eles "HaoQin" nunca sai certo),
# mas embutidos em fala natural, que não tem continuação óbvia. E como formato
# nenhum é garantia, existe uma segunda defesa que não depende disso: o
# _e_eco_da_dica, que compara o resultado com este texto e descarta cópia.
# ═════════════════════════════════════════════════════════════════

# A LISTA DE NOMES SAIU, E NÃO VOLTA
# ───────────────────────────────────
# A primeira tentativa de conserto foi manter os nomes, só reescrevendo em prosa:
#
#     "Fala Vitor, o servidor tá on? O Comuna e o Ryan já entraram no modpack..."
#
# Isso trocou um defeito por outro, pior. Escrito assim, o texto da dica passou a
# conter as frases que as pessoas de fato dizem na call — "o servidor tá on?" é
# provavelmente a mais comum de todas — e o detector de eco começou a acusar fala
# REAL de ser cópia da dica. Medido: "emily o servidor tá on?" foi descartado.
#
# Não existe boa saída aí. Pra ajudar na transcrição, a dica precisa parecer com
# o que se fala; pra ser distinguível de fala real, ela precisa NÃO parecer.
#
# Então a dica virou uma frase meta, que ninguém diz em voz alta, e os nomes
# próprios saíram. O que se perde é pequeno: nome de amigo transcrito errado não
# quebra nada, porque o único nome que o programa precisa reconhecer é o dela — e
# esse é tratado no lugar certo, no resto_call._VARIANTES, que lida com as 18
# formas de o Whisper escrever "Emily" em vez de tentar impedir que ele erre.
#
# Quem quiser tentar de novo com vocabulário próprio pode, por EMILY_CALL_DICA;
# o _e_eco_da_dica continua sendo a rede embaixo.
# E NO FIM A DICA FICOU VAZIA
# ───────────────────────────
# Sem os nomes, o que sobrava era "conversa informal em português do Brasil" — e
# isso o parâmetro language="pt" já faz, sem risco nenhum. A dica passou a ser
# custo sem benefício, e o custo foi observado duas vezes numa call real:
#
#   descartei transcrição (é cópia da dica): "Transcrição de uma conversa
#       informal em português do Brasil, numa call"
#   descartei transcrição (é cópia da dica): "Se você quiser, você pode fazer
#       uma conversa informal em português do"
#
# O detector pegou as duas, então nada de errado saiu — mas cada uma dessas é uma
# fala real que foi perdida, porque o Whisper gastou aquele trecho de áudio
# repetindo o prompt em vez de transcrever.
#
# Vazia por padrão. Quem quiser vocabulário próprio põe em EMILY_CALL_DICA, e o
# _e_eco_da_dica continua de pé como rede.
DICA_TRANSCRICAO = os.getenv("EMILY_CALL_DICA", "")

# Abaixo desta confiança média do Whisper, o texto é descartado. Medido com
# áudio real da call do Vitor:
#
#   fala de verdade ("Emily, tá me ouvindo? Alô?")  ->  -0.24
#   ruído de linha puro (virou " Conexão.")         ->  -0.92
#
# O corte fica no meio, mais perto do ruído, porque errar pra cada lado custa
# coisas diferentes: descartar fala real é ela te ignorar uma vez e você
# repetir; aceitar ruído é ela responder a ninguém, que é o que incomoda.
#
# no_speech_prob NÃO é usado, e a medição é a razão: veio 0 tanto na fala real
# quanto no ruído puro. Não discrimina nada neste caminho.
# CALIBRAGEM CORRIGIDA COM DADOS DE CALL REAL
# ───────────────────────────────────────────
# Os primeiros números vieram de duas medições: fala limpa a -0.24 e ruído puro a
# -0.92. Com base nisso o corte de fala curta foi pra -0.55, e ficou apertado
# demais. Numa call de verdade, com jogo ao fundo e microfone comum, o filtro
# jogou fora isto — tudo fala real:
#
#   -0.56  "Cara inova, mano."        -0.57  "O meu vídeo"
#   -0.63  "Puta que pariu!"          -0.71  "Muito novo, velho."
#   -0.79  "Na moral."                -0.81  "Cadê tu?"
#   -0.82  "Dead Cells, Emily no Cair."   <- essa tinha o NOME dela
#
# A última é a pior de todas: descartar uma fala que menciona a Emily é ela
# ignorar quem a chamou.
#
# O que os dados mostram é que fala curta real e ruído curto OCUPAM A MESMA
# FAIXA. Nenhum corte separa os dois, então a escolha é sobre qual erro doer
# menos. Aceitar ruído custa uma linha estranha na transcrição, que o modelo
# ignora — e que não dispara nada, porque o gatilho exige o nome dela. Descartar
# fala real custa ela não responder. O segundo é muito pior.
#
# Daí -1.0, que é o corte clássico do Whisper.
LOGPROB_MINIMO = float(os.getenv("EMILY_CALL_LOGPROB", "-1.0"))

# Fala curta passa por um corte mais rígido. Frase de duas ou três palavras com
# confiança baixa é quase sempre ruído virando palavra ("Nes, bejme"); a mesma
# confiança numa frase longa costuma ser fala real num ambiente barulhento.
# Corte mais rígido, e agora só pra UMA palavra.
#
# O rigor extra ficou onde ele se paga: transcrição de uma palavra é onde o ruído
# mais aparece ("Tchau!", "Obrigado.", "Dada.", "Tons.", "Conexão.") e onde a
# perda de uma fala real custa menos. De duas palavras pra cima já vale a pena
# manter — "Na moral.", "Cadê tu?", "Eu acho." são fala de verdade e vinham sendo
# descartadas.
#
# Antes isto valia até SEIS palavras, o que atingia frase inteira e curta como
# "Puta que pariu!" e "Muito novo, velho.".
LOGPROB_MINIMO_CURTO = float(os.getenv("EMILY_CALL_LOGPROB_CURTO", "-0.85"))
PALAVRAS_CURTO = int(os.getenv("EMILY_CALL_PALAVRAS_CURTO", "1"))

# Acima disso o texto está se repetindo, que é a assinatura da alucinação em
# laço do Whisper ("sim sim sim sim sim...").
COMPRESSAO_MAXIMA = float(os.getenv("EMILY_CALL_COMPRESSAO", "2.4"))


def _log(msg: str) -> None:
    print(f"[CALL] {msg}")


# ═════════════════════════════════════════════════════════════════
# O TURNO DE FALA
# ═════════════════════════════════════════════════════════════════

@dataclass
class Turno:
    """Uma pessoa falando de uma vez, do começo ao silêncio."""

    user_id: int
    nome: str
    inicio: float
    fim: float
    pcm: bytes = b""
    texto: str = ""
    rms: int = 0
    fechado_em: float = 0.0
    transcrito_em: float = 0.0

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio

    def __str__(self) -> str:
        return f"{self.nome}: {self.texto}"


# ═════════════════════════════════════════════════════════════════
# ESTADO
# ═════════════════════════════════════════════════════════════════

_observadores: List[Callable[[Turno], None]] = []
_historico: List[Turno] = []
_trava_historico = threading.Lock()

_fila: "queue.Queue[Turno]" = queue.Queue(maxsize=60)
_workers: List[threading.Thread] = []
_parar = threading.Event()

_canal_atual: Optional[int] = None
_escutando = False

# Números pro diagnóstico. Sem eles, "ela não respondeu" não tem como ser
# investigado: o turno pode ter sido descartado por curto, por silencioso, ou a
# transcrição pode ter vindo vazia.
class _Conta:
    # Todo campo novo tem que entrar AQUI também, senão o __init__ estoura
    # AttributeError no import do módulo — e aí a escuta simplesmente não sobe,
    # com o erro engolido pelo try do discord_bot. Já aconteceu.
    __slots__ = ("turnos", "curtos", "silenciosos", "transcritos", "vazios",
                 "erros", "segundos_audio", "ultimo_erro", "inventados",
                 "ultimo_descarte", "ultimo_pacote", "reanexos")

    def __init__(self):
        self.zerar()

    def zerar(self):
        self.turnos = 0
        self.curtos = 0
        self.silenciosos = 0
        self.transcritos = 0
        self.vazios = 0
        self.erros = 0
        self.segundos_audio = 0.0
        self.ultimo_erro = ""
        # Texto que o Whisper produziu mas que foi jogado fora por ser cópia da
        # dica ou por confiança baixa. Contador separado de `vazios` de
        # propósito: vazio é "não veio nada", inventado é "veio coisa que
        # ninguém falou", e a investigação de cada um é diferente.
        self.inventados = 0
        self.ultimo_descarte = ""
        # Quando chegou o último pacote de áudio, e quantas vezes o sink teve de
        # ser reanexado. Sem esses dois, "ela parou de ouvir" é indistinguível de
        # "ninguém falou".
        self.ultimo_pacote = 0.0
        self.reanexos = 0


contas = _Conta()


def observar(funcao: Callable[[Turno], None]) -> None:
    """
    Registra alguém pra receber cada turno já transcrito.

    Exceção num observador não pode parar a escuta: se parasse, um erro no código
    de resposta deixaria ela surda, e o sintoma apareceria longe da causa.
    """
    if funcao not in _observadores:
        _observadores.append(funcao)
        _log(f"observador registrado: {getattr(funcao, '__name__', funcao)}")


def _avisar(turno: Turno) -> None:
    for funcao in list(_observadores):
        try:
            funcao(turno)
        except Exception as e:
            _log(f"observador {getattr(funcao, '__name__', '?')} falhou: "
                 f"{type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════
# CONVERSÃO E TRANSCRIÇÃO
# ═════════════════════════════════════════════════════════════════

def _para_wav_16k(pcm48_stereo: bytes) -> bytes:
    """Compatibilidade: só padroniza, sem aplicar as melhorias opcionais."""
    import audio_preprocessing
    return audio_preprocessing.preprocess_audio(
        pcm48_stereo, sample_rate=TAXA_DISCORD, channels=CANAIS_DISCORD,
        sample_width=LARGURA, source="discord_call_padronizacao",
        config=audio_preprocessing.AudioPreprocessingConfig(
            denoise=False, normalize=False, vad=False),
    )


def _energia_de_turno(pcm: bytes) -> int:
    """Volume dos trechos mais audíveis; pausas não apagam uma fala breve."""
    bytes_janela = TAXA_DISCORD * CANAIS_DISCORD * LARGURA // 10  # 100 ms
    energias = sorted(_energia(pcm[i:i + bytes_janela])
                      for i in range(0, len(pcm), bytes_janela))
    if not energias:
        return 0
    return energias[max(0, (len(energias) * 9 + 9) // 10 - 1)]


_cliente_groq = None
_trava_groq = threading.Lock()


def _groq():
    global _cliente_groq
    with _trava_groq:
        if _cliente_groq is None:
            from groq import Groq
            _cliente_groq = Groq(api_key=os.getenv("GROQ_API_KEY"))
        return _cliente_groq


def transcrever(pcm: bytes) -> str:
    """PCM do Discord -> texto. String vazia quando não deu ou não tinha fala."""
    try:
        import audio_preprocessing
        wav = audio_preprocessing.preprocess_audio(
            pcm, sample_rate=TAXA_DISCORD, channels=CANAIS_DISCORD,
            sample_width=LARGURA, source="discord_call")
        if not wav:
            return ""
    except Exception as e:
        contas.erros += 1
        contas.ultimo_erro = f"pré-processamento: {type(e).__name__}: {e}"
        return ""

    arquivo = io.BytesIO(wav)
    arquivo.name = "call.wav"
    try:
        resposta = _groq().audio.transcriptions.create(
            file=arquivo,
            model="whisper-large-v3-turbo",
            language="pt",
            # Só manda prompt se existir um. Mandar string vazia não é o mesmo
            # que não mandar, e o padrão agora é não mandar.
            **({"prompt": DICA_TRANSCRICAO} if DICA_TRANSCRICAO else {}),
            temperature=0.0,
            # verbose_json em vez do padrão: é o que traz avg_logprob e
            # compression_ratio por segmento. Sem esses números, "ela ouviu
            # coisa que ninguém falou" não tem como ser filtrado — o texto de
            # uma alucinação é indistinguível do texto de uma fala.
            response_format="verbose_json",
        )
    except Exception as e:
        contas.erros += 1
        contas.ultimo_erro = f"{type(e).__name__}: {e}"
        return ""

    texto = _limpar(getattr(resposta, "text", "") or "")
    if not texto:
        return ""

    descarte = _motivo_de_descarte(texto, resposta)
    if descarte:
        contas.inventados += 1
        contas.ultimo_descarte = f"{descarte}: {texto[:70]}"
        _log(f"descartei transcrição ({descarte}): {texto[:70]}")
        return ""

    return texto


def _segmentos(resposta) -> list:
    """Os segmentos do verbose_json, seja o SDK objeto ou dicionário."""
    try:
        cru = resposta.model_dump()
    except Exception:
        cru = resposta if isinstance(resposta, dict) else {}
    segs = cru.get("segments") or []
    return [s for s in segs if isinstance(s, dict)]


def _e_eco_da_dica(texto: str) -> bool:
    """
    O Whisper devolveu a própria DICA_TRANSCRICAO em vez de transcrever?

    Esta é a defesa que não depende do formato da dica. Comparar por substring
    não serve: a dica diz "a Emily avisa a gente" e o eco veio "Nomes, Vitor,
    Comuna, Ryan, HaoQin" — parecido, não idêntico, e cada eco recorta um
    trecho diferente.

    O que se mede aqui é o maior TRECHO EM COMUM. Eco é quase todo ele um
    pedaço da dica; fala real que por acaso cite um nome compartilha só a
    palavra, não um trecho longo. Medido com a dica antiga:
        "nomes vitor comuna ryan haoqin"      -> 83% em comum, descarta
        "vitor o comuna entrou no servidor"   -> 24% em comum, mantém
    """
    a = _so_letras(texto)
    if len(a) < 12:
        # Texto curto casa por acaso com qualquer coisa. Fica pro filtro de
        # confiança, que trata curto com rigor maior.
        return False
    b = _so_letras(DICA_TRANSCRICAO)
    if not b:
        return False
    bloco = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(
        0, len(a), 0, len(b))
    # Duas condições, não uma. A porcentagem sozinha acusa fala curta que por
    # acaso repita um pedaço da dica; o tamanho absoluto sozinho acusa fala longa
    # que contenha uma expressão em comum. Eco de prompt tem os dois: é longo E
    # é quase todo o texto.
    return bloco.size >= 20 and (bloco.size / len(a)) >= 0.60


def _so_letras(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def _motivo_de_descarte(texto: str, resposta) -> str:
    """
    Por que este texto NÃO deve contar como fala. Vazio = pode passar.

    Nada aqui olha o CONTEÚDO pra decidir se faz sentido — isso seria adivinhar.
    O que se olha é de onde o texto veio: se é cópia da dica, e o quanto o
    próprio Whisper confiou no que decodificou.
    """
    if _e_eco_da_dica(texto):
        return "é cópia da dica de vocabulário"

    segs = _segmentos(resposta)
    if not segs:
        # Sem números não dá pra julgar; deixa passar em vez de ficar surda.
        return ""

    logprobs = [s["avg_logprob"] for s in segs
                if isinstance(s.get("avg_logprob"), (int, float))]
    if logprobs:
        media = sum(logprobs) / len(logprobs)
        palavras = len(texto.split())
        corte = (LOGPROB_MINIMO_CURTO if palavras <= PALAVRAS_CURTO
                 else LOGPROB_MINIMO)
        if media < corte:
            return (f"confiança {media:.2f} abaixo de {corte:.2f} "
                    f"({palavras} palavra(s))")

    compressoes = [s["compression_ratio"] for s in segs
                   if isinstance(s.get("compression_ratio"), (int, float))]
    if compressoes and max(compressoes) > COMPRESSAO_MAXIMA:
        return f"texto se repetindo (compressão {max(compressoes):.2f})"

    return ""


# Frases que o Whisper inventa quando recebe silêncio ou ruído. É comportamento
# conhecido do modelo: ele foi treinado com legendas do YouTube e alucina
# encerramento de vídeo. Sem esta lista, cada trecho de silêncio viraria uma
# "fala" e a Emily responderia a ninguém.
_ALUCINACOES = (
    "obrigado por assistir", "obrigada por assistir", "se inscreva",
    "inscreva-se", "curta o vídeo", "deixe seu like", "até a próxima",
    "legendas pela comunidade", "amara.org", "tchau tchau",
    "thanks for watching", "subscribe", "subtitles by",
)


def _limpar(texto: str) -> str:
    limpo = " ".join((texto or "").split())
    if not limpo:
        return ""
    baixo = limpo.lower().strip(" .!?")
    # Alucinação costuma vir como a frase INTEIRA, então comparar o texto todo
    # evita apagar uma fala real que por acaso contenha a expressão.
    for ruim in _ALUCINACOES:
        if baixo == ruim or (len(baixo) < 40 and ruim in baixo):
            return ""
    # Uma letra ou um símbolo solto não é fala.
    if len(baixo) < 2:
        return ""
    return limpo


def _trabalhar() -> None:
    """Worker: pega turno da fila, transcreve, avisa os observadores."""
    while not _parar.is_set():
        try:
            turno = _fila.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            inicio_stt = time.monotonic()
            turno.texto = transcrever(turno.pcm)
            turno.transcrito_em = time.monotonic()
            if not turno.texto:
                contas.vazios += 1
                continue
            contas.transcritos += 1
            # O PCM é solto depois de transcrever: guardar áudio de call inteira
            # na memória não serve pra nada e cresce rápido.
            turno.pcm = b""
            with _trava_historico:
                _historico.append(turno)
                # Com STTs paralelos, a resposta da fala mais recente pode
                # chegar antes da mais antiga. O prompt precisa refletir a
                # ordem da conversa, não a ordem das respostas do servidor.
                _historico.sort(key=lambda t: t.fim)
                del _historico[:-JANELA_TURNOS]
            _log(f"{turno.nome}: {turno.texto}")
            print(
                "[CALL-LATENCIA] "
                f"fechamento={max(0.0, turno.fechado_em - turno.fim):.3f}s "
                f"fila_stt={max(0.0, inicio_stt - turno.fechado_em):.3f}s "
                f"stt={turno.transcrito_em - inicio_stt:.3f}s"
            )
            _avisar(turno)
        except Exception as e:
            contas.erros += 1
            contas.ultimo_erro = f"{type(e).__name__}: {e}"
            _log(f"erro processando turno: {e}")
        finally:
            _fila.task_done()


# ═════════════════════════════════════════════════════════════════
# O SINK: MONTAR TURNOS A PARTIR DOS PACOTES
# ═════════════════════════════════════════════════════════════════

class _EmAndamento:
    __slots__ = ("pcm", "inicio", "ultimo", "nome")

    def __init__(self, nome: str, agora: float):
        self.pcm = bytearray()
        self.inicio = agora
        self.ultimo = agora
        self.nome = nome


def _criar_sink():
    """
    Cria a classe do sink na hora.

    Feito dentro de função porque `AudioSink` só existe se o voice_recv estiver
    instalado, e este módulo precisa poder ser importado (pro diagnóstico, pro
    catálogo de ferramentas) numa máquina sem ele.
    """
    from discord.ext import voice_recv

    class EscutaSink(voice_recv.AudioSink):
        """
        Junta os pacotes de cada pessoa até o silêncio fechar o turno.

        O `write` roda na thread de rede do voice_recv e é chamado ~50 vezes por
        segundo por pessoa falando. Nada aqui pode ser lento: só acumula bytes. O
        fechamento de turno e a transcrição acontecem em outras threads.
        """

        def __init__(self):
            super().__init__()
            self.andamento: Dict[int, _EmAndamento] = {}
            self.trava = threading.Lock()
            self.parar = threading.Event()
            self.vigia = threading.Thread(target=self._vigiar,
                                          name="call-turnos", daemon=True)
            self.vigia.start()

        def wants_opus(self) -> bool:
            return False

        def write(self, user, data) -> None:
            """
            NADA aqui pode levantar exceção. Nunca.

            Este método roda dentro do laço da thread de pacotes do voice_recv, e
            o laço é assim (router.py):

                try:    self._do_run()
                except: ...
                finally: self.reader.voice_client.stop_listening()

            O stop_listening está no FINALLY. Então uma exceção que suba daqui não
            derruba um pacote: derruba a recepção INTEIRA, de forma permanente e
            silenciosa. Foi assim que a Emily ficou ouvindo "só de vez em quando"
            — um erro qualquer aqui e ela ficava surda até o vigia reanexar.

            Por isso o try/except largo, que normalmente seria preguiça. Aqui ele
            é a diferença entre perder um pacote e perder a call.
            """
            try:
                if user is None or not data.pcm:
                    return
                agora = time.monotonic()
                # Marca de vida da recepção. É o que permite dizer, no
                # diagnóstico, "o último pacote chegou há 40 minutos" — que é a
                # diferença entre uma call silenciosa e uma escuta morta.
                contas.ultimo_pacote = agora
                nome = getattr(user, "display_name", None) or str(user.id)
                with self.trava:
                    atual = self.andamento.get(user.id)
                    if atual is None:
                        atual = _EmAndamento(nome, agora)
                        self.andamento[user.id] = atual
                    atual.pcm.extend(data.pcm)
                    atual.ultimo = agora
                    atual.nome = nome
                    estourou = (agora - atual.inicio) * 1000 >= MAX_MS
                if estourou:
                    self._fechar(user.id, agora, forcado=True)
            except Exception as e:
                contas.erros += 1
                contas.ultimo_erro = f"sink.write: {type(e).__name__}: {e}"

        def _vigiar(self) -> None:
            """Fecha turnos que ficaram em silêncio. Roda a cada 100 ms."""
            while not self.parar.is_set():
                try:
                    agora = time.monotonic()
                    vencidos = []
                    with self.trava:
                        for uid, atual in self.andamento.items():
                            if (agora - atual.ultimo) * 1000 >= GAP_MS:
                                vencidos.append(uid)
                    for uid in vencidos:
                        self._fechar(uid, agora)
                except Exception as e:
                    contas.erros += 1
                    contas.ultimo_erro = f"sink.vigia: {type(e).__name__}: {e}"
                self.parar.wait(0.1)

        def _fechar(self, user_id: int, agora: float,
                    forcado: bool = False) -> None:
            # Também blindado: o _fechar é chamado de dentro do write, então uma
            # exceção aqui chega no mesmo finally e causa o mesmo estrago.
            try:
                self._fechar_real(user_id, agora, forcado)
            except Exception as e:
                contas.erros += 1
                contas.ultimo_erro = f"sink.fechar: {type(e).__name__}: {e}"

        def _fechar_real(self, user_id: int, agora: float,
                         forcado: bool = False) -> None:
            with self.trava:
                atual = self.andamento.pop(user_id, None)
                if forcado and atual is not None:
                    # Turno cortado no meio: a fala continua, então já abre o
                    # próximo pra não perder o que vem depois do corte.
                    novo = _EmAndamento(atual.nome, agora)
                    self.andamento[user_id] = novo
            if atual is None or not atual.pcm:
                return

            pcm = bytes(atual.pcm)
            duracao_ms = len(pcm) / (TAXA_DISCORD * CANAIS_DISCORD * LARGURA) * 1000
            contas.turnos += 1

            if duracao_ms < MIN_MS:
                contas.curtos += 1
                return

            energia = _energia_de_turno(pcm)
            if energia < RMS_MINIMO:
                contas.silenciosos += 1
                return

            contas.segundos_audio += duracao_ms / 1000
            turno = Turno(user_id=user_id, nome=atual.nome,
                          inicio=atual.inicio, fim=atual.ultimo,
                          pcm=pcm, rms=energia, fechado_em=agora)
            try:
                _fila.put_nowait(turno)
            except queue.Full:
                # Fila cheia significa que a transcrição não está dando conta.
                # Descartar o mais novo é melhor que travar a thread de rede.
                contas.erros += 1
                contas.ultimo_erro = "fila de transcrição cheia"

        def cleanup(self) -> None:
            self.parar.set()
            agora = time.monotonic()
            for uid in list(self.andamento):
                self._fechar(uid, agora)

    return EscutaSink


# ═════════════════════════════════════════════════════════════════
# ENTRAR E SAIR
# ═════════════════════════════════════════════════════════════════

_sink = None


def ligar_workers() -> None:
    global _workers
    if _workers and any(w.is_alive() for w in _workers):
        return
    try:
        import audio_preprocessing
        audio_preprocessing.warmup_async()
    except Exception as e:
        _log(f"não consegui aquecer pré-processamento: {e}")
    _parar.clear()
    _workers = []
    for i in range(max(1, TRABALHADORES)):
        w = threading.Thread(target=_trabalhar, name=f"call-stt-{i}",
                             daemon=True)
        w.start()
        _workers.append(w)


# A conexão de voz em que o sink está pendurado. Guardada porque reconexão do
# Discord troca o objeto, e comparar a referência é como se descobre isso.
_vc = None
_vigia_conexao: Optional[threading.Thread] = None

# Como o vigia é acordado pra morrer. Um Event em vez de time.sleep() porque com
# sleep o vigia só percebia que foi parado no fim da soneca — e enquanto isso
# continuava vivo, o que fazia o comecar_a_ouvir seguinte reaproveitar uma thread
# que estava de saída, com o intervalo antigo. Com Event, parar é imediato.
_vigia_parar = threading.Event()

# De quanto em quanto tempo o vigia confere se a recepção está viva.
#
# Baixou de 10s pra 4s depois que o reanexo passou a FUNCIONAR (ver o
# _SemStopListening). Antes, conferir rápido só adiantava o próximo reanexo
# inútil; agora cada checagem é uma chance real de consertar antes de alguém
# reparar. Quanto mais rápido o conserto, menos a Emily precisa recorrer à
# reconexão de voz — que é o que o Vitor vê como "ela sai e entra da call".
INTERVALO_VIGIA = float(os.getenv("EMILY_CALL_VIGIA", "4"))

# Quanto tempo SEM NENHUM PACOTE numa call é motivo pra desconfiar.
#
# Dez minutos, e o número foi corrigido de 20 SEGUNDOS depois de uma call real.
# O erro original foi conceitual, não de calibragem: eu tratei silêncio de call
# como sintoma de falha. Não é. As pessoas estavam jogando, e o log mostrou o
# padrão com clareza — "30s sem pacote", "31s sem pacote", "30s sem pacote", de
# meio em meio minuto, a call inteira. Trinta segundos sem ninguém falar numa
# call de jogo é o comportamento normal.
#
# Com o limite curto, o vigia reanexou 32 vezes numa call que funcionava, e cada
# reanexo comeu as falas que estavam sendo montadas.
#
# Dez minutos é largo de propósito. Silêncio nunca é evidência forte de defeito;
# ele é, no máximo, a última rede de segurança pro caso em que is_listening()
# mente. Quem detecta problema de verdade é o is_listening().
SILENCIO_SUSPEITO = float(os.getenv("EMILY_CALL_SILENCIO_SUSPEITO", "600"))

# Quantas checagens ruins seguidas antes de mexer em qualquer coisa.
#
# UMA quando o diagnóstico vem da API pública (is_listening() = não): esse sinal
# não dá falso positivo, então esperar confirmação só atrasa o conserto e
# aumenta a chance de alguém falar no meio e não ser ouvido.
#
# DUAS quando o diagnóstico é silêncio longo, que é indício e não prova.
CHECAGENS_ANTES_DE_AGIR = int(os.getenv("EMILY_CALL_CHECAGENS", "1"))
CHECAGENS_POR_SILENCIO = int(os.getenv("EMILY_CALL_CHECAGENS_SILENCIO", "2"))

# Quantas vezes vale tentar o reparo barato (reanexar o sink) antes de concluir
# que o problema não é o sink.
#
# Subiu de 2 pra 5 porque o reparo barato agora funciona de verdade, e porque a
# alternativa é caríssima em experiência: a reconexão de voz faz a Emily sair e
# voltar na call na frente de todos. Cinco tentativas de 4 em 4 segundos custam
# vinte segundos de escuta ruim; uma reconexão custa a call parecer bugada.
MAX_REANEXOS_SEGUIDOS = int(os.getenv("EMILY_CALL_MAX_REANEXOS", "5"))

# Espera mínima entre dois pedidos de reconexão de voz. Reconectar derruba e
# levanta a call, então não pode virar rotina.
ESPERA_ENTRE_RECONEXOES = float(os.getenv("EMILY_CALL_ESPERA_RECONEXAO", "120"))

# Quanto o vigia espera, depois de reanexar, antes de conferir se funcionou.
#
# Dois segundos porque o que mata a escuta nova vem de outra thread (o finally do
# roteador do voice_recv) e leva um tempo imprevisível pra disparar. Conferir
# cedo demais dava "recepção de volta" e a morte acontecia meio segundo depois,
# fora do log.
#
# É constante, e não número solto no meio do laço, porque sleep fixo dentro de
# laço é código intestável: com ele cravado, exercitar o caminho de escalada
# levava minutos e o teste ficava dependente de tempo de parede.
ESPERA_CONFERIR_REANEXO = float(os.getenv("EMILY_CALL_ESPERA_CONFERIR", "2"))


class _SemStopListening:
    """
    Um cliente de voz de fachada, igual ao de verdade em tudo menos numa coisa:
    stop_listening() não faz nada.

    POR QUE ISSO EXISTE
    ───────────────────
    O voice_recv tem isto no laço da thread de pacotes (router.py, no run):

        try:     self._do_run()
        except:  ...
        finally: self.reader.voice_client.stop_listening()

    Está num FINALLY, então a thread chama stop_listening() ao terminar por
    QUALQUER motivo — inclusive quando é parada de propósito. E como
    stop_listening() age sobre o cliente, e não sobre o reader que está morrendo,
    o alvo é quem estiver escutando NAQUELE momento.

    Isso torna reanexar impossível pelo caminho ingênuo:

        stop_listening()        -> reader velho começa a morrer
        listen(sink_novo)       -> reader novo, ativo, funcionando
        (milissegundos depois)
        finally do roteador     -> stop_listening() -> MATA O READER NOVO

    Foi exatamente o que apareceu no log: "reanexei e a recepção CONTINUA caída",
    uma vez atrás da outra, e a recepção nunca voltava por reanexo nenhum.

    A saída é desarmar a bomba antes de ela chegar: depois de parar o reader
    velho, troca-se o voice_client DELE por esta fachada. O finally continua
    disparando, só que agora contra um objeto que ignora o pedido. Tudo o mais é
    repassado pro cliente real, pra não quebrar nada do resto da limpeza.
    """

    __slots__ = ("_real",)

    def __init__(self, real):
        object.__setattr__(self, "_real", real)

    def stop_listening(self):
        return None

    def __getattr__(self, nome):
        return getattr(object.__getattribute__(self, "_real"), nome)

    def __setattr__(self, nome, valor):
        setattr(object.__getattribute__(self, "_real"), nome, valor)


def _desarmar_reader_velho(voice_client) -> None:
    """Para o reader atual de um jeito que ele não mate o próximo."""
    reader = getattr(voice_client, "_reader", None)
    try:
        if voice_client.is_listening():
            # Precisa acontecer com o cliente REAL na mão: é aqui que o callback
            # é desregistrado do socket. Trocar antes deixaria o registro pra
            # trás e o reader velho continuaria recebendo pacote.
            voice_client.stop_listening()
    except Exception:
        pass

    if reader is not None and not isinstance(
            getattr(reader, "voice_client", None), _SemStopListening):
        try:
            reader.voice_client = _SemStopListening(voice_client)
        except Exception:
            pass


def _anexar(voice_client) -> None:
    """
    Pendura um sink NOVO na conexão de voz. Sem checagem de estado, sem enfeite.

    Sink novo e não o antigo de propósito: o sink guarda os turnos em andamento e
    a thread que fecha eles por silêncio. Reaproveitar um sink cujo AudioReader
    morreu seria carregar turnos pela metade de antes da queda.
    """
    global _sink, _vc, _canal_atual

    if _sink is not None:
        try:
            _sink.cleanup()
        except Exception:
            pass

    _desarmar_reader_velho(voice_client)

    # Cada escuta nova merece um diagnóstico novo: os avisos de motivo de
    # descarte do patch do DAVE disparam uma vez por sessão justamente pra não
    # virar spam de pacote — então precisam zerar quando a sessão recomeça.
    try:
        import patch_dave
        patch_dave._resetar_avisos()
    except Exception:
        pass

    ligar_workers()
    _sink = _criar_sink()()
    voice_client.listen(_sink)
    _vc = voice_client
    _canal_atual = getattr(getattr(voice_client, "channel", None), "id", None)


def _recepcao_viva(voice_client=None) -> bool:
    """
    A recepção de áudio está DE FATO funcionando?

    A flag `_escutando` deste módulo não responde isso, e foi exatamente esse o
    defeito: o Discord derruba a conexão de voz de vez em quando (erro 4006,
    troca de região, mudança de canal). Quando isso acontece o sink fica órfão,
    mas `_escutando` continuava True — e o comecar_a_ouvir, confiando nela,
    respondia "Já estou ouvindo" e NÃO reanexava. A Emily ficava surda pelo resto
    do processo, sem log e sem erro, porque do ponto de vista dela estava tudo
    certo.

    A checagem usa SÓ a API pública: is_connected() e is_listening().

    POR QUE A CHECAGEM PROFUNDA FOI REMOVIDA
    ────────────────────────────────────────
    Havia aqui uma segunda camada que olhava dentro do discord.py: se o callback
    do reader ainda estava em _connection._socket_reader._callbacks. A ideia era
    pegar um reader órfão, cuja conexão tinha sido substituída, e que continuaria
    respondendo is_listening() == True.

    Ela foi embora porque produziu falso negativo em produção, com o áudio
    FUNCIONANDO. Medido numa call real: 32 reanexos, e no meio deles as
    transcrições saindo normalmente. O log dizia "reanexei e a recepção CONTINUA
    caída" logo antes de transcrever a fala de duas pessoas.

    O saldo é o que decide. O falso negativo custa caro: cada reanexo joga fora o
    sink e as falas que estavam sendo montadas, então o efeito é justamente a
    escuta intermitente que se queria evitar — e ainda gera fragmentos de frase,
    que por serem fragmentos vêm com confiança baixa e são descartados depois. O
    ganho, por outro lado, era hipotético: o cenário do reader órfão foi
    deduzido lendo o código, nunca observado.

    Atributo privado de biblioteca, lido de outra thread, no meio de reconexão e
    de rotinas de limpeza em background, não é base pra decidir destruir estado
    bom.
    """
    vc = voice_client or _vc
    if vc is None:
        return False
    try:
        return bool(vc.is_connected() and vc.is_listening())
    except Exception:
        return False


# Injetado pelo discord_bot: derruba e levanta a conexão de voz inteira. É o
# único reparo capaz de resolver uma thread de socket morta, porque só reconectar
# recria o VoiceConnectionState (e com ele o SocketReader).
_pedir_reconexao: Optional[Callable[[], None]] = None


def definir_reconexao(funcao) -> None:
    global _pedir_reconexao
    _pedir_reconexao = funcao


# Estado do vigia. Fora da classe _Conta porque é máquina de estado, não
# estatística: zerar contadores no meio de um diagnóstico não pode fazer o vigia
# esquecer que já tentou consertar duas vezes.
_ruins_seguidas = 0
_reanexos_seguidos = 0
_ultima_reconexao = 0.0
_desisti = ""


def _vigiar_conexao() -> None:
    """
    Conserta a recepção quando ela cai, e SABE PARAR quando o conserto não
    resolve.

    A primeira versão disto era só "está morto? reanexa" num laço, e numa call
    real ela reanexou seis vezes seguidas de 10 em 10 segundos, gritando
    "recepção de volta" toda vez sem nunca conferir se voltou. Como cada reanexo
    joga fora o sink e os turnos em andamento, o vigia passou a ser a causa da
    surdez que ele existia pra consertar.

    As três regras que saíram daquele episódio:

      1. PROVA GANHA DE INDÍCIO. Se chegou pacote de áudio há pouco, está
         funcionando — não importa o que a introspecção ache.

      2. CONFERE O CONSERTO. Depois de reanexar, olha de novo. Reparo que não
         muda o diagnóstico é reparo errado, e insistir nele é laço.

      3. ESCALA E DESISTE. Reanexar o sink só resolve problema de sink. Se duas
         tentativas não resolveram, o problema está mais embaixo (a thread de
         socket do discord.py morre de vez num disconnect com cleanup, e aí nada
         que eu penduro nela funciona) — então pede reconexão de voz, que recria
         tudo. Se nem isso resolver, para de tentar e diz que parou. Ficar
         tentando pra sempre destrói áudio bom e enche o terminal de mentira.
    """
    global _ruins_seguidas, _reanexos_seguidos, _ultima_reconexao, _desisti

    while True:
        if _vigia_parar.wait(INTERVALO_VIGIA):
            return
        if not _escutando or _parar.is_set():
            return
        if _desisti:
            continue          # já desisti; não fica mexendo

        vc = _vc
        if vc is None:
            continue

        try:
            if not vc.is_connected():
                # Fora da call: quem cuida disso é o discord_bot, que chama o
                # parar_de_ouvir. Aqui não se faz nada.
                _ruins_seguidas = 0
                continue

            agora = time.monotonic()
            calado_ha = (agora - contas.ultimo_pacote
                         if contas.ultimo_pacote else 0.0)

            # ── O que conta como "está funcionando" ──
            #
            # A API pública manda. Se o cliente diz que está recebendo, está
            # recebendo, e o vigia não tem nada a fazer — mesmo que ninguém fale
            # há meia hora. Silêncio de call é silêncio de call.
            #
            # A única exceção é o extremo: is_listening() dizendo sim com NENHUM
            # pacote em dez minutos. Aí vale uma tentativa, porque nesse ponto o
            # silêncio deixou de ser plausível.
            if _recepcao_viva(vc):
                if not contas.ultimo_pacote or calado_ha < SILENCIO_SUSPEITO:
                    _ruins_seguidas = 0
                    _reanexos_seguidos = 0
                    continue
                motivo = (f"o cliente diz que está recebendo, mas não chega "
                          f"pacote há {calado_ha / 60:.0f} min")
                # Silêncio é indício: exige confirmação antes de agir.
                minimo = CHECAGENS_POR_SILENCIO
            else:
                motivo = "o cliente parou de receber (is_listening = não)"
                # A API pública é prova: agir na hora. Esperar aqui só significa
                # mais segundos de gente falando e ela não ouvindo.
                minimo = CHECAGENS_ANTES_DE_AGIR

            _ruins_seguidas += 1
            if _ruins_seguidas < minimo:
                continue

            silencio = motivo

            # ── Regra 3: escala ──
            if _reanexos_seguidos >= MAX_REANEXOS_SEGUIDOS:
                if _pedir_reconexao is None:
                    _desisti = ("a recepção não voltou e eu não tenho como "
                                "reconectar a voz sozinha")
                    _log(f"DESISTI: {_desisti}. Alguém precisa me tirar e me "
                         f"colocar de volta na call.")
                    continue
                if (agora - _ultima_reconexao) < ESPERA_ENTRE_RECONEXOES:
                    continue
                _ultima_reconexao = agora
                _log(f"reanexar não resolveu ({silencio}); o problema está na "
                     f"conexão de voz, pedindo reconexão completa")
                try:
                    _pedir_reconexao()
                except Exception as e:
                    _log(f"não consegui pedir reconexão: {type(e).__name__}: {e}")
                    _desisti = f"a reconexão de voz falhou: {e}"
                _reanexos_seguidos = 0
                _ruins_seguidas = 0
                continue

            # ── Reparo barato: reanexar o sink ──
            contas.reanexos += 1
            _reanexos_seguidos += 1
            _log(f"a recepção de áudio parece caída ({silencio}); reanexando "
                 f"— reanexo nº {contas.reanexos}")
            _anexar(vc)

            # ── Regra 2: confere o conserto, em vez de anunciar vitória ──
            time.sleep(ESPERA_CONFERIR_REANEXO)
            if _recepcao_viva(vc):
                _log("recepção de volta")
                _ruins_seguidas = 0
                _reanexos_seguidos = 0
            else:
                _log(f"reanexei e a recepção CONTINUA caída "
                     f"(tentativa {_reanexos_seguidos} de "
                     f"{MAX_REANEXOS_SEGUIDOS})")
                _ruins_seguidas = CHECAGENS_ANTES_DE_AGIR   # já confirmado

        except Exception as e:
            contas.erros += 1
            contas.ultimo_erro = f"vigia: {type(e).__name__}: {e}"
            _log(f"o vigia falhou: {type(e).__name__}: {e}")


async def comecar_a_ouvir(voice_client) -> str:
    """
    Começa a escutar numa conexão de voz que já existe.

    Chamar isto com a escuta já rodando é normal e seguro: acontece a cada
    entrada em call, e é o caminho que conserta uma recepção que caiu.

    Devolve texto explicando o resultado, porque isso vai virar resposta de
    ferramenta e mensagem no chat.
    """
    global _escutando, _vigia_conexao

    if not ATIVO:
        return ("A escuta de call está desligada na configuração "
                "(EMILY_ESCUTA_CALL=0).")
    if voice_client is None or not voice_client.is_connected():
        return "Não estou conectada em call nenhuma."

    if not os.getenv("GROQ_API_KEY"):
        return ("Falta a GROQ_API_KEY no .env — sem ela eu ouço mas não "
                "entendo nada.")

    import patch_dave
    ok, msg = patch_dave.aplicar()
    if not ok:
        return f"Não consegui preparar a decifragem do áudio: {msg}"

    try:
        from discord.ext import voice_recv
    except ImportError:
        return ("A extensão discord-ext-voice-recv não está instalada, então "
                "não tenho como receber áudio.")

    if not isinstance(voice_client, voice_recv.VoiceRecvClient):
        return ("Entrei na call pelo caminho antigo, que não recebe áudio. "
                "Preciso sair e entrar de novo pra conseguir ouvir.")

    # O atalho de "já estou ouvindo" agora exige DUAS coisas verdadeiras: ser a
    # mesma conexão de voz, e essa conexão estar de fato recebendo. Antes bastava
    # a flag, e era por isso que ela ficava surda pra sempre depois de uma
    # reconexão.
    if _escutando and voice_client is _vc and _recepcao_viva(voice_client):
        return "Já estou ouvindo."

    motivo = ""
    if _escutando:
        motivo = (" (a conexão de voz é outra)" if voice_client is not _vc
                  else " (a recepção anterior tinha caído)")

    try:
        _anexar(voice_client)
    except Exception as e:
        contas.erros += 1
        contas.ultimo_erro = f"anexar: {type(e).__name__}: {e}"
        return (f"Não consegui pendurar a escuta na call: "
                f"{type(e).__name__}: {e}")

    _escutando = True

    # Toda entrada em call é uma chance nova: zera a máquina de estado do vigia,
    # inclusive o "desisti". Sem isso, um problema de uma call anterior deixaria o
    # vigia desligado numa call onde tudo está bem.
    global _ruins_seguidas, _reanexos_seguidos, _desisti
    _ruins_seguidas = 0
    _reanexos_seguidos = 0
    _desisti = ""

    _vigia_parar.clear()
    if _vigia_conexao is None or not _vigia_conexao.is_alive():
        _vigia_conexao = threading.Thread(target=_vigiar_conexao,
                                          name="call-vigia", daemon=True)
        _vigia_conexao.start()

    _log(f"escutando o canal {_canal_atual}{motivo}")
    return "Tô ouvindo a call agora."


def parar_de_ouvir(voice_client=None) -> str:
    global _sink, _escutando, _vc
    if not _escutando:
        return "Não estava ouvindo."
    _escutando = False          # para o vigia antes de desmontar
    _vigia_parar.set()
    if _vigia_conexao is not None and _vigia_conexao.is_alive():
        # Espera pro vigia sair de fato. Sem isso, o próximo comecar_a_ouvir pode
        # reaproveitar uma thread que está morrendo. O teto é 4s porque o vigia
        # pode estar no meio da espera de 2s que confere um reanexo.
        _vigia_conexao.join(timeout=4.0)
    try:
        vc = voice_client or _vc
        if vc is not None and vc.is_connected():
            # Mesmo desarme do _anexar: se ela voltar pra call logo depois, o
            # finally do roteador antigo não pode matar a escuta nova.
            _desarmar_reader_velho(vc)
    except Exception as e:
        _log(f"erro ao parar: {e}")
    if _sink is not None:
        try:
            _sink.cleanup()
        except Exception:
            pass
    _sink = None
    _vc = None
    _log("parei de ouvir")
    return "Parei de ouvir a call."


def escutando() -> bool:
    """
    Está ouvindo de verdade — não "acha que está".

    A diferença importa: esta função alimenta a ferramenta que responde "você tá
    me ouvindo?" e o portão que liga o resto_call. Responder sim com a recepção
    caída é o pior resultado possível, porque manda todo mundo procurar o defeito
    no lugar errado.
    """
    if not _escutando:
        return False
    if _vc is None:
        return False
    return _recepcao_viva(_vc)


def pretendo_ouvir() -> bool:
    """
    O sink está pendurado e o vigia está de pé — mesmo que a recepção esteja
    caída neste instante.

    Existe separado do escutando() por um motivo prático: quem liga o resto_call
    deve usar ESTA, não aquela. Uma recepção caída é conserto do vigia, que vem em
    segundos; desligar a resposta por causa disso deixaria a Emily muda mesmo
    depois do áudio voltar.
    """
    return _escutando


# ═════════════════════════════════════════════════════════════════
# A JANELA DE CONVERSA
# ═════════════════════════════════════════════════════════════════

# Como as falas DELA aparecem na transcrição. Igual ao que o caminho de texto
# usa na janela do canal, porque o modelo já sabe ler essa marca.
NOME_DELA = "Emily (você)"

# ID reservado pra ela. Não é 0 por acaso: 0 nunca é um snowflake de Discord
# válido, então não colide com pessoa nenhuma e dá pra filtrar as falas dela
# sem depender do nome.
ID_DELA = 0


def registrar_fala_dela(texto: str) -> None:
    """
    Guarda uma fala DELA na transcrição da call.

    Isto conserta um buraco que só existe em call e não existe em texto: o bot
    não recebe os próprios pacotes de áudio, então nada do que ela fala passa
    pelo sink. O resultado, medido em uso real, é que a transcrição fica só com
    as perguntas e nenhuma resposta:

        Vitor: emily o servidor tá on?
        Vitor: e quem tá jogando?

    Lendo isso, o modelo não tem como saber que já respondeu a primeira. Ele vê
    duas perguntas seguidas sem resposta no meio, conclui que a primeira ficou
    pendente e responde ela de novo — foi assim que ela ficou presa dizendo
    "tô verificando" a cada frase nova.

    Os observadores NÃO são avisados, e essa omissão é o ponto: avisar faria a
    própria fala dela virar um turno candidato a gatilho, e ela responderia a si
    mesma. O anti-eco pegaria a maioria dos casos, mas depender dele pra isso
    seria construir o laço e confiar na rede embaixo.
    """
    texto = (texto or "").strip()
    if not texto:
        return
    agora = time.monotonic()
    with _trava_historico:
        _historico.append(Turno(
            user_id=ID_DELA, nome=NOME_DELA,
            inicio=agora, fim=agora, texto=texto,
        ))
        del _historico[:-JANELA_TURNOS]


def zerar_historico() -> None:
    """Começa uma call sem herdar falas da sessão de voz anterior."""
    with _trava_historico:
        _historico.clear()


def turnos_recentes(segundos: float = 90.0, limite: int = 12) -> List[Turno]:
    corte = time.monotonic() - segundos
    with _trava_historico:
        return [t for t in _historico if t.fim >= corte][-limite:]


def transcricao_recente(segundos: float = 90.0, limite: int = 12) -> str:
    """
    A conversa recente da call em texto.

    É isto que faz a resposta dela ter contexto: sem a janela, ela responderia
    só à frase que a chamou e pareceria alguém que acabou de chegar na sala.
    """
    def nome_do_turno(turno):
        if turno.user_id == ID_DELA:
            return turno.nome
        try:
            import perfil_discord
            return perfil_discord.nome_de(turno.user_id) or turno.nome
        except Exception:
            return turno.nome

    linhas = [f"{nome_do_turno(t)}: {t.texto}"
              for t in turnos_recentes(segundos, limite)]
    return "\n".join(linhas)


def estado() -> str:
    """Resposta de ferramenta e de diagnóstico."""
    if not ATIVO:
        return "Minha escuta de call está desligada na configuração."
    # Os dois estados são reportados SEPARADOS de propósito. Quando eles
    # divergem, a divergência é o diagnóstico: significa que a recepção caiu por
    # baixo e o vigia ainda não reanexou.
    vivo = _recepcao_viva()
    if _escutando and vivo:
        situacao = "sim"
    elif _escutando and not vivo:
        situacao = ("ACHO QUE SIM, MAS NÃO ESTOU — a recepção de áudio caiu "
                    "(reconexão do Discord). O vigia reanexa em até "
                    f"{INTERVALO_VIGIA:.0f}s")
    else:
        situacao = "não"

    linhas = [
        f"Ouvindo: {situacao}"
        + (f" (canal {_canal_atual})" if _canal_atual else ""),
    ]
    if contas.ultimo_pacote:
        atras = time.monotonic() - contas.ultimo_pacote
        linhas.append(f"Último pacote de áudio: há {atras:.0f}s")
    elif _escutando:
        linhas.append("Último pacote de áudio: NENHUM desde que comecei a ouvir")
    if contas.reanexos:
        linhas.append(f"Vezes que tive de reanexar a escuta: {contas.reanexos}")
    if _desisti:
        linhas.append(f"DESISTI DE CONSERTAR SOZINHA: {_desisti}. "
                      f"Me tirem da call e me chamem de novo.")
    linhas += [
        f"Turnos de fala vistos: {contas.turnos}",
        f"Aguardando transcrição: {_fila.qsize()} turno(s) "
        f"({sum(w.is_alive() for w in _workers)} workers ativos)",
        f"  transcritos: {contas.transcritos}",
        f"  curtos demais: {contas.curtos}",
        f"  silenciosos: {contas.silenciosos}",
        f"  sem texto: {contas.vazios}",
        f"  texto inventado, descartado: {contas.inventados}"
        + (f" — último: {contas.ultimo_descarte[:90]}"
           if contas.ultimo_descarte else ""),
        f"Áudio processado: {contas.segundos_audio:.0f}s "
        f"(~US$ {contas.segundos_audio / 3600 * 0.04:.3f} no Groq)",
    ]
    if contas.erros:
        linhas.append(f"Erros: {contas.erros} — último: {contas.ultimo_erro[:120]}")
    try:
        import patch_dave
        if patch_dave.estatisticas.total:
            linhas.append("")
            linhas.append(patch_dave.estatisticas.resumo())
    except Exception:
        pass
    recente = transcricao_recente(120, 6)
    if recente:
        linhas.append("")
        linhas.append("Últimas falas que ouvi:")
        linhas.append(recente)
    return "\n".join(linhas)


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("  ESCUTA DE CALL")
    print("=" * 66)
    print(f"  ativa:            {ATIVO}")
    print(f"  chave do Groq:    "
          f"{'presente' if os.getenv('GROQ_API_KEY') else 'AUSENTE'}")
    print(f"  gap de turno:     {GAP_MS} ms")
    print(f"  duração mínima:   {MIN_MS} ms")
    print(f"  duração máxima:   {MAX_MS} ms")
    print(f"  rms mínimo:       {RMS_MINIMO}")
    print(f"  trabalhadores:    {TRABALHADORES}")

    print(f"  motor de áudio:   {_MOTOR_AUDIO}")
    try:
        import audio_preprocessing
        pre = audio_preprocessing.status()
        print(f"  pré-processamento: RNNoise={pre['denoise']} "
              f"loudnorm={pre['normalize']} Silero={pre['vad']}")
        print(f"  recursos:         ffmpeg={pre['ffmpeg']} "
              f"rnnoise_model={pre['rnnoise_model']} "
              f"silero_model={pre['silero_model']}")
    except Exception as e:
        print(f"  pré-processamento: indisponível ({e})")

    print("\n-- conversão de formato --")
    # Meio segundo de senoide em 48k estéreo, pra provar que a conta fecha.
    import math
    import struct
    amostras = []
    quadros = int(TAXA_DISCORD * 0.5)
    for i in range(quadros):
        v = int(9000 * math.sin(2 * math.pi * 220 * i / TAXA_DISCORD))
        amostras.append(struct.pack("<hh", v, v))
    pcm = b"".join(amostras)
    print(f"  entrada: {len(pcm)} bytes "
          f"({len(pcm) / (TAXA_DISCORD * CANAIS_DISCORD * LARGURA):.2f}s "
          f"a 48k estéreo)")
    wav = _para_wav_16k(pcm)
    print(f"  saída:   {len(wav)} bytes de WAV 16k mono "
          f"(redução de {len(pcm) / len(wav):.1f}x)")
    with wave.open(io.BytesIO(wav)) as w:
        print(f"  conferindo: {w.getnchannels()} canal, "
              f"{w.getframerate()} Hz, {w.getsampwidth() * 8} bits, "
              f"{w.getnframes() / w.getframerate():.2f}s")

    print("\n-- filtro de alucinação do Whisper --")
    casos = [
        "Obrigado por assistir!",
        "obrigado por assistir",
        "Legendas pela comunidade Amara.org",
        "tchau tchau",
        "a",
        "",
        "   ",
        "emily o servidor tá on?",
        "vamo jogar hoje pessoal",
        "obrigado por assistir o vídeo que o vitor fez do servidor",
    ]
    for c in casos:
        limpo = _limpar(c)
        marca = "DESCARTA" if not limpo else "mantém  "
        print(f"  {marca} {c!r}")

    print("\n-- estado --")
    print("  " + estado().replace("\n", "\n  "))

    print("\n" + "=" * 66)
    print("Nada foi conectado: o diagnóstico só calcula.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())
