import test from 'node:test';import assert from 'node:assert/strict';
import {validateFields,mergeFields,syncLibrary} from '../src/library.js';
const key='["track","default","aaaaaaaaaaa"]';
const entry=(valor,quando=100,id='a')=>({valor,quando,id});
const track={video_id:'aaaaaaaaaaa',titulo:'Music',thumb:'',adicionada:1};
test('deletions survive stale devices and concurrent merge is deterministic',()=>{
 const first={[key]:entry(track)},deleted={[key]:entry(null,101)};
 assert.equal(mergeFields(deleted,first)[key].valor,null);
 const left={[key]:entry(track,102,'a')},right={[key]:entry(null,102,'z')};
 assert.deepEqual(mergeFields(left,right),mergeFields(right,left));
});
test('local private fields and future revisions rejected',()=>{
 assert.throws(()=>validateFields({'["sources","a"]':entry('file://secret')}));
 assert.throws(()=>validateFields({[key]:entry({...track,uri:'content://secret'})}));
 assert.throws(()=>validateFields({[key]:entry(track,Date.now()+3600000)}));
 assert.throws(()=>validateFields({'["playlist","__locais__"]':entry({foto:''})}));
 assert.deepEqual(validateFields({[key]:entry(track)})[key].valor,track);
});
test('CAS retries concurrent change and never crosses user boundary',async()=>{
 let row={payload:'{}',revision:1},attempt=0;
 const db={prepare(sql){return {bind(...args){return {async first(){assert.equal(args[0],'alice');return {...row}},async run(){attempt++;assert.equal(args[2],'alice');if(attempt===1){row={payload:JSON.stringify({'["favorite","other"]':entry(true,102)}),revision:2};return {meta:{changes:0}}}assert.equal(args[3],2);row={payload:args[0],revision:3};return {meta:{changes:1}}}}}}}};
 const result=await syncLibrary(db,'alice',{[key]:entry(track)},1000);
 assert.ok(result.fields['["favorite","other"]']);assert.ok(result.fields[key]);assert.equal(result.revision,3);assert.equal(attempt,2);
});
test('listening snapshots preserve independent device counters and reject unsafe or excessive records',()=>{
 const row={video_id:'aaaaaaaaaaa',titulo:'Song',artist:'Artist',thumb:'',count:2,last:100};
 const a='["listening","device-aaaa"]',b='["listening","device-bbbb"]';
 const merged=mergeFields(validateFields({[a]:entry([row])}),validateFields({[b]:entry([{...row,count:3}])}));
 assert.equal(merged[a].valor[0].count+merged[b].valor[0].count,5);
 assert.deepEqual(mergeFields(merged,{[a]:entry([row])}),merged);
 for(const r of [{...row,count:-1},{...row,last:Date.now()+3600000},{...row,uri:'file://private'}])assert.throws(()=>validateFields({[a]:entry([r])}));
 assert.throws(()=>validateFields({[a]:entry(Array(201).fill(row))}));
 assert.throws(()=>validateFields({[a]:entry([row,row])}));
});

test('playlist import pending metadata survives validation and rejects unsafe rows',()=>{
  const key=JSON.stringify(['playlist','Imported']);const now=Date.now();
  const row={spotify_id:'AAAAAAAAAAAAAAAAAAAAAA',title:'A song',artists:'An artist',duration:180};
  const make=pending=>({[key]:{valor:{foto:'https://i.scdn.co/image/example',pending},quando:now,id:'test'}});
  assert.equal(validateFields(make([row]),now)[key].valor.pending.length,1);
  assert.throws(()=>validateFields(make([row,row]),now));
  assert.throws(()=>validateFields(make([{...row,duration:-1}]),now));
  assert.throws(()=>validateFields(make([{...row,secret:'not allowed'}]),now));
});

test('older clients changing artwork cannot discard imported pending tracks',()=>{
  const key=JSON.stringify(['playlist','Imported']);const pending=[{spotify_id:'AAAAAAAAAAAAAAAAAAAAAA',title:'Song',artists:'Artist',duration:180}];
  const old={[key]:{valor:{foto:'old',pending},quando:1,id:'a'}};
  const photo={[key]:{valor:{foto:'new'},quando:2,id:'b'}};
  assert.deepEqual(mergeFields(old,photo)[key].valor,{foto:'new',pending});
  const resolved={[key]:{valor:{foto:'new',pending:[]},quando:3,id:'c'}};
  assert.deepEqual(mergeFields(mergeFields(old,photo),resolved)[key].valor.pending,[]);
  const deleted={[key]:{valor:null,quando:4,id:'d'}};
  assert.equal(mergeFields(old,deleted)[key].valor,null);
});

test('playlist pins sync independently of artwork and stale devices',()=>{
 const pin='["pin","Imported"]',playlist='["playlist","Imported"]';
 const current=validateFields({[pin]:entry(true,200),[playlist]:entry({foto:'old'},100)});
 const old=validateFields({[pin]:entry(false,150),[playlist]:entry({foto:'new'},250)});
 assert.equal(mergeFields(current,old)[pin].valor,true);
 assert.equal(mergeFields(current,{[pin]:entry(false,300)})[pin].valor,false);
 assert.throws(()=>validateFields({[pin]:entry('true')}));
 assert.throws(()=>validateFields({'["pin","__locais__"]':entry(true)}));
});

test('YouTube playlist identity syncs and survives artwork edits from older clients',()=>{
 const key=JSON.stringify(['playlist','YouTube list']);const id='PL1234567890abcdef';
 const left={[key]:{valor:{foto:'',youtube_id:id,pending:[]},quando:10,id:'a'}};
 validateFields(left,100);
 const merged=mergeFields(left,{[key]:{valor:{foto:'new'},quando:11,id:'b'}});
 assert.equal(merged[key].valor.youtube_id,id);
 assert.throws(()=>validateFields({[key]:{valor:{foto:'',youtube_id:'https://evil.test'},quando:10,id:'a'}},100));
});
