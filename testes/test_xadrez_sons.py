import base64
import io
import sys
import wave
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import xadrez_sons
from publicar_windows_codigo import arquivos_publicaveis


def wav():
    result = io.BytesIO()
    with wave.open(result, 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000)
        f.writeframes(b'\x10\x00' * 2400)
    return result.getvalue()


def test_persistencia_e_exclusao_dos_pacotes(tmp_path):
    p = tmp_path / 'sons_xadrez_pessoais/pacote.json'
    item = {'formato': 'wav', 'base64': base64.b64encode(wav()).decode()}
    assert xadrez_sons.acao('importar', {'arquivos': {'move': item}}, p)['personalizado']
    assert xadrez_sons.acao('ler', pasta=p)['arquivos']['move'] == item
    assert not xadrez_sons.acao('selecionar', {'personalizado': False}, p)['personalizado']
    assert xadrez_sons.acao('ler', pasta=p)['arquivos']
    (tmp_path/'main.py').write_text('')
    assert p not in arquivos_publicaveis(tmp_path)
    assert xadrez_sons.acao('limpar', pasta=p)['arquivos'] == {}
    with pytest.raises(ValueError):
        xadrez_sons.acao('importar', {'arquivos': {'../escape': item}}, p)
    with pytest.raises(ValueError):
        xadrez_sons.acao('importar', {'arquivos': {'move': {'formato': 'wav', 'base64': '!'}}}, p)
    assert xadrez_sons.acao('ler', pasta=p)['arquivos'] == {}


def test_audio_importado_real_fallback_toggle_reabertura_e_invalido(tmp_path):
    saved = tmp_path/'sons/pacote.json'
    def bridge(action, dados):
        assert action == 'sons'
        try:
            return xadrez_sons.acao(dados['operacao'], dados, saved)
        except ValueError as exc:
            return {'ok': False, 'erro': str(exc)}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.expose_function('bridge', bridge)
        def setup():
            page.set_content('<button id="wake">Som</button>')
            page.add_script_tag(content='window.pywebview={api:{xadrez_acao:bridge}};')
            page.add_script_tag(path=ROOT/'web/xadrez-audio.js')
            page.evaluate('''() => {
              window.lengths=[];
              const original=AudioContext.prototype.createBufferSource;
              AudioContext.prototype.createBufferSource=function(){
                const s=original.call(this),start=s.start.bind(s);
                s.start=(t)=>{lengths.push(s.buffer.duration);start(t);};return s;
              };
              document.querySelector('#wake').onclick=()=>EmilyChessAudio.wake();
            }''')
            page.click('#wake')
            page.wait_for_timeout(50)
        setup()
        raw = list(wav())
        page.evaluate('''async bytes=>{
          await EmilyChessAudio.carregar();
          await EmilyChessAudio.importar({move:new File([new Uint8Array(bytes)],'move.wav')});
          EmilyChessAudio.aoLance({flags:'n'},{isCheckmate:()=>false,isDraw:()=>false,isCheck:()=>false});
          EmilyChessAudio.aoLance({captured:'p'},{isCheckmate:()=>false,isDraw:()=>false,isCheck:()=>false});
        }''', raw)
        assert page.evaluate('lengths') == pytest.approx([.3, .15])
        page.evaluate('EmilyChessAudio.selecionar(false)')
        page.evaluate("EmilyChessAudio.aoLance({}, {isCheckmate:()=>false,isDraw:()=>false,isCheck:()=>false})")
        assert page.evaluate('lengths.at(-1)') == pytest.approx(.15)
        page.evaluate('EmilyChessAudio.selecionar(true)')
        # Fresh renderer/AudioContext restores from backend, independent of origin/port.
        page.reload();setup()
        page.evaluate('EmilyChessAudio.carregar()')
        assert page.evaluate('EmilyChessAudio.personalizado && EmilyChessAudio.tiposLocais.includes("move")')
        error = page.evaluate('''async()=>{
          try{await EmilyChessAudio.importar({move:new File(['not audio'],'move.wav')});return '';}
          catch(e){return e.message;}
        }''')
        assert 'Não consegui reproduzir' in error
        assert xadrez_sons.acao('ler', pasta=saved)['arquivos']['move']['base64'] == base64.b64encode(wav()).decode()
        page.evaluate('EmilyChessAudio.limpar()')
        assert page.evaluate('EmilyChessAudio.tiposLocais.length') == 0
        browser.close()


def test_interface_importa_e_alterna_sem_mudar_partida(tmp_path):
    saved = tmp_path/'sons.json'
    state = {'id': 'teste', 'revisao': 0, 'posicao': None, 'lance': {'estado': 'pronto'},
             'conversa': {'estado': 'pronto'}, 'mensagens': []}
    def bridge(action, dados):
        if action == 'sons':
            return xadrez_sons.acao(dados['operacao'], dados, saved)
        if action == 'salvar':
            state['posicao'] = dados['posicao'];state['revisao'] += 1
        return {'ok': True, 'estado': state}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1350, 'height': 740})
        errors = [];page.on('pageerror', lambda e: errors.append(str(e)))
        page.expose_function('bridge', bridge)
        page.set_content('<button id="btn-xadrez">Xadrez</button><button id="btn-navegador-interno">Navegador</button><div class="corpo"><main id="palco"></main><section id="xadrez-painel" hidden></section></div>')
        page.add_style_tag(content=':root{--bg:#1d1c19;--bg-raise:#25231f;--bg-hover:#302c27;--txt:#eee6da;--txt-2:#c3bdb4;--txt-3:#8b867e;--line:#ffffff15;--line-forte:#ffffff25;--acento:#c96442;--acento-fu:#c9644220;--sans:Arial,sans-serif;--serif:Georgia,serif}body{background:var(--bg)}')
        page.add_style_tag(path=ROOT/'web/xadrez.css')
        page.add_script_tag(content='window.pywebview={api:{xadrez_acao:bridge}};')
        for script in ('vendor/chess.js', 'xadrez-audio.js', 'xadrez.js'):
            page.add_script_tag(path=ROOT/'web'/script)
        page.click('#btn-xadrez')
        page.wait_for_selector('#xe-config-som')
        assert page.locator('#xe-sons-locais').is_disabled()
        page.click('#xe-config-som')
        page.locator('[data-som="move"]').set_input_files({'name': 'move.wav', 'mimeType': 'audio/wav', 'buffer': wav()})
        page.click('#xe-audio-salvar')
        page.wait_for_function('document.querySelector("#xe-modal").hidden')
        assert page.locator('#xe-sons-locais').get_attribute('aria-pressed') == 'true'
        page.click('#xe-sons-locais')
        page.wait_for_function('document.querySelector("#xe-sons-locais").getAttribute("aria-pressed")==="false"')
        assert not xadrez_sons.acao('ler', pasta=saved)['personalizado']
        page.click('#xe-config-som')
        page.screenshot(path='/tmp/emily-xadrez-sons-locais.png')
        bounds = page.locator('#xe-modal section').bounding_box()
        assert bounds['y'] >= 0 and bounds['y'] + bounds['height'] <= 740
        page.click('#xe-audio-limpar')
        page.wait_for_function('document.querySelector("#xe-modal").hidden')
        assert page.locator('#xe-sons-locais').is_disabled()
        assert state['posicao']['fatos']['meios_lances'] == 0
        assert errors == []
        browser.close()
