package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MusicSearchPerformanceDeviceTest {
    @Test fun realSearchAndAudioResolutionReuseCachedResults() = runBlocking(Dispatchers.IO) {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        org.junit.Assume.assumeTrue("Login real precisa estar aprovado",MusicCloud.locallyApproved(context))
        EmilyMusicLibrary.init(context)
        val query="Celeste Resurrections Lena Raine"
        fun now()=android.os.SystemClock.elapsedRealtime()
        var start=now()
        val results=EmilyMusicSearch.search(query).getJSONArray("resultados")
        val coldSearch=now()-start
        assertTrue("Busca real deve retornar músicas",results.length()>0)
        start=now()
        val cached=EmilyMusicSearch.search(query).getJSONArray("resultados")
        val cachedSearch=now()-start
        assertEquals(results.toString(),cached.toString())
        val id=results.getJSONObject(0).getString("video_id")
        EmilyMusicAudio.invalidate(id)
        start=now()
        val audio=EmilyMusicAudio.resolve(id)
        val coldAudio=now()-start
        start=now()
        val reused=EmilyMusicAudio.resolve(id)
        val cachedAudio=now()-start
        assertEquals(audio,reused)
        assertTrue(cachedSearch<1000)
        assertTrue(cachedAudio<1000)
        val report=android.os.Bundle().apply {putString("stream","\nMUSIC_PERF search_first_ms=$coldSearch search_cached_ms=$cachedSearch audio_resolution_first_ms=$coldAudio audio_resolution_cached_ms=$cachedAudio\n")}
        InstrumentationRegistry.getInstrumentation().sendStatus(0,report)
    }
}
