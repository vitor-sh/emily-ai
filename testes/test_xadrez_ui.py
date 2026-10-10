import json
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from xadrez_emily import Partida


def drag(page,source,target,button='left'):
    page.locator('#xe-board').scroll_into_view_if_needed()
    a=page.locator(f'[data-square="{source}"]').bounding_box();b=page.locator(f'[data-square="{target}"]').bounding_box()
    page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down(button=button)
    page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=8);page.mouse.up(button=button)


def test_tabuleiro_drag_premove_chat_salvar_reabrir_e_promocao(tmp_path):
    calls=[]
    def modelo(msgs,**kw):
        calls.append(kw)
        if kw.get('lance'):
            time.sleep(.8)
            p=json.loads(msgs[-1]['content'])
            escolhido=next((m['uci'] for m in p['legais'] if m['uci']=='e7e5'),p['legais'][0]['uci'])
            return json.dumps({'uci':escolhido})
        return 'Bora, Vitor. Tô de olho nesse tabuleiro.'
    match=Partida(tmp_path/'partida.json',chamar=modelo)
    def bridge(action,d=None):
        d=d or {}
        if action=='estado':return {'ok':True,'estado':match.estado()}
        if action=='visibilidade':return {'ok':True}
        if action=='contexto':return match.atualizar_contexto(d['posicao'],d['revisao'])
        if action=='salvar':return match.sincronizar(d['posicao'],d['revisao'],d.get('nova',False))
        if action=='lance':return match.escolher_lance(d['revisao'])
        if action=='conversar':return match.conversar(d['texto'])
        if action=='comentar':return match.comentar(d['revisao'])
        if action=='voz':return {'ok':True}
        raise AssertionError(action)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1450,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.expose_function('chessBridge',bridge)
        page.set_content('''<html><body><button id="btn-xadrez">Xadrez</button><button id="btn-navegador-interno">Navegador</button><div class="corpo" style="display:flex"><main id="palco"></main><section id="xadrez-painel" class="xadrez-painel" hidden></section></div></body></html>''')
        page.add_style_tag(content=':root{--bg:#1d1c19;--bg-raise:#25231f;--bg-hover:#302c27;--txt:#eee6da;--txt-2:#c3bdb4;--txt-3:#8b867e;--line:#ffffff15;--line-forte:#ffffff25;--acento:#c96442;--acento-fu:#c9644220;--sans:Arial,sans-serif;--serif:Georgia,serif}body{margin:0;background:var(--bg)}')
        page.add_style_tag(path=ROOT/'web/xadrez.css')
        page.add_script_tag(content="window.pywebview={api:{xadrez_acao:async(a,d)=>{if(a==='salvar')await new Promise(r=>setTimeout(r,300));return window.chessBridge(a,d);}}};")
        page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        page.add_script_tag(path=ROOT/'web/xadrez-audio.js')
        page.add_script_tag(path=ROOT/'web/xadrez.js')
        page.click('#btn-xadrez');page.wait_for_selector('[data-square="e2"]')
        assert page.locator('.xe-square').count()==64
        assert 'dark' in page.locator('[data-square="a1"]').get_attribute('class')
        assert 'light' in page.locator('[data-square="h1"]').get_attribute('class')
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('Sua vez')")
        # Actual pointer dragging, never a desktop automation API.
        a=page.locator('[data-square="e2"]').bounding_box();b=page.locator('[data-square="e4"]').bounding_box()
        page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down()
        page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=8)
        page.wait_for_function("document.querySelector('.xe-ghost') && getComputedStyle(document.querySelector('[data-square=\"e2\"] .xe-peca')).visibility==='hidden'")
        ghost=page.locator('.xe-ghost').bounding_box()
        assert abs(ghost['x']+ghost['width']/2-(b['x']+b['width']/2))<2
        assert abs(ghost['y']+ghost['height']/2-(b['y']+b['height']/2))<2
        page.mouse.up()
        # The visual drop must finish while persistence is deliberately delayed.
        assert page.locator('[data-square="e4"] .xe-peca').count()==1
        assert page.locator('[data-square="e2"] .xe-peca').count()==0
        assert page.locator('.xe-ghost').count()==0
        assert '1. e4' not in match.estado()['posicao']['pgn']
        page.wait_for_timeout(1800)
        assert 'e5' in page.locator('#xe-lances').inner_text(), (page.locator('#xe-status').inner_text(),match.estado(),errors)
        assert 'e4' in page.locator('#xe-lances').inner_text()
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('Sua vez')")
        page.fill('#xe-texto','Tudo bem?');page.click('#xe-enviar')
        page.wait_for_function("document.querySelector('#xe-mensagens').textContent.includes('Tô de olho')")
        assert any(c.get('lance') for c in calls) and any(not c.get('lance') for c in calls)
        # Prepare a pre-move while the reply is being calculated.
        drag(page,'g1','f3')
        page.wait_for_function("document.querySelector('#xe-lances').textContent.includes('Nf3')")
        drag(page,'f1','c4')
        page.wait_for_timeout(2400)
        assert 'Bc4' in page.locator('#xe-lances').inner_text(), (page.locator('#xe-status').inner_text(),match.estado(),errors)
        before=match.estado()['posicao']['pgn']
        page.click('#xe-fechar');page.click('#btn-xadrez')
        page.wait_for_timeout(2400)
        assert 'Bc4' in page.locator('#xe-lances').inner_text(), (page.locator('#xe-status').inner_text(),match.estado(),errors)
        assert match.estado()['posicao']['pgn'].startswith(before.rsplit(' *',1)[0])
        page.screenshot(path='/tmp/emily-xadrez-preview.png',full_page=True)
        # Rule engine checks: castling, en passant, checkmate and repetition.
        checks=page.evaluate('''() => {
          const C=EmilyChessRules.Chess, c=new C();
          ['e4','e5','Nf3','Nc6','Bc4','Nf6','O-O'].forEach(m=>c.move(m));
          const castle=c.get('g1').type==='k' && c.get('f1').type==='r';
          const ep=new C();['e4','a6','e5','d5','exd6'].forEach(m=>ep.move(m));
          const mate=new C();['f3','e5','g4','Qh4#'].forEach(m=>mate.move(m));
          const repeat=new C();['Nf3','Nf6','Ng1','Ng8','Nf3','Nf6','Ng1','Ng8'].forEach(m=>repeat.move(m));
          const promotion=new C('7k/P7/8/8/8/8/8/7K w - - 0 1');promotion.move({from:'a7',to:'a8',promotion:'n'});
          return {castle,ep:!ep.get('d5') && ep.get('d6').type==='p',mate:mate.isCheckmate(),repeat:repeat.isThreefoldRepetition(),promotion:promotion.get('a8').type==='n'};
        }''')
        assert all(checks.values()),checks
        assert errors==[]
        browser.close()


def test_sons_reais_e_eventos_especiais():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page()
        page.set_content('<button id="ativar">Ativar áudio</button>')
        page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        page.add_script_tag(path=ROOT/'web/xadrez-audio.js')
        page.evaluate('''() => {
          window.scheduled=[];
          const original=AudioContext.prototype.createBufferSource;
          AudioContext.prototype.createBufferSource=function(){
            const source=original.call(this),start=source.start.bind(source);
            source.start=(when)=>{
              const samples=source.buffer.getChannelData(0);
              scheduled.push({duration:source.buffer.duration,peak:Math.max(...samples),rms:Math.sqrt(samples.reduce((a,v)=>a+v*v,0)/samples.length),when});
              start(when);
            };return source;
          };
          document.querySelector('#ativar').onclick=()=>EmilyChessAudio.wake();
        }''')
        page.click('#ativar')
        page.wait_for_timeout(50)
        events=page.evaluate('''() => {
          const cases=[
            {fen:null,moves:['e4'],expected:['move']},
            {fen:null,moves:['e4','d5','exd5'],expected:['capture']},
            {fen:null,moves:['e4','e5','Nf3','Nc6','Bc4','Nf6','O-O'],expected:['castle']},
            {fen:null,moves:['e4','f6','Qh5+'],expected:['move','check']},
            {fen:null,moves:['f3','e5','g4','Qh4#'],expected:['move','mate']},
            {fen:'7k/P7/8/8/8/8/8/7K w - - 0 1',moves:['a8=Q+'],expected:['promotion','check']},
            {fen:null,moves:['Nf3','Nf6','Ng1','Ng8','Nf3','Nf6','Ng1','Ng8'],expected:['move','draw']}
          ];
          return cases.map(test=>{
            const g=test.fen?new EmilyChessRules.Chess(test.fen):new EmilyChessRules.Chess();
            let move;test.moves.forEach(m=>move=g.move(m));
            const selected=EmilyChessAudio.events(move,g);EmilyChessAudio.aoLance(move,g);
            return {selected,expected:test.expected};
          });
        }''')
        assert all(c['selected']==c['expected'] for c in events)
        scheduled=page.evaluate('scheduled')
        assert len(scheduled)==11
        assert all(0<s['rms']<.2 and 0<s['peak']<1 for s in scheduled)
        assert len({round(s['duration'],2) for s in scheduled})>=5
        page.evaluate('EmilyChessAudio.ativar(false); const g=new EmilyChessRules.Chess();EmilyChessAudio.aoLance(g.move("e4"),g);')
        assert len(page.evaluate('scheduled'))==11
        browser.close()


def test_marcar_casas_setas_premove_cancelamento_e_inversao():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1450,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content('<button id="btn-xadrez">Xadrez</button><button id="btn-navegador-interno">Navegador</button><div class="corpo"><main id="palco"></main><section id="xadrez-painel" hidden></section></div>')
        page.add_style_tag(path=ROOT/'web/xadrez.css');page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        page.add_script_tag(content='''
          window.matchState={id:'teste',revisao:0,posicao:null,lance:{estado:'pronto'},conversa:{estado:'pronto'},mensagens:[]};
          window.pywebview={api:{xadrez_acao:async(a,d)=>{
            if(a==='salvar'){matchState.posicao=d.posicao;matchState.revisao++;matchState.lance={estado:'pronto'};}
            if(a==='lance')matchState.lance={estado:'pensando'};
            return {ok:true,estado:structuredClone(matchState)};
          }}};
        ''');page.add_script_tag(path=ROOT/'web/xadrez.js');page.click('#btn-xadrez')
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('Sua vez')")
        page.click('[data-square="e2"]');page.click('[data-square="e4"]')
        assert page.locator('.xe-square.marked').count()==2
        assert page.locator('[data-square="e2"] .xe-peca').count()==1
        assert page.evaluate('matchState.posicao.fatos.meios_lances')==0
        a=page.locator('[data-square="e2"]').bounding_box();b=page.locator('[data-square="e4"]').bounding_box()
        page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down()
        page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=5)
        assert page.locator('.xe-ghost').count()==1
        page.mouse.down(button='right');page.mouse.up(button='right');page.mouse.up()
        assert page.locator('.xe-ghost').count()==0
        assert page.locator('[data-square="e2"] .xe-peca').count()==1
        assert page.evaluate('matchState.posicao.fatos.meios_lances')==0
        assert page.locator('.xe-annotations > path').count()==0
        assert page.locator('#xe-thinking').count()==0
        assert 'Stockfish' not in page.locator('#xe-jogador-emily').inner_text()
        page.click('#xe-dificuldade');assert page.locator('#xe-niveis').is_visible();page.keyboard.press('Escape');assert page.locator('#xe-niveis').is_hidden()
        # Só criar a seta ao soltar; o caminho não acompanha o ponteiro.
        a=page.locator('[data-square="e2"]').bounding_box();b=page.locator('[data-square="e4"]').bounding_box()
        page.mouse.move(a['x']+a['width']/2,a['y']+a['height']/2);page.mouse.down(button='right')
        page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2,steps=5)
        assert page.locator('.xe-annotations > path').count()==0
        page.mouse.up(button='right')
        drag(page,'g1','f3','right')
        assert page.locator('.xe-annotations > path').count()==2
        assert ' L ' in page.locator('[data-arrow="g1-f3"]').get_attribute('d')
        page.click('[data-square="a4"]',button='right')
        assert page.locator('.xe-annotations > path').count()==0
        assert page.locator('.xe-square.marked').count()==0
        drag(page,'e2','e4','right');drag(page,'g1','f3','right')
        page.click('#xe-inverter')
        assert page.locator('[data-arrow="e2-e4"]').get_attribute('d').startswith('M 350 150')
        drag(page,'e2','e4','right')
        assert page.locator('.xe-annotations > path').count()==1
        drag(page,'e2','e4')
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('pensando')")
        assert page.locator('.xe-square.marked').count()==0
        assert page.locator('.xe-annotations > path').count()==0
        assert page.evaluate('matchState.posicao.fatos.ultimos_lances[0].ator')=='Você'
        assert page.evaluate('matchState.posicao.fatos.ultimos_lances[0].captura') is None
        drag(page,'g1','g3')
        assert page.locator('.xe-square.premove').count()==0
        drag(page,'g1','f3')
        assert page.locator('.xe-square.premove').count()==2
        page.click('[data-square="a4"]',button='right')
        assert page.locator('.xe-square.premove').count()==0
        drag(page,'g1','f3')
        page.keyboard.press('Escape')
        assert page.locator('.xe-square.premove').count()==0
        # Cancelar também funciona no intervalo depois do lance adversário.
        drag(page,'g1','f3')
        page.evaluate("matchState.lance={estado:'escolhido',uci:'e7e5',revisao:matchState.revisao,segundos:1}")
        page.wait_for_function("document.querySelector('#xe-lances').textContent.includes('e5')")
        page.click('[data-square="a4"]',button='right')
        page.wait_for_timeout(500)
        assert 'Nf3' not in page.locator('#xe-lances').inner_text()
        assert page.locator('[data-square="g1"] .xe-peca').count()==1
        drag(page,'g1','f3')
        page.wait_for_function("document.querySelector('#xe-lances').textContent.includes('Nf3')")
        drag(page,'f1','c4','right');drag(page,'d1','h5','right')
        page.screenshot(path='/tmp/emily-xadrez-setas.png',full_page=True)
        def show(moves,cor='w',fen=None):
            revision=page.evaluate("matchState.revisao")+1
            page.evaluate("""({moves,cor,fen,revision})=>{
              const g=fen?new EmilyChessRules.Chess(fen):new EmilyChessRules.Chess();moves.forEach(m=>g.move(m));
              matchState.revisao=revision;matchState.posicao={fen:g.fen(),pgn:g.pgn(),cor,turno:g.turn(),fim:g.isGameOver(),resultado:''};
              matchState.lance={estado:'pensando'};
            }""",{'moves':moves,'cor':cor,'fen':fen,'revision':revision})
            expected=''.join((str(i//2+1)+'.' if i%2==0 else '')+m for i,m in enumerate(moves))
            page.wait_for_function("r=>document.querySelector('#xe-lances').textContent.replace(/\\s/g,'')===r",arg=expected)
            page.wait_for_timeout(80)
        show(['e4','d5','exd5'])
        assert page.locator('#xe-material-voce .xe-peca.preta').count()==1
        assert page.locator('#xe-material-voce .xe-vantagem').inner_text()=='+1'
        assert page.locator('#xe-turno-emily').inner_text()=='Vez da Emily'
        assert page.locator('#xe-turno-voce').inner_text()=='Aguardando'
        # Ao desfazer, o histórico e os pontos deixam de incluir a captura.
        show(['e4','d5'])
        assert page.locator('#xe-material-voce .xe-peca').count()==0
        assert page.locator('.xe-vantagem').count()==0
        assert page.locator('#xe-turno-voce').inner_text()=='Sua vez'
        show(['e4','a6','e5','d5','exd6'])
        assert page.locator('#xe-material-voce .xe-peca').count()==1
        assert page.locator('#xe-material-voce .xe-vantagem').inner_text()=='+1'
        # Emily pode jogar de brancas; o material pertence ao jogador, não à posição visual.
        show(['e4','d5','exd5'],cor='b')
        assert page.locator('#xe-material-emily .xe-peca.preta').count()==1
        assert page.locator('#xe-material-emily .xe-vantagem').inner_text()=='+1'
        assert page.locator('#xe-turno-voce').inner_text()=='Sua vez'
        show(['a8=Q+'],fen='7k/P7/8/8/8/8/8/7K w - - 0 1')
        assert page.locator('#xe-material-voce .xe-vantagem').inner_text()=='+9'
        assert page.locator('#xe-material-voce .xe-peca').count()==0
        show(['f3','e5','g4','Qh4#'])
        assert page.locator('#xe-turno-voce').inner_text()=='Partida encerrada'
        assert page.locator('#xe-turno-emily').inner_text()=='Partida encerrada'
        assert page.locator('.xe-jogador.tem-vez').count()==0
        assert errors==[]
        browser.close()


def test_chat_aceita_nova_mensagem_enquanto_responde_e_preserva_digitacao():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1450,'height':1000})
        page.set_content('<button id="btn-xadrez">Xadrez</button><button id="btn-navegador-interno">Navegador</button><div class="corpo"><main id="palco"></main><section id="xadrez-painel" hidden></section></div>')
        page.add_style_tag(path=ROOT/'web/xadrez.css');page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        page.add_script_tag(content='''
          window.recebidas=[];
          window.matchState={id:'teste',revisao:0,posicao:null,lance:{estado:'pronto'},conversa:{estado:'pronto'},mensagens:[]};
          window.pywebview={api:{xadrez_acao:async(a,d)=>{
            if(a==='salvar'){matchState.posicao=d.posicao;matchState.revisao++;}
            if(a==='conversar'){
              recebidas.push(d.texto);await new Promise(resolve=>window.confirmarEnvio=resolve);
              matchState.mensagens.push({role:'user',content:d.texto});matchState.conversa={estado:'pensando'};
            }
            return {ok:true,estado:structuredClone(matchState)};
          }}};
        ''')
        page.add_script_tag(path=ROOT/'web/xadrez.js');page.click('#btn-xadrez')
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('Sua vez')")
        page.fill('#xe-texto','Primeira');page.click('#xe-enviar')
        page.wait_for_function('recebidas.length===1')
        assert page.locator('#xe-enviar').is_disabled()
        page.fill('#xe-texto','Segunda')
        page.evaluate('confirmarEnvio()')
        page.wait_for_function("!document.querySelector('#xe-enviar').disabled")
        assert page.locator('#xe-texto').input_value()=='Segunda'
        page.click('#xe-enviar');page.wait_for_function('recebidas.length===2')
        page.evaluate('confirmarEnvio()')
        page.wait_for_function("!document.querySelector('#xe-enviar').disabled && document.querySelector('#xe-texto').value===''")
        assert page.evaluate('recebidas')==['Primeira','Segunda']
        browser.close()


def test_tela_resultado_desistencia_mate_afogamento_e_revanche():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1450,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content('<button id="btn-xadrez">Xadrez</button><button id="btn-navegador-interno">Navegador</button><div class="corpo"><main id="palco"></main><section id="xadrez-painel" hidden></section></div>')
        page.add_style_tag(path=ROOT/'web/xadrez.css');page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        page.add_script_tag(content='''
          window.matchState={id:'resultado',revisao:0,posicao:null,lance:{estado:'pronto'},conversa:{estado:'pronto'},mensagens:[],dificuldade:'casual'};
          window.pywebview={api:{xadrez_acao:async(a,d)=>{
            if(a==='salvar'){matchState.posicao=d.posicao;matchState.revisao++;matchState.lance={estado:'pronto'};}
            if(a==='lance')matchState.lance={estado:'pensando'};
            if(a==='dificuldade'){matchState.dificuldade=d.nivel;matchState.revisao++;}
            return {ok:true,estado:structuredClone(matchState)};
          }}};
        ''');page.add_script_tag(path=ROOT/'web/xadrez.js');page.click('#btn-xadrez')
        page.wait_for_function("document.querySelector('#xe-status').textContent.includes('Sua vez')")
        page.click('#xe-dificuldade');page.click('[data-nivel=equilibrado]')
        page.wait_for_function("document.querySelector('#xe-dificuldade').textContent.includes('Equilibrado')")
        page.click('#xe-desistir');page.click('#xe-confirmar')
        page.wait_for_selector('#xe-fim:not([hidden])')
        assert page.locator('.xe-fim-card h3').inner_text()=='Emily venceu'
        assert page.locator('.xe-fim-card p').inner_text()=='Por desistência'
        assert page.locator('.xe-selo-rei.vencedor').count()==1
        assert page.locator('.xe-selo-rei.derrotado').count()==1
        page.click('.xe-fim-ver');page.wait_for_timeout(800)
        assert page.locator('#xe-fim').is_hidden()
        page.click('#xe-ver-resultado');assert page.locator('#xe-fim').is_visible()
        page.click('#xe-revanche')
        page.wait_for_function("document.querySelector('#xe-cor').textContent==='Pretas'")
        assert page.locator('#xe-fim').is_hidden()
        assert page.locator('.xe-selo-rei').count()==0
        page.evaluate("""()=>{const g=new EmilyChessRules.Chess();['f3','e5','g4','Qh4#'].forEach(m=>g.move(m));matchState.revisao++;matchState.posicao={fen:g.fen(),pgn:g.pgn(),cor:'w',turno:g.turn(),fim:true,resultado:'Xeque-mate. Emily venceu.'};matchState.lance={estado:'pronto'};}""")
        page.wait_for_function("document.querySelector('.xe-fim-card p')?.textContent==='Por xeque-mate'")
        assert page.locator('.xe-selo-rei.derrotado').get_attribute('title')=='Por xeque-mate'
        page.click('.xe-fim-ver');page.click('#xe-voltar')
        page.wait_for_function("document.querySelector('#xe-turno-voce').textContent==='Sua vez'")
        assert page.locator('.xe-selo-rei').count()==0
        page.evaluate("""()=>{const g=new EmilyChessRules.Chess('7k/5K2/6Q1/8/8/8/8/8 b - - 0 1');matchState.revisao++;matchState.posicao={fen:g.fen(),pgn:g.pgn(),cor:'w',turno:'b',fim:true,resultado:'Empate por afogamento.'};matchState.lance={estado:'pronto'};}""")
        page.wait_for_function("document.querySelector('.xe-fim-card p')?.textContent==='Por afogamento'")
        assert page.locator('.xe-fim-card h3').inner_text()=='Empate'
        assert page.locator('.xe-selo-rei.empate').count()==2
        assert errors==[]
        browser.close()


def test_fatos_taticos_promocao_captura_e_bispo_cravado():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page()
        page.set_content('<button id="btn-xadrez"></button><button id="btn-navegador-interno"></button>')
        page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        js=(ROOT/'web/xadrez.js').read_text().replace('window.EmilyXadrez={abrir,fechar};',"window.__context=(fen,cor)=>{game=new EmilyChessRules.Chess(fen);state={posicao:{cor}};return posicao();};window.EmilyXadrez={abrir,fechar};")
        page.add_script_tag(content=js)
        p=page.evaluate("__context('k7/6P1/8/8/8/8/8/1b5K b - - 0 1','b')")
        t=p['fatos']['tatico'];assert t['vez']=='Você'
        assert t['peoes_perto_promocao'][0]['dono']=='Emily'
        assert t['peoes_perto_promocao'][0]['capturas_legais_contra_peao']==[]
        assert t['promocoes_legais_agora']==[]
        p=page.evaluate("__context('k3r3/8/8/8/8/3p4/4B3/4K3 w - - 0 1','w')")
        assert p['fatos']['tatico']['capturas_legais_agora']==[]
        p=page.evaluate("__context('7k/8/8/8/6p1/5B2/8/K7 w - - 0 1','w')")
        captura=p['fatos']['tatico']['capturas_legais_agora'][0]
        assert {k:captura[k] for k in ('de','para','peca','ator','vitima','casa_vitima')}=={'de':'f3','para':'g4','peca':'bispo','ator':'Você','vitima':'peão','casa_vitima':'g4'}
        assert captura['recapturas_legais']==[] and not captura['risco_perda_material_imediata']
        # En passant tem casa da vítima diferente da casa de destino.
        p=page.evaluate("__context('7k/8/8/3pP3/8/8/8/K7 w - d6 0 1','w')")
        captura=p['fatos']['tatico']['capturas_legais_agora'][0]
        assert captura['para']=='d6' and captura['casa_vitima']=='d5'
        browser.close()

def test_captura_legal_nao_confunde_com_segura_e_nao_muda_tabuleiro():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page()
        page.set_content('<button id="btn-xadrez"></button><button id="btn-navegador-interno"></button>')
        page.add_script_tag(path=ROOT/'web/vendor/chess.js')
        js=(ROOT/'web/xadrez.js').read_text().replace('window.EmilyXadrez={abrir,fechar};',
            'window.__tatico=(fen)=>{game=new EmilyChessRules.Chess(fen);state={posicao:{cor:"w"}};const antes=game.fen();const fatos=fatosTaticos();return {antes,depois:game.fen(),historico:game.history(),fatos};};window.EmilyXadrez={abrir,fechar};')
        page.add_script_tag(content=js)
        pos=page.evaluate('(fen)=>__tatico(fen)','r1b2rk1/pp2qppp/5p2/8/2P5/3QbP2/P3B1PP/R3K2R w KQ - 0 16')
        captura=next(m for m in pos['fatos']['capturas_legais_agora'] if m['uci']=='d3e3')
        assert captura['risco_perda_material_imediata'] and captura['saldo_material_se_recapturada']==-6
        assert any(r['uci']=='e7e3' for r in captura['recapturas_legais'])
        assert pos['antes']==pos['depois'] and pos['historico']==[]
        # O cavalo cravado em e7 não pode recapturar a dama em d5.
        pos=page.evaluate('(fen)=>__tatico(fen)','4k3/4n3/8/3b4/2Q5/8/8/K3R3 w - - 0 1')
        captura=next(m for m in pos['fatos']['capturas_legais_agora'] if m['uci']=='c4d5')
        assert not captura['recapturas_legais']
        browser.close()
