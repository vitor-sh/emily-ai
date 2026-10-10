package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.TimeUnit

@RunWith(AndroidJUnit4::class)
class MusicAudioFallbackDeviceTest {
    @Test fun rejectedAddressUsesReadableLegacyAudio()=runBlocking(Dispatchers.IO) {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context))
        EmilyMusicLibrary.init(context)
        val lists=EmilyMusicLibrary.library().getJSONObject("playlists")
        val id=lists.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS}.flatMap{name->
            val tracks=lists.getJSONObject(name).getJSONArray("musicas")
            (0 until tracks.length()).asSequence().map{tracks.getJSONObject(it).getString("video_id")}
        }.first{it.matches(Regex("[A-Za-z0-9_-]{11}"))}
        try {
            EmilyMusicAudio.clearCache()
            // The same invalidation the service performs on BAD_HTTP_STATUS.
            EmilyMusicAudio.invalidate(id,legacy=true)
            val start=android.os.SystemClock.elapsedRealtime()
            val stream=EmilyMusicAudio.resolve(id)
            assertEquals("yt-dlp",stream.source)
            val http=okhttp3.OkHttpClient.Builder().callTimeout(10,TimeUnit.SECONDS).build()
            val request=okhttp3.Request.Builder().url(stream.uri.toString()).header("Range","bytes=0-1023")
            stream.headers.forEach{(k,v)->request.header(k,v)}
            http.newCall(request.build()).execute().use {r->
                assertTrue("Alternativa precisa retornar áudio",r.isSuccessful)
                val bytes=ByteArray(1024)
                assertTrue("Resposta precisa ter conteúdo",r.body!!.byteStream().read(bytes)>0)
            }
            instrumentation.sendStatus(0,android.os.Bundle().apply{putString("stream","\nMUSIC_FALLBACK source=${stream.source} resolve_and_first_bytes_ms=${android.os.SystemClock.elapsedRealtime()-start}\n")})
        } finally {EmilyMusicAudio.clearCache()}
    }
}
