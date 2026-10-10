package com.emily.music

import androidx.media3.common.Player

/** Run on the player looper. A seek alone cannot restart a failed/idle player. */
internal object MusicPlaybackActions {
    fun resume(player:Player) {
        if(player.mediaItemCount==0)return
        if(player.playbackState==Player.STATE_ENDED)player.seekToDefaultPosition()
        if(player.playerError!=null || player.playbackState==Player.STATE_IDLE)player.prepare()
        player.play()
    }
    fun toggle(player:Player) {
        if(player.playWhenReady && player.playerError==null &&
            player.playbackState!=Player.STATE_IDLE && player.playbackState!=Player.STATE_ENDED)player.pause()
        else resume(player)
    }
    fun next(player:Player) {
        if(player.hasNextMediaItem())player.seekToNextMediaItem()
        else if(player.repeatMode!=Player.REPEAT_MODE_OFF && player.mediaItemCount>0)player.seekTo(0,0)
        prepareIfWanted(player)
    }
    fun previous(player:Player) {
        if(player.mediaItemCount==0)return
        if(player.currentPosition>3000)player.seekTo(0)
        else if(player.hasPreviousMediaItem())player.seekToPreviousMediaItem()
        else player.seekTo(0)
        prepareIfWanted(player)
    }
    fun prepareIfWanted(player:Player) {
        if(player.playWhenReady && player.mediaItemCount>0 &&
            (player.playerError!=null || player.playbackState==Player.STATE_IDLE))player.prepare()
    }
}
