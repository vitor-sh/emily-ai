package com.emily.music

import android.content.Context
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.ClearCredentialStateRequest
import androidx.credentials.CustomCredential
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.GoogleAuthProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.tasks.await
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Independent Music API: no personal bridge token and no YouTube key in the APK. */
internal object MusicCloud {
    private val http=OkHttpClient.Builder().callTimeout(12,TimeUnit.SECONDS).connectTimeout(6,TimeUnit.SECONDS)
        .followRedirects(false).followSslRedirects(false).build()
    private val auth get()=FirebaseAuth.getInstance()
    fun configured()=BuildConfig.MUSIC_CLOUD_URL.isNotBlank()
    fun currentUser()=auth.currentUser
    fun observeAccount(listener:(String?)->Unit):()->Unit {
        var previous=auth.currentUser?.uid
        val callback=FirebaseAuth.AuthStateListener {
            val next=it.currentUser?.uid
            if(previous!=next){EmilyMusicService.logoutPlayback();EmilyMusicLibrary.close();EmilyMusicAudio.clearCache();EmilyMusicSearch.clearCache();previous=next}
            listener(next)
        }
        auth.addAuthStateListener(callback)
        return {auth.removeAuthStateListener(callback)}
    }
    private fun prefs(context:Context)=context.getSharedPreferences("music-account",Context.MODE_PRIVATE)
    fun locallyApproved(context:Context):Boolean {
        val uid=auth.currentUser?.uid ?: return false
        return prefs(context).getString("approved-uid",null)==uid
    }
    suspend fun authorize(context:Context) {
        val user=auth.currentUser ?: error("Entre com Google.")
        val manager=context.applicationContext.getSystemService(android.net.ConnectivityManager::class.java)
        val capabilities=manager?.getNetworkCapabilities(manager.activeNetwork)
        val online=capabilities?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED)==true
        if(!online && locallyApproved(context))return
        val base=BuildConfig.MUSIC_CLOUD_URL.trim().trimEnd('/')
        val uri=android.net.Uri.parse(base)
        require(uri.scheme=="https" && !uri.host.isNullOrBlank() && uri.userInfo==null && uri.query==null && uri.fragment==null){"Servidor Music inválido."}
        suspend fun send(force:Boolean):Pair<Int,String> {
            val token=user.getIdToken(force).await().token ?: error("Entre novamente com Google.")
            check(auth.currentUser?.uid==user.uid){"A conta mudou. Entre novamente."}
            return withContext(Dispatchers.IO) {
                http.newCall(Request.Builder().url("$base/v1/account").header("Authorization","Bearer $token").build()).execute().use {r->r.code to (r.body?.string()?:"")}
            }
        }
        var response=send(false)
        if(response.first==401)response=send(true)
        check(auth.currentUser?.uid==user.uid){"A conta mudou. Entre novamente."}
        if(response.first==401 || response.first==403) {
            signOut(context)
            error(if(response.first==403)"Esta conta ainda não foi autorizada para a beta." else "Sessão expirada. Entre novamente.")
        }
        check(response.first==200){"Não foi possível confirmar a conta. Verifique sua conexão."}
        check(auth.currentUser?.uid==user.uid && JSONObject(response.second).getString("uid")==user.uid){"A conta mudou. Entre novamente."}
        prefs(context).edit().putString("approved-uid",user.uid).apply()
    }
    fun accountKey():String=auth.currentUser?.uid ?: error("Entre com Google no Emily Music para pesquisar.")
    suspend fun signIn(context:Context) {
        val resource=context.resources.getIdentifier("default_web_client_id","string",context.packageName)
        check(resource!=0){"O login Google ainda precisa ser configurado no Firebase."}
        val option=GetGoogleIdOption.Builder().setServerClientId(context.getString(resource))
            .setFilterByAuthorizedAccounts(false).setAutoSelectEnabled(false).build()
        val result=CredentialManager.create(context).getCredential(context,GetCredentialRequest.Builder().addCredentialOption(option).build())
        val credential=result.credential
        check(credential is CustomCredential && credential.type==GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL){"Não foi possível confirmar a conta Google."}
        val id=GoogleIdTokenCredential.createFrom(credential.data).idToken
        auth.signInWithCredential(GoogleAuthProvider.getCredential(id,null)).await()
        EmilyMusicSearch.clearCache()
    }
    suspend fun signOut(context:Context) {
        withContext(Dispatchers.Main.immediate) {EmilyMusicService.logoutPlayback()}
        androidx.work.WorkManager.getInstance(context.applicationContext).cancelAllWorkByTag("emily-music-download")
        prefs(context).edit().remove("approved-uid").apply()
        auth.signOut();EmilyMusicSearch.clearCache();EmilyMusicAudio.clearCache();EmilyMusicLibrary.close()
        try {CredentialManager.create(context).clearCredentialState(ClearCredentialStateRequest())}
        catch(e:kotlinx.coroutines.CancellationException){throw e}
        catch(_:androidx.credentials.exceptions.ClearCredentialException){ /* Firebase is already signed out. */ }
    }
    suspend fun syncLibrary(uid:String,fields:JSONObject,revision:Long):JSONObject=withContext(Dispatchers.IO) {
        val user=auth.currentUser ?: error("Entre com Google.")
        check(user.uid==uid){"A conta mudou."}
        val base=BuildConfig.MUSIC_CLOUD_URL.trimEnd('/')
        suspend fun send(force:Boolean):Pair<Int,String> {
            val token=user.getIdToken(force).await().token ?: error("Sessão expirada")
            check(auth.currentUser?.uid==uid)
            val body=JSONObject().put("fields",fields).put("revision",revision).toString().toRequestBody("application/json".toMediaType())
            http.newCall(Request.Builder().url("$base/v1/music/library").header("Authorization","Bearer $token").post(body).build()).execute().use {r->return r.code to (r.body?.string()?:"")}
        }
        var response=send(false);if(response.first==401)response=send(true)
        check(auth.currentUser?.uid==uid)
        check(response.first==200){if(response.first==400)"Biblioteca excedeu os limites de sincronização." else "Sincronização pendente. Tentarei novamente."}
        JSONObject(response.second)
    }
    suspend fun search(query:String,latest:Boolean=false):JSONObject=withContext(Dispatchers.IO) {
        val base=BuildConfig.MUSIC_CLOUD_URL.trim().trimEnd('/')
        val uri=android.net.Uri.parse(base)
        require(uri.scheme=="https" && !uri.host.isNullOrBlank() && uri.userInfo==null && uri.query==null && uri.fragment==null){"Servidor Music inválido."}
        val user=auth.currentUser ?: error("Entre com Google no Emily Music para pesquisar.")
        suspend fun send(force:Boolean):Pair<Int,String> {
            val token=user.getIdToken(force).await().token ?: error("Entre novamente com Google.")
            check(auth.currentUser?.uid==user.uid){"A conta mudou. Pesquise novamente."}
            val body=JSONObject().put("query",query).put("mode",if(latest)"latest" else "search").toString().toRequestBody("application/json".toMediaType())
            val call=http.newCall(Request.Builder().url("$base/v1/music/search").header("Authorization","Bearer $token").post(body).build())
            call.execute().use {r->return r.code to (r.body?.string()?:"")}
        }
        var response=send(false)
        if(response.first==401)response=send(true)
        check(auth.currentUser?.uid==user.uid){"A conta mudou. Pesquise novamente."}
        when(response.first) {
            200->JSONObject(response.second).also {result->
                val tracks=result.getJSONArray("resultados")
                for(i in 0 until tracks.length()) {
                    val track=tracks.getJSONObject(i)
                    track.put("titulo",android.text.Html.fromHtml(track.getString("titulo"),android.text.Html.FROM_HTML_MODE_LEGACY).toString().take(120))
                }
            }
            401->error("Sessão expirada. Entre novamente com Google.")
            403->error("Esta conta ainda não foi autorizada para a beta.")
            429->error("Limite de buscas atingido. Tente mais tarde.")
            else->error("Servidor de busca indisponível. Tente novamente em instantes.")
        }
    }
}
