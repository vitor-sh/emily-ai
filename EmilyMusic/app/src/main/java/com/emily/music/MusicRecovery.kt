package com.emily.music

/** A pause/track change cancels recovery; exhausted retries still wait for internet. */
internal class MusicRecovery {
    private var track: String? = null
    private var wanted = false
    private var attempts = 0
    fun failed(id: String?, playWhenReady: Boolean, networkError: Boolean) {
        if (!playWhenReady || !networkError || id == null) { stop(); return }
        if (track != id) attempts = 0
        track = id; wanted = true
    }
    fun canAttempt(id: String?, online: Boolean) = wanted && track == id && online && attempts < 3
    fun attempted() { attempts++ }
    fun connectionRestored() { if (wanted) attempts = 0 }
    fun stop() { wanted = false; track = null; attempts = 0 }
}
