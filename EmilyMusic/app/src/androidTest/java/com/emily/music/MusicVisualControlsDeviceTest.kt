package com.emily.music
import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.*

class MusicVisualControlsDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun sharedStatusesUnlikeMiniControlsAndUncroppedFocusedPlayer() {
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(compose.activity))
  compose.activity.runOnUiThread {compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String {val latch=CountDownLatch(1);var value="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){value=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return value}
  for(i in 0..50){compose.waitForIdle();if(js("!!window.MusicListeningUI&&!!window.EmilyMusic&&!!document.getElementById('modal-player')&&!document.getElementById('modal-player').hidden&&!EmilyMusic.polling")=="true")break;Thread.sleep(200)}
  assertEquals("true",js("!!window.MusicListeningUI"))
  val script="""
   (()=>{window.visualResult='running';const old={state:window.musicState,lib:_playlistsGeral,load:carregarGeral,tenta,offline:EmilyMusic.offline,poll:EmilyMusic.pollOffline,track:Player._faixaAtual,queue:Player.playlist,prev:Player.anterior,next:Player.proxima,view:EmilyMusic.view,tab:EmilyMusic.tab,results:EmilyMusic.searchResults,query:EmilyMusic.searchQuery,input:document.getElementById('pl-query').value};
   window.visualCleanup=()=>{MusicMobile.close();window.musicState=old.state;_playlistsGeral=old.lib;carregarGeral=old.load;tenta=old.tenta;EmilyMusic.offline=old.offline;EmilyMusic.pollOffline=old.poll;Player._faixaAtual=old.track;Player.playlist=old.queue;Player.anterior=old.prev;Player.proxima=old.next;EmilyMusic.searchResults=old.results;EmilyMusic.searchQuery=old.query;document.getElementById('pl-query').value=old.input;EmilyMusic.view=old.view;EmilyMusic.go(old.tab);MusicMobile.update();if(old.track)Player._pintaBarra();};
   const assert=(v,msg)=>{if(!v)throw Error(msg);};const m={video_id:'aaaaaaaaaaa',titulo:'A very long title that should wrap without cropping outside the screen',artist:'Test artist',thumb:old.track?.thumb||''};
   window.musicState=()=>{};_playlistsGeral={playlists:{default:{musicas:[m]}},favoritos:{[m.video_id]:true},ativa:'default',listening:[{...m,count:3,last:100}]};carregarGeral=async()=>{};EmilyMusic.pollOffline=async()=>{};EmilyMusic.offline={online:true,faixas:{[m.video_id]:{estado:'pronto'}}};tenta=async(method,id,value)=>{if(method==='playlist_favoritar'){_playlistsGeral.favoritos[id]=value;return true;}return false;};
   (async()=>{try{EmilyMusic.view='default';EmilyMusic.go('playlist');assert(document.querySelector('#pl-lista .music-like.ativo'),'playlist heart');assert(document.querySelector('#pl-lista .music-download[data-state=pronto] svg'),'playlist download');
   const row=EmilyMusic.searchRow(m,null);assert(row.querySelector('.music-like.ativo'),'search heart');assert(row.querySelector('.music-download[data-state=pronto] svg'),'search download');
   EmilyMusic.go('inicio');assert(document.querySelector('.listening-track-actions .music-like.ativo'),'history heart');assert(document.querySelector('.listening-track-actions .music-download[data-state=pronto]'),'history downloaded');assert(document.querySelector('.listening-artist'),'artist cards missing');
   EmilyMusic.go('favoritas');document.querySelector('#pl-lista .music-like').click();await new Promise(r=>setTimeout(r,100));assert(!_playlistsGeral.favoritos[m.video_id],'unlike state');assert(!document.querySelector('#pl-lista .music-like'),'liked playlist did not remove track');assert(!EmilyMusic.searchRow(m,null).querySelector('.music-like.ativo'),'search stale heart');
   Player._faixaAtual=m;Player._pintaBarra();Player.playlist=[m,{...m,video_id:'bbbbbbbbbbb'}];let prev=0,next=0;Player.anterior=()=>prev++;Player.proxima=()=>next++;MusicMobile.update();document.getElementById('mobile-mini-prev').click();document.getElementById('mobile-mini-next').click();assert(prev===1&&next===1,'mini controls');MusicMobile.open();assert(document.querySelector('#mobile-now-download .music-download[data-state=pronto]'),'focused downloaded '+JSON.stringify({track:Player._faixaAtual,offline:EmilyMusic.offline.faixas[m.video_id],html:document.getElementById('mobile-now-download').innerHTML}));assert(!document.querySelector('#mobile-mini .mini-downloaded,#mobile-mini .mini-liked,#mobile-mini .mini-status'),'mini indicators remain');for(const value of [-1,null,NaN]){const box=document.createElement('div');EmilyMusic.offline.faixas[m.video_id]={estado:'baixando',progresso:value};EmilyMusic.downloadButton(m,box);assert(box.querySelector('small').textContent==='…','unknown progress shown as percent');}EmilyMusic.offline.faixas[m.video_id]={estado:'baixando',progresso:42};MusicMobile.update();assert(document.querySelector('#mobile-now-download .music-download>span').textContent==='42%','focused progress incorrect');assert(!document.querySelector('#mobile-now-download small'),'duplicate progress badge');await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));assert(getComputedStyle(document.querySelector('#mobile-now .player-thumb')).objectFit==='cover','artwork not filling card');const playIcon=[...document.querySelectorAll('#player-play svg')].find(el=>getComputedStyle(el).display!=='none');assert(playIcon&&Number(getComputedStyle(playIcon).opacity)>.9,'play icon invisible');const area=document.getElementById('mobile-now');const rect=area.getBoundingClientRect();assert(rect.left>=-1&&rect.right<=innerWidth+1,'focused bounds');assert(getComputedStyle(document.getElementById('player-barra'),'::after').content==='none','invisible card remains');const title=document.getElementById('player-titulo');title.textContent=m.titulo;for(const id of ['player-titulo','player-centro','player-seek-row']){const el=document.getElementById(id)||document.querySelector('.'+id);if(el){const r=el.getBoundingClientRect();assert(r.left>=-1&&r.right<=innerWidth+1,'cropped '+id);}}window.visualResult='ok';}catch(e){window.visualResult=e.message;}})();return true;})()
  """.trimIndent()
  try {
   assertEquals("true",js(script));var result="running"
   for(i in 0..60){result=js("window.visualResult").trim('"');if(result!="running")break;Thread.sleep(150)}
   assertEquals("ok",result)
   InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()?.let {bitmap->java.io.File(compose.activity.cacheDir,"visual-controls-preview.png").outputStream().use{bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}}
  } finally {js("window.visualCleanup?.();true")}
 }
}
