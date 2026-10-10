package com.emily.music

import androidx.media3.common.PlaybackException

internal object MusicRecoveryPolicy {
    fun retryable(code:Int,status:Int?,resolutionFailure:Boolean,online:Boolean):Boolean =
        resolutionFailure || !online || code in listOf(
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
            PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT
        ) || (code==PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS && (status==429 || status in 500..599))
}
