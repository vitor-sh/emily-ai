/* Dropdowns HTML, iguais no WebKitGTK e no Edge; mantém o select original como modelo. */
(() => {
  const controls=new Map();let popup=null,current=null;
  function close(){if(current)current.button.setAttribute('aria-expanded','false');popup?.remove();popup=null;current=null;}
  function optionKey(select,option){let h=2166136261;for(const c of option.value)h=Math.imul(h^c.charCodeAt(0),16777619);const source=select.dataset.emilyEditorKey||(select.id?'id:'+select.id:'');return source?source+'|option.'+(h>>>0).toString(16):'';}
  function optionLabel(select,option){if(!option)return '';const edited=window.EmilyEditor?.labelFor?.(optionKey(select,option));return typeof edited==='string'?edited:option.textContent;}
  function refresh(select,record){
    record.button.disabled=select.disabled;record.button.hidden=select.hidden||select.style.display==='none';
    const text=optionLabel(select,select.selectedOptions[0])||optionLabel(select,select.options[0])||'Escolher…';
    if(!record.button.dataset.editorLabelOverride&&record.caption.textContent!==text)record.caption.textContent=text;
    record.button.setAttribute('aria-label',select.getAttribute('aria-label')||select.labels?.[0]?.textContent.trim()||select.title||text);
    record.button.title=select.title;
  }
  function choose(select,index){if(select.disabled||select.options[index]?.disabled)return;select.selectedIndex=index;select.dispatchEvent(new Event('input',{bubbles:true}));select.dispatchEvent(new Event('change',{bubbles:true}));const r=controls.get(select);if(r)refresh(select,r);close();r?.button.focus();}
  function open(select,record){
    if(select.disabled)return;if(current===record){close();return;}close();current=record;
    popup=document.createElement('div');popup.className='emily-select-popup';if(select.closest('#editor-inspector,#editor-toolbar'))popup.dataset.editorOwned='true';popup.setAttribute('role','listbox');popup.setAttribute('aria-label',record.button.getAttribute('aria-label'));record.button.setAttribute('aria-expanded','true');
    const list=document.createElement('div');list.className='emily-select-options';popup.append(list);
    const render=term=>{list.replaceChildren();let count=0;[...select.options].forEach((option,index)=>{if(option.hidden||term&&!optionLabel(select,option).toLocaleLowerCase().includes(term))return;count++;const b=document.createElement('button');b.type='button';b.setAttribute('role','option');b.dataset.selectValue=option.value;const key=optionKey(select,option);if(key)b.dataset.emilyEditorKey=key;b.setAttribute('aria-selected',String(index===select.selectedIndex));b.disabled=option.disabled||option.parentElement?.disabled;b.textContent=optionLabel(select,option);b.onclick=()=>choose(select,index);list.append(b);});if(!count){const p=document.createElement('p');p.textContent='Nenhuma opção encontrada';list.append(p);}};
    let search;if(select.options.length>10){search=document.createElement('input');search.type='search';search.placeholder='Filtrar opções…';search.setAttribute('aria-label','Filtrar opções');search.oninput=()=>render(search.value.toLocaleLowerCase());popup.prepend(search);}render('');document.body.append(popup);
    const rect=record.button.getBoundingClientRect(),height=Math.min(340,popup.scrollHeight),width=Math.min(Math.max(rect.width,250),innerWidth-24);
    popup.style.width=width+'px';popup.style.left=Math.max(12,Math.min(rect.left,innerWidth-width-12))+'px';popup.style.top=(rect.bottom+height+8<innerHeight?rect.bottom+6:Math.max(12,rect.top-height-6))+'px';
    (search||list.querySelector('[aria-selected=true]')||list.querySelector('button'))?.focus();
    popup.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();close();record.button.focus();}else if(['ArrowUp','ArrowDown','Home','End'].includes(e.key)){e.preventDefault();const buttons=[...list.querySelectorAll('button:not(:disabled)')];if(!buttons.length)return;const index=buttons.indexOf(document.activeElement);const next=e.key==='Home'?0:e.key==='End'?buttons.length-1:Math.max(0,Math.min(buttons.length-1,index+(e.key==='ArrowDown'?1:-1)));buttons[next]?.focus();}};
  }
  function upgrade(select){
    if(controls.has(select)||select.multiple||select.size>1)return;
    const button=document.createElement('button');button.type='button';button.className='emily-native-select';button._emilySelectSource=select;button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
    const caption=document.createElement('span');button.append(caption);const arrow=document.createElement('span');arrow.className='emily-select-arrow';arrow.textContent='⌄';arrow.setAttribute('aria-hidden','true');button.append(arrow);
    const record={button,caption};controls.set(select,record);select.classList.add('emily-select-source');select.after(button);refresh(select,record);
    button.onclick=()=>open(select,record);button.onkeydown=e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();open(select,record);}};
    select.addEventListener('change',()=>refresh(select,record));select.addEventListener('input',()=>refresh(select,record));
    if(select.id)document.querySelectorAll('label[for]').forEach(l=>{if(l.htmlFor===select.id)l.addEventListener('click',e=>{if(e.target===l){e.preventDefault();button.focus();}});});
  }
  let queued=false;
  function scan(){queued=false;for(const [s,r] of controls){if(!s.isConnected){r.button.remove();controls.delete(s);if(current===r)close();}else refresh(s,r);}document.querySelectorAll('select').forEach(upgrade);}
  const observer=new MutationObserver(()=>{if(!queued){queued=true;queueMicrotask(scan);}});
  function start(){scan();observer.observe(document.body,{childList:true,subtree:true});setInterval(scan,750);}
  document.addEventListener('click',e=>{if(popup&&!popup.contains(e.target)&&!current?.button.contains(e.target))close();});
  document.addEventListener('focusin',e=>{if(popup&&!popup.contains(e.target)&&!current?.button.contains(e.target))close();});
  window.addEventListener('resize',close);window.addEventListener('scroll',e=>{if(popup&&!popup.contains(e.target))close();},true);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
