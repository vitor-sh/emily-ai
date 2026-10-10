package com.emily.music

import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.*
import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import org.json.JSONArray

@UnstableApi
@RunWith(AndroidJUnit4::class)
class MusicAudioUiDeviceTest {
    @Test fun playlistPreparationAndRealButtonReachPlayback()=runBlocking {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context))
        withContext(Dispatchers.IO){EmilyMusicLibrary.init(context)}
        val library=EmilyMusicLibrary.session();val saved=JSONObject(library.playerState().toString()).apply {put("volume",optDouble("volume",100.0));put("loop",optInt("loop",1));put("shuffle",optBoolean("shuffle"))}
        lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
        instrumentation.runOnMainSync {future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
        val controller=future.get(15,java.util.concurrent.TimeUnit.SECONDS)
        var active=false
        instrumentation.runOnMainSync{active=controller.playWhenReady}
        org.junit.Assume.assumeFalse("Não interromper música do usuário",active)
        val lists=library.library().getJSONObject("playlists")
        val pair=lists.keys().asSequence().filter{it!=EmilyMusicLibrary.LOCALS}.mapNotNull {name->
            val tracks=lists.getJSONObject(name).getJSONArray("musicas")
            val first=(0 until tracks.length()).asSequence().map{tracks.getJSONObject(it)}.firstOrNull{it.getString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}
            first?.let{name to it.getString("video_id")}
        }.first()
        val name=pair.first;val id=pair.second
        var scenario:ActivityScenario<MainActivity>?=null
        suspend fun js(script:String):String {
            val result=CompletableDeferred<String>()
            fun find(view:View):WebView?=when(view){is WebView->view;is ViewGroup->(0 until view.childCount).firstNotNullOfOrNull{find(view.getChildAt(it))};else->null}
            scenario!!.onActivity {activity->
                val web=find(activity.window.decorView)
                if(web==null)result.complete("null")else web.evaluateJavascript(script){result.complete(it)}
            }
            return withTimeout(5000){result.await()}
        }
        try {
            scenario=ActivityScenario.launch(MainActivity::class.java)
            var ready=false
            for(n in 0..60){if(js("typeof EmilyMusic!=='undefined' && typeof _playlistsGeral!=='undefined' && !!_playlistsGeral.playlists[${JSONObject.quote(name)}]")=="true"){ready=true;break};delay(250)}
            assertTrue("WebView deve carregar a biblioteca",ready)
            EmilyMusicAudio.clearCache()
            assertEquals("true",js("EmilyMusic.view=${JSONObject.quote(name)};EmilyMusic.go('playlist');true"))
            delay(6000)
            val preparedStart=android.os.SystemClock.elapsedRealtime()
            val stream=withContext(Dispatchers.IO){EmilyMusicAudio.resolve(id,foreground=false)}
            val cached=android.os.SystemClock.elapsedRealtime()-preparedStart
            assertTrue("Abrir playlist deve preparar a faixa, sem depender do clique ($cached ms)",cached<300)
            js("document.getElementById('player-vol').value=0;true")
            val start=android.os.SystemClock.elapsedRealtime()
            assertEquals("true",js("(()=>{const b=document.querySelector('#pl-lista [data-video-id=\"$id\"] .music-track-main');if(!b||b.disabled)return false;b.click();return true;})()"))
            var playing=false
            for(n in 0..200){instrumentation.runOnMainSync{playing=controller.isPlaying && controller.currentMediaItem?.mediaId==id};if(playing)break;delay(50)}
            val elapsed=android.os.SystemClock.elapsedRealtime()-start
            instrumentation.sendStatus(0,android.os.Bundle().apply{putString("stream","\nMUSIC_UI prepared_resolution_ms=$cached button_to_playing_ms=$elapsed source=${stream.source}\n")})
            assertTrue("Clique real da biblioteca deve iniciar reprodução",playing)
        } finally {
            scenario?.close()
            instrumentation.runOnMainSync {
                controller.pause();controller.stop();controller.clearMediaItems()
                val items=musicItems(saved.optJSONArray("queue")?:JSONArray(),library)
                if(items.isNotEmpty())controller.setMediaItems(items,saved.optInt("indice",0).coerceIn(0,items.size-1),(saved.optDouble("posicao",0.0)*1000).toLong())
                controller.repeatMode=when(saved.optInt("loop",1)){2->Player.REPEAT_MODE_ONE;1->Player.REPEAT_MODE_ALL;else->Player.REPEAT_MODE_OFF}
                controller.shuffleModeEnabled=saved.optBoolean("shuffle")
                controller.volume=saved.optDouble("volume",100.0).toFloat()/100
            }
            delay(500)
            withContext(Dispatchers.IO){library.savePlayer(saved.put("queue",saved.optJSONArray("queue")?:JSONArray()).put("posicao",saved.optDouble("posicao",0.0)))}
            instrumentation.runOnMainSync{MediaController.releaseFuture(future)}
            EmilyMusicAudio.clearCache()
        }
    }
}
