package com.emily.music

import androidx.media3.common.MediaItem
import androidx.media3.common.Player

/** Edit the native timeline in place so the current audio never restarts. */
internal object MusicQueueEditor {
 fun apply(player:Player,requested:List<MediaItem>,expectedCurrent:String):Boolean {
  if(player.currentMediaItem?.mediaId.orEmpty()!=expectedCurrent)return false
  require(requested.size<=200&&requested.map{it.mediaId}.distinct().size==requested.size)
  val desired=requested.toMutableList()
  val current=player.currentMediaItem
  if(current!=null&&desired.none{it.mediaId==current.mediaId})desired.add(player.currentMediaItemIndex.coerceIn(0,desired.size),current)
  val ids=desired.map{it.mediaId}.toSet()
  for(index in player.mediaItemCount-1 downTo 0)if(player.getMediaItemAt(index).mediaId !in ids)player.removeMediaItem(index)
  desired.forEachIndexed {index,item->
   val old=(0 until player.mediaItemCount).firstOrNull{player.getMediaItemAt(it).mediaId==item.mediaId}
   if(old==null)player.addMediaItem(index,item) else if(old!=index)player.moveMediaItem(old,index)
  }
  return true
 }
}
