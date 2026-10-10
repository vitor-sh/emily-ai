package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.json.JSONObject
import java.io.File

@RunWith(AndroidJUnit4::class)
class MusicPlayerStoreDeviceTest {
    @Test fun legacyCheckpointSurvivesLibraryMigrationAndProcessRecreation() {
        val root=File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir,"music-store-test-${System.nanoTime()}").apply {mkdirs()}
        try {
            val file=File(root,"player.json")
            val legacy=JSONObject().put("posicao",42).put("indice",2).put("loop",1)
            val store=MusicPlayerStore(file)
            assertEquals(42,store.load(legacy).getInt("posicao"))
            // The full library can now omit the player without losing the checkpoint.
            assertEquals(42,MusicPlayerStore(file).load(JSONObject()).getInt("posicao"))
            store.write(JSONObject().put("posicao",43).put("indice",2))
            assertEquals(43,MusicPlayerStore(file).load(JSONObject()).getInt("posicao"))
            assertTrue(file.length()<100)
        } finally {root.deleteRecursively()}
    }
    @Test fun actualMusicServiceKeepsPlayingWithScreenOff() {
        val instrumentation=InstrumentationRegistry.getInstrumentation()
        val context=instrumentation.targetContext
        org.junit.Assume.assumeTrue("Login real precisa estar aprovado",MusicCloud.locallyApproved(context))
        EmilyMusicLibrary.init(context)
        val onMain: (() -> Unit) -> Unit = { instrumentation.runOnMainSync(it) }
        lateinit var future: com.google.common.util.concurrent.ListenableFuture<androidx.media3.session.MediaController>
        onMain { future=androidx.media3.session.MediaController.Builder(context,androidx.media3.session.SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync() }
        val controller=future.get(15,java.util.concurrent.TimeUnit.SECONDS)
        Thread.sleep(1000)
        var active=false
        onMain {active=controller.playWhenReady}
        org.junit.Assume.assumeFalse("Não interromper música do usuário",active)
        val saved=EmilyMusicLibrary.playerState()
        var previous=emptyList<androidx.media3.common.MediaItem>()
        var index=0;var position=0L;var volume=1f
        onMain {previous=(0 until controller.mediaItemCount).map {controller.getMediaItemAt(it)};index=controller.currentMediaItemIndex.coerceAtLeast(0);position=controller.currentPosition;volume=controller.volume}
        val id="local_"+java.security.MessageDigest.getInstance("SHA-256").digest("test-${System.nanoTime()}".toByteArray()).joinToString(""){"%02x".format(it)}
        val file=File(EmilyMusicLibrary.folder,"$id.mp3")
        try {
            // A local PCM fixture avoids network, account access and audible playback.
            val size=8000*2*30
            val bytes=java.nio.ByteBuffer.allocate(44+size).order(java.nio.ByteOrder.LITTLE_ENDIAN)
            bytes.put("RIFF".toByteArray()).putInt(36+size).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(8000).putInt(16000).putShort(2).putShort(16).put("data".toByteArray()).putInt(size)
            file.writeBytes(bytes.array())
            onMain {controller.volume=0f;controller.setMediaItem(androidx.media3.common.MediaItem.Builder().setMediaId(id).setUri("emilymusic://$id").build());controller.prepare();controller.play()}
            var playing=false
            for(attempt in 0..40){onMain {playing=controller.isPlaying};if(playing)break;Thread.sleep(250)}
            assertTrue("Serviço deve iniciar áudio local",playing)
            var before=0L
            onMain {before=controller.currentPosition}
            instrumentation.uiAutomation.executeShellCommand("input keyevent 223").close()
            Thread.sleep(12000)
            var after=0L
            onMain {after=controller.currentPosition;playing=controller.isPlaying}
            assertTrue("Áudio deve continuar com tela apagada",playing)
            assertTrue("Reprodução deve avançar em segundo plano",after-before>=10000)
            // Exercise the same player shutdown used by account logout without changing Google credentials.
            onMain {EmilyMusicService.logoutPlayback()}
            var stopped=false
            for(attempt in 0..20) {
                onMain {stopped=!controller.playWhenReady && controller.mediaItemCount==0}
                if(stopped)break
                Thread.sleep(100)
            }
            assertTrue("Logout deve interromper áudio e remover a fila",stopped)
        } finally {
            instrumentation.uiAutomation.executeShellCommand("input keyevent 224").close()
            onMain {controller.pause();controller.stop();controller.clearMediaItems();if(previous.isNotEmpty())controller.setMediaItems(previous,index,position);controller.volume=volume}
            Thread.sleep(500)
            EmilyMusicLibrary.savePlayer(saved)
            onMain {androidx.media3.session.MediaController.releaseFuture(future)}
            file.delete()
        }
    }
}
