package com.emily.music

import android.content.ComponentName
import android.os.Bundle
import androidx.media3.common.*
import androidx.media3.session.*
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.*
import org.junit.Assert.*
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.*

/** Exercise both Media3 and the platform browser API used by Android Auto. */
class MusicCarDeviceTest {
 private val i=InstrumentationRegistry.getInstrumentation()
 private val context get()=i.targetContext
 private fun main(block:()->Unit)=i.runOnMainSync(block)
 @Test fun browseAndPlayPlaylistWithoutAnActivity() {
  Assume.assumeTrue(MusicCloud.locallyApproved(context))
  lateinit var future:com.google.common.util.concurrent.ListenableFuture<MediaBrowser>
  main{future=MediaBrowser.Builder(context,SessionToken(context,ComponentName(context,EmilyMusicService::class.java))).buildAsync()}
  val browser=future.get(15,TimeUnit.SECONDS)
  var original=emptyList<MediaItem>();var index=0;var position=0L;var volume=1f;var repeat=0;var shuffle=false
  var playing=false;main{playing=browser.playWhenReady};Assume.assumeFalse("Preservar áudio do usuário",playing)
  Thread.sleep(700)
  val library=EmilyMusicLibrary.session();val saved=library.playerState()
  main{original=(0 until browser.mediaItemCount).map{browser.getMediaItemAt(it)};index=browser.currentMediaItemIndex.coerceAtLeast(0);position=browser.currentPosition;volume=browser.volume;repeat=browser.repeatMode;shuffle=browser.shuffleModeEnabled}
  fun <T> request(block:()->com.google.common.util.concurrent.ListenableFuture<T>):T {lateinit var f:com.google.common.util.concurrent.ListenableFuture<T>;main{f=block()};return f.get(45,TimeUnit.SECONDS)}
  try {
   val root=request{browser.getLibraryRoot(null)};assertEquals(0,root.resultCode);assertEquals(MusicCarCatalog.ROOT,root.value!!.mediaId)
   val sections=request{browser.getChildren(root.value!!.mediaId,0,100,null)}.value!!
   assertEquals(4,sections.size);assertTrue(sections.all{it.mediaMetadata.isBrowsable==true&&it.mediaMetadata.isPlayable==false})
   val lists=request{browser.getChildren(MusicCarCatalog.PLAYLISTS,0,100,null)}.value!!;assertTrue(lists.isNotEmpty())
   val list=lists.firstOrNull{request{browser.getChildren(it.mediaId,0,200,null)}.value!!.size>=2}
   Assume.assumeNotNull(list)
   val songs=request{browser.getChildren(list!!.mediaId,0,200,null)}.value!!
   assertTrue(songs.all{it.mediaMetadata.isPlayable==true&&it.mediaMetadata.isBrowsable==false})
   val one=request{browser.getChildren(list!!.mediaId,1,1,null)}.value!!;assertEquals(songs[1].mediaId,one.single().mediaId)
   assertEquals(songs[0].mediaId,request{browser.getItem(songs[0].mediaId)}.value!!.mediaId)
   assertEquals(0,request{browser.search(songs[0].mediaMetadata.title.toString(),null)}.resultCode)
   assertTrue(request{browser.getSearchResult(songs[0].mediaMetadata.title.toString(),0,200,null)}.value!!.isNotEmpty())
   main{browser.volume=0f;browser.repeatMode=Player.REPEAT_MODE_OFF;browser.shuffleModeEnabled=false;browser.setMediaItem(MediaItem.Builder().setMediaId(songs[0].mediaId).build());browser.prepare();browser.play()}
   var started=false
   for(n in 0..300){main{started=browser.isPlaying};if(started)break;Thread.sleep(100)}
   main{assertTrue("Reprodução pelo ID de navegação do carro",started);assertEquals(songs.size,browser.mediaItemCount);assertEquals(songs[0].mediaId.substringAfterLast(':'),browser.currentMediaItem!!.mediaId);assertFalse(browser.currentMediaItem!!.mediaMetadata.extras!!.getString("track")!!.contains("Reprodução avulsa"));browser.seekToNextMediaItem()}
   var next=false;for(n in 0..200){main{next=browser.isPlaying&&browser.currentMediaItem?.mediaId==songs[1].mediaId.substringAfterLast(':')};if(next)break;Thread.sleep(100)};assertTrue("Próxima faixa mantém reprodução",next)
   i.sendStatus(0,Bundle().apply{putString("stream","\nCAR_MEDIA browse pagination search playlist_queue play next=ok\n")})
  }finally{main{browser.pause();browser.stop();browser.clearMediaItems();if(original.isNotEmpty())browser.setMediaItems(original,index,position);browser.volume=volume;browser.repeatMode=repeat;browser.shuffleModeEnabled=shuffle};Thread.sleep(300);library.savePlayer(saved);main{MediaBrowser.releaseFuture(future)}}
 }
 @Test fun legacyAndroidAutoBrowserCanConnectAndBrowse() {
  Assume.assumeTrue(MusicCloud.locallyApproved(context))
  val connected=CountDownLatch(1);val loaded=CountDownLatch(1);var failed=false
  lateinit var browser:android.media.browse.MediaBrowser
  main{browser=android.media.browse.MediaBrowser(context,ComponentName(context,EmilyMusicService::class.java),object:android.media.browse.MediaBrowser.ConnectionCallback(){override fun onConnected(){connected.countDown()};override fun onConnectionFailed(){failed=true;connected.countDown()}},null);browser.connect()}
  try{assertTrue(connected.await(15,TimeUnit.SECONDS));assertFalse(failed)
   main{assertEquals(MusicCarCatalog.ROOT,browser.root);browser.subscribe(browser.root,object:android.media.browse.MediaBrowser.SubscriptionCallback(){override fun onChildrenLoaded(parentId:String,children:MutableList<android.media.browse.MediaBrowser.MediaItem>){failed=children.size!=4;loaded.countDown()};override fun onError(parentId:String){failed=true;loaded.countDown()}})}
   assertTrue(loaded.await(15,TimeUnit.SECONDS));assertFalse(failed)
  }finally{main{browser.disconnect()}}
 }
 @Test fun accountCatalogRejectsUnknownTracksAndKeepsNamesAndOrder() {
  val uid="car-test-"+System.nanoTime();val library=MusicLibrarySession(context,uid,false)
  try {
   val name="Teste / café : carro";library.mutate("playlist_criar",JSONArray().put(name))
   val tracks=(0..2).map{JSONObject().put("video_id","aaaaaaaaaa$it").put("titulo","Faixa $it").put("artist","Artista")}
   tracks.forEach{library.mutate("music_copiar",JSONArray().put(name).put(it))}
   library.mutate("playlist_favoritar",JSONArray().put("aaaaaaaaaa1").put(true))
   val catalog=MusicCarCatalog(library);val folder=catalog.children(MusicCarCatalog.PLAYLISTS).first{it.mediaMetadata.title==name}
   if(library.online()){val songs=catalog.children(folder.mediaId);assertEquals(3,songs.size);val chosen=catalog.selection(songs[1].mediaId);assertEquals(1,chosen.index);assertEquals(listOf("Faixa 0","Faixa 1","Faixa 2"),chosen.items.map{it.mediaMetadata.title});assertEquals(name,JSONObject(chosen.items[1].mediaMetadata.extras!!.getString("track")!!).getString("source_title"));assertEquals(1,catalog.children(MusicCarCatalog.FAVORITES).size)}
   assertTrue(catalog.children(MusicCarCatalog.DOWNLOADS).isEmpty())
   try{catalog.selection("car:track:fake:bbbbbbbbbbb");fail("Unknown ID must not inject an arbitrary audio URI")}catch(_:IllegalArgumentException){}
   assertTrue(catalog.page(emptyList(),Int.MAX_VALUE,Int.MAX_VALUE).isEmpty())
  }finally{library.close();java.io.File(context.filesDir,"accounts/${MusicAccountPaths.key(uid)}").deleteRecursively();java.io.File(context.getExternalFilesDir(android.os.Environment.DIRECTORY_MUSIC),"Emily Music/${MusicAccountPaths.key(uid)}").deleteRecursively()}
 }
}
