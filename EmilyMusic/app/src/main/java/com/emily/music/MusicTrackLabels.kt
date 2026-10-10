package com.emily.music

import org.json.JSONArray
import org.json.JSONObject

/** A presentation copy: saved and synced originals, IDs and audio URLs are untouched. */
internal fun musicTrackLabels(value:Any?):Any?=when(value) {
    is JSONObject->JSONObject().apply {
        value.keys().forEach {key->put(key,musicTrackLabels(value.opt(key)))}
        if(value.optString("title_source")!="spotify"&&value.has("video_id")&&!value.optBoolean("local")&&!value.optString("video_id").startsWith("local_")) {
            val raw=value.optString("titulo")
            val title=MusicTrackTitle.display(raw)
            if(title!=raw){put("titulo",title);if(optString("titulo_original").isBlank())put("titulo_original",raw)}
        }
    }
    is JSONArray->JSONArray((0 until value.length()).map {musicTrackLabels(value.opt(it))})
    else->value
}
