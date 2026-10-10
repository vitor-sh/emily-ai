package com.emily.music

import org.junit.Assert.*
import org.junit.Test

class MusicRecoveryTest {
    @Test fun exhaustedAttemptsCanResumeWhenInternetReturns() {
        val r=MusicRecovery();r.failed("a",true,true)
        repeat(3){assertTrue(r.canAttempt("a",true));r.attempted()}
        assertFalse(r.canAttempt("a",true))
        r.connectionRestored();assertTrue(r.canAttempt("a",true))
        assertFalse(r.canAttempt("a",false))
    }
    @Test fun pauseAndTrackChangeDoNotRestartOldAudio() {
        val r=MusicRecovery();r.failed("a",true,true);r.stop();r.connectionRestored()
        assertFalse(r.canAttempt("a",true))
        r.failed("b",true,true);assertFalse(r.canAttempt("a",true));assertTrue(r.canAttempt("b",true))
    }
    @Test fun failedPausedOrNonNetworkAudioDoesNotAutoPlay() {
        val r=MusicRecovery();r.failed("a",false,true);assertFalse(r.canAttempt("a",true))
        r.failed("a",true,false);assertFalse(r.canAttempt("a",true))
    }
}
