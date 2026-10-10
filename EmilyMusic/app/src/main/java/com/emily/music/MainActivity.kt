package com.emily.music
import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.compose.material3.*
import androidx.core.content.ContextCompat
import com.emily.music.ui.theme.EmilyAPPTheme

class MainActivity:ComponentActivity() {
    private val closeReceiver=object:android.content.BroadcastReceiver(){
        override fun onReceive(context:android.content.Context?,intent:android.content.Intent?){
            if(intent?.action==EmilyMusicService.ACTION_CLOSE)finishAndRemoveTask()
        }
    }
    override fun onDestroy(){unregisterReceiver(closeReceiver);super.onDestroy()}
    override fun onCreate(savedInstanceState:Bundle?) {
        super.onCreate(savedInstanceState)
        ContextCompat.registerReceiver(this,closeReceiver,android.content.IntentFilter(EmilyMusicService.ACTION_CLOSE),ContextCompat.RECEIVER_NOT_EXPORTED)
        MusicUpdateWorker.schedule(this)
        setContent {
            val notifications=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()){}
            LaunchedEffect(Unit) {
                if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(this@MainActivity,Manifest.permission.POST_NOTIFICATIONS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)
                    notifications.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
            LaunchedEffect(Unit) {MusicUpdater.check(this@MainActivity)}
            EmilyAPPTheme {
                EmilyMusicScreen {finish()}
                val update by MusicUpdater.state.collectAsState()
                var dismissed by remember {mutableStateOf(false)}
                if(update.ready && !dismissed)AlertDialog(onDismissRequest={dismissed=true},title={Text("Atualização disponível")},text={Text("Uma nova versão está pronta. Suas músicas e playlists serão preservadas.")},confirmButton={TextButton(onClick={MusicUpdater.install(this@MainActivity)}){Text("Instalar")}},dismissButton={TextButton(onClick={dismissed=true}){Text("Depois")}})
            }
        }
    }
}
