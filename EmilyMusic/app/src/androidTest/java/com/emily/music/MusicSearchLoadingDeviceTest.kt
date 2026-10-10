package com.emily.music

import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.*
import org.junit.Assert.*
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class MusicSearchLoadingDeviceTest {
 @get:Rule val compose=createAndroidComposeRule<MainActivity>()
 @Test fun mainAndPlaylistSearchShowAccessibleSpinnerAndDismissNormally() {
  compose.activity.runOnUiThread {
   compose.activity.setShowWhenLocked(true);compose.activity.setTurnScreenOn(true)
   compose.activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
  }
  fun find(v:View):WebView?=when(v){is WebView->v;is ViewGroup->(0 until v.childCount).firstNotNullOfOrNull{find(v.getChildAt(it))};else->null}
  fun js(code:String):String{val done=CountDownLatch(1);var result="null";compose.activity.runOnUiThread{find(compose.activity.window.decorView)?.evaluateJavascript(code){result=it;done.countDown()}?:done.countDown()};assertTrue(done.await(5,TimeUnit.SECONDS));return result}
  for(n in 0..200){compose.waitForIdle();if(js("!!window.EmilyMusic&&!!window.PlaylistSearch")=="true")break;Thread.sleep(100)}
  assertEquals("true",js("!!window.EmilyMusic"))
  try {
   assertEquals("true",js("""(()=>{EmilyMusic.go('busca');EmilyMusic.searchQuery='teste';EmilyMusic.searchLoading=true;document.querySelector('#pl-query').value='teste';EmilyMusic.renderSearch();const box=document.querySelector('#pl-preview');return !!box.querySelector('.music-search-spinner')&&box.querySelector('[role=status]').getAttribute('aria-label')==='Buscando músicas'&&!box.textContent.includes('YouTube');})()"""))
   assertEquals("true",js("""(()=>{window.testHistoryKey='emily-music-searches:'+new URLSearchParams(location.search).get('account');window.testHistoryValue=localStorage.getItem(window.testHistoryKey);window.originalMusicOnline=EmilyMusic.online;EmilyMusic.online=()=>true;window.originalMusicImportCall=musicImportCall;window.musicImportCall=()=>new Promise(()=>{});PlaylistSearch.open('default');const input=document.querySelector('#playlist-search input');input.value='teste';document.querySelector('#playlist-search form').requestSubmit();return !!document.querySelector('#playlist-search .music-search-spinner')&&!document.querySelector('.playlist-search-results').textContent.includes('YouTube');})()"""))
   assertEquals("true",js("PlaylistSearch.back()&&!document.querySelector('#playlist-search').open"))
  } finally {js("if(window.originalMusicImportCall)window.musicImportCall=window.originalMusicImportCall;if(window.originalMusicOnline)EmilyMusic.online=window.originalMusicOnline;if(window.testHistoryKey){if(window.testHistoryValue===null)localStorage.removeItem(window.testHistoryKey);else localStorage.setItem(window.testHistoryKey,window.testHistoryValue);}EmilyMusic.searchLoading=false;EmilyMusic.go('inicio');true")}
 }
}
