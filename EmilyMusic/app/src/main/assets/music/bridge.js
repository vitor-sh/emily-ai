const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ICO={};const svg=()=>'';
let seq=0;const pending=new Map();
window.musicReply=(id,value,error)=>{const p=pending.get(id);if(!p)return;pending.delete(id);clearTimeout(p.timer);if(p.envelope){p.resolve({data:value,error:error||null});return;}if(error){toast(error,'erro');p.resolve(null);}else p.resolve(value);};
function tenta(method,...args){return new Promise(resolve=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);toast('A operação demorou. Tente novamente.','erro');resolve(null);},60000);pending.set(id,{resolve,timer});EmilyAndroid.call(String(id),method,JSON.stringify(args));});}
let toastTimer;
function toast(msg){const el=$('#music-toast');el.textContent=msg;el.classList.add('visivel');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('visivel'),4500);}

// Imports show errors in their own screen; canceled previews cannot emit late toasts.
function musicImportCall(method,...args){return new Promise(resolve=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);resolve({data:null,error:"A operação demorou. Confira a conexão e tente novamente."});},60000);pending.set(id,{resolve,timer,envelope:true});EmilyAndroid.call(String(id),method,JSON.stringify(args));});}

window.musicProgress=(id,value)=>{const p=pending.get(id);if(p?.progress)p.progress(value);};
function musicSearchCall(progress,...args){return new Promise(resolve=>{const id=++seq;const timer=setTimeout(()=>{pending.delete(id);resolve({data:null,error:"A busca demorou. Tente novamente."});},60000);pending.set(id,{resolve,timer,envelope:true,progress});EmilyAndroid.call(String(id),'playlist_buscar_preview',JSON.stringify(args));});}
