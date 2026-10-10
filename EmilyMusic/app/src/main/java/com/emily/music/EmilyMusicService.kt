package com.emily.music

import android.app.PendingIntent
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.media3.session.CommandButton
import androidx.media3.session.SessionCommand
import androidx.media3.session.SessionResult
import com.google.common.util.concurrent.Futures
import androidx.media3.common.*
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.*
import androidx.media3.datasource.cache.*
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.session.MediaSession
import androidx.media3.session.MediaLibraryService
import androidx.media3.session.MediaLibraryService.MediaLibrarySession
import androidx.media3.session.LibraryResult
import com.google.common.collect.ImmutableList
import com.google.common.util.concurrent.ListenableFuture
import com.google.common.util.concurrent.SettableFuture
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File

/** O áudio e a sessão pertencem ao serviço, nunca à WebView/Activity. */
@UnstableApi
class EmilyMusicService : MediaLibraryService() {
    private lateinit var library:MusicLibrarySession
    private var session:MediaLibrarySession?=null
    @Volatile private var loggedOut=false
    private var loginOnly=false
    private val tokenCommand=SessionCommand(ACTION_TOKEN,Bundle.EMPTY)
    private val closeCommand=SessionCommand(ACTION_CLOSE,Bundle.EMPTY)
    private val queueCommand=SessionCommand(ACTION_QUEUE,Bundle.EMPTY)
    private val toggleCommand=SessionCommand(ACTION_TOGGLE,Bundle.EMPTY)
    private val repeatCommand=SessionCommand("emily.music.repeat",Bundle.EMPTY)
    private val shuffleCommand=SessionCommand("emily.music.shuffle",Bundle.EMPTY)
    private fun modeButtons(player:Player)=listOf(
        CommandButton.Builder(when(player.repeatMode){Player.REPEAT_MODE_ONE->CommandButton.ICON_REPEAT_ONE;Player.REPEAT_MODE_ALL->CommandButton.ICON_REPEAT_ALL;else->CommandButton.ICON_REPEAT_OFF})
            .setDisplayName(when(player.repeatMode){Player.REPEAT_MODE_ONE->"Repetição: faixa";Player.REPEAT_MODE_ALL->"Repetição: playlist";else->"Repetição: desligada"})
            .setSessionCommand(repeatCommand).setSlots(CommandButton.SLOT_OVERFLOW).build(),
        CommandButton.Builder(CommandButton.ICON_UNDEFINED).setCustomIconResId(R.drawable.ic_music_close)
            .setDisplayName("Fechar player").setSessionCommand(closeCommand).setSlots(CommandButton.SLOT_OVERFLOW).build()
    )
    private fun carButtons(player:Player)=listOf(modeButtons(player).first(),
        CommandButton.Builder(if(player.shuffleModeEnabled)CommandButton.ICON_SHUFFLE_ON else CommandButton.ICON_SHUFFLE_OFF)
            .setDisplayName(if(player.shuffleModeEnabled)"Aleatório: ligado" else "Aleatório: desligado").setSessionCommand(shuffleCommand).setSlots(CommandButton.SLOT_OVERFLOW).build())
    private fun updateButtons(player:Player) {session?.let{s->s.setMediaButtonPreferences(modeButtons(player));s.connectedControllers.filter{s.isAutoCompanionController(it)||s.isAutomotiveController(it)}.forEach{s.setMediaButtonPreferences(it,carButtons(player))}}}
    private fun modes(player:Player)=JSONObject()
        .put("loop",when(player.repeatMode){Player.REPEAT_MODE_ONE->2;Player.REPEAT_MODE_ALL->1;else->0})
        .put("shuffle",player.shuffleModeEnabled)
    private fun snapshot(player:Player)=JSONObject()
        .put("video_id",player.currentMediaItem?.mediaId?:"").put("indice",player.currentMediaItemIndex.coerceAtLeast(0)).put("posicao",player.currentPosition/1000.0)
    private var network:android.net.ConnectivityManager.NetworkCallback?=null
    private var reconnect:Job?=null
    private var preload:Job?=null
    private var preloadId:String?=null
    private fun prepareNext(player:Player) {
        val nextIndex=player.nextMediaItemIndex
        val next=if(nextIndex in 0 until player.mediaItemCount)player.getMediaItemAt(nextIndex).mediaId else null
        val cm=getSystemService(android.net.ConnectivityManager::class.java)
        val caps=cm.getNetworkCapabilities(cm.activeNetwork)
        // If the user advances to the track being prepared, let the foreground
        // resolver reuse its pending work instead of cancelling/restarting it.
        if(preload?.isActive==true && preloadId==player.currentMediaItem?.mediaId && player.playWhenReady)return
        val allowed=MusicPreloadPolicy.eligible(player.isPlaying,player.duration-player.currentPosition,
            caps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)==true,
            caps?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI)==true,
            caps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_NOT_METERED)==true,
            player.currentMediaItem?.mediaId,next,next?.startsWith("local_")==true,
            cm.restrictBackgroundStatus==android.net.ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED)
        if(!allowed){preload?.cancel();preload=null;preloadId=null;return}
        if(preloadId==next)return
        preload?.cancel();preloadId=next
        preload=work.launch(Dispatchers.IO) {
            delay(2000)
            try {
                if(next!=null && library.localUri(next)==null) {
                    val activeCaps=cm.getNetworkCapabilities(cm.activeNetwork)
                    val budget=MusicPreloadPolicy.byteBudget(
                        activeCaps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)==true,
                        activeCaps?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI)==true,
                        activeCaps?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_NOT_METERED)==true,
                        cm.restrictBackgroundStatus==android.net.ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED)
                    MusicHeadPreloader.prepare(next,library,budget)
                }
            }catch(e:CancellationException){throw e}catch(e:Exception){/* Optional preparation must not stop playback. */}
        }
    }
    private var suggestions:Job?=null
    private var suggestionSession=""
    private var suggestionRetryAt=0L
    private val recentAutoplay=linkedSetOf<String>()
    private fun track(item:MediaItem?)=item?.mediaMetadata?.extras?.getString("track")?.let {runCatching {JSONObject(it)}.getOrNull()}
    private fun continueDiscovery(player:Player) {
        val seed=track(player.currentMediaItem)
        val key=seed?.optString("autoplay_session").orEmpty()
        val enabled=!loggedOut && seed?.optBoolean("autoplay")==true && key.isNotBlank()
        if(key!=suggestionSession){suggestions?.cancel();suggestions=null;suggestionSession=key;suggestionRetryAt=0;recentAutoplay.clear()}
        if(!enabled || !player.playWhenReady || player.repeatMode==Player.REPEAT_MODE_ONE){suggestions?.cancel();suggestions=null;return}
        val current=player.currentMediaItem?.mediaId.orEmpty()
        recentAutoplay.remove(current);recentAutoplay.add(current)
        while(recentAutoplay.size>60)recentAutoplay.remove(recentAutoplay.first())
        var n=player.currentMediaItemIndex;var remaining=0;val visited=mutableSetOf(n)
        while(!player.currentTimeline.isEmpty){n=player.currentTimeline.getNextWindowIndex(n,Player.REPEAT_MODE_OFF,player.shuffleModeEnabled)
            if(n==C.INDEX_UNSET||!visited.add(n))break;remaining++}
        // If recommendations temporarily run out, keep the existing discovery
        // queue alive while retrying. Never restart after a user pause.
        if(player.playbackState==Player.STATE_ENDED && suggestions?.isActive!=true && suggestionRetryAt>android.os.SystemClock.elapsedRealtime() && library.online()) {
            val next=(0 until player.mediaItemCount).firstOrNull {player.getMediaItemAt(it).mediaId!=current} ?: player.currentMediaItemIndex
            if(next>=0){player.seekTo(next,0);player.prepare()};return
        }
        if(remaining>2 || suggestions?.isActive==true || !library.online() || android.os.SystemClock.elapsedRealtime()<suggestionRetryAt)return
        suggestions=work.launch {
            try {
                val rows=withContext(Dispatchers.IO){MusicRecommendations.related(seed!!)}
                val active=track(player.currentMediaItem)
                if(loggedOut || !player.playWhenReady || player.repeatMode==Player.REPEAT_MODE_ONE || active?.optString("autoplay_session")!=key)return@launch
                val queued=(0 until player.mediaItemCount).map {player.getMediaItemAt(it).mediaId}.toSet()
                val added=(0 until rows.length()).map {rows.getJSONObject(it)}.filter {it.optString("video_id") !in queued && it.optString("video_id") !in recentAutoplay}.take(10)
                if(added.isEmpty()){suggestionRetryAt=android.os.SystemClock.elapsedRealtime()+30000;return@launch}
                // Bound the timeline, preserving current and unplayed songs.
                for(i in player.mediaItemCount-1 downTo 0)if(player.mediaItemCount>100 && i!=player.currentMediaItemIndex && player.getMediaItemAt(i).mediaId in recentAutoplay)player.removeMediaItem(i)
                val tracks=org.json.JSONArray(added.take((200-player.mediaItemCount).coerceAtLeast(0)).map {JSONObject(it.toString()).put("origem","__avulsa__").put("autoplay",true).put("autoplay_session",key)})
                val items=withContext(Dispatchers.IO){musicItems(tracks,library)}
                if(track(player.currentMediaItem)?.optString("autoplay_session")!=key||!player.playWhenReady||player.repeatMode==Player.REPEAT_MODE_ONE)return@launch
                val ended=player.playbackState==Player.STATE_ENDED
                val start=player.mediaItemCount
                player.addMediaItems(items)
                if(ended&&items.isNotEmpty()){player.seekTo(start,0);player.prepare()}
                val queue=org.json.JSONArray((0 until player.mediaItemCount).map {track(player.getMediaItemAt(it))})
                withContext(Dispatchers.IO){if(!loggedOut)library.savePlayer(JSONObject().put("queue",queue))}
            }catch(e:CancellationException){throw e}catch(_:Exception){suggestionRetryAt=android.os.SystemClock.elapsedRealtime()+30000}
        }
    }
    private val recovery=MusicRecovery()
    private val listening=MusicListeningTracker()
    private val modeSnapshots=kotlinx.coroutines.channels.Channel<JSONObject>(kotlinx.coroutines.channels.Channel.CONFLATED)
    private val snapshots=kotlinx.coroutines.channels.Channel<JSONObject>(kotlinx.coroutines.channels.Channel.CONFLATED)
    private val work=CoroutineScope(SupervisorJob()+Dispatchers.Main)
    private fun logoutPlayer() {
        loggedOut=true;suggestions?.cancel();preload?.cancel();preload=null;preloadId=null;reconnect?.cancel();recovery.stop()
        session?.player?.run {pause();stop();clearMediaItems()}
        stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()
    }
    private fun closePlayer() {
        if(loggedOut)return
        loggedOut=true;suggestions?.cancel();preload?.cancel();reconnect?.cancel();recovery.stop()
        session?.player?.run {pause();stop();clearMediaItems()}
        sendBroadcast(Intent(ACTION_CLOSE).setPackage(packageName))
        stopForeground(STOP_FOREGROUND_REMOVE)
        work.launch {
            try {withContext(Dispatchers.IO){library.savePlayer(JSONObject().put("queue",org.json.JSONArray()).put("video_id","").put("indice",0).put("posicao",0))}}
            finally {stopSelf()}
        }
    }
    companion object {
        const val ACTION_TOKEN="com.emily.music.PLATFORM_TOKEN"
        const val ACTION_RETRY="com.emily.music.RETRY_PLAYBACK"
        const val ACTION_QUEUE="com.emily.music.EDIT_QUEUE"
        const val ACTION_TOGGLE="com.emily.music.TOGGLE_PLAYBACK"
        const val ACTION_CLOSE="com.emily.music.CLOSE_PLAYER"
        @Volatile private var running:EmilyMusicService?=null
        fun logoutPlayback(){running?.logoutPlayer()}
        private val caches=mutableMapOf<String,SimpleCache>()
        @Synchronized private fun releaseAudioCache(key:String){if(running==null)caches.remove(key)?.release()}
        @Synchronized fun audioCache(context:android.content.Context):SimpleCache {
            val key=EmilyMusicLibrary.accountId
            return caches.getOrPut(key){SimpleCache(File(context.cacheDir,"music-stream/$key"),LeastRecentlyUsedCacheEvictor(128L*1024*1024),StandaloneDatabaseProvider(context))}
        }
    }
    override fun onCreate() {
        super.onCreate()
        running=this
        if(MusicCloud.currentUser()==null || !MusicCloud.locallyApproved(this)){
            loginOnly=true
            val intent=PendingIntent.getActivity(this,702,Intent(this,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            session=MediaLibrarySession.Builder(this,ExoPlayer.Builder(this).build(),MusicCarSignIn(intent)).setSessionActivity(intent).build()
            return
        }
        startPlaybackSession()
    }
    private fun startPlaybackSession() {
        EmilyMusicLibrary.init(this);library=EmilyMusicLibrary.session();carDiscovery=MusicCarDiscovery(library);running=this
        val http=DefaultHttpDataSource.Factory().setConnectTimeoutMs(8000).setReadTimeoutMs(10000)
        val raw=DefaultDataSource.Factory(this,http)
        val upstream=DataSource.Factory {MusicStreamDataSource(raw.createDataSource(),library::localUri)}
        val data=CacheDataSource.Factory().setCache(audioCache(this)).setUpstreamDataSourceFactory(upstream)
            .setCacheKeyFactory {spec->spec.key?:spec.uri.toString()}.setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
        val provider=androidx.media3.session.DefaultMediaNotificationProvider.Builder(this).build()
        provider.setSmallIcon(R.drawable.ic_music)
        setMediaNotificationProvider(provider)
        val player=ExoPlayer.Builder(this).setLoadControl(MusicPlaybackTuning.loadControl()).setMediaSourceFactory(DefaultMediaSourceFactory(data).setLoadErrorHandlingPolicy(MusicLoadErrorPolicy())).setWakeMode(C.WAKE_MODE_NETWORK).build()
        player.setAudioAttributes(AudioAttributes.Builder().setUsage(C.USAGE_MEDIA).setContentType(C.AUDIO_CONTENT_TYPE_MUSIC).build(),true)
        player.setHandleAudioBecomingNoisy(true)
        work.launch {
            val saved=withContext(Dispatchers.IO){library.playerState()}
            val queue=saved.optJSONArray("queue") ?: org.json.JSONArray()
            val items=withContext(Dispatchers.IO){runCatching {musicItems(queue,library)}.getOrDefault(emptyList())}
            // Não substituir uma fila que o usuário já iniciou durante a leitura.
            if(!loggedOut && player.mediaItemCount==0 && player.playbackState==Player.STATE_IDLE) {
                if(items.isNotEmpty())player.setMediaItems(items,saved.optInt("indice",0).coerceIn(0,items.size-1),(saved.optDouble("posicao",0.0)*1000).toLong())
                player.repeatMode=when(saved.optInt("loop",1)){2->Player.REPEAT_MODE_ONE;1->Player.REPEAT_MODE_ALL;else->Player.REPEAT_MODE_OFF}
                player.shuffleModeEnabled=saved.optBoolean("shuffle");player.volume=saved.optDouble("volume",100.0).toFloat()/100
            }
        }
        work.launch {for(options in modeSnapshots)withContext(Dispatchers.IO){library.savePlayer(options)}}
        work.launch {for(snapshot in snapshots)withContext(Dispatchers.IO){synchronized(library){if(!loggedOut)library.savePlayer(snapshot)}}}
        work.launch {while(isActive){delay(10000);player.currentMediaItem?.let {snapshots.trySend(snapshot(player))}}}
        work.launch {while(isActive){delay(1000)
            continueDiscovery(player)
            if(player.isPlaying&&listening.qualify(android.os.SystemClock.elapsedRealtime(),player.duration)) {
                val item=player.currentMediaItem
                val track=item?.mediaMetadata?.extras?.getString("track")?.let {runCatching {JSONObject(it)}.getOrNull()}
                if(track!=null)withContext(Dispatchers.IO){runCatching {
                    if(track.optString("artist",track.optString("artista")).isBlank()) {
                        var artist=MusicNativeExtractor.artist(track.getString("video_id"))
                        if(artist.isBlank())runCatching {library.localUri(track.getString("video_id"))?.let {uri->
                            val retriever=android.media.MediaMetadataRetriever()
                            try {retriever.setDataSource(this@EmilyMusicService,uri);artist=retriever.extractMetadata(android.media.MediaMetadataRetriever.METADATA_KEY_ARTIST).orEmpty()} finally {retriever.release()}
                        }}
                        track.put("artist",artist.take(180))
                    }
                    library.recordListening(track)
                }}
            }
        }}
        player.addListener(object:Player.Listener {
            override fun onRepeatModeChanged(repeatMode:Int){updateButtons(player);modeSnapshots.trySend(modes(player))}
            override fun onShuffleModeEnabledChanged(shuffleModeEnabled:Boolean){updateButtons(player);modeSnapshots.trySend(modes(player))}
            override fun onIsPlayingChanged(isPlaying:Boolean){listening.playing(android.os.SystemClock.elapsedRealtime(),isPlaying);if(isPlaying){recovery.stop();reconnect?.cancel();reconnect=null;library.playbackNotice=""}}
            override fun onPlayWhenReadyChanged(playWhenReady:Boolean,reason:Int){if(!playWhenReady){recovery.stop();reconnect?.cancel()}}
            override fun onMediaItemTransition(item:MediaItem?,reason:Int) {
                EmilyMusicAudio.selectPlayback(item?.mediaId,reason!=Player.MEDIA_ITEM_TRANSITION_REASON_AUTO && reason!=Player.MEDIA_ITEM_TRANSITION_REASON_REPEAT)
                listening.transition(android.os.SystemClock.elapsedRealtime(),player.isPlaying)
                reconnect?.cancel();recovery.stop();library.playbackNotice=""
                if(item==null)return
                session?.connectedControllers?.forEach{MusicCarArtwork.grant(this@EmilyMusicService,it.packageName,listOf(item))}
                work.launch {
                    val id=item.mediaId
                    if(player.currentMediaItem?.mediaId==id && !loggedOut)MusicPlaybackActions.prepareIfWanted(player)
                    val candidates=(0 until player.mediaItemCount).map {player.getMediaItemAt(it).mediaId}
                    val available=withContext(Dispatchers.IO){
                        if(library.online())null else candidates.filter {library.localUri(it)!=null}.toSet()
                    } ?: return@launch
                    if(player.currentMediaItem?.mediaId!=id || id in available)return@launch
                    var next=player.currentMediaItemIndex
                    val visited=mutableSetOf(next)
                    while(!player.currentTimeline.isEmpty){
                        next=player.currentTimeline.getNextWindowIndex(next,if(player.repeatMode==Player.REPEAT_MODE_ONE)Player.REPEAT_MODE_ALL else player.repeatMode,player.shuffleModeEnabled)
                        if(next==C.INDEX_UNSET||!visited.add(next))break
                        if(player.getMediaItemAt(next).mediaId in available){player.seekTo(next,0);return@launch}
                    }
                    player.pause()
                }
            }
            override fun onPlayerError(error:PlaybackException) {
                val status=generateSequence(error as Throwable?){it.cause}.filterIsInstance<HttpDataSource.InvalidResponseCodeException>().firstOrNull()?.responseCode
                val resolutionError=generateSequence(error as Throwable?){it.cause}.any{it is MusicAudioResolutionException}
                val networkError=MusicRecoveryPolicy.retryable(error.errorCode,status,resolutionError,library.online())
                android.util.Log.w("MusicPlayback","Falha de reprodução: code=${error.errorCode}, http=$status, resolution=$resolutionError, retry=$networkError")
                val id=player.currentMediaItem?.mediaId
                recovery.failed(id,player.playWhenReady,networkError)
                if(networkError&&reconnect?.isActive!=true){reconnect=work.launch {
                    for(wait in listOf(1000L,3000L,8000L)) {
                        delay(wait)
                        if(!recovery.canAttempt(id,library.online()) || player.currentMediaItem?.mediaId!=id)continue
                        if(player.isPlaying){recovery.stop();return@launch}
                        if(player.playerError==null)continue
                        recovery.attempted();EmilyMusicAudio.invalidate(id,legacy=error.errorCode==PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS);player.prepare();player.play()
                    }
                    if(!loggedOut && player.currentMediaItem?.mediaId==id && player.playerError!=null)
                        library.playbackNotice="Não foi possível retomar o áudio. Verifique a conexão ou escolha outra faixa."
                }}
                library.playbackNotice=if(networkError)"O áudio falhou. Tentando reconectar…" else if(error.errorCode==PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS)
                    "Não foi possível acessar o áudio desta faixa após renovar o endereço. Tente novamente ou escolha outra faixa."
                else "Não foi possível tocar esta faixa. Verifique a conexão ou tente novamente."
                // Não avança silenciosamente para uma faixa errada nem repete ações.
            }
            override fun onEvents(p:Player,events:Player.Events){
                prepareNext(p)
                continueDiscovery(p)
                snapshots.trySend(snapshot(p))
            }
        })
        val intent=Intent(this,MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP).putExtra("emily_music",true)
        val pending=PendingIntent.getActivity(this,701,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val retry=PendingIntent.getService(this,703,Intent(this,EmilyMusicService::class.java).setAction(ACTION_RETRY),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        session=MediaLibrarySession.Builder(this,MusicSessionPlayer(player,retry),object:MediaLibrarySession.Callback {
                override fun onGetLibraryRoot(s:MediaLibrarySession,c:MediaSession.ControllerInfo,p:LibraryParams?):ListenableFuture<LibraryResult<MediaItem>> =
                    Futures.immediateFuture(LibraryResult.ofItem(MusicCarCatalog(library).root(),LibraryParams.Builder().setExtras(Bundle(p?.extras?:Bundle.EMPTY).apply{
                        putBoolean(androidx.media.utils.MediaConstants.BROWSER_SERVICE_EXTRAS_KEY_SEARCH_SUPPORTED,true)
                        putInt("android.media.browse.CONTENT_STYLE_BROWSABLE_HINT",2)
                        putInt("android.media.browse.CONTENT_STYLE_PLAYABLE_HINT",1)
                        putStringArrayList(androidx.media.utils.MediaConstants.DESCRIPTION_EXTRAS_KEY_CUSTOM_BROWSER_ACTION_ID_LIST,arrayListOf(MusicCarNavigation.PLAYING))
                    }).build()))
                override fun onGetChildren(s:MediaLibrarySession,c:MediaSession.ControllerInfo,id:String,page:Int,size:Int,p:LibraryParams?):ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> =
                    carFuture {val catalog=MusicCarCatalog(library);val items=catalog.page((if(carDiscovery.owns(id))carDiscovery.children(id) else null)?:catalog.children(id),page,size);MusicCarArtwork.grant(this@EmilyMusicService,c.packageName,items);LibraryResult.ofItemList(items,p)}
                override fun onGetItem(s:MediaLibrarySession,c:MediaSession.ControllerInfo,id:String):ListenableFuture<LibraryResult<MediaItem>> =
                    carFuture {((if(carDiscovery.owns(id))carDiscovery.getItem(id) else null)?:MusicCarCatalog(library).item(id))?.let{MusicCarArtwork.grant(this@EmilyMusicService,c.packageName,listOf(it));LibraryResult.ofItem(it,null)}?:LibraryResult.ofError(SessionResult.RESULT_ERROR_BAD_VALUE)}
                override fun onSearch(s:MediaLibrarySession,c:MediaSession.ControllerInfo,q:String,p:LibraryParams?):ListenableFuture<LibraryResult<Void>> {
                    val result=SettableFuture.create<LibraryResult<Void>>()
                    work.launch {try {val count=withContext(Dispatchers.IO){val found=carDiscovery.search(q);EmilyMusicAudio.prepareVisible(carDiscovery.preparationIds(found),library);found.size};if(accountOpen()){s.notifySearchResultChanged(c,q,count,p);result.set(LibraryResult.ofVoid(p))}else result.set(LibraryResult.ofError(SessionResult.RESULT_ERROR_SESSION_DISCONNECTED))}catch(e:Exception){result.set(LibraryResult.ofError(SessionResult.RESULT_ERROR_IO))}}
                    return result
                }
                override fun onGetSearchResult(s:MediaLibrarySession,c:MediaSession.ControllerInfo,q:String,page:Int,size:Int,p:LibraryParams?):ListenableFuture<LibraryResult<ImmutableList<MediaItem>>> =
                    carFuture {val catalog=MusicCarCatalog(library);val items=catalog.page(carDiscovery.search(q),page,size);MusicCarArtwork.grant(this@EmilyMusicService,c.packageName,items);LibraryResult.ofItemList(items,p)}
                override fun onSetMediaItems(s:MediaSession,c:MediaSession.ControllerInfo,items:List<MediaItem>,index:Int,position:Long):ListenableFuture<MediaSession.MediaItemsWithStartPosition> {
                    if(c.uid==android.os.Process.myUid()&&items.none{it.mediaId.startsWith("car:")})return Futures.immediateFuture(MediaSession.MediaItemsWithStartPosition(items,index,position))
                    return carFuture {require(items.isNotEmpty());val catalog=MusicCarCatalog(library)
                        if(items.size==1){val requested=items[0];val query=requested.requestMetadata.searchQuery.orEmpty()
                            val id=if(requested.mediaId.isBlank()&&query.isNotBlank())carDiscovery.search(query).firstOrNull{it.mediaMetadata.isPlayable==true}?.mediaId?:throw IllegalArgumentException("Nenhuma música encontrada") else requested.mediaId
                            val chosen=(if(carDiscovery.owns(id))carDiscovery.selection(id) else null)?:catalog.selection(id);MediaSession.MediaItemsWithStartPosition(chosen.items,chosen.index,position)}
                        else MediaSession.MediaItemsWithStartPosition(items.map{(if(carDiscovery.owns(it.mediaId))carDiscovery.selection(it.mediaId) else null)?.let{chosen->chosen.items[chosen.index]}?:catalog.single(it.mediaId)},index,position)}
                }
                override fun onAddMediaItems(s:MediaSession,c:MediaSession.ControllerInfo,items:List<MediaItem>):ListenableFuture<List<MediaItem>> =
                    if(c.uid==android.os.Process.myUid()&&items.none{it.mediaId.startsWith("car:")})Futures.immediateFuture(items) else carFuture {items.map{(if(carDiscovery.owns(it.mediaId))carDiscovery.selection(it.mediaId) else null)?.let{chosen->chosen.items[chosen.index]}?:MusicCarCatalog(library).single(it.mediaId)}}

                override fun onPlaybackResumption(s:MediaSession,c:MediaSession.ControllerInfo,isForPlayback:Boolean):ListenableFuture<MediaSession.MediaItemsWithStartPosition> = carFuture {
                    val saved=library.playerState();val queue=saved.optJSONArray("queue")?:org.json.JSONArray()
                    val rows=(0 until queue.length()).mapNotNull{queue.optJSONObject(it)}.filter{m->val id=m.optString("video_id");id.matches(Regex("[A-Za-z0-9_-]{11}|local_[a-f0-9]{64}"))&&(library.localUri(id)!=null||(!id.startsWith("local_")&&library.online()))}
                    require(rows.isNotEmpty()){"Escolha uma música no celular ou no carro"}
                    val index=rows.indexOfFirst{it.optString("video_id")==saved.optString("video_id")}.coerceAtLeast(0)
                    MediaSession.MediaItemsWithStartPosition(musicItems(org.json.JSONArray(rows),library),index,(saved.optDouble("posicao",0.0)*1000).toLong().coerceAtLeast(0))
                }
                override fun onConnect(s:MediaSession,c:MediaSession.ControllerInfo):MediaSession.ConnectionResult {
                    val companion=c.packageName=="com.example.emilyapp" &&
                        packageManager.checkSignatures(packageName,c.packageName)==android.content.pm.PackageManager.SIGNATURE_MATCH
                    if(!accountOpen() || !(companion||c.uid==android.os.Process.myUid()||c.isTrusted||s.isAutoCompanionController(c)||s.isAutomotiveController(c)))return MediaSession.ConnectionResult.reject()
                    player.currentMediaItem?.let{MusicCarArtwork.grant(this@EmilyMusicService,c.packageName,listOf(it))}
                    val commands=MediaSession.ConnectionResult.DEFAULT_SESSION_AND_LIBRARY_COMMANDS.buildUpon().add(repeatCommand).add(shuffleCommand).add(closeCommand).apply{(MusicCarNavigation.commands+MusicCarDiscovery.commands).forEach{add(SessionCommand(it,Bundle.EMPTY))}}.apply{if(c.uid==android.os.Process.myUid()){add(queueCommand);add(toggleCommand);add(tokenCommand)}}.build()
                    return MediaSession.ConnectionResult.AcceptedResultBuilder(s).setAvailableSessionCommands(commands).apply{if(s.isAutoCompanionController(c)||s.isAutomotiveController(c))setMediaButtonPreferences(carButtons(player))}.build()
                }
                override fun onCustomCommand(s:MediaSession,c:MediaSession.ControllerInfo,command:SessionCommand,args:Bundle):com.google.common.util.concurrent.ListenableFuture<SessionResult> {
                    val carId=args.getString(androidx.media3.session.MediaConstants.EXTRA_KEY_MEDIA_ID)
                        ?:args.getString(androidx.media.utils.MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_MEDIA_ITEM_ID)
                    if(command.customAction in MusicCarDiscovery.commands || (command.customAction==MusicCarNavigation.BACK&&carId!=null&&carDiscovery.owns(carId)))return carFuture {
                        try {
                            val result=if(command.customAction==MusicCarNavigation.BACK)Bundle().apply{putString(androidx.media.utils.MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE,carDiscovery.parent(carId!!)?:MusicCarCatalog.ROOT)}
                            else carDiscovery.action(command.customAction,carId?:throw IllegalArgumentException("Escolha um resultado da busca."))
                            val catalog=MusicCarCatalog(library)
                            val counts=listOf(MusicCarCatalog.PLAYLISTS,MusicCarCatalog.ALL,MusicCarCatalog.FAVORITES,MusicCarCatalog.DOWNLOADS).associateWith{catalog.children(it).size}
                            work.launch {counts.forEach{(parent,count)->(s as MediaLibrarySession).notifyChildrenChanged(parent,count,null)}}
                            SessionResult(SessionResult.RESULT_SUCCESS,result)
                        }catch(e:kotlinx.coroutines.CancellationException){throw e}catch(e:Exception){SessionResult(SessionResult.RESULT_ERROR_BAD_VALUE,Bundle().apply{putString(androidx.media.utils.MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_MESSAGE,e.message?.take(200)?:"Não foi possível concluir. Tente novamente.")})}
                    }
                    MusicCarNavigation.result(command.customAction,carId)?.let{
                        return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS,it))
                    }
                    when(command.customAction) {
                        tokenCommand.customAction->return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS,Bundle().apply{putParcelable("token",s.platformToken)}))
                        toggleCommand.customAction->{MusicPlaybackActions.toggle(player);return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))}
                        queueCommand.customAction->{
                            val result=com.google.common.util.concurrent.SettableFuture.create<SessionResult>()
                            work.launch {
                                try {
                                    val items=withContext(Dispatchers.IO){val q=org.json.JSONArray(args.getString("queue")?:"[]");require(q.length()<=200);musicItems(q,library)}
                                    val ok=!loggedOut&&MusicQueueEditor.apply(player,items,args.getString("expected").orEmpty())
                                    if(ok){val rows=org.json.JSONArray((0 until player.mediaItemCount).map {n->JSONObject(player.getMediaItemAt(n).mediaMetadata.extras?.getString("track")?:"{}")});withContext(Dispatchers.IO){library.savePlayer(JSONObject().put("queue",rows))}}
                                    result.set(SessionResult(if(ok)SessionResult.RESULT_SUCCESS else SessionResult.RESULT_ERROR_INVALID_STATE))
                                }catch(e:Exception){result.set(SessionResult(SessionResult.RESULT_ERROR_BAD_VALUE))}
                            }
                            return result
                        }
                        closeCommand.customAction->{closePlayer();return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))}
                        shuffleCommand.customAction->player.shuffleModeEnabled=!player.shuffleModeEnabled
                        repeatCommand.customAction->player.repeatMode=when(player.repeatMode){Player.REPEAT_MODE_OFF->Player.REPEAT_MODE_ALL;Player.REPEAT_MODE_ALL->Player.REPEAT_MODE_ONE;else->Player.REPEAT_MODE_OFF}
                        else->return Futures.immediateFuture(SessionResult(SessionResult.RESULT_ERROR_NOT_SUPPORTED))
                    }
                    modeSnapshots.trySend(modes(player))
                    return Futures.immediateFuture(SessionResult(SessionResult.RESULT_SUCCESS))
                }
            }).setCommandButtonsForMediaItems(MusicCarNavigation.buttons(this)+MusicCarDiscovery.buttons(this)).setSessionActivity(pending).setMediaButtonPreferences(modeButtons(player)).build()
        val cm=getSystemService(android.net.ConnectivityManager::class.java)
        network=object:android.net.ConnectivityManager.NetworkCallback(){
            override fun onCapabilitiesChanged(n:android.net.Network,c:android.net.NetworkCapabilities){
                if(!c.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)) {
                    work.launch {preload?.cancel();preload=null;preloadId=null};return
                }
                work.launch {if(!loggedOut){suggestionRetryAt=0;prepareNext(player);continueDiscovery(player)}}
                work.launch {if(!loggedOut && player.playerError!=null){
                    recovery.connectionRestored()
                    val id=player.currentMediaItem?.mediaId
                    if(recovery.canAttempt(id,true)){recovery.attempted();EmilyMusicAudio.invalidate(id);player.prepare();player.play()}
                }}
            }
        }
        runCatching{cm.registerDefaultNetworkCallback(network!!)}

    }
    private lateinit var carDiscovery:MusicCarDiscovery
    private fun accountOpen()=this::library.isInitialized&&!library.closed&&!loggedOut&&library.uid==MusicCloud.currentUser()?.uid
    private fun <T> carFuture(block:suspend ()->T):ListenableFuture<T> {
        val result=SettableFuture.create<T>()
        val job=work.launch {try {check(accountOpen());val value=withContext(Dispatchers.IO){block()};check(accountOpen());result.set(value)}catch(e:Exception){result.setException(e)}}
        result.addListener({if(result.isCancelled)job.cancel()},com.google.common.util.concurrent.MoreExecutors.directExecutor())
        return result
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        val result=super.onStartCommand(intent,flags,startId)
        if(intent?.action==ACTION_RETRY && accountOpen()) {
            recovery.stop();reconnect?.cancel();reconnect=null
            EmilyMusicAudio.invalidate(session?.player?.currentMediaItem?.mediaId)
            session?.player?.let(MusicPlaybackActions::resume)
        }
        return result
    }
    override fun onGetSession(controllerInfo:MediaSession.ControllerInfo):MediaLibrarySession? {
        if(loginOnly&&!loggedOut&&MusicCloud.locallyApproved(this)){
            session?.run{player.release();release()};session=null;loginOnly=false;startPlaybackSession()
        }
        return if((loginOnly&&!loggedOut)||accountOpen())session else null
    }
    override fun onTaskRemoved(rootIntent:Intent?) {if(session?.player?.playWhenReady!=true)stopSelf()}
    override fun onDestroy(){
        val visible=EmilyMusicAudio.stopVisiblePreparation()
        val nextPreparation=preload
        if(running===this){running=null;EmilyMusicAudio.selectPlayback(null)}
        network?.let{runCatching{getSystemService(android.net.ConnectivityManager::class.java).unregisterNetworkCallback(it)}}
        session?.run {player.release();release()};session=null;work.cancel()
        if(this::library.isInitialized){
            val key=library.accountId
            // Finish canceled reads before closing the shared cache. A newly started service may reuse it.
            CoroutineScope(Dispatchers.IO).launch {
                visible?.join();nextPreparation?.join()
                runCatching{releaseAudioCache(key)}
            }
        }
        super.onDestroy()
    }
}
