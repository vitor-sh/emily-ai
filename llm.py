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
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union, TYPE_CHECKING

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:
    genai = None

if TYPE_CHECKING:
    from google.genai import types
else:
    types = None

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
    papel: str                                  # "system" | "user" | "assistant" | "tool"
    texto: str = ""
    imagens: List[Tuple[str, str]] = field(default_factory=list)  # [(media_type, base64)]
    # Mensagem já no formato de fio, usada pelo laço de ferramentas: o turno
    # do assistente que pediu a ferramenta e o turno com o resultado dela
    # têm campos próprios (tool_calls, tool_call_id) que não cabem no
    # formato canônico. Quando 'bruta' vem preenchida, o provedor a repassa
    # sem tocar.
    bruta: Optional[dict] = None

    def vazia(self) -> bool:
        return not self.texto and not self.imagens and self.bruta is None


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

        # Turnos do laço de ferramentas passam intactos: 'tool' carrega
        # tool_call_id e o turno do assistente carrega tool_calls.
        if papel == "tool" or "tool_calls" in msg:
            resultado.append(Mensagem(papel=papel, bruta=dict(msg)))
            continue

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

    def fichas_livres(self) -> float:
        """
        Quantas fichas há agora, SEM consumir nenhuma.

        Existe para quem pode desistir de chamar. O balde é por provedor, então
        todas as rotas dividem o mesmo teto, e adquirir() espera até 60s quando
        ele está vazio — o que na prática significa uma thread parada.

        Medido em uso real: o chat do Minecraft consumindo fichas deixou o
        Discord esperando, e do lado de fora parecia que a Emily tinha ignorado
        quem falou com ela. Consumidor de conversa (jogo) agora espia isto antes
        e fica quieto quando a cota está apertada, guardando o balde para quem
        não pode esperar (Discord, administração).
        """
        with self._cond:
            self._repor()
            return self._fichas


# Free tier do NIM é 40 RPM e a NVIDIA não aumenta pra conta pessoal.
# Deixo margem de segurança porque o relógio deles não é o nosso.
RPM_PADRAO = int(os.getenv("EMILY_LLM_RPM", "36"))

# O plano pago do Kiro não publica teto de requisições por minuto — o que
# ele cobra é crédito por chamada, com multiplicador por modelo. Este balde
# existe para proteger contra rajada acidental (o laço de triagem de tela
# dispara de várias threads), não para respeitar um limite conhecido.
RPM_KIRO = int(os.getenv("EMILY_KIRO_RPM", "30"))

_limitadores: Dict[str, Limitador] = {}
_lock_limitadores = threading.Lock()


def limitador_de(nome: str, por_minuto: int) -> Limitador:
    with _lock_limitadores:
        if nome not in _limitadores:
            _limitadores[nome] = Limitador(por_minuto, nome=nome)
        return _limitadores[nome]


def folga_da_rota(rota: str) -> float:
    """
    Fichas livres no balde que essa rota usa. Não consome nada.

    Serve para o chamador decidir se vale a pena chamar. Devolve um número alto
    quando não dá para saber, porque na dúvida é melhor tentar a chamada do que
    ficar mudo por causa de uma medição que falhou.
    """
    try:
        cfg = ROTAS.get(rota)
        if cfg is None:
            return 999.0
        return cfg.limitador(rota).fichas_livres()
    except Exception as e:
        _log(f"não consegui medir a folga da rota '{rota}': {e}")
        return 999.0


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


# ═════════════════════════════════════════════════════════════════
# TOOL CALLING
#
# O modelo recebe o catálogo de ferramentas e decide sozinho qual
# chamar, em vez de a Emily depender de palavra-chave e de um
# classificador de intenção separado.
#
# Confirmado empiricamente contra o NIM com z-ai/glm-5.2:
#   - aceita 'tools' e 'tool_choice'
#   - escolhe a ferramenta certa e monta os argumentos ("quanto custa
#     uma RTX 5090" virou consulta="preço RTX 5090 Brasil")
#   - NÃO chama ferramenta quando é conversa pura
#   - fecha o ciclo: tool_call -> resultado -> resposta final na voz dela
#   - funciona com stream=True, e o delta de tool_call chega antes do
#     primeiro token de texto, o que permite decidir no meio do fluxo
# ═════════════════════════════════════════════════════════════════

@dataclass
class ChamadaFerramenta:
    """Um pedido do modelo para executar uma ferramenta."""
    id: str
    nome: str
    argumentos: str = "{}"      # JSON cru, como o modelo mandou
    thought_signature: Optional[str] = None

    def args(self) -> dict:
        """Interpreta os argumentos, devolvendo {} se o modelo mandar JSON torto."""
        try:
            dados = json.loads(self.argumentos or "{}")
            return dados if isinstance(dados, dict) else {}
        except (json.JSONDecodeError, TypeError):
            _log(f"argumentos invalidos da ferramenta '{self.nome}': {self.argumentos!r}")
            return {}


@dataclass
class Resposta:
    """Resposta do modelo quando há ferramentas na jogada."""
    texto: str = ""
    chamadas: List[ChamadaFerramenta] = field(default_factory=list)

    def quer_ferramenta(self) -> bool:
        return bool(self.chamadas)


class Provedor:
    """Contrato que todo provedor implementa. Nada acima daqui conhece formato de fio."""

    nome = "base"
    suporta_ferramentas = False

    def chamar(
        self,
        mensagens: List[Mensagem],
        modelo: str,
        max_tokens: Optional[int],
        temperatura: Optional[float],
        raciocinio: str,
        stream: bool,
        ferramentas: Optional[List[dict]] = None,
        obrigar_ferramenta: bool = False,
        proibir_ferramenta: bool = False,
    ) -> RespostaLLM:
        raise NotImplementedError


class ProvedorOpenAI(Provedor):
    """
    Provedor para qualquer endpoint compatível com a API da OpenAI:
    NVIDIA NIM, DeepSeek, Groq, OpenRouter, Fireworks, Together.
    É o caminho principal da Emily hoje.
    """

    suporta_ferramentas = True

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
            # Mensagens de ferramenta e de tool_call têm forma própria e
            # passam direto, sem virar bloco de texto.
            if m.bruta is not None:
                saida.append(m.bruta)
                continue
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
        ferramentas: Optional[List[dict]] = None,
        obrigar_ferramenta: bool = False,
        proibir_ferramenta: bool = False,
    ) -> RespostaLLM:
        cliente = self._obter_cliente()
        corpo = {
            "model": modelo,
            "messages": self._montar_mensagens(mensagens),
        }
        if ferramentas:
            corpo["tools"] = ferramentas
            # 'required' obriga o modelo a escolher alguma ferramenta. Usado
            # como segunda tentativa quando ele responde anunciando a ação em
            # vez de executá-la.
            #
            # 'none' mantém o catálogo declarado e proíbe o uso. Parece o mesmo
            # que mandar a lista vazia, e NÃO é: o gateway do Kiro, quando a
            # requisição não declara tools, converte o histórico de ferramentas
            # em TEXTO ("[Tool: nome (id)]\n{args}") pra não perder o contexto.
            # O modelo lê isso como o formato das falas dele e imita — foi assim
            # que a Emily mandou "[Tool: gerenciar_mod_launcher_mc (toolu_...)]"
            # como mensagem no Discord. Com tools declarado, o histórico segue
            # estruturado e não há formato nenhum pra imitar.
            if obrigar_ferramenta:
                corpo["tool_choice"] = "required"
            elif proibir_ferramenta:
                corpo["tool_choice"] = "none"
            else:
                corpo["tool_choice"] = "auto"
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
                # Com ferramentas na jogada, quem consome precisa poder
                # descobrir se veio texto ou pedido de ferramenta.
                if ferramentas:
                    return FluxoComFerramentas(resposta)
                return self._iterar_stream(resposta)

            resposta = cliente.chat.completions.create(**corpo)
            if ferramentas:
                return self._resposta_de(resposta)
            return self._texto_de(resposta)

        except Exception as e:
            self._tratar_erro(e, modelo, list(extras.keys()))
            raise  # _tratar_erro sempre levanta; isso é só pro type checker

    @staticmethod
    def _resposta_de(resposta) -> Resposta:
        """Extrai texto e pedidos de ferramenta de uma resposta não-streamada."""
        try:
            escolha = resposta.choices[0]
            msg = escolha.message
        except (AttributeError, IndexError) as e:
            raise ErroResposta(f"formato de resposta inesperado: {e}") from e

        chamadas = []
        for c in (getattr(msg, "tool_calls", None) or []):
            try:
                chamadas.append(ChamadaFerramenta(
                    id=c.id,
                    nome=c.function.name,
                    argumentos=c.function.arguments or "{}",
                ))
            except AttributeError as e:
                _log(f"tool_call malformada, ignorando: {e}")

        return Resposta(texto=msg.content or "", chamadas=chamadas)

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


class FluxoComFerramentas:
    """
    Envolve um stream que pode virar texto OU pedido de ferramenta.

    O problema: quando o modelo tem ferramentas disponíveis, só dá pra saber
    o que ele decidiu depois que os primeiros deltas chegam. Mas a Emily é
    assistente de voz e não pode esperar a resposta inteira pra começar a
    falar.

    A solução: consumir o stream até o primeiro sinal, guardando o que veio,
    e então expor o resultado. Medido no NIM, o delta de tool_call chega em
    ~0,45s e o primeiro token de texto em ~0,80s, então a espera é curta.

    Uso correto (a releitura de .chamadas no fim NÃO é opcional):
        fluxo = ...
        if fluxo.quer_ferramenta():
            for c in fluxo.chamadas: ...
        else:
            for pedaco in fluxo.texto(): ...
            # O modelo pode ter pedido ferramenta DEPOIS do texto.
            for c in fluxo.chamadas: ...
    """

    # Quantos caracteres não-brancos de texto o modelo precisa escrever antes
    # de a camada concluir "isso é resposta em texto". Preâmbulo curto seguido
    # de tool_call ("Peraí, vou olhar.") cabe embaixo desse teto, então a
    # ferramenta é detectada sem esperar a resposta inteira. Se o preâmbulo
    # passar disso, o texto começa a ser falado e a ferramenta ainda é
    # executada — só não dá pra decidir antes de ouvir.
    _CHARS_PARA_DECIDIR = 80

    def __init__(self, stream_bruto):
        self._stream = stream_bruto
        self._buffer: List[str] = []
        self._parciais: Dict[int, dict] = {}   # índice -> {id, nome, args}
        self._decidido = False
        self._esgotado = False

    def _proximo_pedaco(self) -> Optional[str]:
        """Consome um evento do stream. Devolve texto se houver, senão None."""
        try:
            pedaco = next(self._stream)
        except StopIteration:
            self._esgotado = True
            return None
        except Exception as e:
            self._esgotado = True
            _log(f"stream com ferramentas interrompido: {type(e).__name__}: {e}")
            raise ErroTransporte(f"stream interrompido: {e}") from e

        if not getattr(pedaco, "choices", None):
            return None
        delta = pedaco.choices[0].delta

        for tc in (getattr(delta, "tool_calls", None) or []):
            idx = getattr(tc, "index", 0) or 0
            alvo = self._parciais.setdefault(idx, {"id": "", "nome": "", "args": ""})
            if getattr(tc, "id", None):
                alvo["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    alvo["nome"] = fn.name
                if getattr(fn, "arguments", None):
                    alvo["args"] += fn.arguments

        return getattr(delta, "content", None) or None

    def _decidir(self) -> None:
        """
        Consome até saber se é texto ou ferramenta.

        REGRA: texto antes do tool_call NÃO significa que não há tool_call.
        O GLM (como qualquer modelo treinado no formato Hermes) costuma
        escrever um preâmbulo — "Peraí, vou olhar sua tela." — e SÓ DEPOIS
        emitir o tool_call. A versão anterior decidia no primeiro delta de
        texto e devolvia quer_ferramenta()=False; o tool_call chegava depois,
        era parseado em _parciais e ninguém lia. Resultado: a Emily falava
        "vou olhar sua tela" e não olhava, porque a chamada tinha sido
        jogada no lixo pela própria camada, não pelo modelo.

        Pior: modelo GLM em streaming abre a resposta com um "\\n" sozinho.
        Isso bastava pra derrubar a decisão inteira. Por isso espaço em
        branco não decide nada aqui.
        """
        if self._decidido:
            return
        uteis = 0
        while not self._esgotado:
            texto = self._proximo_pedaco()
            # Ferramenta tem prioridade: se apareceu tool_call, a decisão está
            # tomada, mesmo que já tenha vindo texto antes.
            if self._parciais:
                break
            if texto:
                self._buffer.append(texto)
                # Só caractere de verdade conta. "\n" e " " não decidem.
                uteis += len(texto.strip())
                if uteis >= self._CHARS_PARA_DECIDIR:
                    break
        self._decidido = True

    def quer_ferramenta(self) -> bool:
        """
        True se o modelo pediu ferramenta antes de escrever texto relevante.

        False NÃO garante ausência de ferramenta: o tool_call pode vir depois
        do preâmbulo. Quem consome precisa reler .chamadas depois de esgotar
        .texto() — é o que o laço em modelo.py faz.
        """
        self._decidir()
        return bool(self._parciais)

    @property
    def preambulo(self) -> str:
        """Texto que o modelo escreveu antes de pedir a ferramenta."""
        return "".join(self._buffer)

    @property
    def chamadas(self) -> List[ChamadaFerramenta]:
        """Termina de consumir o stream e devolve os pedidos de ferramenta."""
        self._decidir()
        while not self._esgotado:
            self._proximo_pedaco()
        saida = []
        for idx in sorted(self._parciais):
            p = self._parciais[idx]
            if p["nome"]:
                saida.append(ChamadaFerramenta(
                    id=p["id"] or f"chamada_{idx}",
                    nome=p["nome"],
                    argumentos=p["args"] or "{}",
                ))
        return saida

    def texto(self) -> Iterator[str]:
        """Gera o texto da resposta, incluindo o que foi consumido na decisão."""
        self._decidir()
        for pedaco in self._buffer:
            yield pedaco
        self._buffer = []
        while not self._esgotado:
            pedaco = self._proximo_pedaco()
            if pedaco:
                yield pedaco


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
        ferramentas: Optional[List[dict]] = None,
        obrigar_ferramenta: bool = False,
        proibir_ferramenta: bool = False,
    ) -> RespostaLLM:
        if ferramentas:
            # O formato de ferramenta da Anthropic é outro. Este provedor está
            # aqui como plano B de conversa; se for preciso tool calling nele,
            # implementar a conversão em _montar em vez de falhar quieto.
            raise ErroConfiguracao(
                f"provedor '{self.nome}' ainda não implementa tool calling. "
                f"Use um provedor OpenAI-compatible nessa rota."
            )
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


class FluxoComFerramentasGemini:
    """Mesma lógica de FluxoComFerramentas, adaptada para os chunks de genai.types.GenerateContentResponse"""
    _CHARS_PARA_DECIDIR = 80

    def __init__(self, stream_bruto):
        self._stream = stream_bruto
        self._buffer: List[str] = []
        self._parciais: List[dict] = []   # chamadas em andamento
        self._decidido = False
        self._esgotado = False

    def _proximo_pedaco(self) -> Optional[str]:
        try:
            pedaco = next(self._stream)
        except StopIteration:
            self._esgotado = True
            return None
        except Exception as e:
            self._esgotado = True
            _log(f"stream gemini interrompido: {type(e).__name__}: {e}")
            raise ErroTransporte(f"stream interrompido: {e}") from e
        
        # O Pydantic Parse do Google GenAI muitas vezes esconde o Part dentro dos candidates
        if getattr(pedaco, "candidates", None) and pedaco.candidates[0].content:
            for part in pedaco.candidates[0].content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    ts = getattr(part, "thought_signature", None)
                    print(f"[DEBUG Vertex Stream] Recebido function_call: {fc.name}, thought_signature={ts}")
                    self._parciais.append({
                        "id": "",
                        "nome": fc.name,
                        "args": json.dumps(fc.args) if fc.args else "{}",
                        "thought_signature": ts
                    })
                
        return getattr(pedaco, "text", None) or None

    def _decidir(self) -> None:
        if self._decidido:
            return
        uteis = 0
        while not self._esgotado:
            texto = self._proximo_pedaco()
            if self._parciais:
                break
            if texto:
                self._buffer.append(texto)
                uteis += len(texto.strip())
                if uteis >= self._CHARS_PARA_DECIDIR:
                    break
        self._decidido = True

    def quer_ferramenta(self) -> bool:
        self._decidir()
        return bool(self._parciais)

    @property
    def preambulo(self) -> str:
        return "".join(self._buffer)

    @property
    def chamadas(self) -> List[ChamadaFerramenta]:
        self._decidir()
        while not self._esgotado:
            self._proximo_pedaco()
        saida = []
        for i, p in enumerate(self._parciais):
            saida.append(ChamadaFerramenta(
                id=f"chamada_{i}",
                nome=p["nome"],
                argumentos=p["args"],
                thought_signature=p.get("thought_signature")
            ))
        return saida

    def texto(self) -> Iterator[str]:
        self._decidir()
        for pedaco in self._buffer:
            yield pedaco
        self._buffer = []
        while not self._esgotado:
            pedaco = self._proximo_pedaco()
            if pedaco:
                yield pedaco


class ProvedorVertexGemini(Provedor):
    nome = "vertex"
    suporta_ferramentas = True

    def __init__(self, timeout: float = 90.0):
        self.timeout = timeout
        self._cliente = None
        self._lock = threading.Lock()

    def _obter_cliente(self):
        if self._cliente is not None:
            return self._cliente
        with self._lock:
            if self._cliente is not None:
                return self._cliente
            if genai is None:
                raise ErroConfiguracao("pacote 'google-genai' não está instalado")
            
            project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
            location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
            
            if not project_id:
                raise ErroConfiguracao("provedor 'vertex' precisa da variável GOOGLE_CLOUD_PROJECT")
            
            try:
                self._cliente = genai.Client(vertexai=True, project=project_id, location=location)
                _log(f"provedor 'vertex' conectado no projeto {project_id} ({location})")
                return self._cliente
            except Exception as e:
                raise ErroConfiguracao(f"falha ao conectar no Vertex AI: {e}") from e

    def _montar_mensagens(self, mensagens: List[Mensagem]) -> Tuple[Optional[str], List["types.Content"]]:
        if types is None:
            from google.genai import types as _types
            t = _types
        else:
            t = types
            
        saida = []
        system = None

        for m in mensagens:
            if m.bruta is not None:
                if m.papel == "tool" or m.bruta.get("role") == "tool":
                    name = m.bruta.get("name", "unknown")
                    content = m.bruta.get("content", "")
                    try:
                        content_dict = json.loads(content) if content.startswith("{") else {"result": content}
                    except:
                        content_dict = {"result": content}
                    
                    saida.append(t.Content(
                        role="user",
                        parts=[t.Part.from_function_response(name=name, response=content_dict)]
                    ))
                    continue

                if "tool_calls" in m.bruta:
                    partes = []
                    if m.bruta.get("content"):
                        partes.append(t.Part.from_text(text=m.bruta["content"]))
                    for tc in m.bruta["tool_calls"]:
                        if tc.get("type") == "function":
                            fn = tc["function"]
                            try:
                                args = json.loads(fn.get("arguments", "{}"))
                            except:
                                args = {}
                            part = t.Part.from_function_call(name=fn["name"], args=args)
                            ts_b64 = tc.get("thought_signature")
                            print(f"[DEBUG Vertex] Reconstruindo tool_call {fn['name']}, thought_signature b64 do historico: {ts_b64}")
                            if ts_b64:
                                part.thought_signature = base64.b64decode(ts_b64)
                            print(f"[DEBUG Vertex] Part reconstruida tem thought_signature? {getattr(part, 'thought_signature', None) is not None}")
                            partes.append(part)
                    
                    if partes:
                        saida.append(t.Content(role="model", parts=partes))
                    continue

            if m.papel == "system":
                system = m.texto if system is None else f"{system}\n\n{m.texto}"
                continue
            
            papel = "model" if m.papel == "assistant" else "user"
            partes = []
            
            if m.texto:
                partes.append(t.Part.from_text(text=m.texto))
                
            for media_type, dados in m.imagens:
                if media_type != "url":
                    b_dados = base64.b64decode(dados)
                    partes.append(t.Part.from_bytes(data=b_dados, mime_type=media_type))
            
            if partes:
                saida.append(t.Content(role=papel, parts=partes))
                
        return system, saida

    def chamar(self, mensagens: List[Mensagem], modelo: str, max_tokens: Optional[int], 
               temperatura: Optional[float], raciocinio: str, stream: bool, 
               ferramentas: Optional[List[dict]] = None, obrigar_ferramenta: bool = False, 
               proibir_ferramenta: bool = False) -> RespostaLLM:
        cliente = self._obter_cliente()
        system, contents = self._montar_mensagens(mensagens)
        
        config_kwargs = {}
        if system:
            config_kwargs["system_instruction"] = system
        if types is None:
            from google.genai import types as _types
            t = _types
        else:
            t = types

        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens
        if temperatura is not None:
            config_kwargs["temperature"] = temperatura

        if raciocinio == RACIOCINIO_DESLIGADO:
            config_kwargs["thinking_config"] = t.ThinkingConfig(thinking_budget=0)
        elif raciocinio == RACIOCINIO_MINIMO:
            config_kwargs["thinking_config"] = t.ThinkingConfig(thinking_budget=16)


        if raciocinio == RACIOCINIO_DESLIGADO:
            config_kwargs["thinking_config"] = t.ThinkingConfig(thinking_budget=0)
        elif raciocinio == RACIOCINIO_MINIMO:
            config_kwargs["thinking_config"] = t.ThinkingConfig(thinking_budget=16)
            
        if ferramentas and not proibir_ferramenta:
            gemini_tools = []
            for f in ferramentas:
                if f.get("type") == "function":
                    func = f["function"]
                    gemini_tools.append(t.Tool(
                        function_declarations=[
                            t.FunctionDeclaration(
                                name=func["name"],
                                description=func.get("description", ""),
                                parameters=func.get("parameters") 
                            )
                        ]
                    ))
            if gemini_tools:
                config_kwargs["tools"] = gemini_tools
                
        if types is None:
            from google.genai import types as _types
            t = _types
        else:
            t = types
            
        config = t.GenerateContentConfig(**config_kwargs)

        try:
            if stream:
                resposta = cliente.models.generate_content_stream(model=modelo, contents=contents, config=config)
                if ferramentas:
                    return FluxoComFerramentasGemini(resposta)
                return self._iterar_stream(resposta)

            resposta = cliente.models.generate_content(model=modelo, contents=contents, config=config)
            if ferramentas:
                return self._resposta_de(resposta)
            return self._texto_de(resposta)

        except Exception as e:
            texto = str(e)
            if "429" in texto:
                raise ErroLimiteTaxa(f"429 do provedor 'vertex': {texto}") from e
            raise ErroTransporte(f"falha no provedor 'vertex': {texto}") from e

    @staticmethod
    def _resposta_de(resposta) -> Resposta:
        chamadas = []
        if getattr(resposta, "candidates", None) and resposta.candidates[0].content:
            for i, part in enumerate(resposta.candidates[0].content.parts):
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    ts = getattr(part, "thought_signature", None)
                    print(f"[DEBUG Vertex Não-Stream] Recebido function_call: {fc.name}, thought_signature={ts}")
                    chamadas.append(ChamadaFerramenta(
                        id=f"chamada_{i}",
                        nome=fc.name,
                        argumentos=json.dumps(fc.args) if fc.args else "{}",
                        thought_signature=ts
                    ))
        return Resposta(texto=getattr(resposta, "text", "") or "", chamadas=chamadas)

    @staticmethod
    def _texto_de(resposta) -> str:
        return getattr(resposta, "text", "") or ""

    @staticmethod
    def _iterar_stream(resposta) -> Iterator[str]:
        try:
            for pedaco in resposta:
                t = getattr(pedaco, "text", None)
                if t:
                    yield t
        except Exception as e:
            _log(f"stream vertex interrompido: {e}")
            raise ErroTransporte(f"stream interrompido: {e}") from e


class ProvedorKiro(ProvedorOpenAI):
    """
    O gateway local do Kiro: os modelos Claude do plano pago do Vitor
    expostos numa API OpenAI-compatible por um proxy em 127.0.0.1.

    Herda o ProvedorOpenAI inteiro — formato de fio, streaming, tool calling
    e classificação de erro são idênticos, porque o gateway fala OpenAI de
    verdade. A única coisa que muda é que este endpoint não existe até
    alguém subir o subprocesso.

    Por que sobrescreve chamar() e não _obter_cliente()
    ───────────────────────────────────────────────────
    O cliente é cacheado: _obter_cliente() roda UMA vez por sessão. Se a
    garantia do gateway morasse lá, um gateway que caísse no meio da tarde
    nunca seria religado — a Emily emudeceria até reiniciar. Em chamar(), a
    garantia roda em toda chamada, e é barata porque o gateway.py mantém o
    último /health em cache com TTL.

    Falha de gateway sai como ErroConfiguracao de propósito: é a única
    classe que o chamar() NÃO repete. Gateway fora do ar não melhora com
    backoff, e quatro tentativas de 300s deixariam a Emily muda por vinte
    minutos em vez de avisar o Vitor em dois segundos.
    """

    nome = "kiro"

    # O aviso de gateway.py ausente é impresso uma vez, não a cada chamada.
    _avisou_sem_modulo = False

    def _garantir_gateway(self) -> None:
        """
        Garante que o proxy está no ar antes de qualquer I/O.

        O import é lazy e tolerante de propósito: o llm.py precisa continuar
        importável (e o `python llm.py` precisa continuar rodando) mesmo sem
        o gateway.py — que é o caso enquanto a Task 3 não existir, e também
        se alguém copiar o llm.py para outro projeto.
        """
        try:
            import gateway  # noqa: PLC0415  (lazy de propósito, evita ciclo de import)
        except ImportError:
            if not ProvedorKiro._avisou_sem_modulo:
                ProvedorKiro._avisou_sem_modulo = True
                _log(
                    "gateway.py não encontrado: não vou subir nem checar o proxy. "
                    "Se as chamadas falharem com conexão recusada, suba o gateway "
                    "à mão (python main.py dentro de kiro_gateway)."
                )
            return

        try:
            gateway.garantir()
        except gateway.ErroGateway as e:
            # ErroConfiguracao porque o retry de chamar() não repete essa classe.
            raise ErroConfiguracao(
                f"gateway do Kiro indisponível ({e.motivo}): {e.detalhe}"
            ) from e

    def chamar(self, **kwargs) -> RespostaLLM:
        self._garantir_gateway()
        return super().chamar(**kwargs)


# ─────────────────────────────────────────────────────────────────
# Registro de provedores. Adicionar um novo endpoint OpenAI-compatible
# é acrescentar uma linha aqui.
# ─────────────────────────────────────────────────────────────────

# Base do proxy local. O /v1 é acrescentado aqui para que a variável de
# ambiente guarde só host e porta, que é o que o gateway.py também usa.
URL_KIRO = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000").rstrip("/")


def _url_com_v1(base: str) -> str:
    """
    Garante um sufixo /v1 na base URL sem duplicá-lo.

    O endpoint Claude OpenAI-compatible do Vitor é configurado por .env
    (EMILY_CLAUDE_URL) preenchido à mão, e não dá pra saber se ele vai
    colar a URL COM ou SEM /v1 no fim. Aceitar os dois evita o erro mais
    idiota possível de configuração: 404 em toda chamada por causa de um
    '/v1/v1' ou da falta dele.
    """
    base = (base or "").rstrip("/")
    if not base:
        return base
    return base if base.endswith("/v1") else f"{base}/v1"


# Endpoint OpenAI-compatible que serve o Claude (claude-opus-4-8). Só host e
# porta/caminho vão no .env; o /v1 é normalizado aqui. Vazio até o Vitor
# preencher EMILY_CLAUDE_URL — nesse caso a rota falha com ErroConfiguracao
# clara em vez de bater num host inválido.
URL_CLAUDE = _url_com_v1(os.getenv("EMILY_CLAUDE_URL", ""))

PROVEDORES: Dict[str, Provedor] = {

    # Caminho principal desde a migração para o plano pago do Kiro.
    #
    # timeout de 300s, não 90s: as rotas de visão mandam imagem base64 e o
    # Claude via Q Developer é mais lento que o nemotron. Casa com o
    # STREAMING_READ_TIMEOUT default do gateway, que também é 300s.
    "kiro": ProvedorKiro(
        nome="kiro",
        base_url=f"{URL_KIRO}/v1",
        env_chave="KIRO_PROXY_API_KEY",
        timeout=float(os.getenv("EMILY_KIRO_TIMEOUT", "300")),
    ),
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
    "vertex": ProvedorVertexGemini(),
    # Novo cérebro principal: Claude (claude-opus-4-8) servido por um endpoint
    # OpenAI-compatible. Reusa o ProvedorOpenAI inteiro — formato de fio,
    # streaming, tool calling e visão são idênticos, porque o endpoint fala
    # OpenAI de verdade e o proxy é quem traduz pro formato nativo da Anthropic.
    #
    # Só preencher EMILY_CLAUDE_URL e CLAUDE_API_KEY no .env: nada além disso
    # precisa mudar pra Emily inteira passar a rodar no Claude.
    #
    # timeout de 300s, não 90s: as rotas de visão mandam imagem base64 e o
    # Opus é mais lento que os modelos de texto puro.
    "claude": ProvedorOpenAI(
        nome="claude",
        base_url=URL_CLAUDE,
        env_chave="CLAUDE_API_KEY",
        timeout=float(os.getenv("EMILY_CLAUDE_TIMEOUT", "300")),
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

# ─── Modelos do Kiro (caminho principal) ─────────────────────────
#
# Cada grupo de rota tem variável de ambiente própria porque modelo sai do
# ar sem aviso: os dois Qwen3.5 morreram com 410 Gone no NIM, o Opus 4.5
# saiu do free tier do Kiro em janeiro, e o Opus 5 é "experimental preview"
# no painel. Trocar modelo tem que ser edição de .env, não de código.
#
# O que a medição da Task 1 mostrou, contra o gateway de verdade:
#
#   modelo               1a chamada   depois    papel
#   claude-sonnet-5          4,98s   1,8-2,8s   conversa, texto, visão
#   claude-opus-5            1,75s        —     agente de UI
#   claude-haiku-4.5         1,78s        —     classificador, triagem
#
# Streaming em claude-sonnet-5: 6 pedaços, 3,36s até o PRIMEIRO pedaço,
# 3,64s no total. Visão: 2,26s e 1.343 tokens de prompt numa imagem
# 480x160.
#
# Detalhe que vale saber, e que confirma nos DOIS sentidos o aviso que já
# estava escrito aqui embaixo sobre o NIM: o GET /v1/models desta conta
# lista 13 modelos e NENHUM deles é claude-sonnet-5 ou claude-opus-5 — mas
# os dois respondem normalmente na chamada real, porque o ModelResolver do
# gateway é pass-through ("gateway, not gatekeeper"). A lista não é
# autoridade nem para dizer que existe, nem para dizer que não existe.
MODELO_KIRO_CONVERSA = os.getenv("EMILY_KIRO_MODELO_CONVERSA", "claude-sonnet-5")
MODELO_KIRO_VISAO = os.getenv("EMILY_KIRO_MODELO_VISAO", "claude-sonnet-5")
MODELO_KIRO_AGENTE_UI = os.getenv("EMILY_KIRO_MODELO_AGENTE_UI", "claude-opus-5")
MODELO_KIRO_AGENTE_JOGO = os.getenv("EMILY_KIRO_MODELO_AGENTE_JOGO", "claude-sonnet-5")

# Rotas de saída minúscula (SIM/NAO, JSON curto) que disparam muito. Haiku
# custa menos crédito e responde mais rápido; 'auto' (1x) NÃO existe nesta
# conta — o /v1/models só expõe 'auto-kiro', que é alias do gateway.
MODELO_KIRO_BARATO = os.getenv("EMILY_KIRO_MODELO_BARATO", "claude-haiku-4.5")

# ─── Modelos do NIM (plano B, caminho de reversão) ───────────────

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
#
# ── Medição da migração pro Kiro (_bench_visao.py) ──────────────
#
# Mesma metodologia acima, MESMA captura 640x360 nos três modelos, na
# mesma execução. 2 amostras cada:
#
#   modelo                            descr.   triagem   leitura da tela
#   nvidia/nemotron-nano-12b-v2-vl     4,62s     0,58s   ERRADA
#   claude-sonnet-5                   10,09s     2,63s   correta
#   claude-haiku-4.5                   3,34s     2,12s   correta
#
# O número que decidiu não foi a latência, foi a LEITURA. Na mesma tela
# (VS Code com o CONTRIBUTING.md do kiro-gateway aberto), o nemotron
# alucinou "um chat em tempo real com vários usuários discutindo
# melhorias para uma plataforma de contribuição de código" — ele leu o
# texto do arquivo e concluiu que era conversa entre pessoas. Os dois
# Claude descreveram certo, e o Sonnet até nomeou o projeto.
#
# Para a Emily isso é a diferença entre comentar a tela e inventar a
# tela. A rota 'visao' existe para ela reagir ao que o Vitor está
# fazendo; reagir a uma tela imaginária é pior que não reagir.
#
# Escolhas, e o que muda se você discordar:
#   visao          -> claude-sonnet-5 (leitura mais detalhada; 10s é muito,
#                     e claude-haiku-4.5 faz em 3,34s lendo certo também.
#                     Se a latência incomodar, troque EMILY_KIRO_MODELO_VISAO)
#   triagem_visual -> claude-haiku-4.5 (o mais barato que existe na conta)
#
# O que a migração PERDEU: a triagem era 0,58s e grátis no free tier do
# NIM; agora é 2,12s e consome crédito por disparo. Ela roda em laço
# durante o monitoramento de tela e de jogo, então é a primeira
# candidata a voltar pro nemotron se o crédito apertar.
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

    def limitador(self, nome_rota: str = None) -> Limitador:
        # No Vertex AI as cotas são por modelo, e as tarefas competem por
        # latência (triagem visual constante vs conversa). Separar por rota
        # resolve o gargalo.
        chave = f"{self.provedor}_{nome_rota}" if nome_rota else self.provedor
        return limitador_de(chave, self.rpm)


ROTAS_KIRO: Dict[str, Rota] = {
    # Conversa por voz. Raciocínio desligado: aqui token de pensamento é
    # silêncio no alto-falante. Temperatura alta pra personalidade variar.
    #
    # MIGRADA para o Kiro (Task 2 do spec migracao-llm-kiro-gateway). Foi a
    # primeira porque é a rota que mais importa e a que mais expõe problema:
    # se a personalidade da Emily não sobreviver ao Claude, aparece aqui
    # antes de qualquer outro lugar.
    #
    # rpm próprio: o limitador é por provedor, e o teto do plano pago do
    # Kiro não é publicado. 30 é margem, não medição.
    "conversa": Rota(
        provedor="kiro", modelo=MODELO_KIRO_CONVERSA,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
        rpm=RPM_KIRO,
    ),

    # Classificadores SIM/NAO e extração de JSON. Determinístico e curto.
    #
    # Haiku porque é a rota que MAIS dispara: cada mensagem do Vitor que
    # mencione tela passa por aqui, e no Kiro cada chamada custa crédito.
    #
    # O orçamento de 16 tokens era o risco declarado desta migração: o
    # Claude é mais verboso que o GLM e resposta vazia por orçamento
    # estourado já derrubou a triagem neste projeto antes. MEDIDO na Task 5,
    # 3 amostras por combinação, temperatura 0:
    #
    #   modelo             max_tokens  vazias  decisão correta
    #   claude-haiku-4.5        8       0/3         3/3
    #   claude-haiku-4.5       10       0/3         3/3
    #   claude-haiku-4.5       16       0/3         3/3
    #   claude-sonnet-5         8       0/3         3/3
    #
    # Inclui o caso negativo ("me conta uma piada" -> NAO), que é o que
    # pega classificador viciado em dizer sim. Funciona porque o
    # RACIOCINIO_DESLIGADO manda reasoning_effort='none' e o gateway
    # DESLIGA o thinking — nenhum token é gasto antes da resposta.
    #
    # O call site mais apertado é o _llm_confirma_visao do modelo.py, que
    # passa max_tokens=8 por parâmetro. Também medido, também limpo.
    "classificador": Rota(
        provedor="kiro", modelo=MODELO_KIRO_BARATO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_KIRO,
    ),

    # Interpretação de comando e fallback de intenção: JSON estruturado.
    # Sonnet e não Haiku: JSON malformado aqui vira ação errada na máquina
    # do Vitor, e a rota dispara pouco em comparação com o classificador.
    "comando": Rota(
        provedor="kiro", modelo=MODELO_KIRO_CONVERSA,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_KIRO,
    ),

    # Extração de fatos pra memória. Roda em background, latência não importa.
    # O memoria.py também usa esta rota para a deduplicação semântica, com
    # max_tokens=10 por parâmetro — medido junto do classificador na Task 5.
    "extracao": Rota(
        provedor="kiro", modelo=MODELO_KIRO_CONVERSA,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
        rpm=RPM_KIRO,
    ),

    # Análise de tela de verdade — a que gera comentário pro Vitor.
    #
    # ATENÇÃO ao raciocinio: aqui é DESLIGADO, e nas versões NIM destas
    # rotas era NORMAL. Não é descuido, é o oposto do mesmo problema.
    # No NIM, NORMAL significava "não manda parâmetro", porque o
    # nemotron-nano-vl REJEITA reasoning_effort='none' com 400 (só aceita
    # low/medium/high). No gateway do Kiro é o contrário: mandar 'none'
    # DESLIGA o thinking, e NÃO mandar nada LIGA com budget default —
    # confirmado lendo o extract_thinking_config_from_openai do gateway.
    # Ou seja, deixar NORMAL aqui faria o Claude pensar antes de descrever
    # a tela, gastando token e latência à toa.
    "visao": Rota(
        provedor="kiro", modelo=MODELO_KIRO_VISAO,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.7,
        rpm=RPM_KIRO,
    ),

    # Triagem SIM/NAO de tela. Saída minúscula, e a rota que dispara MAIS
    # vezes em todo o projeto: roda em laço enquanto o monitoramento de
    # tela ou de jogo está ativo.
    #
    # Haiku porque é o mais barato disponível na conta. Ainda assim, esta é
    # a primeira rota a considerar devolver pro nemotron se o crédito do
    # mês começar a acabar — no NIM ela era grátis, aqui cada disparo
    # custa. Reverter é uma linha: EMILY_KIRO_MODELO_BARATO ou o campo
    # provedor aqui.
    "triagem_visual": Rota(
        provedor="kiro", modelo=MODELO_KIRO_BARATO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_KIRO,
    ),

    # Agente de UI: precisa de visão, decisão estruturada em JSON e, acima
    # de tudo, precisão para apontar onde clicar. Usa um modelo diferente
    # das outras rotas de visão por isso — ver MODELO_VISAO_AGENTE.
    #
    # Medição de grade 10x10 antes de migrar (_bench_grade.py, 12 alvos em
    # cantos, bordas e centro, gabarito exato porque o alvo é desenhado):
    #
    #   modelo                              exatos  linha  coluna  latência
    #   meta/llama-3.2-90b-vision-instruct   12/12  12/12   12/12    2,19s
    #   claude-opus-5                        12/12  12/12   12/12    3,85s
    #   claude-sonnet-5                      12/12  12/12   12/12    3,46s
    #
    # O benchmark SATUROU: os três acertam tudo, então ele prova que o Opus
    # não é pior, mas não distingue Opus de Sonnet. Como o Opus custa 2,2x
    # de crédito contra 1,3x do Sonnet, e o Sonnet foi até um pouco mais
    # rápido aqui, vale saber que trocar é uma linha de .env
    # (EMILY_KIRO_MODELO_AGENTE_UI). Separar os dois exigiria um alvo mais
    # difícil que um círculo magenta — um botão pequeno entre elementos
    # parecidos, que é o caso real.
    "agente_ui": Rota(
        provedor="kiro", modelo=MODELO_KIRO_AGENTE_UI,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_KIRO,
    ),

    # Agente de jogo: decide tecla a partir da tela, em LAÇO, enquanto o
    # Vitor joga.
    #
    # Rota própria criada nesta migração. Antes o agente_jogo.py usava a
    # rota 'agente_ui' — o que era inofensivo quando as duas apontavam pro
    # mesmo modelo no NIM, e virou problema de custo quando o agente_ui foi
    # pro Opus a 2,2x de crédito: um monitoramento de jogo de meia hora
    # gastaria crédito de Opus a cada poucos segundos, sem precisar da
    # precisão que justifica o Opus.
    "agente_jogo": Rota(
        provedor="kiro", modelo=MODELO_KIRO_AGENTE_JOGO,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_KIRO,
    ),

    # Discord: respostas curtas de chat.
    # Sonnet e não Haiku porque aqui a personalidade importa tanto quanto na
    # conversa por voz — é a Emily falando com gente do servidor.
    "discord": Rota(
        provedor="kiro", modelo=MODELO_KIRO_CONVERSA,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
        rpm=RPM_KIRO,
    ),
}


# ═════════════════════════════════════════════════════════════════
# TABELA DO NIM — CAMINHO DE REVERSÃO
#
# Esta tabela existe para uma linha de .env devolver a Emily inteira ao
# NVIDIA NIM: EMILY_PROVEDOR_LLM=nvidia.
#
# Não é zelo excessivo, é histórico deste projeto: os dois Qwen3.5 VLM
# morreram com 410 Gone, o Opus 4.5 saiu do free tier do Kiro em janeiro, e
# o Opus 5 está marcado como "experimental preview" no painel. Modelo sai do
# ar sem avisar, e quando isso acontecer a Emily não pode ficar muda
# esperando alguém editar código.
#
# É a configuração que rodava antes da migração, com os valores de
# raciocínio que o NIM exige — note RACIOCINIO_NORMAL nas rotas de visão,
# que ali significa "não manda parâmetro nenhum" porque o nemotron rejeita
# reasoning_effort='none' com 400. A semântica é INVERTIDA em relação ao
# gateway do Kiro, e é justamente por isso que as duas tabelas precisam
# existir separadas em vez de uma tabela com o provedor trocado.
#
# A rota 'agente_jogo' é nova (criada na migração) e por isso não tem
# histórico no NIM: aponta para o mesmo modelo de visão do agente de UI,
# que era o comportamento efetivo antes da separação.
# ═════════════════════════════════════════════════════════════════

ROTAS_NVIDIA: Dict[str, Rota] = {
    "conversa": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
    ),
    "classificador": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
    ),
    "comando": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
    ),
    "extracao": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
    ),
    "visao": Rota(
        provedor="nvidia", modelo=MODELO_VISAO,
        max_tokens=1024, raciocinio=RACIOCINIO_NORMAL, temperatura=0.7,
    ),
    "triagem_visual": Rota(
        provedor="nvidia", modelo=MODELO_VISAO_RAPIDO,
        max_tokens=16, raciocinio=RACIOCINIO_NORMAL, temperatura=0.0,
    ),
    "agente_ui": Rota(
        provedor="nvidia", modelo=MODELO_VISAO_AGENTE,
        max_tokens=1024, raciocinio=RACIOCINIO_NORMAL, temperatura=0.1,
    ),
    "agente_jogo": Rota(
        provedor="nvidia", modelo=MODELO_VISAO_AGENTE,
        max_tokens=2048, raciocinio=RACIOCINIO_NORMAL, temperatura=0.1,
    ),
    "discord": Rota(
        provedor="nvidia", modelo=MODELO_TEXTO,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
    ),
}


# ═════════════════════════════════════════════════════════════════
# SELEÇÃO DA TABELA ATIVA
# ═════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════
# TABELA VERTEX GEMINI — NOVO CÉREBRO PRINCIPAL
# ═════════════════════════════════════════════════════════════════

# MODELOS VERTEX
MODELO_VERTEX_PRINCIPAL = os.getenv("EMILY_VERTEX_MODELO_PRINCIPAL", "gemini-3.6-flash")
MODELO_VERTEX_RAPIDO = os.getenv("EMILY_VERTEX_MODELO_RAPIDO", "gemini-3.5-flash-lite")
RPM_VERTEX = int(os.getenv("EMILY_VERTEX_RPM", "10"))

ROTAS_VERTEX: Dict[str, Rota] = {
    "conversa": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
        rpm=RPM_VERTEX,
    ),
    "classificador": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_RAPIDO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_VERTEX,
    ),
    "comando": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_VERTEX,
    ),
    "extracao": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_RAPIDO,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
        rpm=RPM_VERTEX,
    ),
    "visao": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.7,
        rpm=RPM_VERTEX,
    ),
    "triagem_visual": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_RAPIDO,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_VERTEX,
    ),
    "agente_ui": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_VERTEX,
    ),
    "agente_jogo": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_VERTEX,
    ),
    "discord": Rota(
        provedor="vertex", modelo=MODELO_VERTEX_PRINCIPAL,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
        rpm=RPM_VERTEX,
    ),
}

# ═════════════════════════════════════════════════════════════════
# TABELA CLAUDE — CÉREBRO PRINCIPAL (endpoint OpenAI-compatible)
#
# Emily inteira alimentada pelo Claude via um endpoint OpenAI-compatible.
# Ativar é uma linha de .env: EMILY_PROVEDOR_LLM=claude.
#
# TODAS as rotas usam o mesmo modelo (claude-opus-4-8) porque é o único
# disponível na conta do Vitor. Trocar é editar EMILY_CLAUDE_MODELO no .env,
# sem tocar em código.
#
# Raciocínio DESLIGADO em todas: manda reasoning_effort='none'. Se o endpoint
# não conhecer esse parâmetro, o ProvedorOpenAI aprende com o primeiro 400 e
# para de mandar sozinho (ver _tratar_erro / _marcar_rejeitado) — então isto
# é seguro tanto num endpoint que entende reasoning_effort quanto num que não.
#
# max_tokens e temperatura são os mesmos das outras tabelas, mantendo o
# comportamento de cada tarefa: saída curta e determinística na triagem e no
# classificador, temperatura alta na conversa e no Discord pra personalidade
# variar.
# ═════════════════════════════════════════════════════════════════

# Modelo único de todas as rotas. claude-opus-4-8 conforme pedido; trocável
# por .env caso o nome do modelo mude no endpoint.
MODELO_CLAUDE = os.getenv("EMILY_CLAUDE_MODELO", "claude-opus-4-8")

# Balde do limitador do provedor claude. O endpoint não publica RPM;
# 30 é margem contra rajada, não medição.
RPM_CLAUDE = int(os.getenv("EMILY_CLAUDE_RPM", "30"))

ROTAS_CLAUDE: Dict[str, Rota] = {
    "conversa": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
        rpm=RPM_CLAUDE,
    ),
    "classificador": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "comando": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "extracao": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
        rpm=RPM_CLAUDE,
    ),
    "visao": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.7,
        rpm=RPM_CLAUDE,
    ),
    "triagem_visual": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "agente_ui": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "agente_jogo": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "discord": Rota(
        provedor="claude", modelo=MODELO_CLAUDE,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
        rpm=RPM_CLAUDE,
    ),
}

TABELAS: Dict[str, Dict[str, Rota]] = {
    "claude": ROTAS_CLAUDE,
    "kiro": ROTAS_KIRO,
    "nvidia": ROTAS_NVIDIA,
    "vertex": ROTAS_VERTEX,
}

TABELA_PADRAO = "claude"



def _resolver_tabela(nome: Optional[str]) -> Tuple[str, Dict[str, Rota]]:
    """
    Escolhe a tabela de rotas ativa a partir do valor da variável.

    Tolera espaço nas pontas e qualquer caixa, porque valor de .env copiado
    à mão vem com lixo — e falhar por causa de um espaço seria um jeito
    idiota de deixar a Emily muda.

    Levanta ErroConfiguracao citando os valores aceitos quando não reconhece.
    Não cai no default em silêncio: se o Vitor escreveu 'nvida' por engano,
    ele precisa SABER, e não descobrir três dias depois que estava no Kiro
    o tempo todo.
    """
    limpo = (nome or "").strip().lower()
    if not limpo:
        return TABELA_PADRAO, TABELAS[TABELA_PADRAO]
    if limpo not in TABELAS:
        raise ErroConfiguracao(
            f"EMILY_PROVEDOR_LLM='{nome}' não é um valor aceito. "
            f"Use um destes: {', '.join(sorted(TABELAS))}"
        )
    return limpo, TABELAS[limpo]


TABELA_ATIVA, ROTAS = _resolver_tabela(os.getenv("EMILY_PROVEDOR_LLM"))

if TABELA_ATIVA != TABELA_PADRAO:
    _log(f"tabela de rotas ATIVA: '{TABELA_ATIVA}' (via EMILY_PROVEDOR_LLM)")

ROTA_PADRAO = "conversa"


def rota(nome: str) -> Rota:
    if nome not in ROTAS:
        raise ErroConfiguracao(
            f"rota '{nome}' não existe na tabela '{TABELA_ATIVA}'. "
            f"Rotas disponíveis: {', '.join(sorted(ROTAS))}"
        )
    return ROTAS[nome]


# ═════════════════════════════════════════════════════════════════
# RETRY E PORTA DE ENTRADA
# ═════════════════════════════════════════════════════════════════

ESPERA_BASE = 1.0      # segundos
ESPERA_MAXIMA = 20.0

# Teto de tempo TOTAL gasto tentando, contado da primeira tentativa. Depois
# disso nenhuma tentativa nova começa, mesmo que ainda haja tentativa no
# orçamento de `cfg.tentativas`.
#
# Existe porque contar tentativas não limita espera. O caso medido: o gateway
# do Kiro derrubava a requisição em 15s sem primeiro token e repetia 3 vezes
# sozinho; cada uma dessas rodadas de 45s valia UMA tentativa aqui, e as 4
# tentativas com backoff deixaram a Emily calada uns 3 minutos no Discord, com
# o "digitando..." ligado, pra no fim dizer que não conseguiu. Falhar em 1
# minuto e admitir é melhor que sumir por 3 e admitir.
ORCAMENTO_RETENTATIVA = float(os.getenv("EMILY_ORCAMENTO_RETENTATIVA", "90"))


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
    ferramentas: Optional[List[dict]] = None,
    obrigar_ferramenta: bool = False,
    proibir_ferramenta: bool = False,
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
    limitador = cfg.limitador(rota_nome)

    ultimo_erro: Optional[Exception] = None
    comeco = time.monotonic()

    for tentativa in range(cfg.tentativas):
        if tentativa and time.monotonic() - comeco > ORCAMENTO_RETENTATIVA:
            _log(
                f"rota '{rota_nome}': já gastei "
                f"{time.monotonic() - comeco:.0f}s tentando (teto de "
                f"{ORCAMENTO_RETENTATIVA:.0f}s). Paro na tentativa "
                f"{tentativa} de {cfg.tentativas} em vez de deixar quem "
                f"pediu esperando mais."
            )
            break

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
                ferramentas=ferramentas,
                obrigar_ferramenta=obrigar_ferramenta,
                proibir_ferramenta=proibir_ferramenta,
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

    gasto = time.monotonic() - comeco
    _log(f"rota '{rota_nome}' desistiu depois de {gasto:.0f}s. "
         f"Último erro: {ultimo_erro}")
    raise ErroLLM(
        f"rota '{rota_nome}' falhou depois de {gasto:.0f}s de tentativa"
    ) from ultimo_erro


def chamar_com_ferramentas(
    mensagens: Sequence[dict],
    ferramentas: List[dict],
    rota_nome: str = ROTA_PADRAO,
    max_tokens: Optional[int] = None,
    stream: bool = False,
    obrigar_ferramenta: bool = False,
    proibir_ferramenta: bool = False,
) -> Union[Resposta, "FluxoComFerramentas"]:
    """
    Chamada com catálogo de ferramentas. O modelo decide se responde em texto
    ou pede a execução de uma ou mais ferramentas.

    Com stream=False devolve um Resposta(texto, chamadas).
    Com stream=True devolve um FluxoComFerramentas, que permite descobrir a
    decisão sem esperar a resposta inteira — importante porque a Emily fala
    o resultado por TTS.

    Levanta ErroConfiguracao se o provedor da rota não fizer tool calling.
    """
    cfg = rota(rota_nome)
    provedor = PROVEDORES.get(cfg.provedor)
    if provedor is not None and not provedor.suporta_ferramentas:
        raise ErroConfiguracao(
            f"o provedor '{cfg.provedor}' da rota '{rota_nome}' não suporta tool calling"
        )
    return chamar(
        mensagens,
        rota_nome=rota_nome,
        max_tokens=max_tokens,
        stream=stream,
        ferramentas=ferramentas,
        obrigar_ferramenta=obrigar_ferramenta,
        proibir_ferramenta=proibir_ferramenta,
    )


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

    # 0. Estado do gateway do Kiro.
    #
    # Vem antes de tudo porque desde a migração é o pré-requisito de todas
    # as rotas do provedor 'kiro': se ele não está no ar, o resto do
    # diagnóstico só produz o mesmo erro repetido nove vezes.
    print("\n[0] Gateway do Kiro")
    try:
        import gateway as _gw

        for chave, valor in _gw.estado().items():
            print(f"    {chave:<14} {valor}")
        relatorio["gateway"] = _gw.estado()
    except ImportError:
        print("    gateway.py não encontrado (rotas do provedor 'kiro' vão falhar)")
        relatorio["gateway"] = {"erro": "modulo ausente"}
    except Exception as e:
        print(f"    falha ao consultar o gateway: {type(e).__name__}: {e}")
        relatorio["gateway"] = {"erro": str(e)}

    # 1. Credenciais presentes?
    #
    # getattr com default porque nem todo provedor usa uma chave só do .env: o
    # ProvedorVertexGemini autentica por credencial do Google (arquivo apontado
    # por GOOGLE_APPLICATION_CREDENTIALS), então não tem env_chave. Sem o
    # default, o diagnóstico quebrava com AttributeError logo no começo.
    print("\n[1] Credenciais no .env")
    envs = sorted({getattr(p, "env_chave", None) for p in PROVEDORES.values()} - {None})

    for env in envs:
        presente = bool(os.getenv(env))
        print(f"    {env:<24} {'presente' if presente else 'AUSENTE'}")
        relatorio[env] = presente

    # 2. Rotas
    print(f"\n[2] Tabela de rotas ATIVA: '{TABELA_ATIVA}'"
          f"  (tabelas disponíveis: {', '.join(sorted(TABELAS))})")
    print(f"    troca por .env: EMILY_PROVEDOR_LLM=<tabela>")
    relatorio["tabela_ativa"] = TABELA_ATIVA
    print()
    for nome, cfg in ROTAS.items():
        print(f"    {nome:<16} {cfg.provedor:<10} {cfg.modelo:<28} "
              f"max_tokens={cfg.max_tokens} raciocinio={cfg.raciocinio}")

    # Progresso da migração, de olho: rota apontando para provedor não
    # registrado é erro de digitação que só apareceria na primeira chamada.
    por_provedor: Dict[str, List[str]] = {}
    orfas = []
    for nome, cfg in ROTAS.items():
        por_provedor.setdefault(cfg.provedor, []).append(nome)
        if cfg.provedor not in PROVEDORES:
            orfas.append(f"{nome} -> '{cfg.provedor}'")
    print()
    for provedor_nome in sorted(por_provedor):
        rotas_do_provedor = sorted(por_provedor[provedor_nome])
        print(f"    {provedor_nome:<10} {len(rotas_do_provedor)} rota(s): "
              f"{', '.join(rotas_do_provedor)}")
    if orfas:
        print(f"    ATENÇÃO: rota(s) apontando para provedor não registrado: {', '.join(orfas)}")
    relatorio["rotas_por_provedor"] = {k: sorted(v) for k, v in por_provedor.items()}
    relatorio["rotas_orfas"] = orfas

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
