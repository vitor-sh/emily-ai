package com.emily.music

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class MusicSearchFallbackTest {
    @Test fun successfulPrimaryNeverSpendsReserveQuota()=runBlocking {
        var calls=0
        assertEquals("native",musicSearchWithFallback({}, {"native"}, {calls++;"reserve"}))
        assertEquals(0,calls)
    }
    @Test fun parserFailureAndDeadlineUseReserve()=runBlocking {
        assertEquals("reserve",musicSearchWithFallback({}, {throw IOException("parser changed")}, {"reserve"}))
        assertEquals("reserve",musicSearchWithFallback({}, {delay(1000);"late"}, {"reserve"},10))
    }
    @Test fun cancellationDoesNotStartReserve()=runBlocking {
        var calls=0
        try {
            musicSearchWithFallback({}, {throw CancellationException("superseded")}, {calls++;"reserve"})
            fail("Cancellation must propagate")
        }catch(_:CancellationException) {}
        assertEquals(0,calls)
    }
    @Test fun accountChangeBlocksReserveEvenAfterPrimaryFailure()=runBlocking {
        var valid=true;var calls=0
        try {
            musicSearchWithFallback({if(!valid)throw CancellationException("signed out")},
                {valid=false;throw IOException()}, {calls++;"reserve"})
            fail("Account change must stop search")
        }catch(_:CancellationException) {}
        assertEquals(0,calls)
    }
    @Test fun reserveFailureIsVisibleAndNotConvertedIntoSuccess()=runBlocking {
        try {
            musicSearchWithFallback({}, {throw IOException()}, {throw IllegalStateException("quota")})
            fail("Reserve error must propagate")
        }catch(e:IllegalStateException){assertEquals("quota",e.message)}
    }
}
