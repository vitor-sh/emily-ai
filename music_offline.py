"""Downloads locais, fila limitada e mídia com Range servida só no loopback da UI."""
from __future__ import annotations
import json, os, re, secrets, shutil, threading, time, urllib.request
from pathlib import Path
from urllib.parse import urlsplit

TOKEN=secrets.token_urlsafe(24)
_lock=threading.RLock()
_jobs={}
_worker=None
_online=True
_probe_at=0
_probing=False


def pasta():
    if os.getenv('EMILY_DATA_DIR'):
        return Path(os.environ['EMILY_DATA_DIR'])/'music_offline'
    if os.name=='nt':
        from emily_paths import pasta_dados
        return pasta_dados()/'music_offline'
    return Path(os.getenv('XDG_DATA_HOME') or Path.home()/'.local/share')/'emily/music_offline'


def valido(vid):return isinstance(vid,str) and bool(re.fullmatch(r'(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})',vid))

def _dados():
    try:
        d=json.loads((pasta()/'downloads.json').read_text())
        return d if isinstance(d,dict) else {}
    except (OSError,ValueError):return {}

def _salvar(d):
    raiz=pasta();raiz.mkdir(parents=True,exist_ok=True)
    tmp=raiz/'downloads.tmp'
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(d,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
    tmp.replace(raiz/'downloads.json')

def arquivo(vid,imagem=False):
    if not valido(vid):return None
    p=pasta()/(vid+('.jpg' if imagem else '.mp3'))
    if p.is_symlink() or not p.is_file() or p.stat().st_size<=0:return None
    return p

def _probe():
    global _online,_probing,_probe_at
    try:
        with urllib.request.urlopen('https://www.youtube.com/generate_204',timeout=4) as r:ok=r.status in (200,204)
    except Exception:ok=False
    with _lock:_online=ok;_probe_at=time.monotonic();_probing=False

def estado(forcar=False):
    global _probing
    with _lock:
        if not _probing and (forcar or time.monotonic()-_probe_at>(10 if _online else 2)):
            _probing=True;threading.Thread(target=_probe,daemon=True).start()
        d=_dados();result={}
        for vid,m in d.items():
            if not valido(vid):continue
            p=arquivo(vid)
            if p and p.stat().st_size==m.get('tamanho'):
                result[vid]={**m,'estado':'pronto','url':f'/__emily_music/{TOKEN}/{vid}.mp3',
                    'thumb':f'/__emily_music/{TOKEN}/{vid}.jpg' if arquivo(vid,True) else ''}
        for vid,j in _jobs.items():
            if vid not in result:
                result[vid]={k:v for k,v in j.items() if k not in ('cancelar','item')}
                if j['estado']=='pronto':result[vid].update(estado='erro',erro='Arquivo offline ausente ou incompleto. Baixe novamente.')
        import music_player,music_sync
        settings={k:v for k,v in music_player.estado().items() if k in ('volume','loop','shuffle')}
        return {'faixas':result,'online':_online,'pasta':str(pasta()),'settings':settings,'aviso':music_sync.status()}

def baixar(items):
    global _worker
    if not isinstance(items,list) or len(items)>200:return {'erro':'Lista de músicas inválida.'}
    with _lock:
        d=_dados();n=0
        for item in items:
            if not isinstance(item,dict) or not valido(item.get('video_id')):continue
            vid=item['video_id']
            if vid.startswith('local_'):continue
            if vid in d and arquivo(vid) and arquivo(vid).stat().st_size==d[vid].get('tamanho'):continue
            if _jobs.get(vid,{}).get('estado') in ('fila','baixando'):continue
            _jobs[vid]={'estado':'fila','progresso':0,'titulo':str(item.get('titulo',''))[:120],
                'item':{'video_id':vid,'titulo':str(item.get('titulo',''))[:120]},'cancelar':threading.Event()};n+=1
        if not _worker or not _worker.is_alive():
            _worker=threading.Thread(target=_executar,daemon=True);_worker.start()
    return {'ok':True,'enfileiradas':n}

def cancelar(vid):
    with _lock:
        if vid not in _jobs:return False
        _jobs[vid]['cancelar'].set()
        if _jobs[vid]['estado']=='fila':_jobs[vid]['estado']='cancelado'
        return True

def remover(vid):
    if not valido(vid):return False
    with _lock:
        if _jobs.get(vid,{}).get('estado') in ('fila','baixando'):return False
        d=_dados();d.pop(vid,None);_salvar(d);_jobs.pop(vid,None)
        for ext in ('.mp3','.jpg'):
            try:(pasta()/(vid+ext)).unlink(missing_ok=True)
            except OSError:return False
    return True

def _download(item,temp,hook):
    try:
        import yt_dlp
    except ImportError:
        return _download_externo(item,temp,hook)
    ff=os.getenv('EMILY_FFMPEG') or shutil.which('ffmpeg')
    if not ff:raise ValueError('FFmpeg indisponível. Instale o componente de áudio para baixar músicas.')
    opts={'format':'bestaudio/best','noplaylist':True,'quiet':True,'no_warnings':True,
        'outtmpl':str(temp/'audio.%(ext)s'),'ffmpeg_location':ff,'socket_timeout':15,
        'retries':2,'fragment_retries':2,'max_filesize':512*1024*1024,'progress_hooks':[hook],
        'postprocessors':[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}]}
    with yt_dlp.YoutubeDL(opts) as y: y.extract_info('https://www.youtube.com/watch?v='+item['video_id'],download=True)
    p=temp/'audio.mp3'
    if not p.is_file() or not 0<p.stat().st_size<=512*1024*1024:raise ValueError('O download não produziu um arquivo de áudio válido.')
    return p

def _executar():
    global _worker
    while True:
        with _lock:
            entry=next(((v,j) for v,j in _jobs.items() if j['estado']=='fila'),None)
            if not entry:
                _worker=None
                return
            vid,j=entry;j['estado']='baixando'
        temp=None
        try:
            import tempfile
            raiz=pasta();raiz.mkdir(parents=True,exist_ok=True)
            if shutil.disk_usage(raiz).free<100*1024*1024:raise ValueError('Espaço insuficiente no disco.')
            temp=Path(tempfile.mkdtemp(prefix='.download-',dir=raiz));inicio=time.monotonic()
            def hook(d):
                if j['cancelar'].is_set():raise ValueError('Download cancelado.')
                if time.monotonic()-inicio>900:raise ValueError('O download demorou demais. Tente novamente.')
                total=d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                if total>512*1024*1024 or shutil.disk_usage(raiz).free<30*1024*1024:raise ValueError('Arquivo muito grande ou disco sem espaço.')
                with _lock:j['progresso']=min(99,int(d.get('downloaded_bytes',0)/total*100)) if total else 0
            p=_download(j['item'],temp,hook)
            if j['cancelar'].is_set():raise ValueError('Download cancelado.')
            # Só arquivos finalizados entram no índice; partes nunca são tocáveis.
            with _lock:
                p.replace(raiz/(vid+'.mp3'));d=_dados();d[vid]={'titulo':j['titulo'],'tamanho':(raiz/(vid+'.mp3')).stat().st_size,'baixada':time.time()};_salvar(d)
                j['estado']='pronto';j['progresso']=100
            try:
                with urllib.request.urlopen(f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',timeout=5) as r:thumb=r.read(1_000_001)
                if 0<len(thumb)<=1_000_000:(raiz/(vid+'.jpg')).write_bytes(thumb)
            except Exception:pass
        except Exception as e:
            with _lock:j['estado']='cancelado' if j['cancelar'].is_set() else 'erro';j['erro']=str(e)[:250]
        finally:
            if temp:shutil.rmtree(temp,ignore_errors=True)


def servir(handler,head=False):
    path=urlsplit(handler.path).path
    if not path.startswith('/__emily_music/'):return False
    m=re.fullmatch(r'/__emily_music/([^/]+)/((?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64}))\.(mp3|jpg)',path)
    if not m or not secrets.compare_digest(m[1],TOKEN):handler.send_error(404);return True
    p=arquivo(m[2],m[3]=='jpg')
    if not p:handler.send_error(404);return True
    size=p.stat().st_size;start,end,status=0,size-1,200
    rng=handler.headers.get('Range')
    if rng:
        r=re.fullmatch(r'bytes=(\d*)-(\d*)',rng)
        if not r or not any(r.groups()):handler.send_error(416);return True
        a,b=r.groups()
        if a:start=int(a);end=min(int(b) if b else end,end)
        else:
            if int(b)<=0:handler.send_error(416);return True
            start=max(0,size-int(b))
        if start>end:handler.send_error(416);return True
        status=206
    handler.send_response(status);handler.send_header('Content-Type','audio/mpeg' if m[3]=='mp3' else 'image/jpeg');handler.send_header('Content-Length',str(end-start+1));handler.send_header('Accept-Ranges','bytes')
    if status==206:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.end_headers()
    if not head:
        try:
            with p.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    chunk=f.read(min(65536,remaining))
                    if not chunk:break
                    handler.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass
    return True


def _download_externo(item,temp,hook):
    """Instalações antigas podem não conter yt-dlp no PYZ: binário oficial isolado."""
    import hashlib, subprocess
    raiz=pasta()/'runtime';raiz.mkdir(parents=True,exist_ok=True)
    nome='yt-dlp.exe' if os.name=='nt' else 'yt-dlp_linux'
    exe=raiz/nome
    if not exe.is_file():
        base='https://github.com/yt-dlp/yt-dlp/releases/latest/download/'
        with urllib.request.urlopen(base+'SHA2-256SUMS',timeout=30) as r:sums=r.read(100000).decode()
        digest=next((line.split()[0] for line in sums.splitlines() if line.split()[-1].lstrip('*')==nome),None)
        if not digest:raise ValueError('Não foi possível validar o componente de download.')
        with urllib.request.urlopen(base+nome,timeout=60) as r:data=r.read(100_000_001)
        if len(data)>100_000_000 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Componente de download inválido.')
        part=exe.with_suffix('.tmp');part.write_bytes(data);part.chmod(0o700);part.replace(exe)
    ff=os.getenv('EMILY_FFMPEG') or shutil.which('ffmpeg')
    if not ff:raise ValueError('FFmpeg indisponível para converter a música.')
    log=temp/'download.log'
    with log.open('wb') as f:
        proc=subprocess.Popen([str(exe),'--no-playlist','--no-progress','--socket-timeout','15','--retries','2',
            '--max-filesize','512M','-f','bestaudio/best','-x','--audio-format','mp3','--audio-quality','192K',
            '--ffmpeg-location',ff,'-o',str(temp/'audio.%(ext)s'),'https://www.youtube.com/watch?v='+item['video_id']],
            stdout=f,stderr=f,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            while proc.poll() is None:
                hook({});time.sleep(.2)
            if proc.returncode:raise ValueError('Não foi possível baixar esta música do YouTube. Tente novamente mais tarde.')
        finally:
            if proc.poll() is None:proc.kill()
            proc.wait()
    p=temp/'audio.mp3'
    if not p.is_file() or p.stat().st_size<=0:raise ValueError('Download de áudio incompleto.')
    return p


def importar_local(vid, origem):
    if not valido(vid) or not vid.startswith('local_'):raise ValueError('ID inválido')
    with _lock:
        destino=pasta()/(vid+'.mp3');destino.parent.mkdir(parents=True,exist_ok=True)
        os.replace(origem,destino)
        # Capa embutida é opcional; falhar aqui não invalida o áudio transferido.
        imagem=pasta()/(vid+'.tmp.jpg')
        try:
            import subprocess
            result=subprocess.run([os.getenv('EMILY_FFMPEG') or 'ffmpeg','-v','error','-i',str(destino),'-map','0:v:0','-frames:v','1','-vf','scale=320:-1','-y',str(imagem)],capture_output=True,timeout=10)
            if result.returncode==0 and imagem.is_file() and imagem.stat().st_size>0:imagem.replace(pasta()/(vid+'.jpg'))
        except (OSError,subprocess.SubprocessError):pass
        finally:imagem.unlink(missing_ok=True)
        d=_dados();d[vid]={'titulo':'Música local','tamanho':destino.stat().st_size,'baixada':time.time(),'local':True};_salvar(d)
