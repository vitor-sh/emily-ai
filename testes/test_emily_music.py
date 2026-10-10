import json
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import music_player as mp
import music_letras as letras
ROOT=Path(__file__).resolve().parents[1]


def test_organizar_nao_perde_musicas_com_estado_antigo(tmp_path,monkeypatch):
    monkeypatch.setattr(mp,'ARQUIVO',tmp_path/'musicas.json');monkeypatch.setattr(mp,'_cache',None)
    for i in ['aaaaaaaaaaa','bbbbbbbbbbb']:mp.adicionar({'video_id':i,'titulo':i})
    assert not mp.organizar('default',['aaaaaaaaaaa'])
    assert not mp.organizar('default',['aaaaaaaaaaa','aaaaaaaaaaa'])
    assert mp.organizar('default',['bbbbbbbbbbb','aaaaaaaaaaa'])
    assert [m['video_id'] for m in mp.listar()]==['bbbbbbbbbbb','aaaaaaaaaaa']


def test_letras_cache_erro_e_texto_nao_viram_html(monkeypatch):
    letras._buscar.cache_clear();calls=[]
    class Resp:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self,*a):return json.dumps([{'trackName':'Canção','artistName':'Artista','syncedLyrics':'[00:01.00]<b>texto</b>'}]).encode()
    def request(req,timeout):calls.append(req.full_url);assert timeout==10;return Resp()
    monkeypatch.setattr(letras.urllib.request,'urlopen',request)
    a=letras.buscar('Canção Artista');a['resultados'][0]['titulo']='alterado'
    assert letras.buscar('Canção Artista')['resultados'][0]['titulo']=='Canção'
    assert len(calls)==1 and '%C3%A7' in calls[0]
    assert letras.buscar('')['erro']
    letras._buscar.cache_clear()
    monkeypatch.setattr(letras.urllib.request,'urlopen',lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
    assert letras.buscar('falha')['erro']


def test_biblioteca_fila_controles_letras_e_layout(tmp_path,monkeypatch):
    monkeypatch.setattr(mp,'ARQUIVO',tmp_path/'musicas.json');monkeypatch.setattr(mp,'_cache',None)
    for i,t in [('aaaaaaaaaaa','Primeira faixa'),('bbbbbbbbbbb','Outra faixa')]:mp.adicionar({'video_id':i,'titulo':t,'thumb':'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg'})
    mp.criar_playlist('Noite');mp.adicionar({'video_id':'ccccccccccc','titulo':'Música da noite'},'Noite')
    offline={'faixas':{},'online':True}
    def bridge(method,args):
        actions={'playlist_adicionar':lambda i,t,f:mp.adicionar({'video_id':i,'titulo':t,'thumb':f}),'playlist_geral':mp.listar_playlists,'playlist':mp.listar,'playlist_selecionar':mp.selecionar_playlist,'playlist_favoritar':mp.favoritar,'playlist_remover':mp.remover,'music_remover':lambda n,i:mp.remover(i,n),'music_organizar':mp.organizar,'music_copiar':lambda n,m:mp.adicionar(m,n),'player_salvar_estado':lambda d:mp.salvar_estado(**d),'player_estado':mp.estado,'playlist_criar':lambda n,f='':{'ok':mp.criar_playlist(n)},'playlist_foto':mp.definir_foto_playlist,'playlist_renomear':lambda a,b:{'ok':mp.renomear_playlist(a,b)}}
        if method=='music_offline_estado':return offline
        if method=='playlist_buscar_preview':return {'resultados':[{'video_id':'ddddddddddd','titulo':'Resultado '+args[0],'thumb':''}]}
        if method=='music_letras_buscar':return {'resultados':[{'titulo':'Teste','artista':'Artista','sincronizada':'[00:00.00]Primeira linha\n[00:10.00]Segunda linha','texto':''}]}
        return actions[method](*args)
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True);p=b.new_page(viewport={'width':1440,'height':1000});errors=[];p.on('pageerror',lambda e:errors.append(str(e)));p.expose_function('bridge',bridge)
        import re
        html=re.sub(r'<script\b[^>]*>.*?</script>','', (ROOT/'web/index.html').read_text(),flags=re.S)
        html=re.sub(r'<link\b[^>]*>','',html);p.set_content(html)
        p.add_style_tag(path=ROOT/'web/estilo.css');p.add_style_tag(path=ROOT/'web/emily-music.css')
        p.add_script_tag(content='''const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const tenta=(m,...a)=>window.bridge(m,a);const toast=()=>{};const ICO={};const svg=()=>'';''')
        source=(ROOT/'web/app.js').read_text();p.add_script_tag(content=source[source.index('const Player = {'):source.index('// Liga junto com os outros botões no boot.')])
        p.add_script_tag(path=ROOT/'web/music-offline.js');p.add_script_tag(path=ROOT/'web/emily-music.js');p.evaluate("document.body.classList.remove('carregando');ligarPlayer()")
        p.evaluate('''Player.pronto=true;Player._carregarIframe=()=>{};Player.player={tempo:0,volume:100,id:'',getVideoData(){return {video_id:this.id};},loadVideoById(id){this.id=id;},setVolume(v){this.volume=v;},mute(){this.muted=true;},unMute(){this.muted=false;},isMuted(){return !!this.muted;},playVideo(){},pauseVideo(){},getCurrentTime(){return this.tempo;},getDuration(){return 120;},seekTo(t){this.tempo=t;},stopVideo(){}};''')
        p.click('#btn-music');p.wait_for_selector('.music-card');assert p.locator('#modal-player-titulo').inner_text()=='Emily Music'
        p.locator('.music-card').filter(has_text='Minha seleção').click();p.locator('#pl-lista .music-track-main').first.click();p.wait_for_function("Player._faixaAtual?.video_id==='aaaaaaaaaaa'")
        p.evaluate('Player.definirVolume(42);Player.player.tempo=37')
        assert p.input_value('#player-vol')=='42' and p.evaluate('Player.player.volume')==42
        p.locator('.music-sidebar-open').filter(has_text='Noite').click()
        assert p.evaluate('Player.player.id')=='aaaaaaaaaaa' and p.evaluate('Player.player.tempo')==37
        assert p.locator('#pl-info').inner_text().startswith('PLAYLIST\nNoite')
        p.locator('#pl-lista .music-track-action').first.click();p.wait_for_function("!!_playlistsGeral.favoritos.ccccccccccc")
        p.click('[data-music-tab=favoritas]');assert p.locator('#pl-lista .music-track').count()==1
        p.click('[data-music-tab=fila]');assert p.locator('#music-queue .music-track').count()==2
        p.click('#player-next');p.wait_for_function("Player._faixaAtual.video_id==='bbbbbbbbbbb'")
        p.fill('#pl-query','Um som');p.locator('#pl-form').evaluate('(el)=>el.requestSubmit()');p.wait_for_selector('.music-search-row')
        p.select_option('.music-search-target','Noite');p.click('.music-search-row .music-search-add');p.wait_for_function("_playlistsGeral.playlists.Noite.musicas.length===2")
        assert p.evaluate('Player.player.id')=='bbbbbbbbbbb'
        p.click('[data-music-tab=letras]');p.fill('#music-lyrics-query','Teste');p.locator('#music-lyrics-form').evaluate('(el)=>el.requestSubmit()');p.wait_for_selector('.music-lyric-result');p.click('.music-lyric-result');p.evaluate('Player.player.tempo=12;EmilyMusic.tick()')
        assert p.locator('.music-lyric-line.atual').inner_text()=='Segunda linha'
        p.locator('.music-lyric-line').first.click();assert p.evaluate('Player.player.tempo')==0
        p.click('[data-music-tab=inicio]');p.screenshot(path='/tmp/emily-music-home.png')
        assert p.evaluate("document.querySelector('.emusic').scrollWidth<=document.querySelector('.emusic').clientWidth")
        p.set_viewport_size({'width':900,'height':720});assert p.evaluate("document.querySelector('.emusic').scrollWidth<=document.querySelector('.emusic').clientWidth")
        p.click('#pl-nova');p.fill('#pl-modal-nome','Trabalho');p.click('#pl-modal-confirmar');p.wait_for_function("!!_playlistsGeral.playlists.Trabalho")
        assert p.evaluate('Player.player.id')=='bbbbbbbbbbb'
        p.click('[data-music-tab=favoritas]');p.click('#pl-tocar-tudo');p.wait_for_function("Player._filaFavoritas && Player._faixaAtual.video_id==='ccccccccccc'")
        assert p.evaluate('Player.playlist.length')==1
        # Um resultado antigo nunca substitui a pesquisa mais recente.
        p.evaluate('''async()=>{const old=window.bridge;const pending={};window.bridge=(method,args)=>method==='playlist_buscar_preview'?new Promise(resolve=>pending[args[0]]=resolve):old(method,args);const a=EmilyMusic.search('antiga'),b=EmilyMusic.search('nova');pending.nova({resultados:[{video_id:'eeeeeeeeeee',titulo:'Resultado novo',thumb:''}]});await b;pending.antiga({resultados:[{video_id:'fffffffffff',titulo:'Resultado antigo',thumb:''}]});await a;window.bridge=old;}''')
        assert 'Resultado novo' in p.locator('#pl-preview').inner_text() and 'Resultado antigo' not in p.locator('#pl-preview').inner_text()
        # Estado da busca depende da playlist e persiste ao pesquisar novamente.
        p.select_option('.music-search-target','Noite');assert not p.locator('.music-search-row .music-search-add').is_disabled()
        p.click('.music-search-row .music-search-add');p.wait_for_function("_playlistsGeral.playlists.Noite.musicas.some(m=>m.video_id==='eeeeeeeeeee')")
        p.wait_for_function("document.querySelector('.music-search-row .music-search-add').disabled")
        p.select_option('.music-search-target','default');assert not p.locator('.music-search-row .music-search-add').is_disabled()
        p.select_option('.music-search-target','Noite');assert p.locator('.music-search-row .music-search-add').is_disabled()
        p.evaluate('EmilyMusic.renderSearch()');assert p.locator('.music-search-row .music-search-add').is_disabled()
        p.evaluate('EmilyMusic.view="default";EmilyMusic.go("playlist")')
        p.locator('#pl-lista button[aria-label="Adicionar a uma playlist ou às curtidas"]').first.click()
        assert p.locator('.music-add-menu button').filter(has_text='Minha seleção').is_disabled()
        p.keyboard.press('Escape');assert p.locator('.music-add-menu').count()==0 and p.locator('#modal-player').is_visible()
        # Áudio MP3 real, entregue localmente; nenhuma chamada ao YouTube.
        import subprocess
        mp3=tmp_path/'tone.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=4','-y',str(mp3)],check=True)
        import music_offline as mo,http.server,threading
        monkeypatch.setattr(mo,'pasta',lambda:tmp_path)
        mp3.rename(tmp_path/'aaaaaaaaaaa.mp3')
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):mo.servir(self)
            def log_message(self,*a):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=server.serve_forever,daemon=True).start()
        url=f'http://127.0.0.1:{server.server_port}/__emily_music/{mo.TOKEN}/aaaaaaaaaaa.mp3'
        offline.update(online=False,faixas={'aaaaaaaaaaa':{'estado':'pronto','url':url,'thumb':''}})
        p.evaluate('async()=>{await EmilyMusic.pollOffline();await EmilyMusic.play("default","aaaaaaaaaaa");}')
        p.wait_for_function('EmilyMusicAudio.localActive && EmilyMusicAudio.audio.currentTime>0.1')
        # Duas voltas reais: repetir faixa e fila offline com só uma baixada.
        p.evaluate('''() => {
            window.repeatLoads=0; window.repeatEnds=0;
            EmilyMusicAudio.audio.addEventListener('loadstart',()=>window.repeatLoads++);
            EmilyMusicAudio.audio.addEventListener('ended',()=>window.repeatEnds++);
            Player.loop=2; Player.player.seekTo(3.8);
        }''')
        p.wait_for_function('repeatEnds>=1 && EmilyMusicAudio.audio.currentTime>0.1 && EmilyMusicAudio.audio.currentTime<2')
        assert p.evaluate('repeatLoads')==0, 'Repetir não deve recarregar o arquivo'
        assert p.evaluate('EmilyMusicAudio.audio.src')==url
        p.evaluate('Player.loop=1;Player.player.seekTo(3.8)')
        p.wait_for_function('repeatEnds>=2 && EmilyMusicAudio.audio.currentTime>0.1 && EmilyMusicAudio.audio.currentTime<2')
        assert p.evaluate('repeatLoads')==0, 'Fila offline também reutiliza a faixa já aberta'
        p.evaluate('EmilyMusic.view="default";EmilyMusic.go("playlist")')
        assert p.locator('#pl-lista .indisponivel').count()==1
        assert p.locator('#pl-query').is_disabled()
        p.click('#player-play');assert p.evaluate('EmilyMusicAudio.audio.paused')
        p.evaluate('Player.player.seekTo(2)');p.wait_for_function('Player.player.getCurrentTime()>=2')
        offline['online']=True;p.evaluate('async()=>{await EmilyMusic.pollOffline(true);}')
        assert p.locator('#pl-query').is_enabled() and p.locator('#pl-lista .indisponivel').count()==0
        assert p.evaluate('EmilyMusicAudio.localActive'), 'Reconectar não troca a música local'
        p.evaluate('Player._persistir();Player.fechar()')
        mp.salvar_estado(playlist='default',video_id='aaaaaaaaaaa',indice=0,posicao=1)
        p.evaluate('async()=>{await Player.restaurar();}')
        p.wait_for_function('EmilyMusicAudio.audio.currentTime>=1')
        assert p.evaluate('EmilyMusicAudio.localActive && EmilyMusicAudio.audio.paused')
        p.click('#modal-player-fechar');assert p.locator('#modal-player').is_hidden();assert p.evaluate('Player._faixaAtual.video_id')=='aaaaaaaaaaa'
        assert not errors,errors
        server.shutdown();server.server_close();b.close()
