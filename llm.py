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
import re
import threading
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from dotenv import load_dotenv

load_dotenv()

# Pasta do projeto. Usada pelo parser de seções do .env pra achar o arquivo
# certo independente de onde o Python foi invocado.
DIR_PROJETO = os.path.dirname(os.path.abspath(__file__))


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


def descrever_erro(erro: Exception) -> str:
    """Mensagem curta sem URL, token ou corpo bruto do provedor."""
    if isinstance(erro, ErroLimiteTaxa):
        return "O serviço de IA atingiu o limite de requisições e não voltou após as tentativas."
    if isinstance(erro, ErroConfiguracao):
        return "O serviço de IA recusou a configuração ou a credencial. Confira as configurações."
    if isinstance(erro, ErroTransporte):
        texto = str(erro).lower()
        if any(s in texto for s in ("timeout", "timed out", "connection", "connect", "dns", "sem rede")):
            return "A conexão com o serviço de IA falhou ou demorou demais e não voltou após as tentativas."
        return "O serviço de IA ficou indisponível e não voltou após as tentativas."
    if isinstance(erro, ErroResposta):
        return "O serviço de IA respondeu sem um resultado utilizável."
    return "O serviço de IA não conseguiu concluir esta resposta."


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
# Níveis expostos na interface. Mapeiam direto pro
# reasoning_effort do endpoint. Ficam separados dos de cima porque estes são
# ESCOLHA do Vitor no chat, não afinação por tarefa.
RACIOCINIO_BAIXO = "baixo"
RACIOCINIO_MEDIO = "medio"
RACIOCINIO_ALTO = "alto"
RACIOCINIO_EXTRA_ALTO = "extra_alto"
RACIOCINIO_MAXIMO = "maximo"

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
    # Os três níveis do seletor da interface.
    RACIOCINIO_BAIXO: {
        "reasoning_effort": "low",
    },
    RACIOCINIO_MEDIO: {
        "reasoning_effort": "medium",
    },
    RACIOCINIO_ALTO: {
        "reasoning_effort": "high",
    },
    RACIOCINIO_EXTRA_ALTO: {
        "reasoning_effort": "xhigh",
    },
    RACIOCINIO_MAXIMO: {
        "reasoning_effort": "max",
    },
}


def _modelo_gpt6(modelo: str) -> bool:
    """Inclui o prefixo cx/ do OmniRoute sem afetar outros provedores."""
    return bool(re.search(r"(?:^|/)gpt-6(?:\.\d+)?-(?:sol|luna|astra)(?:$|[-:])",
                          (modelo or "").lower()))


def _modelo_gpt6_sem_none(modelo: str) -> bool:
    return bool(re.search(r"(?:^|/)gpt-6(?:\.\d+)?-astra(?:$|[-:])|"
                          r"(?:^|/)gpt-6\.1-sol(?:$|[-:])",
                          (modelo or "").lower()))

# Parâmetros que um endpoint já rejeitou, por (provedor, modelo).
# Evita insistir em algo que sabemos que não existe naquele build.
_params_rejeitados: Dict[str, Set[str]] = {}
_lock_rejeitados = threading.Lock()


def _chave_rejeicao(provedor: str, modelo: str) -> str:
    return f"{provedor}::{modelo}"


def _params_validos(provedor: str, modelo: str, nivel: str) -> dict:
    base = PARAMS_RACIOCINIO.get(nivel, {})
    if _modelo_gpt6_sem_none(modelo) and base.get("reasoning_effort") == "none":
        # Rotas internas como Discord ainda nascem com raciocínio desligado;
        # Astra/6.1 Sol rejeitam esse valor mesmo fora do seletor do chat.
        base = {**base, "reasoning_effort": "low"}
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


# ════════════════════════════════════════════════════════════════
# POOL HTTP COM KEEP-ALIVE LONGO — o conserto de latência dos provedores
# ════════════════════════════════════════════════════════════════
#
# O QUE ESTAVA ERRADO
# ───────────────────
# O SDK criava o próprio httpx.Client, e o default do httpx fecha conexão
# ociosa depois de 5 segundos (`Limits(keepalive_expiry=5.0)`).
#
# Numa conversa de verdade a Emily é chamada a cada 10–40s. Ou seja: quase
# TODA chamada pagava handshake novo (DNS + TCP + TLS). Medido contra o
# relay da Anthropic configurado no .env:
#
#   conexão fria  -> 8–10s   (com picos)
#   conexão quente -> 1,8–2,2s
#
# Com um cliente de keep-alive de 5 minutos, as três chamadas medidas
# ficaram em 1,95s / 2,14s / 2,12s, contra 4,80s / 2,29s / 2,25s do
# cliente padrão. É o ganho mais barato que existe aqui: nenhuma linha
# de prompt muda, nenhum modelo muda — só o socket para de morrer entre
# um turno e outro.
#
# POR QUE UM POOL POR PROVEDOR
# ────────────────────────────
# As threads da Emily (voz, call, memória, agenda, agentes) batem no
# MESMO provedor em paralelo. Um pool por provedor evita que a rajada de
# ferramentas derrube conexões umas das outras, e o teto maior (64) cobre
# o paralelismo real sem repetir o handshake.
_POOL_HTTP_LOCK = threading.Lock()
_POOL_HTTP: Dict[str, object] = {}


def _env_float_llm(nome: str, padrao: float) -> float:
    """Lê float de variável de ambiente sem explodir em valor torto."""
    try:
        return float(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao


def _cliente_http_do_provedor(nome: str, timeout: float):
    """
    httpx.Client com keep-alive longo, um por provedor.

    Devolve None quando o httpx não está disponível (nesse caso o SDK volta
    ao cliente padrão dele — comportamento antigo, só mais lento).
    """
    try:
        import httpx
    except ImportError:
        return None
    with _POOL_HTTP_LOCK:
        cliente = _POOL_HTTP.get(nome)
        if cliente is not None and not getattr(cliente, "is_closed", False):
            return cliente
        expiracao = _env_float_llm("EMILY_LLM_KEEPALIVE", 300.0)
        max_conexoes = int(_env_float_llm("EMILY_LLM_MAX_CONEXOES", 64.0))
        if expiracao < 0:
            # Valor negativo = não usar pool próprio. É o comportamento
            # HISTÓRICO (o SDK cria o cliente dele, com o keepalive de 5s do
            # httpx) e existe pra medição A/B e como escotilha caso algum
            # endpoint reclame de conexão reaproveitada.
            return None
        try:
            cliente = httpx.Client(
                # O timeout real da chamada é o do SDK (por requisição); este
                # aqui é só o teto de segurança do transporte.
                timeout=httpx.Timeout(max(10.0, timeout)),
                limits=httpx.Limits(
                    max_connections=max(8, max_conexoes),
                    max_keepalive_connections=max(4, max_conexoes // 2),
                    keepalive_expiry=max(0.0, expiracao),
                ),
            )
        except Exception as e:
            _log(f"pool HTTP de '{nome}' indisponível ({e}); usando o cliente do SDK")
            return None
        _POOL_HTTP[nome] = cliente
        _log(
            f"pool HTTP de '{nome}': keepalive={expiracao:.0f}s "
            f"max_conexoes={max(8, max_conexoes)}"
        )
        return cliente


def fechar_pools_http() -> None:
    """
    Fecha os pools HTTP e invalida os clientes de SDK que os usavam.

    A invalidação é obrigatória, não zelo: o cliente do SDK guarda uma
    referência ao httpx.Client. Fechar só o pool deixaria o SDK falando num
    socket morto — toda chamada vira "Connection error" e a cadeia de
    fallback transforma isso em ~20s de espera antes de desistir.
    """
    provedores_limpos = 0
    for provedor in list(PROVEDORES.values()):
        # O provedor híbrido guarda um segundo SDK para a Messages API visual.
        # Os dois apontam para pools deste módulo e precisam ser invalidados
        # juntos; senão o próximo anexo reutiliza um httpx.Client já fechado.
        clientes = [provedor]
        visual = getattr(provedor, "_visao_anthropic", None)
        if visual is not None:
            clientes.append(visual)
        for cliente_sdk in clientes:
            try:
                cliente_sdk._cliente = None
                cliente_sdk._pool_do_cliente = None
                provedores_limpos += 1
            except Exception:
                pass
    with _POOL_HTTP_LOCK:
        for nome, cliente in list(_POOL_HTTP.items()):
            try:
                cliente.close()
            except Exception:
                pass
            _POOL_HTTP.pop(nome, None)


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
        self._pool_do_cliente = None   # httpx.Client que o SDK está usando
        self._lock = threading.Lock()

    def _obter_cliente(self):
        # Pool e cliente do SDK andam JUNTOS: fechar/recrear o pool tem que
        # invalidar o cliente do SDK, senão ele segue apontando pro
        # httpx.Client já fechado e TODA chamada falha com "Connection
        # error" — e com a cadeia de fallback isso vira 20s de tentativa
        # antes de desistir. Comparar a identidade do pool resolve sem flag.
        pool = _cliente_http_do_provedor(self.nome, self.timeout)
        if self._cliente is not None and self._pool_do_cliente is pool:
            return self._cliente
        with self._lock:
            pool = _cliente_http_do_provedor(self.nome, self.timeout)
            if self._cliente is not None and self._pool_do_cliente is pool:
                return self._cliente
            # O campo _CHAVE do .env normalmente guarda o NOME da env var
            # (ex: DEEPSEEK_API_KEY). Mas aceita também o VALOR direto
            # (ex: sk-xxxx) quando o Vitor colou a chave no campo — nesse
            # caso usa ela mesma em vez de procurar uma env var que não
            # existe. O _provedores_config usa env_chave_opcional pra
            # tolerar a falta; aqui resolvemos o valor de verdade.
            if self.env_chave.startswith("sk-"):
                chave = self.env_chave
            else:
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
            # O pool com keep-alive longo é o que evita o handshake frio a
            # cada turno — ver o comentário de _cliente_http_do_provedor.
            self._cliente = OpenAI(
                base_url=self.base_url, api_key=chave, timeout=self.timeout,
                http_client=pool,
            )
            self._pool_do_cliente = pool
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
            # que mandar a lista vazia, e NÃO é: proxy que recebe requisição
            # SEM 'tools' costuma achatar o histórico de ferramentas em TEXTO
            # ("[Tool: nome (id)]\n{args}") pra não perder o contexto. O modelo
            # lê isso como o formato das falas dele e imita — foi assim que a
            # Emily mandou "[Tool: gerenciar_mod_launcher_mc (toolu_...)]" como
            # mensagem no Discord. Com 'tools' declarado o histórico segue
            # estruturado e não há formato nenhum pra imitar.
            if obrigar_ferramenta:
                corpo["tool_choice"] = "auto" if any(x in modelo.replace('.', '-') for x in ('sonnet-5-5','opus-5-5','fable-5-1','mythos-5-1')) else "required"
            elif proibir_ferramenta:
                corpo["tool_choice"] = "none"
            else:
                corpo["tool_choice"] = "auto"
        if max_tokens:
            corpo["max_tokens"] = max_tokens
        # GPT-6 usa raciocínio médio por padrão; temperatura não é aceita
        # nessa modalidade. Vale também quando nenhum esforço foi enviado.
        extras = _params_validos(self.nome, modelo, raciocinio)
        esforco = extras.get("reasoning_effort", "medium")
        if temperatura is not None and not (_modelo_gpt6(modelo) and esforco != "none"):
            corpo["temperature"] = temperatura
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
                "Confira a credencial do provedor nas configurações."
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
                escolha = pedaco.choices[0]
                # Loga o finish_reason quando o stream termina (último chunk).
                # 'length' = estouro de max_tokens de saída — o texto final
                # veio cortado. Sem isso, o corte passa despercebido.
                motivo = getattr(escolha, "finish_reason", None)
                if motivo:
                    _log(f"stream finalizado: finish_reason={motivo}")
                delta = escolha.delta
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
        # Pode ser reduzido pelo consumidor ANTES de quer_ferramenta(). Em um
        # pedido conversacional que já foi classificado como não-ação, esperar
        # 80 caracteres faz respostas curtas aparecerem apenas quando o stream
        # inteiro termina. Pedidos de ação mantêm o teto conservador acima.
        self._chars_para_decidir = self._CHARS_PARA_DECIDIR
        self._parciais: Dict[int, dict] = {}   # índice -> {id, nome, args}
        self._decidido = False
        self._esgotado = False
        # Por que capturar finish_reason: o último chunk do stream traz
        # choices[0].finish_reason ("stop" | "length" | ...) sem conteúdo.
        # Se o modelo corta por 'length' (max_tokens de saída estourado — o
        # caso das leituras de 220KB de código), o stream simplesmente para
        # e o texto da resposta final nunca vem. Antes isso passava
        # despercebido: o laço achava que "acabou" e devolvia o preâmbulo.
        self._finish_reason: Optional[str] = None
        self._reabrir = None
        self._avisar_reconexao = None
        self._reconexoes = 0
        self._texto_entregue = False
        self._aguardando_retorno = False

    def configurar_reconexao(self, reabrir, avisar=None, limite: int = 3) -> None:
        """Reabre somente a geração ainda não entregue; ferramenta não foi executada."""
        self._reabrir = reabrir
        self._avisar_reconexao = avisar
        self._limite_reconexoes = max(0, limite)

    def definir_limite_decisao_texto(self, limite: int) -> None:
        """Ajusta quanto texto é necessário para decidir, antes do consumo.

        O limite só pode ser alterado enquanto nenhum evento foi lido. Isso
        evita mudar retroativamente uma decisão e mantém 80 caracteres como
        padrão seguro para pedidos que podem virar tool call.
        """
        if self._decidido or self._buffer or self._parciais or self._esgotado:
            return
        try:
            self._chars_para_decidir = max(1, int(limite))
        except (TypeError, ValueError):
            return

    def _proximo_pedaco(self) -> Optional[str]:
        """Consome um evento do stream. Devolve texto se houver, senão None."""
        while True:
            try:
                pedaco = next(self._stream)
                if self._aguardando_retorno:
                    self._aguardando_retorno = False
                    if self._avisar_reconexao:
                        self._avisar_reconexao(0, self._limite_reconexoes)
                break
            except StopIteration:
                self._esgotado = True
                return None
            except Exception as e:
                _log(f"stream com ferramentas interrompido: {type(e).__name__}: {e}")
                # O modelo pode ter escrito metade de uma chamada, mas nenhuma
                # ferramenta foi executada: descartamos esses argumentos parciais.
                # Se texto já foi entregue ao TTS/chat, reiniciar a geração
                # duplicaria a fala. Nesse caso a camada acima mostra a falha.
                if (self._texto_entregue or not self._reabrir
                        or self._reconexoes >= self._limite_reconexoes):
                    self._esgotado = True
                    raise ErroTransporte(f"stream interrompido: {e}") from e
                self._reconexoes += 1
                if self._avisar_reconexao:
                    self._avisar_reconexao(self._reconexoes, self._limite_reconexoes)
                time.sleep(_espera_backoff(self._reconexoes - 1))
                try:
                    self._stream = self._reabrir()
                except (ErroTransporte, ErroLimiteTaxa):
                    if self._reconexoes >= self._limite_reconexoes:
                        self._esgotado = True
                        raise
                    continue
                self._buffer.clear()
                self._parciais.clear()
                self._finish_reason = None
                self._decidido = False
                self._aguardando_retorno = True

        if not getattr(pedaco, "choices", None):
            return None
        escolha = pedaco.choices[0]
        # O último chunk do stream costuma ter finish_reason definido.
        # Captura pra o consumidor poder detectar corte por 'length'.
        motivo = getattr(escolha, "finish_reason", None)
        if motivo:
            self._finish_reason = motivo
        delta = escolha.delta

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

    def finish_reason(self) -> Optional[str]:
        """O finish_reason do último chunk (ex: 'stop', 'length', None)."""
        return self._finish_reason

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
                if uteis >= self._chars_para_decidir:
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
            self._texto_entregue = True
            yield pedaco
        self._buffer = []
        while not self._esgotado:
            pedaco = self._proximo_pedaco()
            if pedaco:
                self._texto_entregue = True
                yield pedaco


class ProvedorAnthropic(Provedor):
    """
    Provedor Anthropic (usado hoje via Puter). Mantido vivo de propósito:
    é o plano B imediato se a personalidade da Emily não segurar no modelo
    novo. Trocar de volta é editar o campo 'provedor' da rota "conversa".
    """

    nome = "anthropic"
    suporta_ferramentas = True

    def __init__(self, nome: str, base_url: Optional[str], env_chave: str, timeout: float = 90.0):
        self.nome = nome
        self.base_url = base_url
        self.env_chave = env_chave
        self.timeout = timeout
        self._cliente = None
        self._pool_do_cliente = None   # httpx.Client que o SDK está usando
        self._lock = threading.Lock()

    def _obter_cliente(self):
        # Mesma regra do ProvedorOpenAI: pool e cliente do SDK são
        # recriados juntos (ver o comentário lá).
        pool = _cliente_http_do_provedor(self.nome, self.timeout)
        if self._cliente is not None and self._pool_do_cliente is pool:
            return self._cliente
        with self._lock:
            pool = _cliente_http_do_provedor(self.nome, self.timeout)
            if self._cliente is not None and self._pool_do_cliente is pool:
                return self._cliente
            # Mesma tolerância do ProvedorOpenAI: o campo _CHAVE aceita o
            # NOME da variável de ambiente ou o VALOR direto da chave. Sem
            # isto, colar a chave no .env (em vez do nome da variável) fazia
            # o provedor morrer com "precisa de sk-xxx no .env" — mensagem
            # sem sentido para quem acabou de colar justamente a chave.
            if self.env_chave.startswith("sk-"):
                chave = self.env_chave
            else:
                chave = os.getenv(self.env_chave)
            if not chave:
                raise ErroConfiguracao(
                    f"provedor '{self.nome}' precisa de {self.env_chave} no .env"
                )
            try:
                from anthropic import Anthropic
            except ImportError as e:
                raise ErroConfiguracao("pacote 'anthropic' não instalado") from e
            kwargs = {
                "api_key": chave, "timeout": self.timeout,
                # Keep-alive longo também aqui: o SDK da Anthropic aceita um
                # httpx.Client próprio (ver _cliente_http_do_provedor).
                "http_client": pool,
            }
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._cliente = Anthropic(**kwargs)
            self._pool_do_cliente = pool
            _log(f"provedor '{self.nome}' conectado")
            return self._cliente

    def _montar(self, mensagens: List[Mensagem]) -> Tuple[Optional[str], List[dict]]:
        system: Optional[str] = None
        saida: List[dict] = []

        for m in mensagens:
            if m.bruta is not None:
                raw = m.bruta
                if m.papel == 'tool':
                    blocos = [{'type':'tool_result', 'tool_use_id':raw['tool_call_id'], 'content':raw.get('content') or ''}]
                    papel = 'user'
                else:
                    blocos = []
                    if raw.get('content'): blocos.append({'type':'text','text':raw['content']})
                    for call in raw.get('tool_calls') or []:
                        fn=call['function']
                        blocos.append({'type':'tool_use','id':call['id'],'name':fn['name'],'input':json.loads(fn.get('arguments') or '{}')})
                    papel = 'assistant'
                if saida and saida[-1]['role']==papel: saida[-1]['content'].extend(blocos)
                elif blocos: saida.append({'role':papel,'content':blocos})
                continue
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
        cliente = self._obter_cliente()
        system, msgs = self._montar(mensagens)
        corpo = {"model": modelo, "max_tokens": max_tokens or 4096, "messages": msgs}
        if ferramentas:
            corpo['tools']=[{'name':t['function']['name'], 'description':t['function'].get('description',''), 'input_schema':t['function'].get('parameters',{'type':'object','properties':{}})} for t in ferramentas]
            choice='none' if proibir_ferramenta else 'any' if obrigar_ferramenta else 'auto'
            if choice=='any' and any(x in modelo.replace('.', '-') for x in ('sonnet-5-5','opus-5-5','fable-5-1','mythos-5-1')): choice='auto'
            corpo['tool_choice']={'type':choice}
        if system:
            corpo["system"] = system
        if temperatura is not None:
            corpo["temperature"] = temperatura

        try:
            if stream:
                if ferramentas:
                    events=cliente.messages.create(**corpo, stream=True)
                    return FluxoComFerramentas(self._eventos_ferramentas(events))
                return self._iterar_stream(cliente, corpo)
            resposta = cliente.messages.create(**corpo)
            texto="".join(b.text for b in resposta.content if getattr(b, "type", None) == "text")
            if ferramentas:
                return Resposta(texto, [ChamadaFerramenta(b.id,b.name,json.dumps(b.input,ensure_ascii=False)) for b in resposta.content if getattr(b,'type',None)=='tool_use'])
            return texto
        except Exception as e:
            texto = str(e)
            status = getattr(e, "status_code", None)
            if status == 429 or "429" in texto:
                raise ErroLimiteTaxa(f"429 do provedor '{self.nome}': {texto}") from e
            if status in (401, 403):
                raise ErroConfiguracao(
                    f"provedor '{self.nome}' recusou a credencial ou o acesso ao modelo ({status}). Confira as configurações do provedor."
                ) from e
            raise ErroTransporte(f"falha no provedor '{self.nome}': {texto}") from e

    @staticmethod
    def _eventos_ferramentas(events):
        """Preserva texto, IDs e JSON incremental no contrato comum do agente."""
        from types import SimpleNamespace as N
        try:
            for event in events:
                delta=N(content=None,tool_calls=[]); finish=None
                if event.type=='content_block_start' and event.content_block.type=='tool_use':
                    block=event.content_block
                    delta.tool_calls=[N(index=event.index,id=block.id,function=N(name=block.name,arguments=''))]
                elif event.type=='content_block_delta':
                    if event.delta.type=='text_delta': delta.content=event.delta.text
                    elif event.delta.type=='input_json_delta':
                        delta.tool_calls=[N(index=event.index,id=None,function=N(name=None,arguments=event.delta.partial_json))]
                elif event.type=='message_delta':
                    finish={'max_tokens':'length','tool_use':'tool_calls'}.get(event.delta.stop_reason,'stop')
                yield N(choices=[N(delta=delta,finish_reason=finish)])
        finally:
            close=getattr(events,'close',None)
            if close:close()

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


class ProvedorOpenAIComVisaoAnthropic(ProvedorOpenAI):
    """Chat Completions para texto/ferramentas e Messages API para imagens.

    Alguns relays de Claude expõem os dois protocolos com a mesma chave:
    ``/v1/chat/completions`` mantém a compatibilidade OpenAI usada pelo laço de
    ferramentas da Emily, enquanto ``/v1/messages`` preserva os blocos nativos
    de imagem da Anthropic. Usar só o primeiro pode fazer o modelo receber o
    texto do turno sem conseguir decodificar a imagem.

    O desvio é deliberadamente estreito: só ocorre quando a mensagem contém
    imagem e não há catálogo de ferramentas. Todo o restante continua passando
    pelo comportamento já testado de :class:`ProvedorOpenAI`.
    """

    def __init__(self, nome: str, base_url: str, env_chave: str,
                 timeout: float = 90.0):
        super().__init__(nome, base_url, env_chave, timeout)
        self._visao_anthropic = ProvedorAnthropic(
            nome=f"{nome}:visao",
            base_url=_url_sem_v1(base_url) or None,
            env_chave=env_chave,
            timeout=timeout,
        )

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
        if not ferramentas and any(m.imagens for m in mensagens):
            _log_debug(
                f"provedor '{self.nome}': imagem via Messages API nativa"
            )
            return self._visao_anthropic.chamar(
                mensagens=mensagens,
                modelo=modelo,
                max_tokens=max_tokens,
                temperatura=temperatura,
                raciocinio=raciocinio,
                stream=stream,
                ferramentas=None,
                obrigar_ferramenta=False,
                proibir_ferramenta=False,
            )
        return super().chamar(
            mensagens=mensagens,
            modelo=modelo,
            max_tokens=max_tokens,
            temperatura=temperatura,
            raciocinio=raciocinio,
            stream=stream,
            ferramentas=ferramentas,
            obrigar_ferramenta=obrigar_ferramenta,
            proibir_ferramenta=proibir_ferramenta,
        )


# ─────────────────────────────────────────────────────────────────
# Registro de provedores. Adicionar um novo endpoint OpenAI-compatible
# é acrescentar uma linha aqui.
# ─────────────────────────────────────────────────────────────────

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


def _url_sem_v1(base: str) -> str:
    """Base para SDK Anthropic, que acrescenta ``/v1/messages`` sozinho."""
    base = (base or "").rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


# Endpoint OpenAI-compatible que serve o Claude (claude-opus-4-8). Só host e
# porta/caminho vão no .env; o /v1 é normalizado aqui. Vazio até o Vitor
# preencher EMILY_CLAUDE_URL — nesse caso a rota falha com ErroConfiguracao
# clara em vez de bater num host inválido.
URL_CLAUDE = _url_com_v1(os.getenv("EMILY_CLAUDE_URL", ""))

# ═════════════════════════════════════════════════════════════════
# PROVEDORES VIA .ENV — formato por seção
#
# A Emily hoje usa três provedores ativos (claude, nvidia, openrouter) e
# quatro legados (groq, fireworks, puter) registrados pra plano B. Adicionar
# GMI e Ollama — pedidos do Vitor — sem ter que reescrever o dict a cada vez.
#
# Nova forma: o .env carrega seções marcadas por "# >>> provedor: nome" /
# "# <<< provedor: nome" e o _carregar_provedores_do_env() constrói o dict
# PROVEDORES em runtime. Variáveis por provedor:
#
#   EMILY_PROVEDOR_<NOME>_BASE     URL do endpoint (OpenAI-compatible)
#   EMILY_PROVEDOR_<NOME>_CHAVE    variável de ambiente que segura a API key
#                                  (NÃO o valor da chave — o nome da envvar;
#                                  assim a chave real fica onde já está hoje,
#                                  tipo GROQ_API_KEY=...)
#   EMILY_PROVEDOR_<NOME>_MODELO   modelo padrão pra rota "conversa"
#   EMILY_PROVEDOR_<NOME>_MODELOS  lista CSV opcional de modelos pro seletor
#   EMILY_PROVEDOR_<NOME>_TIMEOUT  timeout do SDK em segundos
#   EMILY_PROVEDOR_<NOME>_RPM      limite de requisições por minuto
#   EMILY_PROVEDOR_<NOME>_TIPO     "openai" (default) | "ollama" | "anthropic"
#                                  | "openai_anthropic" (OpenAI para ferramentas,
#                                    Anthropic nativo para imagens)
#   EMILY_PROVEDOR_<NOME>_SEM_CHAVE se "1", não exige API key (Ollama local)
#   EMILY_PROVEDOR_<NOME>_OCULTO   se "1", fica fora dos seletores da interface
#                                  (continua valendo como fallback)
#
# Se nenhuma seção nova for achada no .env, cai no modo legado (PROVEDORES
# hardcoded abaixo) com aviso único no log. Assim .envs antigos continuam
# funcionando até o Vitor migrar pra nova estrutura.
# ═════════════════════════════════════════════════════════════════


@dataclass
class ProvedorConfig:
    """Config de um provedor lido do .env."""
    id: str
    nome_exibicao: str
    base_url: str
    env_chave: str
    env_chave_opcional: bool
    modelo_padrao: str
    modelos_csv: List[str]
    timeout: float
    rpm: int
    tipo: str   # "openai" | "ollama" | "anthropic" | "openai_anthropic"
    oculto: bool = False   # fora dos seletores; segue disponível como fallback


def _parsear_secoes_provedor(caminho_env: str) -> Dict[str, ProvedorConfig]:
    """
    Lê o .env e extrai seções `# >>> provedor: nome` / `# <<< provedor: nome`.

    Variáveis dentro de uma seção viram ProvedorConfig. O formato
    `# >>> provedor: NOME` (com `>>>` e `:`) é o que distingue de comentário
    comum; errei o número de `>` ou esqueci o `:` e a seção é ignorada
    silenciosamente, com log.
    """
    secoes: Dict[str, Dict[str, str]] = {}
    if not os.path.isfile(caminho_env):
        return {}
    secao_atual: Optional[str] = None
    from dotenv import dotenv_values
    valores_decodificados = dotenv_values(caminho_env)
    try:
        with open(caminho_env, "r", encoding="utf-8") as f:
            for linha in f:
                stripped = linha.strip()
                if not stripped or stripped.startswith("#"):
                    m_abre = re.match(r"^#\s*>>>\s*provedor:\s*([A-Za-z0-9_\-]+)\s*$", stripped)
                    m_fecha = re.match(r"^#\s*<<<\s*provedor:\s*([A-Za-z0-9_\-]+)\s*$", stripped)
                    if m_abre:
                        secao_atual = m_abre.group(1).lower()
                        secoes.setdefault(secao_atual, {})
                    elif m_fecha:
                        if secao_atual == m_fecha.group(1).lower():
                            secao_atual = None
                    continue
                if secao_atual is None or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                chave = chave.strip()
                valor = valor.strip()
                if not chave.startswith(f"EMILY_PROVEDOR_{secao_atual.upper()}_"):
                    continue
                # Sobrescreve silenciosamente: última definição vence, igual
                # o .env já se comporta. Empilhamento exigiria schema de lista
                # e nenhum caso de uso justificou até agora.
                secoes[secao_atual][chave] = valores_decodificados.get(chave) or valor
    except OSError as e:
        _log(f"não consegui ler .env em {caminho_env}: {e}")
        return {}

    resultado: Dict[str, ProvedorConfig] = {}
    for pid, vars_ in secoes.items():
        def v(sufixo: str, padrao: str = "") -> str:
            return vars_.get(f"EMILY_PROVEDOR_{pid.upper()}_{sufixo}", padrao)

        tipo = v("TIPO", "openai").strip().lower()
        if tipo not in ("openai", "ollama", "anthropic", "openai_anthropic"):
            _log(f"provedor '{pid}': TIPO='{tipo}' desconhecido, ignorando seção")
            continue

        base_url = v("BASE", "").strip()
        if not base_url and tipo != "anthropic":
            _log(f"provedor '{pid}': BASE vazia, ignorando seção")
            continue

        env_chave = v("CHAVE", "").strip()
        sem_chave = v("SEM_CHAVE", "0").strip() == "1"
        if not env_chave and not sem_chave:
            _log(f"provedor '{pid}': CHAVE vazia e SEM_CHAVE!=1, ignorando seção")
            continue

        modelos_csv = [m.strip() for m in v("MODELOS", "").split(",") if m.strip()]
        if not modelos_csv and v("MODELO", "").strip():
            modelos_csv = [v("MODELO", "").strip()]

        try:
            timeout = float(v("TIMEOUT", "120"))
            rpm = int(v("RPM", str(RPM_PADRAO)))
        except ValueError:
            _log(f"provedor '{pid}': TIMEOUT/RPM inválido, ignorando seção")
            continue

        if pid in ("openai", "omniroute"):
            from emily_remote import provedor_via_fedora, base_llm_fedora
            if provedor_via_fedora(pid, base_url):
                try:
                    base_url = base_llm_fedora()
                    env_chave = "EMILY_PONTE_TOKEN"
                    sem_chave = False
                    _log(f"provedor '{pid}': OmniRoute pela ponte Fedora")
                except RuntimeError as exc:
                    _log(f"provedor '{pid}': {exc}")

        resultado[pid] = ProvedorConfig(
            id=pid,
            nome_exibicao=v("NOME", pid.capitalize()).strip() or pid.capitalize(),
            base_url=_url_com_v1(base_url) if base_url else "",
            env_chave=env_chave or "EMILY_DUMMY_KEY",
            env_chave_opcional=sem_chave or not env_chave,
            modelo_padrao=v("MODELO", "").strip(),
            modelos_csv=modelos_csv,
            timeout=timeout,
            rpm=rpm,
            tipo=tipo,
            oculto=v("OCULTO", "0").strip() == "1",
        )
    return resultado


def _instanciar_provedor(cfg: ProvedorConfig) -> Provedor:
    if cfg.tipo == "anthropic":
        return ProvedorAnthropic(
            nome=cfg.id, base_url=cfg.base_url or None,
            env_chave=cfg.env_chave, timeout=cfg.timeout,
        )
    if cfg.tipo == "openai_anthropic":
        return ProvedorOpenAIComVisaoAnthropic(
            nome=cfg.id, base_url=cfg.base_url,
            env_chave=cfg.env_chave, timeout=cfg.timeout,
        )
    # openai e ollama usam o mesmo ProvedorOpenAI — o Ollama expõe
    # /v1/chat/completions compatível com OpenAI desde 0.1.14. O que muda é
    # a listagem de modelos: o Ollama tem /api/tags próprio, que a interface
    # consulta via _listar_modelos_ollama().
    return ProvedorOpenAI(
        nome=cfg.id, base_url=cfg.base_url,
        env_chave=cfg.env_chave, timeout=cfg.timeout,
    )


def _carregar_provedores_do_env() -> Tuple[Dict[str, Provedor], Dict[str, ProvedorConfig]]:
    """
    Lê seções do .env e devolve (PROVEDORES_instanciados, configs_por_id).

    Se nenhuma seção nova for achada, devolve o dict legado (Claude,
    OpenRouter, NVIDIA, Groq, Fireworks, Puter) e configs vazio. Esse modo
    é o que mantém .envs antigos funcionando até o Vitor migrar.

    Efeito colateral importante: popula o dict global TABELAS com uma entrada
    por provedor novo, contendo as rotas 'conversa' e 'discord'. As demais
    rotas (visão, agentes, títulos) continuam vindo da tabela padrão
    (ROTAS_CLAUDE), que é afinada por tarefa — o provedor novo só entra na
    conversa de verdade. Se um dia uma rota específica precisar do provedor
    novo, basta adicionar a entrada correspondente em _construir_tabela_provedor.
    """
    # O .env ao lado do código é o canônico (funciona no Python direto). No
    # build PyInstaller o DIR_PROJETO é o _internal com um .env empacotado e
    # velho; aí o .env que o Vitor edita está no diretório de trabalho. Tentar
    # os dois, o primeiro que tiver seção vence.
    configs = {}
    caminhos_tentados: List[str] = []
    candidatos = (os.environ["EMILY_CONFIG_FILE"],) if os.getenv("EMILY_CONFIG_FILE") else (
        os.path.join(DIR_PROJETO, ".env"),
        os.path.join(os.getcwd(), ".env"),
    )
    for candidato in candidatos:
        if os.path.isfile(candidato) and candidato not in caminhos_tentados:
            caminhos_tentados.append(candidato)
            configs = _parsear_secoes_provedor(candidato)
            if configs:
                _log(f"seções de provedor encontradas em {candidato}")
                break
    if not configs:
        if os.getenv("EMILY_PUBLIC_MODE") == "1":
            raise ErroConfiguracao("Perfil público sem provedor configurado. Abra emily_public.py --configurar.")
        _log("nenhuma seção [PROVEDOR:*] no .env — usando tabela legada (claude/nvidia/openrouter)")
        return _PROVEDORES_LEGADOS, {}

    provedores: Dict[str, Provedor] = {}
    for pid, cfg in configs.items():
        try:
            provedores[pid] = _instanciar_provedor(cfg)
            _log(f"provedor '{pid}' carregado do .env ({cfg.tipo}, base={cfg.base_url})")
        except Exception as e:
            _log(f"provedor '{pid}': falhou ao instanciar ({e}), pulando")
    return provedores, configs


def _construir_tabela_provedor(pid: str) -> Dict[str, "Rota"]:
    """
    Tabela mínima (rotas 'conversa' e 'discord') pra provedor do .env novo.

    As outras 8 rotas (visão, agentes, etc.) foram afinadas pra Claude /
    NIM / OpenRouter e continuam ativas por baixo; o provedor novo só
    aparece na conversa por voz/texto e no Discord. Quando o Vitor quiser
    afinar uma rota específica pro provedor novo, é esta função que muda.

    A rota 'discord' existe aqui de propósito: TODO o caminho de voz/texto
    do Discord chama por nome (`rota_nome="discord"`), e sem a entrada o
    `rota()` caía no fallback da tabela padrão — trocar o provedor na
    interface continuava mandando o Discord pro claude (que pode estar
    fora), e a Emily "não escutava" na call/chat.

    As duas rotas ganham fallback pro Qwen (quando a seção dele existe
    no .env e o provedor subiu): se o cérebro primário morrer de vez, a
    conversa desce pro Qwen em vez de deixar a Emily muda.
    """
    cfg = PROVEDORES_CONFIG.get(pid)
    modelo = (cfg.modelo_padrao if cfg else "") or ""
    rpm = cfg.rpm if cfg else RPM_PADRAO
    timeout = cfg.timeout if cfg else 90.0

    fallbacks: Tuple[Tuple[str, str], ...] = tuple(_fallbacks_para(pid))
    if pid == PROVEDOR_ROTAS and pid != "claude":
        # Mesmo provedor das rotas internas: herda a cadeia delas (degrau
        # rápido do Kiro e o Claude externo por último), sem repetir o primário.
        fallbacks = tuple(fb for fb in _cadeia_fallbacks_claude if fb != (pid, modelo))

    return {
        "conversa": Rota(
            provedor=pid, modelo=modelo,
            max_tokens=4096, raciocinio=RACIOCINIO_DESLIGADO,
            temperatura=0.85, rpm=rpm,
            fallbacks=tuple(fallbacks),
        ),
        # Mesma afinação da rota discord das tabelas afinadas (claude usa
        # max_tokens=200, temperatura=0.9): os call sites do Discord passam
        # max_tokens explícito, aqui é só o teto de segurança da rota.
        "discord": Rota(
            provedor=pid, modelo=modelo,
            max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO,
            temperatura=0.9, rpm=rpm,
            fallbacks=tuple(fallbacks),
        ),
    }


# ═════════════════════════════════════════════════════════════════
# MODO LEGADO — fallback quando o .env não usa o formato de seções.
# Mantido pra que .env antigos (sem as marcas # >>> provedor:) continuem
# funcionando. O Vitor migra quando quiser; até lá, este dict é o PROVEDORES.
# ═════════════════════════════════════════════════════════════════

_PROVEDORES_LEGADOS: Dict[str, Provedor] = {

    # Só o claude sobrou aqui: é o único provedor que o .env novo usa e o
    # único caminho legado que ainda faz sentido (EMILY_CLAUDE_URL +
    # CLAUDE_API_KEY). NVIDIA, Groq, Fireworks, OpenRouter e Puter saíram
    # junto com os provedores que os usavam — o OmniRoute local cobre o que
    # eles faziam, com uma seção no .env em vez de código.
    #
    # Cérebro principal: Claude servido por um endpoint OpenAI-compatible.
    # Reusa o ProvedorOpenAI inteiro — formato de fio, streaming, tool calling
    # e visão são idênticos, porque o endpoint fala OpenAI de verdade e o proxy
    # é quem traduz pro formato nativo da Anthropic.
    #
    # Só preencher EMILY_CLAUDE_URL e CLAUDE_API_KEY no .env.
    #
    # timeout de 300s, não 90s: as rotas de visão mandam imagem base64 e o
    # Opus é mais lento que os modelos de texto puro.
    "claude": ProvedorOpenAI(
        nome="claude",
        base_url=URL_CLAUDE,
        env_chave="CLAUDE_API_KEY",
        timeout=float(os.getenv("EMILY_CLAUDE_TIMEOUT", "300")),
    ),
}


# Atribuição final: resultado de carregar seções do .env OU o dict legado
# (se o .env ainda não migrou). PROVEDORES_CONFIG é o companion: enquanto
# o legado está ativo, é {} — o que faz listar_provedores() cair na lista
# fixa _PROVEDORES_INTERFACE_FALLBACK lá embaixo.
PROVEDORES: Dict[str, Provedor]
PROVEDORES_CONFIG: Dict[str, ProvedorConfig]
PROVEDORES, PROVEDORES_CONFIG = _carregar_provedores_do_env()



# ═════════════════════════════════════════════════════════════════
# MODELOS E ROTAS
#
# ESTA É A TABELA QUE O BRIEFING PEDIU. Trocar de modelo em qualquer
# tarefa da Emily é mudar uma linha daqui — sem tocar em modelo.py,
# automacao.py, agente_ui.py ou memoria.py.
# ═════════════════════════════════════════════════════════════════

# ─── Modelos do NIM (plano B) ───────────────────────────────────────

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
# ── O AVISO que vale para quem cair no plano B ──────────────────
#
# Comparação medida com a MESMA captura 640x360, 2 amostras por modelo:
#
#   modelo                            descr.   triagem   leitura da tela
#   nvidia/nemotron-nano-12b-v2-vl     4,62s     0,58s   ERRADA
#   Claude (endpoint atual)            3-10s     2,1s    correta
#
# O nemotron é mais rápido e sai de graça no free tier, mas ERRA a leitura.
# Na tela de um editor de texto aberto ele alucinou "um chat em tempo real
# com vários usuários discutindo melhorias para uma plataforma de
# contribuição de código" — leu o texto do arquivo e concluiu que era
# conversa entre pessoas.
#
# Para a Emily isso é a diferença entre comentar a tela e inventar a
# tela. A rota 'visao' existe para ela reagir ao que o Vitor está
# fazendo; reagir a uma tela imaginária é pior que não reagir. Então cair
# no NIM devolve latência e custo zero, e cobra em precisão de visão.
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
    # Cadeia de FALLBACK por (provedor, modelo): se o primário falhar de vez
    # (todas as tentativas), desce pra o próximo par antes de desistir. O
    # chamar() resolve o provedor de cada degrau — é o que permite cair do
    # claude pro Qwen, que vive em outro endpoint. A cadeia das rotas claude
    # é montada depois de ROTAS_CLAUDE (haiku do proxy + Qwen do .env); a da
    # conversa (gmi) ganha o Qwen em _construir_tabela_provedor.
    fallbacks: Tuple[Tuple[str, str], ...] = ()

    def limitador(self, nome_rota: str = None) -> Limitador:
        # Balde por (provedor, rota) e não só por provedor: as tarefas
        # competem por latência entre si — a triagem visual dispara em laço
        # e deixaria a conversa esperando ficha atrás dela.
        chave = f"{self.provedor}_{nome_rota}" if nome_rota else self.provedor
        return limitador_de(chave, self.rpm)


# ══════════════════════════════════════════════════════════════
# TABELA NVIDIA — REMOVIDA
#
# A tabela do NVIDIA NIM (o antigo "plano B") saiu junto com o provedor:
# o .env agora tem só Anthropic, OpenAI e OmniRoute. Todas as rotas que ela
# tinha (conversa, classificador, comando, extracao, visao, triagem_visual,
# agente_ui, agente_jogo, discord) existem na tabela do provedor ATIVO com a
# MESMA afinação por tarefa — nada se perdeu.
#
# A diferença de raciocínio que obrigava tabela separada (o nemotron rejeitava
# reasoning_effort='none') morreu com o provedor.
#
# Quem quiser a NIM de volta hoje tem o OmniRoute, que já roteia modelos
# NVIDIA junto com todo o resto — uma seção no .env, sem tabela nova.
# ══════════════════════════════════════════════════════════════



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

# Modelo único de todas as rotas claude. ORDEM DE LEITURA: primeiro o .env
# novo (EMILY_PROVEDOR_CLAUDE_MODELO — o mesmo que instanciou o provedor),
# depois o var legado (EMILY_CLAUDE_MODELO) e por fim o default histórico.
# Era exatamente essa lacuna que deixava a rota do Discord num modelo morto:
# o provedor vinha do .env novo (base certa) e o MODELO da tabela legada
# velha ("claude-opus-4-8", que o proxy novo rejeita como "Ambiguous model").
MODELO_CLAUDE = (
    os.getenv("EMILY_PROVEDOR_CLAUDE_MODELO", "").strip()
    or os.getenv("EMILY_CLAUDE_MODELO", "").strip()
    or "claude-sonnet-5"
)

# Modelos de FALLBACK do provedor claude, da lista do .env novo
# (EMILY_PROVEDOR_CLAUDE_MODELOS). A cadeia sempre COMEÇA no primário: os
# demais entram na ordem do .env. Com o .env atual fica
# sonnet 4.5 -> haiku 4.5, que é o que o Vitor pediu.
def _modelos_de_secao(pid: str) -> List[str]:
    """
    Os modelos declarados numa seção EMILY_PROVEDOR_<PID>_* do .env, na ordem
    deles. Serve pra montar cadeias de fallback ENTRE provedores (ex.: as
    rotas claude caírem pro Qwen quando o proxy claude morre).
    """
    cfg = PROVEDORES_CONFIG.get(pid)
    if cfg is not None:
        # A seção lida do arquivo vale mais que o ambiente do processo: um
        # reinício por exec herda as variáveis da execução anterior, e elas
        # podem ser de um .env que já mudou.
        modelos = [m for m in cfg.modelos_csv if m]
        padrao = (cfg.modelo_padrao or "").strip()
    else:
        prefixo = f"EMILY_PROVEDOR_{pid.upper()}_"
        csv = os.getenv(prefixo + "MODELOS", "")
        modelos = [m.strip() for m in csv.split(",") if m.strip()]
        padrao = os.getenv(prefixo + "MODELO", "").strip()
    if padrao and padrao not in modelos:
        modelos.insert(0, padrao)
    return modelos

# Balde do limitador do provedor claude. O endpoint não publica RPM;
# 30 é margem contra rajada, não medição.
RPM_CLAUDE = int(os.getenv("EMILY_CLAUDE_RPM", "30"))

# Modelo "rápido" do proxy claude, pros serviços internos baratos (título de
# conversa). Preferência: um modelo com "haiku" na lista do .env
# (EMILY_PROVEDOR_CLAUDE_MODELOS); sem nenhum, cai no ID histórico que o
# proxy Kiro sempre atendeu.
MODELO_CLAUDE_HAIKU = next(
    (m for m in _modelos_de_secao("claude") if "haiku" in m.lower()),
    "kr/claude-haiku-4.5",
)

# ── Provedor das rotas internas ───────────────────────────────────
# Desde 10/10/2026 o provedor externo "claude" ficou instável (falhas e 4–10 s
# por resposta) e a assinatura Codex acabou. As rotas internas passam a usar o
# Kiro do OmniRoute na Oracle, medido em ~1,1 s até o primeiro texto. Sem a
# seção omniroute no .env (outra instalação), tudo continua no "claude".
#
#   EMILY_ROTAS_PROVEDOR       provedor das rotas internas (padrão: omniroute)
#   EMILY_ROTAS_MODELO         modelo forte (padrão: o MODELO da seção)
#   EMILY_ROTAS_MODELO_RAPIDO  modelo das rotas baratas (padrão: um Haiku da lista)
def _provedor_rotas_internas() -> str:
    pedido = os.getenv("EMILY_ROTAS_PROVEDOR", "").strip().lower()
    if pedido and pedido in PROVEDORES:
        return pedido
    return "omniroute" if "omniroute" in PROVEDORES and _modelos_de_secao("omniroute") else "claude"


PROVEDOR_ROTAS = _provedor_rotas_internas()
if PROVEDOR_ROTAS == "claude":
    MODELO_ROTAS = MODELO_CLAUDE
    MODELO_ROTAS_RAPIDO = MODELO_CLAUDE_HAIKU
else:
    _modelos_rotas = _modelos_de_secao(PROVEDOR_ROTAS)
    MODELO_ROTAS = (os.getenv("EMILY_ROTAS_MODELO", "").strip()
                    or (PROVEDORES_CONFIG[PROVEDOR_ROTAS].modelo_padrao
                        if PROVEDOR_ROTAS in PROVEDORES_CONFIG else "").strip()
                    or _modelos_rotas[0])
    MODELO_ROTAS_RAPIDO = (os.getenv("EMILY_ROTAS_MODELO_RAPIDO", "").strip()
                           or next((m for m in _modelos_rotas if "haiku" in m.lower()), MODELO_ROTAS))

ROTAS_CLAUDE: Dict[str, Rota] = {
    "conversa": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.85,
        rpm=RPM_CLAUDE,
    ),
    "classificador": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "comando": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=512, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "extracao": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=300, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.2,
        rpm=RPM_CLAUDE,
    ),
    "visao": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.7,
        rpm=RPM_CLAUDE,
    ),
    "triagem_visual": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "agente_ui": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "agente_jogo": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "discord": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=200, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.9,
        rpm=RPM_CLAUDE,
    ),
    # Rota do título automático (resumo da 1a mensagem). Era GMI/MiniMax-M3,
    # mas o token da GMI morreu (401 "Invalid token, failed to decode") e os
    # títulos pararam de ser gerados por LLM. Agora é o Haiku do proxy claude:
    # rápido, barato, já provado pelo celular, e herda a cadeia de fallback
    # das rotas claude (se o haiku cair, o sonnet assume sozinho).
    "titulo": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS_RAPIDO,
        max_tokens=40, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    # Extração da memória unificada. É uma rota DEDICADA e fica presa ao Haiku:
    # trocar o cérebro no composer não deve transformar um serviço barato em
    # várias chamadas ao modelo principal. O extrator pede JSON estruturado e
    # valida tudo localmente antes de persistir.
    "memoria_extracao": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS_RAPIDO,
        max_tokens=900, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    # Rotas extras da família claude. Existiam para dar ao Discord/Emily Code
    # modelos de outro provedor (GMI/Qwen/DeepSeek), mas esses provedores
    # foram REMOVIDOS do .env. Agora usam o próprio Claude: o Sonnet 5 é
    # multimodal (vê imagem — o que o Qwen não fazia) e o Haiku segura as
    # tarefas baratas/determinísticas. Os nomes '_gmi' ficam para não quebrar
    # quem chama por eles.
    "comando_interpreta": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=256, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "visao_gmi": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=1024, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.7,
        rpm=RPM_CLAUDE,
    ),
    "triagem_visual_gmi": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=16, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.0,
        rpm=RPM_CLAUDE,
    ),
    "agente_ui_gmi": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    "agente_jogo_gmi": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=2048, raciocinio=RACIOCINIO_DESLIGADO, temperatura=0.1,
        rpm=RPM_CLAUDE,
    ),
    # Emily Code multi-modelo: o Sonnet implementa (escreve o código de
    # verdade) e o Haiku revisa. Continuam na tabela padrão pra funcionar
    # independente de qual provedor está ativo no EMILY_PROVEDOR_LLM (o
    # rota() cai aqui quando a rota não existe na tabela ativa).
    "code_implementador": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=4096, raciocinio=RACIOCINIO_NORMAL, temperatura=0.5,
        rpm=RPM_CLAUDE,
    ),
    "code_revisor": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS_RAPIDO,
        max_tokens=4096, raciocinio=RACIOCINIO_NORMAL, temperatura=0.3,
        rpm=RPM_CLAUDE,
    ),
    "code_debatedor": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=4096, raciocinio=RACIOCINIO_NORMAL, temperatura=0.5,
        rpm=RPM_CLAUDE,
    ),
    # Planejador do Emily Code multi-modelo: raciocínio alto de verdade, que
    # o modelo novo sustenta.
    "code_planejador": Rota(
        provedor=PROVEDOR_ROTAS, modelo=MODELO_ROTAS,
        max_tokens=2048, raciocinio=RACIOCINIO_NORMAL, temperatura=0.7,
        rpm=RPM_CLAUDE,
    ),
}

# Cadeia de fallback das rotas claude, em pares (provedor, modelo):
#   1. os outros modelos do próprio provedor claude (a lista do .env, ex.:
#      haiku 4.5, opus 5, fable 5);
#   2. o OMNIROUTE LOCAL, quando a seção dele existe no .env.
#
# O OmniRoute é a rede de segurança certa porque é LOCAL: sobrevive à queda
# do provedor externo e ainda responde se a internet cair, sem depender de
# internet nenhuma pra falar com um provedor de terceiro.
#
# As rotas de visão que moram nesta tabela (visão, agentes, code_*) ficam de
# fora — o fallback é por provedor, não por tabela.
def _fallbacks_para(pid: str) -> List[Tuple[str, str]]:
    """Cadeia de segurança de um provedor: OmniRoute configurado, se existir."""
    if pid == "omniroute" or "omniroute" not in PROVEDORES:
        return []
    return [("omniroute", m) for m in _modelos_de_secao("omniroute")]


if PROVEDOR_ROTAS == "claude":
    _cadeia_fallbacks_claude: List[Tuple[str, str]] = [
        ("claude", m) for m in _modelos_de_secao("claude") if m != MODELO_CLAUDE
    ]
    _cadeia_fallbacks_claude += _fallbacks_para("claude")
else:
    # Um degrau rápido do mesmo provedor e, por último, o Claude externo, que
    # serve de reserva se o Kiro cair. Poucos degraus de propósito: cada um
    # gasta tentativas e tempo antes de desistir.
    _cadeia_fallbacks_claude = [
        (PROVEDOR_ROTAS, m) for m in dict.fromkeys((MODELO_ROTAS_RAPIDO, "kr/claude-sonnet-4.6"))
        if m != MODELO_ROTAS and m in _modelos_de_secao(PROVEDOR_ROTAS)
    ]
    if "claude" in PROVEDORES and MODELO_CLAUDE:
        _cadeia_fallbacks_claude.append(("claude", MODELO_CLAUDE))
if _cadeia_fallbacks_claude:
    _log(f"rotas internas em '{PROVEDOR_ROTAS}' ({MODELO_ROTAS}); fallbacks: "
         + ", ".join(f"{p}:{m}" for p, m in _cadeia_fallbacks_claude))
    for _nome_rota_claude, _rota_claude in ROTAS_CLAUDE.items():
        if not _rota_claude.fallbacks:
            _rota_claude.fallbacks = tuple(
                fb for fb in _cadeia_fallbacks_claude
                if fb != (_rota_claude.provedor, _rota_claude.modelo))

# ═══════════════════════════════════════════════════════════════
# TABELA OPENROUTER — REMOVIDA
#
# A tabela do OpenRouter saiu junto com o provedor. Ela existia para deixar
# a Emily inteira em QUALQUER modelo do catálogo do OpenRouter, e as rotas
# que ela produzia eram as mesmas da tabela claude só que apontando para
# outro provedor — nada exclusivo se perdeu.
#
# Para ter modelos variados hoje: a seção `omniroute` do .env alcança
# mais de mil modelos (kr/*, gpt-5.6-*, claude-*, minimax...) pelo gateway
# LOCAL — sem o OpenRouter no meio e sem RPM de terceiro.
# ═══════════════════════════════════════════════════════════════



# ═════════════════════════════════════════════════════════════════
# SELEÇÃO DA TABELA ATIVA
# ═════════════════════════════════════════════════════════════════

TABELAS: Dict[str, Dict[str, Rota]] = {
    # Tabela única, afinada por tarefa, servida pelo provedor ATIVO. Os ids
    # 'openai' e 'omniroute' entram sob demanda em _resolver_tabela (tabela
    # mínima com 'conversa' e 'discord'); as demais rotas caem aqui.
    "claude": ROTAS_CLAUDE,
}

TABELA_PADRAO = "claude"


def _resolver_tabela(nome: Optional[str]) -> Tuple[str, Dict[str, Rota]]:
    """
    Escolhe a tabela de rotas ativa a partir do valor da variável.

    Tolera espaço nas pontas e qualquer caixa, porque valor de .env copiado
    à mão vem com lixo — e falhar por causa de um espaço seria um jeito
    idiota de deixar a Emily muda.

    Provedores novos (vindos das seções do .env) NÃO estão em TABELAS
    inicialmente — eles ganham entrada sob demanda aqui. Sem isso, o
    `EMILY_PROVEDOR_LLM=gmi` falharia com "valor não aceito" mesmo o
    provedor estando registrado. A tabela construída na hora é mínima
    (só 'conversa') — ver _construir_tabela_provedor pra entender.

    Levanta ErroConfiguracao citando os valores aceitos quando o valor não
    bate com nenhum provedor registrado. Não cai no default em silêncio:
    se o Vitor escreveu 'nvida' por engano, ele precisa SABER, e não
    descobrir três dias depois que estava na tabela errada o tempo todo.
    """
    limpo = (nome or "").strip().lower()
    if not limpo:
        return TABELA_PADRAO, TABELAS[TABELA_PADRAO]
    if limpo in TABELAS:
        return limpo, TABELAS[limpo]
    if limpo in PROVEDORES:
        # Tabela sob demanda pro provedor novo. Adiciona ao TABELAS pra que
        # chamadas seguintes não recriem — e pra que o diagnóstico liste ela.
        TABELAS[limpo] = _construir_tabela_provedor(limpo)
        _log(f"tabela '{limpo}' construída em runtime "
             "(rotas 'conversa' e 'discord' do provedor novo)")
        return limpo, TABELAS[limpo]
    raise ErroConfiguracao(
        f"EMILY_PROVEDOR_LLM='{nome}' não é um valor aceito. "
        f"Use um destes: {', '.join(sorted(PROVEDORES))}"
    )


def _provedor_llm_efetivo() -> Optional[str]:
    """EMILY_PROVEDOR_LLM, trocado pelo provedor das rotas se o pedido não tem modelos.

    Uma seção sem modelo nenhum (a assinatura acabou, o .env foi esvaziado) deixava
    o seletor do chat vazio e a conversa sem modelo. Cair no provedor das rotas
    internas mantém a Emily utilizável e avisa no log.
    """
    pedido = os.getenv("EMILY_PROVEDOR_LLM")
    pid = (pedido or "").strip().lower()
    cfg = PROVEDORES_CONFIG.get(pid)
    if (cfg is not None and cfg.tipo != "ollama"
            and not (cfg.modelos_csv or cfg.modelo_padrao)
            and PROVEDOR_ROTAS != pid and PROVEDOR_ROTAS in PROVEDORES):
        _log(f"EMILY_PROVEDOR_LLM='{pid}' não tem modelos; usando '{PROVEDOR_ROTAS}'")
        return PROVEDOR_ROTAS
    return pedido


TABELA_ATIVA, ROTAS = _resolver_tabela(_provedor_llm_efetivo())

if TABELA_ATIVA != TABELA_PADRAO:
    _log(f"tabela de rotas ATIVA: '{TABELA_ATIVA}' (via EMILY_PROVEDOR_LLM)")

ROTA_PADRAO = "conversa"


# ── Modelo do Discord escolhido na interface ─────────────────────
# O Vitor pediu pra trocar o modelo das respostas do Discord SEM editar
# código. O override vive aqui (não na tabela, que é imutável por design)
# e persiste nas preferências — sobrevive a fechar a Emily. Vazio/nulo =
# "Padrão", a rota discord afinada no dicionário de cima.
_discord_lock = threading.Lock()
_discord_modelo_override: Optional[str] = None


def modelo_discord() -> str:
    """Modelo em uso na rota do Discord ('' = o padrão da rota)."""
    with _discord_lock:
        override = _discord_modelo_override
    if override:
        return override
    try:
        import preferencias
        return (preferencias.obter("modelo_discord") or "").strip()
    except Exception:
        return ""


def definir_modelo_discord(nome: str) -> bool:
    """Define (ou reseta, com '') o modelo do Discord. Valida que a rota existe."""
    global _discord_modelo_override
    nome = (nome or "").strip()
    if nome:
        try:
            rota("discord")
        except Exception:
            return False
    with _discord_lock:
        _discord_modelo_override = nome or None
    try:
        import preferencias
        preferencias.definir(modelo_discord=nome)
    except Exception:
        pass
    return True


def _modelo_do_provedor(pid: str, modelo: str) -> bool:
    """O modelo `modelo` pode ser servido pelo provedor `pid`?

    Provedor legado sem config (sem seção no .env): devolve True — sem lista
    pra conferir, mantém o comportamento antigo em vez de descartar override
    válido. Com config, vale o modelo padrão ou qualquer id da lista MODELOS.
    """
    cfg = PROVEDORES_CONFIG.get(pid)
    if cfg is None:
        return True
    if cfg.tipo in ('anthropic','openai_anthropic'):
        from limites_modelos import catalogo
        live=catalogo(pid)
        if live:return modelo.lower() in live
    if cfg.modelo_padrao and cfg.modelo_padrao == modelo:
        return True
    return modelo in cfg.modelos_csv


def _com_override(nome: str, r: Rota) -> Rota:
    """Devolve a rota com o override do Discord aplicado (cópia, sem mutar
    a instância compartilhada da tabela — outras rotas leem dela)."""
    if nome != "discord":
        return r
    alvo = modelo_discord()
    if not alvo or alvo == r.modelo:
        return r
    if not _modelo_do_provedor(r.provedor, alvo):
        # A pref de modelo do Discord foi salva quando OUTRO provedor estava
        # ativo (ex.: modelo do claude escolhido antes de trocar pro Qwen).
        # Aplicar um modelo de outro provedor aqui viraria 400 na hora da
        # chamada — ignora e usa o padrão da rota ativa.
        _log(f"override de modelo do Discord ('{alvo}') não pertence ao "
             f"provedor '{r.provedor}'; usando o modelo da rota ('{r.modelo}')")
        return r
    return replace(r, modelo=alvo)


def rota(nome: str) -> Rota:
    if os.getenv("EMILY_PUBLIC_MODE") == "1" and nome not in ROTAS:
        # Classificação e títulos devem usar a mesma conta escolhida no setup,
        # sem cair nos endpoints/modelos legados da instalação do autor.
        if nome in TABELAS.get(TABELA_PADRAO, {}):
            return _com_override(nome, replace(ROTAS["conversa"], fallbacks=()))
        raise ErroConfiguracao(f"A rota '{nome}' não existe.")
    if nome not in ROTAS:
        # Fallback para a tabela padrão (claude). Provedores novos (GMI,
        # Ollama, Qwen) definem as rotas "conversa" e "discord"; as demais
        # (visão, triagem, classificador, etc.) continuam na tabela padrão,
        # que tem todas as rotas afinadas por tarefa. Sem este fallback,
        # trocar o provedor da conversa quebraria visão e agentes.
        if nome in TABELAS.get(TABELA_PADRAO, {}):
            return _com_override(nome, TABELAS[TABELA_PADRAO][nome])
        raise ErroConfiguracao(
            f"rota '{nome}' não existe na tabela '{TABELA_ATIVA}' "
            f"nem na tabela padrão '{TABELA_PADRAO}'. "
            f"Rotas disponíveis: {', '.join(sorted(ROTAS))}"
        )
    return _com_override(nome, ROTAS[nome])


# ═════════════════════════════════════════════════════════════════
# TROCA EM RUNTIME — o Vitor escolhe modelo e raciocínio no chat
#
# Só a rota 'conversa' (o cérebro do chat e da voz) é afetada. Visão,
# classificador e triagem continuam com o que foi afinado pra elas — botar
# raciocínio 'alto' num classificador só somaria latência à toa. Rota é
# dataclass mutável, então mexer no modelo/raciocínio dela é uma atribuição.
# ═════════════════════════════════════════════════════════════════

# Catálogo do que a interface oferece, POR TABELA. O seletor do chat mostra só
# a lista da tabela ativa — não faz sentido oferecer Opus quando a Emily roda
# no OpenRouter, e vice-versa.
#
# Modo dinâmico (PROVEDORES_CONFIG populado pelas seções do .env): cada
# provedor tem sua lista vinda de EMILY_PROVEDOR_<NOME>_MODELOS. O Ollama tem
# ainda o fallback de consultar /api/tags — ver _listar_modelos_ollama().
#
# Modo legado (PROVEDORES_CONFIG vazio): mantém o comportamento antigo, com
# listas fixas por nome de provedor, pra .envs que ainda não migraram.
#
# 'id' é o nome EXATO que o endpoint aceita; 'nome' é o rótulo curto do botão;
# 'sobre' é a descriçãozinha embaixo do nome.

# Lista fixa por provedor, usada APENAS no modo legado (sem seções no .env).
# Ficou só o claude: é o único provedor com tabela legada que sobrou.
_MODELOS_POR_TABELA: Dict[str, list] = {
    "claude": [
        {"id": "claude-sonnet-5", "nome": "Sonnet 5", "sobre": "Padrão"},
        {"id": "claude-opus-5", "nome": "Opus 5", "sobre": "Trabalho pesado"},
        {"id": "claude-haiku-4.5", "nome": "Haiku 4.5", "sobre": "Rápido e barato"},
    ],
}


# Cache de modelos do Ollama. O endpoint expõe /api/tags; cachear por 60s evita
# bater lá toda vez que a interface re-renderiza o seletor. Vazio = ainda não
# consultou. Erro de conexão = chave "erro" no dict, lido uma vez e nunca mais.
_MODELOS_OLLAMA_CACHE: Dict[str, object] = {"quando": 0.0, "modelos": [], "erro": ""}
_MODELOS_OLLAMA_TTL = 60.0


def _listar_modelos_ollama(base_url: str) -> Tuple[List[str], str]:
    """
    Lista modelos do Ollama via /api/tags. Devolve (lista, erro).

    O Ollama expõe dois endpoints: o OpenAI-compat em /v1/chat/completions
    (que a Emily usa pra conversar) e o nativo em /api/tags (que lista
    modelos). Se a base_url termina em /v1, troco pelo /api/tags na mesma
    origem; se for a URL nativa `http://localhost:11434`, uso direto.
    """
    agora = time.monotonic()
    if agora - _MODELOS_OLLAMA_CACHE["quando"] < _MODELOS_OLLAMA_TTL:
        if _MODELOS_OLLAMA_CACHE["erro"] or _MODELOS_OLLAMA_CACHE["modelos"]:
            return (list(_MODELOS_OLLAMA_CACHE["modelos"]),  # type: ignore[arg-type]
                    str(_MODELOS_OLLAMA_CACHE["erro"]))

    # base_url vem com /v1 (passou por _url_com_v1). A origem do /api/tags
    # é a base SEM o /v1: http://localhost:11434/v1 -> http://localhost:11434/api/tags.
    raiz = base_url.rstrip("/")
    if raiz.endswith("/v1"):
        raiz = raiz[:-3]
    url = f"{raiz}/api/tags"
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=3) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
        modelos = [m["name"] for m in dados.get("models", []) if m.get("name")]
        _MODELOS_OLLAMA_CACHE.update({"quando": agora, "modelos": modelos, "erro": ""})
        return modelos, ""
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        _MODELOS_OLLAMA_CACHE.update({"quando": agora, "modelos": [], "erro": msg})
        return [], msg


def _nome_limpo_modelo(modelo_id: str) -> str:
    """
    Converte um ID técnico de modelo num rótulo legível.

    Entradas comuns:
      'qwen/qwen3.8-max-free'      -> 'Qwen 3.8 Max'
      'MiniMaxAI/MiniMax-M3'       -> 'MiniMax M3'
      'z-ai/glm-5.2'               -> 'GLM 5.2'
      'claude-opus-4-8'            -> 'Claude Opus 4.8'
      'meta-llama/llama-3.3-70b'   -> 'Llama 3.3 70B'
      'stealth/ox-alpha'           -> 'Ox Alpha'

    O ID cru ('qwen/qwen3.8-max-free') é mantido no campo 'id' — quem chama a
    API precisa dele exato. Este rótulo é só o que a interface mostra.
    """
    texto = (modelo_id or "").strip()

    # Remove sufixos do OpenRouter/plataformas que ninguém quer ver.
    texto = re.sub(r"[:/-]?(free|beta|latest)$", "", texto, flags=re.IGNORECASE).strip()

    # Remove prefixo 'fornecedor/' (qwen/, MiniMaxAI/, z-ai/, meta-llama/...).
    if "/" in texto:
        texto = texto.split("/", 1)[1]

    # Números de versão separados por hífen viram ponto (4-8 -> 4.8).
    texto = re.sub(r"(\d)-(\d)", r"\1.\2", texto)

    # Separa palavra de várias letras seguida de número (qwen3.8 -> qwen 3.8),
    # mas NÃO quebra siglas de 1 letra (M3, v2) — senão vira "M 3".
    texto = re.sub(r"([a-zA-Z]{2,})(\d)", r"\1 \2", texto)

    # Hífen restante vira espaço.
    texto = texto.replace("-", " ")

    # Tokeniza, preservando unidades tipo "70b", "M3", "v2", "4.8".
    tokens = re.findall(r"[a-zA-Z]+(?:\d+(?:\.\d+)?)?|\d+(?:\.\d+)?[a-zA-Z]*|[a-zA-Z]+|\d+(?:\.\d+)?", texto)

    # Mapeamento de siglas/nomes pra capitalização bonita.
    MAPA_PALAVRA = {
        "qwen": "Qwen", "glm": "GLM", "mini": "Mini", "max": "Max",
        "claude": "Claude", "opus": "Opus", "sonnet": "Sonnet",
        "haiku": "Haiku", "llama": "Llama", "gemini": "Gemini",
        "deepseek": "DeepSeek", "gpt": "GPT", "ox": "Ox", "alpha": "Alpha",
        "stealth": "Stealth", "nemotron": "Nemotron", "nano": "Nano",
        "z": "Z", "ai": "AI", "turbovl": "TurboVL", "grok": "Grok",
        "instruct": "Instruct", "vl": "VL", "v": "V", "it": "IT",
        "b": "B", "nano": "Nano",
    }

    partes = []
    for tok in tokens:
        t_low = tok.lower()
        # Token só de letras: capitaliza via mapa.
        if tok.isalpha():
            base = MAPA_PALAVRA.get(t_low, tok)
            partes.append(base[:1].upper() + base[1:])
            continue
        # Token com letra + número (M3, 70b, v2, 4.8, 5.2): capitaliza a letra
        # e mantém o número junto. "M3" -> "M3", "70b" -> "70B".
        letras = re.findall(r"[a-zA-Z]+", tok)
        numeros = re.findall(r"\d+(?:\.\d+)?", tok)
        if letras and numeros:
            resultado = ""
            # Reconstroi na ordem: começa com número ou letra.
            if tok[0].isdigit():
                # "70b" -> "70" + "B"
                resultado = numeros[0]
                for l in letras:
                    base = MAPA_PALAVRA.get(l.lower(), l)
                    resultado += base[:1].upper() + base[1:]
            else:
                # "M3", "v2" -> "M" + "3", "V" + "2"
                for l in letras:
                    base = MAPA_PALAVRA.get(l.lower(), l)
                    resultado += base[:1].upper() + base[1:]
                resultado += numeros[0]
            partes.append(resultado)
        else:
            # Só número
            partes.append(tok)

    resultado = " ".join(partes)
    return resultado or (modelo_id or "")


def _janelas_conhecidas(pid: str) -> Dict[str, int]:
    """Janelas de contexto já conhecidas do provedor (memória/disco, sem rede)."""
    try:
        from limites_modelos import catalogo_em_cache
        return catalogo_em_cache(pid)
    except Exception:  # noqa: BLE001 - o rótulo é só um enfeite
        return {}


def _rotulo_janela(tokens: Optional[int]) -> str:
    if not tokens:
        return ""
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:g}M de contexto"
    return f"{tokens // 1000}k de contexto"


def _modelos_provedor(pid: str) -> List[dict]:
    """
    Modelos do provedor `pid` no formato do seletor ({id, nome, sobre}).

    Ordem: lista do .env primeiro, depois fallback (lista fixa legado para os
    três provedores clássicos; /api/tags para Ollama). Se nada der certo,
    devolve o modelo padrão como única opção.
    """
    cfg = PROVEDORES_CONFIG.get(pid)

    # Modo dinâmico: provedor veio de uma seção do .env.
    if cfg is not None:
        candidatos: List[str] = list(cfg.modelos_csv)
        if cfg.tipo in ('anthropic','openai_anthropic'):
            from limites_modelos import catalogo
            live=catalogo(pid)
            if live: candidatos=list(live)

        if cfg.tipo == "ollama" and not candidatos:
            locais, erro = _listar_modelos_ollama(cfg.base_url)
            if erro:
                _log(f"Ollama '{pid}': não consegui listar modelos ({erro}). "
                     f"Usando só o modelo padrão.")
            candidatos = locais
        if not candidatos and cfg.modelo_padrao:
            candidatos = [cfg.modelo_padrao]

        janelas = _janelas_conhecidas(pid)
        saida = []
        for mid in candidatos:
            mid = mid.strip()
            if not mid:
                continue
            # O subtítulo mostra a janela de contexto quando o catálogo do
            # provedor já foi consultado; senão, o nome do provedor.
            sobre = _rotulo_janela(janelas.get(mid.lower())) or cfg.nome_exibicao
            saida.append({"id": mid, "nome": _nome_limpo_modelo(mid), "sobre": sobre})
        return saida

    # Modo legado.
    return [dict(m) for m in _MODELOS_POR_TABELA.get(pid, [])]


def listar_provedores() -> list:
    """
    Provedores conhecidos, no formato que a interface consome.

    Cada provedor traz seus modelos já prontos pra renderizar. A interface
    antiga só recebia a lista de modelos da tabela ativa — agora ela vê o
    mapa inteiro e desenha o popover em dois passos (provedor → modelo).
    """
    saida = []
    for pid in PROVEDORES:
        cfg = PROVEDORES_CONFIG.get(pid)
        if cfg is not None and cfg.oculto:
            continue
        modelos = _modelos_provedor(pid)
        # Seção sem modelo nenhum (ex.: assinatura encerrada) não é opção:
        # mostrar "sem modelos" no seletor só convidava a um clique inútil.
        if cfg is not None and not modelos:
            continue
        nome = cfg.nome_exibicao if cfg else pid.capitalize()
        saida.append({
            "id": pid,
            "nome": nome,
            "modelos": modelos,
        })
    return saida


# Mantida por compatibilidade: o JS antigo chama modelos_disponiveis() e
# espera só a lista de modelos do provedor ativo. Devolve o mesmo formato.
def modelos_disponiveis() -> list:
    """Modelos do provedor ativo (cópia, pra não vazar referência)."""
    return _modelos_provedor(TABELA_ATIVA)


def _provedor_padrao() -> str:
    """Provedor default se o usuário não escolheu nenhum. A tabela ativa vence."""
    return TABELA_ATIVA


# Os níveis de raciocínio que a interface expõe, na ordem do seletor.
NIVEIS_RACIOCINIO_INTERFACE = [
    {"id": RACIOCINIO_BAIXO, "nome": "Baixo"},
    {"id": RACIOCINIO_MEDIO, "nome": "Médio"},
    {"id": RACIOCINIO_ALTO, "nome": "Alto"},
]
NIVEIS_RACIOCINIO_GPT6 = [
    {"id": RACIOCINIO_DESLIGADO, "nome": "Sem raciocínio"},
    *NIVEIS_RACIOCINIO_INTERFACE,
    {"id": RACIOCINIO_EXTRA_ALTO, "nome": "Extra alto"},
    {"id": RACIOCINIO_MAXIMO, "nome": "Máximo"},
]


def _modelo_claude_kiro(modelo: str) -> bool:
    """Claude servido pelo Kiro via OmniRoute (ids kr/claude-* ou kiro/claude-*)."""
    return bool(re.match(r"^(?:kr|kiro)/claude-", (modelo or "").lower()))


def niveis_raciocinio(modelo: str = "") -> list:
    """Níveis disponíveis para o modelo do chat, sem opções que ele rejeita.

    Os Claude do Kiro publicam effort_tiers none..max no catálogo e aceitaram os
    seis valores em chamadas reais (10/10/2026); os demais Claude seguem com os
    três da interface porque o relay deles não foi medido.
    """
    niveis = (NIVEIS_RACIOCINIO_GPT6 if (_modelo_gpt6(modelo) or _modelo_claude_kiro(modelo))
              else NIVEIS_RACIOCINIO_INTERFACE)
    return [dict(n) for n in niveis
            if not (_modelo_gpt6_sem_none(modelo)
                    and n["id"] == RACIOCINIO_DESLIGADO)]


def definir_provedor_e_modelo(provedor: str, modelo: str) -> bool:
    """
    Troca provedor e modelo em runtime.

    Se o provedor pedido não está registrado (não veio do .env OU não é legado),
    devolve False sem mexer em nada. Se o modelo vier vazio, usa o padrão do
    provedor (primeiro da lista de modelos, ou cfg.modelo_padrao).
    """
    global TABELA_ATIVA, ROTAS
    pid = (provedor or "").strip().lower()
    if pid not in PROVEDORES:
        _log(f"definir_provedor_e_modelo: provedor '{pid}' não está registrado")
        return False

    modelo = (modelo or "").strip()
    if not modelo:
        # Modelo default do provedor novo: primeiro da lista OU modelo_padrao.
        candidatos = _modelos_provedor(pid)
        if candidatos:
            modelo = candidatos[0]["id"]
        elif pid in PROVEDORES_CONFIG and PROVEDORES_CONFIG[pid].modelo_padrao:
            modelo = PROVEDORES_CONFIG[pid].modelo_padrao
        else:
            # Sem lista e sem modelo_padrao: herda o modelo atual, que é a
            # melhor chance de a chamada não falhar com 400.
            modelo = ROTAS["conversa"].modelo if "conversa" in ROTAS else ""

    # Troca a tabela de rotas ativa. Cada provedor tem a sua própria.
    try:
        nome_tabela, rotas = _resolver_tabela(pid)
    except ErroConfiguracao:
        return False
    TABELA_ATIVA = nome_tabela
    ROTAS = rotas

    # Aplica o modelo na nova tabela ativa.
    if "conversa" in ROTAS:
        ROTAS["conversa"].modelo = modelo
        if (_modelo_gpt6_sem_none(modelo)
                and ROTAS["conversa"].raciocinio == RACIOCINIO_DESLIGADO):
            ROTAS["conversa"].raciocinio = RACIOCINIO_BAIXO
        _log(f"provedor agora é '{pid}', modelo da conversa: '{modelo}'")
    # O Discord tem rota própria. A troca de provedor feita na interface
    # precisa alcançá-la também — o modelo antigo (ou o default da seção)
    # pertencia a outro provedor e viraria 400 na primeira resposta.
    if "discord" in ROTAS and ROTAS["discord"].provedor == pid:
        ROTAS["discord"].modelo = modelo
        _log(f"rota discord agora é '{pid}/{modelo}'")
    return True


def definir_modelo_conversa(modelo: str) -> bool:
    """
    Troca o modelo da rota de conversa em runtime. Devolve se aplicou.

    Mantida por compatibilidade com o JS antigo. Não valida contra uma lista
    fechada de propósito: o endpoint é a fonte da verdade sobre quais modelos
    existem, e amarrar aqui obrigaria a editar código toda vez que surgisse
    um modelo novo. Vazio é ignorado.
    """
    modelo = (modelo or "").strip()
    if not modelo:
        _log("definir_modelo_conversa: nome vazio, ignorando")
        return False
    if "conversa" not in ROTAS:
        _log("definir_modelo_conversa: rota 'conversa' não existe na tabela ativa")
        return False
    ROTAS["conversa"].modelo = modelo
    if (_modelo_gpt6_sem_none(modelo)
            and ROTAS["conversa"].raciocinio == RACIOCINIO_DESLIGADO):
        ROTAS["conversa"].raciocinio = RACIOCINIO_BAIXO
    _log(f"modelo da conversa agora é '{modelo}'")
    return True


def definir_raciocinio_conversa(nivel: str) -> bool:
    """
    Troca o nível de raciocínio da rota de conversa. Devolve se aplicou.

    Só aceita nível conhecido de PARAMS_RACIOCINIO — nível inventado viraria
    'sem parâmetro' silencioso, e o Vitor acharia que mudou sem ter mudado.
    """
    nivel = (nivel or "").strip().lower()
    if nivel not in PARAMS_RACIOCINIO:
        _log(f"definir_raciocinio_conversa: nível '{nivel}' desconhecido, ignorando "
             f"(aceitos: {', '.join(sorted(PARAMS_RACIOCINIO))})")
        return False
    if "conversa" not in ROTAS:
        _log("definir_raciocinio_conversa: rota 'conversa' não existe na tabela ativa")
        return False
    if _modelo_gpt6_sem_none(ROTAS["conversa"].modelo) and nivel == RACIOCINIO_DESLIGADO:
        _log("GPT-6 Astra e GPT-6.1 Sol não aceitam raciocínio desligado; usando baixo")
        nivel = RACIOCINIO_BAIXO
    ROTAS["conversa"].raciocinio = nivel
    _log(f"raciocínio da conversa agora é '{nivel}'")
    return True


# ═════════════════════════════════════════════════════════════════
# RETRY E PORTA DE ENTRADA
# ═════════════════════════════════════════════════════════════════

ESPERA_BASE = 1.0      # segundos
ESPERA_MAXIMA = 20.0

# Teto de tempo TOTAL gasto tentando, contado da primeira tentativa. Depois
# disso nenhuma tentativa nova começa, mesmo que ainda haja tentativa no
# orçamento de `cfg.tentativas`.
#
# Existe porque contar tentativas não limita espera. O caso medido: o endpoint
# derrubava a requisição em 15s sem primeiro token e repetia 3 vezes
# sozinho; cada uma dessas rodadas de 45s valia UMA tentativa aqui, e as 4
# tentativas com backoff deixaram a Emily calada uns 3 minutos no Discord, com
# o "digitando..." ligado, pra no fim dizer que não conseguiu. Falhar em 1
# minuto e admitir é melhor que sumir por 3 e admitir.
ORCAMENTO_RETENTATIVA = float(os.getenv("EMILY_ORCAMENTO_RETENTATIVA", "90"))


def _espera_backoff(tentativa: int) -> float:
    """Exponencial com jitter, pra não sincronizar as threads no retry."""
    bruto = min(ESPERA_MAXIMA, ESPERA_BASE * (2 ** tentativa))
    return bruto * (0.5 + random.random() * 0.5)


from diagnostico_execucao import measured as _medir_execucao, stream_events as _medir_stream, event as _evento_execucao

@_medir_execucao("model_request")
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
    provedor: Optional[str] = None,
    raciocinio: Optional[str] = None,
    on_retry: Optional[Callable[[int, int], None]] = None,
) -> RespostaLLM:
    """
    Porta de entrada única. Resolve a rota, respeita o rate limit,
    tenta de novo em 429/5xx com backoff, e loga tudo que der errado.

    max_tokens, modelo, provedor, raciocinio e temperatura sobrescrevem a rota
    quando informados. Os overrides são locais à chamada: não alteram a rota
    global nem a escolha salva na interface.

    Levanta ErroLLM se todas as tentativas falharem. NÃO devolve None
    silenciosamente — falha silenciosa é o bug que essa camada existe
    pra matar.
    """
    cfg = rota(rota_nome)
    provedor_primario = (provedor or cfg.provedor).strip()
    provedor_obj = PROVEDORES.get(provedor_primario)
    if provedor_obj is None:
        raise ErroConfiguracao(
            f"provedor '{provedor_primario}' da rota '{rota_nome}' não está registrado"
        )

    # Aceita tanto os dicts crus do projeto quanto mensagens já canônicas,
    # pra quem já normalizou (o adaptador em modelo.py) não pagar duas vezes.
    if mensagens and isinstance(mensagens[0], Mensagem):
        canonicas = list(mensagens)
    else:
        canonicas = normalizar_mensagens(mensagens)

    if not canonicas:
        raise ErroResposta(f"rota '{rota_nome}' recebeu lista de mensagens vazia")

    modelo_primario = modelo or cfg.modelo
    tokens_final = max_tokens if max_tokens is not None else cfg.max_tokens
    temp_final = temperatura if temperatura is not None else cfg.temperatura
    raciocinio_final = raciocinio if raciocinio is not None else cfg.raciocinio
    if raciocinio_final not in PARAMS_RACIOCINIO:
        raise ErroConfiguracao(
            f"raciocínio '{raciocinio_final}' não existe. "
            f"Use um destes: {', '.join(sorted(PARAMS_RACIOCINIO))}"
        )

    # CADEIA DE MODELOS, em pares (provedor, modelo): o primário da rota
    # primeiro, depois os fallbacks declarados nela. Cada degrau resolve o
    # PRÓPRIO provedor — é o que permite cair do claude pro Qwen, que vive
    # em outro endpoint. Um modelo que o endpoint não aceita mais não pode
    # deixar a Emily muda.
    cadeia_modelos: List[Tuple[str, str]] = [(provedor_primario, modelo_primario)]
    # Um provedor/modelo fixado por chamada representa uma escolha deliberada
    # do consumidor (voz rápida, agente isolado etc.). Não misture os fallbacks
    # da rota global, que podem pertencer a outro produto e outro comportamento.
    if provedor is None:
        for _prov_fb, _mod_fb in getattr(cfg, "fallbacks", ()):
            if (_prov_fb, _mod_fb) not in cadeia_modelos and _prov_fb in PROVEDORES:
                cadeia_modelos.append((_prov_fb, _mod_fb))

    ultimo_erro: Optional[Exception] = None
    comeco = time.monotonic()

    for _indice_modelo, (_provedor_id, modelo_final) in enumerate(cadeia_modelos):
        # O primário usa o orçamento de tentativas da rota; os fallbacks
        # ganham menos — já estamos em modo de degradação. Cada degrau tem
        # limitador próprio, porque provedor novo tem RPM próprio.
        tentativas_do_modelo = (cfg.tentativas if _indice_modelo == 0
                                else max(2, cfg.tentativas - 2))
        provedor_atual = PROVEDORES[_provedor_id]
        _cfg_prov_atual = PROVEDORES_CONFIG.get(_provedor_id)
        _rpm_atual = _cfg_prov_atual.rpm if _cfg_prov_atual else RPM_PADRAO
        limitador_atual = limitador_de(f"{_provedor_id}_{rota_nome}",
                                       _rpm_atual)
        if _indice_modelo:
            if time.monotonic() - comeco > ORCAMENTO_RETENTATIVA * 2:
                _log(f"rota '{rota_nome}': sem orçamento pra tentar o "
                     f"fallback {_provedor_id}:{modelo_final}; desistindo.")
                break
            _log(f"rota '{rota_nome}': caindo pro fallback "
                 f"{_provedor_id}:{modelo_final} ({_indice_modelo + 1}/"
                 f"{len(cadeia_modelos)})")

        for tentativa in range(tentativas_do_modelo):
            if tentativa and time.monotonic() - comeco > ORCAMENTO_RETENTATIVA:
                _log(
                    f"rota '{rota_nome}': já gastei "
                    f"{time.monotonic() - comeco:.0f}s tentando (teto de "
                    f"{ORCAMENTO_RETENTATIVA:.0f}s). Paro na tentativa "
                    f"{tentativa} de {tentativas_do_modelo} em vez de deixar "
                    f"quem pediu esperando mais."
                )
                break

            _inicio_fila = time.perf_counter()
            _fila_ok = limitador_atual.adquirir(timeout=60.0)
            _evento_execucao("model_queue", f"{_provedor_id}:{modelo_final}", _inicio_fila, ok=_fila_ok)
            if not _fila_ok:
                _log(f"rota '{rota_nome}': esperei 60s por espaço no rate limit e não conseguiu")
                raise ErroLimiteTaxa(f"rota '{rota_nome}' não conseguiu ficha do limitador")

            try:
                inicio = time.monotonic()
                resultado = provedor_atual.chamar(
                    mensagens=canonicas,
                    modelo=modelo_final,
                    max_tokens=tokens_final,
                    temperatura=temp_final,
                    raciocinio=raciocinio_final,
                    stream=stream,
                    ferramentas=ferramentas,
                    obrigar_ferramenta=obrigar_ferramenta,
                    proibir_ferramenta=proibir_ferramenta,
                )
                # Log SEMPRE (não só em debug) quando há ferramentas: é o caminho
                # onde a latência percebida mora — um turno com ferramenta são
                # várias chamadas em série e sem este log não dá pra saber quanto
                # cada uma comeu. Tokens de saída aproximam o tempo de geração.
                if ferramentas and not stream:
                    _log(
                        f"rota '{rota_nome}' ok em {time.monotonic() - inicio:.2f}s "
                        f"(msgs={len(canonicas)}, chars_prompt="
                        f"{sum(len(str(m.texto or m.bruta or '')) for m in canonicas)})"
                    )
                elif not stream:
                    _log_debug(
                        f"rota '{rota_nome}' modelo '{modelo_final}' "
                        f"ok em {time.monotonic() - inicio:.2f}s"
                    )
                if stream and isinstance(resultado, FluxoComFerramentas):
                    def _reabrir_stream():
                        novo = chamar(
                            mensagens, rota_nome=rota_nome, max_tokens=max_tokens,
                            stream=True, modelo=modelo, temperatura=temperatura,
                            ferramentas=ferramentas,
                            obrigar_ferramenta=obrigar_ferramenta,
                            proibir_ferramenta=proibir_ferramenta,
                            provedor=provedor, raciocinio=raciocinio,
                            on_retry=on_retry,
                        )
                        return novo._stream
                    resultado.configurar_reconexao(_reabrir_stream, on_retry)
                if tentativa and on_retry:
                    on_retry(0, tentativas_do_modelo)
                _evento_execucao("model_response", f"{_provedor_id}:{modelo_final}", inicio,
                                  attempt=tentativa, streaming=stream)
                if stream:
                    if isinstance(resultado, FluxoComFerramentas):
                        resultado._stream = _medir_stream(resultado._stream, inicio, modelo_final)
                    elif not isinstance(resultado, str):
                        resultado = _medir_stream(resultado, inicio, modelo_final)
                return resultado

            except ErroConfiguracao:
                # Chave errada ou faltando não melhora com retry.
                raise

            except (ErroLimiteTaxa, ErroTransporte) as e:
                ultimo_erro = e
                if tentativa >= tentativas_do_modelo - 1:
                    break
                espera = _espera_backoff(tentativa)
                _log(
                    f"rota '{rota_nome}' tentativa {tentativa + 1}/{tentativas_do_modelo} falhou "
                    f"({type(e).__name__}: {e}). Tentando de novo em {espera:.1f}s"
                )
                if on_retry:
                    on_retry(tentativa + 1, tentativas_do_modelo)
                _evento_execucao("model_retry",f"{_provedor_id}:{modelo_final}",inicio,
                                  ok=False,error=type(e).__name__,backoff_ms=espera*1000,attempt=tentativa+1)
                time.sleep(espera)

            except Exception as e:
                # Erro que o provedor não classificou. Loga com tipo e sobe.
                _log(f"rota '{rota_nome}' erro não classificado: {type(e).__name__}: {e}")
                raise ErroLLM(f"rota '{rota_nome}': {e}") from e

    gasto = time.monotonic() - comeco
    _log(f"rota '{rota_nome}' desistiu depois de {gasto:.0f}s. "
         f"Último erro: {ultimo_erro}")
    if ultimo_erro is not None:
        raise type(ultimo_erro)(
            f"rota '{rota_nome}' falhou depois de {gasto:.0f}s de tentativa: {ultimo_erro}"
        ) from ultimo_erro
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
    modelo: Optional[str] = None,
    provedor: Optional[str] = None,
    raciocinio: Optional[str] = None,
    temperatura: Optional[float] = None,
    on_retry: Optional[Callable[[int, int], None]] = None,
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
    provedor_id = (provedor or cfg.provedor).strip()
    provedor_obj = PROVEDORES.get(provedor_id)
    if provedor_obj is not None and not provedor_obj.suporta_ferramentas:
        raise ErroConfiguracao(
            f"o provedor '{provedor_id}' da rota '{rota_nome}' não suporta tool calling"
        )
    return chamar(
        mensagens,
        rota_nome=rota_nome,
        max_tokens=max_tokens,
        stream=stream,
        modelo=modelo,
        provedor=provedor,
        raciocinio=raciocinio,
        temperatura=temperatura,
        ferramentas=ferramentas,
        obrigar_ferramenta=obrigar_ferramenta,
        proibir_ferramenta=proibir_ferramenta,
        on_retry=on_retry,
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

    # 1. Credenciais presentes?
    #
    # getattr com default porque provedor não é obrigado a autenticar por uma
    # única variável de .env. Sem o default, o diagnóstico quebrava com
    # AttributeError logo no começo por causa de um provedor assim.
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
    # Rotas que recebem IMAGEM no diagnóstico. A detecção pelo nome do modelo
    # deixou de cobrir tudo quando as rotas de visão passaram a usar o modelo
    # multimodal principal (o Qwen antigo não enxergava; o Claude vê) — então
    # o nome da rota é o sinal confiável.
    _ROTAS_COM_IMAGEM = {
        "visao", "triagem_visual", "agente_ui", "agente_jogo",
        "visao_gmi", "triagem_visual_gmi", "agente_ui_gmi", "agente_jogo_gmi",
    }
    resultados = {}

    for nome, cfg in ROTAS.items():
        eh_visao = cfg.modelo in modelos_de_visao or nome in _ROTAS_COM_IMAGEM
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
