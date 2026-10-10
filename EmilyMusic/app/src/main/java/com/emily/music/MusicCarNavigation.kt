package com.emily.music

import android.content.Context
import android.net.Uri
import android.os.Bundle
import androidx.media3.common.util.UnstableApi
import androidx.media3.session.CommandButton
import androidx.media3.session.SessionCommand
import androidx.media.utils.MediaConstants

/** Navigation is a browser result, never a playback command or a phone Activity. */
@UnstableApi
internal object MusicCarNavigation {
    const val HOME="emily.music.car.home"
    const val BACK="emily.music.car.back"
    const val PLAYING="emily.music.car.playing"
    val commands=listOf(HOME,BACK,PLAYING)
    fun supported(id:String)=if(id==MusicCarCatalog.ROOT)listOf(PLAYING) else commands
    fun buttons(context:Context)=listOf(
        Triple(HOME,"Início","home"),Triple(BACK,"Voltar","back"),Triple(PLAYING,"Em reprodução","play")
    ).map{(action,title,icon)->CommandButton.Builder(CommandButton.ICON_UNDEFINED)
        .setDisplayName(title).setIconUri(icon(context.packageName,icon))
        .setSessionCommand(SessionCommand(action,Bundle.EMPTY)).build()}
    fun icon(packageName:String,name:String):Uri {
        val resource=when(name){"home"->R.drawable.ic_car_home;"back"->R.drawable.ic_car_back;"play"->R.drawable.ic_car_play;"favorites"->R.drawable.ic_car_favorites;"downloads"->R.drawable.ic_car_downloads;"locals"->R.drawable.ic_car_locals;"all"->R.drawable.ic_car_all;"save"->R.drawable.ic_car_save;"add"->R.drawable.ic_car_add;"filter"->R.drawable.ic_car_filter;"retry"->R.drawable.ic_car_retry;else->R.drawable.ic_car_playlists}
        return Uri.parse("android.resource://$packageName/$resource")
    }
    fun result(action:String,id:String?):Bundle?=when(action){
        HOME->Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE,MusicCarCatalog.ROOT)}
        BACK->Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_BROWSE_NODE,parent(id))}
        PLAYING->Bundle().apply{putString(MediaConstants.EXTRAS_KEY_CUSTOM_BROWSER_ACTION_RESULT_SHOW_PLAYING_ITEM,null)}
        else->null
    }
    // A menu attached to a song returns to its list, never browses a playable song ID.
    internal fun browseTarget(parent:String,playableParent:String?):String = playableParent
        ?: if(parent.startsWith("car:track:"))MusicCarNavigation.parent(parent) else parent
    private fun decode(value:String)=runCatching{java.net.URLDecoder.decode(value.replace("+","%2B"),"UTF-8")}.getOrNull()
    internal fun parent(id:String?):String=when{
        id==null||id==MusicCarCatalog.ROOT->MusicCarCatalog.ROOT
        id.startsWith("car:track:")->decode(id.removePrefix("car:track:").substringBeforeLast(':',""))
            ?.takeIf{it==MusicCarCatalog.ALL||it==MusicCarCatalog.FAVORITES||it==MusicCarCatalog.DOWNLOADS||it==MusicCarCatalog.LOCALS||it.startsWith("car:playlist:")}?:MusicCarCatalog.ROOT
        id.startsWith("car:playlist:")||id==MusicCarCatalog.ALL->MusicCarCatalog.PLAYLISTS
        else->MusicCarCatalog.ROOT
    }
}
