import copy
import io
import json
from pathlib import Path

import pytest
from PIL import Image
import editor_interface as editor


def layout():
    d=copy.deepcopy(editor.PADRAO)
    d['theme']['--acento']='#ed8055'
    d['elements']['id:btn-config']={'label':'Ajustes','styles':{'width':140,'color':'#ffffff','x':20}}
    d['pages']=[{'id':'custom:aba','title':'Minha aba','icon':'🧩','items':[
        {'id':'custom:grupo','type':'group','label':'Atalhos','styles':{'display':'grid'}},
        {'id':'custom:botao','type':'button','label':'Abrir arquivos','parent':'custom:grupo','action':'cloud'},
    ]}]
    return d


def test_layout_completo_e_validado_sem_mudar_original():
    d=layout();antes=copy.deepcopy(d);saida=editor.validar(d)
    assert d==antes
    assert saida['pages'][0]['items'][1]['parent']=='custom:grupo'
    assert saida['elements']['id:btn-config']['styles']['width']==140


@pytest.mark.parametrize('modificar',[
    lambda d:d['elements']['id:btn-config']['styles'].update(backgroundImage='url(https://evil)'),
    lambda d:d['elements']['id:btn-config'].update(onclick='exec()'),
    lambda d:d['elements']['id:btn-config']['styles'].update(width=float('nan')),
    lambda d:d['pages'][0]['items'][1].update(action='executar_codigo'),
    lambda d:d['pages'][0]['items'][0].update(parent='custom:grupo'),
    lambda d:d['pages'][0]['items'][1].update(id='custom:grupo'),
    lambda d:d['theme'].update({'--bg':'red;display:none'}),
    lambda d:d['elements'].update({'id:editor-toolbar':{'hidden':True}}),
])
def test_recusa_codigo_injecao_ciclos_e_valores_invalidos(modificar):
    d=layout();modificar(d)
    with pytest.raises((ValueError,TypeError)):editor.validar(d)


def test_gravacao_real_multiplos_destinos_e_conflito(monkeypatch,tmp_path):
    fonte=tmp_path/'fonte';runtime=tmp_path/'dist/web/editor-layout.json';user=tmp_path/'dados/editor-layout.json';destinos=[user,fonte/'web/editor-layout.json',runtime]
    monkeypatch.setattr(editor,'destinos',lambda:(destinos,fonte))
    meta=editor.carregar();r=editor.salvar(layout(),meta['revision'],publicar=False)
    assert r['ok'] and len(r['saved'])==3
    assert user.read_bytes()==runtime.read_bytes()==destinos[1].read_bytes()
    assert editor.carregar()['document']['elements']['id:btn-config']['label']=='Ajustes'
    outra=editor.salvar(layout(),meta['revision'],publicar=False)
    assert not outra['ok'] and outra['conflict']
    assert list(tmp_path.rglob('*.tmp'))==[]


def test_layout_mais_recente_e_arquivo_corrompido(monkeypatch,tmp_path):
    a=tmp_path/'a.json';b=tmp_path/'b.json';c=tmp_path/'c.json'
    d=layout();d['updated_at']=20;a.write_text(json.dumps(d));d['updated_at']=30;d['pages'][0]['title']='Atualizada';b.write_text(json.dumps(d));c.write_text('{quebrado')
    monkeypatch.setattr(editor,'destinos',lambda:([a,b,c],None))
    r=editor.carregar();assert r['document']['pages'][0]['title']=='Atualizada';assert r['warnings']


def test_importacao_imagem_real_e_sanitizada(tmp_path):
    path=tmp_path/'icone.png';Image.new('RGB',(1400,800),'red').save(path)
    uri=editor.importar_imagem(path)
    assert uri.startswith('data:image/png;base64,')
    assert editor._imagem(uri)==uri
    with pytest.raises(ValueError):editor._imagem('data:image/svg+xml;base64,PHN2Zz4=')


def test_publicacao_so_ocorre_com_fonte_salvo(monkeypatch,tmp_path):
    fonte=tmp_path/'src';user=tmp_path/'user.json';src=fonte/'web/editor-layout.json'
    monkeypatch.setattr(editor,'destinos',lambda:([user,src],fonte))
    gravar=editor._gravar
    def falhar(path,dados):
        if path==src:raise PermissionError('somente leitura')
        gravar(path,dados)
    monkeypatch.setattr(editor,'_gravar',falhar)
    monkeypatch.setattr(editor,'publicar_windows',lambda *_:pytest.fail('não publique fonte antigo'))
    r=editor.salvar(layout(),editor.carregar()['revision'])
    assert r['ok'] and r['warnings'] and not r['publication']['ok']


def test_detecta_projeto_runtime_e_instancias(monkeypatch,tmp_path):
    fonte=tmp_path/'src';runtime=fonte/'dist/Emily/_internal'
    for path in [fonte/'interface_web.py',fonte/'main.py',fonte/'web/index.html',runtime/'web/index.html',fonte/'emily-windows-instance/web/index.html']:
        path.parent.mkdir(parents=True,exist_ok=True);path.touch()
    monkeypatch.setattr(editor.sys,'_MEIPASS',str(runtime),raising=False)
    monkeypatch.setattr(editor.Path,'home',lambda:tmp_path/'home')
    alvos,src=editor.destinos()
    assert src==fonte
    assert fonte/'web/editor-layout.json' in alvos
    assert runtime/'web/editor-layout.json' in alvos
    assert fonte/'emily-windows-instance/web/editor-layout.json' in alvos


def test_auto_save_real_recuperacao_e_descarte_atomico(monkeypatch,tmp_path):
    monkeypatch.setattr(editor,'destinos',lambda:([tmp_path/'layout.json'],None))
    r=editor.salvar_rascunho(layout(),'revisao-original')
    assert r['ok'] and r['saved_at']>0
    draft=editor.carregar_rascunho()['draft']
    assert draft['base_revision']=='revisao-original'
    assert draft['document']['pages'][0]['title']=='Minha aba'
    editor.limpar_rascunho()
    assert editor.carregar_rascunho()['draft']['saved_at']==0
    assert not list(tmp_path.glob('*.tmp'))


def test_fechamento_nativo_dirty_cancela_e_abre_dialogo():
    from types import SimpleNamespace
    import interface_web
    j=interface_web.JanelaEmily.__new__(interface_web.JanelaEmily)
    j._editor_dirty=True;j._sair_de_verdade=False
    pedidos=[];j._pedir_saida_editor=lambda real:pedidos.append(real)
    assert j._ao_tentar_fechar() is False
    j._tray_sair()
    assert pedidos==[False,True]
    assert not j._sair_de_verdade


def test_mirror_descarta_eventos_antigos():
    from types import SimpleNamespace
    import interface_web
    j=SimpleNamespace();api=interface_web.Api(j)
    api.editor_estado(True,True,5);api.editor_estado(False,False,4)
    assert j._editor_dirty and j._editor_active


def test_publicacao_zip_contem_editor_e_preserva_codigo_anterior(tmp_path):
    import hashlib
    import publicar_windows_codigo as canal
    from zipfile import ZipFile
    root=Path(__file__).resolve().parents[1]
    destino=tmp_path/'canal'
    canal.publicar(1,'1.0.2',destino=destino,root=root,selecionar=['pc_terminal.py'])
    arquivos=['editor_assistant.py','editor_interface.py','interface_web.py','web/index.html','web/app.js','web/editor-core.js','web/editor.js','web/editor.css','web/editor-layout.json','web/editor-panel.html','web/editor-panel.js','web/editor-controls.js','web/dark-controls.js','web/dark-controls.css','web/estilo.css']
    canal.publicar(2,'1.0.2',destino=destino,root=root,selecionar=arquivos)
    meta=json.loads((destino/'latest.json').read_text())
    zips=list(destino.glob('*.zip'))
    assert meta['version']==2
    with ZipFile(max(zips,key=lambda p:p.stat().st_mtime_ns)) as z:
        assert 'pc_terminal.py' in z.namelist()
        for nome in arquivos:assert z.read(nome)==(root/nome).read_bytes()


def test_janela_propriedades_nativa_reutiliza_e_nao_fecha_editor(monkeypatch):
    from types import SimpleNamespace
    import interface_web, webview
    class Event:
        def __init__(self): self.handler=None
        def __iadd__(self, handler): self.handler=handler;return self
    calls=[]
    panel=SimpleNamespace(events=SimpleNamespace(closing=Event()),hide=lambda:calls.append('hide'),show=lambda:calls.append('show'),restore=lambda:calls.append('restore'))
    def create(*args,**kwargs):
        calls.append(kwargs);assert kwargs['width']>=1000 and kwargs['height']>=800;assert kwargs['resizable'];assert isinstance(kwargs['js_api'],interface_web.EditorPanelApi);return panel
    monkeypatch.setattr(webview,'create_window',create)
    j=SimpleNamespace(_httpd=SimpleNamespace(server_address=('127.0.0.1',1234)),_push=lambda e,d:calls.append((e,d)))
    api=interface_web.Api(j)
    assert api.editor_painel_abrir()['ok'];assert api.editor_painel_abrir()['ok'];assert len([x for x in calls if isinstance(x,dict)])==1
    assert panel.events.closing.handler() is False
    assert calls[-1]=='hide'
    bridge=interface_web.EditorPanelApi(api)
    api.editor_painel_estado({'selected':'id:teste'},2);api.editor_painel_estado({'selected':'velho'},1)
    assert bridge.estado()['state']['selected']=='id:teste'
    assert not bridge.estado(api._editor_panel_version)['changed']
    assert not bridge.comando({'kind':'executar_codigo'})['ok']
    assert bridge.comando({'kind':'mode','value':'interact'})['ok']
    assert calls[-1]==('editor_panel_action',{'kind':'mode','value':'interact'})
