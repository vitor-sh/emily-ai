package com.emily.music

internal object MusicPreloadPolicy {
    fun byteBudget(validated:Boolean,wifi:Boolean,unmetered:Boolean,dataSaver:Boolean):Long =
        if(!validated || dataSaver)0 else if(wifi && unmetered)512L*1024 else 128L*1024
    fun eligible(playing:Boolean,remainingMs:Long,validated:Boolean,wifi:Boolean,unmetered:Boolean,
                 current:String?,next:String?,local:Boolean,dataSaver:Boolean=false):Boolean =
        playing && remainingMs>20000 && byteBudget(validated,wifi,unmetered,dataSaver)>0 && !local &&
        current!=next && next?.matches(Regex("[A-Za-z0-9_-]{11}"))==true
}
