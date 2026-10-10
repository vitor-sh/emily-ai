package com.emily.music

import android.content.ComponentName
import android.content.Intent
import android.os.Bundle
import android.support.v4.media.session.MediaSessionCompat
import androidx.car.app.*
import androidx.car.app.constraints.ConstraintManager
import androidx.car.app.media.MediaPlaybackManager
import androidx.car.app.media.model.MediaPlaybackTemplate
import androidx.car.app.model.*
import androidx.car.app.validation.HostValidator
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.IconCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.session.*
import com.google.common.util.concurrent.ListenableFuture
import kotlinx.coroutines.*

/** Projected UI owns its navigation; playback remains in the existing account service. */
class MusicCarAppService:CarAppService() {
    override fun createHostValidator():HostValidator = HostValidator.Builder(this)
        .addAllowedHosts(androidx.car.app.R.array.hosts_allowlist_sample).build()
    override fun onCreateSession():Session=MusicCarSession()
}

internal class MusicCarSession:Session() {
    internal val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    internal var browser:MediaBrowser?=null
    private var future:ListenableFuture<MediaBrowser>?=null
    internal var ready=false
    internal var connecting=false
    internal var notice=""
    private var removeAccountObserver:(()->Unit)?=null
    private val screens=mutableSetOf<MusicCarScreen>()
    private val listener=object:Player.Listener {
        override fun onEvents(player:Player,events:Player.Events){refresh()}
    }
    init {lifecycle.addObserver(object:DefaultLifecycleObserver {
        override fun onDestroy(owner:LifecycleOwner){removeAccountObserver?.invoke();scope.cancel();browser?.removeListener(listener);future?.let(MediaBrowser::releaseFuture);browser=null;ready=false}
    })}
    override fun onCreateScreen(intent:Intent):Screen {
        val root=MusicCarScreen(carContext,this,"home","Emily Music");root.setMarker("home")
        removeAccountObserver=MusicCloud.observeAccount {
            browser?.removeListener(listener);future?.let(MediaBrowser::releaseFuture);future=null;browser=null;ready=false;connecting=false
            screens.forEach{it.clearAccount()};notice="A conta mudou. Entre no celular e tente novamente.";home();refresh()
        }
        connect()
        if(intent.action=="androidx.car.app.media.action.SHOW_MEDIA_PLAYBACK")ContextCompat.getMainExecutor(carContext).execute{showPlayer()}
        return root
    }
    override fun onNewIntent(intent:Intent){
        super.onNewIntent(intent)
        if(intent.action=="androidx.car.app.media.action.SHOW_MEDIA_PLAYBACK")showPlayer()
    }
    internal fun observe(screen:MusicCarScreen){screens.add(screen)}
    internal fun forget(screen:MusicCarScreen){screens.remove(screen)}
    internal fun refresh(){screens.toList().forEach{it.invalidate()}}
    internal fun connect() {
        if(connecting||ready)return
        if(!MusicCloud.locallyApproved(carContext)){notice="Entre com Google no Emily Music pelo celular. Depois volte aqui.";refresh();return}
        connecting=true;notice="";refresh()
        val pending=MediaBrowser.Builder(carContext,SessionToken(carContext,ComponentName(carContext,EmilyMusicService::class.java)))
            .setListener(object:MediaBrowser.Listener {override fun onDisconnected(controller:MediaController){ready=false;connecting=false;notice="O player desconectou. Tente novamente.";refresh()}}).buildAsync()
        future=pending
        pending.addListener({
            if(!scope.isActive||future!==pending)return@addListener
            try {
                val b=pending.get();browser=b;b.addListener(listener)
                val token=b.sendCustomCommand(SessionCommand(EmilyMusicService.ACTION_TOKEN,Bundle.EMPTY),Bundle.EMPTY)
                token.addListener({
                    if(!scope.isActive||future!==pending)return@addListener
                    try {
                        val platform=token.get().extras.getParcelable<android.media.session.MediaSession.Token>("token") ?: error("Token ausente")
                        val compat=MediaSessionCompat.Token.fromToken(platform) ?: error("Sessão ausente")
                        carContext.getCarService(MediaPlaybackManager::class.java).registerMediaPlaybackToken(compat)
                        ready=true;connecting=false;refresh()
                    }catch(_:Exception){connectionFailed()}
                },ContextCompat.getMainExecutor(carContext))
            }catch(_:Exception){connectionFailed()}
        },ContextCompat.getMainExecutor(carContext))
    }
    private fun connectionFailed(){
        connecting=false;ready=false;notice="Não consegui conectar ao player. Tente novamente."
        browser?.removeListener(listener);future?.let(MediaBrowser::releaseFuture);future=null;browser=null;refresh()
    }
    internal fun home(){carContext.getCarService(ScreenManager::class.java).popToRoot()}
    internal fun open(id:String,title:String){
        val manager=carContext.getCarService(ScreenManager::class.java)
        // Browsing is at most home -> playlists -> tracks -> player -> queue.
        if(manager.stackSize>=5)manager.pop()
        manager.push(MusicCarScreen(carContext,this,id,title))
    }
    internal fun showPlayer(){
        val manager=carContext.getCarService(ScreenManager::class.java)
        if(manager.screenStack.any{it.marker=="player"})manager.popTo("player")
        else {if(manager.stackSize>=5)manager.pop();val screen=MusicCarScreen(carContext,this,"player","Tocando agora");screen.setMarker("player");manager.push(screen)}
    }
    internal fun play(item:MediaItem){
        val b=browser ?: return
        try {
            if(item.mediaMetadata.isBrowsable==true){open(item.mediaId,item.mediaMetadata.title.toString());return}
            b.setMediaItem(MediaItem.Builder().setMediaId(item.mediaId).build());b.prepare();b.play();showPlayer()
        }catch(_:Exception){notice="Não foi possível abrir esta música. Volte à biblioteca e tente novamente.";refresh()}
    }
}

internal class MusicCarScreen(context:CarContext,private val session:MusicCarSession,private val id:String,private val title:String):Screen(context) {
    private var rows:List<MediaItem>?=null
    private var loading=false
    private var message=""
    private var generation=0
    private var offset=0
    private var query=""
    init {
        session.observe(this)
        lifecycle.addObserver(object:DefaultLifecycleObserver {
            override fun onStart(owner:LifecycleOwner){if(id!="home"&&id!="player"&&id!="queue"&&id!="search")load();invalidate()}
            override fun onDestroy(owner:LifecycleOwner){generation++;session.forget(this@MusicCarScreen)}
        })
    }
    private fun icon(resource:Int)=CarIcon.Builder(IconCompat.createWithResource(carContext,resource)).build()
    private fun action(label:String,resource:Int,click:()->Unit)=Action.Builder().setTitle(label).setIcon(icon(resource)).setOnClickListener(click).build()
    private fun iconAction(resource:Int,click:()->Unit)=Action.Builder().setIcon(icon(resource)).setOnClickListener(click).build()
    private fun header(player:Boolean=false)=Header.Builder().setTitle(title)
        .setStartHeaderAction(if(id=="home")Action.APP_ICON else Action.BACK)
        .apply {
            if(id!="home")addEndHeaderAction(action("Início",R.drawable.ic_car_home){session.home()})
            if(player)addEndHeaderAction(action("Fila",R.drawable.ic_car_queue){session.open("queue","Fila")})
            else addEndHeaderAction(action("Player",R.drawable.ic_car_play){session.showPlayer()})
        }.build()
    internal fun clearAccount(){generation++;rows=null;loading=false;offset=0;query=""}
    private fun load(search:String?=null) {
        if(loading)return
        val run=++generation;loading=true;message="";invalidate()
        session.scope.launch {
            try {
                val loaded=withContext(Dispatchers.IO){
                    EmilyMusicLibrary.init(carContext)
                    val catalog=MusicCarCatalog(EmilyMusicLibrary.session())
                    if(search!=null)catalog.search(search) else catalog.children(id)
                }
                if(run!=generation)return@launch
                rows=loaded;offset=0
            }catch(e:CancellationException){throw e}
            catch(_:Exception){if(run==generation)message="Não foi possível carregar. Volte e tente novamente."}
            finally{if(run==generation){loading=false;invalidate()}}
        }
    }
    private fun row(title:String,subtitle:String="",click:(()->Unit)?=null)=Row.Builder().setTitle(title).apply {
        if(subtitle.isNotBlank())addText(subtitle)
        if(click!=null)setOnClickListener(click)
    }.build()
    private fun items(source:List<MediaItem>,queue:Boolean=false):ItemList {
        val limit=carContext.getCarService(ConstraintManager::class.java).getContentLimit(ConstraintManager.CONTENT_LIMIT_TYPE_LIST).coerceAtLeast(2).coerceAtMost(30)
        val count=(limit-1).coerceAtLeast(1)
        offset=offset.coerceIn(0,((source.size-1).coerceAtLeast(0)/count)*count)
        return ItemList.Builder().apply {
            source.drop(offset).take(count).forEach {m->addItem(row(m.mediaMetadata.title?.toString()?:"Música",m.mediaMetadata.artist?.toString().orEmpty()) {
                if(queue){val b=session.browser ?: return@row;val n=(0 until b.mediaItemCount).firstOrNull{b.getMediaItemAt(it).mediaId==m.mediaId};if(n!=null){b.seekTo(n,0);b.prepare();b.play();session.showPlayer()}}
                else session.play(m)
            })}
            if(source.size>count)addItem(row(if(offset+count<source.size)"Mais músicas" else "Voltar às primeiras", "${offset+1}–${minOf(offset+count,source.size)} de ${source.size}") {offset=if(offset+count<source.size)offset+count else 0;invalidate()})
            if(source.isEmpty())addItem(row("Nenhuma música disponível", "Sem internet, aparecem somente as músicas deste celular."))
        }.build()
    }
    override fun onGetTemplate():Template {
        if(!session.ready) {
            if(!session.connecting&&session.notice.isBlank())session.connect()
            return MessageTemplate.Builder(session.notice.ifBlank{"Conectando ao player…"}).setHeader(header()).setLoading(session.connecting)
                .apply{if(!session.connecting)addAction(Action.Builder().setTitle("Tentar novamente").setOnClickListener{session.connect()}.build())}.build()
        }
        if(!MusicCloud.locallyApproved(carContext))return MessageTemplate.Builder("Entre com Google novamente pelo celular.").setHeader(header()).build()
        if(id=="player") {
            val b=session.browser!!
            if(b.playerError!=null)return MessageTemplate.Builder(musicPlaybackErrorMessage(b.playerError!!)).setHeader(header(true))
                .addAction(Action.Builder().setTitle("Tentar novamente").setOnClickListener{b.prepare();b.play();invalidate()}.build())
                .addAction(Action.Builder().setTitle("Biblioteca").setOnClickListener{session.home()}.build()).build()
            if(b.mediaItemCount==0)return MessageTemplate.Builder("Escolha uma música na biblioteca.").setHeader(header(true))
                .addAction(Action.Builder().setTitle("Biblioteca").setOnClickListener{session.home()}.build()).build()
            return MediaPlaybackTemplate.Builder().setHeader(header(true)).build()
        }
        if(id=="search") {
            val strip=ActionStrip.Builder().addAction(action("Início",R.drawable.ic_car_home){session.home()}).addAction(iconAction(R.drawable.ic_car_play){session.showPlayer()}).build()
            return SearchTemplate.Builder(object:SearchTemplate.SearchCallback {
                override fun onSearchSubmitted(text:String){query=text.trim().take(300);generation++;loading=false;rows=null;if(query.isNotBlank())load(query)else invalidate()}
            }).setHeaderAction(Action.BACK).setActionStrip(strip).setSearchHint("Música ou artista na biblioteca").setInitialSearchText(query).setLoading(loading)
                .apply {if(!loading)setItemList(if(message.isNotBlank())ItemList.Builder().addItem(row(message)).build() else items(rows?:emptyList()))}.build()
        }
        val list=when(id) {
            "home"->ItemList.Builder()
                .addItem(row("Tocando agora",session.browser?.currentMediaItem?.mediaMetadata?.title?.toString().orEmpty()){session.showPlayer()})
                .addItem(row("Playlists"){session.open(MusicCarCatalog.PLAYLISTS,"Playlists")})
                .addItem(row("Curtidas"){session.open(MusicCarCatalog.FAVORITES,"Curtidas")})
                .addItem(row("Baixadas"){session.open(MusicCarCatalog.DOWNLOADS,"Baixadas")})
                .addItem(row("Músicas locais"){session.open(MusicCarCatalog.LOCALS,"Músicas locais")})
                .addItem(row("Buscar na biblioteca"){session.open("search","Buscar")}).build()
            "queue"->{val b=session.browser!!;items((0 until b.mediaItemCount).map{b.getMediaItemAt(it)},true)}
            else->if(message.isNotBlank())ItemList.Builder().addItem(row(message)).build() else items(rows?:emptyList())
        }
        return ListTemplate.Builder().setHeader(header()).setLoading(loading).apply {if(!loading)setSingleList(list)}.build()
    }
}
