// Field-wise last writer wins. Null tombstones prevent deleted tracks from reappearing.
export const MAX_LIBRARY_BYTES=1_500_000;
export function validateFields(fields,now=Date.now()) {
  if(!fields || typeof fields!=='object' || Array.isArray(fields) || Object.keys(fields).length>12000)throw new TypeError('Biblioteca inválida');
  const safe=Object.create(null);
  for(const [key,entry] of Object.entries(fields)) {
    let parts;try{parts=JSON.parse(key);}catch{throw new TypeError('Campo inválido');}
    if(!Array.isArray(parts)||!['playlist','track','favorite','pin','order','setting','listening'].includes(parts[0])||parts.some(p=>typeof p!=='string'||p.length>180)||parts.includes('__locais__'))throw new TypeError('Campo inválido');
    if(!entry || typeof entry!=='object' || !Number.isSafeInteger(entry.quando)||entry.quando<0||entry.quando>now+300000 || typeof entry.id!=='string'||entry.id.length>100 || !('valor' in entry))throw new TypeError('Revisão inválida');
    const v=entry.valor;
    if(parts[0]==='playlist' && (parts.length!==2 || (v!==null && (typeof v!=='object'||Array.isArray(v)||typeof v.foto!=='string'||(v.youtube_id!==undefined&&(typeof v.youtube_id!=='string'||(v.youtube_id!==''&&! /^[A-Za-z0-9_-]{10,100}$/.test(v.youtube_id))))||Object.keys(v).some(k=>!['foto','pending','youtube_id'].includes(k)) || (v.pending!==undefined && (!Array.isArray(v.pending)||v.pending.length>100||new Set(v.pending.map(t=>t?.spotify_id)).size!==v.pending.length||v.pending.some(t=>!t||typeof t!=='object'||Array.isArray(t)||! /^[A-Za-z0-9]{22}$/.test(t.spotify_id)||typeof t.title!=='string'||!t.title.trim()||t.title.length>300||typeof t.artists!=='string'||!t.artists.trim()||t.artists.length>500||!Number.isSafeInteger(t.duration)||t.duration<1||t.duration>86400||Object.keys(t).some(k=>!['spotify_id','title','artists','duration'].includes(k)))))))))throw new TypeError();
    if(parts[0]==='track' && (parts.length!==3 || (v!==null && (typeof v!=='object'||Array.isArray(v)||v.video_id!==parts[2]||typeof v.titulo!=='string'||v.titulo.length>300||Object.keys(v).some(k=>!['video_id','titulo','thumb','adicionada','local','duration','duracao','artist','artista'].includes(k))))))throw new TypeError();
    if(parts[0]==='pin' && (parts.length!==2 || (v!==null && typeof v!=='boolean')))throw new TypeError('Fixação inválida');
    if(parts[0]==='favorite' && (parts.length!==2 || (v!==null && typeof v!=='boolean')))throw new TypeError();
    if(parts[0]==='order' && (parts.length!==2 || (v!==null && (!Array.isArray(v)||v.length>200||v.some(id=>typeof id!=='string'||id.length>180)))))throw new TypeError();
    if(parts[0]==='setting' && (parts.length!==2 || !['volume','loop','shuffle'].includes(parts[1]) || (v!==null && typeof v!=='number' && typeof v!=='boolean')))throw new TypeError();
    if(parts[0]==='listening' && (parts.length!==2 || !/^[a-zA-Z0-9-]{8,80}$/.test(parts[1]) || (v!==null && (!Array.isArray(v)||v.length>200||new Set(v.map(t=>t?.video_id)).size!==v.length||v.some(t=>!t||typeof t!=='object'||Array.isArray(t)||! /^(?:[A-Za-z0-9_-]{11}|local_[a-f0-9]{64})$/.test(t.video_id)||typeof t.titulo!=='string'||t.titulo.length>300||typeof t.artist!=='string'||t.artist.length>180||typeof t.thumb!=='string'||t.thumb.length>500||!Number.isSafeInteger(t.count)||t.count<1||t.count>1000000000||!Number.isSafeInteger(t.last)||t.last<0||t.last>now+300000||Object.keys(t).some(k=>!['video_id','titulo','artist','thumb','count','last'].includes(k)))))))throw new TypeError('Histórico inválido');
    safe[key]={valor:v,quando:entry.quando,id:entry.id};
  }
  if(new TextEncoder().encode(JSON.stringify(safe)).length>MAX_LIBRARY_BYTES)throw new RangeError('Biblioteca muito grande');
  return safe;
}
export function mergeFields(left,right) {
  const merged=Object.assign(Object.create(null),left);
  for(const [key,v] of Object.entries(right)) {const old=merged[key];if(!old||v.quando>old.quando||(v.quando===old.quando&&v.id>old.id)) {
      // Older clients edit artwork without knowing the pending metadata field.
      // Explicit [] from a new client clears it; omitted data preserves it.
      const kind=JSON.parse(key)[0];
      if(kind==='playlist'&&v.valor!==null&&old?.valor){
        const value={...v.valor};for(const field of ['pending','youtube_id'])if(old.valor[field]!==undefined&&!Object.hasOwn(value,field))value[field]=old.valor[field];
        merged[key]={...v,valor:value};
      }else merged[key]=v;
    }}
  if(new TextEncoder().encode(JSON.stringify(merged)).length>MAX_LIBRARY_BYTES)throw new RangeError();
  return merged;
}
export async function syncLibrary(db,uid,incoming,now,knownRevision=-1) {
  for(let n=0;n<6;n++) {
    const row=await db.prepare('SELECT payload,revision FROM music_libraries WHERE uid=?').bind(uid).first();
    const merged=mergeFields(row?JSON.parse(row.payload):{},incoming),payload=JSON.stringify(merged);
    if(row && payload===row.payload)return {fields:knownRevision===row.revision?{}:merged,revision:row.revision};
    const result=row
      ?await db.prepare('UPDATE music_libraries SET payload=?,revision=revision+1,updated=? WHERE uid=? AND revision=?').bind(payload,now,uid,row.revision).run()
      :await db.prepare('INSERT OR IGNORE INTO music_libraries(uid,payload,revision,updated) VALUES(?,?,1,?)').bind(uid,payload,now).run();
    if(result.meta.changes)return {fields:merged,revision:row?row.revision+1:1};
  }
  throw new Error('Concurrent library update');
}
