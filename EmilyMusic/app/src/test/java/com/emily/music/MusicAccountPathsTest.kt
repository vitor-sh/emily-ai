package com.emily.music
import org.junit.Assert.*
import org.junit.Test
class MusicAccountPathsTest {
    @Test fun stableSeparatedSafePaths() {
        assertEquals(MusicAccountPaths.key("account-a"),MusicAccountPaths.key("account-a"))
        assertNotEquals(MusicAccountPaths.key("account-a"),MusicAccountPaths.key("account-b"))
        assertTrue(MusicAccountPaths.key("../a/b").matches(Regex("[a-f0-9]{64}")))
    }
    @Test fun rejectsMissingOwner() {
        assertThrows(IllegalArgumentException::class.java){MusicAccountPaths.key("")}
        assertThrows(IllegalArgumentException::class.java){MusicAccountPaths.key("x".repeat(129))}
    }
}
