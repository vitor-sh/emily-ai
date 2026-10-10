const assert=require('node:assert/strict');
const {create}=require('../web/progressive-reply.js');
let pending=[],frames=[];
const p=create(text=>frames.push(text),fn=>{pending.push(fn);return fn;},fn=>{pending=pending.filter(x=>x!==fn);});
const tick=()=>{const fn=pending.shift();if(fn)fn();};
const finish=()=>{let n=0;while(pending.length){tick();assert(++n<1000);}};
p.set('Olá! Esta é uma resposta com **formatação**, emoji 🎵 e várias palavras.');
assert.equal(frames.length,0); tick(); assert(frames[0].length<20);
// Final arrival keeps the same queue, does not jump to complete text.
p.set('Olá! Esta é uma resposta com **formatação**, emoji 🎵 e várias palavras. Final.');
assert(p.current().length<20); finish();assert(p.current().endsWith('Final.'));
assert(frames.every(t=>!/[\uD800-\uDBFF]$/.test(t)));
p.set('Outra resposta corrigida'); finish(); assert.equal(p.current(),'Outra resposta corrigida');
p.set('não deve continuar');p.stop();finish();assert.equal(p.current(),'Outra resposta corrigida');
let longFrames=0,q=[];
const long=create(()=>longFrames++,fn=>{q.push(fn);return fn;});long.set('x'.repeat(10000));
while(q.length){q.shift()();assert(longFrames<300);}
console.log('Progressive reply: queue, final, correction, emoji, cancellation and bounded tail OK');
