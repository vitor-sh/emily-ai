package com.emily.music

import androidx.media3.common.C
import androidx.media3.datasource.*
import androidx.media3.datasource.cache.*
import kotlinx.coroutines.*

/** Uses the playback cache/key, bounded reads, and no blocking cache locks. */
internal object MusicHeadPreloader {
    suspend fun prepare(id:String,library:MusicLibrarySession,bytes:Long,
                        cache:Cache=EmilyMusicService.audioCache(library.context())):Long=withContext(Dispatchers.IO) {
        val cm=library.context().getSystemService(android.net.ConnectivityManager::class.java)
        fun networkBudget():Long {
            val caps=cm.getNetworkCapabilities(cm.activeNetwork)
            return MusicPreloadPolicy.byteBudget(
                caps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)==true,
                caps?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI)==true,
                caps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_NOT_METERED)==true,
                cm.restrictBackgroundStatus==android.net.ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED)
        }
        val limit=minOf(bytes,networkBudget())
        if(limit<=0 || library.localUri(id)!=null)return@withContext 0L
        require(bytes<=512L*1024)
        currentCoroutineContext().ensureActive()
        if(cache.isCached(id,0,limit))return@withContext 0L
        val stream=EmilyMusicAudio.resolve(id,false)
        check(!library.closed && library.uid==MusicCloud.currentUser()?.uid)
        val http=DefaultHttpDataSource.Factory().setConnectTimeoutMs(2500).setReadTimeoutMs(2500)
        val source=CacheDataSource.Factory().setCache(cache)
            .setUpstreamDataSourceFactory(http).setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
            .setCacheKeyFactory{it.key?:it.uri.toString()}.createDataSource()
        var total=0L
        try {
            source.open(DataSpec.Builder().setUri(stream.uri).setKey(id).setLength(limit)
                .setHttpRequestHeaders(stream.headers).build())
            val buffer=ByteArray(16*1024)
            while(total<limit) {
                currentCoroutineContext().ensureActive()
                check(!library.closed && library.uid==MusicCloud.currentUser()?.uid)
                val remaining=minOf(limit,networkBudget())-total
                if(remaining<=0)break
                val n=source.read(buffer,0,minOf(buffer.size.toLong(),remaining).toInt())
                if(n==C.RESULT_END_OF_INPUT)break
                total+=n
            }
        } finally {source.close()}
        total
    }
}
