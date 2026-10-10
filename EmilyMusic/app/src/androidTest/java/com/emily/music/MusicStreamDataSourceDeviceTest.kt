package com.emily.music

import android.net.Uri
import androidx.media3.datasource.*
import org.junit.Assert.*
import org.junit.Test

class MusicStreamDataSourceDeviceTest {
 @Test fun extractorExceptionBecomesRecoverableIoWithoutHidingCancellation() {
  val delegate=object:DataSource {
   override fun addTransferListener(l:TransferListener){}
   override fun getUri():Uri?=null
   override fun open(spec:DataSpec):Long=error("Não deve abrir após falha de resolução")
   override fun read(b:ByteArray,o:Int,n:Int)=0
   override fun close(){}
  }
  val spec=DataSpec(Uri.parse("emilymusic://aaaaaaaaaaa"))
  val transient=MusicStreamDataSource(delegate,{null},resolve={throw IllegalStateException("Temporary extractor failure")})
  val error=assertThrows(MusicAudioResolutionException::class.java){transient.open(spec)}
  assertTrue(error.cause is IllegalStateException)
  val cancelled=MusicStreamDataSource(delegate,{null},resolve={throw kotlinx.coroutines.CancellationException("Track replaced")})
  assertThrows(java.io.InterruptedIOException::class.java){cancelled.open(spec)}
 }
 @Test fun renewsForbiddenUrlOnceAndPreservesRangeAndCacheIdentity() {
  var opens=0;var closed=0;var resolutions=0;var invalidations=0;var last:DataSpec?=null
  val delegate=object:DataSource {
   override fun addTransferListener(l:TransferListener){}
   override fun getUri():Uri?=last?.uri
   override fun open(spec:DataSpec):Long {last=spec;opens++;if(opens==1)throw HttpDataSource.InvalidResponseCodeException(403,"Forbidden",null,emptyMap(),spec,byteArrayOf());return 1024}
   override fun read(b:ByteArray,o:Int,n:Int)=0
   override fun close(){closed++}
  }
  val source=MusicStreamDataSource(delegate,{null},resolve={resolutions++;EmilyMusicAudio.Stream(Uri.parse("https://example.com/$resolutions"),mapOf("User-Agent" to "test"),Long.MAX_VALUE)},invalidate={_,legacy->assertFalse(legacy);invalidations++})
  val spec=DataSpec.Builder().setUri("emilymusic://aaaaaaaaaaa").setKey("same-song").setPosition(300).setLength(1024).build()
  assertEquals(1024L,source.open(spec));assertEquals(2,opens);assertEquals(2,resolutions);assertEquals(1,closed);assertEquals(1,invalidations)
  assertEquals("same-song",last!!.key);assertEquals(300L,last!!.position);assertEquals(1024L,last!!.length);assertEquals("test",last!!.httpRequestHeaders["User-Agent"])
 }
 @Test fun mediaPlayerReportsPersistentRefusalWithoutRepeatingLongAttempts() {
  val i=androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
  val attempts=java.util.concurrent.atomic.AtomicInteger()
  val factory=DataSource.Factory {MusicStreamDataSource(object:DataSource {
   override fun addTransferListener(l:TransferListener){}
   override fun getUri():Uri?=null
   override fun open(spec:DataSpec):Long {attempts.incrementAndGet();throw HttpDataSource.InvalidResponseCodeException(403,"Forbidden",null,emptyMap(),spec,byteArrayOf())}
   override fun read(b:ByteArray,o:Int,n:Int)=0
   override fun close(){}
  },{null},resolve={EmilyMusicAudio.Stream(Uri.parse("https://example.com/audio"),emptyMap(),Long.MAX_VALUE)},invalidate={_,_->})}
  lateinit var player:androidx.media3.exoplayer.ExoPlayer
  val done=java.util.concurrent.CountDownLatch(1)
  val start=android.os.SystemClock.elapsedRealtime()
  try {
   i.runOnMainSync {
    player=androidx.media3.exoplayer.ExoPlayer.Builder(i.targetContext).setMediaSourceFactory(androidx.media3.exoplayer.source.DefaultMediaSourceFactory(factory).setLoadErrorHandlingPolicy(MusicLoadErrorPolicy())).build()
    player.addListener(object:androidx.media3.common.Player.Listener {override fun onPlayerError(e:androidx.media3.common.PlaybackException){done.countDown()}})
    player.setMediaItem(androidx.media3.common.MediaItem.fromUri("emilymusic://aaaaaaaaaaa"));player.prepare();player.play()
   }
   assertTrue("Persistent refusal must report an error promptly",done.await(2,java.util.concurrent.TimeUnit.SECONDS))
   assertEquals(3,attempts.get())
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nREJECTED_STREAM bounded_renewal=true error_ms=${android.os.SystemClock.elapsedRealtime()-start}\n")})
  } finally {i.runOnMainSync {player.release()}}
 }
 @Test fun repeatedRefusalDoesNotCreateUnboundedRenewal() {
  var attempts=0;val modes=mutableListOf<Boolean>()
  val delegate=object:DataSource {
   override fun addTransferListener(l:TransferListener){}
   override fun getUri():Uri?=null
   override fun open(spec:DataSpec):Long {attempts++;throw HttpDataSource.InvalidResponseCodeException(403,"Forbidden",null,emptyMap(),spec,byteArrayOf())}
   override fun read(b:ByteArray,o:Int,n:Int)=0
   override fun close(){}
  }
  val source=MusicStreamDataSource(delegate,{null},resolve={EmilyMusicAudio.Stream(Uri.parse("https://example.com/audio"),emptyMap(),Long.MAX_VALUE)},invalidate={_,legacy->modes.add(legacy)})
  assertThrows(HttpDataSource.InvalidResponseCodeException::class.java){source.open(DataSpec(Uri.parse("emilymusic://aaaaaaaaaaa")))}
  assertEquals(3,attempts);assertEquals(listOf(false,true),modes)
 }
}
