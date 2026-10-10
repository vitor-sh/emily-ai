/* ════════════════════════════════════════════════════════════════
   ARQUIVO DA EMILY — biblioteca local-first com sincronização opcional.
   Este arquivo só desenha. Toda operação real acontece no Python por ID.
   ════════════════════════════════════════════════════════════════ */

const CLOUD = {
  parent: '', filtro: 'arquivos', busca: '', modo: 'grade',
  itens: [], breadcrumb: [], status: {}, selecionado: '', carregando: false,
  assinaturaItens: '', migrando: false, selecionados: new Set(), arrastando: [],
};
let _cloudAoVivoTimer = null;

const CLOUD_FILTROS = [
  ['arquivos', 'Meus arquivos', 'pasta'], ['recentes', 'Recentes', 'relogio'],
  ['favoritos', 'Favoritos', 'coracao'], ['imagens', 'Imagens', 'imagem'],
  ['videos', 'Vídeos', 'video'], ['audios', 'Áudios', 'musica'],
  ['documentos', 'Documentos', 'documento'], ['compactados', 'Compactados', 'arquivo'],
  ['lixeira', 'Lixeira', 'lixo'],
];

function _cloudIco(nome) {
  const extras = {
    arquivo: '<path d="M6 2.5h8l4 4V21H6z"/><path d="M14 2.5V7h4"/>',
    documento: '<path d="M6 2.5h8l4 4V21H6z"/><path d="M14 2.5V7h4M9 11h6M9 15h6"/>',
    imagem: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M4 17l5-4 3 2 3-3 5 5"/>',
    video: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/>',
    alerta: '<path d="M12 3l10 18H2L12 3z"/><path d="M12 9v5M12 17h.01"/>',
    coracao: '<path d="M12 21s-7-4.4-9.4-8.2C.8 10 1.8 6.4 4.9 5.2A5 5 0 0112 7.1a5 5 0 017.1-1.9c3.1 1.2 4.1 4.8 2.3 7.6C19 16.6 12 21 12 21z"/>',
    relogio: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
    grade: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    lista: '<path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
    nuvem: '<path d="M7.5 18.5h10a4 4 0 00.7-7.94A6.5 6.5 0 005.7 8.7 4.8 4.8 0 007.5 18.5z"/>',
    baixar: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
    abrir: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 13v6H5V6h6"/>',
  };
  return extras[nome] || ICO[nome] || extras.arquivo;
}

function telaCloud() {
  const sec = document.createElement('section');
  sec.className = 'tela cloud';
  sec.innerHTML = `
    <div class="cloud-ambiente" aria-hidden="true"><i></i><i></i><i></i></div>
    <header class="cloud-topo">
      <div class="cloud-marca">
        <span class="cloud-selo">${svg(_cloudIco('nuvem'))}<i></i></span>
        <div><small>SUA NUVEM PESSOAL</small><h1>Arquivo da Emily</h1></div>
      </div>
      <div class="cloud-topo-acoes">
        <button class="cloud-btn secundario" id="cloud-storage" title="Escolher outro disco ou pasta">${svg(ICO.disco || _cloudIco('arquivo'))}<span>Armazenamento</span></button>
        <button class="cloud-btn secundario" id="cloud-nova-pasta">${svg(ICO.pasta)}<span>Nova pasta</span></button>
        <button class="cloud-btn principal" id="cloud-upload">${svg(ICO.clipe)}<span>Guardar</span></button>
      </div>
    </header>
    <div class="cloud-shell">
      <aside class="cloud-nav">
        <nav>${CLOUD_FILTROS.map(([id, rot, ico]) => `
          <button data-cloud-filtro="${id}" class="${id === CLOUD.filtro ? 'ativo' : ''}">
            ${svg(_cloudIco(ico))}<span>${rot}</span><i data-conta="${id}"></i>
          </button>`).join('')}</nav>
        <div class="cloud-espaco">
          <div class="cloud-espaco-topo"><span>Armazenamento</span><strong id="cloud-uso">—</strong></div>
          <div class="cloud-espaco-bar"><i id="cloud-uso-bar"></i></div>
          <small id="cloud-livre">Calculando espaço…</small>
          <button class="cloud-local" id="cloud-local" title="Trocar disco ou pasta"><span id="cloud-local-nome">Local atual</span><small id="cloud-local-caminho">—</small></button>
          <div class="cloud-sync" id="cloud-sync"><i></i><span>Somente neste computador</span></div>
        </div>
      </aside>
      <main class="cloud-main">
        <div class="cloud-toolbar">
          <div class="cloud-breadcrumb" id="cloud-breadcrumb"></div>
          <label class="cloud-busca">${svg(ICO.lupa)}<input id="cloud-busca" placeholder="Buscar no seu arquivo" value="${esc(CLOUD.busca)}"><button id="cloud-busca-x" hidden>${svg(ICO.x)}</button></label>
          <div class="cloud-view">
            <button id="cloud-grade" class="${CLOUD.modo === 'grade' ? 'ativo' : ''}" title="Grade">${svg(_cloudIco('grade'))}</button>
            <button id="cloud-lista" class="${CLOUD.modo === 'lista' ? 'ativo' : ''}" title="Lista">${svg(_cloudIco('lista'))}</button>
          </div>
        </div>
        <div class="cloud-contexto"><div><h2 id="cloud-titulo">Meus arquivos</h2><p id="cloud-resumo">Carregando sua biblioteca…</p></div><button id="cloud-atualizar" title="Atualizar">${svg(ICO.refazer)}</button></div>
        <div class="cloud-conteudo" id="cloud-conteudo"><div class="cloud-loading"><i></i><span>Abrindo o arquivo…</span></div></div>
      </main>
      <aside class="cloud-detalhes" id="cloud-detalhes" hidden></aside>
    </div>
    <div class="cloud-drop" id="cloud-drop" hidden>${svg(ICO.clipe)}<strong>Solte para guardar</strong><span>Os originais continuam onde estão</span></div>
    <div class="cloud-migracao" id="cloud-migracao" hidden><i></i><strong>Mudando o armazenamento…</strong><span>Copiando e verificando o catálogo. Não desligue o PC.</span></div>
    <div class="cloud-viewer" id="cloud-viewer" hidden>
      <div class="cloud-viewer-caixa" role="dialog" aria-modal="true">
        <header><button data-cv="fechar" title="Voltar">${svg(ICO.seta)}</button><div><h2></h2><p></p></div>
          <button data-cv="externo" title="Abrir no aplicativo do sistema">${svg(_cloudIco('abrir'))}<span>Abrir no sistema</span></button>
          <button data-cv="exportar" title="Exportar">${svg(_cloudIco('baixar'))}</button></header>
        <main class="cloud-viewer-corpo"></main>
      </div>
    </div>`;
  return sec;
}

async function montarCloud() {
  const titulo = CLOUD_FILTROS.find(f => f[0] === CLOUD.filtro)?.[1] || 'Meus arquivos';
  $('#cloud-titulo').textContent = titulo;
  $('#cloud-upload').onclick = cloudImportar;
  $('#cloud-storage').onclick = cloudTrocarArmazenamento;
  $('#cloud-local').onclick = cloudTrocarArmazenamento;
  $('#cloud-nova-pasta').onclick = cloudNovaPasta;
  $('#cloud-atualizar').onclick = () => cloudCarregar(false, true);
  $('#cloud-grade').onclick = () => { CLOUD.modo = 'grade'; cloudDesenhar(); };
  $('#cloud-lista').onclick = () => { CLOUD.modo = 'lista'; cloudDesenhar(); };
  $$('[data-cloud-filtro]').forEach(b => b.onclick = () => {
    CLOUD.filtro = b.dataset.cloudFiltro; CLOUD.parent = ''; CLOUD.busca = '';
    CLOUD.selecionado = ''; cloudCarregar();
  });
  const busca = $('#cloud-busca');
  let timer;
  busca.oninput = () => {
    clearTimeout(timer); CLOUD.busca = busca.value.trim();
    $('#cloud-busca-x').hidden = !CLOUD.busca;
    timer = setTimeout(cloudCarregar, 240);
  };
  busca.onkeydown = e => { if (e.key === 'Enter') cloudCarregar(); };
  $('#cloud-busca-x').onclick = () => { busca.value = ''; CLOUD.busca = ''; cloudCarregar(); };
  cloudLigarDrop();
  await cloudCarregar();
  // PC e celular operam o MESMO SQLite. Enquanto esta tela estiver aberta,
  // uma alteração vinda do celular aparece aqui em até 4s sem o Vitor clicar
  // em Atualizar. Ao sair da aba, o próprio timer vê que o DOM sumiu e morre.
  clearInterval(_cloudAoVivoTimer);
  _cloudAoVivoTimer = setInterval(() => {
    if (!$('#cloud-conteudo')) {
      clearInterval(_cloudAoVivoTimer); _cloudAoVivoTimer = null; return;
    }
    if (!document.hidden && !CLOUD.carregando && !CLOUD.migrando) cloudCarregar(true);
  }, 4000);
}

function cloudAssinatura(itens, breadcrumb) {
  return JSON.stringify({
    itens: (itens || []).map(i => [i.id,i.parent_id,i.nome,i.tipo,i.mime,i.tamanho,i.favorito,
      i.estado_sync,i.alterado_em,i.apagado_em,i.tem_preview,i.preview_url]),
    breadcrumb: (breadcrumb || []).map(p => [p.id,p.nome]),
  });
}

async function cloudCarregar(silencioso = false, forcar = false) {
  if (!$('#cloud-conteudo') || CLOUD.carregando || CLOUD.migrando) return;
  CLOUD.carregando = true;
  if (!silencioso) $('#cloud-conteudo').classList.add('carregando');
  const r = await tenta('cloud_listar', CLOUD.parent, CLOUD.filtro, CLOUD.busca, { __teto: 30000 });
  CLOUD.carregando = false;
  if (!$('#cloud-conteudo')) return;
  if (!silencioso) $('#cloud-conteudo').classList.remove('carregando');
  if (!r || r.ok === false) {
    // Polling ao vivo é best-effort: uma oscilação de rede/gateway não deve
    // apagar a grade atual nem causar uma piscada de erro a cada 4 segundos.
    if (silencioso) return;
    $('#cloud-conteudo').innerHTML = `<div class="cloud-vazio erro">${svg(ICO.info)}<strong>Não consegui abrir seu arquivo</strong><span>${esc(r?.erro || 'A ponte com a Emily não respondeu.')}</span></div>`;
    return;
  }
  const itens = r.itens || []; const breadcrumb = r.breadcrumb || [];
  const assinatura = cloudAssinatura(itens, breadcrumb);
  const mudou = forcar || assinatura !== CLOUD.assinaturaItens;
  CLOUD.itens = itens; CLOUD.breadcrumb = breadcrumb; CLOUD.status = r.status || {};
  CLOUD.assinaturaItens = assinatura;
  if (mudou) cloudDesenhar();
  cloudPintarStatus();
}

function cloudPintarStatus() {
  const s = CLOUD.status || {};
  $('#cloud-uso').textContent = s.uso_legivel || '0 B';
  $('#cloud-livre').textContent = `${s.livre_legivel || '—'} livres · ${s.arquivos || 0} arquivo${s.arquivos === 1 ? '' : 's'}`;
  const caminho = String(s.pasta || '');
  const partes = caminho.replace(/\\/g, '/').split('/').filter(Boolean);
  $('#cloud-local-nome').textContent = partes.at(-1) || 'Emily Cloud';
  $('#cloud-local-caminho').textContent = caminho || 'Local não informado';
  $('#cloud-local').title = caminho ? `Armazenamento atual: ${caminho}\nClique para trocar` : 'Trocar armazenamento';
  const total = Number(s.bytes_fisicos || 0) + Number(s.bytes_livres || 0);
  $('#cloud-uso-bar').style.width = `${total ? Math.max(1, Math.min(100, s.bytes_fisicos * 100 / total)) : 1}%`;
  const sync = $('#cloud-sync');
  sync.classList.toggle('ativo', !!s.s3_ativo);
  $('span', sync).textContent = s.s3_ativo ? `${s.sincronizados || 0} sincronizado(s)` : 'Somente neste computador';
  const dot = $('.cloud-dot'); if (dot) dot.classList.toggle('online', !!s.s3_ativo);
}

async function cloudTrocarArmazenamento() {
  if (CLOUD.migrando) return;
  const plano = await tenta('cloud_escolher_armazenamento', { __teto: 120000 });
  if (!plano || plano.cancelado) return;
  if (!plano.ok) { toast(plano.erro || 'Não consegui usar essa pasta', 'erro'); return; }
  const novoSemOrigem = plano.modo === 'novo' || plano.origem_disponivel === false;
  const confirmar = await modal({
    titulo: novoSemOrigem ? 'Usar um novo armazenamento vazio?' : 'Mover a Emily Cloud?',
    texto: novoSemOrigem
      ? `O armazenamento anterior não está disponível:\n${plano.origem}\n\nA Emily Cloud será iniciada vazia em:\n${plano.destino}\n\nNenhum arquivo será copiado ou apagado do disco desconectado. Se ele for conectado depois, os dados antigos continuarão nele.`
      : `Destino: ${plano.destino}\n\nSerão copiados ${cloudBytes(plano.bytes_migrar)}. O disco possui ${cloudBytes(plano.bytes_livres)} livres. Durante a migração, uploads ficam pausados e o gateway reinicia automaticamente.`,
    ok: novoSemOrigem ? 'Usar novo local' : 'Mover armazenamento',
  });
  if (!confirmar) return;
  CLOUD.migrando = true;
  $('#cloud-migracao').hidden = false;
  const r = await tenta('cloud_migrar_armazenamento', plano.destino, novoSemOrigem,
    { __teto: 24 * 60 * 60 * 1000 });
  CLOUD.migrando = false;
  $('#cloud-migracao').hidden = true;
  if (!r?.ok) { toast(r?.erro || 'A migração falhou; o local anterior foi mantido.', 'erro'); return; }
  CLOUD.assinaturaItens = '';
  toast(r.aviso || `Armazenamento movido para ${r.destino}`);
  await cloudCarregar(false, true);
}

function cloudBreadcrumb() {
  const el = $('#cloud-breadcrumb'); if (!el) return;
  el.innerHTML = `<button data-cloud-pasta="">Arquivo</button>` + CLOUD.breadcrumb.map((p, i) =>
    `<span>${svg(ICO.seta)}</span><button data-cloud-pasta="${p.id}" class="${i === CLOUD.breadcrumb.length - 1 ? 'atual' : ''}">${esc(p.nome)}</button>`
  ).join('');
  $$('[data-cloud-pasta]', el).forEach(b => b.onclick = () => {
    CLOUD.parent = b.dataset.cloudPasta || ''; CLOUD.filtro = 'arquivos'; CLOUD.busca = ''; cloudCarregar();
  });
}

function cloudDesenhar() {
  if (!$('#cloud-conteudo')) return;
  cloudBreadcrumb();
  $$('[data-cloud-filtro]').forEach(b => b.classList.toggle('ativo', b.dataset.cloudFiltro === CLOUD.filtro));
  $('#cloud-grade').classList.toggle('ativo', CLOUD.modo === 'grade');
  $('#cloud-lista').classList.toggle('ativo', CLOUD.modo === 'lista');
  const titulo = CLOUD.parent && CLOUD.breadcrumb.length ? CLOUD.breadcrumb.at(-1).nome
    : (CLOUD_FILTROS.find(f => f[0] === CLOUD.filtro)?.[1] || 'Resultados');
  $('#cloud-titulo').textContent = titulo;
  $('#cloud-resumo').textContent = CLOUD.busca
    ? `${CLOUD.itens.length} resultado(s) para “${CLOUD.busca}”`
    : `${CLOUD.itens.length} item${CLOUD.itens.length === 1 ? '' : 's'} · tudo disponível offline`;
  if (!CLOUD.itens.length) {
    $('#cloud-conteudo').innerHTML = `<div class="cloud-vazio">${svg(_cloudIco(CLOUD.filtro === 'lixeira' ? 'lixo' : 'nuvem'))}<strong>${CLOUD.busca ? 'Nada com esse nome' : CLOUD.filtro === 'lixeira' ? 'A lixeira está vazia' : 'Seu arquivo começa aqui'}</strong><span>${CLOUD.busca ? 'Tente outro termo.' : 'Guarde arquivos, vídeos, músicas, mods ou pastas inteiras.'}</span>${CLOUD.busca || CLOUD.filtro === 'lixeira' ? '' : '<button id="cloud-vazio-upload">Guardar primeiro arquivo</button>'}</div>`;
    $('#cloud-vazio-upload')?.addEventListener('click', cloudImportar);
    return;
  }
  $('#cloud-conteudo').className = `cloud-conteudo modo-${CLOUD.modo}`;
  $('#cloud-conteudo').innerHTML = CLOUD.itens.map(cloudCard).join('');
  $$('[data-cloud-id]', $('#cloud-conteudo')).forEach(el => {
    const id = el.dataset.cloudId;
    el.draggable = CLOUD.filtro === 'arquivos';
    el.onclick = e => {
      if (e.target.closest('button')) return;
      if (e.ctrlKey || e.metaKey) {
        CLOUD.selecionados.has(id) ? CLOUD.selecionados.delete(id) : CLOUD.selecionados.add(id);
        cloudPintarSelecao();
      } else cloudSelecionar(id);
    };
    el.ondblclick = e => { if (!e.target.closest('button')) cloudAbrir(id); };
    el.ondragstart = e => {
      if (!CLOUD.selecionados.has(id)) { CLOUD.selecionados.clear(); CLOUD.selecionados.add(id); }
      CLOUD.arrastando = [...CLOUD.selecionados];
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('application/x-emily-cloud-items', JSON.stringify(CLOUD.arrastando));
      cloudPintarSelecao();
    };
    if (CLOUD.itens.find(i => i.id === id)?.tipo === 'pasta') {
      el.ondragover = e => { if (CLOUD.arrastando.length) { e.preventDefault(); el.classList.add('cloud-drop-alvo'); } };
      el.ondragleave = () => el.classList.remove('cloud-drop-alvo');
      el.ondrop = async e => {
        if (!CLOUD.arrastando.length) return;
        e.preventDefault(); e.stopPropagation(); el.classList.remove('cloud-drop-alvo');
        const ids = CLOUD.arrastando.filter(x => x !== id);
        const r = await tenta('cloud_mover_varios', ids, id);
        CLOUD.arrastando = []; CLOUD.selecionados.clear();
        if (r?.ok || r?.parcial) { toast(`${r.itens.length} item(ns) movido(s)`); cloudCarregar(); }
        else toast(r?.erro || r?.erros?.[0]?.erro || 'Não consegui mover', 'erro');
      };
    }
    $('[data-acao="fav"]', el).onclick = e => { e.stopPropagation(); cloudFavoritar(id); };
    $('[data-acao="menu"]', el).onclick = e => { e.stopPropagation(); cloudMenu(e.currentTarget, id); };
  });
}

function cloudCard(i) {
  const preview = i.preview_url ? `<img src="${i.preview_url}" alt="">` : svg(_cloudIco(i.icone), 'cloud-item-ico');
  const data = new Date((i.alterado_em || i.criado_em || 0) * 1000).toLocaleDateString('pt-BR');
  const sync = i.estado_sync === 'sincronizado' ? 'Na nuvem' : i.estado_sync === 'erro' ? 'Erro no sync' : 'Neste PC';
  return `<article class="cloud-item tipo-${esc(i.categoria)} ${i.id === CLOUD.selecionado || CLOUD.selecionados.has(i.id) ? 'selecionado' : ''}" data-cloud-id="${i.id}">
    <div class="cloud-thumb">${preview}<span class="cloud-tipo">${esc(i.extensao?.replace('.', '') || i.categoria)}</span></div>
    <div class="cloud-item-info"><strong title="${esc(i.nome)}">${esc(i.nome)}</strong><small>${i.tipo === 'pasta' ? 'Pasta' : i.tamanho_legivel} · ${data}</small><span><i class="${i.estado_sync}"></i>${sync}</span></div>
    <div class="cloud-item-acoes"><button data-acao="fav" class="${i.favorito ? 'ativo' : ''}" title="Favoritar">${svg(_cloudIco('coracao'))}</button><button data-acao="menu" title="Mais ações"><svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg></button></div>
  </article>`;
}

function cloudPintarSelecao() {
  $$('[data-cloud-id]', $('#cloud-conteudo')).forEach(el =>
    el.classList.toggle('selecionado', CLOUD.selecionados.has(el.dataset.cloudId)));
  const resumo = $('#cloud-resumo');
  if (resumo && CLOUD.selecionados.size) resumo.textContent = `${CLOUD.selecionados.size} selecionado(s) · arraste para uma pasta`;
}

async function cloudSelecionar(id) {
  CLOUD.selecionado = id;
  $$('[data-cloud-id]', $('#cloud-conteudo')).forEach(el =>
    el.classList.toggle('selecionado', el.dataset.cloudId === id));
  const painel = $('#cloud-detalhes'); painel.hidden = false;
  painel.innerHTML = '<div class="cloud-detalhe-loading"><i></i></div>';
  const r = await tenta('cloud_detalhes', id);
  if (!r?.ok || !$('#cloud-detalhes')) { painel.hidden = true; return; }
  const i = r.item;
  const visual = i.preview_url ? `<img src="${i.preview_url}" alt="">` : `<div class="cloud-detalhe-icone">${svg(_cloudIco(i.icone))}</div>`;
  painel.innerHTML = `<button class="cloud-detalhe-fechar">${svg(ICO.x)}</button>
    <div class="cloud-detalhe-preview">${visual}</div><h3>${esc(i.nome)}</h3><p>${esc(i.categoria)} · ${i.tamanho_legivel}</p>
    <div class="cloud-meta"><span><small>Local</small>${esc(i.pasta_nome || 'Meus arquivos')}</span><span><small>Origem</small>${esc(i.origem || 'manual')}</span><span><small>Sincronização</small>${esc(i.estado_sync || 'local')}</span><span><small>Versões</small>${i.versoes?.length || 0}</span></div>
    <div class="cloud-detalhe-acoes"><button data-d="abrir">${svg(_cloudIco('abrir'))}<span>Abrir</span></button><button data-d="anexar">${svg(ICO.clipe)}<span>Anexar</span></button><button data-d="exportar">${svg(_cloudIco('baixar'))}<span>Exportar</span></button><button data-d="mais">${svg(ICO.raio)}<span>Ações</span></button></div>`;
  $('.cloud-detalhe-fechar', painel).onclick = () => {
    painel.hidden = true; CLOUD.selecionado = '';
    $$('[data-cloud-id]', $('#cloud-conteudo')).forEach(el => el.classList.remove('selecionado'));
  };
  $('[data-d="abrir"]', painel).onclick = () => cloudAbrir(id);
  $('[data-d="anexar"]', painel).onclick = () => cloudAnexar(id);
  $('[data-d="exportar"]', painel).onclick = () => cloudExportar(id);
  $('[data-d="mais"]', painel).onclick = e => cloudMenu(e.currentTarget, id);
}

async function cloudAbrir(id) {
  const item = CLOUD.itens.find(i => i.id === id);
  if (item?.tipo === 'pasta') { CLOUD.parent = id; CLOUD.filtro = 'arquivos'; CLOUD.busca = ''; CLOUD.selecionado = ''; cloudCarregar(); return; }
  const r = await tenta('cloud_visualizar', id);
  if (!r?.ok) { toast(r?.erro || 'Não consegui abrir', 'erro'); return; }
  await cloudViewerMostrar(r.item, r.url);
}

function cloudViewerFechar() {
  const viewer = $('#cloud-viewer'); if (!viewer) return;
  const corpo = $('.cloud-viewer-corpo', viewer);
  corpo?.querySelectorAll('video,audio').forEach(m => { try { m.pause(); m.removeAttribute('src'); m.load(); } catch (_) {} });
  viewer.hidden = true; if (corpo) corpo.innerHTML = '';
}

function cloudBytes(n) {
  let v = Number(n || 0); const unidades = ['B', 'KB', 'MB', 'GB'];
  for (const u of unidades) { if (v < 1024 || u === 'GB') return u === 'B' ? `${Math.round(v)} B` : `${v.toFixed(1)} ${u}`; v /= 1024; }
}

function cloudEhTexto(i) {
  return String(i.mime || '').startsWith('text/') || ['.txt','.md','.json','.xml','.yaml','.yml','.csv','.log','.ini','.cfg','.toml','.py','.js','.ts','.css','.html','.kt','.java','.c','.cpp','.h','.sql'].includes(String(i.extensao || '').toLowerCase());
}

async function cloudViewerMostrar(item, url) {
  const viewer = $('#cloud-viewer'); const corpo = $('.cloud-viewer-corpo', viewer);
  viewer.hidden = false; $('h2', viewer).textContent = item.nome;
  $('header p', viewer).textContent = `${item.tamanho_legivel || cloudBytes(item.tamanho)} · ${item.mime || item.categoria || 'arquivo'}`;
  $('[data-cv="fechar"]', viewer).onclick = cloudViewerFechar;
  $('[data-cv="externo"]', viewer).onclick = async () => { const r = await tenta('cloud_abrir', item.id); if (!r?.ok) toast(r?.erro || 'Não consegui abrir no sistema', 'erro'); };
  $('[data-cv="exportar"]', viewer).onclick = () => cloudExportar(item.id);
  viewer.onclick = e => { if (e.target === viewer) cloudViewerFechar(); };
  corpo.innerHTML = '<div class="cloud-viewer-loading"><i></i><span>Preparando visualização…</span></div>';

  const mime = String(item.mime || ''); const ext = String(item.extensao || '').toLowerCase();
  if (mime.startsWith('image/')) {
    corpo.innerHTML = `<div class="cloud-viewer-imagem"><img alt=""></div><p class="cloud-viewer-dica">Use a roda do mouse para ampliar</p>`;
    const img = $('img', corpo); img.src = url; let escala = 1;
    corpo.onwheel = e => { e.preventDefault(); escala = Math.max(1, Math.min(6, escala * (e.deltaY < 0 ? 1.15 : .87))); img.style.transform = `scale(${escala})`; };
  } else if (mime.startsWith('video/')) {
    corpo.innerHTML = '<video class="cloud-viewer-video" controls autoplay playsinline></video>';
    $('video', corpo).src = url;
  } else if (mime.startsWith('audio/')) {
    corpo.innerHTML = `<div class="cloud-viewer-audio">${svg(_cloudIco('musica'))}<strong>${esc(item.nome)}</strong><audio controls autoplay></audio></div>`;
    $('audio', corpo).src = url;
  } else if (mime === 'application/pdf' || ext === '.pdf') {
    corpo.innerHTML = '<iframe class="cloud-viewer-pdf" title="PDF"></iframe>';
    $('iframe', corpo).src = url;
  } else if (item.categoria === 'compactado') {
    await cloudViewerCompactado(item, corpo);
  } else if (cloudEhTexto(item)) {
    const r = await tenta('cloud_ler_texto', item.id, 100000, { __teto: 30000 });
    corpo.innerHTML = r?.ok ? `<pre class="cloud-viewer-texto">${esc(r.texto)}</pre>` : cloudViewerFallback(item, r?.erro);
  } else {
    corpo.innerHTML = cloudViewerFallback(item);
    $('[data-cloud-externo]', corpo)?.addEventListener('click', () => tenta('cloud_abrir', item.id));
  }
}

function cloudViewerFallback(item, erro = '') {
  return `<div class="cloud-viewer-fallback">${svg(_cloudIco(item.icone || 'arquivo'))}<h3>Prévia interna indisponível</h3><p>${esc(erro || 'Este formato pode ser aberto por um aplicativo instalado no computador.')}</p><button data-cloud-externo> Abrir no sistema</button></div>`;
}

async function cloudViewerCompactado(item, corpo) {
  const r = await tenta('cloud_compactado_listar', item.id, { __teto: 30000 });
  if (!r?.ok) { corpo.innerHTML = cloudViewerFallback(item, r?.erro); $('[data-cloud-externo]', corpo)?.addEventListener('click', () => tenta('cloud_abrir', item.id)); return; }
  corpo.innerHTML = `<div class="cloud-zip-topo"><div>${svg(_cloudIco('arquivo'))}<span><strong>${r.total_arquivos} arquivo(s)</strong><small>${cloudBytes(r.bytes_extraidos)} ao extrair · ${esc(String(r.formato).toUpperCase())}</small></span></div><div><button data-zip="selecionados" disabled>Extrair selecionados</button><button data-zip="tudo" class="principal">Extrair tudo</button></div></div><div class="cloud-zip-lista">${(r.entradas || []).map(e => `<label><input type="checkbox" value="${encodeURIComponent(e.caminho)}"><i>${svg(_cloudIco(e.diretorio ? 'pasta' : 'arquivo'))}</i><span title="${esc(e.caminho)}">${esc(e.caminho)}</span><small>${e.diretorio ? 'Pasta' : cloudBytes(e.tamanho)}</small></label>`).join('')}</div>`;
  const selecionados = $('[data-zip="selecionados"]', corpo);
  $$('input[type="checkbox"]', corpo).forEach(c => c.onchange = () => { selecionados.disabled = !$$('input:checked', corpo).length; });
  const extrair = async entradas => {
    $$('[data-zip]', corpo).forEach(b => b.disabled = true);
    const x = await tenta('cloud_compactado_extrair', item.id, item.parent_id || CLOUD.parent, entradas, { __teto: 30 * 60 * 1000 });
    if (x?.ok) { toast(`${x.extraidos || 0} arquivo(s) extraído(s)`); cloudViewerFechar(); cloudCarregar(); }
    else { toast(x?.erro || 'Não consegui extrair', 'erro'); $$('[data-zip]', corpo).forEach(b => b.disabled = false); }
  };
  $('[data-zip="tudo"]', corpo).onclick = () => extrair(null);
  selecionados.onclick = () => extrair($$('input:checked', corpo).map(c => decodeURIComponent(c.value)));
}

function cloudMenu(ancora, id) {
  const i = CLOUD.itens.find(x => x.id === id) || {};
  const lixo = CLOUD.filtro === 'lixeira' || !!i.apagado_em;
  const bloqueioExterno = ESTADO.demo ? {
    desabilitado: true,
    motivo: 'Ação externa bloqueada durante o Modo Demo',
    sub: 'Indisponível na sessão pública isolada',
  } : {};
  const itens = lixo ? [
    { icone: ICO.refazer, rotulo: 'Restaurar', acao: () => cloudRestaurar(id) },
    { icone: ICO.lixo, rotulo: 'Excluir definitivamente', classe: 'perigo', acao: () => cloudExcluir(id) },
  ] : [
    { icone: _cloudIco('abrir'), rotulo: i.tipo === 'pasta' ? 'Abrir pasta' : 'Abrir', acao: () => cloudAbrir(id) },
    { icone: ICO.lapis, rotulo: 'Renomear', acao: () => cloudRenomear(id) },
    ...(i.tipo === 'arquivo' ? [{ icone: ICO.clipe, rotulo: 'Anexar ao chat', acao: () => cloudAnexar(id) }] : []),
    { icone: _cloudIco('baixar'), rotulo: 'Exportar para o PC', acao: () => cloudExportar(id) },
    ...(i.tipo === 'arquivo' ? [
      { icone: _cloudIco('nuvem'), rotulo: 'Sincronizar', ...bloqueioExterno, acao: () => cloudSync(id) },
      { icone: ICO.globo, rotulo: 'Criar link temporário', ...bloqueioExterno, acao: () => cloudCompartilhar(id) },
    ] : []),
    { icone: ICO.lixo, rotulo: 'Mover para lixeira', classe: 'perigo', acao: () => cloudLixeira(id) },
  ];
  abrirPop(ancora, itens);
}

async function cloudImportar() {
  abrirPop($('#cloud-upload'), [
    { icone: ICO.clipe, rotulo: 'Arquivos', sub: 'Um ou vários arquivos', acao: () => cloudExecutarImport('cloud_escolher_importar') },
    { icone: ICO.pasta, rotulo: 'Pasta completa', sub: 'Mantém a estrutura interna', acao: () => cloudExecutarImport('cloud_escolher_pasta_importar') },
  ]);
}

async function cloudExecutarImport(metodo) {
  const btn = $('#cloud-upload'); btn.disabled = true; btn.classList.add('ocupado');
  const r = await tenta(metodo, CLOUD.parent, { __teto: 30 * 60 * 1000 });
  btn.disabled = false; btn.classList.remove('ocupado');
  if (!r || r.ok === false) { toast(r?.erro || r?.erros?.[0]?.erro || 'Não consegui guardar', 'erro'); return; }
  if (!r.cancelado) { toast(`${r.itens?.length || 0} item(ns) guardado(s)`); await cloudCarregar(); }
}

async function cloudNovaPasta() {
  const nome = await modal({ titulo: 'Nova pasta', texto: 'Dê um nome para organizar seu arquivo.', campo: 'Nome da pasta', ok: 'Criar' });
  if (!nome) return;
  const r = await tenta('cloud_criar_pasta', nome, CLOUD.parent);
  if (r?.ok) { toast('Pasta criada'); cloudCarregar(); } else toast(r?.erro || 'Não consegui criar', 'erro');
}

async function cloudRenomear(id) {
  const atual = CLOUD.itens.find(i => i.id === id)?.nome || '';
  const nome = await modal({ titulo: 'Renomear item', texto: atual, campo: 'Novo nome', ok: 'Renomear' });
  if (!nome) return;
  const r = await tenta('cloud_renomear', id, nome);
  if (r?.ok) { toast('Renomeado'); cloudCarregar(); } else toast(r?.erro || 'Não consegui renomear', 'erro');
}

async function cloudFavoritar(id) {
  const i = CLOUD.itens.find(x => x.id === id); if (!i) return;
  const r = await tenta('cloud_favoritar', id, !i.favorito);
  if (r?.ok) { i.favorito = !i.favorito; cloudDesenhar(); } else toast(r?.erro || 'Não consegui favoritar', 'erro');
}

async function cloudLixeira(id) {
  const i = CLOUD.itens.find(x => x.id === id);
  const ok = await modal({ titulo: 'Mover para a lixeira?', texto: `“${i?.nome || 'Item'}” pode ser restaurado depois.`, ok: 'Mover', perigo: true });
  if (!ok) return;
  const r = await tenta('cloud_lixeira', id);
  if (r?.ok) { toast('Movido para a lixeira'); $('#cloud-detalhes').hidden = true; cloudCarregar(); } else toast(r?.erro || 'Não consegui mover', 'erro');
}

async function cloudRestaurar(id) { const r = await tenta('cloud_restaurar', id); if (r?.ok) { toast('Restaurado'); cloudCarregar(); } else toast(r?.erro || 'Não consegui restaurar', 'erro'); }
async function cloudExcluir(id) {
  const ok = await modal({ titulo: 'Excluir para sempre?', texto: 'Essa ação não pode ser desfeita e remove os bytes sem outras referências.', ok: 'Excluir definitivamente', perigo: true });
  if (!ok) return; const r = await tenta('cloud_excluir', id, { __teto: 60000 });
  if (r?.ok) { toast('Excluído definitivamente'); cloudCarregar(); } else toast(r?.erro || 'Não consegui excluir', 'erro');
}
async function cloudExportar(id) { const r = await tenta('cloud_exportar', id, { __teto: 30 * 60 * 1000 }); if (r?.ok && !r.cancelado) toast(`Exportado para ${r.caminho}`); else if (!r?.cancelado) toast(r?.erro || 'Não consegui exportar', 'erro'); }
async function cloudAnexar(id) {
  const a = await tenta('cloud_anexar', id); if (!a) { toast('Não consegui anexar', 'erro'); return; }
  ESTADO.anexos.push(a); desenharAnexos(); ajustarEntrada(); irPara(ESTADO.atual ? 'chat' : 'inicio', { forcar: true }); toast('Item anexado à conversa');
}
async function cloudSync(id) { toast('Sincronizando…'); const r = await tenta('cloud_sincronizar', id, { __teto: 60 * 60 * 1000 }); if (r?.ok) { toast('Sincronizado'); cloudCarregar(); } else toast(r?.erro || 'Configure o S3 nas variáveis EMILY_CLOUD_S3_*', 'erro'); }
async function cloudCompartilhar(id) {
  const ok = await modal({ titulo: 'Criar link de 24 horas?', texto: 'O arquivo será sincronizado e qualquer pessoa com o link poderá baixá-lo até expirar.', ok: 'Criar link' });
  if (!ok) return; const r = await tenta('cloud_compartilhar', id, 24, { __teto: 60 * 60 * 1000 });
  if (r?.ok) { await tenta('copiar', r.url); toast('Link copiado para a área de transferência'); } else toast(r?.erro || 'Não consegui compartilhar', 'erro');
}

function cloudLigarDrop() {
  const tela = $('.cloud'); if (!tela) return; const drop = $('#cloud-drop');
  let profundidade = 0;
  tela.ondragenter = e => { e.preventDefault(); profundidade++; drop.hidden = false; };
  tela.ondragleave = () => { profundidade--; if (profundidade <= 0) { profundidade = 0; drop.hidden = true; } };
  tela.ondragover = e => e.preventDefault();
  tela.ondrop = async e => {
    e.preventDefault(); e.stopPropagation(); profundidade = 0; drop.hidden = true;
    const nomes = [...(e.dataTransfer?.files || [])].map(f => f.name); if (!nomes.length) return;
    const resolvidos = await tenta('resolver_arrastados', nomes) || [];
    const caminhos = resolvidos.map(a => a.caminho).filter(Boolean);
    if (!caminhos.length) { toast('Não achei o caminho; use o botão Guardar', 'erro'); return; }
    const r = await tenta('cloud_importar_caminhos', caminhos, CLOUD.parent, { __teto: 30 * 60 * 1000 });
    if (r?.itens?.length) { toast(`${r.itens.length} item(ns) guardado(s)`); cloudCarregar(); }
    else toast(r?.erro || r?.erros?.[0]?.erro || 'Não consegui guardar', 'erro');
  };
}