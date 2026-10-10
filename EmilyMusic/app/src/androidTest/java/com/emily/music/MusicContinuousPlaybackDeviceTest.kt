package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.media3.common.*
import androidx.media3.session.*
import org.junit.Test
import org.junit.Assert.*
import java.util.concurrent.TimeUnit
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Real service and real end-of-file, without clicks or audible output. */
class MusicContinuousPlaybackDeviceTest {
 @Test fun sequentialShuffleReorderRepeatAndOnlinePrebuffer() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  val main: (() -> Unit)->Unit={i.runOnMainSync(it)}
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  main{future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val c=future.get(15,TimeUnit.SECONDS);Thread.sleep(800)
  var active=false;main{active=c.playWhenReady};org.junit.Assume.assumeFalse("Não interromper música do usuário",active)
  val lib=EmilyMusicLibrary.session();val saved=lib.playerState();var old=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var loop=0;var shuffle=false
  main{old=(0 until c.mediaItemCount).map{c.getMediaItemAt(it)};index=c.currentMediaItemIndex.coerceAtLeast(0);position=c.currentPosition;volume=c.volume;loop=c.repeatMode;shuffle=c.shuffleModeEnabled}
  val file=File(context.cacheDir,"continuous-test.wav")
  val samples=22050*2;val b=ByteBuffer.allocate(44+samples*2).order(ByteOrder.LITTLE_ENDIAN)
  b.put("RIFF".toByteArray()).putInt(36+samples*2).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(22050).putInt(44100).putShort(2).putShort(16).put("data".toByteArray()).putInt(samples*2)
  file.writeBytes(b.array())
  val items=(0..2).map{MediaItem.Builder().setMediaId("test_$it").setUri(android.net.Uri.fromFile(file)).build()}
  fun awaitId(expected:String){var id="";var playing=false;var error:PlaybackException?=null
   for(n in 0..220){main{id=c.currentMediaItem?.mediaId.orEmpty();playing=c.isPlaying;error=c.playerError};if(id==expected&&playing)break;if(error!=null)break;Thread.sleep(50)}
   assertNull("Erro no avanço automático",error);assertEquals(expected,id);assertTrue("Próxima faixa deve tocar sem despausar",playing)
  }
  try {
   i.uiAutomation.executeShellCommand("input keyevent KEYCODE_HOME").close()
   main{c.volume=0f;c.repeatMode=Player.REPEAT_MODE_OFF;c.shuffleModeEnabled=false;c.setMediaItems(items,0,0);c.prepare();c.play()};awaitId("test_0");awaitId("test_1");awaitId("test_2")
   var ended=false;for(n in 0..80){main{ended=c.playbackState==Player.STATE_ENDED};if(ended)break;Thread.sleep(50)};assertTrue("Fim da fila sem loop",ended)
   // Index zero can be LAST in a random order with repeat off. Start from the
   // first shuffled window so this really tests an automatic next transition.
   main{c.pause();c.setMediaItems(items,0,0);c.shuffleModeEnabled=true;c.prepare()}
   var ready=false;for(n in 0..100){main{ready=c.playbackState==Player.STATE_READY};if(ready)break;Thread.sleep(50)};assertTrue("Fila aleatória preparada",ready)
   var first="";main{val start=c.currentTimeline.getFirstWindowIndex(true);first=c.getMediaItemAt(start).mediaId;c.seekTo(start,0);c.play()};awaitId(first);var next="";main{assertTrue("Próxima faixa aleatória disponível",c.nextMediaItemIndex>=0);next=c.getMediaItemAt(c.nextMediaItemIndex).mediaId};awaitId(next)
   main{c.shuffleModeEnabled=false;c.setMediaItems(items,0,0);c.prepare();c.play()};awaitId("test_0");main{val positionBefore=c.currentPosition;assertFalse(MusicQueueEditor.apply(c,items,"stale"));assertTrue(MusicQueueEditor.apply(c,listOf(items[0],items[2],items[1]),"test_0"));assertEquals("test_0",c.currentMediaItem?.mediaId);assertTrue(c.currentPosition>=positionBefore)};awaitId("test_2")
   main{c.setMediaItems(items,0,0);c.repeatMode=Player.REPEAT_MODE_ALL;c.seekTo(2,0);c.prepare();c.play()};awaitId("test_2");awaitId("test_0")
   main{c.repeatMode=Player.REPEAT_MODE_ONE;c.setMediaItem(items[0]);c.prepare();c.play()};awaitId("test_0");Thread.sleep(2400);var stillPlaying=false;main{stillPlaying=c.isPlaying};assertTrue("Loop de faixa mantém reprodução",stillPlaying)
   // Online ExoPlayer resolves the next source before its transition callback.
   val lists=lib.library().getJSONObject("playlists")
   val tracks=lists.keys().asSequence().flatMap {n->val a=lists.getJSONObject(n).getJSONArray("musicas");(0 until a.length()).asSequence().map{a.getJSONObject(it)}}.filter{it.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}.distinctBy{it.optString("video_id")}.take(2).toList()
   assertTrue("Duas faixas online disponíveis",tracks.size==2)
   val online=musicItems(org.json.JSONArray(tracks),lib).mapIndexed{n,item->item.buildUpon().setMediaMetadata(item.mediaMetadata.buildUpon().setExtras(null).build()).setClippingConfiguration(MediaItem.ClippingConfiguration.Builder().setEndPositionMs(if(n==0)1500 else 6000).build()).build()}
   main{c.repeatMode=Player.REPEAT_MODE_OFF;c.setMediaItems(online);c.prepare();c.play()};awaitId(online[0].mediaId);awaitId(online[1].mediaId)
   var edit:com.google.common.util.concurrent.ListenableFuture<SessionResult>?=null
   val queue=org.json.JSONArray(listOf(tracks[1],tracks[0]))
   main{edit=c.sendCustomCommand(SessionCommand(EmilyMusicService.ACTION_QUEUE,android.os.Bundle.EMPTY),android.os.Bundle().apply{putString("queue",queue.toString());putString("expected",online[1].mediaId)})}
   assertEquals(SessionResult.RESULT_SUCCESS,edit!!.get(10,TimeUnit.SECONDS).resultCode)
   main{assertEquals(online[1].mediaId,c.currentMediaItem?.mediaId);assertTrue(c.playWhenReady)}
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nCONTINUOUS_PLAYBACK sequential shuffle reordered repeat_all repeat_one online_prebuffer=ok\n")})
  } finally {
   main{c.pause();c.stop();c.clearMediaItems();if(old.isNotEmpty())c.setMediaItems(old,index,position);c.volume=volume;c.repeatMode=loop;c.shuffleModeEnabled=shuffle};Thread.sleep(300);lib.savePlayer(saved);main{MediaController.releaseFuture(future)};file.delete()
  }
 }
}
