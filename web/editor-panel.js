/* A janela de propriedades envia intenções; a janela principal mantém o histórico. */
(() => {
  let version=-1,state={},busy=false,focusedAt=0,bridge,lastAssets=0;
  const $=s=>document.querySelector(s);
  const help={select:'Clique no elemento na Emily para editar.',move:'Arraste o elemento na Emily. Setas movem pela grade; Shift move 1 px.',resize:'Selecione e arraste o canto inferior direito da marcação.',interact:'Use os botões normalmente para navegar, sem sair do editor.'};
  async function send(c){
    try{const r=await bridge.comando({...c,selected:state.selected});if(!r?.ok)throw new Error(r?.error||'Comando recusado.');}
    catch(e){$('#panel-status').textContent='Não consegui aplicar: '+e.message;}
  }
  function render(next){
    if(lastAssets&&next.assets&&lastAssets!==next.assets){location.reload();return;}
    lastAssets=next.assets||lastAssets;state=next;$('#panel-status').textContent=state.active?state.notice:'O editor está fechado na Emily. Abra Editor para continuar.';
    document.querySelectorAll('[data-panel-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.panelMode===state.mode)));
    $('#panel-mode-help').textContent=help[state.mode]||help.select;
    document.querySelectorAll('[data-panel-shortcut]').forEach(b=>{b.disabled=!!state.saving||!state.active||(b.dataset.panelShortcut==='undo'&&!state.canUndo)||(b.dataset.panelShortcut==='redo'&&!state.canRedo);});
    const root=$('#editor-inspector'),focused=document.activeElement;
    const typing=root.contains(focused)&&focused.matches('input[type=text],input[type=number],input[type=search],input[type=range]')&&root.dataset.selection===state.selected;
    if(root.dataset.html!==state.html&&!typing){
      const scroll=window.scrollY,opened=[...root.querySelectorAll('details[open]')].map(d=>d.querySelector('summary')?.textContent);
      root.innerHTML=state.html||'<p>Escolha um elemento na Emily.</p>';root.dataset.html=state.html;root.dataset.selection=state.selected||'';
      root.querySelectorAll('details').forEach(d=>{if(opened.includes(d.querySelector('summary')?.textContent))d.open=true;});
      window.scrollTo(0,scroll);
    }
    root.inert=!!state.saving||!state.active;
  }
  async function poll(){
    if(busy||!bridge)return;busy=true;
    try{const r=await bridge.estado(version);if(r?.ok&&r.changed){version=r.version;render(r.state||{});}}
    catch(e){$('#panel-status').textContent='A conexão com a Emily foi interrompida. Tentando reconectar…';}
    finally{busy=false;}
  }
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.panelShortcut){document.activeElement?.blur();send({kind:'shortcut',value:b.dataset.panelShortcut});return;}
    if(b.dataset.panelMode){send({kind:'mode',value:b.dataset.panelMode});return;}
    if(b.id==='panel-android'){try{const r=await bridge.android();if(!r?.ok)throw new Error(r?.error); }catch(e){$('#panel-status').textContent=e.message;}return;}
    if(b.id==='panel-show-main'){send({kind:'show_main'});return;}
    if(b.dataset.editorCategory){send({kind:'category',value:b.dataset.editorCategory});return;}
    if(b.id?.startsWith('editor-'))send({kind:'click',id:b.id});
  });
  for(const event of ['input','change'])document.addEventListener(event,e=>{
    const el=e.target;if(!el.closest('#editor-inspector')||!el.matches('input,select,textarea')||el.hasAttribute('data-color-channel'))return;
    if((el.tagName==='SELECT'||el.type==='checkbox')&&event!=='change')return;
    if(el.dataset.editorColor&&el.value!==''&&!/^#[a-f\d]{6}$/i.test(el.value))return;
    if(!el.id&&!el.dataset.editorField&&!el.dataset.editorTheme)return;
    send({kind:'field',id:el.id,field:el.dataset.editorField,theme:el.dataset.editorTheme,value:el.type==='checkbox'?el.checked:el.value,event});
  });
  document.addEventListener('keydown',e=>{
    if(e.key==='Delete'&&!e.target.closest?.('input,textarea,select,[contenteditable=true]')){e.preventDefault();send({kind:'shortcut',value:'delete'});return;}
    if(!(e.ctrlKey||e.metaKey))return;let value;
    if(e.key.toLowerCase()==='s')value='save';if(e.key.toLowerCase()==='z')value=e.shiftKey?'redo':'undo';if(e.key.toLowerCase()==='y')value='redo';
    if(value){e.preventDefault();document.activeElement?.blur();send({kind:'shortcut',value});}
  });
  document.addEventListener('focusout',()=>setTimeout(()=>{if(state.html)render(state);},0));
  function ready(){bridge=window.pywebview?.api;if(bridge){poll();setInterval(poll,300);}else $('#panel-status').textContent='Abra esta janela pelo botão Editor da Emily.';}
  if(window.pywebview?.api)ready();else window.addEventListener('pywebviewready',ready,{once:true});
})();
