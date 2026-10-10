"""Biblioteca replicada por campo, com tombstones; nunca replica posição/fila/downloads."""
from __future__ import annotations
import copy, json, os, threading, time, uuid
from contextlib import contextmanager
from pathlib import Path

SETTINGS = ('volume', 'loop', 'shuffle')
LOCAL = '__locais__'

def key(*parts): return json.dumps(parts, ensure_ascii=False, separators=(',', ':'))

def flattened(d):
    out = {}
    for name, tracks in d.get('playlists', {}).items():
        if name == LOCAL: continue
        out[key('playlist',name)] = {'foto': d.get('playlists_fotos',{}).get(name,'')}
        out[key('order',name)] = [t['video_id'] for t in tracks]
        for track in tracks: out[key('track',name,track['video_id'])] = track
    for vid, value in d.get('favoritos',{}).items(): out[key('favorite',vid)] = bool(value)
    for setting in SETTINGS: out[key('setting',setting)] = d.get('player_estado',{}).get(setting, {'volume':100,'loop':1,'shuffle':False}[setting])
    return out

def stamp(d, before):
    after=flattened(d); entries=d.setdefault('music_sync',{})
    for k in before.keys() | after.keys():
        if before.get(k) == after.get(k): continue
        entries[k]={'valor':copy.deepcopy(after.get(k)), 'quando':max(int(time.time()*1000),int(entries.get(k,{}).get('quando',0))+1), 'id':uuid.uuid4().hex}

def seed(d):
    if 'music_sync' not in d:
        d['music_sync']={k:{'valor':copy.deepcopy(v),'quando':1,'id':'migration'} for k,v in flattened(d).items()}

@contextmanager
def transaction(mp):
    with mp._lock:
        lock=mp.ARQUIVO.with_name(mp.ARQUIVO.name+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
        with lock.open('a+b') as f:
            if os.name=='nt':
                import msvcrt
                if not f.tell():f.write(b'0');f.flush()
                f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX)
            try:
                mp._cache=None
                d=mp._carregar();seed(d)
                yield d
            finally:
                if os.name=='nt':f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


def valid_entry(k, e):
    import music_player as mp
    try: p=json.loads(k)
    except (TypeError,ValueError):return False
    if not isinstance(p,list) or not p or not isinstance(e,dict):return False
    if p[0] not in ('playlist','track','order','favorite','setting'):return False
    if len(p)!={'playlist':2,'track':3,'order':2,'favorite':2,'setting':2}[p[0]]:return False
    if not all(isinstance(x,str) and 0<len(x)<=100 for x in p):return False
    if LOCAL in p:return False
    v=e.get('valor'); ts=e.get('quando'); ident=e.get('id')
    if not isinstance(ts,(int,float)) or not 0<=ts<=time.time()*1000+86400000:return False
    if not isinstance(ident,str) or len(ident)>100:return False
    if v is None:return p!=['playlist','default']
    if p[0]=='playlist':return isinstance(v,dict) and isinstance(v.get('foto',''),str) and len(v.get('foto',''))<7_000_000 and (not v.get('foto') or v['foto'].startswith(('data:image/','https://')))
    if p[0]=='track':return isinstance(v,dict) and mp.id_valido(p[2]) and v.get('video_id')==p[2] and isinstance(v.get('titulo'),str) and len(v['titulo'])<=500 and isinstance(v.get('thumb',''),str) and len(v.get('thumb',''))<=7_000_000 and (not v.get('thumb') or v['thumb'].startswith(('https://','data:image/')))
    if p[0]=='order':return isinstance(v,list) and len(v)<=mp.MAX_MUSICAS and all(mp.id_valido(x) for x in v)
    if p[0]=='favorite':return mp.id_valido(p[1]) and isinstance(v,bool)
    if p[0]=='setting':return p[1] in SETTINGS and (isinstance(v,bool) if p[1]=='shuffle' else isinstance(v,int) and not isinstance(v,bool) and 0<=v<=(100 if p[1]=='volume' else 2))
    return False


def rebuild(d):
    entries=d['music_sync']; playlists={'default':[]};photos={};fav={};orders={}
    for k,e in entries.items():
        p=json.loads(k);v=e['valor']
        if p[0]=='playlist' and v is not None:playlists[p[1]]=[];photos[p[1]]=v.get('foto','')
        elif p[0]=='order' and v is not None:orders[p[1]]=v
        elif p[0]=='favorite' and v:fav[p[1]]=True
        elif p[0]=='setting' and v is not None:d['player_estado'][p[1]]=v
    for k,e in entries.items():
        p=json.loads(k);v=e['valor']
        if p[0]=='track' and v is not None and p[1] in playlists:playlists[p[1]].append(copy.deepcopy(v))
    for n, tracks in playlists.items():
        order=orders.get(n,[]); rank={v:i for i,v in enumerate(order)}
        tracks.sort(key=lambda t:(rank.get(t['video_id'],len(rank)),t.get('adicionada',0),t['video_id']))
    d.update(playlists=playlists,playlists_fotos=photos,favoritos=fav)
    if d.get('playlist_ativa') not in playlists:d['playlist_ativa']='default'


def exchange(remote):
    import music_player as mp
    if not isinstance(remote,dict) or len(remote)>20000:raise ValueError('Biblioteca inválida')
    with transaction(mp) as d:
        for k,e in remote.items():
            if not valid_entry(k,e):raise ValueError('Campo inválido na biblioteca')
            old=d['music_sync'].get(k,{'quando':0,'id':''})
            if (e['quando'],e['id'])>(old['quando'],old['id']):d['music_sync'][k]=copy.deepcopy(e)
        rebuild(d);mp._salvar()
        return copy.deepcopy(d['music_sync'])


def install(mp):
    """Todas as escritas usam a mesma trava do gateway e registram o delta."""
    import functools
    def wrap(fn):
        @functools.wraps(fn)
        def call(*a,**kw):
            with transaction(mp) as d:
                before=copy.deepcopy(flattened(d));result=fn(*a,**kw)
                stamp(d,before);mp._salvar()
                return result
        return call
    for name in ('criar_playlist','renomear_playlist','definir_foto_playlist','apagar_playlist','selecionar_playlist','adicionar','organizar','remover','favoritar','salvar_estado'):
        setattr(mp,name,wrap(getattr(mp,name)))

_started=False
_last_sync=0.0

def status():
    return "" if time.time()-_last_sync<30 else "Biblioteca salva neste aparelho; aguardando sincronização."


def endpoint():
    if os.name != 'nt':return 'http://127.0.0.1:5000'
    from emily_remote import gateway_fedora
    return gateway_fedora().rstrip('/')


def start():
    global _started
    if _started:return
    _started=True
    def loop():
        global _last_sync
        import requests, music_player as mp, windows_code_update
        while True:
            try:
                base=endpoint()
                if base.startswith(('https://','http://')):
                    with mp._lock:
                        mp._cache=None;d=mp._carregar();seed(d);fields=copy.deepcopy(d['music_sync'])
                    r=requests.post(base+'/music/sync',json={'campos':fields},headers=windows_code_update._headers(),timeout=15)
                    r.raise_for_status();exchange(r.json()['campos']);_last_sync=time.time()
                    receive_local_files(base,windows_code_update._headers())
            except Exception:pass # journal persists; subsequent cycle retries
            time.sleep(5)
    threading.Thread(target=loop,name='emily-music-sync',daemon=True).start()


def receive_local_files(endpoint, headers):
    import requests,music_player as mp,music_offline as mo,hashlib,tempfile
    ids={m['video_id'] for p in mp.listar_playlists()['playlists'].values() for m in p['musicas'] if m['video_id'].startswith('local_')}
    for vid in ids:
        if mo.arquivo(vid):continue
        try:
            with requests.get(endpoint+'/music/files/'+vid,headers=headers,stream=True,timeout=30) as r:
                if r.status_code!=200:continue
                mo.pasta().mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=mo.pasta(),delete=False) as f:
                    tmp=Path(f.name);h=hashlib.sha256();size=0
                    for chunk in r.iter_content(65536):
                        size+=len(chunk)
                        if size>128*1024*1024:raise ValueError('MP3 grande demais')
                        f.write(chunk);h.update(chunk)
                if h.hexdigest()!=vid[6:]:raise ValueError('Arquivo incompleto')
                mo.importar_local(vid,tmp)
        except Exception:pass
        finally:
            if 'tmp' in locals():tmp.unlink(missing_ok=True)
