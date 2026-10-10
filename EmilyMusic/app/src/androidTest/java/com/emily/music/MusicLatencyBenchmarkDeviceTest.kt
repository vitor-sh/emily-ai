package com.emily.music

import androidx.test.platform.app.InstrumentationRegistry
import androidx.media3.common.*
import androidx.media3.datasource.*
import androidx.media3.datasource.cache.*
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import kotlinx.coroutines.*
import org.json.*
import org.junit.Test
import org.junit.Assert.*
import java.io.File
import java.util.concurrent.atomic.AtomicReference

/** Real, silent playback. Independent transient byte cache; no changes to playlists or listening history. */
class MusicLatencyBenchmarkDeviceTest {
 @Test fun compareSearchWithFrozen27()=runBlocking(Dispatchers.IO) {
  val i=InstrumentationRegistry.getInstrumentation();val ctx=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(ctx));EmilyMusicLibrary.init(ctx)
  for(round in 0..1)for(q in listOf("The Score The Fear","Lena Raine Resurrections Celeste","NEFFEX Careless")) {
   for(old in if(round==0)listOf(true,false) else listOf(false,true)) {
    EmilyMusicSearch.clearCache();BaselineMusicSearch27.clearCache()
    val start=android.os.SystemClock.elapsedRealtime();var first=0L
    val result=if(old)BaselineMusicSearch27.search(q,"all") else EmilyMusicSearch.search(q,"all"){
      if(first==0L)first=android.os.SystemClock.elapsedRealtime()-start
    }
    val elapsed=android.os.SystemClock.elapsedRealtime()-start
    assertTrue(result.getJSONArray("resultados").length()>0)
    val row=JSONObject().put("kind","paired_search").put("round",round).put("query",q)
      .put("old",old).put("ms",elapsed).put("first_ms",if(first>0)first else elapsed)
    i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nMUSIC_LATENCY $row\n")})
   }
  }
 }
 @Test fun measureSearchAndClickToPlayback()=runBlocking(Dispatchers.IO) {
  val i=InstrumentationRegistry.getInstrumentation();val ctx=i.targetContext
  org.junit.Assume.assumeTrue(MusicCloud.locallyApproved(ctx));EmilyMusicLibrary.init(ctx)
  val args=InstrumentationRegistry.getArguments();val label=args.getString("label","baseline")
  val out=File(ctx.getExternalFilesDir("performance"),"fixtures.json")
  val queries=listOf("The Score The Fear","Lena Raine Resurrections Celeste","NEFFEX Careless")
  fun now()=android.os.SystemClock.elapsedRealtime()
  fun emit(row:JSONObject){i.sendStatus(0,android.os.Bundle().apply{putString("stream","\nMUSIC_LATENCY "+row.put("label",label)+"\n")})}
  val fixtures=JSONArray()
  for(q in queries) {
   EmilyMusicSearch.clearCache();val start=now()
   var first=0L
   val data=EmilyMusicSearch.search(q,"all"){if(first==0L)first=now()-start};val elapsed=now()-start
   val rows=data.getJSONArray("resultados");assertTrue(rows.length()>0)
   emit(JSONObject().put("kind","search_cold").put("query",q).put("ms",elapsed).put("count",rows.length()).put("first_ms",if(first>0)first else elapsed))
   val cachedStart=now();val cached=EmilyMusicSearch.search(q,"all")
   emit(JSONObject().put("kind","search_cached").put("query",q).put("ms",now()-cachedStart).put("count",cached.getJSONArray("resultados").length()))
   if(label!="baseline")for(filter in listOf("videos","playlists")) {
    val filterStart=now();val filtered=EmilyMusicSearch.search(q,filter);val filterMs=now()-filterStart
    assertTrue("Switching filters must reuse the complete group",filtered.getJSONArray("resultados").length()>6)
    assertTrue("Cached filters should not make a network trip",filterMs<500)
    emit(JSONObject().put("kind","search_filter_cached").put("filter",filter).put("ms",filterMs).put("count",filtered.getJSONArray("resultados").length()))
   }
   val m=(0 until rows.length()).map{rows.getJSONObject(it)}.first{it.optString("video_id").matches(Regex("[A-Za-z0-9_-]{11}"))}
   fixtures.put(JSONObject().put("query",q).put("video_id",m.getString("video_id")))
  }
  out.parentFile!!.mkdirs();if(!out.exists())out.writeText(fixtures.toString())
  val selected=JSONArray(out.readText())
  var successful=0
  for(round in 0..1)for(n in 0 until selected.length()) {
   val id=selected.getJSONObject((n+round)%selected.length()).getString("video_id")
   for(prepared in listOf(false,true)) {
    EmilyMusicAudio.clearCache()
    val directory=File(ctx.cacheDir,"latency-$label-$round-$n-$prepared");directory.deleteRecursively()
    val cache=SimpleCache(directory,LeastRecentlyUsedCacheEvictor(128L*1024*1024),StandaloneDatabaseProvider(ctx))
    var preparation=0L
    if(prepared){val start=now();try {
      EmilyMusicAudio.resolve(id,false)
      if(label!="baseline"){
        MusicHeadPreloader.prepare(id,EmilyMusicLibrary.session(),128L*1024,cache)
        assertTrue("The bounded head must be persisted before the click",cache.isCached(id,0,128L*1024))
        assertEquals("A repeat must not fetch the same head twice",0L,MusicHeadPreloader.prepare(id,EmilyMusicLibrary.session(),128L*1024,cache))
      }
    }catch(e:Exception){cache.release();directory.deleteRecursively();throw e};preparation=now()-start}
    var resolution=0L;var source="";var opens=0
    val raw=DefaultDataSource.Factory(ctx,DefaultHttpDataSource.Factory().setConnectTimeoutMs(8000).setReadTimeoutMs(10000))
    val upstream=DataSource.Factory{MusicStreamDataSource(raw.createDataSource(),{null},{vid->
      val start=now();val stream=EmilyMusicAudio.resolve(vid);resolution+=now()-start;source=stream.source;opens++;stream
    })}
    val data=CacheDataSource.Factory().setCache(cache).setUpstreamDataSourceFactory(upstream).setCacheKeyFactory{it.key?:it.uri.toString()}.setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
    lateinit var player:ExoPlayer;val error=AtomicReference<PlaybackException?>();var playing=false
    i.runOnMainSync{val builder=ExoPlayer.Builder(ctx).setMediaSourceFactory(DefaultMediaSourceFactory(data))
      if(label!="baseline")builder.setLoadControl(MusicPlaybackTuning.loadControl())
      player=builder.build();player.volume=0f;player.addListener(object:Player.Listener{override fun onPlayerError(e:PlaybackException){error.set(e)}})}
    val start=now()
    try {
      i.runOnMainSync{player.setMediaItem(MediaItem.Builder().setMediaId(id).setUri("emilymusic://$id").setCustomCacheKey(id).build());player.prepare();player.play()}
      while(now()-start<40_000&&error.get()==null){i.runOnMainSync{playing=player.isPlaying};if(playing)break;delay(20)}
      val row=JSONObject().put("kind",if(prepared)"play_prepared" else "play_cold").put("round",round).put("video_id",id).put("ms",now()-start).put("preparation_ms",preparation).put("resolution_ms",resolution).put("source",source).put("opens",opens).put("cached_bytes",cache.cacheSpace).put("success",playing).put("error_code",error.get()?.errorCode?:0)
      emit(row);if(playing)successful++
    }finally{i.runOnMainSync{player.release()};cache.release();directory.deleteRecursively()}
   }
  }
  EmilyMusicAudio.clearCache();assertTrue("At least half of real playback measurements must succeed",successful>=6)
 }
}
