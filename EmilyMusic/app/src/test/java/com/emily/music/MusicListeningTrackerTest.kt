package com.emily.music
import org.junit.Assert.*
import org.junit.Test
class MusicListeningTrackerTest {
 @Test fun bufferingPausesAndSeeksDoNotCountAsListening(){val t=MusicListeningTracker();t.transition(0,true);assertFalse(t.qualify(5000,180000));t.playing(5000,false);assertFalse(t.qualify(60000,180000));t.playing(60000,true);assertFalse(t.qualify(64999,180000));assertTrue(t.qualify(65000,180000));assertFalse(t.qualify(120000,180000))}
 @Test fun RepeatIsANewListenAndShortTracksUseHalfDuration(){val t=MusicListeningTracker();t.transition(0,true);assertTrue(t.qualify(10000,30000));t.transition(11000,true);assertFalse(t.qualify(12000,8000));assertTrue(t.qualify(15000,8000))}
}
