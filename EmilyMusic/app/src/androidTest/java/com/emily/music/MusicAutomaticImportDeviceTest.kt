package com.emily.music
import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.*

class MusicAutomaticImportDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun linkStartsAutomaticImportScrollsAndKeepsUncertainTracksPending() {
  assertTrue(MusicCloud.locallyApproved(compose.activity))
  compose.activity.runOnUiThread {compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String {val latch=CountDownLatch(1);var value="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){value=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return value}
  for(i in 0..60){compose.waitForIdle();if(js("!!window.MusicImport&&!!window.EmilyMusic&&!document.getElementById('modal-player').hidden")=="true")break;Thread.sleep(200)}
  val script="""
   (()=>{window.autoImportResult='running';const old={lib:_playlistsGeral,load:carregarGeral,call:musicImportCall,prepare:EmilyMusic.prepareVisible,view:EmilyMusic.view,tab:EmilyMusic.tab};
   window.autoImportCleanup=()=>{MusicImport.back();_playlistsGeral=old.lib;carregarGeral=old.load;musicImportCall=old.call;EmilyMusic.prepareVisible=old.prepare;EmilyMusic.view=old.view;EmilyMusic.go(old.tab);};
   const assert=(v,msg)=>{if(!v)throw Error(msg);};let commits=0,inflight=0,maxInflight=0;
   const originals=Array.from({length:20},(_,i)=>({spotify_id:String(i).padStart(22,'0'),title:'Song '+i,artists:'Test artist',duration:180}));
   _playlistsGeral={playlists:{default:{musicas:[]}},favoritos:{},ativa:'default'};carregarGeral=async()=>{};EmilyMusic.prepareVisible=()=>{};
   musicImportCall=async(method,...args)=>{
    if(method==='music_import_preview')return {data:{name:'Imported fixture',cover:'brands/spotify.svg',tracks:originals}};
    if(method==='music_import_match'){inflight++;maxInflight=Math.max(maxInflight,inflight);await new Promise(r=>setTimeout(r,220));inflight--;const i=Number(args[0].split(' ')[1]);return {data:{candidates:[{video_id:String(i).padStart(11,'0'),titulo:'Song '+i,artist:'Test artist',duration:180,suggested:i!==19}]}};}
    if(method==='music_import_commit'){commits++;assert(args[0]==='Imported fixture','name lost');assert(args[1].length===19,'uncertain match imported');assert(args[3]==='brands/spotify.svg','cover lost');assert(args[4].length===1,'pending missing');_playlistsGeral.playlists[args[0]]={musicas:args[1],foto:args[3],pending:args[4]};return {data:{ok:true,name:args[0],added:19,pending:1}};}
    if(method==='music_import_resolve'){assert(args[1]===originals[19].spotify_id,'wrong pending resolved');_playlistsGeral.playlists[args[0]].pending=[];return {data:{ok:true}};}
    return {data:null,error:'Unexpected method '+method};
   };
   MusicImport.open('spotify');const input=document.querySelector('#music-import input[type=url]');input.value='https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA';input.dispatchEvent(new Event('input'));
   (async()=>{try{await new Promise(r=>setTimeout(r,950));const d=document.getElementById('music-import');assert(d.open,'dialog closed prematurely');assert(!d.querySelector('input[type=checkbox]'),'checkbox still present');assert(d.scrollHeight>d.clientHeight,'long list not scrollable');d.scrollTop=160;assert(d.scrollTop>0,'scroll blocked');const rows=d.querySelector('.import-tracks');assert(getComputedStyle(rows).overflowY==='visible','nested scroll still active');await Promise.all(d.getAnimations().map(a=>a.finished.catch(()=>{})));const rect=d.getBoundingClientRect();assert(rect.left>=0&&rect.right<=innerWidth+1&&rect.bottom<=innerHeight+1,'sheet outside screen '+JSON.stringify({rect:rect.toJSON(),width:innerWidth,height:innerHeight,visual:visualViewport.height}));
   while(d.open)await new Promise(r=>setTimeout(r,100));assert(commits===1,'automatic save did not happen exactly once');assert(maxInflight<=2&&maxInflight===2,'unbounded matching');assert(EmilyMusic.tab==='playlist'&&EmilyMusic.view==='Imported fixture','not navigated');assert(document.querySelector('.import-pending-banner'),'pending banner missing');EmilyMusic.tracks();assert(document.querySelectorAll('.import-pending-banner').length===1,'duplicate banners');
   MusicImport.openPending('Imported fixture');await new Promise(r=>setTimeout(r,400));const review=d.querySelector('.import-track button');assert(review&&!review.disabled,'pending versions unavailable');review.click();d.querySelector('.import-choices button').click();await new Promise(r=>setTimeout(r,200));assert(!_playlistsGeral.playlists['Imported fixture'].pending.length,'pending not resolved');MusicImport.back();MusicImport.open();const cancelInput=d.querySelector('input');cancelInput.value='https://open.spotify.com/playlist/AAAAAAAAAAAAAAAAAAAAAA';cancelInput.dispatchEvent(new Event('input'));await new Promise(r=>setTimeout(r,750));MusicImport.back();await new Promise(r=>setTimeout(r,600));assert(commits===1,'cancelled import was saved');window.autoImportResult='ok';}catch(e){window.autoImportResult=e.message;}})();return true;})()
  """.trimIndent()
  try {
   assertEquals("true",js(script));Thread.sleep(1300)
   InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()?.let {bitmap->java.io.File(compose.activity.cacheDir,"import-auto-preview.png").outputStream().use{bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}}
   var result="running";for(i in 0..100){result=js("window.autoImportResult").trim('"');if(result!="running")break;Thread.sleep(150)}
   assertEquals("ok",result)
  }finally{js("window.autoImportCleanup?.();true")}
 }
}
