package com.emily.music
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
@RunWith(AndroidJUnit4::class)
class MusicLibraryIsolationDeviceTest {
    @Test fun pinnedPlaylistsSurviveReloadRenameAndResetAfterRecreation() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val uid="pin-test-${System.nanoTime()}";var session=MusicLibrarySession(context,uid)
        try {
            session.mutate("playlist_criar",JSONArray().put("Pinned"))
            assertEquals(true,session.mutate("playlist_fixar",JSONArray().put("Pinned").put(true)))
            assertEquals(false,session.mutate("playlist_fixar",JSONArray().put("__locais__").put(true)))
            session.close();session=MusicLibrarySession(context,uid)
            assertTrue(session.library().getJSONObject("playlists").getJSONObject("Pinned").getBoolean("pinned"))
            session.mutate("playlist_renomear",JSONArray().put("Pinned").put("Renamed"))
            assertTrue(session.library().getJSONObject("playlists").getJSONObject("Renamed").getBoolean("pinned"))
            session.mutate("playlist_apagar",JSONArray().put("Renamed"))
            session.mutate("playlist_criar",JSONArray().put("Renamed"))
            assertFalse(session.library().getJSONObject("playlists").getJSONObject("Renamed").getBoolean("pinned"))
        } finally {
            session.close()
            File(context.filesDir,"accounts/${MusicAccountPaths.key(uid)}").deleteRecursively()
            File(context.getExternalFilesDir(android.os.Environment.DIRECTORY_MUSIC),"Emily Music/${MusicAccountPaths.key(uid)}").deleteRecursively()
        }
    }
    @Test fun accountsKeepPlaylistsDownloadsAndPlayerSeparateAfterReload() {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val one="test-a-${System.nanoTime()}";val two="test-b-${System.nanoTime()}"
        val sessions=mutableListOf<MusicLibrarySession>()
        try {
            val a=MusicLibrarySession(context,one).also {sessions.add(it)}
            val b=MusicLibrarySession(context,two).also {sessions.add(it)}
            a.mutate("playlist_criar",JSONArray().put("Somente A"))
            a.savePlayer(JSONObject().put("posicao",42).put("volume",33))
            File(a.folder,"abcdefghijk.mp3").writeBytes(byteArrayOf(1,2,3))
            assertFalse(b.library().getJSONObject("playlists").has("Somente A"))
            assertNull(b.localUri("abcdefghijk"))
            assertFalse(b.playerState().has("posicao"))
            assertNotEquals(a.covers,b.covers)
            a.close()
            assertThrows(IllegalStateException::class.java){a.mutate("playlist_criar",JSONArray().put("Atrasada"))}
            val restored=MusicLibrarySession(context,one).also {sessions.add(it)}
            assertTrue(restored.library().getJSONObject("playlists").has("Somente A"))
            assertEquals(42,restored.playerState().getInt("posicao"))
            assertNotNull(restored.localUri("abcdefghijk"))
            assertFalse(restored.library().getJSONObject("playlists").has("Atrasada"))
        } finally {
            sessions.forEach {it.close()}
            for(uid in listOf(one,two)) {
                File(context.filesDir,"accounts/${MusicAccountPaths.key(uid)}").deleteRecursively()
                File(context.getExternalFilesDir(android.os.Environment.DIRECTORY_MUSIC),"Emily Music/${MusicAccountPaths.key(uid)}").deleteRecursively()
            }
        }
    }
}
