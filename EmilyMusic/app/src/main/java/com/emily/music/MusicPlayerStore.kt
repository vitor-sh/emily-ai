package com.emily.music

import android.util.AtomicFile
import org.json.JSONObject
import java.io.File

/** Playback checkpoint is small and independent of the full synchronized library. */
internal class MusicPlayerStore(file:File) {
    private val disk=AtomicFile(file)
    fun load(legacy:JSONObject):JSONObject {
        return runCatching {JSONObject(disk.openRead().bufferedReader().use {it.readText()})}.getOrElse {
            // Migrate before any library write can remove the legacy checkpoint.
            if(legacy.length()>0)write(legacy)
            JSONObject(legacy.toString())
        }
    }
    fun write(player:JSONObject) {
        val out=disk.startWrite()
        try {out.write(player.toString().toByteArray());disk.finishWrite(out)}
        catch(e:Exception){disk.failWrite(out);throw e}
    }
}
