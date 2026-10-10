package com.emily.music

import android.view.*
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertIsDisplayed
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.*

class MusicOverlayDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun missingQueueAndHiddenOverlayRecoverFromCurrentTrack() {
  val i=InstrumentationRegistry.getInstrumentation()
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(i.targetContext))
  compose.activity.runOnUiThread{compose.activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String{val latch=CountDownLatch(1);var result="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){result=it;latch.countDown()}?:latch.countDown()};assertTrue(latch.await(5,TimeUnit.SECONDS));return result}
  for(n in 0..100){compose.waitForIdle();if(js("!!window.musicState&&!!window.MusicMobile")=="true")break;Thread.sleep(200)}
  assertEquals("true",js("!!window.musicState&&!!window.MusicMobile"))
  try {
   assertEquals("true",js("""(()=>{window.overlaySaved={...nativeState};window.overlayModalHidden=document.querySelector('#modal-player').hidden;document.querySelector('#modal-player').hidden=false;nativeState={queue:[],video_id:'',playing:false};Player._faixaAtual=null;
     musicState({video_id:'aaaaaaaaaaa',indice:0,playing:true,posicao:1,duracao:100,track:{video_id:'aaaaaaaaaaa',titulo:'Test song',origem:'Test playlist'},output:'Bluetooth test',external_output:true});
     return !document.querySelector('#mobile-mini').hidden&&Player._faixaAtual.titulo==='Test song'&&document.querySelector('.music-output-button span').textContent==='Bluetooth test';})()"""))
   assertEquals("true",js("""(()=>{const render=EmilyMusic.render;let paints=0;EmilyMusic.render=function(){paints++;render.call(this);};document.querySelector('#mobile-mini').hidden=true;musicState({...nativeState,queue:[...nativeState.queue]});EmilyMusic.render=render;return !document.querySelector('#mobile-mini').hidden&&paints===0;})()"""))
   assertEquals("true",js("""(()=>{const mini=document.querySelector('#mobile-mini');const output=mini.querySelector('.music-output-button');musicState({...nativeState,video_id:'aaaaaaaaaaa',track:{video_id:'aaaaaaaaaaa',titulo:'Test song'},external_output:true});const expanded=mini.getBoundingClientRect().height;musicState({...nativeState,external_output:false});const compact=mini.getBoundingClientRect().height;const hidden=output.hidden&&!mini.hidden&&compact<expanded;musicState({...nativeState,external_output:true});if(!(hidden&&!output.hidden&&mini.getBoundingClientRect().height===expanded))return JSON.stringify({expanded,compact,hidden,outputHidden:output.hidden,miniHidden:mini.hidden,display:getComputedStyle(mini).display,parentDisplay:getComputedStyle(mini.parentElement).display});return true;})()"""))
   js("document.querySelector('.music-output-button').click();true")
   compose.waitForIdle();compose.onNodeWithText("Onde você quer ouvir?").assertIsDisplayed()
   i.uiAutomation.injectInputEvent(KeyEvent(KeyEvent.ACTION_DOWN,KeyEvent.KEYCODE_BACK),true);i.uiAutomation.injectInputEvent(KeyEvent(KeyEvent.ACTION_UP,KeyEvent.KEYCODE_BACK),true);compose.waitForIdle()
   assertEquals("true",js("""(()=>{musicState({video_id:'',indice:0,playing:false,queue:[],track:null});return document.querySelector('#mobile-mini').hidden&&!Player._faixaAtual;})()"""))
  } finally {js("musicState(window.overlaySaved);document.querySelector('#modal-player').hidden=window.overlayModalHidden;delete window.overlayModalHidden;delete window.overlaySaved;true")}
 }
 @Test fun connectedLocalOutputsCanBeReadAndSelectedWithoutClearingPlayback() {
  val i=InstrumentationRegistry.getInstrumentation()
  i.runOnMainSync {
   val routes=MusicAudioRoutes(compose.activity)
   val outputs=routes.outputs();assertTrue(outputs.isNotEmpty())
   val selected=outputs.firstOrNull {routes.selected(it)}
   assertNotNull(selected);try {outputs.forEach {routes.select(it);assertTrue(routes.selected(it))}} finally {routes.select(selected!!)}
   assertTrue(routes.currentName().isNotBlank())
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nAUDIO_ROUTES local_outputs=${outputs.size} selected_name_present=true\n")})
  }
 }
}
