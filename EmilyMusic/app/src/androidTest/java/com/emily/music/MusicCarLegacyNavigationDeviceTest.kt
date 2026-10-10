package com.emily.music

import android.content.ComponentName
import android.graphics.BitmapFactory
import android.os.Bundle
import android.support.v4.media.MediaBrowserCompat
import androidx.media.utils.MediaConstants
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Assume
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Test the real legacy browser transport, not a FakeHost for the separate template UI. */
class MusicCarLegacyNavigationDeviceTest {
    @Test fun legacyBrowseActionsNavigateWithoutChangingPlayback() {
        val i=InstrumentationRegistry.getInstrumentation();val ctx=i.targetContext
        Assume.assumeTrue(MusicCloud.locallyApproved(ctx))
        val connected=CountDownLatch(1);var failure=false
        lateinit var browser:MediaBrowserCompat
        val hints=Bundle().apply{putInt(MediaConstants.BROWSER_ROOT_HINTS_KEY_CUSTOM_BROWSER_ACTION_LIMIT,3)}
        i.runOnMainSync{
            browser=MediaBrowserCompat(ctx,ComponentName(ctx,EmilyMusicService::class.java),object:MediaBrowserCompat.ConnectionCallback(){
                override fun onConnected(){connected.countDown()}
                override fun onConnectionFailed(){failure=true;connected.countDown()}
            },hints);browser.connect()
        }
        try {
            assertTrue(connected.await(15,TimeUnit.SECONDS));assertFalse(failure)
            lateinit var controller:android.support.v4.media.session.MediaControllerCompat
            var before:android.support.v4.media.session.PlaybackStateCompat?=null
            i.runOnMainSync{
                assertEquals(MusicCarCatalog.ROOT,browser.root)
                assertEquals(2,browser.extras!!.getInt("android.media.browse.CONTENT_STYLE_BROWSABLE_HINT"))
                assertTrue(browser.extras!!.getBoolean(MediaConstants.BROWSER_SERVICE_EXTRAS_KEY_SEARCH_SUPPORTED))
                val actions=browser.extras!!.getParcelableArrayList<Bundle>(MediaConstants.BROWSER_SERVICE_EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ROOT_LIST)!!
                assertEquals((MusicCarNavigation.commands+MusicCarDiscovery.commands).toSet(),actions.map{it.getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ID)}.toSet())
                assertTrue(actions.all{it.getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ICON_URI)!!.startsWith("android.resource://")})
                controller=android.support.v4.media.session.MediaControllerCompat(ctx,browser.sessionToken);before=controller.playbackState
            }
            fun request(action:String,id:String?):Bundle {
                val done=CountDownLatch(1);var result:Bundle?=null;var failed=false
                i.runOnMainSync{browser.sendCustomAction(action,Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_MEDIA_ITEM_ID,id)},object:MediaBrowserCompat.CustomActionCallback(){
                    override fun onResult(action:String?,extras:Bundle?,data:Bundle?){result=data;done.countDown()}
                    override fun onError(action:String?,extras:Bundle?,data:Bundle?){failed=true;done.countDown()}
                })}
                assertTrue(done.await(10,TimeUnit.SECONDS));assertFalse(failed);return result!!
            }
            assertEquals(MusicCarCatalog.ROOT,request(MusicCarNavigation.HOME,MusicCarCatalog.FAVORITES).getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE))
            assertEquals(MusicCarCatalog.PLAYLISTS,request(MusicCarNavigation.BACK,"car:playlist:Teste%20%2F%20caf%C3%A9").getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE))
            assertEquals("car:playlist:Teste / café",request(MusicCarNavigation.BACK,"car:track:car%3Aplaylist%3ATeste%20%2F%20caf%C3%A9:aaaaaaaaaaa").getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE))
            assertTrue(request(MusicCarNavigation.PLAYING,MusicCarCatalog.ROOT).containsKey(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_SHOW_PLAYING_ITEM))
            i.runOnMainSync{assertEquals(before?.state,controller.playbackState?.state);assertEquals(before?.activeQueueItemId,controller.playbackState?.activeQueueItemId)}
            val loaded=CountDownLatch(1);var folders=emptyList<MediaBrowserCompat.MediaItem>()
            i.runOnMainSync{browser.subscribe(browser.root,object:MediaBrowserCompat.SubscriptionCallback(){
                override fun onChildrenLoaded(parentId:String,children:MutableList<MediaBrowserCompat.MediaItem>){folders=children;loaded.countDown()}
                override fun onError(parentId:String){loaded.countDown()}
            })}
            assertTrue(loaded.await(10,TimeUnit.SECONDS));assertEquals(4,folders.size)
            assertTrue(folders.all{it.description.iconUri!!.scheme=="android.resource"})
            assertTrue(folders.all{ctx.resources.getDrawable(it.description.iconUri!!.lastPathSegment!!.toInt(),ctx.theme) is android.graphics.drawable.VectorDrawable})
            assertTrue(folders.all{it.description.subtitle.isNullOrEmpty()})
            assertTrue(folders.all{it.isBrowsable&&!it.isPlayable&&it.description.iconUri!=null})
            assertTrue(folders.all{it.description.extras!!.getStringArrayList(MediaConstants.DESCRIPTION_EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ID_LIST)!!.contains(MusicCarNavigation.HOME)})
        } finally {i.runOnMainSync{browser.disconnect()}}
    }
    @Test fun packagedIconsAreReadableAndCannotExposePrivateFiles() {
        val ctx=InstrumentationRegistry.getInstrumentation().targetContext
        for(name in listOf("home","back","play","playlists","favorites","downloads","locals","all")){
            val uri=android.net.Uri.parse("content://${ctx.packageName}.car-icons/$name")
            assertEquals("image/png",ctx.contentResolver.getType(uri))
            ctx.contentResolver.openInputStream(uri)!!.use{val image=BitmapFactory.decodeStream(it);assertNotNull(image);assertEquals(192,image.width);image.recycle()}
        }
        for(path in listOf("../accounts/library.json","home/extra","unknown")){
            try{ctx.contentResolver.openInputStream(android.net.Uri.parse("content://${ctx.packageName}.car-icons/$path"))?.close();fail("Private paths must be rejected")}
            catch(_:java.io.FileNotFoundException){}
        }
        try{ctx.contentResolver.openOutputStream(android.net.Uri.parse("content://${ctx.packageName}.car-icons/home"));fail("Read only")}
        catch(_:java.io.FileNotFoundException){}
    }
}
