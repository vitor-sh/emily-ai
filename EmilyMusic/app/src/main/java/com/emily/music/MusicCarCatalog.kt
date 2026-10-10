package com.emily.music

import android.net.Uri
import android.os.Bundle
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import org.json.JSONArray
import org.json.JSONObject

/** Read-only view of the signed-in account. Does not depend on an Activity or WebView. */
internal class MusicCarCatalog(private val library:MusicLibrarySession) {
    companion object {
        const val ALL="car:all"
        const val ROOT="car:root"
        const val PLAYLISTS="car:playlists"
        const val FAVORITES="car:favorites"
        const val DOWNLOADS="car:downloads"
        const val LOCALS="car:locals"
        private fun playlistId(name:String)="car:playlist:"+Uri.encode(name)
        private fun trackId(parent:String,id:String)="car:track:"+Uri.encode(parent)+":"+id
        private val validId=Regex("[A-Za-z0-9_-]{11}|local_[a-f0-9]{64}")
    }
    fun root()=folder(ROOT,"Biblioteca")
    private fun folder(id:String,title:String,art:String="",subtitle:String=""):MediaItem {
        val tab=id in listOf(ROOT,PLAYLISTS,FAVORITES,DOWNLOADS,LOCALS)
        val icon=when(id){PLAYLISTS->"playlists";FAVORITES->"favorites";DOWNLOADS->"downloads";LOCALS->"locals";ALL->"all";ROOT->"home";else->"playlists"}
        val artwork=if(tab)MusicCarNavigation.icon("com.emily.music",icon) else MusicCarArtwork.cover(library,art,tracks(id),if(id==ALL)"all" else "playlist")
        return MediaItem.Builder().setMediaId(id).setMediaMetadata(MediaMetadata.Builder().setTitle(title).setDisplayTitle(title)
            .setSubtitle(subtitle.takeIf{it.isNotBlank()}).setSupportedCommands((if(id==ALL||id==FAVORITES||id.startsWith("car:playlist:"))listOf(MusicCarDiscovery.DOWNLOAD) else emptyList())+MusicCarNavigation.supported(id)).setIsBrowsable(true).setIsPlayable(false)
            .setMediaType(MediaMetadata.MEDIA_TYPE_FOLDER_PLAYLISTS).setArtworkUri(artwork)
            .setExtras(Bundle().apply{
                putInt(androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_BROWSABLE,androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_VALUE_CONTENT_STYLE_GRID_ITEM)
                putInt(androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_PLAYABLE,androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_VALUE_CONTENT_STYLE_LIST_ITEM)
                if(tab)putInt(androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_KEY_CONTENT_STYLE_SINGLE_ITEM,androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_VALUE_CONTENT_STYLE_CATEGORY_GRID_ITEM)
            }).build()).build()
    }
    private val document by lazy {library.library()}
    private val online by lazy {library.online()}
    private fun lists()=document.getJSONObject("playlists")
    private fun rows(a:JSONArray)=(0 until a.length()).mapNotNull{a.optJSONObject(it)}
    private fun available(track:JSONObject):Boolean {
        val id=track.optString("video_id")
        if(!validId.matches(id))return false
        return library.localUri(id)!=null || (!id.startsWith("local_")&&online)
    }
    fun tracks(parent:String):List<JSONObject> {
        val doc=document;val lists=doc.getJSONObject("playlists")
        val all by lazy {lists.keys().asSequence().flatMap{rows(lists.getJSONObject(it).getJSONArray("musicas")).asSequence()}.distinctBy{it.optString("video_id")}.toList()}
        val chosen=when {
            parent==ALL->all.sortedBy{normalized(it.optString("titulo"))}
            parent==FAVORITES->all.filter{doc.getJSONObject("favoritos").optBoolean(it.optString("video_id"))}
            parent==DOWNLOADS->all.filter{validId.matches(it.optString("video_id"))&&library.localUri(it.optString("video_id"))!=null}
            parent==LOCALS->rows(lists.getJSONObject(EmilyMusicLibrary.LOCALS).getJSONArray("musicas"))
            parent.startsWith("car:playlist:")->lists.optJSONObject(Uri.decode(parent.removePrefix("car:playlist:")))?.optJSONArray("musicas")?.let(::rows)?:emptyList()
            else->emptyList()
        }
        val title=when(parent){ALL->"Todas as músicas";FAVORITES->"Músicas curtidas";DOWNLOADS->"Baixadas";LOCALS->"Músicas locais";else->Uri.decode(parent.removePrefix("car:playlist:")).let{if(it=="default")"Minha seleção" else it}}
        return chosen.filter(::available).distinctBy{it.optString("video_id")}.map {JSONObject(it.toString()).put("origem",if(parent.startsWith("car:playlist:"))title else parent).put("source_title",title)}
    }
    private fun song(parent:String,raw:JSONObject):MediaItem {
        val m=musicTrackLabels(raw) as JSONObject
        return MediaItem.Builder().setMediaId(trackId(parent,m.getString("video_id")))
            .setMediaMetadata(MediaMetadata.Builder().setTitle(m.optString("titulo","Música"))
                .setArtist(m.optString("artist",m.optString("artista"))).setSupportedCommands(listOf(MusicCarDiscovery.OPTIONS,MusicCarDiscovery.ADD,MusicCarDiscovery.FAVORITE,MusicCarDiscovery.DOWNLOAD)+MusicCarNavigation.supported(trackId(parent,m.getString("video_id")))).setIsBrowsable(false).setIsPlayable(true).setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC)
                .setArtworkUri(MusicCarArtwork.track(library,raw)).build()).build()
    }
    fun children(parent:String):List<MediaItem> = when(parent) {
        ROOT->listOf(folder(PLAYLISTS,"Biblioteca"),folder(FAVORITES,"Curtidas"),folder(DOWNLOADS,"Baixadas"),folder(LOCALS,"Local"))
        PLAYLISTS->{val lists=lists();listOf(folder(ALL,"Todas"))+lists.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS && (it!="default"||lists.length()<=2||rows(lists.getJSONObject(it).getJSONArray("musicas")).isNotEmpty())}
            .sortedWith(compareByDescending<String>{lists.getJSONObject(it).optBoolean("pinned")}.thenBy{it.lowercase()})
            .map{folder(playlistId(it),if(it=="default")"Minha seleção" else it,lists.getJSONObject(it).optString("foto"))}.toList()}
        else->tracks(parent).map{song(parent,it)}
    }
    private fun browseId(id:String):String? {
        if(id.startsWith("car:"))return id
        if(!validId.matches(id))return null
        return children(PLAYLISTS).asSequence().flatMap{children(it.mediaId).asSequence()}
            .firstOrNull{it.mediaId.substringAfterLast(':')==id}?.mediaId
    }
    fun item(id:String):MediaItem? {
        if(!id.startsWith("car:"))return browseId(id)?.let(::item)
        if(id==ROOT)return root()
        if(id==ALL)return children(PLAYLISTS).first{it.mediaId==ALL}
        children(ROOT).firstOrNull{it.mediaId==id}?.let{return it}
        if(id.startsWith("car:playlist:"))return children(PLAYLISTS).firstOrNull{it.mediaId==id}
        val parent=parent(id)?:return null
        return children(parent).firstOrNull{it.mediaId==id}
    }
    private fun parent(id:String):String?=id.takeIf{it.startsWith("car:track:")}?.removePrefix("car:track:")?.substringBeforeLast(':',"")?.takeIf{it.isNotBlank()}?.let(Uri::decode)
    data class Selection(val items:List<MediaItem>,val index:Int)
    fun selection(id:String):Selection {
        val selected=browseId(id)?:throw IllegalArgumentException("Faixa inválida")
        val parent=parent(selected)?:throw IllegalArgumentException("Faixa inválida")
        val tracks=tracks(parent);val index=tracks.indexOfFirst{trackId(parent,it.optString("video_id"))==selected}
        require(index>=0){"Esta faixa não está disponível"}
        return Selection(musicItems(JSONArray(tracks),library),index)
    }
    fun single(id:String):MediaItem {val chosen=selection(id);return chosen.items[chosen.index]}
    fun search(query:String):List<MediaItem> {
        val terms=MusicCarQuery.terms(query)
        if(terms.isEmpty())return emptyList()
        return children(ALL).filter {m->MusicCarQuery.matches(terms,"${m.mediaMetadata.title} ${m.mediaMetadata.artist}")}
    }
    private fun normalized(text:String)=MusicCarQuery.normalize(text)
    fun page(items:List<MediaItem>,page:Int,size:Int):List<MediaItem> {
        require(page>=0&&size>0)
        val from=page.toLong()*size
        return if(from>=items.size)emptyList() else items.subList(from.toInt(),minOf(items.size.toLong(),from+size).toInt())
    }
}
