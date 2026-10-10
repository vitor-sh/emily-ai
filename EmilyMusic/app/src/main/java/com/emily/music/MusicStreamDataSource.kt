package com.emily.music

import android.net.Uri
import androidx.media3.datasource.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import java.io.InterruptedIOException

/** Extractors can throw non-IO exceptions; expose them as retryable source failures. */
internal class MusicAudioResolutionException(cause:Exception):java.io.IOException("Não foi possível obter o áudio desta faixa",cause)

/** Refresh via the fast extractor first; use the reserve only after another refusal. */
internal class MusicStreamDataSource(
    private val delegate:DataSource,
    private val local:(String)->Uri?,
    private val resolve:suspend (String)->EmilyMusicAudio.Stream={EmilyMusicAudio.resolve(it)},
    private val invalidate:(String,Boolean)->Unit={id,legacy->EmilyMusicAudio.invalidate(id,legacy=legacy)},
):DataSource {
    override fun addTransferListener(listener:TransferListener)=delegate.addTransferListener(listener)
    override fun getUri():Uri?=delegate.uri
    override fun getResponseHeaders():Map<String,List<String>> = delegate.responseHeaders
    override fun read(buffer:ByteArray,offset:Int,length:Int)=delegate.read(buffer,offset,length)
    override fun close()=delegate.close()
    private fun checkCancelled(){if(Thread.currentThread().isInterrupted)throw InterruptedIOException("Faixa anterior cancelada")}
    override fun open(spec:DataSpec):Long {
        checkCancelled()
        if(spec.uri.scheme!="emilymusic")return delegate.open(spec)
        val id=spec.uri.host?:throw java.io.IOException("Faixa inválida")
        local(id)?.let {return delegate.open(spec.withUri(it))}
        fun resolved():DataSpec {
            checkCancelled()
            val stream=try {runBlocking(Dispatchers.IO){resolve(id)}}
            catch(e:InterruptedException){Thread.currentThread().interrupt();throw InterruptedIOException("Faixa anterior cancelada").apply{initCause(e)}}
            catch(e:kotlinx.coroutines.CancellationException){throw InterruptedIOException("Obtenção do áudio cancelada").apply{initCause(e)}}
            catch(e:Exception){throw MusicAudioResolutionException(e)}
            checkCancelled()
            return spec.withUri(stream.uri).withRequestHeaders(spec.httpRequestHeaders+stream.headers)
        }
        for(attempt in 0..2) {
            try {return delegate.open(resolved())}
            catch(e:HttpDataSource.InvalidResponseCodeException){
                if(e.responseCode !in listOf(401,403,410) || attempt==2)throw e
                checkCancelled();runCatching {delegate.close()}
                // Temporary CDN refusals need not send this track to Python for 15 minutes.
                invalidate(id,attempt==1)
            }
        }
        throw java.io.IOException("Áudio indisponível")
    }
}
