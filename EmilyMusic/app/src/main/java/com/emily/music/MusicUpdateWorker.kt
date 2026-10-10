package com.emily.music

import android.content.Context
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import androidx.core.app.NotificationCompat
import androidx.work.*
import java.util.concurrent.TimeUnit

internal class MusicUpdateWorker(context:Context,params:WorkerParameters):CoroutineWorker(context,params) {
    override suspend fun doWork():Result {
        MusicUpdater.check(applicationContext)
        if(MusicUpdater.state.value.ready) {
            val manager=applicationContext.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel("music_updates","Atualizações do Emily Music",NotificationManager.IMPORTANCE_DEFAULT))
            val intent=PendingIntent.getActivity(applicationContext,420,Intent(applicationContext,MainActivity::class.java),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val notification=NotificationCompat.Builder(applicationContext,"music_updates").setSmallIcon(R.drawable.ic_music).setContentTitle("Emily Music: atualização disponível").setContentText("Toque para abrir e instalar a nova versão.").setContentIntent(intent).setAutoCancel(true).build()
            runCatching {manager.notify(420,notification)}
        }
        return Result.success()
    }
    companion object {
        fun schedule(context:Context) {
            val job=PeriodicWorkRequestBuilder<MusicUpdateWorker>(12,TimeUnit.HOURS).setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.UNMETERED).setRequiresStorageNotLow(true).build()).build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork("music-update",ExistingPeriodicWorkPolicy.KEEP,job)
        }
    }
}
