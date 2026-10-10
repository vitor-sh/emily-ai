/* Interface móvel; todos os comandos continuam na sessão de áudio nativa. */
(()=>{
 const svg=paths=>`<svg viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
 const icons={home:svg('<path d="m3 10 9-7 9 7M5 9v12h14V9"/>'),search:svg('<circle cx="10" cy="10" r="7"/><path d="m16 16 5 5"/>'),library:svg('<path d="M4 3v18M10 3v18M16 4l4 16"/>'),plus:svg('<path d="M12 4v16M4 12h16"/>'),down:svg('<path d="m5 9 7 7 7-7"/>'),list:svg('<path d="M8 6h13M8 12h13M8 18h13M3 6h1M3 12h1M3 18h1"/>'),heart:svg('<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>')};
 const label=n=>n==='default'?'Minha seleção':n==='__locais__'?'Músicas locais':n==='__avulsa__'?'Reprodução avulsa':n||'Emily Music';
 const root=$('.emusic');
 const settings=document.createElement('button');settings.id='mobile-settings';settings.type='button';settings.setAttribute('aria-label','Configurações');settings.title='Configurações';
 settings.innerHTML=svg('<path d="m9.5 3-.7 2.4-2 .9-2.3-.7-2 3.4 1.7 1.7v2.6L2.5 15l2 3.4 2.3-.7 2 .9.7 2.4h5l.7-2.4 2-.9 2.3.7 2-3.4-1.7-1.7v-2.6l1.7-1.7-2-3.4-2.3.7-2-.9L14.5 3Z"/><circle cx="12" cy="12" r="3"/>');
 settings.onclick=()=>window.EmilyAndroid?.settings();$('.emusic-top').append(settings);

 const nav=document.createElement('nav');nav.className='mobile-bottom-nav';nav.setAttribute('aria-label','Navegação do Music');
 nav.innerHTML=`<button data-mobile-tab="inicio">${icons.home}<span>Início</span></button><button data-mobile-tab="busca">${icons.search}<span>Buscar</span></button><button data-mobile-tab="biblioteca">${icons.library}<span>Biblioteca</span></button><button id="mobile-create">${icons.plus}<span>Criar</span></button>`;root.append(nav);
 nav.querySelectorAll('[data-mobile-tab]').forEach(b=>b.onclick=()=>{EmilyMusic.go(b.dataset.mobileTab);if(b.dataset.mobileTab==='busca')$('#pl-query').focus();});$('#mobile-create').onclick=()=>abrirModalPlaylist('',{});
 const mini=document.createElement('div');mini.id='mobile-mini';mini.hidden=true;
 mini.innerHTML='<button id="mobile-mini-open" aria-label="Abrir música tocando"><span class="mini-art">♫<img alt="" hidden></span><span class="mini-info"><strong></strong><small></small></span></button><button id="mobile-mini-prev" class="pbtn" aria-label="Música anterior"><svg viewBox="0 0 24 24"><path d="M6 5v14M18 5 8 12l10 7Z"/></svg></button><button id="mobile-mini-play" class="pbtn" aria-label="Tocar"></button><button id="mobile-mini-next" class="pbtn" aria-label="Próxima música"><svg viewBox="0 0 24 24"><path d="M18 5v14M6 5l10 7-10 7Z"/></svg></button><div class="mini-progress"><i></i></div>';
 const outputIcon=svg('<path d="M4 15v-3a8 8 0 0 1 16 0v3M4 13h3v7H4zM17 13h3v7h-3z"/>');
 function outputButton(){const b=document.createElement('button');b.className='music-output-button';b.innerHTML=outputIcon+'<span>Este telefone</span><span aria-hidden="true">⌄</span>';b.onclick=()=>window.EmilyAndroid?.outputs();return b;}
 const miniOutput=outputButton();miniOutput.hidden=true;mini.append(miniOutput);
 $('#music-dock').append(mini);
 const full=document.createElement('section');full.id='mobile-now';full.hidden=true;full.setAttribute('aria-label','Música tocando');
 full.innerHTML=`<header class="mobile-now-head"><button id="mobile-now-close" aria-label="Recolher música">${icons.down}</button><div><small>TOCANDO DA PLAYLIST</small><strong id="mobile-now-source"></strong></div><button id="mobile-now-queue" aria-label="Abrir fila">${icons.list}</button></header><div id="mobile-now-player"></div><div class="mobile-now-extra"><button id="mobile-now-like">${icons.heart}<span>Curtir</span></button><span id="mobile-now-download"></span><button id="mobile-now-add">${icons.plus}<span>Adicionar</span></button><button id="mobile-now-lyrics">♫<span>Letras</span></button></div>`;root.append(full);$('#mobile-now-player').after(outputButton());
 const options=document.createElement('dialog');options.id='mobile-track-options';options.setAttribute('aria-labelledby','mobile-options-title');
 options.innerHTML='<header><h2 id="mobile-options-title"></h2><button aria-label="Fechar opções" id="mobile-options-close">×</button></header><div class="mobile-track-actions"></div>';
 document.body.append(options);let optionsAnchor=null;
 function closeOptions(){if(!options.open)return;options.close();if(optionsAnchor?.isConnected)optionsAnchor.focus();}
 $('#mobile-options-close').onclick=closeOptions;options.addEventListener('cancel',e=>{e.preventDefault();closeOptions();});
 options.addEventListener('click',e=>{if(e.target===options){const b=options.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)closeOptions();}else if(e.target.closest('.music-track-action'))closeOptions();});
 const resize=new ResizeObserver(()=>{if(root.clientHeight>0)root.style.setProperty('--music-height',root.clientHeight+'px');});resize.observe(root);
 let focused=null;
 const mobile=window.MusicMobile={
  open(){if(!Player._faixaAtual)return;focused=document.activeElement;$('#mobile-now-player').append($('#player-barra'));$('#player-barra').hidden=false;full.hidden=false;root.classList.add('now-expanded');[...root.children].forEach(el=>{if(el!==full)el.inert=true;});this.update();$('#mobile-now-close').focus();},
  close(){if(full.hidden)return;full.hidden=true;root.classList.remove('now-expanded');[...root.children].forEach(el=>el.inert=false);focused?.isConnected&&focused.focus();},
  back(){if(options.open){closeOptions();return true;}if($('.music-add-menu')){$('.music-add-menu').remove();return true;}if(!$('#pl-modal-overlay')?.hidden){fecharModalPlaylist();return true;}if(!full.hidden){this.close();return true;}if(['playlist','favoritas','fila','letras'].includes(EmilyMusic.tab)){EmilyMusic.go('biblioteca');return true;}if(EmilyMusic.tab==='busca'){EmilyMusic.go('inicio');return true;}return false;},
  update(){miniOutput.hidden=nativeState.external_output!==true;document.querySelectorAll('.music-output-button').forEach(b=>{const n=nativeState.output||'Este telefone';b.querySelector('span').textContent=n;b.setAttribute('aria-label','Escolher saída de áudio. Atual: '+n);});const m=Player._faixaAtual;mini.hidden=!m;if(!m){this.close();return;}
   const art=EmilyMusic.offline.faixas[m.video_id]?.thumb||m.thumb||'';
   const img=mini.querySelector('img');if(img.getAttribute('src')!==art){img.src=art;img.hidden=!art;}
   mini.querySelector('strong').textContent=m.titulo;mini.querySelector('small').textContent=nativeState.buffering?'Carregando…':(m.source_title||label(m.origem||Player._playlistAtivaSalva));
   const button=$('#mobile-mini-play');button.innerHTML=svg(Player.tocando?'<path d="M8 5v14M16 5v14"/>':'<path d="m8 5 11 7-11 7Z"/>');button.setAttribute('aria-label',Player.tocando?'Pausar':'Tocar');
   $('#player-sub').textContent=(m.source_title||label(m.origem||Player._playlistAtivaSalva))+(m.video_id.startsWith('local_')?' • Arquivo local':' • YouTube');
   $('#mobile-now .mobile-now-head small').textContent=Player._playlistAtivaSalva==='__avulsa__'?'TOCANDO DA BUSCA':'TOCANDO DA PLAYLIST';
   $('#mobile-now-source').textContent=Player._filaFavoritas?'Músicas curtidas':(m.source_title||label(m.origem||Player._playlistAtivaSalva));
   $('#mobile-mini-prev').disabled=Player.playlist.length<1;$('#mobile-mini-next').disabled=Player.playlist.length<2;
   const liked=!!_playlistsGeral.favoritos[m.video_id];
   const downloadKey=m.video_id+JSON.stringify(EmilyMusic.offline.faixas[m.video_id]||{})+EmilyMusic.online()+EmilyMusic.saved(m.video_id);
   const downloadSlot=$('#mobile-now-download');if(downloadSlot.dataset.key!==downloadKey){downloadSlot.replaceChildren();EmilyMusic.downloadButton(m,downloadSlot);const control=downloadSlot.firstElementChild;if(control){const text=document.createElement('span');const state=EmilyMusic.offline.faixas[m.video_id];text.textContent=state?.estado==='pronto'?'Baixada':state?.estado==='baixando'?EmilyMusic.downloadProgressText(state):state?.estado==='fila'?'Na fila':'Baixar';control.querySelector('small')?.remove();control.append(text);}downloadSlot.dataset.key=downloadKey;}

   $('#mobile-now-like').classList.toggle('ativo',liked);$('#mobile-now-like').setAttribute('aria-pressed',String(liked));$('#mobile-now-like span').textContent=liked?'Curtida':'Curtir';
   $('#player-loop').setAttribute('aria-label',$('#player-loop').title);$('#player-shuffle').setAttribute('aria-label',$('#player-shuffle').title);
  },
  progress(){const pct=nativeState.duracao>0?Math.min(100,100*nativeState.posicao/nativeState.duracao):0;mini.querySelector('.mini-progress i').style.width=pct+'%';}
 };
 $('#mobile-mini-prev').onclick=()=>Player.anterior();$('#mobile-mini-next').onclick=()=>Player.proxima();
 $('#mobile-mini-open').onclick=()=>mobile.open();$('#mobile-mini-play').onclick=()=>$('#player-play').click();
 $('#mobile-now-close').onclick=()=>mobile.close();$('#mobile-now-queue').onclick=()=>{mobile.close();EmilyMusic.go('fila');};
 $('#mobile-now-lyrics').onclick=()=>{mobile.close();EmilyMusic.go('letras');};
 $('#mobile-now-add').onclick=e=>EmilyMusic.addMenu(Player._faixaAtual,e.currentTarget);
 $('#mobile-now-like').onclick=async()=>{const id=Player._faixaAtual?.video_id;if(!id)return;if(await EmilyMusic.favorite(Player._faixaAtual,!_playlistsGeral.favoritos[id])){await EmilyMusic.refresh();EmilyMusic.renderSearch();window.PlaylistSearch?.renderResults();window.MusicListeningUI?.render();mobile.update();EmilyMusic.animateLike(id);}else toast('Não foi possível salvar a curtida');};
 $('#player-faixa').onclick=()=>{};$('#player-faixa').title='Música tocando';$('#player-faixa').setAttribute('tabindex','-1');
 const paint=Player._pintaControles.bind(Player);Player._pintaControles=()=>{paint();mobile.update();};
 const time=Player._atualizarTempo.bind(Player);Player._atualizarTempo=()=>{time();mobile.progress();};
 const go=EmilyMusic.go.bind(EmilyMusic);EmilyMusic.go=tab=>{closeOptions();mobile.close();root.dataset.mobileView=tab;go(tab);$('#mobile-now-player').append($('#player-barra'));nav.querySelectorAll('[data-mobile-tab]').forEach(b=>{const active=b.dataset.mobileTab===tab||(b.dataset.mobileTab==='biblioteca'&&['playlist','favoritas','fila','letras'].includes(tab));b.classList.toggle('active',active);b.setAttribute('aria-current',active?'page':'false');});$('.emusic-content').scrollTop=0;};
 const pinIcon=svg('<path d="m8 3 8 0-1 6 3 4v2H6v-2l3-4-1-6ZM12 15v6"/>');
 const home=EmilyMusic.home.bind(EmilyMusic);EmilyMusic.home=()=>{home();if(EmilyMusic.tab==='biblioteca'){
   const hero=$('#music-home .music-hero');hero.innerHTML=`<div><h1>Sua biblioteca</h1><p>Suas playlists, sempre por perto.</p></div><button class="mobile-library-create" aria-label="Criar playlist">${icons.plus}</button>`;hero.querySelector('button').onclick=()=>abrirModalPlaylist('',{});
   const grid=$('#music-home .music-cards');grid.previousElementSibling.textContent='Playlists';
   const cards=[...grid.children];grid.replaceChildren();
   const counts=n=>`${n} ${n===1?'faixa':'faixas'}`;
   const fixed=(kind,title,art,count,fn)=>{const b=document.createElement('button');b.className='music-card library-special library-'+kind;b.dataset.library=kind;b.innerHTML=`<span class="music-art">${art}</span><strong>${title}</strong><small>${pinIcon}<span>${counts(count)}</span></small>`;b.onclick=fn;grid.append(b);};
   const liked=new Set(Object.values(_playlistsGeral.playlists).flatMap(d=>d.musicas).filter(m=>_playlistsGeral.favoritos[m.video_id]).map(m=>m.video_id));
   fixed('liked','Músicas curtidas',icons.heart,liked.size,()=>EmilyMusic.go('favoritas'));
   fixed('local','Músicas locais',svg('<path d="M9 18V5l11-2v13M9 7l11-2"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>'),_playlistsGeral.playlists.__locais__?.musicas.length||0,()=>{EmilyMusic.view='__locais__';EmilyMusic.go('playlist');});
   const entries=Object.entries(_playlistsGeral.playlists).filter(([n])=>n!=='__locais__').sort((a,b)=>Number(!!b[1].pinned)-Number(!!a[1].pinned));
   for(const [n,d] of entries){const index=Object.keys(_playlistsGeral.playlists).filter(n=>n!=='__locais__').indexOf(n);const card=cards[index];if(!card)continue;const row=document.createElement('div');row.className='library-playlist-row';row.dataset.playlist=n;card.classList.add('library-open');if(d.pinned){const mark=document.createElement('span');mark.className='library-pin-marker';mark.innerHTML=pinIcon;card.querySelector('small').prepend(mark);}const pin=document.createElement('button');pin.className='library-pin'+(d.pinned?' active':'');pin.innerHTML=pinIcon;pin.setAttribute('aria-label',(d.pinned?'Desafixar':'Fixar')+' '+label(n));pin.setAttribute('aria-pressed',String(!!d.pinned));pin.title=d.pinned?'Desafixar playlist':'Fixar no topo';pin.onclick=async()=>{pin.disabled=true;try{if(await tenta('playlist_fixar',n,!d.pinned)){await EmilyMusic.refresh();}else toast('Não foi possível salvar a fixação');}finally{pin.disabled=false;}};row.append(card,pin);grid.append(row);}
   const tools=document.createElement('div');tools.className='mobile-local-tools';tools.innerHTML='<button>Encontrar músicas no celular</button><button>Escolher pasta</button>';const buttons=tools.querySelectorAll('button');buttons[0].onclick=()=>EmilyAndroid.permission();buttons[1].onclick=()=>EmilyAndroid.folder();$('#music-home').append(tools);
 }};
 const tracks=EmilyMusic.tracks.bind(EmilyMusic);EmilyMusic.tracks=()=>{
  // Recolhe os controles antes de substituir o cabeçalho da playlist.
  $('.emusic-viewbar>div').append($('#pl-tocar-tudo'),$('#pl-filtro-fav'));tracks();
  const actions=document.createElement('div');actions.className='mobile-playlist-actions';
  [...$('#pl-info').children].filter(el=>el.tagName==='BUTTON').forEach(b=>actions.append(b));
  const shuffle=document.createElement('button');shuffle.className='btn-linha mobile-playlist-shuffle';shuffle.innerHTML=$('#player-shuffle').innerHTML;shuffle.setAttribute('aria-label','Aleatório');shuffle.setAttribute('aria-pressed',String(Player.shuffle));shuffle.classList.toggle('ativo',Player.shuffle);shuffle.onclick=()=>{Player.alternarShuffle();shuffle.setAttribute('aria-pressed',String(Player.shuffle));shuffle.classList.toggle('ativo',Player.shuffle);};actions.append(shuffle,$('#pl-tocar-tudo'),$('#pl-filtro-fav'));$('#pl-info').append(actions);
 };
 const row=EmilyMusic.trackRow.bind(EmilyMusic);EmilyMusic.trackRow=(...args)=>{
  const el=row(...args);const track=args[0];
  const actions=[...el.children].filter(x=>x.tagName==='BUTTON'&&!x.classList.contains('music-track-main')&&!x.classList.contains('music-download')&&!x.classList.contains('music-like'));
  const more=document.createElement('button');more.className='mobile-track-more';more.textContent='⋮';more.setAttribute('aria-label','Opções da música');
  more.onclick=()=>{closeOptions();optionsAnchor=more;$('#mobile-options-title').textContent=track.titulo;
    const pop=options.querySelector('.mobile-track-actions');pop.replaceChildren();actions.forEach(b=>{if(!b.querySelector('span')){const text=document.createElement('span');text.textContent=b.title||b.getAttribute('aria-label');b.append(text);}pop.append(b);});options.showModal();};
  // Os comandos ficam guardados fora da linha; o download continua acessível nela.
  actions.forEach(b=>b.remove());el.append(more);return el;
 };
 window.addEventListener('keydown',e=>{if(e.key==='Escape'&&!full.hidden){e.preventDefault();e.stopImmediatePropagation();mobile.close();}},true);
 const render=EmilyMusic.render.bind(EmilyMusic);EmilyMusic.render=()=>{closeOptions();render();mobile.update();};
 // open() é assíncrono; aguarda o primeiro render sem reconstruir a página.
 const open=EmilyMusic.open.bind(EmilyMusic);EmilyMusic.open=async tab=>{await open(tab);$('#mobile-now-player').append($('#player-barra'));if(Player._faixaAtual)$('#player-barra').hidden=false;mobile.update();};
 $('#mobile-now-player').append($('#player-barra'));mobile.update();
})();
