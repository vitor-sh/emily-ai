/* Sons originais do xadrez: síntese local, sem downloads ou chamadas ao PC. */
(() => {
  'use strict';
  let context, enabled = true;
  const buffers = new Map(), sources = new Set(), personalizados = new Map();
  let pacote = {personalizado:false, arquivos:{}}, serial = 0;
  const nomes = {move:'Lance', capture:'Captura', castle:'Roque', promotion:'Promoção', check:'Xeque', mate:'Xeque-mate', draw:'Empate', start:'Início da partida', end:'Fim por desistência'};
  async function ponte(operacao, dados={}) {
    const api=window.pywebview?.api;
    if(!api?.xadrez_acao) throw new Error('A conexão local com a Emily não está pronta.');
    const result=await api.xadrez_acao('sons',{operacao,...dados});
    if(!result?.ok) throw new Error(result?.erro || 'Não consegui salvar os sons locais.');
    return result;
  }
  async function decodificar(item) {
    context ||= new (window.AudioContext || window.webkitAudioContext)();
    const bytes=Uint8Array.from(atob(item.base64),c=>c.charCodeAt(0));
    const decoded=await context.decodeAudioData(bytes.buffer);
    if(decoded.duration>5) throw new Error('Use efeitos de até 5 segundos.');
    return decoded;
  }
  async function carregar() {
    const token=++serial;
    const salvo=await ponte('ler'), decoded=new Map();
    for(const [tipo,item] of Object.entries(salvo.arquivos)) {
      try {decoded.set(tipo,await decodificar(item));} catch(_) { /* Efeito inválido usa síntese. */ }
    }
    if(token!==serial)return;
    pacote=salvo;personalizados.clear();for(const [tipo,b] of decoded)personalizados.set(tipo,b);
  }
  async function importar(arquivos) {
    const novos={}, decoded=new Map();
    for(const [tipo,file] of Object.entries(arquivos)) {
      if(!nomes[tipo] || !file)continue;
      const formato=file.name.split('.').pop().toLowerCase();
      if(!['wav','mp3','ogg'].includes(formato) || !file.size || file.size>1048576)throw new Error('Use MP3, WAV ou OGG de até 1 MB por efeito.');
      const bytes=new Uint8Array(await file.arrayBuffer());
      let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
      novos[tipo]={formato,base64:btoa(binary)};
      try{decoded.set(tipo,await decodificar(novos[tipo]));}catch(_){throw new Error('Não consegui reproduzir '+nomes[tipo]+'. Use áudio válido de até 5 segundos.');}
    }
    const salvo=await ponte('importar',{arquivos:novos});
    ++serial;stop();pacote=salvo;for(const [tipo,b] of decoded)personalizados.set(tipo,b);
  }
  async function selecionar(value) {
    pacote=await ponte('selecionar',{personalizado:Boolean(value)});++serial;stop();
  }
  async function limpar() {
    pacote=await ponte('limpar');++serial;stop();personalizados.clear();
  }
  try { enabled = localStorage.getItem('emily-xadrez-som') !== '0'; } catch (_) {}
  const supported = Boolean(window.AudioContext || window.webkitAudioContext);
  function wake() {
    if (!enabled || !supported) return;
    try {
      context ||= new (window.AudioContext || window.webkitAudioContext)();
      if (context.state === 'suspended') context.resume().catch(() => {});
    } catch (_) { /* Sem saída de áudio, o jogo continua normalmente. */ }
  }
  function buffer(type) {
    if (buffers.has(type)) return buffers.get(type);
    const rate = context.sampleRate;
    const length = type === 'mate' ? .8 : type === 'draw' ? .6 : type === 'check' ? .38 : type === 'promotion' ? .45 : type === 'castle' ? .24 : .15;
    const b = context.createBuffer(1, Math.ceil(rate * length), rate), data = b.getChannelData(0);
    const taps = type === 'castle' ? [0,.105] : [0];
    let seed = 1879, low = 0;
    for (let i = 0; i < data.length; i++) {
      const t = i/rate;
      // Short filtered noise plus a damped wooden resonance: a soft piece tap.
      if (['move','capture','castle'].includes(type)) {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        low += ((seed / 2147483648 - 1) - low) * .22;
        for (const start of taps) {
          const d = t-start;
          if (d < 0 || d > .14) continue;
          const freq = type === 'capture' ? 390 : 670;
          const attack = Math.min(1,d/.0015);
          data[i] += attack * (.18 * low * Math.exp(-d*65) + .13 * Math.sin(2*Math.PI*freq*d) * Math.exp(-d*48));
        }
      } else {
        const notes = type === 'check' ? [784,988] : type === 'promotion' ? [523,659,784] : type === 'mate' ? [523,659,784,1047] : [587,494,440];
        const gap = type === 'mate' ? .13 : .10;
        for (let n=0;n<notes.length;n++) {
          const d=t-n*gap; if(d<0) continue;
          const envelope = Math.min(1,d/.006)*Math.exp(-d*(type==='mate'?8:15));
          data[i] += .085*envelope*(Math.sin(2*Math.PI*notes[n]*d)+.16*Math.sin(4*Math.PI*notes[n]*d));
        }
      }
    }
    buffers.set(type,b);return b;
  }
  function play(type, delay = 0) {
    wake();
    if (!enabled || !context || context.state !== 'running') return;
    try {
      const source=context.createBufferSource();source.buffer=(pacote.personalizado && personalizados.get(type)) || buffer(type);source.connect(context.destination);
      sources.add(source);source.onended=()=>{sources.delete(source);source.disconnect();};
      source.start(context.currentTime+delay);
    } catch (_) {}
  }
  function events(move, board) {
    const base = move?.flags?.match(/[kq]/) ? 'castle' : move?.promotion ? 'promotion' : move?.captured ? 'capture' : 'move';
    if (board.isCheckmate()) return [base,'mate'];
    if (board.isDraw()) return [base,'draw'];
    if (board.isCheck()) return [base,'check'];
    return [base];
  }
  function aoLance(move, board) {
    const selected=events(move,board);
    if(selected.length>1 && pacote.personalizado && personalizados.has(selected.at(-1)))play(selected.at(-1));
    else selected.forEach((type,i)=>play(type,i*.18));
  }
  function stop() { for(const source of sources) {try{source.stop();}catch(_){}} sources.clear(); }
  window.EmilyChessAudio = {
    wake, aoLance, events, supported, carregar, importar, selecionar, limpar, nomes,
    avisar(tipo){if(nomes[tipo])play(tipo);},
    get personalizado(){return pacote.personalizado;},
    get tiposLocais(){return [...personalizados.keys()];},
    get ativo(){return enabled;},
    ativar(value){enabled=Boolean(value);try{localStorage.setItem('emily-xadrez-som',enabled?'1':'0');}catch(_){}if(enabled)wake();else stop();return enabled;},
    stop
  };
})();
