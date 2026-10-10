/* Pesquisa vinculada à playlist: rascunhos não fazem consultas nem entram no histórico. */
(()=>{
 const dialog=document.createElement('dialog');dialog.id='playlist-search';dialog.setAttribute('aria-labelledby','playlist-search-title');
 dialog.innerHTML='<header><div><small>ENCONTRE SEU PRÓXIMO SOM</small><h2 id="playlist-search-title"></h2></div><button class="sheet-close" aria-label="Fechar busca">×</button></header><form><input type="search" placeholder="Música, artista ou link do YouTube" aria-label="Pesquisar músicas nesta playlist" maxlength="300"><button type="submit" aria-label="Buscar">⌕</button></form><div class="playlist-search-results" aria-live="polite"></div>';
 document.body.append(dialog);
 const input=dialog.querySelector('input'),box=dialog.querySelector('.playlist-search-results');let target=null,results=[],query='',loading=false,error='',serial=0,anchor=null;
 function fit(){const h=Math.floor((visualViewport?.height||innerHeight)*.92);dialog.style.height=h+'px';dialog.style.maxHeight=h+'px';dialog.style.bottom=Math.max(0,innerHeight-(visualViewport?.height||innerHeight)-(visualViewport?.offsetTop||0))+'px';}
 visualViewport?.addEventListener('resize',fit);addEventListener('resize',fit);
 function close(){serial++;loading=false;dialog.close();anchor?.isConnected&&anchor.focus();}
 dialog.querySelector('.sheet-close').onclick=close;dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
 const api=window.PlaylistSearch={
  open(name){if(!_playlistsGeral.playlists[name]||_playlistsGeral.playlists[name].readonly)return;anchor=document.activeElement;target=name;results=[];query='';input.value='';error='';loading=false;serial++;dialog.querySelector('h2').textContent='Adicionar em '+(name==='default'?'Minha seleção':name);this.renderResults();fit();dialog.showModal();input.focus();},
  back(){if(!dialog.open)return false;close();return true;},
  renderResults(){if(!dialog.open&&target===null)return;const top=box.scrollTop;box.replaceChildren();
   if(!_playlistsGeral.playlists[target]||_playlistsGeral.playlists[target].readonly){box.textContent='Esta playlist mudou ou foi removida. Feche a busca e abra a playlist novamente.';return;}
   if(loading){box.innerHTML='<div class="music-loading" role="status" aria-label="Buscando músicas"><span class="music-search-spinner" aria-hidden="true"></span></div>';return;}if(error){box.textContent=error;return;}
   if(!query){const h=document.createElement('h3');h.textContent='Pesquisas recentes';box.append(h);
    for(const q of EmilyMusic.history()){const b=document.createElement('button');b.className='playlist-search-recent';b.textContent='↶  '+q;b.onclick=()=>{input.value=q;dialog.querySelector('form').requestSubmit();};box.append(b);}
    const p=document.createElement('p');p.textContent='Pesquise e toque em + para adicionar diretamente a esta playlist. Toque na música para ouvir sem adicionar.';box.append(p);return;}
   if(!results.length){box.textContent='Nenhuma música encontrada. Tente outro nome.';return;}
   const dest={value:target};for(const m of results)box.append(EmilyMusic.searchRow(m,dest));box.scrollTop=top;
  }
 };
 input.addEventListener('input',()=>{serial++;loading=false;query='';results=[];error='';api.renderResults();});
 dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const q=input.value.trim();if(!q)return;const run=++serial;query=q;results=[];error='';loading=true;api.renderResults();if(!EmilyMusic.online()){loading=false;error='A busca precisa de conexão. Suas músicas baixadas continuam disponíveis.';api.renderResults();return;}EmilyMusic.rememberSearch(q);
  const reply=await musicImportCall('playlist_buscar_preview',q);const r=reply.data;if(run!==serial||!dialog.open)return;loading=false;if(!r||r.erro)error=reply.error||r?.erro||'Não foi possível buscar. Tente novamente.';else results=r.resultados||[];api.renderResults();
 };
 const tracks=EmilyMusic.tracks.bind(EmilyMusic);EmilyMusic.tracks=()=>{tracks();const name=EmilyMusic.view;if(EmilyMusic.tab!=='playlist'||!_playlistsGeral.playlists[name]||_playlistsGeral.playlists[name].readonly)return;const b=document.createElement('button');b.className='btn-linha mobile-playlist-add';b.innerHTML='<span aria-hidden="true">＋</span> Adicionar músicas';b.onclick=()=>api.open(name);document.querySelector('.mobile-playlist-actions').prepend(b);};
 const back=MusicMobile.back.bind(MusicMobile);MusicMobile.back=()=>api.back()||back();
})();
