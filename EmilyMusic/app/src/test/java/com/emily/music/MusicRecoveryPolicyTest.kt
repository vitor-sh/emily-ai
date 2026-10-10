package com.emily.music

import androidx.media3.common.PlaybackException
import org.junit.Assert.*
import org.junit.Test

class MusicRecoveryPolicyTest {
    @Test fun extractorFailuresAndTemporaryNetworkErrorsCanRecover() {
        assertTrue(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_IO_UNSPECIFIED,null,true,true))
        assertTrue(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT,null,false,true))
        for(status in listOf(429,500,502,503))assertTrue(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,status,false,true))
    }
    @Test fun permanentSourceOrDecoderFailuresAreNotRetriedOnline() {
        for(status in listOf(401,403,404,410))assertFalse(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,status,false,true))
        assertFalse(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND,null,false,true))
        assertFalse(MusicRecoveryPolicy.retryable(PlaybackException.ERROR_CODE_DECODING_FAILED,null,false,true))
    }
}
