package com.emily.music

import org.junit.Test
import org.junit.Assert.*

class MusicTrackMatcherTest {
 private fun c(id:String,title:String,artist:String="The Score",duration:Long=240)=MusicTrackMatcher.Candidate(id,title,artist,duration)
 @Test fun officialRecordingRanksAboveCoverEvenWithMatchingWordsAndDuration() {
  val result=MusicTrackMatcher.rank("The Fear","The Score",240,listOf(c("cover","The Score - The Fear cover"),c("official","The Fear","The Score - Topic")))
  assertEquals("official",result.first().candidate.id);assertTrue(result.first().trusted);assertFalse(result.last().trusted)
 }
 @Test fun unrelatedSongWithSameArtistIsNeverAutoImported() {
  assertFalse(MusicTrackMatcher.rank("The Fear","The Score",240,listOf(c("wrong","The Heat"))).single().trusted)
 }
 @Test fun remixAndDurationMismatchStayPending() {
  assertTrue(MusicTrackMatcher.rank("The Fear","The Score",240,listOf(c("remix","The Fear remix"),c("long","The Fear",duration=270))).none{it.trusted})
 }
 @Test fun requestedVersionMayMatchButUnknownDurationCannot() {
  assertTrue(MusicTrackMatcher.rank("The Fear acoustic","The Score",240,listOf(c("acoustic","The Fear acoustic"))).single().trusted)
  assertFalse(MusicTrackMatcher.rank("The Fear","The Score",240,listOf(c("unknown","The Fear",duration=-1))).single().trusted)
 }
 @Test fun accentsPunctuationAndDuplicateVideoIdsAreHandled() {
  val row=MusicTrackMatcher.Candidate("id","Açúcar! (Official Audio)","João - Topic",180)
  val result=MusicTrackMatcher.rank("Açúcar","João",180,listOf(row,row))
  assertEquals(1,result.size);assertTrue(result.single().trusted)
 }
}
