"""Regressões do caminho Luna -> delegação Terra exclusivo da voz no PC."""

from __future__ import annotations

import ast
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

@pytest.fixture(autouse=True)
def politica_sem_rede(monkeypatch):
    import politica_agente
    monkeypatch.setattr(politica_agente, "autorizador", lambda *a: lambda *b: True)
    monkeypatch.setattr(politica_agente, "revisar_resposta", lambda p,t,m,r: {"continuar": False, "texto": t})

import ferramentas
import llm
import orquestrador_voz as ov


RAIZ = Path(__file__).resolve().parent.parent


def _esperar(condicao, timeout=1.5):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return bool(condicao())


def _funcao(arquivo: str, nome: str) -> ast.FunctionDef:
    arvore = ast.parse((RAIZ / arquivo).read_text(encoding="utf-8"))
    return next(
        no for no in arvore.body
        if isinstance(no, ast.FunctionDef) and no.name == nome
    )


def test_catalogo_rapido_tem_player_playlist_visao_e_delegacao_apenas():
    catalogo = ov.catalogo_rapido()
    nomes = [item["function"]["name"] for item in catalogo]

    assert "player_tocar" in nomes
    assert "player_minhas_playlists" in nomes
    assert "playlist_adicionar" in nomes
    assert "ver_tela" in nomes
    assert "delegar_tarefa" in nomes
    assert len(nomes) == len(set(nomes))
    assert "pesquisar_internet" in nomes
    assert "executar_terminal" in nomes
    assert "abrir_ferramentas" in nomes
    assert ferramentas.CATALOGO["ver_tela"].somente_leitura is True


def test_luna_executa_ver_tela_diretamente_sem_delegar(monkeypatch):
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    chamadas = []

    class DelegacaoFalsa:
        def iniciar(self, *_args, **_kwargs):
            raise AssertionError("ver_tela não deve delegar para o modelo forte")

    orquestrador.delegacao = DelegacaoFalsa()
    monkeypatch.setattr(
        ferramentas,
        "executar_estruturado",
        lambda nome, args, contexto=None: (
            chamadas.append((nome, args, contexto))
            or ferramentas.ResultadoFerramenta(
                texto="Há um erro de sintaxe na linha 12.", ok=True, mudou=False)
        ),
    )

    resultado = orquestrador._executar_chamada_luna(llm.ChamadaFerramenta(
        id="v1", nome="ver_tela", argumentos='{"pergunta":"qual é o erro?"}'))

    assert resultado.ok is True
    assert resultado.texto == "Há um erro de sintaxe na linha 12."
    assert chamadas == [(
        "ver_tela",
        {"pergunta": "qual é o erro?"},
        {"pedido_explicito": True, "dono_confirmado": True},
    )]


def test_delegacao_inicia_sem_bloquear_e_recusa_segunda():
    liberar = threading.Event()

    def executor(_descricao, _contexto, progresso):
        progresso("trabalhando")
        liberar.wait(1)
        return "resultado pronto"

    gerenciador = ov.GerenciadorDelegacao(executor)
    inicio = time.monotonic()
    ok, _ = gerenciador.iniciar("tarefa longa")
    duracao = time.monotonic() - inicio

    assert ok is True
    assert duracao < 0.2
    assert gerenciador.snapshot().status == "running"

    ok2, texto2 = gerenciador.iniciar("outra tarefa")
    assert ok2 is False
    assert "pendente" in texto2.lower()

    liberar.set()
    assert _esperar(lambda: gerenciador.snapshot().status == "completed")
    assert gerenciador.snapshot().resultado == "resultado pronto"


def test_delegacao_falha_vira_estado_entregavel():
    def executor(_descricao, _contexto, _progresso):
        raise ValueError("quebrou de propósito")

    gerenciador = ov.GerenciadorDelegacao(executor)
    assert gerenciador.iniciar("falhar")[0]
    assert _esperar(lambda: gerenciador.snapshot().status == "failed")

    estado = gerenciador.snapshot()
    assert estado.entregue is False
    assert "ValueError" in estado.erro
    assert "quebrou de propósito" in estado.erro


def test_resultado_so_e_entregue_uma_vez_e_libera_proxima_tarefa():
    gerenciador = ov.GerenciadorDelegacao(
        lambda _d, _c, _p: "feito")
    assert gerenciador.iniciar("primeira")[0]
    assert _esperar(lambda: gerenciador.snapshot().status == "completed")

    reservado = gerenciador.reservar_aviso()
    assert reservado is not None
    assert reservado.status == "completed"
    assert gerenciador.reservar_aviso() is None

    gerenciador.concluir_aviso(reservado.id, entregue=True, sucesso=True)
    assert gerenciador.snapshot().entregue is True
    assert gerenciador.reservar_aviso() is None
    assert gerenciador.iniciar("segunda")[0]


def test_interacao_cancela_aviso_reservado():
    gerenciador = ov.GerenciadorDelegacao(
        lambda _d, _c, _p: "feito")
    assert gerenciador.iniciar("tarefa")[0]
    assert _esperar(lambda: gerenciador.snapshot().status == "completed")

    reservado = gerenciador.reservar_aviso()
    assert reservado is not None
    assert gerenciador.aviso_reservado(reservado.id)

    gerenciador.cancelar_reserva_para_interacao()
    assert not gerenciador.aviso_reservado(reservado.id)
    assert gerenciador.snapshot().entregue is False


def test_contexto_estruturado_expoe_progresso_resultado_e_erro():
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    agora = time.time()

    running = ov.EstadoDelegacao(
        id=1, status="running", descricao="pesquisar", etapa="usando busca",
        criada_em=agora - 7, entregue=False)
    texto_running = orquestrador._contexto_delegacao(running)
    assert '"status": "running"' in texto_running
    assert '"etapa": "usando busca"' in texto_running

    completed = ov.EstadoDelegacao(
        id=2, status="completed", descricao="pesquisar", etapa="concluído",
        criada_em=agora - 10, resultado="achei a resposta", entregue=False)
    texto_completed = orquestrador._contexto_delegacao(completed)
    assert '"resultado": "achei a resposta"' in texto_completed

    failed = ov.EstadoDelegacao(
        id=3, status="failed", descricao="pesquisar", etapa="falhou",
        criada_em=agora - 10, erro="rede indisponível", entregue=False)
    texto_failed = orquestrador._contexto_delegacao(failed)
    assert '"erro": "rede indisponível"' in texto_failed


def test_llm_override_por_chamada_nao_muta_rota_global(monkeypatch):
    original_modelo = llm.rota("conversa").modelo
    capturado = {}

    class ProvedorFalso:
        suporta_ferramentas = True

        def chamar(self, **kwargs):
            capturado.update(kwargs)
            return "ok"

    monkeypatch.setitem(llm.PROVEDORES, "voz_teste", ProvedorFalso())
    monkeypatch.setattr(llm, "limitador_de", lambda *_args: SimpleNamespace(
        adquirir=lambda timeout=0: True))

    resposta = llm.chamar(
        [{"role": "user", "content": "oi"}],
        rota_nome="conversa",
        provedor="voz_teste",
        modelo="luna-teste",
        raciocinio=llm.RACIOCINIO_DESLIGADO,
        max_tokens=12,
    )

    assert resposta == "ok"
    assert capturado["modelo"] == "luna-teste"
    assert capturado["raciocinio"] == llm.RACIOCINIO_DESLIGADO
    assert llm.rota("conversa").modelo == original_modelo


def test_luna_usa_modelo_rapido_e_delega_sem_executar_catalogo_pesado(monkeypatch):
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    orquestrador.modelo_luna = "luna-teste"
    orquestrador.modelo_forte = "terra-teste"
    orquestrador.provedor_luna = "provedor-teste"
    orquestrador.provedor_forte = "provedor-teste"
    orquestrador._catalogo_rapido = ov.catalogo_rapido()
    orquestrador._historico = []
    orquestrador._historico_lock = threading.RLock()
    orquestrador._monitor_parar = threading.Event()
    orquestrador._monitor_thread = None

    delegacoes = []

    class DelegacaoFalsa:
        def snapshot(self):
            return ov.EstadoDelegacao()

        def cancelar_reserva_para_interacao(self):
            pass

        def iniciar(self, objetivo, contexto=""):
            delegacoes.append((objetivo, contexto))
            return True, "iniciada"

        def marcar_entregue_se_final(self, _tarefa_id):
            pass

    orquestrador.delegacao = DelegacaoFalsa()

    chamadas = []

    class FluxoFalso:
        preambulo = ""

        def definir_limite_decisao_texto(self, _limite):
            pass

        def quer_ferramenta(self):
            return True

        @property
        def chamadas(self):
            return [llm.ChamadaFerramenta(
                id="d1", nome="delegar_tarefa",
                argumentos='{"objetivo":"pesquisar preços"}')]

        def texto(self):
            return iter(())

    respostas = iter([
        FluxoFalso(),
        llm.FluxoComFerramentas(iter(())),
    ])

    def chamar_falso(*_args, **kwargs):
        chamadas.append(kwargs)
        if len(chamadas) == 1:
            return next(respostas)

        class TextoFalso:
            def definir_limite_decisao_texto(self, _limite):
                pass

            def quer_ferramenta(self):
                return False

            @property
            def chamadas(self):
                return []

            def texto(self):
                return iter(["Beleza, deixei isso rodando."])

        return TextoFalso()

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar_falso)
    monkeypatch.setattr(modelo := __import__("modelo"),
                        "_registrar_memoria_unificada", lambda *_a, **_k: None)

    resposta = orquestrador.responder("pesquisa isso")

    assert resposta == "Beleza, deixei isso rodando."
    assert delegacoes and delegacoes[0][0] == "pesquisar preços"
    assert chamadas[0]["modelo"] == "luna-teste"
    nomes = {
        item["function"]["name"]
        for item in chamadas[0]["ferramentas"]
    }
    assert "delegar_tarefa" in nomes
    assert "pesquisar_internet" in nomes


def test_caminho_simples_do_luna_responde_sem_delegar(monkeypatch):
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    orquestrador.modelo_luna = "luna-teste"
    orquestrador.provedor_luna = "provedor-teste"
    orquestrador._catalogo_rapido = ov.catalogo_rapido()
    orquestrador._historico = []
    orquestrador._historico_lock = threading.RLock()

    class DelegacaoFalsa:
        iniciada = False

        def snapshot(self):
            return ov.EstadoDelegacao()

        def cancelar_reserva_para_interacao(self):
            pass

        def iniciar(self, *_args, **_kwargs):
            self.iniciada = True
            return True, "iniciada"

        def marcar_entregue_se_final(self, _id):
            pass

    orquestrador.delegacao = DelegacaoFalsa()

    class TextoFalso:
        preambulo = ""

        def definir_limite_decisao_texto(self, _limite):
            pass

        def quer_ferramenta(self):
            return False

        @property
        def chamadas(self):
            return []

        def texto(self):
            return iter(["Tô bem, e você?"])

    monkeypatch.setattr(llm, "chamar_com_ferramentas",
                        lambda *_a, **_k: TextoFalso())
    monkeypatch.setattr(__import__("modelo"), "_registrar_memoria_unificada",
                        lambda *_a, **_k: None)
    fila = queue.Queue()

    resposta = orquestrador.responder("como você tá?", fila_frases=fila)

    assert resposta == "Tô bem, e você?"
    assert orquestrador.delegacao.iniciada is False
    assert fila.get_nowait() == "Tô bem, e você?"
    assert fila.get_nowait() is None


def test_monitor_entrega_conclusao_uma_unica_vez(monkeypatch):
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    orquestrador._monitor_parar = threading.Event()
    orquestrador._monitor_thread = None
    orquestrador.delegacao = ov.GerenciadorDelegacao(
        lambda _d, _c, _p: "resultado final")
    assert orquestrador.delegacao.iniciar("tarefa")[0]
    assert _esperar(lambda: orquestrador.delegacao.snapshot().status == "completed")

    monkeypatch.setattr(orquestrador, "_gerar_aviso_natural",
                        lambda _estado: "Terminei e achei isso.")
    falas = []
    orquestrador.iniciar_monitor(
        pode_falar=lambda: True,
        falar=lambda texto, final: falas.append((texto, final)) or True,
    )

    assert _esperar(lambda: len(falas) == 1)
    time.sleep(0.6)
    orquestrador.parar_monitor()

    assert falas == [("Terminei e achei isso.", True)]
    assert orquestrador.delegacao.snapshot().entregue is True


def test_executor_forte_usa_terra_e_catalogo_completo(monkeypatch):
    orquestrador = ov.OrquestradorVoz.__new__(ov.OrquestradorVoz)
    orquestrador.modelo_forte = "terra-teste"
    orquestrador.provedor_forte = "provedor-teste"
    capturado = {}

    def chamar_falso(*_args, **kwargs):
        capturado.update(kwargs)
        return llm.Resposta(texto="pesquisa concluída", chamadas=[])

    monkeypatch.setattr(llm, "chamar_com_ferramentas", chamar_falso)
    etapas = []
    resposta = orquestrador._executar_tarefa_forte(
        "pesquise", "contexto", etapas.append)

    assert resposta == "pesquisa concluída"
    assert capturado["modelo"] == "terra-teste"
    assert capturado["provedor"] == "provedor-teste"
    nomes = {
        item["function"]["name"]
        for item in capturado["ferramentas"]
    }
    assert "pesquisar_internet" in nomes
    assert "player_tocar" in nomes
    assert etapas


def test_main_separa_voz_rapida_do_chat_digitado():
    rodar = ast.unparse(_funcao("main.py", "rodar_emily"))
    seletor = ast.unparse(_funcao("main.py", "_executar_turno_voz_pc"))
    texto = ast.unparse(_funcao("main.py", "processar_texto_digitado"))

    assert "_executar_turno_voz_pc(entrada)" in rodar
    assert "_executar_turno_voz_rapido(texto)" in seletor
    assert "_executar_turno_com_ferramentas(texto, canal='voz')" in seletor
    assert "_executar_turno_voz_rapido" not in texto
    assert "_executar_turno_com_ferramentas(texto, canal='web')" in texto


def test_modo_ui_prioriza_confirmacao_destrutiva_antes_de_cancelar_sessao():
    funcao = _funcao("main.py", "_processar_modo_ui")
    codigo = ast.unparse(funcao)

    pos_confirmacao = codigo.index("aguardando_confirmacao")
    pos_cancelamento = codigo.index("parar_agente_ui")
    assert pos_confirmacao < pos_cancelamento
    assert "enviar_mensagem_ao_vivo(texto)" in codigo[:pos_cancelamento]


def test_chat_digitado_entrega_confirmacao_pendente_antes_da_conversa_normal():
    codigo = ast.unparse(_funcao("main.py", "processar_texto_digitado"))

    pos_confirmacao = codigo.index("aguardando_confirmacao")
    pos_turno_normal = codigo.index("_executar_turno_com_ferramentas")
    assert pos_confirmacao < pos_turno_normal
    assert "enviar_mensagem_ao_vivo(texto)" in codigo[:pos_turno_normal]


def test_android_nao_importa_orquestrador_de_voz_pc():
    android = RAIZ / "EmilyAPP2"
    if not android.exists():
        return
    for arquivo in android.rglob("*"):
        if arquivo.is_file() and arquivo.suffix in {".kt", ".java", ".gradle"}:
            conteudo = arquivo.read_text(encoding="utf-8", errors="ignore")
            assert "orquestrador_voz" not in conteudo
