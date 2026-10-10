package com.emily.music

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.*
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Downloads persistem na fila do Android e não dependem da tela aberta. */
class EmilyMusicDownload(context:Context, params:WorkerParameters):CoroutineWorker(context,params) {
    private val owner=inputData.getString("owner") ?: ""
    private val video=inputData.getString("video") ?: ""
    override suspend fun doWork():Result=withContext(Dispatchers.IO) {
        if(owner!=MusicCloud.currentUser()?.uid || !MusicCloud.locallyApproved(applicationContext))return@withContext Result.failure()
        EmilyMusicLibrary.init(applicationContext)
        val library=EmilyMusicLibrary.forAccount(owner)
        if(!video.matches(Regex("[A-Za-z0-9_-]{11}")))return@withContext Result.failure()
        if(library.localUri(video)!=null)return@withContext Result.success()
        setForeground(notification())
        slots.withPermit {
            val folder=library.folder;val temp=File(folder,".$video.$id.download")
            try {
                temp.deleteRecursively();temp.mkdirs()
                require(folder.usableSpace>100L*1024*1024){"Espaço insuficiente"}
                YoutubeDownloader.garantirAtualizado(applicationContext)
                val request=YoutubeDLRequest("https://www.youtube.com/watch?v=$video").apply {
                    addOption("--no-playlist");addOption("-f","bestaudio/best");addOption("-x");addOption("--audio-format","mp3");addOption("--audio-quality","192K");addOption("--socket-timeout","15");addOption("--retries","2");addOption("--max-filesize","128M");addOption("-o",File(temp,"audio.%(ext)s").absolutePath)
                }
                withTimeout(15*60*1000L) { suspendCancellableCoroutine<Unit> { continuation ->
                    val tag="music-$video-$id"
                    val cancelled=java.util.concurrent.atomic.AtomicBoolean(false)
                    continuation.invokeOnCancellation {cancelled.set(true);runCatching{YoutubeDL.getInstance().destroyProcessById(tag)}}
                    Thread({
                        try {
                            YoutubeDL.getInstance().execute(request,tag,false){progress,_,_->
                                check(!isStopped&&continuation.isActive){"Download cancelado"}
                                setProgressAsync(workDataOf("percent" to (MusicDownloadProgress.percent(progress)?:-1)))
                            }
                            if(continuation.isActive)continuation.resume(Unit)
                        } catch(e:Exception){if(continuation.isActive)continuation.resumeWithException(e)}
                        finally {if(cancelled.get())temp.deleteRecursively()}
                    },"emily-music-download-$video").apply{isDaemon=true}.start()
                } }
                coroutineContext.ensureActive()
                check(!library.closed && owner==MusicCloud.currentUser()?.uid){"A conta mudou."}
                val audio=File(temp,"audio.mp3");require(audio.length() in 1..128L*1024*1024){"Áudio incompleto ou maior que 128 MB"};check(audio.renameTo(File(folder,"$video.mp3")))
                runCatching {
                    val connection=java.net.URL("https://i.ytimg.com/vi/$video/mqdefault.jpg").openConnection().apply {connectTimeout=5000;readTimeout=5000}
                    connection.getInputStream().use {input->val out=java.io.ByteArrayOutputStream();val buf=ByteArray(8192);while(true){val n=input.read(buf);if(n<0)break;require(out.size()+n<=1024*1024);out.write(buf,0,n)};File(library.covers,"$video.jpg").writeBytes(out.toByteArray())}
                }
                Result.success()
            } catch(e:CancellationException){throw e}
            catch(e:Exception){if(runAttemptCount<3 && (!library.online() || e is java.io.IOException))return@withPermit Result.retry();Result.failure(workDataOf("error" to (e.message?:"Download falhou").take(300)))}
            finally {temp.deleteRecursively()}
        }
    }
    private fun notification():ForegroundInfo {
        val nm=applicationContext.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("emily_music_download","Downloads do Emily Music",NotificationManager.IMPORTANCE_LOW))
        val pending=PendingIntent.getActivity(applicationContext,701,Intent(applicationContext,MainActivity::class.java).putExtra("emily_music",true),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val notification=NotificationCompat.Builder(applicationContext,"emily_music_download").setSmallIcon(R.drawable.ic_music)
            .setContentTitle("Baixando no Emily Music").setContentText(inputData.getString("title")?:"Música")
            .setContentIntent(pending).setOngoing(true).setProgress(0,0,true)
            .addAction(0,"Cancelar",WorkManager.getInstance(applicationContext).createCancelPendingIntent(id)).build()
        return if(Build.VERSION.SDK_INT>=29)ForegroundInfo(id.hashCode().and(0x7fffffff),notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC) else ForegroundInfo(id.hashCode().and(0x7fffffff),notification)
    }
    companion object {
        const val TAG="emily-music-download"
        private val slots=Semaphore(2)
        fun enqueue(items:JSONArray):Int {
            val context=EmilyMusicLibrary.context();val owner=MusicCloud.accountKey();val account=EmilyMusicLibrary.accountId;val wm=WorkManager.getInstance(context);var count=0
            val lists=EmilyMusicLibrary.library().getJSONObject("playlists")
            val saved=lists.keys().asSequence().filter { !lists.getJSONObject(it).optBoolean("readonly") }.flatMap {n->val tracks=lists.getJSONObject(n).getJSONArray("musicas");(0 until tracks.length()).asSequence().map{tracks.getJSONObject(it).optString("video_id")}}.toSet()
            for(i in 0 until items.length().coerceAtMost(200)){
                val m=items.optJSONObject(i)?:continue;val id=m.optString("video_id")
                if(!id.matches(Regex("[A-Za-z0-9_-]{11}"))||id !in saved||EmilyMusicLibrary.localUri(id)!=null)continue
                val states=wm.getWorkInfosForUniqueWork("music-$account-$id").get(3, java.util.concurrent.TimeUnit.SECONDS)
                if(states.any{!it.state.isFinished})continue
                val req=OneTimeWorkRequestBuilder<EmilyMusicDownload>().setInputData(workDataOf("owner" to owner,"video" to id,"title" to m.optString("titulo")))
                    .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()).addTag(TAG).addTag("account-$account").addTag("music-$id").addTag("enqueued-${System.currentTimeMillis()}").build()
                wm.enqueueUniqueWork("music-$account-$id",ExistingWorkPolicy.KEEP,req);count++
            }
            return count
        }
        fun cancel(id:String){require(id.matches(Regex("[A-Za-z0-9_-]{11}")));WorkManager.getInstance(EmilyMusicLibrary.context()).cancelUniqueWork("music-${EmilyMusicLibrary.accountId}-$id")}
        fun states(account:String=EmilyMusicLibrary.accountId):Map<String,JSONObject> = runCatching {
            WorkManager.getInstance(EmilyMusicLibrary.context()).getWorkInfosByTag("account-$account").get(3, java.util.concurrent.TimeUnit.SECONDS).sortedByDescending {w->w.tags.firstOrNull {it.startsWith("enqueued-")}?.removePrefix("enqueued-")?.toLongOrNull() ?: if(!w.state.isFinished) Long.MAX_VALUE else 0L}.distinctBy {it.tags.firstOrNull {tag->tag.startsWith("music-")}}.mapNotNull {w->
                val id=w.tags.firstOrNull {it.startsWith("music-")}?.removePrefix("music-")?:return@mapNotNull null
                val json=when(w.state){WorkInfo.State.ENQUEUED,WorkInfo.State.BLOCKED->JSONObject().put("estado","fila")
                    WorkInfo.State.RUNNING->JSONObject().put("estado","baixando").put("progresso",MusicDownloadProgress.percent(w.progress.getInt("percent",-1))?:JSONObject.NULL)
                    WorkInfo.State.FAILED->JSONObject().put("estado","erro").put("erro",w.outputData.getString("error")?:"Download interrompido")
                    else->return@mapNotNull null}
                id to json
            }.toMap()
        }.getOrElse {emptyMap()}
    }
}
