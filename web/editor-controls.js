/* Paleta desenhada em HTML: não depende do seletor nativo do GTK/Windows. */
(() => {
  const hexInput = box => box.querySelector('input[data-editor-color]');
  const set = (box,value) => {
    const input=hexInput(box);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));
    const swatch=box.querySelector('.editor-color-swatch');swatch.style.background=value||'transparent';
    box.querySelectorAll('[data-color-channel]').forEach(r=>{r.value=parseInt(value.slice(1+Number(r.dataset.colorChannel)*2,3+Number(r.dataset.colorChannel)*2),16)||0;});
  };
  document.addEventListener('click',e=>{
    const box=e.target.closest('.editor-color-control');if(!box)return;
    const toggle=e.target.closest('[data-color-toggle]');
    if(toggle){const picker=box.querySelector('.editor-color-picker');picker.hidden=!picker.hidden;toggle.setAttribute('aria-expanded',String(!picker.hidden));return;}
    if(e.target.closest('[data-color-clear]')){set(box,'');return;}
    const preset=e.target.closest('[data-color-preset]');if(preset)set(box,preset.dataset.colorPreset);
  });
  document.addEventListener('input',e=>{
    const box=e.target.closest('.editor-color-control');if(!box)return;
    if(e.target.matches('[data-color-channel]')){
      const v='#'+[...box.querySelectorAll('[data-color-channel]')].map(r=>Number(r.value).toString(16).padStart(2,'0')).join('');set(box,v);
    }else if(e.target.matches('[data-editor-color]')&&/^#[a-f\d]{6}$/i.test(e.target.value)){
      box.querySelector('.editor-color-swatch').style.background=e.target.value;
    }
  });
})();
