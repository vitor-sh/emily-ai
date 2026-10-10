"""Cartão isolado: estados, escolha de versão e ações sem tocar na biblioteca real."""
from pathlib import Path
from playwright.sync_api import sync_playwright


def test_recognition_card_states_and_actions():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 640})
            page.add_init_script("""window.calls=[];window.sample={fase:'ouvindo',fonte:'sistema',segundos:3,total:12};
            window.pywebview={api:{
              music_identify_state:async()=>window.sample,
              music_identify_start:async(...a)=>{window.calls.push(['start',...a]);return true},
              music_identify_cancel:async()=>window.calls.push(['cancel']),
              playlist_buscar_preview:async q=>({resultados:[{video_id:'dQw4w9WgXcQ',titulo:'Versão escolhida',thumb:''}]}),
              playlist_adicionar:async(...a)=>{window.calls.push(['save',...a]);return true},
              music_identify_play:async m=>{window.calls.push(['play',m.video_id]);return true},
              music_identify_youtube:async()=>window.calls.push(['youtube'])
              ,music_identify_player:async()=>window.mini||{},
              music_identify_control:async a=>{window.calls.push(['control',a]);if(a==='parar')window.mini={};}
            }};""")
            page.goto((Path(__file__).resolve().parents[1]/'web/music-identify.html').as_uri())
            page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
            assert page.locator('#motion').is_visible()
            assert '3/12' in page.locator('#message').inner_text()
            page.locator('#cancel').click()
            page.evaluate("""window.sample={fase:'resultado',musica:{titulo:'<b>Song</b>',artista:'Artist',consulta:'Artist Song',capa:''}};poll()""")
            assert page.locator('#title').inner_text()=='<b>Song</b>'
            assert page.locator('#title b').count()==0
            assert not page.locator('#cover').is_visible()
            assert not page.locator('#motion').is_visible()
            page.locator('#save').click()
            page.locator('#matches button').click()
            assert page.locator('#feedback').inner_text()=='Salva na playlist atual.'
            page.locator('#listen').click()
            page.locator('#matches button').click()
            page.locator('#youtube').click()
            assert page.evaluate("calls.map(x=>x[0])")==['cancel','save','play','youtube']
            page.evaluate("window.mini={titulo:'Prévia',tocando:true,posicao:65};pollMini()")
            assert page.locator('#mini').is_visible()
            assert page.locator('#mini-status').inner_text()=='Reproduzindo · 1:05'
            page.locator('#mini-toggle').click()
            page.locator('#mini-stop').click()
            assert not page.locator('#mini').is_visible()
            assert page.evaluate('calls.slice(-2)')==[['control','alternar'],['control','parar']]
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path='/tmp/emily-identify-card-test.png')
        finally:
            browser.close()
