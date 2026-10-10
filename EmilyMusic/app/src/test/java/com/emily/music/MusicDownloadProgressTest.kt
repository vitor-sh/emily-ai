package com.emily.music
import org.junit.Assert.*
import org.junit.Test
class MusicDownloadProgressTest {
 @Test fun unknownProcessingAndInvalidValuesNeverBecomeNegativePercentages(){
  for(v in listOf(-1f,Float.NaN,Float.POSITIVE_INFINITY,Float.NEGATIVE_INFINITY))assertNull(MusicDownloadProgress.percent(v))
  assertNull(MusicDownloadProgress.percent(-1));assertEquals(0,MusicDownloadProgress.percent(0f));assertEquals(42,MusicDownloadProgress.percent(42.9f));assertEquals(100,MusicDownloadProgress.percent(150f))
 }
}
