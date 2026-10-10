package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.media3.session.*
import androidx.media3.common.*
import android.os.Bundle
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.util.concurrent.TimeUnit

class MusicNotificationCloseDeviceTest {
 @Test fun notificationHasRepeatAndCloseAndCloseClearsPlayback() {
  val instrumentation=InstrumentationRegistry.getInstrumentation();val context=instrumentation.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(context));EmilyMusicLibrary.init(context)
  val main: (() -> Unit)->Unit={instrumentation.runOnMainSync(it)}
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaController>
  main {future=MediaController.Builder(context,SessionToken(context,android.content.ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val controller=future.get(15,TimeUnit.SECONDS);Thread.sleep(1000)
  var active=false;main{active=controller.playWhenReady};org.junit.Assume.assumeFalse("Não interromper música do usuário",active)
  val activity=androidx.test.core.app.ActivityScenario.launch(MainActivity::class.java)
  val saved=EmilyMusicLibrary.playerState();val id="local_"+java.security.MessageDigest.getInstance("SHA-256").digest("notification-${System.nanoTime()}".toByteArray()).joinToString(""){"%02x".format(it)}
  val file=File(EmilyMusicLibrary.folder,"$id.mp3")
  try {
   val size=8000*2*30;val bytes=java.nio.ByteBuffer.allocate(44+size).order(java.nio.ByteOrder.LITTLE_ENDIAN)
   bytes.put("RIFF".toByteArray()).putInt(36+size).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(8000).putInt(16000).putShort(2).putShort(16).put("data".toByteArray()).putInt(size);file.writeBytes(bytes.array())
   main {val buttons=controller.mediaButtonPreferences;assertEquals(listOf("emily.music.repeat",EmilyMusicService.ACTION_CLOSE),buttons.map{it.sessionCommand?.customAction});assertTrue(controller.availableSessionCommands.contains(SessionCommand(EmilyMusicService.ACTION_CLOSE,Bundle.EMPTY)));controller.volume=0f;controller.setMediaItems(listOf(MediaItem.Builder().setMediaId(id).setUri("emilymusic://$id").setMediaMetadata(MediaMetadata.Builder().setTitle("Teste silencioso").build()).build(),MediaItem.Builder().setMediaId(id).setUri("emilymusic://$id").build()));controller.prepare();controller.play()}
   var playing=false;for(i in 0..40){main{playing=controller.isPlaying};if(playing)break;Thread.sleep(150)};assertTrue(playing)
   Thread.sleep(1000)
   val actions=context.getSystemService(android.app.NotificationManager::class.java).activeNotifications.first{it.notification.category==android.app.Notification.CATEGORY_TRANSPORT}.notification.actions.map{it.title.toString()}
   assertTrue("X deve aparecer na notificação: $actions",actions.contains("Fechar player"))
   assertTrue("Repetição deve aparecer na notificação: $actions",actions.any{it.startsWith("Repetição:")})
   assertFalse(actions.any{it.contains("aleatório")})
   lateinit var command:com.google.common.util.concurrent.ListenableFuture<SessionResult>
   main {command=controller.sendCustomCommand(SessionCommand("emily.music.repeat",Bundle.EMPTY),Bundle.EMPTY)};assertEquals(SessionResult.RESULT_SUCCESS,command.get(5,TimeUnit.SECONDS).resultCode)
   main {command=controller.sendCustomCommand(SessionCommand(EmilyMusicService.ACTION_CLOSE,Bundle.EMPTY),Bundle.EMPTY)};assertEquals(SessionResult.RESULT_SUCCESS,command.get(5,TimeUnit.SECONDS).resultCode)
   var empty=false;for(i in 0..40){Thread.sleep(100);empty=EmilyMusicLibrary.playerState().optJSONArray("queue")?.length()==0;if(empty)break};assertTrue("Fila não deve ressuscitar depois de fechar",empty)
   var stopped=false;main{stopped=!controller.isConnected||(!controller.playWhenReady&&controller.mediaItemCount==0)};assertTrue("X deve parar e limpar áudio",stopped)
   Thread.sleep(500)
   assertEquals("X deve fechar a tela do app",androidx.lifecycle.Lifecycle.State.DESTROYED,activity.state)
   val notification=context.getSystemService(android.app.NotificationManager::class.java).activeNotifications
   assertFalse("Notificação não deve ficar presa",notification.any{it.notification.category==android.app.Notification.CATEGORY_TRANSPORT})
  } finally {
   activity.close();main{MediaController.releaseFuture(future)};Thread.sleep(300);EmilyMusicLibrary.savePlayer(saved);file.delete()
  }
 }
}
