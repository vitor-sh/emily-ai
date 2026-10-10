package com.emily.music

import org.junit.Test
import org.junit.Assert.*

class MusicCarUsabilityTest {
    @Test fun backFromSongMenusReturnsToSearchOrPlaylistRatherThanPlayableItem() {
        assertEquals("car:discover:query",MusicCarNavigation.browseTarget("car:discover:song","car:discover:query"))
        assertEquals("car:playlist:Café",MusicCarNavigation.browseTarget("car:track:car%3Aplaylist%3ACaf%C3%A9:aaaaaaaaaaa",null))
        assertEquals("car:discover:options",MusicCarNavigation.browseTarget("car:discover:options",null))
    }

    @Test fun onlineIdsKeepCaseWhileNaturalLanguageHandlesAccents() {
        assertNotEquals(MusicCarDiscovery.queryKey("Abcdefghijk"),MusicCarDiscovery.queryKey("abcdefghijk"))
        assertNotEquals(MusicCarDiscovery.queryKey("https://www.youtube.com/playlist?list=PLAbCd"),MusicCarDiscovery.queryKey("https://www.youtube.com/playlist?list=PLabcd"))
        assertEquals(MusicCarDiscovery.queryKey("CAFÉ"),MusicCarDiscovery.queryKey("cafe"))
    }

    @Test fun backTracksEncodedParentsAndStaysInsideCatalog() {
        assertEquals(MusicCarCatalog.ROOT,MusicCarNavigation.parent(null))
        assertEquals(MusicCarCatalog.ROOT,MusicCarNavigation.parent(MusicCarCatalog.PLAYLISTS))
        assertEquals(MusicCarCatalog.ROOT,MusicCarNavigation.parent(MusicCarCatalog.FAVORITES))
        assertEquals(MusicCarCatalog.PLAYLISTS,MusicCarNavigation.parent(MusicCarCatalog.ALL))
        assertEquals(MusicCarCatalog.PLAYLISTS,MusicCarNavigation.parent("car:playlist:Caf%C3%A9"))
        assertEquals("car:playlist:Teste / café",MusicCarNavigation.parent("car:track:car%3Aplaylist%3ATeste%20%2F%20caf%C3%A9:aaaaaaaaaaa"))
        assertEquals("car:playlist:A+B",MusicCarNavigation.parent("car:track:car%3Aplaylist%3AA+B:aaaaaaaaaaa"))
        assertEquals(MusicCarCatalog.ROOT,MusicCarNavigation.parent("car:track:%ZZ:aaaaaaaaaaa"))
        assertEquals(MusicCarCatalog.ROOT,MusicCarNavigation.parent("car:track:file%3A%2F%2Fprivate:aaaaaaaaaaa"))
    }
    @Test fun librarySearchHandlesAccentsSpacingAndRequiresAllWords() {
        assertTrue(MusicCarQuery.matches(MusicCarQuery.terms("  ACAO\n CAFE "),"Ação — Café"))
        assertTrue(MusicCarQuery.matches(MusicCarQuery.terms("ARTISTA música"),"Música boa Artista"))
        assertFalse(MusicCarQuery.matches(MusicCarQuery.terms("outro artista"),"Música Artista"))
        assertFalse(MusicCarQuery.matches(MusicCarQuery.terms("  "),"Música Artista"))
        assertEquals(300,MusicCarQuery.terms("a".repeat(10000)).single().length)
    }
}
