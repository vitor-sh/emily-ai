package com.emily.music
import org.junit.Assert.assertEquals
import org.junit.Test

class MusicTrackTitleTest {
    @Test fun albumPrefixesKeepTheSongAndItsVersion() {
        assertEquals("Resurrections",MusicTrackTitle.display("[Official] Celeste Original Soundtrack - 03 - Resurrections"))
        assertEquals("Awake",MusicTrackTitle.display("Celeste OST: Awake"))
        assertEquals("First Steps",MusicTrackTitle.display("Celeste OST — 02 — First Steps"))
        assertEquals("Exhale (Live)",MusicTrackTitle.display("Celeste Soundtrack | Exhale (Live)"))
        assertEquals("A jornada",MusicTrackTitle.display("Jogo Trilha Sonora - Faixa 12: A jornada"))
    }
    @Test fun ordinaryTitlesAndAmbiguousNumbersArePreserved() {
        for(title in listOf("Awake","Guns N' Roses - Sweet Child O' Mine","1999 - Prince","Soundtrack of My Life","Soundtrack of My Life - Artist","Celeste OST - 01 - 123","Artist - Song (OST)"))assertEquals(title,MusicTrackTitle.display(title))
    }
    @Test fun cleanupIsIdempotent() {
        val title=MusicTrackTitle.display("Celeste OST - 03 - Resurrections")
        assertEquals(title,MusicTrackTitle.display(title))
    }
}
