package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.json.*
import java.io.File
import java.util.UUID

class MusicImportDeviceTest {
    @Test fun actualSpotify32TracksAndYouTubeMatching()=runBlocking {
        val args=InstrumentationRegistry.getArguments()
        val link=args.getString("spotifyPlaylist")?:"https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF"
        val expected=args.getString("spotifyCount")?.toInt()?:50
        val data=withContext(Dispatchers.IO){MusicPlaylistImport.preview("spotify",link)}
        val tracks=data.getJSONArray("tracks");assertEquals(expected,tracks.length())
        val first=tracks.getJSONObject(0)
        val result=MusicPlaylistImport.match(first.getString("title"),first.getString("artists"),first.getLong("duration"))
        assertTrue("Busca deve encontrar versões para revisar",result.getJSONArray("candidates").length()>0)
        android.util.Log.i("MusicImportTest","Spotify tracks=${tracks.length()}, YouTube candidates=${result.getJSONArray("candidates").length()}")
        Unit
    }
    @Test fun realMatchingSamplesAndCover()=runBlocking(Dispatchers.IO) {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val args=InstrumentationRegistry.getArguments()
        val link=args.getString("spotifyPlaylist")?:"https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF"
        val expected=args.getString("spotifyCount")?.toInt()?:50
        val data=MusicPlaylistImport.preview("spotify",link)
        assertEquals(expected,data.getJSONArray("tracks").length())
        assertTrue("Source playlist cover should be retained",MusicPlaylistImport.validCover(data.getString("cover")))
        val report=JSONArray()
        for(i in listOf(0,expected/6,expected/3,expected/2,expected*2/3,expected-1).distinct()) {
            val track=data.getJSONArray("tracks").getJSONObject(i);val start=android.os.SystemClock.elapsedRealtime()
            val matches=MusicPlaylistImport.match(track.getString("title"),track.getString("artists"),track.getLong("duration"))
            val candidates=matches.getJSONArray("candidates")
            assertTrue(candidates.length()>0)
            report.put(JSONObject().put("track",track).put("ms",android.os.SystemClock.elapsedRealtime()-start).put("candidates",candidates))
        }
        File(context.cacheDir,"import-v10-matches.json").writeText(report.toString(2))
        InstrumentationRegistry.getInstrumentation().sendStatus(0,android.os.Bundle().apply{putString("stream","\nIMPORT_MATCH_SAMPLE ${report.toString()}\n")})
    }
    @Test fun publicYoutubePlaylistIsReadable()=runBlocking {
        val data=MusicPlaylistImport.preview("youtube","https://music.youtube.com/playlist?list=PLe1jcCJWvkWiWLp9h3ge0e5v7n6kxEfOG")
        assertTrue(data.getJSONArray("tracks").length()>0)
        android.util.Log.i("MusicImportTest","YouTube tracks=${data.getJSONArray("tracks").length()}")
        Unit
    }
    @Test fun invalidLinksAndTruncatedSpotifyAreRefused() {
        for(link in listOf("https://evil.test/playlist/AAAAAAAAAAAAAAAAAAAAAA","https://open.spotify.com/track/AAAAAAAAAAAAAAAAAAAAAA")) {
            try {MusicPlaylistImport.spotifyId(link);fail("Invalid source must fail")}catch(_:IllegalArgumentException){}catch(_:IllegalStateException){}
        }
        val pid="AAAAAAAAAAAAAAAAAAAAAA";val uri="spotify:playlist:$pid"
        val public=JSONObject().put("entities",JSONObject().put("items",JSONObject().put(uri,JSONObject().put("uri",uri).put("content",JSONObject().put("totalCount",200)))))
        val embed=JSONObject().put("props",JSONObject().put("pageProps",JSONObject().put("state",JSONObject().put("data",JSONObject().put("entity",JSONObject().put("uri",uri).put("trackList",JSONArray()))))))
        val p="<script id=\"initialState\">${android.util.Base64.encodeToString(public.toString().toByteArray(),android.util.Base64.NO_WRAP)}</script>"
        val e="<script id=\"__NEXT_DATA__\">$embed</script>"
        try {MusicPlaylistImport.parseSpotify(pid,p,e);fail("Truncation must fail")}catch(_:IllegalArgumentException){}
    }
    @Test fun isolatedBatchImportIsIdempotentAndDoesNotChangePlayback()=runBlocking {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val uid=MusicCloud.currentUser()?.uid;org.junit.Assume.assumeNotNull(uid)
        val root=File(base.cacheDir,"import-test-${UUID.randomUUID()}").apply{mkdirs()}
        val ctx=object:android.content.ContextWrapper(base) {
            override fun getApplicationContext():android.content.Context=this
            override fun getFilesDir()=File(root,"files").apply{mkdirs()}
            override fun getExternalFilesDir(type:String?)=File(root,"external").apply{mkdirs()}
        }
        val lib=withContext(Dispatchers.IO){MusicLibrarySession(ctx,uid!!,false)}
        try {
            val playback=lib.playerState().toString()
            val tracks=JSONArray().put(JSONObject().put("video_id","dQw4w9WgXcQ").put("titulo","Test"))
            tracks.put(tracks.getJSONObject(0));val operation=UUID.randomUUID().toString()
            val pending=JSONArray().put(JSONObject().put("spotify_id","AAAAAAAAAAAAAAAAAAAAAA").put("title","Missing song").put("artists","Artist").put("duration",180))
            val first=lib.importPlaylist("Import test",tracks,operation,"https://i.scdn.co/image/test",pending)
            assertEquals(1,first.getInt("added"));assertEquals(1,first.getInt("duplicates"))
            assertEquals(first.toString(),lib.importPlaylist("Import test",tracks,operation).toString())
            assertEquals(playback,lib.playerState().toString())
            assertEquals(1,lib.library().getJSONObject("playlists").getJSONObject("Import test").getJSONArray("musicas").length())
            val imported=lib.library().getJSONObject("playlists").getJSONObject("Import test")
            assertEquals("https://i.scdn.co/image/test",imported.getString("foto"));assertEquals(1,imported.getJSONArray("pending").length())
            lib.mutate("playlist_foto",JSONArray().put("Import test").put("https://i.scdn.co/image/new"))
            assertEquals(1,lib.library().getJSONObject("playlists").getJSONObject("Import test").getJSONArray("pending").length())
            val resolved=JSONObject().put("video_id","K5U7b_E14cE").put("titulo","Resolved")
            lib.resolveImport("Import test","AAAAAAAAAAAAAAAAAAAAAA",resolved)
            lib.resolveImport("Import test","AAAAAAAAAAAAAAAAAAAAAA",resolved)
            assertEquals(0,lib.library().getJSONObject("playlists").getJSONObject("Import test").getJSONArray("pending").length())
            assertEquals(2,lib.library().getJSONObject("playlists").getJSONObject("Import test").getJSONArray("musicas").length())
            val emptyPending=lib.importPlaylist("Only pending",JSONArray(),UUID.randomUUID().toString(),"",pending)
            assertEquals(0,emptyPending.getInt("added"));assertEquals(1,emptyPending.getInt("pending"))
            val duplicateName=lib.importPlaylist("Import test",tracks,UUID.randomUUID().toString())
            assertEquals("Import test (2)",duplicateName.getString("name"))
            val youtubeId="PL1234567890abcdefghij"
            val yt=lib.importPlaylist("YouTube fixture",tracks,"youtube_$youtubeId",youtubeId=youtubeId)
            val ytName=yt.getString("name")
            assertEquals(ytName,lib.importPlaylist("Renamed source",tracks,UUID.randomUUID().toString(),youtubeId=youtubeId).getString("name"))
            lib.mutate("playlist_renomear",JSONArray().put(ytName).put("YouTube renamed"))
            assertEquals("YouTube renamed",lib.importPlaylist("Source",tracks,UUID.randomUUID().toString(),youtubeId=youtubeId).getString("name"))
            lib.mutate("playlist_apagar",JSONArray().put("YouTube renamed"))
            assertEquals("Source",lib.importPlaylist("Source",tracks,"youtube_$youtubeId",youtubeId=youtubeId).getString("name"))
            val before=lib.library().toString()
            try {lib.importPlaylist("Broken",JSONArray().put(JSONObject().put("video_id","invalid").put("titulo","Bad")),UUID.randomUUID().toString());fail("Invalid item must fail")}catch(_:IllegalArgumentException){}
            assertEquals(before,lib.library().toString())
        } finally {lib.close();root.deleteRecursively()}
    }
}
