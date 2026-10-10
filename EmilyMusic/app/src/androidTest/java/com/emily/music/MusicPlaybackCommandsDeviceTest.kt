package com.emily.music

import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.media3.common.*
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.*

/** Exercise the real JavaScript bridge, not just direct MediaController calls. */
class MusicPlaybackCommandsDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun latestSelectionAndOrderedNextPreviousThroughWebView() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  compose.activity.runOnUiThread {compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String {val latch=CountDownLatch(1);var value="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){value=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return value}
  for(n in 0..100){compose.waitForIdle();if(js("typeof native==='function'&&!!window.EmilyMusic")=="true")break;Thread.sleep(200)}
  assertEquals("true",js("typeof native==='function'"))
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  val main: (() -> Unit)->Unit={i.runOnMainSync(it)}
  main{future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val c=future.get(15,TimeUnit.SECONDS);Thread.sleep(500)
  var active=false;main{active=c.playWhenReady};org.junit.Assume.assumeFalse("Não interromper áudio do usuário",active)
  val lib=EmilyMusicLibrary.session();val saved=lib.playerState();var old=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var loop=0;var shuffle=false
  main{old=(0 until c.mediaItemCount).map{c.getMediaItemAt(it)};index=c.currentMediaItemIndex.coerceAtLeast(0);position=c.currentPosition;volume=c.volume;loop=c.repeatMode;shuffle=c.shuffleModeEnabled}
  val lists=lib.library().getJSONObject("playlists")
  val tracks=lists.keys().asSequence().flatMap {n->val a=lists.getJSONObject(n).getJSONArray("musicas");(0 until a.length()).asSequence().map{a.getJSONObject(it)}}.filter{it.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}.distinctBy{it.optString("video_id")}.take(3).toList()
  org.junit.Assume.assumeTrue(tracks.size==3)
  fun awaitResult(){var result="running";for(n in 0..150){result=js("window.commandsTest").trim('"');if(result!="running")break;Thread.sleep(100)};assertEquals("ok",result)}
  try {
   val big=JSONArray((0..199).map{tracks[0]})
   val one=JSONArray().put(tracks[1]);val last=JSONArray().put(tracks[2])
   js("window.commandsTest='running';Promise.all([native('play',$big,0,{loop:0,shuffle:false,volume:0}),native('play',$one,0,{loop:0,shuffle:false,volume:0}),native('play',$last,0,{loop:0,shuffle:false,volume:0})]).then(r=>window.commandsTest=r.every(Boolean)?'ok':'failed');true")
   awaitResult();main{assertEquals(tracks[2].getString("video_id"),c.currentMediaItem?.mediaId)}
   js("window.commandsTest='running';native('play',${JSONArray(tracks)},0,{loop:0,shuffle:false,volume:0}).then(()=>Promise.all([native('next'),native('prev'),native('next'),native('next')])).then(r=>window.commandsTest=r.every(Boolean)?'ok':'failed');true")
   awaitResult();main{assertEquals(tracks[2].getString("video_id"),c.currentMediaItem?.mediaId);assertTrue(c.playWhenReady)}
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nWEBVIEW_MEDIA latest_selection ordered_next_prev=ok\n")})
  }finally{
   main{c.pause();c.stop();c.clearMediaItems();if(old.isNotEmpty())c.setMediaItems(old,index,position);c.volume=volume;c.repeatMode=loop;c.shuffleModeEnabled=shuffle};Thread.sleep(300);lib.savePlayer(saved);main{MediaController.releaseFuture(future)}
  }
 }
}
