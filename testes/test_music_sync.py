import copy, json, subprocess, hashlib
from pathlib import Path
import pytest
import music_player as mp
import music_sync as sync
import music_offline as offline

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(mp,'ARQUIVO',tmp_path/'library.json');monkeypatch.setattr(mp,'_cache',None)
    monkeypatch.setattr(offline,'pasta',lambda:tmp_path/'audio')
    return tmp_path

def test_merge_add_remove_settings_keep_position(isolated):
    mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'PC'})
    mp.salvar_estado(video_id='aaaaaaaaaaa',indice=0,posicao=38)
    fields=sync.exchange({})
    remote=copy.deepcopy(fields)
    remote[sync.key('track','default','bbbbbbbbbbb')]={'valor':{'video_id':'bbbbbbbbbbb','titulo':'Celular','thumb':'','adicionada':1},'quando':fields[sync.key('track','default','aaaaaaaaaaa')]['quando']+1,'id':'phone'}
    remote[sync.key('setting','loop')]={'valor':2,'quando':fields[sync.key('setting','loop')]['quando']+1,'id':'phone'}
    sync.exchange(remote)
    assert {m['video_id'] for m in mp.listar()}=={'aaaaaaaaaaa','bbbbbbbbbbb'}
    assert mp.estado()['posicao']==38 and mp.estado()['loop']==2
    stale=copy.deepcopy(remote);mp.remover('bbbbbbbbbbb');sync.exchange(stale)
    assert [m['video_id'] for m in mp.listar()]==['aaaaaaaaaaa']

def test_cross_process_reload_and_deleted_playlist(isolated):
    mp.criar_playlist('Viagem');mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'Oi'},'Viagem')
    old=sync.exchange({});mp.apagar_playlist('Viagem');sync.exchange(old)
    assert 'Viagem' not in mp.listar_playlists()['playlists']
    env=__import__('os').environ.copy();env['EMILY_ARQUIVO_PLAYLIST']=str(mp.ARQUIVO)
    subprocess.run(['python3','-c',"import music_player as m;m.adicionar({'video_id':'bbbbbbbbbbb','titulo':'Outro processo'})"],env=env,check=True)
    assert mp.listar()[0]['video_id']=='bbbbbbbbbbb'

def test_local_ids_and_validation(isolated):
    local='local_'+'a'*64
    assert mp.adicionar({'video_id':local,'titulo':'Local'})
    assert mp.listar()[0]['thumb']==''
    fields=sync.exchange({})
    assert sync.valid_entry(sync.key('track','default',local),fields[sync.key('track','default',local)])
    assert not sync.valid_entry(sync.key('playlist','__locais__'),{'valor':{},'quando':1,'id':'bad'})
    assert not sync.valid_entry(sync.key('track','default','../../file'),{'valor':{},'quando':1,'id':'bad'})

def test_private_gateway_file_hash_and_range(isolated):
    from flask import Flask,jsonify,request
    from music_gateway import register
    app=Flask(__name__)
    register(app,lambda:None if request.headers.get('Authorization')=='Bearer test' else (jsonify(erro='token'),401))
    client=app.test_client();headers={'Authorization':'Bearer test'}
    assert client.post('/music/sync',json={'campos':{}}).status_code==401
    assert client.post('/music/sync',json={'campos':{}},headers=headers).status_code==200
    for route in ('sync','search','lyrics'):
        assert client.post('/music/'+route,json=['invalid'],headers=headers).status_code==400
        assert client.post('/music/'+route,json=[],headers=headers).status_code==400
    f=isolated/'tone.mp3';subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=duration=0.2','-y',str(f)],check=True)
    data=f.read_bytes();vid='local_'+hashlib.sha256(data).hexdigest()
    assert client.put('/music/files/'+vid,data=data,headers=headers).status_code==200
    assert client.get('/music/files/'+vid,headers={**headers,'Range':'bytes=0-9'}).data==data[:10]
    assert client.put('/music/files/local_'+'a'*64,data=data,headers=headers).status_code==400
    assert client.put('/music/files/local_'+'a'*64,data=b'invalid',headers=headers).status_code==400


def test_fedora_uses_permanent_local_gateway():
    if __import__('os').name!='nt':assert sync.endpoint()=='http://127.0.0.1:5000'


def test_invalid_batch_is_atomic_and_duplicate_sync_does_not_write(isolated,monkeypatch):
    mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'Original'})
    original=sync.exchange({})
    baseline=mp.ARQUIVO.read_bytes()
    incoming={sync.key('track','default','bbbbbbbbbbb'):{'valor':{'video_id':'bbbbbbbbbbb','titulo':'Novo'},'quando':__import__('time').time()*1000,'id':'valid'},'invalid':{}}
    with pytest.raises(ValueError):sync.exchange(incoming)
    assert [m['video_id'] for m in mp.listar()]==['aaaaaaaaaaa']
    assert mp.ARQUIVO.read_bytes()==baseline
    calls=[];monkeypatch.setattr(mp,'_salvar',lambda:calls.append(True))
    assert sync.exchange(original)==original
    assert not calls


def test_sync_rejects_bad_sort_fields_and_duplicate_order(isolated):
    entry={'valor':{'video_id':'aaaaaaaaaaa','titulo':'Faixa','adicionada':'ontem'},'quando':1,'id':'bad'}
    assert not sync.valid_entry(sync.key('track','default','aaaaaaaaaaa'),entry)
    entry['valor']['adicionada']=float('nan')
    assert not sync.valid_entry(sync.key('track','default','aaaaaaaaaaa'),entry)
    assert not sync.valid_entry(sync.key('order','default'),{'valor':['aaaaaaaaaaa','aaaaaaaaaaa'],'quando':1,'id':'bad'})


def test_failed_write_discards_partial_cache(isolated,monkeypatch):
    mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'Original'})
    baseline=mp.ARQUIVO.read_bytes()
    fields=sync.exchange({})
    fields[sync.key('track','default','bbbbbbbbbbb')]={'valor':{'video_id':'bbbbbbbbbbb','titulo':'Novo'},'quando':__import__('time').time()*1000,'id':'new'}
    def fail():raise OSError('disk unavailable')
    monkeypatch.setattr(mp,'_salvar',fail)
    with pytest.raises(OSError):sync.exchange(fields)
    assert mp._cache is None
    assert mp.ARQUIVO.read_bytes()==baseline
    assert [m['video_id'] for m in mp.listar()]==['aaaaaaaaaaa']
