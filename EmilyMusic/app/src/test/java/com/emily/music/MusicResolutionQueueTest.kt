package com.emily.music

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class MusicResolutionQueueTest {
    @Test fun selectingPreparedSongKeepsItAliveWhenPreparationWaiterCloses()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var calls=0
        val queue=MusicResolutionQueue(scope,{_:String->true}){id->calls++;started.complete(Unit);release.await();id}
        try {
            val prep=launch{queue.resolve("chosen",false)};started.await()
            queue.selectPlayback("chosen");prep.cancelAndJoin()
            val clicked=async{queue.resolve("chosen")};yield();release.complete(Unit)
            assertEquals("chosen",clicked.await());assertEquals(1,calls)
        } finally {scope.cancel()}
    }
    @Test fun rapidSelectionCancelsOldPlayback()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val cancelled=CompletableDeferred<Unit>()
        val queue=MusicResolutionQueue(scope,{_:String->true}) {id->
            if(id=="old"){started.complete(Unit);try{awaitCancellation()}finally{cancelled.complete(Unit)}}
            id
        }
        try {
            queue.selectPlayback("old");val old=async {queue.resolve("old")};started.await()
            queue.selectPlayback("skipped");queue.selectPlayback("latest")
            withTimeout(1000){cancelled.await()}
            assertEquals("latest",withTimeout(1000){queue.resolve("latest")})
            old.join();assertTrue(old.isCancelled)
            queue.selectPlayback(null);assertEquals("other",queue.resolve("other"))
        } finally {scope.cancel()}
    }
    @Test fun playerCanBufferNextBeforeTransitionAndAutomaticTransitionKeepsIt()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        val queue=MusicResolutionQueue(scope,{_:String->true}) {id->if(id=="next"){started.complete(Unit);release.await()};id}
        try {
            queue.selectPlayback("current")
            val next=async{queue.resolve("next")};withTimeout(1000){started.await()}
            queue.selectPlayback("next",cancelObsolete=false)
            release.complete(Unit);assertEquals("next",next.await())
            assertEquals("later",queue.resolve("later"))
        } finally {release.complete(Unit);scope.cancel()}
    }
    @Test fun preparingCannotCompeteWithPendingPlayback()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        val queue=MusicResolutionQueue(scope,{_:String->true}) {id->started.complete(Unit);release.await();id}
        try {
            val clicked=async{queue.resolve("clicked")};started.await()
            assertThrows(CancellationException::class.java){runBlocking{queue.resolve("background",false)}}
            release.complete(Unit);assertEquals("clicked",clicked.await())
        } finally {release.complete(Unit);scope.cancel()}
    }
    @Test fun clearingWhileOldWorkFinishesCannotPopulateNewAccountCache()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        val calls=java.util.concurrent.atomic.AtomicInteger()
        val queue=MusicResolutionQueue(scope,{_:String->true}) {
            if(calls.incrementAndGet()==1){started.complete(Unit);withContext(NonCancellable){release.await()};"old"}else "new"
        }
        try {
            val old=async {queue.resolve("same")};started.await();queue.clear()
            assertEquals("new",queue.resolve("same"));release.complete(Unit)
            old.join()
            assertEquals("new",queue.resolve("same"));assertEquals(2,calls.get())
        } finally {release.complete(Unit);scope.cancel()}
    }
    @Test fun foregroundPreemptsDifferentPreparationAndSharesSameTrack()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val cancelled=CompletableDeferred<Unit>()
        val release=CompletableDeferred<Unit>();var calls=0
        val queue=MusicResolutionQueue(scope,{_:String->true}) {id->
            if(id=="background"){started.complete(Unit);try{awaitCancellation()}finally{cancelled.complete(Unit)}}
            else {calls++;release.await();id}
        }
        try {
            val bg=async {queue.resolve("background",false)};started.await()
            val first=async {queue.resolve("clicked")}
            withTimeout(1000){cancelled.await()}
            val same=async {queue.resolve("clicked")};yield();release.complete(Unit)
            assertEquals("clicked",first.await());assertEquals("clicked",same.await());assertEquals(1,calls)
            bg.join()
            assertTrue(bg.isCancelled)
        } finally {scope.cancel()}
    }
    @Test fun promotesSamePreparationWithoutRestartingAndClearsOldAccountResults()=runBlocking {
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
        val started=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>();var calls=0
        val queue=MusicResolutionQueue(scope,{_:String->true}){id->calls++;started.complete(Unit);release.await();id}
        try {
            val prepared=async {queue.resolve("same",false)};started.await()
            val clicked=async {queue.resolve("same")};yield();release.complete(Unit)
            assertEquals("same",clicked.await());assertEquals("same",prepared.await());assertEquals(1,calls)
            assertEquals("same",queue.resolve("same"));assertEquals(1,calls)
            queue.clear();assertEquals("same",queue.resolve("same"));assertEquals(2,calls)
        } finally {scope.cancel()}
    }
}
