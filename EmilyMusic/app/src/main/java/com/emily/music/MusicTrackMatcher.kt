package com.emily.music

import java.text.Normalizer
import kotlin.math.abs

/** Metadata evidence, never a guarantee of identical recordings. */
internal object MusicTrackMatcher {
    data class Candidate(val id:String,val title:String,val artist:String,val duration:Long)
    data class Ranked(val candidate:Candidate,val score:Double,val trusted:Boolean)
    private fun normalized(s:String)=Normalizer.normalize(s,Normalizer.Form.NFD).replace(Regex("\\p{M}"),"")
        .lowercase().replace("remastered","remaster").replace(Regex("[^\\p{L}\\p{N}]+")," ").trim()
    private fun words(s:String)=normalized(s).split(" ").filter {it.isNotBlank()}.toSet()
    private val variants=listOf("cover","remix","nightcore","sped up","slowed","karaoke","instrumental","live","acoustic","remaster","demo","extended","piano","reaction","tribute","8d","mashup")
    fun rank(title:String,artists:String,duration:Long,candidates:List<Candidate>):List<Ranked> {
        val wanted=words(title);val performers=words(artists).filter {it !in setOf("feat","ft","and","the")}.toSet()
        val original=" ${normalized(title)} "
        return candidates.distinctBy{it.id}.map {c ->
            val text=" ${normalized(c.title+" "+c.artist)} ";val found=words(c.title+" "+c.artist)
            val titleScore=wanted.count{it in found}.toDouble()/wanted.size.coerceAtLeast(1)
            val artistScore=performers.count{it in found}.toDouble()/performers.size.coerceAtLeast(1)
            val distance=abs(c.duration-duration)
            val versionMatches=variants.all {v -> (" $v " in text)==(" $v " in original) }
            val durationScore=if(c.duration<=0)0.0 else if(distance<=3).2 else if(distance<=8).12 else 0.0
            val official=" topic " in text || " official audio " in text || " vevo " in text
            val score=titleScore*.5+artistScore*.3+durationScore+(if(official).03 else 0.0)-(if(versionMatches)0.0 else .6)
            Ranked(c,score,titleScore==1.0&&artistScore>=.8&&c.duration>0&&distance<=8&&versionMatches)
        }.sortedWith(compareByDescending<Ranked>{it.trusted}.thenByDescending{it.score})
    }
}
