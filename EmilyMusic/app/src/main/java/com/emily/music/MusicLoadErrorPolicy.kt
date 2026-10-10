package com.emily.music

import androidx.media3.common.C
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.upstream.DefaultLoadErrorHandlingPolicy
import androidx.media3.exoplayer.upstream.LoadErrorHandlingPolicy

/** Rejected URLs have already been renewed once by MusicStreamDataSource. */
internal class MusicLoadErrorPolicy:DefaultLoadErrorHandlingPolicy(1) {
    override fun getRetryDelayMsFor(info:LoadErrorHandlingPolicy.LoadErrorInfo):Long {
        val http=generateSequence(info.exception as Throwable?){it.cause}.filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()
        return if(http?.responseCode in listOf(401,403,410))C.TIME_UNSET else super.getRetryDelayMsFor(info)
    }
}
