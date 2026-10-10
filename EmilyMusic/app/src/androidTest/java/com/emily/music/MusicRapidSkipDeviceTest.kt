package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.media3.common.*
import androidx.media3.session.*
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.TimeUnit

class MusicRapidSkipDeviceTest {
 @Test fun latestTrackWinsRapidSkipsInRealPlaybackService() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  val main: (() -> Unit)->Unit={i.runOnMainSync(it)}
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  main{future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val c=future.get(15,TimeUnit.SECONDS);Thread.sleep(1000)
  var active=false;main{active=c.playWhenReady};org.junit.Assume.assumeFalse("Não interromper áudio do usuário",active)
  val lib=EmilyMusicLibrary.session();val lists=lib.library().getJSONObject("playlists")
  val tracks=lists.keys().asSequence().flatMap {name->val rows=lists.getJSONObject(name).getJSONArray("musicas");(0 until rows.length()).asSequence().map{rows.getJSONObject(it)}}.filter{it.getString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}.distinctBy{it.getString("video_id")}.filter{lib.localUri(it.getString("video_id"))==null}.take(3).toList()
  org.junit.Assume.assumeTrue("Precisa de três faixas online",tracks.size==3)
  val saved=lib.playerState();var previous=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var loop=0;var shuffle=false
  main{previous=(0 until c.mediaItemCount).map{c.getMediaItemAt(it)};index=c.currentMediaItemIndex.coerceAtLeast(0);position=c.currentPosition;volume=c.volume;loop=c.repeatMode;shuffle=c.shuffleModeEnabled}
  try {
   for(round in 1..4) {
    EmilyMusicAudio.clearCache()
    val items=musicItems(JSONArray(tracks),lib).map{it.buildUpon().setCustomCacheKey("rapid-test-$round-${System.nanoTime()}-${it.mediaId}").setMediaMetadata(it.mediaMetadata.buildUpon().setExtras(null).build()).build()}
    main{c.volume=0f;c.repeatMode=Player.REPEAT_MODE_OFF;c.shuffleModeEnabled=false;c.setMediaItems(items);c.prepare();c.play()}
    Thread.sleep(80);main{c.seekToNextMediaItem()};Thread.sleep(50);main{c.seekToPreviousMediaItem()};Thread.sleep(60);main{c.seekToNextMediaItem()};Thread.sleep(40)
    val start=android.os.SystemClock.elapsedRealtime();main{c.seekToNextMediaItem()}
    var playing=false;var id="";var error:PlaybackException?=null
    for(n in 0..250){main{playing=c.isPlaying;id=c.currentMediaItem?.mediaId.orEmpty();error=c.playerError};if(playing&&id==tracks.last().getString("video_id")||error!=null)break;Thread.sleep(100)}
    val elapsed=android.os.SystemClock.elapsedRealtime()-start
    i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nRAPID_SKIP cold_round=$round final_track_correct=${id==tracks.last().getString("video_id")} playing=$playing elapsed_ms=$elapsed error=${error?.errorCode}\n")})
    assertNull("Áudio não deve falhar nas trocas rápidas",error);assertEquals(tracks.last().getString("video_id"),id);assertTrue("Última faixa deve tocar sem esperar as puladas",playing)
    main{c.pause();c.stop()}
   }
  } finally {
   main{c.pause();c.stop();c.clearMediaItems();if(previous.isNotEmpty())c.setMediaItems(previous,index,position);c.volume=volume;c.repeatMode=loop;c.shuffleModeEnabled=shuffle}
   Thread.sleep(300);lib.savePlayer(saved);main{MediaController.releaseFuture(future)}
  }
 }
}
