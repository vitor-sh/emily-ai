package com.emily.music

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import java.io.IOException

/** A slow primary may be overtaken by the reserve; failed/cancelled work never wins. */
internal suspend fun <T:Any> musicAudioRace(
    delayMs:Long=2500,
    primary:suspend ()->T,
    reserve:suspend ()->T,
):T=coroutineScope {
    val failed=CompletableDeferred<Unit>()
    val results=Channel<Result<T>>(Channel.UNLIMITED)
    suspend fun attempt(block:suspend ()->T,first:Boolean) {
        try {results.send(Result.success(block()))}
        catch(e:Exception){
            currentCoroutineContext().ensureActive()
            if(first)failed.complete(Unit)
            results.send(Result.failure(if(e is CancellationException)IOException("Tempo limite do áudio",e) else e))
        }
    }
    val a=launch {attempt(primary,true)}
    val b=launch {withTimeoutOrNull(delayMs){failed.await()};attempt(reserve,false)}
    try {
        var error:Throwable?=null
        repeat(2){val r=results.receive();if(r.isSuccess)return@coroutineScope r.getOrThrow();error=r.exceptionOrNull()}
        throw error?:IOException("Áudio indisponível")
    } finally {a.cancel();b.cancel();results.close()}
}
