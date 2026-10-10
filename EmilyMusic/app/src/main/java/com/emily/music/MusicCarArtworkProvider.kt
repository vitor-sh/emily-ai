package com.emily.music

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.graphics.*
import android.net.Uri
import android.os.ParcelFileDescriptor
import org.json.JSONObject
import java.io.File
import java.io.FileNotFoundException
import java.util.concurrent.TimeUnit

/** Granted cover URIs only. Work is bounded and runs on the pipe writer, never the main thread. */
class MusicCarArtworkProvider:ContentProvider() {
    companion object {private val locks=Array(32){Any()}}
    override fun onCreate()=true
    override fun getType(uri:Uri)="image/jpeg"
    override fun openFile(uri:Uri,mode:String):ParcelFileDescriptor {
        if(mode!="r")throw FileNotFoundException("Somente leitura")
        val (library,descriptor)=MusicCarArtwork.descriptor(context!!,uri)
        return openPipeHelper(uri,"image/jpeg",null,descriptor){out,_,_,_,value->
            val file=requireNotNull(value)
            runCatching{ParcelFileDescriptor.AutoCloseOutputStream(out).use{stream->
                if(library.closed||MusicCloud.currentUser()?.uid!=library.uid)throw FileNotFoundException("Conta mudou")
                synchronized(locks[(file.path.hashCode() and Int.MAX_VALUE)%locks.size]){
                val cached=File(file.parentFile,file.nameWithoutExtension+".jpg")
                if(cached.isFile){cached.inputStream().use{it.copyTo(stream)}} else {
                    val info=JSONObject(file.readText());val sources=info.getJSONArray("images")
                    val images=(0 until sources.length().coerceAtMost(4)).mapNotNull{n->load(sources.getString(n),library,library.online())}
                    val result=render(images,info.optString("kind"))
                    try {
                        // Do not permanently cache a temporary network failure or incomplete collage.
                        if(images.size==sources.length()){val atomic=android.util.AtomicFile(cached);val target=atomic.startWrite();try{result.compress(Bitmap.CompressFormat.JPEG,88,target);atomic.finishWrite(target)}catch(e:Exception){atomic.failWrite(target);throw e}}
                        if(library.closed||MusicCloud.currentUser()?.uid!=library.uid)throw FileNotFoundException("Conta mudou")
                        result.compress(Bitmap.CompressFormat.JPEG,88,stream)
                    } finally {result.recycle();images.forEach{it.recycle()}}
                }
            }}}
        }
    }
    private val http by lazy{okhttp3.OkHttpClient.Builder().connectTimeout(2,TimeUnit.SECONDS).readTimeout(2,TimeUnit.SECONDS).callTimeout(3,TimeUnit.SECONDS).followRedirects(false).build()}
    private fun load(source:String,library:MusicLibrarySession,online:Boolean):Bitmap?=runCatching{
        val bytes=if(source.startsWith("local:")){
            val name=source.removePrefix("local:");require(name.matches(Regex("(?:local_[a-f0-9]{64}|[A-Za-z0-9_-]{11}|playlist-[a-f0-9]{64})\\.(?:jpg|png|webp)")))
            val file=File(library.covers,name);require(file.length() in 1..2_000_000);file.readBytes()
        }else{
            if(!online)return null
            val uri=Uri.parse(source)
            // No credentials, redirects or arbitrary local-network requests from imported cover data.
            require(uri.scheme=="https"&&uri.host in setOf("i.ytimg.com","img.youtube.com","i.scdn.co","mosaic.scdn.co","image-cdn-ak.spotifycdn.com")&&uri.userInfo==null)
            http.newCall(okhttp3.Request.Builder().url(source).build()).execute().use{response->
                require(response.isSuccessful);val body=response.body?:return null;val stream=body.byteStream();val output=java.io.ByteArrayOutputStream();val buffer=ByteArray(8192)
                while(true){val count=stream.read(buffer);if(count<0)break;require(output.size()+count<=2_000_000);output.write(buffer,0,count)};output.toByteArray()
            }
        }
        val options=BitmapFactory.Options().apply{inJustDecodeBounds=true};BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
        require(options.outWidth>0&&options.outHeight>0);options.inSampleSize=1
        while(options.outWidth/options.inSampleSize>512||options.outHeight/options.inSampleSize>512)options.inSampleSize*=2
        options.inJustDecodeBounds=false;BitmapFactory.decodeByteArray(bytes,0,bytes.size,options)
    }.getOrNull()
    internal fun render(images:List<Bitmap>,kind:String):Bitmap {
        val bitmap=Bitmap.createBitmap(512,512,Bitmap.Config.ARGB_8888);val canvas=Canvas(bitmap);val paint=Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
        paint.shader=LinearGradient(0f,0f,512f,512f,intArrayOf(Color.rgb(89,43,39),Color.rgb(35,29,38)),null,Shader.TileMode.CLAMP);canvas.drawRect(0f,0f,512f,512f,paint);paint.shader=null
        if(images.isNotEmpty()){
            val cells=if(images.size==1)listOf(RectF(0f,0f,512f,512f)) else if(images.size==2)listOf(RectF(0f,0f,256f,512f),RectF(256f,0f,512f,512f)) else listOf(RectF(0f,0f,256f,256f),RectF(256f,0f,512f,256f),RectF(0f,256f,256f,512f),RectF(256f,256f,512f,512f))
            cells.forEachIndexed{n,target->val image=images[n%images.size];val scale=maxOf(target.width()/image.width,target.height()/image.height);val width=target.width()/scale;val height=target.height()/scale
                val source=Rect(((image.width-width)/2).toInt(),((image.height-height)/2).toInt(),((image.width+width)/2).toInt(),((image.height+height)/2).toInt());canvas.drawBitmap(image,source,target,paint)}
        }else{
            val res=when(kind){"all"->R.drawable.ic_car_all;"favorites"->R.drawable.ic_car_favorites;"downloads"->R.drawable.ic_car_downloads;"locals"->R.drawable.ic_car_locals;"track"->R.drawable.ic_music;else->R.drawable.ic_car_playlists}
            context!!.getDrawable(res)!!.mutate().apply{setTint(Color.rgb(241,199,165));setBounds(176,176,336,336);draw(canvas)}
        }
        return bitmap
    }
    override fun query(uri:Uri,projection:Array<out String>?,selection:String?,selectionArgs:Array<out String>?,sortOrder:String?):Cursor?=null
    override fun insert(uri:Uri,values:ContentValues?):Uri?=throw UnsupportedOperationException("Somente leitura")
    override fun delete(uri:Uri,selection:String?,selectionArgs:Array<out String>?):Int=throw UnsupportedOperationException("Somente leitura")
    override fun update(uri:Uri,values:ContentValues?,selection:String?,selectionArgs:Array<out String>?):Int=throw UnsupportedOperationException("Somente leitura")
}
