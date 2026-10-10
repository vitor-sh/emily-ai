package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class MusicPrimarySearchDeviceTest {
    @Test fun primarySearchLinksAndCache()=runBlocking(Dispatchers.IO) {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        assertTrue("Approved login needed",MusicCloud.locallyApproved(context))
        EmilyMusicLibrary.init(context)
        EmilyMusicSearch.clearCache()
        val query="The Score The Fear"
        val start=android.os.SystemClock.elapsedRealtime()
        val result=EmilyMusicSearch.search(query)
        val first=android.os.SystemClock.elapsedRealtime()-start
        assertEquals("newpipe",result.getString("search_source"))
        assertTrue(result.getJSONArray("resultados").length()>0)
        val cachedStart=android.os.SystemClock.elapsedRealtime()
        assertEquals(result.toString(),EmilyMusicSearch.search(query).toString())
        val cached=android.os.SystemClock.elapsedRealtime()-cachedStart
        assertTrue(cached<1000)
        val id=result.getJSONArray("resultados").getJSONObject(0).getString("video_id")
        val linked=EmilyMusicSearch.search("https://youtu.be/$id?si=test")
        assertEquals("newpipe",linked.getString("search_source"))
        assertEquals(1,linked.getJSONArray("resultados").length())
        assertEquals(id,linked.getJSONArray("resultados").getJSONObject(0).getString("video_id"))
        instrumentation.sendStatus(0,android.os.Bundle().apply {putString("stream","\nPRIMARY_SEARCH first_ms=$first cache_ms=$cached link_id=$id\n")})
    }
}
