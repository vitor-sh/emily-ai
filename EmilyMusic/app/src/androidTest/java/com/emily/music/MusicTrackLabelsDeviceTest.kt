package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class MusicTrackLabelsDeviceTest {
    @Test fun savedTitlesArePresentedWithoutChangingTheOriginalOrPlaylistName() {
        val title="[Official] Celeste Original Soundtrack - 03 - Resurrections"
        val track=JSONObject().put("video_id","aaaaaaaaaaa").put("titulo",title)
        val original=JSONObject().put("name","Celeste Original Soundtrack").put("tracks",JSONArray().put(track))
        val result=musicTrackLabels(original) as JSONObject
        val displayed=result.getJSONArray("tracks").getJSONObject(0)
        assertEquals("Resurrections",displayed.getString("titulo"))
        assertEquals(title,displayed.getString("titulo_original"))
        assertEquals(title,track.getString("titulo"))
        assertEquals(original.getString("name"),result.getString("name"))
        assertEquals(result.toString(),(musicTrackLabels(result) as JSONObject).toString())
    }
    @Test fun spotifyAndLocalTitlesAreKeptExactlyAsProvided() {
        for(extra in listOf("title_source" to "spotify","local" to true)) {
            val track=JSONObject().put("video_id","aaaaaaaaaaa").put("titulo","My Soundtrack - A song").put(extra.first,extra.second)
            assertEquals(track.toString(),(musicTrackLabels(track) as JSONObject).toString())
        }
    }
    @Test fun restoredQueueAndNotificationUseTheSongTitle() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
        val track=JSONObject().put("video_id","aaaaaaaaaaa").put("titulo","Celeste OST - 03 - Resurrections").put("source_title","Celeste Original Soundtrack")
        val item=musicItems(JSONArray().put(track)).single()
        assertEquals("Resurrections",item.mediaMetadata.title.toString())
        val saved=JSONObject(item.mediaMetadata.extras!!.getString("track")!!)
        assertEquals("Celeste Original Soundtrack",saved.getString("source_title"))
        assertEquals("Celeste OST - 03 - Resurrections",saved.getString("titulo_original"))
    }
}
