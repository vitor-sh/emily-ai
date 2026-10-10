package com.emily.music

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import java.io.FileNotFoundException

/** Public, read-only packaged icons. No filesystem paths or account data are exposed. */
class MusicCarIconProvider:ContentProvider() {
    private val names=setOf("home","back","play","playlists","favorites","downloads","locals","all")
    override fun onCreate()=true
    private fun name(uri:Uri):String {
        val name=uri.pathSegments.singleOrNull()
        if(uri.authority!="${context!!.packageName}.car-icons"||name !in names||uri.query!=null)
            throw FileNotFoundException("Ícone desconhecido")
        return name!!
    }
    override fun getType(uri:Uri):String {name(uri);return "image/png"}
    override fun openFile(uri:Uri,mode:String):ParcelFileDescriptor {
        if(mode!="r")throw FileNotFoundException("Somente leitura")
        val asset=name(uri)
        return openPipeHelper(uri,"image/png",null,asset){out,_,_,_,key->
            runCatching{ParcelFileDescriptor.AutoCloseOutputStream(out).use{stream->context!!.assets.open("car-icons/$key.png").use{it.copyTo(stream)}}}
        }
    }
    override fun query(uri:Uri,projection:Array<out String>?,selection:String?,selectionArgs:Array<out String>?,sortOrder:String?):Cursor? {name(uri);return null}
    override fun insert(uri:Uri,values:ContentValues?):Uri?=throw UnsupportedOperationException("Somente leitura")
    override fun delete(uri:Uri,selection:String?,selectionArgs:Array<out String>?):Int=throw UnsupportedOperationException("Somente leitura")
    override fun update(uri:Uri,values:ContentValues?,selection:String?,selectionArgs:Array<out String>?):Int=throw UnsupportedOperationException("Somente leitura")
}
