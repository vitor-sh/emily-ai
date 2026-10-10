/* Editor visual: altera layout/dados declarativos e preserva os handlers reais. */
(() => {
  'use strict';
  const C = window.EmilyEditorCore, $ = s => document.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const editable = 'div,span,strong,small,a,ul,ol,li,dl,dt,dd,summary,details,table,tr,td,th,svg,img,button,input,textarea,select,h1,h2,h3,h4,label,p,section,nav,aside,main,header,footer,.secao,.cfg-nav-item,.app,.hero,.busca,.perfil,.linha-pe,.editor-custom-item';
  const excluded = '#btn-editor,#editor-toolbar,#editor-inspector,#editor-outline,#toasts,#yt-host,template,script,style,link,meta';
  const actions = {none:'Sem ação',inicio:'Tela inicial',nova_conversa:'Nova conversa',config:'Configurações',code:'Emily Code',cloud:'Arquivo da Emily',music:'Emily Music',navegador:'Navegador',xadrez:'Xadrez',agente_visual:'Controles do agente visual',logs:'Logs',ptt:'Falar com a Emily',captura:'Capturar tela',anexo:'Escolher arquivo',comando:'Pedir uma tarefa à Emily',pagina:'Abrir outra aba personalizada'};
  const colors = {backgroundColor:'Fundo',color:'Texto',borderColor:'Borda'};
  const numbers = {width:'Largura',height:'Altura',fontSize:'Fonte',borderRadius:'Arredondamento',borderWidth:'Borda',padding:'Espaço interno',gap:'Espaço entre itens',marginTop:'Margem superior',marginRight:'Margem direita',marginBottom:'Margem inferior',marginLeft:'Margem esquerda',minWidth:'Largura mínima',maxWidth:'Largura máxima',minHeight:'Altura mínima',maxHeight:'Altura máxima',opacity:'Opacidade',order:'Ordem no grupo',flexGrow:'Expandir no grupo',x:'Deslocamento X',y:'Deslocamento Y'};
  Object.assign(numbers,{fontSize:'Tamanho do texto (px)',borderRadius:'Cantos arredondados (px)',borderWidth:'Espessura da borda (px)',opacity:'Opacidade (0 invisível, 1 opaco)',padding:'Espaço interno (px)',gap:'Distância entre itens (px)',x:'Mover na horizontal (px)',y:'Mover na vertical (px)',flexGrow:'Dividir espaço livre (peso)'});
  const enums = {textAlign:['Alinhamento do texto','left','center','right'],fontWeight:['Peso da fonte','normal','400','500','600','700','bold'],display:['Layout','block','flex','grid','inline-flex'],flexDirection:['Direção','row','column','row-reverse','column-reverse'],justifyContent:['Distribuição','flex-start','center','flex-end','space-between','space-around'],alignItems:['Alinhamento dos itens','stretch','flex-start','center','flex-end'],gridTemplateColumns:['Colunas','1fr','1fr 1fr','1fr 1fr 1fr','1fr 1fr 1fr 1fr']};
  const themes = {'--bg':'Fundo geral','--bg-side':'Barra lateral','--bg-raise':'Cartões','--bg-hover':'Ao passar o mouse','--bg-active':'Itens ativos','--txt':'Texto principal','--txt-2':'Texto secundário','--txt-3':'Texto discreto','--acento':'Destaque','--acento-mo':'Destaque ao passar','--line':'Linhas','--line-forte':'Bordas','--ok':'Sucesso','--aviso':'Aviso','--erro':'Erro'};
  let doc = C.blank(), saved = C.clone(doc), history = new C.History(doc), revision = '', active = false, selecting = true, selected = '', saving = false, customPage = '', observer, initialized = false;
  let nodes = new Map(), original = new Map(), lastTheme = {}, pending = false, drag = null, appliedLabels = new WeakMap(), appliedTexts = new WeakMap();
  const draftKey = 'emily-editor-draft-v1';
  let mode='select',category='element',detached=false,panelSerial=Date.now()*1000,panelScheduled=false,lastPanel='',grid=8,snap=true,panelAssets=Date.now(),liveReload=false;
  let notice = '', recovery = null, draftTimer = null, draftFlight = Promise.resolve(), draftPending = null, stateSerial = Date.now()*1000, closeIntent = null, lastDraftTime = 0;
  const dirty = () => JSON.stringify(doc) !== JSON.stringify(saved);
  const own = node => node instanceof Element && !!node.closest('#btn-editor,#editor-toolbar,#editor-inspector,#editor-outline,#editor-close-dialog,#editor-ai-chat,[data-editor-owned=true]');
  const allowed = node => node instanceof Element && !own(node) && !node.closest(excluded);
  function key(node) {
    if (!node || !allowed(node)) return '';
    if(node._emilySelectSource){const alias=key(node._emilySelectSource);if(alias)node.dataset.emilyEditorKey=alias;return alias;}
    if (node.dataset.emilyEditorKey) return node.dataset.emilyEditorKey;
    let value;
    if (node.id) value = `id:${node.id}`;
    else if (node.dataset.cfgAbrir) value = `cfg:${node.dataset.cfgAbrir}`;
    else if (node.dataset.cfgSecao) value = `section:${node.dataset.cfgSecao}`;
    else {
      const parent = node.parentElement;
      const parentKey = parent && parent !== document.body ? key(parent) : 'root';
      if (!parentKey) return '';
      const index = [...parent.children].filter(s => s.tagName === node.tagName).indexOf(node);
      const component = [...node.classList].find(c=>!c.startsWith('editor-') && !c.startsWith('emily-select') && c!=='emily-native-select' && !['ativa','ativo','oculto','selecionado'].includes(c)) || 'element';
      value = `${parentKey}|${node.tagName.toLowerCase()}.${component}.${index}`;
    }
    if(value.length>350){let a=2166136261,b=3339675911;for(const c of value){a=Math.imul(a^c.charCodeAt(0),16777619);b=Math.imul(b^c.charCodeAt(0),2246822519);}value='auto:'+(a>>>0).toString(16)+(b>>>0).toString(16);}
    if (!/^[\w:|./@=-]+$/.test(value)) return '';
    node.dataset.emilyEditorKey = value;
    return value;
  }
  function indexNodes() {
    nodes = new Map();
    document.querySelectorAll(editable).forEach(node => { const k = key(node); if (k && (!nodes.get(k)?._emilySelectSource || node._emilySelectSource)) nodes.set(k, node); });
    // Contêineres intermediários também recebem identidade para movimentos.
    document.querySelectorAll('[data-emily-editor-key]').forEach(node => { if (allowed(node)&&(!nodes.get(node.dataset.emilyEditorKey)?._emilySelectSource||node._emilySelectSource)) nodes.set(node.dataset.emilyEditorKey,node); });
  }
  const info = k => doc.elements[k] || {};
  const itemFor = k => doc.pages.flatMap(p => p.items).find(i => i.id === k);
  const pageFor = k => doc.pages.find(p => p.id === k);
  const name = node => (labelText(node) || node?.getAttribute('aria-label') || node?.getAttribute('title') || node?.placeholder || node?.id || node?.tagName || '').trim().replace(/\s+/g,' ').slice(0,65);
  function labelTarget(node) {
    if(original.get(node)?.target?.isConnected)return original.get(node).target;
    if (!node || ['INPUT','TEXTAREA','SELECT','IMG','SVG'].includes(node.tagName)) return null;
    // Editar o título real, nunca anexar outra legenda a um controle composto.
    const candidates=[node,...node.querySelectorAll('strong,h1,h2,h3,h4,label,span,p,small')];
    const valid=n=>!n.closest('svg,.editor-user-icon,[aria-hidden=true]')&&[...n.childNodes].some(t=>t.nodeType===Node.TEXT_NODE&&t.textContent.trim());
    const heading=candidates.find(n=>n!==node&&n.matches('strong,h1,h2,h3,h4')&&valid(n));
    return heading||candidates.find(valid)||(!node.children.length?node:null);
  }
  function labelNodes(target){
    if(!target)return [];const walker=document.createTreeWalker(target,NodeFilter.SHOW_TEXT),result=[];let n;
    while((n=walker.nextNode())){const parent=n.parentElement;if(parent?.closest('svg,.editor-user-icon,[aria-hidden=true]'))continue;const control=parent?.closest('button,input,textarea,select');if(control&&control!==target&&!control.contains(target))continue;result.push(n);}return result;
  }
  function labelText(node){return labelNodes(labelTarget(node)).map(n=>n.textContent).join('').trim();}
  function setLabel(node,text){
    const target=labelTarget(node);if(!target)return;const textNodes=labelNodes(target).filter(n=>n.textContent.trim());
    if(textNodes.length){textNodes[0].textContent=text;textNodes.slice(1).forEach(n=>n.textContent='');}
    else if(!target.children.length)target.textContent=text;
  }
  function remember(node) {
    if (!original.has(node)) {
      const target = labelTarget(node);
      original.set(node, {title:node.getAttribute('title'), placeholder:node.getAttribute('placeholder'), src:node.getAttribute('src'), target,text:target ? labelNodes(target).map(n=>{const prior=[...original.values()].flatMap(s=>s.text).find(v=>v[0]===n);return[n,prior?prior[1]:n.textContent];}) : [], marker:null});
    }
    return original.get(node);
  }
  function restore() {
    const restored=new Set();
    for (const [node, state] of original) {
      if (!node.isConnected) { original.delete(node); continue; }
      for (const attr of ['title','placeholder','src']) { const value = attr === 'title' ? state.title : state[attr]; if (value === null) node.removeAttribute(attr); else node.setAttribute(attr,value); }
      const texts = appliedLabels.get(node);
      for (const [n,value] of state.text) {
        // Uma atualização normal do app vira a nova base, sem congelar status.
        if(restored.has(n))continue;restored.add(n);
        if (appliedTexts.has(n) && n.textContent !== appliedTexts.get(n)) { state.text.find(x=>x[0]===n)[1] = n.textContent; }
        else n.textContent = value;
      }
      for(const [n] of state.text)appliedTexts.delete(n);
      appliedLabels.delete(node);
      node.querySelectorAll(':scope > .editor-user-icon,:scope > .editor-caption').forEach(n=>n.remove());
      node.querySelectorAll(':scope > .editor-replaced-icon').forEach(n=>n.classList.remove('editor-replaced-icon'));
      node.classList.remove('editor-hidden');delete node.dataset.editorLabelOverride;
      if (state.marker?.isConnected && !node.contains(state.marker)) state.marker.parentNode.insertBefore(node,state.marker.nextSibling);
    }
  }
  function icon(node, value, image) {
    if (!value && !image) return;
    node.querySelectorAll(':scope > svg,:scope > img').forEach(n=>n.classList.add('editor-replaced-icon'));
    const span = document.createElement('span');span.className='editor-user-icon';span.setAttribute('aria-hidden','true');
    if (image) { const img = document.createElement('img');img.src=image;img.alt='';span.append(img); }
    else span.textContent=value;
    node.prepend(span);
  }
  function apply() {
    observer?.disconnect();
    try {
      restore();indexNodes();
      for (const k of Object.keys(lastTheme)) document.documentElement.style.removeProperty(k);
      for (const [k,v] of Object.entries(doc.theme)) document.documentElement.style.setProperty(k,v);
      lastTheme = {...doc.theme};
      let sheet='';
      for (const [k,rule] of Object.entries(doc.elements)) {
        const node=nodes.get(k);if (!node || !/^[\w:|./@=-]+$/.test(k)) continue;
        const state=remember(node);
        if (typeof rule.label==='string') {node.dataset.editorLabelOverride='true';setLabel(node,rule.label);const target=labelTarget(node);if(target){appliedLabels.set(node,new Map(labelNodes(target).map(n=>[n,n.textContent])));for(const n of labelNodes(target))appliedTexts.set(n,n.textContent);}}
        if ('tooltip' in rule) node.title=rule.tooltip;
        if ('placeholder' in rule && ['INPUT','TEXTAREA'].includes(node.tagName)) node.placeholder=rule.placeholder;
        if (rule.image && node.tagName==='IMG') node.src=rule.image;
        else icon(node,rule.icon,rule.image);
        if (rule.hidden && !node.contains($('#btn-editor'))) node.classList.add('editor-hidden');
        const css=C.css(rule.styles);const selector=`[data-emily-editor-key="${k}"]`;
        sheet+=`${selector}{${Object.entries(css).map(([a,b])=>`${a.replace(/[A-Z]/g,c=>'-'+c.toLowerCase())}:${b}!important`).join(';')}}\n`;
        if (rule.parent) {
          const parent=nodes.get(rule.parent), before=nodes.get(rule.before);
          if (parent && parent!==node && !node.contains(parent) && parent.matches('div,nav,aside,section,main,header,footer')) {
            if (!state.marker) {state.marker=document.createComment('posição original');node.before(state.marker);}
            parent.insertBefore(node,before?.parentNode===parent && before!==node ? before : null);
          }
        }
      }
      $('#editor-layout-style').textContent=sheet;
      drawNav();const heading=$('#editor-inspector .editor-panel-heading h3');if(heading&&selected)heading.textContent=pageFor(selected)?.title||name(nodes.get(selected))||'Elemento selecionado';updateToolbar();outline();
    } finally { observe(); }
  }
  function observe() { observer?.observe(document.body,{childList:true,subtree:true,characterData:true}); }
  function schedule() {
    if (pending) return;pending=true;
    requestAnimationFrame(()=>{pending=false;apply();});
  }
  function change(mutator, group='') {
    if(saving)return;const next=C.clone(doc);mutator(next);if (saving || !history.push(next,group)) return;
    doc=history.current;notice='';apply();persistDraft();
  }
  function mirrorState() {
    api('editor_estado',active,dirty(),++stateSerial).catch(()=>{});
  }
  function persistDraft() {
    mirrorState();
    try { if(dirty()) localStorage.setItem(draftKey,JSON.stringify({revision,document:doc,saved_at:Date.now()/1000})); else localStorage.removeItem(draftKey); } catch (_) { notice='Sem espaço no navegador para guardar o rascunho.'; }
    if(dirty()) {
      draftPending={document:C.clone(doc),revision};clearTimeout(draftTimer);
      draftTimer=setTimeout(()=>{flushDraft();},750);
    }else if(active&&!recovery){
      clearTimeout(draftTimer);draftPending=null;
      draftFlight=draftFlight.catch(()=>{}).then(()=>api('editor_limpar_rascunho')).catch(e=>{notice='Falha ao limpar rascunho: '+e.message;updateToolbar();});
    }
  }
  async function flushDraft() {
    clearTimeout(draftTimer);draftTimer=null;
    const pending=draftPending;draftPending=null;
    if(pending) draftFlight=draftFlight.catch(()=>{}).then(async()=>{
      try {
        const r=await api('editor_rascunho',pending.document,pending.revision);
        if(!r?.ok)throw new Error(r?.error||'Não consegui gravar o rascunho.');
        lastDraftTime=r.saved_at || Date.now()/1000;
      }catch(e){notice='Falha no auto-save: '+e.message;updateToolbar();}
    });
    await draftFlight;
  }
  function property(field,value,style=false) {
    if (!selected) return;
    if(style&&typeof value==='number'){const min=field==='x'||field==='y'||field.startsWith('margin')?-3000:0;value=Math.max(min,Math.min(field==='opacity'?1:3000,value));}
    change(next=>{
      const item=next.pages.flatMap(p=>p.items).find(i=>i.id===selected), page=next.pages.find(p=>p.id===selected);
      if(page && ['label','icon'].includes(field)){page[field==='label'?'title':field]=value;return;}
      if(item && ['label','icon','image','placeholder'].includes(field)){item[field]=value;return;}
      const target=next.elements[selected] ||= {};
      if(style){target.styles ||= {};if(value==='')delete target.styles[field];else target.styles[field]=value;}
      else target[field]=value;
    },`${selected}:${field}`);
  }
  function undo() { if(saving)return;doc=history.undo();notice='';renderCustom();apply();inspect();persistDraft(); }
  function redo() { if(saving)return;doc=history.redo();notice='';renderCustom();apply();inspect();persistDraft(); }
  function toolbarButton(id,label,fn,primary=false) {
    const b=document.createElement('button');b.id=id;b.textContent=label;b.type='button';if(primary)b.className='editor-primary';b.onclick=fn;$('#editor-toolbar').append(b);return b;
  }
  function updateToolbar() {
    $('#editor-undo').disabled=saving||!history.canUndo;$('#editor-redo').disabled=saving||!history.canRedo;
    $('#editor-inspector').inert=saving;
    $('#editor-save').disabled=saving;$('#editor-save').textContent=saving?'Salvando…':'Salvar';
    $('#editor-select').textContent='Selecionar';for(const m of ['select','move','resize','interact'])$('#editor-'+m)?.setAttribute('aria-pressed',String(mode===m));
    $('#editor-state').textContent=notice || (dirty()?'Alterações não salvas':'Layout salvo');
    $('#btn-editor').setAttribute('aria-pressed',String(active));document.body.classList.toggle('editor-select',active&&selecting);
    $('#editor-recover').hidden=!recovery;queuePanel();
    requestAnimationFrame(()=>{document.documentElement.style.setProperty('--editor-height',`${$('#editor-toolbar').offsetHeight}px`);document.documentElement.style.setProperty('--editor-inspector-top',`${$('#editor-toolbar').getBoundingClientRect().bottom+12}px`);});
  }
  async function save() {
    if(saving)return false;saving=true;updateToolbar();
    try {
      await flushDraft();
      const result=await api('editor_salvar',doc,revision,{__teto:30000});
      if(!result?.ok)throw new Error(result?.error || 'Não foi possível salvar.');
      doc=C.clone(result.document);saved=C.clone(doc);revision=result.revision;
      // Mantém o histórico anterior ao salvar: Ctrl+Z ainda reverte a edição.
      history.stack[history.index]=C.clone(doc);
      notice=(result.warnings?.length?'Salvo parcialmente: '+result.warnings.join('; '):'Salvo no projeto e na instalação.');
      if(result.publication) notice+=' '+result.publication.message;
      try{const cleared=await api('editor_limpar_rascunho');if(!cleared?.ok)throw new Error(cleared?.error||'Falha ao limpar rascunho.');}catch(e){notice+=' Rascunho anterior não pôde ser limpo: '+e.message;}recovery=null;apply();persistDraft();toast(result.publication?.ok && !result.warnings?.length?'Interface salva e atualização Windows publicada':notice,result.warnings?.length?'erro':undefined);return true;
    } catch(e) { notice=e.message || String(e);toast(notice,'erro');return false; }
    finally { saving=false;updateToolbar();if(closeIntent!==null){const intent=closeIntent;closeIntent=null;requestClose(intent);} }
  }
  async function toggle() {
    if(!initialized)return;
    if(active&&dirty()){
      if(!confirm('Sair sem salvar e voltar ao layout salvo? O rascunho fica guardado para recuperar depois.'))return;
      persistDraft();recovery={revision,document:C.clone(doc)};doc=C.clone(saved);history.reset(doc);renderCustom();apply();
    }
    active=!active;document.body.classList.toggle('modo-editor',active);updateToolbar();if(active){setMode('select');if(recovery && recovery.revision===revision){const r=recovery;recovery=null;change(d=>Object.assign(d,r.document));notice='Rascunho recuperado automaticamente.';}indexNodes();inspect();await openPanel();}else{api('editor_painel_ocultar').catch(()=>{});}mirrorState();outline();
  }
  function select(node) { if(!allowed(node))return;selected=key(node);inspect();outline(); }
  function outline() {
    const box=$('#editor-outline'),node=nodes.get(selected);if(!box)return;
    if(!active||!selecting||!node?.isConnected||!node.getClientRects().length){box.style.visibility='hidden';return;}
    const r=node.getBoundingClientRect();box.style.visibility='visible';Object.assign(box.style,{left:r.left+'px',top:r.top+'px',width:r.width+'px',height:r.height+'px'});box.querySelector('span').textContent=name(node)||selected;
  }
  function controls(label,field,value,type='text',style=false) {
    return `<label>${esc(label)}<input data-editor-field="${field}" data-editor-style="${style}" type="${type}" ${type==='number'?'step="any"':''} value="${esc(value ?? '')}"></label>`;
  }
  function enumLabel(v){return ({left:'À esquerda',center:'Centralizado',right:'À direita',normal:'Normal',bold:'Negrito',block:'Bloco',flex:'Linha ou coluna flexível',grid:'Grade', 'inline-flex':'Linha compacta',row:'Linha horizontal',column:'Coluna vertical','row-reverse':'Linha invertida','column-reverse':'Coluna invertida','flex-start':'No início','flex-end':'No fim','space-between':'Espalhar até as bordas','space-around':'Espaços em volta',stretch:'Preencher', '1fr':'1 coluna','1fr 1fr':'2 colunas','1fr 1fr 1fr':'3 colunas','1fr 1fr 1fr 1fr':'4 colunas','400':'Normal (400)','500':'Médio (500)','600':'Seminegrito (600)','700':'Negrito (700)'})[v]||v;}
  function colorControl(label,field,value,style=false,theme=false){
    const presets=['#1c1b19','#302d29','#edebe7','#c96442','#d3a35c','#7fae76','#5599d4','#9b7fd4'];
    return `<div class="editor-color-label"><span>${esc(label)}</span><div class="editor-color-control"><button type="button" data-color-toggle title="Abrir paleta de ${esc(label)}" aria-expanded="false"><span class="editor-color-swatch" style="background:${esc(value)}"></span><span>Cor</span></button><input type="text" ${theme?`data-editor-theme="${field}"`:`data-editor-field="${field}" data-editor-style="${style}"`} data-editor-color="true" value="${esc(value)}" maxlength="7" spellcheck="false" aria-label="${esc(label)}: código da cor"><button type="button" data-color-clear title="Voltar à cor original">Padrão</button><div class="editor-color-picker" hidden><p>Escolha uma cor ou ajuste vermelho, verde e azul.</p><div class="editor-color-presets">${presets.map(c=>`<button type="button" data-color-preset="${c}" style="background:${c}" aria-label="Usar ${c}"></button>`).join('')}</div>${['R','G','B'].map((c,i)=>`<label>${c}<input type="range" data-color-channel="${i}" min="0" max="255" value="${parseInt(value.slice(1+i*2,3+i*2),16)||0}"></label>`).join('')}</div></div></div>`;
  }
  function setCategory(value){category=['element','layout','pages','theme','files'].includes(value)?value:'element';const p=$('#editor-inspector');p.querySelectorAll('[data-editor-section]').forEach(s=>s.hidden=s.dataset.editorSection!==category);p.querySelectorAll('[data-editor-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.editorCategory===category)));queuePanel();}
  function setMode(value){mode=['select','move','resize','interact'].includes(value)?value:'select';selecting=mode!=='interact';document.body.dataset.editorMode=mode;updateToolbar();outline();}
  function queuePanel(){
    if(panelScheduled||!initialized)return;panelScheduled=true;
    queueMicrotask(()=>{panelScheduled=false;const p=$('#editor-inspector');if(!p)return;
      const copy=p.cloneNode(true);copy.querySelectorAll('.emily-native-select').forEach(b=>b.remove());copy.querySelectorAll('select').forEach(el=>el.classList.remove('emily-select-source'));p.querySelectorAll('input,select').forEach((el,i)=>{const clone=copy.querySelectorAll('input,select')[i];if(el.tagName==='INPUT'){clone.setAttribute('value',el.value);clone.toggleAttribute('checked',el.checked);}else [...clone.options].forEach(o=>o.toggleAttribute('selected',o.value===el.value));});
      const state={html:copy.innerHTML,assets:panelAssets,selected,mode,category,active,dirty:dirty(),saving,canUndo:history.canUndo,canRedo:history.canRedo,notice:notice||(dirty()?'Alterações não salvas':'Layout salvo')};const signature=JSON.stringify(state);if(signature===lastPanel)return;lastPanel=signature;
      api('editor_painel_estado',state,++panelSerial).catch(()=>{});
    });
  }
  async function openPanel(){queuePanel();try{const r=await api('editor_painel_abrir');if(!r?.ok)throw new Error(r?.error||'Janela separada indisponível.');detached=true;document.body.classList.add('editor-detached');}catch(e){detached=false;document.body.classList.remove('editor-detached');$('#editor-inspector').style.visibility='visible';notice='Painel dentro da Emily: '+e.message;updateToolbar();}}
  function command(c){
    if(!c||!active)return;
    if(c.kind==='mode'){setMode(c.value);return;}if(c.kind==='category'){setCategory(c.value);return;}
    if(c.kind==='shortcut'){if(c.value==='delete')deleteCustom();else if(c.value==='save')save();else if(c.value==='undo')undo();else if(c.value==='redo')redo();return;}
    if(c.selected!==selected){notice='A seleção mudou. Use as propriedades atualizadas.';queuePanel();return;}
    if(c.kind==='click'){const el=document.getElementById(c.id);if(el&&el.closest('#editor-inspector,#editor-toolbar'))el.click();return;}
    if(c.kind==='field'){
      const root=$('#editor-inspector');let el;
      if(c.id&&/^editor-[\w-]+$/.test(c.id))el=root.querySelector('#'+c.id);
      else if(c.field&&/^[\w-]+$/.test(c.field))el=[...root.querySelectorAll('[data-editor-field]')].find(n=>n.dataset.editorField===c.field);
      else if(c.theme&&/^--[\w-]+$/.test(c.theme))el=[...root.querySelectorAll('[data-editor-theme]')].find(n=>n.dataset.editorTheme===c.theme);
      if(!el||!el.matches('input,select,textarea'))return;
      if(el.type==='checkbox')el.checked=!!c.value;else el.value=String(c.value??'');
      if(el.tagName==='SELECT'){el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}else el.dispatchEvent(new Event(c.event==='change'?'change':'input',{bubbles:true}));queuePanel();
    }
  }
  function inspect() {
    const p=$('#editor-inspector'),node=nodes.get(selected),item=itemFor(selected),page=pageFor(selected),rule=info(selected),styles=rule.styles||{},target=labelTarget(node);
    const head=`<header class="editor-panel-heading"><div><p class="editor-eyebrow">PERSONALIZE A EMILY</p><h3>${esc(page?.title||name(node)||'Seu espaço de edição')}</h3><p class="editor-help">${selected?'As mudanças aparecem na janela da Emily. Salve quando gostar do resultado.':'Escolha um elemento na janela da Emily, ou crie uma aba com seus atalhos.'}</p></div></header>`;
    const tabs={element:'Texto e aparência',layout:'Tamanho e posição',pages:'Abas e atalhos',theme:'Cores gerais',files:'Backup e restauração'};
    let html=head+`<nav class="editor-categories" aria-label="Categorias do editor">${Object.entries(tabs).map(([key,title])=>`<button type="button" data-editor-category="${key}" aria-pressed="${category===key}">${title}</button>`).join('')}</nav>`;
    html+=`<details class="editor-section editor-finder" ${!selected?'open':''}><summary>Escolher ou trocar o elemento</summary><div class="editor-finder-content"><h4>Escolher o que editar</h4><p class="editor-help">Clique na interface no modo Selecionar. Ou procure pelo nome aqui; elementos ocultos também aparecem.</p><input id="editor-find" type="search" placeholder="Buscar botão, seção, campo…" aria-label="Buscar elemento"><select id="editor-element-list"><option value="">Escolher elemento…</option>${[...nodes.entries()].filter(([k,n])=>n.matches(editable)).map(([k,n])=>`<option value="${k}" ${selected===k?'selected':''}>${esc(name(n)||k)}</option>`).join('')}</select><button id="editor-parent-select" type="button" ${!node?'disabled':''}>Selecionar a seção que contém este elemento</button></div></details>`;
    html+=`<section class="editor-section" data-editor-section="element"><h4>Texto e ícone</h4><p class="editor-help">Muda a apresentação do controle; sua função continua a mesma.</p>`;
    if(node||page){
      html+='<div class="editor-grid">';
      if(target||item||page||node?.tagName==='IMG')html+=controls('Nome ou texto exibido','label',rule.label??item?.label??page?.title??labelText(node));
      if(!page)html+=controls('Dica ao passar o mouse','tooltip',rule.tooltip??node?.title);
      if(node?.matches('input,textarea'))html+=controls('Exemplo dentro do campo vazio','placeholder',rule.placeholder??item?.placeholder??node.placeholder);
      html+=controls('Ícone: cole um emoji ou símbolo','icon',rule.icon??item?.icon??page?.icon??'');
      const parts=node?[...node.querySelectorAll('strong,small,span,p,label,h1,h2,h3,h4')].filter(n=>labelTarget(n)===n&&!n.closest('svg,[aria-hidden=true],.editor-user-icon')&&n!==target):[];
      if(parts.length)html+=`<label>Editar outro texto dentro deste elemento<select id="editor-text-part"><option value="">Escolher título, descrição ou legenda…</option>${parts.map(n=>`<option value="${esc(key(n))}">${esc(labelText(n)||'Texto vazio')}</option>`).join('')}</select></label>`;
      html+='</div><div class="editor-row"><button id="editor-image">Escolher imagem ou ícone…</button><button id="editor-clear-icon">Remover ícone personalizado</button></div>';
      if(!page){
        html+=`<h4>Cores deste elemento</h4><p class="editor-help">A pequena amostra mostra a cor. Clique nela para abrir a paleta, ou digite uma cor como #C96442. Padrão remove sua alteração.</p><div class="editor-grid">${Object.entries(colors).map(([k,l])=>colorControl(l,k,styles[k]||rgbToHex(getComputedStyle(node)[k]),true)).join('')}</div>`;
        html+=`<h4>Estilo rápido</h4><div class="editor-row"><button id="editor-preset-compact">Compacto</button><button id="editor-preset-comfort">Confortável</button><button id="editor-preset-emphasis">Destaque</button></div><div class="editor-grid">${['fontSize','borderRadius','borderWidth','opacity'].map(k=>controls(numbers[k],k,styles[k]??'','number',true)).join('')}</div>`;
      }
    }else html+='<p class="editor-empty">Selecione um elemento para editar seu texto e suas cores.</p>';
    html+='</section><section class="editor-section" data-editor-section="layout"><h4>Tamanho e espaços</h4><p class="editor-help">Medidas em pixels. Campo vazio mantém o tamanho original. Espaço interno afasta o conteúdo da borda; margens afastam o elemento de seus vizinhos.</p>';
    if(node&&!page){
      html+=`<div class="editor-grid">${['width','height','padding','gap','marginTop','marginRight','marginBottom','marginLeft','x','y'].map(k=>controls(numbers[k],k,styles[k]??'','number',true)).join('')}</div>`;
      html+=`<h4>Posição com o mouse</h4><p class="editor-help">Mover: arraste o elemento na Emily. Redimensionar: arraste o canto inferior direito. Shift suspende o encaixe na grade durante o arrasto.</p><div class="editor-row"><label><input id="editor-snap" type="checkbox" ${snap?'checked':''}> Encaixar na grade</label><label>Grade (pixels)<input id="editor-grid" type="number" min="1" max="100" value="${grid}"></label></div><div class="editor-row"><button id="editor-zero">Zerar deslocamento</button><button id="editor-natural-size">Usar tamanho original</button></div>`;
      html+=`<h4>Alinhamento e organização</h4><p class="editor-help">Linha coloca os filhos lado a lado; coluna empilha; grade organiza em colunas. Essas opções têm mais efeito em seções e grupos.</p>${Object.entries(enums).map(([k,[label,...vals]])=>`<label>${label}<select data-editor-field="${k}" data-editor-style="true"><option value="">Manter original</option>${vals.map(v=>`<option value="${v}" ${styles[k]===v?'selected':''}>${enumLabel(v)}</option>`).join('')}</select></label>`).join('')}`;
      html+=`<div class="editor-row"><button id="editor-up">Mover antes do vizinho</button><button id="editor-down">Mover depois do vizinho</button></div><label>Mover para outra seção<select id="editor-parent"><option value="">Seção original</option>${[...nodes.entries()].filter(([k,n])=>n!==node&&!node.contains(n)&&n.matches('div,section,nav,aside,main,header,footer')&&!n.closest('.editor-custom-page')).slice(0,150).map(([k,n])=>`<option value="${k}" ${rule.parent===k?'selected':''}>${esc(name(n)||k)}</option>`).join('')}</select></label><label><input id="editor-hidden" type="checkbox" ${rule.hidden?'checked':''}> Ocultar na interface normal (continua acessível no editor)</label>`;
      html+=`<details><summary>Limites de tamanho e expansão (avançado)</summary><p class="editor-help">Restringem o tamanho conforme a janela muda. Expansão define quanto espaço livre recebe dentro de uma linha ou coluna.</p><div class="editor-grid">${['minWidth','maxWidth','minHeight','maxHeight','order','flexGrow'].map(k=>controls(numbers[k],k,styles[k]??'','number',true)).join('')}</div></details>`;
    }else html+='<p class="editor-empty">Selecione um botão, campo, imagem ou seção para ajustar tamanho e posição.</p>';
    html+='</section><section class="editor-section" data-editor-section="pages"><h4>Suas abas</h4><p class="editor-help">Uma aba aparece na barra lateral. Monte textos, imagens, grupos e botões usando as funções que a Emily já tem.</p>';
    html+=`<div class="editor-row"><button id="editor-add-page" class="editor-primary">Criar nova aba</button><select id="editor-page-list"><option value="">Abrir uma aba…</option>${doc.pages.map(p=>`<option value="${p.id}" ${customPage===p.id?'selected':''}>${esc(p.title)}</option>`).join('')}</select></div><label>Tipo de componente<select id="editor-add-type"><option value="text">Texto</option><option value="button">Botão de ação</option><option value="image">Imagem</option><option value="input">Campo para digitar</option><option value="group">Grupo / seção</option><option value="divider">Linha separadora</option></select></label><button id="editor-add-item" ${!customPage?'disabled':''}>Adicionar à aba aberta</button>${!customPage?'<p class="editor-help">Abra ou crie uma aba antes de adicionar componentes.</p>':''}`;
    if(item?.type==='button')html+=`<h4>O que este botão faz?</h4><label>Função<select id="editor-action">${Object.entries(actions).map(([k,l])=>`<option value="${k}" ${item.action===k?'selected':''}>${l}</option>`).join('')}</select></label>${item.action==='pagina'?`<label>Aba de destino<select id="editor-target-page"><option value="">Escolher aba…</option>${doc.pages.map(p=>`<option value="${p.id}" ${item.value===p.id?'selected':''}>${esc(p.title)}</option>`).join('')}</select></label>`:controls('Pedido para a Emily (quando usar essa função)','value',item.value)}<p class="editor-help">Um pedido é preparado para você conferir antes de enviar. Nenhum código novo é executado pelo editor.</p>`;
    if(item&&!page){const groups=doc.pages.find(p=>p.items.includes(item))?.items.filter(i=>i.type==='group'&&i!==item)||[];html+=`<label>Colocar dentro de um grupo<select id="editor-group"><option value="">Fora dos grupos</option>${groups.map(g=>`<option value="${g.id}" ${item.parent===g.id?'selected':''}>${esc(g.label||'Grupo')}</option>`).join('')}</select></label>`;}
    if(item||page)html+='<div class="editor-row"><button id="editor-duplicate">Duplicar selecionado</button></div>';
    html+='</section><section class="editor-section" data-editor-section="theme"><h4>Cores de toda a interface</h4><p class="editor-help">Aplica uma paleta geral. Cores específicas de um elemento têm prioridade. Padrão volta à cor original dessa parte do tema.</p><div class="editor-grid">'+Object.entries(themes).map(([k,l])=>colorControl(l,k,doc.theme[k]||rgbToHex(getComputedStyle(document.documentElement).getPropertyValue(k)),false,true)).join('')+'</div></section>';
    html+='<section class="editor-section" data-editor-section="files"><h4>Backup do seu layout</h4><p class="editor-help">Exportar cria um arquivo para guardar ou compartilhar. Importar abre o layout para conferir; só é aplicado à instalação quando você salvar.</p><div class="editor-row"><button id="editor-import">Importar layout…</button><button id="editor-export">Exportar layout…</button></div><h4>Restaurar</h4><p class="editor-help">Você pode desfazer uma restauração antes de salvar.</p><button id="editor-reset-all">Restaurar toda a interface original…</button></section>';
    if(selected)html+=`<div class="editor-row"><button id="editor-delete" class="editor-danger">Excluir selecionado · Delete</button></div><footer class="editor-selected-footer"><button id="editor-reset">Restaurar personalizações deste elemento</button><details><summary>Identificador técnico</summary><code>${esc(selected)}</code></details></footer>`;
    const scroll=p.scrollTop;p.innerHTML=html;p.scrollTop=scroll;setCategory(category);
    p.querySelectorAll('[data-editor-category]').forEach(b=>b.onclick=()=>setCategory(b.dataset.editorCategory));
    $('#editor-find').oninput=e=>{const term=e.target.value.toLocaleLowerCase();$('#editor-element-list').querySelectorAll('option').forEach(o=>{o.hidden=!!o.value&&!o.textContent.toLocaleLowerCase().includes(term);});};
    const snapInput=$('#editor-snap');if(snapInput)snapInput.onchange=()=>{snap=snapInput.checked;queuePanel();};
    const gridInput=$('#editor-grid');if(gridInput)gridInput.onchange=()=>{grid=Math.max(1,Math.min(100,Number(gridInput.value)||8));gridInput.value=grid;queuePanel();};
    bind('#editor-zero',()=>{change(d=>{const r=d.elements[selected]||={};r.styles||={};delete r.styles.x;delete r.styles.y;});inspect();});
    bind('#editor-natural-size',()=>{change(d=>{const r=d.elements[selected]||={};r.styles||={};delete r.styles.width;delete r.styles.height;});inspect();});
    for(const [id,values] of Object.entries({'compact':{padding:6,fontSize:12,borderRadius:6},'comfort':{padding:14,fontSize:15,borderRadius:10},'emphasis':{padding:14,fontWeight:'bold',borderRadius:10}}))bind('#editor-preset-'+id,()=>{change(d=>{const r=d.elements[selected]||={};Object.assign(r.styles||={},values);});inspect();});
    p.querySelectorAll('[data-editor-field]').forEach(input=>input.oninput=()=>{
      let val=input.value;if(input.dataset.editorColor==='true'&&val!==''&&!/^#[a-f\d]{6}$/i.test(val))return;if(input.type==='number'&&val!==''){val=Number(val);if(!Number.isFinite(val))return;}
      if(item&&input.dataset.editorField==='value'){change(d=>{d.pages.flatMap(p=>p.items).find(i=>i.id===selected).value=val;},selected+':value');return;}
      property(input.dataset.editorField,val,input.dataset.editorStyle==='true');renderCustom();
    });
    p.querySelectorAll('[data-editor-theme]').forEach(input=>input.oninput=()=>{if(input.value!==''&&!/^#[a-f\d]{6}$/i.test(input.value))return;change(d=>{if(input.value)d.theme[input.dataset.editorTheme]=input.value;else delete d.theme[input.dataset.editorTheme];},input.dataset.editorTheme);});
    const part=$('#editor-text-part');if(part)part.onchange=()=>{if(nodes.get(part.value))select(nodes.get(part.value));};
    bind('#editor-parent-select',()=>{const parent=node?.parentElement;if(parent&&parent!==document.body)select(parent);});
    bind('#editor-add-page',addPage);bind('#editor-add-item',addItem);bind('#editor-up',()=>reorder(-1));bind('#editor-down',()=>reorder(1));
    bind('#editor-reset',()=>{change(d=>{delete d.elements[selected];const original=saved.pages.flatMap(p=>p.items).find(i=>i.id===selected),it=d.pages.flatMap(p=>p.items).find(i=>i.id===selected);if(it&&original)Object.assign(it,C.clone(original));});renderCustom();inspect();});
    bind('#editor-delete',deleteCustom);bind('#editor-duplicate',duplicateCustom);
    bind('#editor-image',async()=>{try{const r=await api('editor_imagem');if(r?.ok&&r.image){property('image',r.image);renderCustom();}else if(!r?.cancelled)toast(r?.error||'Falha ao importar','erro');}catch(e){toast(e.message,'erro');}});
    bind('#editor-clear-icon',()=>{change(d=>{const it=d.pages.flatMap(p=>p.items).find(i=>i.id===selected);if(it){delete it.icon;delete it.image;}if(d.elements[selected]){delete d.elements[selected].icon;delete d.elements[selected].image;}});renderCustom();inspect();});
    bind('#editor-import',async()=>{try{const r=await api('editor_importar');if(r?.ok&&r.document){change(d=>{Object.keys(d).forEach(k=>delete d[k]);Object.assign(d,r.document);});const hadCustom=!!customPage;customPage='';if(hadCustom)irPara('inicio',{forcar:true});renderCustom();inspect();}else if(!r?.cancelled)toast(r?.error||'Falha ao importar','erro');}catch(e){toast(e.message,'erro');}});
    bind('#editor-export',async()=>{try{const r=await api('editor_exportar',doc);if(!r?.ok)toast(r?.error||'Falha ao exportar','erro');}catch(e){toast(e.message,'erro');}});
    bind('#editor-reset-all',()=>{if(confirm('Restaurar o tema, os elementos e as abas? Você pode desfazer antes de salvar.')){change(d=>{Object.assign(d,C.blank());});const hadCustom=!!customPage;customPage='';if(hadCustom)irPara('inicio',{forcar:true});renderCustom();inspect();}});
    const pages=$('#editor-page-list');pages.onchange=()=>{if(pages.value)openPage(pages.value);};
    $('#editor-element-list').onchange=e=>{selected=e.target.value;inspect();outline();};
    const hidden=$('#editor-hidden');if(hidden)hidden.onchange=()=>property('hidden',hidden.checked);
    const parent=$('#editor-parent');if(parent)parent.onchange=()=>{change(d=>{const r=d.elements[selected]||={};if(parent.value)r.parent=parent.value;else{delete r.parent;delete r.before;}});};
    const action=$('#editor-action');if(action)action.onchange=()=>{change(d=>{d.pages.flatMap(p=>p.items).find(i=>i.id===selected).action=action.value;});inspect();};
    const destination=$('#editor-target-page');if(destination)destination.onchange=()=>change(d=>{d.pages.flatMap(p=>p.items).find(i=>i.id===selected).value=destination.value;});
    const group=$('#editor-group');if(group)group.onchange=()=>{change(d=>{const it=d.pages.flatMap(p=>p.items).find(i=>i.id===selected);if(group.value){let parent=group.value;const seen=new Set([it.id]);while(parent){if(seen.has(parent)){toast('Um grupo não pode ficar dentro de si mesmo.','erro');return;}seen.add(parent);parent=d.pages.flatMap(p=>p.items).find(i=>i.id===parent)?.parent;}it.parent=group.value;}else delete it.parent;});renderCustom();};
    queuePanel();
  }
  function bind(selector,fn){const el=$(selector);if(el)el.onclick=fn;}
  function rgbToHex(value){value=String(value).trim();if(/^#[\da-f]{6}$/i.test(value))return value;const n=value.match(/[\d.]+/g);if(!n||n.length<3)return '#292623';return '#'+n.slice(0,3).map(v=>Math.min(255,Math.round(Number(v))).toString(16).padStart(2,'0')).join('');}
  function uid(){return 'custom:'+ (crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`);}
  function addPage(){const id=uid();change(d=>d.pages.push({id,title:'Nova aba',icon:'▦',items:[]}));openPage(id);selected=id;inspect();}
  function addItem(){const page=doc.pages.find(p=>p.id===customPage);if(!page)return;const type=$('#editor-add-type').value,id=uid();change(d=>d.pages.find(p=>p.id===page.id).items.push({id,type,label:type==='button'?'Novo botão':type==='text'?'Seu texto aqui':type==='group'?'Nova seção':'',action:'none',value:'',styles:{}}));renderCustom();selected=id;inspect();outline();}
  function deleteCustom(){
    if(!selected||saving)return;
    if(nodes.get(selected)?.contains($('#btn-editor'))){notice='Esta seção contém o acesso ao Editor. Exclua seus elementos internos separadamente.';updateToolbar();return;}
    if(!itemFor(selected)&&!pageFor(selected)){change(d=>{(d.elements[selected]||={}).hidden=true;});notice='Elemento removido da interface. Ctrl+Z restaura.';inspect();updateToolbar();return;}
    change(d=>{if(pageFor(selected)){const page=d.pages.find(p=>p.id===selected);for(const it of page.items)delete d.elements[it.id];d.pages=d.pages.filter(p=>p.id!==selected);}else{const page=d.pages.find(p=>p.items.some(i=>i.id===selected));if(page){const remove=new Set([selected]);let changed=true;while(changed){changed=false;page.items.forEach(i=>{if(remove.has(i.parent)&&!remove.has(i.id)){remove.add(i.id);changed=true;}});}page.items=page.items.filter(i=>!remove.has(i.id));for(const id of remove)delete d.elements[id];}}delete d.elements[selected];});selected='';renderCustom();inspect();
  }
  function duplicateCustom(){
    change(d=>{const page=d.pages.find(p=>p.id===selected);if(page){const copy=C.clone(page),ids=new Map([[copy.id,uid()],...copy.items.map(i=>[i.id,uid()])]);copy.id=ids.get(copy.id);copy.title+=' (cópia)';for(const i of copy.items){const old=i.id;i.id=ids.get(i.id);if(i.parent)i.parent=ids.get(i.parent);if(d.elements[old]){d.elements[i.id]=C.clone(d.elements[old]);for(const field of ['parent','before'])if(ids.has(d.elements[i.id][field]))d.elements[i.id][field]=ids.get(d.elements[i.id][field]);}if(i.action==='pagina'&&ids.has(i.value))i.value=ids.get(i.value);}d.pages.push(copy);}else{const page=d.pages.find(p=>p.items.some(i=>i.id===selected));if(!page)return;const old=page.items.find(i=>i.id===selected),included=new Set([old.id]);let more=true;while(more){more=false;for(const i of page.items){if(included.has(i.parent)&&!included.has(i.id)){included.add(i.id);more=true;}}}const ids=new Map([...included].map(id=>[id,uid()]));const copies=page.items.filter(i=>included.has(i.id)).map(i=>{const copy=C.clone(i);copy.id=ids.get(i.id);if(ids.has(i.parent))copy.parent=ids.get(i.parent);if(i.id===selected)copy.label+=' (cópia)';if(d.elements[i.id]){d.elements[copy.id]=C.clone(d.elements[i.id]);if(ids.has(d.elements[copy.id].parent))d.elements[copy.id].parent=ids.get(d.elements[copy.id].parent);if(ids.has(d.elements[copy.id].before))d.elements[copy.id].before=ids.get(d.elements[copy.id].before);}return copy;});page.items.push(...copies);}});renderCustom();inspect();
  }
  function reorder(direction){
    const node=nodes.get(selected);if(!node)return;
    const siblings=[...node.parentElement.children].filter(n=>allowed(n));const i=siblings.indexOf(node),other=siblings[i+direction];if(!other)return;
    change(d=>{const r=d.elements[selected]||={};r.parent=key(node.parentElement);r.before=direction<0?key(other):key(siblings[i+2])||'';});
  }
  function drawNav(){
    let nav=$('#editor-custom-nav');if(!nav){nav=document.createElement('nav');nav.id='editor-custom-nav';nav.className='editor-custom-nav';nav.setAttribute('aria-label','Abas personalizadas');$('#lateral')?.insertBefore(nav,$('#conversas'));}
    const signature=JSON.stringify(doc.pages.map(p=>[p.id,p.title,p.icon]));if(nav.dataset.signature===signature)return;nav.dataset.signature=signature;nav.replaceChildren();
    for(const page of doc.pages){const b=document.createElement('button');b.type='button';b.dataset.emilyEditorKey=page.id;b.textContent=`${page.icon} ${page.title}`;b.onclick=()=>openPage(page.id);nav.append(b);nodes.set(page.id,b);}
  }
  function openPage(id){if(!doc.pages.some(p=>p.id===id))return;irPara('inicio',{forcar:true});customPage=id;renderCustom(true);selected=id;inspect();}
  function renderCustom(force=false){
    if(!customPage)return;const page=doc.pages.find(p=>p.id===customPage);
    if(!page){customPage='';irPara('inicio',{forcar:true});return;}
    if(!force&&!$('#palco .editor-custom-page')){customPage='';return;}
    observer?.disconnect();
    const palco=$('#palco');
    // O composer é singleton. Retê-lo fora da página evita perder seus listeners.
    const composer=$('#composer');if(composer&&palco.contains(composer)){composer.hidden=true;document.body.append(composer);}
    const section=document.createElement('section');section.className='editor-custom-page';section.dataset.editorPage=page.id;
    const content=document.createElement('div');content.className='editor-custom-content';const title=document.createElement('h1');title.textContent=page.title;content.append(title);section.append(content);
    const built=new Map();for(const item of page.items){const tag={text:'p',button:'button',image:'img',divider:'hr',input:'input',group:'section'}[item.type];const node=document.createElement(tag);node.className='editor-custom-item';node.dataset.editorType=item.type;node.dataset.emilyEditorKey=item.id;
      if(tag==='button')node.type='button';if(tag==='img'){node.alt=item.label; if(item.image)node.src=item.image;}else if(tag==='input'){node.placeholder=item.placeholder||item.label;}else if(tag!=='hr')node.textContent=item.label;
      if(item.type==='button')node.onclick=()=>runAction(item,content);
      Object.assign(node.style,C.css(item.styles));built.set(item.id,node);
    }
    for(const item of page.items){const node=built.get(item.id);(built.get(item.parent)||content).append(node);}
    palco.replaceChildren(section);ESTADO.tela='editor-custom';indexNodes();apply();
  }
  async function runAction(item,container){
    try{const map={inicio:'btn-inicio',nova_conversa:'btn-novo',config:'btn-config',code:'btn-code',cloud:'btn-cloud',music:'btn-music',navegador:'btn-navegador-interno',xadrez:'btn-xadrez',agente_visual:'btn-tela',ptt:'btn-mic',captura:'btn-captura-editor',anexo:'btn-arquivo-editor'};
      if(item.action==='none')return;if(item.action==='captura'){await api('capturar_tela');return;}if(item.action==='anexo'){await api('enviar_arquivo');return;}if(item.action==='pagina'){openPage(item.value);return;}customPage='';
      if(item.action==='logs'){await abrirLogs();return;}
      if(item.action==='comando'){const fields=[...container.querySelectorAll('input.editor-custom-item')].map(n=>n.value).filter(Boolean);const text=[item.value,...fields].filter(Boolean).join('\n');if(!text){toast('Defina um pedido ou preencha um campo.','erro');return;}irPara('inicio',{forcar:true});$('#composer').hidden=false;$('#entrada').value=text;ajustarEntrada();toast('Pedido preparado. Confira e envie para a Emily.');return;}
      const btn=document.getElementById(map[item.action]);if(!btn){toast('Este controle não está disponível nesta tela.','erro');return;}btn.click();
    }catch(e){toast(e.message||String(e),'erro');}
  }
  function startDrag(event,resize){
    const node=nodes.get(selected);if(!node||saving)return;event.preventDefault();event.stopPropagation();const rect=node.getBoundingClientRect(),styles=info(selected).styles||{};
    drag={pointer:event.pointerId,node,startX:event.clientX,startY:event.clientY,x:styles.x||0,y:styles.y||0,width:rect.width,height:rect.height,resize,before:C.clone(doc)};
    event.target.setPointerCapture?.(event.pointerId);
  }
  function dragMove(event){if(!drag)return;const adjust=v=>snap&&!event.shiftKey?Math.round(v/grid)*grid:v;const dx=adjust(event.clientX-drag.startX),dy=adjust(event.clientY-drag.startY);const rule=doc.elements[selected]||={};rule.styles||={};if(drag.resize){rule.styles.width=Math.round(Math.max(24,Math.min(3000,drag.width+dx)));rule.styles.height=Math.round(Math.max(24,Math.min(3000,drag.height+dy)));}else{rule.styles.x=Math.round(Math.max(-3000,Math.min(3000,drag.x+dx)));rule.styles.y=Math.round(Math.max(-3000,Math.min(3000,drag.y+dy)));}apply();}
  function dragEnd(){if(!drag)return;const next=C.clone(doc);doc=drag.before;drag=null;history.push(next);doc=history.current;apply();inspect();persistDraft();}
  function requestClose(encerrar) {
    if(saving){closeIntent=encerrar;return;}
    if($('#editor-close-dialog'))return;
    const modal=document.createElement('div');modal.id='editor-close-dialog';modal.className='editor-close-dialog';
    modal.innerHTML='<div role="alertdialog" aria-modal="true" aria-labelledby="editor-close-title"><h3 id="editor-close-title">Salvar alterações antes de sair?</h3><p>Há alterações na interface que ainda não foram salvas.</p><div class="editor-row"><button id="editor-close-cancel">Cancelar</button><button id="editor-close-discard">Sair sem salvar</button><button id="editor-close-save">Salvar e sair</button></div></div>';
    document.body.append(modal);
    const finish=async()=>{modal.remove();active=false;document.body.classList.remove('modo-editor');updateToolbar();mirrorState();await api('editor_fechar',encerrar);};
    $('#editor-close-cancel').onclick=()=>modal.remove();
    $('#editor-close-discard').onclick=async()=>{
      try{await flushDraft();const r=await api('editor_limpar_rascunho');if(!r?.ok)throw new Error(r?.error||'Não consegui descartar o rascunho.');localStorage.removeItem(draftKey);recovery=null;doc=C.clone(saved);history.reset(doc);renderCustom();apply();await finish();}catch(e){notice=e.message;updateToolbar();toast(notice,'erro');}
    };
    $('#editor-close-save').onclick=async()=>{if(await save())await finish();};
    const onKey=e=>{if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();modal.remove();}if(e.key==='Tab'){const buttons=[...modal.querySelectorAll('button')];if(e.shiftKey&&document.activeElement===buttons[0]){e.preventDefault();buttons.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===buttons.at(-1)){e.preventDefault();buttons[0].focus();}}};modal.addEventListener('keydown',onKey);$('#editor-close-cancel').focus();
  }
  let aiJob='',aiHandled='',aiContext=null,aiRunning=false,aiRestartPending=false,aiResult=null,aiLayoutBefore=null;
  let aiImages=[],aiPreparing=0;
  function aiMessage(text,who='emily',images=[]){
    const bubble=document.createElement('div');bubble.className='editor-ai-bubble '+who;bubble.dataset.raw=text;
    const body=document.createElement('div');body.className='editor-ai-text';
    if(who==='emily'&&typeof markdown==='function')body.innerHTML=markdown(text);else body.textContent=text;
    bubble.append(body);
    // O histórico guarda somente miniaturas; as referências completas vão ao modelo uma vez.
    for(const im of images){const img=document.createElement('img');img.className='editor-ai-reference';img.src=im.preview||im.data;img.alt=im.name||'Referência';img.title=img.alt;img.onload=()=>{const log=$('#editor-ai-messages');log.scrollTop=log.scrollHeight;};bubble.append(img);}
    const log=$('#editor-ai-messages');log.append(bubble);log.scrollTop=log.scrollHeight;
  }
  function renderAIImages(){
    const list=$('#editor-ai-attachments');list.replaceChildren();
    aiImages.forEach((im,i)=>{const item=document.createElement('div');item.className='editor-ai-attachment';const img=document.createElement('img');img.src=im.preview||im.data;img.alt=im.name;const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.title='Remover '+im.name;remove.setAttribute('aria-label',remove.title);remove.onclick=()=>{aiImages.splice(i,1);renderAIImages();};item.append(img,remove);list.append(item);});
    $('#editor-ai-attach').disabled=aiRunning||aiPreparing>0;$('#editor-ai-send').disabled=aiRunning||aiPreparing>0;
  }
  async function addAIImages(files,silent=false){
    let added=0;
    for(const file of files){
      if(aiImages.length+aiPreparing>=4){aiMessage('Envie até quatro imagens por pedido.');break;}
      if(file.size>4*1024*1024||!/^image\/(png|jpeg|webp|gif|x-icon|vnd.microsoft.icon)$/.test(file.type)){if(!silent)aiMessage('Use imagens PNG, JPEG, WebP ou GIF de até 4 MB.');continue;}
      aiPreparing++;renderAIImages();
      try{
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Não consegui ler a imagem.'));reader.readAsDataURL(file);});
        const image=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('Arquivo de imagem inválido.'));img.src=data;});
        if(image.naturalWidth*image.naturalHeight>20000000)throw new Error('Use imagens de até 20 megapixels.');
        const canvas=document.createElement('canvas'),scale=Math.min(1,2048/image.naturalWidth,2048/image.naturalHeight);canvas.width=Math.max(1,Math.round(image.naturalWidth*scale));canvas.height=Math.max(1,Math.round(image.naturalHeight*scale));canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);const normalized=canvas.toDataURL('image/webp',.9);
        const thumb=document.createElement('canvas'),small=Math.min(1,160/canvas.width,160/canvas.height);thumb.width=Math.max(1,Math.round(canvas.width*small));thumb.height=Math.max(1,Math.round(canvas.height*small));thumb.getContext('2d').drawImage(canvas,0,0,thumb.width,thumb.height);
        aiImages.push({name:file.name||'Imagem colada',data:normalized,preview:thumb.toDataURL('image/webp',.75)});added++;
      }catch(e){if(!silent)aiMessage(e.message);}finally{aiPreparing--;renderAIImages();}
    }
    return added;
  }
  async function addAIResponse(response){
    if(!response?.ok)return false;
    const files=[];
    for(const im of response.images||[]){if(!/^data:image\/(png|jpeg|webp|gif);base64,/.test(im.data||''))continue;const blob=await (await fetch(im.data)).blob();files.push(new File([blob],im.name||'Imagem colada',{type:blob.type}));}
    const count=await addAIImages(files);
    for(const error of response.errors||[])aiMessage(error);
    return count>0;
  }
  async function nativeAIPaste(){
    try{return await addAIResponse(await api('editor_ai_clipboard',{__teto:15000}));}catch(_){return false;}
  }
  function aiPaths(dt){
    const lines=(dt?.getData?.('text/uri-list')||dt?.getData?.('x-special/gnome-copied-files')||dt?.getData?.('text/plain')||'').split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&s!=='copy'&&s!=='cut'&&!s.startsWith('#'));
    return lines.filter(s=>/^file:/i.test(s)||/^(?:\/|[A-Za-z]:[\\/])/.test(s)).slice(0,4);
  }
  async function importAIPaths(paths){
    if(!paths.length)return false;
    try{return await addAIResponse(await api('editor_ai_arquivos',paths,false,{__teto:15000}));}catch(_){return false;}
  }
  async function pasteAI(e){
    const dt=e.clipboardData,types=[...(dt?.types||[])],items=[...(dt?.items||[])];
    const files=[...(dt?.files||[])];if(!files.length)files.push(...items.filter(i=>i.kind==='file').map(i=>i.getAsFile()).filter(Boolean));
    const html=dt?.getData?.('text/html')||'',paths=aiPaths(dt);
    const announces=files.length||items.some(i=>i.type?.startsWith('image/'))||types.some(t=>t.startsWith('image/'))||/<img\b/i.test(html)||paths.length;
    e.stopPropagation();
    if(aiRunning){if(announces)e.preventDefault();return;}
    if(announces)e.preventDefault();
    if(files.length&&await addAIImages(files,true))return;
    if(paths.length&&await importAIPaths(paths))return;
    if(announces&&navigator.clipboard?.read){
      try{const read=await navigator.clipboard.read(),webFiles=[];for(const item of read){const type=item.types.find(t=>/^image\/(png|jpeg|webp|gif)$/.test(t));if(type)webFiles.push(new File([await item.getType(type)],'Imagem colada',{type}));}if(webFiles.length&&await addAIImages(webFiles,true))return;}catch(_){}
    }
    if(/<img\b/i.test(html)){
      const doc=new DOMParser().parseFromString(html,'text/html'),sources=[...doc.querySelectorAll('img[src]')].map(n=>n.getAttribute('src')).filter(u=>/^data:image\/(png|jpeg|webp|gif);base64,/.test(u)||/^blob:/.test(u)).slice(0,4);
      for(const src of sources){try{const blob=await (await fetch(src)).blob();if(await addAIImages([new File([blob],'Imagem colada',{type:blob.type})],true))return;}catch(_){}}
    }
    // WebKit pode entregar DataTransfer vazio; texto normal conserva a colagem nativa.
    if(announces||!types.length&&!items.length){if(await nativeAIPaste())return;}
    if(announces)aiMessage('Não consegui ler essa imagem. Tente o botão Imagens ou copiar o arquivo.');
  }
  function aiExternalDrag(e){const dt=e.dataTransfer,types=[...(dt?.types||[])];return !types.length||types.includes('Files')||types.includes('text/uri-list')||types.includes('x-special/gnome-copied-files')||[...(dt?.items||[])].some(i=>i.kind==='file')||!!dt?.files?.length;}
  async function dropAI(e){
    // Cancelar é síncrono, mesmo se FileList estiver vazio ou a importação falhar.
    e.preventDefault();e.stopImmediatePropagation();
    if(aiRunning)return;
    const dt=e.dataTransfer,files=[...(dt?.files||[])],paths=aiPaths(dt);
    if(files.length&&await addAIImages(files,true))return;
    if(await importAIPaths(paths.length?paths:files.map(f=>f.name)))return;
    aiMessage('Não consegui ler a imagem arrastada. Use o botão Imagens. A interface continua aberta.');
  }
  function fitAIChat(){
    const box=$('#editor-ai-chat');if(!box)return;
    const top=Math.max(12,Math.min(parseFloat(box.style.top)||12,Math.max(12,innerHeight-400)));
    box.style.top=top+'px';box.style.maxHeight=Math.max(160,innerHeight-top-12)+'px';
    box.style.left=Math.max(12,Math.min(parseFloat(box.style.left)||12,innerWidth-box.getBoundingClientRect().width-12))+'px';
  }
  function openAI(){
    if(!selected)return;
    const node=nodes.get(selected),r=node?.getBoundingClientRect();
    aiContext={key:selected,name:name(node),tag:node?.tagName||'custom',html:node?.outerHTML?.replace(/data:image\/[^"' >]+/g,'[imagem importada]').slice(0,16000)||'',computed:node?Object.fromEntries([...Object.keys(colors),...Object.keys(numbers)].map(k=>[k,getComputedStyle(node)[k]])): {},rule:{...C.clone(info(selected)),image:info(selected).image?'Imagem importada':undefined},page:pageFor(selected)||null};
    const box=$('#editor-ai-chat');box.hidden=false;box.style.left=Math.max(12,Math.min((r?.right||100)+12,innerWidth-460))+'px';box.style.top=Math.max(12,Math.min(r?.top||100,innerHeight-620))+'px';
    fitAIChat();$('#editor-ai-selection').textContent=aiContext.name||selected;$('#editor-ai-prompt').focus();
  }
  async function aiSend(){
    const input=$('#editor-ai-prompt'),text=input.value.trim();if(!text||aiRunning||aiPreparing||!aiContext)return;
    const button=$('#editor-ai-send');button.disabled=true;
    try{const response=await api('editor_ai_enviar',text,aiContext,aiImages.map(({name,data})=>({name,data})));if(!response?.ok)throw new Error(response?.error||'Não consegui iniciar.');aiJob=response.id;aiHandled='';aiRunning=true;input.value='';aiMessage(text,'user',aiImages);aiImages=[];renderAIImages();}
    catch(e){aiMessage(e.message);}
    finally{button.disabled=aiRunning;}
    pollAI();
  }
  async function refreshCode(files){
    if(files?.some(f=>f.endsWith('.html')||f.endsWith('.js'))){
      await flushDraft();sessionStorage.setItem('emily-editor-ai-session',JSON.stringify({job:aiJob,handled:aiHandled,context:aiContext,result:aiResult,messages:[...$('#editor-ai-messages').children].map(p=>({text:p.dataset.raw??p.textContent,who:p.classList.contains('user')?'user':'emily',images:[...p.querySelectorAll('.editor-ai-reference')].map(img=>({preview:img.src,name:img.alt}))})),pendingImages:aiImages,prompt:$('#editor-ai-prompt').value,open:!$('#editor-ai-chat').hidden}));sessionStorage.setItem('emily-editor-ai-handled',aiHandled);const live={selected,mode,document:doc,revision,history:{stack:C.clone(history.stack),index:history.index}};
      while(JSON.stringify(live).length>2500000&&live.history.stack.length>1){if(live.history.index>0){live.history.stack.shift();live.history.index--;}else live.history.stack.pop();}
      if(JSON.stringify(live).length>2500000){delete live.history;delete live.document;}
      sessionStorage.setItem('emily-editor-live',JSON.stringify(live));liveReload=true;location.reload();return;
    }
    panelAssets=Date.now();queuePanel();
    document.querySelectorAll('link[rel=stylesheet]').forEach(link=>{const u=new URL(link.href);if(files?.some(f=>u.pathname.endsWith('/'+f.replace(/^web\//,'')))){u.searchParams.set('editor_update',Date.now());link.href=u.href;}});
  }
  let pollingAI=false;
  async function pollAI(){
    if(pollingAI)return;pollingAI=true;
    try{
      const response=await api('editor_ai_estado');if(!response?.ok)return;
      const job=response.job;aiRestartPending=!!response.restart_pending;$('#editor-ai-restart').hidden=!aiRestartPending;
      if(!job)return;aiJob=job.id;aiRunning=job.running;
      const status=$('#editor-ai-status');status.textContent=job.status;status.dataset.phase=job.phase;
      $('#editor-ai-send').disabled=aiRunning||aiPreparing>0;$('#editor-ai-attach').disabled=aiRunning||aiPreparing>0;$('#editor-ai-cancel').hidden=!aiRunning;
      if(!job.running&&aiHandled!==job.id){
        aiHandled=job.id;aiResult=job.result;
        if(job.error)aiMessage(job.error);
        if(job.result){
          const result=job.result;if(result.undone)return;
          if(result.layout&&Object.keys(result.layout).length){aiLayoutBefore=C.clone(doc);const origin=job.selected;change(d=>{const rule=d.elements[origin]||={};if(result.layout.styles)Object.assign(rule.styles||={},result.layout.styles);Object.assign(rule,Object.fromEntries(Object.entries(result.layout).filter(([k])=>k!=='styles')));},'');inspect();}
          aiMessage(result.message,'emily',result.images||[]);if(result.files?.length)aiMessage('Arquivos alterados: '+result.files.join(', ')+'. Sintaxe conferida; use Navegar/testar para conferir o comportamento.');
          if(result.restart)aiMessage('O código Python mudou. Preciso reiniciar para carregar essa parte. Você pode fazer isso agora ou continuar e reiniciar depois.');
          if(result.publication?.ok===false)aiMessage('Aplicado neste PC, mas a publicação Windows falhou: '+result.publication.error);
          $('#editor-ai-undo').hidden=!result.files?.length;
          await refreshCode(result.files);
        }
      }
    }catch(e){if(aiRunning)$('#editor-ai-status').textContent='Reconectando ao editor…';}
    finally{pollingAI=false;}
  }
  function initializeAI(){
    const box=document.createElement('section');box.id='editor-ai-chat';box.className='editor-ai-chat';box.hidden=true;
    box.innerHTML='<header><div><strong>✦ Editar com a Emily</strong><small id="editor-ai-selection"></small></div><button id="editor-ai-close" aria-label="Fechar chat">×</button></header><p class="editor-ai-model">GPT 6 Sol · Médio · Interface e código</p><div id="editor-ai-messages" role="log" aria-live="polite"></div><div id="editor-ai-status" role="status"></div><div id="editor-ai-attachments" aria-label="Imagens anexadas"></div><input id="editor-ai-files" type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden><div class="editor-ai-attach-row"><button id="editor-ai-attach" type="button">＋ Imagens</button><small>Anexe, cole ou arraste · até 4 imagens</small></div><textarea id="editor-ai-prompt" rows="3" maxlength="6000" placeholder="O que você quer mudar neste elemento?"></textarea><div class="editor-ai-actions"><button id="editor-ai-send" class="editor-primary">Enviar</button><button id="editor-ai-cancel" hidden>Cancelar tarefa</button><button id="editor-ai-undo" hidden>Desfazer código</button><button id="editor-ai-restart" hidden>Reiniciar agora</button><button id="editor-ai-later">Agora não / depois</button></div>';
    document.body.append(box);$('#editor-ai-close').onclick=()=>box.hidden=true;$('#editor-ai-later').onclick=()=>box.hidden=true;$('#editor-ai-send').onclick=aiSend;
    $('#editor-ai-attach').onclick=async()=>{
      try{const r=await api('editor_ai_arquivos',[],true,{__teto:120000});if(!r?.ok){aiMessage(r?.error||'Não consegui abrir o seletor.');return;}await addAIResponse(r);}
      catch(e){if(/não existe|ponte indisponível/.test(e.message))$('#editor-ai-files').click();else aiMessage(e.message);} // Prévia em navegador sem ponte nativa.
    };
    $('#editor-ai-files').onchange=e=>{addAIImages([...e.target.files]);e.target.value='';};
    box.addEventListener('paste',pasteAI);
    window.addEventListener('dragover',e=>{if(!box.hidden&&aiExternalDrag(e)){e.preventDefault();e.stopImmediatePropagation();if(e.dataTransfer)e.dataTransfer.dropEffect='copy';}},true);
    window.addEventListener('drop',e=>{if(!box.hidden&&aiExternalDrag(e))dropAI(e);},true);
    $('#editor-ai-prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();aiSend();}};
    $('#editor-ai-cancel').onclick=async()=>{await api('editor_ai_cancelar');$('#editor-ai-status').textContent='Cancelando antes de aplicar…';};
    $('#editor-ai-restart').onclick=async()=>{if(dirty()&&!await save())return;await flushDraft();const r=await api('editor_ai_reiniciar');if(!r?.ok)aiMessage(r?.error||'Não consegui reiniciar.');};
    $('#editor-ai-undo').onclick=async()=>{const r=await api('editor_ai_desfazer',aiJob);if(!r?.ok){aiMessage(r?.error||'Não consegui desfazer.');return;}aiMessage('Restaurei os arquivos anteriores.');$('#editor-ai-undo').hidden=true;if(aiResult)aiResult.undone=true;await refreshCode(r.files);};
    try{const session=JSON.parse(sessionStorage.getItem('emily-editor-ai-session'));sessionStorage.removeItem('emily-editor-ai-session');if(session){aiJob=session.job;aiHandled=session.handled;aiContext=session.context;aiResult=session.result;for(const m of session.messages||[])aiMessage(m.text,m.who,m.images||[]);aiImages=session.pendingImages||[];renderAIImages();$('#editor-ai-prompt').value=session.prompt||'';$('#editor-ai-selection').textContent=aiContext?.name||'';$('#editor-ai-undo').hidden=!aiResult?.files?.length||!!aiResult.undone;if(session.open){box.hidden=false;box.style.left='40px';box.style.top='100px';}}}catch(_){}
    addEventListener('resize',fitAIChat);fitAIChat();setInterval(pollAI,800);
  }
  async function initialize(){
    if(initialized)return;initialized=true;
    const style=document.createElement('style');style.id='editor-layout-style';document.head.append(style);
    const inspector=document.createElement('aside');inspector.id='editor-inspector';inspector.className='editor-inspector';inspector.setAttribute('aria-label','Propriedades do editor');document.body.append(inspector);
    initializeAI();
    const box=document.createElement('div');box.id='editor-outline';box.className='editor-outline';box.innerHTML='<button type="button" class="editor-ai-star" title="Editar este elemento com a Emily" aria-label="Editar com a Emily">✦</button><span></span><div class="editor-move" title="Arrastar para mover">✥</div><div class="editor-size" title="Arrastar para redimensionar"></div>';document.body.append(box);
    const bar=$('#editor-toolbar');const title=document.createElement('strong');title.textContent='MODO EDITOR';bar.append(title);
    toolbarButton('editor-select','Selecionar',()=>setMode(mode==='select'?'interact':'select'));
    toolbarButton('editor-move','Mover',()=>setMode('move'));toolbarButton('editor-resize','Redimensionar',()=>setMode('resize'));toolbarButton('editor-interact','Navegar / testar',()=>setMode('interact'));
    const modeHelp=document.createElement('span');modeHelp.className='editor-mode-help';modeHelp.textContent='Selecionar escolhe; Mover arrasta; Navegar usa os controles.';bar.append(modeHelp);
    toolbarButton('editor-properties','Janela de propriedades',openPanel);
    toolbarButton('editor-android','📱 Editor Android',async()=>{const r=await api('editor_android_abrir');if(!r?.ok){notice=r?.error||'Não consegui abrir o editor Android.';updateToolbar();}});
    toolbarButton('editor-undo','↶ Desfazer',undo);toolbarButton('editor-redo','↷ Refazer',redo);
    toolbarButton('editor-save','Salvar',save,true);
    toolbarButton('editor-ai-open','✦ Pedir ajuste à Emily',openAI);
    const state=document.createElement('span');state.id='editor-state';state.className='editor-state';state.setAttribute('role','status');bar.append(state);
    toolbarButton('editor-recover','Recuperar rascunho',()=>{if(recovery){if(recovery.revision!==revision&&!confirm('O layout salvo mudou desde este rascunho. Recuperar a versão antiga para conferir antes de salvar?'))return;change(d=>Object.assign(d,recovery.document));recovery=null;renderCustom();inspect();updateToolbar();}});
    toolbarButton('editor-exit','Sair do editor',toggle);
    $('#btn-editor').onclick=toggle;
    box.querySelector('.editor-ai-star').onclick=openAI;
    box.querySelector('.editor-move').onpointerdown=e=>startDrag(e,false);box.querySelector('.editor-size').onpointerdown=e=>startDrag(e,true);
    document.addEventListener('pointerdown',e=>{if(!active||mode!=='move'||own(e.target)||e.button!==0)return;const node=e.target.closest(editable);if(node&&allowed(node)){select(node);startDrag(e,false);}},true);
    document.addEventListener('pointermove',dragMove,true);document.addEventListener('pointerup',dragEnd,true);document.addEventListener('pointercancel',()=>{if(drag){doc=drag.before;drag=null;apply();}},true);
    let loaded;try{loaded=await api('editor_carregar');}catch(e){notice='Falha ao carregar layout: '+e.message;}
    if(loaded?.ok){doc=C.clone(loaded.document);saved=C.clone(doc);revision=loaded.revision;if(loaded.warnings?.length)notice=loaded.warnings.join('; ');}
    else {notice ||= 'Editor indisponível: não foi possível carregar o layout.';$('#btn-editor').disabled=true;}
    history.reset(doc);
    try{const live=JSON.parse(sessionStorage.getItem('emily-editor-live'));sessionStorage.removeItem('emily-editor-live');if(live&&live.revision===revision){if(live.document){doc=C.clone(live.document);if(live.history?.stack?.length){history.stack=live.history.stack;history.index=live.history.index;history.lastKey='';}else history.push(doc);}selected=live.selected;mode=live.mode;aiHandled=sessionStorage.getItem('emily-editor-ai-handled')||'';setTimeout(async()=>{await toggle();setMode(live.mode);outline();},80);}}catch(_){}
    try{const disk=await api('editor_recuperar');if(disk?.ok===false)notice=disk.error||'Falha ao recuperar rascunho.';if(disk?.draft?.saved_at) recovery={revision:disk.draft.base_revision,document:disk.draft.document,saved_at:disk.draft.saved_at};}catch(_){}
    try{const draft=JSON.parse(localStorage.getItem(draftKey));if(draft?.document&&JSON.stringify(draft.document)!==JSON.stringify(doc)&&(!recovery||(draft.saved_at||0)>(recovery.saved_at||0)))recovery=draft;}catch(_){}
    observer=new MutationObserver(records=>{if(records.some(r=>{
      const node=r.target instanceof Element?r.target:r.target.parentElement;if(!allowed(node))return false;if(active)return true;
      // Respostas em streaming não precisam reindexar toda a interface a cada token.
      const zone=node.closest('.msg,.mensagem,.bolha,#conversas,.pl-faixa,.code-mensagem');
      if(zone){const base=zone.dataset.emilyEditorKey;return Object.keys(doc.elements).some(k=>base&&(k===base||k.startsWith(base+'|')));}
      if(r.type==='characterData'||r.type==='childList'&&[...r.addedNodes,...r.removedNodes].every(n=>n.nodeType===Node.TEXT_NODE)){
        for(let el=node;el;el=el.parentElement)if(typeof info(el.dataset.emilyEditorKey).label==='string')return true;return false;
      }
      return true;
    }))schedule();});
    if(typeof ResizeObserver==='function')new ResizeObserver(outline).observe(document.body);
    window.addEventListener('resize',()=>{updateToolbar();outline();});window.addEventListener('scroll',outline,true);
    document.addEventListener('click',e=>{if(!active||!selecting||own(e.target))return;const node=e.target.closest(editable);if(node&&allowed(node)){e.preventDefault();e.stopImmediatePropagation();select(node);}},true);
    document.addEventListener('change',e=>{if(active&&selecting&&!own(e.target)){e.preventDefault();e.stopImmediatePropagation();}},true);
    document.addEventListener('submit',e=>{if(active&&selecting&&!own(e.target)){e.preventDefault();e.stopImmediatePropagation();}},true);
    document.addEventListener('keydown',e=>{
      if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='e'){e.preventDefault();e.stopImmediatePropagation();toggle();return;}
      if(!active)return;
      if(e.target.closest?.('#editor-ai-chat'))return;
      if(e.key==='Delete'&&!e.target.closest?.('input,textarea,select,[contenteditable=true]')&&!$('#editor-close-dialog')){e.preventDefault();e.stopImmediatePropagation();deleteCustom();return;}
      if(!own(e.target)&&!e.target.matches?.('input,textarea,select')&&['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)&&mode==='move'&&selected){e.preventDefault();e.stopImmediatePropagation();const delta=e.shiftKey?1:grid;const field=['ArrowLeft','ArrowRight'].includes(e.key)?'x':'y';property(field,(info(selected).styles?.[field]||0)+(['ArrowLeft','ArrowUp'].includes(e.key)?-delta:delta),true);inspect();return;}
      const modal=$('#editor-close-dialog');if(modal){if(e.key==='Escape'){e.preventDefault();modal.remove();}else if(e.key==='Tab'){const buttons=[...modal.querySelectorAll('button')];if(e.shiftKey&&document.activeElement===buttons[0]){e.preventDefault();buttons.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===buttons.at(-1)){e.preventDefault();buttons[0].focus();}}e.stopImmediatePropagation();return;}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.stopImmediatePropagation();e.shiftKey?redo():undo();return;}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();e.stopImmediatePropagation();redo();return;}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();e.stopImmediatePropagation();save();return;}
      if(e.key==='Escape'&&!own(e.target)){e.preventDefault();e.stopImmediatePropagation();selected='';inspect();outline();}
      if(active&&selecting&&!own(e.target)&&e.target.matches?.('button,input,textarea,select')){e.preventDefault();e.stopImmediatePropagation();return;}
      if(own(e.target))e.stopImmediatePropagation();
    },true);
    setInterval(()=>{if(active&&dirty()){draftPending={document:C.clone(doc),revision};flushDraft();}},10000);
    window.addEventListener('pagehide',()=>{if(dirty()){persistDraft();flushDraft();}});
    window.addEventListener('beforeunload',e=>{if(!liveReload&&active&&dirty()){persistDraft();e.preventDefault();e.returnValue='';}});
    // Reexibir composer singleton ao voltar às telas normais.
    observer.observe(document.body,{childList:true,subtree:true,characterData:true});apply();inspect();
  }
  window.EmilyEditor={labelFor:k=>info(k).label,initialize,toggle,save,undo,redo,openPage,requestClose,command,getState:()=>({active,selecting,mode,selected,dirty:dirty(),document:C.clone(doc),revision})};
})();
