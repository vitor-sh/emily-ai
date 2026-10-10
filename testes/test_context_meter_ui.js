const assert=require('node:assert/strict');
const fs=require('node:fs');
const {JSDOM}=require('jsdom');
const dom=new JSDOM('<button id="btn-uso-contexto"></button><section id="painel-uso-contexto" hidden></section>',{runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window;
w.eval("var ESTADO={atual:'chat-a'}; function pontePronta(){return true};");
let resolve;
w.api=()=>new Promise(r=>{resolve=r});
const text=fs.readFileSync('web/app.js','utf8');
w.eval(text.slice(text.indexOf('window.EmilyUsage = (() => {')));
const latest={conversation_key:'chat-a',model:'claude-sonnet-5',updated_at:200,percent:21,used:210000,limit:1000000,source:'catalogo'};
w.EmilyUsage.setContext(latest);
w.EmilyUsage.setContext({...latest,updated_at:100,percent:4});
assert.match(w.document.querySelector('.contexto-valor').textContent,/21/);
assert.match(w.document.querySelector('small').textContent,/1.000.000/);
async function test(){
 w.EmilyUsage.refresh();
 resolve({context:{...latest,updated_at:100,percent:4},usage:{}});
 await new Promise(r=>setImmediate(r));
 assert.match(w.document.querySelector('.contexto-valor').textContent,/21/);
 w.EmilyUsage.setContext({...latest,model:'claude-haiku-4.5',updated_at:201,percent:30,limit:200000});
 assert.match(w.document.querySelector('.contexto-valor').textContent,/30/);
 w.EmilyUsage.setContext({...latest,updated_at:200});
 assert.match(w.document.querySelector('.contexto-valor').textContent,/30/);
 dom.window.close();console.log('Contexto: respostas antigas ignoradas, troca de modelo e janela corretas.');
}
test().catch(e=>{console.error(e);process.exitCode=1});
