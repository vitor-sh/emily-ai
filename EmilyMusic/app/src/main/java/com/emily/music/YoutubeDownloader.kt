package com.emily.music
import android.content.Context
import android.util.Log
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.ffmpeg.FFmpeg
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
internal object YoutubeDownloader {
    private const val TAG="MusicExtractor"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val initMutex = Mutex()
    private val updateMutex = Mutex()
    @Volatile private var inicializado = false

    // ─── Init preguiçoso ──────────────────────────────────────────────────────
    internal suspend fun garantirInit(context: Context) {
        if (inicializado) return
        initMutex.withLock {
            if (inicializado) return
            withContext(Dispatchers.IO) {
                YoutubeDL.getInstance().init(context)
                FFmpeg.getInstance().init(context)
            }
            inicializado = true
            Log.d(TAG, "yt-dlp/FFmpeg inicializados")
        }
    }

    /** Mantém o extrator usado pelo Music atual; o binário empacotado envelhece
     * quando o YouTube muda. Uma consulta diária, compartilhada entre operações. */
    internal suspend fun garantirAtualizado(context: Context) {
        garantirInit(context)
        updateMutex.withLock {
            val prefs=context.getSharedPreferences("music_extractor",Context.MODE_PRIVATE)
            val now=System.currentTimeMillis()
            if(now-prefs.getLong("checked",0)<24*60*60*1000L)return@withLock
            if(now-prefs.getLong("attempt",0)<60*60*1000L)return@withLock
            prefs.edit().putLong("attempt",now).apply()
            withContext(Dispatchers.IO) {
                runCatching {YoutubeDL.getInstance().updateYoutubeDL(context.applicationContext)}
                    .onSuccess {prefs.edit().putLong("checked",now).apply()}
                    .onFailure {Log.w(TAG,"Extrator aguardando nova tentativa de atualização",it)}
            }
        }
    }

    /** Warm initialization only; daily maintenance does not delay the first song. */
    internal suspend fun prepararMusic(context:Context) {
        garantirInit(context)
        scope.launch {garantirAtualizado(context.applicationContext)}
    }

}
