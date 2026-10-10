package com.emily.music

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.flow.MutableStateFlow
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

internal data class MusicUpdateState(val message:String="",val progress:Float?=null,val ready:Boolean=false,val busy:Boolean=false)

/** Independent public release metadata; never sends Firebase or personal credentials to APK hosts. */
internal object MusicUpdater {
    val state=MutableStateFlow(MusicUpdateState())
    private val lock=Mutex()
    private val http=OkHttpClient.Builder().callTimeout(3,TimeUnit.MINUTES).connectTimeout(10,TimeUnit.SECONDS).readTimeout(30,TimeUnit.SECONDS).followRedirects(false).build()
    private fun target(activity:Context)=File(activity.cacheDir,"updates/music-update.apk")
    suspend fun check(activity:Context,manual:Boolean=false)=lock.withLock {
        if(state.value.ready)return@withLock
        if(!manual) {
            val network=activity.getSystemService(android.net.ConnectivityManager::class.java)
            val capabilities=network?.getNetworkCapabilities(network.activeNetwork)
            if(capabilities?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)!=true || !capabilities.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_NOT_METERED))return@withLock
        }
        state.value=MusicUpdateState(if(manual)"Verificando atualização…" else "",busy=true)
        try {
            val base=BuildConfig.MUSIC_CLOUD_URL.trimEnd('/')
            val metadata=withContext(Dispatchers.IO) {
                http.newCall(Request.Builder().url("$base/v1/app/update").build()).execute().use {r->
                    if(r.code==204)return@use null
                    check(r.isSuccessful){"Não foi possível consultar as atualizações."}
                    val body=r.body?:error("Resposta vazia")
                    require(body.contentLength()<=32768){"Resposta muito grande"}
                    val raw=body.byteStream().use{input->val data=java.io.ByteArrayOutputStream();val buffer=ByteArray(4096);while(data.size()<=32768){val n=input.read(buffer);if(n<0)break;data.write(buffer,0,n)};data.toString("UTF-8")}
                    require(raw.length<=32768)
                    JSONObject(raw)
                }
            }
            if(metadata==null || metadata.getLong("version_code")<=BuildConfig.VERSION_CODE){state.value=MusicUpdateState(if(manual)"Você está na versão mais recente." else "");return@withLock}
            val version=metadata.getLong("version_code")
            val hash=metadata.getString("sha256").lowercase()
            val size=metadata.getLong("size")
            val url=metadata.getString("url")
            require(hash.matches(Regex("[0-9a-f]{64}")) && size in 1..(200L*1024*1024))
            safeUrl(url)
            state.value=MusicUpdateState("Baixando atualização…",0f,busy=true)
            withContext(Dispatchers.IO) {
                val apk=target(activity);apk.parentFile!!.mkdirs();val part=File(apk.parentFile,"music-update.part")
                part.delete()
                if(apk.isFile && apk.length()==size) {
                    val digest=MessageDigest.getInstance("SHA-256")
                    apk.inputStream().use {input->val buffer=ByteArray(65536);while(true){val n=input.read(buffer);if(n<0)break;digest.update(buffer,0,n)}}
                    if(digest.digest().joinToString(""){"%02x".format(it)}==hash){validateApk(activity,apk,version);return@withContext}
                }
                try {
                    var location=url
                    var response=http.newCall(Request.Builder().url(location).build()).execute()
                    var redirects=0
                    while(response.code in listOf(301,302,303,307,308)) {
                        val next=response.header("Location")?:error("Redirecionamento inválido")
                        response.close();require(++redirects<=5)
                        location=Uri.parse(location).let {java.net.URI(it.toString()).resolve(next).toString()};safeUrl(location)
                        response=http.newCall(Request.Builder().url(location).build()).execute()
                    }
                    response.use {r->
                        check(r.isSuccessful){"Download indisponível. Tente novamente."}
                        val body=r.body?:error("APK vazio");val digest=MessageDigest.getInstance("SHA-256");var total=0L;var notified=0L
                        body.byteStream().use {input->part.outputStream().use {out->
                            val buffer=ByteArray(65536)
                            while(true){ensureActive();val n=input.read(buffer);if(n<0)break;total+=n;require(total<=size);digest.update(buffer,0,n);out.write(buffer,0,n)
                                if(total-notified>=1024*1024 || total==size){notified=total;state.value=MusicUpdateState("Baixando atualização…",total.toFloat()/size,busy=true)}}
                        }}
                        require(total==size && digest.digest().joinToString(""){"%02x".format(it)}==hash){"Download incompleto ou inválido."}
                    }
                    validateApk(activity,part,version)
                    check(part.renameTo(apk)){"Não foi possível salvar a atualização."}
                }finally{part.delete()}
            }
            state.value=MusicUpdateState("Atualização pronta para instalar.",1f,ready=true)
        }catch(e:CancellationException){state.value=MusicUpdateState();throw e}
        catch(_:Exception){state.value=MusicUpdateState(if(manual)"Não foi possível atualizar. Tente novamente com conexão." else "")}
    }
    private fun safeUrl(value:String) {
        val u=java.net.URI(value)
        require(u.scheme=="https" && u.userInfo==null && u.fragment==null && u.host in setOf("github.com","release-assets.githubusercontent.com","objects.githubusercontent.com")){"Origem de atualização inválida"}
    }
    @Suppress("DEPRECATION")
    private fun validateApk(activity:Context,file:File,version:Long) {
        val pm=activity.packageManager
        val flags=PackageManager.GET_SIGNING_CERTIFICATES
        val archive=pm.getPackageArchiveInfo(file.absolutePath,flags)?:error("APK inválido")
        val installed=pm.getPackageInfo(activity.packageName,flags)
        require(archive.packageName==activity.packageName && archive.longVersionCode==version)
        val old=installed.signingInfo?.apkContentsSigners?.map{it.toCharsString()}?.toSet()
        val next=archive.signingInfo?.apkContentsSigners?.map{it.toCharsString()}?.toSet()
        require(!old.isNullOrEmpty() && old==next){"Assinatura diferente. Não desinstale o aplicativo."}
    }
    fun install(activity:Activity) {
        if(!state.value.ready)return
        if(!activity.packageManager.canRequestPackageInstalls()) {
            activity.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:${activity.packageName}")));return
        }
        val file=target(activity);if(!file.isFile){state.value=MusicUpdateState("Atualização não encontrada. Verifique novamente.");return}
        val uri=FileProvider.getUriForFile(activity,"${activity.packageName}.updates",file)
        activity.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
    }
}
