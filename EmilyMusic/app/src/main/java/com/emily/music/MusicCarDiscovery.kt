package com.emily.music

import android.content.Context
import android.os.Bundle
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.session.CommandButton
import androidx.media3.session.SessionCommand
import androidx.media.utils.MediaConstants
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Account-scoped discovery. Opaque IDs authorize only results actually returned to this browser. */
internal class MusicCarDiscovery(
    private val library:MusicLibrarySession,
    private val find:suspend (String,String)->JSONObject={q,f->EmilyMusicSearch.search(q,f)},
    private val preview:suspend (String)->JSONObject={MusicPlaylistImport.preview("youtube",it)},
    private val connected:()->Boolean={library.online()}
) {
    companion object {
        const val OPTIONS="emily.music.car.options"
        const val SAVE="emily.music.car.save"
        const val ADD="emily.music.car.add"
        const val FAVORITE="emily.music.car.favorite"
        const val DOWNLOAD="emily.music.car.download"
        const val ADD_HERE="emily.music.car.add_here"
        const val FILTERS="emily.music.car.filters"
        const val RETRY="emily.music.car.retry"
        // Video and playlist IDs are case-sensitive; natural-language searches may ignore accents.
        internal fun queryKey(q:String)=if(q.contains("://")||q.matches(Regex("[A-Za-z0-9_-]{11}")))q else MusicCarQuery.normalize(q)
        val commands=listOf(OPTIONS,SAVE,ADD,FAVORITE,DOWNLOAD,ADD_HERE,FILTERS,RETRY)
        fun buttons(ctx:Context)=listOf(
            Triple(OPTIONS,"Mais ações","all"),Triple(SAVE,"Salvar na biblioteca","save"),Triple(ADD,"Adicionar à playlist","add"),
            Triple(FAVORITE,"Curtir / descurtir","favorites"),Triple(DOWNLOAD,"Baixar","downloads"),
            Triple(ADD_HERE,"Adicionar aqui","add"),Triple(FILTERS,"Filtros","filter"),Triple(RETRY,"Tentar novamente","retry")
        ).map{(action,label,icon)->CommandButton.Builder(CommandButton.ICON_UNDEFINED).setDisplayName(label)
            .setIconUri(MusicCarNavigation.icon(ctx.packageName,icon)).setSessionCommand(SessionCommand(action,Bundle.EMPTY)).build()}
    }
    private class Node(val kind:String,val title:String,val parent:String,val row:JSONObject=JSONObject(),val query:String="",val filter:String="all") {
        var children:List<MediaItem>?=null
        var data:JSONObject?=null
        var filtersId:String?=null
        val operation="car-"+UUID.randomUUID()
    }
    private data class Query(val id:String,val at:Long)
    private val lock=Mutex()
    private val nodes=linkedMapOf<String,Node>()
    private val queries=linkedMapOf<String,Query>()
    private fun node(n:Node):String {
        val id="car:discover:"+UUID.randomUUID()
        nodes[id]=n
        return id
    }
    fun owns(id:String)=id.startsWith("car:discover:")
    private fun rows(a:JSONArray)=(0 until a.length()).mapNotNull{a.optJSONObject(it)}
    private fun actions(n:Node)=when(n.kind){
        "track"->listOf(OPTIONS,SAVE,ADD,FAVORITE,DOWNLOAD)
        "playlist"->listOf(OPTIONS,SAVE,DOWNLOAD)
        "destination"->listOf(ADD_HERE)
        "choice"->listOf(n.row.getString("action"))
        "query"->listOf(FILTERS,RETRY)
        "status"->listOf(RETRY)
        else->emptyList()
    }+MusicCarNavigation.commands
    private fun item(id:String,n:Node):MediaItem {
        val raw=n.row
        val meta=MediaMetadata.Builder().setTitle(n.title).setDisplayTitle(n.title).setSupportedCommands(actions(n))
            .setIsPlayable(n.kind=="track").setIsBrowsable(n.kind!="track")
            .setMediaType(if(n.kind=="track")MediaMetadata.MEDIA_TYPE_MUSIC else MediaMetadata.MEDIA_TYPE_FOLDER_PLAYLISTS)
            .setExtras(Bundle().apply{
                putInt(MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_BROWSABLE,2)
                putInt(MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_PLAYABLE,1)
                putString(MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_GROUP_TITLE,when(n.kind){"track"->"Músicas";"playlist"->"Playlists";else->"Busca"})
            })
        if(n.kind=="track")meta.setArtist(raw.optString("artist")).setArtworkUri(MusicCarArtwork.track(library,raw))
        else if(n.kind=="playlist")meta.setArtworkUri(MusicCarArtwork.cover(library,raw.optString("thumb"),emptyList(),"playlist"))
        else meta.setArtworkUri(MusicCarNavigation.icon("com.emily.music",if(n.kind=="filters"||n.kind=="query")"filter" else if(n.kind=="status")"retry" else "playlists"))
        return MediaItem.Builder().setMediaId(id).setMediaMetadata(meta.build()).build()
    }
    suspend fun search(query:String):List<MediaItem> = lock.withLock {
        val q=query.trim().take(300)
        if(q.isEmpty())return@withLock emptyList()
        if(nodes.size>6000){nodes.clear();queries.clear()}
        val key=queryKey(q)
        val cached=queries[key]?.takeIf{System.currentTimeMillis()-it.at<5*60_000&&nodes.containsKey(it.id)}
        val id=cached?.id?:node(Node("query",q,MusicCarCatalog.ROOT,query=q)).also{queries[key]=Query(it,System.currentTimeMillis())}
        results(id,nodes.getValue(id))
    }
    private suspend fun results(id:String,n:Node):List<MediaItem> {
        val catalog=MusicCarCatalog(library)
        val localSongs=catalog.search(n.query)
        val terms=MusicCarQuery.terms(n.query)
        val localLists=catalog.children(MusicCarCatalog.PLAYLISTS).filter{it.mediaId!=MusicCarCatalog.ALL&&MusicCarQuery.matches(terms,it.mediaMetadata.title.toString())}
        val local=when(n.filter){"playlists"->localLists;"library"->localLists+localSongs;"videos"->localSongs;"views","short","long"->emptyList();else->localLists+localSongs}
        val filters=n.filtersId?:node(Node("filters","Filtros",id,query=n.query)).also{n.filtersId=it}
        val header=item(filters,nodes.getValue(filters))
        if(n.filter=="library")return listOf(header)+local
        if(n.data==null&&connected()) {
            try {n.data=withTimeout(35_000){find(n.query,when(n.filter){"playlists"->"playlists";"all"->"all";else->"videos"})}}
            catch(e:CancellationException){if(e is kotlinx.coroutines.TimeoutCancellationException)n.data=JSONObject().put("aviso","A busca demorou demais. Tente novamente.") else throw e}
            catch(_:Exception){n.data=JSONObject().put("aviso","Não foi possível buscar agora. Tente novamente.")}
        }
        val source=rows(n.data?.optJSONArray("resultados")?:JSONArray())
        val selected=when(n.filter){
            "views"->source.filter{it.optString("type")!="playlist"}.sortedByDescending{it.optLong("views")}
            "short"->source.filter{it.optString("type")!="playlist"&&it.optLong("duration") in 1..239}
            "long"->source.filter{it.optString("type")!="playlist"&&it.optLong("duration")>=1200}
            else->source
        }
        if(n.children==null&&n.data!=null)n.children=selected.take(60).mapNotNull{r->
            val playlist=r.optString("type")=="playlist"
            if(playlist&&!r.optString("playlist_id").matches(Regex("[A-Za-z0-9_-]{10,100}")))return@mapNotNull null
            if(!playlist&&!r.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}")))return@mapNotNull null
            val raw=JSONObject(r.toString()).put("source_title","Busca: ${n.query}")
            val child=node(Node(if(playlist)"playlist" else "track",raw.optString("titulo","Música"),id,raw))
            item(child,nodes.getValue(child))
        }
        // Local results are refreshed after saving; online nodes remain stable for playback and menus.
        val online=connected()
        val remote=n.children.orEmpty().filter {m->
            val entry=nodes[m.mediaId]?:return@filter false
            val video=entry.row.optString("video_id")
            val available=online||if(entry.kind=="playlist")rows(entry.data?.optJSONArray("tracks")?:JSONArray()).any{library.localUri(it.optString("video_id"))!=null} else library.localUri(video)!=null
            available&&(video.isEmpty()||localSongs.none{song->song.mediaId.endsWith(":$video")})
        }
        val warning=if(!connected())"Sem internet. Mostrando a biblioteca disponível." else n.data?.optString("aviso").orEmpty()
        val info=if(warning.isNotBlank())listOf(status(id,warning)) else if(local.isEmpty()&&remote.isEmpty())listOf(status(id,"Nenhum resultado. Tente outra busca ou filtro.")) else emptyList()
        return listOf(header)+local+remote+info
    }
    private fun status(parent:String,message:String):MediaItem {val id=node(Node("status",message,parent));return item(id,nodes.getValue(id))}
    private suspend fun playlist(n:Node):JSONObject {
        n.data?.let{return it}
        check(connected()){"Sem internet para abrir esta playlist."}
        val id=n.row.getString("playlist_id")
        val data=withTimeout(35_000){preview("https://www.youtube.com/playlist?list=$id")}
        require(data.optString("youtube_id")==id&&data.optJSONArray("tracks")?.length() in 1..200){"Playlist indisponível."}
        require(rows(data.getJSONArray("tracks")).all{it.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))&&it.optString("titulo").isNotBlank()})
        n.data=data
        return data
    }
    suspend fun children(id:String):List<MediaItem>? = lock.withLock {
        val n=nodes[id]?:return@withLock if(owns(id))listOf(status(MusicCarCatalog.ROOT,"A busca expirou. Pesquise novamente.")) else null
        when(n.kind){
            "query"->results(id,n)
            "filters"->n.children?:listOf("all" to "Tudo","videos" to "Músicas","playlists" to "Playlists","views" to "Mais vistas","short" to "Até 4 min","long" to "20 min ou mais","library" to "Na biblioteca").map{(filter,label)->
                val child=node(Node("query",label,id,query=n.query,filter=filter));item(child,nodes.getValue(child))}.also{n.children=it}
            "playlist"->{try{
                val data=playlist(n)
                if(n.children==null)n.children=rows(data.getJSONArray("tracks")).map{r->val raw=JSONObject(r.toString()).put("source_title",data.getString("name"));val child=node(Node("track",raw.getString("titulo"),id,raw));item(child,nodes.getValue(child))}
                val warning=data.optString("warning").takeIf{it.isNotBlank()}?:data.optLong("unavailable").takeIf{it>0}?.let{"$it faixas indisponíveis nesta playlist."}
                n.children.orEmpty().filter{connected()||library.localUri(nodes.getValue(it.mediaId).row.getString("video_id"))!=null}+if(warning!=null)listOf(status(id,warning)) else emptyList()
            }catch(e:CancellationException){if(e is kotlinx.coroutines.TimeoutCancellationException)listOf(status(id,"A playlist demorou demais. Tente novamente.")) else throw e}catch(_:Exception){listOf(status(id,"Não foi possível abrir a playlist. Tente novamente."))}}
            "destinations"->n.children?:MusicCarCatalog(library).children(MusicCarCatalog.PLAYLISTS).filter{it.mediaId!=MusicCarCatalog.ALL}.map {folder->
                val child=node(Node("destination",folder.mediaMetadata.title.toString(),id,JSONObject(n.row.toString()).put("destination",android.net.Uri.decode(folder.mediaId.removePrefix("car:playlist:")))))
                item(child,nodes.getValue(child))}.also{n.children=it}
            "options"->n.children?:n.row.getJSONArray("actions").let {a->(0 until a.length()).map {index->
                val action=a.getString(index)
                val label=when(action){SAVE->"Salvar na biblioteca";ADD->"Adicionar à playlist";FAVORITE->"Curtir / descurtir";DOWNLOAD->"Baixar";else->"Ação"}
                val child=node(Node("choice",label,id,JSONObject().put("action",action).put("target",n.row.getString("target"))));item(child,nodes.getValue(child))
            }}.also{n.children=it}
            "status"->if(nodes[n.parent]?.kind=="query")results(n.parent,nodes.getValue(n.parent)) else emptyList()
            else->emptyList()
        }
    }
    suspend fun preparationIds(items:List<MediaItem>):List<String> = lock.withLock {
        items.mapNotNull{nodes[it.mediaId]?.row?.optString("video_id")}
            .filter{it.matches(Regex("[A-Za-z0-9_-]{11}"))}.distinct().take(2)
    }
    suspend fun getItem(id:String):MediaItem?=lock.withLock {nodes[id]?.let{item(id,it)}}
    suspend fun parent(id:String):String?=lock.withLock {
        val parent=nodes[id]?.parent?:return@withLock null
        if(owns(parent)&&!nodes.containsKey(parent))MusicCarCatalog.ROOT
        else MusicCarNavigation.browseTarget(parent,nodes[parent]?.takeIf{it.kind=="track"}?.parent)
    }
    suspend fun selection(id:String):MusicCarCatalog.Selection?=lock.withLock {
        val n=nodes[id]?:return@withLock null
        require(n.kind=="track"){"Escolha uma música."}
        val siblings=nodes[n.parent]?.children.orEmpty().mapNotNull{nodes[it.mediaId]}.filter{it.kind=="track"}
        val tracks=(if(siblings.isEmpty())listOf(n) else siblings).filter{connected()||library.localUri(it.row.getString("video_id"))!=null}
        require(n in tracks){"Esta faixa precisa de internet ou de um download no celular."}
        MusicCarCatalog.Selection(musicItems(JSONArray(tracks.map{it.row}),library),tracks.indexOf(n).coerceAtLeast(0))
    }
    private fun raw(id:String):JSONObject {
        nodes[id]?.takeIf{it.kind=="track"||it.kind=="destination"}?.let{return JSONObject(it.row.toString())}
        val catalog=MusicCarCatalog(library);val selected=catalog.selection(id)
        return JSONObject(selected.items[selected.index].mediaMetadata.extras!!.getString("track")!!)
    }
    private fun saved(raw:JSONObject)=MusicCarCatalog(library).tracks(MusicCarCatalog.ALL).any{it.optString("video_id")==raw.getString("video_id")}
    private fun copy(raw:JSONObject,destination:String) {check(library.mutate("music_copiar",JSONArray().put(destination).put(raw))==true){"Não foi possível adicionar. A playlist pode estar cheia ou ter sido removida."}}
    suspend fun action(action:String,requestedId:String):Bundle=lock.withLock {
        check(!library.closed&&library.uid==MusicCloud.currentUser()?.uid){"Entre novamente na sua conta."}
        val choice=nodes[requestedId]?.takeIf{it.kind=="choice"}
        if(choice!=null)require(choice.row.getString("action")==action){"Ação indisponível"}
        val id=choice?.row?.getString("target")?:requestedId
        val n=nodes[id]
        var browse:String?=null
        val message=when(action){
            OPTIONS->{
                val supported=if(n?.kind=="playlist")listOf(SAVE,DOWNLOAD) else if(id==MusicCarCatalog.ALL||id==MusicCarCatalog.FAVORITES||id.startsWith("car:playlist:"))listOf(DOWNLOAD) else {raw(id);listOf(SAVE,ADD,FAVORITE,DOWNLOAD)}
                browse=node(Node("options","Mais ações",id,JSONObject().put("target",id).put("actions",JSONArray(supported))));"Escolha a ação no menu do item"
            }
            FILTERS->{require(n?.kind=="query");browse=node(Node("filters","Filtros",id,query=n.query));"Escolha um filtro"}
            RETRY->{val target=if(n?.kind=="status")nodes[n.parent] else n;require(target!=null);target.data=null;target.children=null;browse=if(n?.kind=="status")n.parent else id;"Tente abrir novamente"}
            ADD->{val r=raw(id);browse=node(Node("destinations","Adicionar à playlist",id,r));"Escolha uma playlist e use Adicionar aqui"}
            ADD_HERE->{require(n?.kind=="destination");copy(raw(id),n.row.getString("destination"));browse=n.parent;"Adicionada à playlist"}
            SAVE,DOWNLOAD->{
                val tracks=if(n?.kind=="playlist") {
                    val p=playlist(n)
                    val receipt=library.importPlaylist(p.getString("name").take(100),p.getJSONArray("tracks"),n.operation,p.optString("cover"),youtubeId=p.getString("youtube_id"))
                    check(receipt.optBoolean("ok"));p.getJSONArray("tracks")
                }else if(action==DOWNLOAD&&(id==MusicCarCatalog.ALL||id==MusicCarCatalog.FAVORITES||id.startsWith("car:playlist:"))){
                    val rows=MusicCarCatalog(library).tracks(id);require(rows.isNotEmpty()){"Esta coleção está vazia ou indisponível."};JSONArray(rows)
                }else {val r=raw(id);if(!saved(r))copy(r,"default");JSONArray().put(r)}
                if(action==DOWNLOAD){val count=EmilyMusicAudio.download(tracks);if(count>0)"$count músicas na fila de download" else "As músicas já estão baixadas ou na fila"}
                else if(n?.kind=="playlist")"Playlist salva${n.data?.optString("warning")?.takeIf{it.isNotBlank()}?.let{". $it"}.orEmpty()}" else "Música salva na biblioteca"
            }
            FAVORITE->{val r=raw(id);val key=r.getString("video_id");val next=!library.library().getJSONObject("favoritos").optBoolean(key);if(next&&!saved(r))copy(r,"default");check(library.mutate("playlist_favoritar",JSONArray().put(key).put(next))==true);if(next)"Música curtida" else "Curtida removida"}
            else->throw IllegalArgumentException("Ação indisponível")
        }
        Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_MESSAGE,message);if(browse!=null)putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE,browse) else putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_REFRESH_ITEM,id)}
    }
}
