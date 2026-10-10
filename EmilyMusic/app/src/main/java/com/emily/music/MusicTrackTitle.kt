package com.emily.music

/** Remove explicit album/track-number prefixes, never guess from an arbitrary dash. */
internal object MusicTrackTitle {
    private val split=Regex("^(.+?)(?:\\s+[-–—|]\\s+|:\\s+)(.+)$")
    private val album=Regex("\\b(soundtrack|ost|trilha sonora)\\s*$",RegexOption.IGNORE_CASE)
    private val number=Regex("^(?:track\\s+|faixa\\s+)?[0-9]{1,3}\\s*[-–—|:.]\\s*(.+)$",RegexOption.IGNORE_CASE)
    fun display(title:String):String {
        val parts=split.matchEntire(title.trim()) ?: return title
        if(!album.containsMatchIn(parts.groupValues[1]))return title
        val tail=parts.groupValues[2].trim()
        val song=number.matchEntire(tail)?.groupValues?.get(1)?.trim() ?: tail
        return song.takeIf {it.isNotBlank()&&it.any(Char::isLetter)} ?: title
    }
}
