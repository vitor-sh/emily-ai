"""A interface real empacotada no APK, em viewport móvel; ponte nativa simulada."""
import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('width,height',[(320,640),(390,844),(411,855)])
def test_mobile_local_readonly_controls_and_offline(width,height):
    root=ROOT/'EmilyAPP2/app/src/main/assets/music'
    local='local_'+'a'*64
    library={'playlists':{'default':{'musicas':[{'video_id':'bbbbbbbbbbb','titulo':'Online','thumb':'','adicionada':1}],'foto':''},'__locais__':{'musicas':[{'video_id':local,'titulo':'MP3 local','thumb':'','adicionada':1}],'foto':'','readonly':True}},'ativa':'default','favoritos':{}}
    library['playlists']['Viagem']={'musicas':[],'foto':''}
    offline={'faixas':{local:{'estado':'pronto','local':True}},'online':True,'settings':{'revision':'initial','loop':1,'shuffle':False,'volume':100}}
    calls=[]
    def bridge(m,a):
        calls.append((m,a))
        if m=='playlist_geral':return library
        if m=='music_offline_estado':return offline
        if m=='playlist_buscar_preview':return {'resultados':[{'video_id':'ccccccccccc','titulo':'Resultado avulso','thumb':''}]}
        if m=='player_estado':return {'loop':1,'volume':100,'shuffle':False}
        if m=='music_copiar':
            n,track=a
            if all(t['video_id']!=track['video_id'] for t in library['playlists'][n]['musicas']):library['playlists'][n]['musicas'].append(track)
            return True
        return True
    with sync_playwright() as pw:
        b=pw.chromium.launch(headless=True);p=b.new_page(viewport={'width':width,'height':height},is_mobile=True);errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
        p.expose_function('musicBridge',bridge)
        p.add_init_script("window.EmilyAndroid={call(id,m,a){musicBridge(m,JSON.parse(a)).then(v=>musicReply(Number(id),v,null));},back(){},permission(){},folder(){}}")
        p.route('https://appassets.androidplatform.net/assets/music/**',lambda r:r.fulfill(path=str(root/r.request.url.rsplit('/',1)[-1])))
        p.goto('https://appassets.androidplatform.net/assets/music/index.html');p.wait_for_selector('.music-card')
        # Catálogo maior: carrossel e faixa de playlists devem rolar na horizontal.
        p.evaluate("""() => {
            for(let i=0;i<6;i++) _playlistsGeral.playlists['test'+i]={foto:'',musicas:[]};
            EmilyMusic.sidebar();EmilyMusic.render();
        }""")
        for selector in ['#music-home .music-cards']:
            assert p.locator(selector).first.evaluate("el=>el.scrollWidth>el.clientWidth")
            p.locator(selector).first.evaluate("el=>el.scrollLeft=100")
            assert p.locator(selector).first.evaluate("el=>el.scrollLeft")>0
        assert p.evaluate("document.querySelector('.emusic').scrollWidth")<=width
        p.locator('#music-home .music-card').filter(has_text='Minha seleção').click()
        download=p.locator('#pl-lista .music-download')
        assert download.is_visible()
        assert download.evaluate("el=>el.parentElement.classList.contains('music-track')")
        download.click();assert any(m=='music_offline_baixar' for m,a in calls)
        p.locator('#pl-lista .mobile-track-more').click()
        assert p.locator('#mobile-track-options').evaluate('el=>el.open')
        assert p.locator('#mobile-track-options button[title="Curtir"]').is_visible()
        assert p.locator('#mobile-track-options').evaluate("el=>{const b=el.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth&&b.bottom<=innerHeight;}")
        p.screenshot(path=f'/tmp/emily-music31-menu-{width}.png')
        assert p.evaluate('MusicMobile.back()') is True
        assert not p.locator('#mobile-track-options').evaluate('el=>el.open')
        p.locator('[data-mobile-tab="biblioteca"]').click()
        p.locator('#music-home .music-card').filter(has_text='Músicas locais').click()
        assert p.locator('#pl-info').get_by_text('Editar',exact=True).count()==0
        assert p.locator('#pl-lista .music-download').count()==0
        assert p.locator('#pl-lista button[title="Remover desta playlist"]').count()==0
        assert p.locator('#pl-lista button[title="Mover para cima"]').count()==0
        p.locator('#pl-lista .mobile-track-more').click()
        p.locator('#mobile-track-options button[title="Adicionar a uma playlist ou às curtidas"]').click()
        assert p.locator('.music-add-menu').get_by_text('+ Músicas locais',exact=True).count()==0
        p.locator('.music-add-menu').get_by_text('+ Minha seleção',exact=True).click()
        p.wait_for_function("_playlistsGeral.playlists.default.musicas.length===2")
        assert p.locator('.music-add-menu').get_by_text('✓ Minha seleção',exact=True).is_disabled()
        p.locator('.music-add-menu').get_by_text('Fechar',exact=True).click()
        p.locator('#pl-lista .music-track-main').click()
        p.wait_for_function('Player._faixaAtual!=null')
        assert any(m=='media_play' for m,a in calls),'Reprodução precisa ser nativa'
        p.evaluate("musicState({queue:[{video_id:'"+local+"',titulo:'MP3 local',thumb:''}],indice:0,video_id:'"+local+"',playing:true,duracao:180,posicao:32})")
        # Ticks de progresso não recriam a fila, capa ou controles.
        result=p.evaluate("""() => {
            let paints=0;
            const original=Player._pintaBarra;
            Player._pintaBarra=()=>{paints++;original.call(Player);};
            for(let i=0;i<12;i++) musicState({indice:0,video_id:Player._faixaAtual.video_id,playing:true,buffering:false,duracao:180,posicao:33+i});
            Player._pintaBarra=original;
            return {paints,queue:Player.playlist.length,title:Player._faixaAtual.titulo,time:Player.player.getCurrentTime()};
        }""")
        assert result=={'paints':1,'queue':1,'title':'MP3 local','time':44},result
        p.wait_for_timeout(500)
        p.locator('#mobile-mini-open').click()
        assert p.locator('#mobile-now').is_visible()
        p.wait_for_timeout(300)
        p.evaluate("Player._faixaAtual.titulo='Ronova Boss Theme - Genshin Impact OST (Full Version Complete) '+ 'LongTitle'.repeat(12);Player._pintaBarra();MusicMobile.update()")
        for selector in ['#player-faixa','#player-titulo','#player-thumb','#player-seek','#player-loop','#player-shuffle']:
            assert p.locator(selector).evaluate("el=>{const b=el.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth;}")
        assert p.locator('#mobile-now').evaluate('el=>el.scrollWidth<=el.clientWidth')
        # Nome enorme pode precisar de rolagem vertical, sem cortar controles.
        p.locator('#player-play').scroll_into_view_if_needed()
        p.screenshot(path=f'/tmp/emily-music31-full-{width}.png')
        bounds=p.locator('#player-play').bounding_box();assert bounds['y']+bounds['height']<=height
        p.locator('#player-shuffle').click();assert any(m=='media_options' and a[0]['shuffle'] for m,a in calls)
        p.locator('#player-loop').click();assert any(m=='media_options' and a[0]['loop']==2 for m,a in calls)
        p.locator('#player-seek').fill('50');p.locator('#player-seek').dispatch_event('change')
        assert any(m=='media_seek' for m,a in calls)
        p.locator('#mobile-now-add').click()
        assert p.locator('dialog.music-add-menu').evaluate('el=>el.open&&el.matches(":modal")')
        action=p.locator('.music-add-menu').get_by_text('+ Viagem',exact=True)
        assert action.evaluate("el=>{const b=el.getBoundingClientRect();return el.contains(document.elementFromPoint(b.left+b.width/2,b.top+b.height/2));}"), 'Adicionar deve estar acima da tela ampliada'
        action.click()
        p.wait_for_function("_playlistsGeral.playlists.Viagem.musicas.length===1")
        assert p.locator('.music-add-menu').get_by_text('✓ Viagem',exact=True).is_disabled()
        assert p.locator('#mobile-now').is_visible()
        p.locator('.music-add-menu').get_by_text('Fechar',exact=True).click()
        p.screenshot(path='/tmp/emily-music-android-fullplayer.png')
        assert p.evaluate('MusicMobile.back()') is True
        assert p.locator('#mobile-now').is_hidden()
        # Alterações da notificação chegam sem perder a fila ou reabrir a tela.
        p.evaluate("musicState({indice:0,video_id:Player._faixaAtual.video_id,playing:true,buffering:false,duracao:180,posicao:44,loop:0,shuffle:false})")
        assert p.evaluate('Player.loop===0&&!Player.shuffle')
        p.evaluate('EmilyMusic.pollOffline(true)')
        p.wait_for_function('!EmilyMusic.polling')
        assert p.evaluate('Player.loop===0&&!Player.shuffle'), 'Configuração antiga não desfaz os modos da notificação'
        offline['settings']={'revision':'external','loop':2,'shuffle':True,'volume':100}
        p.evaluate('EmilyMusic.pollOffline(true)');p.wait_for_function('!EmilyMusic.polling')
        assert p.evaluate('Player.loop===2&&Player.shuffle'), 'Alteração nova sincronizada deve chegar à sessão'
        p.locator('[data-mobile-tab="biblioteca"]').click()
        assert p.locator('#music-home .music-card').filter(has_text='Músicas locais').is_visible()
        assert p.evaluate("document.querySelector('.emusic').scrollWidth")<=width
        p.screenshot(path='/tmp/emily-music-android-validated.png')
        offline['online']=False;p.evaluate('EmilyMusic.pollOffline(true)');p.wait_for_function('document.querySelector("#pl-query").disabled')
        p.locator('#music-home .music-card').filter(has_text='Minha seleção').click()
        assert p.locator('#pl-lista .indisponivel').count()==1
        assert p.locator('#pl-lista .music-track-main').filter(has_text='MP3 local').is_enabled()
        offline['online']=True;p.evaluate('EmilyMusic.pollOffline(true)');p.wait_for_function('!document.querySelector("#pl-query").disabled')
        p.locator('#pl-lista .mobile-track-more').first.click()
        assert p.locator('#mobile-mini').is_visible()
        action=p.locator('#mobile-track-options button[title="Curtir"]').first
        assert action.evaluate("el=>{const b=el.getBoundingClientRect();return el.contains(document.elementFromPoint(b.left+b.width/2,b.top+b.height/2));}"), 'Menu deve ficar acima do mini player'
        p.screenshot(path=f'/tmp/emily-music31-menu-playing-{width}.png')
        assert p.evaluate('MusicMobile.back()') is True
        assert p.locator('#pl-lista>.music-track>.music-download').is_visible()
        p.evaluate("EmilyMusic.view='__locais__';EmilyMusic.go('busca')")
        assert p.locator('.music-search-add').first.is_disabled(), 'Destino dos recentes deve ignorar a biblioteca local somente leitura'
        p.evaluate("EmilyMusic.search('Minha busca recente')")
        p.wait_for_selector('.music-search-play')
        p.screenshot(path=f'/tmp/emily-music36-search-{width}.png')
        count=sum(len(v['musicas']) for v in library['playlists'].values())
        p.locator('.music-search-play').first.click()
        assert any(m=='media_play' and a[0][0]['video_id']=='ccccccccccc' for m,a in calls)
        assert p.evaluate("Player._playlistAtivaSalva==='__avulsa__'")
        p.evaluate("EmilyMusic.go('fila')")
        assert p.locator('#music-queue button[title="Remover desta playlist"]').count()==0
        p.locator('#music-queue .music-track-main').click()
        p.evaluate("EmilyMusic.go('busca')")
        assert sum(len(v['musicas']) for v in library['playlists'].values())==count,'Ouvir não adiciona à biblioteca'
        p.evaluate("EmilyMusic.favorite(Player._faixaAtual,true)")
        p.wait_for_function("_playlistsGeral.playlists.default.musicas.some(m=>m.video_id==='ccccccccccc')")
        assert p.evaluate("Player._playlistAtivaSalva==='__avulsa__'&&Player.playlist[0].video_id==='ccccccccccc'"),'Curtir salva a faixa sem trocar a reprodução avulsa'
        p.locator('#pl-query').fill('')
        assert p.locator('.music-query-open').get_by_text('↶  Minha busca recente',exact=True).is_visible()
        assert p.locator('#pl-preview').get_by_text('Adicionadas recentemente',exact=True).is_visible()
        p.reload();p.wait_for_selector('.music-card')
        p.locator('[data-mobile-tab="busca"]').click()
        assert p.locator('.music-query-open').count()==1,'Histórico persiste sem repetir a busca online'
        assert sum(1 for m,a in calls if m=='playlist_buscar_preview')==1
        p.locator('.music-clear-history').click()
        assert p.locator('.music-query-open').count()==0
        result=p.evaluate("""async()=>{
          const original=tenta,waiting={};
          tenta=(method,...args)=>method==='playlist_buscar_preview'?new Promise(resolve=>waiting[args[0]]=resolve):original(method,...args);
          try{
            const first=EmilyMusic.search('old'),second=EmilyMusic.search('new');
            waiting.new({resultados:[{video_id:'ddddddddddd',titulo:'Nova resposta',thumb:''}]});await second;
            waiting.old({resultados:[{video_id:'eeeeeeeeeee',titulo:'Resposta antiga',thumb:''}]});await first;
            return EmilyMusic.searchResults[0].titulo;
          }finally{tenta=original;}
        }""")
        assert result=='Nova resposta','Resultado antigo não substitui a busca nova'
        assert not errors,errors
        b.close()
