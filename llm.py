"""
llm.py — Camada única de acesso a LLM da Emily.

Por que esse arquivo existe
───────────────────────────
A Emily já trocou de provedor de LLM várias vezes (Ollama, Azure, Fireworks,
Bedrock, Puter). Cada troca exigiu reescrever a função de chamada inteira,
porque o formato de fio do provedor estava soldado dentro dela. O objetivo
aqui é que trocar de modelo passe a ser edição de UMA LINHA na tabela ROTAS.

Como está organizado
────────────────────
1. Mensagem canônica  — formato interno, independente de provedor
2. Provedor           — sabe traduzir o canônico pro formato de fio dele
3. ROTAS              — que modelo/parâmetros cada tarefa da Emily usa
4. Limitador          — token bucket compartilhado entre todas as threads
5. chamar()           — porta de entrada, com retry e log explícito

Regras que esse módulo segue
────────────────────────────
- Nunca engolir exceção em silêncio. Todo erro é logado com causa antes de
  subir. O bug mais difícil desse projeto sempre foi falha silenciosa.
- Rate limit é tratado, não ignorado. O free tier do NIM é 40 RPM e a Emily
  chama LLM de várias threads ao mesmo tempo.
- Nada de chave hardcoded. Tudo vem do .env.
"""

from __future__ import annotations

import base64
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from dotenv import load_dotenv

load_dotenv()


# ═════════════════════════════════════════════════════════════════
# ERROS
# ═════════════════════════════════════════════════════════════════

class ErroLLM(Exception):
    """Base de todos os erros dessa camada."""


class ErroConfiguracao(ErroLLM):
    """Falta chave de API, provedor desconhecido, rota inexistente."""


class ErroLimiteTaxa(ErroLLM):
    """429 — estourou o limite de requisições."""


class ErroTransporte(ErroLLM):
    """Falha de rede ou 5xx do provedor."""


class ErroResposta(ErroLLM):
    """O provedor respondeu, mas a resposta não tinha conteúdo utilizável."""


# ═════════════════════════════════════════════════════════════════
# LOG
# ═════════════════════════════════════════════════════════════════

# O resto do projeto usa print() com prefixo entre colchetes. Mantido
# por consistência, e porque a Emily roda com console visível.
DEBUG = os.getenv("EMILY_LLM_DEBUG", "0").strip() == "1"


def _log(msg: str) -> None:
    print(f"[LLM] {msg}")


def _log_debug(msg: str) -> None:
    if DEBUG:
        print(f"[LLM:debug] {msg}")


# ═════════════════════════════════════════════════════════════════
# MENSAGEM CANÔNICA
#
# Formato interno, independente de provedor. Os call sites do projeto
# mandam mensagem em três formatos históricos diferentes; normalizar
# tudo aqui é o que permite trocar o formato de fio sem tocar neles.
# ═════════════════════════════════════════════════════════════════

@dataclass
class Mensagem:
    papel: str                                  # "system" | "user" | "assistant"
    texto: str = ""
    imagens: List[Tuple[str, str]] = field(default_factory=list)  # [(media_type, base64)]

    def vazia(self) -> bool:
        return not self.texto and not self.imagens


def _extrair_imagem_de_data_url(url: str) -> Optional[Tuple[str, str]]:
    """Converte 'data:image/jpeg;base64,XXXX' em ('image/jpeg', 'XXXX')."""
    if not url.startswith("data:"):
        return None
    try:
        cabecalho, dados = url.split(",", 1)
        media_type = cabecalho.split(":", 1)[1].split(";", 1)[0]
        return (media_type or "image/jpeg", dados)
    except (ValueError, IndexError):
        return None


def normalizar_mensagens(messages: Sequence[dict]) -> List[Mensagem]:
    """
    Aceita os formatos que o projeto usa e devolve mensagens canônicas.

    Formatos aceitos:
      {"role": "user", "content": "texto"}
      {"role": "user", "content": "texto", "images": [b64, ...]}
      {"role": "user", "content": [{"type": "text", "text": ...},
                                   {"type": "image_url", "image_url": {"url": "data:..."}},
                                   {"type": "image", "source": {"type": "base64", ...}}]}
    """
    resultado: List[Mensagem] = []

    for msg in messages or []:
        papel = msg.get("role", "user")
        if papel not in ("system", "user", "assistant"):
            papel = "user"

        conteudo = msg.get("content")
        texto_partes: List[str] = []
        imagens: List[Tuple[str, str]] = []

        if isinstance(conteudo, list):
            for item in conteudo:
                if not isinstance(item, dict):
                    texto_partes.append(str(item))
                    continue
                tipo = item.get("type")
                if tipo == "text":
                    texto_partes.append(str(item.get("text") or ""))
                elif tipo == "image_url":
                    url = (item.get("image_url") or {}).get("url", "")
                    img = _extrair_imagem_de_data_url(url)
                    if img:
                        imagens.append(img)
                    elif url:
                        # URL remota: repassa como está, o provedor decide
                        imagens.append(("url", url))
                elif tipo == "image":
                    fonte = item.get("source") or {}
                    if fonte.get("type") == "base64" and fonte.get("data"):
                        imagens.append((fonte.get("media_type") or "image/jpeg", fonte["data"]))
        elif conteudo is not None:
            texto_partes.append(str(conteudo))

        # Convenção histórica do projeto: chave "images" separada do content
        for img in msg.get("images") or []:
            if isinstance(img, str):
                imagens.append(("image/jpeg", img))
            elif isinstance(img, (bytes, bytearray)):
                imagens.append(("image/jpeg", base64.b64encode(bytes(img)).decode()))
            elif isinstance(img, dict) and img.get("data"):
                imagens.append((img.get("media_type") or "image/jpeg", img["data"]))

        mensagem = Mensagem(papel=papel, texto="\n".join(p for p in texto_partes if p), imagens=imagens)
        if not mensagem.vazia():
            resultado.append(mensagem)

    return resultado


# ═════════════════════════════════════════════════════════════════
# LIMITADOR — token bucket compartilhado entre threads
#
# A Emily chama LLM do loop de voz, do loop de visão, do bot de Discord
# e da extração de memória em background, tudo em paralelo. Sem um
# limitador central, quatro threads independentes furam os 40 RPM juntas.
# ═════════════════════════════════════════════════════════════════

class Limitador:
    """Token bucket simples e thread-safe."""

    def __init__(self, por_minuto: int, nome: str = "global"):
        self.por_minuto = max(1, int(por_minuto))
        self.nome = nome
        self._capacidade = float(self.por_minuto)
        self._fichas = float(self.por_minuto)
        self._taxa = self.por_minuto / 60.0      # fichas por segundo
        self._ultimo = time.monotonic()
        self._cond = threading.Condition()

    def _repor(self) -> None:
        agora = time.monotonic()
        decorrido = agora - self._ultimo
        if decorrido > 0:
            self._fichas = min(self._capacidade, self._fichas + decorrido * self._taxa)
            self._ultimo = agora

    def adquirir(self, timeout: Optional[float] = None) -> bool:
        """
        Consome uma ficha, esperando se necessário.
        Retorna False se estourou o timeout sem conseguir.
        """
        limite = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                self._repor()
                if self._fichas >= 1.0:
                    self._fichas -= 1.0
                    return True

                falta = (1.0 - self._fichas) / self._taxa
                if limite is not None:
                    restante = limite - time.monotonic()
                    if restante <= 0:
                        return False
                    falta = min(falta, restante)

                _log_debug(f"limitador '{self.nome}' cheio, esperando {falta:.2f}s")
                self._cond.wait(timeout=falta)

    def devolver(self) -> None:
        """Devolve uma ficha (usado quando a chamada nem saiu do chão)."""
        with self._cond:
            self._repor()
            self._fichas = min(self._capacidade, self._fichas + 1.0)
            self._cond.notify()


# Free tier do NIM é 40 RPM e a NVIDIA não aumenta pra conta pessoal.
# Deixo margem de segurança porque o relógio deles não é o nosso.
RPM_PADRAO = int(os.getenv("EMILY_LLM_RPM", "36"))

_limitadores: Dict[str, Limitador] = {}
_lock_limitadores = threading.Lock()


def limitador_de(nome: str, por_minuto: int) -> Limitador:
    with _lock_limitadores:
        if nome not in _limitadores:
            _limitadores[nome] = Limitador(por_minuto, nome=nome)
        return _limitadores[nome]


# ═════════════════════════════════════════════════════════════════
# CONTROLE DE RACIOCÍNIO
#
# GLM-5.2 é modelo de raciocínio. Para assistente de VOZ, token de
# raciocínio é latência percebida direta — e pior: nas rotas com
# max_tokens minúsculo (triagem SIM/NAO usa 16) o raciocínio pode
# consumir o orçamento inteiro e devolver string vazia.
#
# O nome do parâmetro varia entre builds do NIM/vLLM, então NÃO é
# chutado: mandamos o que está configurado e, se o endpoint rejeitar
# com 400, aprendemos e paramos de mandar aquele parâmetro pra aquele
# modelo. O log diz exatamente o que aconteceu.
# ═════════════════════════════════════════════════════════════════

# Níveis aceitos nas rotas
RACIOCINIO_DESLIGADO = "desligado"
RACIOCINIO_MINIMO = "minimo"
RACIOCINIO_NORMAL = "normal"

# Como cada nível é expressado no corpo da requisição OpenAI-compatible.
#
# Estes valores foram DESCOBERTOS EMPIRICAMENTE contra o endpoint do NIM,
# não chutados. O que o teste mostrou com z-ai/glm-5.2:
#
#   reasoning_effort="none"                      -> 'OK' em 0,84s, 2 tokens
#   reasoning_effort="low"                       -> 'OK' em 2,33s, 2 tokens
#   sem parâmetro nenhum                         -> 'OK' em 2,56s, 2 tokens
#   chat_template_kwargs={"enable_thinking":False} -> 'OK' em 1,91s
#   chat_template_kwargs={"thinking": False}     -> QUEBRA: content=None,
#       raciocínio despejado em reasoning_content, finish_reason=length,
#       64 tokens queimados, 8,36s. A chave 'thinking' LIGA o raciocínio
#       em vez de desligar — o template reage à presença da chave, não ao
#       valor. Foi o que fez a triagem devolver string vazia.
#   {"reasoning": {"enabled": False}}            -> 400 Unsupported parameter
#
# Lição: 'chat_template_kwargs' com a chave 'thinking' é uma armadilha
# nesse build. Fica de fora. reasoning_effort é suportado e é o caminho.
PARAMS_RACIOCINIO: Dict[str, dict] = {
    RACIOCINIO_DESLIGADO: {
        "reasoning_effort": "none",
    },
    RACIOCINIO_MINIMO: {
        "reasoning_effort": "low",
    },
    RACIOCINIO_NORMAL: {},
}

# Parâmetros que um endpoint já rejeitou, por (provedor, modelo).
# Evita insistir em algo que sabemos que não existe naquele build.
_params_rejeitados: Dict[str, Set[str]] = {}
_lock_rejeitados = threading.Lock()


def _chave_rejeicao(provedor: str, modelo: str) -> str:
    return f"{provedor}::{modelo}"


def _params_validos(provedor: str, modelo: str, nivel: str) -> dict:
    base = PARAMS_RACIOCINIO.get(nivel, {})
    if not base:
        return {}
    with _lock_rejeitados:
        rejeitados = _params_rejeitados.get(_chave_rejeicao(provedor, modelo), set())
    return {k: v for k, v in base.items() if k not in rejeitados}


def _marcar_rejeitado(provedor: str, modelo: str, param: str) -> None:
    chave = _chave_rejeicao(provedor, modelo)
    with _lock_rejeitados:
        _params_rejeitados.setdefault(chave, set()).add(param)
    _log(
        f"o endpoint rejeitou o parâmetro '{param}' para {modelo}. "
        f"Não vou mandar de novo nessa sessão. Se o controle de raciocínio "
        f"importa nessa rota, ajuste PARAMS_RACIOCINIO em llm.py."
    )


def _param_desconhecido_no_erro(mensagem_erro: str, candidatos: Sequence[str]) -> Optional[str]:
    """
    Descobre qual parâmetro o endpoint reclamou, se algum.

    Cobre dois casos distintos, os dois vistos de verdade no NIM:

    1. Parâmetro que o build não conhece
       "Validation: Unsupported parameter(s): `reasoning`"

    2. Parâmetro que existe mas não aceita o VALOR enviado. O
       nvidia/nemotron-nano-12b-v2-vl aceita reasoning_effort, mas só
       'low', 'medium' ou 'high' — manda 'none' e ele devolve
       "Input should be 'low', 'medium' or 'high'". O GLM-5.2 aceita
       'none' numa boa. Ou seja: o valor válido varia por MODELO, não
       só por provedor.

    Nos dois casos a saída é a mesma: para de mandar aquele parâmetro
    para aquele modelo.
    """
    erro = (mensagem_erro or "").lower()
    pistas = (
        # parâmetro inexistente
        "unknown", "unexpected", "unrecognized", "not permitted",
        "extra inputs", "invalid_request", "does not support",
        "unsupported parameter",
        # valor inválido para um parâmetro que existe
        "input should be", "literal_error", "value_error",
        "must be one of", "is not one of", "permitted values",
    )
    if not any(p in erro for p in pistas):
        return None
    for candidato in candidatos:
        if candidato.lower() in erro:
            return candidato
    return None


# ═════════════════════════════════════════════════════════════════
# PROVEDORES
# ═════════════════════════════════════════════════════════════════

RespostaLLM = Union[str, Iterator[str]]


class Provedor:
    """Contrato que todo provedor implementa. Nada acima daqui conhece formato de fio."""

    nome = "base"

    def chamar(
        self,
        mensagens: List[Mensagem],
        modelo: str,
        max_tokens: Optional[int],
        temperatura: Optional[float],
        raciocinio: str,
        stream: bool,
    ) -> RespostaLLM:
        raise NotImplementedError


class ProvedorOpenAI(Provedor):
    """
    Provedor para qualquer endpoint compatível com a API da OpenAI:
    NVIDIA NIM, DeepSeek, Groq, OpenRouter, Fireworks, Together.
    É o caminho principal da Emily hoje.
    """

    def __init__(self, nome: str, base_url: str, env_chave: str, timeout: float = 90.0):
        self.nome = nome
        self.base_url = base_url
        self.env_chave = env_chave
        self.timeout = timeout
        self._cliente = None
        self._lock = threading.Lock()

    def _obter_cliente(self):
        if self._cliente is not None:
            return self._cliente
        with self._lock:
            if self._cliente is not None:
                return self._cliente
            chave = os.getenv(self.env_chave)
            if not chave:
                raise ErroConfiguracao(
                    f"provedor '{self.nome}' precisa da variável {self.env_chave} no .env "
                    f"e ela não está definida"
                )
            try:
                from openai import OpenAI
            except ImportError as e:
                raise ErroConfiguracao(
                    "o pacote 'openai' não está instalado. Rode: pip install openai"
                ) from e
            self._cliente = OpenAI(base_url=self.base_url, api_key=chave, timeout=self.timeout)
            _log(f"provedor '{self.nome}' conectado em {self.base_url}")
            return self._cliente

    def _montar_mensagens(self, mensagens: List[Mensagem]) -> List[dict]:
        saida = []
        for m in mensagens:
            if m.imagens:
                partes: List[dict] = []
                if m.texto:
                    partes.append({"type": "text", "text": m.texto})
                for media_type, dados in m.imagens:
                    url = dados if media_type == "url" else f"data:{media_type};base64,{dados}"
                    partes.append({"type": "image_url", "image_url": {"url": url}})
                saida.append({"role": m.papel, "content": partes})
            else:
                saida.append({"role": m.papel, "content": m.texto})
        return saida

    def chamar(
        self,
        mensagens: List[Mensagem],
        modelo: str,
        max_tokens: Optional[int],
        temperatura: Optional[float],
        raciocinio: str,
        stream: bool,
    ) -> RespostaLLM:
        cliente = self._obter_cliente()
        corpo = {
            "model": modelo,
            "messages": self._montar_mensagens(mensagens),
        }
        if max_tokens:
            corpo["max_tokens"] = max_tokens
        if temperatura is not None:
            corpo["temperature"] = temperatura

        extras = _params_validos(self.nome, modelo, raciocinio)
        # reasoning_effort é campo de primeira classe em alguns SDKs;
        # o resto vai em extra_body, que o SDK repassa cru.
        extra_body = {}
        for chave, valor in extras.items():
            if chave == "reasoning_effort":
                corpo["reasoning_effort"] = valor
            else:
                extra_body[chave] = valor
        if extra_body:
            corpo["extra_body"] = extra_body

        try:
            if stream:
                corpo["stream"] = True
                resposta = cliente.chat.completions.create(**corpo)
                return self._iterar_stream(resposta)

            resposta = cliente.chat.completions.create(**corpo)
            return self._texto_de(resposta)

        except Exception as e:
            self._tratar_erro(e, modelo, list(extras.keys()))
            raise  # _tratar_erro sempre levanta; isso é só pro type checker

    def _tratar_erro(self, e: Exception, modelo: str, params_enviados: Sequence[str]) -> None:
        texto = str(e)
        status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)

        # O endpoint pode não conhecer o parâmetro de raciocínio desse build.
        if status == 400 or "400" in texto:
            culpado = _param_desconhecido_no_erro(texto, params_enviados)
            if culpado:
                _marcar_rejeitado(self.nome, modelo, culpado)
                raise ErroTransporte(f"parâmetro '{culpado}' rejeitado, vou tentar sem ele") from e

        if status == 429 or "429" in texto or "rate limit" in texto.lower():
            raise ErroLimiteTaxa(f"429 do provedor '{self.nome}': {texto}") from e

        if status and 500 <= int(status) < 600:
            raise ErroTransporte(f"{status} do provedor '{self.nome}': {texto}") from e

        if status in (401, 403):
            raise ErroConfiguracao(
                f"provedor '{self.nome}' recusou a credencial ({status}). "
                f"Confira {self.env_chave} no .env."
            ) from e

        raise ErroTransporte(f"falha no provedor '{self.nome}': {texto}") from e

    @staticmethod
    def _texto_de(resposta) -> str:
        try:
            escolhas = resposta.choices
            if not escolhas:
                raise ErroResposta("resposta sem choices")
            escolha = escolhas[0]
            conteudo = escolha.message.content
        except AttributeError as e:
            raise ErroResposta(f"formato de resposta inesperado: {e}") from e

        if conteudo:
            return conteudo

        # Resposta vazia tem uma causa muito específica em modelo de
        # raciocínio: o orçamento de max_tokens foi todo consumido pensando,
        # e o texto de verdade nunca começou. Sem esse log, o sintoma que
        # chega no usuário é a Emily simplesmente emudecer.
        raciocinio = getattr(escolha.message, "reasoning_content", None)
        motivo = getattr(escolha, "finish_reason", "?")
        if raciocinio and motivo == "length":
            _log(
                "resposta vazia porque o modelo gastou TODO o max_tokens em "
                f"raciocínio (finish_reason={motivo}, {len(raciocinio)} chars pensando). "
                "Aumente o max_tokens dessa rota ou baixe o esforço de raciocínio."
            )
        elif motivo == "length":
            _log(f"resposta vazia com finish_reason=length — max_tokens curto demais")
        else:
            _log(f"resposta vazia do provedor (finish_reason={motivo})")
        return ""

    @staticmethod
    def _iterar_stream(resposta) -> Iterator[str]:
        try:
            for pedaco in resposta:
                if not getattr(pedaco, "choices", None):
                    continue
                delta = pedaco.choices[0].delta
                texto = getattr(delta, "content", None)
                if texto:
                    yield texto
        except Exception as e:
            # Stream que morre no meio não pode falhar calado: quem consome
            # só veria a Emily parar de falar sem motivo aparente.
            _log(f"stream interrompido no meio da resposta: {type(e).__name__}: {e}")
            raise ErroTransporte(f"stream interrompido: {e}") from e


class ProvedorAnthropic(Provedor):
    """
    Provedor Anthropic (usado hoje via Puter). Mantido vivo de propósito:
    é o plano B imediato se a personalidade da Emily não segurar no modelo
    novo. Trocar de volta é editar o campo 'provedor' da rota "conversa".
    """

    nome = "anthropic"

    def __init__(self, nome: str, base_url: Optional[str], env_chave: str, timeout: float = 90.0):
        self.nome = nome
        self.base_url = base_url
        self.env_chave = env_chave
        self.timeout = timeout
        self._cliente = None
        self._lock = threading.Lock()

    def _obter_cliente(self):
        if self._cliente is not None:
            return self._cliente
        with self._lock:
            if self._cliente is not None:
                return self._cliente
            chave = os.getenv(self.env_chave)
            if not chave:
                raise ErroConfiguracao(
                    f"provedor '{self.nome}' precisa de {self.env_chave} no .env"
                )
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ErroConfiguracao("pacote 'anthropic' não instalado") from e
            kwargs = {"api_key": chave, "timeout": self.timeout}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._cliente = Anthropic(**kwargs)
            _log(f"provedor '{self.nome}' conectado")
            return self._cliente

    def _montar(self, mensagens: List[Mensagem]) -> Tuple[Optional[str], List[dict]]:
        system: Optional[str] = None
        saida: List[dict] = []

        for m in mensagens:
            if m.papel == "system":
                system = m.texto if system is None else f"{system}\n\n{m.texto}"
                continue

            papel = "assistant" if m.papel == "assistant" else "user"
            blocos: List[dict] = []
            if m.texto:
                blocos.append({"type": "text", "text": m.texto})
            for media_type, dados in m.imagens:
                if media_type == "url":
                    blocos.append({"type": "image", "source": {"type": "url", "url": dados}})
                else:
                    blocos.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": dados},
                    })
            if not blocos:
                continue
            # A API da Anthropic exige alternância user/assistant
            if saida and saida[-1]["role"] == papel:
                saida[-1]["content"].extend(blocos)
            else:
                saida.append({"role": papel, "content": blocos})

        return system, saida

    def chamar(
        self,
        mensagens: List[Mensagem],
        modelo: str,
        max_tokens: Optional[int],
        temperatura: Optional[float],
        raciocinio: str,
        stream: bool,
    ) -> RespostaLLM:
        cliente = self._obter_cliente()
        system, msgs = self._montar(mensagens)
        corpo = {"model": modelo, "max_tokens": max_tokens or 4096, "messages": msgs}
        if system:
            corpo["system"] = system
        if temperatura is not None:
            corpo["temperature"] = temperatura

        try:
            if stream:
                return self._iterar_stream(cliente, corpo)
            resposta = cliente.messages.create(**corpo)
            return "".join(b.text for b in resposta.content if getattr(b, "type", None) == "text")
        except Exception as e:
            texto = str(e)
            status = getattr(e, "status_code", None)
            if status == 429 or "429" in texto:
                raise ErroLimiteTaxa(f"429 do provedor '{self.nome}': {texto}") from e
            if status in (401, 403):
                raise ErroConfiguracao(
                    f"provedor '{self.nome}' recusou a credencial ({status}). Confira {self.env_chave}."
                ) from e
            raise ErroTransporte(f"falha no provedor '{self.nome}': {texto}") from e

    @staticmethod
    def _iterar_stream(cliente, corpo) -> Iterator[str]:
        try:
            with cliente.messages.stream(**corpo) as fluxo:
                for texto in fluxo.text_stream:
                    if texto:
                        yield texto
        except Exception as e:
            _log(f"stream interrompido no meio da resposta: {type(e).__name__}: {e}")
            raise ErroTransporte(f"stream interrompido: {e}") from e


# ─────────────────────────────────────────────────────────────────
# Registro de provedores. Adicionar um novo endpoint OpenAI-compatible
# é acrescentar uma linha aqui.
# ─────────────────────────────────────────────────────────────────

PROVEDORES: Dict[str, Provedor] = {
    "nvidia": ProvedorOpenAI(
        nome="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        env_chave="NVIDIA_API_KEY",
    ),
    "groq": ProvedorOpenAI(
        nome="groq",
        base_url="https://api.groq.com/openai/v1",
        env_chave="GROQ_API_KEY",
    ),
    "fireworks": ProvedorOpenAI(
        nome="fireworks",
        base_url="https://api.fireworks.ai/inference/v1",
        env_chave="FIREWORKS_API_KEY",
    ),
    # Plano B: o caminho que a Emily usava antes dessa migração.
    "puter": ProvedorAnthropic(
        nome="puter",
        base_url="https://api.puter.com/puterai/anthropic",
        env_chave="PUTER_AUTH_TOKEN",
    ),
}


# ═════════════════════════════════════════════════════════════════
# MODELOS E ROTAS
#
# ESTA É A TABELA QUE O BRIEFING PEDIU. Trocar de modelo em qualquer
# tarefa da Emily é mudar uma linha daqui — sem tocar em modelo.py,
# automacao.py, agente_ui.py ou memoria.py.
# ═════════════════════════════════════════════════════════════════

# Texto puro. GLM-5.2 NÃO tem visão — daí a necessidade de dois modelos.
MODELO_TEXTO = os.getenv("EMILY_MODELO_TEXTO", "z-ai/glm-5.2")

# ─── Visão ───────────────────────────────────────────────────────
# Os dois Qwen3.5 VLM que o briefing indicava MORRERAM: o endpoint
# devolve 410 Gone. qwen3.5-397b-a17b saiu em 2026-07-27 e o
# qwen3.5-122b-a10b em 2026-07-20.
#
# Estes números vieram de medição real, com uma print 640x360 da tela
# do Vitor, pedindo descrição em português e uma triagem SIM/NAO:
#
#   modelo                                    descr.   tk prompt  triagem
#   nvidia/nemotron-nano-12b-v2-vl             2,00s       809     0,61s  <- escolhido
#   nvidia/llama-3.1-nemotron-nano-vl-8b-v1    1,25s     2.355     0,98s
#   meta/llama-3.2-11b-vision-instruct         1,52s     3.242     0,95s
#   meta/llama-3.2-90b-vision-instruct         2,55s     3.242     9,31s  (errou a triagem)
#   nvidia/nemotron-3-nano-omni-30b-a3b        32,84s      329     2,23s  (melhor leitura, lento)
#   google/gemma-4-31b-it                    129,36s      304     8,70s  (inviável)
#   google/gemma-3-12b-it, gemma-3-4b-it, microsoft/phi-3-vision  -> 404
#
# O nemotron-nano-12b-v2-vl ganha em tudo que importa aqui: é o mais
# rápido na triagem e gasta 4x menos token de prompt na MESMA imagem que
# os llama-3.2 — o que pesa direto no free tier de 40 RPM.
#
# Detalhe que vale saber: GET /v1/models lista modelos que devolvem 404
# quando você chama de verdade. A lista não é garantia de disponibilidade.
MODELO_VISAO = os.getenv("EMILY_MODELO_VISAO", "nvidia/nemotron-nano-12b-v2-vl")
MODELO_VISAO_RAPIDO = os.getenv("EMILY_MODELO_VISAO_RAPIDO", "nvidia/nemotron-nano-12b-v2-vl")

# ─── Visão do agente de UI ───────────────────────────────────────
# O agente de UI tem uma exigência diferente das outras rotas de visão:
# ele precisa APONTAR um lugar da tela com precisão, não descrever o que vê.
#
# Testado com a grade 10x10 desenhada na print, perguntando em que célula
# está um elemento conhecido (botão Iniciar, bandeja do sistema, barra de
# título), 12 amostras por modelo:
#
#   meta/llama-3.2-90b-vision-instruct   12/12 acertos
#   nvidia/nemotron-nano-12b-v2-vl        7/12 acertos
#
# O nemotron erra a coluna com frequência — acerta a linha e escorrega na
# horizontal. Num agente que clica, isso é clique no lugar errado.
#
# Custa mais: ~3.242 tokens de prompt contra 809 do nemotron. Mas o agente
# de UI roda ocasionalmente e sob supervisão, então precisão vale mais que
# custo aqui. As outras rotas de visão ficam no nemotron, que é barato e
# rápido e só precisa descrever.
MODELO_VISAO_AGENTE = os.getenv(
    "EMILY_MODELO_VISAO_AGENTE", "meta/llama-3.2-90b-vision-instruct"
)


@dataclass
class Rota:
    """Configuração de uma tarefa da Emily."""
    provedor: str
    modelo: str
    max_tokens: Optional[int] = None
    raciocinio: str = RACIOCINIO_DESLIGADO
    temperatura: Optional[float] = None
    rpm: int = RPM_PADRAO
    # Quantas tentativas no total (1 = sem retry)
    tentativas: int = 4

    def limitador(self) -> Limitador:
        # Um limitador por provedor: o teto de RPM é da conta, não da tarefa.
        return limitador_de(self.provedor, self.rpm)


ROTAS: Dict[str, Rota] = {
    # Conversa por voz. Raciocínio desligado: aqui token de pensamento é
    # silêncio no alto-falante. Temperatura alta pra personalidade variar.
    "conversa": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
    ),

    # Classificadores SIM/NAO e extração de JSON. Determinístico e curto.
    "classificador": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
    ),

    # Interpretação de comando e fallback de intenção: JSON estruturado.
    "comando": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
    ),

    # Extração de fatos pra memória. Roda em background, latência não importa.
    "extracao": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
    ),

    # Análise de tela de verdade — a que gera comentário pro Vitor.
    #
    # RACIOCINIO_NORMAL aqui significa "não manda parâmetro nenhum": o
    # nemotron-nano-vl não é modelo de raciocínio, e ele REJEITA
    # reasoning_effort='none' com 400 (só aceita low/medium/high). Usar
    # DESLIGADO nessas rotas custava um round-trip jogado fora até a
    # camada aprender a rejeição.
    "visao": Rota(
        provedor="nvidia", modelo=MODELO_VISAO,
        max_tokens=1024, raciocinio=RACIOCINIO_NORMAL, temperatura=0.7,
    ),

    # Triagem SIM/NAO de tela. Modelo rápido, saída minúscula.
    "triagem_visual": Rota(
        provedor="nvidia", modelo=MODELO_VISAO_RAPIDO,
        max_tokens=16, raciocinio=RACIOCINIO_NORMAL, temperatura=0.0,
    ),

    # Agente de UI: precisa de visão, decisão estruturada em JSON e, acima
    # de tudo, precisão para apontar onde clicar. Usa um modelo diferente
    # das outras rotas de visão por isso — ver MODELO_VISAO_AGENTE.
    "agente_ui": Rota(
        provedor="nvidia", modelo=MODELO_VISAO_AGENTE,
        max_tokens=1024, raciocinio=RACIOCINIO_NORMAL, temperatura=0.1,
    ),

    # Discord: respostas curtas de chat.
    "discord": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
    ),
}

ROTA_PADRAO = "conversa"


def rota(nome: str) -> Rota:
    if nome not in ROTAS:
        raise ErroConfiguracao(
            f"rota '{nome}' não existe. Rotas disponíveis: {', '.join(sorted(ROTAS))}"
        )
    return ROTAS[nome]


# ═════════════════════════════════════════════════════════════════
# RETRY E PORTA DE ENTRADA
# ═════════════════════════════════════════════════════════════════

ESPERA_BASE = 1.0      # segundos
ESPERA_MAXIMA = 20.0


def _espera_backoff(tentativa: int) -> float:
    """Exponencial com jitter, pra não sincronizar as threads no retry."""
    bruto = min(ESPERA_MAXIMA, ESPERA_BASE * (2 ** tentativa))
    return bruto * (0.5 + random.random() * 0.5)


def chamar(
    mensagens: Sequence[dict],
    rota_nome: str = ROTA_PADRAO,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    modelo: Optional[str] = None,
    temperatura: Optional[float] = None,
) -> RespostaLLM:
    """
    Porta de entrada única. Resolve a rota, respeita o rate limit,
    tenta de novo em 429/5xx com backoff, e loga tudo que der errado.

    max_tokens, modelo e temperatura sobrescrevem a rota quando informados.

    Levanta ErroLLM se todas as tentativas falharem. NÃO devolve None
    silenciosamente — falha silenciosa é o bug que essa camada existe
    pra matar.
    """
    cfg = rota(rota_nome)
    provedor = PROVEDORES.get(cfg.provedor)
    if provedor is None:
        raise ErroConfiguracao(
            f"provedor '{cfg.provedor}' da rota '{rota_nome}' não está registrado"
        )

    # Aceita tanto os dicts crus do projeto quanto mensagens já canônicas,
    # pra quem já normalizou (o adaptador em modelo.py) não pagar duas vezes.
    if mensagens and isinstance(mensagens[0], Mensagem):
        canonicas = list(mensagens)
    else:
        canonicas = normalizar_mensagens(mensagens)

    if not canonicas:
        raise ErroResposta(f"rota '{rota_nome}' recebeu lista de mensagens vazia")

    modelo_final = modelo or cfg.modelo
    tokens_final = max_tokens if max_tokens is not None else cfg.max_tokens
    temp_final = temperatura if temperatura is not None else cfg.temperatura
    limitador = cfg.limitador()

    ultimo_erro: Optional[Exception] = None

    for tentativa in range(cfg.tentativas):
        if not limitador.adquirir(timeout=60.0):
            _log(f"rota '{rota_nome}': esperei 60s por espaço no rate limit e não conseguiu")
            raise ErroLimiteTaxa(f"rota '{rota_nome}' não conseguiu ficha do limitador")

        try:
            inicio = time.monotonic()
            resultado = provedor.chamar(
                mensagens=canonicas,
                modelo=modelo_final,
                max_tokens=tokens_final,
                temperatura=temp_final,
                raciocinio=cfg.raciocinio,
                stream=stream,
            )
            if not stream:
                _log_debug(
                    f"rota '{rota_nome}' modelo '{modelo_final}' "
                    f"ok em {time.monotonic() - inicio:.2f}s"
                )
            return resultado

        except ErroConfiguracao:
            # Chave errada ou faltando não melhora com retry.
            raise

        except (ErroLimiteTaxa, ErroTransporte) as e:
            ultimo_erro = e
            if tentativa >= cfg.tentativas - 1:
                break
            espera = _espera_backoff(tentativa)
            _log(
                f"rota '{rota_nome}' tentativa {tentativa + 1}/{cfg.tentativas} falhou "
                f"({type(e).__name__}: {e}). Tentando de novo em {espera:.1f}s"
            )
            time.sleep(espera)

        except Exception as e:
            # Erro que o provedor não classificou. Loga com tipo e sobe.
            _log(f"rota '{rota_nome}' erro não classificado: {type(e).__name__}: {e}")
            raise ErroLLM(f"rota '{rota_nome}': {e}") from e

    _log(f"rota '{rota_nome}' esgotou as {cfg.tentativas} tentativas. Último erro: {ultimo_erro}")
    raise ErroLLM(f"rota '{rota_nome}' falhou após {cfg.tentativas} tentativas") from ultimo_erro


def chamar_texto(
    prompt: str,
    rota_nome: str = ROTA_PADRAO,
    system: Optional[str] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Atalho para o caso mais comum: um prompt, uma resposta de texto."""
    mensagens = []
    if system:
        mensagens.append({"role": "system", "content": system})
    mensagens.append({"role": "user", "content": prompt})
    resultado = chamar(mensagens, rota_nome=rota_nome, max_tokens=max_tokens, stream=False)
    return resultado if isinstance(resultado, str) else "".join(resultado)


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
#
# Rodar `python llm.py` testa a configuração contra o endpoint de
# verdade, sem precisar subir a Emily inteira.
# ═════════════════════════════════════════════════════════════════

def diagnosticar(verbose: bool = True) -> dict:
    """
    Testa cada rota contra o endpoint real e relata o que funcionou.
    Descobre empiricamente se o parâmetro de raciocínio é aceito,
    em vez de assumir.
    """
    relatorio = {}

    print("=" * 66)
    print("DIAGNÓSTICO DA CAMADA DE LLM DA EMILY")
    print("=" * 66)

    # 1. Credenciais presentes?
    print("\n[1] Credenciais no .env")
    envs = sorted({p.env_chave for p in PROVEDORES.values()})
    for env in envs:
        presente = bool(os.getenv(env))
        print(f"    {env:<24} {'presente' if presente else 'AUSENTE'}")
        relatorio[env] = presente

    # 2. Rotas
    print("\n[2] Tabela de rotas")
    for nome, cfg in ROTAS.items():
        print(f"    {nome:<16} {cfg.provedor:<10} {cfg.modelo:<28} "
              f"max_tokens={cfg.max_tokens} raciocinio={cfg.raciocinio}")

    # 3. Chamada real em TODAS as rotas.
    # Testar por modelo distinto não bastava: o que quebra é a combinação
    # de max_tokens com esforço de raciocínio, e isso é por rota.
    print("\n[3] Chamada real ao endpoint, rota por rota")

    imagem_teste = None
    try:
        import visao
        imagem_teste = visao.capturar_tela_triagem()
    except Exception as e:
        print(f"    (sem imagem de teste: {e})")

    modelos_de_visao = {MODELO_VISAO, MODELO_VISAO_RAPIDO}
    resultados = {}

    for nome, cfg in ROTAS.items():
        eh_visao = cfg.modelo in modelos_de_visao
        print(f"\n    rota '{nome}' -> {cfg.provedor} / {cfg.modelo}"
              f"  (max_tokens={cfg.max_tokens}, raciocinio={cfg.raciocinio})")

        if eh_visao and not imagem_teste:
            print("      PULADA: rota de visao e nao consegui capturar a tela")
            resultados[nome] = {"ok": False, "erro": "sem imagem de teste"}
            continue

        if eh_visao:
            pergunta = "Responda apenas com a palavra OK. Ignore a imagem."
            mensagens = [{
                "role": "user",
                "content": pergunta,
                "images": [imagem_teste],
            }]
        else:
            mensagens = [{"role": "user", "content": "Responda apenas com a palavra OK."}]

        try:
            inicio = time.monotonic()
            # Usa o max_tokens DA ROTA de propósito, pra pegar exatamente o
            # caso em que o orçamento é curto e o raciocínio come tudo.
            resposta = chamar(mensagens, rota_nome=nome, stream=False)
            decorrido = time.monotonic() - inicio
            limpo = (resposta if isinstance(resposta, str) else "").strip()
            ok = bool(limpo)
            print(f"      resposta: {limpo[:70]!r}")
            print(f"      latencia: {decorrido:.2f}s")
            print(f"      status:   {'OK' if ok else 'VAZIO'}")
            resultados[nome] = {"ok": ok, "latencia": decorrido, "resposta": limpo}
        except ErroLLM as e:
            print(f"      FALHOU: {type(e).__name__}: {e}")
            resultados[nome] = {"ok": False, "erro": str(e)}
        except Exception as e:
            print(f"      FALHOU (nao classificado): {type(e).__name__}: {e}")
            resultados[nome] = {"ok": False, "erro": str(e)}

    relatorio["rotas"] = resultados

    # 3b. A personalidade sobreviveu? Sinal de fumaça, não substitui o
    # teste de 10 minutos de conversa que só o Vitor pode fazer.
    print("\n[3b] Amostra de personalidade na rota 'conversa'")
    try:
        import modelo as _mdl
        amostra = chamar(
            [
                {"role": "system", "content": _mdl.system_prompt},
                {"role": "user", "content": "Emily, acabei de deletar a pasta errada sem querer."},
            ],
            rota_nome="conversa",
        )
        texto = amostra if isinstance(amostra, str) else "".join(amostra)
        print(f"      {texto.strip()[:400]!r}")
        problemas = []
        if any(m in texto for m in ("**", "##", "- ", "* ")):
            problemas.append("markdown/lista")
        if any(ord(c) > 0x2500 for c in texto):
            problemas.append("possivel emoji")
        print(f"      sinais de degradacao: {', '.join(problemas) if problemas else 'nenhum'}")
        relatorio["personalidade"] = {"texto": texto, "problemas": problemas}
    except Exception as e:
        print(f"      FALHOU: {type(e).__name__}: {e}")
        relatorio["personalidade"] = {"erro": str(e)}

    # 4. O que o endpoint rejeitou
    print("\n[4] Parametros de raciocinio rejeitados pelo endpoint")
    with _lock_rejeitados:
        if not _params_rejeitados:
            print("    nenhum — os parametros configurados foram aceitos")
        else:
            for chave, params in _params_rejeitados.items():
                print(f"    {chave}: {', '.join(sorted(params))}")
    relatorio["params_rejeitados"] = {k: sorted(v) for k, v in _params_rejeitados.items()}

    print("\n" + "=" * 66)
    return relatorio


if __name__ == "__main__":
    diagnosticar()
