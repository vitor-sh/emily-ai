"""Testes headless do agente visual contínuo e de seu backend injetável."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import agente_ui  # noqa: E402
import desktop_backend  # noqa: E402


def _esperar(condicao, timeout: float = 2.0) -> None:
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(0.005)
    raise AssertionError("condição não foi atingida dentro do tempo esperado")


@pytest.fixture(autouse=True)
def _sem_contexto_externo(monkeypatch):
    """Os testes da sessão não devem importar memória/persona nem acessar I/O."""

    monkeypatch.setattr(agente_ui, "_contexto_fixo_padrao", lambda: "")


def _sessao(backend, decisor, **kwargs):
    # A maioria dos testes existentes valida o ciclo genérico, não o protocolo
    # visual extra. Os testes de confirmação o habilitam explicitamente abaixo.
    kwargs.setdefault("verificar_cliques", False)
    return agente_ui.SessaoAgenteUI(
        backend=backend,
        decisor=decisor,
        intervalo_passos=0,
        timeout_total=30,
        timeout_sem_progresso=30,
        **kwargs,
    )


def test_backend_falso_e_deterministico_e_nao_acessa_display():
    backend = desktop_backend.BackendDesktopFalso(
        capturas=["primeira", "segunda"],
        geometria={"left": 10, "top": 20, "width": 800, "height": 600},
    )

    assert backend.capacidades().como_dict() == {
        "nome": "falso", "captura": True, "entrada": True,
        "janelas": True, "motivo_indisponivel": "",
    }
    assert backend.capturar_tela_com_grade() == "primeira"
    assert backend.capturar_tela_com_grade() == "segunda"
    assert backend.capturar_tela_com_grade() == "segunda"
    backend.clicar(12, 34, cliques=2)

    assert backend.geometria() == {"left": 10, "top": 20, "width": 800, "height": 600}
    assert backend.acoes[-1] == ("clicar", (12, 34), {"botao": "left", "cliques": 2})


def test_ciclo_executa_acao_e_conclui_com_observabilidade():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "pressionar", "texto": "tab", "descricao": "Ir ao próximo campo"},
        {"acao": "concluido", "mensagem": "Tudo certo"},
    ])
    falas = []
    estados = []
    sessao = agente_ui.SessaoAgenteUI(
        backend=backend,
        decisor=lambda *_: next(decisoes),
        callback_falar=falas.append,
        callback_estado=lambda estado: estados.append(estado["estado"]),
        intervalo_passos=0,
    )

    assert sessao.iniciar("preencher formulário", em_thread=False) is True

    retrato = sessao.retrato()
    assert retrato["estado"] == "concluido"
    assert retrato["ativo"] is False
    assert retrato["mensagem"] == "Tudo certo"
    assert falas == ["Tudo certo"]
    assert ("pressionar", ("tab",), {"vezes": 1}) in backend.acoes
    assert "capturando" in estados
    assert "decidindo" in estados
    assert "executando" in estados
    assert estados[-1] == "concluido"
    assert sessao.aguardar(0) is True


def test_falha_operacional_da_acao_aparece_imediatamente_no_estado():
    class BackendFalhaClique(desktop_backend.BackendDesktopFalso):
        def clicar(self, x, y, botao="left", cliques=1):
            raise desktop_backend.ErroBackendDesktop("cursor ficou fora da margem segura")

    backend = BackendFalhaClique()
    decisoes = iter([
        {"acao": "clicar", "celula": "A0", "descricao": "Clicar no botão"},
        {"acao": "concluido", "mensagem": "parei com segurança"},
    ])
    estados = []
    sessao = agente_ui.SessaoAgenteUI(
        backend=backend,
        decisor=lambda *_: next(decisoes),
        callback_estado=lambda estado: estados.append(estado),
        intervalo_passos=0,
        verificar_cliques=False,
    )

    assert sessao.iniciar("testar erro visível", em_thread=False) is True

    falhas_visiveis = [estado for estado in estados if estado.get("erro")]
    assert falhas_visiveis
    assert falhas_visiveis[-1]["mensagem"] == "Falha ao executar clicar"
    assert "fora da margem segura" in falhas_visiveis[-1]["erro"]


def test_pausa_durante_decisao_impede_execucao_ate_retomar():
    backend = desktop_backend.BackendDesktopFalso()
    entrou = threading.Event()
    liberar = threading.Event()
    chamadas = 0

    def decidir(*_):
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            entrou.set()
            assert liberar.wait(2)
            return {"acao": "clicar", "celula": "A0", "descricao": "Clique controlado"}
        return {"acao": "concluido", "mensagem": "retomou"}

    sessao = _sessao(backend, decidir)
    assert sessao.iniciar("testar pausa", em_thread=True) is True
    assert entrou.wait(2)
    assert sessao.pausar() is True
    liberar.set()

    _esperar(lambda: sessao.retrato()["estado"] == "pausado")
    time.sleep(0.03)
    assert not any(acao[0] == "clicar" for acao in backend.acoes)

    assert sessao.retomar() is True
    assert sessao.aguardar(2) is True
    assert sessao.retrato()["estado"] == "concluido"
    assert sum(acao[0] == "clicar" for acao in backend.acoes) == 1


def test_cancelamento_durante_decisao_nao_executa_acao_pendente():
    backend = desktop_backend.BackendDesktopFalso()
    entrou = threading.Event()
    liberar = threading.Event()

    def decidir(*_):
        entrou.set()
        assert liberar.wait(2)
        return {"acao": "clicar", "celula": "A0", "descricao": "Não deve executar"}

    sessao = _sessao(backend, decidir)
    assert sessao.iniciar("testar cancelamento", em_thread=True) is True
    assert entrou.wait(2)
    assert sessao.cancelar() is True
    liberar.set()

    assert sessao.aguardar(2) is True
    assert sessao.retrato()["estado"] == "cancelado"
    assert not any(acao[0] == "clicar" for acao in backend.acoes)


class _RelogioFalso:
    def __init__(self):
        self.agora = 0.0

    def __call__(self):
        return self.agora


def test_watchdog_interrompe_apos_operacao_demorada_antes_de_executar():
    backend = desktop_backend.BackendDesktopFalso()
    relogio = _RelogioFalso()

    def decidir(*_):
        relogio.agora = 11
        return {"acao": "clicar", "celula": "A0", "descricao": "Tarde demais"}

    sessao = agente_ui.SessaoAgenteUI(
        backend=backend,
        decisor=decidir,
        max_passos=3,
        timeout_total=10,
        timeout_sem_progresso=20,
        intervalo_passos=0,
        relogio=relogio,
    )

    assert sessao.iniciar("testar watchdog", em_thread=False) is True
    retrato = sessao.retrato()
    assert retrato["estado"] == "watchdog"
    assert "Tempo total excedeu" in retrato["erro"]
    assert not any(acao[0] == "clicar" for acao in backend.acoes)


def test_watchdog_interrompe_por_ausencia_de_progresso():
    backend = desktop_backend.BackendDesktopFalso()
    relogio = _RelogioFalso()
    chamadas = 0

    def decidir(*_):
        nonlocal chamadas
        chamadas += 1
        if chamadas == 2:
            relogio.agora = 6
        return {"acao": "acao_inexistente", "descricao": "Falha sem progresso"}

    sessao = agente_ui.SessaoAgenteUI(
        backend=backend,
        decisor=decidir,
        max_passos=3,
        timeout_total=20,
        timeout_sem_progresso=5,
        intervalo_passos=0,
        relogio=relogio,
    )

    assert sessao.iniciar("testar falta de progresso", em_thread=False) is True
    retrato = sessao.retrato()
    assert retrato["estado"] == "watchdog"
    assert "Sem progresso por mais de 5s" in retrato["erro"]
    assert any("FALHA em acao_inexistente" in item for item in retrato["historico"])


def test_limite_de_passos_encerra_sem_conclusao():
    backend = desktop_backend.BackendDesktopFalso()
    chamadas = 0

    def decidir(*_):
        nonlocal chamadas
        chamadas += 1
        return {"acao": "pressionar", "texto": "tab", "vezes": chamadas}

    sessao = _sessao(backend, decidir, max_passos=2)
    assert sessao.iniciar("não concluir", em_thread=False) is True

    retrato = sessao.retrato()
    assert retrato["estado"] == "limite"
    assert retrato["passo"] == 2
    assert "limite de 2 passos" in retrato["mensagem"]


def test_anti_loop_bloqueia_terceira_repeticao_estrutural():
    backend = desktop_backend.BackendDesktopFalso()
    sessao = _sessao(
        backend,
        lambda *_: {"acao": "clicar", "celula": "B3", "descricao": "texto variável não importa"},
        max_passos=4,
    )

    assert sessao.iniciar("repetir", em_thread=False) is True

    cliques = [acao for acao in backend.acoes if acao[0] == "clicar"]
    assert len(cliques) == 2
    assert any("LOOP DETECTADO" in item for item in sessao.retrato()["historico"])


def test_esperar_nao_libera_repetir_clique_no_mesmo_ponto():
    backend = desktop_backend.BackendDesktopFalso()
    clique = {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50}
    respostas = iter([
        clique, {"acao": "esperar", "tempo": 0}, clique,
        {"acao": "esperar", "tempo": 0}, clique,
    ])
    sessao = _sessao(backend, lambda *_: next(respostas), max_passos=5)
    assert sessao.iniciar("abrir um resultado", em_thread=False)
    assert sum(a[0] == "clicar" for a in backend.acoes) == 2
    assert any("LOOP DETECTADO" in h for h in sessao.retrato()["historico"])


def test_limita_alt_tab_mesmo_quando_intercalado_com_esperas():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "trocar_janela", "descricao": "Ir para Steam"},
        {"acao": "esperar", "tempo": 0},
        {"acao": "trocar_janela", "descricao": "Voltar"},
        {"acao": "esperar", "tempo": 0},
        {"acao": "trocar_janela", "descricao": "Ir para Steam de novo"},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(backend, lambda *_: next(decisoes), max_passos=6)

    assert sessao.iniciar("não entrar em ciclo de janelas", em_thread=False) is True

    alt_tabs = [
        acao for acao in backend.acoes
        if acao[0] == "atalho" and acao[1] == (("alt", "tab"),)
    ]
    assert len(alt_tabs) == 2
    assert any("limite de alternâncias" in item for item in sessao.retrato()["historico"])


def test_limite_alt_tab_tambem_cobre_acao_atalho():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "trocar_janela", "descricao": "Primeira troca"},
        {"acao": "atalho", "texto": "alt+tab", "descricao": "Segunda troca"},
        {"acao": "atalho", "texto": "alt+tab", "descricao": "Terceira troca"},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(backend, lambda *_: next(decisoes), max_passos=4)

    assert sessao.iniciar("não contornar limite com atalho", em_thread=False) is True

    alt_tabs = [
        acao for acao in backend.acoes
        if acao[0] == "atalho" and acao[1] == (("alt", "tab"),)
    ]
    assert len(alt_tabs) == 2
    assert any("limite de alternâncias" in item for item in sessao.retrato()["historico"])


class _BackendCapturaBloqueada(desktop_backend.BackendDesktopFalso):
    def __init__(self):
        super().__init__()
        self.entrou_captura = threading.Event()
        self.liberar_captura = threading.Event()
        self._primeira = True

    def capturar_tela_com_grade(self) -> str:
        if self._primeira:
            self._primeira = False
            self.entrou_captura.set()
            assert self.liberar_captura.wait(2)
        return super().capturar_tela_com_grade()


def test_mensagem_ao_vivo_entra_no_historico_do_proximo_passo():
    backend = _BackendCapturaBloqueada()
    historicos = []

    def decidir(_imagem, _objetivo, historico, _telas, _fixo):
        historicos.append(list(historico))
        if len(historicos) == 1:
            return {"acao": "pressionar", "texto": "tab"}
        return {"acao": "concluido", "mensagem": "instrução recebida"}

    sessao = _sessao(backend, decidir)
    assert sessao.iniciar("objetivo inicial", em_thread=True) is True
    assert backend.entrou_captura.wait(2)
    assert sessao.enviar_mensagem("use o campo da direita") is True
    backend.liberar_captura.set()

    assert sessao.aguardar(2) is True
    assert len(historicos) == 2
    assert not any("INSTRUÇÃO AO VIVO" in item for item in historicos[0])
    assert any("use o campo da direita" in item for item in historicos[1])


def test_escala_coordenadas_da_grade_para_monitor_com_offset():
    backend = desktop_backend.BackendDesktopFalso(
        geometria={"left": 100, "top": 50, "width": 2560, "height": 1440},
    )
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "descricao": "Escalar"},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(backend, lambda *_: next(decisoes))

    assert sessao.iniciar("testar escala", em_thread=False) is True

    assert ("mover", (484, 554), {"duracao": 0.2}) in backend.acoes
    assert ("clicar", (484, 554), {"botao": "left", "cliques": 1}) in backend.acoes


def test_offsets_dentro_da_celula_aumentam_precisao_do_clique():
    backend = desktop_backend.BackendDesktopFalso(
        geometria={"left": 0, "top": 0, "width": 1280, "height": 720},
    )
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 80, "offset_y": 25,
         "descricao": "Clicar no centro exato do botão"},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(backend, lambda *_: next(decisoes))

    assert sessao.iniciar("testar clique fino", em_thread=False) is True

    # B3 começa em (128,216); 80% de 128 = 102 e 25% de 72 = 18.
    assert ("mover", (230, 234), {"duracao": 0.2}) in backend.acoes
    assert ("clicar", (230, 234), {"botao": "left", "cliques": 1}) in backend.acoes


def test_coordenadas_normalizadas_respeitam_monitor_5_por_4_e_limites():
    backend = desktop_backend.BackendDesktopFalso(
        geometria={"left": 1536, "top": 0, "width": 1280, "height": 1024},
    )
    sessao = _sessao(backend, lambda *_: {"acao": "concluido"})

    assert sessao._coordenadas({
        "celula": "B3", "offset_x": 80, "offset_y": 25,
    }) == (1766, 332)
    assert sessao._coordenadas({
        "celula": "J9", "offset_x": 100, "offset_y": 100,
    }) == (2815, 1023)


def test_captura_mss_e_clique_usam_mesma_geometria_ate_em_monitor_secundario(monkeypatch):
    import base64
    from io import BytesIO
    from PIL import Image
    import mss
    import visao

    # Ordem do mss diferente da ordem humana, e monitor com origem negativa.
    monitores = [
        {"left": -1280, "top": 0, "width": 3200, "height": 1080},
        {"left": -1280, "top": 0, "width": 1280, "height": 1024},
        {"left": 0, "top": 0, "width": 1920, "height": 1080, "is_primary": True},
    ]
    gravados = []

    class MSSFalso:
        monitors = monitores

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def grab(self, monitor):
            gravados.append(dict(monitor))
            imagem = Image.new("RGB", (monitor["width"], monitor["height"]), "blue")
            return SimpleNamespace(size=imagem.size, bgra=imagem.tobytes("raw", "BGRX"))

    monkeypatch.setattr(mss, "mss", MSSFalso)
    monkeypatch.setattr(visao, "monitor_atual", 2)
    backend = desktop_backend.BackendPyAutoGUI()
    captura = backend.capturar_tela_com_grade()
    imagem = Image.open(BytesIO(base64.b64decode(captura)))
    assert imagem.size == (1280, 1024)
    assert gravados == [monitores[1]]
    sessao = _sessao(backend, lambda *_: {"acao": "concluido"})
    assert sessao._coordenadas({"celula": "B3", "offset_x": 80, "offset_y": 25}) == (-1050, 332)
    # Outro monitor passou a ser o ativo, mas a imagem ainda é a anterior.
    monkeypatch.setattr(visao, "monitor_atual", 1)
    assert backend.geometria() == {"left": -1280, "top": 0, "width": 1280, "height": 1024}


def test_backend_empacotado_nao_depende_de_python_no_path(monkeypatch):
    import mss

    backend = desktop_backend.BackendPyAutoGUI()
    backend._pyautogui = SimpleNamespace()
    monkeypatch.setattr(desktop_backend.shutil, "which", lambda _: None)
    assert backend.capacidades().captura is True
    assert backend.capacidades().entrada is True
    assert mss is not None


def test_modo_verificado_cancela_se_monitor_mudar_no_meio(monkeypatch):
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    original = backend.capturar_tela_para_verificacao

    def trocar_monitor(x, y):
        imagens = original(x, y)
        backend._geometria["left"] = 1280
        return imagens

    monkeypatch.setattr(backend, "capturar_tela_para_verificacao", trocar_monitor)
    sessao = _sessao(backend, lambda *_: next(decisoes), verificar_cliques=True)
    assert sessao.iniciar("clique seguro", em_thread=False)
    assert not any(acao[0] == "clicar" for acao in backend.acoes)
    assert any("monitor ou resolução mudou" in item for item in sessao.retrato()["historico"])


def test_modo_verificado_recusa_clique_sem_offsets_finos():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "descricao": "Botão sem ponto fino"},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(decisoes), verificar_cliques=True,
    )

    assert sessao.iniciar("testar proteção", em_thread=False) is True
    assert not any(acao[0] == "clicar" for acao in backend.acoes)
    assert any("faltam offset_x e offset_y" in item for item in sessao.retrato()["historico"])


def test_modo_verificado_so_clica_depois_de_confirmacao_visual():
    backend = desktop_backend.BackendDesktopFalso()
    chamadas = 0

    def decidir(imagens, *_):
        nonlocal chamadas
        chamadas += 1
        if chamadas == 1:
            return {
                "acao": "clicar", "celula": "B3", "offset_x": 80, "offset_y": 25,
                "descricao": "Botão Desinstalar",
            }
        if chamadas == 2:
            assert imagens == ["verificacao-geral-falsa", "verificacao-zoom-falso"]
            return {
                "acao": "confirmar_clique", "alvo_confere": True,
                "confianca": 0.93, "descricao": "Botão Desinstalar",
            }
        return {"acao": "concluido", "mensagem": "ok"}

    sessao = _sessao(backend, decidir, verificar_cliques=True)
    assert sessao.iniciar("desinstalar o jogo", em_thread=False) is True

    cliques = [acao for acao in backend.acoes if acao[0] == "clicar"]
    assert cliques == [("clicar", (230, 234), {"botao": "left", "cliques": 1})]
    assert any("ALVO CONFIRMADO" in item for item in sessao.retrato()["historico"])


def test_modo_verificado_relocaliza_e_reconfirma_antes_de_clicar():
    backend = desktop_backend.BackendDesktopFalso()
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Botão Desinstalar"},
        {"acao": "clicar", "celula": "C4", "offset_x": 25, "offset_y": 75,
         "descricao": "Corrigir para o botão Desinstalar"},
        {"acao": "confirmar_clique", "alvo_confere": True, "confianca": 0.88,
         "descricao": "Botão Desinstalar"},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(backend, lambda *_: next(respostas), verificar_cliques=True)

    assert sessao.iniciar("desinstalar o jogo", em_thread=False) is True

    cliques = [acao for acao in backend.acoes if acao[0] == "clicar"]
    assert cliques == [("clicar", (288, 342), {"botao": "left", "cliques": 1})]
    movimentos = [acao[1][:2] for acao in backend.acoes if acao[0] == "mover"]
    assert movimentos[:2] == [(192, 252), (288, 342)]
    assert any("RELOCALIZAÇÃO" in item for item in sessao.retrato()["historico"])


def test_zoom_relocaliza_alvo_na_escala_logica_e_verifica_antes_de_clicar():
    from PIL import Image

    imagem = Image.new("RGB", (1920, 1080), "white")
    geometria = {"left": 100, "top": 50, "width": 1536, "height": 864}
    _, mapa = desktop_backend._imagens_para_verificacao_base64(
        imagem, 868, 482, geometria, retornar_mapa=True,
    )
    assert desktop_backend._coordenada_no_zoom(mapa, 500, 500) == (868, 482)

    class BackendZoom(desktop_backend.BackendDesktopFalso):
        def coordenada_no_zoom(self, zoom_x, zoom_y):
            return desktop_backend._coordenada_no_zoom(mapa, zoom_x, zoom_y)

    backend = BackendZoom(geometria=geometria)
    respostas = iter([
        {"acao": "clicar", "celula": "E5", "offset_x": 50, "offset_y": 50,
         "descricao": "Abrir vídeo"},
        {"acao": "ajustar_clique_zoom", "zoom_x": 500, "zoom_y": 500,
         "descricao": "Centro do vídeo"},
        {"acao": "confirmar_clique", "alvo_confere": True, "confianca": 0.9},
        {"acao": "concluido", "mensagem": "abriu"},
    ])
    sessao = _sessao(backend, lambda *_: next(respostas), verificar_cliques=True)
    assert sessao.iniciar("abrir vídeo", em_thread=False)
    assert [a[1][:2] for a in backend.acoes if a[0] == "clicar"] == [(868, 482)]
    assert sum(a[0] == "capturar_verificacao" for a in backend.acoes) == 2


def test_conclusao_exige_evidencia_visual_apos_clique():
    backend = desktop_backend.BackendDesktopFalso(capturas=["busca", "resultados", "resultados"])
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Abrir vídeo"},
        {"acao": "concluido", "mensagem": "vídeo aberto"},
        {"acao": "erro", "mensagem": "o vídeo não abriu"},
    ])
    verificacoes = []

    def verificar(atual, objetivo, historico, anterior):
        verificacoes.append((atual, anterior))
        return {"concluido": False, "confianca": 0.99,
                "evidencia": "a busca ainda está visível", "proximo_passo": "abrir o resultado"}

    sessao = _sessao(
        backend, lambda *_: next(respostas), verificar_resultado=True,
        verificador_resultado=verificar,
    )
    assert sessao.iniciar("abrir vídeo no YouTube", em_thread=False)
    assert verificacoes == [("resultados", "busca")]
    assert sessao.retrato()["estado"] == "erro"
    assert any("resultado não comprovado" in h for h in sessao.retrato()["historico"])


def test_conclusao_confirmada_por_evidencia_visivel():
    backend = desktop_backend.BackendDesktopFalso(capturas=["busca", "video", "video"])
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50},
        {"acao": "concluido", "mensagem": "Vídeo aberto"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(respostas), verificar_resultado=True,
        verificador_resultado=lambda *_: {
            "concluido": True, "confianca": 0.94,
            "evidencia": "Página do vídeo correto visível e reprodução iniciada",
        },
    )
    assert sessao.iniciar("abrir vídeo", em_thread=False)
    assert sessao.retrato()["estado"] == "concluido"


def test_verificador_envia_estado_anterior_e_atual_com_mime_correto(monkeypatch):
    import base64
    import modelo

    png = base64.b64encode(b"\x89PNG\r\n\x1a\nalgum-conteudo").decode()
    jpeg = base64.b64encode(b"\xff\xd8\xffalgum-conteudo").decode()
    chamadas = []

    def llm_falso(mensagens, **kwargs):
        chamadas.append((mensagens, kwargs))
        return '{"concluido":false,"confianca":0.96,"evidencia":"apenas resultados de busca"}'

    monkeypatch.setattr(modelo.llm, "chamar", llm_falso)
    resultado = modelo.verificar_resultado_ui(jpeg, "abrir um vídeo", ["Clique enviado"], png)
    assert resultado["concluido"] is False
    imagens = chamadas[0][0][0]["images"]
    assert [imagem["media_type"] for imagem in imagens] == ["image/png", "image/jpeg"]
    assert "a lista de resultados não basta" in chamadas[0][0][0]["content"]


def test_modo_verificado_cancela_clique_com_baixa_confianca():
    backend = desktop_backend.BackendDesktopFalso()
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Botão ambíguo"},
        {"acao": "confirmar_clique", "alvo_confere": True, "confianca": 0.61,
         "descricao": "Não tenho certeza"},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(backend, lambda *_: next(respostas), verificar_cliques=True)

    assert sessao.iniciar("testar baixa confiança", em_thread=False) is True
    assert not any(acao[0] == "clicar" for acao in backend.acoes)
    assert any("confiança 0.61" in item for item in sessao.retrato()["historico"])


def test_acao_destrutiva_exige_confirmacao_humana_antes_de_mover_e_clicar():
    backend = desktop_backend.BackendDesktopFalso()
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Desinstalar o jogo", "destrutiva": True},
        {"acao": "confirmar_clique", "alvo_confere": True, "confianca": 0.94,
         "descricao": "Botão Desinstalar"},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(respostas), verificar_cliques=True,
        timeout_confirmacao_destrutiva=2,
    )

    assert sessao.iniciar("desinstalar o jogo", em_thread=True) is True
    _esperar(lambda: sessao.retrato()["estado"] == "aguardando_confirmacao")
    assert not any(acao[0] in {"mover", "clicar"} for acao in backend.acoes)

    assert sessao.enviar_mensagem("sim, confirmo") is True
    assert sessao.aguardar(2) is True
    assert sum(acao[0] == "clicar" for acao in backend.acoes) == 1
    assert any("AÇÃO DESTRUTIVA AUTORIZADA" in item for item in sessao.retrato()["historico"])


def test_confirmacao_destrutiva_respeita_pausa_ate_retomada_explicita():
    backend = desktop_backend.BackendDesktopFalso()
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Desinstalar agora", "destrutiva": True},
        {"acao": "confirmar_clique", "alvo_confere": True, "confianca": 0.91},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(respostas), verificar_cliques=True,
        timeout_confirmacao_destrutiva=2,
    )

    assert sessao.iniciar("desinstalar o jogo", em_thread=True) is True
    _esperar(lambda: sessao.retrato()["estado"] == "aguardando_confirmacao")
    assert sessao.pausar() is True
    assert sessao.enviar_mensagem("sim, confirmo") is True
    time.sleep(0.03)
    assert not any(acao[0] in {"mover", "clicar"} for acao in backend.acoes)

    assert sessao.retomar() is True
    assert sessao.aguardar(2) is True
    assert sum(acao[0] == "clicar" for acao in backend.acoes) == 1


def test_resposta_ambigua_nao_libera_acao_destrutiva():
    backend = desktop_backend.BackendDesktopFalso()
    respostas = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Desinstalar o jogo", "destrutiva": True},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(respostas), verificar_cliques=True,
        timeout_confirmacao_destrutiva=2,
    )

    assert sessao.iniciar("desinstalar o jogo", em_thread=True) is True
    _esperar(lambda: sessao.retrato()["estado"] == "aguardando_confirmacao")
    assert sessao.enviar_mensagem("acho que talvez sim") is True
    time.sleep(0.03)
    assert sessao.retrato()["estado"] == "aguardando_confirmacao"
    assert not any(acao[0] in {"mover", "clicar"} for acao in backend.acoes)

    assert sessao.enviar_mensagem("não, cancelar") is True
    assert sessao.aguardar(2) is True
    assert not any(acao[0] == "clicar" for acao in backend.acoes)
    assert any("ação destrutiva negada" in item for item in sessao.retrato()["historico"])


def test_acao_destrutiva_negada_nao_pode_ser_repetida_na_mesma_sessao():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Confirmar desinstalação"},
        {"acao": "clicar", "celula": "B3", "offset_x": 50, "offset_y": 50,
         "descricao": "Confirmar desinstalação"},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    sessao = _sessao(
        backend, lambda *_: next(decisoes), verificar_cliques=True,
        timeout_confirmacao_destrutiva=2,
    )

    assert sessao.iniciar("desinstalar o jogo", em_thread=True) is True
    _esperar(lambda: sessao.retrato()["estado"] == "aguardando_confirmacao")
    assert sessao.enviar_mensagem("não") is True
    assert sessao.aguardar(2) is True
    assert not any(acao[0] in {"mover", "clicar"} for acao in backend.acoes)
    pedidos = [
        item for item in sessao.retrato()["historico"]
        if "CONFIRMAÇÃO HUMANA NECESSÁRIA" in item
    ]
    assert len(pedidos) == 1


def test_acao_destrutiva_sem_offsets_e_recusada_antes_de_pedir_confirmacao():
    backend = desktop_backend.BackendDesktopFalso()
    decisoes = iter([
        {"acao": "clicar", "celula": "B3", "descricao": "Desinstalar agora",
         "destrutiva": True},
        {"acao": "concluido", "mensagem": "parei"},
    ])
    falas = []
    sessao = _sessao(
        backend, lambda *_: next(decisoes), callback_falar=falas.append,
        verificar_cliques=True, timeout_confirmacao_destrutiva=2,
    )

    assert sessao.iniciar("desinstalar o jogo", em_thread=False) is True
    assert not any(acao[0] in {"mover", "clicar"} for acao in backend.acoes)
    assert not any("Confirma a execução" in fala for fala in falas)
    assert any("faltam offset_x e offset_y" in item for item in sessao.retrato()["historico"])


def test_backend_indisponivel_recusa_inicio_e_sinaliza_finalizacao():
    backend = desktop_backend.BackendDesktopFalso(disponivel=False)
    sessao = _sessao(backend, lambda *_: {"acao": "concluido"})

    assert sessao.iniciar("não deve iniciar", em_thread=True) is False
    retrato = sessao.retrato()
    assert retrato["estado"] == "erro"
    assert retrato["ativo"] is False
    assert "indisponível" in retrato["erro"]
    assert sessao.aguardar(0) is True


def test_acao_ferramenta_usa_executor_estruturado_com_contexto(monkeypatch):
    import ferramentas

    backend = desktop_backend.BackendDesktopFalso()
    chamadas = []

    def executar(nome, argumentos, contexto=None):
        chamadas.append((nome, argumentos, contexto))
        return SimpleNamespace(ok=True, texto="feito", erro=None)

    monkeypatch.setattr(ferramentas, "executar_estruturado", executar)
    decisoes = iter([
        {"acao": "ferramenta", "ferramenta": "eco", "argumentos": {"texto": "oi"}},
        {"acao": "concluido", "mensagem": "ok"},
    ])
    sessao = _sessao(backend, lambda *_: next(decisoes))

    assert sessao.iniciar("usar ferramenta", em_thread=False) is True
    assert chamadas == [(
        "eco", {"texto": "oi"},
        {"pedido_explicito": True, "dono_confirmado": True},
    )]
    assert any("Passo 1: OK" in item for item in sessao.retrato()["historico"])


def test_decisao_visual_configurada_sem_mudar_rota_global(monkeypatch):
    import llm
    import modelo
    import config_agente_visual
    # Independente da preferência pessoal salva no PC onde pytest roda.
    monkeypatch.setattr(config_agente_visual, "configuracao", lambda: {
        "provedor": "omniroute", "modelo": "kr/claude-opus-5", "raciocinio": "medio"})

    chamadas = []
    rota_antes = llm.rota(modelo.ROTA_AGENTE_UI_GMI)

    def chamar(mensagens, **kwargs):
        chamadas.append((mensagens, kwargs))
        return '{"acao":"concluido","mensagem":"ok"}'

    monkeypatch.setattr(llm, "chamar", chamar)
    decisao = modelo.decidir_proxima_acao_ui(
        "base64-falso", "objetivo", [], [], contexto_fixo="",
    )
    rota_depois = llm.rota(modelo.ROTA_AGENTE_UI_GMI)

    assert decisao == {"acao": "concluido", "mensagem": "ok"}
    assert len(chamadas) == 1
    mensagens, kwargs = chamadas[0]
    assert mensagens[0]["images"] == [
        {"media_type": "image/jpeg", "data": "base64-falso"},
    ]
    assert kwargs["provedor"] == "omniroute"
    assert kwargs["modelo"] == "kr/claude-opus-5"
    assert kwargs["raciocinio"] == "medio"
    assert kwargs["max_tokens"] == 8192
    assert kwargs["stream"] is False
    assert rota_depois == rota_antes
