package com.emily.music
import java.security.MessageDigest
internal object MusicAccountPaths {
    fun key(uid:String):String {
        require(uid.isNotBlank() && uid.length<=128)
        return MessageDigest.getInstance("SHA-256").digest(uid.toByteArray(Charsets.UTF_8)).joinToString(""){"%02x".format(it)}
    }
}
