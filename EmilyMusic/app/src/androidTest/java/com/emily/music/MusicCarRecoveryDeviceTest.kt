package com.emily.music

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import androidx.media3.common.*
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.TimeUnit

/** A real failed source, observed and resumed through the same legacy API as the car. */
class MusicCarRecoveryDeviceTest {
 @Test fun legacyErrorIsReadableAndOnePlayRecoversWithoutRestartingApp() {
  val i=InstrumentationRegistry.getInstrumentation();val ctx=i.targetContext
  lateinit var player:ExoPlayer;lateinit var session:MediaSession;lateinit var legacy:android.media.session.MediaController
  val missing=File(ctx.cacheDir,"car-recovery-${System.nanoTime()}.wav")
  fun main(block:()->Unit)=i.runOnMainSync(block)
  fun await(label:String,check:()->Boolean){for(n in 0..160){var ok=false;main{ok=check()};if(ok)return;Thread.sleep(50)};fail(label)}
  try {
   main {
    player=ExoPlayer.Builder(ctx).build();player.volume=0f
    val retry=PendingIntent.getActivity(ctx,999,Intent(ctx,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
    session=MediaSession.Builder(ctx,MusicSessionPlayer(player,retry)).setId("car-test-${System.nanoTime()}").build()
    legacy=android.media.session.MediaController(ctx,session.platformToken)
    player.setMediaItem(MediaItem.fromUri(Uri.fromFile(missing)));player.prepare();player.play()
   }
   await("Missing fixture fails"){legacy.playbackState?.state==android.media.session.PlaybackState.STATE_ERROR}
   main {
    val error=legacy.playbackState!!
    assertFalse(error.errorMessage.toString().contains("Source error"));assertTrue(error.errorMessage.toString().contains("celular"))
    assertEquals("Tentar novamente",error.extras!!.getString("android.media.extras.ERROR_RESOLUTION_ACTION_LABEL"))
    assertNotNull(error.extras!!.getParcelable<PendingIntent>("android.media.extras.ERROR_RESOLUTION_ACTION_INTENT"))
   }
   val samples=22050*6;val data=ByteBuffer.allocate(44+samples*2).order(ByteOrder.LITTLE_ENDIAN)
   data.put("RIFF".toByteArray()).putInt(36+samples*2).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(22050).putInt(44100).putShort(2).putShort(16).put("data".toByteArray()).putInt(samples*2)
   missing.writeBytes(data.array());main{legacy.transportControls.play()}
   await("Single Play resumes repaired source"){player.isPlaying&&legacy.playbackState?.state==android.media.session.PlaybackState.STATE_PLAYING}
   main{legacy.transportControls.pause()};await("Pause preserved"){!player.playWhenReady}
  } finally {main{session.release();player.release()};missing.delete()}
 }
}
