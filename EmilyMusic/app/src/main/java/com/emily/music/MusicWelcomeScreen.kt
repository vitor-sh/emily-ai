package com.emily.music

import androidx.compose.animation.core.*
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MusicNote
import androidx.compose.material.icons.filled.OfflinePin
import androidx.compose.material.icons.filled.QueueMusic
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Presentation only: rendering this screen never loads playlists or starts a player. */
@Composable
internal fun MusicWelcomeScreen(busy:Boolean,hasAccount:Boolean,error:String?,onEnter:()->Unit,onChangeAccount:()->Unit,onBack:()->Unit) {
    val accent=Color(0xFFD9795A)
    val text=Color(0xFFEDEBE7)
    val muted=Color(0xFFA5A19A)
    val motion=rememberInfiniteTransition(label="music-welcome")
    val glow by motion.animateFloat(.25f,.55f,infiniteRepeatable(tween(3500),RepeatMode.Reverse),label="glow")
    val drift by motion.animateFloat(1f,1.035f,infiniteRepeatable(tween(9000),RepeatMode.Reverse),label="artwork")
    BoxWithConstraints(Modifier.fillMaxSize().background(Color(0xFF080809))) {
        val artSpace=(maxHeight*.21f).coerceIn(70.dp,155.dp)
        Image(painterResource(R.drawable.music_login_art),null,Modifier.fillMaxSize().graphicsLayer {scaleX=drift;scaleY=drift},contentScale=ContentScale.Crop)
        Box(Modifier.fillMaxSize().background(Brush.verticalGradient(0f to Color.Black.copy(alpha=.08f),.32f to Color.Black.copy(alpha=.4f),.65f to Color(0xFF080809).copy(alpha=.94f),1f to Color(0xFF080809))))
        Column(Modifier.fillMaxSize().systemBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal=24.dp,vertical=24.dp),horizontalAlignment=Alignment.CenterHorizontally) {
            Spacer(Modifier.height(artSpace))
            Row(verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(5.dp)) {
                for(i in 0..4)Box(Modifier.width(3.dp).height((10+(if(i==2)13 else if(i==0 || i==4)0 else 7)).dp).graphicsLayer {alpha=glow+.4f}.clip(RoundedCornerShape(3.dp)).background(accent))
            }
            Spacer(Modifier.height(20.dp))
            Text("Emily Music",color=text,fontFamily=FontFamily.Serif,fontSize=46.sp,lineHeight=52.sp,letterSpacing=(-1).sp,textAlign=TextAlign.Center)
            Spacer(Modifier.height(8.dp))
            Text("Seu som, do seu jeito.",color=accent,fontSize=17.sp,textAlign=TextAlign.Center)
            Spacer(Modifier.height(14.dp))
            Text("Uma trilha para cada momento.\nEntre e encontre suas músicas por aqui.",Modifier.widthIn(max=340.dp),color=muted,fontSize=14.sp,lineHeight=22.sp,textAlign=TextAlign.Center)
            Spacer(Modifier.height(28.dp))
            Row(Modifier.widthIn(max=460.dp).fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(10.dp)) {
                MusicWelcomeFeature(Icons.Default.QueueMusic,"Suas playlists","Tudo organizado",Modifier.weight(1f))
                MusicWelcomeFeature(Icons.Default.OfflinePin,"Música offline","Baixe e leve com você",Modifier.weight(1f))
            }
            Spacer(Modifier.height(28.dp))
            Button(onClick=onEnter,enabled=!busy,modifier=Modifier.widthIn(max=460.dp).fillMaxWidth().heightIn(min=56.dp),shape=RoundedCornerShape(18.dp),border=BorderStroke(1.dp,Color(0xFF8E918F)),colors=ButtonDefaults.buttonColors(containerColor=Color(0xFF131314),contentColor=text,disabledContainerColor=Color(0xFF29292B),disabledContentColor=muted)) {
                if(busy) {CircularProgressIndicator(Modifier.size(20.dp),color=text,strokeWidth=2.dp);Spacer(Modifier.width(12.dp))}
                else if(!hasAccount) {
                    Box(Modifier.size(26.dp).clip(CircleShape).background(Color.White),contentAlignment=Alignment.Center){Image(painterResource(R.drawable.google_signin_logo),null,Modifier.size(20.dp))}
                    Spacer(Modifier.width(12.dp))
                }
                Text(if(busy)"Conectando…" else if(hasAccount)"Tentar novamente" else "Entrar com Google",fontSize=16.sp,fontWeight=FontWeight.SemiBold)
            }
            if(error!=null) {
                Spacer(Modifier.height(12.dp))
                Surface(Modifier.widthIn(max=460.dp).fillMaxWidth(),shape=RoundedCornerShape(14.dp),color=Color(0xFF372521)) {
                    Text(error,Modifier.padding(14.dp),color=Color(0xFFF1B5A6),fontSize=13.sp,textAlign=TextAlign.Center)
                }
            }
            if(hasAccount && !busy)TextButton(onClick=onChangeAccount){Text("Usar outra conta",color=accent)}
            Spacer(Modifier.height(14.dp))
            Text("Sua biblioteca aparece depois de entrar.",color=muted,fontSize=12.sp,textAlign=TextAlign.Center)
            TextButton(onClick=onBack){Text("Fechar",color=muted)}
        }
    }
}

@Composable
private fun MusicWelcomeFeature(icon:ImageVector,title:String,detail:String,modifier:Modifier) {
    Column(modifier.clip(RoundedCornerShape(18.dp)).background(Color(0xFF171719).copy(alpha=.9f)).border(1.dp,Color(0xFF303033),RoundedCornerShape(18.dp)).padding(14.dp)) {
        Icon(icon,null,Modifier.size(23.dp),tint=Color(0xFFD9795A))
        Spacer(Modifier.height(10.dp))
        Text(title,color=Color(0xFFEDEBE7),fontSize=13.sp,fontWeight=FontWeight.Medium)
        Spacer(Modifier.height(4.dp))
        Text(detail,color=Color(0xFFA5A19A),fontSize=11.sp,lineHeight=15.sp)
    }
}
