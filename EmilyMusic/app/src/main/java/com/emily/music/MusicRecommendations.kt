package com.emily.music

import android.net.Uri
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.stream.StreamInfoItem

/** Metadata only: discovery never adds songs to the library. */
internal object MusicRecommendations {
    private val cache=MusicSearchCache(capacity=80,ttl=60*60*1000L)
    suspend fun related(track:JSONObject):JSONArray {
        val id=track.getString("video_id")
        cache.get(id)?.let {return JSONArray(it)}
        val rows=withTimeout(15000L) {
            val related=try {MusicNativeExtractor.metadata {
                val ex=ServiceList.YouTube.getStreamExtractor("https://www.youtube.com/watch?v=$id");ex.fetchPage()
                rows(ex.relatedItems?.items.orEmpty().filterIsInstance<StreamInfoItem>())
            }}catch(e:CancellationException){throw e}catch(_:Exception){JSONArray()}
            if(related.length()>0)related else MusicNativeExtractor.metadata {
                val query=(track.optString("artist").ifBlank {track.optString("titulo")}+" music audio").take(200)
                val ex=ServiceList.YouTube.getSearchExtractor(query,listOf("videos"),"");ex.fetchPage()
                rows(ex.initialPage.items.filterIsInstance<StreamInfoItem>())
            }
        }
        if(rows.length()>0)cache.put(id,rows.toString())
        return rows
    }
    private fun rows(items:List<StreamInfoItem>):JSONArray {
        val rows=JSONArray();val seen=mutableSetOf<String>()
        for(m in items){val id=Uri.parse(m.url).getQueryParameter("v").orEmpty()
            if(!id.matches(Regex("[A-Za-z0-9_-]{11}"))||m.name.isBlank()||m.duration<=0||!seen.add(id))continue
            rows.put(JSONObject().put("video_id",id).put("titulo",m.name.take(120)).put("artist",m.uploaderName.orEmpty().take(180))
                .put("duration",m.duration).put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg"))
            if(rows.length()==20)break
        };return rows
    }
}
