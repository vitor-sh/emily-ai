/* Executar com NODE_PATH apontando para jsdom; nenhuma ação do PC é executada. */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {History,blank,css}=require('../web/editor-core.js');
test('undo/redo agrupa digitação, retém histórico após salvar e corta ramificações',()=>{
 const h=new History(blank(),3);let d=h.current;d.theme['--bg']='#111111';h.push(d,'cor',1000);d.theme['--bg']='#222222';h.push(d,'cor',1300);
 assert.equal(h.index,1);assert.equal(h.undo().theme['--bg'],undefined);assert.equal(h.redo().theme['--bg'],'#222222');
 h.undo();d=h.current;d.theme['--bg']='#333333';h.push(d);assert.equal(h.canRedo,false);
 d=h.current;d.theme['--bg']='#444444';assert.equal(h.current.theme['--bg'],'#333333');
});
test('medidas distinguem pixels, opacidade e ordem',()=>assert.deepEqual(css({width:140,opacity:.5,order:2,x:4,y:9}),{width:'140px',opacity:'0.5',order:'2',translate:'4px 9px'}));
const {JSDOM}=require('jsdom');
async function fixture(draft=null,live=null){
 const dom=new JSDOM('<!doctype html><html><head></head><body><header id="barra"><button id="btn-editor">Editor</button><button id="btn-novo"><svg></svg><span>Nova conversa</span></button></header><div id="editor-toolbar"></div><aside id="lateral"><nav id="conversas"></nav></aside><main id="palco"><section id="inicio"><h1 id="titulo">Emily</h1><input id="entrada"></section></main><div id="composer"></div></body></html>',{runScripts:'outside-only',pretendToBeVisual:true,url:'http://localhost/'});
 const w=dom.window;w.confirm=()=>true;w.toast=()=>{};w.ESTADO={tela:'inicio'};w.irPara=()=>{w.document.getElementById('palco').innerHTML='<section id="inicio"><h1 id="titulo">Emily</h1><input id="entrada"></section>';};
 let saved=blank(),revision='base';w.editorCalls=[];w.api=async(name,doc)=>{w.editorCalls.push(name);if(name==='editor_recuperar')return{ok:true,draft};if(name==='editor_carregar')return{ok:true,document:saved,revision};if(name==='editor_salvar'){saved=JSON.parse(JSON.stringify(doc));revision='novo';return{ok:true,document:saved,revision,publication:{ok:true,message:'Publicado'}};}return{ok:true};};
 if(live)w.sessionStorage.setItem('emily-editor-live',JSON.stringify(live));
 w.eval(fs.readFileSync(path.join(__dirname,'../web/editor-core.js'),'utf8'));w.eval(fs.readFileSync(path.join(__dirname,'../web/editor.js'),'utf8'));
 await w.EmilyEditor.initialize();if(live)await new Promise(r=>w.setTimeout(r,220));else await w.EmilyEditor.toggle();
 const pause=()=>new Promise(r=>w.setTimeout(r,40));return{w,dom,pause};
}
test('editar botão preserva SVG e handler, Ctrl+Z/Ctrl+Shift+Z e salvar',async()=>{
 const {w,dom,pause}=await fixture();let clicked=0;const b=w.document.getElementById('btn-novo');b.onclick=()=>clicked++;
 b.click();assert.equal(clicked,0);assert.equal(w.EmilyEditor.getState().selected,'id:btn-novo');
 const label=w.document.querySelector('[data-editor-field=label]');label.value='Novo chat';label.dispatchEvent(new w.Event('input',{bubbles:true}));
 assert.equal(b.querySelector('span').textContent,'Novo chat');assert.ok(b.querySelector('svg'));
 w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'z',ctrlKey:true,bubbles:true}));assert.equal(b.querySelector('span').textContent,'Nova conversa');
 w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'z',ctrlKey:true,shiftKey:true,bubbles:true}));assert.equal(b.querySelector('span').textContent,'Novo chat');
 await w.EmilyEditor.save();assert.equal(w.EmilyEditor.getState().dirty,false);
 w.document.getElementById('editor-select').click();b.click();assert.equal(clicked,1);
 dom.window.close();
});
test('aba, grupos, botão, edição, desfazer e refazer',async()=>{
 const{w,dom,pause}=await fixture();w.document.getElementById('editor-add-page').click();
 assert.equal(w.EmilyEditor.getState().document.pages.length,1);assert.ok(w.document.querySelector('.editor-custom-page'));
 w.document.getElementById('editor-add-type').value='group';w.document.getElementById('editor-add-item').click();
 w.document.getElementById('editor-add-type').value='button';w.document.getElementById('editor-add-item').click();
 assert.equal(w.EmilyEditor.getState().document.pages[0].items.length,2);
 const input=w.document.querySelector('[data-editor-field=label]');input.value='Meu atalho';input.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(w.document.querySelector('[data-editor-type=button]').textContent,'Meu atalho');
 w.EmilyEditor.undo();assert.equal(w.document.querySelector('[data-editor-type=button]').textContent,'Novo botão');
 w.EmilyEditor.redo();assert.equal(w.document.querySelector('[data-editor-type=button]').textContent,'Meu atalho');
 dom.window.close();
});
test('personalização sobrevive a reconstrução do componente e restaurar recupera texto',async()=>{
 const{w,dom,pause}=await fixture();w.document.getElementById('btn-novo').click();let input=w.document.querySelector('[data-editor-field=label]');input.value='Meu chat';input.dispatchEvent(new w.Event('input',{bubbles:true}));
 const old=w.document.getElementById('btn-novo'),fresh=old.cloneNode(true);fresh.removeAttribute('data-emily-editor-key');fresh.querySelector('span').textContent='Nova conversa';old.replaceWith(fresh);await pause();
 assert.equal(fresh.querySelector('span').textContent,'Meu chat');fresh.click();w.document.getElementById('editor-reset').click();assert.equal(fresh.querySelector('span').textContent,'Nova conversa');dom.window.close();
});
test('fechar oferece cancelar, salvar e sair, ou descartar; autosave preserva rascunho',async()=>{
 const {w,dom,pause}=await fixture();w.document.getElementById('btn-novo').click();const input=w.document.querySelector('[data-editor-field=label]');input.value='Rascunho';input.dispatchEvent(new w.Event('input',{bubbles:true}));
 assert.ok(w.localStorage.getItem('emily-editor-draft-v1'));
 w.EmilyEditor.requestClose(true);assert.ok(w.document.getElementById('editor-close-save'));
 w.document.getElementById('editor-close-cancel').click();assert.ok(w.EmilyEditor.getState().dirty);assert.equal(w.document.getElementById('editor-close-dialog'),null);
 w.EmilyEditor.requestClose(true);w.document.getElementById('editor-close-save').click();await pause();assert.equal(w.EmilyEditor.getState().dirty,false);assert.equal(w.EmilyEditor.getState().active,false);dom.window.close();
});

test('rascunho em arquivo reaparece ao entrar no editor e pode ser descartado ao sair',async()=>{
 const d=blank();d.elements['id:btn-novo']={label:'Recuperado'};
 const{w,dom,pause}=await fixture({saved_at:100,base_revision:'base',document:d});
 assert.equal(w.document.querySelector('#btn-novo span').textContent,'Recuperado');assert.ok(w.EmilyEditor.getState().dirty);
 w.EmilyEditor.requestClose(true);w.document.getElementById('editor-close-discard').click();await pause();
 assert.equal(w.EmilyEditor.getState().dirty,false);assert.equal(w.document.querySelector('#btn-novo span').textContent,'Nova conversa');assert.equal(w.localStorage.getItem('emily-editor-draft-v1'),null);dom.window.close();
});

test('desfazer até o layout salvo cancela autosave pendente e restaurar sai da aba removida',async()=>{
 const{w,dom}=await fixture();w.document.getElementById('btn-novo').click();let input=w.document.querySelector('[data-editor-field=label]');input.value='Temporário';input.dispatchEvent(new w.Event('input',{bubbles:true}));w.EmilyEditor.undo();
 await new Promise(r=>w.setTimeout(r,850));assert.equal(w.editorCalls.includes('editor_rascunho'),false);assert.ok(w.editorCalls.includes('editor_limpar_rascunho'));
 w.document.getElementById('editor-add-page').click();assert.ok(w.document.querySelector('.editor-custom-page'));
 w.document.getElementById('editor-reset-all').click();assert.equal(w.document.querySelector('.editor-custom-page'),null);assert.equal(w.EmilyEditor.getState().document.pages.length,0);dom.window.close();
});

test('modo navegar mantém ações, mover usa grade e rejeita comando de seleção antiga',async()=>{
 const{w,dom,pause}=await fixture();let clicks=0;const button=w.document.getElementById('btn-novo');button.onclick=()=>clicks++;
 w.document.getElementById('editor-interact').click();button.click();assert.equal(clicks,1);
 w.document.getElementById('editor-move').click();button.click();assert.equal(clicks,1);
 button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles.x,8);
 button.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowDown',shiftKey:true,bubbles:true}));assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles.y,1);
 w.EmilyEditor.command({kind:'field',selected:'id:errado',field:'label',value:'Não aplicar'});assert.notEqual(button.querySelector('span').textContent,'Não aplicar');dom.window.close();
});

test('paleta HTML escolhe cor, padrão desfaz override e dropdown escuro mantém onchange',async()=>{
 const{w,dom,pause}=await fixture();w.eval(fs.readFileSync(path.join(__dirname,'../web/editor-controls.js'),'utf8'));w.eval(fs.readFileSync(path.join(__dirname,'../web/dark-controls.js'),'utf8'));
 w.document.getElementById('btn-novo').click();await pause();
 assert.equal(w.document.querySelector('input[type=color]'),null);
 const field=w.document.querySelector('[data-editor-field=backgroundColor]'),box=field.closest('.editor-color-control');box.querySelector('[data-color-toggle]').click();assert.equal(box.querySelector('.editor-color-picker').hidden,false);box.querySelector('[data-color-preset="#c96442"]').click();assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles.backgroundColor,'#c96442');
 box.querySelector('[data-color-clear]').click();assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles.backgroundColor,undefined);
 const select=w.document.getElementById('editor-element-list');const trigger=select.nextElementSibling;assert.ok(trigger.classList.contains('emily-native-select'));trigger.click();assert.ok(w.document.querySelector('.emily-select-popup'));
 const option=w.document.querySelector('.emily-select-popup [data-select-value="id:titulo"]');assert.ok(option);option.click();await pause();assert.equal(w.EmilyEditor.getState().selected,'id:titulo');dom.window.close();
});

test('janela de propriedades sincroniza edição e atalhos mantendo um único histórico',async()=>{
 const{w,dom,pause}=await fixture();let state={},version=0;const old=w.api;w.api=async(name,...args)=>{if(name==='editor_painel_estado'){state=JSON.parse(JSON.stringify(args[0]));version++;return{ok:true};}return old(name,...args);};
 w.document.getElementById('btn-novo').click();await pause();
 const preview=path.join(__dirname,'../output/editor-detached-2026-10-07/preview');fs.mkdirSync(preview,{recursive:true});fs.writeFileSync(path.join(preview,'state.json'),JSON.stringify(state));
 const child=new JSDOM(fs.readFileSync(path.join(__dirname,'../web/editor-panel.html'),'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,url:'http://localhost/editor-panel.html'});const c=child.window;c.scrollTo=()=>{};c.pywebview={api:{estado:async after=>({ok:true,changed:after!==version,version,state}),comando:async command=>{w.EmilyEditor.command(command);return{ok:true};}}};
 c.eval(fs.readFileSync(path.join(__dirname,'../web/editor-panel.js'),'utf8'));await new Promise(r=>c.setTimeout(r,80));
 const input=c.document.querySelector('[data-editor-field=label]');assert.ok(input);input.value='Pelo painel';input.dispatchEvent(new c.Event('input',{bubbles:true}));await pause();assert.equal(w.document.querySelector('#btn-novo span').textContent,'Pelo painel');
 c.document.dispatchEvent(new c.KeyboardEvent('keydown',{key:'z',ctrlKey:true,bubbles:true}));await pause();assert.equal(w.document.querySelector('#btn-novo span').textContent,'Nova conversa');
 const align=c.document.querySelector('[data-editor-field=textAlign]');align.value='center';align.dispatchEvent(new c.Event('change',{bubbles:true}));await pause();assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles.textAlign,'center');
 c.document.querySelector('[data-panel-mode=interact]').click();await pause();assert.equal(w.EmilyEditor.getState().mode,'interact');
 child.window.close();dom.window.close();
});

test('dropdown de outra página permanece personalizável após substituir controle nativo',async()=>{
 const{w,dom,pause}=await fixture();const select=w.document.createElement('select');select.id='teste-dropdown';select.innerHTML='<option value="a">Primeira</option><option value="b">Segunda</option>';w.document.getElementById('inicio').append(select);w.eval(fs.readFileSync(path.join(__dirname,'../web/dark-controls.js'),'utf8'));await pause();
 const button=select.nextElementSibling;button.click();assert.equal(w.EmilyEditor.getState().selected,'id:teste-dropdown');assert.equal(button.dataset.emilyEditorKey,'id:teste-dropdown');const width=w.document.querySelector('[data-editor-field=width]');width.value='220';width.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(w.getComputedStyle(button).width,'220px');dom.window.close();
});

test('renomeia título composto sem acrescentar legenda; descrição e ícone permanecem',async()=>{
 const{w,dom,pause}=await fixture();const b=w.document.createElement('button');b.id='modelo-composto';b.innerHTML='<svg></svg><span class="pi-txt"><strong>Claude Sonnet 4.5</strong><small>claude-sonnet-5.5</small></span>';w.document.getElementById('inicio').append(b);await pause();b.click();let label=w.document.querySelector('[data-editor-field=label]');assert.equal(label.value,'Claude Sonnet 4.5');label.value='Meu Sonnet';label.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(b.querySelector('strong').textContent,'Meu Sonnet');assert.equal(b.querySelector('small').textContent,'claude-sonnet-5.5');assert.equal(b.querySelectorAll('.editor-caption').length,0);assert.ok(b.querySelector('svg'));w.EmilyEditor.undo();assert.equal(b.querySelector('strong').textContent,'Claude Sonnet 4.5');w.EmilyEditor.redo();assert.equal(b.querySelector('strong').textContent,'Meu Sonnet');
 b.querySelector('small').click();label=w.document.querySelector('[data-editor-field=label]');label.value='Descrição própria';label.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(b.querySelector('small').textContent,'Descrição própria');assert.equal(b.querySelector('strong').textContent,'Meu Sonnet');w.EmilyEditor.undo();assert.equal(b.querySelector('small').textContent,'claude-sonnet-5.5');dom.window.close();
});
test('nome vazio não passa a editar a descrição e rótulo de lista sobrevive a recriação',async()=>{
 const{w,dom,pause}=await fixture();const b=w.document.createElement('button');b.dataset.emilyEditorKey='id:modelos|option.abc';b.innerHTML='<span><strong>Nome</strong><small>ID técnico</small></span>';w.document.getElementById('inicio').append(b);await pause();b.click();const input=w.document.querySelector('[data-editor-field=label]');input.value='';input.dispatchEvent(new w.Event('input',{bubbles:true}));input.value='Renomeado';input.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(b.querySelector('strong').textContent,'Renomeado');assert.equal(b.querySelector('small').textContent,'ID técnico');const fresh=b.cloneNode(true);fresh.querySelector('strong').textContent='Nome';b.replaceWith(fresh);await pause();assert.equal(fresh.querySelector('strong').textContent,'Renomeado');dom.window.close();
});
test('Delete remove elemento existente, botão exclui e histórico restaura; texto não é excluído ao digitar',async()=>{
 const{w,dom,pause}=await fixture();const b=w.document.getElementById('btn-novo');b.click();const input=w.document.querySelector('[data-editor-field=label]');input.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Delete',bubbles:true}));assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'],undefined);w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Delete',bubbles:true}));assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].hidden,true);w.EmilyEditor.undo();assert.equal(b.classList.contains('editor-hidden'),false);w.document.getElementById('editor-delete').click();assert.equal(b.classList.contains('editor-hidden'),true);w.EmilyEditor.undo();assert.equal(b.classList.contains('editor-hidden'),false);dom.window.close();
});
test('estrelinha abre chat do elemento e resultado visual entra no desfazer sem mudar seleção',async()=>{
 const{w,dom,pause}=await fixture();const original=w.api;let sent,job=null;w.api=async(name,...args)=>{if(name==='editor_ai_enviar'){sent=args;job={id:'testjob',running:false,selected:args[1].key,status:'Concluído',phase:'done',result:{files:[],layout:{label:'Feito pela Emily'},message:'Ajustei o nome.'}};return{ok:true,id:job.id};}if(name==='editor_ai_estado')return{ok:true,job};return original(name,...args);};
 w.document.getElementById('btn-novo').click();w.document.querySelector('.editor-ai-star').click();assert.equal(w.document.getElementById('editor-ai-chat').hidden,false);const prompt=w.document.getElementById('editor-ai-prompt');prompt.value='Mude o nome';prompt.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await pause();await pause();assert.equal(sent[1].key,'id:btn-novo');assert.equal(w.document.querySelector('#btn-novo span').textContent,'Feito pela Emily');w.EmilyEditor.undo();assert.equal(w.document.querySelector('#btn-novo span').textContent,'Nova conversa');assert.ok(w.document.getElementById('editor-ai-messages').textContent.includes('Ajustei'));dom.window.close();
});

test('título com trechos inline é renomeado integralmente e restaura estrutura original',async()=>{
 const{w,dom,pause}=await fixture();const heading=w.document.getElementById('titulo');heading.innerHTML='Boa tarde, <span>Vitor</span>.';await pause();heading.click();let input=w.document.querySelector('[data-editor-field=label]');assert.equal(input.value,'Boa tarde, Vitor.');input.value='Olá, meu amigo';input.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(heading.textContent,'Olá, meu amigo');assert.ok(heading.querySelector('span'));w.EmilyEditor.undo();assert.equal(heading.textContent,'Boa tarde, Vitor.');dom.window.close();
});

test('atualização ao vivo recupera modo, seleção e histórico anterior',async()=>{
 const one=blank();one.elements['id:btn-novo']={label:'Personalizado'};const two=JSON.parse(JSON.stringify(one));two.elements['id:btn-novo'].styles={width:180};
 const{w,dom,pause}=await fixture(null,{revision:'base',document:two,selected:'id:btn-novo',mode:'interact',history:{stack:[blank(),one,two],index:2}});
 assert.equal(w.EmilyEditor.getState().active,true);assert.equal(w.EmilyEditor.getState().mode,'interact');assert.equal(w.EmilyEditor.getState().selected,'id:btn-novo');assert.equal(w.document.querySelector('#btn-novo span').textContent,'Personalizado');w.EmilyEditor.undo();assert.equal(w.EmilyEditor.getState().document.elements['id:btn-novo'].styles,undefined);assert.equal(w.document.querySelector('#btn-novo span').textContent,'Personalizado');w.EmilyEditor.undo();assert.equal(w.document.querySelector('#btn-novo span').textContent,'Nova conversa');dom.window.close();
});

test('elementos profundamente aninhados recebem identidade estável e continuam editáveis',async()=>{
 const{w,dom,pause}=await fixture();let container=w.document.getElementById('inicio');for(let i=0;i<45;i++){const child=w.document.createElement('div');child.className='container-com-nome-longo';container.append(child);container=child;}const button=w.document.createElement('button');button.textContent='Profundo';container.append(button);await pause();button.click();const selected=w.EmilyEditor.getState().selected;assert.ok(selected&&selected.length<=350);const input=w.document.querySelector('[data-editor-field=label]');input.value='Alterado';input.dispatchEvent(new w.Event('input',{bubbles:true}));assert.equal(button.textContent,'Alterado');w.EmilyEditor.undo();assert.equal(button.textContent,'Profundo');dom.window.close();
});

test('mini chat usa o Markdown real, prévias compactas e envia imagem com pedido',async()=>{
 const{w,dom,pause}=await fixture();
 try{
 const app=fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8');
 const code=app.slice(app.indexOf('const esc = t =>'),app.indexOf('function toast(msg'));
 w.eval('const svg=()=>"<svg></svg>", ICO={copiar:""};'+code);
 // Simula a mesma decodificação/canvas do navegador; a validade real é testada no backend.
 w.Image=class{set src(v){this.naturalWidth=800;this.naturalHeight=600;w.setTimeout(()=>this.onload(),0);}};
 w.HTMLCanvasElement.prototype.getContext=()=>({drawImage:()=>{}});
 w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/webp;base64,UklGRg==';
 let sent,job=null;const old=w.api;
 w.api=async(name,...args)=>{if(name==='editor_ai_enviar'){sent=args;job={id:'images',running:false,status:'Concluído',phase:'done',selected:args[1].key,result:{files:[],layout:{},message:'## Pronto\n\n**Ajustei** a imagem.\n\n- Fundo removido\n- Ícone aplicado\n\n```js\nconst cor = "verde";\n```\n\n<script>bad()</script>'}};return{ok:true,id:job.id};}if(name==='editor_ai_estado')return{ok:true,job};return old(name,...args);};
 w.document.getElementById('btn-novo').click();w.document.querySelector('.editor-ai-star').click();
 const input=w.document.getElementById('editor-ai-files');Object.defineProperty(input,'files',{configurable:true,value:[new w.File(['png'],'referencia.png',{type:'image/png'})]});input.dispatchEvent(new w.Event('change',{bubbles:true}));for(let i=0;i<80&&!w.document.querySelector('.editor-ai-attachment');i++)await pause();
 assert.equal(w.document.querySelectorAll('.editor-ai-attachment').length,1);
 const prompt=w.document.getElementById('editor-ai-prompt');prompt.value='Use minha imagem';prompt.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));await pause();await pause();
 assert.equal(sent[2].length,1);assert.equal(sent[2][0].name,'referencia.png');assert.equal(w.document.querySelectorAll('.editor-ai-attachment').length,0);
 assert.ok(w.document.querySelector('.editor-ai-reference'));assert.ok(w.document.querySelector('#editor-ai-messages h2'));assert.ok(w.document.querySelector('#editor-ai-messages strong'));assert.equal(w.document.querySelectorAll('#editor-ai-messages li').length,2);assert.ok(w.document.querySelector('#editor-ai-messages pre code'));assert.equal(w.document.querySelector('#editor-ai-messages script'),null);
 assert.ok(w.document.querySelector('.editor-ai-bubble.emily').dataset.raw.includes('**Ajustei**'));
 }finally{dom.window.close();}
});

test('clipboard Wayland sem File usa fallback nativo sem encaminhar ao chat principal',async()=>{
 const{w,dom,pause}=await fixture();try{
 w.Image=class{set src(v){this.naturalWidth=80;this.naturalHeight=60;w.setTimeout(()=>this.onload(),0);}};
 w.HTMLCanvasElement.prototype.getContext=()=>({drawImage:()=>{}});w.HTMLCanvasElement.prototype.toDataURL=()=> 'data:image/webp;base64,UklGRg==';
 w.fetch=async()=>({blob:async()=>new w.Blob(['image'],{type:'image/webp'})});
 let native=0,mainPaste=0;const old=w.api;w.api=async(name,...args)=>name==='editor_ai_clipboard'?(native++,{ok:true,images:[{name:'clipboard.webp',data:'data:image/webp;base64,UklGRg=='}]}):old(name,...args);
 w.document.addEventListener('paste',()=>mainPaste++);
 w.document.getElementById('btn-novo').click();w.document.querySelector('.editor-ai-star').click();
 const e=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(e,'clipboardData',{value:{types:['image/png'],items:[{kind:'file',type:'image/png',getAsFile:()=>null}],files:[],getData:()=>''}});
 w.document.getElementById('editor-ai-prompt').dispatchEvent(e);assert.ok(e.defaultPrevented);await pause();await pause();
 assert.equal(native,1);assert.equal(mainPaste,0);assert.equal(w.document.querySelectorAll('.editor-ai-attachment').length,1);
 const text=new w.Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(text,'clipboardData',{value:{types:['text/plain'],items:[],files:[],getData:t=>t==='text/plain'?'meu pedido':''}});w.document.getElementById('editor-ai-prompt').dispatchEvent(text);await pause();assert.equal(text.defaultPrevented,false);assert.equal(native,1);
 }finally{dom.window.close();}
});

test('arrastar URI sem File bloqueia navegação mesmo fora do mini chat e mantém interface em falha',async()=>{
 const{w,dom,pause}=await fixture();try{
 let paths=[],bubbled=0;const old=w.api;w.api=async(name,...args)=>name==='editor_ai_arquivos'?(paths=args[0],{ok:true,images:[]}):old(name,...args);
 w.document.addEventListener('drop',()=>bubbled++);w.document.getElementById('btn-novo').click();w.document.querySelector('.editor-ai-star').click();
 const dt={types:new Set(['text/uri-list']),files:[],items:[],getData:t=>t==='text/uri-list'?'file:///home/user/ref%20image.png':''};
 const over=new w.Event('dragover',{bubbles:true,cancelable:true});Object.defineProperty(over,'dataTransfer',{value:dt});w.document.body.dispatchEvent(over);assert.ok(over.defaultPrevented);
 const drop=new w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(drop,'dataTransfer',{value:dt});w.document.body.dispatchEvent(drop);assert.ok(drop.defaultPrevented);await pause();assert.deepEqual([...paths],['file:///home/user/ref%20image.png']);assert.equal(bubbled,0);assert.equal(w.document.querySelector('#editor-ai-chat').hidden,false);assert.ok(w.document.querySelector('#btn-editor'));assert.ok(w.document.querySelector('#editor-ai-messages').textContent.includes('interface continua aberta'));
 const empty=new w.Event('drop',{bubbles:true,cancelable:true});Object.defineProperty(empty,'dataTransfer',{value:{types:[],files:[],getData:()=>''}});w.document.body.dispatchEvent(empty);assert.ok(empty.defaultPrevented);
 }finally{dom.window.close();}
});
