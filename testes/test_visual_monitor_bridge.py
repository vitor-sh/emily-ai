"""A ponte visual não inicia cliques em duplicidade nem aceita uma segunda tarefa."""

from __future__ import annotations

import sys
from types import SimpleNamespace


def test_desktop_visual_request_is_idempotent_and_bound_to_action(monkeypatch):
    import servidor

    state = {"ativo": False, "estado": "parado", "objetivo": ""}
    calls = []
    fake = SimpleNamespace(
        estado_agente_ui=lambda: dict(state),
        iniciar_agente_ui=lambda objective, action_id="": (
            calls.append(objective),
            state.update(ativo=True, estado="rodando", objetivo=objective, action_id=action_id),
            "iniciado",
        )[-1],
        enviar_mensagem_ao_vivo=lambda message: calls.append(message) is None,
        parar_agente_ui=lambda: state.update(ativo=False, estado="cancelado"),
    )
    monkeypatch.setitem(sys.modules, "agente_ui", fake)
    monkeypatch.setattr(servidor, "_ponte_token_ok", lambda: True)
    monkeypatch.setattr(servidor, "_callback_processar", lambda _: None)
    monkeypatch.setattr(servidor, "_visual_monitor_action_id", "")
    client = servidor.app.test_client()
    action_id = "12345678-1234-1234-1234-123456789abc"
    payload = {"operation": "start", "action_id": action_id, "objective": "abrir o resultado"}

    assert client.post("/pc/visual-monitor", json=payload).json["ok"] is True
    assert client.post("/pc/visual-monitor", json=payload).json["ok"] is True
    assert calls == ["abrir o resultado"]
    assert client.post("/pc/visual-monitor", json={**payload, "action_id": "aaaaaaaa"}).status_code == 409
    assert client.post("/pc/visual-monitor", json={"operation": "status"}).json["action_id"] == action_id
    state.update(estado="aguardando_confirmacao", mensagem="Confirmar exclusão?")
    assert client.post("/pc/visual-monitor", json={"operation": "status"}).json["estado"]["estado"] == "aguardando_confirmacao"
    assert client.post("/pc/visual-monitor", json={"operation": "message", "action_id": "aaaaaaaa",
                                                  "message": "sim, confirmo"}).status_code == 409
    assert client.post("/pc/visual-monitor", json={"operation": "message", "action_id": action_id,
                                                  "message": "sim, confirmo"}).json["ok"]
    assert calls[-1] == "sim, confirmo"
    assert client.post("/pc/visual-monitor", json={"operation": "cancel", "action_id": action_id}).json["ok"]
    assert state["estado"] == "cancelado"
    # Uma nova tarefa do desktop não pode receber supervisão ou cancelamento
    # direcionados à ação anterior do Android.
    state.update(ativo=True, estado="rodando", objetivo="tarefa do PC", action_id="")
    assert client.post("/pc/visual-monitor", json={"operation":"status"}).json["action_id"] == ""
    for op in ("cancel", "message"):
        assert client.post("/pc/visual-monitor", json={"operation":op, "action_id":action_id,
                                                       "message":"continue"}).status_code == 409
    assert client.post("/pc/visual-monitor", json=payload).status_code == 409
    assert state["ativo"] is True



def test_desktop_visual_request_requires_bridge_token(monkeypatch):
    import servidor

    monkeypatch.setattr(servidor, "_ponte_token_ok", lambda: False)
    assert servidor.app.test_client().post("/pc/visual-monitor", json={"operation": "status"}).status_code == 401


def test_gateway_starts_only_the_fixed_compiled_binary(monkeypatch, tmp_path):
    from pathlib import Path

    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("pc_control_visual_test", root / "emily-gateway-service/pc_control.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    started = []

    class Process:
        def poll(self):
            return None

    controller = module.PCController(home=tmp_path, executor=lambda command, **kwargs:
                                     (started.append((command, kwargs)), Process())[-1])
    monkeypatch.setattr(controller, "_desktop_ready", lambda: False)
    monkeypatch.setattr(module.os, "access", lambda *_: True)
    monkeypatch.setattr(module.Path, "is_file", lambda _: True)
    monkeypatch.setattr(module.Path, "iterdir", lambda _: iter(()))
    monkeypatch.setenv("DISPLAY", ":0")

    first = controller.executar("emily_iniciar", {}, turno_id="turno-1")
    second = controller.executar("emily_iniciar", {}, turno_id="turno-2")
    assert first["ok"] and second["ok"]
    assert len(started) == 1
    assert started[0][0][0].endswith("/dist/Emily/Emily")
    assert started[0][1]["start_new_session"] is True


def test_tarefa_rapida_concluida_nao_e_reiniciada(monkeypatch):
    import servidor
    state = dict(ativo=False, estado='parado', objetivo='')
    calls=[]
    def iniciar(objective, action_id=''):
        calls.append(objective)
        state.update(ativo=False, estado='concluido', objetivo=objective, action_id=action_id)
        return 'concluído'
    monkeypatch.setitem(sys.modules,'agente_ui',SimpleNamespace(estado_agente_ui=lambda:dict(state), iniciar_agente_ui=iniciar))
    monkeypatch.setattr(servidor,'_ponte_token_ok',lambda:True)
    monkeypatch.setattr(servidor,'_callback_processar',lambda _:None)
    monkeypatch.setattr(servidor,'_visual_monitor_action_id','')
    payload=dict(operation='start',action_id='aaaaaaaa',objective='verificar')
    client=servidor.app.test_client()
    assert client.post('/pc/visual-monitor',json=payload).json['ok']
    assert client.post('/pc/visual-monitor',json=payload).json['ok']
    assert calls==['verificar']


def test_servidor_local_isola_socket_do_gateway_e_do_webkit(monkeypatch):
    import servidor
    import threading
    import requests
    import werkzeug.serving
    real=werkzeug.serving.make_server
    servers=[]
    def create(host,port,app,**kwargs):
        server=real(host,port,app,**kwargs)
        servers.append(server)
        return server
    monkeypatch.setattr(werkzeug.serving,'make_server',create)
    monkeypatch.setenv('WERKZEUG_SERVER_FD','123456')
    thread=threading.Thread(target=servidor.iniciar_servidor,args=(0,),daemon=True)
    thread.start()
    import time
    for _ in range(100):
        if servers:break
        time.sleep(.01)
    server=servers[0]
    try:
        r=requests.get(f'http://127.0.0.1:{server.server_port}/status',timeout=2)
        assert r.json()['ok']
        assert not server.socket.get_inheritable()
    finally:
        server.shutdown();thread.join(2)


def test_gateway_nao_duplica_desktop_aberto_quando_ponte_falha(monkeypatch,tmp_path):
    import importlib.util
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('pc_control_instancia_teste',root/'emily-gateway-service/pc_control.py')
    module=importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules,spec.name,module);spec.loader.exec_module(module)
    entry=tmp_path/'22222';entry.mkdir()
    (entry/'exe').symlink_to(root/'dist/Emily/Emily')
    original=Path.iterdir
    monkeypatch.setattr(Path,'iterdir',lambda p:iter([entry]) if str(p)=='/proc' else original(p))
    calls=[]
    controller=module.PCController(home=tmp_path,executor=lambda *a,**k:calls.append(a))
    monkeypatch.setattr(controller,'_desktop_ready',lambda:False)
    result=controller.executar('emily_iniciar',{},turno_id='teste')
    assert result['ok'] and not result['pronta'] and not calls
    assert 'Não abri outra instância' in result['mensagem']
