package com.emily.music

import android.app.PendingIntent
import android.os.Bundle
import androidx.media3.common.*
import androidx.media3.common.util.UnstableApi
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/** Standard controllers must be able to resume an idle/failed source with one Play. */
@UnstableApi
internal class MusicSessionPlayer(player:Player,private val retry:PendingIntent):ForwardingSimpleBasePlayer(player) {
    override fun getState():State {
        val state=super.getState()
        val error=state.playerError ?: return state
        val extras=Bundle(error.extras).apply {
            putString("android.media.extras.ERROR_RESOLUTION_ACTION_LABEL","Tentar novamente")
            putParcelable("android.media.extras.ERROR_RESOLUTION_ACTION_INTENT",retry)
        }
        return state.buildUpon().setPlayerError(PlaybackException(musicPlaybackErrorMessage(error),error.cause,error.errorCode,extras)).setPlayWhenReady(false,Player.PLAY_WHEN_READY_CHANGE_REASON_USER_REQUEST).build()
    }
    override fun handleSetPlayWhenReady(wanted:Boolean):ListenableFuture<*> {
        if(wanted)MusicPlaybackActions.resume(player) else player.pause()
        return Futures.immediateVoidFuture()
    }
    override fun handleSeek(index:Int,position:Long,command:Int):ListenableFuture<*> {
        val result=super.handleSeek(index,position,command)
        MusicPlaybackActions.prepareIfWanted(player)
        return result
    }
}

internal fun musicPlaybackErrorMessage(error:PlaybackException):String=when(error.errorCode) {
    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT->"A conexão interrompeu o áudio. Tente novamente ou escolha outra música."
    PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND->"O arquivo desta música não está disponível neste celular. Escolha outra música."
    else->"Não foi possível tocar esta música. Tente novamente ou escolha outra na biblioteca."
}
