package com.emily.music

import android.content.Context
import android.content.ContentUris
import android.database.ContentObserver
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.util.AtomicFile
import androidx.documentfile.provider.DocumentFile
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/** Biblioteca persistida e sincronizada; caminhos e reprodução são sempre locais. */
internal class MusicLibrarySession(context:Context,val uid:String,private val syncEnabled:Boolean=true) {
    private val LOCALS = EmilyMusicLibrary.LOCALS
    val accountId=MusicAccountPaths.key(uid)
    @Volatile var closed=false
        private set
    private var observer:ContentObserver?=null
    private val root=File(context.filesDir,"accounts/$accountId").apply {mkdirs()}
    private lateinit var app: Context
    private lateinit var disk: AtomicFile
    private lateinit var playerDisk: MusicPlayerStore
    private var doc = JSONObject()
    val scope = CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private val syncMutex = Mutex()
    private val syncedIds=mutableMapOf<String,String>()
    private var cloudRevision=-1L
    private var syncScheduled:Job?=null
    private val scanMutex = Mutex()
    val jobs = ConcurrentHashMap<String, JSONObject>()
    @Volatile var notice = ""
    @Volatile var playbackNotice = ""
    @Volatile private var started = false
    private val playlistArt = ConcurrentHashMap<String, String>()
    val covers: File get() = File(root,"covers").apply {mkdirs()}
    val folder: File get() = File(app.getExternalFilesDir(android.os.Environment.DIRECTORY_MUSIC) ?: app.filesDir, "Emily Music/$accountId").apply { mkdirs() }
    init {initialize(context)}
    fun close() {
        closed=true;scope.cancel()
        observer?.let {runCatching {app.contentResolver.unregisterContentObserver(it)}}
        observer=null;playlistArt.clear()
    }
    private fun ensureOpen() {check(!closed){"A sessão Music foi encerrada"}}
    private fun initialize(context: Context) {
        if (started) return
        app=context.applicationContext;disk=AtomicFile(File(root,"library.json"))
        doc=runCatching { JSONObject(disk.openRead().bufferedReader().use { it.readText() }) }.getOrElse { JSONObject() }
        for (k in listOf("campos","sources","downloaded","scanCache","uploaded","player")) if (!doc.has(k)) doc.put(k,JSONObject())
        playerDisk=MusicPlayerStore(File(root,"player.json"))
        doc.put("player",playerDisk.load(doc.getJSONObject("player")))
        if (!fields().has(key("playlist","default"))) fields().put(key("playlist","default"),entry(JSONObject().put("foto",""),1))
        observer=object:ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange:Boolean) {if(!closed)scope.launch {scan()}}
        }
        runCatching {app.contentResolver.registerContentObserver(MediaStore.Audio.Media.EXTERNAL_CONTENT_URI,true,observer!!)}
        started=true
        scope.launch {scan()}
        if(syncEnabled)scope.launch {while(isActive){sync();delay(15000)}}
    }
    private fun key(vararg p:String)=JSONArray(p.toList()).toString()
    private fun fields()=doc.getJSONObject("campos")
    private fun entry(value:Any?,ts:Long=System.currentTimeMillis())=JSONObject().put("valor",value?:JSONObject.NULL).put("quando",ts).put("id",UUID.randomUUID().toString())
    private fun mark(k:String,v:Any?) { fields().put(k,entry(v,maxOf(System.currentTimeMillis(),fields().optJSONObject(k)?.optLong("quando")?.plus(1)?:0)));if(syncEnabled && started && !closed){syncScheduled?.cancel();syncScheduled=scope.launch {delay(800);sync()}} }
    @Synchronized private fun save() {
        val out=disk.startWrite()
        try { out.write(JSONObject(doc.toString()).apply { remove("player") }.toString().toByteArray());disk.finishWrite(out) } catch(e:Exception) {disk.failWrite(out);throw e}
    }
    fun online():Boolean {
        val cm=app.getSystemService(ConnectivityManager::class.java)
        val cap=cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return cap.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }
    private fun value(k:String):Any? = fields().optJSONObject(k)?.opt("valor")?.takeUnless {it==JSONObject.NULL}
    @Synchronized fun library():JSONObject {
        ensureOpen()
        val playlists=JSONObject();val favorites=JSONObject()
        fields().keys().forEach { k -> val p=JSONArray(k); val v=value(k)
            if (p.optString(0)=="playlist" && v is JSONObject) playlists.put(p.getString(1),JSONObject().put("foto",playlistCover(v.optString("foto"))).put("pending",v.optJSONArray("pending")?:JSONArray()).put("youtube_id",v.optString("youtube_id")).put("pinned",value(key("pin",p.getString(1)))==true).put("musicas",JSONArray()))
            if (p.optString(0)=="favorite" && v==true) favorites.put(p.getString(1),true)
        }
        fields().keys().forEach {k -> val p=JSONArray(k);val v=value(k)
            if (p.optString(0)=="track" && v is JSONObject) playlists.optJSONObject(p.getString(1))?.getJSONArray("musicas")?.put(v)
        }
        playlists.keys().forEach { n -> val p=playlists.getJSONObject(n);val arr=p.getJSONArray("musicas");val order=value(key("order",n)) as? JSONArray
            val rank=mutableMapOf<String,Int>();if(order!=null)for(i in 0 until order.length())rank[order.getString(i)]=i
            val items=(0 until arr.length()).map {arr.getJSONObject(it)}.sortedWith(compareBy({rank[it.getString("video_id")]?:Int.MAX_VALUE},{it.optDouble("adicionada")},{it.getString("video_id")}))
            p.put("musicas",JSONArray(items)).put("quantidade",items.size)
        }
        val local=doc.optJSONArray("locals") ?: JSONArray()
        playlists.put(LOCALS,JSONObject().put("foto","").put("musicas",local).put("quantidade",local.length()).put("readonly",true))
        val active=doc.optString("active","default").takeIf {playlists.has(it)}?:"default"
        return JSONObject().put("playlists",playlists).put("favoritos",favorites).put("ativa",active).put("listening",listeningSummary())
    }
    /** Cada aparelho publica seu próprio contador; o merge não perde audições simultâneas. */
    @Synchronized fun recordListening(track:JSONObject,whenPlayed:Long=System.currentTimeMillis()) {
        ensureOpen()
        val id=track.optString("video_id");require(id.matches(Regex("(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})")))
        val device=doc.optString("listeningDevice").ifEmpty {UUID.randomUUID().toString().also {doc.put("listeningDevice",it)}}
        val k=key("listening",device)
        val old=(value(k) as? JSONArray)?:JSONArray()
        val rows=(0 until old.length()).map {JSONObject(old.getJSONObject(it).toString())}.toMutableList()
        val previous=rows.firstOrNull {it.optString("video_id")==id};rows.removeAll {it.optString("video_id")==id}
        val entry=JSONObject().put("video_id",id).put("titulo",track.optString("titulo","Música").take(300))
            .put("artist",track.optString("artist",track.optString("artista")).take(180))
            .put("thumb",track.optString("thumb").takeIf {it.startsWith("https://i.ytimg.com/")}?:"")
            .put("count",minOf(1000000000L,(previous?.optLong("count")?:0)+1)).put("last",whenPlayed)
        rows.add(entry);mark(k,JSONArray(rows.sortedByDescending {it.optLong("last")}.take(200)));save()
    }
    private fun listeningSummary():JSONArray {
        val merged=linkedMapOf<String,JSONObject>()
        fields().keys().forEach {k->if(JSONArray(k).optString(0)=="listening") {
            val rows=value(k) as? JSONArray ?: return@forEach
            for(i in 0 until rows.length()) {
                val row=rows.getJSONObject(i);val id=row.optString("video_id");val old=merged[id]
                val count=(old?.optLong("count")?:0)+row.optLong("count")
                val latest=if(old==null||row.optLong("last")>old.optLong("last"))JSONObject(row.toString()) else old
                latest.put("count",count);merged[id]=latest
            }
        }}
        return JSONArray(merged.values.sortedByDescending {it.optLong("last")}.take(200))
    }
    // Capas base64 permanecem nos dados sincronizados, mas a WebView recebe
    // somente um endereço local. Evita megabytes de JS a cada atualização.
    private fun playlistCover(photo:String):String {
        if (!photo.startsWith("data:image/")) return photo
        return playlistArt.getOrPut(photo) {
            runCatching {
                if(playlistArt.size>=32)playlistArt.clear()
                val ext=when {photo.startsWith("data:image/png")->".png";photo.startsWith("data:image/webp")->".webp";else->".jpg"}
                val name = "playlist-" + MessageDigest.getInstance("SHA-256")
                    .digest(photo.toByteArray()).joinToString(""){"%02x".format(it)} + ext
                val target = File(covers,name)
                if (!target.exists()) target.writeBytes(android.util.Base64.decode(photo.substringAfter(','),android.util.Base64.DEFAULT))
                "https://appassets.androidplatform.net/art/$accountId/$name"
            }.getOrDefault("")
        }
    }
    @Synchronized fun selected(name:String):Boolean {if(!library().getJSONObject("playlists").has(name))return false;if(doc.optString("active")!=name){doc.put("active",name);save()};return true}
    @Synchronized fun importPlaylist(name:String,tracks:JSONArray,operation:String,photo:String="",pending:JSONArray=JSONArray(),youtubeId:String=""):JSONObject {
        ensureOpen();check(uid==MusicCloud.currentUser()?.uid){"A conta mudou."}
        require(operation.matches(Regex("[A-Za-z0-9_-]{8,80}")))
        val receipts=doc.optJSONObject("imports")?:JSONObject()
        receipts.optJSONObject(operation)?.let {if(library().getJSONObject("playlists").has(it.optString("name")))return it}
        require(youtubeId.isEmpty()||youtubeId.matches(Regex("[A-Za-z0-9_-]{10,100}")))
        if(youtubeId.isNotEmpty()){val existing=library().getJSONObject("playlists");existing.keys().forEach {n->if(existing.getJSONObject(n).optString("youtube_id")==youtubeId)return JSONObject().put("ok",true).put("name",n).put("existing",true)}}
        val original=name.trim();val lists=library().getJSONObject("playlists")
        require(original.isNotEmpty()&&original.length<=100&&original!=LOCALS){"Nome inválido."}
        var n=original;var suffix=2
        while(lists.has(n)){val tail=" ($suffix)";n=original.take(100-tail.length)+tail;suffix++}
        require(lists.length()<21){"Limite de playlists atingido."}
        require(tracks.length()+pending.length() in 1..200){"A playlist deve ter de 1 a 200 músicas."}
        require(photo.isEmpty()||MusicPlaylistImport.validCover(photo)){"Capa inválida."}
        val safePending=validatePending(pending)
        val prepared=linkedMapOf<String,JSONObject>()
        for(i in 0 until tracks.length()) {
            val item=musicTrackLabels(tracks.getJSONObject(i)) as JSONObject;val id=item.getString("video_id")
            require(id.matches(Regex("[A-Za-z0-9_-]{11}"))&&item.optString("titulo").isNotBlank())
            prepared[id]=JSONObject().put("video_id",id).put("titulo",item.getString("titulo").take(300))
                .put("titulo_original",item.optString("titulo_original").take(1000)).put("title_source",item.optString("title_source").take(30))
                .put("artist",item.optString("artist",item.optString("artista")).take(180)).put("thumb","https://i.ytimg.com/vi/$id/mqdefault.jpg").put("adicionada",System.currentTimeMillis()/1000.0+i*.001)
        }
        val before=JSONObject(doc.toString())
        try {
            mark(key("playlist",n),JSONObject().put("foto",photo).put("pending",safePending).put("youtube_id",youtubeId));mark(key("pin",n),false)
            prepared.forEach {(id,item)->mark(key("track",n,id),item)}
            mark(key("order",n),JSONArray(prepared.keys.toList()))
            val result=JSONObject().put("ok",true).put("name",n).put("added",prepared.size).put("duplicates",tracks.length()-prepared.size).put("pending",safePending.length())
            if(receipts.length()>=20)receipts.remove(receipts.keys().next())
            receipts.put(operation,result);doc.put("imports",receipts);save();return result
        } catch(e:Exception){doc=before;throw e}
    }
    private fun validatePending(pending:JSONArray):JSONArray {
        require(pending.length()<=100)
        val result=JSONArray();val ids=mutableSetOf<String>()
        for(i in 0 until pending.length()) {
            val p=pending.getJSONObject(i);val id=p.getString("spotify_id")
            require(id.matches(Regex("[A-Za-z0-9]{22}"))&&ids.add(id))
            val title=p.getString("title");val artists=p.getString("artists");val duration=p.getLong("duration")
            require(title.isNotBlank()&&title.length<=300&&artists.isNotBlank()&&artists.length<=500&&duration in 1..86400)
            result.put(JSONObject().put("spotify_id",id).put("title",title).put("artists",artists).put("duration",duration))
        }
        return result
    }
    @Synchronized fun resolveImport(name:String,spotifyId:String,track:JSONObject):JSONObject {
        ensureOpen();check(uid==MusicCloud.currentUser()?.uid){"A conta mudou."}
        val metadata=value(key("playlist",name)) as? JSONObject ?: error("A playlist não existe mais.")
        val pending=metadata.optJSONArray("pending")?:JSONArray()
        // A repeated acknowledgement cannot add a second copy or consume another pending item.
        if((0 until pending.length()).none {pending.getJSONObject(it).optString("spotify_id")==spotifyId})return JSONObject().put("ok",true)
        val before=JSONObject(doc.toString())
        try {
            check(mutate("music_copiar",JSONArray().put(name).put(track))==true){"Não foi possível adicionar a música."}
            val remaining=JSONArray((0 until pending.length()).map{pending.getJSONObject(it)}.filter{it.getString("spotify_id")!=spotifyId})
            mark(key("playlist",name),JSONObject(metadata.toString()).put("pending",remaining));save()
            return JSONObject().put("ok",true)
        }catch(e:Exception){doc=before;save();throw e}
    }
    @Synchronized fun mutate(method:String,args:JSONArray):Any {
        ensureOpen()
        val lib=library();val lists=lib.getJSONObject("playlists")
        fun exists(n:String)=n!=LOCALS && lists.has(n)
        when(method) {
            "playlist_criar" -> {val n=args.getString(0).trim();if(n.isEmpty()||n.length>100||n==LOCALS||lists.has(n)||lists.length()>=21)return JSONObject().put("erro","Nome já usado ou limite de playlists")
                mark(key("playlist",n),JSONObject().put("foto",args.optString(1)));mark(key("pin",n),false);selected(n);save();return JSONObject().put("ok",true)}
            "playlist_fixar" -> {val n=args.getString(0);if(!exists(n))return false
                mark(key("pin",n),args.getBoolean(1));save();return true}
            "playlist_foto" -> {val n=args.getString(0);if(!exists(n))return JSONObject().put("ok",false);val requestedPhoto=args.optString(1)
                val oldPhoto=(value(key("playlist",n)) as? JSONObject)?.optString("foto")?:""
                val photo=if(requestedPhoto.startsWith("https://appassets.androidplatform.net/art/")&&requestedPhoto==playlistCover(oldPhoto))oldPhoto else requestedPhoto
                val metadata=JSONObject(((value(key("playlist",n)) as? JSONObject)?:JSONObject()).toString()).put("foto",photo)
                mark(key("playlist",n),metadata);save();return JSONObject().put("ok",true)}
            "playlist_renomear" -> {val old=args.getString(0);val n=args.getString(1).trim();if(!exists(old)||old=="default"||n.isBlank()||n==LOCALS||lists.has(n))return JSONObject().put("ok",false)
                mark(key("playlist",n),value(key("playlist",old)));mark(key("playlist",old),null)
                mark(key("pin",n),value(key("pin",old)));mark(key("pin",old),null)
                val tracks=lists.getJSONObject(old).getJSONArray("musicas");for(i in 0 until tracks.length()){val m=tracks.getJSONObject(i);mark(key("track",n,m.getString("video_id")),m);mark(key("track",old,m.getString("video_id")),null)}
                mark(key("order",n),value(key("order",old)));doc.put("active",n);save();return JSONObject().put("ok",true)}
            "playlist_apagar" -> {val n=args.getString(0);if(!exists(n)||n=="default")return false
                mark(key("playlist",n),null);mark(key("pin",n),null);fields().keys().asSequence().toList().forEach {k->val p=JSONArray(k);if(p.optString(0)=="track"&&p.optString(1)==n)mark(k,null)};save();return true}
            "music_copiar" -> {val n=args.getString(0);val item=args.getJSONObject(1);val id=item.getString("video_id");if(!exists(n))return false
                require(id.matches(Regex("(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})"))&&item.optString("titulo").isNotBlank())
                if(value(key("track",n,id))==null&&lists.getJSONObject(n).getJSONArray("musicas").length()>=200)return false
                if(id.startsWith("local_"))ensureLocalCopy(id)
                if(value(key("track",n,id))==null)mark(key("track",n,id),JSONObject()
                    .put("video_id",id).put("titulo",item.getString("titulo").take(300))
                    .put("thumb",item.optString("thumb").take(1000).takeUnless {it.contains("appassets.androidplatform.net")}?:"")
                    .put("titulo_original",item.optString("titulo_original").take(1000)).put("title_source",item.optString("title_source").take(30))
                .put("artist",item.optString("artist",item.optString("artista")).take(180))
                    .put("local",id.startsWith("local_")).put("adicionada",System.currentTimeMillis()/1000.0))
                save();return true}
            "playlist_favoritar" -> {val id=args.getString(0);val fav=args.getBoolean(1)
                if(fav&&id.startsWith("local_"))ensureLocalCopy(id)
                if(fav&&id.startsWith("local_")&&value(key("track","default",id))==null){val local=doc.optJSONArray("locals")?:JSONArray();for(i in 0 until local.length()){val m=local.getJSONObject(i);if(m.getString("video_id")==id)mark(key("track","default",id),JSONObject(m.toString()).apply {remove("uri");remove("origem")})}}
                mark(key("favorite",id),fav);save();return true}
            "music_remover" -> {val n=args.getString(0);if(!exists(n))return false;mark(key("track",n,args.getString(1)),null);save();return true}
            "music_organizar" -> {val n=args.getString(0);if(!exists(n))return false;val ids=args.getJSONArray(1);val old=lists.getJSONObject(n).getJSONArray("musicas");val a=(0 until ids.length()).map {ids.getString(it)};val b=(0 until old.length()).map {old.getJSONObject(it).getString("video_id")};if(a.size!=b.size||a.toSet()!=b.toSet())return false;mark(key("order",n),ids);save();return true}
        }
        return false
    }
    /** Importar/curtir congela a cópia antes de publicar os dados da faixa. */
    private fun ensureLocalCopy(id:String) {
        require(id.matches(Regex("local_[a-f0-9]{64}")))
        val dest=File(folder,"$id.mp3");if(dest.isFile&&dest.length()>0)return
        val uri=localUri(id)?:error("Arquivo local indisponível. Atualize a biblioteca.")
        val temp=File(folder,".$id.import")
        try {
            val hash=MessageDigest.getInstance("SHA-256");var size=0L
            require(folder.usableSpace>100L*1024*1024){"Espaço insuficiente para importar a música"}
            app.contentResolver.openInputStream(uri)!!.use {input->temp.outputStream().use {output->
                val b=ByteArray(65536);while(true){val n=input.read(b);if(n<0)break;size+=n
                    require(size<=128L*1024*1024){"Músicas locais compartilhadas devem ter até 128 MB"}
                    hash.update(b,0,n);output.write(b,0,n)
                }
            }}
            check(hash.digest().joinToString(""){"%02x".format(it)}==id.removePrefix("local_")){"O arquivo mudou. Atualize a biblioteca e tente novamente."}
            check(temp.renameTo(dest))
        } finally {temp.delete()}
    }
    @Synchronized fun playerState():JSONObject {val p=JSONObject(doc.getJSONObject("player").toString());for(k in listOf("volume","loop","shuffle"))value(key("setting",k))?.let {p.put(k,it)};return p}
    @Synchronized fun settingsRevision():String=listOf("loop","shuffle").joinToString(":"){fields().optJSONObject(key("setting",it))?.optString("id")?:""}
    @Synchronized fun savePlayer(p:JSONObject):Boolean {
        if(closed)return false
        val current=doc.getJSONObject("player")
        val merged=JSONObject(current.toString())
        var changed=false
        p.keys().forEach {k->val v=p.get(k);if(current.opt(k)?.toString()!=v.toString()){merged.put(k,v);changed=true}}
        if(changed){playerDisk.write(merged);doc.put("player",merged)}
        val changedSettings=p.keys().asSequence().filter {it in listOf("volume","loop","shuffle") && value(key("setting",it))!=p.get(it)}.toList()
        if(changedSettings.isNotEmpty()){
            val before=JSONObject(fields().toString())
            changedSettings.forEach {mark(key("setting",it),p.get(it))}
            try {save()}catch(e:Exception){doc.put("campos",before);throw e}
        }
        return true
    }
    @Synchronized fun localUri(id:String):Uri? {
        ensureOpen()
        require(id.matches(Regex("[A-Za-z0-9_-]{11}|local_[a-f0-9]{64}"))){"Identificador de música inválido"}
        val f=File(folder,"$id.mp3");if(f.isFile&&f.length()>0)return Uri.fromFile(f)
        return doc.getJSONObject("sources").optString(id).takeIf {it.isNotEmpty()}?.let {Uri.parse(it)}
    }
    fun offline():JSONObject {
        val tracks=JSONObject();val sources=synchronized(this){JSONObject(doc.getJSONObject("sources").toString())};sources.keys().forEach { id -> if(localUri(id)!=null)tracks.put(id,JSONObject().put("estado","pronto").put("local",true).put("thumb",artUrl(id))) }
        folder.listFiles()?.filter {it.extension=="mp3"&&!it.name.startsWith(".")}?.forEach {f->tracks.put(f.nameWithoutExtension,JSONObject().put("estado","pronto").put("local",f.name.startsWith("local_")).put("thumb",artUrl(f.nameWithoutExtension)))}
        EmilyMusicDownload.states(accountId).forEach {(id,j)->if(!tracks.has(id))tracks.put(id,j)}
        return JSONObject().put("faixas",tracks).put("online",online()).put("pasta",folder.absolutePath).put("aviso",playbackNotice.ifBlank {notice})
    }
    suspend fun scan() {
        if(closed)return
        if (!scanMutex.tryLock()) return
        try { scanFiles() } finally { scanMutex.unlock() }
    }
    private fun scanFiles() {
        val tracks=JSONArray();val sources=JSONObject();val volumes=if(Build.VERSION.SDK_INT>=29)MediaStore.getExternalVolumeNames(app) else setOf("external")
        for(volume in volumes)runCatching {
            val base=if(Build.VERSION.SDK_INT>=29)MediaStore.Audio.Media.getContentUri(volume) else MediaStore.Audio.Media.EXTERNAL_CONTENT_URI
            app.contentResolver.query(base,arrayOf("_id","title","_display_name","mime_type","_size","date_modified"),null,null,null)?.use {c->
                while(c.moveToNext()) {val name=c.getString(2)?:"";if(!name.endsWith(".mp3",true)&&c.getString(3)!="audio/mpeg")continue
                    val uri=ContentUris.withAppendedId(base,c.getLong(0));indexFile(uri,name,c.getString(1),c.getLong(4),c.getLong(5),tracks,sources)
                }
            }
        }
        val folders=synchronized(this){doc.optJSONArray("folders")?:JSONArray()}
        for(i in 0 until folders.length())runCatching {DocumentFile.fromTreeUri(app,Uri.parse(folders.getString(i)))?.let { walk(it,tracks,sources) }}
        synchronized(this){
            if(closed)return
            if (doc.optJSONArray("locals")?.toString()!=tracks.toString() || doc.getJSONObject("sources").toString()!=sources.toString()) {
                doc.put("locals",tracks).put("sources",sources);save()
            }
        }
    }
    private fun walk(dir:DocumentFile,tracks:JSONArray,sources:JSONObject,depth:Int=0){if(depth>12)return;dir.listFiles().forEach {if(it.isDirectory)walk(it,tracks,sources,depth+1) else if(it.name?.endsWith(".mp3",true)==true)indexFile(it.uri,it.name?:"Música local",null,it.length(),it.lastModified(),tracks,sources)}}
    private fun indexFile(uri:Uri,name:String,title:String?,size:Long,modified:Long,tracks:JSONArray,sources:JSONObject){
        if(size<=0)return
        runCatching {
            val cacheKey="$uri:$size:$modified";var id=synchronized(this){doc.getJSONObject("scanCache").optString(cacheKey)}
            if(id.isEmpty()){val hash=MessageDigest.getInstance("SHA-256");app.contentResolver.openInputStream(uri)!!.use {input->val buf=ByteArray(65536);while(true){val n=input.read(buf);if(n<0)break;hash.update(buf,0,n)}};id="local_"+hash.digest().joinToString(""){"%02x".format(it)};synchronized(this){doc.getJSONObject("scanCache").put(cacheKey,id)}}
            if(sources.has(id))return
            val cover=File(covers,"$id.jpg");val noart=File(covers,"$id.noart")
            if(!cover.exists()&&!noart.exists())runCatching {
                val retriever=android.media.MediaMetadataRetriever()
                try {retriever.setDataSource(app,uri);val art=retriever.embeddedPicture
                    if(art!=null&&art.size<10*1024*1024){val options=android.graphics.BitmapFactory.Options().apply {inJustDecodeBounds=true}
                        android.graphics.BitmapFactory.decodeByteArray(art,0,art.size,options)
                        options.inSampleSize=1
                        while(options.outWidth/options.inSampleSize>512||options.outHeight/options.inSampleSize>512)options.inSampleSize*=2
                        options.inJustDecodeBounds=false;val bitmap=android.graphics.BitmapFactory.decodeByteArray(art,0,art.size,options);if(bitmap!=null){cover.outputStream().use{bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,80,it)};bitmap.recycle()}}
                    else noart.createNewFile()
                } finally {retriever.release()}
            }
            sources.put(id,uri.toString());tracks.put(JSONObject().put("video_id",id).put("titulo",(title?.takeIf {it.isNotBlank()}?:name.removeSuffix(".mp3")).take(120)).put("thumb","").put("adicionada",modified.toDouble()).put("local",true))
        }
    }
    fun addFolder(uri:Uri){synchronized(this){ensureOpen();val a=doc.optJSONArray("folders")?:JSONArray();if((0 until a.length()).none {a.getString(it)==uri.toString()})a.put(uri.toString());doc.put("folders",a);save()};scope.launch {scan()}}
    suspend fun sync() {
        if(closed || !syncMutex.tryLock())return
        try {
            if(!online()){notice="Offline • alterações salvas no aparelho.";return}
            val outgoing=synchronized(this){
                ensureOpen();JSONObject().also {delta->fields().keys().forEach {k->val entry=fields().getJSONObject(k);if(syncedIds[k]!=entry.optString("id"))delta.put(k,JSONObject(entry.toString()))}}
            }
            // Cloud covers are thumbnails; the original full-quality image stays on this device.
            outgoing.keys().forEach {k->
                if(JSONArray(k).optString(0)=="playlist") {
                    val value=outgoing.getJSONObject(k).optJSONObject("valor")
                    val photo=value?.optString("foto")?:""
                    if(photo.startsWith("data:image/") && photo.length>80000) {
                        val bytes=android.util.Base64.decode(photo.substringAfter(','),android.util.Base64.DEFAULT)
                        val bounds=android.graphics.BitmapFactory.Options().apply{inJustDecodeBounds=true}
                        android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,bounds)
                        var sample=1;while(maxOf(bounds.outWidth,bounds.outHeight)/sample>512)sample*=2
                        val bitmap=android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,android.graphics.BitmapFactory.Options().apply{inSampleSize=sample}) ?: error("Capa inválida")
                        try {val output=java.io.ByteArrayOutputStream();bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,80,output);value!!.put("foto","data:image/jpeg;base64,"+android.util.Base64.encodeToString(output.toByteArray(),android.util.Base64.NO_WRAP))}finally{bitmap.recycle()}
                    }
                }
            }
            val response=MusicCloud.syncLibrary(uid,outgoing,cloudRevision)
            val remote=response.getJSONObject("fields")
            synchronized(this) {
                ensureOpen()
                var changed=false
                remote.keys().forEach {k->
                    val next=remote.getJSONObject(k);val old=fields().optJSONObject(k)
                    if(old==null || next.getLong("quando")>old.optLong("quando") || (next.getLong("quando")==old.optLong("quando") && next.getString("id")>old.optString("id"))){fields().put(k,next);changed=true}
                }
                if(changed)save()
                outgoing.keys().forEach {k->syncedIds[k]=outgoing.getJSONObject(k).optString("id")}
                remote.keys().forEach {k->syncedIds[k]=remote.getJSONObject(k).optString("id")}
                cloudRevision=response.getLong("revision")
            }
            notice="Biblioteca sincronizada com sua conta."
        }catch(e:CancellationException){throw e}
        catch(e:Exception){if(!closed)notice=e.message?:"Sincronização pendente. Alterações salvas no aparelho."}
        finally {syncMutex.unlock()}
    }
    private fun artUrl(id:String)=if(File(covers,"$id.jpg").isFile)"https://appassets.androidplatform.net/art/$accountId/$id.jpg" else ""
    fun context()=app
}
