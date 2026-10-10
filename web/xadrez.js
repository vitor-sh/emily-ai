/* Xadrez da Emily. Regras locais chess.js; mouse não toca o desktop. */
(() => {
  'use strict';
  let enviandoChat=false, edicaoChat=0, resultadoVisto='', arrastoCancelado=false;
  const $ = id => document.getElementById(id);
  // Silhuetas vetoriais próprias, inspiradas em peças clássicas de xadrez.
  const shapes = {
    p: '<circle cx="22" cy="9" r="4.8"/><path d="M19 14c-6 1-7 6-3 9-5 3-8 9-8 16h28c0-7-3-13-8-16 4-3 3-8-3-9z"/>',
    r: '<path d="M9 5h6v4h5V5h5v4h5V5h5v11l-6 4v13l6 3v4H9v-4l6-3V20l-6-4z"/><path class="xe-detail" d="M10 13h24M16 21h12M15 33h14M11 37h22"/>',
    n: '<path d="M11 38c2-7 5-12 10-17l-5 2-4 5-5-3 2-7 5-6 2-7 5 4 5-3c10 4 13 14 11 32z"/><path class="xe-detail" d="M26 10c6 5 8 13 7 23M11 20l4-1M17 12l2-2"/><circle class="xe-eye" cx="20" cy="15" r="1.5"/>',
    b: '<circle cx="22" cy="5" r="2.4"/><path d="M22 8c-4 3-10 7-10 13 0 5 5 7 10 7s10-2 10-7c0-6-6-10-10-13zM17 28h10l2 5H15zM14 34c-4 0-7 1-10 3l2 4c7-3 11-1 16-1s9-2 16 1l2-4c-3-2-6-3-10-3z"/><path class="xe-detail" d="M22 14v9M18 19h8M16 31h12"/>',
    q: '<path d="m7 12 7 18h16l7-18-9 11-6-15-6 15zM14 30h16l3 9c-8 2-14 2-22 0z"/><circle cx="7" cy="10" r="2.3"/><circle cx="15" cy="7" r="2.3"/><circle cx="22" cy="5" r="2.3"/><circle cx="29" cy="7" r="2.3"/><circle cx="37" cy="10" r="2.3"/><path class="xe-detail" d="M14 33q8-2 16 0M13 37q9-2 18 0"/>',
    k: '<path d="M22 2v9M18 5h8" fill="none"/><path d="M22 11c-3-5-5 3-5 5-8-9-17-2-13 7l8 10h20l8-10c4-9-5-16-13-7 0-2-2-10-5-5zM12 33h20l2 7c-8 2-16 2-24 0z"/><path class="xe-detail" d="M22 14v16M12 30c-2-4-7-8-6-11 2-5 8-3 12 4M32 30c2-4 7-8 6-11-2-5-8-3-12 4M12 36q10-2 20 0"/>'
  };
  const names = {p:'peão', r:'torre', n:'cavalo', b:'bispo', q:'dama', k:'rei'};
  function piece(p) { return `<svg class="xe-peca ${p.color === 'w' ? 'branca' : 'preta'}" viewBox="0 0 44 44" aria-hidden="true">${shapes[p.type]}</svg>`; }
  const avatar = '<span class="xe-avatar xe-emily"><img src="assets/emily-app-icon.png" alt="Emily" draggable="false"></span>';
  const audio = window.EmilyChessAudio;
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let game, state, selected, premove, stopped = '', mounted = false, open = false;
  let saving = false, polling = false, chatHash = '', dragging = null, ghost = null;
  let flipped = false, voice = false, lockPromotion = false, note = '', lastTime = '';
  let timer, boardHash = '';
  let opening = false, skipClick = false, viewSerial=0;
  let saveDone = Promise.resolve();
  let drawing=null, arrows=[], marked=new Set(), inputSerial=0;
  const api = async (acao, dados = {}) => {
    if (!window.pywebview?.api?.xadrez_acao) throw new Error('A ponte com a Emily ainda não está pronta. Tente novamente.');
    const r = await window.pywebview.api.xadrez_acao(acao, dados);
    if (!r?.ok) throw Object.assign(new Error(r?.erro || 'Não consegui atualizar a partida.'), {remote:r?.estado});
    return r;
  };
  function message(text) { note = text; if ($('xe-status')) $('xe-status').textContent = text; }
  function posicao() {
    const history = game.history({verbose:true});
    return {fen:game.fen(), pgn:game.pgn(), turno:game.turn(), cor:state?.posicao?.cor || 'w',
      legais:game.moves({verbose:true}).map(m => ({uci:m.from+m.to+(m.promotion || ''), san:m.san})),
      fim:game.isGameOver() || Boolean(stopped), resultado:stopped || resultado(),
      ultimo:history.at(-1)?.san || '', fatos: {
        fen_antes_ultimo_lance:history.at(-1)?.before || null, meios_lances:history.length, lances_completos:Math.floor(history.length/2), vez:game.turn()===state?.posicao?.cor?'Você':'Emily',
        pecas:game.board().flat().filter(Boolean).map(p=>({casa:p.square,peca:names[p.type],dono:p.color===state?.posicao?.cor?'Você':'Emily'})),
        material:['w','b'].map(c=>({dono:c===state?.posicao?.cor?'Você':'Emily',
          pecas:Object.fromEntries(Object.keys(names).map(t=>[names[t],game.board().flat().filter(p=>p?.color===c && p.type===t).length]))})),
        ultimos_lances:history.slice(-6).map(m=>({san:m.san,ator:m.color===state?.posicao?.cor?'Você':'Emily',peca:names[m.piece],
          origem:m.from,destino:m.to,captura:m.captured?{peca:names[m.captured],dono:m.color===state?.posicao?.cor?'Emily':'Você',casa:m.flags.includes('e')?m.to[0]+m.from[1]:m.to}:null,
          xeque:m.san.includes('+') || m.san.includes('#'),mate:m.san.includes('#'),
          roque:m.flags.includes('k')?'curto':m.flags.includes('q')?'longo':null,promocao:m.promotion?names[m.promotion]:null})),
        tatico: fatosTaticos(), xeque:game.isCheck(),resultado:stopped || resultado()
      }};
  }
  function fatosTaticos(){
    const legal=game.moves({verbose:true}),human=state?.posicao?.cor || 'w';
    const dono=c=>c===human?'Você':'Emily';
    const capturaCasa=m=>m.flags.includes('e')?m.to[0]+m.from[1]:m.to;
    const valores={p:1,n:3,b:3,r:5,q:9,k:0};
    const capturas=legal.filter(m=>m.captured).map(m=>{
      // Simula em outro tabuleiro: nunca altera o jogo nem o histórico reais.
      const depois=new window.EmilyChessRules.Chess(game.fen());
      depois.move({from:m.from,to:m.to,promotion:m.promotion});
      const respostas=depois.moves({verbose:true}).filter(r=>r.captured && capturaCasa(r)===m.to);
      const valorPeca=valores[m.promotion || m.piece];
      const saldo=valores[m.captured]+(m.promotion?valores[m.promotion]-valores.p:0)-valorPeca;
      return {uci:m.from+m.to+(m.promotion || ''),de:m.from,para:m.to,peca:names[m.piece],ator:dono(m.color),
        vitima:names[m.captured],casa_vitima:capturaCasa(m),
        recapturas_legais:respostas.map(r=>({uci:r.from+r.to+(r.promotion || ''),de:r.from,para:r.to,peca:names[r.piece],ator:dono(r.color),vitima:names[r.captured]})),
        risco_perda_material_imediata:respostas.length>0 && saldo<0,
        saldo_material_se_recapturada:respostas.length?saldo:null,
        aviso_recaptura:respostas.length?'Saldo parcial após capturar e sofrer recaptura: não inclui continuação, compensação ou sacrifício. Captura legal não significa segura.':
          'Não há recaptura imediata legal da peça nessa casa. Isso não prova que o lance seja bom.'};
    });
    const pecas=game.board().flat().filter(Boolean);
    return {vez:dono(game.turn()),capturas_legais_agora:capturas,
      promocoes_legais_agora:legal.filter(m=>m.promotion).map(m=>({de:m.from,para:m.to,peca:names[m.promotion],ator:dono(m.color)})),
      peoes_perto_promocao:pecas.filter(p=>p.type==='p' && p.square[1]===(p.color==='w'?'7':'2')).map(p=>{
        const frente=p.square[0]+(p.color==='w'?'8':'1');
        return {casa:p.square,dono:dono(p.color),casa_promocao:frente,frente_ocupada:Boolean(game.get(frente)),
          capturas_legais_contra_peao:capturas.filter(m=>m.casa_vitima===p.square),
          atacantes_geometricos:game.attackers(p.square,p.color==='w'?'b':'w').map(s=>({casa:s,peca:names[game.get(s).type]}))};
      }),
      aviso:'Capturas e promoções listadas são legais SÓ para o jogador da vez. Ataques geométricos não provam uma captura legal (peças cravadas/rei em xeque). A ausência de captura não prova promoção inevitável: podem existir bloqueios ou xeques. Não invente uma defesa.'};
  }
  function resultado() {
    if (game.isCheckmate()) return game.turn() === state?.posicao?.cor ? 'Xeque-mate. Emily venceu.' : 'Xeque-mate. Você venceu!';
    if (game.isStalemate()) return 'Empate por afogamento.';
    if (game.isThreefoldRepetition()) return 'Empate por repetição de posição.';
    if (game.isInsufficientMaterial()) return 'Empate por material insuficiente.';
    if (game.isDraw()) return 'Empate pela regra dos 50 lances.';
    return '';
  }
  function restaurar(s) {
    inputSerial++; state = s; game = new window.EmilyChessRules.Chess();
    if (s.posicao?.pgn) game.loadPgn(s.posicao.pgn);
    if (s.posicao && game.fen() !== s.posicao.fen) throw new Error('O histórico salvo não corresponde ao tabuleiro. Comece uma nova partida.');
    stopped = s.posicao?.fim && !game.isGameOver() ? s.posicao.resultado : '';
    voice = Boolean(s.voz); selected = null; premove = null; clearAnnotations();
    flipped = s.posicao?.cor === 'b';
    chatHash = ''; render();
  }
  async function save(nova = false) {
    let resolveSave;
    saveDone=new Promise(resolve=>{resolveSave=resolve;});
    saving = true;
    render();
    try {
      const r = await api('salvar', {posicao:posicao(), revisao:state.revisao, nova});
      state = r.estado; note = ''; return true;
    } catch (e) {
      if (e.remote) restaurar(e.remote);
      else { try { restaurar((await api('estado')).estado); } catch (_) {} }
      message(e.message); return false;
    } finally { saving = false; render(); resolveSave(); }
  }
  function mount() {
    const panel = $('xadrez-painel');
    panel.innerHTML = `
      <header class="xe-header"><div><span class="xe-kicker">UM TEMPO COM A EMILY</span><h2>Xadrez</h2></div><button id="xe-fechar" class="xe-button" title="Voltar ao chat">Voltar ao chat ×</button></header>
      <div class="xe-layout">
        <div class="xe-jogo">
          <div class="xe-jogador" id="xe-jogador-emily">${avatar}<div class="xe-identidade"><div class="xe-nome"><strong>Emily</strong><span class="xe-turno" id="xe-turno-emily"></span></div><small>Jogando com você</small><div class="xe-material" id="xe-material-emily"></div></div></div>
          <div class="xe-board-area"><div class="xe-board" id="xe-board" role="group" aria-label="Tabuleiro de xadrez"></div><div id="xe-fim" class="xe-fim" hidden></div></div>
          <div class="xe-jogador" id="xe-jogador-voce"><span class="xe-avatar xe-voce">V</span><div class="xe-identidade"><div class="xe-nome"><strong>Você</strong><span class="xe-turno" id="xe-turno-voce"></span></div><small id="xe-cor">Brancas</small><div class="xe-material" id="xe-material-voce"></div></div><span class="xe-badge">Casual · sem relógio</span></div>
          <p id="xe-status" class="xe-status" role="status" aria-live="polite"></p>
          <div class="xe-nivel"><span>Desafio da Emily</span><div class="xe-dificuldade-wrap"><button id="xe-dificuldade" class="xe-button" type="button" aria-label="Dificuldade da partida" aria-haspopup="listbox" aria-expanded="false" aria-controls="xe-niveis">Casual ▾</button><div id="xe-niveis" role="listbox" aria-label="Desafio da Emily" hidden><button type="button" role="option" data-nivel="casual">Casual</button><button type="button" role="option" data-nivel="equilibrado">Equilibrado</button><button type="button" role="option" data-nivel="desafiador">Desafiador</button><button type="button" role="option" data-nivel="sol">Só Sol · sem apoio</button></div></div><small>Perfis de dificuldade, sem equivalência garantida com rating.</small></div><div class="xe-controls"><button id="xe-nova" class="xe-button acento">Nova partida</button><button id="xe-voltar" class="xe-button">Voltar lance</button><button id="xe-inverter" class="xe-button" title="Inverter tabuleiro">⇅</button><button id="xe-desistir" class="xe-button">Desistir</button><button id="xe-ver-resultado" class="xe-button" hidden>Ver resultado</button><button id="xe-pgn" class="xe-button">Salvar PGN</button><button id="xe-som" class="xe-button xe-som" aria-pressed="true" title="Silenciar sons do tabuleiro"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h4l5-4v14l-5-4H4zM16 8a6 6 0 0 1 0 8M19 5a10 10 0 0 1 0 14"/></svg><span>Som</span></button><button id="xe-sons-locais" class="xe-button" aria-pressed="false" title="Alternar entre os sons padrão e os seus arquivos locais">Sons locais</button><button id="xe-config-som" class="xe-button" title="Importar efeitos de áudio deste PC">♫ Personalizar</button><button id="xe-retry" class="xe-button acento" hidden>Tentar lance novamente</button></div>
          <details class="xe-historico" open><summary>Lances da partida <span id="xe-tempo"></span></summary><div id="xe-lances"></div></details>
          <small class="xe-hint">Arraste para jogar ou preparar um pré-lance. Clique esquerdo marca casas; arraste com o direito para desenhar setas. Clique direito limpa as marcações e cancela o pré-lance. Esc limpa as marcações.</small>
        </div>
        <div class="xe-conversa">
          <header>${avatar}<div><strong>Converse enquanto joga</strong><small>Emily</small></div><button id="xe-voz" class="xe-button" aria-pressed="false" title="Narrar respostas com a voz da Emily">♪ Voz</button></header>
          <div class="xe-mensagens" id="xe-mensagens" aria-live="polite"></div>
          <p id="xe-chat-status" role="status"></p>
          <form id="xe-form"><textarea id="xe-texto" rows="2" maxlength="8000" placeholder="Fala com a Emily…" aria-label="Mensagem para a Emily durante a partida"></textarea><button id="xe-enviar" class="xe-button acento" type="submit">Enviar ↑</button></form>
        </div>
      </div>
      <div class="xe-modal" id="xe-modal" hidden></div>`;
    panel.addEventListener('pointerdown',()=>audio?.wake(),{passive:true});
    panel.addEventListener('keydown',()=>audio?.wake());
    $('xe-som').onclick=()=>{audio?.ativar(!audio.ativo);render();};
    audio?.carregar().then(()=>render()).catch(()=>{});
    $('xe-sons-locais').onclick=async()=>{
      try{await audio.selecionar(!audio.personalizado);render();}catch(e){modal('Sons locais',`<p>${esc(e.message)}</p>`,()=>{});}
    };
    $('xe-config-som').onclick=()=>modal('Seus sons do tabuleiro',
      '<p>Importe efeitos deste PC. MP3, WAV ou OGG, até 1 MB e 5 segundos por efeito. Os sons ficam neste aparelho; os efeitos não importados usam o padrão.</p>'+
      Object.entries(audio.nomes).map(([tipo,nome])=>`<label class="xe-audio-arquivo">${nome}<small>${audio.tiposLocais.includes(tipo)?'Som local salvo':'Som padrão'}</small><span class="xe-audio-escolher">Escolher arquivo</span><span class="xe-audio-nome">Nenhum selecionado</span><input class="xe-audio-input" type="file" data-som="${tipo}" accept=".mp3,.wav,.ogg" aria-label="Som de ${nome}"></label>`).join('')+
      '<p class="xe-hint">Importe somente arquivos que você tenha direito de usar. Importar não concede licença para compartilhá-los.</p><p id="xe-audio-erro" role="status"></p><button id="xe-audio-salvar">Salvar sons</button> <button id="xe-audio-limpar">Remover sons locais</button>',content=>{
        const salvar=content.querySelector('#xe-audio-salvar'), limpar=content.querySelector('#xe-audio-limpar');
        content.querySelectorAll('[data-som]').forEach(input=>input.onchange=()=>{input.parentElement.querySelector('.xe-audio-nome').textContent=input.files[0]?.name || 'Nenhum selecionado';});
        async function executar(acao){
          salvar.disabled=limpar.disabled=true;
          try{await acao();closeModal();render();}catch(e){content.querySelector('#xe-audio-erro').textContent=e.message;}
          finally{salvar.disabled=limpar.disabled=false;}
        }
        salvar.onclick=()=>executar(()=>audio.importar(Object.fromEntries([...content.querySelectorAll('[data-som]')].filter(i=>i.files.length).map(i=>[i.dataset.som,i.files[0]]))));
        limpar.onclick=()=>executar(()=>audio.limpar());
      });
    $('xe-fechar').onclick = fechar;
    $('xe-nova').onclick = () => modal('Uma nova partida?', '<p>A partida atual será substituída. Você pode salvar o PGN antes.</p><div class="xe-escolha"><button data-cor="w">Jogar com as brancas</button><button data-cor="b">Jogar com as pretas</button></div>', content => {
      content.querySelectorAll('[data-cor]').forEach(b => b.onclick = async () => { closeModal(); await nova(b.dataset.cor); });
    });
    const fecharNiveis=()=>{$('xe-niveis').hidden=true;$('xe-dificuldade').setAttribute('aria-expanded','false');};
    $('xe-dificuldade').onclick=()=>{
      const abrir=$('xe-niveis').hidden;$('xe-niveis').hidden=!abrir;$('xe-dificuldade').setAttribute('aria-expanded',String(abrir));
      if(abrir)$('xe-niveis').querySelector('[aria-selected="true"]')?.focus();
    };
    $('xe-niveis').querySelectorAll('[data-nivel]').forEach(b=>b.onclick=async()=>{
      fecharNiveis();$('xe-dificuldade').focus();
      try{const r=await api('dificuldade',{nivel:b.dataset.nivel});restaurar(r.estado);await ensureMove();}catch(e){message(e.message);render();}
    });
    document.addEventListener('pointerdown',e=>{if(!e.target.closest('.xe-dificuldade-wrap'))fecharNiveis();});
    $('xe-niveis').onkeydown=e=>{
      const options=[...$('xe-niveis').querySelectorAll('button')],i=options.indexOf(document.activeElement);
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();fecharNiveis();$('xe-dificuldade').focus();}
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();options[e.key==='Home'?0:e.key==='End'?options.length-1:(i+(e.key==='ArrowDown'?1:options.length-1))%options.length].focus();}
    };
    $('xe-inverter').onclick = () => { flipped = !flipped; board(); };
    $('xe-voltar').onclick = undo;
    $('xe-desistir').onclick = () => modal('Encerrar esta partida?', '<p>A Emily vence por desistência.</p><button id="xe-confirmar">Desistir</button>', c => {
      c.querySelector('#xe-confirmar').onclick = async () => {closeModal(); if(saving) return; stopped = 'Você desistiu. Emily venceu.'; premove = null; if(await save())audio?.avisar('end');};
    });
    $('xe-ver-resultado').onclick=()=>{resultadoVisto='';renderFim();};
    $('xe-pgn').onclick = () => {
      const blob = new Blob([game.pgn()], {type:'application/x-chess-pgn'}), url = URL.createObjectURL(blob);
      const a = document.createElement('a'); a.href=url; a.download='Emily-xadrez.pgn'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 2000);
    };
    $('xe-retry').onclick = async () => { try { await api('lance',{revisao:state.revisao}); note=''; await poll(); } catch(e){message(e.message);} };
    $('xe-voz').onclick = async () => { try {await api('voz',{ativo:!voice}); voice=!voice; render();} catch(e){message(e.message);} };
    $('xe-form').onsubmit = async e => {
      e.preventDefault(); const text=$('xe-texto').value.trim(); if (!text || enviandoChat) return;
      const edicao=edicaoChat;
      enviandoChat=true; $('xe-enviar').disabled=true;
      try { await api('conversar',{texto:text,voz:voice}); if(edicaoChat===edicao) $('xe-texto').value=''; await poll(); }
      catch(e){$('xe-chat-status').textContent=e.message;}
      finally{enviandoChat=false; $('xe-enviar').disabled=false;}
    };
    $('xe-texto').oninput = () => {edicaoChat++;};
    $('xe-texto').onkeydown = e => { if(e.key==='Enter' && !e.shiftKey && !e.isComposing){e.preventDefault(); if(!$('xe-enviar').disabled) $('xe-form').requestSubmit();} };
    const b=$('xe-board'); b.onpointerdown=startPointer; b.onpointermove=movePointer; b.onpointerup=endPointer; b.oncontextmenu=e=>e.preventDefault(); b.onpointercancel=cancelDrag; b.onlostpointercapture=cancelDrag;
    b.onmousedown=cancelarArrastoDireito;
    document.addEventListener('mouseup',e=>{if(e.button===0 && arrastoCancelado){arrastoCancelado=false;setTimeout(()=>{skipClick=false;},0);}});
    window.addEventListener('blur',()=>{cancelDrag();arrastoCancelado=false;skipClick=false;});
    b.onclick = e => { if(skipClick) return; const square=e.target.closest('[data-square]')?.dataset.square; if(square) markSquare(square); };
    document.addEventListener('keydown', e => { if(open && e.key==='Escape'){inputSerial++;cancelDrag();selected=null;premove=null;clearAnnotations();closeModal();if($('xe-fim'))$('xe-fim').hidden=true;board();} });
    mounted=true;
  }
  function modal(title, html, setup) {
    cancelDrag(); $('xe-modal').hidden=false;
    $('xe-modal').innerHTML=`<section role="dialog" aria-modal="true" aria-label="${esc(title)}"><h3>${esc(title)}</h3>${html}<button class="xe-button" id="xe-cancelar">Cancelar</button></section>`;
    $('xe-cancelar').onclick=closeModal; setup($('xe-modal')); $('xe-modal').querySelector('button')?.focus();
  }
  function closeModal(){if($('xe-modal')){$('xe-modal').hidden=true;$('xe-modal').innerHTML='';} lockPromotion=false;}
  async function nova(cor) {
    if(saving) return;
    game=new window.EmilyChessRules.Chess(); stopped=''; selected=null;premove=null;lastTime='';clearAnnotations();
    state.posicao={cor}; flipped=cor==='b';
    if(await save(true)) { chatHash=''; render(); audio?.avisar('start'); await ensureMove(); }
  }
  async function undo() {
    if(saving || !game.history().length) return;
    stopped=''; premove=null; selected=null;clearAnnotations();
    // Return to the player's previous decision, including an in-flight reply.
    game.undo(); if(game.turn() !== state.posicao.cor && game.history().length) game.undo();
    if(await save()) await ensureMove();
  }
  function status() {
    if(!state?.posicao?.fen) return 'Preparando o tabuleiro…';
    if(note) return note;
    if(stopped || game.isGameOver()) return stopped || resultado();
    const l=state.lance;
    if(l.estado==='preparando') return l.detalhe || 'Preparando apoio tático…';
    if(l.estado==='erro') return l.erro;
    if(l.estado==='reconectando') return 'Reconectando ao Sol… Seu tabuleiro está preservado.';
    if(premove) return `Pré-lance ${premove.from} → ${premove.to} preparado. Clique direito para cancelar.`;
    if(game.turn() !== state.posicao.cor) return 'A Emily está pensando no próximo lance…';
    return game.isCheck() ? 'Você está em xeque. Sua vez.' : 'Sua vez. Escolha um lance.';
  }
  function render() {
    if(!mounted || !game || !state) return;
    board();renderPlayers();renderFim(); $('xe-cor').textContent=state.posicao?.cor==='b' ? 'Pretas' : 'Brancas';
    $('xe-status').textContent=status();
    const nivel=state.dificuldade || 'casual';
    $('xe-dificuldade').textContent=({casual:'Casual',equilibrado:'Equilibrado',desafiador:'Desafiador',sol:'Só Sol · sem apoio'}[nivel])+' ▾';
    $('xe-niveis').querySelectorAll('[data-nivel]').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.nivel===nivel)));
    $('xe-dificuldade').disabled=saving;
    $('xe-retry').hidden=state.lance.estado!=='erro' || Boolean(stopped) || game.isGameOver();
    $('xe-voltar').disabled=saving || !game.history().length;
    $('xe-desistir').disabled=saving || Boolean(stopped) || game.isGameOver();
    $('xe-ver-resultado').hidden=!(stopped || game.isGameOver());
    $('xe-som').disabled=!audio?.supported;
    $('xe-sons-locais').disabled=!audio?.supported || !audio?.tiposLocais.length;
    $('xe-config-som').disabled=!audio?.supported;
    $('xe-sons-locais').setAttribute('aria-pressed',String(Boolean(audio?.personalizado)));

    $('xe-som').setAttribute('aria-pressed',String(Boolean(audio?.ativo)));
    $('xe-som').title=!audio?.supported ? 'Áudio indisponível neste dispositivo' : audio.ativo ? 'Silenciar sons do tabuleiro' : 'Ativar sons do tabuleiro';
    $('xe-nova').disabled=saving; $('xe-voz').setAttribute('aria-pressed',String(voice));
    $('xe-chat-status').textContent=state.conversa.estado==='erro' ? state.conversa.erro : state.conversa.estado==='pensando' ? 'Emily está respondendo…' : (state.aviso_voz || '');
    $('xe-enviar').disabled=enviandoChat;
    $('xe-tempo').textContent=lastTime ? '· último lance '+lastTime+' s' : '';
    const history=game.history();
    $('xe-lances').innerHTML=history.map((m,i)=>i%2===0 ? `<span class="xe-numero">${i/2+1}.</span><span>${esc(m)}</span>` : `<span>${esc(m)}</span>`).join('');
    const h=JSON.stringify(state.mensagens);
    if(chatHash!==h){
      chatHash=h;
      $('xe-mensagens').innerHTML=state.mensagens.length ? state.mensagens.map(m=>`<article class="xe-msg ${m.role==='user'?'user':'emily'}"><strong>${m.role==='user'?'Você':'Emily'}</strong><p>${esc(m.content)}</p></article>`).join('') : `<div class="xe-boas">${avatar}<h3>Sua próxima jogada?</h3><p>Pode conversar comigo enquanto eu penso. Vamos jogar sem pressa.</p></div>`;
      $('xe-mensagens').scrollTop=$('xe-mensagens').scrollHeight;
    }
  }
  function renderPlayers(){
    const ready=Boolean(state.posicao?.fen),ended=Boolean(stopped)||game.isGameOver();
    const values={p:1,n:3,b:3,r:5,q:9,k:0},pieces=game.board().flat().filter(Boolean);
    const points=c=>pieces.filter(p=>p.color===c).reduce((sum,p)=>sum+values[p.type],0);
    const history=game.history({verbose:true});
    for(const who of ['voce','emily']){
      const color=who==='voce'?(state.posicao?.cor||'w'):(state.posicao?.cor==='b'?'w':'b');
      const active=ready && !ended && game.turn()===color;
      $('xe-jogador-'+who).classList.toggle('tem-vez',active);
      $('xe-turno-'+who).textContent=!ready?'Preparando':ended?'Partida encerrada':active?(who==='voce'?'Sua vez':'Vez da Emily'):'Aguardando';
      $('xe-turno-'+who).classList.toggle('ativo',active);
      const enemy=color==='w'?'b':'w', captured=history.filter(m=>m.color===color && m.captured).map(m=>m.captured);
      const advantage=points(color)-points(enemy);
      const groups=['p','n','b','r','q'].map(t=>{
        const count=captured.filter(c=>c===t).length;if(!count)return '';
        return `<span class="xe-captura-grupo" title="${count} × ${names[t]}" aria-label="${count} ${names[t]} capturado${count>1?'s':''}">${Array.from({length:count},()=>piece({type:t,color:enemy})).join('')}</span>`;
      }).join('');
      const label=who==='voce'?'Você':'Emily';
      const material=$('xe-material-'+who);
      const html=groups+(advantage>0?`<span class="xe-vantagem" title="Vantagem de ${advantage} pontos em material">+${advantage}</span>`:'');
      if(material.innerHTML!==html)material.innerHTML=html;
      material.setAttribute('aria-label',`${label}: ${captured.length} peças capturadas; ${points(color)} pontos de material restante${advantage>0?`; vantagem de ${advantage} pontos`:''}.`);
      material.title='Material: peão 1 · cavalo 3 · bispo 3 · torre 5 · dama 9. O total considera promoções e não mede a posição.';

    }
  }
  function board() {
    if(dragging) return;
    const b=$('xe-board'); if(!b || !game) return;
    const focused=document.activeElement?.closest('[data-square]')?.dataset.square;
    const hash=JSON.stringify([game.fen(),stopped,selected,premove,flipped,[...marked]]);
    if(hash===boardHash) return; boardHash=hash;
    const files=flipped ? 'hgfedcba' : 'abcdefgh', ranks=flipped ? '12345678' : '87654321';
    const moves=selected && game.turn()===state.posicao?.cor ? game.moves({square:selected,verbose:true}).map(m=>m.to) : [];
    const prev=game.history({verbose:true}).at(-1);
    b.innerHTML=[...ranks].flatMap((rank,ri)=>[...files].map((file,fi)=>{
      const sq=file+rank, p=game.get(sq), dark=(file.charCodeAt(0)-97+Number(rank))%2===1;
      const check=game.isCheck() && p?.type==='k' && p.color===game.turn();
      return `<button type="button" data-square="${sq}" class="xe-square ${dark?'dark':'light'} ${sq===selected?'selected':''} ${moves.includes(sq)?'legal':''} ${prev && [prev.from,prev.to].includes(sq)?'last':''} ${premove && [premove.from,premove.to].includes(sq)?'premove':''} ${check?'check':''} ${marked.has(sq)?'marked':''}" aria-label="${sq}${p?', '+names[p.type]+(p.color==='w'?' branco':' preto'):''}">${p?piece(p):''}${p?.type==='k'?seloRei(p.color):''}${fi===0?'<small class="rank">'+rank+'</small>':''}${ri===7?'<small class="file">'+file+'</small>':''}</button>`;
    })).join('');
    drawAnnotations();
    if(focused) b.querySelector(`[data-square="${focused}"]`)?.focus({preventScroll:true});
  }
  function fimPartida(){
    if(!stopped && !game.isGameOver())return null;
    const vencedor=stopped ? (state.posicao.cor==='w'?'b':'w') : game.isCheckmate() ? (game.turn()==='w'?'b':'w') : null;
    const motivo=stopped?'Por desistência':game.isCheckmate()?'Por xeque-mate':game.isStalemate()?'Por afogamento':game.isThreefoldRepetition()?'Por repetição de posição':game.isInsufficientMaterial()?'Por material insuficiente':'Pela regra dos 50 lances';
    return {vencedor,motivo,titulo:!vencedor?'Empate':vencedor===state.posicao.cor?'Você venceu!':'Emily venceu',tipo:stopped?'desistencia':game.isCheckmate()?'mate':game.isStalemate()?'afogamento':'empate'};
  }
  function iconeFim(tipo){
    const paths={coroa:'<path d="m3 6 4 4 5-7 5 7 4-4-2 13H5z"/>',bandeira:'<path d="M6 21V3m0 1c5-4 7 4 12 0v10c-5 4-7-4-12 0"/>',mate:'<path d="m6 6 12 12M18 6 6 18"/>',empate:'<path d="M5 9h14M5 15h14"/>',afogamento:'<circle cx="12" cy="12" r="8"/><path d="M8 12h8"/>'};
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[tipo]}</svg>`;
  }
  function seloRei(color){
    const fim=fimPartida();if(!fim)return '';
    const venceu=fim.vencedor===color,tipo=venceu?'coroa':fim.tipo==='desistencia'?'bandeira':fim.tipo;
    return `<span class="xe-selo-rei ${venceu?'vencedor':fim.vencedor?'derrotado':'empate'}" title="${esc(venceu?'Vencedor':fim.motivo)}">${iconeFim(tipo)}</span>`;
  }
  function renderFim(){
    const box=$('xe-fim'),fim=fimPartida();if(!box)return;
    if(!fim){resultadoVisto='';box.hidden=true;box.innerHTML='';return;}
    const key=state.id+game.fen()+stopped;
    if(saving || resultadoVisto===key)return;
    resultadoVisto=key;cancelDrag();premove=null;box.hidden=false;
    box.innerHTML=`<section class="xe-fim-card" role="dialog" aria-label="Resultado da partida"><button class="xe-fim-fechar" aria-label="Fechar resultado">×</button><div class="xe-fim-emblema">${iconeFim(fim.vencedor?'coroa':fim.tipo)}</div><h3>${esc(fim.titulo)}</h3><p>${esc(fim.motivo)}</p><div class="xe-fim-jogadores"><div class="${fim.vencedor && fim.vencedor!==state.posicao.cor?'ganhou':''}">${avatar}<strong>Emily</strong></div><span>×</span><div class="${fim.vencedor===state.posicao.cor?'ganhou':''}"><span class="xe-avatar xe-voce">V</span><strong>Você</strong></div></div><div class="xe-fim-acoes"><button class="xe-button acento" id="xe-revanche">Revanche</button><button class="xe-button" id="xe-fim-nova">Nova partida</button></div><button class="xe-fim-ver">Ver tabuleiro</button></section>`;
    const close=()=>{box.hidden=true;};
    box.querySelector('.xe-fim-fechar').onclick=close;box.querySelector('.xe-fim-ver').onclick=close;
    $('xe-revanche').onclick=async()=>{const cor=state.posicao.cor==='w'?'b':'w';close();await nova(cor);};
    $('xe-fim-nova').onclick=()=>{close();$('xe-nova').click();};
    if(document.activeElement!==$('xe-texto'))box.querySelector('.xe-fim-fechar').focus({preventScroll:true});
  }
  function available(){return !stopped && !game.isGameOver() && !lockPromotion;}
  function markSquare(sq){
    if(marked.has(sq))marked.delete(sq);else marked.add(sq);
    boardHash='';board();
  }
  function clearAnnotations(){arrows=[];marked.clear();drawing=null;}
  function center(sq){
    const file=sq.charCodeAt(0)-97, rank=Number(sq[1])-1;
    return flipped?[(7-file)*100+50,rank*100+50]:[file*100+50,(7-rank)*100+50];
  }
  function drawAnnotations(){
    const b=$('xe-board');if(!b)return;
    b.querySelector('.xe-annotations')?.remove();
    const all=arrows;
    const lines=all.map(a=>{
      const [x,y]=center(a.from),[u,v]=center(a.to),dx=u-x,dy=v-y;
      // Cotovelo deixa setas de cavalo tão legíveis quanto as retas.
      const knight=(Math.abs(dx)===100 && Math.abs(dy)===200)||(Math.abs(dx)===200 && Math.abs(dy)===100);
      const len=Math.hypot(dx,dy);
      const ex=knight ? (Math.abs(dy)>Math.abs(dx)?u-Math.sign(dx)*48:u) : u-dx/len*48;
      const ey=knight ? (Math.abs(dx)>Math.abs(dy)?v-Math.sign(dy)*48:v) : v-dy/len*48;
      const middle=knight?(Math.abs(dy)>Math.abs(dx)?` L ${x} ${ey}`:` L ${ex} ${y}`):'';
      return `<path data-arrow="${a.from}-${a.to}" d="M ${x} ${y}${middle} L ${ex} ${ey}" marker-end="url(#xe-arrowhead)"/>`;
    }).join('');
    b.insertAdjacentHTML('beforeend',`<svg class="xe-annotations" viewBox="0 0 800 800" aria-hidden="true"><defs><marker id="xe-arrowhead" markerUnits="userSpaceOnUse" markerWidth="56" markerHeight="56" refX="0" refY="28" orient="auto"><path d="M0 0 L48 28 L0 56z"/></marker></defs>${lines}</svg>`);
  }
  function cancelarArrastoDireito(e){
    if(e.button!==2 || !dragging)return false;
    e.preventDefault();inputSerial++;arrastoCancelado=true;skipClick=true;
    cancelDrag();premove=null;selected=null;clearAnnotations();board();return true;
  }
  function startPointer(e){
    if(cancelarArrastoDireito(e))return;
    const sq=e.target.closest('[data-square]')?.dataset.square;
    if(e.button===2 && sq){
      e.preventDefault();inputSerial++;cancelDrag();premove=null;selected=null;note='';board();$('xe-status').textContent=status();
      drawing={from:sq,to:sq,id:e.pointerId};$('xe-board').setPointerCapture(e.pointerId);return;
    }
    startDrag(e);
  }
  function movePointer(e){
    if(drawing){
      e.preventDefault();drawing.to=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-square]')?.dataset.square;
      return;
    }moveDrag(e);
  }
  function endPointer(e){
    if(drawing){
      const d=drawing;drawing=null;
      if(d.to && d.from!==d.to){const i=arrows.findIndex(a=>a.from===d.from && a.to===d.to);if(i<0)arrows.push({from:d.from,to:d.to});else arrows.splice(i,1);}
      else {clearAnnotations();boardHash='';board();}
      if($('xe-board').hasPointerCapture(d.id))$('xe-board').releasePointerCapture(d.id);
      drawAnnotations();return;
    }endDrag(e);
  }
  function possiblePremove(from,to){
    const p=game.get(from),dest=game.get(to);if(!p || dest?.color===p.color)return false;
    const dx=to.charCodeAt(0)-from.charCodeAt(0),dy=Number(to[1])-Number(from[1]),x=Math.abs(dx),y=Math.abs(dy);
    if(p.type==='n')return x*y===2;
    if(p.type==='k')return Math.max(x,y)===1 || (y===0 && x===2 && from[0]==='e' && ['1','8'].includes(from[1]));
    if(p.type==='p'){const dir=p.color==='w'?1:-1;return (x===1 && dy===dir) || (x===0 && (dy===dir || dy===2*dir && from[1]===(p.color==='w'?'2':'7')));}
    return (p.type==='b' && x===y)||(p.type==='r' && (x===0 || y===0))||(p.type==='q' && (x===y || x===0 || y===0));
  }
  function act(from,to,promotion,dragDrop=false){
    if(!available() || from===to) {board();return;}
    const p=game.get(from); if(p?.color!==state.posicao.cor){board();return;}
    if(game.turn()!==state.posicao.cor){
      if(!possiblePremove(from,to)){message('Essa peça não pode fazer esse pré-lance.');board();return;}
      note='';
      // A pre-move is a proposal; it is revalidated after the opponent moves.
      premove={from,to,promotion:promotion || 'q'};board();$('xe-status').textContent=status();return;
    }
    if(saving){
      // O adversário já apareceu no tabuleiro, mas a ponte ainda salva o lance.
      // Aceitar o arraste agora evita perder uma jogada legítima nessa janela.
      const fen=game.fen(),id=state.id,serial=++inputSerial;
      saveDone.then(()=>{if(open && serial===inputSerial && state.id===id && game.fen()===fen)act(from,to,promotion,dragDrop);});
      return;
    }
    const legal=game.moves({square:from,verbose:true}).filter(m=>m.to===to);
    if(!legal.length){message('Esse lance não é válido nesta posição.');board();return;}
    if(legal.some(m=>m.promotion) && !promotion){
      lockPromotion=true;
      modal('Promover peão', '<div class="xe-promocao">'+['q','r','b','n'].map(t=>`<button data-promotion="${t}" aria-label="${names[t]}">${piece({type:t,color:state.posicao.cor})}</button>`).join('')+'</div>', c=>{
        c.querySelectorAll('[data-promotion]').forEach(b=>b.onclick=()=>{const t=b.dataset.promotion;closeModal();act(from,to,t,dragDrop);});
      });return;
    }
    applyMove({from,to,...(promotion?{promotion}:{})},dragDrop);
  }
  async function applyMove(move,dragDrop=false){
    if(saving) return;
    note='';
    let committed;
    try {committed=game.move(move);} catch(_){message('O lance deixou de ser válido. O tabuleiro foi preservado.');board();return;}
    selected=null;clearAnnotations();
    render();
    if(!dragDrop) animate(move);
    audio?.aoLance(committed,game);
    if(await save()) await ensureMove();
  }
  function animate(m){
    const dest=$('xe-board').querySelector(`[data-square="${m.to}"] .xe-peca`), src=$('xe-board').querySelector(`[data-square="${m.from}"]`);
    if(!dest || !src || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const a=src.getBoundingClientRect(),b=dest.getBoundingClientRect();
    dest.animate([{transform:`translate(${a.x-b.x}px,${a.y-b.y}px)`},{transform:'translate(0,0)'}],{duration:230,easing:'ease-out'});
  }
  function startDrag(e){
    if(e.button!==0 || !available())return;
    const sq=e.target.closest('[data-square]')?.dataset.square, p=sq && game.get(sq);
    if(!p || p.color!==state.posicao.cor)return;
    dragging={from:sq,x:e.clientX,y:e.clientY,moved:false,id:e.pointerId,origin:e.target.closest('[data-square]'),frame:0};
    $('xe-board').setPointerCapture(e.pointerId);
  }
  function positionGhost(){
    if(!ghost || !dragging)return;
    ghost.style.transform=`translate3d(${dragging.x}px,${dragging.y}px,0) translate(-50%,-50%)`;
    dragging.frame=0;
  }
  function moveDrag(e){
    if(!dragging)return;
    if(!dragging.moved && Math.hypot(e.clientX-dragging.x,e.clientY-dragging.y)<3)return;
    e.preventDefault();dragging.moved=true;dragging.x=e.clientX;dragging.y=e.clientY;
    if(!ghost){
      ghost=document.createElement('div');ghost.className='xe-ghost';ghost.setAttribute('aria-hidden','true');
      ghost.innerHTML=piece(game.get(dragging.from));ghost.style.width=dragging.origin.getBoundingClientRect().width+'px';
      dragging.origin.classList.add('drag-origin');document.body.classList.add('xe-dragging');
      document.body.append(ghost);positionGhost();
    } else if(!dragging.frame) dragging.frame=requestAnimationFrame(positionGhost);
  }
  function endDrag(e){
    if(!dragging)return;
    const d=dragging;const target=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-square]')?.dataset.square;
    cancelDrag();
    skipClick=true;setTimeout(()=>{skipClick=false;},0);
    if(d.moved){e.preventDefault();selected=null;if(target)act(d.from,target,undefined,true);else board();}
    else markSquare(d.from);
  }
  function cancelDrag(){
    if(drawing){const id=drawing.id;drawing=null;if($('xe-board')?.hasPointerCapture(id))$('xe-board').releasePointerCapture(id);drawAnnotations();}
    if(dragging){
      if(dragging.frame)cancelAnimationFrame(dragging.frame);
      dragging.origin?.classList.remove('drag-origin');
      if($('xe-board').hasPointerCapture(dragging.id))$('xe-board').releasePointerCapture(dragging.id);
    }
    document.body.classList.remove('xe-dragging');dragging=null;ghost?.remove();ghost=null;
  }
  async function ensureMove(){
    if(!open || saving || !state?.posicao || stopped || game.isGameOver() || game.turn()===state.posicao.cor) return;
    if(['pensando','reconectando','preparando','escolhido','erro'].includes(state.lance.estado))return;
    try {await api('lance',{revisao:state.revisao});} catch(e){message(e.message);}
  }
  async function poll(){
    if(!open || polling || saving || lockPromotion || dragging || drawing) return;
    polling=true;
    try{
      const requested=[state.id,state.revisao];
      const r=await api('estado');
      if(!open || saving || dragging || drawing || lockPromotion || requested[0]!==state.id || requested[1]!==state.revisao)return;
      if(r.estado.revisao!==state.revisao || r.estado.id!==state.id) restaurar(r.estado);
      else state=r.estado;
      if(state.lance.estado==='escolhido' && state.lance.revisao===state.revisao){
        const u=state.lance.uci, move={from:u.slice(0,2),to:u.slice(2,4),...(u[4]?{promotion:u[4]}:{})};
        const valid=game.moves({verbose:true}).some(m=>m.from+m.to+(m.promotion||'')===u);
        if(!valid){message('A sugestão do Sol não corresponde ao tabuleiro. Volte um lance ou comece uma nova partida.');return;}
        lastTime=String(state.lance.segundos);
        // Saving acknowledges this suggestion so polling cannot play it twice.
        const committed=game.move(move); selected=null;clearAnnotations();
        render();animate(move);audio?.aoLance(committed,game);
        if(await save()){
          if(premove){const queued=premove,id=state.id,rev=state.revisao;
            setTimeout(()=>{
              if(!open || premove!==queued || id!==state.id || rev!==state.revisao)return;
              premove=null;
              const valid=game.moves({verbose:true}).some(m=>m.from===queued.from && m.to===queued.to && (!m.promotion || m.promotion===queued.promotion));
              if(valid)act(queued.from,queued.to,queued.promotion);
              else {message('Pré-lance cancelado: a posição mudou e ele deixou de ser válido.');board();}
            },260);
          }
        }
      }
      render();await ensureMove();await api('comentar',{revisao:state.revisao});
    }catch(e){message(e.message);}finally{polling=false;}
  }
  async function abrir(){
    if(!window.EmilyChessRules){message('As regras de xadrez não carregaram. Reinicie a Emily.');return;}
    if(opening) return; opening=true;
    if(typeof ESTADO !== 'undefined' && !['chat','inicio'].includes(ESTADO.tela) && typeof irPara === 'function') irPara(ESTADO.cid ? 'chat' : 'inicio');
    if(!mounted)mount();
    if(typeof fecharPainelNavegador==='function')fecharPainelNavegador(false);
    $('xadrez-painel').hidden=false;document.body.classList.add('xadrez-aberto');$('btn-xadrez').setAttribute('aria-expanded','true');open=true;
    try{
      await api('visibilidade',{ativo:true,serial:Date.now()*1000+(++viewSerial)});
      await saveDone;
      if(!open)return;
      restaurar((await api('estado')).estado);
      if(!state.posicao){state.posicao={cor:'w'};if(await save(true))audio?.avisar('start');}
      else {state=(await api('contexto',{posicao:posicao(),revisao:state.revisao})).estado;}
      message(state.aviso || '');render();await ensureMove();await api('comentar',{revisao:state.revisao});
      clearInterval(timer);timer=setInterval(poll,650);
    }catch(e){message(e.message);}finally{opening=false;}
  }
  function fechar(){inputSerial++;api('visibilidade',{ativo:false,serial:Date.now()*1000+(++viewSerial)}).catch(()=>{});audio?.stop();open=false;clearInterval(timer);cancelDrag();closeModal();$('xadrez-painel').hidden=true;document.body.classList.remove('xadrez-aberto');$('btn-xadrez').setAttribute('aria-expanded','false');}
  window.EmilyXadrez={abrir,fechar};
  $('btn-xadrez').onclick=()=>{audio?.wake();return open?fechar():abrir();};
  $('btn-navegador-interno').addEventListener('click',()=>{if(open)fechar();});
  ['btn-inicio','btn-config','btn-music','btn-cloud','btn-nova','btn-nova-conversa','btn-novo','btn-code','conversas'].forEach(id=>$(id)?.addEventListener('click',()=>{if(open)fechar();}));
})();
