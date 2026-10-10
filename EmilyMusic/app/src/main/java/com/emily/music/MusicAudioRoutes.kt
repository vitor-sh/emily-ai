package com.emily.music

import android.content.Context
import android.media.MediaRouter
import android.media.MediaRouter2
import android.media.AudioManager
import android.media.AudioDeviceInfo
import android.os.Build

/** System-managed local outputs; no microphone, Bluetooth scanning or global audio mode. */
internal class MusicAudioRoutes(private val context:Context) {
    private val router=context.getSystemService(MediaRouter::class.java)
    fun hasExternalOutput():Boolean=runCatching {
        context.getSystemService(AudioManager::class.java).getDevices(AudioManager.GET_DEVICES_OUTPUTS)
            .any { it.type in externalOutputTypes }
    }.getOrDefault(false)
    fun currentName():String=runCatching {router.getSelectedRoute(MediaRouter.ROUTE_TYPE_LIVE_AUDIO)?.getName(context)?.toString().orEmpty().ifBlank {"Saída de áudio"}}.getOrDefault("Saída de áudio")
    fun outputs():List<MediaRouter.RouteInfo> = runCatching {(0 until router.routeCount).map {router.getRouteAt(it)}
        .filter {it.isEnabled && it.playbackType==0 && it.supportedTypes and MediaRouter.ROUTE_TYPE_LIVE_AUDIO!=0}}.getOrDefault(emptyList())
    data class Output(val route:MediaRouter.RouteInfo,val label:String,val selected:Boolean)
    fun choices()=outputs().map {Output(it,name(it),selected(it))}
    fun selected(route:MediaRouter.RouteInfo)=runCatching {route===router.getSelectedRoute(MediaRouter.ROUTE_TYPE_LIVE_AUDIO)}.getOrDefault(false)
    fun name(route:MediaRouter.RouteInfo)=runCatching {route.getName(context).toString()}.getOrDefault("Dispositivo de áudio")
    fun select(route:MediaRouter.RouteInfo) {
        check(outputs().any {it===route}){"Este dispositivo desconectou. Escolha outra saída."}
        router.selectRoute(MediaRouter.ROUTE_TYPE_LIVE_AUDIO,route)
    }
    fun openSystemPicker():Boolean=Build.VERSION.SDK_INT>=34 && runCatching {MediaRouter2.getInstance(context).showSystemOutputSwitcher()}.getOrDefault(false)
    private companion object {
        val externalOutputTypes=setOf(
            AudioDeviceInfo.TYPE_BLUETOOTH_A2DP, AudioDeviceInfo.TYPE_BLUETOOTH_SCO,
            AudioDeviceInfo.TYPE_BLE_HEADSET, AudioDeviceInfo.TYPE_BLE_SPEAKER,
            AudioDeviceInfo.TYPE_HEARING_AID, AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES, AudioDeviceInfo.TYPE_USB_DEVICE,
            AudioDeviceInfo.TYPE_USB_HEADSET, AudioDeviceInfo.TYPE_USB_ACCESSORY,
            AudioDeviceInfo.TYPE_HDMI, AudioDeviceInfo.TYPE_HDMI_ARC,
            AudioDeviceInfo.TYPE_HDMI_EARC, AudioDeviceInfo.TYPE_DOCK,
            AudioDeviceInfo.TYPE_LINE_ANALOG, AudioDeviceInfo.TYPE_LINE_DIGITAL
        )
    }
}
