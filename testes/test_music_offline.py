import json,time,threading,http.server
from pathlib import Path
import requests
import music_offline as mo
import music_player as mp

def setup(tmp,monkeypatch):
    monkeypatch.setattr(mo,'pasta',lambda:tmp)
    monkeypatch.setattr(mo,'_jobs',{});monkeypatch.setattr(mo,'_worker',None)
    monkeypatch.setattr(mo,'_probe_at',time.monotonic());monkeypatch.setattr(mo,'_online',True)

def test_adicao_idempotente_preserva_ordem(tmp_path,monkeypatch):
    monkeypatch.setattr(mp,'ARQUIVO',tmp_path/'lib.json');monkeypatch.setattr(mp,'_cache',None)
    mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'original'});mp.adicionar({'video_id':'bbbbbbbbbbb','titulo':'segunda'})
    original=mp.listar();mp.adicionar({'video_id':'aaaaaaaaaaa','titulo':'novo'})
    assert mp.listar()==original

def test_download_atomicidade_cancelamento_retentativa(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch);started=threading.Event();release=threading.Event();calls=[]
    def download(item,temp,hook):
        calls.append(item['video_id']);started.set();release.wait(3);hook({'total_bytes':100,'downloaded_bytes':50})
        p=temp/'audio.mp3';p.write_bytes(b'audio final');return p
    monkeypatch.setattr(mo,'_download',download)
    monkeypatch.setattr(mo.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(OSError()))
    item={'video_id':'aaaaaaaaaaa','titulo':'Teste'}
    assert mo.baixar([item])['enfileiradas']==1;assert started.wait(1)
    assert mo.baixar([item])['enfileiradas']==0
    assert mo.estado()['faixas'][item['video_id']]['estado']=='baixando'
    assert not mo.arquivo(item['video_id'])
    mo.cancelar(item['video_id']);worker=mo._worker;release.set();worker.join(3)
    assert not mo.arquivo(item['video_id']) and not list(tmp_path.glob('.download-*'))
    assert mo.baixar([item])['enfileiradas']==1;worker=mo._worker
    if worker:worker.join(3)
    state=mo.estado()['faixas'][item['video_id']];assert state['estado']=='pronto' and state['url']
    assert mo.baixar([item])['enfileiradas']==0
    (tmp_path/'aaaaaaaaaaa.mp3').write_bytes(b'corrompido')
    assert mo.estado()['faixas'][item['video_id']]['estado']=='erro'
    assert mo.baixar([{'video_id':'../../oops'}])['enfileiradas']==0

def test_http_local_ranges_token_e_traversal(tmp_path,monkeypatch):
    setup(tmp_path,monkeypatch);(tmp_path/'aaaaaaaaaaa.mp3').write_bytes(b'0123456789')
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):mo.servir(self)
        def do_HEAD(self):mo.servir(self,True)
        def log_message(self,*a):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{server.server_port}/__emily_music/{mo.TOKEN}/aaaaaaaaaaa.mp3'
    try:
        r=requests.get(url,headers={'Range':'bytes=2-5'});assert r.status_code==206 and r.content==b'2345'
        assert requests.get(url,headers={'Range':'bytes=50-'}).status_code==416
        assert requests.get(url,headers={'Range':'bytes=-0'}).status_code==416
        assert requests.head(url).headers['Content-Length']=='10'
        assert requests.get(url.replace(mo.TOKEN,'wrong')).status_code==404
        assert mo.arquivo('../aaaaaaaa') is None
    finally:server.shutdown();server.server_close()
