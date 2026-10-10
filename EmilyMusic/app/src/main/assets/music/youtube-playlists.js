/* Descoberta do YouTube: a prévia não altera a biblioteca nem a reprodução. */
(()=>{
 const E=EmilyMusic,$=s=>document.querySelector(s);
 const dialog=document.createElement('section');dialog.id='youtube-playlist-preview';dialog.hidden=true;dialog.setAttribute('aria-label','Playlist do YouTube');$('.emusic-content').append(dialog);
 let searchScroll=0,returnTab='busca';
 let epoch=0,preview=null,source=null,busy=false,anchor=null,filter='all';
 const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value;return e;};
 function savedName(){return Object.keys(_playlistsGeral.playlists).find(n=>source&&_playlistsGeral.playlists[n].youtube_id===source.playlist_id);}
 function close(){if(busy)return;epoch++;dialog.hidden=true;E.go(returnTab);$('.emusic-content').scrollTop=searchScroll;anchor?.isConnected&&anchor.focus({preventScroll:true});}
 function button(label,action){const b=text('button',label);b.type='button';b.className='btn-linha';b.disabled=busy;b.onclick=action;return b;}
 function render(message=''){
  const scroll=$('.emusic-content').scrollTop;dialog.replaceChildren();
  const head=document.createElement('header');head.append(text('small','PLAYLIST • YOUTUBE'));const x=button('← Voltar',close);x.className='youtube-back';x.setAttribute('aria-label','Voltar à busca');head.append(x);dialog.append(head);
  if(!preview){const p=text('p',message||'Abrindo playlist…');p.className='music-muted';p.setAttribute('role','status');dialog.append(p);return;}
  const hero=document.createElement('div');hero.className='pl-info youtube-preview-hero';const art=document.createElement('span');art.className='music-art';const img=document.createElement('img');img.src=preview.cover||source.thumb||preview.tracks[0]?.thumb||'';img.alt='Capa da playlist';let tried=false;img.onerror=()=>{const fallback=preview.tracks[0]?.thumb;if(!tried&&fallback&&img.getAttribute('src')!==fallback){tried=true;img.src=fallback;}else art.textContent='♫';};art.append(img);hero.append(art);const info=document.createElement('div');info.append(text('h1',preview.name),text('p',(preview.uploader||source.artist||'YouTube')+' • '+preview.tracks.length+' faixas'));hero.append(info);dialog.append(hero);
  const actions=document.createElement('div');actions.className='youtube-preview-actions';
  actions.append(button('▶ Ouvir',()=>play(0)));const shuffle=button('⇄ Aleatório',()=>{Player.alternarShuffle();render();});shuffle.setAttribute('aria-pressed',String(Player.shuffle));actions.append(shuffle);
  actions.append(button(savedName()?'Abrir na biblioteca':'＋ Salvar playlist',async()=>{const n=await save();if(n){close();E.view=n;E.go('playlist');}}));
  actions.append(button('↓ Baixar playlist',async()=>{const n=await save();if(n){await E.download(_playlistsGeral.playlists[n].musicas);render('Playlist salva. Downloads adicionados à fila.');}}));dialog.append(actions);
  const note=text('p',message||((preview.warning?preview.warning+' ':'')+(preview.unavailable?'Mostrando somente as faixas disponíveis. ':''))+'Toque em + para adicionar uma faixa a outra playlist. Para baixar, salve a playlist na biblioteca.');note.className='music-muted';note.setAttribute('role','status');dialog.append(note);
  const rows=document.createElement('div');rows.className='youtube-preview-tracks';
  for(const m of preview.tracks){const row=E.searchRow(m,null),add=row.querySelector('.music-search-add');add.disabled=false;add.setAttribute('aria-label','Escolher playlist para '+m.titulo);add.textContent='＋';add.onclick=()=>E.addMenu(m,add);row.querySelector('.music-search-play').onclick=()=>play(preview.tracks.indexOf(m));rows.append(row);}dialog.append(rows);$('.emusic-content').scrollTop=scroll;
 }
 function play(index){if(!preview?.tracks.length)return;const origin='__youtube__:'+source.playlist_id;Player.playlist=preview.tracks.map(m=>({...m,origem:origin,source_title:preview.name,autoplay:false}));Player._playlistAtivaSalva=origin;Player._filaFavoritas=false;Player._historico=[];if(Player.shuffle)Player._embaralhar();Player.tocar(index);}
 async function save(){const existing=savedName();if(existing)return existing;if(busy)return null;busy=true;let failure='';render('Salvando na sua biblioteca…');
  try {const reply=await musicImportCall('music_import_commit',preview.name.slice(0,100),preview.tracks,'youtube_'+source.playlist_id,preview.cover||'',[],source.playlist_id);if(!reply.data?.ok){failure=reply.error||reply.data?.erro||'Não foi possível salvar. Tente novamente.';return null;}await E.refresh();return reply.data.name;}
  finally{busy=false;if(!dialog.hidden)render(failure);}
 }
 const api=window.YouTubePlaylists={
  async open(item){if(!E.online()){toast('Conecte-se para abrir esta playlist','erro');return;}anchor=document.activeElement;searchScroll=$('.emusic-content').scrollTop;returnTab=E.tab==='youtube'?'busca':E.tab;source=item;preview=null;busy=false;const run=++epoch;E.go('youtube');render();
   const reply=await musicImportCall('music_import_preview','youtube',item.url);if(run!==epoch||dialog.hidden)return;
   if(!reply.data){render(reply.error||'Não foi possível abrir a playlist.');return;}preview=reply.data;render();
  },
  refresh(){if(!dialog.hidden&&preview&&!busy)render();},
  back(){if(dialog.hidden)return false;close();return true;},
  row(m){const row=document.createElement('div');row.className='music-search-row youtube-playlist-row';const b=document.createElement('button');b.className='music-search-play';b.setAttribute('aria-label','Abrir playlist '+m.titulo);
   const art=document.createElement('span');art.className='music-search-art';if(m.thumb){const img=document.createElement('img');img.src=m.thumb;img.alt='';img.loading='lazy';art.append(img);}art.append(text('em','☷'));
   const info=document.createElement('span');info.append(text('strong',m.titulo),text('small','Playlist • '+(m.artist||'YouTube')+(m.count>0?' • '+m.count+' faixas':'')));b.append(art,info);b.onclick=()=>api.open(m);row.append(b,text('span','›'));return row;
  }
 };

 const back=MusicMobile.back.bind(MusicMobile);MusicMobile.back=()=>{if(!$('#mobile-now').hidden||$('.music-add-menu')||document.querySelector('dialog[open]'))return back();return api.back()||back();};
 const go=E.go.bind(E);E.go=tab=>{dialog.hidden=tab!=='youtube';go(tab);if(tab==='youtube'){$('#music-breadcrumb').textContent='Playlist • YouTube';render();}};
 const oldRender=E.render.bind(E);E.render=()=>{oldRender();api.refresh();};
 E.searchKind=()=>filter==='playlists'?'playlists':filter==='all'?'all':'videos';
 const old=E.renderSearch.bind(E);E.renderSearch=()=>{
  const rows=E.searchResults,active=$('#pl-query').value.trim()===E.searchQuery&&E.searchQuery;
  if(active){E.searchResults=filter==='views'?[...rows].filter(m=>m.type!=='playlist').sort((a,b)=>(b.views||0)-(a.views||0)):filter==='short'?rows.filter(m=>m.type!=='playlist'&&m.duration>0&&m.duration<240):filter==='long'?rows.filter(m=>m.type!=='playlist'&&m.duration>=1200):rows;}
  E.visibleSearchTracks=E.searchResults.filter(m=>m.type!=='playlist');try{old();}finally{E.searchResults=rows;}
  if(E.tab!=='busca')return;const box=$('#pl-preview'),bar=document.createElement('div');bar.className='youtube-search-filters';bar.setAttribute('aria-label','Filtros de busca');
  for(const [value,label] of [['all','Tudo'],['videos','Músicas'],['playlists','Playlists'],['views','Mais vistas'],['short','Até 4 min'],['long','20 min ou mais']]){const b=text('button',label);b.className=filter===value?'ativo':'';b.setAttribute('aria-pressed',String(filter===value));b.onclick=()=>{const before=E.searchKind();filter=value;if(active&&before!==E.searchKind())E.search(E.searchQuery);else E.renderSearch();};bar.append(b);}box.prepend(bar);
  if(E.searchWarning&&active){const p=text('p',E.searchWarning);p.className='music-muted';bar.after(p);}
  if(filter==='views'&&active){const p=text('p','Ordenadas por visualizações entre os resultados desta busca.');p.className='music-muted';bar.after(p);}
  if(active&&filter==='all'){const title=box.querySelector('h2');if(title)title.textContent='Músicas e playlists';}
 };
})();

