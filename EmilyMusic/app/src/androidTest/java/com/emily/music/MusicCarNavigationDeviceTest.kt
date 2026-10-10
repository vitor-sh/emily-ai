package com.emily.music

import android.content.ComponentName
import android.content.Intent
import androidx.car.app.ScreenManager
import androidx.car.app.model.*
import androidx.car.app.media.model.MediaPlaybackTemplate
import androidx.car.app.testing.*
import androidx.lifecycle.Lifecycle
import kotlinx.coroutines.cancel
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.TimeUnit

/** Build the actual templates and exercise the stack with the library's official fake host. */
class MusicCarNavigationDeviceTest {
 @Test fun everyCarScreenHasReturnAndHomeAndSearchDoesNotTrapNavigation() {
  val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
  Assume.assumeTrue(MusicCloud.locallyApproved(context))
  lateinit var browserFuture:com.google.common.util.concurrent.ListenableFuture<MediaBrowser>
  i.runOnMainSync{browserFuture=MediaBrowser.Builder(context,SessionToken(context,ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val browser=browserFuture.get(15,TimeUnit.SECONDS)
  lateinit var session:MusicCarSession;lateinit var controller:SessionController
  try {
   i.runOnMainSync {
    val car=TestCarContext.createCarContext(context)
    session=MusicCarSession();controller=SessionController(session,car,Intent())
    // The token registration belongs to the real host; this test owns only templates/stack.
    session.browser=browser;session.ready=true
    car.lifecycleOwner.registry.currentState=Lifecycle.State.CREATED
    val manager=car.getCarService(ScreenManager::class.java)
    val root=MusicCarScreen(car,session,"home","Emily Music");root.setMarker("home");manager.push(root)
    val home=root.onGetTemplate() as ListTemplate
    assertEquals(6,home.singleList!!.items.size);assertEquals(Action.APP_ICON,home.header!!.startHeaderAction)
    session.open("search","Buscar")
    val search=manager.top.onGetTemplate() as SearchTemplate
    assertEquals(Action.BACK,search.headerAction);assertEquals("Início",search.actionStrip!!.actions.first().title.toString());assertNotNull(search.actionStrip!!.actions[1].icon)
    session.home();assertSame(root,manager.top)
    session.open("queue","Fila")
    val queue=manager.top.onGetTemplate() as ListTemplate
    assertEquals(Action.BACK,queue.header!!.startHeaderAction);assertEquals("Início",queue.header!!.endHeaderActions.first().title.toString())
    session.showPlayer();val player=manager.top.onGetTemplate()
    val header=when(player){is MediaPlaybackTemplate->player.header;is MessageTemplate->player.header;else->error("Wrong player template")}
    assertEquals(Action.BACK,header!!.startHeaderAction);assertEquals(listOf("Início","Fila"),header.endHeaderActions.map{it.title.toString()})
    session.open("queue","Fila");session.showPlayer();assertEquals("player",manager.top.marker);assertTrue(manager.stackSize<=5)
    session.home();assertSame(root,manager.top)
    // Disconnection still provides a usable header and a retry action.
    session.ready=false;session.notice="O player desconectou";val disconnected=root.onGetTemplate() as MessageTemplate
    assertEquals(1,disconnected.actions.size);assertNotNull(disconnected.header)
   }
  } finally {i.runOnMainSync{session.scope.cancel();session.carContext.let{(it as TestCarContext).lifecycleOwner.registry.currentState=Lifecycle.State.DESTROYED};MediaBrowser.releaseFuture(browserFuture)}}
 }
}
