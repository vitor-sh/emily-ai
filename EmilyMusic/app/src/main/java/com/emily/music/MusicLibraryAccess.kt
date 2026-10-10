package com.emily.music
import android.content.Context
import android.net.Uri
import org.json.JSONObject
import org.json.JSONArray
import java.io.File

/** Each instance owns its disk, observers and jobs; old work never writes a new account. */
object EmilyMusicLibrary {
    const val LOCALS="__locais__"
    @Volatile private var active:MusicLibrarySession?=null
    @Synchronized fun init(context:Context) {
        val uid=MusicCloud.accountKey()
        check(MusicCloud.locallyApproved(context)){"Entre no Emily Music."}
        if(active?.uid==uid && active?.closed==false)return
        active?.close()
        active=MusicLibrarySession(context.applicationContext,uid)
    }
    @Synchronized fun close() {active?.close();active=null}
    internal fun session():MusicLibrarySession {
        val current=active ?: error("Entre no Emily Music.")
        check(!current.closed && current.uid==MusicCloud.currentUser()?.uid){"A conta mudou. Abra novamente o Music."}
        return current
    }
    internal fun forAccount(uid:String):MusicLibrarySession=session().also {check(it.uid==uid){"A conta mudou."}}
    val covers:File get()=session().covers
    val folder:File get()=session().folder
    val accountId:String get()=session().accountId
    var notice:String get()=session().notice;set(v){session().notice=v}
    var playbackNotice:String get()=session().playbackNotice;set(v){session().playbackNotice=v}
    fun context()=session().context()
    fun online()=session().online()
    fun library()=session().library()
    fun selected(n:String)=session().selected(n)
    fun mutate(m:String,a:JSONArray)=session().mutate(m,a)
    fun playerState()=session().playerState()
    fun settingsRevision()=session().settingsRevision()
    fun savePlayer(p:JSONObject)=session().savePlayer(p)
    fun localUri(id:String):Uri?=session().localUri(id)
    fun offline()=session().offline()
    suspend fun scan()=session().scan()
    fun addFolder(uri:Uri)=session().addFolder(uri)
}
