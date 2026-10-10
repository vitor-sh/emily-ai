package com.emily.music
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
class MusicYouTubeSearchDeviceTest {
 @Test fun mixedAndPlaylistOnlySearchAndRealPreview()=runBlocking(Dispatchers.IO){
  val i=InstrumentationRegistry.getInstrumentation();assertTrue(MusicCloud.locallyApproved(i.targetContext));EmilyMusicLibrary.init(i.targetContext)
  val start=android.os.SystemClock.elapsedRealtime()
  val mixed=EmilyMusicSearch.search("Celeste soundtrack","all").getJSONArray("resultados")
  assertTrue((0 until mixed.length()).any{mixed.getJSONObject(it).optString("type")=="playlist"})
  assertTrue((0 until mixed.length()).any{mixed.getJSONObject(it).has("video_id")})
  val playlists=EmilyMusicSearch.search("Celeste soundtrack","playlists").getJSONArray("resultados")
  assertTrue(playlists.length()>0);assertTrue((0 until playlists.length()).all{playlists.getJSONObject(it).getString("type")=="playlist"})
  val preview=MusicPlaylistImport.preview("youtube","https://music.youtube.com/playlist?list=PLe1jcCJWvkWiWLp9h3ge0e5v7n6kxEfOG")
  assertTrue(preview.getJSONArray("tracks").length()>0);assertTrue(MusicPlaylistImport.validCover(preview.getString("cover")))
  i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nYOUTUBE_DISCOVERY mixed=${mixed.length()} playlists=${playlists.length()} preview_tracks=${preview.getJSONArray("tracks").length()} elapsed_ms=${android.os.SystemClock.elapsedRealtime()-start}\n")})
 }
}
