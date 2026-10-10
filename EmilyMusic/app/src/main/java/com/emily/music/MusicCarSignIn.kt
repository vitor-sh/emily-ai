package com.emily.music

import android.app.PendingIntent
import android.os.Bundle
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.session.*
import androidx.media3.session.MediaLibraryService.*
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture

/** The car gets a sign-in explanation rather than repeatedly starting an empty service. */
internal class MusicCarSignIn(private val intent:PendingIntent):MediaLibrarySession.Callback {
    override fun onConnect(s:MediaSession,c:MediaSession.ControllerInfo):MediaSession.ConnectionResult {
        if(!(c.uid==android.os.Process.myUid()||c.isTrusted||s.isAutoCompanionController(c)||s.isAutomotiveController(c)))return MediaSession.ConnectionResult.reject()
        return MediaSession.ConnectionResult.AcceptedResultBuilder(s).setAvailablePlayerCommands(Player.Commands.EMPTY).build()
    }
    override fun onGetLibraryRoot(s:MediaLibrarySession,c:MediaSession.ControllerInfo,p:LibraryParams?):ListenableFuture<LibraryResult<MediaItem>> =
        Futures.immediateFuture(LibraryResult.ofError(SessionError(SessionError.ERROR_SESSION_AUTHENTICATION_EXPIRED,"Entre com Google no Emily Music pelo celular antes de usar no carro.",Bundle().apply{
            putString("android.media.extras.ERROR_RESOLUTION_ACTION_LABEL","Entrar no celular")
            putParcelable("android.media.extras.ERROR_RESOLUTION_ACTION_INTENT",intent)
        })))
}
