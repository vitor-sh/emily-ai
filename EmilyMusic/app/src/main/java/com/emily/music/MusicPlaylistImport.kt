package com.emily.music

import android.net.Uri
import android.util.Base64
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.stream.StreamInfoItem
import java.util.concurrent.TimeUnit
import java.text.Normalizer
import kotlinx.coroutines.CancellationException

/** Experimental metadata import. Never plays or downloads Spotify previews. */
internal object MusicPlaylistImport {
    private val http=OkHttpClient.Builder().callTimeout(12,TimeUnit.SECONDS).connectTimeout(5,TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()
    private val matches=MusicSearchCache(capacity=200,ttl=24*60*60*1000L)
    private fun page(path:String):String = http.newCall(Request.Builder().url("https://open.spotify.com/$path")
        .header("User-Agent","Mozilla/5.0").build()).execute().use {r->
        check(r.isSuccessful){"Não foi possível ler o Spotify. Confira se a playlist é pública e tente novamente."}
        val output=java.io.ByteArrayOutputStream()
        r.body!!.byteStream().use {input->val buffer=ByteArray(16384);while(true){val n=input.read(buffer);if(n<0)break
            require(output.size()+n<=5_000_000){"Playlist muito grande para a leitura experimental."};output.write(buffer,0,n)}}
        output.toString("UTF-8")
    }
    private fun script(page:String,id:String):String=Regex("<script[^>]*id=[\"']${Regex.escape(id)}[\"'][^>]*>(.*?)</script>",RegexOption.DOT_MATCHES_ALL)
        .find(page)?.groupValues?.get(1) ?: error("O Spotify não disponibilizou a lista. Ela pode ser privada ou o formato mudou.")
    fun spotifyId(link:String):String {
        val u=Uri.parse(link.trim());require(u.scheme=="https"&&u.host=="open.spotify.com"&&u.userInfo==null&&u.port==-1){"No Spotify, use Compartilhar → Copiar link da playlist pública."}
        return Regex("/(?:intl-[a-z]{2}/)?playlist/([A-Za-z0-9]{22})/?").matchEntire(u.path.orEmpty())?.groupValues?.get(1)
            ?: error("Use o link de uma playlist do Spotify, não de uma música ou álbum.")
    }
    fun youtubeId(link:String):String {
        val u=Uri.parse(link.trim());require(u.scheme=="https"&&u.host in listOf("music.youtube.com","youtube.com","www.youtube.com","m.youtube.com")&&u.userInfo==null&&u.port==-1){"Cole o link de uma playlist pública ou não listada do YouTube Music."}
        require(u.path in listOf("/playlist","/watch")){"Use Compartilhar → Copiar link da playlist."}
        val id=u.getQueryParameter("list").orEmpty()
        require(id.matches(Regex("[A-Za-z0-9_-]{10,100}")) && !id.startsWith("RD") && id !in listOf("WL","LL")){"Use uma playlist compartilhável. Mixes e músicas curtidas privadas não são compatíveis."}
        return id
    }
    fun parseSpotify(id:String,public:String,embed:String):JSONObject {
        val uri="spotify:playlist:$id"
        val state=JSONObject(String(Base64.decode(script(public,"initialState"),Base64.DEFAULT),Charsets.UTF_8))
        val e=state.getJSONObject("entities").getJSONObject("items").getJSONObject(uri)
        val total=e.getJSONObject("content").getInt("totalCount")
        val entity=JSONObject(script(embed,"__NEXT_DATA__")).getJSONObject("props").getJSONObject("pageProps")
            .getJSONObject("state").getJSONObject("data").getJSONObject("entity")
        require(e.getString("uri")==uri&&entity.getString("uri")==uri){"A playlist retornada não corresponde ao link."}
        val rows=entity.getJSONArray("trackList")
        require(total in 1..100&&rows.length()==total){"O Spotify retornou ${rows.length()} de $total músicas. Esta importação experimental aceita até 100 e só continua com a lista completa."}
        val tracks=JSONArray()
        for(i in 0 until rows.length()) {
            val r=rows.getJSONObject(i);val tid=r.optString("uri").removePrefix("spotify:track:")
            require(tid.matches(Regex("[A-Za-z0-9]{22}"))&&r.optString("title").isNotBlank()&&r.optString("subtitle").isNotBlank()&&r.optLong("duration")>0){"Uma faixa está indisponível ou sem informações. A importação foi interrompida para não perder músicas."}
            tracks.put(JSONObject().put("spotify_id",tid).put("title",r.getString("title")).put("artists",r.getString("subtitle").replace('\u00a0',' ')).put("duration",r.getLong("duration")/1000))
        }
        // Regional album variants may have different IDs; verify metadata too.
        val preview=e.getJSONObject("content").getJSONArray("items")
        for(i in 0 until preview.length()) {
            val a=preview.getJSONObject(i).getJSONObject("itemV2").getJSONObject("data");val b=rows.getJSONObject(i)
            if(a.optString("uri")!=b.optString("uri")) {
                val artists=a.getJSONObject("artists").getJSONArray("items")
                val names=(0 until artists.length()).joinToString(", "){artists.getJSONObject(it).getJSONObject("profile").getString("name")}
                require(normalize(a.getString("name"))==normalize(b.getString("title"))&&normalize(names)==normalize(b.getString("subtitle"))&&a.getJSONObject("duration").getLong("totalMilliseconds")==b.getLong("duration")){"A playlist mudou durante a leitura. Tente novamente."}
            }
        }
        val photo=sequenceOf(
            entity.optJSONObject("coverArt")?.optJSONArray("sources")?.optJSONObject(0)?.optString("url"),
            e.optJSONObject("images")?.optJSONArray("items")?.optJSONObject(0)?.optJSONArray("sources")?.optJSONObject(0)?.optString("url"),
            entity.optString("imageUri")
        ).filterNotNull().firstOrNull {validCover(it)}.orEmpty()
        return JSONObject().put("name",entity.getString("name")).put("cover",photo).put("tracks",tracks).put("source","spotify")
    }
    suspend fun preview(source:String,link:String):JSONObject {
        if(source=="spotify") {val id=spotifyId(link);return parseSpotify(id,page("playlist/$id"),page("embed/playlist/$id"))}
        require(source=="youtube");val id=youtubeId(link)
        return MusicNativeExtractor.metadata {
            val ex=ServiceList.YouTube.getPlaylistExtractor("https://www.youtube.com/playlist?list=$id");ex.fetchPage()
            val declared=ex.streamCount
            val tracks=JSONArray();var next=ex.initialPage;var pages=0;var partial=false;var warning=""
            val seen=mutableSetOf<String>()
            while(true) {
                for(item in next.items) {
                    val row=runCatching {track(item)}.getOrNull() ?: continue
                    if(!seen.add(row.getString("video_id")))continue
                    if(tracks.length()==200){partial=true;warning="Mostrando as primeiras 200 faixas disponíveis desta playlist.";break}
                    tracks.put(row)
                }
                if(partial||!next.hasNextPage())break
                if(++pages>=8){partial=true;warning="Mostrando as faixas disponíveis que foi possível ler.";break}
                try {next=ex.getPage(next.nextPage)}catch(e:CancellationException){throw e}catch(_:Exception){partial=true;warning="A conexão interrompeu a leitura. Você pode ouvir ou salvar as faixas já carregadas.";break}
            }
            require(tracks.length()>0){"Playlist vazia, privada ou indisponível."}

            JSONObject().put("source","youtube").put("name",ex.name).put("tracks",tracks).put("youtube_id",id).put("declared",declared).put("unavailable",if(partial)0 else (declared-tracks.length()).coerceAtLeast(0)).put("warning",warning).put("cover",runCatching { ex.thumbnails.firstOrNull { validCover(it.url) }?.url }.getOrNull() ?: tracks.optJSONObject(0)?.optString("thumb").orEmpty()).put("uploader",ex.uploaderName.orEmpty())
        }
    }
    private fun track(item:StreamInfoItem):JSONObject {
        val id=Uri.parse(item.url).getQueryParameter("v").orEmpty()
        require(id.matches(Regex("[A-Za-z0-9_-]{11}"))&&item.name.isNotBlank()&&item.name !in listOf("[Private video]","[Deleted video]","Private video","Deleted video","[Vídeo privado]","[Vídeo excluído]")){"Faixa indisponível na playlist."}
        return JSONObject().put("video_id",id).put("titulo",MusicTrackTitle.display(item.name).take(300)).put("titulo_original",item.name.take(1000)).put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg")
            .put("duration",item.duration).put("artist",item.uploaderName.orEmpty())
    }
    private fun normalize(s:String)=Normalizer.normalize(s,Normalizer.Form.NFD).replace(Regex("\\p{M}"),"").lowercase()
        .replace(Regex("[^\\p{L}\\p{N}]+")," ").trim()
    fun validCover(url:String):Boolean {
        val u=runCatching {Uri.parse(url)}.getOrNull() ?: return false
        return u.scheme=="https"&&u.userInfo==null&&u.port==-1&&u.host in listOf("i.scdn.co","image-cdn-ak.spotifycdn.com","image-cdn-fa.spotifycdn.com","i.ytimg.com","yt3.ggpht.com","yt3.googleusercontent.com","lh3.googleusercontent.com")
    }
    suspend fun match(title:String,artists:String,duration:Long):JSONObject {
        require(title.isNotBlank()&&title.length<=300&&artists.length<=500&&duration in 1..86400)
        val cacheKey="$title|$artists|$duration"
        matches.get(cacheKey)?.let {return JSONObject(it)}
        val result=MusicNativeExtractor.metadata {
            val items=linkedMapOf<String,StreamInfoItem>()
            fun collect(query:String,filter:String) {
                val ex=ServiceList.YouTube.getSearchExtractor(query,listOf(filter),"");ex.fetchPage()
                ex.initialPage.items.filterIsInstance<StreamInfoItem>().take(12).forEach {item ->
                    val id=Uri.parse(item.url).getQueryParameter("v").orEmpty()
                    if(id.matches(Regex("[A-Za-z0-9_-]{11}")))items.putIfAbsent(id,item)
                }
            }
            fun ranked()=MusicTrackMatcher.rank(title,artists,duration,items.map {(id,item)->
                MusicTrackMatcher.Candidate(id,item.name,item.uploaderName.orEmpty(),item.duration)})
            val query="${title.take(150)} ${artists.take(150)}"
            // Some regions or extractor changes can affect the music catalogue alone.
            try {collect(query,"music_songs")}catch(e:CancellationException){throw e}catch(_:Exception){}
            if(ranked().none {it.trusted})collect("$query audio","videos")
            if(ranked().none {it.trusted})collect("$query topic","videos")
            val ordered=ranked().take(12)
            JSONObject().put("candidates",JSONArray(ordered.map {r -> track(items.getValue(r.candidate.id))
                .put("suggested",r.trusted).put("score",r.score)}))
        }
        if(result.getJSONArray("candidates").let {a -> (0 until a.length()).any {a.getJSONObject(it).optBoolean("suggested")}})
            matches.put(cacheKey,result.toString())
        return result
    }
}
