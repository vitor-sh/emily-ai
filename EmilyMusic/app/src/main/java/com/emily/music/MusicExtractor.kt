package com.emily.music

import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.CancellationException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Cancelling a screen/request also cancels its Python extractor process. */
internal object MusicExtractor {
    suspend fun execute(request:YoutubeDLRequest,retryAfterUpdate:Boolean=true,timeoutMs:Long=45000L):String = try {once(request,timeoutMs)}
        catch(e:CancellationException){throw e}
        catch(e:Exception){if(!retryAfterUpdate)throw e;YoutubeDownloader.garantirAtualizado(EmilyMusicLibrary.context());once(request,timeoutMs)}
    private suspend fun once(request:YoutubeDLRequest,timeoutMs:Long):String=withTimeout(timeoutMs) {
        suspendCancellableCoroutine { continuation ->
            val id="music-query-${java.util.UUID.randomUUID()}"
            val thread=Thread({
                try {
                    if(!continuation.isActive)return@Thread
                    val output=YoutubeDL.getInstance().execute(request,id,false,null).out
                    if(continuation.isActive)continuation.resume(output)
                } catch(e:Exception){if(continuation.isActive)continuation.resumeWithException(e)}
            },"emily-music-extractor").apply{isDaemon=true}
            continuation.invokeOnCancellation {thread.interrupt();runCatching {YoutubeDL.getInstance().destroyProcessById(id)}}
            thread.start()
        }
    }
}
