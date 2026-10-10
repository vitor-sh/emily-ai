package com.emily.music

import android.Manifest
import android.content.Context
import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.webkit.*
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.material3.*
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.media3.common.MediaItem
import androidx.media3.common.MediaMetadata
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.MediaController
import androidx.media3.session.SessionToken
import androidx.webkit.WebViewAssetLoader
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject

@UnstableApi
@Composable
fun EmilyMusicScreen(onBack:()->Unit) {
    val context=LocalContext.current
    val scope=rememberCoroutineScope()
    var uid by remember {mutableStateOf(MusicCloud.currentUser()?.uid)}
    var approved by remember {mutableStateOf(false)}
    var checking by remember {mutableStateOf(false)}
    var signing by remember {mutableStateOf(false)}
    var error by remember {mutableStateOf<String?>(null)}
    var retry by remember {mutableStateOf(0)}
    DisposableEffect(Unit) {
        val remove=MusicCloud.observeAccount {value->if(uid!=value){approved=false;uid=value}}
        onDispose {remove()}
    }
    LaunchedEffect(uid,retry) {
        approved=false
        if(uid!=null) {
            checking=true;error=null
            try {MusicCloud.authorize(context);withContext(Dispatchers.IO){EmilyMusicLibrary.init(context)};approved=true}
            catch(e:CancellationException){throw e}
            catch(e:Exception){error=e.message?:"Não foi possível confirmar sua conta."}
            finally {checking=false}
        }
    }
    if(approved && uid!=null) {key(uid){EmilyMusicScreenContent(onBack)};return}
    BackHandler {onBack()}
    MusicWelcomeScreen(busy=checking || signing,hasAccount=uid!=null,error=error,
        onEnter={
            if(uid!=null)retry++
            else scope.launch(Dispatchers.Main.immediate) {
                signing=true;error=null
                try {MusicCloud.signIn(context)}
                catch(e:CancellationException){throw e}
                catch(e:androidx.credentials.exceptions.GetCredentialCancellationException){ /* User closed account chooser. */ }
                catch(_:Exception){error="Não foi possível entrar com Google. Tente novamente."}
                finally {signing=false}
            }
        },onChangeAccount={scope.launch(Dispatchers.Main.immediate) {
            try {MusicCloud.signOut(context)}
            catch(e:CancellationException){throw e}
            catch(_:Exception){error="Não foi possível concluir a saída. Tente novamente."}
        }},onBack=onBack)

}

@UnstableApi
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EmilyMusicScreenContent(onBack:()->Unit) {
    val context=LocalContext.current
    val library=remember {EmilyMusicLibrary.session()}
    val update by MusicUpdater.state.collectAsState()
    var settingsOpen by remember {mutableStateOf(false)}
    val audioRoutes=remember(context){MusicAudioRoutes(context)}
    var outputOpen by remember {mutableStateOf(false)}
    var outputError by remember {mutableStateOf<String?>(null)}
    var outputChoices by remember {mutableStateOf(emptyList<MusicAudioRoutes.Output>())}
    LaunchedEffect(outputOpen){while(outputOpen){outputChoices=audioRoutes.choices();delay(1000)}}
    var accountBusy by remember {mutableStateOf(false)}
    var accountError by remember {mutableStateOf<String?>(null)}
    var web by remember {mutableStateOf<WebView?>(null)}
    var controller by remember {mutableStateOf<MediaController?>(null)}
    val scope=rememberCoroutineScope()
    var fileCallback by remember {mutableStateOf<ValueCallback<Array<Uri>>?>(null)}
    val filePick=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()){uri->fileCallback?.onReceiveValue(uri?.let{arrayOf(it)});fileCallback=null}
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){allowed->
        scope.launch(Dispatchers.Main.immediate) {withContext(Dispatchers.IO){library.scan()};web?.evaluateJavascript("EmilyMusic.refresh()",null)}
        if(!allowed)web?.evaluateJavascript("toast('Autorize o acesso ao áudio para encontrar os MP3 do celular.')",null)
    }
    val folder=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()){uri->if(uri!=null){
        runCatching{context.contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)}
        scope.launch(Dispatchers.IO) { library.addFolder(uri) }
    }}
    LaunchedEffect(Unit) {
        // Prepare binaries while the user browses; never block the UI or fetch audio.
        launch(Dispatchers.IO){if(library.online())runCatching {YoutubeDownloader.prepararMusic(context.applicationContext)}}
        val permissionName=if(Build.VERSION.SDK_INT>=33)Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE
        val prefs=context.getSharedPreferences("music_permissions",Context.MODE_PRIVATE)
        if(ContextCompat.checkSelfPermission(context,permissionName)!=android.content.pm.PackageManager.PERMISSION_GRANTED && !prefs.getBoolean("asked",false)) {
            prefs.edit().putBoolean("asked",true).apply();permission.launch(permissionName)
        }
        while(isActive){withContext(Dispatchers.IO){library.scan()};delay(30000)}
    }
    BackHandler {
        val current=web
        if(current==null)onBack() else current.evaluateJavascript("window.MusicMobile ? MusicMobile.back() : false") {handled->if(handled!="true")onBack()}
    }
    DisposableEffect(Unit) {
        val future=MediaController.Builder(context,SessionToken(context,ComponentName(context,EmilyMusicService::class.java))).buildAsync()
        var disposed=false
        future.addListener({if(!disposed)runCatching{controller=future.get()}},ContextCompat.getMainExecutor(context))
        onDispose {EmilyMusicAudio.stopVisiblePreparation();disposed=true;fileCallback?.onReceiveValue(null);fileCallback=null;MediaController.releaseFuture(future);web?.removeJavascriptInterface("EmilyAndroid");web?.destroy();web=null}
    }
    LaunchedEffect(controller) {
        val c=controller ?: return@LaunchedEffect
        var lastTimeline: androidx.media3.common.Timeline? = null
        var lastOrder=""
        var fullSnapshotAt=0L;var lastWeb:WebView?=null
        while(isActive){
            val state=withContext(Dispatchers.Main.immediate) {
            val snapshot=JSONObject().put("indice",c.currentMediaItemIndex.coerceAtLeast(0)).put("video_id",c.currentMediaItem?.mediaId?:"")
                .put("playing",c.playWhenReady&&c.playbackState!=Player.STATE_ENDED&&c.playbackState!=Player.STATE_IDLE)
                .put("loop",when(c.repeatMode){Player.REPEAT_MODE_ONE->2;Player.REPEAT_MODE_ALL->1;else->0}).put("shuffle",c.shuffleModeEnabled)
                .put("buffering",c.playbackState==Player.STATE_BUFFERING).put("posicao",c.currentPosition/1000.0).put("duracao",c.duration.coerceAtLeast(0)/1000.0)
            val current=c.currentMediaItem
            val track=current?.let {musicPlaybackTrack(it)}
            snapshot.put("track",track?:JSONObject.NULL).put("output",audioRoutes.currentName())
                .put("external_output",audioRoutes.hasExternalOutput())
            val now=android.os.SystemClock.elapsedRealtime()
            if (lastTimeline !== c.currentTimeline || web!==lastWeb || now-fullSnapshotAt>=3000) {
                lastWeb=web;fullSnapshotAt=now
                lastTimeline=c.currentTimeline
                val tracks=(0 until c.mediaItemCount).map {musicPlaybackTrack(c.getMediaItemAt(it))}
                snapshot.put("queue",JSONArray(tracks))
            }
            val orderKey="${c.currentMediaItemIndex}:${c.shuffleModeEnabled}:${c.currentTimeline.hashCode()}"
            if(orderKey!=lastOrder){
                lastOrder=orderKey
                val order=JSONArray();var index=c.currentMediaItemIndex
                while(index>=0 && index<c.currentTimeline.windowCount && order.length()<c.mediaItemCount){
                    order.put(index);index=c.currentTimeline.getNextWindowIndex(index,Player.REPEAT_MODE_OFF,c.shuffleModeEnabled)
                }
                snapshot.put("order",order)
            }
            snapshot
            }
            val json=withContext(Dispatchers.Default){state.toString()}
            withContext(Dispatchers.Main.immediate){web?.evaluateJavascript("window.musicState&&musicState($json)",null)}
            delay(500)
        }
    }
    Column(Modifier.fillMaxSize().systemBarsPadding()) {
    AndroidView(modifier=Modifier.fillMaxWidth().weight(1f),factory={ctx->
        val assets=WebViewAssetLoader.Builder().addPathHandler("/assets/",WebViewAssetLoader.AssetsPathHandler(ctx)).addPathHandler("/art/${library.accountId}/",WebViewAssetLoader.InternalStoragePathHandler(ctx,library.covers)).build()
        WebView(ctx).apply {
            web=this;setBackgroundColor(android.graphics.Color.rgb(25,25,23))
            settings.javaScriptEnabled=true;settings.domStorageEnabled=true;settings.allowFileAccess=false;settings.allowContentAccess=true
            settings.mixedContentMode=WebSettings.MIXED_CONTENT_NEVER_ALLOW
            webViewClient=object:WebViewClient(){
                override fun shouldInterceptRequest(view:WebView,request:WebResourceRequest)=assets.shouldInterceptRequest(request.url)
                override fun shouldOverrideUrlLoading(view:WebView,request:WebResourceRequest)=request.url.host!="appassets.androidplatform.net"
            }
            webChromeClient=object:WebChromeClient(){
                override fun onJsAlert(v:WebView,u:String,m:String,result:JsResult):Boolean{evaluateJavascript("toast(${JSONObject.quote(m)})",null);result.confirm();return true}
                override fun onJsConfirm(v:WebView,u:String,m:String,result:JsResult):Boolean {
                    android.app.AlertDialog.Builder(ctx).setMessage(m).setPositiveButton("Confirmar"){_,_->result.confirm()}.setNegativeButton("Cancelar"){_,_->result.cancel()}.setOnCancelListener{result.cancel()}.show();return true
                }
                override fun onShowFileChooser(v:WebView,cb:ValueCallback<Array<Uri>>,params:FileChooserParams):Boolean {fileCallback?.onReceiveValue(null);fileCallback=cb;filePick.launch(arrayOf("image/*"));return true}
            }
            val playbackSerial=java.util.concurrent.atomic.AtomicLong()
            addJavascriptInterface(object {
                private var pendingSearch:Job?=null
                @JavascriptInterface fun outputs(){post{if(!library.closed&&!audioRoutes.openSystemPicker()){outputError=null;outputChoices=audioRoutes.choices();outputOpen=true}}}
                @JavascriptInterface fun settings(){post{if(!library.closed){accountError=null;settingsOpen=true}}}
                @JavascriptInterface fun back(){post{onBack()}}
                @JavascriptInterface fun permission(){post{permission.launch(if(Build.VERSION.SDK_INT>=33)Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE)}}
                @JavascriptInterface fun folder(){post{folder.launch(null)}}
                @JavascriptInterface fun call(id:String,method:String,args:String) {
                    val requestId=id.toIntOrNull() ?: return
                    if(args.length>8_000_000){post{evaluateJavascript("musicReply($requestId,null,\"Pedido muito grande\")",null)};return}
                    // The WebView bridge receives calls in order. Parse media commands
                    // here so a Default-dispatcher hop cannot reorder next/previous.
                    val mediaArgs=if(method.startsWith("media_"))try {JSONArray(args)}catch(e:Exception){post{evaluateJavascript("musicReply($requestId,null,${JSONObject.quote("Comando de áudio inválido")})",null)};return} else null
                    val replacesPlayback=method in listOf("media_play","media_pause","media_stop")
                    val playbackRequest=if(replacesPlayback)playbackSerial.incrementAndGet() else playbackSerial.get()
                    if(method=="playlist_buscar_preview")pendingSearch?.cancel()
                    val task=scope.launch(Dispatchers.Main.immediate) {
                        try {
                            val a=mediaArgs ?: withContext(Dispatchers.Default){JSONArray(args)}
                            val result=if(method.startsWith("media_")) {
                                val c=controller ?: error("O player está iniciando. Tente novamente.")
                                if(replacesPlayback && playbackRequest!=playbackSerial.get())true else when(method.removePrefix("media_")) {
                                    "play"->{val q=a.getJSONArray(0);val options=a.getJSONObject(2);val items=withContext(Dispatchers.IO){musicItems(q,library)}
                                        require(items.isNotEmpty())
                                        if(playbackRequest==playbackSerial.get()) {
                                            c.setMediaItems(items,a.getInt(1),0);applyOptions(c,options);c.volume=options.optDouble("volume",100.0).toFloat()/100;c.prepare();c.play()
                                            withContext(Dispatchers.IO){if(playbackRequest==playbackSerial.get())library.savePlayer(JSONObject().put("queue",q).put("indice",a.getInt(1)).put("posicao",0))}
                                        };true}
                                    "queue"->{val args=Bundle().apply{putString("queue",a.getJSONArray(0).toString());putString("expected",a.getString(1))};val result=c.sendCustomCommand(androidx.media3.session.SessionCommand(EmilyMusicService.ACTION_QUEUE,Bundle.EMPTY),args);withContext(Dispatchers.IO){result.get(10,java.util.concurrent.TimeUnit.SECONDS).resultCode==androidx.media3.session.SessionResult.RESULT_SUCCESS}}
                                    "resume"->{MusicPlaybackActions.resume(c);true}
                                    "toggle"->{val result=c.sendCustomCommand(androidx.media3.session.SessionCommand(EmilyMusicService.ACTION_TOGGLE,Bundle.EMPTY),Bundle.EMPTY);withContext(Dispatchers.IO){result.get(10,java.util.concurrent.TimeUnit.SECONDS).resultCode==androidx.media3.session.SessionResult.RESULT_SUCCESS}}
                                    "pause"->{c.pause();true}
                                    "stop"->{c.stop();c.clearMediaItems();withContext(Dispatchers.IO){library.savePlayer(JSONObject().put("queue",JSONArray()))};true}
                                    "seek"->{c.seekTo((a.getDouble(0)*1000).toLong());true}
                                    "volume"->{c.volume=(a.getDouble(0)/100).toFloat().coerceIn(0f,1f);true}
                                    "next"->{MusicPlaybackActions.next(c);true}
                                    "prev"->{MusicPlaybackActions.previous(c);true}
                                    "options"->{applyOptions(c,a.getJSONObject(0));true}
                                    else->false
                                }
                            } else if(method=="playlist_buscar_preview")withContext(Dispatchers.IO){
                                EmilyMusicSearch.search(a.getString(0),a.optString(1,"videos")){partial->
                                    val json=partial.toString()
                                    post{if(!library.closed)evaluateJavascript("window.musicProgress?.($requestId,$json)",null)}
                                }
                            } else withContext(Dispatchers.IO){musicCall(method,a,library)}
                            val json=withContext(Dispatchers.IO){JSONArray().put(musicTrackLabels(result)).toString().removePrefix("[").removeSuffix("]")}
                            evaluateJavascript("musicReply($requestId,$json,null)",null)
                        } catch(e:CancellationException){if(method=="playlist_buscar_preview"&&!library.closed)evaluateJavascript("musicReply($requestId,null,\"Busca substituída\")",null);throw e} catch(e:Exception){if(method in listOf("media_options","media_volume")&&controller==null){evaluateJavascript("musicReply($requestId,true,null)",null);return@launch};evaluateJavascript("musicReply($requestId,null,${JSONObject.quote(e.message?:"Não foi possível concluir")})",null)}
                    }
                    if(method=="playlist_buscar_preview")pendingSearch=task
                }
            },"EmilyAndroid")
            loadUrl("https://appassets.androidplatform.net/assets/music/index.html?account=${library.accountId}")
        }
    })
    }
    if(outputOpen)ModalBottomSheet(onDismissRequest={outputOpen=false}) {
        Column(Modifier.fillMaxWidth().padding(24.dp)) {
            Text("Onde você quer ouvir?",style=MaterialTheme.typography.titleLarge)
            Text("Saída atual: ${audioRoutes.currentName()}",Modifier.padding(vertical=12.dp))
            outputChoices.forEach {route->
                OutlinedButton(onClick={runCatching {audioRoutes.select(route.route)}.onSuccess {outputOpen=false}.onFailure {outputError=it.message?:"Não foi possível trocar a saída."}},modifier=Modifier.fillMaxWidth()) {
                    Text((if(route.selected)"✓  " else "")+route.label)
                }
            }
            if(outputChoices.isEmpty())Text("As saídas estão temporariamente indisponíveis. Feche e tente novamente.",Modifier.padding(vertical=12.dp))
            if(outputChoices.size==1)Text("Conecte um fone ou caixa para ver outras saídas disponíveis.",Modifier.padding(vertical=12.dp))
            outputError?.let {Text(it,color=MaterialTheme.colorScheme.error)}
        }
    }
    if(settingsOpen)MusicSettingsSheet(MusicCloud.currentUser()?.email.orEmpty(),accountBusy,accountError,
        onDismiss={settingsOpen=false},onSignOut={
            if(!accountBusy)scope.launch(Dispatchers.Main.immediate) {
                accountBusy=true;accountError=null
                try {MusicCloud.signOut(context);settingsOpen=false}
                catch(e:CancellationException){throw e}
                catch(_:Exception){accountError="Não foi possível sair da conta. Tente novamente."}
                finally {accountBusy=false}
            }
        },onUpdate={val activity=context as? android.app.Activity;if(activity!=null){if(update.ready)MusicUpdater.install(activity) else scope.launch(Dispatchers.Main.immediate){MusicUpdater.check(activity,true)}}},onSources={context.startActivity(Intent(Intent.ACTION_VIEW,Uri.parse("https://github.com/vitor-sh/emily-music-releases")))},update=update,
        onImport={settingsOpen=false;web?.evaluateJavascript("window.MusicImport?.open()",null)})
}

object EmilyMusicNavigation {val requested=kotlinx.coroutines.flow.MutableStateFlow(0)}

private fun applyOptions(c:MediaController,o:JSONObject){c.repeatMode=when(o.optInt("loop",1)){2->Player.REPEAT_MODE_ONE;1->Player.REPEAT_MODE_ALL;else->Player.REPEAT_MODE_OFF};c.shuffleModeEnabled=o.optBoolean("shuffle")}
private suspend fun musicCall(m:String,a:JSONArray,lib:MusicLibrarySession):Any {
    check(!lib.closed && lib.uid==MusicCloud.currentUser()?.uid){"A conta mudou."}
    return when(m){
        "playlist_geral"->lib.library()
        "playlist"->lib.library().let {it.getJSONObject("playlists").getJSONObject(it.getString("ativa")).getJSONArray("musicas")}
        "playlist_selecionar"->lib.selected(a.getString(0))
        "playlist_buscar_preview"->EmilyMusicSearch.search(a.getString(0),a.optString(1,"videos"))

        "music_import_preview"->MusicPlaylistImport.preview(a.getString(0),a.getString(1))
        "music_import_resolve"->lib.resolveImport(a.getString(0),a.getString(1),a.getJSONObject(2))
        "music_import_match"->MusicPlaylistImport.match(a.getString(0),a.getString(1),a.getLong(2))
        "music_import_commit"->lib.importPlaylist(a.getString(0),a.getJSONArray(1),a.getString(2),a.optString(3),a.optJSONArray(4)?:JSONArray(),a.optString(5))
        "music_audio_preparar"->EmilyMusicAudio.prepareVisible((0 until minOf(a.getJSONArray(0).length(),2)).map{a.getJSONArray(0).getString(it)},lib)
        "music_letras_buscar"->EmilyMusicSearch.lyrics(a.getString(0))
        "music_offline_estado"->lib.offline().put("settings",JSONObject().apply {put("revision",lib.settingsRevision());val p=lib.playerState();for(k in listOf("volume","loop","shuffle"))if(p.has(k))put(k,p.get(k))})
        "music_offline_baixar"->JSONObject().put("ok",true).put("enfileiradas",EmilyMusicAudio.download(a.getJSONArray(0)))
        "music_offline_cancelar"->EmilyMusicAudio.cancel(a.getString(0))
        "music_offline_remover"->{val id=a.getString(0);require(id.matches(Regex("[A-Za-z0-9_-]{11}")));java.io.File(lib.folder,"$id.mp3").delete()}
        "player_estado"->lib.playerState()
        "player_salvar_estado"->lib.savePlayer(a.getJSONObject(0))
        "playlist_criar","playlist_fixar","playlist_foto","playlist_renomear","playlist_apagar","playlist_favoritar","music_copiar","music_remover","music_organizar"->lib.mutate(m,a)
        else->error("Operação desconhecida")
    }
}

@UnstableApi
internal fun musicItems(q:JSONArray,library:MusicLibrarySession=EmilyMusicLibrary.session()):List<MediaItem> = (0 until q.length()).map {i->
    val m=musicTrackLabels(q.getJSONObject(i)) as JSONObject;val vid=m.getString("video_id")
    require(vid.matches(Regex("(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})")))
    MediaItem.Builder().setMediaId(vid).setUri("emilymusic://$vid").setCustomCacheKey(vid)
        .setMediaMetadata(MediaMetadata.Builder().setIsPlayable(true).setIsBrowsable(false).setMediaType(MediaMetadata.MEDIA_TYPE_MUSIC).setTitle(m.optString("titulo","Música")).setArtist(m.optString("artist",m.optString("artista")).ifBlank {"Emily Music"})
            .setArtworkUri(MusicCarArtwork.track(library,m))
            .setExtras(Bundle().apply{putString("track",m.toString())}).build()).build()
}

internal fun musicPlaybackTrack(item:MediaItem):JSONObject {
    val track=item.mediaMetadata.extras?.getString("track")?.let {runCatching {JSONObject(it)}.getOrNull()}
        ?.takeIf {it.optString("video_id")==item.mediaId&&it.optString("titulo").isNotBlank()}
    return track ?: JSONObject().put("video_id",item.mediaId).put("titulo",item.mediaMetadata.title?.toString()?:"Música")
        .put("artist",item.mediaMetadata.artist?.toString().orEmpty()).put("thumb",item.mediaMetadata.artworkUri?.toString().orEmpty())
}
