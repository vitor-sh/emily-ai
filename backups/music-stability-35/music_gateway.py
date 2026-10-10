"""Rotas privadas do Emily Music, disponíveis mesmo com a janela do PC fechada."""
import hashlib, os, tempfile, subprocess
from pathlib import Path
from flask import request, jsonify, send_file

def register(app, authorize):
    @app.route('/music/sync',methods=['POST'])
    def sync():
        denied=authorize()
        if denied:return denied
        if request.content_length is None or request.content_length>16*1024*1024:return jsonify(erro='Biblioteca grande demais'),413
        try:
            import music_sync
            body=request.get_json(silent=True) or {}
            return jsonify(ok=True,campos=music_sync.exchange(body.get('campos')))
        except (ValueError,TypeError,KeyError):return jsonify(erro='Biblioteca inválida'),400

    @app.route('/music/search',methods=['POST'])
    def search():
        denied=authorize()
        if denied:return denied
        import music_player
        query=str((request.get_json(silent=True) or {}).get('query',''))[:300]
        return jsonify(resultados=music_player.buscar_preview(query))

    @app.route('/music/lyrics',methods=['POST'])
    def lyrics():
        denied=authorize()
        if denied:return denied
        import music_letras
        return jsonify(music_letras.buscar(str((request.get_json(silent=True) or {}).get('query',''))[:300]))

    @app.route('/music/files/<vid>',methods=['PUT','GET','HEAD'])
    def audio(vid):
        denied=authorize()
        if denied:return denied
        import music_offline as mo
        if not mo.valido(vid) or not vid.startswith('local_'):return jsonify(erro='ID inválido'),400
        if request.method!='PUT':
            f=mo.arquivo(vid)
            if not f:return jsonify(erro='Aguardando transferência do celular'),404
            return send_file(f,mimetype='audio/mpeg',conditional=True,etag=vid)
        size=request.content_length
        if size is None or not 0<size<=128*1024*1024:return jsonify(erro='MP3 deve ter até 128 MB'),413
        root=mo.pasta();root.mkdir(parents=True,exist_ok=True);tmp=None
        try:
            with tempfile.NamedTemporaryFile(dir=root,delete=False) as f:
                tmp=Path(f.name);h=hashlib.sha256();total=0
                while chunk:=request.stream.read(65536):
                    total+=len(chunk)
                    if total>size:raise ValueError('Tamanho inválido')
                    f.write(chunk);h.update(chunk)
            if h.hexdigest()!=vid[6:] or total!=size:raise ValueError('Hash inválido')
            result=subprocess.run(['ffprobe','-v','error','-show_entries','format=format_name','-of','default=nw=1:nk=1',str(tmp)],capture_output=True,timeout=15)
            if result.returncode or b'mp3' not in result.stdout:raise ValueError('MP3 inválido')
            mo.importar_local(vid,tmp)
            return jsonify(ok=True)
        except (ValueError,subprocess.SubprocessError):return jsonify(erro='Arquivo de áudio inválido'),400
        finally:
            if tmp:tmp.unlink(missing_ok=True)
