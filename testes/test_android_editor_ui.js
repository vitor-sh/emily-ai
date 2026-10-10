const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{JSDOM}=require('jsdom');
const root=path.join(__dirname,'../web');
async function fixture(){
 const dom=new JSDOM(fs.readFileSync(path.join(root,'android-editor.html'),'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,url:'http://localhost/'}),w=dom.window;
 w.calls=[];let document={version:1,elements:{},pages:[]};
 w.pywebview={api:{command:async(name,p)=>{w.calls.push([name,p]);if(name==='load')return{ok:true,document,revision:'saved',catalog:[{key:'Screen:Text:1',kind:'Text',label:'Texto original',file:'Screen.kt'},{key:'Screen:Button:1',kind:'Button',label:'Botão',file:'Screen.kt'}],devices:[{serial:'phone',state:'device',model:'Android'}]};if(name==='status')return w.statusResult||{ok:true};if(name==='ai')return{ok:true,id:'ai1'};if(name==='frame')return w.frameResult||{ok:true,image:'data:image/png;base64,AA==',width:720,height:1600,density:1.75,nodes:[{key:'Screen:Text:1',bounds:[100,100,200,150]},{key:'Screen:Button:1',bounds:[90,90,210,160]}]};if(name==='build')return{ok:true,job:{id:'job',running:true,revision:'new',document:p.document,publish:p.publish}};return{ok:true};}}};
 w.eval(fs.readFileSync(path.join(root,'editor-core.js'),'utf8'));w.eval(fs.readFileSync(path.join(root,'editor-markdown.js'),'utf8'));w.eval(fs.readFileSync(path.join(root,'android-editor.js'),'utf8'));
 const pause=()=>new Promise(r=>w.setTimeout(r,25));await pause();return{dom,w,pause};
}
function select(w,key){const el=w.document.getElementById('elements');el.value=key;el.dispatchEvent(new w.Event('change'));}
function field(w,key,value){const el=w.document.querySelector('[data-field='+key+']');el.value=value;el.dispatchEvent(new w.Event('change'));}
test('editar texto substitui o valor do componente e permite desfazer/refazer',async()=>{
 const{dom,w}=await fixture();try{select(w,'Screen:Text:1');field(w,'label','Novo título');assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1'].label,'Novo título');assert.equal(w.document.querySelector('#selected-title').textContent,'Novo título');w.document.getElementById('undo').click();assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1'],undefined);w.document.getElementById('redo').click();assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1'].label,'Novo título');}finally{dom.window.close();}
});
test('Delete oculta elemento, close pede decisão e descartar restaura histórico',async()=>{
 const{dom,w,pause}=await fixture();try{select(w,'Screen:Button:1');w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Delete',bubbles:true}));assert.equal(w.AndroidEditor.getState().document.elements['Screen:Button:1'].hidden,true);w.AndroidEditor.requestClose();assert.equal(w.document.querySelector('#close-dialog').hidden,false);w.document.getElementById('close-discard').click();await pause();assert.ok(w.calls.some(([n,p])=>n==='finish'&&p.discard===true));assert.equal(w.AndroidEditor.getState().dirty,false);}finally{dom.window.close();}
});
test('Ctrl+S publica; atualizar prévia compila sem publicação',async()=>{
 const a=await fixture();try{a.w.document.dispatchEvent(new a.w.KeyboardEvent('keydown',{key:'s',ctrlKey:true,bubbles:true,cancelable:true}));await a.pause();assert.equal(a.w.calls.find(([n])=>n==='build')[1].publish,true);}finally{a.dom.window.close();}
 const b=await fixture();try{b.w.document.getElementById('preview-build').click();await b.pause();assert.equal(b.w.calls.find(([n])=>n==='build')[1].publish,false);}finally{b.dom.window.close();}
});
test('texto colado mantém comportamento normal e URI arrastada é bloqueada antes da importação',async()=>{
 const{dom,w,pause}=await fixture();try{const e=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(e,'clipboardData',{value:{types:['text/plain'],files:[],items:[]}});w.document.querySelector('#ai-prompt').dispatchEvent(e);assert.equal(e.defaultPrevented,false);assert.ok(!w.calls.some(([n])=>n==='clipboard'));
 const d=new w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(d,'dataTransfer',{value:{types:['text/uri-list'],files:[],getData:()=> 'file:///tmp/image.png'}});w.document.body.dispatchEvent(d);assert.equal(d.defaultPrevented,true);await pause();assert.ok(w.calls.some(([n,p])=>n==='image_paths'&&p.paths[0]==='file:///tmp/image.png'));assert.ok(w.document.querySelector('#screen'));}finally{dom.window.close();}
});
test('novas páginas e componentes são nativos e ficam no documento com histórico',async()=>{
 const{dom,w}=await fixture();try{w.document.querySelector('#page-title').value='Atalhos';w.document.querySelector('#add-page').click();w.document.querySelector('#item-type').value='button';w.document.querySelector('#item-label').value='Configurar';w.document.querySelector('#item-action').value='settings';w.document.querySelector('#add-item').click();const d=w.AndroidEditor.getState().document;assert.equal(d.pages[0].title,'Atalhos');assert.equal(d.pages[0].items[0].action,'settings');w.document.querySelector('#delete').click();assert.equal(w.AndroidEditor.getState().document.pages[0].items.length,0);w.document.querySelector('#undo').click();assert.equal(w.AndroidEditor.getState().document.pages[0].items.length,1);}finally{dom.window.close();}
});

test('seleção precisa usa a chave da instância e texto real, sem editar as outras linhas',async()=>{
 const{dom,w,pause}=await fixture();try{
 w.frameResult={ok:true,stream:'http://127.0.0.1:9999/private',width:720,height:1600,nodes:[{key:'Screen:Button:1',kind:'Button',instance:'parent',bounds:[50,80,500,260]},{key:'Screen:Text:1:scope-a',baseKey:'Screen:Text:1',label:'Usar root',kind:'Text',instance:'a',bounds:[100,100,220,145]},{key:'Screen:Text:1:scope-b',baseKey:'Screen:Text:1',label:'Outra opção',kind:'Text',instance:'b',bounds:[100,180,220,220]}]};
 w.document.querySelector('#devices').value='phone';w.document.querySelector('#connect').click();await new Promise(r=>w.setTimeout(r,1600));
 const screen=w.document.querySelector('#screen');screen.getBoundingClientRect=()=>({left:0,top:0,width:720,height:1600});screen.setPointerCapture=()=>{};
 screen.dispatchEvent(new w.MouseEvent('pointerdown',{clientX:140,clientY:120,button:0,bubbles:true}));
 assert.equal(w.AndroidEditor.getState().selected,'Screen:Text:1:scope-a');assert.equal(w.document.querySelector('[data-field=label]').disabled,false);
 assert.equal(w.document.querySelector('[data-field=label]').value,'Usar root');field(w,'label','Permitir root');
 assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1:scope-a'].label,'Permitir root');assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1:scope-b'],undefined);
 assert.equal(w.document.querySelector('#frame').getAttribute('src'),w.frameResult.stream);
 }finally{dom.window.close();}
});

test('AI recebe documento e só apresenta aplicação confirmada após a tarefa terminar',async()=>{
 const{dom,w,pause}=await fixture();try{
 select(w,'Screen:Text:1');w.document.querySelector('#ai-prompt').value='Ajustar';w.document.querySelector('#ai-send').click();await pause();
 const sent=w.calls.find(([name])=>name==='ai')[1];assert.equal(sent.revision,'saved');assert.equal(sent.document.version,1);
 w.statusResult={ok:true,ai:{job:{id:'ai1',running:true,status:'Instalando',result:null}}};await new Promise(r=>w.setTimeout(r,950));
 field(w,'label','Concorrente');assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1'],undefined);
 w.statusResult={ok:true,ai:{job:{id:'ai1',running:false,status:'Aplicado',result:{document:{version:1,elements:{'Screen:Text:1':{label:'Confirmado'}},pages:[]},files:['Screen.kt'],preview_applied:true,message:'Pronto'}}}};
 await new Promise(r=>w.setTimeout(r,950));assert.equal(w.AndroidEditor.getState().document.elements['Screen:Text:1'].label,'Confirmado');
 assert.match(w.document.querySelector('#ai-messages').textContent,/instalado e confirmado/);assert.doesNotMatch(w.document.querySelector('#ai-messages').textContent,/Clique em Atualizar/);
 }finally{dom.window.close();}
});
