package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.media3.common.*
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.*
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.atomic.AtomicReference

/** Same Media3 resolver path, silent playback and no byte cache to hide startup cost. */
@UnstableApi
@RunWith(AndroidJUnit4::class)
class MusicAudioStartupDeviceTest {
    @Test fun compareColdLegacyIntegratedAndPreparedPlayback()=runBlocking {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        org.junit.Assume.assumeTrue("Entre primeiro com Google",MusicCloud.locallyApproved(context))
        withContext(Dispatchers.IO){EmilyMusicLibrary.init(context)}
        val library=EmilyMusicLibrary.session()
        val lists=library.library().getJSONObject("playlists")
        val ids=lists.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS}.flatMap {name->
            val items=lists.getJSONObject(name).getJSONArray("musicas")
            (0 until items.length()).asSequence().map{items.getJSONObject(it).getString("video_id")}
        }.filter{it.matches(Regex("[A-Za-z0-9_-]{11}"))}.distinct().take(2).toList()
        assertEquals("Duas faixas da biblioteca para comparar",2,ids.size)
        fun report(text:String)=instrumentation.sendStatus(0,android.os.Bundle().apply{putString("stream","\n$text\n")})
        suspend fun play(id:String,label:String,resolve:suspend (String)->EmilyMusicAudio.Stream):Long {
            var source="";var resolution=0L
            val upstream=ResolvingDataSource.Factory(DefaultDataSource.Factory(context,DefaultHttpDataSource.Factory())){spec->
                val start=android.os.SystemClock.elapsedRealtime()
                val stream=runBlocking(Dispatchers.IO){resolve(id)}
                source=stream.source;resolution=android.os.SystemClock.elapsedRealtime()-start
                spec.withUri(stream.uri).withRequestHeaders(stream.headers)
            }
            lateinit var player:ExoPlayer
            val error=AtomicReference<PlaybackException?>()
            var playing=false
            instrumentation.runOnMainSync {
                player=ExoPlayer.Builder(context).setMediaSourceFactory(DefaultMediaSourceFactory(upstream)).build()
                player.volume=0f
                player.addListener(object:Player.Listener{override fun onPlayerError(e:PlaybackException){error.set(e)}})
            }
            val start=android.os.SystemClock.elapsedRealtime()
            try {
                instrumentation.runOnMainSync {player.setMediaItem(MediaItem.fromUri("emilymusic://$id"));player.prepare();player.play()}
                while(android.os.SystemClock.elapsedRealtime()-start<60_000 && error.get()==null) {
                    instrumentation.runOnMainSync {playing=player.isPlaying}
                    if(playing)break
                    delay(50)
                }
                val elapsed=android.os.SystemClock.elapsedRealtime()-start
                report("MUSIC_STARTUP $label source=$source resolution_ms=$resolution command_to_playing_ms=$elapsed error_code=${error.get()?.errorCode?:0}")
                assertNull("Falha de reprodução: ${error.get()?.errorCodeName}",error.get())
                assertTrue("Áudio deve começar",playing)
                return elapsed
            } finally {instrumentation.runOnMainSync{player.release()}}
        }
        try {
            for((n,id) in ids.withIndex()) {
                EmilyMusicAudio.clearCache()
                play(id,"legacy_${n+1}"){EmilyMusicAudio.legacy(it,library)}
                EmilyMusicAudio.clearCache()
                play(id,"combined_${n+1}"){EmilyMusicAudio.resolve(it)}
                if(n==0)play(id,"prepared_1"){EmilyMusicAudio.resolve(it)}
            }
        } finally {EmilyMusicAudio.clearCache()}
    }
}
