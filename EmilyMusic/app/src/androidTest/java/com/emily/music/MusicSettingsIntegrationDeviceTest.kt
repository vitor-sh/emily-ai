package com.emily.music

import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class MusicSettingsIntegrationDeviceTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()
    @Test fun actualGearOpensAndBackClosesWithoutSigningOut() {
        org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(compose.activity))
        compose.activity.runOnUiThread {compose.activity.window.addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)}
        val owner=MusicCloud.currentUser()?.uid
        fun find(view:View):WebView?=when(view){is WebView->view;is ViewGroup->(0 until view.childCount).firstNotNullOfOrNull{find(view.getChildAt(it))};else->null}
        var clicked=false
        for(n in 0..40) {
            compose.waitForIdle()
            val latch=CountDownLatch(1)
            compose.activity.runOnUiThread {
                val web=find(compose.activity.window.decorView)
                if(web==null)latch.countDown() else web.evaluateJavascript("(()=>{const b=document.getElementById('mobile-settings');const modal=document.getElementById('modal-player');if(!b||!modal||modal.hidden)return false;b.click();return true;})()") {clicked=it=="true";latch.countDown()}
            }
            assertTrue(latch.await(3,TimeUnit.SECONDS))
            if(clicked)break
            Thread.sleep(250)
        }
        assertTrue("Engrenagem deve existir na interface real",clicked)
        compose.onNodeWithText("Configurações").assertIsDisplayed()
        compose.onNodeWithText("Sair da conta").assertIsDisplayed()
        compose.onNodeWithText("Importar playlists").assertIsDisplayed().performClick()
        var importOpen=false
        for(n in 0..15) {
            val latch=CountDownLatch(1)
            compose.activity.runOnUiThread {find(compose.activity.window.decorView)?.evaluateJavascript("document.getElementById('music-import')?.open===true") {importOpen=it=="true";latch.countDown()} ?: latch.countDown()}
            assertTrue(latch.await(3,TimeUnit.SECONDS));if(importOpen)break;Thread.sleep(200)
        }
        assertTrue("Configurações deve abrir o importador real",importOpen)
        val args=InstrumentationRegistry.getArguments()
        val spotify=args.getString("spotifyPlaylist")?:"https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF"
        val expected=args.getString("spotifyCount")?.toInt()?:50
        val submitted=CountDownLatch(1)
        compose.activity.runOnUiThread {find(compose.activity.window.decorView)?.evaluateJavascript("(()=>{const f=document.querySelector('#music-import form');f.querySelector('input').value=${org.json.JSONObject.quote(spotify)};f.querySelector('input').dispatchEvent(new Event('input'));f.requestSubmit();return true;})()") {submitted.countDown()} ?: submitted.countDown()}
        assertTrue(submitted.await(3,TimeUnit.SECONDS))
        var rows=0
        for(n in 0..80) {
            val latch=CountDownLatch(1)
            compose.activity.runOnUiThread {find(compose.activity.window.decorView)?.evaluateJavascript("document.querySelectorAll('#music-import .import-track').length") {rows=it.toIntOrNull()?:0;latch.countDown()} ?: latch.countDown()}
            assertTrue(latch.await(3,TimeUnit.SECONDS));if(rows==expected)break;Thread.sleep(250)
        }
        assertEquals("Prévia real deve chegar pela ponte nativa",expected,rows)
        compose.waitForIdle()
        Thread.sleep(700)
        val screenshot=InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
        if(screenshot!=null)java.io.File(compose.activity.cacheDir,"import-preview.png").outputStream().use {screenshot.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)}
        val checked=CountDownLatch(1);var fits=false
        compose.activity.runOnUiThread {
            find(compose.activity.window.decorView)?.evaluateJavascript("(()=>{const d=document.getElementById('music-import');const b=d.getBoundingClientRect();console.log('IMPORT_LAYOUT',JSON.stringify({rect:b.toJSON(),height:innerHeight,visual:visualViewport?.height,scroll:d.scrollHeight,css:getComputedStyle(d).height}));const ok=b.left>=0&&b.right<=innerWidth+1&&b.top>=0&&b.bottom<=innerHeight+1&&b.height>innerHeight*.5&&d.querySelectorAll('.import-sources button').length===2;window.MusicImport.back();return ok;})()") {fits=it=="true";checked.countDown()} ?: checked.countDown()
        }
        assertTrue(checked.await(3,TimeUnit.SECONDS));assertTrue("Importador deve caber na tela",fits)
        compose.activity.runOnUiThread {find(compose.activity.window.decorView)?.evaluateJavascript("document.getElementById('mobile-settings').click()",null)}
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand("input keyevent 4").close()
        compose.waitUntil(3000){compose.onAllNodesWithText("Configurações").fetchSemanticsNodes().isEmpty()}
        compose.onNodeWithText("Sair da conta").assertDoesNotExist()
        assertEquals(owner,MusicCloud.currentUser()?.uid)
    }
}
