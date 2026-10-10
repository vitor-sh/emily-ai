/* Chromium isolado da Emily visto no painel lateral do chat. */
let _niMontado = false;
let _niSuprimirAuto = false;
let _niLargura = 0;
let _niLiberarControle = null;

function restaurarAberturaAutomaticaNavegador() { _niSuprimirAuto = false; }

function _niLimitarLargura(valor) {
  const corpo = document.getElementById('corpo');
  const lateral = document.getElementById('lateral');
  const disponivel = corpo.clientWidth - (lateral?.getBoundingClientRect().width || 0);
  return Math.max(300, Math.min(Math.round(valor), Math.max(300, disponivel - 340)));
}

function _niAplicarLargura(valor, salvar = false) {
  _niLargura = _niLimitarLargura(valor);
  document.documentElement.style.setProperty('--navegador-w', _niLargura + 'px');
  if (salvar) try { localStorage.setItem('emily-navegador-largura', String(_niLargura)); } catch (_) {}
}

function abrirPainelNavegador(automatico = false) {
  if (automatico && _niSuprimirAuto) return;
  if (!['chat', 'inicio'].includes(ESTADO.tela)) {
    if (automatico) return;
    irPara(ESTADO.cid ? 'chat' : 'inicio');
  }
  const painel = document.getElementById('navegador-painel');
  const divisor = document.getElementById('navegador-divisor');
  if (!_niLargura) {
    let salva = 0;
    try { salva = Number(localStorage.getItem('emily-navegador-largura')) || 0; } catch (_) {}
    _niAplicarLargura(salva || window.innerWidth * .43);
  } else _niAplicarLargura(_niLargura);
  painel.hidden = false;
  divisor.hidden = false;
  document.body.classList.add('navegador-aberto');
  const botao = document.getElementById('btn-navegador-interno');
  botao.setAttribute('aria-expanded', 'true');
  botao.title = 'Recolher navegador';
  if (!_niMontado) { montarNavegadorInterno(painel); _niMontado = true; }
}

function fecharPainelNavegador(manual = true) {
  if (manual) _niSuprimirAuto = true;
  if (_niLiberarControle) _niLiberarControle();
  document.getElementById('navegador-painel').hidden = true;
  document.getElementById('navegador-divisor').hidden = true;
  document.body.classList.remove('navegador-aberto');
  const botao = document.getElementById('btn-navegador-interno');
  botao.setAttribute('aria-expanded', 'false');
  botao.title = 'Mostrar navegador ao lado do chat';
}

function ligarPainelNavegador() {
  const botao = document.getElementById('btn-navegador-interno');
  botao.onclick = () => {
    if (document.body.classList.contains('navegador-aberto')) fecharPainelNavegador();
    else { _niSuprimirAuto = false; abrirPainelNavegador(); }
  };
  const divisor = document.getElementById('navegador-divisor');
  let arrastando = false;
  divisor.onpointerdown = e => {
    arrastando = true; divisor.setPointerCapture(e.pointerId);
    document.body.classList.add('navegador-redimensionando');
    e.preventDefault();
  };
  divisor.onpointermove = e => {
    if (!arrastando) return;
    _niAplicarLargura(document.getElementById('corpo').getBoundingClientRect().right - e.clientX);
  };
  const terminar = () => {
    if (!arrastando) return;
    arrastando = false; document.body.classList.remove('navegador-redimensionando');
    _niAplicarLargura(_niLargura, true);
  };
  divisor.onpointerup = terminar;
  divisor.onpointercancel = terminar;
  window.addEventListener('resize', () => {
    if (_niLargura && document.body.classList.contains('navegador-aberto')) _niAplicarLargura(_niLargura);
  });
}

function montarNavegadorInterno(palco) {
  palco.innerHTML = `
    <section class="ni" aria-label="Navegador da Emily">
      <header class="ni-topo">
        <span class="ni-marca" aria-label="Navegador da Emily">E</span>
        <div class="ni-abas" id="ni-abas" aria-label="Abas do navegador da Emily"></div>
        <button class="ni-fechar" id="ni-fechar" type="button" title="Recolher navegador" aria-label="Recolher navegador">×</button>
      </header>
      <div class="ni-barra">
        <button type="button" id="ni-voltar" title="Voltar" aria-label="Voltar">←</button>
        <button type="button" id="ni-avancar" title="Avançar" aria-label="Avançar">→</button>
        <button type="button" id="ni-recarregar" title="Recarregar" aria-label="Recarregar">↻</button>
        <form id="ni-form" autocomplete="off"><span class="ni-url-icone" aria-hidden="true">⌕</span>
          <input id="ni-url" aria-label="Endereço ou busca" placeholder="Pesquisar ou inserir endereço" spellcheck="false">
        </form>
        <button type="button" id="ni-ir" title="Ir para o endereço" aria-label="Ir para o endereço">↵</button>
      </div>
      <div class="ni-informacao"><span id="ni-titulo">Página em branco</span><span class="ni-estado" id="ni-estado">Iniciando…</span></div>
      <div class="ni-palco"><div class="ni-viewport" id="ni-viewport" tabindex="0" aria-label="Página do navegador interno. Clique e digite para interagir.">
        <img id="ni-imagem" alt="Página atual do navegador da Emily" draggable="false">
        <span class="ni-cursor" id="ni-cursor" aria-hidden="true" hidden><svg viewBox="0 0 24 24"><path d="M2 2v18l5-4 4 6 3-2-4-6 7-1z"/></svg><i>E</i></span>
        <div class="ni-carregando" id="ni-carregando">Preparando navegador…</div>
        <div class="ni-vazio" id="ni-vazio" hidden><span class="ni-vazio-marca">E</span><strong>Um espaço só nosso para explorar</strong><p>Pesquise, abra um endereço ou peça para eu investigar um site por aqui.</p></div>
      </div></div>
      <footer class="ni-rodape"><span>O cursor E é da Emily. Clique na página para assumir o controle; clique fora para ela continuar.</span><span id="ni-download" hidden></span></footer>
    </section>`;
  const $ni = sel => palco.querySelector(sel);
  const viewport = $ni('#ni-viewport');
  const imagem = $ni('#ni-imagem');
  const cursor = $ni('#ni-cursor');
  const url = $ni('#ni-url');
  $ni('#ni-fechar').onclick = () => fecharPainelNavegador();
  let ativo = true, consultando = false, movendo = false, ultimoMove = 0, botaoPressionado = null;
  let controleUsuario = false, ultimoCliqueEmily = 0;
  let filaEntrada = Promise.resolve();
  let ultimoPonto = {x: 0, y: 0};
  let larguraRemota = 1280, alturaRemota = 800;
  let ultimaUrl = '', tocouUrl = false;
  const existe = () => ativo && viewport.isConnected;
  const visivel = () => existe() && !palco.hidden;
  const enviarEntrada = (nome, dados = {}) => {
    const proxima = filaEntrada.catch(() => {}).then(() =>
      api('navegador_interno_acao', nome, dados, {__teto: 30000}));
    filaEntrada = proxima;
    return proxima;
  };
  const controlar = ligado => {
    if (controleUsuario === ligado) return;
    controleUsuario = ligado;
    enviarEntrada('usuario_ativo', {ativo: ligado}).catch(() => {});
  };
  _niLiberarControle = () => controlar(false);
  const liberarSeSaiu = () => {
    if (!palco.contains(document.activeElement)) controlar(false);
  };
  palco.addEventListener('focusin', () => controlar(true));
  palco.addEventListener('focusout', () => setTimeout(liberarSeSaiu, 0));
  palco.addEventListener('pointerdown', () => controlar(true));
  palco.addEventListener('pointerleave', liberarSeSaiu);
  const status = (mensagem, erro = false) => {
    if (!existe()) return;
    $ni('#ni-estado').textContent = mensagem;
    $ni('#ni-estado').classList.toggle('erro', erro);
  };
  const renderAbas = abas => {
    const barra = $ni('#ni-abas');
    if (!barra) return;
    barra.replaceChildren();
    for (const aba of abas || []) {
      const item = document.createElement('div');
      item.className = 'ni-aba' + (aba.ativa ? ' ativa' : '');
      const abrir = document.createElement('button');
      abrir.type = 'button'; abrir.className = 'ni-aba-abrir';
      const icone = document.createElement('span');
      icone.className = 'ni-aba-icone';
      icone.setAttribute('aria-hidden', 'true');
      icone.textContent = aba.url && aba.url !== 'about:blank' ? '◉' : '○';
      const titulo = document.createElement('span');
      titulo.className = 'ni-aba-titulo';
      titulo.textContent = aba.titulo || 'Nova aba';
      abrir.append(icone, titulo);
      abrir.title = aba.url || 'Nova aba';
      abrir.onclick = () => acao('trocar_aba', {indice: aba.indice});
      const fechar = document.createElement('button');
      fechar.type = 'button'; fechar.className = 'ni-aba-fechar';
      fechar.textContent = '×'; fechar.title = 'Fechar aba';
      fechar.setAttribute('aria-label', 'Fechar ' + (aba.titulo || 'aba'));
      fechar.onclick = () => acao('fechar_aba', {indice: aba.indice});
      item.append(abrir, fechar); barra.appendChild(item);
    }
    const nova = document.createElement('button');
    nova.type = 'button'; nova.className = 'ni-aba-nova';
    nova.textContent = '+'; nova.title = 'Nova aba'; nova.setAttribute('aria-label', 'Nova aba');
    nova.onclick = () => acao('nova_aba');
    barra.appendChild(nova);
  };
  const atualizar = async () => {
    if (!visivel() || consultando) return;
    consultando = true;
    try {
      const r = await api('navegador_interno_acao', 'estado', {}, {__teto: 20000});
      if (!existe()) return;
      if (!r.ok) throw new Error(r.erro || 'Não consegui abrir o navegador.');
      larguraRemota = r.largura || larguraRemota;
      alturaRemota = r.altura || alturaRemota;
      if (r.cursor_emily) {
        const caixa = viewport.getBoundingClientRect();
        const escala = Math.min(caixa.width / larguraRemota, caixa.height / alturaRemota);
        const inicioX = (caixa.width - larguraRemota * escala) / 2;
        const inicioY = (caixa.height - alturaRemota * escala) / 2;
        cursor.hidden = false;
        cursor.style.left = (inicioX + r.cursor_emily.x * escala) + 'px';
        cursor.style.top = (inicioY + r.cursor_emily.y * escala) + 'px';
        if (r.sequencia_clique !== ultimoCliqueEmily) {
          ultimoCliqueEmily = r.sequencia_clique;
          cursor.classList.remove('clicou'); void cursor.offsetWidth; cursor.classList.add('clicou');
        }
      } else cursor.hidden = true;
      if (r.imagem) {
        imagem.src = 'data:image/jpeg;base64,' + r.imagem;
        $ni('#ni-carregando').hidden = true;
      }
      $ni('#ni-titulo').textContent = r.titulo || 'Página em branco';
      renderAbas(r.abas);
      if (r.ultimo_download) {
        const aviso = $ni('#ni-download');
        aviso.hidden = false;
        aviso.textContent = r.ultimo_download.startsWith('Falha') ? r.ultimo_download
          : 'Download salvo em ' + r.ultimo_download;
      }
      $ni('#ni-vazio').hidden = r.url !== 'about:blank';
      if (!tocouUrl && ultimaUrl !== r.url) { url.value = r.url === 'about:blank' ? '' : r.url; ultimaUrl = r.url; }
      status(r.usuario_ativo ? 'Emily pausada enquanto você usa a página' : 'Pronto');
    } catch (e) { status(e.message, true); }
    finally { consultando = false; }
  };
  const acao = async (nome, dados = {}) => {
    if (['trocar_aba', 'nova_aba', 'fechar_aba', 'voltar', 'avancar', 'recarregar'].includes(nome)) tocouUrl = false;
    status('Navegando…');
    try {
      const r = await enviarEntrada(nome, dados);
      if (!r.ok) throw new Error(r.erro || 'Ação não concluída.');
      await atualizar();
    } catch (e) { status(e.message, true); }
  };
  const ir = () => { tocouUrl = false; acao('abrir', {url: url.value}); };
  $ni('#ni-form').onsubmit = e => { e.preventDefault(); ir(); };
  $ni('#ni-ir').onclick = ir;
  url.oninput = () => { tocouUrl = true; };
  for (const nome of ['voltar', 'avancar', 'recarregar']) $ni('#ni-' + nome).onclick = () => acao(nome);
  const ponto = evento => {
    const caixa = viewport.getBoundingClientRect();
    const escala = Math.min(caixa.width / larguraRemota, caixa.height / alturaRemota);
    const largura = larguraRemota * escala, altura = alturaRemota * escala;
    const inicioX = caixa.left + (caixa.width - largura) / 2;
    const inicioY = caixa.top + (caixa.height - altura) / 2;
    const x = (evento.clientX - inicioX) / escala;
    const y = (evento.clientY - inicioY) / escala;
    if (x < 0 || y < 0 || x >= larguraRemota || y >= alturaRemota) return null;
    return {x: Math.round(x), y: Math.round(y)};
  };
  viewport.onpointermove = e => {
    const p = ponto(e);
    if (!p || !controleUsuario) return;
    ultimoPonto = p;
    if (Date.now() - ultimoMove < (botaoPressionado ? 35 : 110) || movendo) return;
    ultimoMove = Date.now(); movendo = true;
    enviarEntrada('mover', p).catch(() => {}).finally(() => { movendo = false; });
  };
  viewport.onpointerleave = liberarSeSaiu;
  viewport.onpointerdown = e => {
    const p = ponto(e);
    if (!p) return;
    ultimoPonto = p;
    e.preventDefault(); viewport.focus();
    botaoPressionado = e.button === 2 ? 'right' : e.button === 1 ? 'middle' : 'left';
    viewport.setPointerCapture(e.pointerId);
    enviarEntrada('pressionar', {...p, botao: botaoPressionado}).catch(e => status(e.message, true));
  };
  viewport.onpointerup = e => {
    if (!botaoPressionado) return;
    const p = ponto(e) || ultimoPonto;
    const botao = botaoPressionado;
    botaoPressionado = null;
    acao('soltar', {...p, botao});
  };
  viewport.onpointercancel = e => {
    if (!botaoPressionado) return;
    const p = ponto(e) || ultimoPonto;
    enviarEntrada('soltar', {...p, botao: botaoPressionado}).catch(() => {});
    botaoPressionado = null;
  };
  viewport.oncontextmenu = e => e.preventDefault();
  viewport.addEventListener('wheel', e => {
    e.preventDefault();
    controlar(true); viewport.focus();
    acao('rolar', {dx: Math.round(e.deltaX), dy: Math.round(e.deltaY)});
  }, {passive: false});
  viewport.onkeydown = e => {
    e.preventDefault();
    controlar(true);
    if (e.key === 'Dead') return;
    const modificadores = [e.ctrlKey && 'Control', e.altKey && 'Alt', e.metaKey && 'Meta', e.shiftKey && 'Shift'].filter(Boolean);
    if (e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
      enviarEntrada('texto', {valor: e.key}).catch(err => status(err.message, true));
    } else {
      const especiais = { ' ': 'Space', Esc: 'Escape', Del: 'Delete', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown', ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight' };
      const tecla = especiais[e.key] || e.key;
      if (!['Control', 'Alt', 'Meta', 'Shift'].includes(tecla))
        enviarEntrada('tecla', {valor: [...modificadores, tecla].join('+')}).catch(err => status(err.message, true));
    }
  };
  viewport.onpaste = e => {
    e.preventDefault();
    controlar(true);
    const texto = e.clipboardData?.getData('text/plain');
    if (texto) enviarEntrada('texto', {valor: texto}).catch(err => status(err.message, true));
  };
  // O viewport virtual fica estável em 1280x800. Redimensionar o painel só
  // escala a imagem: a Emily não perde as coordenadas entre VER e CLICAR.
  atualizar();
  const timer = setInterval(() => { if (!existe()) { ativo = false; clearInterval(timer); } else if (visivel()) atualizar(); }, 600);
}
