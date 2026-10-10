package com.emily.music

import android.net.Uri
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlinx.coroutines.*
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap

object EmilyMusicAudio {
    internal data class Stream(val uri:Uri,val headers:Map<String,String>,val validUntil:Long,val source:String="yt-dlp")
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private val forcedLegacy=ConcurrentHashMap<String,Long>()
    private val queue=MusicResolutionQueue(scope,{s:Stream->System.currentTimeMillis()<s.validUntil}) {id->
        val library=EmilyMusicLibrary.session()
        check(!library.closed)
        val started=android.os.SystemClock.elapsedRealtime()
        val stream=withTimeoutOrNull(25000L) {
            if((forcedLegacy[id]?:0L)>System.currentTimeMillis())legacy(id,library)
            else musicAudioRace(primary={MusicNativeExtractor.resolve(id)},reserve={legacy(id,library)})
        } ?: throw java.io.IOException("O áudio demorou demais. Tente novamente ou escolha outra faixa.")
        check(!library.closed && library.uid==MusicCloud.currentUser()?.uid){"A conta mudou."}
        android.util.Log.i("MusicAudio","Áudio resolvido por ${stream.source} em ${android.os.SystemClock.elapsedRealtime()-started} ms")
        stream
    }
    private var preparation:Job?=null
    private var visibleIds=emptyList<String>()
    @Synchronized fun clearCache(){preparation?.cancel();preparation=null;visibleIds=emptyList();queue.clear();forcedLegacy.clear()}
    internal fun selectPlayback(id:String?,cancelObsolete:Boolean=true){queue.selectPlayback(id,cancelObsolete);stopVisiblePreparation()}
    fun invalidate(id:String?,legacy:Boolean=false){if(id!=null){queue.invalidate(id);if(legacy){forcedLegacy.entries.removeIf{it.value<=System.currentTimeMillis()};if(forcedLegacy.size>=64)forcedLegacy.clear();forcedLegacy[id]=System.currentTimeMillis()+15*60*1000}else forcedLegacy.remove(id)}}
    internal suspend fun resolve(id:String,foreground:Boolean=true):Stream {
        require(id.matches(Regex("[A-Za-z0-9_-]{11}"))){"Áudio local ainda não transferido"}
        return queue.resolve(id,foreground)
    }
    internal suspend fun legacy(id:String,library:MusicLibrarySession=EmilyMusicLibrary.session()):Stream {
        require(id.matches(Regex("[A-Za-z0-9_-]{11}")))
        YoutubeDownloader.prepararMusic(library.context())
        val request=YoutubeDLRequest("https://www.youtube.com/watch?v=$id").apply {
            addOption("--cache-dir",java.io.File(library.context().cacheDir,"music-extractor").apply{mkdirs()}.absolutePath)
            addOption("--extractor-args","youtube:skip=hls,dash;player_skip=configs,initial_data;webpage_skip=initial_data")
            addOption("--no-playlist");addOption("--no-warnings");addOption("-f","bestaudio[ext=m4a]/bestaudio/best")
            addOption("--dump-single-json");addOption("--skip-download");addOption("--socket-timeout","6");addOption("--retries","1");addOption("--extractor-retries","1")
        }
        val output=try {MusicExtractor.execute(request,retryAfterUpdate=false,timeoutMs=20000L)}
        catch(e:TimeoutCancellationException){currentCoroutineContext().ensureActive();throw java.io.IOException("O método alternativo demorou demais.",e)}
        val json=JSONObject(output)
        val uri=Uri.parse(json.getString("url"));require(uri.scheme=="https")
        val headers=json.optJSONObject("http_headers")?:JSONObject()
        val map=headers.keys().asSequence().associateWith {headers.getString(it)}
        val now=System.currentTimeMillis()
        val expiry=uri.getQueryParameter("expire")?.toLongOrNull()?.times(1000)?.minus(60000)?:Long.MAX_VALUE
        check(!library.closed && library.uid==MusicCloud.currentUser()?.uid){"A conta mudou."}
        return Stream(uri,map,minOf(now+15*60*1000,expiry))
    }
    /** Prepare visible candidates sequentially, honoring Data Saver and the mobile byte budget. */
    @Synchronized internal fun prepareVisible(ids:List<String>,library:MusicLibrarySession):Boolean {
        val cm=library.context().getSystemService(ConnectivityManager::class.java)
        val caps=cm.getNetworkCapabilities(cm.activeNetwork)
        val wifi=caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)==true
        val unmetered=caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)==true
        val budget=MusicPreloadPolicy.byteBudget(caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)==true,
            wifi,unmetered,cm.restrictBackgroundStatus==ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED)
        val tracks=if(budget>0)ids.filter{it.matches(Regex("[A-Za-z0-9_-]{11}"))}.distinct().take(if(wifi&&unmetered)2 else 1) else emptyList()
        if(tracks==visibleIds && preparation?.isActive==true)return true
        preparation?.cancel();visibleIds=tracks
        if(tracks.isEmpty()){preparation=null;return false}
        preparation=scope.launch {
            delay(200)
            for(id in tracks){
                if(library.closed || library.uid!=MusicCloud.currentUser()?.uid)break
                try {if(library.localUri(id)==null)MusicHeadPreloader.prepare(id,library,budget)}
                catch(e:CancellationException){throw e}
                catch(_:Exception){ /* Preparation is optional, errors stay out of the UI. */ }
            }
        }
        return true
    }
    internal fun stopVisiblePreparation():Job?=synchronized(this){val previous=preparation;previous?.cancel();preparation=null;visibleIds=emptyList();previous}
    fun download(items:org.json.JSONArray):Int=EmilyMusicDownload.enqueue(items)
    fun cancel(id:String):Boolean{EmilyMusicDownload.cancel(id);return true}
}
