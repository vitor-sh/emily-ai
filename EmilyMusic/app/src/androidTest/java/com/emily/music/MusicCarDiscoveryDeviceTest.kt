package com.emily.music

import androidx.media.utils.MediaConstants
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Test
import org.junit.Assume
import org.junit.Assert.*

class MusicCarDiscoveryDeviceTest {
 @Test fun legacySearchAndMenusUseTheActualAndroidAutoTransport() {
  val i=InstrumentationRegistry.getInstrumentation();val ctx=i.targetContext
  Assume.assumeTrue(MusicCloud.locallyApproved(ctx))
  val connected=java.util.concurrent.CountDownLatch(1);var failure=false
  lateinit var browser:android.support.v4.media.MediaBrowserCompat
  i.runOnMainSync{browser=android.support.v4.media.MediaBrowserCompat(ctx,android.content.ComponentName(ctx,EmilyMusicService::class.java),object:android.support.v4.media.MediaBrowserCompat.ConnectionCallback(){
   override fun onConnected(){connected.countDown()};override fun onConnectionFailed(){failure=true;connected.countDown()}
  },android.os.Bundle().apply{putInt(MediaConstants.BROWSER_ROOT_HINTS_KEY_CUSTOM_BROWSER_ACTION_LIMIT,3)});browser.connect()}
  try {
   assertTrue(connected.await(15,java.util.concurrent.TimeUnit.SECONDS));assertFalse(failure)
   val done=java.util.concurrent.CountDownLatch(1);var results=emptyList<android.support.v4.media.MediaBrowserCompat.MediaItem>()
   i.runOnMainSync{browser.search("Linkin Park In The End",null,object:android.support.v4.media.MediaBrowserCompat.SearchCallback(){
    override fun onSearchResult(q:String,extras:android.os.Bundle?,items:MutableList<android.support.v4.media.MediaBrowserCompat.MediaItem>){results=items;done.countDown()}
    override fun onError(q:String,extras:android.os.Bundle?){failure=true;done.countDown()}
   })}
   assertTrue(done.await(50,java.util.concurrent.TimeUnit.SECONDS));assertFalse(failure)
   val track=results.firstOrNull{it.isPlayable&&it.mediaId!!.startsWith("car:discover:")}
   assertNotNull("Online music through the legacy search protocol",track)
   assertTrue(track!!.description.extras!!.getStringArrayList(MediaConstants.DESCRIPTION_EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ID_LIST)!!.contains(MusicCarDiscovery.OPTIONS))
   assertTrue(results.any{it.description.title=="Filtros"&&it.isBrowsable})
   val actionDone=java.util.concurrent.CountDownLatch(1);var target:String?=null
   i.runOnMainSync{browser.sendCustomAction(MusicCarDiscovery.OPTIONS,android.os.Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_MEDIA_ITEM_ID,track.mediaId)},object:android.support.v4.media.MediaBrowserCompat.CustomActionCallback(){
    override fun onResult(action:String?,extras:android.os.Bundle?,data:android.os.Bundle?){target=data?.getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE);actionDone.countDown()}
    override fun onError(action:String?,extras:android.os.Bundle?,data:android.os.Bundle?){failure=true;actionDone.countDown()}
   })}
   assertTrue(actionDone.await(15,java.util.concurrent.TimeUnit.SECONDS));assertFalse(failure);assertNotNull(target)
   val loaded=java.util.concurrent.CountDownLatch(1);var options=emptyList<android.support.v4.media.MediaBrowserCompat.MediaItem>()
   i.runOnMainSync{browser.subscribe(target!!,object:android.support.v4.media.MediaBrowserCompat.SubscriptionCallback(){
    override fun onChildrenLoaded(id:String,items:MutableList<android.support.v4.media.MediaBrowserCompat.MediaItem>){options=items;loaded.countDown()}
    override fun onError(id:String){failure=true;loaded.countDown()}
   })}
   assertTrue(loaded.await(15,java.util.concurrent.TimeUnit.SECONDS));assertFalse(failure);assertEquals(4,options.size)
   assertTrue(options.all{it.description.extras!!.getStringArrayList(MediaConstants.DESCRIPTION_EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ID_LIST)!!.isNotEmpty()})
   i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nCAR_SEARCH online tracks filters limited_host_menus=ok\n")})
  }finally{i.runOnMainSync{browser.disconnect()}}
 }

 private val ctx get()=InstrumentationRegistry.getInstrumentation().targetContext
 private fun track(id:String,title:String,duration:Long,views:Long)=JSONObject().put("type","track").put("video_id",id).put("titulo",title).put("artist","Teste").put("duration",duration).put("views",views)
 private fun fixture()=JSONArray().put(track("carTest0001","Curta",120,20)).put(track("carTest0002","Longa",1500,90)).put(JSONObject().put("type","playlist").put("playlist_id","PLcarTest000001").put("titulo","Playlist teste"))
 @Test fun discoveryFiltersPlaylistQueueAndOfflineFallback()=runBlocking {
  val uid="car-discovery-test-"+System.nanoTime();val lib=MusicLibrarySession(ctx,uid,false)
  try {
   lib.mutate("playlist_criar",JSONArray().put("Café teste"))
   var calls=0;var previews=0
   val car=MusicCarDiscovery(lib,{_,_->calls++;JSONObject().put("resultados",fixture())},{_->previews++;JSONObject().put("youtube_id","PLcarTest000001").put("name","Playlist teste").put("tracks",JSONArray().put(track("carTest0001","Curta",120,20)).put(track("carTest0002","Longa",1500,90)))},{true})
   val search=car.search("cafe")
   assertTrue(search.any{it.mediaMetadata.title=="Café teste"});assertEquals(1,calls)
   assertEquals(search.filter{it.mediaMetadata.isPlayable==true}.map{it.mediaId},car.search("CAFÉ").filter{it.mediaMetadata.isPlayable==true}.map{it.mediaId});assertEquals(1,calls)
   val filters=car.children(search.first().mediaId)!!;assertEquals(7,filters.size)
   fun filter(title:String)=filters.first{it.mediaMetadata.title==title}.mediaId
   val short=car.children(filter("Até 4 min"))!!.filter{it.mediaMetadata.isPlayable==true};assertEquals(listOf("Curta"),short.map{it.mediaMetadata.title.toString()})
   val long=car.children(filter("20 min ou mais"))!!.filter{it.mediaMetadata.isPlayable==true};assertEquals(listOf("Longa"),long.map{it.mediaMetadata.title.toString()})
   val views=car.children(filter("Mais vistas"))!!.filter{it.mediaMetadata.isPlayable==true};assertEquals(listOf("Longa","Curta"),views.map{it.mediaMetadata.title.toString()})
   val local=car.children(filter("Na biblioteca"))!!;assertTrue(local.any{it.mediaMetadata.title=="Café teste"});assertFalse(local.any{it.mediaMetadata.isPlayable==true})
   val playlist=search.first{it.mediaMetadata.title=="Playlist teste"};val tracks=car.children(playlist.mediaId)!!
   assertEquals(2,tracks.size);assertEquals(1,previews);assertEquals(tracks.map{it.mediaId},car.children(playlist.mediaId)!!.map{it.mediaId});assertEquals(1,previews)
   val chosen=car.selection(tracks[1].mediaId)!!;assertEquals(1,chosen.index);assertEquals(listOf("carTest0001","carTest0002"),chosen.items.map{it.mediaId});assertEquals("Playlist teste",JSONObject(chosen.items[1].mediaMetadata.extras!!.getString("track")!!).getString("source_title"))
   assertEquals(playlist.mediaId,car.parent(tracks[0].mediaId));assertNull(car.selection("car:discover:invented"))
   val offline=MusicCarDiscovery(lib,{_,_->fail("Offline cannot query the provider");JSONObject()},{JSONObject()},{false}).search("cafe")
   assertTrue(offline.any{it.mediaMetadata.title=="Café teste"});assertTrue(offline.any{it.mediaMetadata.title.toString().startsWith("Sem internet")})
  }finally{lib.close();java.io.File(ctx.filesDir,"accounts/${MusicAccountPaths.key(uid)}").deleteRecursively();java.io.File(ctx.getExternalFilesDir(android.os.Environment.DIRECTORY_MUSIC),"Emily Music/${MusicAccountPaths.key(uid)}").deleteRecursively()}
 }
 @Test fun saveImportAndChooseDestinationAreIdempotentAndAccountScoped()=runBlocking {
  Assume.assumeTrue(MusicCloud.locallyApproved(ctx));EmilyMusicLibrary.init(ctx)
  val lib=EmilyMusicLibrary.session();val name="Teste carro "+System.nanoTime();val destinations=listOf("$name A","$name B")
  val pid="PLcar"+System.nanoTime();var imported:String?=null
  try {
   destinations.forEach{lib.mutate("playlist_criar",JSONArray().put(it))}
   val car=MusicCarDiscovery(lib,{_,_->JSONObject().put("resultados",fixture().apply{getJSONObject(2).put("playlist_id",pid)})},{_->JSONObject().put("youtube_id",pid).put("name",name).put("tracks",JSONArray().put(track("carTest0001","Curta",120,20)))},{true})
   val search=car.search(name);val track=search.first{it.mediaMetadata.isPlayable==true}
   val menu=car.action(MusicCarDiscovery.OPTIONS,track.mediaId).getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE)!!
   val choices=car.children(menu)!!;assertEquals(4,choices.size)
   assertEquals(true,car.getItem(car.parent(menu)!!)!!.mediaMetadata.isBrowsable)
   val addChoice=choices.first{it.mediaMetadata.title=="Adicionar à playlist"}
   val pick=car.action(MusicCarDiscovery.ADD,addChoice.mediaId).getString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE)!!
   val options=car.children(pick)!!
   assertEquals(true,car.getItem(car.parent(pick)!!)!!.mediaMetadata.isBrowsable)
   val a=options.first{it.mediaMetadata.title==destinations[0]};val b=options.first{it.mediaMetadata.title==destinations[1]}
   car.action(MusicCarDiscovery.ADD_HERE,a.mediaId);car.action(MusicCarDiscovery.ADD_HERE,a.mediaId)
   val lists=lib.library().getJSONObject("playlists");assertEquals(1,lists.getJSONObject(destinations[0]).getJSONArray("musicas").length());assertEquals(0,lists.getJSONObject(destinations[1]).getJSONArray("musicas").length())
   car.action(MusicCarDiscovery.ADD_HERE,b.mediaId);assertEquals(1,lib.library().getJSONObject("playlists").getJSONObject(destinations[1]).getJSONArray("musicas").length())
   val playlist=search.first{it.mediaMetadata.title=="Playlist teste"}
   car.action(MusicCarDiscovery.SAVE,playlist.mediaId);imported=lib.library().getJSONObject("playlists").keys().asSequence().first{lib.library().getJSONObject("playlists").getJSONObject(it).optString("youtube_id")==pid}
   val count=lib.library().getJSONObject("playlists").length();car.action(MusicCarDiscovery.SAVE,playlist.mediaId);assertEquals(count,lib.library().getJSONObject("playlists").length())
   try{car.action(MusicCarDiscovery.ADD_HERE,"car:discover:invented");fail("Reject unknown IDs")}catch(_:IllegalArgumentException){}
  }finally{(destinations+listOfNotNull(imported)).forEach{lib.mutate("playlist_apagar",JSONArray().put(it))}}
 }
}
