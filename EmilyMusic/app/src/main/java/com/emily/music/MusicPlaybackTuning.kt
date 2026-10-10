package com.emily.music

import androidx.media3.exoplayer.DefaultLoadControl

/** Start sooner; retain the conservative rebuffer threshold for unstable mobile networks. */
internal object MusicPlaybackTuning {
    fun loadControl()=DefaultLoadControl.Builder()
        .setBufferDurationsMs(50_000,50_000,1_000,5_000).build()
}
