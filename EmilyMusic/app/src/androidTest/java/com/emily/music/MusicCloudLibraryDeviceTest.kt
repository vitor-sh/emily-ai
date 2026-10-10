package com.emily.music
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
internal class MusicCloudLibraryDeviceTest {
    @Test fun currentAccountLibraryBacksUpWithoutChangingTracks()=runBlocking {
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context))
        withContext(Dispatchers.IO){EmilyMusicLibrary.init(context)}
        val library=EmilyMusicLibrary.session()
        val before=withContext(Dispatchers.IO){library.library().toString()}
        withTimeout(30000){while(true){library.sync();if(library.notice=="Biblioteca sincronizada com sua conta.")break;delay(1000)}}
        assertEquals(before,withContext(Dispatchers.IO){library.library().toString()})
        val reply=MusicCloud.syncLibrary(library.uid,org.json.JSONObject(),-1)
        assertTrue(reply.getLong("revision")>=1)
        assertTrue(reply.getJSONObject("fields").length()>0)
        try {MusicCloud.syncLibrary("different-owner",org.json.JSONObject(),-1);fail("Other account must be refused")}
        catch(_:IllegalStateException){}
    }
    @Test fun freshDeviceProfileRestoresCurrentAccountLibrary()=runBlocking {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(base))
        withContext(Dispatchers.IO){EmilyMusicLibrary.init(base)}
        val original=EmilyMusicLibrary.session().library()
        val location=java.io.File(base.cacheDir,"sync-restore-test/"+java.util.UUID.randomUUID()).apply{mkdirs()}
        val isolated=object:android.content.ContextWrapper(base) {
            override fun getFilesDir()=java.io.File(location,"files").apply{mkdirs()}
            override fun getApplicationContext():android.content.Context=this
            override fun getExternalFilesDir(type:String?)=java.io.File(location,"external").apply{mkdirs()}
        }
        val restored=withContext(Dispatchers.IO){MusicLibrarySession(isolated,MusicCloud.accountKey())}
        try {
            withTimeout(30000){while(true){restored.sync();if(restored.notice=="Biblioteca sincronizada com sua conta.")break;delay(1000)}}
            val data=restored.library()
            val before=original.getJSONObject("playlists");val after=data.getJSONObject("playlists")
            val names=before.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS}.toSet()
            assertEquals(names,after.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS}.toSet())
            for(name in names)assertEquals(before.getJSONObject(name).getJSONArray("musicas").length(),after.getJSONObject(name).getJSONArray("musicas").length())
            assertEquals(original.getJSONObject("favoritos").keys().asSequence().toSet(),data.getJSONObject("favoritos").keys().asSequence().toSet())
        }finally{restored.close();location.deleteRecursively()}
    }

}
