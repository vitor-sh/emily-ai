package com.emily.music

import android.net.Uri
import kotlinx.coroutines.*
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import org.schabi.newpipe.extractor.NewPipe
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.downloader.Downloader
import org.schabi.newpipe.extractor.downloader.Request
import org.schabi.newpipe.extractor.downloader.Response
import org.schabi.newpipe.extractor.localization.Localization
import org.schabi.newpipe.extractor.stream.DeliveryMethod
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** No Python startup. Only stream metadata; no related videos, images or audio downloads. */
internal object MusicNativeExtractor {
    private const val AGENT="Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
    private val http=OkHttpClient.Builder().connectTimeout(4,TimeUnit.SECONDS)
        .readTimeout(5,TimeUnit.SECONDS).callTimeout(6,TimeUnit.SECONDS).build()
    private val requests=ThreadLocal<MutableSet<Call>>()
    private val artists=MusicSearchCache(capacity=200,ttl=24*60*60*1000L)
    fun artist(id:String)=artists.get(id).orEmpty()
    suspend fun <T:Any> metadata(block:()->T):T=withTimeoutOrNull(35000L) {
        suspendCancellableCoroutine {continuation->
            val calls=mutableSetOf<Call>()
            val thread=Thread({
                requests.set(calls)
                try {if(continuation.isActive){init();val result=block();if(continuation.isActive)continuation.resume(result)}}
                catch(e:Exception){if(continuation.isActive)continuation.resumeWithException(e)}
                finally {requests.remove()}
            },"music-import-metadata").apply {isDaemon=true}
            continuation.invokeOnCancellation {thread.interrupt();synchronized(calls){calls.toList().forEach {it.cancel()}}}
            thread.start()
        }
    } ?: throw IOException("A leitura demorou demais. Confira a conexão e tente novamente.")
    @Volatile private var initialized=false
    @Synchronized private fun init() {
        if(initialized)return
        NewPipe.init(object:Downloader() {
            override fun execute(request:Request):Response {
                if(Thread.currentThread().isInterrupted)throw IOException("Extração cancelada")
                val builder=okhttp3.Request.Builder().url(request.url()).header("User-Agent",AGENT)
                request.headers().forEach {(name,values)->builder.removeHeader(name);values.forEach{builder.addHeader(name,it)}}
                val method=request.httpMethod()
                val body=if(method=="GET" || method=="HEAD")null else (request.dataToSend()?:byteArrayOf()).toRequestBody()
                val call=http.newCall(builder.method(method,body).build())
                val active=requests.get() ?: error("Extração fora do executor")
                synchronized(active){if(Thread.currentThread().isInterrupted)throw IOException("Extração cancelada");active.add(call)}
                try {return call.execute().use {r->Response(r.code,r.message,r.headers.toMultimap(),r.body?.string(),r.request.url.toString())}}
                finally {synchronized(active){active.remove(call)}}
            }
        },Localization("pt","BR"))
        initialized=true
    }
    suspend fun resolve(id:String):EmilyMusicAudio.Stream=withTimeoutOrNull(8000L) {
        suspendCancellableCoroutine {continuation->
            val calls=mutableSetOf<Call>()
            val thread=Thread({
                requests.set(calls)
                try {
                    if(!continuation.isActive)return@Thread
                    init()
                    val extractor=ServiceList.YouTube.getStreamExtractor("https://www.youtube.com/watch?v=$id")
                    extractor.fetchPage()
                    runCatching {artists.put(id,extractor.uploaderName.orEmpty().take(180))}
                    val candidates=extractor.audioStreams.filter {it.isUrl && it.content.startsWith("https://") && it.deliveryMethod==DeliveryMethod.PROGRESSIVE_HTTP && it.format?.suffix=="m4a"}
                    // Keep the original track, prefer broadly supported AAC, then highest bitrate.
                    val stream=candidates.filter {it.audioTrackType==null || it.audioTrackType?.name=="ORIGINAL"}
                        .sortedWith(compareByDescending<org.schabi.newpipe.extractor.stream.AudioStream>{it.format?.suffix=="m4a"}.thenByDescending{it.averageBitrate})
                        .firstOrNull() ?: error("Nenhum áudio direto disponível")
                    val uri=Uri.parse(stream.content)
                    val now=System.currentTimeMillis()
                    val expiry=uri.getQueryParameter("expire")?.toLongOrNull()?.times(1000)?.minus(60000)?:now+15*60*1000
                    val result=EmilyMusicAudio.Stream(uri,mapOf("User-Agent" to AGENT),minOf(expiry,now+15*60*1000),"newpipe")
                    if(continuation.isActive)continuation.resume(result)
                } catch(e:Exception){if(continuation.isActive){android.util.Log.w("MusicAudio","Extração integrada falhou: ${e.javaClass.simpleName}");continuation.resumeWithException(e)}}
                finally {requests.remove()}
            },"music-native-extractor").apply{isDaemon=true}
            continuation.invokeOnCancellation {thread.interrupt();synchronized(calls){calls.toList().forEach{it.cancel()}}}
            thread.start()
        }
    } ?: throw IOException("Extração integrada excedeu o tempo limite")
}
