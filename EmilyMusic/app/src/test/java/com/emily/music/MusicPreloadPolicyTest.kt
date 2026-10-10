package com.emily.music
import org.junit.Assert.*
import org.junit.Test
class MusicPreloadPolicyTest {
    @Test fun mobileIsBoundedAndDataSaverDisablesAllPreparation(){
        assertEquals(128L*1024,MusicPreloadPolicy.byteBudget(true,false,false,false))
        assertEquals(512L*1024,MusicPreloadPolicy.byteBudget(true,true,true,false))
        assertEquals(128L*1024,MusicPreloadPolicy.byteBudget(true,true,false,false))
        assertEquals(0L,MusicPreloadPolicy.byteBudget(true,true,true,true))
        assertEquals(0L,MusicPreloadPolicy.byteBudget(false,true,true,false))
        assertFalse(MusicPreloadPolicy.eligible(true,60000,true,true,true,"aaaaaaaaaaa","bbbbbbbbbbb",false,true))
    }
    @Test fun validNextOnUnmeteredWifi(){assertTrue(MusicPreloadPolicy.eligible(true,60000,true,true,true,"aaaaaaaaaaa","bbbbbbbbbbb",false))}
    @Test fun excludesPausedOfflineShortLocalAndRepeat(){
        assertFalse(MusicPreloadPolicy.eligible(false,60000,true,true,true,"aaaaaaaaaaa","bbbbbbbbbbb",false))
        assertTrue(MusicPreloadPolicy.eligible(true,60000,true,true,false,"aaaaaaaaaaa","bbbbbbbbbbb",false))
        assertTrue(MusicPreloadPolicy.eligible(true,60000,true,false,true,"aaaaaaaaaaa","bbbbbbbbbbb",false))
        assertFalse(MusicPreloadPolicy.eligible(true,60000,false,true,true,"aaaaaaaaaaa","bbbbbbbbbbb",false))
        assertFalse(MusicPreloadPolicy.eligible(true,10000,true,true,true,"aaaaaaaaaaa","bbbbbbbbbbb",false))
        assertFalse(MusicPreloadPolicy.eligible(true,60000,true,true,true,"aaaaaaaaaaa","aaaaaaaaaaa",false))
        assertFalse(MusicPreloadPolicy.eligible(true,60000,true,true,true,"aaaaaaaaaaa","local_abc",true))
        assertFalse(MusicPreloadPolicy.eligible(true,60000,true,true,true,"aaaaaaaaaaa",null,false))
    }
}
