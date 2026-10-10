package com.emily.music

import java.text.Normalizer
import java.util.Locale

internal object MusicCarQuery {
    fun normalize(text:String)=Normalizer.normalize(text,Normalizer.Form.NFD)
        .replace(Regex("\\p{M}"),"").lowercase(Locale.ROOT).trim()
    fun terms(query:String)=normalize(query.take(300)).split(Regex("\\s+")).filter{it.isNotBlank()}
    fun matches(terms:List<String>,text:String):Boolean=terms.isNotEmpty()&&normalize(text).let{normalized->terms.all{normalized.contains(it)}}
}
