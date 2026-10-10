package com.emily.music

import androidx.media3.common.*
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.TimeUnit

/** Real background service: no WebView timer is allowed to advance discovery. */
class MusicDiscoveryPlaybackDeviceTest {
 @Test fun recommendationsContinueAfterEndAndRespectRepeatPauseAndPlaylistSwitch() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  val main: (() -> Unit)->Unit={i.runOnMainSync(it)}
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  main{future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val c=future.get(15,TimeUnit.SECONDS);Thread.sleep(800)
  var active=false;main{active=c.playWhenReady};org.junit.Assume.assumeFalse("Não interromper áudio do usuário",active)
  val lib=EmilyMusicLibrary.session();val saved=lib.playerState();var old=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var loop=0;var shuffle=false
  main{old=(0 until c.mediaItemCount).map{c.getMediaItemAt(it)};index=c.currentMediaItemIndex.coerceAtLeast(0);position=c.currentPosition;volume=c.volume;loop=c.repeatMode;shuffle=c.shuffleModeEnabled}
  val lists=lib.library().getJSONObject("playlists")
  val seed=lists.keys().asSequence().flatMap {n->val a=lists.getJSONObject(n).getJSONArray("musicas");(0 until a.length()).asSequence().map{a.getJSONObject(it)}}.first {it.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}
  val row=JSONObject(seed.toString()).put("origem","__avulsa__").put("autoplay",true).put("autoplay_session","device-test")
  val item=musicItems(JSONArray().put(row),lib).first().buildUpon().setClippingConfiguration(MediaItem.ClippingConfiguration.Builder().setEndPositionMs(800).build()).build()
  fun checkFor(ms:Long,condition:()->Boolean):Boolean {val end=System.currentTimeMillis()+ms;while(System.currentTimeMillis()<end){var ok=false;main{ok=condition()};if(ok)return true;Thread.sleep(100)};return false}
  try {
   i.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").close()
   main{c.volume=0f;c.repeatMode=Player.REPEAT_MODE_ONE;c.shuffleModeEnabled=false;c.setMediaItem(item);c.prepare();c.play()}
   assertTrue(checkFor(20000){c.isPlaying});Thread.sleep(1500);main{assertEquals("Repeat one must not grow discovery",1,c.mediaItemCount)}
   main{c.repeatMode=Player.REPEAT_MODE_OFF}
   assertTrue("Related songs must append and play without a resume click",checkFor(35000){c.currentMediaItem?.mediaId!=item.mediaId&&c.isPlaying&&c.mediaItemCount>1})
   main{c.pause()};var count=0;main{count=c.mediaItemCount};Thread.sleep(1500);main{assertFalse(c.playWhenReady);assertEquals(count,c.mediaItemCount)}
   val playlist=item.buildUpon().setMediaMetadata(item.mediaMetadata.buildUpon().setExtras(null).build()).build()
   main{c.setMediaItem(playlist);c.prepare();c.play()};Thread.sleep(1800);main{assertEquals("Old discovery must not extend playlist",1,c.mediaItemCount)}
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nDISCOVERY_PLAYBACK background continuation repeat_one pause switch=ok\n")})
  } finally {
   main{c.pause();c.stop();c.clearMediaItems();if(old.isNotEmpty())c.setMediaItems(old,index,position);c.volume=volume;c.repeatMode=loop;c.shuffleModeEnabled=shuffle};Thread.sleep(300);lib.savePlayer(saved);main{MediaController.releaseFuture(future)}
  }
 }
}
