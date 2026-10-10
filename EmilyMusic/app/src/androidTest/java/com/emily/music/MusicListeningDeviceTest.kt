package com.emily.music
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.json.*
import java.io.File
import java.util.UUID
class MusicListeningDeviceTest {
 @Test fun listeningIsPersistedBoundedAndIndependentFromPlaylistsAndPlayer()=runBlocking {
  val base=InstrumentationRegistry.getInstrumentation().targetContext
  val uid=MusicCloud.currentUser()?.uid;org.junit.Assume.assumeNotNull(uid)
  val root=File(base.cacheDir,"listening-test-${UUID.randomUUID()}").apply{mkdirs()}
  val ctx=object:android.content.ContextWrapper(base){override fun getApplicationContext():android.content.Context=this;override fun getFilesDir()=File(root,"files").apply{mkdirs()};override fun getExternalFilesDir(type:String?)=File(root,"external").apply{mkdirs()}}
  var lib=withContext(Dispatchers.IO){MusicLibrarySession(ctx,uid!!,false)}
  try {
   val before=lib.library().getJSONObject("playlists").toString();val player=lib.playerState().toString()
   val row=JSONObject().put("video_id","aaaaaaaaaaa").put("titulo","Song").put("artist","Artist")
   withContext(Dispatchers.IO){lib.recordListening(row,1000);lib.recordListening(row,2000)}
   assertEquals(2,lib.library().getJSONArray("listening").getJSONObject(0).getInt("count"))
   assertEquals(before,lib.library().getJSONObject("playlists").toString());assertEquals(player,lib.playerState().toString())
   lib.close();lib=withContext(Dispatchers.IO){MusicLibrarySession(ctx,uid!!,false)}
   assertEquals(2,lib.library().getJSONArray("listening").getJSONObject(0).getInt("count"))
   lib.close()
   val disk=File(ctx.filesDir,"accounts/${MusicAccountPaths.key(uid!!)}/library.json")
   val persisted=JSONObject(disk.readText())
   persisted.getJSONObject("campos").put("[\"listening\",\"other-device\"]",JSONObject().put("quando",3000).put("id","remote-test").put("valor",JSONArray().put(JSONObject(row.toString()).put("count",3).put("last",3000).put("thumb",""))))
   disk.writeText(persisted.toString());lib=withContext(Dispatchers.IO){MusicLibrarySession(ctx,uid,false)}
   assertEquals(5,lib.library().getJSONArray("listening").getJSONObject(0).getInt("count"))
   withContext(Dispatchers.IO){for(i in 0..200)lib.recordListening(JSONObject().put("video_id",i.toString().padStart(11,'0')).put("titulo","Song $i"),3000L+i)}
   assertEquals(200,lib.library().getJSONArray("listening").length())
   val history=lib.library().getJSONArray("listening").getJSONObject(0)
   assertEquals(true,lib.mutate("music_copiar",JSONArray().put("default").put(history)))
   val stored=lib.library().getJSONObject("playlists").getJSONObject("default").getJSONArray("musicas").getJSONObject(0)
   assertFalse(stored.has("count"));assertFalse(stored.has("last"))
   assertEquals(player,lib.playerState().toString())
  } finally {lib.close();root.deleteRecursively()}
 }
}
