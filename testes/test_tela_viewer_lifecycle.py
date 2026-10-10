import importlib.util
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest

@pytest.fixture
def service(monkeypatch):
    root=Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root/'tela-pc-service'))
    spec=importlib.util.spec_from_file_location('viewer_service_test', root/'tela-pc-service/tela_pc_service.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'token_ok',lambda _h:True)
    return module

def test_bad_monitor_keeps_existing_pipeline(service):
    ger=service.Gerenciador()
    ger.portal=SimpleNamespace(streams=[{'node':1,'tamanho':(1920,1080)}])
    existing=SimpleNamespace(parar=lambda:pytest.fail('monitor válido encerrado'))
    ger.pipelines={1:existing}
    with pytest.raises(ValueError):ger._ligar_pipeline(3)
    assert ger.pipelines=={1:existing}

def test_list_uses_authorized_portal_not_x11_phantom_outputs(service,monkeypatch):
    service.GER.rodando=True
    service.GER.portal=SimpleNamespace(streams=[{'node':11,'tamanho':(1920,1080)}, {'node':12,'tamanho':(1600,900)}])
    monkeypatch.setattr(service,'_monitores_humana',lambda:pytest.fail('não deve anunciar monitores não autorizados'))
    result=service.app.test_client().get('/tela/monitores').get_json()
    assert [m['indice'] for m in result['monitores']]==[1,2]
    assert result['monitores'][1]['largura']==1600

def test_static_image_stays_alive_and_sends_keepalive(service,monkeypatch):
    now=[100.0]
    monkeypatch.setattr(service.time,'time',lambda:now[0])
    def next_frame(_ts):now[0]+=2;return b'jpeg-static',99
    pm=SimpleNamespace(erro='',pipeline=SimpleNamespace(get_state=lambda _: (None,service.Gst.State.PLAYING,None)),esperar_novo=next_frame)
    service.GER.pipelines={1:pm}
    monkeypatch.setattr(service.GER,'demandar',lambda _m:None)
    heartbeats=[]
    monkeypatch.setattr(service.GER,'batimento',lambda:heartbeats.append(now[0]))
    response=service.app.test_client().get('/tela/stream?monitor=1',buffered=False)
    it=iter(response.response)
    assert b'jpeg-static' in next(it)
    assert b'jpeg-static' in next(it)
    assert len(heartbeats)>=3
    response.close()

def test_gstreamer_error_is_tuple_and_wakes_waiters(service):
    pm=object.__new__(service.PipelineMonitor);pm.indice=1
    pm.novo_frame=threading.Condition();pm.erro=''
    pm._erro_gst(None,SimpleNamespace(parse_error=lambda:(SimpleNamespace(message='erro real'),'debug')))
    assert pm.erro=='erro real'

def test_composite_capture_is_split_into_physical_outputs_and_virtual_is_not_added(service):
    from tela_monitors import authorized_sources,crop_pipeline
    streams=[{'node':42,'tamanho':(2816,1024)},{'node':43,'tamanho':(1920,1080)}]
    outputs=[{'nome':'HDMI-A-2','posicao':(0,0),'tamanho':(1536,864)},
             {'nome':'DP-1','posicao':(1536,0),'tamanho':(1280,1024)}]
    mapped=authorized_sources(streams,outputs)
    assert len(mapped)==2
    assert [m['node'] for m in mapped]==[42,42]
    assert mapped[0]['crop']==(0,0,1280,160)
    assert mapped[1]['crop']==(1536,0,0,0)
    assert mapped[0]['tamanho']==(1536,864)
    assert 'left=1536' in crop_pipeline(mapped[1])
