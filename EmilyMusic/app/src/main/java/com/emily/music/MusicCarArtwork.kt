package com.emily.music

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.media3.common.MediaItem
import org.json.JSONArray
import java.io.File
import java.security.MessageDigest

/** Only cover descriptors are shared with the connected media controller, never account files. */
internal object MusicCarArtwork {
    private val localName=Regex("(?:local_[a-f0-9]{64}|[A-Za-z0-9_-]{11}|playlist-[a-f0-9]{64})\\.(?:jpg|png|webp)")
    private fun sources(library:MusicLibrarySession,photo:String):String? {
        if(photo.startsWith("https://appassets.androidplatform.net/art/${library.accountId}/")){
            val name=Uri.parse(photo).lastPathSegment.orEmpty()
            if(localName.matches(name)&&File(library.covers,name).isFile)return "local:$name"
        }
        if(photo.startsWith("https://")&&!photo.contains("appassets.androidplatform.net"))return if(Uri.parse(photo).host=="i.ytimg.com")photo.replace("/mqdefault.jpg","/hqdefault.jpg") else photo
        return null
    }
    fun cover(library:MusicLibrarySession,photo:String,tracks:List<org.json.JSONObject>,kind:String="playlist"):Uri {
        val explicit=sources(library,photo)
        if(explicit!=null&&explicit.startsWith("https://")&&Uri.parse(explicit).host !in setOf("i.ytimg.com","img.youtube.com","i.scdn.co","mosaic.scdn.co","image-cdn-ak.spotifycdn.com"))return Uri.parse(explicit)
        // Explicit covers remain intact; generated collages use up to four distinct artworks.
        val pictures=if(explicit!=null)listOf(explicit) else tracks.asSequence().mapNotNull{track->
            val id=track.optString("video_id")
            val local=if(id.matches(Regex("local_[a-f0-9]{64}|[A-Za-z0-9_-]{11}")))File(library.covers,"$id.jpg") else null
            if(local?.isFile==true)"local:${local.name}" else sources(library,track.optString("thumb"))
        }.distinct().take(4).toList()
        val descriptor=org.json.JSONObject().put("images",JSONArray(pictures)).put("kind",kind).toString()
        val key=MessageDigest.getInstance("SHA-256").digest(descriptor.toByteArray()).joinToString(""){"%02x".format(it)}
        val directory=File(library.covers,"car").apply{mkdirs()}
        val file=File(directory,"$key.json")
        synchronized(this){if(!file.exists())android.util.AtomicFile(file).let{atomic->val output=atomic.startWrite();try{output.write(descriptor.toByteArray());atomic.finishWrite(output)}catch(e:Exception){atomic.failWrite(output);throw e}}}
        return Uri.parse("content://com.emily.music.car-art/${library.accountId}/$key")
    }
    fun track(library:MusicLibrarySession,raw:org.json.JSONObject):Uri {
        val id=raw.optString("video_id")
        val photo=if(id.matches(Regex("local_[a-f0-9]{64}|[A-Za-z0-9_-]{11}"))&&File(library.covers,"$id.jpg").isFile)"https://appassets.androidplatform.net/art/${library.accountId}/$id.jpg" else raw.optString("thumb")
        return cover(library,photo,listOf(raw),"track")
    }
    fun grant(context:Context,packageName:String,items:List<MediaItem>) {
        items.mapNotNull{it.mediaMetadata.artworkUri}.filter{it.authority=="${context.packageName}.car-art"}.distinct().forEach{
            if(packageName!="android.media.session.MediaController")context.grantUriPermission(packageName,it,Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
    fun descriptor(context:Context,uri:Uri):Pair<MusicLibrarySession,File> {
        val library=EmilyMusicLibrary.session()
        val parts=uri.pathSegments
        if(!MusicCloud.locallyApproved(context)||library.closed||uri.authority!="${context.packageName}.car-art"||parts.size!=2||parts[0]!=library.accountId||!parts[1].matches(Regex("[a-f0-9]{64}"))||uri.query!=null)
            throw java.io.FileNotFoundException("Capa indisponível")
        val file=File(library.covers,"car/${parts[1]}.json")
        if(!file.isFile)throw java.io.FileNotFoundException("Capa indisponível")
        return library to file
    }
}
