"""Ponte HTTPS privada: pareamento revogável, APKs locais e gateway PC por SSH."""
from __future__ import annotations
from contextlib import contextmanager
import argparse
import hashlib
import hmac
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import time
from urllib.parse import urlsplit
import re
import requests
from flask import Flask, Response, jsonify, request, send_file, stream_with_context

CONFIG_FILE = Path(os.getenv('EMILY_RELAY_CONFIG', str(Path.home()/'.config/emily-relay/config.json')))
MODELS = ['kr/claude-sonnet-5.5','kr/claude-opus-5.5','kr/claude-opus-5','kr/claude-haiku-4.5']

def load_config():
    return json.loads(CONFIG_FILE.read_text())

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

@contextmanager
def database(cfg):
    folder = Path(cfg['data_dir'])
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(folder/'devices.sqlite', timeout=10)
    db.row_factory = sqlite3.Row
    db.executescript('''CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,label TEXT,token_hash TEXT UNIQUE,created REAL,revoked INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS pairing(code_hash TEXT PRIMARY KEY,expires REAL,used INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS attempts(ip TEXT,at REAL);''')
    try:
        with db: yield db
    finally: db.close()

def make_pair(cfg):
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    with database(cfg) as db:
        db.execute('DELETE FROM pairing WHERE expires < ?', (time.time(),))
        db.execute('INSERT INTO pairing VALUES(?,?,0)', (digest(code),time.time()+600))
    return code

def create_app(cfg=None):
    cfg = cfg or load_config()
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 24*1024*1024
    with database(cfg): pass

    def public_viewer():
        return request.method == 'GET' and re.fullmatch(r'/cloud/content/[^/]+',request.path) and bool(re.fullmatch('[0-9a-f]{64}',request.args.get('sig',''))) and request.args.get('exp','').isdigit() and not request.headers.get('Authorization')

    @app.before_request
    def authenticate():
        if request.path.startswith('/admin/'):
            expected = cfg.get('upload_key', '')
            supplied = request.headers.get('Authorization', '')
            if expected and secrets.compare_digest(supplied, 'Bearer '+expected): return
            return jsonify(erro='Publicação não autorizada'),401
        if request.path == '/pair/claim' and request.method == 'POST': return
        # Links de visualização existentes: a assinatura é validada pelo PC,
        # sem acrescentar a credencial do proprietário a pedidos públicos.
        if public_viewer(): return
        auth = request.headers.get('Authorization','')
        if not auth.startswith('Bearer ') or len(auth) > 512:
            return jsonify(ok=False, erro='Dispositivo não autorizado. Conecte novamente.'),401
        with database(cfg) as db:
            row = db.execute('SELECT id FROM devices WHERE token_hash=? AND revoked=0', (digest(auth[7:]),)).fetchone()
        if row is None: return jsonify(ok=False, erro='Dispositivo não autorizado. Conecte novamente.'),401

    @app.after_request
    def private_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/tela/rtc/config')
    def turn_credentials():
        turn = cfg.get('turn', {})
        if not turn.get('secret'):
            return jsonify(ok=True, ice_servers=[])
        username = f"{int(time.time())+3600}:{secrets.token_hex(8)}"
        credential = base64.b64encode(hmac.new(turn['secret'].encode(),username.encode(),hashlib.sha1).digest()).decode()
        host = turn['host']
        return jsonify(ok=True, ice_servers=[{'urls':[f'stun:{host}:3478']},
            {'urls':[f'turn:{host}:3478?transport=udp',f'turn:{host}:3478?transport=tcp'],
             'username':username,'credential':credential}])

    @app.post('/pair/claim')
    def claim():
        if request.content_length and request.content_length > 2048: return jsonify(erro='Pedido grande demais'),413
        data = request.get_json(silent=True) or {}
        if not isinstance(data,dict): return jsonify(erro='Pedido inválido'),400
        code = str(data.get('code','')).upper().replace('-','').replace(' ','')
        label = str(data.get('label','Celular'))[:80]
        token = secrets.token_urlsafe(32)
        device_id = secrets.token_hex(8)
        with database(cfg) as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            ip = request.remote_addr or 'unknown'  # Caddy é a única origem do socket.
            db.execute('DELETE FROM attempts WHERE at < ?', (now-60,))
            if db.execute('SELECT COUNT(*) FROM attempts WHERE ip=?',(ip,)).fetchone()[0] >= 10:
                return jsonify(erro='Aguarde um minuto antes de tentar novamente.'),429
            db.execute('INSERT INTO attempts VALUES(?,?)',(ip,now))
            row = db.execute('SELECT * FROM pairing WHERE code_hash=? AND used=0 AND expires>?',(digest(code),now)).fetchone()
            if row is None: return jsonify(erro='Código inválido, expirado ou já utilizado.'),400
            db.execute('UPDATE pairing SET used=1 WHERE code_hash=?',(digest(code),))
            db.execute('INSERT INTO devices VALUES(?,?,?,?,0)',(device_id,label,digest(token),now))
        return jsonify(ok=True,device_id=device_id,token=token,base=cfg['public_base'],inference_base=cfg['public_base']+'/v1')

    @app.post('/admin/uploads/<sha>/<int:part>')
    def upload_part(sha,part):
        if not re.fullmatch('[0-9a-f]{64}',sha) or not 0 <= part < 64:
            return jsonify(erro='Upload inválido'),400
        if request.content_length is None or not 0 < request.content_length <= 8*1024*1024:
            return jsonify(erro='Parte grande demais ou vazia'),413
        folder=Path(cfg['data_dir'])/'incoming'/sha
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=folder/('.part-'+secrets.token_hex(8))
        try:
            with temporary.open('wb') as output:
                output.write(request.get_data())
            temporary.chmod(0o600)
            os.replace(temporary,folder/str(part))
        finally: temporary.unlink(missing_ok=True)
        return jsonify(ok=True)

    @app.get('/connection/status')
    def connection():
        try:
            result=requests.get(cfg['pc_url'].rstrip('/')+'/pc/status',headers={'Authorization':'Bearer '+cfg['pc_token']},timeout=(2,3))
            online=result.ok
            result.close()
        except requests.RequestException: online=False
        return jsonify(ok=True,cloud_online=True,pc_online=online)

    @app.get('/gateway/endpoint')
    def endpoint():
        return jsonify(ok=True,url=cfg['public_base'],atualizado_em=cfg.get('created_at',0),tipo='oracle')

    @app.get('/android/update')
    def update():
        try:
            meta=json.loads((Path(cfg['data_dir'])/'updates/latest.json').read_text())
            path=Path(cfg['data_dir'])/'updates'/f"emily-{int(meta['version_code'])}.apk"
            if not path.is_file() or path.stat().st_size != int(meta['size']): raise ValueError()
            return jsonify(ok=True,**meta)
        except (OSError,ValueError,KeyError,TypeError): return jsonify(ok=False,erro='Nenhuma atualização publicada.'),404

    @app.get('/android/update/apk')
    def apk():
        try:
            version=request.args.get('version')
            if version is None: version=json.loads((Path(cfg['data_dir'])/'updates/latest.json').read_text())['version_code']
            version=int(version)
            if version <= 0: raise ValueError()
            path=Path(cfg['data_dir'])/'updates'/f'emily-{version}.apk'
            if not path.is_file() or path.is_symlink(): raise ValueError()
            return send_file(path,mimetype='application/vnd.android.package-archive',conditional=True,download_name='emily-update.apk')
        except (OSError,ValueError,KeyError,TypeError): return jsonify(ok=False,erro='Versão não disponível.'),404

    def runtime_proxy(route):
        if not cfg.get('runtime_url'):
            return jsonify(erro='Serviço da nuvem não configurado'),503
        try:
            upstream=requests.post(cfg['runtime_url'].rstrip('/')+'/'+route,
                headers={'Authorization':'Bearer '+cfg['upload_key'], 'Content-Type':'application/json'},
                data=request.get_data(), timeout=(3,600 if route=='context' else 90), allow_redirects=False)
            try:
                return Response(upstream.content,status=upstream.status_code,
                    content_type=upstream.headers.get('Content-Type','application/json'))
            finally: upstream.close()
        except requests.RequestException:
            return jsonify(erro='Serviço da nuvem reconectando. Tente novamente.'),503

    @app.get('/llm/usage')
    @app.post('/admin/llm/usage')
    def model_usage():
        return runtime_proxy('usage')

    @app.post('/llm/context')
    @app.post('/admin/llm/context')
    def model_context():
        if request.content_length and request.content_length>12*1024*1024:
            return jsonify(ok=False,error='Contexto grande demais; original preservado.'),413
        return runtime_proxy('context')

    @app.post('/llm/busca')
    def cloud_search():
        if request.content_length and request.content_length > 4096:
            return jsonify(erro='Consulta grande demais'),413
        return runtime_proxy('search')

    @app.post('/admin/discord/rpc')
    def discord_rpc():
        if request.content_length and request.content_length > 256*1024:
            return jsonify(erro='Pedido grande demais'),413
        return runtime_proxy('discord/rpc')

    @app.route('/<path:path>', methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'])
    def proxy(path):
        if '..' in path.split('/') or path.startswith('/') or path.startswith(('pair/','admin/')):
            return jsonify(erro='Rota não permitida'),404
        if path.startswith('v1/'):
            allowed=(path=='v1/models' and request.method=='GET') or (path=='v1/chat/completions' and request.method=='POST')
            if not allowed: return jsonify(erro='Rota não permitida'),404
            url=cfg['omni_url'].rstrip('/')+'/'+path[3:]
            key=cfg['omni_key']
        else:
            url=cfg['pc_url'].rstrip('/')+'/'+path
            key=cfg['pc_token']
        # Não envie uma ação mutável para um túnel que só aceita TCP mas já
        # perdeu o PC. A consulta é autenticada e nunca repete o comando.
        if path == 'pc/action':
            try:
                with requests.get(cfg['pc_url'].rstrip('/')+'/pc/status',
                        headers={'Authorization':'Bearer '+cfg['pc_token']},
                        timeout=(1,2), allow_redirects=False) as health:
                    if health.status_code != 200:
                        return jsonify(ok=False,erro='Conexão com o PC indisponível. Nenhuma ação foi enviada.'),503
            except requests.RequestException:
                return jsonify(ok=False,erro='Conexão com o PC indisponível. Nenhuma ação foi enviada.'),503
        headers={k:v for k,v in request.headers if k.lower() in {'content-type','range','if-none-match','if-modified-since'}}
        if not public_viewer(): headers['Authorization']='Bearer '+key
        try:
            upstream=requests.request(request.method,url,params=list(request.args.items(multi=True)),
                data=request.get_data(),headers=headers,stream=True,timeout=(2,5 if path.endswith("/status") else 240),allow_redirects=False)
        except requests.RequestException:
            return jsonify(ok=False,erro='PC desconectado. Ligue o PC e aguarde a conexão automática.' if not path.startswith('v1/') else 'Modelo na nuvem indisponível.'),503
        response_headers={k:v for k,v in upstream.headers.items() if k.lower() in {'content-type','content-range','accept-ranges','etag','last-modified'} or k.lower().startswith('x-emily-')}
        def chunks():
            try:
                if upstream.headers.get('Content-Type','').lower().startswith('text/event-stream'):
                    # requests preenche chunks de 8 KiB antes de entregá-los se o
                    # upstream não usa Transfer-Encoding: chunked. SSE precisa
                    # liberar cada linha, inclusive a vazia que fecha o evento.
                    for line in upstream.iter_lines(chunk_size=1):
                        yield line + b'\n'
                else:
                    yield from upstream.iter_content(chunk_size=8192)
            finally: upstream.close()
        return Response(stream_with_context(chunks()),status=upstream.status_code,headers=response_headers)
    @app.post('/music/identify')
    def identify_music():
        import sys
        recognition_root = Path(__file__).resolve().parent.parent
        if not (recognition_root/'music_identify.py').is_file():
            recognition_root = Path.home()/'emily-runtime-cloud/current'
        if str(recognition_root) not in sys.path:
            sys.path.insert(0, str(recognition_root))
        import music_identify
        import wave
        if request.content_length is None or not 0 < request.content_length <= music_identify.MAX_BYTES:
            return jsonify(ok=False, mensagem='Gravação deve ter até 3 MiB'), 413
        try:
            return jsonify(music_identify.recognize(request.get_data(), request.args.get('audd') == '1'))
        except (ValueError, wave.Error, EOFError):
            return jsonify(ok=False, mensagem='Gravação WAV inválida'), 400

    return app

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['pair','list','revoke'])
    parser.add_argument('--id')
    args=parser.parse_args();cfg=load_config()
    if args.command=='pair': print(make_pair(cfg))
    elif args.command=='list':
        with database(cfg) as db:
            print(json.dumps([dict(r) for r in db.execute('SELECT id,label,created,revoked FROM devices')],ensure_ascii=False))
    elif args.command=='revoke':
        if not args.id: parser.error('--id é obrigatório')
        with database(cfg) as db: db.execute('UPDATE devices SET revoked=1 WHERE id=?',(args.id,))
        print('Dispositivo revogado.')
