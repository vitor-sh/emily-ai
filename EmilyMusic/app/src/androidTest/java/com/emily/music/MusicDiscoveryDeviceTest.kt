package com.emily.music
import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.*

class MusicDiscoveryDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun draftsSpacesDestinationDeduplicationAndListeningCards() {
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(compose.activity))
  compose.activity.runOnUiThread {compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String {val latch=CountDownLatch(1);var value="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){value=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return value}
  for(i in 0..50){compose.waitForIdle();if(js("!!window.PlaylistSearch&&!!window.EmilyMusic&&!!document.getElementById('modal-player')&&!document.getElementById('modal-player').hidden&&!EmilyMusic.polling")=="true")break;Thread.sleep(200)}
  assertEquals("true",js("!!window.PlaylistSearch"))
  val script="""
   (()=>{window.discoveryResult='running';const old={state:window.musicState,poll:EmilyMusic.pollOffline,lib:_playlistsGeral,load:carregarGeral,tenta,importCall:musicImportCall,view:EmilyMusic.view,tab:EmilyMusic.tab,history:localStorage.getItem('emily-music-searches:'+new URLSearchParams(location.search).get('account')),input:document.getElementById('pl-query').value};
   window.discoveryCleanup=()=>{MusicMobile.back();window.musicState=old.state;EmilyMusic.pollOffline=old.poll;_playlistsGeral=old.lib;carregarGeral=old.load;tenta=old.tenta;musicImportCall=old.importCall;const key='emily-music-searches:'+new URLSearchParams(location.search).get('account');if(old.history===null)localStorage.removeItem(key);else localStorage.setItem(key,old.history);document.getElementById('pl-query').value=old.input;EmilyMusic.view=old.view;EmilyMusic.go(old.tab);};
   const assert=(v,msg)=>{if(!v)throw Error(msg);};let searches=0,copies=0;
   const m={video_id:'aaaaaaaaaaa',titulo:'A song with spaces',artist:'Test artist',thumb:''};
   window.musicState=()=>{};EmilyMusic.pollOffline=async()=>{};_playlistsGeral={playlists:{default:{musicas:[]},'Test destination':{musicas:[]}},favoritos:{},ativa:'default',listening:[{...m,count:3,last:100}]};carregarGeral=async()=>{};
   musicImportCall=async()=>{searches++;return {data:{resultados:[m]}};};tenta=async(method,name,track)=>{if(method==='playlist_fixar'){_playlistsGeral.playlists[name].pinned=track;return true;}if(method==='music_copiar'){copies++;assert(name==='Test destination','wrong playlist');_playlistsGeral.playlists[name].musicas.push(track);return true;}return old.tenta(method,name,track);};
   (async()=>{try{EmilyMusic.go('busca');const input=document.getElementById('pl-query');const history=JSON.stringify(EmilyMusic.history());input.value='A ';input.dispatchEvent(new Event('input'));await new Promise(r=>setTimeout(r,850));assert(input.value==='A ','space was trimmed');assert(searches===0,'draft searched');assert(JSON.stringify(EmilyMusic.history())===history,'draft saved');
   await EmilyMusic.search('A song');assert(searches===1,'explicit search missing');assert(!document.querySelector('.music-search-more'),'redundant menu');
   EmilyMusic.view='Test destination';EmilyMusic.go('playlist');assert(document.querySelector('.mobile-playlist-add'),'add button missing');document.querySelector('.mobile-playlist-add').click();const d=document.getElementById('playlist-search');const box=d.querySelector('input');box.value='A song ';box.dispatchEvent(new Event('input'));assert(box.value==='A song ','playlist space trimmed');d.querySelector('form').requestSubmit();await new Promise(r=>setTimeout(r,100));d.querySelector('.music-search-add').click();await new Promise(r=>setTimeout(r,100));assert(copies===1,'add missing');assert(d.querySelector('.music-search-add').disabled,'duplicate allowed');assert(!_playlistsGeral.playlists.default.musicas.length,'wrong target changed');
   await new Promise(r=>setTimeout(r,500));await Promise.all(d.getAnimations().map(a=>a.finished.catch(()=>{})));const rect=d.getBoundingClientRect();const visibleHeight=visualViewport?.height||innerHeight;assert(rect.height>visibleHeight*.5&&rect.bottom<=(visualViewport?.offsetTop||0)+visibleHeight+1&&rect.left>=0&&rect.right<=innerWidth+1,'dialog does not fit');
   PlaylistSearch.back();EmilyMusic.go('inicio');assert(document.querySelectorAll('.listening-section').length===3,'listening sections missing');EmilyMusic.go('biblioteca');assert(!document.querySelector('.music-discovery'),'discovery repeated in library');let grid=document.querySelector('#music-home .music-cards');assert(grid.children[0].dataset.library==='liked'&&grid.children[1].dataset.library==='local','fixed playlists order');assert(getComputedStyle(grid).flexDirection==='column','vertical list missing');assert(grid.querySelector('.music-art').getBoundingClientRect().width>=80,'playlist cover too small');assert(document.querySelector('.mobile-library-create'),'create playlist missing');let row=document.querySelector('.library-playlist-row[data-playlist="Test destination"]');row.querySelector('.library-pin').click();await new Promise(r=>setTimeout(r,150));assert(_playlistsGeral.playlists['Test destination'].pinned,'pin not saved');assert(document.querySelector('.library-playlist-row').dataset.playlist==='Test destination','pinned playlist not on top');document.querySelector('.library-playlist-row .library-pin').click();await new Promise(r=>setTimeout(r,150));assert(!_playlistsGeral.playlists['Test destination'].pinned,'unpin not saved');assert(document.querySelector('.library-playlist-row').dataset.playlist==='default','unpin order');row=document.querySelector('.library-playlist-row[data-playlist="Test destination"]');assert(row.querySelector('small').textContent==='1 faixa','track count grammar');row.querySelector('.library-open').click();assert(EmilyMusic.view==='Test destination'&&EmilyMusic.tab==='playlist','playlist did not open');EmilyMusic.go('biblioteca');window.discoveryResult='ok';return;}catch(e){window.discoveryResult=e.message;}})();return true;})()
  """.trimIndent()
  try {
   assertEquals("true",js(script));var result="running"
   for(i in 0..50){result=js("window.discoveryResult").trim('"');if(result!="running")break;Thread.sleep(150)}
   assertEquals("ok",result);Thread.sleep(300)
   InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()?.let {bitmap->java.io.File(compose.activity.cacheDir,"discovery-preview.png").outputStream().use{bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}}
  } finally {js("window.discoveryCleanup?.();true")}
 }
}
