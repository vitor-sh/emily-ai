"""Controle direto do PC: contrato, validação e confirmação destrutiva."""

from __future__ import annotations

import importlib.util
import base64
import io
from pathlib import Path
import subprocess
import sys

import pytest


RAIZ = Path(__file__).resolve().parents[1]
CAMINHO = RAIZ / "emily-gateway-service" / "pc_control.py"


@pytest.fixture()
def modulo():
    spec = importlib.util.spec_from_file_location("pc_control_teste", CAMINHO)
    carregado = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = carregado
    spec.loader.exec_module(carregado)
    return carregado


@pytest.fixture()
def ambiente(tmp_path, modulo, monkeypatch):
    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    docs = home / "Documentos"
    apps.mkdir(parents=True)
    docs.mkdir(parents=True)
    (apps / "org.mozilla.firefox.desktop").write_text(
        "[Desktop Entry]\nName=Firefox\nExec=firefox\nType=Application\n",
        encoding="utf-8",
    )
    (docs / "relatorio.txt").write_text("conteúdo", encoding="utf-8")
    chamadas = []

    def executor(comando, **kwargs):
        chamadas.append((comando, kwargs))
        return object()

    monkeypatch.setattr(modulo.shutil, "which", lambda programa: f"/usr/bin/{programa}")
    controlador = modulo.PCController(home=home, executor=executor)
    return controlador, home, chamadas


def test_rejeita_acao_e_terminal_arbitrarios(ambiente):
    controlador, _, chamadas = ambiente
    resposta = controlador.executar("terminal", {"comando": "rm -rf /"}, turno_id="t1")
    assert resposta == {"ok": False, "mensagem": "ação não permitida"}
    assert chamadas == []


def test_inventario_pendencias_consulta_monitores_abas_e_processos_sem_acionar_programas(
    modulo, tmp_path, monkeypatch,
):
    class Resposta:
        ok = True

        def json(self):
            return {"monitores": [{"indice": 1}, {"indice": 2}]}

    class Navegador:
        def executar(self, acao, **kwargs):
            assert acao == "listar_abas"
            return {"ok": True, "browser": {"abas": [{"id": 7, "titulo": "Cline", "url": "https://exemplo.com"}]}}

    chamadas = []
    monkeypatch.setattr(modulo.requests, "get", lambda *a, **k: Resposta())
    controller = modulo.PCController(home=tmp_path, token_provider=lambda: "token",
                                     browser_bridge=Navegador(), executor=lambda *a, **k: chamadas.append(a))
    resultado = controller.executar("observacao_pendencias", {}, turno_id="t1")
    assert resultado["ok"]
    assert [m["indice"] for m in resultado["monitores"]] == [1, 2]
    assert resultado["abas"][0]["titulo"] == "Cline"
    assert isinstance(resultado["processos"], list)
    assert chamadas == []


def test_inventario_continua_sem_servico_de_tela(modulo, tmp_path, monkeypatch):
    def indisponivel(*args, **kwargs):
        raise modulo.requests.ConnectionError()

    monkeypatch.setattr(modulo.requests, "get", indisponivel)
    controller = modulo.PCController(home=tmp_path, token_provider=lambda: "token")
    resultado = controller.executar("observacao_pendencias", {}, turno_id="t1")
    assert resultado["ok"] is True
    assert resultado["monitores"] == []


def test_abre_app_com_lista_de_argumentos_sem_shell(ambiente):
    controlador, _, chamadas = ambiente
    resposta = controlador.executar("abrir_app", {"nome": "Firefox"}, turno_id="t1")
    assert resposta["ok"] is True
    comando, opcoes = chamadas[0]
    assert comando == ["gtk-launch", "org.mozilla.firefox"]
    assert "shell" not in opcoes
    assert opcoes["start_new_session"] is True


def test_catalogo_inclui_exports_do_flatpak(modulo, tmp_path):
    controlador = modulo.PCController(home=tmp_path)
    pastas = controlador._desktop_dirs()
    assert Path("/var/lib/flatpak/exports/share/applications") in pastas
    assert tmp_path / ".local/share/flatpak/exports/share/applications" in pastas


def test_busca_e_abertura_ficam_dentro_das_raizes_permitidas(ambiente, tmp_path):
    controlador, home, chamadas = ambiente
    busca = controlador.executar("buscar", {"query": "relatorio", "tipo": "arquivos"}, turno_id="t1")
    assert busca["ok"] is True
    assert busca["resultados"][0]["alvo"] == str(home / "Documentos/relatorio.txt")

    aberto = controlador.executar(
        "abrir_arquivo", {"caminho": str(home / "Documentos/relatorio.txt")}, turno_id="t1",
    )
    assert aberto["ok"] is True
    assert chamadas[-1][0] == ["xdg-open", str(home / "Documentos/relatorio.txt")]

    fora = tmp_path / "fora.txt"
    fora.write_text("não", encoding="utf-8")
    negado = controlador.executar("abrir_arquivo", {"caminho": str(fora)}, turno_id="t1")
    assert negado["ok"] is False
    assert "fora das pastas permitidas" in negado["mensagem"]


def test_site_aceita_http_https_e_rejeita_outros_esquemas(ambiente):
    controlador, _, chamadas = ambiente
    ok = controlador.executar("abrir_site", {"url": "example.com/teste#segredo"}, turno_id="t1")
    assert ok["ok"] is True
    assert chamadas[-1][0] == ["xdg-open", "https://example.com/teste"]

    negado = controlador.executar("abrir_site", {"url": "file:///etc/passwd"}, turno_id="t2")
    assert negado["ok"] is False
    assert len(chamadas) == 1


def test_abertura_reconstroi_ambiente_grafico_de_servico_iniciado_cedo(
    modulo, tmp_path, monkeypatch,
):
    runtime = tmp_path / "run-user"
    runtime.mkdir()
    (runtime / "bus").touch()
    socket_wayland = runtime / "wayland-0"
    socket_wayland.touch()
    capturado = {}

    class Processo:
        def wait(self, timeout):
            assert timeout == 0.35
            return 0

    def executor(comando, **kwargs):
        capturado.update(kwargs)
        return Processo()

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(modulo.Path, "is_socket", lambda caminho: caminho == socket_wayland)
    monkeypatch.setattr(modulo.shutil, "which", lambda programa: f"/usr/bin/{programa}")

    controlador = modulo.PCController(home=tmp_path, executor=executor)
    resposta = controlador.executar("abrir_site", {"url": "example.com"}, turno_id="t1")

    assert resposta["ok"] is True
    assert capturado["env"]["WAYLAND_DISPLAY"] == "wayland-0"
    assert capturado["env"]["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={runtime}/bus"
    assert capturado["stderr"] == subprocess.PIPE


def test_abertura_nao_confirma_quando_launcher_morre_com_erro(modulo, tmp_path, monkeypatch):
    class Processo:
        stderr = io.StringIO("Error: cannot open display")

        def wait(self, timeout):
            assert timeout == 0.35
            return 1

    monkeypatch.setattr(modulo.shutil, "which", lambda programa: f"/usr/bin/{programa}")
    controlador = modulo.PCController(home=tmp_path, executor=lambda *args, **kwargs: Processo())

    resposta = controlador.executar("abrir_site", {"url": "example.com"}, turno_id="t1")

    assert resposta["ok"] is False
    assert "cannot open display" in resposta["mensagem"]


def test_energia_exige_novo_turno_e_token_descartavel(ambiente, modulo, monkeypatch):
    _, home, chamadas = ambiente
    execucoes = []

    def runner(comando, **kwargs):
        execucoes.append((comando, kwargs))
        return subprocess.CompletedProcess(comando, 0, stdout="", stderr="")

    controlador = modulo.PCController(
        home=home,
        executor=lambda comando, **kwargs: chamadas.append((comando, kwargs)),
        runner=runner,
        energia_habilitada=True,
    )

    preparada = controlador.executar("preparar_energia", {"acao": "reiniciar"}, turno_id="turno-1")
    cid = preparada["confirmation_id"]
    assert preparada["requer_confirmacao"] is True
    assert preparada["confirmacao_expira_em_segundos"] == 90

    mesmo_turno = controlador.executar(
        "confirmar_energia", {"confirmation_id": cid}, turno_id="turno-1",
    )
    assert mesmo_turno["ok"] is False
    assert execucoes == []

    novo_turno = controlador.executar(
        "confirmar_energia", {"confirmation_id": cid}, turno_id="turno-2",
    )
    assert novo_turno["ok"] is True
    assert novo_turno["atraso_segundos"] == 10
    assert len([c for c, _ in execucoes if c[0] == "systemd-run"]) == 1
    comando = next(c for c, _ in execucoes if c[0] == "systemd-run")
    assert comando[:4] == ["systemd-run", "--user", comando[2], "--on-active=10s"]
    assert comando[-2:] == ["systemctl", "reboot"]
    assert chamadas == []

    reutilizada = controlador.executar(
        "confirmar_energia", {"confirmation_id": cid}, turno_id="turno-3",
    )
    assert reutilizada["ok"] is False


def test_energia_fica_desabilitada_por_padrao(ambiente):
    controlador, _, chamadas = ambiente
    resposta = controlador.executar("preparar_energia", {"acao": "reiniciar"}, turno_id="turno-1")
    assert resposta["ok"] is False
    assert "desabilitado" in resposta["mensagem"]
    assert chamadas == []


def test_pytest_bloqueia_runner_real_mesmo_com_energia_habilitada(modulo, tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "teste-disjuntor")
    controlador = modulo.PCController(home=tmp_path, energia_habilitada=True)
    resposta = controlador.executar("preparar_energia", {"acao": "reiniciar"}, turno_id="turno-1")
    assert resposta["ok"] is False
    assert "desabilitado" in resposta["mensagem"]


def test_status_nao_dispara_programa(ambiente):
    controlador, _, chamadas = ambiente
    resposta = controlador.executar("status", {}, turno_id="status")
    assert resposta["ok"] is True
    assert "status" in resposta
    assert chamadas == []


def test_navegador_preserva_aba_explicita_e_limita_leitura(modulo, tmp_path):
    chamadas = []

    class BridgeFalsa:
        def executar(self, acao, **kwargs):
            chamadas.append((acao, kwargs))
            if acao == "fechar_outras_abas":
                return {"ok": True, "browser": {"tipo": "ok", "preservada_id": 77, "fechadas": 4}}
            return {"ok": True, "browser": {"tipo": "ok", "titulo": "Página", "texto": "abcdef"}}

    controlador = modulo.PCController(home=tmp_path, browser_bridge=BridgeFalsa())
    fechou = controlador.executar("navegador_fechar_outras", {"tab_id": 77}, turno_id="t1")
    leu = controlador.executar("navegador_ler", {"tab_id": 77, "limite": 3}, turno_id="t2")

    assert fechou["ok"] is True
    assert chamadas[0] == ("fechar_outras_abas", {"timeout": 12.0, "tab_id": 77})
    assert chamadas[1] == ("ler_pagina", {"timeout": 20.0, "tab_id": 77})
    # O controlador impõe mínimo de 1000 caracteres; o texto curto permanece inteiro.
    assert leu["pagina"]["texto"] == "abcdef"


def test_youtube_abre_video_direto_e_historico_retorna_urls_reais(modulo, tmp_path):
    chamadas = []

    class BridgeFalsa:
        def executar(self, acao, **kwargs):
            chamadas.append((acao, kwargs))
            if acao == "abrir_youtube":
                return {"ok": True, "browser": {
                    "tipo": "ok", "video_encontrado": True,
                    "titulo": "Vídeo escolhido", "url": "https://www.youtube.com/watch?v=abc123",
                }}
            if acao == "historico_youtube":
                return {"ok": True, "browser": {"tipo": "ok", "videos": [{
                    "titulo": "Vídeo antigo", "url": "https://www.youtube.com/watch?v=xyz789",
                }]}}
            raise AssertionError(acao)

    controlador = modulo.PCController(home=tmp_path, browser_bridge=BridgeFalsa())
    abriu = controlador.executar(
        "navegador_youtube", {"busca": "vídeo escolhido", "nova_aba": True}, turno_id="t1",
    )
    historico = controlador.executar(
        "navegador_historico_youtube", {"busca": "antigo", "limite": 5}, turno_id="t2",
    )

    assert abriu["ok"] is True
    assert abriu["url"] == "https://www.youtube.com/watch?v=abc123"
    assert historico["videos"][0]["url"] == "https://www.youtube.com/watch?v=xyz789"
    assert chamadas == [
        ("abrir_youtube", {"timeout": 20.0, "busca": "vídeo escolhido", "nova_aba": True, "ativa": True}),
        ("historico_youtube", {"timeout": 20.0, "busca": "antigo", "limite": 5}),
    ]


def test_midia_faz_fallback_limitado_para_extensao(modulo, tmp_path, monkeypatch):
    comandos = []

    def runner(comando, **kwargs):
        comandos.append(comando)
        return subprocess.CompletedProcess(comando, 1, stdout="", stderr="")

    class BridgeFalsa:
        def executar(self, acao, **kwargs):
            assert acao == "controlar_midia"
            assert kwargs["controle"] == "pausar"
            assert kwargs["tab_id"] == 9
            return {"ok": True, "browser": {"tipo": "ok", "controle": "pausar"}}

    monkeypatch.setattr(modulo.shutil, "which", lambda programa: f"/usr/bin/{programa}")
    controlador = modulo.PCController(home=tmp_path, runner=runner, browser_bridge=BridgeFalsa())
    resposta = controlador.executar("midia_controlar", {"acao": "pausar", "tab_id": 9}, turno_id="t1")

    assert resposta["ok"] is True
    assert comandos[0] == ["playerctl", "-l"]


def test_captura_jpeg_autenticada_e_limitada(modulo, tmp_path, monkeypatch):
    jpeg = b"\xff\xd8conteudo-jpeg"
    chamadas = []

    class Resposta:
        status_code = 200
        content = jpeg
        headers = {"X-Emily-Idade": "0.2"}

    def get(url, **kwargs):
        chamadas.append((url, kwargs))
        return Resposta()

    monkeypatch.setattr(modulo.requests, "get", get)
    controlador = modulo.PCController(home=tmp_path, token_provider=lambda: "segredo")
    resposta = controlador.executar("capturar_tela", {"monitor": 2}, turno_id="t1")

    assert resposta["ok"] is True
    assert base64.b64decode(resposta["imagem_base64"]) == jpeg
    assert resposta["mime_type"] == "image/jpeg"
    assert chamadas == [(
        "http://127.0.0.1:8790/tela/jpg?monitor=2&unico=1",
        {"headers": {"Authorization": "Bearer segredo"}, "timeout": (1.5, 25.0)},
    )]


def test_captura_indisponivel_aponta_servico_de_tela(modulo, tmp_path, monkeypatch):
    def get(*_args, **_kwargs):
        raise modulo.requests.ConnectionError("offline")

    monkeypatch.setattr(modulo.requests, "get", get)
    controlador = modulo.PCController(home=tmp_path, token_provider=lambda: "segredo")
    resposta = controlador.executar("capturar_tela", {}, turno_id="t1")

    assert resposta["ok"] is False
    assert "tela-pc.service" in resposta["mensagem"]


def test_confirmacao_de_energia_usa_fala_natural(modulo, tmp_path):
    controlador = modulo.PCController(
        home=tmp_path,
        energia_habilitada=True,
        runner=lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout="", stderr=""),
    )
    resposta = controlador.executar("preparar_energia", {"acao": "desligar"}, turno_id="t1")
    assert resposta["requer_confirmacao"] is True
    assert resposta["mensagem"] == "Tá bom, cê tem certeza que quer desligar o computador agora?"


def test_download_youtube_restringe_host_e_monta_yt_dlp_sem_shell(modulo, tmp_path, monkeypatch):
    ytdlp = tmp_path / "yt-dlp"
    ytdlp.write_text("", encoding="utf-8")
    chamadas = []

    def which(programa):
        return str(ytdlp) if programa == "yt-dlp" else f"/usr/bin/{programa}"

    class Processo:
        pid = 4321

    def executor(comando, **kwargs):
        chamadas.append((comando, kwargs))
        return Processo()

    monkeypatch.setattr(modulo.shutil, "which", which)
    controlador = modulo.PCController(home=tmp_path, executor=executor)
    negado = controlador.executar(
        "baixar_youtube", {"url": "https://example.com/video", "formato": "mp4"}, turno_id="t1",
    )
    resposta = controlador.executar(
        "baixar_youtube", {"url": "https://youtu.be/abc", "formato": "mp3"}, turno_id="t2",
    )

    assert negado["ok"] is False
    assert resposta["ok"] is True
    assert chamadas[0][0][0] == str(ytdlp)
    assert "--no-playlist" in chamadas[0][0]
    assert chamadas[0][0][-1] == "https://youtu.be/abc"
    assert "shell" not in chamadas[0][1]


def test_status_e_cancelamento_de_timer_usam_apenas_runner_falso(modulo, tmp_path, monkeypatch):
    chamadas = []

    def runner(comando, **kwargs):
        chamadas.append(comando)
        if "list-units" in comando:
            stdout = "emily-energia-abc.timer loaded active waiting\noutra.timer loaded active waiting\n"
        elif "show" in comando:
            stdout = (
                "Id=emily-energia-abc.timer\nActiveState=active\nSubState=waiting\n"
                "NextElapseUSecRealtime=Tue 2026-09-22 20:00:00\nTriggers=emily-energia-abc.service\n"
            )
        else:
            stdout = ""
        return subprocess.CompletedProcess(comando, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(modulo.shutil, "which", lambda programa: f"/usr/bin/{programa}")
    controlador = modulo.PCController(home=tmp_path, runner=runner)
    status = controlador.executar("status_energia", {}, turno_id="t1")
    cancelou = controlador.executar(
        "cancelar_agendamento_energia", {"agendamento_id": "emily-energia-abc"}, turno_id="t2",
    )

    assert status["agendamentos"][0]["id"] == "emily-energia-abc"
    assert cancelou["cancelados"] == ["emily-energia-abc"]
    assert chamadas[-1] == [
        "systemctl", "--user", "stop", "emily-energia-abc.timer", "emily-energia-abc.service",
    ]


def test_fechar_app_verifica_saida_real(modulo, tmp_path):
    import shutil
    executable=tmp_path/'emclose-test'
    shutil.copy('/usr/bin/sleep', executable)
    process=subprocess.Popen([str(executable),'20'])
    try:
        c=modulo.PCController(home=tmp_path)
        r=c.executar('fechar_app',dict(nome=executable.name),turno_id='teste')
        assert r['ok']
        process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill();process.wait()


def test_fechar_app_nao_inventa_sucesso_quando_sinal_nao_fecha(modulo, tmp_path, monkeypatch):
    import shutil
    executable=tmp_path/'emclose-test'
    shutil.copy('/usr/bin/sleep',executable)
    process=subprocess.Popen([str(executable),'20'])
    try:
        # Apenas este processo temporário: simula um aplicativo que ignora o pedido de saída.
        kill=modulo.os.kill
        monkeypatch.setattr(modulo.os,'kill',lambda pid,sig:None if pid==process.pid else kill(pid,sig))
        c=modulo.PCController(home=tmp_path)
        r=c.executar('fechar_app',dict(nome=executable.name),turno_id='teste')
        assert not r['ok'] and process.pid in r['processos_restantes']
        assert process.poll() is None
    finally:
        monkeypatch.undo()
        process.kill();process.wait()


def test_energia_irrestrita_dispensa_confirmacao_e_retry_nao_duplica(modulo,tmp_path):
    calls=[]
    def runner(command,**kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command,0,stdout='',stderr='')
    c=modulo.PCController(home=tmp_path,runner=runner,energia_habilitada=True)
    args={'acao':'suspender'}
    a=c.executar('preparar_energia',args,turno_id='pedido1',irrestrito=True)
    b=c.executar('preparar_energia',args,turno_id='pedido1',irrestrito=True)
    assert a['ok'] and not a.get('requer_confirmacao')
    assert a==b and len([c for c in calls if c[0]=='systemd-run'])==1
    assert next(c for c in calls if c[0]=='systemd-run')[-2:]==['systemctl','suspend']
    assert a['atraso_segundos']==10
    normal=c.executar('preparar_energia',{'acao':'reiniciar','irrestrito':True},turno_id='pedido2')
    assert normal['requer_confirmacao'] and len([c for c in calls if c[0]=='systemd-run'])==1


def test_energia_negada_nao_cria_timer(modulo, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(modulo.shutil, 'which', lambda p: '/usr/bin/' + p)
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='s "no"\n', stderr='')
    c = modulo.PCController(home=tmp_path, runner=runner, energia_habilitada=True)
    r = c.executar('preparar_energia', {'acao':'suspender'}, turno_id='t', irrestrito=True)
    assert not r['ok'] and 'Nenhuma ação foi agendada' in r['mensagem']
    assert not any(command[0]=='systemd-run' for command in calls)


def test_status_energia_preserva_falha_do_servico_sem_timer(modulo, tmp_path):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        output = ('emily-energia-abc.service loaded failed failed\n' if 'list-units' in command else
                  'Id=emily-energia-abc.service\nActiveState=failed\nResult=exit-code\nExecMainStatus=1\n')
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr='')
    c = modulo.PCController(home=tmp_path, runner=runner)
    r = c.executar('status_energia', {}, turno_id='t')
    assert r['agendamentos'][0]['falhou']
    assert r['agendamentos'][0]['codigo_saida']=='1'
    assert len(calls)==2


@pytest.mark.parametrize('action',['desligar','reiniciar','suspender','hibernar'])
def test_energy_ack_is_terminal_acceptance_not_physical_proof(modulo,tmp_path,action):
    def runner(command,**kwargs):
        return subprocess.CompletedProcess(command,0,stdout='s "yes"' if command[0]=='busctl' else '',stderr='')
    pc=modulo.PCController(home=tmp_path,runner=runner,energia_habilitada=True)
    result=pc.executar('preparar_energia',{'acao':action},turno_id='energy-receipt',irrestrito=True)
    assert result['ok'] and result['comando_aceito']
    assert result['estado']=='agendado' and result['desconexao_esperada']
    assert result['verificacao_remota_necessaria'] is False
    assert result['acao']==action and result['atraso_segundos']==10


def test_rejected_energy_timer_is_not_accepted(modulo,tmp_path):
    def runner(command,**kwargs):
        return subprocess.CompletedProcess(command,1 if command[0]=='systemd-run' else 0,stdout='s "yes"',stderr='')
    pc=modulo.PCController(home=tmp_path,runner=runner,energia_habilitada=True)
    result=pc.executar('preparar_energia',{'acao':'suspender'},turno_id='rejected',irrestrito=True)
    assert not result['ok'] and not result.get('comando_aceito')
