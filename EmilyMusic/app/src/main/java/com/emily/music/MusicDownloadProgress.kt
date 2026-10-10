package com.emily.music

/** Extractors use negative values for unknown size or processing phases. */
internal object MusicDownloadProgress {
    fun percent(raw:Float):Int?=if(!raw.isFinite()||raw<0)null else raw.toInt().coerceIn(0,100)
    fun percent(raw:Int):Int?=if(raw<0)null else raw.coerceAtMost(100)
}
