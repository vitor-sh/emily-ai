import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from editor_assistant import Transaction, Assistant, path_in_project, validate_source


def make(tmp_path):
    root=tmp_path/'source';root.mkdir();(root/'sample.py').write_text('value = 1\n');runtime=tmp_path/'runtime';runtime.mkdir();(runtime/'sample.py').write_text('value = 1\n')
    return root,runtime,Transaction(root,{'key':'id:button'},[runtime],tmp_path/'backup')


def test_prepare_validate_apply_multiple_copies_and_undo(tmp_path):
    root,runtime,tx=make(tmp_path)
    tx.tool('editar_codigo',{'arquivo':'sample.py','buscar':'value = 1','substituir':'value = 2'})
    assert root.joinpath('sample.py').read_text()=='value = 1\n'
    result=tx.commit();assert result['restart'] and result['checks']==['sample.py']
    assert root.joinpath('sample.py').read_bytes()==runtime.joinpath('sample.py').read_bytes()==b'value = 2\n'
    assert Path(result['backup'],'manifest.json').exists()
    tx.undo();assert root.joinpath('sample.py').read_bytes()==b'value = 1\n'


def test_invalid_python_or_js_never_applied(tmp_path):
    root,runtime,tx=make(tmp_path)
    tx.tool('editar_codigo',{'arquivo':'sample.py','buscar':'value = 1','substituir':'def broken('})
    with pytest.raises(SyntaxError):tx.commit()
    assert root.joinpath('sample.py').read_bytes()==runtime.joinpath('sample.py').read_bytes()==b'value = 1\n'
    with pytest.raises(ValueError):validate_source('sample.js','const = ;')


@pytest.mark.parametrize('name',['../secret.py','/tmp/secret.py','.env','web/editor-layout.json','dist/file.py','editor_assistant.py','web/../../escape.py'])
def test_scope_blocks_traversal_secrets_and_protected_editor(tmp_path,name):
    with pytest.raises(ValueError):path_in_project(tmp_path,name)


def test_conflicts_prevent_overwrite_and_undo_after_manual_edit(tmp_path):
    root,runtime,tx=make(tmp_path);tx.tool('editar_codigo',{'arquivo':'sample.py','buscar':'value = 1','substituir':'value = 2'});root.joinpath('sample.py').write_text('value = 3\n')
    with pytest.raises(ValueError,match='mudou'):tx.commit()
    assert runtime.joinpath('sample.py').read_text()=='value = 1\n'
    root.joinpath('sample.py').write_text('value = 1\n');tx.commit();runtime.joinpath('sample.py').write_text('manual = 7\n')
    with pytest.raises(ValueError,match='depois'):tx.undo()
    assert root.joinpath('sample.py').read_text()=='value = 2\n'


def test_new_files_and_layout_are_reversible_and_validated(tmp_path):
    root,runtime,tx=make(tmp_path)
    tx.tool('criar_arquivo',{'arquivo':'feature.py','conteudo':'answer = 42\n'})
    tx.tool('personalizar_elemento',{'propriedades_json':json.dumps({'label':'Meu botão','styles':{'width':100}})})
    tx.tool('personalizar_elemento',{'propriedades_json':json.dumps({'styles':{'height':40}})})
    assert tx.layout['styles']=={'width':100,'height':40}
    with pytest.raises(ValueError):tx.tool('personalizar_elemento',{'propriedades_json':'{"onclick":"exec()"}'})
    tx.commit();assert root.joinpath('feature.py').exists();tx.undo();assert not root.joinpath('feature.py').exists()


def test_agent_tools_loop_and_cancellation(tmp_path):
    root,runtime,tx=make(tmp_path);calls=[]
    def model(messages):
        calls.append(messages)
        if len(calls)==1:
            c=SimpleNamespace(id='call1',nome='editar_codigo',argumentos='{}',args=lambda:{'arquivo':'sample.py','buscar':'value = 1','substituir':'value = 9'})
            return SimpleNamespace(texto='',chamadas=[c])
        return SimpleNamespace(texto='Ajustei o código.',chamadas=[])
    a=Assistant(root,[runtime],model);a.start('Mude',{'key':'id:button'})
    for _ in range(200):
        if not a.state()['job']['running']:break
        time.sleep(.01)
    assert a.state()['job']['result']['restart'];assert root.joinpath('sample.py').read_text()=='value = 9\n';assert calls[1][-1]['role']=='tool'
    gate=threading.Event();entered=threading.Event()
    def waiting(messages):entered.set();gate.wait(2);return SimpleNamespace(texto='Feito',chamadas=[])
    b=Assistant(root,[runtime],waiting);b.start('Mude',{'key':'id:button'});entered.wait(1);b.cancel.set();gate.set()
    for _ in range(200):
        if not b.state()['job']['running']:break
        time.sleep(.01)
    assert 'cancelada' in b.state()['job']['error'];assert b.state()['job']['result'] is None


def test_fixed_model_override_does_not_change_global_route(monkeypatch):
    import llm,editor_assistant
    calls=[]
    monkeypatch.setattr(llm,'chamar_com_ferramentas',lambda *a,**kw:calls.append(kw))
    editor_assistant.call_model([{'role':'user','content':'teste'}])
    assert calls[0]['modelo']=='cx/gpt-6-sol' and calls[0]['raciocinio']=='medio' and calls[0]['provedor']=='openai'

def test_restart_requires_saved_editor_and_idle_app(monkeypatch,tmp_path):
    import interface_web,sys,subprocess
    root,runtime,tx=make(tmp_path)
    window=SimpleNamespace(_ultimo_status=('aguardando',''),_editor_dirty=True,_tray_sair=lambda:None)
    api=interface_web.Api(window);api._editor_ai=Assistant(root);api._editor_ai_restart_pending=True
    monkeypatch.setitem(sys.modules,'agente_ui',SimpleNamespace(estado_agente_ui=lambda:{'ativo':False}))
    assert 'Salve' in api.editor_ai_reiniciar()['error']
    window._editor_dirty=False;window._ultimo_status=('falando','')
    assert 'atendimento' in api.editor_ai_reiniciar()['error']
    window._ultimo_status=('aguardando','');calls=[]
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:calls.append((a,kw)))
    monkeypatch.setattr(interface_web.threading,'Timer',lambda *a,**kw:SimpleNamespace(start=lambda:None))
    assert api.editor_ai_reiniciar()['ok'];assert calls and window._editor_close_authorized
    assert calls[0][1]['env']['PYINSTALLER_RESET_ENVIRONMENT']=='1'


def image_reference():
    import io,base64
    from PIL import Image,ImageDraw
    im=Image.new('RGB',(120,100),'white');ImageDraw.Draw(im).ellipse((30,20,90,80),fill='green')
    b=io.BytesIO();im.save(b,'PNG')
    return {'name':'referencia.png','data':'data:image/png;base64,'+base64.b64encode(b.getvalue()).decode()}


def test_attachment_vision_payload_and_no_image_in_polling(tmp_path):
    from editor_assets import attachments
    from llm import normalizar_mensagens
    seen=[]
    def model(messages):
        seen.append(messages);return SimpleNamespace(texto='Vi a referência.',chamadas=[])
    a=Assistant(tmp_path,model_call=model)
    assert a.start('Veja a imagem',{'key':'id:button'},[image_reference()])['ok']
    for _ in range(200):
        if not a.state()['job']['running']:break
        time.sleep(.01)
    assert seen[0][1]['content'][1]['type']=='image_url'
    assert normalizar_mensagens(seen[0])[1].imagens
    assert 'data:image' not in json.dumps(a.state())
    assert not a.start('Veja',{'key':'id:button'},[{'data':'data:image/png;base64,Zm9v'}])['ok']
    with pytest.raises(ValueError):attachments([image_reference()]*5)


def test_raster_edit_composite_transparency_apply_and_undo(tmp_path):
    import io
    from PIL import Image
    from editor_assets import attachments
    root,runtime,tx=make(tmp_path);tx.images=attachments([image_reference()])
    result=json.loads(tx.tool('editar_imagem',{'origem':'imagem1','arquivo':'web/editor-assets/result.webp','operacoes_json':json.dumps([
        {'op':'remove_background','mode':'color','color':'#ffffff','tolerance':25},
        {'op':'crop','box':[10,0,110,100]}, {'op':'resize','width':64,'height':64},
        {'op':'canvas','width':100,'height':100,'x':18,'y':18},
        {'op':'composite','source':'imagem1','width':15,'height':15,'x':0,'y':0}])}))
    assert result['width']==100 and tx.previews
    with Image.open(io.BytesIO(tx.staged['web/editor-assets/result.webp'])) as im:
        assert im.getpixel((99,99))[3]==0
        assert im.getpixel((50,50))[3]>250
    tx.tool('aplicar_imagem',{'origem':'web/editor-assets/result.webp'});assert tx.layout['image'].startswith('data:image/webp')
    r=tx.commit();assert r['images'] and not r['restart']
    assert root.joinpath('web/editor-assets/result.webp').read_bytes()==runtime.joinpath('web/editor-assets/result.webp').read_bytes()
    tx.undo();assert not root.joinpath('web/editor-assets/result.webp').exists()


def test_asset_conflicts_and_svg_active_content_blocked(tmp_path,monkeypatch):
    import editor_assets
    root,runtime,tx=make(tmp_path)
    monkeypatch.setattr(editor_assets,'download',lambda url:('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>','.svg',url))
    tx.tool('baixar_imagem',{'url':'https://example.org/logo.svg','arquivo':'web/editor-assets/logo.svg'})
    with pytest.raises(ValueError):tx.tool('baixar_imagem',{'url':'https://example.org/logo.svg','arquivo':'web/app.js'})
    tx.commit();root.joinpath('web/editor-assets/logo.svg').write_text('manual')
    with pytest.raises(ValueError):tx.undo()
    for raw in [b'<svg><script>alert(1)</script></svg>',b'<svg onload="x"/>',b'<svg><use href="https://evil.com/x"/></svg>',b'<!DOCTYPE svg><svg/>']:
        with pytest.raises(ValueError):editor_assets.safe_svg(raw)
    assert 'path' in editor_assets.safe_svg(b'<svg><path fill="url(#gradient)"/></svg>')


def test_background_model_really_runs_and_preserves_existing_alpha():
    import io,base64
    from PIL import Image
    from editor_assets import remove_background
    raw=base64.b64decode(image_reference()['data'].split(',')[1])
    with Image.open(io.BytesIO(raw)) as im:
        output=remove_background(im.convert('RGBA'))
    assert output.size==(120,100)
    assert output.getchannel('A').getextrema()[0]<10
    assert output.getchannel('A').getextrema()[1]>200


def test_operation_bounds_and_multiple_adjustments(tmp_path):
    from PIL import Image
    import editor_assets
    image=Image.new('RGBA',(50,40),'red')
    operations=[{'op':'flip'}, {'op':'rotate','degrees':90},{'op':'brightness','factor':.8},{'op':'contrast','factor':1.2},
      {'op':'saturation','factor':.5},{'op':'sharpness','factor':1.1},{'op':'blur','radius':1}, {'op':'opacity','factor':.5},
      {'op':'tint','color':'#44aa88'}, {'op':'text','text':'Emily','size':8}, {'op':'border','width':2}]
    raw,w,h=editor_assets.edit(image,operations,lambda _:image)
    assert raw and (w,h)==(44,54)
    with pytest.raises(ValueError):editor_assets.edit(image,[{'op':'resize','width':500000,'height':10}],lambda _:image)
    with pytest.raises(ValueError):editor_assets.edit(image,[{'op':'crop','box':[-1,0,10,10]}],lambda _:image)


def test_public_asset_redirects_revalidated_and_size_limited(monkeypatch):
    import editor_assets,pesquisa,requests
    calls=[]
    class Response:
        status_code=302
        headers={'Location':'http://127.0.0.1/private'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
    def validate(url):
        if '127.0.0.1' in url:raise ValueError('URL local bloqueada')
        return url
    monkeypatch.setattr(pesquisa,'_validar_url_publica',validate)
    monkeypatch.setattr(requests,'get',lambda url,**kwargs:calls.append(url) or Response())
    with pytest.raises(ValueError,match='local'):editor_assets.download('https://example.org/logo')
    assert calls==['https://example.org/logo']
    Response.status_code=200;Response.headers={'Content-Type':'image/png'}
    Response.raise_for_status=lambda self:None
    Response.iter_content=lambda self,n:iter([b'x'*(editor_assets.MAX_INPUT+1)])
    with pytest.raises(ValueError,match='4 MB'):editor_assets.download('https://example.org/logo')


def test_resource_inspection_returns_image_urls_and_safe_inline_svg(monkeypatch):
    import editor_assets
    monkeypatch.setattr(editor_assets,'public_file',lambda url:(b'<html><link href="/brand.svg"><img src="logo.png" alt="Logo"><svg><path d="M0 0"/></svg><svg><script>bad()</script></svg></html>','text/html',url))
    result=editor_assets.inspect_page('https://example.org/page')
    assert result['images'][0]['url']=='https://example.org/brand.svg'
    assert result['images'][1]['url']=='https://example.org/logo.png'
    assert len(result['inline_svg'])==1 and 'script' not in result['inline_svg'][0]


def test_completion_waits_for_apply_callback(tmp_path):
    root,runtime,_=make(tmp_path);entered=threading.Event();release=threading.Event()
    def finalize(result):entered.set();release.wait(2);result['preview_applied']=True;return result
    a=Assistant(root,[runtime],lambda _:SimpleNamespace(texto='Aplicado',chamadas=[]),finalize_result=finalize)
    a.start('Teste',{'key':'id:button'});assert entered.wait(1)
    assert a.state()['job']['running'] and a.state()['job']['result'] is None
    release.set()
    for _ in range(100):
        if not a.state()['job']['running']:break
        time.sleep(.01)
    assert a.state()['job']['result']['preview_applied'] and not a.state()['job']['error']


def test_editor_continua_alem_do_antigo_teto_e_interrompe_repeticao(tmp_path):
    root,runtime,tx=make(tmp_path)
    count=[0]
    def model(messages):
        count[0]+=1
        if count[0]>45: return SimpleNamespace(texto='Ajustado.',chamadas=[])
        args={'arquivo':'sample.py','buscar':f'value = {count[0]}','substituir':f'value = {count[0]+1}'}
        c=SimpleNamespace(id=str(count[0]),nome='editar_codigo',argumentos=json.dumps(args),args=lambda:args)
        return SimpleNamespace(texto='',chamadas=[c])
    a=Assistant(root,[runtime],model)
    a.start('Ajuste o arquivo',{'key':'id:button'})
    for _ in range(300):
        if not a.state()['job']['running']: break
        time.sleep(.01)
    assert not a.state()['job']['error']
    assert root.joinpath('sample.py').read_text()=='value = 46\n'
    def stuck(messages):
        c=SimpleNamespace(id='s',nome='ler_arquivo',argumentos='{}',args=lambda:{'arquivo':'sample.py'})
        return SimpleNamespace(texto='',chamadas=[c])
    b=Assistant(root,[runtime],stuck)
    b.start('Mude',{'key':'id:button'})
    for _ in range(300):
        if not b.state()['job']['running']: break
        time.sleep(.01)
    assert 'sem nova evidência' in b.state()['job']['error']
    assert b.state()['job']['result'] is None
