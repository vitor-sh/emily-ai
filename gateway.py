"""
gateway.py — ciclo de vida do kiro-gateway, o proxy local que dá à Emily
acesso aos modelos Claude do plano pago do Kiro.

Por que este arquivo existe
───────────────────────────
Desde a migração para o Kiro, o LLM da Emily não é mais um endpoint remoto:
é um processo que precisa estar rodando na máquina dela. Alguém tem que
subir esse processo, saber se ele está de pé, e derrubá-lo no fim.

Este é o único lugar do projeto que sabe disso. O llm.py chama garantir()
e não faz ideia de subprocesso; o modelo.py só sabe traduzir a falha em
frase falada.

O que ele NÃO faz
─────────────────
Não escolhe modelo, não monta requisição, não decide fallback. Isso é do
llm.py. A dependência é de mão única: llm.py importa gateway (de forma
lazy, dentro do método), e gateway não importa llm.py. Sem ciclo.

Contratos que este módulo garante
─────────────────────────────────
1. No máximo UM processo de gateway é subido por nós, por vida do processo
   da Emily, não importa quantas threads chamem garantir() ao mesmo tempo.
2. Se garantir() retorna sem exceção, o /health respondeu naquele instante.
3. Gateway que o Vitor subiu à mão nunca é recriado nem derrubado por nós.
4. O ambiente do subprocesso não carrega configuração da Emily que possa
   sobrescrever o .env do gateway (ver _ambiente_do_gateway).
5. Toda falha tem motivo declarado e frase pronta para o TTS.

Nota de implementação: o health check usa urllib da biblioteca padrão, não
httpx nem requests. É caminho quente (roda em toda chamada de LLM, mesmo
com o cache de TTL) e um GET em localhost não justifica dependência de
terceiro nem o custo de construir cliente.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping, Optional
from urllib.parse import urlparse

# ═════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ═════════════════════════════════════════════════════════════════

RAIZ = Path(__file__).resolve().parent

# Pasta do gateway. Em modo empacotado (PyInstaller) o código do gateway é
# incluído como dado, então fica ao lado do executável desempacotado.
PASTA = Path(os.getenv("EMILY_GATEWAY_PASTA") or (RAIZ / "kiro_gateway"))

URL_BASE = os.getenv("EMILY_KIRO_URL", "http://127.0.0.1:8000").rstrip("/")

# Health é local: 1,5s já é generoso. Paciência aqui só atrasa a descoberta
# de que o gateway caiu.
TIMEOUT_HEALTH = float(os.getenv("EMILY_GATEWAY_TIMEOUT_HEALTH", "1.5"))

# Subir uvicorn, carregar credencial e inicializar a conta leva alguns
# segundos na primeira vez.
TIMEOUT_BOOT = float(os.getenv("EMILY_GATEWAY_TIMEOUT_BOOT", "60"))

# Janela em que confiamos no último /health positivo sem bater de novo.
# É o que faz garantir() ser barato o suficiente para rodar em toda chamada.
TTL_HEALTH = float(os.getenv("EMILY_GATEWAY_TTL_HEALTH", "20"))

# Vitor pode preferir subir o gateway à mão.
AUTOSTART = os.getenv("EMILY_GATEWAY_AUTOSTART", "1").strip() == "1"

# Onde a saída do subprocesso é gravada. Sem isso, a causa de uma falha de
# boot morre com o processo e o Vitor fica só com "não subiu".
ARQUIVO_LOG = PASTA / "gateway.log"

# Windows: sem console piscando na cara do Vitor a cada boot da Emily.
_CREATE_NO_WINDOW = 0x08000000


def _log(mensagem: str) -> None:
    """Mesmo formato de prefixo que o resto do projeto usa."""
    print(f"[GATEWAY] {mensagem}")


# ═════════════════════════════════════════════════════════════════
# MOTIVOS E ERRO
#
# O motivo não é decoração: cada um tem uma frase própria que a Emily
# fala. "Deu erro" não ajuda o Vitor a resolver nada; "o login do Kiro
# expirou" resolve.
# ═════════════════════════════════════════════════════════════════

MOTIVO_PORTA_OCUPADA = "porta_ocupada"
MOTIVO_NAO_SUBIU = "nao_subiu"
MOTIVO_CREDENCIAL = "credencial"
MOTIVO_SEM_PYTHON = "sem_python"
MOTIVO_SEM_PASTA = "sem_pasta"

FRASES = {
    MOTIVO_CREDENCIAL: (
        "Vitor, o login do Kiro expirou. Abre o Kiro e faz login de novo "
        "que eu volto a funcionar."
    ),
    MOTIVO_PORTA_OCUPADA: (
        "Vitor, tem outra coisa usando a porta do meu gateway. Fecha ela ou "
        "muda a porta no env."
    ),
    MOTIVO_NAO_SUBIU: (
        "Vitor, meu gateway não subiu. Dá uma olhada no console que o erro tá lá."
    ),
    MOTIVO_SEM_PYTHON: (
        "Vitor, não achei um Python pra subir meu gateway. Configura o "
        "EMILY_GATEWAY_PYTHON."
    ),
    MOTIVO_SEM_PASTA: (
        "Vitor, a pasta do meu gateway não tá aqui. Sem ela eu não penso."
    ),
}

FRASE_GENERICA = "Vitor, deu problema pra subir meu gateway. Olha o console."


class ErroGateway(RuntimeError):
    """
    Falha no ciclo de vida do gateway.

    Carrega motivo (para decidir a frase) e detalhe (para o console). O
    llm.py traduz isso em ErroConfiguracao, que é a única classe que o
    retry da camada de LLM não repete — gateway fora do ar não melhora
    com backoff.
    """

    def __init__(self, motivo: str, detalhe: str = ""):
        self.motivo = motivo
        self.detalhe = detalhe or ""
        super().__init__(f"{motivo}: {self.detalhe}" if self.detalhe else motivo)

    def frase(self) -> str:
        """Frase pronta para o TTS: sem markdown, sem emoji, sempre não vazia."""
        return FRASES.get(self.motivo, FRASE_GENERICA)


# ═════════════════════════════════════════════════════════════════
# ESTADO INTERNO
#
# RLock e não Lock: garantir() pode ser reentrante por caminhos indiretos
# (uma exceção que dispare log que chame estado(), por exemplo), e um Lock
# simples travaria o processo inteiro nesse caso.
# ═════════════════════════════════════════════════════════════════

_lock = threading.RLock()
_processo: Optional[subprocess.Popen] = None
_dono = False            # nós subimos este gateway?
_ultimo_ok = 0.0         # time.monotonic() do último /health positivo
_atexit_registrado = False


# ═════════════════════════════════════════════════════════════════
# CHAVES RESERVADAS DO SUBPROCESSO
#
# Armadilha real, não hipótese: o load_dotenv() da Emily joga o .env dela
# em os.environ, o subprocesso herda o ambiente inteiro, e o load_dotenv()
# do gateway NÃO sobrescreve variável que já está no ambiente. Resultado:
# qualquer chave homônima no .env da Emily vence silenciosamente o
# kiro_gateway/.env — inclusive as quatro que a migração depende
# (SERVER_HOST, FAKE_REASONING, WEB_SEARCH_ENABLED, AUTO_TRIM_PAYLOAD).
#
# É por isso que a chave da Emily se chama KIRO_PROXY_API_KEY e não
# PROXY_API_KEY. Mas depender só da convenção de nome é frágil, então as
# chaves do gateway saem do ambiente do filho na força.
# ═════════════════════════════════════════════════════════════════

CHAVES_RESERVADAS = frozenset({
    "SERVER_HOST", "SERVER_PORT", "LOG_LEVEL", "PROXY_API_KEY",
    "REFRESH_TOKEN", "PROFILE_ARN",
    "FAKE_REASONING", "FAKE_REASONING_MAX_TOKENS", "FAKE_REASONING_BUDGET_CAP",
    "FAKE_REASONING_HANDLING", "FAKE_REASONING_INITIAL_BUFFER_SIZE",
    "WEB_SEARCH_ENABLED", "AUTO_TRIM_PAYLOAD", "KIRO_MAX_PAYLOAD_BYTES",
    "DEBUG_MODE", "DEBUG_DIR", "VPN_PROXY_URL",
    "STREAMING_READ_TIMEOUT", "FIRST_TOKEN_TIMEOUT", "FIRST_TOKEN_MAX_RETRIES",
    "TRUNCATION_RECOVERY", "SQLITE_READONLY", "STATE_SAVE_INTERVAL_SECONDS",
})

PREFIXOS_RESERVADOS = ("KIRO_", "ACCOUNT_")

# Chaves que NÓS impomos no filho, sobrescrevendo o que a Emily tiver.
#
# Diferente das reservadas (que são removidas para o .env do gateway poder
# valer), estas são ditadas por nós porque o subprocesso não funciona sem
# elas. Hoje é só codificação — ver o comentário em _ambiente_do_gateway.
AMBIENTE_IMPOSTO = {
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}


def _ambiente_do_gateway(base: Mapping[str, str]) -> dict:
    """
    Monta o ambiente do subprocesso removendo o que possa atropelar o
    .env do gateway.

    Pós-condições:
      - nenhuma chave reservada (lista fixa ou prefixo) está no resultado;
      - toda chave não reservada e não imposta de `base` está no resultado
        com o valor original;
      - toda chave de AMBIENTE_IMPOSTO está no resultado com o valor que
        nós ditamos, independentemente do que `base` trouxesse;
      - `base` não é modificado.

    As chaves EMILY_* ficam: o gateway não lê nada com esse prefixo.
    """
    limpo = {}
    for chave, valor in base.items():
        if chave in CHAVES_RESERVADAS:
            continue
        if chave.startswith(PREFIXOS_RESERVADOS):
            continue
        limpo[chave] = valor

    # UTF-8 na força, e isso NÃO é preciosismo: o banner de boot do gateway
    # imprime um emoji. Com a saída redirecionada para arquivo (que é o que
    # fazemos, para poder classificar a falha depois), o stdout do filho
    # deixa de ser terminal e o Python passa a usar a codificação local —
    # cp1252 numa máquina em português. O emoji então estoura
    # UnicodeEncodeError e o gateway MORRE no boot, antes de servir uma
    # única requisição.
    #
    # Descoberto rodando de verdade: o primeiro `python gateway.py` com a
    # porta livre falhou exatamente assim. Vale para a Emily empacotada
    # também, que roda sem console nenhum.
    limpo.update(AMBIENTE_IMPOSTO)

    return limpo


# ═════════════════════════════════════════════════════════════════
# SONDAGEM
# ═════════════════════════════════════════════════════════════════

def _host_e_porta() -> tuple[str, int]:
    partes = urlparse(URL_BASE)
    return (partes.hostname or "127.0.0.1", partes.port or 8000)


def esta_no_ar(timeout: float = TIMEOUT_HEALTH) -> bool:
    """
    O gateway responde /health?

    Nunca levanta exceção: erro de rede, timeout ou resposta estranha são
    todos "não está no ar". Quem chama decide o que fazer.
    """
    try:
        with urllib.request.urlopen(f"{URL_BASE}/health", timeout=timeout) as resposta:
            return resposta.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError):
        return False


def _porta_ocupada(host: str, porta: int, timeout: float = 0.6) -> bool:
    """
    Alguém aceita conexão nessa porta?

    Usado quando o /health falhou: se a porta ainda aceita conexão, quem
    está lá NÃO é o gateway (ou é um gateway quebrado), e subir outro só
    produziria "address already in use" — erro que não explica nada pro
    Vitor.
    """
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except OSError:
        return False


# ═════════════════════════════════════════════════════════════════
# INTERPRETADOR
# ═════════════════════════════════════════════════════════════════

def _interpretador() -> str:
    """
    Qual Python usar para subir o gateway.

    Ordem: variável explícita, executável atual (só se não estamos
    empacotados), depois PATH.

    O caso empacotado é o motivo desta função existir: com PyInstaller,
    sys.executable é o Emily.exe, e passar isso pro Popen faria a Emily
    tentar subir outra Emily.

    Levanta ErroGateway(MOTIVO_SEM_PYTHON) se nada resolver.
    """
    explicito = os.getenv("EMILY_GATEWAY_PYTHON", "").strip()
    if explicito:
        if Path(explicito).exists() or shutil.which(explicito):
            return explicito
        raise ErroGateway(
            MOTIVO_SEM_PYTHON,
            f"EMILY_GATEWAY_PYTHON aponta para algo que não existe: {explicito}",
        )

    empacotado = getattr(sys, "frozen", False)
    if not empacotado and sys.executable:
        return sys.executable

    for nome in ("python", "python3", "py"):
        caminho = shutil.which(nome)
        if caminho:
            return caminho

    raise ErroGateway(
        MOTIVO_SEM_PYTHON,
        "nenhum Python no PATH e EMILY_GATEWAY_PYTHON não está definida "
        f"(empacotado={empacotado})",
    )


# ═════════════════════════════════════════════════════════════════
# SUBIDA
# ═════════════════════════════════════════════════════════════════

def _ler_cauda_do_log(linhas: int = 40) -> str:
    """Últimas linhas do log do subprocesso, para explicar uma morte."""
    try:
        conteudo = ARQUIVO_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(sem log)"
    return "\n".join(conteudo.splitlines()[-linhas:]).strip() or "(log vazio)"


def _classificar_morte(processo: subprocess.Popen) -> ErroGateway:
    """
    O subprocesso morreu antes de responder. Por quê?

    Sempre devolve um ErroGateway — nunca None — com a cauda do log no
    detalhe, porque é lá que está a causa de verdade.
    """
    cauda = _ler_cauda_do_log()
    minuscula = cauda.lower()

    if ("failed to initialize any account" in minuscula
            or "invalid_grant" in minuscula
            or "no kiro credentials configured" in minuscula
            or "recusou a credencial" in minuscula):
        return ErroGateway(MOTIVO_CREDENCIAL, cauda)

    if "address already in use" in minuscula or "only one usage of each socket" in minuscula:
        return ErroGateway(MOTIVO_PORTA_OCUPADA, cauda)

    # Rede de segurança para a detecção de porta ocupada.
    #
    # O _porta_ocupada() é best-effort: um programa que ocupa a porta mas
    # não drena o backlog pode recusar a nossa sondagem e passar batido —
    # foi exatamente o que aconteceu num teste de sabotagem real. Quando
    # isso acontece, chegamos aqui sem nada conclusivo no log.
    #
    # Se a porta está ocupada AGORA, é muito mais provável que a causa da
    # morte seja isso do que um motivo genérico. A diferença importa porque
    # muda a frase que o Vitor ouve: "tem outra coisa usando a porta" é
    # acionável, "não subiu, olha o console" não é.
    host, porta = _host_e_porta()
    if _porta_ocupada(host, porta):
        return ErroGateway(
            MOTIVO_PORTA_OCUPADA,
            f"{host}:{porta} está ocupada e o gateway morreu ao subir "
            f"(código {processo.returncode}). Log:\n{cauda}",
        )

    return ErroGateway(
        MOTIVO_NAO_SUBIU,
        f"o processo saiu com código {processo.returncode}. Log:\n{cauda}",
    )


def _subir() -> subprocess.Popen:
    """
    Sobe o gateway como subprocesso.

    A saída vai para arquivo, não para PIPE: com PIPE, ninguém lê o buffer
    enquanto o polling de health roda, e um gateway falante trava quando o
    buffer do pipe enche. Arquivo não tem esse problema e sobrevive ao
    processo, o que é justamente o que _classificar_morte precisa.
    """
    executavel = _interpretador()
    ambiente = _ambiente_do_gateway(os.environ)

    try:
        log = ARQUIVO_LOG.open("w", encoding="utf-8")
    except OSError as e:
        raise ErroGateway(MOTIVO_NAO_SUBIU, f"não consegui abrir {ARQUIVO_LOG}: {e}") from e

    try:
        processo = subprocess.Popen(
            [executavel, "main.py"],
            cwd=str(PASTA),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=ambiente,
            creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError as e:
        log.close()
        raise ErroGateway(MOTIVO_NAO_SUBIU, f"Popen falhou: {e}") from e

    _log(f"subindo o gateway (pid {processo.pid}), log em {ARQUIVO_LOG.name}")
    return processo


def _matar(processo: subprocess.Popen, graca: float = 8.0) -> None:
    """Encerra pedindo, depois obrigando."""
    if processo.poll() is not None:
        return
    try:
        processo.terminate()
        processo.wait(timeout=graca)
    except subprocess.TimeoutExpired:
        processo.kill()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _log(f"o processo {processo.pid} não morreu nem com kill")
    except OSError:
        pass


def _registrar_atexit() -> None:
    global _atexit_registrado
    if not _atexit_registrado:
        atexit.register(derrubar)
        _atexit_registrado = True


# ═════════════════════════════════════════════════════════════════
# API PÚBLICA
# ═════════════════════════════════════════════════════════════════

def garantir() -> None:
    """
    Garante que o gateway está no ar, subindo se necessário.

    Idempotente e seguro sob concorrência: pode ser chamada de qualquer
    thread, em qualquer ordem, quantas vezes quiser. A Emily chama LLM do
    laço de voz, do laço de visão, do bot de Discord e da extração de
    memória em paralelo — sem serialização aqui, quatro threads subiriam
    quatro uvicorns na mesma porta.

    Pós-condições:
      - retornou sem exceção => /health estava positivo naquele instante;
      - no máximo um processo é subido por nós durante toda a vida do
        processo da Emily;
      - gateway que já estava no ar sem ser nosso não é recriado, e _dono
        permanece False;
      - em falha, levanta ErroGateway com motivo declarado e frase não
        vazia, deixando o estado interno consistente para uma nova
        tentativa.
    """
    global _processo, _dono, _ultimo_ok

    # Caminho rápido, sem lock: health recente já validado. É isso que
    # torna aceitável chamar garantir() em toda chamada de LLM.
    if time.monotonic() - _ultimo_ok < TTL_HEALTH:
        return

    with _lock:
        # Outra thread pode ter subido enquanto esperávamos o lock.
        if time.monotonic() - _ultimo_ok < TTL_HEALTH:
            return

        if esta_no_ar():
            _ultimo_ok = time.monotonic()
            return

        # Nosso processo morreu? Limpa a referência antes de decidir.
        if _processo is not None and _processo.poll() is not None:
            _log(f"o gateway que subimos morreu (código {_processo.returncode})")
            _processo = None
            _dono = False

        if not AUTOSTART:
            raise ErroGateway(
                MOTIVO_NAO_SUBIU,
                "auto-start desligado (EMILY_GATEWAY_AUTOSTART=0) e o gateway "
                "não está respondendo. Suba à mão: python main.py dentro de "
                f"{PASTA.name}",
            )

        if not PASTA.exists():
            raise ErroGateway(MOTIVO_SEM_PASTA, str(PASTA))

        # O /health não respondeu, mas a porta aceita conexão? Então quem
        # está lá não é o gateway. Subir outro daria "address in use", que
        # não explica nada.
        host, porta = _host_e_porta()
        if _porta_ocupada(host, porta):
            raise ErroGateway(
                MOTIVO_PORTA_OCUPADA,
                f"{host}:{porta} aceita conexão mas não responde /health — "
                "tem outro programa nessa porta",
            )

        processo = _subir()
        limite = time.monotonic() + TIMEOUT_BOOT

        while time.monotonic() < limite:
            if processo.poll() is not None:
                raise _classificar_morte(processo)
            if esta_no_ar():
                _processo = processo
                _dono = True
                _ultimo_ok = time.monotonic()
                _registrar_atexit()
                _log(f"gateway no ar em {URL_BASE}")
                return
            time.sleep(0.4)

        # Estourou o tempo com o processo vivo mas mudo.
        _matar(processo)
        raise ErroGateway(
            MOTIVO_NAO_SUBIU,
            f"subiu mas não respondeu /health em {TIMEOUT_BOOT:.0f}s. "
            f"Log:\n{_ler_cauda_do_log()}",
        )


def derrubar() -> None:
    """
    Encerra o gateway — mas só se fomos nós que subimos.

    Se o Vitor subiu o gateway à mão num terminal, fechar a Emily não pode
    matar o processo dele. Idempotente: pode ser chamada quantas vezes
    quiser, inclusive pelo atexit depois de uma chamada manual.
    """
    global _processo, _dono, _ultimo_ok

    with _lock:
        if not _dono or _processo is None:
            return
        pid = _processo.pid
        _matar(_processo)
        _log(f"gateway encerrado (pid {pid})")
        _processo = None
        _dono = False
        _ultimo_ok = 0.0


def estado() -> dict:
    """Retrato do ciclo de vida, para o diagnosticar() do llm.py."""
    with _lock:
        vivo = _processo is not None and _processo.poll() is None
        return {
            "url": URL_BASE,
            "no_ar": esta_no_ar(),
            "dono": _dono,
            "pid": _processo.pid if vivo and _processo else None,
            "autostart": AUTOSTART,
            "pasta": str(PASTA),
            "pasta_existe": PASTA.exists(),
            "log": str(ARQUIVO_LOG),
        }


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
#
# `python gateway.py` sobe, checa e derruba, sem precisar da Emily.
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    print("=" * 66)
    print("DIAGNÓSTICO DO CICLO DE VIDA DO GATEWAY")
    print("=" * 66)
    print()

    print(f"  url:          {URL_BASE}")
    print(f"  pasta:        {PASTA}")
    print(f"  pasta existe: {PASTA.exists()}")
    print(f"  autostart:    {AUTOSTART}")
    try:
        print(f"  interpretador: {_interpretador()}")
    except ErroGateway as e:
        print(f"  interpretador: FALHOU ({e.motivo})")
    print()

    ja_estava = esta_no_ar()
    print(f"  já estava no ar antes: {ja_estava}")
    print()

    inicio = time.monotonic()
    try:
        garantir()
    except ErroGateway as e:
        print(f"  garantir() FALHOU: {e.motivo}")
        print(f"  frase falada: {e.frase()}")
        print(f"  detalhe: {e.detalhe[:600]}")
        return 1
    decorrido = time.monotonic() - inicio

    print(f"  garantir() ok em {decorrido:.2f}s")
    for chave, valor in estado().items():
        print(f"    {chave:<14} {valor}")
    print()

    # Idempotência: a segunda chamada tem que ser instantânea (TTL) e não
    # subir nada.
    inicio = time.monotonic()
    garantir()
    print(f"  garantir() de novo: {time.monotonic() - inicio:.4f}s (cache de TTL)")
    print()

    if ja_estava:
        print("  o gateway já estava no ar: não somos donos, não vou derrubar.")
        print(f"  dono={estado()['dono']} (esperado: False)")
    else:
        derrubar()
        print(f"  derrubado. no_ar agora: {esta_no_ar()} (esperado: False)")
        derrubar()
        print("  derrubar() de novo não levantou exceção (idempotente)")

    print()
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnosticar())
