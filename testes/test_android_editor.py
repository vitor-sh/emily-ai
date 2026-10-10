import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from android_editor import validate_document,android_path,Manager,API,revision,atomic
from android_editor_instrument import instrument


def blank():return {'version':1,'elements':{},'pages':[]}

def project(tmp_path):
    assets=tmp_path/'EmilyAPP2/app/src/main/assets';assets.mkdir(parents=True)
    (assets/'editor-layout.json').write_text(json.dumps(blank()));(assets/'editor-catalog.json').write_text('[]')
    (tmp_path/'output').mkdir();return Manager(tmp_path)


def test_layout_rejects_invalid_numbers_and_structural_properties():
    for rule in [{'width':-1},{'opacity':2},{'fontSize':float('nan')},{'action':'terminal'},{'hidden':'yes'},{'unexpected':'x'}]:
        with pytest.raises(ValueError):validate_document({'version':1,'elements':{'Text:1':rule},'pages':[]})
    d={'version':1,'elements':{'Text:1':{'label':'Título','x':-30,'color':'#ff8833'}},'pages':[]}
    assert validate_document(d)==d
    for key in ['../passwd','key with spaces']:
        with pytest.raises(ValueError):validate_document({'version':1,'elements':{key:{}},'pages':[]})


def test_android_ai_cannot_read_credentials_or_desktop(tmp_path):
    for name in ['local.properties','../.env','app/build.gradle.kts','app/src/main/java/com/example/emilyapp/UiEditor.kt','web/app.js']:
        with pytest.raises(ValueError):android_path(tmp_path,name)
    allowed='app/src/main/java/com/example/emilyapp/Test.kt';assert android_path(tmp_path,allowed)==tmp_path/allowed
    assert android_path(tmp_path,'web/editor-assets/icon.webp')==tmp_path/'app/src/main/assets/editor-images/icon.webp'
    target=tmp_path/'app/src/main/java/com/example/emilyapp';target.mkdir(parents=True);(target/'Link.kt').symlink_to(tmp_path/'outside.kt')
    with pytest.raises(ValueError):android_path(tmp_path,'app/src/main/java/com/example/emilyapp/Link.kt')


def test_preview_build_does_not_change_apk_defaults(tmp_path,monkeypatch):
    m=project(tmp_path);doc=blank();doc['elements']['Text:1']={'label':'Só prévia'}
    monkeypatch.setattr('threading.Thread',lambda *a,**kw:SimpleNamespace(start=lambda:None))
    r=m.build(doc,revision(blank()),publish=False)
    assert json.loads(m.saved.read_text())==blank()
    assert r['job']['revision']==revision(blank())
    assert json.loads(m.draft.read_text())['document']==doc
    with pytest.raises(ValueError):m.build(doc,revision(blank()),publish=False)


def test_publication_conflict_preserves_source(tmp_path,monkeypatch):
    m=project(tmp_path);before=m.saved.read_bytes()
    with pytest.raises(ValueError):m.build(blank(),'stale',True)
    assert m.saved.read_bytes()==before


def test_failed_build_keeps_recoverable_draft(tmp_path,monkeypatch):
    m=project(tmp_path);monkeypatch.setattr('threading.Thread',lambda *a,**kw:SimpleNamespace(start=lambda:None))
    doc=blank();doc['elements']['Text:1']={'label':'Novo'};m.build(doc,revision(blank()),True)
    monkeypatch.setattr('subprocess.run',lambda *a,**kw:SimpleNamespace(returncode=1))
    m._build(True)
    assert not m.job['running'] and m.job['ok'] is False
    assert m.draft.exists() and json.loads(m.draft.read_text())['document']==doc


def test_discard_restores_code_and_refuses_external_changes(tmp_path):
    m=project(tmp_path);file=tmp_path/'Test.kt';file.write_bytes(b'edited')
    m.code_changes[str(file)]={'original':b'original','applied':b'edited'}
    file.write_bytes(b'external')
    with pytest.raises(ValueError):m.finish(True)
    assert file.read_bytes()==b'external'
    file.write_bytes(b'edited');m.finish(True);assert file.read_bytes()==b'original'


def test_instrumentation_preserves_positional_modifier_and_literal_text(tmp_path):
    p=tmp_path/'Screen.kt';p.write_text('''package com.example.emilyapp
@Composable fun Screen() {
 Spacer(Modifier.height(5.dp))
 Text(text = "Nome", /* comentário */ color = Color.White)
 Text("Outro", Modifier.padding(4.dp))
 Column(Modifier.fillMaxSize()) { Text("Filho") }
}''')
    catalog=instrument(p,tmp_path/'backup.kt');text=p.read_text()
    assert len(catalog)==5
    assert 'Spacer(UiEditor.mod(' in text
    assert 'UiEditor.text("Screen:Text:0001", "Nome")' in text
    assert 'Text(UiEditor.text("Screen:Text:0002","Outro"),UiEditor.mod(' in text.replace(', ', ',')
    assert 'Modifier.padding(4.dp)' in text
    assert text.count('modifier = UiEditor.mod(')==2  # only the two Text calls without positional modifiers


def test_new_pages_validate_uniqueness():
    doc=blank();doc['pages']=[{'id':'custom:p','title':'Minha página','items':[{'id':'custom:i','type':'button','label':'Config','action':'settings'}]}]
    assert validate_document(doc)==doc
    doc['pages'][0]['items'].append(doc['pages'][0]['items'][0].copy())
    with pytest.raises(ValueError):validate_document(doc)


def test_code_draft_recovers_after_restart_and_discards(tmp_path):
    m=project(tmp_path);name='app/src/main/java/com/example/emilyapp/Screen.kt';p=m.project/name;p.parent.mkdir(parents=True);p.write_bytes(b'edited')
    m.code_changes[str(p)]={'original':b'old','applied':b'edited'};m.persist_code()
    recovered=Manager(tmp_path);assert recovered.dirty and recovered.code_changes[str(p)]['original']==b'old'
    recovered.finish(True);assert p.read_bytes()==b'old' and not recovered.code_draft.exists()


def test_ai_applies_layout_before_finishing_and_preserves_draft(tmp_path,monkeypatch):
    m=project(tmp_path);m.preview=True;m.ai_document=blank();m.ai_revision=revision(blank());seen=[]
    m.assistant=SimpleNamespace(tx=SimpleNamespace(originals={},applied={}),job={'id':'ai','selected':'Text:1'},progress=lambda *x:seen.append(x))
    monkeypatch.setattr(m,'push_preview',lambda doc:seen.append(('push',doc.copy())))
    monkeypatch.setattr(m,'wait_preview',lambda doc:seen.append(('confirmed',doc.copy())))
    result=m.apply_ai_result({'files':[],'layout':{'label':'Novo'},'message':'Pronto'})
    assert result['preview_applied'] and result['document']['elements']['Text:1']['label']=='Novo'
    assert seen[-1][0]=='confirmed' and json.loads(m.draft.read_text())['document']==result['document']
    assert json.loads(m.saved.read_text())==blank()


def test_ai_code_build_failure_keeps_committed_changes_undoable(tmp_path,monkeypatch):
    m=project(tmp_path);m.preview=True;m.ai_document=blank();m.ai_revision=revision(blank())
    p=m.project/'app/src/main/java/com/example/emilyapp/Screen.kt';p.parent.mkdir(parents=True);p.write_bytes(b'new')
    m.assistant=SimpleNamespace(tx=SimpleNamespace(originals={p:b'old'},applied={p:b'new'}),job={'id':'ai','selected':'Text:1'},progress=lambda *x:None)
    def failed(*args,**kw):m.job={'running':False,'ok':False,'error':'USB desconectado'}
    monkeypatch.setattr(m,'build',failed)
    with pytest.raises(ValueError,match='não foi confirmada'):m.apply_ai_result({'files':['Screen.kt'],'layout':{},'message':'Pronto'})
    assert m.code_changes[str(p)]['original']==b'old' and m.code_draft.exists()
    assert m.assistant.job['result']['files'] and not m.assistant.job['result'].get('preview_applied')


def test_preview_confirmation_requires_revision_and_active_tree(tmp_path,monkeypatch):
    m=project(tmp_path);responses=iter([{'active':True,'revision':'old','nodes':[1]},{'active':True,'revision':revision(blank()),'nodes':[1]},{'active':True,'revision':revision(blank()),'nodes':[1]}])
    monkeypatch.setattr(m,'adb_run',lambda *a,**kw:json.dumps(next(responses)).encode())
    m.wait_preview(blank(),timeout=2)


def test_confirmation_waits_for_the_edited_screen_after_install(tmp_path,monkeypatch):
    m=project(tmp_path);trees=[{'active':True,'revision':revision(blank()),'nodes':[1],'route':route,'section':section} for route,section in [('home',''),('settings',''),('settings','AVANCADO'),('settings','AVANCADO')]]
    monkeypatch.setattr(m,'adb_run',lambda *a,**kw:json.dumps(trees.pop(0)).encode())
    m.wait_preview(blank(),location={'route':'settings','section':'AVANCADO'},timeout=3)
    assert not trees


def test_stale_app_preview_cannot_click_another_android_app(tmp_path,monkeypatch):
    m=project(tmp_path);m.preview=True;calls=[]
    def adb(*args,**kw):calls.append(args);return b'{"focused": false}'
    monkeypatch.setattr(m,'adb_run',adb)
    with pytest.raises(ValueError,match='janela atual'):m.input('tap',[10,10])
    assert len(calls)==1
    m.input('key',['4']);assert calls[-1][-2:]==('keyevent','4')


def test_reconnect_waits_for_the_new_native_video_session(tmp_path,monkeypatch):
    m=project(tmp_path);m.preview=True;m.serial='phone';seen=[]
    monkeypatch.setattr(m,'devices',lambda:[{'serial':'phone','state':'device'}])
    monkeypatch.setattr(m,'adb_run',lambda *a,**kw:b'{"path":"old-session"}' if 'editor-video.json' in ' '.join(a) else b'')
    monkeypatch.setattr(m,'start_stream',lambda **kw:seen.append(kw))
    assert m.connect('phone')['ok'] and seen==[{'after':'old-session'}]
    assert m.preview
