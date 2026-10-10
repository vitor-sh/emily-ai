// Local integration fixture only; never deploy this entry point.
import {syncLibrary,validateFields} from '../src/library.js';
import {D1Store} from '../src/worker.js';
export default {async fetch(request,env) {
 await env.DB.prepare('CREATE TABLE IF NOT EXISTS budgets(bucket TEXT PRIMARY KEY,used INTEGER NOT NULL CHECK(used>0 AND used<=ceiling),ceiling INTEGER NOT NULL,expires INTEGER NOT NULL)').run();
 await env.DB.prepare('CREATE TABLE IF NOT EXISTS music_libraries(uid TEXT PRIMARY KEY,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated INTEGER NOT NULL)').run();
 if(new URL(request.url).pathname==='/library') {
  const body=await request.json();return Response.json(await syncLibrary(env.DB,body.uid,validateFields(body.fields),Date.now(),body.revision??-1));
 }
 const store=new D1Store(env.DB);
 if(request.method==='DELETE'){await env.DB.prepare('DELETE FROM budgets').run();return Response.json({ok:true});}
 if(request.method==='GET')return Response.json((await env.DB.prepare('SELECT bucket,used FROM budgets ORDER BY bucket').all()).results);
 try {await store.reserve(await request.json());return Response.json({ok:true});}
 catch{return Response.json({ok:false},{status:429});}
}};
