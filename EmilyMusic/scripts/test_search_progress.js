const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const root=path.join(__dirname,'../app/src/main/assets/music');
async function test(){
 const timers=new Map();let tid=0,calls=[];
 const ctx={window:{},document:{querySelector:()=>({value:''})},setTimeout:f=>{timers.set(++tid,f);return tid},clearTimeout:id=>timers.delete(id),EmilyAndroid:{call:(...a)=>calls.push(a)}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(root,'bridge.js'),'utf8'),ctx);
 vm.runInContext('var seen=[];var result;musicSearchCall(v=>seen.push(v),"example","all").then(r=>result=r);',ctx);
 const id=+calls[0][0];ctx.window.musicProgress(id,{resultados:[1]});assert.equal(vm.runInContext('seen.length',ctx),1);
 ctx.window.musicReply(id,{resultados:[1,2]},null);ctx.window.musicProgress(id,{resultados:[3]});await Promise.resolve();
 assert.equal(vm.runInContext('seen.length',ctx),1);assert.equal(vm.runInContext('result.data.resultados.length',ctx),2);assert.equal(timers.size,0);
 vm.runInContext('musicSearchCall(v=>seen.push(v),"second","all");',ctx);const second=+calls[1][0];[...timers.values()][0]();ctx.window.musicProgress(second,{resultados:[4]});assert.equal(vm.runInContext('seen.length',ctx),1);
 vm.runInContext(fs.readFileSync(path.join(root,'emily-music.js'),'utf8'),ctx);
 const music=ctx.window.EmilyMusic;let jobs=[],prepared=0;
 ctx.musicSearchCall=(progress,...args)=>new Promise(resolve=>jobs.push({progress,resolve,args}));
 music.go=()=>{};music.online=()=>true;music.rememberSearch=()=>{};music.renderSearch=()=>{};music.prepareVisible=()=>prepared++;
 const first=music.search('old'),last=music.search('new');
 jobs[0].progress({resultados:[{video_id:'old'}]});assert.equal(music.searchResults.length,0);
 jobs[1].progress({resultados:[{video_id:'new'}]});assert.equal(music.searchResults[0].video_id,'new');assert.equal(music.searchLoading,true);
 jobs[0].resolve({data:{resultados:[{video_id:'late'}]}});await first;assert.equal(music.searchResults[0].video_id,'new');assert.equal(music.searchLoading,true);
 jobs[1].resolve({data:{resultados:[{video_id:'new'},{type:'playlist'}]}});await last;assert.equal(music.searchLoading,false);assert.equal(music.searchResults.length,2);assert.equal(prepared,2);
 const closing=music.search('closed');music.searchSerial++;jobs[2].progress({resultados:[{video_id:'closed'}]});assert.equal(music.searchResults.length,0);jobs[2].resolve({data:{resultados:[{video_id:'closed'}]}});await closing;assert.equal(music.searchResults.length,0);
 console.log('PASS: partial results; final merge; stale queries and closed views; bridge timeout cleanup');
}
test().catch(e=>{console.error(e);process.exitCode=1;});
