package com.emily.music

/** Small, per-process cache; neither requests nor cached failures are synchronized. */
internal class MusicSearchCache(private val now:()->Long={System.currentTimeMillis()},private val capacity:Int=32,private val ttl:Long=10*60*1000L) {
    private val entries=LinkedHashMap<String,Pair<Long,String>>(16,.75f,true)
    @Synchronized fun clear(){entries.clear()}
    @Synchronized fun get(query:String):String? {
        val item=entries[query]?:return null
        if(now()-item.first>=ttl){entries.remove(query);return null}
        return item.second
    }
    @Synchronized fun put(query:String,result:String){entries[query]=now() to result;while(entries.size>capacity)entries.remove(entries.keys.first())}
}
