package com.emily.music

import org.junit.Assert.*
import org.junit.Test

class MusicSearchCacheTest {
    @Test fun expiresResultsAndEvictsLeastRecentlyUsed() {
        var time=0L
        val cache=MusicSearchCache({time},2,100)
        cache.put("one","1");cache.put("two","2")
        assertEquals("1",cache.get("one"))
        cache.put("three","3")
        assertNull(cache.get("two"))
        assertEquals("1",cache.get("one"))
        time=100
        assertNull(cache.get("one"))
        assertNull(cache.get("three"))
    }
}
