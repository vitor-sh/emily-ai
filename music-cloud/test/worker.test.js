import test from 'node:test';
import assert from 'node:assert/strict';
import {createHandler,normalizeQuery,youtube,LimitError} from '../src/worker.js';
import {verifyFirebase} from '../src/auth.js';
const env={YOUTUBE_API_KEY:'test-secret',FIREBASE_PROJECT_ID:'test-project',ALLOWED_EMAILS:'friend@example.com',DB:{}};
const user={sub:'user1',email:'friend@example.com'};
const request=(query='test',token='test')=>new Request('https://example.test/v1/music/search',{method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify({query})});
function fixture(options={}) {
 let calls=0;const cache=new Map(),reserved=[];
 const store={cached:async k=>cache.get(k),save:async(k,v)=>cache.set(k,v),reserve:async b=>reserved.push(b)};
 const handler=createHandler({verify:async()=>user,storeFactory:()=>store,fetcher:async(url,opts)=>{calls++;assert.equal(opts.headers['X-Goog-Api-Key'],'test-secret');assert.equal(url.searchParams.has('key'),false);return Response.json({items:[{id:{videoId:'aaaaaaaaaaa'},snippet:{title:'Music'}}]});},...options});
 return {handler,cache,reserved,get calls(){return calls;}};
}
test('authenticated searches cache across requests without exposing key',async()=>{
 const f=fixture();for(let n=0;n<2;n++) {const r=await f.handler(request(),env);assert.equal(r.status,200);assert.doesNotMatch(await r.text(),/secret/);}assert.equal(f.calls,1);assert.equal(f.reserved.length,3);
});
test('missing, expired or rejected identity never reaches YouTube',async()=>{
 const f=fixture();assert.equal((await f.handler(request('test',''),env)).status,401);assert.equal(f.calls,0);
 const bad=fixture({verify:async()=>{throw Error('private details');}});const r=await bad.handler(request(),env);assert.equal(r.status,401);assert.doesNotMatch(await r.text(),/private/);
});
test('unlisted accounts forbidden and incomplete deployment closed',async()=>{
 const f=fixture();assert.equal((await f.handler(request(),{...env,ALLOWED_EMAILS:'other@example.com'})).status,403);assert.equal((await f.handler(request(),{...env,ALLOWED_EMAILS:''})).status,503);assert.equal(f.calls,0);
});
test('invalid or oversized input refused without upstream work',async()=>{
 const f=fixture();for(const q of ['',{},'a'.repeat(5000),'a\nb']) assert.equal((await f.handler(request(q),env)).status,400);assert.equal(f.calls,0);
});
test('quota and upstream failures produce safe errors',async()=>{
 const f=fixture({storeFactory:()=>({reserve:async()=>{throw new LimitError();}})});assert.equal((await f.handler(request(),env)).status,429);
 const broken=fixture({fetcher:async()=>{throw Error('test-secret');}});const r=await broken.handler(request(),env);assert.equal(r.status,503);assert.doesNotMatch(await r.text(),/secret/);
});
test('service exposes no personal PC routes',async()=>{
 const f=fixture();for(const path of ['/music/sync','/music/files/test','/pc','/llm'])assert.equal((await f.handler(new Request('https://example.test'+path),env)).status,404);
});
test('direct URL maps to official video lookup, rejects malformed results',async()=>{
 const out=await youtube('https://youtu.be/aaaaaaaaaaa','test',async url=>{assert.equal(url.pathname,'/youtube/v3/videos');return Response.json({items:[{id:'aaaaaaaaaaa',snippet:{title:'A'}},{id:'bad',snippet:{title:'B'}}]});});assert.equal(out.resultados.length,1);
});
test('cryptographically valid Firebase token accepted; altered/wrong project tokens refused',async()=>{
 const pair=await crypto.subtle.generateKey({name:'RSASSA-PKCS1-v1_5',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['sign','verify']);
 const publicKey=await crypto.subtle.exportKey('jwk',pair.publicKey);publicKey.kid='fixture';
 const b64=x=>Buffer.from(typeof x==='string'?x:JSON.stringify(x)).toString('base64url');
 const now=Date.now(),sec=Math.floor(now/1000);
 const claims={sub:'user1',email:'friend@example.com',email_verified:true,aud:'test-project',iss:'https://securetoken.google.com/test-project',iat:sec,auth_time:sec,exp:sec+3600,firebase:{sign_in_provider:'google.com'}};
 async function token(data){const raw=b64({alg:'RS256',kid:'fixture'})+'.'+b64(data);return raw+'.'+Buffer.from(await crypto.subtle.sign('RSASSA-PKCS1-v1_5',pair.privateKey,new TextEncoder().encode(raw))).toString('base64url');}
 const opts={now,fetcher:async()=>Response.json({keys:[publicKey]})};
 assert.equal((await verifyFirebase(await token(claims),'test-project',opts)).sub,'user1');
 for(const changed of [{exp:sec-1},{aud:'another'},{email_verified:false},{firebase:{sign_in_provider:'password'}}]) await assert.rejects(verifyFirebase(await token({...claims,...changed}),'test-project',opts));
 const signed=await token(claims);await assert.rejects(verifyFirebase(signed.slice(0,-10)+'aaaaaaaaaa','test-project',opts));
});
test('latest-channel mode follows uploads and reserves three calls',async()=>{
 const reserved=[];let calls=0;
 const handler=createHandler({verify:async()=>user,storeFactory:()=>({reserve:async b=>reserved.push(...b),cached:async()=>null,save:async()=>{}}),fetcher:async url=>{
  calls++;
  if(url.pathname.endsWith('/search'))return Response.json({items:[{id:{channelId:'UC'+'a'.repeat(22)}}]});
  if(url.pathname.endsWith('/channels'))return Response.json({items:[{contentDetails:{relatedPlaylists:{uploads:'UU'+'a'.repeat(22)}}}]});
  assert.ok(url.pathname.endsWith('/playlistItems'));return Response.json({items:[{snippet:{title:'Latest',resourceId:{videoId:'aaaaaaaaaaa'}}}]});
 }});
 const r=await handler(new Request('https://example.test/v1/music/search',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer test'},body:JSON.stringify({query:'Official channel',mode:'latest'})}),env);
 assert.equal(r.status,200);assert.equal((await r.json()).resultados[0].video_id,'aaaaaaaaaaa');assert.equal(calls,3);assert.equal(reserved[1].amount,3);
});
test('video IDs keep their case; query ordering in YouTube URLs is supported',async()=>{
 const {youtubeId}=await import('../src/worker.js');
 assert.equal(youtubeId('https://m.youtube.com/watch?feature=share&v=aAaaaaaaaaa&t=10'),'aAaaaaaaaaa');
 assert.equal(youtubeId('https://youtube.com.evil.test/watch?v=aaaaaaaaaaa'),null);
 const f=fixture();await f.handler(request('aAaaaaaaaaa'),env);await f.handler(request('aaaaaaaaaaa'),env);assert.equal(f.calls,2);
});

test('account gate validates allowlist without using YouTube or search quota',async()=>{
 const f=fixture();
 const req=token=>new Request('https://example.test/v1/account',{headers:token?{Authorization:'Bearer test'}:{}});
 const ok=await f.handler(req(true),env);
 assert.equal(ok.status,200);assert.deepEqual(await ok.json(),{uid:user.sub});
 assert.equal((await f.handler(req(false),env)).status,401);
 assert.equal((await f.handler(req(true),{...env,ALLOWED_EMAILS:'other@example.com'})).status,403);
 assert.equal(f.calls,0);assert.equal(f.reserved.length,0);
});

test('open Google registration accepts any verified user but still rejects invalid tokens',async()=>{
 const f=fixture({verify:async()=>({sub:'another-user',email:'new@example.com'})});
 const r=await f.handler(new Request('https://example.test/v1/account',{headers:{Authorization:'Bearer test'}}),{...env,ALLOWED_EMAILS:'',ACCOUNT_MODE:'google'});
 assert.equal(r.status,200);assert.equal((await r.json()).uid,'another-user');
 const bad=fixture({verify:async()=>{throw Error('bad')}});
 assert.equal((await bad.handler(request(),{...env,ACCOUNT_MODE:'google'})).status,401);
});
test('update metadata has no auth credentials and no configured release returns 204',async()=>{
 const f=fixture();const req=new Request('https://example.test/v1/app/update');
 assert.equal((await f.handler(req,env)).status,204);
 const r=await f.handler(req,{...env,MUSIC_UPDATE_JSON:JSON.stringify({version_code:5})});
 assert.deepEqual(await r.json(),{version_code:5});assert.equal(f.calls,0);
});
