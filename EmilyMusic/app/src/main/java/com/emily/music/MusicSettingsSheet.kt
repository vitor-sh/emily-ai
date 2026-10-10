package com.emily.music

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun MusicSettingsSheet(email:String,busy:Boolean,error:String?,onDismiss:()->Unit,onSignOut:()->Unit,onUpdate:()->Unit={},onSources:()->Unit={},update:MusicUpdateState=MusicUpdateState(),onImport:()->Unit={}) {
    ModalBottomSheet(onDismissRequest=onDismiss,containerColor=MaterialTheme.colorScheme.surface,
        sheetState=rememberModalBottomSheetState(skipPartiallyExpanded=true)) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal=24.dp).padding(bottom=24.dp),verticalArrangement=Arrangement.spacedBy(20.dp)) {
            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                Icon(Icons.Outlined.Settings,null,tint=MaterialTheme.colorScheme.primary)
                Text("Configurações",style=MaterialTheme.typography.headlineSmall)
            }
            Surface(color=MaterialTheme.colorScheme.surfaceVariant,shape=RoundedCornerShape(16.dp)) {
                Row(Modifier.fillMaxWidth().padding(16.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Outlined.AccountCircle,null,Modifier.size(32.dp),tint=MaterialTheme.colorScheme.primary)
                    Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(4.dp)) {
                        Text("Conta Google",style=MaterialTheme.typography.labelMedium,color=MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(email,style=MaterialTheme.typography.bodyMedium,maxLines=2,overflow=TextOverflow.Ellipsis)
                    }
                }
            }
            Text("Sua biblioteca permanece salva nesta conta ao sair.",style=MaterialTheme.typography.bodyMedium,color=MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick=onImport,enabled=!busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Importar playlists")}
            if(error!=null)Text(error,color=MaterialTheme.colorScheme.error,style=MaterialTheme.typography.bodyMedium)
            OutlinedButton(onClick=onSignOut,enabled=!busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp),shape=RoundedCornerShape(12.dp)) {
                if(busy)CircularProgressIndicator(Modifier.size(18.dp),strokeWidth=2.dp)
                else Icon(Icons.Outlined.Logout,null,Modifier.size(20.dp))
                Spacer(Modifier.width(10.dp));Text(if(busy)"Saindo…" else "Sair da conta")
            }
            OutlinedButton(onClick=onUpdate,enabled=!update.busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                Text(if(update.ready)"Instalar atualização" else if(update.busy)"Verificando…" else "Verificar atualização")
            }
            Text("Novas versões são baixadas automaticamente em redes sem cobrança por dados. A instalação pede sua confirmação.",style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
            if(update.message.isNotBlank())Text(update.message,style=MaterialTheme.typography.bodySmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
            if(update.busy && update.progress!=null)LinearProgressIndicator(progress={update.progress},modifier=Modifier.fillMaxWidth())
            TextButton(onClick=onSources){Text("Código e licenças") }
            Text("Emily Music · ${BuildConfig.VERSION_NAME}",style=MaterialTheme.typography.labelSmall,color=MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
