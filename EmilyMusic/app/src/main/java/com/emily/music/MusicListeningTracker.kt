package com.emily.music

/** Conta tempo realmente tocado, sem transformar seek, pausa ou buffering em audições. */
internal class MusicListeningTracker {
    private var elapsed=0L
    private var start:Long?=null
    private var counted=false
    fun transition(now:Long,playing:Boolean) {elapsed=0;counted=false;start=if(playing)now else null}
    fun playing(now:Long,value:Boolean) {
        start?.let {elapsed+=(now-it).coerceAtLeast(0)}
        start=if(value)now else null
    }
    fun qualify(now:Long,duration:Long):Boolean {
        if(counted||start==null)return false
        val heard=elapsed+(now-start!!).coerceAtLeast(0)
        val threshold=if(duration in 1..19999)maxOf(1000,duration/2) else 10000
        if(heard<threshold)return false
        counted=true;return true
    }
}
