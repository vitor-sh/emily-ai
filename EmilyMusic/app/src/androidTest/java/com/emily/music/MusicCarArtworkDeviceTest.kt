package com.emily.music

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume
import org.junit.Test
import java.io.File
import java.security.MessageDigest

class MusicCarArtworkDeviceTest {
    @Test fun localArtworkCollageIsSquareCachedAndIsolatedByAccount() {
        val ctx=InstrumentationRegistry.getInstrumentation().targetContext
        Assume.assumeTrue(MusicCloud.locallyApproved(ctx))
        EmilyMusicLibrary.init(ctx)
        val library=EmilyMusicLibrary.session();val files=mutableListOf<File>();val artifacts=mutableListOf<Uri>()
        val colors=listOf(Color.RED,Color.GREEN,Color.BLUE,Color.YELLOW)
        try {
            val tracks=colors.mapIndexed{index,color->
                val key=MessageDigest.getInstance("SHA-256").digest("car-art-fixture-$index-${System.nanoTime()}".toByteArray()).joinToString(""){"%02x".format(it)}
                val file=File(library.covers,"playlist-$key.png");files.add(file)
                val bitmap=Bitmap.createBitmap(320,180,Bitmap.Config.ARGB_8888);bitmap.eraseColor(color);file.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)};bitmap.recycle()
                JSONObject().put("video_id","aaaaaaaaaa$index").put("thumb","https://appassets.androidplatform.net/art/${library.accountId}/${file.name}")
            }
            val collage=MusicCarArtwork.cover(library,"",tracks);artifacts.add(collage)
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,ctx.checkUriPermission(collage,0,2000,android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION))
            ctx.grantUriPermission("com.android.shell",collage,android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)
            try {assertEquals(android.content.pm.PackageManager.PERMISSION_GRANTED,ctx.checkUriPermission(collage,0,2000,android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION))}
            finally {ctx.revokeUriPermission("com.android.shell",collage,android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION)}
            assertEquals(android.content.pm.PackageManager.PERMISSION_DENIED,ctx.checkUriPermission(collage,0,2000,android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION))
            repeat(2){ctx.contentResolver.openInputStream(collage)!!.use{stream->
                val image=BitmapFactory.decodeStream(stream);assertNotNull(image);assertEquals(512,image.width);assertEquals(512,image.height)
                listOf(128 to 128,384 to 128,128 to 384,384 to 384).forEachIndexed{n,(x,y)->
                    val actual=image.getPixel(x,y);val expected=colors[n]
                    assertTrue(kotlin.math.abs(Color.red(actual)-Color.red(expected))<10)
                    assertTrue(kotlin.math.abs(Color.green(actual)-Color.green(expected))<10)
                    assertTrue(kotlin.math.abs(Color.blue(actual)-Color.blue(expected))<10)
                };image.recycle()
            }}
            val single=MusicCarArtwork.cover(library,tracks.first().getString("thumb"),tracks);artifacts.add(single)
            ctx.contentResolver.openInputStream(single)!!.use{val image=BitmapFactory.decodeStream(it);assertTrue(Color.red(image.getPixel(384,384))>240);assertTrue(Color.green(image.getPixel(384,384))<10);image.recycle()}
            try{ctx.contentResolver.openInputStream(Uri.parse("content://${ctx.packageName}.car-art/wrong-account/${collage.lastPathSegment}"));fail("Wrong account")}
            catch(_:java.io.FileNotFoundException){}
            try{ctx.contentResolver.openOutputStream(collage);fail("Read only")}
            catch(_:java.io.FileNotFoundException){}
            // Root tabs use resources, while cards use protected artwork; never file:// or WebView URLs.
            val catalog=MusicCarCatalog(library)
            val tabs=catalog.children(MusicCarCatalog.ROOT)
            assertTrue(tabs.all{it.mediaMetadata.artworkUri!!.scheme=="android.resource"})
            val cards=catalog.children(MusicCarCatalog.PLAYLISTS)
            assertEquals("Todas",cards.first().mediaMetadata.title.toString())
            assertTrue(cards.all{it.mediaMetadata.subtitle.isNullOrEmpty()})
            assertTrue(cards.none{it.mediaMetadata.artworkUri!!.scheme=="file"})
            val preview=Bitmap.createBitmap(960,340,Bitmap.Config.ARGB_8888);val canvas=android.graphics.Canvas(preview);canvas.drawColor(Color.rgb(31,29,33));val paint=android.graphics.Paint(android.graphics.Paint.ANTI_ALIAS_FLAG)
            paint.color=Color.WHITE;paint.textSize=24f
            cards.take(3).forEachIndexed{n,card->
                ctx.contentResolver.openInputStream(card.mediaMetadata.artworkUri!!)!!.use{input->
                    val art=BitmapFactory.decodeStream(input);assertNotNull(art)
                    canvas.drawBitmap(art,null,android.graphics.RectF(n*320f+16,16f,n*320f+304,304f),paint);art.recycle()
                }
                canvas.drawText(card.mediaMetadata.title.toString().take(20),n*320f+16,334f,paint)
            }
            File(ctx.getExternalFilesDir(null),"car-art-preview.jpg").outputStream().use{preview.compress(Bitmap.CompressFormat.JPEG,90,it)};preview.recycle()
        }finally{
            files.forEach{it.delete()}
            artifacts.forEach{uri->val key=uri.lastPathSegment;File(library.covers,"car/$key.json").delete();File(library.covers,"car/$key.jpg").delete()}
        }
    }
}
