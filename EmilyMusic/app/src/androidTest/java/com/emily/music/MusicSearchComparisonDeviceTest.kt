package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.json.*
import org.schabi.newpipe.extractor.ServiceList
import org.schabi.newpipe.extractor.stream.StreamInfoItem
import java.io.File

/** Compara no mesmo aparelho/rede, sem trocar a busca pública nem alterar a biblioteca. */
class MusicSearchComparisonDeviceTest {
    @Test fun compareOfficialAndIntegratedSearch()=runBlocking(Dispatchers.IO) {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context))
        val queries=listOf("The Score The Fear","Lena Raine Resurrections Celeste","NEFFEX Careless",
            "Shiro Sagisu never meant to belong","Panic At The Disco House of Memories","Genshin Impact Ronova boss theme")
        val report=JSONArray()
        val caches=mapOf("official" to MusicSearchCache(),"newpipe" to MusicSearchCache())
        suspend fun call(provider:String,query:String):JSONObject=if(provider=="official")MusicCloud.search(query) else MusicNativeExtractor.metadata {
            val extractor=ServiceList.YouTube.getSearchExtractor(query,listOf("videos"),"")
            extractor.fetchPage()
            val results=JSONArray()
            extractor.initialPage.items.filterIsInstance<StreamInfoItem>().take(8).forEach {item->
                val id=android.net.Uri.parse(item.url).getQueryParameter("v")
                if(id!=null&&id.matches(Regex("[A-Za-z0-9_-]{11}"))&&item.name.isNotBlank())results.put(JSONObject()
                    .put("video_id",id).put("titulo",item.name.take(120)).put("artist",item.uploaderName.orEmpty().take(180))
                    .put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg"))
            }
            JSONObject().put("resultados",results)
        }
        fun emit(row:JSONObject) {report.put(row);File(context.cacheDir,"search-comparison.json").writeText(report.toString(2))
            instrumentation.sendStatus(0,android.os.Bundle().apply{putString("stream","\nSEARCH_COMPARE $row\n")})}
        for(round in 0..1)for((index,q) in queries.withIndex()) {
            val order=if((index+round)%2==0)listOf("official","newpipe") else listOf("newpipe","official")
            for(provider in order) {
                val start=android.os.SystemClock.elapsedRealtime()
                val row=JSONObject().put("provider",provider).put("query",q).put("round",round).put("cache","network")
                try {
                    val data=call(provider,q);val results=data.getJSONArray("resultados")
                    row.put("ms",android.os.SystemClock.elapsedRealtime()-start).put("count",results.length()).put("results",results)
                    require(results.length()>0){"Busca vazia"};caches.getValue(provider).put(q,data.toString())
                }catch(e:CancellationException){throw e}catch(e:Exception){row.put("ms",android.os.SystemClock.elapsedRealtime()-start).put("error",e.message?:e.javaClass.simpleName)}
                emit(row)
                val cacheStart=android.os.SystemClock.elapsedRealtime()
                caches.getValue(provider).get(q)?.let {cached->
                    val result=JSONObject(cached)
                    emit(JSONObject().put("provider",provider).put("query",q).put("round",round).put("cache","local")
                        .put("ms",android.os.SystemClock.elapsedRealtime()-cacheStart).put("count",result.getJSONArray("resultados").length()))
                }
            }
        }
        assertEquals(24,(0 until report.length()).count {report.getJSONObject(it).optString("cache")=="network"})
    }
}
