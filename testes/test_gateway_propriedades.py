"""
Testes de propriedade do gateway.py — Properties 1 a 4 do design.

Nenhum teste aqui toca a rede nem sobe processo de verdade: `esta_no_ar` e
`_subir` são dublados. O alvo é a LÓGICA do ciclo de vida, que é onde os
bugs de concorrência e de vazamento de ambiente moram. A validação contra
o gateway real é o `python gateway.py`.

Rodar:
    python -m pytest testes/test_gateway_propriedades.py -v
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gateway  # noqa: E402


# ═════════════════════════════════════════════════════════════════
# DUBLÊS
# ═════════════════════════════════════════════════════════════════

class ProcessoFalso:
    """
    Substituto de subprocess.Popen que não executa nada.

    `codigo_saida=None` significa "continua vivo", que é o caso do gateway
    saudável. Qualquer inteiro simula um processo que morreu.
    """

    def __init__(self, pid: int = 4242, codigo_saida=None):
        self.pid = pid
        self._codigo = codigo_saida
        self.returncode = codigo_saida
        self.terminate_chamado = 0
        self.kill_chamado = 0

    def poll(self):
        return self._codigo

    def terminate(self):
        self.terminate_chamado += 1
        self._codigo = -15
        self.returncode = -15

    def kill(self):
        self.kill_chamado += 1
        self._codigo = -9
        self.returncode = -9

    def wait(self, timeout=None):
        if self._codigo is None:
            self._codigo = 0
            self.returncode = 0
        return self._codigo


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    """
    Zera o estado de módulo antes e depois de cada teste.

    gateway.py guarda estado global de propósito (é um processo por Emily),
    então sem esta limpeza um teste contamina o seguinte.
    """
    monkeypatch.setattr(gateway, "_processo", None, raising=False)
    monkeypatch.setattr(gateway, "_dono", False, raising=False)
    monkeypatch.setattr(gateway, "_ultimo_ok", 0.0, raising=False)
    monkeypatch.setattr(gateway, "_atexit_registrado", True, raising=False)  # não registra atexit
    monkeypatch.setattr(gateway, "AUTOSTART", True, raising=False)
    # Porta livre e pasta presente: o alvo aqui não é essa validação.
    monkeypatch.setattr(gateway, "_porta_ocupada", lambda *a, **k: False)
    yield
    gateway._processo = None
    gateway._dono = False
    gateway._ultimo_ok = 0.0


# ═════════════════════════════════════════════════════════════════
# Property 1: Um gateway, não vários
#
# "Para qualquer número de chamadas a garantir(), feitas em qualquer ordem
# e de qualquer quantidade de threads simultâneas, o módulo inicia no
# máximo um processo de gateway."
#
# Validates: Requirements 3.1, 3.2, 3.6
# ═════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("n_threads", [1, 2, 4, 8, 16])
def test_property1_uma_subida_sob_concorrencia(monkeypatch, n_threads):
    subidas = []
    barreira = threading.Barrier(n_threads)

    def subir_falso():
        subidas.append(1)
        return ProcessoFalso()

    # Está no ar somente DEPOIS de alguém ter subido. É o cenário que
    # provoca a corrida: todas as threads veem "fora do ar" ao entrar.
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: bool(subidas))
    monkeypatch.setattr(gateway, "_subir", subir_falso)

    erros = []

    def trabalho():
        try:
            barreira.wait(timeout=5)
            gateway.garantir()
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=trabalho) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not erros, f"garantir() levantou exceção: {erros}"
    assert len(subidas) == 1, f"{n_threads} threads subiram {len(subidas)} gateways"


def test_property1_chamadas_repetidas_nao_multiplicam(monkeypatch):
    subidas = []
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: bool(subidas))
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    for _ in range(25):
        gateway.garantir()

    assert len(subidas) == 1


def test_property1_falha_nao_deixa_orfao(monkeypatch):
    """
    Requisito 3.6: falha seguida de nova tentativa não deixa processo órfão
    e o estado interno continua consistente.
    """
    processos = []

    def subir_que_morre():
        p = ProcessoFalso(codigo_saida=1)
        processos.append(p)
        return p

    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: False)
    monkeypatch.setattr(gateway, "_subir", subir_que_morre)
    monkeypatch.setattr(gateway, "_ler_cauda_do_log", lambda linhas=40: "boom")

    for _ in range(3):
        with pytest.raises(gateway.ErroGateway):
            gateway.garantir()

    # Nenhum processo morto ficou registrado como o gateway ativo.
    assert gateway._processo is None
    assert gateway._dono is False


# ═════════════════════════════════════════════════════════════════
# Property 2: Retorno de garantir implica gateway no ar
#
# "Toda chamada que retorna sem exceção implica que a checagem de saúde
# estava positiva no instante do retorno; toda chamada que falha levanta
# ErroGateway com motivo declarado e frase falada não vazia."
#
# Validates: Requirements 3.3, 3.7, 4.4
# ═════════════════════════════════════════════════════════════════

def test_property2_retorno_implica_no_ar(monkeypatch):
    subidas = []
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: bool(subidas))
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    gateway.garantir()
    assert gateway.esta_no_ar() is True


def test_property2_nunca_no_ar_levanta_com_motivo(monkeypatch):
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: False)
    monkeypatch.setattr(gateway, "_subir", lambda: ProcessoFalso())
    monkeypatch.setattr(gateway, "TIMEOUT_BOOT", 1.0)
    monkeypatch.setattr(gateway, "_ler_cauda_do_log", lambda linhas=40: "mudo")

    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway.garantir()

    erro = capturado.value
    assert erro.motivo == gateway.MOTIVO_NAO_SUBIU
    assert erro.frase()


MOTIVOS_DECLARADOS = [
    gateway.MOTIVO_PORTA_OCUPADA,
    gateway.MOTIVO_NAO_SUBIU,
    gateway.MOTIVO_CREDENCIAL,
    gateway.MOTIVO_SEM_PYTHON,
    gateway.MOTIVO_SEM_PASTA,
]


@pytest.mark.parametrize("motivo", MOTIVOS_DECLARADOS)
def test_property2_todo_motivo_tem_frase_falavel(motivo):
    """
    Requisito 4.4: frase não vazia, sem markdown e sem emoji — vai direto
    pro TTS, e o Vitor OUVE isso.
    """
    frase = gateway.ErroGateway(motivo, "detalhe").frase()

    assert frase.strip(), f"motivo '{motivo}' não tem frase"
    for proibido in ("**", "##", "- ", "* ", "`"):
        assert proibido not in frase, f"frase do motivo '{motivo}' tem markdown: {proibido!r}"
    assert all(ord(c) < 0x2500 for c in frase), f"frase do motivo '{motivo}' tem emoji"
    assert "Vitor" in frase, "a Emily fala com o Vitor, não com 'o usuário'"


@given(motivo=st.text(min_size=1, max_size=40), detalhe=st.text(max_size=200))
def test_property2_frase_nunca_vazia_nem_para_motivo_desconhecido(motivo, detalhe):
    """Motivo fora da tabela cai na frase genérica, nunca em string vazia."""
    assert gateway.ErroGateway(motivo, detalhe).frase().strip()


def test_property2_classificar_morte_sempre_devolve_erro(monkeypatch):
    monkeypatch.setattr(gateway, "_ler_cauda_do_log", lambda linhas=40: "qualquer coisa")
    erro = gateway._classificar_morte(ProcessoFalso(codigo_saida=3))
    assert isinstance(erro, gateway.ErroGateway)
    assert erro.frase()


@pytest.mark.parametrize("cauda,esperado", [
    ("Failed to initialize any account", gateway.MOTIVO_CREDENCIAL),
    ("erro: invalid_grant no refresh", gateway.MOTIVO_CREDENCIAL),
    ("No Kiro credentials configured!", gateway.MOTIVO_CREDENCIAL),
    ("OSError: [Errno 48] Address already in use", gateway.MOTIVO_PORTA_OCUPADA),
    ("Only one usage of each socket address is normally permitted",
     gateway.MOTIVO_PORTA_OCUPADA),
    ("ImportError: No module named fastapi", gateway.MOTIVO_NAO_SUBIU),
])
def test_property2_classificacao_por_cauda_de_log(monkeypatch, cauda, esperado):
    monkeypatch.setattr(gateway, "_ler_cauda_do_log", lambda linhas=40: cauda)
    assert gateway._classificar_morte(ProcessoFalso(codigo_saida=1)).motivo == esperado


# ═════════════════════════════════════════════════════════════════
# Property 3: Gateway alheio sobrevive
#
# "Para qualquer estado inicial em que o gateway já estava no ar sem ter
# sido iniciado pelo módulo, garantir() não cria processo e derrubar() não
# envia sinal a processo algum."
#
# Validates: Requirements 3.4, 3.5
# ═════════════════════════════════════════════════════════════════

def test_property3_nao_sobe_se_ja_esta_no_ar(monkeypatch):
    subidas = []
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: True)
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    for _ in range(5):
        gateway.garantir()

    assert subidas == []
    assert gateway._dono is False, "não subimos, então não somos donos"


def test_property3_derrubar_nao_toca_processo_alheio(monkeypatch):
    """
    O Vitor subiu o gateway num terminal. Fechar a Emily não pode matar o
    processo dele.
    """
    alheio = ProcessoFalso(pid=999)
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: True)
    monkeypatch.setattr(gateway, "_processo", alheio, raising=False)
    monkeypatch.setattr(gateway, "_dono", False, raising=False)

    gateway.derrubar()

    assert alheio.terminate_chamado == 0
    assert alheio.kill_chamado == 0
    assert alheio.poll() is None, "o processo alheio continua vivo"


def test_property3_derrubar_encerra_o_nosso_e_e_idempotente(monkeypatch):
    subidas = []

    def subir_falso():
        p = ProcessoFalso(pid=555)
        subidas.append(p)
        return p

    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: bool(subidas))
    monkeypatch.setattr(gateway, "_subir", subir_falso)

    gateway.garantir()
    assert gateway._dono is True
    nosso = subidas[0]

    gateway.derrubar()
    assert nosso.terminate_chamado == 1
    assert nosso.poll() is not None

    # Idempotência: nada explode, nada é sinalizado de novo.
    gateway.derrubar()
    gateway.derrubar()
    assert nosso.terminate_chamado == 1


# ═════════════════════════════════════════════════════════════════
# Property 4: Ambiente do subprocesso não vaza configuração
#
# "Para qualquer mapa de ambiente de entrada, o ambiente montado para o
# subprocesso não contém nenhuma chave reservada do gateway (lista fixa
# mais os prefixos KIRO_ e ACCOUNT_), preserva o valor de todas as chaves
# não reservadas e não modifica o mapa de entrada."
#
# Validates: Requirements 3.8
#
# Esta é a propriedade que protege a migração de um bug silencioso: o
# load_dotenv() do gateway NÃO sobrescreve variável já presente no
# ambiente, então uma chave homônima vinda da Emily venceria o
# kiro_gateway/.env sem avisar ninguém.
# ═════════════════════════════════════════════════════════════════

_chaves_env = st.text(
    alphabet=st.characters(min_codepoint=65, max_codepoint=90, whitelist_characters="_0123456789"),
    min_size=1, max_size=24,
)
_valores_env = st.text(max_size=60)


@settings(max_examples=200)
@given(base=st.dictionaries(_chaves_env, _valores_env, max_size=40))
def test_property4_nenhuma_chave_reservada_sobrevive(base):
    resultado = gateway._ambiente_do_gateway(base)

    for chave in resultado:
        assert chave not in gateway.CHAVES_RESERVADAS
        assert not chave.startswith(gateway.PREFIXOS_RESERVADOS)


@settings(max_examples=200)
@given(base=st.dictionaries(_chaves_env, _valores_env, max_size=40))
def test_property4_preserva_o_que_nao_e_reservado(base):
    resultado = gateway._ambiente_do_gateway(base)

    for chave, valor in base.items():
        reservada = (chave in gateway.CHAVES_RESERVADAS
                     or chave.startswith(gateway.PREFIXOS_RESERVADOS))
        # Chave imposta é ditada por nós de propósito; preservar o valor
        # herdado ali seria o bug, não a garantia. Foi o hypothesis que
        # apontou essa contradição na primeira versão da propriedade.
        imposta = chave in gateway.AMBIENTE_IMPOSTO
        if not reservada and not imposta:
            assert resultado[chave] == valor


@settings(max_examples=100)
@given(base=st.dictionaries(_chaves_env, _valores_env, max_size=40))
def test_property4_nao_modifica_a_entrada(base):
    copia = dict(base)
    gateway._ambiente_do_gateway(base)
    assert base == copia


@settings(max_examples=100)
@given(base=st.dictionaries(_chaves_env, _valores_env, max_size=40))
def test_property4_forca_utf8_no_subprocesso(base):
    """
    Regressão de um bug encontrado rodando de verdade.

    O banner de boot do gateway imprime um emoji. Com a saída redirecionada
    para arquivo, o stdout do filho não é terminal e o Python usa a
    codificação local (cp1252 em máquina PT-BR), o que estoura
    UnicodeEncodeError e MATA o gateway no boot.

    O ambiente do subprocesso tem que forçar UTF-8, sempre, mesmo que a
    Emily tenha herdado outra coisa.
    """
    resultado = gateway._ambiente_do_gateway(base)
    assert resultado["PYTHONIOENCODING"] == "utf-8"
    assert resultado["PYTHONUTF8"] == "1"


def test_property4_utf8_vence_valor_herdado():
    base = {"PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}
    resultado = gateway._ambiente_do_gateway(base)
    assert resultado["PYTHONIOENCODING"] == "utf-8"
    assert resultado["PYTHONUTF8"] == "1"


def test_property4_as_quatro_chaves_criticas_da_migracao():
    """
    Teste concreto do caso que motivou a propriedade: se estas quatro
    vazarem da Emily para o subprocesso, o .env do gateway perde e a
    migração quebra de formas difíceis de diagnosticar.
    """
    base = {
        "SERVER_HOST": "0.0.0.0",
        "FAKE_REASONING": "true",
        "WEB_SEARCH_ENABLED": "true",
        "AUTO_TRIM_PAYLOAD": "false",
        "PROXY_API_KEY": "senha-errada",
        "KIRO_PROXY_API_KEY": "senha-da-emily",
        "KIRO_CREDS_FILE": "caminho/errado",
        "ACCOUNT_SYSTEM": "true",
        "EMILY_KIRO_URL": "http://127.0.0.1:8000",
        "PATH": "/usr/bin",
    }
    resultado = gateway._ambiente_do_gateway(base)

    for vazaria in ("SERVER_HOST", "FAKE_REASONING", "WEB_SEARCH_ENABLED",
                    "AUTO_TRIM_PAYLOAD", "PROXY_API_KEY", "KIRO_PROXY_API_KEY",
                    "KIRO_CREDS_FILE", "ACCOUNT_SYSTEM"):
        assert vazaria not in resultado, f"{vazaria} vazou para o subprocesso"

    # EMILY_* fica: o gateway não lê nada com esse prefixo. PATH também,
    # senão o subprocesso não acha o Python.
    assert resultado["EMILY_KIRO_URL"] == "http://127.0.0.1:8000"
    assert resultado["PATH"] == "/usr/bin"


# ═════════════════════════════════════════════════════════════════
# Interpretador (Requisito 10.2)
# ═════════════════════════════════════════════════════════════════

def test_interpretador_respeita_variavel_explicita(monkeypatch):
    monkeypatch.setenv("EMILY_GATEWAY_PYTHON", sys.executable)
    assert gateway._interpretador() == sys.executable


def test_interpretador_recusa_caminho_inexistente(monkeypatch):
    monkeypatch.setenv("EMILY_GATEWAY_PYTHON", "Z:/nao/existe/python.exe")
    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway._interpretador()
    assert capturado.value.motivo == gateway.MOTIVO_SEM_PYTHON
    assert capturado.value.frase()


def test_interpretador_usa_executavel_atual_quando_nao_empacotado(monkeypatch):
    monkeypatch.delenv("EMILY_GATEWAY_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert gateway._interpretador() == sys.executable


def test_interpretador_ignora_executavel_quando_empacotado(monkeypatch):
    """
    Com PyInstaller, sys.executable é o Emily.exe. Usar isso faria a Emily
    tentar subir outra Emily como se fosse o gateway.
    """
    monkeypatch.delenv("EMILY_GATEWAY_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:/qualquer/Emily.exe", raising=False)
    monkeypatch.setattr(gateway.shutil, "which",
                        lambda nome: "C:/Python311/python.exe" if nome == "python" else None)
    assert gateway._interpretador() == "C:/Python311/python.exe"


def test_interpretador_sem_nada_disponivel(monkeypatch):
    monkeypatch.delenv("EMILY_GATEWAY_PYTHON", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(gateway.shutil, "which", lambda nome: None)
    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway._interpretador()
    assert capturado.value.motivo == gateway.MOTIVO_SEM_PYTHON


# ═════════════════════════════════════════════════════════════════
# Casos de borda do garantir()
# ═════════════════════════════════════════════════════════════════

def test_autostart_desligado_nao_sobe_e_explica(monkeypatch):
    subidas = []
    monkeypatch.setattr(gateway, "AUTOSTART", False, raising=False)
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: False)
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway.garantir()

    assert subidas == []
    assert capturado.value.motivo == gateway.MOTIVO_NAO_SUBIU
    assert "auto-start" in capturado.value.detalhe.lower()


def test_porta_ocupada_por_outro_programa(monkeypatch):
    """
    /health não responde mas a porta aceita conexão: quem está lá não é o
    gateway. Subir outro daria "address in use", que não explica nada.
    """
    subidas = []
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: False)
    monkeypatch.setattr(gateway, "_porta_ocupada", lambda *a, **k: True)
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway.garantir()

    assert subidas == []
    assert capturado.value.motivo == gateway.MOTIVO_PORTA_OCUPADA


def test_pasta_ausente(monkeypatch, tmp_path):
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: False)
    monkeypatch.setattr(gateway, "PASTA", tmp_path / "nao_existe", raising=False)

    with pytest.raises(gateway.ErroGateway) as capturado:
        gateway.garantir()

    assert capturado.value.motivo == gateway.MOTIVO_SEM_PASTA


def test_gateway_que_subimos_morreu_e_religa(monkeypatch):
    """
    Cenário real: o gateway cai no meio da tarde. A próxima chamada de LLM
    tem que religar, não emudecer a Emily até reiniciar.
    """
    estado = {"vivo": False}
    subidas = []

    def subir_falso():
        subidas.append(1)
        estado["vivo"] = True
        return ProcessoFalso()

    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: estado["vivo"])
    monkeypatch.setattr(gateway, "_subir", subir_falso)

    gateway.garantir()
    assert len(subidas) == 1

    # O gateway morre e o TTL expira.
    estado["vivo"] = False
    gateway._processo = ProcessoFalso(codigo_saida=1)
    gateway._ultimo_ok = 0.0

    gateway.garantir()
    assert len(subidas) == 2, "não religou o gateway morto"
    assert gateway._dono is True


def test_ttl_evita_ida_na_rede(monkeypatch):
    """
    Requisito 3.10: dentro da janela de confiança, garantir() não faz
    requisição. É o que permite chamá-la em toda chamada de LLM.
    """
    chamadas = []
    subidas = []

    def health_falso(*a, **k):
        chamadas.append(1)
        return bool(subidas)

    monkeypatch.setattr(gateway, "esta_no_ar", health_falso)
    monkeypatch.setattr(gateway, "_subir", lambda: (subidas.append(1), ProcessoFalso())[1])

    gateway.garantir()
    antes = len(chamadas)

    for _ in range(50):
        gateway.garantir()

    assert len(chamadas) == antes, "o cache de TTL não está segurando as checagens"


def test_estado_reporta_o_essencial(monkeypatch):
    monkeypatch.setattr(gateway, "esta_no_ar", lambda *a, **k: True)
    info = gateway.estado()
    for chave in ("url", "no_ar", "dono", "pid", "autostart", "pasta", "pasta_existe", "log"):
        assert chave in info
