import assert from 'node:assert/strict';
const url='http://127.0.0.1:8798';
await fetch(url,{method:'DELETE'});
const reserve=async buckets=>(await fetch(url,{method:'POST',body:JSON.stringify(buckets)})).status;
const bucket=(key,limit,amount=1)=>({key,limit,amount,expires:Date.now()+60000});
const raced=await Promise.all(Array.from({length:8},()=>reserve([bucket('global',3)])));
assert.equal(raced.filter(s=>s===200).length,3);
assert.equal((await (await fetch(url)).json())[0].used,3);
await fetch(url,{method:'DELETE'});
assert.equal(await reserve([bucket('user',1)]),200);
assert.equal(await reserve([bucket('global',90),bucket('user',1)]),429);
assert.deepEqual(await (await fetch(url)).json(),[{bucket:'user',used:1}]);
assert.equal(await reserve([bucket('latest',3,3)]),200);
assert.equal(await reserve([bucket('latest',3)]),429);
console.log('D1 real local: concurrent cap, atomic rollback and weighted reserve passed.');

const library=async(uid,fields,revision=-1)=>{
 const r=await fetch(url+'/library',{method:'POST',body:JSON.stringify({uid,fields,revision})});assert.equal(r.status,200);return r.json();
};
const uid='fixture-'+crypto.randomUUID(),b='fixture-'+crypto.randomUUID();
const e=(v,id)=>({valor:v,quando:Date.now(),id});
const changes=Array.from({length:4},(_,i)=>({[JSON.stringify(['favorite',String(i)])]:e(true,String(i))}));
await Promise.all(changes.map(fields=>library(uid,fields)));
const combined=await library(uid,{});assert.equal(Object.keys(combined.fields).length,4);
assert.deepEqual((await library(b,{})).fields,{});
const unchanged=await library(uid,{},combined.revision);assert.deepEqual(unchanged.fields,{});
console.log('D1 library: concurrent merge, account isolation and unchanged revision passed.');
