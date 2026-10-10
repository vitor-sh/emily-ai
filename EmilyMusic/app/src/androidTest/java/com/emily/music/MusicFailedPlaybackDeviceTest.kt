package com.emily.music

import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.media3.common.*
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.*

/** Actual service + WebView controls; missing local fixture simulates a terminal source error. */
class MusicFailedPlaybackDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun failedSourceNextPreviousPauseAndSingleClickResume() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  compose.activity.runOnUiThread{compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String{val latch=CountDownLatch(1);var value="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){value=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return value}
  for(n in 0..100){compose.waitForIdle();if(js("typeof native==='function'")=="true")break;Thread.sleep(100)}
  assertEquals("true",js("typeof native==='function'"))
  val main: (() -> Unit)->Unit={i.runOnMainSync(it)}
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  main{future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val c=future.get(15,TimeUnit.SECONDS);Thread.sleep(500)
  var active=false;main{active=c.playWhenReady};Assume.assumeFalse("Não interromper áudio do usuário",active)
  val lib=EmilyMusicLibrary.session();val saved=lib.playerState();var old=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var loop=0;var shuffle=false
  main{old=(0 until c.mediaItemCount).map{c.getMediaItemAt(it)};index=c.currentMediaItemIndex.coerceAtLeast(0);position=c.currentPosition;volume=c.volume;loop=c.repeatMode;shuffle=c.shuffleModeEnabled}
  val file=File(context.cacheDir,"failed-playback-fixture.wav")
  val samples=22050*8;val b=ByteBuffer.allocate(44+samples*2).order(ByteOrder.LITTLE_ENDIAN)
  b.put("RIFF".toByteArray()).putInt(36+samples*2).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(22050).putInt(44100).putShort(2).putShort(16).put("data".toByteArray()).putInt(samples*2);file.writeBytes(b.array())
  val good=MediaItem.Builder().setMediaId("fixture_good").setUri(android.net.Uri.fromFile(file)).build()
  val missing=MediaItem.Builder().setMediaId("fixture_missing").setUri(android.net.Uri.fromFile(File(context.cacheDir,"does-not-exist-playback.wav"))).build()
  fun awaitCondition(label:String,condition:()->Boolean){var ok=false;for(n in 0..100){main{ok=condition()};if(ok)return;Thread.sleep(50)};fail(label)}
  try {
   main{c.volume=0f;c.repeatMode=Player.REPEAT_MODE_OFF;c.shuffleModeEnabled=false;c.setMediaItems(listOf(missing,good));c.prepare();c.play()}
   awaitCondition("Fixture must fail"){c.playerError!=null&&c.playbackState==Player.STATE_IDLE}
   js("native('next');true")
   awaitCondition("Next after error must play without a second click"){c.currentMediaItem?.mediaId==good.mediaId&&c.isPlaying}
   main{c.setMediaItems(listOf(missing,good));c.prepare();c.play()}
   awaitCondition("Car-control fixture must fail"){c.playerError!=null&&c.playbackState==Player.STATE_IDLE}
   main{c.seekToNextMediaItem()}
   awaitCondition("MediaController next, as used by external controls, must recover"){c.currentMediaItem?.mediaId==good.mediaId&&c.isPlaying}
   main{c.pause();c.setMediaItems(listOf(good,good.buildUpon().setMediaId("fixture_second").build()));c.prepare()}
   js("native('next');true")
   awaitCondition("Next while paused preserves the pause"){c.currentMediaItem?.mediaId=="fixture_second"&&!c.playWhenReady}
   main{c.setMediaItems(listOf(good,missing),1,0);c.prepare();c.play()}
   awaitCondition("Previous fixture must fail"){c.playerError!=null&&c.playbackState==Player.STATE_IDLE}
   js("native('prev');true")
   awaitCondition("Previous after error must play"){c.currentMediaItem?.mediaId==good.mediaId&&c.isPlaying}
   main{c.pause()}
   // Deliberately stale UI reports 'playing'; the service must still resume once.
   js("Player.tocando=true;document.querySelector('#player-play').click();true")
   awaitCondition("Single click resumes despite stale WebView state"){c.isPlaying}
   main{c.setMediaItem(good);c.repeatMode=Player.REPEAT_MODE_OFF;c.prepare();c.play()}
   awaitCondition("Single-item end fixture must play"){c.isPlaying&&c.duration>0}
   main{c.seekTo(c.duration-100)}
   awaitCondition("Fixture must end"){c.playbackState==Player.STATE_ENDED}
   js("Player.tocando=true;document.querySelector('#player-play').click();true")
   awaitCondition("Single click restarts an ended queue"){c.isPlaying&&c.currentPosition<2000}
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nFAILED_PLAYBACK next external_next previous paused_navigation stale_toggle ended_resume=ok\n")})
  } finally {
   main{c.pause();c.stop();c.clearMediaItems();if(old.isNotEmpty())c.setMediaItems(old,index,position);c.volume=volume;c.repeatMode=loop;c.shuffleModeEnabled=shuffle};Thread.sleep(400);lib.savePlayer(saved);main{MediaController.releaseFuture(future)};file.delete()
  }
 }
}
