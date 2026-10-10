package com.emily.music

import kotlinx.coroutines.*

/** Shares work for the same track, but speculative work never holds up a click. */
internal class MusicResolutionQueue<T>(
    private val scope:CoroutineScope,
    private val valid:(T)->Boolean,
    private val load:suspend (String)->T,
) {
    private class Pending<T>(val result:Deferred<T>,var background:Boolean,var waiters:Int=0,var selected:Boolean=false)
    private val lock=Any()
    private val cached=LinkedHashMap<String,T>()
    private val pending=mutableMapOf<String,Pending<T>>()
    private var generation=0L
    /** Manual selection cancels abandoned work. Automatic transitions preserve ExoPlayer prebuffering. */
    fun selectPlayback(id:String?,cancelObsolete:Boolean=true)=synchronized(lock){
        pending[id]?.let {it.selected=true;it.background=false}
        if(!cancelObsolete)return@synchronized
        val obsolete=pending.filter {it.key!=id}
        obsolete.forEach {(key,p)->pending.remove(key);p.result.cancel()}
    }

    suspend fun resolve(id:String,foreground:Boolean=true):T {
        val request=synchronized(lock) {
            if(!foreground && pending.any{it.key!=id&&!it.value.background})throw CancellationException("Reprodução tem prioridade")
            if(foreground) {
                val obsolete=pending.filter {it.key!=id && it.value.background}
                obsolete.forEach {(key,p)->pending.remove(key);p.result.cancel()}
            }
            cached[id]?.takeIf(valid)?.let {return it}
            cached.remove(id)
            val p=pending[id] ?: run {
                val epoch=generation
                val result=scope.async(start=CoroutineStart.LAZY) {
                    val value=load(id)
                    ensureActive()
                    synchronized(lock) {
                        if(epoch==generation) {
                            cached.entries.removeAll {!valid(it.value)}
                            if(cached.size>=64)cached.remove(cached.keys.first())
                            cached[id]=value
                        }
                    }
                    value
                }
                val item=Pending(result,!foreground)
                pending[id]=item
                result.invokeOnCompletion {synchronized(lock){if(pending[id]===item)pending.remove(id)}}
                result.start()
                item
            }
            if(foreground)p.background=false
            p.waiters++
            p
        }
        try {return request.result.await()}
        finally {synchronized(lock){
            request.waiters--
            if(request.waiters==0 && !request.selected && !request.result.isCompleted) {
                if(pending[id]===request)pending.remove(id)
                request.result.cancel()
            }
        }}
    }
    fun invalidate(id:String)=synchronized(lock){cached.remove(id);pending.remove(id)?.result?.cancel();Unit}
    fun clear()=synchronized(lock){generation++;cached.clear();val jobs=pending.values.toList();pending.clear();jobs.forEach{it.result.cancel()}}
}
