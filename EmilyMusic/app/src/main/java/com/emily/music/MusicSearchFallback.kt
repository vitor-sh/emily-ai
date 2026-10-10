package com.emily.music

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withTimeoutOrNull

/** Only provider failures may use the reserve; cancellation/session changes must stop. */
internal suspend fun <T : Any> musicSearchWithFallback(
    checkSession: () -> Unit,
    primary: suspend () -> T,
    reserve: suspend () -> T,
    timeoutMillis: Long = 8_000L,
): T {
    checkSession()
    val first = try {
        withTimeoutOrNull(timeoutMillis) { primary() }
    } catch (e: CancellationException) {
        throw e
    } catch (_: Exception) {
        null
    }
    checkSession()
    val result = first ?: reserve()
    checkSession()
    return result
}
