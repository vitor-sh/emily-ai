package com.emily.music

import com.yausername.youtubedl_android.YoutubeDLRequest
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.stream.StreamInfoItem
import org.schabi.newpipe.extractor.playlist.PlaylistInfoItem
import kotlinx.coroutines.*
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.sync.Semaphore

/** Busca/letras funcionam pela internet mesmo quando o PC está desligado. */
object EmilyMusicSearch {
    private val http=OkHttpClient.Builder().callTimeout(12,TimeUnit.SECONDS).connectTimeout(6,TimeUnit.SECONDS).readTimeout(15,TimeUnit.SECONDS).build()
    private val cache=MusicSearchCache()
    private val searchSlots=Semaphore(2)
    private val generation=AtomicLong()
    suspend fun search(query:String,filter:String="videos",onPartial:((JSONObject)->Unit)?=null):JSONObject = searchSlots.withPermit {
        require(filter in listOf("all","videos","playlists")){"Filtro inválido"}
        val normalized=query.trim().take(300)
        require(normalized.isNotEmpty()) { "Digite o nome de uma música." }
        val account=if(MusicCloud.configured()) MusicCloud.accountKey() else "local"
        val epoch=generation.get()
        fun checkSession() {
            if(generation.get()!=epoch || (MusicCloud.configured() &&
                (MusicCloud.currentUser()?.uid!=account || !MusicCloud.locallyApproved(EmilyMusicLibrary.context())))) {
                throw CancellationException("A sessão mudou. Entre novamente no Emily Music.")
            }
        }
        checkSession()
        val cacheKey=account+":"+epoch+":"+filter+":"+normalized
        cache.get(cacheKey)?.let { checkSession();return@withPermit JSONObject(it) }
        val result=musicSearchWithFallback(::checkSession,
            primary={nativeSearch(normalized,filter,
                onPartial={partial->checkSession();onPartial?.invoke(partial)},
                onGroup={group,rows->
                    checkSession()
                    cache.put(account+":"+epoch+":"+group+":"+normalized,
                        JSONObject().put("resultados",rows).put("search_source","newpipe").toString())
                })},reserve={if(filter!="playlists")reserveSearch(normalized).put("aviso","Não foi possível consultar playlists agora. Mostrando músicas pela busca alternativa.") else throw java.io.IOException("A busca de playlists está indisponível. Tente novamente.")})
        checkSession()
        cache.put(cacheKey,result.toString())
        result
    }
    fun clearCache() { generation.incrementAndGet();cache.clear() }
    private suspend fun nativeSearch(query:String,filter:String,onPartial:(JSONObject)->Unit,onGroup:(String,JSONArray)->Unit):JSONObject=coroutineScope {
        val playlistId=runCatching{MusicPlaylistImport.youtubeId(query)}.getOrNull()
        if(playlistId!=null)return@coroutineScope MusicNativeExtractor.metadata {
            val ex=ServiceList.YouTube.getPlaylistExtractor("https://www.youtube.com/playlist?list=$playlistId");ex.fetchPage()
            val first=ex.initialPage.items.firstOrNull()?.url?.let {videoId(it)}
            JSONObject().put("resultados",JSONArray().put(JSONObject().put("type","playlist").put("playlist_id",playlistId).put("url","https://www.youtube.com/playlist?list=$playlistId").put("titulo",ex.name).put("artist",ex.uploaderName.orEmpty()).put("count",ex.streamCount).put("thumb",first?.let{"https://i.ytimg.com/vi/$it/mqdefault.jpg"}.orEmpty()))).put("search_source","newpipe")
        }
        val id=videoId(query)
        if(id!=null)return@coroutineScope MusicNativeExtractor.metadata {
            val ex=ServiceList.YouTube.getStreamExtractor("https://www.youtube.com/watch?v=$id");ex.fetchPage()
            JSONObject().put("resultados",JSONArray().put(searchRow(id,ex.name,ex.uploaderName).put("duration",ex.length).put("views",ex.viewCount))).put("search_source","newpipe")
        }
        suspend fun fetch(type:String)=MusicNativeExtractor.metadata {
            val ex=ServiceList.YouTube.getSearchExtractor(query,listOf(type),"");ex.fetchPage()
            val rows=JSONArray()
            ex.initialPage.items.take(20).forEach {item->when(item) {
                is StreamInfoItem -> videoId(item.url)?.let {vid->if(item.name.isNotBlank())rows.put(searchRow(vid,item.name,item.uploaderName.orEmpty()).put("duration",item.duration).put("views",item.viewCount))}
                is PlaylistInfoItem -> runCatching{MusicPlaylistImport.youtubeId(item.url)}.getOrNull()?.let {pid->rows.put(JSONObject().put("type","playlist").put("playlist_id",pid).put("url","https://www.youtube.com/playlist?list=$pid").put("titulo",item.name.take(120)).put("artist",item.uploaderName.orEmpty().take(180)).put("count",item.streamCount).put("thumb",item.thumbnails.firstOrNull()?.url.orEmpty()))}
            }}
            rows
        }.also{onGroup(type,it)}
        val rows=if(filter!="all")fetch(filter) else {
            val songs=async {runCatching {fetch("videos").also {rows->
                ensureActive();onPartial(JSONObject().put("resultados",rows).put("search_source","newpipe").put("partial",true))
            }}}
            val lists=async {runCatching {fetch("playlists")}}
            val a=songs.await();val b=lists.await();ensureActive()
            if(a.isFailure&&b.isFailure)throw a.exceptionOrNull()!!
            val result=JSONArray();a.getOrNull()?.let {for(i in 0 until it.length())result.put(it.get(i))}
            b.getOrNull()?.let {for(i in 0 until minOf(6,it.length()))result.put(it.get(i))};result
        }
        JSONObject().put("resultados",rows).put("search_source","newpipe")
    }
    private fun searchRow(id:String,title:String,artist:String)=JSONObject()
        .put("type","track").put("video_id",id).put("titulo",title.take(120)).put("artist",artist.take(180))
        .put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg")
    private fun videoId(query:String):String? {
        if(query.matches(Regex("[A-Za-z0-9_-]{11}")))return query
        val uri=runCatching { android.net.Uri.parse(query) }.getOrNull() ?: return null
        if(uri.scheme !in listOf("https","http") || uri.userInfo!=null)return null
        val host=uri.host?.lowercase()
        val candidate=when(host) {
            "youtu.be" -> uri.pathSegments.firstOrNull()
            "youtube.com","www.youtube.com","m.youtube.com","music.youtube.com" ->
                if(uri.pathSegments.firstOrNull() in listOf("shorts","live","embed"))uri.pathSegments.getOrNull(1)
                else uri.getQueryParameter("v")
            else -> null
        }
        return candidate?.takeIf { it.matches(Regex("[A-Za-z0-9_-]{11}")) }
    }
    private suspend fun reserveSearch(q:String):JSONObject {
        if(MusicCloud.configured())return MusicCloud.search(q).put("search_source","reserve")
        // Searching must not wait for an unreachable personal PC.
        YoutubeDownloader.prepararMusic(EmilyMusicLibrary.context())
        val target=if(q.startsWith("https://www.youtube.com/")||q.startsWith("https://youtu.be/"))q else "ytsearch8:$q"
        val r=YoutubeDLRequest(target).apply {addOption("--flat-playlist");addOption("--dump-single-json");addOption("--skip-download");addOption("--socket-timeout","15");addOption("--no-warnings");addOption("--retries","1");addOption("--extractor-retries","1")}
        val data=JSONObject(MusicExtractor.execute(r));val entries=data.optJSONArray("entries")?:JSONArray().put(data);val result=JSONArray()
        for(i in 0 until entries.length().coerceAtMost(8)){val entry=entries.optJSONObject(i)?:continue;val id=entry.optString("id");if(!id.matches(Regex("[A-Za-z0-9_-]{11}")))continue;result.put(JSONObject().put("video_id",id).put("titulo",entry.optString("title","Música").take(120)).put("artist",entry.optString("artist",entry.optString("uploader")).take(180)).put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg"))}
        return JSONObject().put("resultados",result)
    }
    fun lyrics(query:String):JSONObject {
        val q=query.trim().take(200);require(q.isNotEmpty())
        val url="https://lrclib.net/api/search?q=${URLEncoder.encode(q,"UTF-8")}"
        val request=Request.Builder().url(url).header("User-Agent","EmilyMusic/1.0 (Android lyrics client)").build()
        http.newCall(request).execute().use {r->check(r.isSuccessful){"Não foi possível consultar a letra"};val raw=r.body!!.string();require(raw.length<=2_000_000);val items=JSONArray(raw);val result=JSONArray()
            for(i in 0 until items.length().coerceAtMost(12)){val m=items.getJSONObject(i);result.put(JSONObject().put("titulo",m.optString("trackName")).put("artista",m.optString("artistName")).put("album",m.optString("albumName")).put("duracao",m.optDouble("duration")).put("instrumental",m.optBoolean("instrumental")).put("sincronizada",m.optString("syncedLyrics").take(150000)).put("texto",m.optString("plainLyrics").take(150000)))}
            return JSONObject().put("resultados",result).put("fonte","LRCLIB")
        }
    }
    private fun request(url:String):JSONObject=http.newCall(Request.Builder().url(url).build()).execute().use{r->check(r.isSuccessful);JSONObject(r.body!!.string())}
}
