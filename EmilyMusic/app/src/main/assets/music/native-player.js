/* Media3 controla áudio/fila/repetição mesmo sem tela e sem JavaScript em execução. */
let nativeState={posicao:0,duracao:0,playing:false,video_id:'',queue:[]};
const native=(command,...args)=>tenta('media_'+command,...args);
Player._carregarIframe=()=>{};Player._criarPlayer=()=>{};
Player.player={
 getCurrentTime:()=>nativeState.posicao,getDuration:()=>nativeState.duracao,getVideoData:()=>({video_id:nativeState.video_id}),
 playVideo:()=>native('resume'),pauseVideo:()=>native('pause'),stopVideo:()=>native('stop'),seekTo:t=>native('seek',t),
 setVolume:v=>native('volume',v),mute:()=>{Player._mutado=true;native('volume',0);},unMute:()=>{Player._mutado=false;},isMuted:()=>Player._mutado
};Player.pronto=true;
let playRequestSerial=0;
Player.tocar=function(index){if(!this.playlist.length)return;index=index??0;const m=this.playlist[index];if(!m)return;
 this.indice=index;this._faixaAtual=m;this._playlistAtivaSalva=m.origem||this._playlistAtivaSalva;this._videoEsperado=m.video_id;this.tocando=true;
 this._pintaBarra();this._pintaControles();this._marcarEstadoVisual('carregando');
 const queue=EmilyMusic.online()?this.playlist:this.playlist.filter(t=>EmilyMusic.offline.faixas[t.video_id]?.estado==='pronto');
 const selected=queue.findIndex(t=>t.video_id===m.video_id);if(selected<0){toast('Esta música não está disponível offline');this.tocando=false;return;}
 const request=++playRequestSerial;native('play',queue,selected,{loop:this.loop,shuffle:this.shuffle,volume:this._volumeAtual()}).then(ok=>{if(request!==playRequestSerial)return;if(!ok){this.tocando=false;this._pintaControles();}});
};
Player.proxima=()=>native('next');Player.anterior=()=>native('prev');Player._repetirAtual=()=>native('seek',0);
const toggleLoop=Player.alternarLoop.bind(Player),toggleShuffle=Player.alternarShuffle.bind(Player);
Player.alternarLoop=()=>{toggleLoop();native('options',{loop:Player.loop,shuffle:Player.shuffle});};
Player.alternarShuffle=()=>{toggleShuffle();native('options',{loop:Player.loop,shuffle:Player.shuffle});};
Player.restaurar=async()=>{const p=await tenta('player_estado');if(!p)return;Player.loop=p.loop??1;Player.shuffle=p.shuffle??false;Player.definirVolume(p.volume??100,{persistir:false});Player._pintaControles();};
window.musicState=state=>{
 const oldId=nativeState.video_id,oldPlaying=nativeState.playing,oldBuffering=nativeState.buffering;
 const hasQueue=Array.isArray(state.queue);
 const queueChanged=hasQueue&&JSON.stringify(state.queue)!==JSON.stringify(nativeState.queue);
 nativeState={...nativeState,...state};
 if(hasQueue){Player.playlist=nativeState.queue;}
 if(Array.isArray(state.order)){Player._filaShuffle=state.order;Player._posShuffle=0;}
 Player.indice=nativeState.indice??-1;
 const queued=nativeState.queue[Player.indice];
 const current=state.track?.video_id===nativeState.video_id?state.track:null;
 Player._faixaAtual=current||(queued?.video_id===nativeState.video_id?queued:null)||(Player._faixaAtual?.video_id===nativeState.video_id?Player._faixaAtual:null);if(Player._faixaAtual?.origem)Player._playlistAtivaSalva=Player._faixaAtual.origem;Player._videoEsperado=state.video_id;
 const modesChanged=(typeof state.loop==='number'&&state.loop!==Player.loop)||(typeof state.shuffle==='boolean'&&state.shuffle!==Player.shuffle);
 if(typeof state.loop==='number')Player.loop=state.loop;
 if(typeof state.shuffle==='boolean')Player.shuffle=state.shuffle;
 Player.tocando=state.playing;Player._duracao=state.duracao;
 const changed=modesChanged||oldId!==state.video_id||queueChanged||oldPlaying!==state.playing||oldBuffering!==state.buffering;
 if(Player._faixaAtual){
   if(changed||$('#player-barra').hidden){Player._minimizada=false;Player._pintaBarra();Player._marcarEstadoVisual(state.buffering?'carregando':state.playing?'tocando':'pausado');}
   Player._atualizarTempo();
 }
 if(changed){Player._pintaControles();if(oldId!==state.video_id||queueChanged)EmilyMusic.render();}
 window.MusicMobile?.update();
 EmilyMusic.tick();
};
window.EmilyMusicAudio={init(){},get localActive(){return !!nativeState.video_id&&EmilyMusic.offline.faixas[nativeState.video_id]?.estado==='pronto';}};
// A sessão nativa é a autoridade dos modos, inclusive alterações na notificação.
let settingsRevision=null;
EmilyMusic.applyNativeSettings=settings=>{
 if(settings.revision!==undefined && settings.revision!==settingsRevision){
   settingsRevision=settings.revision;Player.loop=settings.loop??Player.loop;Player.shuffle=settings.shuffle??Player.shuffle;
   native('options',{loop:Player.loop,shuffle:Player.shuffle});
 }
 // Um estado persistido antigo não desfaz um clique recente na notificação.
 settings.loop=Player.loop;settings.shuffle=Player.shuffle;
};
ligarPlayer();
// Decide on the service's live state: the WebView snapshot can be 500 ms old,
// especially while a failure/retry or a new selection is being reported.
Player.playPause=()=>native('toggle');
$('#player-play').onclick=()=>Player.playPause();
EmilyMusic.close=()=>EmilyAndroid.back();
const oldRefresh=EmilyMusic.refresh.bind(EmilyMusic);EmilyMusic.refresh=async()=>{await oldRefresh();};
(async()=>{await Player.restaurar();await EmilyMusic.open();if(!Player._faixaAtual)$('#player-barra').hidden=true;
 const bar=document.createElement('div');bar.className='mobile-local-tools';bar.innerHTML='<button id="music-permission">Encontrar músicas no celular</button><button id="music-folder">Escolher pasta</button>';
 $('.pl-sidebar').append(bar);$('#music-permission').onclick=()=>EmilyAndroid.permission();$('#music-folder').onclick=()=>EmilyAndroid.folder();
})();
/* Volume do app em um painel compacto; os botões originais continuam ligados. */
const volumeButton=document.createElement('button');volumeButton.className='icone-btn';volumeButton.title='Volume';volumeButton.setAttribute('aria-label','Volume');volumeButton.innerHTML='<svg viewBox="0 0 24 24"><path d="m11 5-5 4H2v6h4l5 4zM16 8a5 5 0 0 1 0 8M19 5a9 9 0 0 1 0 14"/></svg>';
$('.emusic-top').insertBefore(volumeButton,$('#modal-player-fechar'));
const volumePanel=document.createElement('div');volumePanel.className='music-mobile-popover';volumePanel.hidden=true;volumePanel.append($('.player-vol'));document.body.append(volumePanel);volumeButton.onclick=()=>{volumePanel.hidden=!volumePanel.hidden;};document.addEventListener('pointerdown',e=>{if(!volumePanel.contains(e.target)&&!volumeButton.contains(e.target))volumePanel.hidden=true;});

// Library edits must reach the native timeline, which owns background playback.
EmilyMusic.syncQueue=function(name){
 if(!_playlistsGeral.playlists[name]||Player._filaFavoritas||name==='__avulsa__'||name!==Player._playlistAtivaSalva||!Player._faixaAtual)return;
 const rows=(_playlistsGeral.playlists[name]?.musicas||[]).map(m=>({...m,origem:name}));
 native('queue',rows,Player._faixaAtual.video_id);
};
