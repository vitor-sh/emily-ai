/* Native Android editor. The preview is isolated from published APK defaults. */
(() => {
'use strict';
const $=s=>document.querySelector(s),C=window.EmilyEditorCore;
let bridge,history,saved,revision,catalog=[],selected='',selectedInstance='',tree=[],frameInfo=null,mode='select',connected=false,connecting=false,recovery=null,busy=false,aiRunning=false,aiId='',aiHandled='',aiKey='',aiBefore=null,buildId='',buildHandled='',closeAfter=false,draftTimer,previewTimer,drag=null,attachments=[],imagePreparing=0,closing=false,codeDirty=false;
const clone=v=>JSON.parse(JSON.stringify(v)),doc=()=>history.current,dirty=()=>JSON.stringify(doc())!==JSON.stringify(saved)||codeDirty;
async function api(name,payload={}){const r=await bridge.command(name,payload);if(!r?.ok)throw new Error(r?.error||'Operação não concluída.');return r;}
function status(text,error=false){$('#status').textContent=text;$('#status').style.color=error?'#f1aaa0':'';$('#status').dataset.error=String(error);}
function item(){const n=tree.find(n=>n.key===selected&&(!selectedInstance||n.instance===selectedInstance))||tree.find(n=>n.key===selected);const base=catalog.find(i=>i.key===(n?.baseKey||selected));return {...(base||{kind:n?.kind||'Custom',file:n?.file||undefined}),key:selected,label:rule().label||n?.label||base?.label||selected};}
function rule(){return doc().elements[selected]||{};}
function tab(name){document.querySelectorAll('[data-content]').forEach(e=>e.hidden=e.dataset.content!==name);document.querySelectorAll('[data-tab]').forEach(e=>e.setAttribute('aria-pressed',String(e.dataset.tab===name)));}
function update(){
 $('#undo').disabled=busy||aiRunning||!history.canUndo;$('#redo').disabled=busy||aiRunning||!history.canRedo;$('#save').disabled=busy||aiRunning;$('#preview-build').disabled=busy||aiRunning;$('#connect').disabled=busy||aiRunning||connecting;$('#exit').disabled=busy;
 $('#fields').disabled=!selected||busy||aiRunning;
 $('#ai-send').disabled=busy||aiRunning||imagePreparing>0;$('#ai-attach').disabled=busy||aiRunning||imagePreparing>0;$('#ai-cancel').hidden=!aiRunning;
 document.querySelectorAll('[data-content=pages] input,[data-content=pages] select,[data-content=pages] button').forEach(e=>e.disabled=busy||aiRunning);
 if(!busy&&$('#status').dataset.error!=='true')status(dirty()?'Alterações em prévia · rascunho salvo automaticamente':'Layout salvo · use Selecionar ou Navegar/testar');
}
async function flush(){if(!history)return;await api('draft',{document:doc(),revision});}
function changed(mutator,group=''){
 if(busy||aiRunning)return;$('#status').dataset.error='false';const next=doc();mutator(next);history.push(next,group);update();renderPages();outline();
 clearTimeout(draftTimer);draftTimer=setTimeout(()=>flush().catch(e=>status('Falha ao salvar rascunho: '+e.message,true)),400);
 clearTimeout(previewTimer);previewTimer=setTimeout(()=>connected&&api('preview',{document:doc()}).catch(e=>status('Ajuste mantido no rascunho; prévia USB: '+e.message,true)),150);
}
function select(key,instance=''){selected=key;selectedInstance=instance;renderFields();outline();}
function findElements(){
 const q=$('#search').value.toLowerCase(),select=$('#elements');select.replaceChildren();
 const live=tree.filter(n=>n.kind!=='Spacer').map(n=>({...catalog.find(c=>c.key===(n.baseKey||n.key)),key:n.key,kind:n.kind,label:n.label||catalog.find(c=>c.key===(n.baseKey||n.key))?.label}));const entries=[...live,...catalog.filter(c=>!live.some(n=>n.key===c.key))];
 for(const e of entries){if(q&&!`${e.label} ${e.kind} ${e.file} ${e.key}`.toLowerCase().includes(q)&&e.key!==selected)continue;const o=document.createElement('option');o.value=e.key;o.textContent=(doc().elements[e.key]?.label||e.label||e.kind)+' · '+(e.file||'Página personalizada');o.selected=e.key===selected;select.append(o);}
 if(!selected)select.selectedIndex=-1;
}
function renderFields(){
 const r=rule(),i=item();$('#selected-title').textContent=selected?(r.label||i.label||i.kind):'Escolha o que editar';$('#element-source').textContent=selected?`${i.kind} · ${i.file||'Página personalizada'}${i.line?' · linha '+i.line:''}`:'';
 document.querySelectorAll('[data-field]').forEach(e=>{e.value=r[e.dataset.field]??(e.dataset.field==='action'?'original':e.dataset.field==='label'?(tree.find(n=>n.key===selected)?.label||''):'');});
 findElements();update();
 const nativeAction=/Button$/.test(i.kind)||i.kind==='FloatingActionButton'||i.kind==='Custom';$('[data-field=action]').disabled=!selected||!nativeAction||busy||aiRunning;
 $('[data-field=label]').disabled=!selected||(i.kind!=='Text'&&i.kind!=='Custom')||busy||aiRunning;
 $('[data-field=fontSize]').disabled=!selected||i.kind!=='Text'||busy||aiRunning;
 $('#icon').disabled=i.kind!=='Icon'||busy||aiRunning;$('#clear-icon').disabled=i.kind!=='Icon'||busy||aiRunning;
 $('#action-help').textContent=nativeAction?'A ação original é preservada até você escolher outra. Para funções novas, peça à Emily.':'Para alterar a função deste contêiner ou controle, peça à Emily; isso requer recompilar Kotlin.';
}
function screenRect(){if(!frameInfo)return null;const imageRect=$('#frame').getBoundingClientRect(),r=imageRect.width&&imageRect.height?imageRect:$('#screen').getBoundingClientRect(),scale=Math.min(r.width/frameInfo.width,r.height/frameInfo.height);return {r,scale,x:(r.width-frameInfo.width*scale)/2,y:(r.height-frameInfo.height*scale)/2};}
function point(e){const m=screenRect();return m?[(e.clientX-m.r.left-m.x)/m.scale,(e.clientY-m.r.top-m.y)/m.scale]:null;}
function hits(x,y){return tree.filter(n=>n.kind!=='Spacer'&&n.bounds?.length===4&&n.bounds[2]>n.bounds[0]&&n.bounds[3]>n.bounds[1]&&x>=n.bounds[0]&&y>=n.bounds[1]&&x<=n.bounds[2]&&y<=n.bounds[3]).sort((a,b)=>(a.bounds[2]-a.bounds[0])*(a.bounds[3]-a.bounds[1])-(b.bounds[2]-b.bounds[0])*(b.bounds[3]-b.bounds[1]));}
function candidates(nodes){const menu=$('#nearby');menu.replaceChildren();for(const n of nodes){const o=document.createElement('option');o.value=n.instance;o.textContent=(n.label||catalog.find(i=>i.key===(n.baseKey||n.key))?.label||n.kind)+' · '+n.kind;menu.append(o);}menu.hidden=nodes.length<2;}
function outline(){
 const n=tree.find(n=>n.key===selected&&(!selectedInstance||n.instance===selectedInstance))||tree.find(n=>n.key===selected);if(n&&n.instance!==selectedInstance){selectedInstance=n.instance;renderFields();}const m=screenRect(),show=!!n&&!!m&&mode!=='interact';$('#outline').hidden=!show;$('#star').hidden=!show;
 if(!show)return;const b=n.bounds;Object.assign($('#outline').style,{left:m.x+b[0]*m.scale+'px',top:m.y+b[1]*m.scale+'px',width:(b[2]-b[0])*m.scale+'px',height:(b[3]-b[1])*m.scale+'px'});Object.assign($('#star').style,{left:Math.min(m.r.width-36,m.x+b[2]*m.scale)+'px',top:Math.max(2,m.y+b[1]*m.scale-20)+'px'});
}
function setMode(next){mode=next;document.querySelectorAll('[data-mode]').forEach(e=>e.setAttribute('aria-pressed',String(e.dataset.mode===mode)));$('#mode-help').textContent={select:'Clique no texto, botão ou seção para editar.',move:'Selecione e arraste. O deslocamento respeita o layout nativo.',resize:'Arraste para ajustar largura e altura. O contêiner limita o tamanho.',interact:'Clique e arraste para usar o app normalmente. Ações no celular são reais.'}[mode];outline();}
async function pollFrame(){
 try{if(connected&&!busy&&!drag){const r=await api('frame');frameInfo=r;tree=r.nodes||[];const source=r.stream||r.image;if(source&&$('#frame').getAttribute('src')!==source)$('#frame').src=source;$('#screen').style.aspectRatio=r.width+'/'+r.height;$('#screen-empty').hidden=true;outline();$('#connection-state').textContent=r.focused===false?'Volte para a Emily no celular · janela do Android ou de outro app em primeiro plano':tree.length?(r.stream?'Vídeo contínuo por USB':'Capturas por USB')+' · '+tree.length+' elementos visíveis':'App conectado. Use Atualizar prévia se ainda não houver elementos selecionáveis.';}}
 catch(e){$('#connection-state').textContent='Prévia indisponível: '+e.message;}
 finally{setTimeout(pollFrame,connected?180:1500);}
}
function mutateRule(key,values){changed(d=>{d.elements[key]={...(d.elements[key]||{}),...values};},'element:'+key);}
function parent(){const n=tree.find(n=>n.key===selected&&(!selectedInstance||n.instance===selectedInstance));if(!n)return;const b=n.bounds,candidates=hits((b[0]+b[2])/2,(b[1]+b[3])/2),index=candidates.findIndex(c=>c.key===selected);const next=candidates.slice(index+1).find(c=>c.key!==selected);if(next)select(next.key);else status('Este é o contêiner mais externo visível.');}
async function input(kind,values){try{await api('input',{kind,values});}catch(e){status(e.message,true);}}
$('#screen').addEventListener('pointerdown',e=>{
 if(e.target.closest('#star')||!connected||busy||e.button!==0)return;const p=point(e);if(!p)return;e.preventDefault();$('#screen').setPointerCapture(e.pointerId);
 if(frameInfo.focused===false){status('Volte para a Emily no celular para usar a prévia. O botão Voltar continua disponível.',true);return;}if(mode==='interact'){drag={start:p,mode};return;}
 const choices=hits(...p);if(frameInfo.focused===false){status('Volte para a Emily no celular: a tela atual pertence ao Android ou a outro app.',true);return;}const hit=e.altKey?(choices[(choices.findIndex(n=>n.key===selected&&n.instance===selectedInstance)+1)%choices.length]):choices[0];if(!hit){status('Esta área pertence ao Android ou não tem um componente editável.');return;}select(hit.key,hit.instance);const b=hit.bounds;candidates(tree.filter(n=>n.kind!=='Spacer'&&n.bounds?.length===4&&n.bounds[2]>n.bounds[0]&&n.bounds[3]>n.bounds[1]&&n.bounds[0]>=b[0]&&n.bounds[1]>=b[1]&&n.bounds[2]<=b[2]&&n.bounds[3]<=b[3]).sort((a,b)=>a.bounds[1]-b.bounds[1]));
 if(mode==='move'||mode==='resize')drag={start:p,mode,key:selected,original:clone(rule()),node:hit,density:frameInfo.density||1};
});
$('#screen').addEventListener('pointerup',e=>{
 if(!drag)return;const end=point(e),d=drag;drag=null;if(!end)return;
 if(d.mode==='interact'){const far=Math.hypot(end[0]-d.start[0],end[1]-d.start[1])>12;input(far?'swipe':'tap',far?[...d.start,...end]:end);return;}
 const dx=(end[0]-d.start[0])/d.density,dy=(end[1]-d.start[1])/d.density,b=d.node.bounds;
 mutateRule(d.key,d.mode==='move'?{x:Math.max(-2400,Math.min(2400,Math.round((d.original.x||0)+dx))),y:Math.max(-2400,Math.min(2400,Math.round((d.original.y||0)+dy)))}:{width:Math.max(1,Math.min(2400,Math.round((d.original.width||(b[2]-b[0])/d.density)+dx))),height:Math.max(1,Math.min(2400,Math.round((d.original.height||(b[3]-b[1])/d.density)+dy)))});renderFields();
});
$('#screen').addEventListener('pointercancel',()=>drag=null);
$('#screen').addEventListener('wheel',e=>{if(mode!=='interact'||!connected||busy)return;e.preventDefault();const p=point(e);input('swipe',[p[0],p[1]+Math.sign(e.deltaY)*100,p[0],p[1]-Math.sign(e.deltaY)*100]);},{passive:false});
function undo(redo=false){if(busy||aiRunning)return;redo?history.redo():history.undo();renderFields();renderPages();outline();flush().catch(e=>status(e.message,true));if(connected)api('preview',{document:doc()}).catch(e=>status(e.message,true));}
function remove(){if(!selected||busy||aiRunning)return;changed(d=>{let found=false;for(const page of d.pages){const ix=page.items.findIndex(i=>i.id===selected);if(ix>=0){page.items.splice(ix,1);delete d.elements[selected];found=true;}}if(!found)d.elements[selected]={...(d.elements[selected]||{}),hidden:true};});renderFields();}
function renderPages(){
 const select=$('#pages'),previous=select.value;select.replaceChildren();for(const p of doc().pages){const o=document.createElement('option');o.value=p.id;o.textContent=p.title;select.append(o);}if(doc().pages.some(p=>p.id===previous))select.value=previous;
 $('#page-items').replaceChildren();const page=doc().pages.find(p=>p.id===select.value);for(const i of page?.items||[]){const li=document.createElement('li'),b=document.createElement('button');li.append(document.createTextNode((i.label||i.type)+' · '+i.type));b.textContent='Editar';b.onclick=()=>{selectElementCustom(i);tab('element');};li.append(b);$('#page-items').append(li);}
}
function selectElementCustom(i){if(!catalog.some(c=>c.key===i.id))catalog.push({key:i.id,kind:'Custom',label:i.label});select(i.id);}
function message(text,user=false,images=[]){const e=document.createElement('div');e.className='bubble'+(user?' user':'');if(user)e.textContent=text;else e.innerHTML=markdown(text);for(const im of images){const img=document.createElement('img');img.src=im.preview||im.data;img.alt=im.name||'Referência';e.append(img);}$('#ai-messages').append(e);$('#ai-messages').scrollTop=$('#ai-messages').scrollHeight;}
function renderImages(){const el=$('#ai-images');el.replaceChildren();attachments.forEach((im,i)=>{const d=document.createElement('div'),img=document.createElement('img'),b=document.createElement('button');img.src=im.preview;img.alt=im.name;b.textContent='×';b.onclick=()=>{attachments.splice(i,1);renderImages();};d.append(img,b);el.append(d);});update();}
async function prepareImage(file){
 if(file.size>4*1024*1024||!/^image\/(png|jpeg|webp|gif|x-icon|vnd.microsoft.icon)$/.test(file.type))throw Error('Use PNG/JPEG/WebP/GIF de até 4 MB.');
 const data=await new Promise((res,rej)=>{const reader=new FileReader();reader.onload=()=>res(reader.result);reader.onerror=rej;reader.readAsDataURL(file);});
 const im=await new Promise((res,rej)=>{const image=new Image();image.onload=()=>res(image);image.onerror=()=>rej(Error('Imagem inválida.'));image.src=data;});if(im.naturalWidth*im.naturalHeight>20000000)throw Error('Use imagens de até 20 megapixels.');
 const canvas=document.createElement('canvas'),scale=Math.min(1,2048/im.naturalWidth,2048/im.naturalHeight);canvas.width=Math.round(im.naturalWidth*scale);canvas.height=Math.round(im.naturalHeight*scale);canvas.getContext('2d').drawImage(im,0,0,canvas.width,canvas.height);const normalized=canvas.toDataURL('image/webp',.9);
 const small=document.createElement('canvas');small.width=Math.round(canvas.width*Math.min(1,160/canvas.width,160/canvas.height));small.height=Math.round(canvas.height*Math.min(1,160/canvas.width,160/canvas.height));small.getContext('2d').drawImage(canvas,0,0,small.width,small.height);return{name:file.name,data:normalized,preview:small.toDataURL('image/webp',.8)};
}
async function addImages(files){imagePreparing++;update();try{for(const f of files){if(attachments.length>=4)throw Error('Até quatro imagens por pedido.');attachments.push(await prepareImage(f));}renderImages();}catch(e){message(e.message);}finally{imagePreparing--;update();}}
async function responseImages(r){const fs=[];for(const im of r.images||[]){const blob=await(await fetch(im.data)).blob();fs.push(new File([blob],im.name,{type:blob.type}));}await addImages(fs);for(const e of r.errors||[])message(e);}
async function sendAI(){
 const prompt=$('#ai-prompt').value.trim();if(!prompt||aiRunning||imagePreparing||busy)return;if(!selected){message('Selecione um elemento antes de pedir uma mudança.');return;}
 try{clearTimeout(draftTimer);clearTimeout(previewTimer);await flush();aiRunning=true;update();aiKey=selected;aiBefore=clone(rule());const images=attachments.map(({name,data})=>({name,data})),r=await api('ai',{prompt,document:doc(),revision,context:{key:selected,...item(),rule:rule(),platform:'Android Compose'},images});aiId=r.id;aiRunning=true;message(prompt,true,attachments);attachments=[];renderImages();$('#ai-prompt').value='';update();}catch(e){aiRunning=false;update();message(e.message);}
}
async function build(publish){try{await flush();const r=await api('build',{document:doc(),revision,publish});busy=true;buildId=r.job.id;revision=r.job.revision;status(r.job.status);update();}catch(e){status(e.message,true);closeAfter=false;}}
async function pollStatus(){
 try{
 const r=await api('status'),j=r.job,ai=r.ai?.job;
 if(j&&j.id===buildId){busy=j.running;if(busy)status(j.status);else if(buildHandled!==j.id){buildHandled=j.id;revision=j.revision;if(j.ok){if(j.publish){saved=clone(j.document);codeDirty=false;$('#ai-undo').hidden=true;}update();status(j.status);if(closeAfter){closeAfter=false;await finish(false);}}else{closeAfter=false;status(j.error,true);update();status(j.error,true);}}}
 if(ai&&ai.id===aiId){aiRunning=ai.running;$('#ai-status').textContent=ai.status;$('#ai-status').classList.toggle('busy',ai.running);update();if(!ai.running&&aiHandled!==ai.id){aiHandled=ai.id;const result=ai.result;if(ai.error)message(ai.error);if(result){
  if(result.document){changed(d=>{Object.keys(d).forEach(k=>delete d[k]);Object.assign(d,clone(result.document));});renderFields();}
  else if(result.layout&&Object.keys(result.layout).length){changed(d=>{d.elements[aiKey]={...(d.elements[aiKey]||{}),...result.layout};});renderFields();}
  if(!ai.error)message(result.message,false,result.images||[]);if(result.files?.length){codeDirty=true;message(result.preview_applied?'Código compilado, instalado e confirmado na prévia. Salvar e publicar envia o APK à Oracle.':'O código está no rascunho; a aplicação na prévia não foi confirmada.');$('#ai-undo').hidden=false;}

 }}}
 }catch(e){status('Falha ao consultar progresso: '+e.message,true);}finally{setTimeout(pollStatus,900);}
}
async function finish(discard){if(closing)return;try{closing=true;if(!discard)await flush();await api('finish',{discard});$('#close-dialog').hidden=true;connected=false;if(discard){history.reset(saved);codeDirty=false;renderFields();renderPages();}}catch(e){status(e.message,true);}finally{closing=false;}}
function requestClose(){if(busy||aiRunning){status('Conclua a publicação ou cancele a tarefa da Emily antes de sair.',true);return;}if(dirty()){$('#close-dialog').hidden=false;$('#close-cancel').focus();}else finish(false);}
async function ready(){
 bridge=window.pywebview?.api;if(!bridge){status('Abra esta janela pelo Editor da Emily.',true);return;}
 try{const r=await api('load');saved=clone(r.document);revision=r.revision;history=new C.History(saved,160);catalog=r.catalog;recovery=r.draft;codeDirty=!!r.pending_code;renderDevices(r.devices);renderFields();renderPages();$('#recover').disabled=!recovery;pollFrame();pollStatus();if(recovery&&JSON.stringify(recovery.document)!==JSON.stringify(saved))status('Há um rascunho recuperável. Abra Backup → Recuperar rascunho.');}
 catch(e){status('Não consegui abrir o projeto: '+e.message,true);}
}
function renderDevices(devices){const s=$('#devices'),old=s.value;s.replaceChildren();for(const d of devices){const o=document.createElement('option');o.value=d.serial;o.textContent=d.model+' · '+d.state;o.disabled=d.state!=='device';s.append(o);}if(devices.some(d=>d.serial===old))s.value=old;if(!devices.length){const o=document.createElement('option');o.textContent='Nenhum dispositivo';o.value='';s.append(o);}}
$('#refresh').onclick=async()=>{try{renderDevices((await api('devices')).devices);}catch(e){status(e.message,true);}};
$('#connect').onclick=async()=>{if(connecting||busy||aiRunning)return;connecting=true;connected=false;update();$('#connection-state').textContent='Conectando à prévia USB…';try{await api('connect',{serial:$('#devices').value});connected=true;await api('preview',{document:doc()});status('Prévia USB conectada.');}catch(e){connected=false;status(e.message,true);}finally{connecting=false;update();}};
$('#phone-type').onclick=async()=>{if(mode!=='interact'){status('Use Navegar/testar e toque em um campo de texto primeiro.',true);return;}try{await api('input',{kind:'text',values:[$('#phone-text').value]});$('#phone-text').value='';status('Texto inserido no app.');}catch(e){status(e.message,true);}};
$('#nearby').onchange=()=>{const n=tree.find(n=>n.instance===$('#nearby').value);if(n)select(n.key,n.instance);};$('#search').oninput=findElements;$('#elements').onchange=()=>select($('#elements').value);$('#parent').onclick=parent;
document.querySelectorAll('[data-field]').forEach(e=>e.addEventListener('change',()=>{if(!selected||busy||aiRunning)return;let value=e.value;const key=e.dataset.field;if(e.type==='number'&&value!==''){value=Number(value);if(!Number.isFinite(value)||value<Number(e.min)||value>Number(e.max)){status('Medida fora do intervalo permitido: '+e.min+' a '+e.max,true);return;}}if(['color','backgroundColor'].includes(key)&&value&&!/^#[\da-f]{6}(?:[\da-f]{2})?$/i.test(value)){status('Use uma cor hexadecimal, como #EDEBE7.',true);return;}changed(d=>{d.elements[selected]={...(d.elements[selected]||{})};if(value==='')delete d.elements[selected][key];else d.elements[selected][key]=value;},selected+':'+key);renderFields();}));
$('#undo').onclick=()=>undo();$('#redo').onclick=()=>undo(true);$('#delete').onclick=remove;$('#reset').onclick=()=>{if(selected)changed(d=>delete d.elements[selected]);renderFields();};$('#save').onclick=()=>build(true);$('#preview-build').onclick=()=>build(false);$('#exit').onclick=requestClose;
$('#star').onclick=$('#ask').onclick=()=>{tab('ai');$('#ai-prompt').focus();};document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>tab(b.dataset.tab));document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>input('key',[b.dataset.key]));
$('#pages').onchange=renderPages;$('#add-page').onclick=()=>{const title=$('#page-title').value.trim();if(!title)return;changed(d=>d.pages.push({id:'custom:'+crypto.randomUUID(),title,items:[]}));$('#page-title').value='';};$('#delete-page').onclick=()=>{changed(d=>{const page=d.pages.find(p=>p.id===$('#pages').value);for(const i of page?.items||[])delete d.elements[i.id];d.pages=d.pages.filter(p=>p.id!==$('#pages').value);});};$('#add-item').onclick=()=>{const page=$('#pages').value;if(!page)return;const entry={id:'custom:'+crypto.randomUUID(),type:$('#item-type').value,label:$('#item-label').value,action:$('#item-action').value};changed(d=>d.pages.find(p=>p.id===page).items.push(entry));selectElementCustom(entry);};
$('#ai-send').onclick=sendAI;$('#ai-prompt').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAI();}});$('#ai-cancel').onclick=()=>api('cancel').catch(e=>message(e.message));$('#ai-undo').onclick=async()=>{try{const result=await api('ai_undo',{id:aiId,document:doc(),revision});message('Código restaurado. A versão anterior está sendo compilada e aplicada automaticamente.');if(result.job){busy=true;buildId=result.job.id;update();}$('#ai-undo').hidden=true;codeDirty=!!result.pending_code;update();}catch(e){message(e.message);}};
$('#ai-attach').onclick=async()=>{try{await responseImages(await api('images'));}catch(e){message(e.message);}};
$('#ai-prompt').addEventListener('paste',e=>{const dt=e.clipboardData,files=[...(dt?.files||[])],types=[...(dt?.types||[])],images=files.filter(f=>f.type.startsWith('image/')),announced=images.length||[...(dt?.items||[])].some(i=>i.type.startsWith('image/'))||types.some(t=>t.startsWith('image/'));if(announced)e.preventDefault();e.stopPropagation();if(busy||aiRunning)return;if(images.length)addImages(images);else if(announced||!types.length)api('clipboard').then(responseImages).catch(err=>message('Não consegui ler a imagem: '+err.message));});
window.addEventListener('dragover',e=>{if([...(e.dataTransfer?.types||[])].some(t=>t==='Files'||t==='text/uri-list'))e.preventDefault();},true);
window.addEventListener('drop',async e=>{const dt=e.dataTransfer,files=[...(dt?.files||[])],types=[...(dt?.types||[])];if(!files.length&&!types.some(t=>t==='Files'||t==='text/uri-list'))return;e.preventDefault();e.stopImmediatePropagation();tab('ai');if(busy||aiRunning)return;if(files.length)await addImages(files);else {const paths=(dt?.getData('text/uri-list')||dt?.getData('x-special/gnome-copied-files')||'').split(/\r?\n/).filter(s=>s.startsWith('file:')||s.startsWith('/'));try{await responseImages(await api('image_paths',{paths}));}catch(err){message(err.message);}}},true);
$('#icon').onclick=async()=>{try{const r=await api('images');if(!r.images?.length)return;const blob=await(await fetch(r.images[0].data)).blob(),im=await prepareImage(new File([blob],r.images[0].name,{type:blob.type}));const image=new Image();image.src=im.data;await image.decode();const canvas=document.createElement('canvas'),scale=Math.min(1,512/image.naturalWidth,512/image.naturalHeight);canvas.width=Math.round(image.naturalWidth*scale);canvas.height=Math.round(image.naturalHeight*scale);canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);mutateRule(selected,{image:canvas.toDataURL('image/webp',.9)});}catch(e){status(e.message,true);}};$('#clear-icon').onclick=()=>changed(d=>{if(d.elements[selected])delete d.elements[selected].image;});
$('#recover').onclick=()=>{if(recovery){changed(d=>{Object.keys(d).forEach(k=>delete d[k]);Object.assign(d,clone(recovery.document));});recovery=null;$('#recover').disabled=true;renderFields();status('Rascunho recuperado na prévia. Confira antes de publicar.');}};
$('#export').onclick=async()=>{try{const r=await api('export',{document:doc()});if(r.saved)status('Layout exportado.');}catch(e){status(e.message,true);}};$('#import').onclick=()=>$('#import-file').click();$('#import-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>2_000_000)throw Error('Layout grande demais.');const d=JSON.parse(await file.text());await api('draft',{document:d,revision});changed(v=>{Object.keys(v).forEach(k=>delete v[k]);Object.assign(v,d);});renderFields();}catch(err){status('Importação recusada: '+err.message,true);}finally{e.target.value='';}};
$('#close-save').onclick=()=>{closeAfter=true;$('#close-dialog').hidden=true;build(true);};$('#close-discard').onclick=()=>finish(true);$('#close-cancel').onclick=()=>$('#close-dialog').hidden=true;
document.addEventListener('keydown',e=>{if(e.key==='Delete'&&!e.target.closest?.('input,textarea,select,[contenteditable=true]')){e.preventDefault();remove();}if(e.ctrlKey||e.metaKey){if(e.key.toLowerCase()==='s'){e.preventDefault();build(true);}else if(e.key.toLowerCase()==='z'&&!e.target.closest?.('input,textarea')){e.preventDefault();undo(e.shiftKey);}}});
document.addEventListener('click',e=>{const b=e.target.closest?.('.btn-copiar-cod');if(b)navigator.clipboard?.writeText(decodeURIComponent(b.dataset.cod)).catch(()=>{});});
window.AndroidEditor={requestClose,getState:()=>({selected,mode,document:doc(),dirty:dirty()})};window.addEventListener('resize',outline);if(window.pywebview?.api)ready();else window.addEventListener('pywebviewready',ready,{once:true});
})();
