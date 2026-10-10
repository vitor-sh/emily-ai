import {MAX_LIBRARY_BYTES,validateFields,syncLibrary} from './library.js';
import {verifyFirebase} from './auth.js';
const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers});
export class LimitError extends Error {}
export function normalizeQuery(query) {
  if(typeof query!=='string') throw new TypeError();
  const value=query.trim();
  if(!value || value.length>300 || /[\x00-\x1f]/.test(value)) throw new TypeError();
  return value;
}
async function hash(text) {
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),v=>v.toString(16).padStart(2,'0')).join('');
}
export class D1Store {
  constructor(db) {this.db=db;}
  async cached(key,now) {
    const row=await this.db.prepare('SELECT payload FROM search_cache WHERE key=? AND expires>?').bind(key,now).first();
    return row ? JSON.parse(row.payload) : null;
  }
  async save(key,value,now) {
    await this.db.prepare('INSERT INTO search_cache(key,payload,expires) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload,expires=excluded.expires').bind(key,JSON.stringify(value),now+3600000).run();
  }
  async reserve(buckets) {
    try {
      await this.db.batch(buckets.map(b=>this.db.prepare('INSERT INTO budgets(bucket,used,ceiling,expires) VALUES(?,?,?,?) ON CONFLICT(bucket) DO UPDATE SET used=used+excluded.used').bind(b.key,b.amount||1,b.limit,b.expires)));
    } catch(e) {
      if(String(e.message).includes('CHECK constraint')) throw new LimitError();
      throw e;
    }
  }
}
async function readBody(request,limit=2048) {
  if(!request.headers.get('content-type')?.startsWith('application/json')) throw new TypeError();
  if(Number(request.headers.get('content-length'))>limit) throw new TypeError();
  const reader=request.body?.getReader();if(!reader) throw new TypeError();
  let raw='';let length=0;const decoder=new TextDecoder();
  try {while(true) {const {done,value}=await reader.read();if(done)break;length+=value.byteLength;if(length>limit)throw new TypeError();raw+=decoder.decode(value,{stream:true});}raw+=decoder.decode();return JSON.parse(raw);}
  finally {await reader.cancel().catch(()=>{});}
}
export function youtubeId(query) {
  if(/^[A-Za-z0-9_-]{11}$/.test(query))return query;
  try {
    const url=new URL(query);
    if(url.protocol!=='https:' && url.protocol!=='http:')return null;
    let id;
    if(url.hostname==='youtu.be')id=url.pathname.split('/')[1];
    else if(['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(url.hostname)) {
      id=url.pathname==='/watch'?url.searchParams.get('v'):/^\/(?:shorts|live|embed)\/([A-Za-z0-9_-]{11})\/?$/.exec(url.pathname)?.[1];
    }
    return /^[A-Za-z0-9_-]{11}$/.test(id||'')?id:null;
  }catch{return null;}
}
async function api(endpoint,params,key,fetcher) {
  const url=new URL(`https://www.googleapis.com/youtube/v3/${endpoint}`);
  for(const [name,value] of Object.entries(params))url.searchParams.set(name,value);
  const response=await fetcher(url,{headers:{'X-Goog-Api-Key':key},signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw new Error('Upstream unavailable');
  const data=await response.json();if(!Array.isArray(data.items))throw new Error('Upstream invalid');return data;
}
export async function youtube(query,key,fetcher=fetch,mode='search') {
  if(mode==='latest') {
    const channels=await api('search',{part:'snippet',type:'channel',maxResults:'1',q:query},key,fetcher);
    const id=channels.items[0]?.id?.channelId;if(!/^UC[A-Za-z0-9_-]{22}$/.test(id||''))return {resultados:[]};
    const channel=await api('channels',{part:'contentDetails',id},key,fetcher);
    const playlist=channel.items[0]?.contentDetails?.relatedPlaylists?.uploads;
    if(!/^[A-Za-z0-9_-]{1,100}$/.test(playlist||''))return {resultados:[]};
    const videos=await api('playlistItems',{part:'snippet',maxResults:'1',playlistId:playlist},key,fetcher);
    const item=videos.items[0],video=item?.snippet?.resourceId?.videoId;
    if(!/^[A-Za-z0-9_-]{11}$/.test(video||''))return {resultados:[]};
    return {resultados:[{video_id:video,titulo:String(item.snippet.title||'Vídeo').slice(0,120),thumb:`https://i.ytimg.com/vi/${video}/mqdefault.jpg`}]};
  }
  const vid=youtubeId(query);
  const url=new URL(`https://www.googleapis.com/youtube/v3/${vid?'videos':'search'}`);
  url.searchParams.set('part','snippet');
  if(vid)url.searchParams.set('id',vid);else {url.searchParams.set('q',query);url.searchParams.set('type','video');url.searchParams.set('maxResults','8');}
  const response=await fetcher(url,{headers:{'X-Goog-Api-Key':key},signal:AbortSignal.timeout(8000)});
  if(!response.ok) throw new Error('Upstream unavailable');
  const data=await response.json();
  if(!Array.isArray(data.items)) throw new Error('Upstream invalid');
  return {resultados:data.items.slice(0,8).flatMap(item=>{
    const id=vid?item.id:item.id?.videoId;
    if(!/^[A-Za-z0-9_-]{11}$/.test(id||'') || typeof item.snippet?.title!=='string') return [];
    return [{video_id:id,titulo:item.snippet.title.slice(0,120),artist:String(item.snippet.channelTitle||'').slice(0,180),thumb:`https://i.ytimg.com/vi/${id}/mqdefault.jpg`}];
  })};
}
export function createHandler({verify=verifyFirebase,fetcher=fetch,clock=Date.now,storeFactory=env=>new D1Store(env.DB)}={}) {
  return async (request,env)=>{
    const path=new URL(request.url).pathname;
    if(path==='/health' && request.method==='GET')return json({ok:true});
    if(path==='/v1/app/update' && request.method==='GET') {
      if(!env.MUSIC_UPDATE_JSON)return new Response(null,{status:204,headers});
      try {return json(JSON.parse(env.MUSIC_UPDATE_JSON));}catch{return json({erro:'Atualização indisponível'},503);}
    }
    const library=path==='/v1/music/library' && request.method==='POST';
    const account=path==='/v1/account' && request.method==='GET';
    if(!account && !library && (path!=='/v1/music/search' || request.method!=='POST'))return json({erro:'Rota indisponível'},404);
    const allowed=new Set((env.ALLOWED_EMAILS||'').split(',').map(v=>v.trim().toLowerCase()).filter(Boolean));
    if(!env.YOUTUBE_API_KEY || !env.FIREBASE_PROJECT_ID || (!allowed.size && env.ACCOUNT_MODE!=='google') || !env.DB)return json({erro:'Serviço aguardando configuração'},503);
    const token=/^Bearer ([^\s]+)$/.exec(request.headers.get('authorization')||'')?.[1];
    if(!token)return json({erro:'Entre com sua conta Google'},401);
    let user;
    try {user=await verify(token,env.FIREBASE_PROJECT_ID);}
    catch {return json({erro:'Sessão inválida ou expirada'},401);}
    if(env.ACCOUNT_MODE!=='google' && !allowed.has(user.email?.toLowerCase()))return json({erro:'Conta ainda não autorizada para a beta'},403);
    if(account)return json({uid:user.sub});
    if(library) {
      try {
        const now=clock(),body=await readBody(request,MAX_LIBRARY_BYTES+1024);
        const fields=validateFields(body.fields,now);
        const store=storeFactory(env);
        await store.reserve([{key:`sync:${Math.floor(now/60000)}:${await hash(user.sub)}`,limit:12,expires:now+120000}]);
        return json(await syncLibrary(env.DB,user.sub,fields,now,Number.isSafeInteger(body.revision)?body.revision:-1));
      }catch(e) {return json({erro:e instanceof LimitError?'Sincronização aguardando':e instanceof TypeError||e instanceof RangeError?'Biblioteca inválida ou muito grande':'Não foi possível sincronizar'},e instanceof LimitError?429:e instanceof TypeError||e instanceof RangeError?400:503);}
    }
    let query,mode;
    try {const body=await readBody(request);query=normalizeQuery(body.query);mode=body.mode??"search";if(!["search","latest"].includes(mode))throw new TypeError();}catch{return json({erro:'Pesquisa inválida'},400);}
    try {
      const now=clock(),store=storeFactory(env),uid=await hash(user.sub),minute=Math.floor(now/60000);
      await store.reserve([{key:`minute:${minute}:${uid}`,limit:12,expires:now+120000}]);
      const video=mode==='search'?youtubeId(query):null;
      const key=await hash(mode+':'+(video?'video:'+video:query.toLocaleLowerCase('pt-BR')));
      const cached=await store.cached(key,now);if(cached)return json(cached);
      // YouTube resets quota at midnight Pacific; DST is handled by Intl.
      const day=new Intl.DateTimeFormat('en-CA',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);
      await store.reserve([{key:`day:${day}:global`,limit:90,amount:mode==='latest'?3:1,expires:now+172800000},{key:`day:${day}:${uid}`,limit:25,amount:mode==='latest'?3:1,expires:now+172800000}]);
      const result=await youtube(query,env.YOUTUBE_API_KEY,fetcher,mode);
      await store.save(key,result,now);
      return json(result);
    }catch(e){return e instanceof LimitError?json({erro:'Limite de buscas atingido. Tente mais tarde.'},429):json({erro:'Busca temporariamente indisponível'},503);}
  };
}
export default {
  fetch:createHandler(),
  async scheduled(event,env,ctx) {
    ctx.waitUntil(env.DB.batch([
      env.DB.prepare('DELETE FROM search_cache WHERE expires<?').bind(Date.now()),
      env.DB.prepare('DELETE FROM budgets WHERE expires<?').bind(Date.now())
    ]));
  }
};
