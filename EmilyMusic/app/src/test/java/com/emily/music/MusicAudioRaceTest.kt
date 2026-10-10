package com.emily.music

import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import java.io.IOException

class MusicAudioRaceTest {
 @Test fun fastPrimaryDoesNotStartReserve()=runBlocking {
  var reserve=false
  assertEquals("fast",musicAudioRace(1000,primary={"fast"},reserve={reserve=true;"slow"}))
  assertFalse(reserve)
 }
 @Test fun slowPrimaryIsCancelledWhenReserveWins()=runBlocking {
  val cancelled=CompletableDeferred<Unit>()
  assertEquals("reserve",musicAudioRace(10,primary={try{awaitCancellation()}finally{cancelled.complete(Unit)}},reserve={"reserve"}))
  assertTrue(cancelled.isCompleted)
 }
 @Test fun oneFailureDoesNotAbortWorkingAlternative()=runBlocking {
  assertEquals("reserve",withTimeout(500){musicAudioRace(10000,primary={throw IOException("one song unavailable")},reserve={"reserve"})})
  assertEquals("primary",musicAudioRace(1,primary={delay(30);"primary"},reserve={throw IOException("reserve failed")}))
 }
 @Test fun cancellingSelectionCancelsBothExtractors()=runBlocking {
  val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
  val started=CompletableDeferred<Unit>();val ended=java.util.concurrent.atomic.AtomicInteger()
  try {val job=scope.launch {musicAudioRace(1,primary={try{awaitCancellation()}finally{ended.incrementAndGet()}},reserve={started.complete(Unit);try{awaitCancellation()}finally{ended.incrementAndGet()}})}
   withTimeout(1000){started.await()};job.cancelAndJoin();assertEquals(2,ended.get())
  }finally{scope.cancel()}
 }
}
