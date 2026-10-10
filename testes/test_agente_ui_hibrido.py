"""Ferramentas e UI na mesma sessão, checkpoints e intervenções humanas."""
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agente_ui as a
from desktop_backend import BackendDesktopFalso


@pytest.fixture(autouse=True)
def sem_persona(monkeypatch):
    monkeypatch.setattr(a, "_contexto_fixo_padrao", lambda: "")


def sessao(decisor, **kwargs):
    return a.SessaoAgenteUI(backend=BackendDesktopFalso(), decisor=decisor,
                           intervalo_passos=0, verificar_resultado=False, **kwargs)


def test_ferramenta_devolve_caminho_ao_proximo_passo_visual(monkeypatch):
    import ferramentas
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda *args, **kw:
                        SimpleNamespace(ok=True, texto="Arquivo salvo em /tmp/teste/Lumafly.AppImage", erro=None))
    historicos = []
    decisoes = iter([{"acao": "ferramenta", "ferramenta": "abrir_arquivo", "argumentos": {"arquivo": "teste"}},
                     {"acao": "pressionar", "texto": "enter"}, {"acao": "concluido"}])
    def decidir(_, objetivo, historico, *_resto):
        historicos.append(historico)
        return next(decisoes)
    s = sessao(decidir)
    assert s.iniciar("Baixar, abrir e verificar", em_thread=False)
    assert "/tmp/teste/Lumafly.AppImage" in "\n".join(historicos[1])
    assert any(acao[0] == "pressionar" for acao in s.backend.acoes)
    assert s.retrato()["estado"] == "concluido"


def test_catalogo_inclui_pesquisa_terminal_extracao_e_exclui_recursao():
    from agente_ui_catalogo import catalogo
    nomes = {e["function"]["name"] for e in catalogo()}
    assert {"pesquisar_internet", "executar_terminal", "extrair_arquivo", "abrir_pasta", "perguntar_usuario_tarefa"} <= nomes
    assert "executar_na_tela" not in nomes


def test_abre_dominio_na_mesma_sessao():
    s = sessao(lambda *_: {"acao": "concluido"})
    assert s._executar_ferramenta({"ferramenta": "abrir_ferramentas", "argumentos": {"dominio": "code"}})[0]
    from agente_ui_catalogo import catalogo
    assert "code_ler_arquivo" in {e["function"]["name"] for e in catalogo(s._dominios_ferramentas)}
    assert not s._executar_ferramenta({"ferramenta": "executar_na_tela", "argumentos": {"objetivo": "outra tarefa"}})[0]


def test_prompt_recebe_catalogo_resultados_e_poupa_verificacao(monkeypatch):
    import modelo
    vistos = []
    monkeypatch.setattr(modelo.llm, "chamar", lambda mensagens, **kw:
                        vistos.append(mensagens[0]["content"]) or '{"acao":"concluido"}')
    modelo.decidir_proxima_acao_ui("imagem", "Instalar mod", [], resultados_ferramentas=["Arquivo /tmp/mod.zip verificado"])
    assert '"nome":"extrair_arquivo"' in vistos[-1]
    assert '/tmp/mod.zip verificado' in vistos[-1]
    modelo.decidir_proxima_acao_ui(["tela", "zoom"], "Confirmar botão", [])
    assert '"nome":"extrair_arquivo"' not in vistos[-1]


def test_renova_passos_sem_reiniciar_tarefa(monkeypatch):
    import ferramentas
    chamadas = []
    monkeypatch.setattr(ferramentas, "executar_estruturado", lambda *args, **kw:
                        SimpleNamespace(ok=True, texto="Consulta concluída", erro=None))
    def decidir(*_):
        chamadas.append(1)
        return {"acao": "concluido"} if len(chamadas) == 6 else {
            "acao": "ferramenta", "ferramenta": "hora_atual", "argumentos": {"etapa": len(chamadas)}}
    s = sessao(decidir, max_passos=2, renovar_limites=True)
    assert s.iniciar("Objetivo único", em_thread=False)
    assert s.retrato()["estado"] == "concluido"
    assert s.retrato()["passo"] == 6
    assert s.retrato()["max_passos"] == 6
    assert s.retrato()["objetivo"] == "Objetivo único"


def test_tempo_renovado_somente_com_progresso():
    clock = SimpleNamespace(agora=0.)
    s = sessao(lambda *_: {"acao": "concluido"}, relogio=lambda: clock.agora,
               timeout_total=10, timeout_sem_progresso=20, renovar_limites=True)
    s._inicio_mono = 0
    clock.agora = 8
    s._registrar("arquivo verificado", progresso=True)
    clock.agora = 11
    assert s._motivo_watchdog() == ""
    assert s._orcamento_tempo == 21
    clock.agora = 22
    assert "Tempo total excedeu" in s._motivo_watchdog()


def test_tempo_em_ferramentas_e_pausa_nao_conta_e_nao_desconta_duas_vezes():
    clock = SimpleNamespace(agora=0.)
    s = sessao(lambda *_: {"acao": "concluido"}, relogio=lambda: clock.agora,
               timeout_total=10, timeout_sem_progresso=10)
    s._iniciar_espera()
    clock.agora = 20
    s._iniciar_espera()
    clock.agora = 80
    assert s._motivo_watchdog() == ""
    s._terminar_espera()
    clock.agora = 100
    s._terminar_espera()
    assert s._inicio_mono == s._ultimo_progresso == 100
    assert s._motivo_watchdog() == ""


def test_pergunta_pela_ponte_aceita_resposta_livre_e_retoma(monkeypatch):
    import interface_web
    monkeypatch.setattr(interface_web, "_api_ativa", lambda: None)
    decisoes = iter([{"acao": "ferramenta", "ferramenta": "perguntar_usuario_tarefa",
                      "argumentos": {"pergunta": "Qual mod?"}}, {"acao": "concluido"}])
    s = sessao(lambda *_: next(decisoes))
    def estado(dados):
        if dados["tipo_pergunta"] == "duvida":
            assert s.enviar_mensagem("O mod de câmera")
    s.adicionar_ouvinte(estado)
    s.iniciar("Instalar mod", em_thread=False)
    assert s.retrato()["estado"] == "concluido"
    assert "O mod de câmera" in "\n".join(s.retrato()["historico"])


def test_cancelar_interrompe_pergunta_sem_resposta(monkeypatch):
    import interface_web
    monkeypatch.setattr(interface_web, "_api_ativa", lambda: None)
    s = sessao(lambda *_: {"acao": "ferramenta", "ferramenta": "perguntar_usuario_tarefa",
                           "argumentos": {"pergunta": "Qual arquivo?"}})
    ready = threading.Event()
    s.adicionar_ouvinte(lambda st: ready.set() if st["tipo_pergunta"] == "duvida" else None)
    s.iniciar("Perguntar", em_thread=True)
    assert ready.wait(5)
    assert s.cancelar()
    assert s.aguardar(5)
    assert s.retrato()["estado"] == "cancelado"


def test_terminal_nao_aceita_confirmacao_inventada(monkeypatch):
    import ferramentas, terminal
    args_recebidos = []
    def executar(nome, args, contexto=None):
        args_recebidos.append(dict(args))
        return SimpleNamespace(ok=bool(args["confirmado"]), texto="Resultado", erro=None)
    monkeypatch.setattr(ferramentas, "executar_estruturado", executar)
    monkeypatch.setattr(terminal, "classificar", lambda _: terminal.CONFIRMAR)
    s = sessao(lambda *_: {"acao": "concluido"})
    s.estado.estado = "rodando"
    s.adicionar_ouvinte(lambda st: s.enviar_mensagem("sim, confirmo")
                       if st["tipo_pergunta"] == "confirmacao" else None)
    ok, _ = s._executar_ferramenta({"ferramenta": "executar_terminal", "argumentos": {
        "comando": "dnf install exemplo", "confirmado": True, "autorizacao_direta": True}})
    assert ok
    assert [args["confirmado"] for args in args_recebidos] == [False, True]
    assert all("autorizacao_direta" not in args for args in args_recebidos)


def test_travamento_pede_orientacao_e_retoma_mesma_sessao(monkeypatch):
    import interface_web
    monkeypatch.setattr(interface_web, "_api_ativa", lambda: None)
    s = sessao(lambda *_: {"acao": "concluido"}, renovar_limites=True)
    s.estado.estado = "rodando"
    s.estado.objetivo = "Instalar e mostrar sucesso"
    s.adicionar_ouvinte(lambda st: s.enviar_mensagem("Sim, tente abrir pela pasta Downloads")
                       if st["tipo_pergunta"] == "duvida" else None)
    assert s._orientar_apos_limite("Não houve progresso")
    assert s.estado.objetivo == "Instalar e mostrar sucesso"
    assert s._mensagens.get_nowait() == "Sim, tente abrir pela pasta Downloads"


def test_extracao_real_de_zip_pela_ferramenta_existente(tmp_path):
    import zipfile
    with zipfile.ZipFile(tmp_path / "mod-teste.zip", "w") as arquivo:
        arquivo.writestr("mod/manifest.txt", "Mod de teste instalado")
    s = sessao(lambda *_: {"acao": "concluido"})
    ok, saida = s._executar_ferramenta({"ferramenta": "extrair_arquivo", "argumentos": {
        "arquivo": "mod-teste.zip", "dentro_de": str(tmp_path)}})
    assert ok, saida
    assert (tmp_path / "mod-teste/mod/manifest.txt").read_text() == "Mod de teste instalado"


def test_cancelamento_de_terminal_real_so_atinge_o_processo_da_tarefa():
    import terminal
    cancelamento = threading.Event()
    resultado = []
    thread = threading.Thread(target=lambda: resultado.append(terminal.executar(
        "sleep 30", cancelar_evento=cancelamento)), daemon=True)
    thread.start()
    time.sleep(.25)
    cancelamento.set()
    thread.join(5)
    assert not thread.is_alive()
    assert resultado and resultado[0][1] is False


def test_cartao_no_pc_recebe_resposta_externa_e_fecha(monkeypatch):
    import interface_web
    eventos = []
    janela = SimpleNamespace(_janela=True, _visivel=True, _cid="teste", _push=lambda *e: eventos.append(e))
    monkeypatch.setattr(interface_web, "_api_ativa", lambda: SimpleNamespace(_j=janela))
    assert interface_web.perguntar_usuario_tarefa("Qual mod?", resposta_externa=lambda: "Câmera") == "Câmera"
    assert [e[0] for e in eventos] == ["pergunta_usuario", "pergunta_usuario_fim"]
    assert not interface_web._perguntas_tarefa


def test_cancelar_tarefa_nao_apaga_registro_nem_mata_outro_terminal():
    import terminal
    a_cancel, b_cancel = threading.Event(), threading.Event()
    resultados = {}
    a_thread = threading.Thread(target=lambda: resultados.update(a=terminal.executar("sleep 30", cancelar_evento=a_cancel)))
    b_thread = threading.Thread(target=lambda: resultados.update(b=terminal.executar("sleep 1", cancelar_evento=b_cancel)))
    try:
        a_thread.start()
        limite = time.monotonic() + 5
        while terminal._processo_ativo is None and time.monotonic() < limite:
            time.sleep(.01)
        primeiro = terminal._processo_ativo
        assert primeiro is not None
        b_thread.start()
        while terminal._processo_ativo is primeiro and time.monotonic() < limite:
            time.sleep(.01)
        segundo = terminal._processo_ativo
        assert segundo is not None and segundo is not primeiro
        a_cancel.set()
        a_thread.join(5)
        assert terminal._processo_ativo is segundo
        assert segundo.poll() is None
        b_thread.join(5)
        assert resultados['a'][1] is False and resultados['b'][1] is True
    finally:
        a_cancel.set(); b_cancel.set()
        a_thread.join(5)
        if b_thread.ident is not None:
            b_thread.join(5)
