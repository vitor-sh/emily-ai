/* ════════════════════════════════════════════════════════════════
   app.js — a lógica da interface da Emily

   O contrato com o Python é pequeno de propósito:

   Python -> JS :  Emily.on(evento, dados)     (via evaluate_js)
   JS -> Python :  pywebview.api.<metodo>(...)  (devolve Promise)

   Nada aqui sabe como a Emily pensa. Isto desenha e avisa.
   ════════════════════════════════════════════════════════════════ */

/* ════════════════════════════════════════════════════════════════
   MODO OFICINA
   Api de mentira com dados de amostra, pra dar pra mexer no CSS num
   navegador comum com DevTools.

   NÃO é ligada por protocolo. O pywebview 5 também serve por http local,
   então checar o protocolo instalava isto em cima da ponte de verdade e a
   Emily abria com conversas de amostra. Quem decide é o esperarPonte():
   ele chama isto só depois de esperar a ponte real e ela não vir.
   ════════════════════════════════════════════════════════════════ */

function oficina() {
  if (pontePronta()) return false;
  console.info('[emily] modo oficina: api de mentira, dados de amostra');
  let urlNavegadorOficina = 'about:blank';
  let larguraNavegadorOficina = 500, alturaNavegadorOficina = 650;

  const conversas = [
    { id: '1', titulo: 'Expulsar alguém do servidor', mexida: Date.now() / 1000 - 300 },
    { id: '2', titulo: 'Mods pesados do modpack', mexida: Date.now() / 1000 - 7200 },
    { id: '3', titulo: 'Erro de importação no main', mexida: Date.now() / 1000 - 100000 },
    { id: '4', titulo: 'Preço da RTX 5090', mexida: Date.now() / 1000 - 900000 },
  ];
  let demoOficina = false;
  const api = {
    estado_demo: () => ({ ativo: demoOficina, nome: demoOficina ? 'Visitante' : '', turnos_ativos: 0 }),
    iniciar_demo: () => ({ ok: true, ativo: (demoOficina = true), nome: 'Visitante' }),
    encerrar_demo: () => ({ ok: true, ativo: (demoOficina = false) }),
    perfil: () => ({ nome: 'Vitor', sub: '', avatar: '', avatar_usuario: '' }),
    sugestoes: () => ([
      { icone: 'monitor', texto: 'olha minha tela e me diz o que tá errado' },
      { icone: 'musica',  texto: 'toca uma música boa pra eu focar' },
      { icone: 'pasta',   texto: 'organiza minha pasta de downloads' },
      { icone: 'disco',   texto: 'quanto espaço eu ainda tenho no disco?' },
    ]),
    listar_conversas: () => conversas,
    abrir_conversa: () => ([
      { papel: 'user', texto: 'olha minha tela e me diz o que tá errado' },
      { papel: 'assistant', texto: 'Ó, achei. Falta o **import** na linha 12:\n\n```python\nimport ferramentas\n```\n\nDois detalhes:\n\n- o interpretador selecionado é o do sistema, não o do venv\n- o `modelo.py` tem alteração não salva\n\nQuer que eu conserte?' },
    ]),
    nova_conversa: () => 'novo',
    renomear_conversa: () => true, apagar_conversa: () => true,
    enviar: () => true, regenerar: () => ({ ok: true, mensagens: [] }), copiar: () => true,
    voz_texto_estado: () => false, voz_texto_definir: ativo => ativo,
    ptt_tecla_estado: () => ({ tecla: 'mb5', rotulo: 'Botão lateral 2', padrao: 'mb5' }),
    ptt_tecla_capturar: () => new Promise(resolve => {
      const aoTeclar = e => {
        document.removeEventListener('keyup', aoTeclar, true);
        resolve({ ok: true, tecla: `scan:${e.keyCode}`, rotulo: e.key });
      };
      document.addEventListener('keyup', aoTeclar, true);
    }),
    ptt_tecla_cancelar: () => true,
    enviar_arquivos: () => 'novo',
    ptt: () => true, capturar_tela: () => true, enviar_arquivo: () => true,
    escolher_arquivos: () => [], salvar_colado: () => null,
    colar_imagem_nativa: () => ({ ok: false, erro: 'indisponivel' }),
    resolver_arrastados: () => [], salvar_imagem: () => 'demo.png',
    listar_apps: () => ([
      { nome: 'Discord', cor: '#5865F2', letra: 'D', tinta: '#fff', existe: true },
      { nome: 'Steam', cor: '#171a21', letra: 'S', tinta: '#fff', existe: true },
      { nome: 'Brave', cor: '#FB542B', letra: 'B', tinta: '#fff', existe: true },
    ]),
    abrir_app: () => true,
    estado_automacao: () => ({ monitor_downloads: true, monitor_discord: false,
      mudo: false, autonomia_experimental: false,
      audio_preprocess_denoise: true, audio_preprocess_normalize: true,
      audio_preprocess_vad: true }),
    agente_ui_estado: () => ({ estado: 'parado', objetivo: '', passo: 0, max_passos: 50,
      mensagem: '', erro: '', ativo: false,
      backend: { nome: 'oficina', captura: true, entrada: true, janelas: true, motivo_indisponivel: '' },
      historico: [] }),
    agente_ui_iniciar: objetivo => ({ ok: true, mensagem: 'Agente iniciado.', estado: {
      estado: 'rodando', objetivo, passo: 1, max_passos: 50, mensagem: 'Analisando a tela',
      erro: '', ativo: true,
      backend: { nome: 'oficina', captura: true, entrada: true, janelas: true, motivo_indisponivel: '' },
      historico: [] } }),
    agente_ui_pausar: () => ({ ok: true, mensagem: 'Agente pausado.', estado: {
      ...(ESTADO.agenteUI || {}), estado: 'pausado', ativo: true } }),
    agente_ui_retomar: () => ({ ok: true, mensagem: 'Agente retomado.', estado: {
      ...(ESTADO.agenteUI || {}), estado: 'rodando', ativo: true } }),
    agente_ui_cancelar: () => ({ ok: true, mensagem: 'Cancelamento solicitado.', estado: {
      ...(ESTADO.agenteUI || {}), estado: 'cancelado', ativo: false } }),
    agente_ui_mensagem: () => ({ ok: true, mensagem: 'Instrução enviada.', estado: ESTADO.agenteUI || {} }),
    responder_pergunta_usuario: () => true,
    navegador_interno_acao: (acao, dados = {}) => {
      if (acao === 'abrir') urlNavegadorOficina = dados.url || 'about:blank';
      if (acao === 'dimensionar') {
        larguraNavegadorOficina = dados.largura || larguraNavegadorOficina;
        alturaNavegadorOficina = dados.altura || alturaNavegadorOficina;
      }
      return {ok: true, url: urlNavegadorOficina,
        titulo: urlNavegadorOficina === 'about:blank' ? 'Página em branco' : 'Prévia do navegador',
        imagem: '', largura: larguraNavegadorOficina, altura: alturaNavegadorOficina,
        abas: [{indice: 0, url: urlNavegadorOficina, titulo: 'Prévia', ativa: true}]};
    },
    set_toggle: () => true, organizar_downloads: () => 'Separei 23 arquivos por tipo.',
    estado_modelo: () => ({
      provedor: 'gmi', modelo: 'MiniMaxAI/MiniMax-M3', raciocinio: 'baixo',
      modelos: [
        { id: 'MiniMaxAI/MiniMax-M3', nome: 'MiniMaxAI/MiniMax-M3', sobre: 'GMI' },
      ],
      provedores: [
        { id: 'claude', nome: 'Claude',
          modelos: [
            { id: 'claude-opus-5', nome: 'claude-opus-5', sobre: 'Claude' },
            { id: 'claude-opus-4-8', nome: 'claude-opus-4-8', sobre: 'Claude' },
          ] },
        { id: 'openrouter', nome: 'OpenRouter',
          modelos: [
            { id: 'qwen/qwen3.8-max-free', nome: 'qwen/qwen3.8-max-free', sobre: 'OpenRouter' },
          ] },
        { id: 'nvidia', nome: 'NVIDIA NIM',
          modelos: [
            { id: 'z-ai/glm-5.2', nome: 'z-ai/glm-5.2', sobre: 'NVIDIA NIM' },
          ] },
        { id: 'gmi', nome: 'GMI',
          modelos: [
            { id: 'MiniMaxAI/MiniMax-M3', nome: 'MiniMaxAI/MiniMax-M3', sobre: 'GMI' },
          ] },
        { id: 'ollama', nome: 'Ollama (local)',
          modelos: [
            { id: 'qwen3.5:9b', nome: 'qwen3.5:9b', sobre: 'Ollama (local)' },
          ] },
      ],
      niveis: [
        { id: 'baixo', nome: 'Baixo' }, { id: 'medio', nome: 'Médio' }, { id: 'alto', nome: 'Alto' },
      ],
    }),
    definir_provedor_e_modelo: () => true,
    definir_modelo: () => true, definir_raciocinio: () => true,
    estado_perfil: () => ({ nome: 'Vitor', avatar_usuario: '', personalidade_extra: '' }),
    definir_perfil: () => true, escolher_avatar: () => '',
    code_listar_conversas: () => ([
      { id: 'code-demo', titulo: 'Refatorar o módulo de memória', mexida: Date.now() / 1000,
        quantas: 2, ativa: true, projeto: '/projetos/emily' },
    ]),
    code_abrir_conversa: () => ([
      { papel: 'user', texto: 'revisa o módulo de memória e separa a persistência' },
      { papel: 'emily', texto: 'Achei o acoplamento. Vou separar a leitura e a gravação sem mudar o contrato público.' },
    ]),
    code_criar_conversa: () => 'code-demo', code_renomear_conversa: () => true,
    code_apagar_conversa: () => true,
    emily_code_estado: () => ({ projeto: '/projetos/emily', permitir_sempre: [] }),
    emily_code_enviar: (_texto, cid) => ({ ok: true, cid: cid || 'code-demo' }),
    emily_code_definir_projeto: caminho => `Pasta de projeto definida: ${caminho}`,
    emily_code_escolher_pasta: () => '', emily_code_cancelar_pasta: () => true,
    playlist: () => ([
      { video_id: 'dQw4w9WgXcQ', titulo: 'Rick Astley - Never Gonna Give You Up', thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' },
      { video_id: '9bZkp7q19f0', titulo: 'PSY - GANGNAM STYLE', thumb: 'https://i.ytimg.com/vi/9bZkp7q19f0/mqdefault.jpg' },
    ]),
    playlist_geral: () => ({
      playlists: {
        default: { musicas: [
          { video_id: 'dQw4w9WgXcQ', titulo: 'Rick Astley - Never Gonna Give You Up', thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' },
        ], quantidade: 1 },
      },
      ativa: 'default',
      favoritos: { 'dQw4w9WgXcQ': true },
    }),
    playlist_criar: () => ({ ok: true }), playlist_selecionar: () => true,
    playlist_renomear: () => ({ ok: true }), playlist_apagar: () => true,
    playlist_foto: () => ({ ok: true }),
    playlist_favoritar: () => true,
    playlist_buscar_preview: () => ({ resultados: [
      { video_id: 'dQw4w9WgXcQ', titulo: 'Rick Astley - Never Gonna Give You Up', thumb: 'https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg' },
      { video_id: '9bZkp7q19f0', titulo: 'PSY - GANGNAM STYLE', thumb: 'https://i.ytimg.com/vi/9bZkp7q19f0/mqdefault.jpg' },
    ] }),
    playlist_adicionar: () => true,
    playlist_buscar_e_add: () => ({ erro: 'Mock: backend não disponível no preview.' }),
    playlist_remover: () => true,
    player_estado: () => ({ volume: 100, loop: 1, shuffle: false, playlist: 'default', indice: -1, video_id: null, posicao: 0 }),
    player_salvar_estado: () => true,
    cloud_listar: (_parent, filtro, busca) => {
      const agora = Date.now() / 1000;
      const itens = [
        {id:'cf1',tipo:'pasta',nome:'Downloads da Emily',mime:'',tamanho:0,tamanho_legivel:'0 B',categoria:'pasta',icone:'pasta',favorito:true,criado_em:agora-90000,alterado_em:agora-200,estado_sync:'local',extensao:'',tem_preview:false,preview_url:''},
        {id:'cf2',tipo:'arquivo',nome:'Episódio 12 — 720p.mp4',mime:'video/mp4',tamanho:734003200,tamanho_legivel:'700.0 MB',categoria:'video',icone:'video',favorito:false,criado_em:agora-7000,alterado_em:agora-7000,estado_sync:'sincronizado',extensao:'.mp4',tem_preview:false,preview_url:''},
        {id:'cf3',tipo:'arquivo',nome:'broxasRPG-modpack.zip',mime:'application/zip',tamanho:188743680,tamanho_legivel:'180.0 MB',categoria:'compactado',icone:'arquivo',favorito:true,criado_em:agora-18000,alterado_em:agora-18000,estado_sync:'local',extensao:'.zip',tem_preview:false,preview_url:''},
        {id:'cf4',tipo:'arquivo',nome:'anotações-do-projeto.md',mime:'text/markdown',tamanho:12400,tamanho_legivel:'12.1 KB',categoria:'documento',icone:'documento',favorito:false,criado_em:agora-400,alterado_em:agora-400,estado_sync:'local',extensao:'.md',tem_preview:false,preview_url:''},
      ].filter(i => !busca || i.nome.toLowerCase().includes(String(busca).toLowerCase()))
       .filter(i => filtro !== 'favoritos' || i.favorito);
      return {ok:true,itens,breadcrumb:[],status:{uso_legivel:'880.0 MB',livre_legivel:'211.4 GB',arquivos:3,bytes_fisicos:922746880,bytes_livres:226989932544,s3_ativo:true,sincronizados:1}};
    },
    cloud_detalhes: id => ({ok:true,item:{id,nome:id==='cf2'?'Episódio 12 — 720p.mp4':'Arquivo da Emily',tipo:'arquivo',categoria:'video',icone:'video',tamanho_legivel:'700.0 MB',pasta_nome:'Meus arquivos',origem:'Emily',estado_sync:'sincronizado',versoes:[{}],preview_url:''}}),
    cloud_armazenamento_estado: () => ({ok:true,pasta:'D:/Emily Cloud',uso_legivel:'880 MB',livre_legivel:'211 GB'}),
    cloud_escolher_armazenamento: () => ({ok:true,cancelado:true}),
    cloud_migrar_armazenamento: destino => ({ok:true,destino}),
    cloud_criar_pasta: nome => ({ok:true,item:{nome}}), cloud_renomear: () => ({ok:true}),
    cloud_favoritar: () => ({ok:true}), cloud_lixeira: () => ({ok:true}),
    cloud_restaurar: () => ({ok:true}), cloud_excluir: () => ({ok:true}),
    cloud_exportar: () => ({ok:true,caminho:'~/Downloads/arquivo'}), cloud_abrir: () => ({ok:true}),
    cloud_visualizar: id => ({ok:true,url:'',item:{id,nome:'Arquivo de demonstração',tipo:'arquivo',mime:'text/plain',categoria:'documento',extensao:'.txt',tamanho:20,tamanho_legivel:'20 B'}}),
    cloud_ler_texto: () => ({ok:true,texto:'Visualizador interno da Emily Cloud.'}),
    cloud_compactado_listar: () => ({ok:true,formato:'zip',total_arquivos:2,bytes_extraidos:300,entradas:[{caminho:'docs/leia.txt',diretorio:false,tamanho:120},{caminho:'imagens/foto.png',diretorio:false,tamanho:180}]}),
    cloud_compactado_extrair: () => ({ok:true,extraidos:2}),
    cloud_anexar: () => ({nome:'arquivo.txt',caminho:'/tmp/arquivo.txt',previa:''}),
    cloud_sincronizar: () => ({ok:true}), cloud_compartilhar: () => ({ok:true,url:'https://exemplo.invalid/share'}),
    cloud_escolher_importar: () => ({ok:true,cancelado:true,itens:[]}),
    cloud_escolher_pasta_importar: () => ({ok:true,cancelado:true,itens:[]}),
    cloud_importar_caminhos: () => ({ok:true,itens:[]}),
    listar_memoria: () => {
      // Muitos fatos de propósito, pra dar pra ver a paginação na oficina.
      const base = [
        'Vitor gosta de Hollow Knight.',
        'O usuário se chama Vitor, tem 19 anos, é brasileiro e mora em SP.',
        'Trabalha com código (programador).',
        'Gosta do estilo antigo do canal Celbit.',
        'Costuma trabalhar até tarde, pelo menos até meia-noite.',
      ];
      return Array.from({ length: 23 }, (_, i) => base[i % base.length] + ` (#${i + 1})`);
    },
    add_fato: () => true, del_fato: () => true,
    memoria_unificada_estado: () => ({ ativa: false, flag: false }),
    memoria_unificada_listar: () => [],
    memoria_unificada_esquecer: () => true,
    memoria_unificada_reativar: () => true,
    sistema: () => ({ cpu: 34 + Math.random() * 20, ram: 61,
                      hora: new Date().toTimeString().slice(0, 5), data: 'sexta, 22/08' }),
    logs_ler: () => ({ ok: true, caminho: '~/.emily_log.txt', tamanho: 7421,
      texto: '[MAIN] Emily iniciada\n[SERVIDOR] Rodando na porta 5000\n[NGROK] URL pública: https://exemplo.ngrok.app\n',
      ngrok: { estado: 'online', url: 'https://exemplo.ngrok.app', erro: '' } }),
    logs_limpar: () => true,
    logs_reiniciar_ngrok: () => true,
    emily_atualizacao_inicio: () => ({ verificar: false, em_pacote: false }),
    janela: () => true,
  };
  window.pywebview = { api };
  window.dispatchEvent(new Event('pywebviewready'));
  return true;
}

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

/* ── A ponte ────────────────────────────────────────────────────────
   Duas armadilhas aqui, as duas já pagas.

   1. Esperar SÓ o evento 'pywebviewready' não serve: dependendo de quando a
      WebView2 injeta a api, o evento pode disparar ANTES do app.js carregar,
      e o listener nunca é chamado.

   2. O pywebview 5 serve o index.html por um HTTP local (é pra isso que o
      bottle entra nas dependências), então `location.protocol` é 'http:'
      TAMBÉM em produção. O modo oficina, que era ligado por protocolo,
      instalava a api de mentira em cima da real — e a Emily abria mostrando
      conversas de amostra em vez das do Vitor. Agora a de mentira só entra
      depois de esperar a real e ela não vir. */

const ESPERA_PONTE_MS = 30000;   // teto pra ponte real subir (boot frio)
const ESPERA_OFICINA_MS = 1800;  // depois disso, sem ponte real, é oficina
const TETO_CHAMADA_MS = 8000;    // teto de UMA chamada, contado depois da ponte

const pontePronta = () => typeof window.pywebview?.api?.perfil === 'function';

let _avisouPonte = false;
function esperarPonte() {
  if (pontePronta()) return Promise.resolve(true);
  return new Promise(resolve => {
    const inicio = Date.now();
    let caiuNaOficina = false;
    const olhar = () => {
      if (pontePronta()) return resolve(true);
      const gasto = Date.now() - inicio;
      // Navegador comum: a ponte real nunca vem. Depois da espera curta,
      // entra a de mentira pra dar pra mexer no design.
      if (!caiuNaOficina && gasto > ESPERA_OFICINA_MS && oficina()) {
        caiuNaOficina = true;
        return resolve(true);
      }
      if (gasto > ESPERA_PONTE_MS) {
        if (!_avisouPonte) {
          _avisouPonte = true;
          console.error('[emily] a ponte com o Python não subiu');
        }
        return resolve(false);
      }
      setTimeout(olhar, 60);
    };
    window.addEventListener('pywebviewready', () => { if (pontePronta()) resolve(true); },
                            { once: true });
    olhar();
  });
}

async function api(metodo, ...args) {
  if (!await esperarPonte()) throw new Error('ponte indisponível');
  const fn = window.pywebview.api[metodo];
  if (!fn) throw new Error(`api.${metodo} não existe`);
  // Um ÚNICO argumento {teto: ms} ajusta o teto DESTE chamada e não vai pro
  // Python. Existe por causa do botão "Atualizar agora": o ensaio dele
  // importa o pacote inteiro e leva MINUTOS — com o teto padrão de 8s o JS
  // desistia no meio, mostrava erro e reabilitava o botão enquanto o
  // preflight seguia; um segundo clique punha dois processos disputando o
  // mesmo staging. Chamadas normais não passam nada e ficam como eram.
  let teto = TETO_CHAMADA_MS;
  // Operações grandes (importar vídeo/pasta, sincronizar) precisam passar
  // argumentos E um teto. O objeto de opções é retirado antes de chamar Python.
  const ultima = args[args.length - 1];
  if (ultima && typeof ultima === 'object' && typeof ultima.__teto === 'number') {
    teto = ultima.__teto;
    args.pop();
  }
  if (args.length === 1 && args[0] && typeof args[0].teto === 'number') {
    teto = args[0].teto;
    args = [];
  }
  return await Promise.race([
    Promise.resolve(fn(...args)),
    new Promise((_, rej) => setTimeout(
      () => rej(new Error(`api.${metodo} passou de ${teto}ms`)), teto)),
  ]);
}

/* Chamada que não deve derrubar a tela. Devolve null quando falha: é melhor
   desenhar sem um dado do que não desenhar. */
const tenta = (m, ...a) => api(m, ...a).catch(e => {
  console.warn(`[emily] ${m} falhou:`, e.message || e);
  return null;
});

const ESTADO = {
  remoto: (() => { try { return localStorage.getItem('emily_remoto') === '1'; } catch (_) { return false; } })(),
  tela: 'inicio',
  conversas: [],
  atual: null,
  filtro: '',
  anexos: [],
  ultimoPedido: '',
  vozTexto: false,
  cfgPagina: 'automacao',
  emilyAberta: null,
  emilyBolhaDoTurno: null,
  ditoNoCartao: '',
  textoStream: '',
  vozPrefixoFiel: false,
  progresso: null,
  // Frases de "processo" — os comentários que ela fala ANTES de agir ("peraí,
  // deixa eu ver"). Vão pro painel de progresso, e são removidas da resposta
  // final pra não ficar tudo embolado numa bolha só.
  falasProcesso: [],
  demo: false,
  demoAlternando: false,
  agenteUI: null,
};

const AGENTE_UI_ESTADOS = {
  parado: 'Parado', iniciando: 'Iniciando', rodando: 'Rodando', capturando: 'Olhando a tela',
  decidindo: 'Decidindo', executando: 'Executando', pausado: 'Pausado',
  concluido: 'Concluído', cancelado: 'Cancelado', erro: 'Erro', limite: 'Limite atingido',
  watchdog: 'Interrompido por segurança',
};

function aplicarEstadoAgenteUI(dados = {}) {
  const anterior = ESTADO.agenteUI || {};
  const estado = { ...anterior, ...dados, backend: { ...(anterior.backend || {}), ...(dados.backend || {}) } };
  ESTADO.agenteUI = estado;
  const painel = $('#agente-ui-painel');
  if (!painel) return;

  const nomeEstado = estado.estado || 'parado';
  const ativo = Boolean(estado.ativo);
  const pausado = nomeEstado === 'pausado';
  const objetivo = String(estado.objetivo || '').trim();
  const backend = estado.backend || {};
  const backendPronto = backend.captura !== false && backend.entrada !== false;
  const motivo = String(estado.erro || backend.motivo_indisponivel || '').trim();
  const resumo = estado.mensagem || estado.ultima_acao || AGENTE_UI_ESTADOS[nomeEstado] || nomeEstado;

  painel.dataset.estado = nomeEstado;
  painel.dataset.ativo = String(ativo);
  painel.classList.toggle('tem-alerta', Boolean(motivo) || !backendPronto);
  const botao = $('#btn-tela');
  botao?.classList.toggle('agente-ativo', ativo);
  botao?.classList.toggle('agente-alerta', Boolean(motivo) || !backendPronto);
  if (botao) botao.title = ativo
    ? `Agente visual: ${resumo || AGENTE_UI_ESTADOS[nomeEstado] || nomeEstado}`
    : 'Abrir agente visual';
  $('#agente-ui-resumo').textContent = resumo || 'Pronto para controlar a tela';
  $('#agente-ui-estado').textContent = AGENTE_UI_ESTADOS[nomeEstado] || nomeEstado;
  $('#agente-ui-backend').textContent = backend.nome || 'Desktop';
  $('#agente-ui-objetivo').textContent = objetivo || 'Sem objetivo ativo.';
  $('#agente-ui-passo').textContent = estado.passo
    ? `${estado.passo}/${estado.max_passos || '—'}` : '';

  const aviso = $('#agente-ui-aviso');
  aviso.hidden = !motivo;
  aviso.textContent = motivo;
  $('#agente-ui-execucao').hidden = !objetivo;
  $('#agente-ui-pausar').hidden = !ativo || pausado;
  $('#agente-ui-retomar').hidden = !ativo || !pausado;
  $('#agente-ui-cancelar').hidden = !ativo;
  $('#agente-ui-form-mensagem').hidden = !ativo;
  $('#agente-ui-form-iniciar').hidden = ativo;

  const bloqueado = Boolean(ESTADO.demo);
  $('#agente-ui-objetivo-input').disabled = bloqueado || ativo || !backendPronto;
  $('#agente-ui-iniciar').disabled = bloqueado || ativo || !backendPronto;
  $('#agente-ui-mensagem-input').disabled = bloqueado || !ativo;
  painel.title = bloqueado ? 'Agente visual bloqueado durante o Modo Demo' : '';

}

function posicionarPainelAgenteUI() {
  const painel = $('#agente-ui-painel');
  const botao = $('#btn-tela');
  if (!painel || !botao || painel.hidden) return;
  const ancora = botao.getBoundingClientRect();
  const direita = window.innerWidth <= 680 ? 10 : Math.max(10, window.innerWidth - ancora.right);
  painel.style.setProperty('--agente-ui-right', `${direita}px`);
  painel.style.setProperty('--agente-ui-bottom', `${Math.max(10, window.innerHeight - ancora.top + 10)}px`);
}

function definirPainelAgenteUI(aberto) {
  const painel = $('#agente-ui-painel');
  const botao = $('#btn-tela');
  if (!painel || !botao) return;
  painel.hidden = !aberto;
  botao.classList.toggle('ativo', Boolean(aberto));
  botao.setAttribute('aria-expanded', String(Boolean(aberto)));
  if (aberto) {
    posicionarPainelAgenteUI();
    requestAnimationFrame(() => $('#agente-ui-objetivo-input')?.focus());
  }
}

async function comandoAgenteUI(metodo, ...args) {
  const resultado = await tenta(metodo, ...args);
  if (!resultado) { toast('Não consegui falar com o agente visual.', 'erro'); return null; }
  if (resultado.estado) aplicarEstadoAgenteUI(resultado.estado);
  if (resultado.mensagem) toast(resultado.mensagem, resultado.ok ? undefined : 'erro');
  return resultado;
}

function ligarAgenteUI() {
  definirPainelAgenteUI(false);
  $('#agente-ui-toggle').onclick = () => definirPainelAgenteUI(false);
  window.addEventListener('resize', posicionarPainelAgenteUI);
  document.addEventListener('click', e => {
    const painel = $('#agente-ui-painel');
    if (!painel || painel.hidden || painel.contains(e.target) || $('#btn-tela')?.contains(e.target)) return;
    definirPainelAgenteUI(false);
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && !$('#agente-ui-painel')?.hidden) definirPainelAgenteUI(false);
  });
  $('#agente-ui-form-iniciar').onsubmit = async e => {
    e.preventDefault();
    if (ESTADO.demo) { toast('Agente visual bloqueado durante a demo', 'erro'); return; }
    const campo = $('#agente-ui-objetivo-input');
    const objetivo = campo.value.trim();
    if (!objetivo) { campo.focus(); return; }
    const resultado = await comandoAgenteUI('agente_ui_iniciar', objetivo);
    if (resultado?.ok) campo.value = '';
  };
  $('#agente-ui-pausar').onclick = () => comandoAgenteUI('agente_ui_pausar');
  $('#agente-ui-retomar').onclick = () => comandoAgenteUI('agente_ui_retomar');
  $('#agente-ui-cancelar').onclick = () => comandoAgenteUI('agente_ui_cancelar');
  $('#agente-ui-form-mensagem').onsubmit = async e => {
    e.preventDefault();
    const campo = $('#agente-ui-mensagem-input');
    const mensagem = campo.value.trim();
    if (!mensagem) return;
    const resultado = await comandoAgenteUI('agente_ui_mensagem', mensagem);
    if (resultado?.ok) campo.value = '';
  };
}

/* ════════════════════════════════════════════════════════════════
   ÍCONES  (traço, monocromáticos — nada de emoji colorido)
   ════════════════════════════════════════════════════════════════ */

const ICO = {
  copiar:  '<path d="M9 9h10v10a2 2 0 01-2 2H9a2 2 0 01-2-2V9z"/><path d="M15 5H7a2 2 0 00-2 2v8"/>',
  refazer: '<path d="M20 11a8 8 0 10-2.6 5.9"/><path d="M20 4v7h-7"/>',
  lixo:    '<path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/>',
  lapis:   '<path d="M4 20h4l11-11a2.1 2.1 0 00-3-3L5 17v3z"/>',
  check:   '<path d="M4 12.5l5 5L20 6.5"/>',
  x:       '<path d="M6 6l12 12M18 6L6 18"/>',
  pasta:   '<path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>',
  raio:    '<path d="M13 2L4 14h6l-1 8 9-12h-6l1-8z"/>',
  cubo:    '<path d="M12 2l9 5v10l-9 5-9-5V7l9-5z"/><path d="M3 7l9 5 9-5M12 12v10"/>',
  chat:    '<path d="M21 12a8 8 0 01-8 8H8l-5 3 1.5-5A8 8 0 1121 12z"/>',
  monitor: '<rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M8 20h8"/>',
  tecla:   '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8"/>',
  seta:    '<path d="M9 6l6 6-6 6"/>',
  volta:   '<path d="M15 6l-6 6 6 6"/>',
  cerebro: '<path d="M9.5 4.5A3.5 3.5 0 006 8v.35A3.4 3.4 0 004.5 14a3.5 3.5 0 003.5 3.5h1.5V4.5zM14.5 4.5A3.5 3.5 0 0118 8v.35A3.4 3.4 0 0119.5 14a3.5 3.5 0 01-3.5 3.5h-1.5V4.5z"/><path d="M9.5 9H8a2 2 0 01-2-2M14.5 9H16a2 2 0 002-2M9.5 14H8a2 2 0 00-2 2M14.5 14H16a2 2 0 012 2M12 4.5v15"/>',
  olho:    '<path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z"/><circle cx="12" cy="12" r="2.5"/>',
  sino:    '<path d="M18 9a6 6 0 00-12 0c0 7-3 7-3 8h18c0-1-3-1-3-8M10 21h4"/>',
  voz:     '<path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M15 9a4 4 0 010 6M18 6a8 8 0 010 12"/>',
  pessoa:  '<circle cx="12" cy="8" r="3.5"/><path d="M5 21a7 7 0 0114 0"/>',
  info:    '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  disco:   '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/>',
  clipe:   '<path d="M21.4 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.2-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/>',
  lupa:    '<circle cx="11" cy="11" r="7"/><path d="M16.5 16.5L21 21"/>',
  musica:  '<path d="M9 18V5l10-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  paleta:  '<path d="M12 3a9 9 0 100 18c1.4 0 2.1-.8 2.1-1.8 0-.9-.6-1.4-.6-2.2 0-1 .8-1.8 2-1.8h1.7A4.9 4.9 0 0021 12.1C21 7.1 17 3 12 3z"/><circle cx="7.6" cy="10.6" r=".9"/><circle cx="10.4" cy="7.4" r=".9"/><circle cx="14.2" cy="7.2" r=".9"/><circle cx="16.9" cy="10" r=".9"/>',
  globo:   '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.7 2.6 15.3 0 18M12 3c-2.6 2.7-2.6 15.3 0 18"/>',
  wifi:    '<path d="M2 8.5a15 15 0 0120 0M5 12a10 10 0 0114 0M8.5 15.5a5 5 0 017 0"/><circle cx="12" cy="19" r="1"/>',
  nuvem:   '<path d="M7 18h10a4 4 0 00.7-7.9A6.5 6.5 0 005.7 8.7 4.8 4.8 0 007 18z"/>',
  tv:      '<rect x="3" y="5" width="18" height="13" rx="2"/><path d="M8 21h8M12 18v3"/>',
  jogo:    '<path d="M7 9h10a4 4 0 013.8 2.7l1.1 4.1a2 2 0 01-3 2.2L16 16H8l-2.9 2a2 2 0 01-3-2.2l1.1-4.1A4 4 0 017 9z"/><path d="M7 12v4M5 14h4M16 13h.01M19 15h.01"/>',
};

// Cada intensidade tem uma silhueta própria, inclusive na pílula fechada.
const ICONES_RACIOCINIO = {
  desligado: '<circle cx="12" cy="12" r="8"/><path d="M6.5 17.5l11-11"/>',
  baixo: '<path d="M12 3v3M5.6 5.6l2.1 2.1M3 12h3M5.6 18.4l2.1-2.1"/><path d="M12 9a3 3 0 100 6 3 3 0 000-6z"/>',
  medio: '<path d="M5 17v-4M10 17V9M15 17V6M20 17v-3"/><path d="M3 20h18"/>',
  alto: '<path d="M12 2l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5L12 2z"/>',
  extra_alto: '<circle cx="12" cy="12" r="3"/><ellipse cx="12" cy="12" rx="10" ry="5" transform="rotate(-35 12 12)"/><path d="M18 4h.01"/>',
  maximo: '<path d="M4 18h16l1-10-5 4-4-7-4 7-5-4 1 10zM4 21h16"/><path d="M12 2v1"/>',
};
const DETALHES_RACIOCINIO = {
  desligado: 'Resposta direta, sem análise extra',
  baixo: 'Rápido para pedidos simples',
  medio: 'Equilíbrio entre velocidade e análise',
  alto: 'Mais cuidado em tarefas difíceis',
  extra_alto: 'Análise aprofundada',
  maximo: 'Profundidade máxima disponível',
};

// Logo do GitHub (preenchido, não traço) — usado no botão do composer e no
// painel de progresso. Declarado aqui, antes do _NOME_BONITO, pra não cair
// na zona morta do const (o que derrubava o app inteiro antes do window.Emily).
const ICO_GITHUB = '<path fill="currentColor" stroke="none" d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>';

const svg = (d, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24">${d}</svg>`;

/* ════════════════════════════════════════════════════════════════
   TEXTO: escape e markdown
   A interface antiga renderizava markdown com três regex e não tinha
   bloco de código nenhum. Aqui é um parser pequeno mas de verdade:
   fence, inline code, negrito, itálico, link, títulos, listas, citações,
   divisores, tabelas e parágrafos. Sem dependência externa no build.
   ════════════════════════════════════════════════════════════════ */

const esc = t => String(t ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/* As instruções entre colchetes pertencem ao Fish Audio, não à conversa.
   O texto cru continua intacto no backend/TTS; só a camada visual as oculta. */
const TAGS_VOZ_FISH = new Set(["angry", "breathy", "chuckling", "clear throat", "clears throat", "confident", "conversational", "crying", "curious", "embarrassed", "empathetic", "emphasis", "excited", "exhale", "friendly", "gasp", "giggle", "grateful", "groan", "in a hurry tone", "inhale", "laughing", "laughs", "long pause", "loud voice", "low voice", "nervous", "panting", "pause", "relieved", "sad", "scared", "screaming", "short pause", "shouting", "sigh", "sighing", "sobbing", "soft", "soft voice", "speaking slowly", "surprised", "tender", "tired", "whisper", "whispering"]);
const PADRAO_TAG_VOZ_LIVRE = /^(?:speaking|sighing|sighs|sigh|sobbing|chuckling|gasping|hesitating|breathing|pausing|pause|whispering|whisper|shouting|screaming|laughing|laughs|laugh|crying|smiling|nodding|tilting|exclaiming|mumbling|sniffling|stuttering|trailing|curious|cheerful|excited|sad|angry|nervous|scared|confident|surprised|calm|sarcastic|teasing|warm|cold|soft|firm|gentle|serious|playful|mocking|smooth|friendly|empathetic|relieved|grateful|embarrassed|conversational|breathy|tender|tired|dead tired|professional|low voice|loud voice|voice breaking|voice rough|pitch up|pitch down|short pause|long pause|emphasis|inhale|exhale|gasp|panting|giggle|groan|clear throat|clears throat|falando|rindo|hesitando|sussurrando|gritando|chorando|suspirando|pausa|calma|com (?:um |uma )?tom|(?:with|in) (?:a |an )?.*tone\b|(?:emotion|tone|style|mood|voice)\s*[:=])\b/i;

function textoVisivelSemTagsDeVoz(texto) {
  return String(texto ?? '')
    .replace(/\[([^\]\r\n]{1,80})\]/g, (tagCompleta, conteudo) => {
      const tag = String(conteudo || '').trim().toLowerCase();
      const livre = PADRAO_TAG_VOZ_LIVRE.test(tag);
      return TAGS_VOZ_FISH.has(tag) || livre ? '' : tagCompleta;
    })
    // O texto do modelo também passa por aqui: recuos de código e quebras de
    // tabela precisam chegar intactos ao renderizador Markdown.
    .trim();
}

/* Estado do saneamento incremental. O backend já filtra o caminho normal, mas
   esta segunda barreira protege eventos vindos de integrações/reconexões que
   chamem `delta` diretamente. Nunca renderiza "[exci" enquanto espera "ted]". */
let _tagVozPendente = '';
function deltaVisivelSemTagsDeVoz(pedaco, finalizar = false) {
  const entrada = _tagVozPendente + String(pedaco ?? '');
  _tagVozPendente = '';
  let saida = '', pos = 0;
  while (pos < entrada.length) {
    const abre = entrada.indexOf('[', pos);
    if (abre < 0) { saida += entrada.slice(pos); break; }
    saida += entrada.slice(pos, abre);
    const fecha = entrada.indexOf(']', abre + 1);
    if (fecha < 0) {
      const candidato = entrada.slice(abre);
      if (finalizar || candidato.includes('\n') || candidato.length > 82) saida += candidato;
      else _tagVozPendente = candidato;
      break;
    }
    const conteudo = entrada.slice(abre + 1, fecha);
    const tag = conteudo.trim().toLowerCase();
    const livre = PADRAO_TAG_VOZ_LIVRE.test(tag);
    if (conteudo.length <= 80 && (TAGS_VOZ_FISH.has(tag) || livre)) {
      pos = fecha + 1;
      continue;
    }
    saida += entrada.slice(abre, fecha + 1);
    pos = fecha + 1;
  }
  return saida;
}

/* ── Realce de código ──────────────────────────────────────────────
   Sem biblioteca externa (é app local, offline). Um tokenizador só, que
   colore o que dá o visual de "código de verdade" na esmagadora maioria
   das linguagens que ela manda: comentário, string, número, palavra-chave,
   constante e nome de função. Não é um parser por linguagem — é um passe
   genérico que acerta Python, JS, e a maioria das de sintaxe C-like. */

const _COD_KW = new Set((
  // controle e declaração — a união das linguagens comuns
  'def class return if elif else for while try except finally raise with as ' +
  'import from in is not and or lambda yield global nonlocal pass break continue assert del ' +
  'async await function var let const new typeof instanceof of do switch case default throw ' +
  'public private protected static void int float double char boolean string export interface ' +
  'extends implements package super this end then elsif module fn use struct impl match'
).split(' '));

const _COD_CONST = new Set(
  'True False None self __name__ true false null undefined nil NaN Infinity'.split(' '));

function destacar(codigo) {
  // Ordem importa: comentário e string primeiro, pra não colorir palavra
  // dentro deles. O último grupo ([\s\S]) garante que nada escapa sem escape.
  const re = /(#[^\n]*|\/\/[^\n]*|\/\*[\s\S]*?\*\/|"""[\s\S]*?"""|'''[\s\S]*?''')|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_.eExXbBoOaAfF]*\b)|([A-Za-z_$][\w$]*)(\s*\()?|([\s\S])/g;
  let out = '';
  codigo.replace(re, (m, com, str, num, id, chamada, resto) => {
    if (com != null) out += `<span class="tk-com">${esc(com)}</span>`;
    else if (str != null) out += `<span class="tk-str">${esc(str)}</span>`;
    else if (num != null) out += `<span class="tk-num">${esc(num)}</span>`;
    else if (id != null) {
      const cls = _COD_KW.has(id) ? 'tk-kw'
        : _COD_CONST.has(id) ? 'tk-const'
          : chamada ? 'tk-fn' : null;
      const marcado = cls ? `<span class="${cls}">${esc(id)}</span>` : esc(id);
      out += marcado + (chamada || '');
    } else out += esc(resto);
    return '';
  });
  return out;
}

// Nome bonito da linguagem pra mostrar no topo do bloco.
const _COD_NOME = {
  py: 'Python', python: 'Python', js: 'JavaScript', javascript: 'JavaScript',
  ts: 'TypeScript', typescript: 'TypeScript', jsx: 'JSX', tsx: 'TSX',
  html: 'HTML', css: 'CSS', json: 'JSON', bash: 'Bash', sh: 'Shell',
  shell: 'Shell', sql: 'SQL', java: 'Java', c: 'C', cpp: 'C++', 'c++': 'C++',
  cs: 'C#', csharp: 'C#', go: 'Go', rust: 'Rust', rs: 'Rust', php: 'PHP',
  rb: 'Ruby', ruby: 'Ruby', yaml: 'YAML', yml: 'YAML', md: 'Markdown',
  toml: 'TOML', xml: 'XML', kt: 'Kotlin', kotlin: 'Kotlin', lua: 'Lua',
};

function inline(t) {
  return esc(t)
    .replace(/`([^`\n]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(?<![*\w])\*([^*\n]+)\*(?![*\w])/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s)<]+)/g, '$1<a href="$2" target="_blank">$2</a>');
}

function markdown(bruto) {
  const texto = String(bruto ?? '');
  const saida = [];
  // Fence primeiro: o conteúdo dele não passa por mais nenhuma regra.
  const partes = texto.split(/```/);
  partes.forEach((parte, i) => {
    if (i % 2 === 1) {
      const nl = parte.indexOf('\n');
      const rotulo = (nl >= 0 ? parte.slice(0, nl) : '').trim().toLowerCase();
      // Se não veio nome de linguagem, o "primeiro token" NÃO é linguagem —
      // é código. Só corta a primeira linha como rótulo se ela for uma
      // palavra só (nome de linguagem), senão é tudo código.
      const ehRotulo = /^[a-z0-9+#]{1,15}$/.test(rotulo);
      const cod = (ehRotulo && nl >= 0 ? parte.slice(nl + 1) : parte).replace(/^\n/, '').replace(/\n$/, '');
      const lang = ehRotulo ? rotulo : '';
      const nome = _COD_NOME[lang] || (lang ? lang : 'código');
      saida.push(
        `<div class="bloco-cod"><div class="bloco-cod-topo"><span>${esc(nome)}</span>` +
        `<button class="btn-copiar-cod" data-cod="${encodeURIComponent(cod)}">` +
        svg(ICO.copiar) + `copiar</button></div>` +
        `<pre><code>${destacar(cod)}</code></pre></div>`
      );
    } else {
      saida.push(blocos(parte));
    }
  });
  return saida.join('');
}

function _celulasTabela(linha) {
  let miolo = String(linha || '').trim();
  if (miolo.startsWith('|')) miolo = miolo.slice(1);
  if (miolo.endsWith('|')) miolo = miolo.slice(0, -1);

  const celulas = [];
  let atual = '', escapado = false, emCodigo = false;
  for (const caractere of miolo) {
    if (escapado) {
      atual += caractere;
      escapado = false;
    } else if (caractere === '\\') {
      escapado = true;
    } else if (caractere === '`') {
      emCodigo = !emCodigo;
      atual += caractere;
    } else if (caractere === '|' && !emCodigo) {
      celulas.push(atual.trim());
      atual = '';
    } else atual += caractere;
  }
  celulas.push(atual.trim());
  return celulas;
}

function _separadorTabela(linha) {
  const celulas = _celulasTabela(linha);
  return celulas.length > 0 && celulas.every(c => /^:?-{3,}:?$/.test(c));
}

function _alinhamentosTabela(linha) {
  return _celulasTabela(linha).map(c => {
    if (c.startsWith(':') && c.endsWith(':')) return 'al-centro';
    if (c.endsWith(':')) return 'al-dir';
    return 'al-esq';
  });
}

function _linhaTabela(celulas, tag, alinhamentos, total) {
  const prontas = celulas.slice(0, total);
  while (prontas.length < total) prontas.push('');
  return `<tr>${prontas.map((c, i) =>
    `<${tag} class="${alinhamentos[i] || 'al-esq'}">${inline(c)}</${tag}>`
  ).join('')}</tr>`;
}

function blocos(trecho) {
  // Alguns modelos colam um header no fim da frase mesmo quando foram
  // instruídos a deixá-lo numa linha própria. O marcador com 2+ # é específico
  // o bastante para recuperar a estrutura sem confundir conversa normal.
  const normalizado = String(trecho).replace(/([^\n])\s+(#{2,6}\s+)/g, '$1\n\n$2');
  const linhas = normalizado.split('\n');
  const out = [];
  let lista = null, para = [], citacao = [];

  const fechaPara = () => {
    if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; }
  };
  const fechaLista = () => {
    if (lista) { out.push(`<${lista.tag}>${lista.itens.join('')}</${lista.tag}>`); lista = null; }
  };
  const fechaCitacao = () => {
    if (citacao.length) {
      out.push(`<blockquote>${inline(citacao.join(' '))}</blockquote>`);
      citacao = [];
    }
  };

  for (let i = 0; i < linhas.length; i++) {
    const linha = linhas[i];
    const l = linha.trim();
    if (!l) { fechaPara(); fechaLista(); fechaCitacao(); continue; }

    const cabecalho = l.match(/^(#{1,6})\s+(.+?)\s*#*$/);
    if (cabecalho) {
      fechaPara(); fechaLista(); fechaCitacao();
      const nivel = Math.min(6, cabecalho[1].length);
      out.push(`<h${nivel}>${inline(cabecalho[2])}</h${nivel}>`);
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(l)) {
      fechaPara(); fechaLista(); fechaCitacao();
      out.push('<hr>');
      continue;
    }

    const linhaSeguinte = linhas[i + 1]?.trim() || '';
    if (l.includes('|') && _separadorTabela(linhaSeguinte)) {
      fechaPara(); fechaLista(); fechaCitacao();
      const cabecalhos = _celulasTabela(l);
      const alinhamentos = _alinhamentosTabela(linhaSeguinte);
      const total = cabecalhos.length;
      const corpo = [];
      i += 2;
      while (i < linhas.length) {
        const candidata = linhas[i].trim();
        if (!candidata || !candidata.includes('|')) break;
        corpo.push(_linhaTabela(_celulasTabela(candidata), 'td', alinhamentos, total));
        i++;
      }
      i--;
      out.push(
        '<div class="md-tabela-wrap" role="region" aria-label="Tabela da resposta" tabindex="0">' +
        '<table class="md-tabela"><thead>' +
        _linhaTabela(cabecalhos, 'th', alinhamentos, total) +
        `</thead>${corpo.length ? `<tbody>${corpo.join('')}</tbody>` : ''}</table></div>`
      );
      continue;
    }

    const mCitacao = l.match(/^>\s?(.*)$/);
    if (mCitacao) {
      fechaPara(); fechaLista();
      citacao.push(mCitacao[1]);
      continue;
    }
    fechaCitacao();

    const mUl = l.match(/^[-*+•]\s+(.*)$/);
    const mOl = l.match(/^\d+[.)]\s+(.*)$/);
    if (mUl || mOl) {
      fechaPara();
      const tag = mUl ? 'ul' : 'ol';
      if (!lista || lista.tag !== tag) { fechaLista(); lista = { tag, itens: [] }; }
      lista.itens.push(`<li>${inline((mUl || mOl)[1])}</li>`);
      continue;
    }
    fechaLista();
    para.push(l);
  }
  fechaPara(); fechaLista(); fechaCitacao();
  return out.join('');
}

/* ════════════════════════════════════════════════════════════════
   TOASTS
   ════════════════════════════════════════════════════════════════ */

function toast(msg, tipo = 'ok') {
  const el = document.createElement('div');
  el.className = 'toast' + (tipo === 'erro' ? ' erro' : '');
  el.innerHTML = svg(tipo === 'erro' ? ICO.info : ICO.check) + `<span>${esc(msg)}</span>`;
  $('#toasts').appendChild(el);
  setTimeout(() => {
    el.classList.add('saindo');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  }, 2200);
}

/* ════════════════════════════════════════════════════════════════
   MODAL
   ════════════════════════════════════════════════════════════════ */

function modal({ titulo, texto = '', campo = null, ok = 'Confirmar', perigo = false }) {
  return new Promise(resolve => {
    const fundo = $('#modal-fundo');
    fundo.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h3>${esc(titulo)}</h3>
        ${texto ? `<p>${esc(texto)}</p>` : ''}
        ${campo !== null ? `<input class="modal-in" id="m-campo" value="${esc(campo)}">` : ''}
        <div class="modal-acoes">
          <button class="btn-linha" id="m-nao">Cancelar</button>
          <button class="btn-linha ${perigo ? '' : 'primario'}" id="m-sim"
                  ${perigo ? 'style="background:var(--erro);color:#fff;border-color:transparent"' : ''}>${esc(ok)}</button>
        </div>
      </div>`;
    fundo.hidden = false;

    const campoEl = $('#m-campo');
    if (campoEl) { campoEl.focus(); campoEl.select(); }

    const fecha = val => {
      document.removeEventListener('keydown', tecla);
      resolve(val);
      fundo.classList.add('saindo');
      // A limpeza NÃO pode depender só do animationend. Na WebView2, trocar a
      // animação pela classe às vezes não dispara o evento, e aí o
      // #modal-fundo — um overlay `position:fixed; inset:0` — nunca recebia
      // hidden e ficava por cima de TUDO comendo os cliques. Era esse o
      // congelamento depois de apagar uma conversa. O timeout é a garantia:
      // um dos dois roda, o flag impede rodar duas vezes.
      let limpou = false;
      const limpar = () => {
        if (limpou) return;
        limpou = true;
        fundo.classList.remove('saindo');
        fundo.hidden = true;
        fundo.innerHTML = '';
      };
      fundo.addEventListener('animationend', limpar, { once: true });
      setTimeout(limpar, 220);
    };
    const confirma = () => fecha(campoEl ? campoEl.value.trim() : true);
    const tecla = e => {
      if (e.key === 'Escape') { e.preventDefault(); fecha(null); }
      if (e.key === 'Enter' && campoEl) { e.preventDefault(); confirma(); }
    };

    $('#m-sim').onclick = confirma;
    $('#m-nao').onclick = () => fecha(null);
    fundo.onclick = e => { if (e.target === fundo) fecha(null); };
    document.addEventListener('keydown', tecla);
  });
}

/* ════════════════════════════════════════════════════════════════
   MODO DEMO — a UI só sinaliza e solicita; o isolamento é do backend.
   ════════════════════════════════════════════════════════════════ */

function aplicarBloqueiosDemo() {
  const bloqueados = ['#btn-add', '#btn-remoto', '#btn-mic', '#btn-voz-texto', '#btn-tela', '#btn-github',
    '#cloud-storage', '#cloud-upload', '#sel-modelo', '#sel-racio'];
  bloqueados.forEach(seletor => {
    const el = $(seletor);
    if (!el) return;
    if (!el.dataset.demoTitulo) el.dataset.demoTitulo = el.title || '';
    el.disabled = !!ESTADO.demo;
    el.title = ESTADO.demo
      ? 'Ação real bloqueada durante o Modo Demo'
      : el.dataset.demoTitulo;
  });
}

function aplicarModoDemo(estado = {}) {
  ESTADO.demo = !!estado.ativo;
  if (ESTADO.demo) ESTADO.remoto = false;
  else {
    try { ESTADO.remoto = localStorage.getItem('emily_remoto') === '1'; }
    catch (_) { ESTADO.remoto = false; }
  }
  document.body.classList.toggle('modo-demo', ESTADO.demo);
  const botao = $('#btn-demo');
  if (botao) {
    botao.classList.toggle('ativo', ESTADO.demo);
    botao.setAttribute('aria-pressed', String(ESTADO.demo));
    botao.title = ESTADO.demo ? 'Encerrar a sessão pública isolada' : 'Iniciar uma sessão pública isolada';
  }
  const texto = $('#btn-demo-txt');
  if (texto) texto.textContent = ESTADO.demo ? 'Sair da demo' : 'Demo';
  const faixa = $('#demo-faixa');
  if (faixa) faixa.setAttribute('aria-hidden', String(!ESTADO.demo));
  const remoto = $('#btn-remoto');
  if (remoto) remoto.classList.toggle('ativo', ESTADO.remoto && !ESTADO.demo);
  const entrada = $('#entrada');
  if (entrada) entrada.placeholder = ESTADO.demo
    ? 'Converse com a Emily usando somente dados fictícios...'
    : (ESTADO.remoto ? 'Falando com a Emily do celular...' : 'Fala com a Emily...');
  aplicarBloqueiosDemo();
  if (ESTADO.agenteUI) aplicarEstadoAgenteUI(ESTADO.agenteUI);
}

function suspenderPlayerSemPersistir() {
  if (typeof Player === 'undefined') return;
  Player._pararTimer();
  Player._ignorarEventos = true;
  try { Player.player && Player.player.stopVideo(); } catch {}
  const barra = $('#player-barra'); if (barra) barra.hidden = true;
  const modalPlayer = $('#modal-player'); if (modalPlayer) modalPlayer.hidden = true;
  document.body.classList.remove('com-player');
  document.getElementById('player-resgate')?.remove();
  Player.playlist = [];
  Player.indice = -1;
  Player._faixaAtual = null;
  Player._videoEsperado = null;
  Player.tocando = false;
}

async function recarregarAposModoDemo() {
  fecharPop();
  ESTADO.atual = null;
  ESTADO.anexos = [];
  ESTADO.textoStream = '';
  ESTADO.falasProcesso = [];
  if (typeof CLOUD !== 'undefined') {
    CLOUD.parent = ''; CLOUD.filtro = 'arquivos'; CLOUD.busca = '';
    CLOUD.itens = []; CLOUD.breadcrumb = []; CLOUD.status = {};
    CLOUD.selecionado = ''; CLOUD.selecionados.clear(); CLOUD.assinaturaItens = '';
  }
  if (typeof _codePendentes !== 'undefined') _codePendentes.clear();
  if (typeof _codeConversas !== 'undefined') _codeConversas = [];
  if (typeof _codeConversaAtiva !== 'undefined') _codeConversaAtiva = '';

  const perfil = await tenta('perfil') || {};
  const nome = perfil.nome || (ESTADO.demo ? 'Visitante' : 'Vitor');
  const perfilNome = $('#perfil-nome'); if (perfilNome) perfilNome.textContent = nome;
  const perfilAv = $('#perfil-av');
  if (perfilAv) {
    if (perfil.avatar_usuario) perfilAv.innerHTML = `<img src="${perfil.avatar_usuario}" alt="">`;
    else perfilAv.textContent = nome[0]?.toUpperCase() || 'V';
  }

  await Promise.all([
    recarregarConversas(), recarregarCodeConversas(), carregarSeletores(), carregarGeral(),
  ]);
  if (typeof Player !== 'undefined') {
    Player._ignorarEventos = false;
    await Player.carregarPlaylist();
    await Player.restaurar();
  }
  const destino = ESTADO.tela === 'chat' ? 'inicio' : ESTADO.tela;
  irPara(destino || 'inicio', { forcar: true });
  aplicarBloqueiosDemo();
}

async function alternarModoDemo() {
  if (ESTADO.demoAlternando) return;
  const saindo = ESTADO.demo;
  const confirmou = await modal({
    titulo: saindo ? 'Encerrar o Modo Demo?' : 'Iniciar o Modo Demo?',
    texto: saindo
      ? 'Chats, arquivos e alterações fictícias serão descartados. Seu contexto pessoal será restaurado.'
      : 'A Emily trocará para dados fictícios e um workspace temporário. Memória, arquivos e ações pessoais ficarão isolados.',
    ok: saindo ? 'Encerrar demo' : 'Iniciar demo',
    perigo: saindo,
  });
  if (!confirmou) return;
  ESTADO.demoAlternando = true;
  const botao = $('#btn-demo'); if (botao) botao.disabled = true;
  suspenderPlayerSemPersistir();
  const resultado = await tenta(saindo ? 'encerrar_demo' : 'iniciar_demo');
  ESTADO.demoAlternando = false;
  if (botao) botao.disabled = false;
  if (!resultado?.ok) {
    toast(resultado?.erro || 'Não consegui alternar o Modo Demo.', 'erro');
    if (typeof Player !== 'undefined') { Player._ignorarEventos = false; await Player.restaurar(); }
    return;
  }
  aplicarModoDemo(resultado);
  await recarregarAposModoDemo();
  toast(ESTADO.demo ? 'Modo Demo ativo: somente dados fictícios' : 'Modo Demo encerrado');
}

/* ════════════════════════════════════════════════════════════════
   NAVEGAÇÃO ENTRE TELAS
   O composer é UM só e é movido de tela em tela, pra o que estava
   digitado não se perder na transição.
   ════════════════════════════════════════════════════════════════ */

/* Monta a tela na hora, SÍNCRONO.

   A primeira versão esperava o `animationend` da tela velha pra montar a
   nova, com um setTimeout de segurança. Isso criava uma corrida: quem
   chamava irPara() e logo depois procurava um elemento da tela nova às
   vezes achava a tela velha ainda no lugar — foi assim que abrir uma
   conversa deixava o chat vazio. Agora a nova entra imediatamente e a
   animação de entrada dela é que faz a transição. */
let _navegacaoGeracao = 0;
function irPara(tela, { forcar = false } = {}) {
  if (ESTADO.tela === tela && !forcar) return;
  ++_navegacaoGeracao;
  if (tela !== 'inicio' && typeof _desligarHeroSub === 'function') _desligarHeroSub();
  const palco = $('#palco');

  /* O composer VIVE dentro da tela, então limpar o palco o destruiria
     junto — com ele o texto digitado e os anexos em espera. Antes de
     limpar, ele é posto em segurança fora do palco. */
  const composer = $('#composer');
  if (composer) document.body.appendChild(composer);

  palco.innerHTML = '';
  if (tela !== 'code') ++_codeMontagem; // cancela awaits/typing do Code anterior
  _naTelaCode = false;   // Emily Code: desliga flag quando troca de tela
  // Tema global: quando a tela do Emily Code está ativa, a sidebar, a barra
  // e o fundo escurecem pra acompanhar o estilo terminal.
  document.body.classList.toggle('modo-code', tela === 'code');
  document.body.classList.toggle('modo-cloud', tela === 'cloud');
  document.body.classList.toggle('modo-config', tela === 'config');
  const novoRotulo = $('#btn-novo span');
  const busca = $('#busca');
  if (novoRotulo) novoRotulo.textContent = tela === 'code' ? 'Nova sessão' : 'Nova conversa';
  if (busca) busca.placeholder = tela === 'code' ? 'Buscar sessão de código' : 'Buscar conversa';
  if (tela === 'config') {
    palco.appendChild(telaConfig());
  } else if (tela === 'perfil') {
    palco.appendChild(telaPerfil());
  } else if (tela === 'code') {
    const tpl = $('#tpl-code');
    palco.appendChild(tpl.content.cloneNode(true));
    // Foco SÍNCRONO no campo do terminal. O template é clonado via JS, então
    // o `autofocus` do HTML não dispara (o parser não roda nele); e o
    // montarCode() é async, então o foco dentro dele só acontece depois do
    // primeiro await — nesse meio tempo o usuário digita e nada entra. Focar
    // aqui garante que a primeira tecla caia no campo.
    const campo = $('#code-campo');
    if (campo) campo.focus();
    montarCode();
  } else if (tela === 'cloud') {
    palco.appendChild(telaCloud());
    montarCloud();
  } else {
    const tpl = $(tela === 'chat' ? '#tpl-chat' : '#tpl-inicio');
    palco.appendChild(tpl.content.cloneNode(true));
    const vaga = $(tela === 'chat' ? '#composer-vaga-chat' : '#composer-vaga-inicio');
    if (vaga && composer) vaga.appendChild(composer);
    if (tela === 'chat') ligarFluxo(); else montarInicio();
    ajustarEntrada();
  }
  ESTADO.tela = tela;
  if (tela === 'config') montarNavegacaoConfig();
  aplicarBloqueiosDemo();
  $('#btn-config').classList.toggle('ativa', tela === 'config');
  $('#btn-cloud')?.classList.toggle('ativo', tela === 'cloud');
  if (!['chat', 'inicio'].includes(tela)) fecharPainelNavegador(false);
  // A sidebar é compartilhada. Sem redesenhar aqui, os cartões Code ficavam
  // visíveis no tema normal até a próxima chamada de rede.
  desenharConversas();
}

/* ── Detalhes vivos da tela inicial ────────────────────────────
   Cumprimento muda com a hora, relógio atualiza sozinho e o
   subtítulo roda entre variações. Nada de servidor: são só
   detalhes de presença pra tela não parecer um cartaz parado. */

function _periodoDoDia(h) {
  if (h >= 5 && h < 12)  return 'Bom dia';
  if (h >= 12 && h < 18) return 'Boa tarde';
  return 'Boa noite';
}

// Relógio do hero. A cada tique, PROCURA o elemento de novo: se a
// tela mudou e ele não existe mais, o timer se cancela sozinho.
function _ligarHeroHora() {
  const el = document.getElementById('hero-hora');
  if (!el) return;
  const tique = () => {
    const alvo = document.getElementById('hero-hora');
    if (!alvo) { clearInterval(_heroHoraTimer); _heroHoraTimer = null; return; }
    const agora = new Date();
    const dias = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
    alvo.textContent = `${dias[agora.getDay()]} · ` +
      `${String(agora.getHours()).padStart(2, '0')}:${String(agora.getMinutes()).padStart(2, '0')}`;
  };
  tique();
  if (_heroHoraTimer) clearInterval(_heroHoraTimer);
  _heroHoraTimer = setInterval(tique, 30_000);
}
let _heroHoraTimer = null;

// Subtítulo rotativo: troca a frase com crossfade, e para no hover
// (ninguém lê um texto que foge de baixo do mouse).
const HERO_SUBS = [
  'No que a gente mexe agora?',
  'Tô por aqui — é só falar.',
  'Me diz o que precisa hoje.',
  'Pronta quando você estiver.',
];
let _heroSubTimer = null;
let _heroSubTrocaTimer = null;
function _desligarHeroSub() {
  if (_heroSubTimer) clearInterval(_heroSubTimer);
  if (_heroSubTrocaTimer) clearTimeout(_heroSubTrocaTimer);
  _heroSubTimer = null;
  _heroSubTrocaTimer = null;
}
function _ligarHeroSub() {
  const el = document.getElementById('hero-sub');
  if (!el) return;
  _desligarHeroSub();
  let i = 0, pausado = false;
  el.addEventListener('mouseenter', () => { pausado = true; });
  el.addEventListener('mouseleave', () => { pausado = false; });
  const tique = () => {
    const alvo = document.getElementById('hero-sub');
    if (!alvo || alvo !== el) { _desligarHeroSub(); return; }
    if (pausado) return;
    i = (i + 1) % HERO_SUBS.length;
    alvo.classList.add('troca');
    if (_heroSubTrocaTimer) clearTimeout(_heroSubTrocaTimer);
    _heroSubTrocaTimer = setTimeout(() => {
      _heroSubTrocaTimer = null;
      if (!alvo.isConnected || document.getElementById('hero-sub') !== alvo) return;
      alvo.textContent = HERO_SUBS[i];
      alvo.classList.remove('troca');
    }, 260);
  };
  _heroSubTimer = setInterval(tique, 6000);
}

async function montarInicio() {
  const perfil = await tenta('perfil') || {};
  const nome = perfil.nome || 'Vitor';
  $('#hero-nome').textContent = nome;
  // A saudação acompanha a hora em que ele abriu a Emily.
  const oi = $('.hero-oi');
  if (oi) {
    const primeiro = oi.firstChild; // nó de texto "Bom dia, " antes do <span>
    if (primeiro && primeiro.nodeType === Node.TEXT_NODE) {
      primeiro.textContent = `${_periodoDoDia(new Date().getHours())}, `;
    }
  }
  // O hero mostra o RETRATO da Emily, não a foto do usuário.
  if (perfil.avatar) $('#hero-img').src = perfil.avatar;

  _ligarHeroHora();
  _ligarHeroSub();

  const btnLogs = $('#btn-logs');
  if (btnLogs) {
    btnLogs.onclick = abrirLogs;
    // Uma leitura leve deixa o cartão dizer se o túnel subiu antes de abrir.
    tenta('logs_ler').then(d => atualizarResumoLogs(d));
  }

  const sugs = await tenta('sugestoes') || [];
  const alvo = $('#sugestoes');
  if (!alvo) return;
  alvo.innerHTML = '';
  sugs.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'sugestao';
    b.style.animationDelay = `${320 + i * 70}ms`;
    b.innerHTML = svg(ICO[s.icone] || ICO.raio) +
      `<span>${esc(s.texto)}</span>` + svg(ICO.seta, 'sugestao-seta');
    b.onclick = () => { $('#entrada').value = s.texto; ajustarEntrada(); enviar(); };
    alvo.appendChild(b);
  });
}

/* ════════════════════════════════════════════════════════════════
   LOGS AO VIVO
   A mesma saída vista no Konsole/VS Code é lida do arquivo unificado.
   Atualiza enquanto o painel está aberto e preserva a rolagem de quem
   subiu pra investigar uma linha antiga.
   ════════════════════════════════════════════════════════════════ */

let _logsTimer = null;
let _logsTecla = null;

function _tamLog(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function _rotuloNgrok(ngrok = {}) {
  const estado = ngrok.estado || 'parado';
  if (estado === 'online') return { classe: 'online', texto: 'ngrok online' };
  if (estado === 'erro') return { classe: 'erro', texto: 'ngrok com erro' };
  if (estado === 'iniciando' || estado === 'aguardando') {
    return { classe: 'iniciando', texto: 'ngrok iniciando' };
  }
  return { classe: 'parado', texto: 'ngrok parado' };
}

function atualizarResumoLogs(dados) {
  if (!dados) return;
  const el = $('#inicio-logs-status');
  const btn = $('#btn-logs');
  if (!el || !btn) return;
  if (dados.ngrok_disponivel === false) {
    el.textContent = 'Terminal e erros da Emily';
    btn.dataset.ngrok = 'inativo';
  } else {
    const ng = _rotuloNgrok(dados.ngrok);
    el.textContent = ng.texto;
    btn.dataset.ngrok = ng.classe;
  }
}

function fecharLogs() {
  const fundo = $('#logs-fundo');
  if (_logsTimer) { clearInterval(_logsTimer); _logsTimer = null; }
  if (_logsTecla) { document.removeEventListener('keydown', _logsTecla); _logsTecla = null; }
  if (!fundo || fundo.hidden) return;
  fundo.classList.add('saindo');
  let limpou = false;
  const limpar = () => {
    if (limpou) return;
    limpou = true;
    fundo.classList.remove('saindo');
    fundo.hidden = true;
    fundo.innerHTML = '';
  };
  fundo.addEventListener('animationend', limpar, { once: true });
  setTimeout(limpar, 220);
}

async function atualizarLogs({ forcarFim = false } = {}) {
  const saida = $('#logs-saida');
  if (!saida) return;
  const pertoDoFim = saida.scrollHeight - saida.scrollTop - saida.clientHeight < 80;
  const dados = await tenta('logs_ler');
  if (!dados || !$('#logs-saida')) return;
  atualizarResumoLogs(dados);

  const texto = dados.texto || 'O arquivo ainda está vazio. As próximas mensagens aparecem aqui.';
  if (saida.textContent !== texto) saida.textContent = texto;
  if (forcarFim || pertoDoFim) saida.scrollTop = saida.scrollHeight;

  const temNgrok = dados.ngrok_disponivel !== false;
  const ng = temNgrok ? _rotuloNgrok(dados.ngrok) : null;
  const status = $('#logs-ngrok');
  if (status) {
    status.hidden = !temNgrok;
    if (temNgrok) {
      status.className = `logs-servico ${ng.classe}`;
      status.querySelector('strong').textContent = ng.texto;
      const detalhe = dados.ngrok?.url || dados.ngrok?.erro ||
        (dados.ngrok?.executavel ? `Executável: ${dados.ngrok.executavel}` : 'Aguardando diagnóstico');
      status.querySelector('small').textContent = detalhe;
    }
  }
  const repetir = $('#logs-repetir-ngrok');
  if (repetir) {
    repetir.hidden = !temNgrok || ng.classe !== 'erro';
    if (temNgrok && ng.classe === 'erro') {
      repetir.disabled = false;
      repetir.textContent = 'Tentar novamente';
    }
  }
  const meta = $('#logs-meta');
  if (meta) meta.textContent = `${dados.caminho || 'log'} · ${_tamLog(dados.tamanho)}`;
}

async function abrirLogs() {
  const fundo = $('#logs-fundo');
  if (!fundo) return;
  if (_logsTimer) clearInterval(_logsTimer);
  fundo.innerHTML = `
    <section class="logs-modal" role="dialog" aria-modal="true" aria-label="Logs ao vivo da Emily">
      <header class="logs-topo">
        <div class="logs-semaforo" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="logs-titulo">
          <strong>Terminal da Emily</strong>
          <small id="logs-meta">Carregando o arquivo de log…</small>
        </div>
        <button class="logs-fechar" id="logs-fechar" title="Fechar">${svg(ICO.x)}</button>
      </header>
      <div class="logs-servicos">
        <div class="logs-servico iniciando" id="logs-ngrok" hidden>
          <span class="logs-servico-ponto"></span>
          <span><strong>Verificando conexão</strong><small>Aguardando diagnóstico</small></span>
        </div>
        <button class="logs-repetir" id="logs-repetir-ngrok" hidden>Tentar novamente</button>
        <span class="logs-ao-vivo"><i></i> ao vivo</span>
      </div>
      <pre class="logs-saida" id="logs-saida" tabindex="0">Carregando…</pre>
      <footer class="logs-acoes">
        <span>Credenciais são ocultadas antes de aparecer aqui.</span>
        <div>
          <button class="btn-linha" id="logs-limpar">${svg(ICO.lixo)} Limpar</button>
          <button class="btn-linha" id="logs-copiar">${svg(ICO.copiar)} Copiar</button>
          <button class="btn-linha primario" id="logs-atualizar">${svg(ICO.refazer)} Atualizar</button>
        </div>
      </footer>
    </section>`;
  fundo.hidden = false;
  fundo.classList.remove('saindo');

  $('#logs-fechar').onclick = fecharLogs;
  fundo.onclick = e => { if (e.target === fundo) fecharLogs(); };
  _logsTecla = e => {
    if (e.key === 'Escape' && $('#modal-fundo')?.hidden) {
      e.preventDefault();
      fecharLogs();
    }
  };
  document.addEventListener('keydown', _logsTecla);
  $('#logs-atualizar').onclick = () => atualizarLogs({ forcarFim: true });
  $('#logs-repetir-ngrok').onclick = async e => {
    e.currentTarget.disabled = true;
    e.currentTarget.textContent = 'Tentando…';
    const ok = await tenta('logs_reiniciar_ngrok');
    toast(ok ? 'Nova tentativa do ngrok iniciada.' : 'O ngrok já está iniciando.',
          ok ? 'ok' : 'erro');
    await atualizarLogs({ forcarFim: true });
  };
  $('#logs-copiar').onclick = async () => {
    await tenta('copiar', $('#logs-saida')?.textContent || '');
    toast('Logs copiados.');
  };
  $('#logs-limpar').onclick = async e => {
    const botao = e.currentTarget;
    if (botao.dataset.confirma !== '1') {
      botao.dataset.confirma = '1';
      botao.classList.add('perigo');
      botao.innerHTML = `${svg(ICO.lixo)} Confirmar limpeza`;
      setTimeout(() => {
        if (!botao.isConnected) return;
        delete botao.dataset.confirma;
        botao.classList.remove('perigo');
        botao.innerHTML = `${svg(ICO.lixo)} Limpar`;
      }, 3500);
      return;
    }
    const ok = await tenta('logs_limpar');
    toast(ok ? 'Histórico de logs limpo.' : 'Não consegui limpar o log.', ok ? 'ok' : 'erro');
    await atualizarLogs({ forcarFim: true });
  };
  await atualizarLogs({ forcarFim: true });
  if ($('#logs-saida')) $('#logs-saida').focus();
  _logsTimer = setInterval(() => atualizarLogs(), 1000);
}

/* ════════════════════════════════════════════════════════════════
   EMILY CODE — tela estilo terminal
   Cada mensagem vira uma linha de prompt (PS Emily:\CodeSession>),
   com boot sequence e animação char a char no estilo Windows Terminal.
   ════════════════════════════════════════════════════════════════ */

let _codeConversaAtiva = '';  // id da conversa cujo terminal está aberto
let _codeMontagem = 0;         // invalida awaits de uma tela/conversa anterior
const _codePendentes = new Set(); // cids com resposta em andamento
const _codeRenderizando = new Set(); // resposta final animando no terminal

function _codeEstaPendente(cid = _codeConversaAtiva) {
  return !!cid && (_codePendentes.has(cid) || _codeRenderizando.has(cid));
}

function _codeAtualizarExecucao() {
  const pendente = _codeEstaPendente();
  const estado = $('#code-run-state');
  if (estado) {
    estado.classList.toggle('rodando', pendente);
    const txt = $('span', estado);
    if (txt) txt.textContent = pendente ? 'Executando' : 'Pronta';
  }
  const campo = $('#code-campo');
  if (campo) campo.disabled = pendente;
}

function _codeAtualizarProjeto(caminho = '') {
  const chip = $('#code-projeto-chip');
  if (!chip) return;
  const texto = caminho ? String(caminho).replace(/\\/g, '/').split('/').filter(Boolean).pop() : 'Sem projeto';
  const alvo = $('span', chip);
  if (alvo) alvo.textContent = texto || caminho;
  chip.title = caminho || 'Nenhum projeto definido nesta conversa';
  chip.classList.toggle('vazio', !caminho);
}

function _codeAdicionarPensando(cid = _codeConversaAtiva) {
  const saida = $('#code-saida');
  if (!saida || !cid || cid !== _codeConversaAtiva
      || $(`.code-pensando[data-cid="${CSS.escape(cid)}"]`, saida)) return null;
  const pensando = document.createElement('div');
  pensando.className = 'code-pensando';
  pensando.dataset.cid = cid;
  pensando.innerHTML = `<span class="code-pensando-core"><i></i><i></i><i></i></span>` +
    `<span><strong>Emily está analisando</strong><small>mapeando contexto e preparando ações</small></span>`;
  saida.appendChild(pensando);
  codeRolarFim();
  return pensando;
}

function _codeTokenValido(token, saida = $('#code-saida')) {
  return token === _codeMontagem && _naTelaCode && saida?.isConnected;
}

async function montarCode() {
  const token = ++_codeMontagem;
  _naTelaCode = true;
  const saida = $('#code-saida');
  if (!saida) return;
  saida.innerHTML = '';
  // Reseta o estado das ações e da barra de status pra sessão nova.
  _codeAcoes = [];
  _codeInicioSessao = Date.now();
  codeAtualizarStatus();

  // Restaura a conversa ativa (com histórico) ou faz o boot numa nova.
  await recarregarCodeConversas();
  if (!_codeTokenValido(token, saida)) return;
  const ativa = _codeConversas.find(c => c.ativa);
  if (ativa && ativa.quantas > 0) {
    await montarCodeHist(ativa.id, token);
  } else {
    // Conversa nova (sem histórico): define a ativa como referência das
    // respostas que vão chegar, e faz o boot.
    if (ativa) _codeConversaAtiva = ativa.id;
    _codeAtualizarProjeto(ativa?.projeto || '');
    codeBoot(token);
  }

  const campo = $('#code-campo');
  const cursor = $('#code-cursor');
  const barra = $('#code-input');
  const atualizaCursor = () => {
    // Bloco piscante só quando o campo está vazio (no fim do prompt).
    // Com texto, o caret nativo do input (verde) acompanha a digitação.
    const vazio = !campo.value;
    if (cursor) cursor.style.display = vazio ? 'inline' : 'none';
    if (barra) barra.classList.toggle('campo-vazio', vazio);
    campo.classList.toggle('tem-texto', !vazio);
  };
  campo.value = '';
  campo.focus();
  campo.onkeydown = e => {
    if (e.key === 'Enter') { e.preventDefault(); codeEnviar(); }
  };
  campo.oninput = atualizaCursor;
  campo.addEventListener('keyup', atualizaCursor);
  atualizaCursor();
  _codeAtualizarExecucao();

  // Clicar na área de saída do terminal (ou no próprio contêiner do terminal)
  // devolve o foco pro campo — assim um clique em qualquer lugar do terminal
  // volta a permitir digitar, sem depender só do foco inicial.
  const term = $('#code-term');
  if (term) {
    term.onclick = () => { if (!campo.disabled) campo.focus(); };
    term.style.cursor = 'text';
  }
}

// Recarrega o terminal com o histórico da conversa do code que abriu.
// Recebe o id da conversa clicada (não confia no cache de metadados,
// que pode estar desatualizado quanto a qual é a ativa).
async function montarCodeHist(cid, token = ++_codeMontagem) {
  const saida = $('#code-saida');
  if (!saida) return;
  if (!cid) {
    const ativa = _codeConversas.find(c => c.ativa);
    cid = ativa && ativa.id;
  }
  if (cid) {
    _codeConversaAtiva = cid;
    const msgs = await tenta('code_abrir_conversa', cid) || [];
    if (!_codeTokenValido(token, saida) || cid !== _codeConversaAtiva) return;
    saida.innerHTML = '';
    // Prefixa a conversa com a linha "Projeto: ..." pra manter o contexto de
    // onde as ferramentas do Emily Code operam.
    const meta = _codeConversas.find(c => c.id === cid);
    _codeAtualizarProjeto(meta?.projeto || '');
    if (meta && meta.projeto) {
      saida.appendChild(codeCriarLinha(`Projeto: ${meta.projeto}`, 'term-boot-linha'));
      codeRolarFim();
    }
    for (const m of msgs) codeRenderMensagem(m.papel === 'user' ? 'user' : 'emily', m.texto || '');
    if (_codeEstaPendente(cid)) _codeAdicionarPensando(cid);
    _codeAtualizarExecucao();
  }
  codeRolarFim();
}

// Boot sequence: 3 linhas aparecendo uma a uma, estilo terminal.
async function codeBoot(token = _codeMontagem) {
  const saida = $('#code-saida');
  if (!saida) return;
  const linhas = [
    { txt: 'Inicializando Emily Code...', cls: '' },
    { txt: 'Carregando módulo Qwen 3.8...', cls: '' },
    { txt: 'Carregando módulo MiniMax-M3...', cls: '' },
  ];
  for (const l of linhas) {
    if (!_codeTokenValido(token, saida)) return;
    const el = codeCriarLinha(l.txt, 'term-boot-linha');
    saida.appendChild(el);
    codeRolarFim();
    await esperar(350);
  }
  // Linha "Pronto." com OK verde.
  const ok = codeCriarLinha('Pronto.', 'term-boot-linha');
  ok.innerHTML += ' <span class="term-boot-ok">OK</span>';
  saida.appendChild(ok);
  codeRolarFim();
  await esperar(300);
  if (!_codeTokenValido(token, saida)) return;
  // Mostra uma linha em branco + prompt pronto.
  codeCriarLinha('', 'term-linha');
  codeRolarFim();
  await codeAvisoProjeto(token);
}

/* Aviso de pasta de projeto: sem pasta definida, as ferramentas do Emily Code
   não têm onde trabalhar. A pergunta aparece com um botão "Escolher pasta…"
   na MESMA linha (abre o explorar nativo); também dá pra digitar o caminho.
   Ao definir, aviso e botão somem, vira a linha "Projeto: ..." e a Emily
   solta a mensagem de boas-vindas do sistema. */
async function codeAvisoProjeto(token = _codeMontagem) {
  const cid = _codeConversaAtiva;
  const estado = await tenta('emily_code_estado', cid);
  const saidaAtual = $('#code-saida');
  if (!_codeTokenValido(token, saidaAtual)) return;
  if (!estado || estado.projeto) {
    if (estado && estado.projeto) {
      const saida = $('#code-saida');
      if (saida) {
        _codeAtualizarProjeto(estado.projeto);
        saida.appendChild(codeCriarLinha(`Projeto: ${estado.projeto}`, 'term-boot-linha'));
        codeRolarFim();
      }
    }
    return;
  }
  await codeMostrarAvisoPasta('Nenhuma pasta de projeto definida. Onde está o seu projeto?', { boasVindas: true });
}

/* Aviso reutilizável: mostra a pergunta + campo + botão "Escolher pasta…" no
   terminal. Opções:
   - boasVindas (bool): se true, chama codeBoasVindas() após definir
   - podeCancelar (bool): se true, mostra botão Cancelar (pra troca de pasta)
   - padrao (string): valor pré-preenchido no campo
   O aviso some e vira "Projeto: ..." ao confirmar, ou é removido ao cancelar. */
async function codeMostrarAvisoPasta(mensagem, { boasVindas = true, podeCancelar = false, padrao = '' } = {}) {
  const saida = $('#code-saida');
  if (!saida) return;
  const aviso = document.createElement('div');
  aviso.className = 'term-linha term-projeto';
  aviso.innerHTML =
    `<span class="term-projeto-topo">` +
    `<span class="term-projeto-txt">${esc(mensagem || '')}</span>` +
    `<button type="button" class="term-projeto-btn" title="Escolher no explorar">` +
    `${svg(ICO.pasta)}<span>Escolher pasta…</span></button>` +
    (podeCancelar ? `<button type="button" class="term-projeto-btn term-projeto-cancelar" title="Cancelar">Cancelar</button>` : '') +
    `</span>` +
    `<span class="term-projeto-in"><span class="code-prompt">&gt;</span>` +
    `<input type="text" class="code-campo term-projeto-campo" spellcheck="false" ` +
    `placeholder="ex: C:\\Users\\conti\\projetos\\meu-app"></span>`;
  saida.appendChild(aviso);
  codeRolarFim();
  const campo = $('.term-projeto-campo', aviso);
  if (padrao) campo.value = padrao;
  campo.focus();
  const definir = async caminho => {
    if (!caminho) return false;
    campo.disabled = true;
    const cid = _codeConversaAtiva;
    const r = await tenta('emily_code_definir_projeto', caminho, cid);
    if (String(r || '').startsWith('Pasta de projeto definida')) {
      const caminhoDefinido = String(r).replace('Pasta de projeto definida: ', '');
      _codeAtualizarProjeto(caminhoDefinido);
      aviso.classList.add('saindo');
      await esperar(200);
      const el = codeCriarLinha(`Projeto: ${caminhoDefinido}`, 'term-boot-linha');
      aviso.replaceWith(el);
      codeRolarFim();
      toast('Pasta de projeto definida');
      recarregarCodeConversas();
      if (boasVindas) await codeBoasVindas();
      $('#code-campo')?.focus();
      return true;
    }
    // Falhou: mostra o motivo e deixa tentar de novo.
    const el = codeCriarLinha(String(r || 'Não consegui definir.'), 'term-sistema');
    aviso.appendChild(el);
    codeRolarFim();
    campo.disabled = false;
    campo.focus();
    return false;
  };
  const salvar = async () => {
    const caminho = campo.value.trim();
    if (!caminho) return;
    await definir(caminho);
  };
  $('.term-projeto-btn', aviso).onclick = async () => {
    const pasta = await tenta('emily_code_escolher_pasta');
    if (pasta) {
      campo.value = pasta;
      await definir(pasta);
    }
  };
  if (podeCancelar) {
    $('.term-projeto-cancelar', aviso).onclick = () => {
      tenta('emily_code_cancelar_pasta');
      aviso.classList.add('saindo');
      setTimeout(() => {
        const el = codeCriarLinha('', 'term-linha');
        aviso.replaceWith(el);
        codeRolarFim();
        $('#code-campo')?.focus();
      }, 200);
    };
  }
  campo.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); salvar(); } };
}

/* Boas-vindas do Emily Code: vibe de sistema antigo. Uma sequência curta de
   linhas "de boot" seguida do resumo (markdown bonito) do que ela sabe fazer
   ali e os atalhos. Resumida — é um hello, não um manual. */
async function codeBoasVindas() {
  const saida = $('#code-saida');
  if (!saida) return;
  const linhas = [
    { txt: 'Bem-vindo ao Emily Code v1.0', cls: 'term-boot-linha' },
    { txt: 'Sessão de código inicializada. Ambiente pronto.', cls: 'term-boot-linha' },
  ];
  for (const l of linhas) {
    const el = codeCriarLinha(l.txt, l.cls);
    saida.appendChild(el);
    codeRolarFim();
    await esperar(300);
  }
  const resumo =
    '**Sobre o que eu posso fazer aqui:**\n' +
    '- Ler, escrever, editar e apagar arquivos do seu projeto\n' +
    '- Buscar texto e arquivos, ver a estrutura de pastas\n' +
    '- Executar comandos e scripts no diretório do projeto\n\n' +
    '**Atalhos:**\n' +
    '- `Ctrl+Shift+K` — abre o Emily Code\n' +
    '- Pergunto antes de qualquer escrita ou execução; escolha "Permitir sempre" pra agilizar as próximas\n\n' +
    '*É só pedir. Manda o primeiro comando!*';
  await codeExibirResposta(resumo);
  codeRolarFim();
}

function codeCriarLinha(texto, cls = 'term-linha') {
  const el = document.createElement('div');
  el.className = cls;
  el.textContent = texto;
  return el;
}

function codeRenderMensagem(autor, texto, { animar = false, cid = _codeConversaAtiva } = {}) {
  const saida = $('#code-saida');
  if (!saida || (cid && cid !== _codeConversaAtiva)) return null;
  const emily = autor === 'emily';
  const linha = document.createElement('article');
  linha.className = `term-mensagem term-${emily ? 'emily' : 'user'}`;
  linha.innerHTML = `<header class="term-mensagem-cab">` +
    `<span class="term-identidade">${emily ? 'EM' : 'YOU'}</span>` +
    `<span>${emily ? 'Emily' : 'Você'}</span>` +
    `<span class="term-mensagem-meta">${emily ? 'assistant.core' : 'workspace.request'}</span>` +
    `</header><div class="term-mensagem-corpo"></div>`;
  const corpo = $('.term-mensagem-corpo', linha);
  if (emily) corpo.innerHTML = markdown(String(texto || '').trim());
  else corpo.textContent = String(texto || '').trim();
  if (animar) linha.classList.add('entrando');
  saida.appendChild(linha);
  codeRolarFim();
  return linha;
}

function codeRolarFim() {
  const term = $('#code-term');
  if (term) term.scrollTop = term.scrollHeight;
}

function esperar(ms) { return new Promise(r => setTimeout(r, ms)); }

async function codeEnviar() {
  const campo = $('#code-campo');
  const texto = (campo.value || '').trim();
  if (!texto) return;
  let cid = _codeConversaAtiva;
  if (!cid) {
    cid = await tenta('code_criar_conversa', '');
    if (!cid) { toast('Não consegui criar a sessão de código', 'erro'); return; }
    _codeConversaAtiva = cid;
  }
  if (_codeEstaPendente(cid)) return;
  _codePendentes.add(cid);
  _codeAtualizarExecucao();

  const saida = $('#code-saida');
  codeRenderMensagem('user', texto, { animar: true, cid });
  campo.value = '';

  // Placeholder da conversa de origem. O data-cid impede uma resposta antiga
  // de remover o indicador de outra sessão.
  const pensando = _codeAdicionarPensando(cid);
  const ack = await tenta('emily_code_enviar', texto, cid);
  if (!ack || ack.ok === false) {
    _codePendentes.delete(cid);
    pensando?.remove();
    _codeAtualizarExecucao();
    codeRenderMensagem('emily', ack?.erro || 'Deu problema no Emily Code.', { animar: true, cid });
    return;
  }
  if (ack.cid && ack.cid !== cid) {
    _codePendentes.delete(cid);
    cid = ack.cid;
    _codeConversaAtiva = cid;
    _codePendentes.add(cid);
    if (pensando) pensando.dataset.cid = cid;
  }
  recarregarCodeConversas();
}

// Detecta se o texto tem markdown que vale renderizar bonito.
function _temMarkdown(texto) {
  return /(\*\*|```|\*[^*\n]+\*|^#{1,6}\s|^\s*[-*+]\s+|^\s*>\s?|^\s*(?:-{3,}|\*{3,}|_{3,})\s*$|^\s*\|?.+\|.+\n\s*\|?\s*:?-{3,}|\d+[.)]\s)/m.test(texto);
}

// Digita uma resposta da Emily no terminal, char a char. Se tiver markdown,
// digita o texto cru e depois aplica o HTML bonito (negrito, código colorido).
async function codeExibirResposta(texto, cid = _codeConversaAtiva) {
  const limpo = String(texto || '').trim();
  const saida = $('#code-saida');
  if (!saida || (cid && cid !== _codeConversaAtiva)) return;
  const token = _codeMontagem;
  $$('.code-pensando', saida).forEach(el => {
    if (!el.dataset.cid || el.dataset.cid === cid) el.remove();
  });
  if (!limpo) return;

  const temMd = _temMarkdown(limpo);
  const linha = codeRenderMensagem('emily', '', { animar: true, cid });
  if (!linha) return;
  const alvo = $('.term-mensagem-corpo', linha);
  alvo.classList.add('term-digitando-texto');

  // Streaming rápido, cancelável ao trocar de sessão/tela.
  for (let i = 0; i < limpo.length; i += 7) {
    if (!_codeTokenValido(token, saida) || cid !== _codeConversaAtiva) return;
    alvo.textContent = limpo.slice(0, i + 7);
    codeRolarFim();
    await esperar(7);
  }

  alvo.classList.remove('term-digitando-texto');
  alvo.innerHTML = temMd ? markdown(limpo) : esc(limpo);
  codeRolarFim();
}

/* ════════════════════════════════════════════════════════════════
   AÇÕES EM TEMPO REAL (Emily Code)
   Cada ferramenta que a Emily executa vira uma linha de status:
   spinner Braille rodando → ✓/✗/⚠ + tempo ao concluir → seta que
   expande um bloco em box-drawing com o resultado (diff colorido,
   saída de comando, erro).
   ════════════════════════════════════════════════════════════════ */

// Descrição legível a partir do nome da ferramenta + argumentos.
// Não mostra o nome técnico (code_ler_arquivo) — mostra "lendo X (linhas Y-Z)".
function _codeDescricao(nome, args) {
  const a = args || {};
  const base = String(nome || '').replace(/^code_/, '');
  const arq = a.arquivo || a.pasta || a.comando || a.nome || a.padrao || '';
  const arqTxt = arq ? ` ${arq}` : '';

  // ler_arquivo / editar_arquivo / escrever_arquivo → verbo + arquivo
  if (base.startsWith('ler_arquivo')) {
    const ini = a.inicio || a.linha_inicio;
    const fim = a.fim || a.linha_fim;
    const faixa = (ini || fim) ? ` (${ini || ''}-${fim || ''})` : '';
    return `lendo${arqTxt}${faixa}`;
  }
  if (base.startsWith('editar_arquivo')) return `editando${arqTxt}`;
  if (base.startsWith('escrever_arquivo')) return `escrevendo${arqTxt}`;
  if (base.startsWith('apagar_arquivo')) return `apagando${arqTxt}`;
  if (base.startsWith('renomear_arquivo')) return `renomeando${arqTxt}`;
  if (base.startsWith('mover_arquivo')) return `movendo${arqTxt}`;
  if (base.startsWith('listar_arquivos')) return `listando${arqTxt}`;
  if (base.startsWith('ver_estrutura')) return 'vendo a estrutura do projeto';
  if (base.startsWith('ver_projeto')) return 'vendo o projeto';
  if (base.startsWith('buscar')) return `buscando "${arqTxt.trim()}"`;
  if (base.startsWith('achar_arquivo')) return `procurando arquivo "${arqTxt.trim()}"`;
  if (base.startsWith('executar_comando')) return `executando: ${arqTxt.trim()}`;
  if (base.startsWith('executar_script')) return `executando script${arqTxt}`;
  if (base.startsWith('perguntar')) return 'perguntando ao Vitor';
  if (base.startsWith('mudar_pasta')) return 'trocando pasta de projeto';

  // Fallback genérico: "ler_arquivo" → "ler arquivo"
  return base.replace(/_/g, ' ') || 'ação';
}

function _codeTipoAcao(nome) {
  const n = String(nome || '').replace(/^code_/, '');
  if (/^(ler|listar|ver_)/.test(n)) return { cls: 'leitura', sigla: 'READ' };
  if (/^(editar|escrever|apagar|renomear|mover|criar)/.test(n)) return { cls: 'edicao', sigla: 'EDIT' };
  if (/^(executar|rodar|testar)/.test(n)) return { cls: 'execucao', sigla: 'RUN' };
  if (/^(buscar|achar|procurar)/.test(n)) return { cls: 'busca', sigla: 'FIND' };
  if (/^(perguntar|mudar_pasta)/.test(n)) return { cls: 'interacao', sigla: 'ASK' };
  return { cls: 'sistema', sigla: 'SYS' };
}

// Estado das ações do terminal (pra medir tempo e atualizar a barra).
let _codeAcoes = [];        // {nome, el, inicio, ok, mudou, erro}
let _codeInicioSessao = Date.now();

// Adiciona uma linha de ação com spinner Braille rodando.
function codeAdicionarAcao(nome, args) {
  const saida = $('#code-saida');
  if (!saida) return;

  const desc = _codeDescricao(nome, args);
  const tipo = _codeTipoAcao(nome);
  const el = document.createElement('div');
  el.className = `code-acao rodando tipo-${tipo.cls}`;
  el.dataset.nome = nome || '';
  el.innerHTML =
    `<div class="code-acao-linha rodando">` +
      `<span class="code-acao-seta">▸</span>` +
      `<span class="code-acao-tipo">${tipo.sigla}</span>` +
      `<span class="code-acao-ico code-spinner"></span>` +
      `<span class="code-acao-desc">${esc(desc)}…</span>` +
    `</div>` +
    `<div class="code-acao-bloco"><div class="code-acao-bloco-in"></div></div>`;
  saida.appendChild(el);
  codeRolarFim();

  const acao = { nome: nome || '', el, inicio: performance.now(), ok: false, mudou: false, erro: '' };
  _codeAcoes.push(acao);
  return acao;
}

// Conclui uma ação: para o spinner, mostra ✓/✗/⚠ + tempo + seta expansível.
function codeConcluirAcao(nome, ok, mudou, erro, texto, duracao) {
  // Acha a ação mais recente com esse nome ainda rodando.
  let acao = null;
  for (let i = _codeAcoes.length - 1; i >= 0; i--) {
    if (_codeAcoes[i].nome === nome && _codeAcoes[i].el.classList.contains('rodando')) {
      acao = _codeAcoes[i];
      break;
    }
  }
  if (!acao) return;

  const el = acao.el;
  el.classList.remove('rodando');
  acao.ok = !!ok;
  acao.mudou = !!mudou;
  acao.erro = erro || '';

  // Ícone: ✓ (leitura/ok), ✗ (falha), ⚠ (escrita que mudou algo).
  let cls = 'ok', icone = '✓';
  if (!ok) { cls = 'erro'; icone = '✗'; }
  else if (mudou) { cls = 'perm'; icone = '⚠'; }
  el.classList.add(cls);

  const linha = el.querySelector('.code-acao-linha');
  const descEl = el.querySelector('.code-acao-desc');
  const tipo = _codeTipoAcao(nome);
  const tempo = (duracao != null) ? duracao
    : (performance.now() - acao.inicio) / 1000;
  const tempoTxt = tempo >= 1 ? `${tempo.toFixed(1)}s` : `${Math.round(tempo * 1000)}ms`;

  // Remove o "…" e o "rodando" do layout; a linha vira clicável.
  descEl.textContent = descEl.textContent.replace(/…$/, '');
  linha.classList.remove('rodando');
  linha.innerHTML =
    `<span class="code-acao-seta">▸</span>` +
    `<span class="code-acao-tipo">${tipo.sigla}</span>` +
    `<span class="code-acao-ico" aria-label="${cls}">${icone}</span>` +
    `<span class="code-acao-desc">${descEl.textContent}</span>` +
    `<span class="code-acao-tempo">${tempoTxt}</span>`;

  // Seta clicável expande/recolhe o bloco.
  const bloco = el.querySelector('.code-acao-bloco-in');
  linha.onclick = () => {
    el.classList.toggle('aberto');
    codeRolarFim();
  };

  // Conteúdo do bloco por tipo de ação.
  codeMontarBlocoAcao(el, bloco, nome, texto, ok, erro);
  codeAtualizarStatus();
}

// Monta o conteúdo do bloco expandido, por tipo de ação.
function codeMontarBlocoAcao(el, bloco, nome, texto, ok, erro) {
  const base = String(nome || '').replace(/^code_/, '');
  const txt = String(texto || '');
  const args = el.dataset.args || '';

  // Erro / permissão negada: fundo avermelhado sutil, erro completo.
  // A cor vem do `ok` do backend (fonte confiável), NÃO de regex sobre o
  // texto — o conteúdo de um arquivo lido pode conter "não achei"/"não
  // existe" no código, e pintava a leitura bem-sucedida de vermelho.
  if (!ok) {
    el.classList.add('erro');
    bloco.innerHTML = `<pre class="saida-cmd erro-cmd">${esc(txt || erro || 'Operação não concluída.')}</pre>`;
    return;
  }

  if (base.startsWith('editar_arquivo') || base.startsWith('escrever_arquivo')) {
    // Diff colorido: o texto que a Emily devolve pode conter um diff.
    // Se o backend mandou o diff (com +/-), pinta; senão mostra o texto.
    bloco.innerHTML = _codeRenderDiff(txt);
  } else if (base.startsWith('ler_arquivo')) {
    // Trecho lido com numeração de linha (estilo cat -n).
    bloco.innerHTML = _codeRenderLeitura(txt);
  } else if (base.startsWith('executar_comando') || base.startsWith('executar_script')) {
    // Saída de comando como terminal real.
    bloco.innerHTML = `<pre class="saida-cmd">${esc(txt)}</pre>`;
  } else if (base.startsWith('buscar') || base.startsWith('achar_arquivo')) {
    // Lista de resultados da busca.
    bloco.innerHTML = _codeRenderBusca(txt);
  } else if (base.startsWith('listar_arquivos') || base.startsWith('ver_estrutura')
             || base.startsWith('ver_projeto')) {
    bloco.innerHTML = `<pre class="saida-cmd">${esc(txt)}</pre>`;
  } else {
    bloco.innerHTML = `<pre class="saida-cmd">${esc(txt)}</pre>`;
  }
}

// Renderiza um diff unificado colorido: - vermelho, + verde, contexto neutro.
function _codeRenderDiff(txt) {
  if (!txt) return '<pre class="saida-cmd">(sem conteúdo)</pre>';
  const linhas = String(txt).split('\n');
  let html = '<pre class="code-diff">';
  let dentroCodigo = false;
  for (const ln of linhas) {
    const linha = ln.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (/^\s*```/.test(ln)) {
      dentroCodigo = !dentroCodigo;
      html += `${linha}\n`;
      continue;
    }
    if (!dentroCodigo) {
      // Fora de bloco de código: pode ser a descrição "Arquivo X (N linhas)"
      // — mostra neutro. Dentro do diff, pinta por prefixo.
      if (/^\+/.test(ln) && !/^\+\+\+/.test(ln)) html += `<span class="d-add">${linha}</span>\n`;
      else if (/^-/.test(ln) && !/^---/.test(ln)) html += `<span class="d-del">${linha}</span>\n`;
      else if (/^@@/.test(ln)) html += `<span class="d-hunk">${linha}</span>\n`;
      else html += `${linha}\n`;
    } else {
      html += `${linha}\n`;
    }
  }
  html += '</pre>';
  return html;
}

// Renderiza a leitura de arquivo com numeração de linha (estilo cat -n).
function _codeRenderLeitura(txt) {
  if (!txt) return '<pre class="saida-cmd">(sem conteúdo)</pre>';
  const linhas = String(txt).split('\n');
  let html = '<pre class="code-diff">';
  let ini = 1;
  // A primeira linha costuma ser "`arquivo` (N linhas, T):" — pula o rótulo.
  const corpoInicio = /^\s*`[^`]+`\s*\(\d+ linhas/.test(linhas[0]) ? 1 : 0;
  if (corpoInicio) {
    html += `${linhas[0].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}\n`;
    ini = 2;
  }
  for (let i = corpoInicio; i < linhas.length; i++) {
    if (linhas[i] === '') { html += '\n'; continue; }
    const num = String(i + (corpoInicio ? 0 : 0) + (corpoInicio ? 0 : ini - 1)).padStart(3, ' ');
    const conteudo = linhas[i].replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    html += `<span class="code-num">${num}</span>${conteudo}\n`;
  }
  html += '</pre>';
  return html;
}

// Renderiza resultados de busca como lista.
function _codeRenderBusca(txt) {
  if (!txt) return '<pre class="saida-cmd">(sem resultados)</pre>';
  const linhas = String(txt).split('\n');
  let html = '<pre class="code-diff">';
  let dentroCodigo = false;
  for (const ln of linhas) {
    const linha = ln.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    if (/^\s*```/.test(ln)) { dentroCodigo = !dentroCodigo; html += `${linha}\n`; continue; }
    if (dentroCodigo) { html += `${linha}\n`; continue; }
    // Linha de resultado "arquivo:linha: trecho" — destaca arquivo:linha.
    const m = /^([^:]+):(\d+):\s*(.*)$/.exec(ln);
    if (m) html += `<span class="d-add">${m[1]}:${m[2]}:</span> ${m[3]}\n`;
    else html += `${linha}\n`;
  }
  html += '</pre>';
  return html;
}

// Atualiza a barra de status do rodapé (contadores da sessão).
function codeAtualizarStatus() {
  const bar = $('#code-status-bar');
  if (!bar) return;
  const csArq = $('#cs-arquivos');
  const csErr = $('#cs-erros');
  const csTmp = $('#cs-tempo');
  if (!csArq || !csErr || !csTmp) return;

  let alterados = 0, erros = 0;
  for (const a of _codeAcoes) {
    if (a.mudou && a.ok) alterados++;
    else if (!a.ok) erros++;
  }

  const partes = [];
  if (alterados) partes.push(`${alterados} arquivo${alterados > 1 ? 's' : ''} alterado${alterados > 1 ? 's' : ''}`);
  if (erros) partes.push(`${erros} erro${erros > 1 ? 's' : ''} pendente${erros > 1 ? 's' : ''}`);

  const tempo = Math.floor((Date.now() - _codeInicioSessao) / 1000);
  const min = Math.floor(tempo / 60);
  const seg = tempo % 60;
  const tempoTxt = `${min}m${String(seg).padStart(2, '0')}s`;
  partes.push(tempoTxt);

  csArq.textContent = alterados ? `${alterados} arquivo${alterados > 1 ? 's' : ''} alterado${alterados > 1 ? 's' : ''}` : '';
  csErr.textContent = erros ? `${erros} erro${erros > 1 ? 's' : ''} pendente${erros > 1 ? 's' : ''}` : '';
  csTmp.textContent = tempoTxt;
}

function ligarFluxo() {
  const fluxo = $('#fluxo');
  if (!fluxo) return;
  fluxo.addEventListener('scroll', () => {
    const longe = fluxo.scrollHeight - fluxo.scrollTop - fluxo.clientHeight > 220;
    const btn = $('#ir-fim');
    if (btn) btn.hidden = !longe;
  });
  const btn = $('#ir-fim');
  if (btn) btn.onclick = () => rolarFim(true);
  const conteudo = $('#fluxo-in');
  if (conteudo && typeof ResizeObserver !== 'undefined') {
    // Imagens e blocos formatados podem crescer depois do evento da mensagem.
    const observador = new ResizeObserver(() => {
      if (ESTADO.tela === 'chat') rolarSePerto();
    });
    observador.observe(conteudo);
  }
}

function rolarFim(suave = false) {
  const fluxo = $('#fluxo');
  if (!fluxo) return;
  fluxo.scrollTo({ top: fluxo.scrollHeight, behavior: suave ? 'smooth' : 'auto' });
}

/* Cada mensagem e trecho da resposta acompanha o fim do chat, inclusive
   quando chegou por voz e a tela estava mostrando mensagens antigas. */
function rolarSePerto() {
  rolarFim();
  // Repete após o layout e agrupa os deltas que chegaram no mesmo frame.
  if (rolarSePerto.frame) return;
  rolarSePerto.frame = requestAnimationFrame(() => {
    rolarSePerto.frame = null;
    if (ESTADO.tela === 'chat') rolarFim();
  });
}

/* ════════════════════════════════════════════════════════════════
   MENSAGENS
   ════════════════════════════════════════════════════════════════ */

let _avatarEmily = '';

function novaMsg(autor, html, { escrevendo = false, indice = null } = {}) {
  if (ESTADO.tela !== 'chat') irPara('chat');
  const alvo = $('#fluxo-in');
  if (!alvo) return null;

  const el = document.createElement('article');
  el.className = `msg de-${autor}` + (escrevendo ? ' escrevendo' : '');
  if (Number.isInteger(indice) && indice >= 0) el.dataset.indice = String(indice);
  const av = autor === 'emily' && _avatarEmily
    ? `<span class="av"><img src="${_avatarEmily}" alt=""></span>` : '';
  el.innerHTML =
    `<header class="msg-autor">${av}<span>${autor === 'emily' ? 'Emily' : 'Você'}</span></header>` +
    `<div class="msg-corpo">${html}</div>`;
  _marcarMensagemEstruturada(el.querySelector('.msg-corpo'));
  alvo.appendChild(el);
  if (autor === 'user') { ESTADO.emilyBolhaDoTurno = null; ESTADO.respostaFinalTexto = ''; }
  acoesDaMsg(el, autor);
  rolarSePerto();
  return el;
}

function fontesDaResposta(el, fontes) {
  if (!el || !Array.isArray(fontes)) return;
  el.querySelector('.msg-fontes')?.remove();
  const vistas = new Set();
  const validas = fontes.map(fonte => {
    try {
      const url = new URL(String(fonte?.url || ''));
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || vistas.has(url.href)) return null;
      vistas.add(url.href);
      return { url: url.href, dominio: url.hostname.replace(/^www\./, ''),
        titulo: String(fonte?.titulo || url.hostname).trim().slice(0, 160),
        favicon: `${url.origin}/favicon.ico` };
    } catch { return null; }
  }).filter(Boolean).slice(0, 16);
  if (!validas.length) return;
  const icone = fonte => `<span class="fonte-icone"><img src="${esc(fonte.favicon)}" alt="" loading="lazy"></span>`;
  const bloco = document.createElement('details');
  bloco.className = 'msg-fontes';
  bloco.innerHTML = `
    <summary><span class="msg-fontes-mini">${validas.slice(0, 3).map(icone).join('')}</span>
      <span>Fontes · ${validas.length}</span>${svg(ICO.seta, 'msg-fontes-seta')}</summary>
    <div class="msg-fontes-lista">${validas.map(fonte => `
      <a href="${esc(fonte.url)}" target="_blank" rel="noopener noreferrer">
        ${icone(fonte)}<span class="msg-fonte-texto"><strong>${esc(fonte.titulo)}</strong>
        <small>${esc(fonte.dominio)}</small></span>${svg(ICO.seta)}</a>`).join('')}</div>`;
  bloco.querySelectorAll('.fonte-icone img').forEach(img => {
    img.onerror = () => { if (img.parentElement) img.parentElement.innerHTML = svg(ICO.globo); };
  });
  el.insertBefore(bloco, el.querySelector('.msg-acoes'));
}

function _marcarMensagemEstruturada(corpo) {
  if (!corpo) return;
  const seletor = 'h1,h2,h3,h4,h5,h6,table,blockquote,.bloco-cod';
  corpo.classList.toggle('md-estruturado', Boolean(corpo.querySelector(seletor)));
}

function _desenharMarkdown(corpo, texto) {
  if (!corpo) return;
  corpo.innerHTML = markdown(texto);
  _marcarMensagemEstruturada(corpo);
}

function acoesDaMsg(el, autor) {
  const barra = document.createElement('div');
  barra.className = 'msg-acoes';

  const botao = (ico, rot, fn, cls = '') => {
    const b = document.createElement('button');
    b.className = 'msg-acao ' + cls;
    b.innerHTML = svg(ico) + `<span>${rot}</span>`;
    b.onclick = () => fn(b);
    barra.appendChild(b);
    return b;
  };

  botao(ICO.copiar, 'Copiar', async b => {
    const txt = el.querySelector('.msg-corpo')?.innerText || '';
    await tenta('copiar', txt);
    b.classList.add('feito');
    b.innerHTML = svg(ICO.check) + '<span>Copiado</span>';
    setTimeout(() => {
      b.classList.remove('feito');
      b.innerHTML = svg(ICO.copiar) + '<span>Copiar</span>';
    }, 1600);
  });

  if (autor === 'emily') {
    botao(ICO.refazer, 'Regenerar', async () => {
      const indice = Number(el.dataset.indice);
      if (!ESTADO.atual || !el.dataset.indice || !Number.isInteger(indice)) {
        return toast('Aguarde a resposta ser salva antes de regenerar.', 'erro');
      }
      const abaixo = $$('.msg[data-indice]', $('#fluxo-in'))
        .some(msg => Number(msg.dataset.indice) > indice);
      if (abaixo) {
        const confirmou = await modal({ titulo: 'Regenerar a partir daqui?',
          texto: 'As mensagens abaixo desta resposta serão apagadas definitivamente em todos os aparelhos.',
          ok: 'Regenerar e apagar', perigo: true });
        if (!confirmou) return;
      }
      const resultado = await tenta('regenerar', ESTADO.atual, indice);
      if (!resultado?.ok) return toast(resultado?.erro || 'Não consegui regenerar.', 'erro');
      emilyFecha();
      ESTADO.progresso = null;
      desenharHistorico(resultado.mensagens || []);
      digitando(true);
      setTimeout(recarregarConversas, 1000);
    });
  }

  botao(ICO.lixo, '', async () => {
    el.style.transition = 'opacity 160ms, transform 160ms';
    el.style.opacity = '0';
    el.style.transform = 'translateX(10px)';
    setTimeout(() => el.remove(), 170);
  }, 'perigo');

  el.appendChild(barra);
}

/* ── A fala dela: chega frase por frase pelo status ──────────────
   O caminho normal é atualizar_status('falando', frase). Cada frase é
   acrescentada à MESMA mensagem enquanto o estado continua 'falando'.

   Mas ela também fala COMENTÁRIOS de processo antes de agir ("peraí, deixa
   eu carregar as ferramentas"). Esses chegam pelo canal de progresso E, como
   são falados, de novo pelo status — e antes ficavam colados na resposta
   final ("...aquiTá ligada sim"). Agora eles são REMOVIDOS da bolha: o texto
   cru de tudo que foi falado fica em ditoNoCartao, e o que aparece é isso
   menos as frases de processo. Order-independent: não importa se o comentário
   chega antes ou depois. */

function _textoLimpoDaBolha() {
  let t = ESTADO.ditoNoCartao || '';
  for (const p of ESTADO.falasProcesso || []) {
    if (p) t = t.split(p).join(' ');
  }
  // Quando a tela acompanha a voz, `t` é um prefixo do stream cru: preserve
  // quebras de parágrafo, listas e markdown desde o primeiro trecho falado.
  // No fallback antigo, montado de frases do TTS, não existem quebras úteis e
  // a compactação continua evitando espaços duplicados entre unidades.
  if (ESTADO.vozPrefixoFiel || ESTADO.textoStream) return textoVisivelSemTagsDeVoz(t);
  return textoVisivelSemTagsDeVoz(t.replace(/\s+/g, ' ').trim());
}

function _renderBolha() {
  const t = _textoLimpoDaBolha();
  if (!t) return;   // só teve comentário de processo até agora; sem bolha vazia
  if (!ESTADO.emilyAberta || !ESTADO.emilyAberta.isConnected) {
    const anterior = ESTADO.emilyBolhaDoTurno;
    ESTADO.emilyAberta = anterior?.isConnected
      ? anterior : novaMsg('emily', '', { escrevendo: true });
    ESTADO.emilyAberta?.classList.add('escrevendo');
  }
  ESTADO.emilyBolhaDoTurno = ESTADO.emilyAberta;
  const corpo = ESTADO.emilyAberta.querySelector('.msg-corpo');
  if (corpo) _desenharMarkdown(corpo, t);
  rolarSePerto();
}

function emilyEscreve(frase, prefixoFiel = '') {
  const limpa = String(frase || '').trim();
  if (!limpa && !prefixoFiel) return;
  if (ESTADO.respostaFinalTexto && (prefixoFiel || ESTADO.respostaFinalTexto.includes(limpa))) return;
  if (prefixoFiel) {
    ESTADO.vozPrefixoFiel = true;
    ESTADO.ditoNoCartao = String(prefixoFiel);
    ESTADO.textoStream = String(prefixoFiel);
    _renderBolha();
    return;
  }
  // No chat escrito, o stream já foi desenhado token a token. O callback do TTS
  // (quando texto digitado foi configurado para também falar) não pode duplicar.
  if (ESTADO.textoStream) return;
  // Acumula tudo que foi falado (cru). Dedup: o TTS às vezes reenvia a frase
  // inteira em vez do pedaço novo.
  const antes = ESTADO.ditoNoCartao;
  if (!antes) ESTADO.ditoNoCartao = limpa;
  else if (antes === limpa || antes.endsWith(limpa)) { /* repetição */ }
  else ESTADO.ditoNoCartao = limpa.startsWith(antes) ? limpa : `${antes} ${limpa}`;
  _renderBolha();
}

/* Texto do modelo chega token por token, independente do TTS. A voz continua
   usando emilyEscreve(frases completas); este caminho só reduz a espera visual. */
function emilyDelta(pedaco) {
  const delta = deltaVisivelSemTagsDeVoz(pedaco);
  if (!delta) return;
  ESTADO.textoStream += delta;
  ESTADO.ditoNoCartao = ESTADO.textoStream;
  digitando(false);
  _renderBolha();
}

function emilyFecha() {
  if (ESTADO.emilyAberta) ESTADO.emilyAberta.classList.remove('escrevendo');
  ESTADO.emilyAberta = null;
  ESTADO.ditoNoCartao = '';
  ESTADO.textoStream = '';
  ESTADO.vozPrefixoFiel = false;
  ESTADO.falasProcesso = [];
  _tagVozPendente = '';
}

/* O texto CRU e final da resposta, mandado pelo Python no fim do turno.
   Por que ele existe: a bolha ao vivo é remontada das frases faladas, e a
   fala PERDE as quebras de linha e as cercas de código (```), então bloco de
   código chegava numa linha só e sem realce. O cru preserva tudo — aqui a
   bolha é reescrita com ele, com markdown e código colorido de verdade. */
function emilyRespostaFinal(texto, fontes = []) {
  _tagVozPendente = '';
  const t = textoVisivelSemTagsDeVoz(texto);
  if (!t) return;
  // Só reutiliza a bolha aberta DESTE turno. Procurar "a última da Emily"
  // sobrescrevia a resposta anterior quando o turno teve apenas notas/processo.
  let bolha = ESTADO.emilyAberta || ESTADO.emilyBolhaDoTurno;
  if (!bolha || !bolha.isConnected) bolha = null;
  const corpo = bolha && bolha.querySelector('.msg-corpo');
  if (corpo) _desenharMarkdown(corpo, t);
  else bolha = novaMsg('emily', markdown(t));
  fontesDaResposta(bolha, fontes);
  digitando(false);
  ESTADO.respostaFinalTexto = t;
  // Depois do texto final, nenhum status atrasado do TTS pode reabrir esta
  // bolha e colar outra frase nela. O próximo turno começa com estado limpo.
  if (bolha) bolha.classList.remove('escrevendo');
  ESTADO.emilyAberta = null;
  ESTADO.emilyBolhaDoTurno = null;
  ESTADO.ditoNoCartao = '';
  ESTADO.textoStream = '';   // streaming do turno encerrado: não vaza pro próximo
  ESTADO.vozPrefixoFiel = false;
  ESTADO.falasProcesso = [];
  rolarSePerto();
}

/* ── Indicador de "digitando" ─────────────────────────────────── */
function digitando(ligado) {
  const existente = $('#digitando');
  if (!ligado) { existente?.remove(); return; }
  if (existente || ESTADO.tela !== 'chat') return;
  const alvo = $('#fluxo-in');
  if (!alvo) return;
  const el = document.createElement('article');
  el.id = 'digitando';
  el.className = 'msg de-emily';
  el.innerHTML = `<header class="msg-autor"><span>Emily</span></header>
    <div class="digitando"><i></i><i></i><i></i></div>`;
  alvo.appendChild(el);
  rolarSePerto();
}

/* ── Atividade das ferramentas ────────────────────────────────────
   A frase acompanha o evento atual. A seta revela ações e comentários
   em ordem cronológica, com entrada e resultado de cada ferramenta. */

// Nome bonito + ícone pra cada ferramenta que a Emily usa. O nome cru que
// chega do Python (ex: "analisar_disco") vira algo legível ("Analisando
// disco") com um ícone que combina. Cai no fallback genérico se não achar.
const _NOME_BONITO = {
  // ── Arquivos e pastas ──
  'abrir_pasta':        { rotulo: 'Abrindo pasta',         ico: ICO.pasta },
  'abrir_arquivo':      { rotulo: 'Abrindo arquivo',       ico: ICO.pasta },
  'abrir_app':          { rotulo: 'Abrindo aplicativo',    ico: ICO.monitor },
  'xadrez_abrir':       { rotulo: 'Abrindo xadrez com a Emily', ico: ICO.jogo },
  'abrir_jogo':         { rotulo: 'Abrindo jogo',           ico: ICO.jogo },
  'fechar_app':         { rotulo: 'Fechando aplicativo',   ico: ICO.monitor },
  'procurar_no_pc':     { rotulo: 'Procurando no PC',      ico: ICO.lupa },
  'criar_pasta':        { rotulo: 'Criando pasta',         ico: ICO.pasta },
  'criar_arquivo_txt':  { rotulo: 'Criando arquivo de texto', ico: ICO.pasta },
  'mover_arquivo':      { rotulo: 'Movendo arquivo',       ico: ICO.pasta },
  'copiar_arquivo':     { rotulo: 'Copiando arquivo',      ico: ICO.pasta },
  'renomear_arquivo':  { rotulo: 'Renomeando arquivo',    ico: ICO.pasta },
  'deletar_arquivo':   { rotulo: 'Apagando arquivo',      ico: ICO.lixo },
  'abrir_site':         { rotulo: 'Abrindo site',          ico: ICO.globo },
  'navegar_para':       { rotulo: 'Navegando até',         ico: ICO.globo },
  'organizar_downloads':{ rotulo: 'Organizando downloads', ico: ICO.pasta },
  // ── Disco e sistema ──
  'analisar_disco':     { rotulo: 'Analisando disco',      ico: ICO.disco },
  'limpar_disco':       { rotulo: 'Limpando disco',        ico: ICO.disco },
  'executar_terminal': { rotulo: 'Executando comando',   ico: ICO.tecla },
  'cancelar_terminal': { rotulo: 'Cancelando comando',   ico: ICO.tecla },
  'ver_sistema':        { rotulo: 'Vendo o sistema',       ico: ICO.monitor },
  // ── Música ──
  'tocar_musica':       { rotulo: 'Tocando música',        ico: ICO.musica },
  'player_tocar':       { rotulo: 'Tocando no player',     ico: ICO.musica },
  'controle_musica':    { rotulo: 'Mexendo na música',     ico: ICO.musica },
  // ── Pesquisa e internet ──
  'pesquisar_internet': { rotulo: 'Pesquisando na internet', ico: ICO.lupa },
  'pesquisar':          { rotulo: 'Pesquisando',           ico: ICO.lupa },
  'ler_pagina_navegador': { rotulo: 'Lendo página',       ico: ICO.globo },
  'navegador_interno_abrir': { rotulo: 'Abrindo no navegador da Emily', ico: ICO.globo },
  'navegador_interno_ler': { rotulo: 'Lendo o navegador da Emily', ico: ICO.globo },
  'navegador_interno_ver': { rotulo: 'Olhando o navegador da Emily', ico: ICO.olho },
  'navegador_interno_interagir': { rotulo: 'Usando o navegador da Emily', ico: ICO.globo },
  'baixar_midia_da_aba': { rotulo: 'Baixando mídia',      ico: ICO.globo },
  'listar_abas_navegador': { rotulo: 'Vendo abas do navegador', ico: ICO.globo },
  // ── Tela e visão ──
  'capturar_tela':      { rotulo: 'Olhando a tela',        ico: ICO.monitor },
  'ver_tela':           { rotulo: 'Olhando a tela',        ico: ICO.monitor },
  'traduzir_tela':      { rotulo: 'Traduzindo a tela',    ico: ICO.olho },
  'executar_na_tela':   { rotulo: 'Usando a tela',         ico: ICO.olho },
  // ── Memória ──
  'guardar_fato':       { rotulo: 'Guardando na memória',  ico: ICO.cerebro },
  'lembrar_fatos':      { rotulo: 'Consultando a memória', ico: ICO.cerebro },
  'esquecer_fato':      { rotulo: 'Atualizando a memória', ico: ICO.cerebro },
  'mandar_mensagem_discord': { rotulo: 'Enviando mensagem no Discord', ico: ICO.chat },
  'mandar_dm_discord': { rotulo: 'Enviando mensagem no Discord', ico: ICO.chat },
  'ler_chat_discord':  { rotulo: 'Lendo conversa no Discord', ico: ICO.chat },
  'ver_canais_discord': { rotulo: 'Vendo canais do Discord', ico: ICO.chat },
  'compartilhar_tela_pc_tv': { rotulo: 'Compartilhando tela na TV', ico: ICO.monitor },
  'ver_tvs':            { rotulo: 'Procurando TVs',         ico: ICO.tv },
  'conectar_tv':        { rotulo: 'Conectando à TV',        ico: ICO.tv },
  'comando_tv':         { rotulo: 'Controlando a TV',       ico: ICO.tv },
  'abrir_app_tv':       { rotulo: 'Abrindo aplicativo na TV', ico: ICO.tv },
  'status_da_tv':       { rotulo: 'Verificando a TV',       ico: ICO.tv },
  'buscar_na_tv':       { rotulo: 'Buscando na TV',         ico: ICO.tv },
  'apps_instalados_tv': { rotulo: 'Vendo aplicativos da TV', ico: ICO.tv },
  'nuvem_buscar':       { rotulo: 'Buscando na nuvem',     ico: ICO.nuvem },
  'nuvem_guardar_arquivo': { rotulo: 'Salvando na nuvem', ico: ICO.nuvem },
  'nuvem_listar':       { rotulo: 'Vendo arquivos na nuvem', ico: ICO.nuvem },
  'nuvem_status':       { rotulo: 'Verificando a nuvem',   ico: ICO.nuvem },
  'hora_atual':         { rotulo: 'Consultando a hora',    ico: ICO.cubo },
  'assistir_tela':      { rotulo: 'Acompanhando a tela',  ico: ICO.olho },
  'player_volume':      { rotulo: 'Ajustando o volume',   ico: ICO.musica },
  'player_proxima':     { rotulo: 'Mudando de música',    ico: ICO.musica },
  'player_anterior':    { rotulo: 'Voltando a música',    ico: ICO.musica },
  'playlist_criar':     { rotulo: 'Criando playlist',     ico: ICO.musica },
  'code_git_status':    { rotulo: 'Verificando alterações no código', ico: ICO.tecla },
  'code_git_diff':      { rotulo: 'Comparando alterações no código', ico: ICO.tecla },
  'code_git_log':       { rotulo: 'Lendo histórico do código', ico: ICO.tecla },
  'code_git_commit':    { rotulo: 'Salvando alterações no código', ico: ICO.tecla },
  // ── GitHub ──
  'github_listar_repos':      { rotulo: 'Vendo repositórios', ico: ICO_GITHUB },
  'github_criar_repo':        { rotulo: 'Criando repositório', ico: ICO_GITHUB },
  'github_apagar_repo':       { rotulo: 'Apagando repositório', ico: ICO_GITHUB },
  'github_ler_arquivo':       { rotulo: 'Lendo arquivo',        ico: ICO_GITHUB },
  'github_escrever_arquivo':  { rotulo: 'Salvando arquivo',     ico: ICO_GITHUB },
  'github_apagar_arquivo':    { rotulo: 'Apagando arquivo',     ico: ICO_GITHUB },
  'github_criar_pr':          { rotulo: 'Abrindo pull request', ico: ICO_GITHUB },
  'github_criar_issue':       { rotulo: 'Abrindo issue',        ico: ICO_GITHUB },
  'abrir_ferramentas':        { rotulo: 'Preparando ferramentas', ico: ICO.cubo },
  // ── Imagem ──
  'criar_imagem':       { rotulo: 'Gerando imagem',        ico: ICO.paleta },
};

function _nomeBonito(nome) {
  if (!nome) return { rotulo: 'Preparando ação', ico: ICO.cubo };
  const m = _NOME_BONITO[nome];
  if (m) return m;
  const partes = String(nome).toLowerCase().split('_').filter(Boolean);
  const prefixo = ['github', 'nuvem', 'code', 'player', 'playlist'].includes(partes[0]) ? partes.shift() : '';
  const verbos = {
    abrir: 'Abrindo', fechar: 'Fechando', listar: 'Listando', ver: 'Verificando',
    pesquisar: 'Pesquisando', buscar: 'Buscando', procurar: 'Procurando',
    criar: 'Criando', copiar: 'Copiando', mover: 'Movendo', renomear: 'Renomeando',
    deletar: 'Apagando', apagar: 'Apagando', extrair: 'Extraindo',
    analisar: 'Analisando', limpar: 'Limpando', executar: 'Executando',
    instalar: 'Instalando', guardar: 'Guardando', esquecer: 'Atualizando',
    lembrar: 'Consultando', ler: 'Lendo', preencher: 'Preenchendo',
    submeter: 'Enviando', baixar: 'Baixando', compartilhar: 'Compartilhando',
    conectar: 'Conectando', configurar: 'Configurando', cancelar: 'Cancelando',
    salvar: 'Salvando', tocar: 'Tocando', status: 'Verificando',
    enviar: 'Enviando', responder: 'Respondendo', traduzir: 'Traduzindo',
    sincronizar: 'Sincronizando', restaurar: 'Restaurando', favoritar: 'Favoritando',
    exportar: 'Exportando', revogar: 'Revogando', descobrir: 'Descobrindo',
    achar: 'Procurando', editar: 'Editando', escrever: 'Escrevendo',
    revisar: 'Revisando', mudar: 'Mudando', perguntar: 'Perguntando',
    encerrar: 'Encerrando', rodar: 'Executando', mesclar: 'Mesclando',
    comentar: 'Comentando', pausar: 'Pausando', adicionar: 'Adicionando',
    remover: 'Removendo', excluir: 'Excluindo', transferir: 'Transferindo',
    monitorar: 'Monitorando', gerar: 'Gerando', organizar: 'Organizando',
    parar: 'Parando', maximizar: 'Maximizando', minimizar: 'Minimizando',
    definir: 'Definindo', assistir: 'Acompanhando',
  };
  const verbo = partes.shift() || 'Usando';
  const resto = partes.join(' ')
    .replace(/\bmidia\b/g, 'mídia').replace(/\bpagina\b/g, 'página')
    .replace(/\bvideo\b/g, 'vídeo').replace(/\bmusica\b/g, 'música')
    .replace(/\bmemoria\b/g, 'memória').replace(/\btv\b/g, 'TV')
    .replace(/\bpc\b/g, 'PC').replace(/\bpr\b/g, 'PR')
    .replace(/\bdm\b/g, 'DM').replace(/\burl\b/g, 'URL');
  let rotulo = `${verbos[verbo] || verbo.charAt(0).toUpperCase() + verbo.slice(1)}${resto ? ` ${resto}` : ''}`;
  if (prefixo === 'github') rotulo += ' no GitHub';
  if (prefixo === 'nuvem') rotulo += ' na nuvem';
  if (prefixo === 'code') rotulo += ' no código';
  if (prefixo === 'player') rotulo += ' no player';
  if (prefixo === 'playlist') rotulo += ' na playlist';
  const n = String(nome).toLowerCase();
  const ico = prefixo === 'github' ? ICO_GITHUB
    : prefixo === 'nuvem' ? ICO.nuvem
    : prefixo === 'code' ? ICO.tecla
    : prefixo === 'player' || prefixo === 'playlist' ? ICO.musica
    : /imagem|foto/.test(n) ? ICO.paleta
    : /jogo|_mc$|modpack/.test(n) ? ICO.jogo
    : /tv|televisao/.test(n) ? ICO.tv
    : /discord|mensagem|chat|dm/.test(n) ? ICO.chat
    : /musica|player|playlist|audio|volume|midia/.test(n) ? ICO.musica
    : /tela|monitor|visao/.test(n) ? ICO.olho
    : /memoria|fato/.test(n) ? ICO.cerebro
    : /terminal|comando|script|javascript/.test(n) ? ICO.tecla
    : /arquivo|pasta|download|disco|backup/.test(n) ? ICO.pasta
    : /pesquis|busca|procur/.test(n) ? ICO.lupa
    : /site|pagina|aba|navegador|web|link/.test(n) ? ICO.globo
    : ICO.cubo;
  return { rotulo, ico };
}

function _detalheArgumentos(args) {
  if (!args || typeof args !== 'object') return '';
  const limpos = Object.entries(args)
    .filter(([, valor]) => valor !== '' && valor !== null && valor !== undefined)
    .slice(0, 8);
  if (!limpos.length) return '';
  return limpos.map(([chave, valor]) => {
    const texto = typeof valor === 'object' ? JSON.stringify(valor) : String(valor);
    return `<div class="passo-arg"><span>${esc(chave.replace(/_/g, ' '))}</span><code>${esc(texto.slice(0, 180))}</code></div>`;
  }).join('');
}

function _contextoFerramenta(args) {
  if (!args || typeof args !== 'object') return '';
  for (const chave of ['consulta', 'query', 'termo', 'pergunta', 'busca', 'prompt',
                       'site', 'url', 'endereco', 'nome_app', 'app', 'aplicativo',
                       'arquivo', 'pasta', 'caminho', 'nome', 'comando']) {
    const valor = args[chave];
    if (typeof valor !== 'string') continue;
    const texto = valor.replace(/\s+/g, ' ').trim();
    if (texto) return texto.slice(0, 100);
  }
  return '';
}

const _ACAO_CONCLUIDA = {
  abrir_site: 'Abriu site', abrir_pasta: 'Abriu pasta', abrir_arquivo: 'Abriu arquivo',
  navegador_interno_abrir: 'Abriu página no navegador da Emily',
  navegador_interno_interagir: 'Interagiu com a página',
  navegador_interno_ler: 'Leu a página', navegador_interno_ver: 'Viu a página',
  abrir_app: 'Abriu aplicativo', criar_pasta: 'Criou pasta',
  criar_arquivo_txt: 'Criou arquivo de texto', executar_terminal: 'Executou comando',
};

function _resumoResultadoFerramenta(nome, ok) {
  const acao = ok ? (_ACAO_CONCLUIDA[nome] || _nomeBonito(nome).rotulo)
    : `${_nomeBonito(nome).rotulo} · não concluído`;
  return acao;
}

function _tempoProgresso(inicio) {
  const segundos = Math.max(0, Math.round((Date.now() - Number(inicio || Date.now())) / 1000));
  if (segundos < 1) return 'menos de 1 s';
  if (segundos < 60) return `${segundos} s`;
  return `${Math.floor(segundos / 60)} min ${segundos % 60} s`;
}

function _atualizarResumoProgresso(p) {
  if (!p) return;
  const total = Number(p.dataset.total || 0);
  const concluidas = Number(p.dataset.concluidas || 0);
  const notas = Number(p.dataset.notas || 0);
  const atual = $$('.passo.trabalhando:not(.fala)', p).at(-1);
  const nota = $$('.passo.fala .passo-nota', p).at(-1);
  const controle = $('.progresso-historico', p);
  const frase = $('.progresso-rot', p);
  const icone = $('.progresso-icone-simbolo', p);
  if (controle) {
    const temHistorico = total + notas > 0;
    controle.disabled = !temHistorico;
    $('.progresso-seta', controle).hidden = !temHistorico;
  }
  let estado;
  if (p.dataset.ultimaFase === 'erro_conexao') {
    estado = { frase: p.dataset.servico === 'voz'
      ? 'Fala interrompida · resposta escrita preservada'
      : p.dataset.servico === 'ferramenta' ? 'Consulta interrompida · abra para ver o erro'
      : 'Conexão interrompida · abra para ver o erro', ico: ICO.wifi };
  } else if (p.dataset.ultimaFase === 'erro_modelo') {
    estado = { frase: 'Tarefa interrompida · abra para ver o erro', ico: ICO.x };
  } else if (p.dataset.ultimaFase === 'reconectando') {
    estado = { frase: `Reconectando ${p.dataset.servico === 'voz' ? 'a voz' : p.dataset.servico === 'ferramenta' ? 'a consulta' : 'ao serviço de IA'} · tentativa ${p.dataset.tentativa || 1}/${p.dataset.limite || 3}`, ico: ICO.wifi };
  } else if (!p.classList.contains('trabalhando')) {
    const falhas = Number(p.dataset.falhas || 0);
    estado = {
      frase: `${falhas ? 'Concluiu com atenção' : 'Trabalhou'} por ${_tempoProgresso(p.dataset.inicio)}`,
      ico: falhas ? ICO.x : ICO.check,
    };
  } else if (p.dataset.ultimaFase === 'fala' && nota?.textContent) {
    estado = { frase: nota.textContent, ico: ICO.chat };
  } else if (atual) {
    const bonito = _nomeBonito(atual.dataset.nome);
    estado = { frase: bonito.rotulo + (atual.dataset.contexto
      ? ` · ${atual.dataset.contexto}` : ''), ico: bonito.ico };
  } else if (total > concluidas) {
    estado = { frase: 'Aguardando resultado das ferramentas', ico: ICO.cubo };
  } else if (p.dataset.ultimoNome) {
    const nome = p.dataset.ultimoNome;
    estado = {
      frase: _resumoResultadoFerramenta(nome, p.dataset.ultimoOk === '1') +
        (p.dataset.ultimoContexto ? ` · ${p.dataset.ultimoContexto}` : ''),
      ico: _nomeBonito(nome).ico,
    };
  } else if (total) {
    estado = { frase: 'Preparando a resposta', ico: ICO.chat };
  } else {
    estado = { frase: 'Escolhendo o próximo passo', ico: ICO.cubo };
  }
  if (frase) {
    frase.textContent = estado.frase;
    frase.title = estado.frase;
  }
  if (icone) icone.innerHTML = svg(estado.ico, 'ico');
  if (controle) controle.setAttribute('aria-label', total + notas
    ? `${estado.frase}. ${p.classList.contains('aberto') ? 'Ocultar' : 'Mostrar'} detalhes`
    : estado.frase);
}

function _trocarDetalhePasso(el, classe, html) {
  const detalhe = $('.passo-detalhe', el);
  if (!detalhe) return;
  $(`.${classe}`, detalhe)?.remove();
  if (html) detalhe.insertAdjacentHTML('beforeend', html);
}

function _rolarProgressoPara(passos, el) {
  requestAnimationFrame(() => {
    if (!passos?.isConnected || !el?.isConnected) return;
    if (!passos.closest('.progresso.aberto')) return;
    passos.scrollTop = Math.max(0, el.offsetTop - passos.clientHeight + el.offsetHeight + 8);
  });
}

function _criarProgresso() {
  if (ESTADO.tela !== 'chat') irPara('chat');
  const alvo = $('#fluxo-in');
  if (!alvo) return null;
  const p = document.createElement('div');
  p.className = 'progresso trabalhando';
  p.dataset.total = '0';
  p.dataset.concluidas = '0';
  p.dataset.falhas = '0';
  p.dataset.mudancas = '0';
  p.dataset.notas = '0';
  p.dataset.ultimaFase = '';
  p.dataset.inicio = String(Date.now());
  p.setAttribute('role', 'group');
  p.setAttribute('aria-label', 'Atividade da Emily');
  p.innerHTML = `
    <div class="progresso-topo">
      <button class="progresso-historico" type="button" aria-expanded="false" disabled>
        <span class="progresso-icone-simbolo" aria-hidden="true">${svg(ICO.cubo, 'ico')}</span>
        <span class="progresso-rot" aria-live="polite" aria-atomic="true">Escolhendo o próximo passo</span>
        <svg class="progresso-seta" viewBox="0 0 24 24" aria-hidden="true" hidden><path d="M6 9l6 6 6-6"/></svg>
      </button>
    </div>
    <div class="progresso-corpo"><div class="progresso-passos"></div></div>`;
  p.querySelector('.progresso-historico').onclick = () => {
    const aberto = p.classList.toggle('aberto');
    p.querySelector('.progresso-historico').setAttribute('aria-expanded', String(aberto));
    _atualizarResumoProgresso(p);
  };
  alvo.appendChild(p);
  ESTADO.progresso = p;
  ESTADO.falasProcesso = [];   // novo turno, novo processo
  return p;
}

function _finalizarProgresso(p) {
  const ferramentas = Number(p.dataset.total || 0);
  const mudancas = Number(p.dataset.mudancas || 0);
  let interrompidas = 0;
  $$('.passo.trabalhando', p).forEach(el => {
    const pendentes = Number(el.dataset.pendentes || 0);
    interrompidas += pendentes;
    const falhasDoPasso = Number(el.dataset.falhas || 0) + pendentes;
    const mudancasDoPasso = Number(el.dataset.mudancas || 0);
    el.classList.remove('trabalhando', 'ok', 'falhou', 'mudou');
    el.classList.add(falhasDoPasso ? 'falhou' : mudancasDoPasso ? 'mudou' : 'ok');
    el.dataset.falhas = String(falhasDoPasso);
    el.dataset.pendentes = '0';
    const status = $('.passo-status', el);
    if (status) status.textContent = pendentes ? 'Interrompido antes do resultado'
      : falhasDoPasso ? 'Concluído com atenção'
      : mudancasDoPasso ? 'Alteração aplicada' : 'Concluído';
  });
  const falhas = Number(p.dataset.falhas || 0) + interrompidas;
  if (p.dataset.ultimaFase === 'erro_conexao' || p.dataset.ultimaFase === 'erro_modelo') {
    p.dataset.falhas = String(Math.max(1, falhas));
  }
  if (!String(p.dataset.ultimaFase || '').startsWith('erro_')) p.dataset.falhas = String(falhas);
  p.dataset.concluidas = String(ferramentas);
  p.classList.remove('trabalhando');
  p.classList.add(Number(p.dataset.falhas) ? 'com-falha' : mudancas ? 'com-mudanca' : 'concluido');
  _atualizarResumoProgresso(p);
}

function progresso(fase, dados = {}) {
  if (fase === 'inicio') { ESTADO.respostaFinalTexto = ''; emilyFecha(); ESTADO.emilyBolhaDoTurno = null; restaurarAberturaAutomaticaNavegador(); }
  if (fase === 'fim') {
    if (ESTADO.progresso) { _finalizarProgresso(ESTADO.progresso); ESTADO.progresso = null; }
    return;
  }
  if (!ESTADO.progresso || !ESTADO.progresso.isConnected) {
    if (!_criarProgresso()) return;
  }
  const painel = ESTADO.progresso;
  const passos = painel.querySelector('.progresso-passos');

  if (['reconectando', 'reconectado', 'erro_conexao', 'erro_modelo'].includes(fase)) {
    painel.dataset.ultimaFase = fase === 'reconectado' ? 'resultado' : fase;
    painel.dataset.servico = dados.servico || 'ia';
    if (fase.startsWith('erro_'))
      painel.dataset.falhas = String(Number(painel.dataset.falhas || 0) + 1);
    if (fase === 'reconectando') {
      painel.dataset.tentativa = String(dados.tentativa || 1);
      painel.dataset.limite = String(dados.limite || 3);
    }
    const el = document.createElement('div');
    el.className = 'passo fala passo-conexao';
    const msg = fase === 'reconectando'
      ? `Reconectando ${dados.servico === 'voz' ? 'a voz' : dados.servico === 'ferramenta' ? 'a consulta' : 'ao serviço de IA'} · tentativa ${dados.tentativa || 1}/${dados.limite || 3}`
      : fase === 'reconectado' ? 'Conexão restabelecida; continuando'
      : (dados.mensagem || 'A tarefa foi interrompida');
    el.innerHTML = `<span class="passo-fala-marca">${svg(fase === 'erro_modelo' ? ICO.x : ICO.wifi)}</span>` +
      `<div class="passo-txt"><small>${dados.servico === 'voz' ? 'Voz' : dados.servico === 'ferramenta' ? 'Ferramenta' : 'Conexão'}</small><span class="passo-nota"></span></div>`;
    $('.passo-nota', el).textContent = msg;
    passos.appendChild(el);
    painel.dataset.notas = String(Number(painel.dataset.notas || 0) + 1);
    _atualizarResumoProgresso(painel);
    _rolarProgressoPara(passos, el);
  } else if (fase === 'ferramenta') {
    const nome = dados.nome || '';
    if (nome.startsWith('navegador_interno_')) abrirPainelNavegador(true);
    const bonito = _nomeBonito(nome);
    const el = document.createElement('div');
    el.className = 'passo trabalhando';
    el.dataset.nome = nome;
    el.dataset.contexto = _contextoFerramenta(dados.args);
    el.dataset.pendentes = '1';
    el.dataset.falhas = '0';
    el.dataset.mudancas = '0';
    el._inicioFerramenta = performance.now();
    el.innerHTML =
      `<button class="passo-linha" type="button" aria-expanded="false">` +
        `<span class="passo-ico">${svg(bonito.ico, 'ico')}<i class="passo-ativo"></i></span>` +
        `<span class="passo-info"><strong class="passo-rot">${esc(bonito.rotulo)}` +
          `${el.dataset.contexto ? ` · ${esc(el.dataset.contexto)}` : ''}</strong>` +
          `<small class="passo-status">Executando</small></span>` +
        `<span class="passo-tempo"></span>` +
        `<svg class="passo-seta" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>` +
      `</button><div class="passo-detalhe"></div>`;
    el.querySelector('.passo-linha').onclick = e => {
      e.stopPropagation();
      const aberto = el.classList.toggle('aberto');
      e.currentTarget.setAttribute('aria-expanded', String(aberto));
    };
    passos.appendChild(el);
    painel.dataset.total = String(Number(painel.dataset.total || 0) + 1);
    painel.dataset.ultimaFase = 'ferramenta';
    const args = dados.args && Object.keys(dados.args).length
      ? _detalheArgumentos(dados.args) : '';
    _trocarDetalhePasso(el, 'passo-entrada', args
      ? `<div class="passo-detalhe-bloco passo-entrada"><span class="passo-det-tit">Parâmetros</span>${args}</div>` : '');
    _atualizarResumoProgresso(painel);
    _rolarProgressoPara(passos, el);
  } else if (fase === 'resultado') {
    // O motor envia resultados na ordem das chamadas, inclusive nos lotes
    // paralelos. Assim cada execução repetida mantém sua própria etapa.
    const el = $$('.passo.trabalhando:not(.fala)', passos)
      .find(p => p.dataset.nome === (dados.nome || ''));
    if (el) {
      const ok = typeof dados.ok === 'boolean'
        ? dados.ok : !/falhou|não existe|inválid|faltou/i.test(dados.resultado || '');
      const mudou = ok && dados.mudou === true;
      el.dataset.pendentes = '0';
      if (!ok) el.dataset.falhas = String(Number(el.dataset.falhas || 0) + 1);
      if (mudou) el.dataset.mudancas = String(Number(el.dataset.mudancas || 0) + 1);
      painel.dataset.concluidas = String(Number(painel.dataset.concluidas || 0) + 1);
      painel.dataset.ultimaFase = 'resultado';
      painel.dataset.ultimoNome = el.dataset.nome;
      painel.dataset.ultimoContexto = el.dataset.contexto || '';
      painel.dataset.ultimoOk = ok ? '1' : '0';
      if (!ok) painel.dataset.falhas = String(Number(painel.dataset.falhas || 0) + 1);
      if (mudou) painel.dataset.mudancas = String(Number(painel.dataset.mudancas || 0) + 1);
      const falhas = Number(el.dataset.falhas || 0);
      const mudancas = Number(el.dataset.mudancas || 0);
      el.classList.remove('trabalhando');
      el.classList.add(falhas ? 'falhou' : mudancas ? 'mudou' : 'ok');
      // O ícone da tarefa permanece no histórico; o ponto indica o resultado.
      const status = el.querySelector('.passo-status');
      if (status) status.textContent = dados.erro === 'resultado_incerto'
        ? 'Resultado incerto · confira antes de repetir'
        : falhas ? 'Com atenção'
        : mudancas ? 'Alteração aplicada' : 'Concluído';
      const tempo = el.querySelector('.passo-tempo');
      const duracao = Number.isFinite(Number(dados.duracao))
        ? Number(dados.duracao) : (performance.now() - el._inicioFerramenta) / 1000;
      if (tempo) tempo.textContent = duracao < 1 ? `${Math.max(1, Math.round(duracao * 1000))}ms` : `${duracao.toFixed(1)}s`;
      const res = String(dados.resultado || '').slice(0, 300);
      _trocarDetalhePasso(el, 'passo-resultado', res
        ? `<div class="passo-detalhe-bloco passo-resultado"><span class="passo-det-tit">Resultado</span>` +
          `<div class="passo-res">${esc(res)}</div></div>` : '');
      _atualizarResumoProgresso(painel);
      _rolarProgressoPara(passos, el);
    }
  } else if (fase === 'fala' && dados.texto) {
    // Cada comentário fica no histórico em ordem, além de ser removido da
    // resposta final quando o texto definitivo da Emily chegar.
    const txt = String(dados.texto).trim();
    if (txt) {
      ESTADO.falasProcesso.push(txt);
      painel.dataset.notas = String(Number(painel.dataset.notas || 0) + 1);
      painel.dataset.ultimaFase = 'fala';
      const el = document.createElement('div');
      el.className = 'passo fala';
      el.innerHTML = `<span class="passo-fala-marca">${svg(ICO.chat)}</span>` +
        `<div class="passo-txt"><small>Atualização da Emily</small><span class="passo-nota"></span></div>`;
      $('.passo-nota', el).textContent = txt;
      passos.appendChild(el);
      _atualizarResumoProgresso(painel);
      _rolarProgressoPara(passos, el);
      _renderBolha();   // se o comentário já tinha entrado na bolha, limpa
    }
  }
  rolarSePerto();
}

/* ── Geração de imagem ───────────────────────────────────────────
   A API não expõe progresso real. Mostramos só o tempo decorrido e o
   pedido, sem porcentagem nem etapas simuladas. */

function _imagemProgresso() {
  return document.querySelector('.img-progresso');
}

function _removerImagemProgresso(card) {
  const mensagem = card?.closest('.msg');
  if (!mensagem) return;
  clearInterval(mensagem._imgTimer);
  mensagem.remove();
}

function imagemProgresso(d = {}) {
  if (ESTADO.tela !== 'chat') irPara('chat');
  const alvo = $('#fluxo-in');
  if (!alvo) return;
  rolarSePerto();

  // Erro: mantém a mensagem legível por alguns segundos.
  if (d.fase === 'erro') {
    const card = _imagemProgresso();
    if (card) {
      card.classList.add('img-erro');
      const rot = card.querySelector('.img-prog-desc');
      if (rot) rot.textContent = d.erro || 'Não consegui gerar a imagem.';
      setTimeout(() => _removerImagemProgresso(card), 6000);
    }
    return;
  }
  // Pronta: o card final (mostrar_opcao_salvar) já está chegando.
  if (d.fase === 'pronta') {
    const card = _imagemProgresso();
    if (card) {
      card.classList.add('img-pronta');
      setTimeout(() => _removerImagemProgresso(card), 900);
    }
    return;
  }
  if (d.fase !== 'inicio') return;

  // Reinício inesperado sem o anterior: tira o velho antes de criar.
  _removerImagemProgresso(_imagemProgresso());

  const el = document.createElement('article');
  el.className = 'msg de-emily';
  el.innerHTML = `
    <header class="msg-autor"><span>Emily</span></header>
    <div class="img-progresso">
      <div class="img-prog-topo">
        <span class="img-prog-ico" aria-hidden="true"></span>
        <div class="img-prog-txt">
          <strong>Gerando imagem</strong>
          <span class="img-prog-desc">${esc(d.prompt || 'gerando sua imagem')}</span>
        </div>
        <span class="img-prog-tempo">0s</span>
      </div>
    </div>`;
  alvo.appendChild(el);

  // Cronômetro real, sem inventar porcentagem ou fases.
  const tempoEl = el.querySelector('.img-prog-tempo');
  const inicio = Date.now();
  const timer = setInterval(() => {
    if (!el.isConnected) { clearInterval(timer); return; }
    const t = (Date.now() - inicio) / 1000;
    if (tempoEl) tempoEl.textContent = `${Math.floor(t)}s`;
  }, 1000);
  el._imgTimer = timer;
}

/* ── Imagem no chat ─────────────────────────────────────────── */
function ampliarAnexo(url) {
  const dialog = document.createElement('dialog');
  dialog.className = 'chat-imagem-ampliada';
  dialog.innerHTML = `<button type="button" aria-label="Fechar imagem">×</button><img src="${esc(url)}" alt="Imagem ampliada">`;
  document.body.appendChild(dialog);
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.onclick = e => { if (e.target === dialog) dialog.close(); };
  dialog.addEventListener('close', () => dialog.remove(), { once: true });
  dialog.showModal();
}

function mensagemComAnexos(texto, anexos, opcoes = {}) {
  const html = anexos.map(a => a.previa || a.url
    ? `<button class="chat-anexo-imagem" type="button" aria-label="Ampliar ${esc(a.nome || 'imagem')}"><img src="${esc(a.previa || a.url)}" alt="${esc(a.nome || 'Imagem anexada')}"></button>`
    : `<span class="chat-anexo-arquivo">📎 ${esc(a.nome || 'Arquivo')}</span>`).join('');
  const el = novaMsg('user', `<div class="chat-anexos">${html}</div>${texto ? markdown(texto) : ''}`, opcoes);
  const imagens = anexos.filter(a => a.previa || a.url);
  el?.querySelectorAll('.chat-anexo-imagem').forEach((btn, i) => {
    btn.addEventListener('click', () => ampliarAnexo(imagens[i].previa || imagens[i].url));
  });
  return el;
}

function imagemNoChat(url, autor = 'user') {
  const el = novaMsg(autor, `<button class="chat-anexo-imagem" type="button" aria-label="Ampliar imagem"><img src="${esc(url)}" alt="Imagem anexada"></button>`);
  el?.querySelector('button')?.addEventListener('click', () => ampliarAnexo(url));
}

function ofertaSalvar(caminho, url) {
  const el = novaMsg('emily', `<div class="img-card"><img src="${url}" alt="">
    <div class="img-acoes">
      <button class="btn-linha primario" data-salvar>Salvar imagem</button>
      <button class="btn-linha" data-descartar>Descartar</button>
    </div></div>`);
  if (!el) return;
  el.querySelector('[data-salvar]').onclick = async e => {
    const r = await tenta('salvar_imagem', caminho);
    e.target.closest('.img-acoes').innerHTML =
      `<span style="font-size:12.5px;color:var(--ok)">${r ? 'Salvo em ' + esc(r) : 'Não salvei'}</span>`;
  };
  el.querySelector('[data-descartar]').onclick = () =>
    el.querySelector('.img-acoes').remove();
}

/* ════════════════════════════════════════════════════════════════
   STATUS
   ════════════════════════════════════════════════════════════════ */

const ROTULO = {
  aguardando: 'Aguardando', ouvindo: 'Ouvindo', gravando: 'Gravando',
  pensando: 'Pensando', falando: 'Falando', ocupada: 'Trabalhando',
  monitorando: 'Olhando a tela', erro: 'Deu problema',
};

function aplicarStatus(estado, texto = '', textoPrefixo = '') {
  const box = $('#status');
  const e = String(estado || 'aguardando').toLowerCase();
  box.dataset.e = e;
  // O texto do status é o que o Python manda; sem ele, o rótulo do estado.
  $('.status-txt', box).textContent = (e === 'falando' ? ROTULO.falando : (texto || ROTULO[e] || e));

  if (e === 'falando') {
    digitando(false);
    if (texto) emilyEscreve(texto, textoPrefixo);
  } else {
    emilyFecha();
    digitando(e === 'pensando' || e === 'ocupada');
  }
}

/* ════════════════════════════════════════════════════════════════
   SIDEBAR: lista, busca, renomear, apagar
   ════════════════════════════════════════════════════════════════ */

function quando(ts) {
  const d = (Date.now() / 1000) - (ts || 0);
  if (d < 86400) return 'Hoje';
  if (d < 172800) return 'Ontem';
  if (d < 604800) return 'Últimos 7 dias';
  if (d < 2592000) return 'Últimos 30 dias';
  return 'Mais antigas';
}

let _versaoListaNormal = 0;
let _versaoListaCode = 0;
const _unicasPorId = lista => {
  const vistos = new Set();
  return (Array.isArray(lista) ? lista : []).filter(c => {
    if (!c?.id || vistos.has(c.id)) return false;
    vistos.add(c.id);
    return true;
  });
};

async function recarregarConversas() {
  const versao = ++_versaoListaNormal;
  const lista = await tenta('listar_conversas');
  if (versao !== _versaoListaNormal) return ESTADO.conversas;
  ESTADO.conversas = _unicasPorId(lista);
  if (!_naTelaCode) desenharConversas();
  return ESTADO.conversas;
}

let _codeConversas = [];

async function recarregarCodeConversas() {
  const versao = ++_versaoListaCode;
  const lista = await tenta('code_listar_conversas');
  if (versao !== _versaoListaCode) return _codeConversas;
  _codeConversas = _unicasPorId(lista);
  if (_naTelaCode) desenharConversas();
  return _codeConversas;
}

function desenharConversas() {
  const alvo = $('#conversas');
  if (!alvo) return;
  alvo.innerHTML = '';

  // No Emily Code, a sidebar mostra as conversas do code (separadas).
  if (_naTelaCode) {
    const filtroCode = ESTADO.filtro.toLowerCase();
    const sessoes = filtroCode
      ? _codeConversas.filter(c => (c.titulo || '').toLowerCase().includes(filtroCode)
          || (c.projeto || '').toLowerCase().includes(filtroCode))
      : _codeConversas;
    if (!sessoes.length) {
      const sub = document.createElement('p');
      sub.className = 'vazio-lista';
      sub.innerHTML = filtroCode
        ? '<strong>Nenhuma sessão encontrada</strong><span>Tente outro nome ou projeto.</span>'
        : '<strong>Nenhuma sessão ainda</strong><span>Crie uma conversa e mande a primeira tarefa.</span>';
      alvo.appendChild(sub);
      return;
    }
    sessoes.forEach((c, i) => {
      const el = document.createElement('div');
      el.className = 'conv conv-code' + (c.ativa ? ' ativa' : '')
        + (_codeEstaPendente(c.id) ? ' executando' : '');
      el.dataset.cid = c.id;
      el.style.animationDelay = `${Math.min(i, 12) * 24}ms`;
      el.innerHTML = `
        <span class="conv-code-rail" aria-hidden="true"></span>
        <span class="conv-code-main"><span class="conv-titulo">${esc(c.titulo || 'Conversa de código')}</span>` +
          `<small>${_codeEstaPendente(c.id) ? 'executando · ' : ''}${c.projeto ? esc(String(c.projeto).replace(/\\/g, '/').split('/').filter(Boolean).pop()) : 'workspace sem projeto'} · ${c.quantas || 0} msg</small></span>
        <span class="conv-acoes">
          <button class="icone-btn mini" data-ren title="Renomear">${svg(ICO.lapis)}</button>
          <button class="icone-btn mini" data-del title="Apagar">${svg(ICO.lixo)}</button>
        </span>`;

      const titulo = $('.conv-titulo', el);
      el.onclick = e => {
        if (e.target.closest('.conv-acoes')) return;
        _codeConversas.forEach(x => { x.ativa = x.id === c.id; });
        _codeConversaAtiva = c.id;
        desenharConversas();
        _codeAtualizarExecucao();
        montarCodeHist(c.id);
      };

      $('[data-ren]', el).onclick = () => {
        el.classList.add('editando');
        titulo.contentEditable = 'true';
        titulo.focus();
        document.getSelection().selectAllChildren(titulo);
        const fim = async salvar => {
          titulo.contentEditable = 'false';
          el.classList.remove('editando');
          const novo = titulo.textContent.trim();
          if (salvar && novo && novo !== c.titulo) {
            await tenta('code_renomear_conversa', c.id, novo);
            c.titulo = novo;
            toast('Renomeada');
          }
          titulo.textContent = c.titulo || 'Conversa de código';
        };
        titulo.onkeydown = ev => {
          if (ev.key === 'Enter') { ev.preventDefault(); fim(true); }
          if (ev.key === 'Escape') { ev.preventDefault(); fim(false); }
        };
        titulo.onblur = () => fim(true);
      };

      $('[data-del]', el).onclick = async () => {
        if (_codeEstaPendente(c.id)) {
          toast('Espera essa execução terminar antes de apagar a sessão', 'erro');
          return;
        }
        const r = await modal({
          titulo: 'Apagar esta conversa de código?',
          texto: `"${c.titulo || 'Conversa de código'}" sai da lista e não volta.`,
          ok: 'Apagar', perigo: true,
        });
        if (!r) return;
        el.style.transition = 'opacity 160ms, transform 160ms';
        el.style.opacity = '0'; el.style.transform = 'translateX(-14px)';
        const apagou = await tenta('code_apagar_conversa', c.id);
        if (!apagou) { toast('Não consegui apagar esta sessão', 'erro'); return; }
        _codePendentes.delete(c.id);
        setTimeout(async () => {
          await recarregarCodeConversas();
          if (c.ativa) {
            const proxima = _codeConversas.find(x => x.ativa) || _codeConversas[0];
            if (proxima) await montarCodeHist(proxima.id);
            else irPara('code', { forcar: true });
          }
        }, 170);
      };

      alvo.appendChild(el);
    });
    return;
  }

  const f = ESTADO.filtro.toLowerCase();
  const lista = f
    ? ESTADO.conversas.filter(c => (c.titulo || '').toLowerCase().includes(f))
    : ESTADO.conversas;

  if (!lista.length) {
    alvo.innerHTML = `<p class="vazio-lista">${f
      ? 'Nada com esse nome.'
      : 'Nenhuma conversa ainda.<br>Manda a primeira mensagem.'}</p>`;
    return;
  }

  let grupoAtual = null;
  lista.forEach((c, i) => {
    const g = f ? null : quando(c.mexida);
    if (g && g !== grupoAtual) {
      grupoAtual = g;
      const r = document.createElement('div');
      r.className = 'grupo-rot';
      r.textContent = g;
      alvo.appendChild(r);
    }
    alvo.appendChild(linhaConversa(c, i));
  });
}

function linhaConversa(c, i) {
  const el = document.createElement('div');
  el.className = 'conv' + (c.id === ESTADO.atual ? ' ativa' : '');
  el.style.animationDelay = `${Math.min(i, 14) * 18}ms`;
  el.innerHTML =
    `<span class="conv-titulo">${esc(c.titulo || 'Conversa nova')}</span>` +
    (c.pendente ? `<span class="conv-pendente" title="Tarefa interrompida; abra para decidir">${svg(ICO.wifi, 'ico')}</span>` : '') + `
     <span class="conv-acoes">
       <button class="icone-btn mini" data-ren title="Renomear">${svg(ICO.lapis)}</button>
       <button class="icone-btn mini" data-del title="Apagar">${svg(ICO.lixo)}</button>
     </span>`;

  const titulo = $('.conv-titulo', el);
  el.onclick = e => { if (!e.target.closest('.conv-acoes')) abrirConversa(c.id); };

  /* Renomear é edição no lugar, não caixa de diálogo: renomear é ação
     leve e abrir modal pra isso é mais cliques do que a coisa vale.
     conversas.renomear() já existia no Python e nunca tinha sido ligada. */
  $('[data-ren]', el).onclick = () => {
    el.classList.add('editando');
    titulo.contentEditable = 'true';
    titulo.focus();
    document.getSelection().selectAllChildren(titulo);

    const fim = async salvar => {
      titulo.contentEditable = 'false';
      el.classList.remove('editando');
      const novo = titulo.textContent.trim();
      if (salvar && novo && novo !== c.titulo) {
        await tenta('renomear_conversa', c.id, novo);
        c.titulo = novo;
        toast('Renomeada');
      }
      titulo.textContent = c.titulo || 'Conversa nova';
    };
    titulo.onkeydown = ev => {
      if (ev.key === 'Enter') { ev.preventDefault(); fim(true); }
      if (ev.key === 'Escape') { ev.preventDefault(); fim(false); }
    };
    titulo.onblur = () => fim(true);
  };

  $('[data-del]', el).onclick = async () => {
    const r = await modal({
      titulo: 'Apagar esta conversa?',
      texto: `"${c.titulo || 'Conversa nova'}" sai da lista e não volta.`,
      ok: 'Apagar', perigo: true,
    });
    if (!r) return;
    el.style.transition = 'opacity 160ms, transform 160ms';
    el.style.opacity = '0'; el.style.transform = 'translateX(-14px)';
    await tenta('apagar_conversa', c.id);
    setTimeout(async () => {
      if (ESTADO.atual === c.id) { ESTADO.atual = null; irPara('inicio'); }
      await recarregarConversas();
    }, 170);
  };

  return el;
}

async function abrirConversa(cid) {
  if (ESTADO.atual === cid && ESTADO.tela === 'chat') return;
  const pedido = ++_navegacaoGeracao;
  const msgs = await tenta('abrir_conversa', cid) || [];
  if (msgs?.bloqueada) return;
  if (pedido !== _navegacaoGeracao || _naTelaCode) return;
  ESTADO.atual = cid;
  emilyFecha();
  ESTADO.progresso = null;
  irPara('chat', { forcar: true });

  desenharHistorico(msgs);
  desenharConversas();
  const pendencia = await tenta('turno_pendente', cid);
  if (ESTADO.atual === cid && pendencia?.pedido) mostrarTurnoPendente(cid, pendencia);
}

function mostrarTurnoPendente(cid, pendencia) {
  const fluxo = $('#fluxo-in');
  if (!fluxo || fluxo.querySelector('.turno-pendente')) return;
  const card = document.createElement('aside');
  card.className = 'turno-pendente';
  card.setAttribute('role', 'status');
  card.innerHTML = `<span class="turno-pendente-ico">${svg(ICO.wifi, 'ico')}</span>` +
    `<div class="turno-pendente-corpo"><strong>Tarefa interrompida</strong>` +
    `<span class="turno-pendente-passo"></span>` +
    `<small class="turno-pendente-aviso"></small>` +
    `<div class="turno-pendente-acoes"><button type="button" class="continuar">Continuar</button>` +
    `<button type="button" class="dispensar">Dispensar aviso</button></div></div>`;
  $('.turno-pendente-passo', card).textContent =
    `${pendencia.passo || 'Preparando resposta'} · ${pendencia.situacao || 'sem conclusão'}`;
  $('.turno-pendente-aviso', card).textContent = pendencia.conferir_acao
    ? 'Uma ação pode ter ocorrido. A Emily deve conferir o estado antes de repetir.'
    : 'A Emily aguardará sua decisão para continuar.';
  $('.continuar', card).onclick = () => {
    const entrada = $('#entrada');
    if (!entrada) return;
    entrada.value = 'Continue a tarefa anterior. Confira o estado atual antes de repetir qualquer ação.';
    ajustarEntrada();
    entrada.focus();
    card.remove();
  };
  $('.dispensar', card).onclick = async () => {
    if (await tenta('dispensar_turno_pendente', cid)) card.remove();
  };
  fluxo.appendChild(card);
  rolarFim();
}

function desenharHistorico(msgs) {
  const alvo = $('#fluxo-in');
  if (alvo) {
    alvo.innerHTML = '';
    msgs.forEach(m => {
      const autor = (m.papel === 'assistant' || m.papel === 'emily') ? 'emily' : 'user';
      const el = autor === 'user' && m.anexos?.length
        ? mensagemComAnexos(m.texto || '', m.anexos, { indice: m.indice })
        : novaMsg(autor, markdown(m.texto || ''), { indice: m.indice });
      if (autor === 'emily') fontesDaResposta(el, m.fontes);
      // Histórico não entra animado uma por uma: com 40 mensagens isso
      // vira uma cascata de dois segundos antes de dar pra ler.
      if (el) el.style.animation = 'none';
    });
    rolarFim();
  }
}

async function novaConversa() {
  // No Emily Code, "novo" abre uma sessão de código limpa (fluxo separado).
  if (_naTelaCode) {
    const cid = await tenta('code_criar_conversa', '');
    if (!cid) { toast('Não consegui criar a sessão', 'erro'); return; }
    _codeConversaAtiva = cid;
    await recarregarCodeConversas();
    _codeConversas.forEach(c => { c.ativa = c.id === cid; });
    irPara('code', { forcar: true });
    $('#code-campo')?.focus();
    return;
  }
  const cid = await tenta('nova_conversa');
  if (cid?.bloqueada) return;
  ESTADO.atual = cid || null;
  emilyFecha();
  irPara('inicio', { forcar: true });
  await recarregarConversas();
  $('#entrada')?.focus();
}

/* ════════════════════════════════════════════════════════════════
   COMPOSER
   ════════════════════════════════════════════════════════════════ */

function ajustarEntrada() {
  const t = $('#entrada');
  if (!t) return;
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 200) + 'px';
  $('#btn-enviar').disabled = !t.value.trim() && !ESTADO.anexos.length;
}

const ANEXO_MAX_QTDE = 12;
const ANEXO_MAX_BYTES = 25 * 1024 * 1024;

function tamanhoLegivel(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function adicionarAnexos(novos) {
  let adicionados = 0;
  for (const anexo of (novos || [])) {
    if (anexo?.erro === 'arquivo_grande') {
      toast(`${anexo.nome || 'Arquivo'} passa do limite de 25 MB`, 'erro');
      continue;
    }
    if (!anexo?.caminho) continue;
    if (Number(anexo.tamanho || 0) > ANEXO_MAX_BYTES) {
      toast(`${anexo.nome || 'Arquivo'} passa do limite de 25 MB`, 'erro');
      continue;
    }
    const repetido = ESTADO.anexos.some(a => a.caminho === anexo.caminho);
    if (repetido) continue;
    if (ESTADO.anexos.length >= ANEXO_MAX_QTDE) {
      toast(`Dá pra enviar no máximo ${ANEXO_MAX_QTDE} anexos por vez`, 'erro');
      break;
    }
    ESTADO.anexos.push(anexo);
    adicionados++;
  }
  if (adicionados) {
    desenharAnexos();
    ajustarEntrada();
  }
  return adicionados;
}

function arquivoEmBase64(arquivo) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result || '').split(',', 2)[1] || '');
    fr.onerror = () => reject(fr.error || new Error('Falha ao ler o arquivo'));
    fr.readAsDataURL(arquivo);
  });
}

async function anexarArquivosWeb(arquivos, origem = 'selecionados', silencioso = false) {
  const lista = [...(arquivos || [])].filter(Boolean);
  if (!lista.length) return 0;
  let adicionados = 0;
  for (const arquivo of lista) {
    if (ESTADO.anexos.length >= ANEXO_MAX_QTDE) {
      toast(`Dá pra enviar no máximo ${ANEXO_MAX_QTDE} anexos por vez`, 'erro');
      break;
    }
    if (Number(arquivo.size || 0) > ANEXO_MAX_BYTES) {
      toast(`${arquivo.name || 'Arquivo'} passa do limite de 25 MB`, 'erro');
      continue;
    }
    try {
      const b64 = await arquivoEmBase64(arquivo);
      const salvo = await tenta(
        'salvar_colado', b64, arquivo.name || '', arquivo.type || '', { __teto: 30000 });
      if (salvo?.caminho) adicionados += adicionarAnexos([salvo]);
      else if (!silencioso) toast(`Não consegui anexar ${arquivo.name || 'o arquivo'}`, 'erro');
    } catch (erro) {
      console.error(`[emily] falha ao anexar arquivo ${origem}`, erro);
      if (!silencioso) toast(`Não consegui ler ${arquivo.name || 'o arquivo'}`, 'erro');
    }
  }
  return adicionados;
}

async function anexarImagemClipboardNativo() {
  const resultado = await tenta('colar_imagem_nativa', { __teto: 15000 });
  if (resultado?.anexo?.caminho) return adicionarAnexos([resultado.anexo]) > 0;
  if (resultado?.erro === 'arquivo_grande') {
    toast('A imagem do clipboard passa do limite de 25 MB', 'erro');
    return true;
  }
  return false;
}

function extensaoImagemMime(mime) {
  const mapa = {
    'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp',
    'image/gif': 'gif', 'image/bmp': 'bmp', 'image/svg+xml': 'svg',
  };
  return mapa[String(mime || '').toLowerCase()] || 'png';
}

/* Chromium/WebView2 às vezes omite a imagem de clipboardData, mas ainda a
   disponibiliza pela Clipboard API moderna. A chamada precisa nascer do gesto
   de Ctrl+V; por isso este fallback é iniciado dentro do próprio handler. */
async function anexarImagensClipboardApi() {
  if (!navigator.clipboard?.read) return false;
  try {
    const itens = await navigator.clipboard.read();
    const arquivos = [];
    for (const item of itens) {
      const mime = (item.types || []).find(t => String(t).toLowerCase().startsWith('image/'));
      if (!mime) continue;
      const blob = await item.getType(mime);
      arquivos.push(new File(
        [blob], `imagem-colada.${extensaoImagemMime(mime)}`, { type: mime }));
      if (arquivos.length >= ANEXO_MAX_QTDE) break;
    }
    return arquivos.length
      ? (await anexarArquivosWeb(arquivos, 'da API do clipboard', true)) > 0
      : false;
  } catch (erro) {
    console.debug('[emily] Clipboard API não expôs a imagem', erro);
    return false;
  }
}

/* WhatsApp Web/Desktop pode copiar somente text/html com uma tag <img>, sem
   FileList nem item image/*. Data URLs e blob URLs acessíveis pela WebView são
   convertidos de volta em File. URLs http(s) não são baixadas aqui para não
   disparar imagens remotas/rastreadores presentes em qualquer HTML copiado. */
async function anexarImagensDoHtmlClipboard(html) {
  if (!html || !/<img\b/i.test(html)) return false;
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const fontes = [...doc.querySelectorAll('img[src]')]
      .map(img => img.getAttribute('src') || '')
      .filter(src => /^data:image\//i.test(src) || /^blob:/i.test(src))
      .slice(0, ANEXO_MAX_QTDE);
    const arquivos = [];
    for (const src of fontes) {
      try {
        const resposta = await fetch(src);
        const blob = await resposta.blob();
        if (!blob.type?.toLowerCase().startsWith('image/')) continue;
        arquivos.push(new File(
          [blob], `imagem-colada.${extensaoImagemMime(blob.type)}`, { type: blob.type }));
      } catch (erro) {
        console.debug('[emily] imagem do HTML do clipboard inacessível', erro);
      }
    }
    return arquivos.length
      ? (await anexarArquivosWeb(arquivos, 'do HTML do clipboard', true)) > 0
      : false;
  } catch (erro) {
    console.debug('[emily] não consegui interpretar o HTML do clipboard', erro);
    return false;
  }
}

function desenharAnexos() {
  const box = $('#anexos');
  box.innerHTML = '';
  box.hidden = !ESTADO.anexos.length;
  ESTADO.anexos.forEach((a, i) => {
    const el = document.createElement('div');
    el.className = 'anexo';
    el.innerHTML = (a.previa
      ? `<img src="${a.previa}" alt="">`
      : svg(ICO.pasta, 'anexo-ico')) +
      `<span class="anexo-nome" title="${esc(a.nome)}">${esc(a.nome)}</span>
       ${a.tamanho ? `<small class="anexo-tamanho">${tamanhoLegivel(a.tamanho)}</small>` : ''}
       <button class="icone-btn mini">${svg(ICO.x)}</button>`;
    el.querySelector('button').onclick = () => {
      ESTADO.anexos.splice(i, 1); desenharAnexos(); ajustarEntrada();
    };
    box.appendChild(el);
  });
}

async function enviar() {
  const t = $('#entrada');
  const texto = t.value.trim();
  if (!texto && !ESTADO.anexos.length) return;

  const anexos = ESTADO.anexos.slice();
  if (anexos.length) {
    ESTADO.ultimoPedido = texto;
    const bolha = mensagemComAnexos(texto, anexos);
    digitando(true);
    const cid = await tenta('enviar_arquivos', anexos.map(a => a.caminho), texto);
    if (cid) {
      ESTADO.atual = cid;
      if (t.value.trim() === texto) { t.value = ''; ajustarEntrada(); }
      ESTADO.anexos = ESTADO.anexos.filter(a => !anexos.includes(a));
      desenharAnexos();
    } else {
      bolha?.remove();
      digitando(false);
      toast('Não foi possível enviar agora. Seus anexos foram mantidos; aguarde a resposta atual e tente novamente.', 'erro');
    }
    setTimeout(recarregarConversas, 1400);
    return;
  }

  if (texto) {
    ESTADO.ultimoPedido = texto;
    const bolhaUsuario = novaMsg('user', markdown(texto));
    const requisicaoId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    t.value = ''; ajustarEntrada();
    if (ESTADO.remoto) {
      // MODO REMOTO: o comando é executado pela Emily do CELULAR. A resposta
      // chega pelo evento “msg” (autor emily) que o backend empurra quando
      // o app responde. Teto de 150s (a Emily do celular pode demorar).
      digitando(true);
      let r = null;
      try { r = await tenta('enviar', texto, true, 'digitado', requisicaoId); }
      catch (e) { r = { ok: false, erro: String(e.message || e) }; }
      if (!r) r = await tenta('enviar', texto, true, 'digitado', requisicaoId,
                              { __teto: 30000 });
      if (typeof r === 'string') ESTADO.atual = r;
      else if (r && r.cid) ESTADO.atual = r.cid;
      if (!r) {
        digitando(false);
        toast('Não consegui confirmar o envio ao celular. Confira a conversa antes de reenviar.', 'erro');
      }
      if (r && r.erro) {
        digitando(false);
        novaMsg('emily', markdown(r.erro));
      }
      // Sem erro: digitando continua até a resposta chegar por push.
      setTimeout(recarregarConversas, 1400);
      return;
    }
    digitando(true);
    // O enviar() agora devolve o cid da conversa (criado na primeira mensagem)
    // — é ele que ata esta sessão à conversa, pra o ESTADO.atual saber qual é.
    let cid = await tenta('enviar', texto, false, 'digitado', requisicaoId);
    if (!cid) cid = await tenta('enviar', texto, false, 'digitado', requisicaoId,
                                 { __teto: 30000 });
    if (cid) ESTADO.atual = cid;
    else {
      // A ponte pode perder somente o ACK depois de salvar o pedido.
      // Não apagar a bolha nem reenviar com outro ID: isso duplicaria ações.
      toast('Não consegui confirmar o envio. Reabra a conversa para conferir antes de reenviar.', 'erro');
      digitando(false);
      return;
    }
    // O título vem do Python (LLM) e leva um instante; recarrega depois.
    setTimeout(recarregarConversas, 1400);
  } else {
    t.value = ''; ajustarEntrada();
  }
}

/* ════════════════════════════════════════════════════════════════
   EMILY CODE — modais de pergunta e permissão
   O Python manda 'emily_code' com {tipo: 'pergunta'|'permissao'}. Aqui
   monta um modal bonito; a resposta volta pro Python.
   ════════════════════════════════════════════════════════════════ */

// True quando a tela do Emily Code está visível (respostas vão pro terminal).
let _naTelaCode = false;

function mostrarPerguntaUsuario(d) {
  if (!d?.id) return;
  document.getElementById('pergunta-usuario')?.remove();
  const cartao = document.createElement('aside');
  cartao.id = 'pergunta-usuario';
  cartao.className = 'pergunta-usuario';
  cartao.dataset.ticket = d.id;
  cartao.setAttribute('role', 'dialog');
  cartao.setAttribute('aria-modal', 'false');
  cartao.setAttribute('aria-label', 'Emily precisa da sua resposta');
  const login = d.tipo === 'login';
  cartao.innerHTML = `
    <div class="pergunta-usuario-topo"><span class="pergunta-usuario-icone">E</span>
      <span>Emily precisa de você</span></div>
    <h3>${esc(d.pergunta || 'Como devo continuar?')}</h3>
    <p>${login ? 'Você pode usar o navegador enquanto a tarefa fica pausada.'
      : 'A tarefa fica pausada aqui até você responder.'}</p>
    <textarea rows="2" placeholder="Responda à Emily..." aria-label="Sua resposta"></textarea>
    <div class="pergunta-usuario-acoes">
      ${login ? '<button type="button" class="pergunta-ver-nav">Ver navegador</button>' : ''}
      <button type="button" class="pergunta-nao">Não consegui</button>
      <button type="button" class="pergunta-enviar">Responder</button>
    </div>`;
  document.body.appendChild(cartao);
  const campo = cartao.querySelector('textarea');
  const enviarResposta = async resposta => {
    resposta = String(resposta || '').trim();
    if (!resposta) { campo.focus(); return; }
    cartao.querySelectorAll('button').forEach(b => { b.disabled = true; });
    const ok = await tenta('responder_pergunta_usuario', d.id, resposta);
    if (ok) cartao.remove();
    else {
      cartao.querySelectorAll('button').forEach(b => { b.disabled = false; });
      toast('Essa pergunta já expirou. Pode enviar uma nova mensagem no chat.', 'erro');
      cartao.remove();
    }
  };
  cartao.querySelector('.pergunta-enviar').onclick = () => enviarResposta(campo.value);
  cartao.querySelector('.pergunta-nao').onclick = () => enviarResposta('Não consegui resolver agora. Explique outra forma de prosseguir.');
  cartao.querySelector('.pergunta-ver-nav')?.addEventListener('click', () => abrirPainelNavegador());
  campo.onkeydown = e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviarResposta(campo.value); }
  };
  campo.focus();
}

function emilyCodeEvento(d) {
  if (d.tipo === 'acao') {
    // Ação de ferramenta em tempo real: spinner → status → expandir.
    if (!_naTelaCode || (d.cid && d.cid !== _codeConversaAtiva)) return;
    if (d.fase === 'iniciou') {
      codeAdicionarAcao(d.nome || '', d.args || {});
    } else if (d.fase === 'concluiu') {
      codeConcluirAcao(d.nome || '', d.ok, d.mudou, d.erro, d.texto, d.duracao);
    } else if (d.fase === 'fim') {
      codeAtualizarStatus();
    }
    return;
  }
  if (d.tipo === 'resposta') {
    // Só conclui o estado pendente da conversa que originou este evento.
    const eraPendente = !d.cid || _codePendentes.has(d.cid);
    if (d.cid) _codePendentes.delete(d.cid);
    if (!_naTelaCode) {
      if (d.conversas) recarregarCodeConversas();
      return;
    }
    // Se o Vitor já trocou de conversa, a resposta da anterior não vai pro
    // terminal da atual (o backend já salvou na conversa certa).
    if (d.cid && _codeConversaAtiva && d.cid !== _codeConversaAtiva) {
      if (d.conversas) recarregarCodeConversas();
      _codeAtualizarExecucao();
      return;
    }
    // A ponte pode reenviar evento após reconexão. O backend já salvou uma
    // única mensagem; sem esta guarda, a UI desenhava a resposta duas vezes.
    if (!eraPendente) {
      if (d.conversas) recarregarCodeConversas();
      // Após reconexão o Set local pode ter sido perdido, mas a resposta já
      // está salva. Reabre o histórico estático em vez de duplicar o evento.
      if (d.cid && d.cid === _codeConversaAtiva) montarCodeHist(d.cid);
      return;
    }
    const cidResposta = d.cid || _codeConversaAtiva;
    if (cidResposta) _codeRenderizando.add(cidResposta);
    _codeAtualizarExecucao();
    codeExibirResposta(d.texto || '', cidResposta).then(() => {
      // Após a Emily terminar de responder, devolve o foco pro campo do
      // terminal (o aviso de pasta pode tê-lo roubado ou o replace tê-lo perdido).
      const c = $('#code-campo');
      if (cidResposta) _codeRenderizando.delete(cidResposta);
      _codeAtualizarExecucao();
      if (c && !c.disabled) c.focus();
    });
    if (d.conversas) recarregarCodeConversas();
    return;
  }
  if (d.tipo === 'mudar_pasta') {
    // A Emily pediu pra trocar a pasta de projeto: reabre o aviso com a pasta
    // atual pré-preenchida e botão Cancelar. Ela espera a escolha.
    if (d.cid && d.cid !== _codeConversaAtiva) {
      _codeConversas.forEach(c => { c.ativa = c.id === d.cid; });
      _codeConversaAtiva = d.cid;
      irPara('code', { forcar: true });
    }
    if (!_naTelaCode) irPara('code', { forcar: true });
    codeMostrarAvisoPasta(d.mensagem || 'Quer trocar a pasta do projeto?', {
      boasVindas: false, podeCancelar: true, padrao: d.projeto || '',
    });
    return;
  }
  if (d.tipo === 'pergunta') {
    // code_perguntar: pergunta com opções (janela bonita).
    const opcoes = Array.isArray(d.opcoes) ? d.opcoes : [];
    const resolve = new Promise(ok => {
      const fundo = $('#modal-fundo');
      fundo.innerHTML = `
        <div class="modal ec-modal" role="dialog" aria-modal="true">
          <div class="ec-modal-topo">
            <span class="ec-modal-chip">Emily Code · ${esc(d.cid ? d.cid.slice(0, 6) : 'sessão')}</span>
          </div>
          <h3>${esc(d.pergunta || 'Pergunta')}</h3>
          <div class="modal-acoes ec-opcoes">
            ${opcoes.length ? opcoes.map((o, i) =>
              `<button class="btn-linha ec-opcao" data-v="${i}">${esc(o)}</button>`).join('')
            : `<button class="btn-linha ec-opcao" data-v="ok">Confirmar</button>`}
          </div>
        </div>`;
      fundo.hidden = false;
      const fecha = val => { fundo.hidden = true; fundo.innerHTML = ''; ok(val); };
      $$('.ec-opcao', fundo).forEach(b => {
        b.onclick = () => fecha(opcoes[+b.dataset.v] ?? 'ok');
      });
    });
    resolve.then(resp => tenta('emily_code_responder', resp));
  } else if (d.tipo === 'permissao') {
    // code_* pede permissão: mostra o preview (diff/conteúdo) do que vai mudar,
    // e dá as opções Permitir / Permitir sempre / Negar.
    const fundo = $('#modal-fundo');
    const preview = String(d.preview || '').trim();
    const temPreview = preview.length > 0 && preview !== '(sem alterações)';
    const previewHtml = temPreview
      ? `<details class="ec-preview" open>
          <summary>O que vai mudar</summary>
          <pre class="ec-preview-pre">${esc(preview)}</pre>
        </details>`
      : '';
    fundo.innerHTML = `
      <div class="modal ec-modal" role="dialog" aria-modal="true">
        <div class="ec-modal-topo">
            <span class="ec-modal-chip ec-chip-perm">Permissão · ${esc(d.cid ? d.cid.slice(0, 6) : 'sessão')}</span>
        </div>
        <h3>${esc(d.acao || 'Ação')}</h3>
        <p class="ec-perm-caminho">${esc(d.caminho || '')}</p>
        ${previewHtml}
        <div class="modal-acoes">
          <button class="btn-linha ec-perm-nao" data-p="nao">Negar</button>
          <button class="btn-linha ec-perm-sim" data-p="sim">Permitir</button>
          <button class="btn-linha primario ec-perm-sempre" data-p="sempre">Permitir sempre</button>
        </div>
      </div>`;
    fundo.hidden = false;
    const fecha = p => { fundo.hidden = true; fundo.innerHTML = '';
      tenta('emily_code_permissao', p, d.acao || '', d.caminho || ''); };
    $$('[data-p]', fundo).forEach(b => { b.onclick = () => fecha(b.dataset.p); });
  }
}

/* ════════════════════════════════════════════════════════════════
   PONTE: o que o Python chama
   ════════════════════════════════════════════════════════════════ */

async function atualizarPreferenciasSincronizadas() {
  const perfil = await tenta('perfil') || {};
  const nome = perfil.nome || 'Vitor';
  const nomeLateral = $('#perfil-nome');
  if (nomeLateral) nomeLateral.textContent = nome;
  const nomeInicio = $('#hero-nome');
  if (nomeInicio) nomeInicio.textContent = nome;
  const fotoLateral = $('#perfil-av');
  if (fotoLateral) {
    if (perfil.avatar_usuario) fotoLateral.innerHTML = `<img src="${perfil.avatar_usuario}" alt="">`;
    else fotoLateral.textContent = nome[0]?.toUpperCase() || 'V';
  }
  const retrato = $('#hero-img');
  if (retrato && perfil.avatar) retrato.src = perfil.avatar;
  const fotoPerfil = $('#perf-av');
  if (fotoPerfil) {
    if (perfil.avatar_usuario) fotoPerfil.innerHTML = `<img src="${perfil.avatar_usuario}" alt="">`;
    else fotoPerfil.textContent = nome[0]?.toUpperCase() || 'V';
  }
  if ($('#perf-corpo')) {
    const dados = await tenta('estado_perfil') || {};
    const nomeCampo = $('#perf-nome');
    const persCampo = $('#perf-pers');
    if (nomeCampo && document.activeElement !== nomeCampo) nomeCampo.value = dados.nome || '';
    if (persCampo && document.activeElement !== persCampo) persCampo.value = dados.personalidade_extra || '';
  }
  if (ESTADO.tela === 'config') {
    const autom = await tenta('estado_automacao') || {};
    $$('.config .chave[data-chave]').forEach(ch => {
      const chave = ch.dataset.chave;
      if (Object.prototype.hasOwnProperty.call(autom, chave))
        ch.setAttribute('aria-checked', String(Boolean(autom[chave])));
    });
    const novoVolume = await tenta('volume_voz');
    const slider = $('#cfg-volume');
    if (slider && novoVolume != null && document.activeElement !== slider) {
      const pct = Math.round(Math.max(0, Math.min(150, Number(novoVolume) * 100)));
      slider.value = String(pct);
      const rotulo = $('#cfg-volume-valor');
      if (rotulo) rotulo.textContent = `${pct}%`;
    }
  }
  await carregarSeletores();
}

window.Emily = {
  on(evento, dados) {
    try {
      const d = dados || {};
      switch (evento) {
        case 'xadrez_abrir': window.EmilyXadrez?.abrir(); break;
        case 'status':    aplicarStatus(d.estado, d.texto, d.texto_prefixo); break;
        case 'msg': {
          const autor = d.autor === 'emily' ? 'emily' : 'user';
          // Histórico também é camada visual: tags Fish ficam armazenadas para
          // preservar o texto original, mas nunca reaparecem ao reabrir o chat.
          const texto = autor === 'emily' ? textoVisivelSemTagsDeVoz(d.texto) : d.texto;
          novaMsg(autor, markdown(texto));
          break;
        }
        case 'resposta':  emilyRespostaFinal(d.texto, d.fontes); break;
        case 'imagem':    imagemNoChat(d.url, d.autor || 'user'); break;
        case 'salvar':    ofertaSalvar(d.caminho, d.url); break;
        case 'progresso': progresso(d.fase, d.dados || {}); break;
        // Streaming de tokens: o texto chega token a token (modelo ->
        // interface_web -> aqui) pra bolha aparecer crescendo. A resposta crua
        // final ainda chega pelo 'resposta' e reescreve a bolha com markdown e
        // código colorido — sem duplicar.
        case 'delta':      emilyDelta(d.texto); break;
        // Criação de imagem (ferramenta criar_imagem): cartão com barra
        // de progresso própria — inicio, pronta e erro.
        case 'imagem_progresso': imagemProgresso(d); break;
        case 'conversas': recarregarConversas(); break;
        case 'mensagem_persistida': {
          if (d.cid !== ESTADO.atual) break;
          const pendentes = $$('.msg.de-emily:not([data-indice])', $('#fluxo-in'));
          const mensagem = pendentes[pendentes.length - 1];
          if (mensagem && Number.isInteger(d.indice)) mensagem.dataset.indice = String(d.indice);
          break;
        }
        case 'regeneracao_falhou': {
          if (d.cid !== ESTADO.atual) break;
          emilyFecha();
          digitando(false);
          desenharHistorico(d.mensagens || []);
          toast('A nova resposta falhou. A conversa anterior foi preservada.', 'erro');
          break;
        }
        case 'conversa_sincronizada': {
          if (d.cid !== ESTADO.atual || ESTADO.tela !== 'chat') break;
          emilyFecha();
          ESTADO.progresso = null;
          desenharHistorico(d.mensagens || []);
          recarregarConversas();
          break;
        }
        case 'avatar':    _avatarEmily = d.url || ''; break;
        case 'preferencias_sync': atualizarPreferenciasSincronizadas(); break;
        case 'gateway_endpoint': atualizarGatewayEndpoint(d); break;
        case 'toast':     toast(d.texto, d.tipo); break;
        // Comando pro Emily Music da interface, vindo das ferramentas player_*.
        // O áudio vive no objeto Player (JS); aqui só repasso a ação.
        case 'player_comando': playerComando(d.acao, d.dados || {}); break;
        // Emily Code: pergunta ou pedido de permissão (modal bonito).
        case 'emily_code': emilyCodeEvento(d); break;
        case 'pergunta_usuario': mostrarPerguntaUsuario(d); break;
        case 'pergunta_usuario_fim': {
          const cartao = document.getElementById('pergunta-usuario');
          if (cartao?.dataset.ticket === d.id) cartao.remove();
          break;
        }
        case 'modo_demo':  aplicarModoDemo(d); recarregarAposModoDemo(); break;
        case 'agente_ui':  aplicarEstadoAgenteUI(d); break;
        // TV: desfecho de conectar/parear (roda em thread no Python).
        case 'tv': tvEvento(d); break;
        default: console.warn('[emily] evento desconhecido:', evento);
      }
    } catch (e) { console.error('[emily] on(' + evento + ')', e); }
  },
};

/* ════════════════════════════════════════════════════════════════
   CONFIGURAÇÕES — a barra lateral vira o índice dos ajustes
   ════════════════════════════════════════════════════════════════ */

const CONFIG_GRUPOS = [
  { nome: 'Emily', paginas: [
    { id: 'automacao', titulo: 'Automação', ico: 'raio', busca: 'discord autonomia espiadinha voz muda' },
    { id: 'voz', titulo: 'Voz e áudio', ico: 'voz', busca: 'volume microfone ruído silero delegação' },
    { id: 'discord', titulo: 'Modelo do Discord', ico: 'chat', busca: 'respostas cérebro modelo' },
  ] },
  { nome: 'Dados', paginas: [
    { id: 'memoria', titulo: 'Memória', ico: 'cerebro', busca: 'você pessoas discord unificada fatos' },
  ] },
  { nome: 'Dispositivos', paginas: [
    { id: 'tv', titulo: 'TV', ico: 'monitor', busca: 'parear conectar dispositivo' },
    { id: 'gateway', titulo: 'Conexão do celular', ico: 'monitor', busca: 'gateway ngrok endpoint android url túnel' },
    { id: 'sistema', titulo: 'Este computador', ico: 'disco', busca: 'processador memória uso sistema' },
  ] },
  { nome: 'Aplicativo', paginas: [
    { id: 'atualizacao', titulo: 'Atualização', ico: 'refazer', busca: 'versão instalar recursos' },
  ] },
];

function _paginaConfig(id) {
  return CONFIG_GRUPOS.flatMap(grupo => grupo.paginas).find(p => p.id === id)
    || CONFIG_GRUPOS[0].paginas[0];
}

function selecionarConfig(id, { rolar = true } = {}) {
  const pagina = _paginaConfig(id);
  ESTADO.cfgPagina = pagina.id;
  let itemAtivo = null;
  $$('.cfg-nav-item').forEach(b => {
    const ativa = b.dataset.cfgAbrir === pagina.id;
    b.classList.toggle('ativa', ativa);
    if (ativa) { b.setAttribute('aria-current', 'page'); itemAtivo = b; }
    else b.removeAttribute('aria-current');
  });
  if (itemAtivo && !itemAtivo.hidden) itemAtivo.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  $$('.config .secao[data-cfg-secao]').forEach(sec => {
    sec.hidden = sec.dataset.cfgSecao !== pagina.id;
  });
  const titulo = $('#cfg-pagina-titulo');
  if (titulo) titulo.textContent = pagina.titulo;
  const trilha = $('#cfg-trilha');
  if (trilha) trilha.textContent = CONFIG_GRUPOS.find(g => g.paginas.includes(pagina))?.nome || 'Emily';
  if (rolar) $('.config')?.scrollTo({ top: 0, behavior: 'auto' });
}

function filtrarNavegacaoConfig() {
  const termo = ($('#cfg-busca')?.value || '').normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
  let encontrados = 0;
  $$('.cfg-nav-grupo').forEach(grupo => {
    let visiveis = 0;
    $$('.cfg-nav-item', grupo).forEach(b => {
      const texto = b.dataset.cfgBusca || '';
      b.hidden = !!termo && !texto.includes(termo);
      if (!b.hidden) visiveis++;
    });
    grupo.hidden = visiveis === 0;
    encontrados += visiveis;
  });
  const vazio = $('#cfg-nav-vazio');
  if (vazio) vazio.hidden = encontrados > 0;
}

function montarNavegacaoConfig() {
  const nav = $('#cfg-nav');
  if (!nav) return;
  nav.innerHTML = CONFIG_GRUPOS.map(grupo => `
    <div class="cfg-nav-grupo">
      <p class="cfg-nav-grupo-titulo">${esc(grupo.nome)}</p>
      ${grupo.paginas.map(p => `<button class="cfg-nav-item" type="button"
        data-cfg-abrir="${p.id}" data-cfg-busca="${esc((p.titulo + ' ' + p.busca)
          .normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase())}">
        ${svg(ICO[p.ico], 'cfg-nav-ico')}<span>${esc(p.titulo)}</span></button>`).join('')}
    </div>`).join('');
  $$('.cfg-nav-item', nav).forEach(b => b.onclick = () => selecionarConfig(b.dataset.cfgAbrir));
  const busca = $('#cfg-busca');
  if (busca) {
    busca.value = '';
    busca.oninput = filtrarNavegacaoConfig;
    busca.onkeydown = e => {
      if (e.key === 'Enter') {
        const primeiro = $('.cfg-nav-item:not([hidden])', nav);
        if (primeiro) { e.preventDefault(); primeiro.click(); busca.blur(); }
      }
    };
  }
  const voltar = $('#cfg-side-voltar');
  if (voltar) {
    voltar.innerHTML = svg(ICO.volta);
    voltar.onclick = () => irPara(ESTADO.atual ? 'chat' : 'inicio');
  }
  const lupa = $('.cfg-side-busca-ico');
  if (lupa) lupa.innerHTML = svg(ICO.lupa);
  selecionarConfig(ESTADO.cfgPagina, { rolar: false });
}

function telaConfig() {
  const sec = document.createElement('section');
  sec.className = 'tela config';
  sec.innerHTML = `
    <div class="config-in">
      <div class="config-topo">
        <span class="cfg-local"><span id="cfg-trilha">Emily</span><span aria-hidden="true">/</span><span id="cfg-pagina-titulo">Automação</span></span>
      </div>
      <div id="cfg-corpo" class="cfg-corpo"><p class="cfg-carregando">Carregando ajustes…</p></div>
    </div>`;
  setTimeout(() => {
    if (!sec.isConnected) return;
    montarConfig();
  }, 0);
  return sec;
}

function secao(titulo, corpoHtml, nota = '', extra = '', id = '') {
  return `<section class="secao"${id ? ` data-cfg-secao="${esc(id)}"` : ''}>
    <div class="secao-cab"><h2>${esc(titulo)}</h2>${extra}</div>
    ${nota ? `<p class="secao-nota">${esc(nota)}</p>` : ''}
    ${corpoHtml}
  </section>`;
}

/* ── Tela de perfil (nome, foto, personalidade) ──────────────────
   Reusa a moldura da tela de configurações (config-in / config-topo). */

function telaPerfil() {
  const sec = document.createElement('section');
  sec.className = 'tela config';
  sec.innerHTML = `
    <div class="config-in">
      <div class="config-topo">
        <button class="btn-voltar" id="perf-voltar">${svg(ICO.volta)}<span>Voltar</span></button>
        <h1>Seu perfil</h1>
      </div>
      <div id="perf-corpo"></div>
    </div>`;
  setTimeout(() => {
    $('#perf-voltar').onclick = () => irPara(ESTADO.atual ? 'chat' : 'inicio');
    montarPerfil();
  }, 0);
  return sec;
}

async function montarPerfil() {
  const corpo = $('#perf-corpo');
  if (!corpo) return;
  const p = await tenta('estado_perfil') || {};
  const inicial = ((p.nome || 'V')[0] || 'V').toUpperCase();

  corpo.innerHTML =
    secao('Identidade', `
      <div class="perf-foto">
        <div class="perf-av" id="perf-av">${p.avatar_usuario ? `<img src="${p.avatar_usuario}" alt="">` : esc(inicial)}</div>
        <div class="perf-foto-txt">
          <button class="btn-linha" id="perf-trocar-foto">Trocar foto</button>
          <small>Sua foto aparece só no seu canto — o retrato da Emily não muda.</small>
        </div>
      </div>
      <label class="campo"><span>Seu nome</span>
        <input id="perf-nome" value="${esc(p.nome || '')}" placeholder="Como a Emily te chama" spellcheck="false">
      </label>`) +
    secao('Personalidade da Emily', `
      <label class="campo"><span>Instruções extras</span>
        <textarea id="perf-pers" rows="5" placeholder="Ex: fala mais curto, me chama de chefe, segura os palavrões quando eu tô no trabalho..." spellcheck="false">${esc(p.personalidade_extra || '')}</textarea>
      </label>`,
      'Isso entra por cima do jeitão dela, sem substituir a base tsundere.') +
    `<div class="perf-salvar"><button class="btn-linha destaque" id="perf-salvar">Salvar</button></div>`;

  $('#perf-trocar-foto').onclick = async () => {
    const uri = await tenta('escolher_avatar');
    if (!uri) { toast('Não troquei a foto', 'erro'); return; }
    $('#perf-av').innerHTML = `<img src="${uri}" alt="">`;
    const pav = $('#perfil-av'); if (pav) pav.innerHTML = `<img src="${uri}" alt="">`;
    // NÃO mexe em _avatarEmily nem no hero: a foto do usuário é do canto só.
    toast('Foto atualizada');
  };
  $('#perf-salvar').onclick = async () => {
    const nome = $('#perf-nome').value.trim();
    const pers = $('#perf-pers').value;
    const ok = await tenta('definir_perfil', nome, pers);
    if (!ok) { toast('Não consegui salvar', 'erro'); return; }
    if (nome) {
      const pn = $('#perfil-nome'); if (pn) pn.textContent = nome;
    }
    toast('Perfil salvo');
  };
}

async function montarConfig() {
  const corpo = $('#cfg-corpo');
  if (!corpo) return;
  const geracao = _navegacaoGeracao;

  /* Tudo que a tela mostra vem numa tacada só. Não há mais a seção "Modos"
     (que puxava listar_modos, lento por importar o catálogo inteiro): o único
     controle de Discord agora é "Acompanhar o Discord", na Automação.
     "Abrir rápido" e as opções de downloads saíram a pedido do Vitor —
     desatualizadas; as ferramentas de download continuam no chat. */
  const [autom, fatos, sis, pessoas, vol, discordMod, pttTecla, gateway] = await Promise.all([
    tenta('estado_automacao'),
    tenta('listar_memoria'), tenta('sistema'),
    tenta('listar_pessoas_discord'),
    tenta('volume_voz'), tenta('discord_modelo'), tenta('ptt_tecla_estado'),
    tenta('gateway_endpoint_estado'),
  ]);
  /* As TVs são leitura de arquivo local (tvs_salvas.json): barata e não
     depende de rede. Vai em chamada separada pra a tela não esperar nada. */
  const tvs = await tenta('tv_dispositivos');
  if (geracao !== _navegacaoGeracao || ESTADO.tela !== 'config' || !corpo.isConnected) return;

  const linhaChave = (id, ico, tit, sub, ligado) => `
    <div class="item">
      ${svg(ico, 'item-ico')}
      <div class="item-txt"><strong>${esc(tit)}</strong><small>${esc(sub)}</small></div>
      <button class="chave" role="switch" data-chave="${id}" aria-label="${esc(tit)}" aria-checked="${!!ligado}"></button>
    </div>`;

  const a = autom || {};
  const volumeCarregado = vol == null ? 1 : Number(vol);
  const volPct = Math.round(Math.max(0, Math.min(150,
    Number.isFinite(volumeCarregado) ? volumeCarregado * 100 : 100)));
  const dm = discordMod || {};
  ESTADO.discordMod = dm;   // ligarConfig() lê daqui (fora do escopo desta fn)
  corpo.innerHTML =
    secao('Automação',
      `<div class="lista">
         ${linhaChave('monitor_discord', ICO.chat, (a.discord_cloud ? 'Acompanhar o Discord na nuvem' : 'Acompanhar o Discord neste PC'),
           (a.discord_cloud ? 'Chat, direct e voz funcionam pela Oracle, mesmo com este PC desligado' : 'Escuta e responde no servidor; ao ligar aqui, desliga no outro computador'), a.monitor_discord)}
         ${linhaChave('autonomia_experimental', ICO.raio, 'Autonomia experimental',
           'Age por conta própria em coisas simples; ordens explícitas do dono dispensam confirmação redundante',
           a.autonomia_experimental)}
         ${linhaChave('espiadinha', ICO.olho, 'Espiadinha',
           'De vez em quando ela dá uma olhadinha na sua aba e comenta algo',
           a.espiadinha)}
         ${linhaChave('mudo', ICO.voz, 'Voz muda',
           'Ela continua respondendo por texto, sem falar', a.mudo)}
         ${a.pet_desktop_disponivel ? linhaChave('pet_desktop_ativo', ICO.pessoa,
           'Emily na área de trabalho',
           'Mostra a Emily animada no Fedora; arraste para mover e clique com o botão direito para abrir o chat',
           a.pet_desktop_ativo) : ''}
         ${a.pet_desktop_disponivel ? `<div class="item">
           ${svg(ICO.pessoa, 'item-ico')}
           <div class="item-txt"><strong>Tamanho da Emily</strong><small>Ajuste a personagem flutuante neste computador</small></div>
           <input type="range" class="vol-slider" id="cfg-pet-tamanho" min="50" max="130" step="5"
                  value="${Math.max(50, Math.min(130, Number(a.pet_desktop_tamanho) || 100))}"
                  aria-label="Tamanho da Emily na área de trabalho">
           <span class="vol-valor" id="cfg-pet-tamanho-valor">${Math.max(50, Math.min(130, Number(a.pet_desktop_tamanho) || 100))}%</span>
         </div>` : ''}
       </div>`, '', '', 'automacao') +
    secao('Voz',
      `<div class="lista">
         <div class="item">
           ${svg(ICO.tecla, 'item-ico')}
           <div class="item-txt"><strong>Tecla para falar</strong><small>Segure para falar com a Emily neste computador</small></div>
           <button class="cfg-ptt-botao" id="cfg-ptt-tecla" type="button" aria-label="Alterar tecla para falar">
             <kbd id="cfg-ptt-rotulo">${esc(pttTecla?.rotulo || 'Botão lateral 2')}</kbd>${svg(ICO.seta, 'ico')}
           </button>
         </div>
         ${linhaChave('voz_delegacao_rapida', ICO.raio, 'Delegação rápida (voz no PC)',
           'Ligado: Luna responde e delega tarefas. Desligado: o modelo selecionado responde diretamente e pode usar todas as ferramentas. Não afeta o Android nem o chat escrito.',
           a.voz_delegacao_rapida ?? true)}
         ${linhaChave('audio_preprocess_denoise', ICO.voz, 'Redução de ruído (RNNoise)',
           'Limpa ruído de fundo antes de enviar o áudio ao Whisper', a.audio_preprocess_denoise)}
         ${linhaChave('audio_preprocess_normalize', ICO.voz, 'Normalizar volume',
           'Equilibra falantes baixos e altos com loudnorm', a.audio_preprocess_normalize)}
         ${linhaChave('audio_preprocess_vad', ICO.voz, 'Cortar silêncio (Silero VAD)',
           'Remove trechos sem fala e reduz alucinações do Whisper', a.audio_preprocess_vad)}
         <div class="item">
           ${svg(ICO.voz, 'item-ico')}
           <div class="item-txt"><strong>Volume da voz</strong><small>Quão alta a Emily fala (afeta o Discord também)</small></div>
           <input type="range" class="vol-slider" id="cfg-volume" min="0" max="150" step="5"
                  value="${volPct}" aria-label="Volume da voz">
           <span class="vol-valor" id="cfg-volume-valor">${volPct}%</span>
         </div>
       </div>`, '', '', 'voz') +
    secao('Modelo do Discord',
      `<div class="lista">
         <div class="item">
           ${svg(ICO.chat, 'item-ico')}
           <div class="item-txt"><strong>Modelo das respostas no Discord</strong><small>Independente do cérebro do chat — troca sem mexer em código</small></div>
         </div>
         <button class="sel-discord-modelo" id="cfg-discord-modelo" type="button"
                 aria-haspopup="menu">
           <span class="sel-rot" id="cfg-discord-modelo-rot"></span>
           ${svg(ICO.seta, 'sel-chev')}
         </button>
       </div>`, '', '', 'discord') +
    secao('Memória',
      `<div class="mem-abas">
        <button class="mem-aba ativa" data-mem="voce" role="tab" aria-selected="true">
          ${svg(ICO.cerebro)}<span>Você</span><span class="mem-conta">${(fatos || []).length}</span>
        </button>
        <button class="mem-aba" data-mem="pessoas" role="tab" aria-selected="false">
          ${svg(ICO.pessoa)}<span>Pessoas do Discord</span><span class="mem-conta">${(pessoas || []).length}</span>
        </button>
        <button class="mem-aba" data-mem="unificada" role="tab" aria-selected="false">
          ${svg(ICO.raio)}<span>Unificada</span><span class="mem-conta" id="memu-conta">…</span>
        </button>
      </div>
      <div id="cfg-mem"></div>
      <div id="cfg-mem-pessoas" hidden></div>
      <div id="cfg-mem-unificada" hidden></div>`,
      'O que ela lembra de você e de quem fala com ela no Discord.', '', 'memoria') +
    secao('Este computador', medidores(sis || {}), '', '', 'sistema') +
    secao('TV',
      `<div id="cfg-tv"></div>
       <p class="secao-nota" id="cfg-tv-status" hidden></p>`,
      'A Emily controla Android TV pelo mesmo protocolo do celular — clique numa TV pra conectar. "Parear" é só na primeira vez: a TV mostra um código e você digita aqui.',
      `<button class="btn-linha tv-add" id="cfg-tv-add" type="button" aria-label="Adicionar TV">${svg('<path d="M12 5v14M5 12h14"/>')}<span>Adicionar</span></button>`, 'tv') +
    secao('Conexão do celular', gateway?.disponivel ? (gateway.modo === 'oracle' ? `
      <div class="lista cfg-gateway-card"><div class="item"><div class="item-txt"><strong>Emily na Oracle</strong><small id="cfg-gateway-status"></small></div></div>
      <button class="btn-linha destaque" id="cfg-gateway-parear" type="button">Gerar código para dispositivo</button>
      <p class="secao-nota" id="cfg-gateway-pair-code" role="status" aria-live="polite"></p></div>` : `
      <div class="lista cfg-gateway-card">
        <div class="item">
          ${svg(ICO.monitor, 'item-ico')}
          <div class="item-txt"><strong>Gateway do Fedora</strong><small id="cfg-gateway-status"></small></div>
        </div>
        <div class="cfg-gateway-controles">
          <label class="campo"><span>Endereço público do ngrok</span>
            <input id="cfg-gateway-url" type="url" spellcheck="false" autocomplete="off"
              value="${esc(gateway.url || '')}" placeholder="https://seu-endereco.ngrok-free.dev">
          </label>
          <div class="cfg-gateway-acoes">
            <button class="btn-linha destaque" id="cfg-gateway-salvar" type="button">Salvar e conectar</button>
            <button class="btn-linha" id="cfg-gateway-reiniciar" type="button">Reiniciar gateway</button>
          </div>
          <p class="secao-nota" id="cfg-gateway-aviso" role="status" aria-live="polite"></p>
        </div>
      </div>`) : `<p class="secao-nota">Essa conexão é administrada no computador Fedora que hospeda o gateway.</p>`,
      gateway?.modo === 'oracle' ? 'A conexão do PC é automática. Gere um código e informe no celular; ele vale por 10 minutos e pode ser usado uma vez.' : 'Troque o endereço quando mudar a conta ou o domínio no ngrok. O Cloud Endpoint precisa encaminhar para https://default.internal.', '', 'gateway') +
    secao('Atualização',
      `<div id="cfg-atualizacao"><p class="secao-nota">Verificando…</p></div>`,
      'O código e os recursos da Emily são atualizados direto da pasta do projeto. Bibliotecas nativas novas ainda podem exigir recompilação.', '', 'atualizacao');

  selecionarConfig(ESTADO.cfgPagina, { rolar: false });
  ligarConfig();
  atualizarGatewayEndpoint(gateway);
  desenharTv(tvs || []);
  desenharAtualizacao();
  ESTADO.pessoas = pessoas || [];
  ESTADO.pessoaPag = 0;
  ligarMemAbas();
  desenharFatos(fatos || []);
  montarMemUnificada();
}

/* ── TV: dispositivos salvos, conectar, parear ─────────────────────
   Mesma lógica da aba TV do celular: lista com nome, IP embaixo e tipo;
   clicar conecta; tudo editável. O desfecho de conectar/parear volta por
   evento 'tv' (as chamadas passam do teto do api() de propósito). */

const _tvStatusEl = () => $('#cfg-tv-status');

function tvAvisar(texto, tipo = '') {
  const el = _tvStatusEl();
  if (!el) { toast(texto, tipo); return; }
  el.hidden = false;
  el.textContent = texto;
  el.style.color = tipo === 'erro' ? 'var(--erro)' : (tipo === 'ok' ? 'var(--ok)' : '');
}

async function redesenharTv() {
  const box = $('#cfg-tv');
  if (!box) return;
  const lista = await tenta('tv_dispositivos');
  desenharTv(lista || []);
}

function desenharTv(dispositivos) {
  const box = $('#cfg-tv');
  if (!box) return;
  if (!dispositivos.length) {
    box.innerHTML = '<p class="secao-nota">Nenhuma TV salva. Adicione o IP dela — o nome e o tipo você escolhe.</p>';
    return;
  }
  box.innerHTML = `<div class="tv-lista">${dispositivos.map(d => `
    <div class="item clicavel tv-card ${d.ativa ? 'tv-ativa' : ''}" data-tv="${esc(d.id)}">
      ${svg(ICO.monitor, 'item-ico')}
      <div class="item-txt">
        <strong>${esc(d.nome || 'TV')}</strong>
        <small>${esc(d.ip)}${d.tipo ? ` · ${esc(d.tipo)}` : ''}${d.pareada ? '' : ' · não pareada'}</small>
      </div>
      <div class="tv-acoes">
        <button class="btn-linha tv-btn" data-tv-acao="parear" data-tv="${esc(d.id)}"
                type="button" aria-label="Parear ${esc(d.nome || 'TV')}"
                title="Parear (primeira vez): a TV mostra o código">${svg(ICO.raio)}</button>
        <button class="btn-linha tv-btn" data-tv-acao="editar" data-tv="${esc(d.id)}"
                type="button" aria-label="Editar ${esc(d.nome || 'TV')}"
                title="Editar nome, IP e tipo">${svg(ICO.lapis)}</button>
        <button class="btn-linha tv-btn perigo" data-tv-acao="remover" data-tv="${esc(d.id)}"
                type="button" aria-label="Remover ${esc(d.nome || 'TV')}"
                title="Remover da lista">${svg(ICO.lixo)}</button>
      </div>
    </div>`).join('')}</div>`;

  $$('.tv-card', box).forEach(card => {
    card.onclick = e => {
      if (e.target.closest('[data-tv-acao]')) return;   // só o corpo conecta
      const id = card.dataset.tv;
      tvAvisar('Conectando…');
      tenta('tv_conectar', id);
    };
  });
  $$('[data-tv-acao]', box).forEach(b => {
    b.onclick = async e => {
      e.stopPropagation();
      const id = b.dataset.tv, acao = b.dataset.tvAcao;
      const d = dispositivos.find(x => x.id === id);
      if (acao === 'parear') {
        tvAvisar('Pedindo código à TV…');
        tenta('tv_parear', id);
      } else if (acao === 'editar') {
        const campos = await tvModalCampos(d || null);
        if (!campos) return;
        if (!campos.ip) { tvAvisar('Informe o IP da TV.', 'erro'); return; }
        const r = await tenta('tv_editar', id, campos.nome, campos.ip, campos.tipo);
        if (r && r.ok === false) { tvAvisar(r.mensagem || 'Falhou', 'erro'); return; }
        tvAvisar('TV atualizada ✓', 'ok');
        redesenharTv();
      } else if (acao === 'remover') {
        const ok = await modal({ titulo: 'Remover TV',
                                 texto: 'Tira este dispositivo da lista (o pareamento na TV continua lá, sem problema).',
                                 ok: 'Remover', perigo: true });
        if (!ok) return;
        await tenta('tv_remover', id);
        tvAvisar('TV removida da lista.', 'ok');
        redesenharTv();
      }
    };
  });
}

/* Diálogo de 3 campos (nome / IP / tipo) — o modal() padrão aceita um campo
   só, e aqui os três são editáveis de propósito (a detecção nem sempre acerta). */
function tvModalCampos(d = null) {
  return new Promise(resolve => {
    const fundo = $('#modal-fundo');
    fundo.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <h3>${d ? 'Editar TV' : 'Adicionar TV'}</h3>
        <label class="campo"><span>Nome</span>
          <input id="tv-nome" value="${esc(d?.nome || '')}" placeholder="ex: TV da Sala" spellcheck="false">
        </label>
        <label class="campo"><span>IP</span>
          <input id="tv-ip" value="${esc(d?.ip || '')}" placeholder="ex: 192.168.0.15" spellcheck="false">
        </label>
        <label class="campo"><span>Tipo <small>(opcional — você sabe melhor)</small></span>
          <input id="tv-tipo" value="${esc(d?.tipo || '')}" placeholder="ex: TCL Android TV" spellcheck="false">
        </label>
        <div class="modal-acoes">
          <button class="btn-linha" id="tv-cancel">Cancelar</button>
          <button class="btn-linha primario" id="tv-ok">Salvar</button>
        </div>
      </div>`;
    fundo.hidden = false;
    $('#tv-nome').focus();
    const fecha = val => {
      resolve(val);
      fundo.classList.add('saindo');
      let limpou = false;
      const limpar = () => {
        if (limpou) return;
        limpou = true;
        fundo.classList.remove('saindo');
        fundo.hidden = true;
        fundo.innerHTML = '';
      };
      fundo.addEventListener('animationend', limpar, { once: true });
      setTimeout(limpar, 220);
    };
    $('#tv-ok').onclick = () => fecha({
      nome: $('#tv-nome').value.trim(), ip: $('#tv-ip').value.trim(),
      tipo: $('#tv-tipo').value.trim(),
    });
    $('#tv-cancel').onclick = () => fecha(null);
    fundo.onclick = e => { if (e.target === fundo) fecha(null); };
  });
}

async function tvEvento(d) {
  switch (d.tipo) {
    case 'conectado':
      tvAvisar(d.mensagem || 'Conectada ✓', 'ok');
      toast(d.mensagem || 'TV conectada');
      redesenharTv();
      break;
    case 'precisa_parear':
      tvAvisar('Esta TV não pareou com a Emily do PC ainda. Toque no raio ⚡ pra parear.');
      break;
    case 'codigo_pedindo': {
      const codigo = await modal({
        titulo: 'Código da TV',
        texto: 'Digite o código que aparece na tela da TV:',
        campo: '', ok: 'Confirmar',
      });
      if (codigo === null || codigo === '') { tvAvisar('Pareamento cancelado'); break; }
      tvAvisar('Concluindo pareamento…');
      tenta('tv_codigo', codigo);
      break;
    }
    case 'pareado':
      tvAvisar(d.mensagem || 'Pareada ✓ — conectando…', 'ok');
      toast(d.mensagem || 'TV pareada!');
      setTimeout(redesenharTv, 800);
      break;
    case 'erro':
      tvAvisar(d.mensagem || 'Algo falhou com a TV.', 'erro');
      break;
    default:
      console.warn('[emily] tv: evento desconhecido', d);
  }
}

/* ── Atualização: estado + aplicar/desfazer ─────────────────────────
   O exe tem o motor embutido (bibliotecas) e o código por cima (que é
   atualizável, inclusive main.py nos builds com bootstrap). O botão sincroniza
   com a pasta do projeto, ensaia tudo
   num preflight e só então aplica e reinicia. No modo fonte, a seção
   mostra que as mudanças já valem ao reiniciar. */

async function checarAtualizacaoAoAbrir() {
  // A API reserva esta checagem ao primeiro carregamento completo do processo.
  // Reabrir pela bandeja ou recarregar a WebView não deve repetir o ensaio.
  let estado;
  try {
    estado = await api('emily_atualizacao_inicio', { teto: 30000 });
  } catch (e) {
    console.warn('[emily] checagem de atualização indisponível:', e);
    return;
  }
  if (!estado?.verificar) return;

  const fundo = $('#atualizacao-fundo');
  if (!fundo) return;
  const titulo = $('#atualizacao-titulo');
  const texto = $('#atualizacao-texto');
  const fechar = $('#atualizacao-fechar');
  fundo.classList.remove('falha');
  titulo.textContent = 'Atualizando a Emily';
  texto.textContent = `${estado.quantos} mudança(s) encontrada(s). Validando antes de reiniciar…`;
  fechar.hidden = true;
  fundo.hidden = false;
  // A WebView precisa pintar o primeiro frame antes do preflight pesado começar.
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  let resultado;
  try {
    resultado = await api('emily_atualizar_aplicar', { teto: 240000 });
  } catch (e) {
    resultado = `Falha ao atualizar: ${e.message || e}`;
  }
  if (String(resultado || '').startsWith('OK Atualização aplicada:')) {
    titulo.textContent = 'Tudo pronto';
    texto.textContent = 'Reiniciando a Emily…';
    // O backend já agenda o reinício; não reiniciar/recarregar aqui.
    return;
  }
  fundo.classList.add('falha');
  titulo.textContent = 'Não consegui atualizar';
  texto.textContent = String(resultado || 'Falha desconhecida.').slice(0, 400);
  fechar.hidden = false;
  fechar.onclick = () => { fundo.hidden = true; };
  // Sem reinício em caso de erro: a versão anterior segue disponível.
}

async function desenharAtualizacao() {
  const box = $('#cfg-atualizacao');
  if (!box) return;
  const st = await tenta('emily_atualizacao_estado') || {};

  if (st.modo_windows) {
    const publicada = st.versao_publicada ? ` · publicada: ${esc(st.versao_publicada)}` : '';
    box.innerHTML = `<p class="secao-nota">Versão instalada: ${esc(st.versao || 'desconhecida')}${publicada}. A Emily verifica novas versões ao abrir.</p>` +
      (st.erro ? `<p class="secao-nota">${esc(st.erro)}</p>` : '') +
      (st.quantos ? '<button class="btn-linha destaque" id="att-windows">Instalar versão nova</button>' : '');
    const instalar = $('#att-windows');
    if (instalar) instalar.onclick = async () => {
      instalar.disabled = true;
      instalar.textContent = 'Baixando e conferindo…';
      const resposta = await api('emily_atualizar_aplicar', { teto: 240000 })
        .catch(e => `Falhou: ${e.message || e}`);
      toast(String(resposta || '').slice(0, 180), String(resposta || '').startsWith('OK') ? undefined : 'erro');
      if (!String(resposta || '').startsWith('OK')) desenharAtualizacao();
    };
    return;
  }

  if (!st.em_pacote) {
    box.innerHTML = `<p class="secao-nota">Rodando do código-fonte: as mudanças que você fizer valem ao reiniciar a Emily.</p>`;
    return;
  }
  if (!st.origem_ok) {
    box.innerHTML = `<p class="secao-nota">Não achei a pasta do projeto (${esc(st.origem || 'origem não registrada')}). Se ela foi movida, selecione a pasta que contém main.py.</p>` +
      `<button class="btn-linha destaque" id="att-origem">Escolher pasta do projeto</button>` +
      (st.pode_desfazer ? `<button class="btn-linha" id="att-desfazer">Desfazer última atualização</button>` : '');
  } else if (!st.quantos) {
    box.innerHTML = `<p class="secao-nota">Tudo em dia — o pacote está igual ao código do projeto.${st.ultima ? ` Última atualização: ${esc(st.ultima)}.` : ''}</p>` +
      (st.pode_desfazer ? `<button class="btn-linha" id="att-desfazer">Desfazer última atualização</button>` : '');
  } else {
    box.innerHTML = `
      <p class="secao-nota"><strong>${st.quantos} mudança(s)</strong> esperando: ${esc(st.resumo || '')}</p>
      ${st.main_mudou ? `<p class="secao-nota" style="color:var(--txt-2)">⚠ Este executável é de antes do bootstrap: faça uma última recompilação para liberar atualizações futuras do main.py. O resto atualiza normal.</p>` : ''}
      <button class="btn-linha destaque" id="att-aplicar">Atualizar agora e reiniciar</button>
      ${st.pode_desfazer ? `<button class="btn-linha" id="att-desfazer">Desfazer última atualização</button>` : ''}`;
  }

  const ap = $('#att-aplicar');
  if (ap) ap.onclick = async () => {
    if (ap.dataset.rodando === '1') return;   // 2º clique: já está rodando
    ap.dataset.rodando = '1';
    ap.disabled = true;
    ap.textContent = 'Validando e aplicando…';
    // O ensaio importa o pacote inteiro e leva MINUTOS: a espera aqui é
    // longa DE PROPÓSITO e independe do teto padrão de chamada.
    const r = await api('emily_atualizar_aplicar', { teto: 240000 })
      .catch(e => `Falhou: ${e.message || e}`);
    if (r && String(r).startsWith('OK')) {
      toast('Atualizado! Reiniciando a Emily…');
      setTimeout(() => location.reload(), 3500);
    } else {
      toast(String(r || 'Falhou').slice(0, 120), 'erro');
      ap.disabled = false;
      delete ap.dataset.rodando;
      ap.textContent = 'Atualizar agora e reiniciar';
      desenharAtualizacao();   // re-render: pendências mudaram (ensaio/erro)
    }
  };
  const origem = $('#att-origem');
  if (origem) origem.onclick = async () => {
    origem.disabled = true;
    origem.textContent = 'Escolhendo…';
    const r = await api('emily_atualizacao_escolher_origem', { teto: 120000 })
      .catch(e => `Falhou: ${e.message || e}`);
    if (r && String(r).startsWith('OK')) {
      toast('Pasta do projeto registrada.');
    } else if (r !== 'Cancelado.') {
      toast(String(r || 'Falhou').slice(0, 160), 'erro');
    }
    desenharAtualizacao();
  };
  const df = $('#att-desfazer');
  if (df) df.onclick = async () => {
    df.disabled = true;
    const r = await tenta('emily_atualizar_desfazer');
    if (r && String(r).startsWith('OK')) {
      toast('Revertido! Reiniciando a Emily…');
      setTimeout(() => location.reload(), 3500);
    } else {
      toast(String(r || 'Falhou').slice(0, 120), 'erro');
      df.disabled = false;
    }
  };
}

/* ── Memória: abas "Você" / "Pessoas do Discord" ───────────────────
   A memória da Emily não é só sobre o Vitor: no Discord ela guarda fatos
   por pessoa (perfil_discord → memoria_discord.json). As abas separam os
   dois mundos sem virar duas telas. */

function ligarMemAbas() {
  $$('.mem-aba').forEach(aba => aba.onclick = () => {
    $$('.mem-aba').forEach(a => {
      a.classList.toggle('ativa', a === aba);
      a.setAttribute('aria-selected', String(a === aba));
    });
    const alvo = aba.dataset.mem;
    const vo = $('#cfg-mem'), px = $('#cfg-mem-pessoas'), uf = $('#cfg-mem-unificada');
    if (vo) vo.hidden = alvo !== 'voce';
    if (px) px.hidden = alvo !== 'pessoas';
    if (uf) uf.hidden = alvo !== 'unificada';
    if (alvo === 'pessoas') desenharPessoas();
    if (alvo === 'unificada') desenharMemUnificada();
  });
}

/* ── Memória, paginada ─────────────────────────────────────────────
   Eram 140 fatos numa lista só — um scroll interminável. Agora vão de
   POR_PAGINA em POR_PAGINA, cada um compacto (duas linhas, expande no
   clique), com um contador e setas. */

const FATOS_POR_PAGINA = 8;

function desenharFatos(lista) {
  if (lista !== undefined) { ESTADO.fatos = lista; ESTADO.fatoPag = 0; }
  const box = $('#cfg-mem');
  if (!box) return;

  const fatos = ESTADO.fatos || [];
  const paginas = Math.max(1, Math.ceil(fatos.length / FATOS_POR_PAGINA));
  ESTADO.fatoPag = Math.min(Math.max(0, ESTADO.fatoPag || 0), paginas - 1);
  const ini = ESTADO.fatoPag * FATOS_POR_PAGINA;
  const pagina = fatos.slice(ini, ini + FATOS_POR_PAGINA);

  const linhas = pagina.map(f => `
    <div class="fato">
      ${svg(ICO.cerebro, 'item-ico')}
      <span class="fato-txt" title="clique pra ler inteiro">${esc(f)}</span>
      <button class="icone-btn mini fato-x" data-fato="${encodeURIComponent(f)}" aria-label="Esquecer este fato" title="Esquecer">${svg(ICO.x)}</button>
    </div>`).join('') ||
    `<div class="fato"><span class="fato-txt" style="color:var(--txt-3)">Nada guardado ainda.</span></div>`;

  const controles = paginas > 1 ? `
    <div class="paginacao">
      <button class="pg-btn" id="pg-ant" ${ESTADO.fatoPag === 0 ? 'disabled' : ''}>${svg(ICO.volta)}</button>
      <span class="pg-cont">${ESTADO.fatoPag + 1} / ${paginas} · ${fatos.length} fatos</span>
      <button class="pg-btn" id="pg-prox" ${ESTADO.fatoPag >= paginas - 1 ? 'disabled' : ''}>${svg(ICO.seta)}</button>
    </div>` : (fatos.length
      ? `<p class="secao-nota" style="text-align:center;margin-top:var(--r2)">${fatos.length} fato${fatos.length > 1 ? 's' : ''}</p>`
      : '');

  box.innerHTML = `
    <div class="lista fatos">${linhas}
      <div class="add-fato">
        ${svg(ICO.raio, 'item-ico')}
        <input id="cfg-novo-fato" placeholder="Ensinar um fato novo sobre você" spellcheck="false">
        <button class="btn-linha" id="cfg-add-fato">Guardar</button>
      </div>
    </div>${controles}`;

  ligarFatos();
}

function ligarFatos() {
  const box = $('#cfg-mem');
  if (!box) return;

  // Clicar no texto expande/recolhe o fato longo.
  $$('.fato-txt', box).forEach(t => t.onclick = () => t.classList.toggle('aberto'));

  $$('[data-fato]', box).forEach(b => b.onclick = async () => {
    const fato = decodeURIComponent(b.dataset.fato);
    const linha = b.closest('.fato');
    linha.classList.add('saindo');
    await tenta('del_fato', fato);
    ESTADO.fatos = (ESTADO.fatos || []).filter(f => f !== fato);
    setTimeout(() => desenharFatos(), 200);   // sem argumento = mantém a página
  });

  const addFato = async () => {
    const inp = $('#cfg-novo-fato', box);
    const txt = inp.value.trim();
    if (!txt) return;
    await tenta('add_fato', txt);
    ESTADO.fatos = [txt, ...(ESTADO.fatos || [])];
    ESTADO.fatoPag = 0;
    toast('Guardado na memória');
    desenharFatos();
  };
  const addBtn = $('#cfg-add-fato', box);
  const addInp = $('#cfg-novo-fato', box);
  if (addBtn) addBtn.onclick = addFato;
  if (addInp) addInp.onkeydown = e => { if (e.key === 'Enter') addFato(); };

  const ant = $('#pg-ant', box), prox = $('#pg-prox', box);
  if (ant) ant.onclick = () => { ESTADO.fatoPag--; desenharFatos(); };
  if (prox) prox.onclick = () => { ESTADO.fatoPag++; desenharFatos(); };
}

/* ── Memória unificada (sistema novo) ─────────────────────────────
   Terceira aba da seção Memória. Mostra o estado do sistema (flag,
   circuit breaker, contadores), busca com filtros e cards por fato com
   origem/importância/tópico e ações esquecer/reativar. Desabilitada com
   uma explicação honesta quando a flag está desligada. */

const MEMU_POR_PAGINA = 8;

async function montarMemUnificada() {
  const estado = await tenta('memoria_unificada_estado') || {};
  ESTADO.memu = { estado, fatos: [], pag: 0, busca: '', status: 'active', pool: 'todos' };
  const conta = $('#memu-conta');
  if (conta) conta.textContent = estado.ativa ? '…' : 'off';
  desenharMemUnificada();
  if (estado.ativa) await recarregarMemUnificada();
}

function _memuData(bruto) {
  const d = new Date((bruto || 0) * 1000);
  if (isNaN(d.getTime())) return '—';
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getDate())}/${p(d.getMonth() + 1)} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function _memuEtiqueta(fato) {
  const mapa = {
    biography: 'biografia', strong_preference: 'preferência',
    assistant_preference: 'como ela deve agir', health: 'saúde',
    project_context: 'projeto', decision: 'decisão',
    commitment: 'compromisso', relationship: 'relação',
    architecture_decision: 'decisão técnica', bug_resolution: 'bug resolvido',
    technical_preference: 'preferência técnica', migration: 'migração',
    completed_work: 'trabalho concluído',
  };
  return mapa[fato.topico] || (fato.topico || 'fato');
}

function desenharMemUnificada() {
  const box = $('#cfg-mem-unificada');
  if (!box) return;
  const { estado, busca, status, pool } = ESTADO.memu;

  if (!estado.ativa) {
    const motivo = estado.desativada_por_erro
      ? `pausada após erros — nova tentativa automática em ${esc(estado.reativar_em_segundos ?? 0)}s`
      : estado.flag === false
        ? 'desligada no .env (defina EMILY_MEMORIA_UNIFICADA=1)'
        : 'indisponível porque a configuração não pôde ser carregada';
    box.innerHTML = `
      <div class="lista fatos">
        <div class="fato">
          ${svg(ICO.cerebro, 'item-ico')}
          <span class="fato-txt" style="color:var(--txt-3)">
            Memória unificada ${esc(motivo)}.
            A memória antiga da aba "Você" continua valendo normalmente.
          </span>
        </div>
      </div>
      ${estado.erro ? `<p class="secao-nota" style="margin-top:var(--r2);color:var(--erro)">Detalhe: ${esc(estado.erro)}</p>` : ''}
      ${estado.pasta_dados ? `<p class="secao-nota" style="margin-top:var(--r2)">Pasta de dados: <code>${esc(estado.pasta_dados)}</code></p>` : ''}`;
    return;
  }

  const sel = (valor, atual, rotulo) =>
    `<option value="${esc(valor)}" ${valor === atual ? 'selected' : ''}>${esc(rotulo)}</option>`;

  box.innerHTML = `
    <div class="memu-status ${estado.modo_degradado ? 'parcial' : ''}">
      <span class="memu-ponto"></span>
      <strong>${estado.modo_degradado ? 'Modo parcial' : 'Ativa'}</strong>
      <small>${esc(estado.eventos_total ?? 0)} eventos · embeddings: ${esc(estado.provedor_embeddings || '?')}/${esc(estado.modelo_embeddings || '?')}</small>
      ${estado.modo_degradado ? `<small class="memu-aviso">journal e contexto recente ativos · ${esc(estado.lotes_pendentes ?? 0)} lote(s) aguardando</small>` : ''}
    </div>
    ${estado.modo_degradado && estado.erro ? `<p class="secao-nota memu-aviso">Camada de longo prazo indisponível: ${esc(estado.erro)}</p>` : ''}
    <div class="memu-filtros">
      <input id="memu-busca" placeholder="Buscar na memória" value="${esc(busca)}" spellcheck="false">
      <select id="memu-status" aria-label="Estado">
        ${sel('active', status, 'Ativos')}${sel('superseded', status, 'Desatualizados')}${sel('forgotten', status, 'Esquecidos')}${sel('todos', status, 'Todos')}
      </select>
      <select id="memu-pool" aria-label="Pool">
        ${sel('todos', pool, 'Tudo')}${sel('general', pool, 'Geral')}${sel('code', pool, 'Code')}
      </select>
    </div>
    <div class="lista fatos" id="memu-lista"></div>
    <div id="memu-controles"></div>`;

  $('#memu-busca').onkeydown = e => {
    if (e.key === 'Enter') {
      ESTADO.memu.busca = e.target.value.trim();
      ESTADO.memu.pag = 0;
      recarregarMemUnificada();
    }
  };
  $('#memu-status').onchange = e => {
    ESTADO.memu.status = e.target.value; ESTADO.memu.pag = 0; recarregarMemUnificada();
  };
  $('#memu-pool').onchange = e => {
    ESTADO.memu.pool = e.target.value; ESTADO.memu.pag = 0; recarregarMemUnificada();
  };

  desenharMemUnificadaLista();
}

function desenharMemUnificadaLista() {
  const lista = $('#memu-lista'), controles = $('#memu-controles');
  if (!lista) return;
  const fatos = ESTADO.memu.fatos || [];
  const paginas = Math.max(1, Math.ceil(fatos.length / MEMU_POR_PAGINA));
  ESTADO.memu.pag = Math.min(Math.max(0, ESTADO.memu.pag || 0), paginas - 1);
  const ini = ESTADO.memu.pag * MEMU_POR_PAGINA;
  const pagina = fatos.slice(ini, ini + MEMU_POR_PAGINA);
  const conta = $('#memu-conta');
  if (conta) conta.textContent = String(fatos.length);

  const barra = n => `<span class="memu-imp" title="importância ${n}/10">${'●'.repeat(n)}${'○'.repeat(10 - n)}</span>`;

  const linhas = pagina.map(f => `
    <div class="fato memu-fato ${f.status !== 'active' ? 'memu-inativo' : ''}">
      ${svg(ICO.cerebro, 'item-ico')}
      <div class="memu-corpo">
        <span class="fato-txt" title="clique pra ler inteiro">${esc(f.texto)}</span>
        <small class="memu-meta">
          ${esc(_memuEtiqueta(f))} · ${esc(f.canal || '?')} · ${barra(Math.max(1, Math.min(10, f.importancia || 1)))} · ${_memuData(f.atualizado_em)}${f.status !== 'active' ? ` · ${f.status === 'superseded' ? 'desatualizado' : 'esquecido'}` : ''}
        </small>
      </div>
      ${f.status === 'active'
        ? `<button class="icone-btn mini fato-x" data-memu-esquecer="${esc(f.id)}" aria-label="Esquecer" title="Esquecer">${svg(ICO.x)}</button>`
        : `<button class="icone-btn mini" data-memu-reativar="${esc(f.id)}" aria-label="Reativar" title="Reativar">${svg(ICO.volta)}</button>`}
    </div>`).join('') ||
    `<div class="fato"><span class="fato-txt" style="color:var(--txt-3)">Nada aqui${ESTADO.memu.busca ? ' pra essa busca' : ''}.</span></div>`;

  lista.innerHTML = linhas;

  controles.innerHTML = paginas > 1 ? `
    <div class="paginacao">
      <button class="pg-btn" id="memu-ant" ${ESTADO.memu.pag === 0 ? 'disabled' : ''}>${svg(ICO.volta)}</button>
      <span class="pg-cont">${ESTADO.memu.pag + 1} / ${paginas} · ${fatos.length} memórias</span>
      <button class="pg-btn" id="memu-prox" ${ESTADO.memu.pag >= paginas - 1 ? 'disabled' : ''}>${svg(ICO.seta)}</button>
    </div>` : '';

  $$('.fato-txt', lista).forEach(t => t.onclick = () => t.classList.toggle('aberto'));
  $$('[data-memu-esquecer]', lista).forEach(b => b.onclick = async () => {
    b.disabled = true;
    if (await tenta('memoria_unificada_esquecer', b.dataset.memuEsquecer)) {
      toast('Esquecido (pode ser reativado)');
      await recarregarMemUnificada('forgotten');
    } else toast('Não consegui esquecer', 'erro');
  });
  $$('[data-memu-reativar]', lista).forEach(b => b.onclick = async () => {
    b.disabled = true;
    if (await tenta('memoria_unificada_reativar', b.dataset.memuReativar)) {
      toast('Reativado');
      await recarregarMemUnificada('active');
    } else toast('Não consegui reativar', 'erro');
  });
  const ant = $('#memu-ant', controles), prox = $('#memu-prox', controles);
  if (ant) ant.onclick = () => { ESTADO.memu.pag--; desenharMemUnificadaLista(); };
  if (prox) prox.onclick = () => { ESTADO.memu.pag++; desenharMemUnificadaLista(); };
}

async function recarregarMemUnificada(statusOpcional) {
  if (statusOpcional) ESTADO.memu.status = statusOpcional;
  const fatos = await tenta(
    'memoria_unificada_listar', ESTADO.memu.busca,
    ESTADO.memu.status, ESTADO.memu.pool) || [];
  ESTADO.memu.fatos = fatos;
  ESTADO.memu.pag = 0;
  desenharMemUnificadaLista();
}

/* ── Memória das pessoas do Discord, paginada igual aos fatos ──────
   Cartão por pessoa: cabeçalho com avatar, contadores, e o corpo que abre
   no clique com os fatos (add/remove) e campo pra ensinar fato novo. */

const PESSOAS_POR_PAGINA = 6;

function desenharPessoas(lista) {
  if (lista !== undefined) { ESTADO.pessoas = lista; ESTADO.pessoaPag = 0; }
  const box = $('#cfg-mem-pessoas');
  if (!box) return;

  const pessoas = ESTADO.pessoas || [];
  const paginas = Math.max(1, Math.ceil(pessoas.length / PESSOAS_POR_PAGINA));
  ESTADO.pessoaPag = Math.min(Math.max(0, ESTADO.pessoaPag || 0), paginas - 1);
  const ini = ESTADO.pessoaPag * PESSOAS_POR_PAGINA;
  const pagina = pessoas.slice(ini, ini + PESSOAS_POR_PAGINA);

  const fichaFatos = p => (p.fatos || []).map(f => `
      <div class="fato">
        ${svg(ICO.cerebro, 'item-ico')}
        <span class="fato-txt" title="clique pra ler inteiro">${esc(f)}</span>
        <button class="icone-btn mini fato-x" data-fato="${encodeURIComponent(f)}"
                title="Esquecer esse fato">${svg(ICO.x)}</button>
      </div>`).join('') ||
    `<div class="fato"><span class="fato-txt" style="color:var(--txt-3)">Nada guardado sobre essa pessoa ainda.</span></div>`;

  const cartoes = pagina.map(p => {
    const n = (p.fatos || []).length;
    return `
    <div class="pessoa" data-uid="${esc(p.id)}">
      <div class="pessoa-cab" title="clique pra abrir a memória">
        <span class="pessoa-av">${esc((p.nome || '?')[0].toUpperCase())}</span>
        <div class="pessoa-txt">
          <strong>${esc(p.nome)}</strong>
          <small>${p.mensagens} mensagem${p.mensagens === 1 ? '' : 's'} ·
                 ${p.interacoes} conversa${p.interacoes === 1 ? '' : 's'} ·
                 ${n} fato${n === 1 ? '' : 's'}</small>
        </div>
        ${svg(ICO.seta, 'item-seta')}
      </div>
      <div class="pessoa-corpo" hidden>
        <div class="lista fatos">${fichaFatos(p)}
          <div class="add-fato">
            ${svg(ICO.raio, 'item-ico')}
            <input placeholder="Ensinar um fato sobre ${esc(p.nome)}" spellcheck="false">
            <button class="btn-linha">Guardar</button>
          </div>
        </div>
      </div>
    </div>`;
  }).join('') ||
    `<div class="fato"><span class="fato-txt" style="color:var(--txt-3)">
       Ninguém na memória ainda — ela guarda fatos das conversas no Discord
       quando está acompanhando o servidor.</span></div>`;

  const controles = paginas > 1 ? `
    <div class="paginacao">
      <button class="pg-btn" id="px-ant" ${ESTADO.pessoaPag === 0 ? 'disabled' : ''}>${svg(ICO.volta)}</button>
      <span class="pg-cont">${ESTADO.pessoaPag + 1} / ${paginas} · ${pessoas.length} pessoa${pessoas.length > 1 ? 's' : ''}</span>
      <button class="pg-btn" id="px-prox" ${ESTADO.pessoaPag >= paginas - 1 ? 'disabled' : ''}>${svg(ICO.seta)}</button>
    </div>` : (pessoas.length
      ? `<p class="secao-nota" style="text-align:center;margin-top:var(--r2)">${pessoas.length} pessoa${pessoas.length > 1 ? 's' : ''} na memória</p>`
      : '');

  box.innerHTML = cartoes + controles;
  ligarPessoas();
}

function ligarPessoas() {
  const box = $('#cfg-mem-pessoas');
  if (!box) return;

  const uidDe = el => el.closest('.pessoa')?.dataset.uid;

  // Abrir/fechar o cartão.
  $$('.pessoa-cab', box).forEach(cab => cab.onclick = () => {
    const corpo = cab.nextElementSibling;
    if (corpo) corpo.hidden = !corpo.hidden;
    cab.classList.toggle('aberto');
  });

  // Fato longo expande no clique (mesmo gesto dos fatos do Vitor).
  $$('.fato-txt', box).forEach(t => t.onclick = () => t.classList.toggle('aberto'));

  // Esquecer um fato.
  $$('[data-fato]', box).forEach(b => b.onclick = async () => {
    const uid = uidDe(b);
    const fato = decodeURIComponent(b.dataset.fato);
    const linha = b.closest('.fato');
    linha.classList.add('saindo');
    await tenta('del_fato_pessoa', uid, fato);
    const p = (ESTADO.pessoas || []).find(x => x.id === uid);
    if (p) p.fatos = (p.fatos || []).filter(f => f !== fato);
    setTimeout(() => desenharPessoas(), 200);
    toast('Fato esquecido');
    atualizarContaPessoas();
  });

  // Ensinar um fato novo (Enter ou botão).
  $$('.add-fato', box).forEach(add => {
    const inp = $('input', add);
    const guardar = async () => {
      const txt = (inp.value || '').trim();
      if (!txt) return;
      const uid = uidDe(add);
      const p = (ESTADO.pessoas || []).find(x => x.id === uid);
      if (!p) return;
      const resp = await tenta('add_fato_pessoa', uid, p.nome, txt);
      if (resp) toast(resp.length > 90 ? 'Guardado na memória' : resp);
      else toast('Não consegui guardar', 'erro');
      inp.value = '';
      const atual = await tenta('listar_pessoas_discord');
      if (atual) ESTADO.pessoas = atual;
      desenharPessoas();
      atualizarContaPessoas();
      // Reabre o cartão que estava aberto (a lista foi redesenhada).
      const novo = $(`.pessoa[data-uid="${CSS.escape(uid)}"] .pessoa-cab`, box);
      if (novo) novo.click();
    };
    $('.btn-linha', add).onclick = guardar;
    inp.onkeydown = e => { if (e.key === 'Enter') guardar(); };
  });

  const ant = $('#px-ant', box), prox = $('#px-prox', box);
  if (ant) ant.onclick = () => { ESTADO.pessoaPag--; desenharPessoas(); };
  if (prox) prox.onclick = () => { ESTADO.pessoaPag++; desenharPessoas(); };
}

function atualizarContaPessoas() {
  const aba = $('[data-mem="pessoas"]');
  if (!aba) return;
  const conta = $('.mem-conta', aba);
  if (conta) conta.textContent = (ESTADO.pessoas || []).length;
}

function medidores(s) {
  const barra = v => {
    const cls = v > 88 ? 'critico' : v > 68 ? 'alto' : '';
    return `<div class="barra-med"><i class="${cls}" style="width:${Math.max(2, Math.min(100, v))}%"></i></div>`;
  };
  const cpu = Math.round(s.cpu || 0), ram = Math.round(s.ram || 0);
  return `<div class="medidores">
    <div class="medidor"><div class="medidor-rot">Processador</div>
      <div class="medidor-val" id="med-cpu">${cpu}%</div>${barra(cpu)}</div>
    <div class="medidor"><div class="medidor-rot">Memória</div>
      <div class="medidor-val" id="med-ram">${ram}%</div>${barra(ram)}</div>
    <div class="medidor"><div class="medidor-rot">Agora</div>
      <div class="medidor-val" id="med-hora">${esc(s.hora || '--:--')}</div>
      <div style="font-size:11.5px;color:var(--txt-3)">${esc(s.data || '')}</div></div>
  </div>`;
}

function capturarTeclaPtt() {
  return new Promise(resolve => {
    const fundo = $('#modal-fundo');
    fundo.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-labelledby="ptt-captura-titulo">
      <h3 id="ptt-captura-titulo">Tecla para falar</h3>
      <p class="ptt-captura-aviso" id="ptt-captura-aviso">Pressione e solte uma tecla ou botão do mouse. A tecla física será salva neste PC.</p>
      <div class="modal-acoes"><button class="btn-linha" id="ptt-captura-cancelar" type="button">Cancelar</button></div>
    </div>`;
    fundo.hidden = false;
    let fechado = false;
    let cancelando = false;
    const requisicao = `ptt-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const fechar = resultado => {
      if (fechado) return;
      fechado = true;
      document.removeEventListener('keydown', aoTeclar, true);
      document.removeEventListener('pointerup', terminarCancelamento, true);
      document.removeEventListener('pointercancel', terminarCancelamento, true);
      fundo.onpointerdown = null;
      fundo.oncontextmenu = null;
      fundo.onauxclick = null;
      fundo.hidden = true;
      fundo.innerHTML = '';
      resolve(resultado);
    };
    const aoTeclar = e => {
      e.preventDefault();
      e.stopImmediatePropagation();
    };
    document.addEventListener('keydown', aoTeclar, true);
    const iniciarCancelamento = () => {
      if (fechado || cancelando) return;
      cancelando = true;
      tenta('ptt_tecla_cancelar', requisicao);
    };
    function terminarCancelamento() {
      if (cancelando) setTimeout(() => fechar({ cancelado: true }), 0);
    }
    const btnCancelar = $('#ptt-captura-cancelar');
    btnCancelar.onpointerdown = iniciarCancelamento;
    btnCancelar.onclick = () => { iniciarCancelamento(); terminarCancelamento(); };
    fundo.onpointerdown = e => { if (e.target === fundo) iniciarCancelamento(); };
    document.addEventListener('pointerup', terminarCancelamento, true);
    document.addEventListener('pointercancel', terminarCancelamento, true);
    fundo.oncontextmenu = e => e.preventDefault();
    fundo.onauxclick = e => e.preventDefault();
    requestAnimationFrame(async () => {
      if (fechado || cancelando) return;
      const resultado = await tenta('ptt_tecla_capturar', requisicao, { __teto: 30000 });
      if (!cancelando) fechar(resultado);
    });
  });
}

function atualizarGatewayEndpoint(dados) {
  if (!dados?.disponivel && !dados?.url) return;
  const status = $('#cfg-gateway-status');
  if (status) {
    const conexao = dados.tunel_online ? 'Conectado e acessível pela internet'
      : dados.servico === 'active' ? 'Túnel ativo; endereço público sem conexão' : 'Desconectado';
    const push = dados.firebase_configurado && dados.celular_registrado ? 'chave e celular registrados'
      : !dados.firebase_configurado ? 'aguardando chave Firebase' : 'aguardando registro do celular';
    status.textContent = dados.modo === "oracle" ? conexao : `${conexao} · ${push}`;
  }
  const aviso = $('#cfg-gateway-aviso');
  if (aviso && dados.mensagem) aviso.textContent = [dados.mensagem, dados.push, dados.windows].filter(Boolean).join(' ');
  const salvar = $('#cfg-gateway-salvar');
  if (salvar) salvar.disabled = false;
  const input = $('#cfg-gateway-url');
  if (input && dados.url && document.activeElement !== input) input.value = dados.url;
}

function ligarConfig() {
  const parear = $('#cfg-gateway-parear');
  if (parear) parear.onclick = async () => {
    parear.disabled = true;
    const resultado = await tenta('gateway_parear_dispositivo');
    const texto = $('#cfg-gateway-pair-code');
    if (texto) texto.textContent = resultado?.ok ? `Código: ${resultado.code} · válido por 10 minutos` : resultado?.mensagem || 'Não foi possível gerar o código';
    parear.disabled = false;
  };

  const gatewaySalvar = $('#cfg-gateway-salvar');
  if (gatewaySalvar) gatewaySalvar.onclick = async () => {
    const input = $('#cfg-gateway-url');
    if (!input?.value.trim()) { toast('Informe o endereço do ngrok.', 'erro'); return; }
    gatewaySalvar.disabled = true;
    const aviso = $('#cfg-gateway-aviso');
    if (aviso) aviso.textContent = 'Conectando ao gateway…';
    const resultado = await tenta('gateway_endpoint_alterar', input.value.trim());
    if (!resultado?.ok) {
      gatewaySalvar.disabled = false;
      if (aviso) aviso.textContent = resultado?.mensagem || 'Não consegui iniciar a troca.';
      toast(resultado?.mensagem || 'Não consegui trocar o endereço.', 'erro');
    }
  };
  const gatewayReiniciar = $('#cfg-gateway-reiniciar');
  if (gatewayReiniciar) gatewayReiniciar.onclick = async () => {
    gatewayReiniciar.disabled = true;
    const resultado = await tenta('gateway_reiniciar');
    gatewayReiniciar.disabled = false;
    toast(resultado?.mensagem || 'Não consegui reiniciar o gateway.', resultado?.ok ? 'ok' : 'erro');
  };
  const botaoPtt = $('#cfg-ptt-tecla');
  if (botaoPtt) botaoPtt.onclick = async () => {
    const resultado = await capturarTeclaPtt();
    if (resultado?.cancelado) return;
    if (!resultado) { toast('Não consegui iniciar a captura de tecla.', 'erro'); return; }
    if (!resultado?.ok) { toast(resultado?.erro || 'Não consegui trocar a tecla', 'erro'); return; }
    const rotulo = $('#cfg-ptt-rotulo');
    if (rotulo) rotulo.textContent = resultado.rotulo;
    toast(`Press to talk: ${resultado.rotulo}`);
  };
  // TV: o botão "Adicionar" da seção. O editar/remover/parear ligam dentro
  // do desenharTv, junto dos cards.
  const tvAdd = $('#cfg-tv-add');
  if (tvAdd) tvAdd.onclick = async () => {
    const campos = await tvModalCampos(null);
    if (!campos) return;
    if (!campos.ip) { tvAvisar('Informe o IP da TV.', 'erro'); return; }
    const r = await tenta('tv_salvar', campos.nome || 'TV da Sala', campos.ip, campos.tipo);
    if (r && r.ok === false) { tvAvisar(r.mensagem || 'Falhou', 'erro'); return; }
    tvAvisar(r?.mensagem || 'TV salva', 'ok');
    const id = r?.dispositivo?.id;
    if (id && campos.parear) { tenta('tv_parear', id); return; }
    redesenharTv();
  };

  // Volume da voz: feedback na hora (o label %), persiste no onchange.
  const vol = $('#cfg-volume');
  if (vol) {
    const rotulo = $('#cfg-volume-valor');
    const pintarVolume = () => {
      if (rotulo) rotulo.textContent = `${vol.value}%`;
      vol.style.setProperty('--pct', `${Number(vol.value) / 1.5}%`);
    };
    pintarVolume();
    vol.oninput = pintarVolume;
    vol.onchange = async () => {
      const ok = await tenta('definir_volume_voz', Number(vol.value) / 100);
      if (!ok) { toast('Não consegui mudar o volume', 'erro'); return; }
      toast(`Volume da voz: ${vol.value}%`);
    };
  }

  // Modelo do Discord: botão com popover no mesmo estilo dos seletores do
  // composer (um <select> nativo aparecia com a barra BRANCA do tema GTK —
  // contrastava com a interface toda escura). Vazio = padrão da rota.
  const _rotDiscord = () => {
    const rot = $('#cfg-discord-modelo-rot');
    if (!rot) return;
    const dm = ESTADO.discordMod || {};
    const atual = dm.atual || '';
    const m = (dm.modelos || []).find(x => x.id === atual);
    rot.textContent = atual ? (m ? m.nome : atual) : 'Padrão (afinação da rota)';
  };
  ESTADO.discordMod = ESTADO.discordMod || {};
  _rotDiscord();
  const selD = $('#cfg-discord-modelo');
  if (selD) selD.onclick = () => {
    const dm = ESTADO.discordMod || {};
    abrirPop(selD, [
      { icone: ICO.cerebro, rotulo: 'Padrão (afinação da rota)',
        selecionavel: true, ativo: !dm.atual,
        acao: async () => {
          const ok = await tenta('discord_definir_modelo', '');
          if (!ok) { toast('Não consegui trocar o modelo', 'erro'); return; }
          ESTADO.discordMod = { ...dm, atual: '' };
          _rotDiscord();
          toast('Discord voltou ao modelo padrão');
        } },
      ...(dm.modelos || []).map(m => ({
        icone: ICO.cerebro, rotulo: m.nome || m.id, sub: m.id !== m.nome ? m.id : '',
        selecionavel: true, ativo: m.id === dm.atual,
        acao: async () => {
          const ok = await tenta('discord_definir_modelo', m.id);
          if (!ok) { toast('Não consegui trocar o modelo', 'erro'); return; }
          ESTADO.discordMod = { ...dm, atual: m.id };
          _rotDiscord();
          toast(`Discord: ${m.nome || m.id}`);
        } })),
    ]);
  };

  $$('.chave').forEach(ch => ch.onclick = async () => {
    const ligado = ch.getAttribute('aria-checked') !== 'true';
    ch.setAttribute('aria-checked', String(ligado));   // otimista: o toggle responde na hora
    const ok = await tenta('set_toggle', ch.dataset.chave, ligado);
    // Reverte se o backend recusou (retorno false) OU se a chamada caiu (null).
    // Antes só revertia em null, então uma falha silenciosa (false) deixava o
    // toggle mentindo que estava ligado.
    if (!ok) {
      ch.setAttribute('aria-checked', String(!ligado));
      toast('Não consegui mudar isso agora', 'erro');
    }
  });
  const petTamanho = $('#cfg-pet-tamanho');
  if (petTamanho) {
    const valor = $('#cfg-pet-tamanho-valor');
    petTamanho.oninput = () => { if (valor) valor.textContent = `${petTamanho.value}%`; };
    petTamanho.onchange = async () => {
      const ok = await tenta('pet_tamanho_definir', Number(petTamanho.value));
      if (!ok) toast('Não consegui salvar o tamanho da Emily', 'erro');
    };
  }
  // Os fatos da memória têm ligação própria (ligarFatos), porque são
  // paginados e redesenhados sem refazer a tela inteira.
}

/* ════════════════════════════════════════════════════════════════
   POPOVER — menu flutuante ancorado (menu do +, seletor de modelo/raciocínio)
   Abre acima da âncora (o composer vive no rodapé), fecha no clique fora ou Esc.
   ════════════════════════════════════════════════════════════════ */

let _popAberto = null;

function fecharPop() {
  if (_popAberto) { _popAberto.remove(); _popAberto = null; }
  document.removeEventListener('click', _popForaClick, true);
  document.removeEventListener('keydown', _popEsc, true);
}
function _popForaClick(e) {
  if (_popAberto && !_popAberto.contains(e.target) && !_popAberto._ancora.contains(e.target))
    fecharPop();
}
function _popEsc(e) { if (e.key === 'Escape') fecharPop(); }

function abrirPop(ancora, itens, opcoes = {}) {
  const jaAberto = _popAberto && _popAberto._ancora === ancora;
  fecharPop();
  if (jaAberto) return;   // segundo clique na mesma âncora fecha

  const pop = document.createElement('div');
  pop.className = 'popover' + (opcoes.classe ? ' ' + opcoes.classe : '');
  pop._ancora = ancora;
  if (opcoes.titulo) {
    const cabecalho = document.createElement('div');
    cabecalho.className = 'popover-cabecalho';
    const titulo = document.createElement('strong');
    titulo.textContent = opcoes.titulo;
    cabecalho.appendChild(titulo);
    if (opcoes.descricao) {
      const descricao = document.createElement('small');
      descricao.textContent = opcoes.descricao;
      cabecalho.appendChild(descricao);
    }
    pop.appendChild(cabecalho);
  }
  itens.forEach(it => {
    const b = document.createElement('button');
    b.className = 'popover-item'
      + (it.ativo ? ' ativo' : '')
      + (it.desabilitado ? ' desabilitado' : '')
      + (it.classe ? ' ' + it.classe : '');
    b.disabled = !!it.desabilitado;
    if (it.selecionavel) b.setAttribute('aria-pressed', it.ativo ? 'true' : 'false');
    if (it.desabilitado) {
      b.setAttribute('aria-disabled', 'true');
      b.title = it.motivo || 'Ação indisponível';
    }
    b.innerHTML =
      (it.icone ? svg(it.icone, 'pi-ico') : '') +
      `<span class="pi-txt"><strong>${esc(it.rotulo)}</strong>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}${it.intensidade ? `<span class="pi-intensidade" aria-hidden="true">${Array.from({length: 6}, (_, i) => `<i${i < it.intensidade ? ' class="aceso"' : ''}></i>`).join('')}</span>` : ''}</span>` +
      (it.selecionavel ? svg(ICO.check, 'pi-check') : '');
    b.onclick = (e) => {
      e.stopPropagation();
      if (it.desabilitado) return;
      fecharPop();
      it.acao && it.acao();
    };
    pop.appendChild(b);
  });
  document.body.appendChild(pop);

  const r = ancora.getBoundingClientRect();
  const pr = pop.getBoundingClientRect();
  let left = Math.max(8, Math.min(r.left, window.innerWidth - pr.width - 8));
  let top = r.top - pr.height - 8;
  if (top < 8 && window.innerHeight - r.bottom >= r.top)
    top = r.bottom + 8;
  // Em janelas baixas, mantém o menu inteiro dentro da área visível.
  top = Math.max(8, Math.min(top, window.innerHeight - pr.height - 8));
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  _popAberto = pop;
  setTimeout(() => {
    document.addEventListener('click', _popForaClick, true);
    document.addEventListener('keydown', _popEsc, true);
  }, 0);
  return pop;
}

/* ── Seletores de modelo e raciocínio do composer ─────────────── */

let _provedorAtual = '', _modeloAtual = '', _racioAtual = '',
    _provedoresDisp = [], _modelosDisp = [], _niveisDisp = [];

async function carregarSeletores() {
  const est = await tenta('estado_modelo');
  if (!est) return;
  _provedoresDisp = est.provedores || [];
  _modelosDisp = est.modelos || [];
  _niveisDisp = est.niveis || [];
  _provedorAtual = est.provedor
    || (_provedoresDisp[0] && _provedoresDisp[0].id)
    || '';
  _modeloAtual = est.modelo
    || (_modelosDisp[0] && _modelosDisp[0].id)
    || '';
  _racioAtual = est.raciocinio || 'baixo';
  pintarSeletores();
}
function pintarSeletores() {
  const p = _provedoresDisp.find(x => x.id === _provedorAtual);
  const m = _modelosDisp.find(x => x.id === _modeloAtual);
  const n = _niveisDisp.find(x => x.id === _racioAtual);
  const em = $('#sel-modelo-nome');
  if (em) {
    // Mostra "Provedor · Modelo" só se houver mais de um provedor (caso
    // contrário é ruído). Em modo legado (sem provedoresDisp), só o modelo.
    if (p && _provedoresDisp.length > 1) em.textContent = `${p.nome} · ${m ? m.nome : _modeloAtual}`;
    else em.textContent = m ? m.nome : (_modeloAtual || 'Modelo');
  }
  const en = $('#sel-racio-nome'); if (en) en.textContent = n ? n.nome : 'Raciocínio';
  const ei = $('#sel-racio-icone');
  if (ei) ei.innerHTML = svg(ICONES_RACIOCINIO[_racioAtual] || ICO.cerebro);
}
function menuModelo() {
  // Sem lista de provedores (modo legado), popover de uma página só.
  if (!_provedoresDisp || _provedoresDisp.length <= 1) {
    abrirPop($('#sel-modelo'), _modelosDisp.map(m => ({
      icone: ICO.cerebro, rotulo: m.nome, sub: m.sobre, selecionavel: true,
      ativo: m.id === _modeloAtual,
      acao: async () => {
        const ok = await tenta('definir_modelo', m.id);
        if (ok) { await carregarSeletores(); toast(`Modelo: ${m.nome}`); }
        else toast('Não consegui trocar o modelo', 'erro');
      },
    })));
    return;
  }
  menuProvedores();
}
function menuProvedores() {
  // Lista os provedores. Cada um age como "abrir lista de modelos desse".
  abrirPop($('#sel-modelo'), _provedoresDisp.map(p => ({
    icone: ICO.cerebro, rotulo: p.nome,
    sub: (p.modelos && p.modelos.length)
      ? `${p.modelos.length} modelo(s)`
      : 'sem modelos',
    ativo: p.id === _provedorAtual,
    acao: () => menuModelosProvedor(p),
  })));
}
function menuModelosProvedor(provedor) {
  // Modelos do provedor, com cabeçalho "← Provedor" pra voltar.
  // O cabeçalho é renderizado como um item extra, sem o check e sem ser
  // "selecionável" — é só um botão que reabre o nível de cima.
  abrirPop($('#sel-modelo'), [
    { rotulo: `← ${provedor.nome}`,
      classe: 'cabecalho',
      acao: () => menuProvedores(),
    },
    ...provedor.modelos.map(m => ({
      icone: ICO.cerebro, rotulo: m.nome, sub: m.sobre, selecionavel: true,
      ativo: m.id === _modeloAtual && provedor.id === _provedorAtual,
      acao: async () => {
        const ok = await tenta('definir_provedor_e_modelo', provedor.id, m.id);
        if (ok) {
          // O modelo novo pode ter outros níveis de raciocínio. Também lê de
          // volta o nível efetivo caso o anterior não exista nesse modelo.
          await carregarSeletores();
          toast(`Modelo: ${provedor.nome} · ${m.nome}`);
        } else toast('Não consegui trocar o provedor/modelo', 'erro');
      },
    })),
  ]);
}
function menuRaciocinio() {
  abrirPop($('#sel-racio'), _niveisDisp.map(n => ({
    icone: ICONES_RACIOCINIO[n.id] || ICO.cerebro,
    rotulo: n.nome, sub: DETALHES_RACIOCINIO[n.id] || '',
    intensidade: {desligado: 0, baixo: 1, medio: 2, alto: 3, extra_alto: 4, maximo: 6}[n.id] || 0,
    classe: 'raciocinio-opcao', selecionavel: true,
    ativo: n.id === _racioAtual,
    acao: async () => {
      const ok = await tenta('definir_raciocinio', n.id);
      if (ok) { _racioAtual = n.id; pintarSeletores(); toast(`Raciocínio: ${n.nome}`); }
      else toast('Não consegui mudar o raciocínio', 'erro');
    },
  })), {
    classe: 'popover-raciocinio',
    titulo: 'Raciocínio',
    descricao: 'Escolha a profundidade para este modelo',
  });
}
function menuAdd() {
  const prefill = txt => { const t = $('#entrada'); if (!t) return; t.value = txt; ajustarEntrada(); t.focus(); };
  const mandar  = txt => { const t = $('#entrada'); if (!t) return; t.value = txt; ajustarEntrada(); enviar(); };
  abrirPop($('#btn-add'), [
    { icone: ICO.clipe, rotulo: 'Anexar arquivo', sub: 'Imagem ou documento do PC', acao: async () => {
        const arqs = await tenta('escolher_arquivos') || [];
        adicionarAnexos(arqs);
    }},
    { icone: ICO.disco, rotulo: 'Analisar o disco', sub: 'Ver o que tá enchendo o espaço', acao: () => mandar('analisa meu disco C e me diz o que tá ocupando espaço') },
    { icone: ICO.pasta, rotulo: 'Organizar downloads', sub: 'Separa a pasta por tipo, agora', acao: async () => {
        toast('Organizando os downloads…'); const r = await tenta('organizar_downloads'); if (r) toast(String(r).slice(0, 70));
    }},
    { icone: ICO.lupa, rotulo: 'Buscar no PC', sub: 'Achar uma pasta ou arquivo', acao: () => prefill('procura no meu PC ') },
    { icone: ICO.musica, rotulo: 'Tocar música', sub: 'No player padrão', acao: () => prefill('toca ') },
    { icone: ICO.globo, rotulo: 'Pesquisar na web', sub: 'Buscar na internet', acao: () => prefill('pesquisa na internet sobre ') },
  ]);
}

/* ════════════════════════════════════════════════════════════════
   MENU GITHUB — popover com repositórios do Vitor
   ════════════════════════════════════════════════════════════════ */

async function menuGithub() {
  const prefill = txt => { const t = $('#entrada'); if (!t) return; t.value = txt; ajustarEntrada(); t.focus(); };
  const mandar  = txt => { const t = $('#entrada'); if (!t) return; t.value = txt; ajustarEntrada(); enviar(); };

  // Tenta carregar os repositórios reais; se falhar, pede pra configurar.
  const repos = await tenta('listar_repos_github') || [];
  const itens = [];

  if (!repos.length) {
    itens.push(
      { icone: ICO_GITHUB, rotulo: 'GitHub não configurado', sub: 'Adicione GITHUB_TOKEN no .env', acao: () => {} },
      { icone: ICO.lupa, rotulo: 'Ver repositórios de outro', sub: 'Buscar usuário no GitHub', acao: () => prefill('mostra os repos do ') },
    );
  } else {
    // Mostra até 10 repos mais recentes
    repos.slice(0, 10).forEach(r => {
      const nome = r.titulo || r.id || '?';
      const desc = r.sub || '';
      itens.push({
        icone: ICO_GITHUB,
        rotulo: nome,
        sub: desc || 'Repositório no GitHub',
        acao: () => mandar(`analisa o repositório ${nome} no GitHub pra mim`),
      });
    });
    itens.push({
      icone: ICO.lupa,
      rotulo: 'Ver todos os repos',
      sub: 'Lista completa no popup',
      acao: () => mandar('lista meus repositórios do GitHub'),
    });
  }

  abrirPop($('#btn-github'), itens);
}

/* ════════════════════════════════════════════════════════════════
   LIGAÇÕES GERAIS
   ════════════════════════════════════════════════════════════════ */

function ligarTudo() {
  // Mover, redimensionar, minimizar/maximizar/fechar são da moldura NATIVA
  // do Windows agora — não há mais botões de janela pra ligar aqui.
  $('#btn-inicio').onclick = () => irPara('inicio', { forcar: true });
  $('#btn-sidebar').onclick = () => {
    if (ESTADO.tela !== 'config') document.body.classList.toggle('sem-lateral');
  };
  ligarResizeLateral();
  $('#btn-novo').onclick   = novaConversa;
  $('#btn-code').onclick   = () => irPara('code', { forcar: true });
  $('#btn-cloud').onclick  = () => irPara('cloud', { forcar: true });
  ligarPainelNavegador();
  $('#btn-config').onclick = () => irPara(ESTADO.tela === 'config' ? 'inicio' : 'config');
  $('#btn-demo').onclick = alternarModoDemo;
  $('#demo-faixa-sair').onclick = alternarModoDemo;
  ligarAgenteUI();

  const busca = $('#busca');
  busca.oninput = () => {
    ESTADO.filtro = busca.value.trim();
    $('#busca-limpar').hidden = !ESTADO.filtro;
    desenharConversas();
  };
  $('#busca-limpar').onclick = () => {
    busca.value = ''; ESTADO.filtro = '';
    $('#busca-limpar').hidden = true; desenharConversas(); busca.focus();
  };

  const t = $('#entrada');
  t.oninput = ajustarEntrada;
  t.onkeydown = e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); }
  };
  $('#btn-enviar').onclick = enviar;

  // Modo remoto: alterna se os comandos do chat executam no celular.
  const btnRemoto = $('#btn-remoto');
  const pintarRemoto = () => btnRemoto.classList.toggle('ativo', ESTADO.remoto);
  pintarRemoto();
  btnRemoto.onclick = () => {
    if (ESTADO.demo) { toast('Modo remoto bloqueado durante a demo', 'erro'); return; }
    ESTADO.remoto = !ESTADO.remoto;
    try { localStorage.setItem('emily_remoto', ESTADO.remoto ? '1' : '0'); } catch (_) { /* sem localStorage, tudo bem */ }
    pintarRemoto();
    const e = $('#entrada');
    if (e) e.placeholder = ESTADO.remoto
      ? 'Falando com a Emily do celular...'
      : 'Fala com a Emily...';
  };
  const btnVozTexto = $('#btn-voz-texto');
  const pintarVozTexto = () => {
    btnVozTexto.classList.toggle('ativo', ESTADO.vozTexto);
    btnVozTexto.setAttribute('aria-pressed', String(ESTADO.vozTexto));
    btnVozTexto.title = ESTADO.vozTexto
      ? 'Narração das respostas digitadas ligada' : 'Narrar respostas das mensagens digitadas';
  };
  pintarVozTexto();
  btnVozTexto.onclick = async () => {
    const novo = !ESTADO.vozTexto;
    const salvo = await tenta('voz_texto_definir', novo);
    if (salvo === null) return toast('Não consegui mudar a narração.', 'erro');
    ESTADO.vozTexto = Boolean(salvo);
    pintarVozTexto();
    toast(ESTADO.vozTexto ? 'Emily vai narrar as respostas.' : 'Narração desligada.');
  };
  $('#btn-mic').onclick    = () => ESTADO.demo ? toast('Microfone bloqueado durante a demo', 'erro') : tenta('ptt');
  $('#btn-tela').onclick   = e => {
    e.stopPropagation();
    const painel = $('#agente-ui-painel');
    definirPainelAgenteUI(Boolean(painel?.hidden));
  };
  $('#btn-github').onclick = (e) => { e.stopPropagation(); ESTADO.demo ? toast('GitHub bloqueado durante a demo', 'erro') : menuGithub(); };
  $('#btn-add').onclick    = (e) => { e.stopPropagation(); ESTADO.demo ? toast('Atalhos e anexos reais bloqueados durante a demo', 'erro') : menuAdd(); };
  $('#sel-modelo').onclick = (e) => { e.stopPropagation(); menuModelo(); };
  $('#sel-racio').onclick  = (e) => { e.stopPropagation(); menuRaciocinio(); };
  const perf = $('#perfil');
  if (perf) perf.onclick = () => irPara(ESTADO.tela === 'perfil' ? (ESTADO.atual ? 'chat' : 'inicio') : 'perfil');
}

/* ── Redimensionar a barra lateral ────────────────────────────────
   Arrastar a alça muda --lateral-w; o chat reflui sozinho (coluna de leitura
   centrada com largura máxima). Abaixo de um mínimo, recolhe inteira. A
   largura fica salva no localStorage e volta na próxima abertura. */

const LAT_MIN = 190, LAT_MAX = 460, LAT_COLAPSA = 150;

function aplicarLarguraLateral(px) {
  document.documentElement.style.setProperty('--lateral-w', px + 'px');
}

function ligarResizeLateral() {
  // Restaura a largura salva.
  try {
    const salvo = localStorage.getItem('emily_lateral');
    if (salvo === 'colapsada') document.body.classList.add('sem-lateral');
    else if (salvo) aplicarLarguraLateral(Math.min(LAT_MAX, Math.max(LAT_MIN, parseInt(salvo, 10))));
  } catch (_) { /* localStorage pode faltar; segue no default */ }

  const alca = $('#lateral-resize');
  if (!alca) return;

  const arrastar = e => {
    e.preventDefault();
    document.body.classList.add('redimensionando');
    // Se estava recolhida, arrastar a traz de volta.
    document.body.classList.remove('sem-lateral');

    const mover = ev => {
      const x = (ev.touches ? ev.touches[0].clientX : ev.clientX);
      if (x < LAT_COLAPSA) {                 // puxou pra bem perto da borda: recolhe
        document.body.classList.add('sem-lateral');
        return;
      }
      document.body.classList.remove('sem-lateral');
      aplicarLarguraLateral(Math.min(LAT_MAX, Math.max(LAT_MIN, x)));
    };
    const soltar = () => {
      document.body.classList.remove('redimensionando');
      window.removeEventListener('mousemove', mover);
      window.removeEventListener('mouseup', soltar);
      window.removeEventListener('touchmove', mover);
      window.removeEventListener('touchend', soltar);
      try {
        if (document.body.classList.contains('sem-lateral'))
          localStorage.setItem('emily_lateral', 'colapsada');
        else
          localStorage.setItem('emily_lateral',
            String(parseInt(getComputedStyle(document.documentElement).getPropertyValue('--lateral-w'), 10)));
      } catch (_) { /* sem localStorage, tudo bem */ }
    };
    window.addEventListener('mousemove', mover);
    window.addEventListener('mouseup', soltar);
    window.addEventListener('touchmove', mover, { passive: false });
    window.addEventListener('touchend', soltar);
  };

  alca.addEventListener('mousedown', arrastar);
  alca.addEventListener('touchstart', arrastar, { passive: false });
  // Duplo-clique na alça: recolhe/reabre.
  alca.addEventListener('dblclick', () => {
    document.body.classList.toggle('sem-lateral');
    try {
      localStorage.setItem('emily_lateral',
        document.body.classList.contains('sem-lateral') ? 'colapsada'
          : String(parseInt(getComputedStyle(document.documentElement).getPropertyValue('--lateral-w'), 10)));
    } catch (_) {}
  });
}

/* Copiar bloco de código: delegação, porque os blocos nascem depois. */
document.addEventListener('click', async e => {
  const b = e.target.closest('.btn-copiar-cod');
  if (!b) return;
  await tenta('copiar', decodeURIComponent(b.dataset.cod));
  const antes = b.innerHTML;
  b.innerHTML = svg(ICO.check) + 'copiado';
  setTimeout(() => { b.innerHTML = antes; }, 1500);
});

/* Clipboard: texto puro fica 100% a cargo do navegador — assim Ctrl+V dentro
   do textarea nunca é sequestrado. Só impedimos o comportamento nativo quando
   há arquivos reais, imagens ou uma lista explícita de URIs de arquivo. */
document.addEventListener('paste', async e => {
  if (ESTADO.demo || _naTelaCode || !['inicio', 'chat'].includes(ESTADO.tela)) return;
  const itens = [...(e.clipboardData?.items || [])];
  const arquivosLista = [...(e.clipboardData?.files || [])];
  const arquivosItens = itens.filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
  const arquivos = arquivosLista.length ? arquivosLista : arquivosItens;
  const tipos = [...(e.clipboardData?.types || [])];
  const htmlClipboard = tipos.some(t => String(t).toLowerCase() === 'text/html')
    ? (e.clipboardData?.getData('text/html') || '') : '';
  const htmlTemImagem = /<img\b/i.test(htmlClipboard);
  const anunciaImagem = tipos.some(t => String(t).toLowerCase().startsWith('image/'))
    || itens.some(i => String(i.type || '').toLowerCase().startsWith('image/'))
    || htmlTemImagem;
  if (arquivos.length) {
    e.preventDefault();
    if (await anexarArquivosWeb(arquivos, 'do clipboard', anunciaImagem)) return;
    // Há WebViews que expõem um File fantasma (nome, mas bytes inacessíveis).
    // Tenta a compatibilidade por caminho/nome antes de desistir.
    const resolvidosPorNome = await tenta(
      'resolver_arrastados', arquivos.map(a => a.name).filter(Boolean), { __teto: 15000 }) || [];
    if (adicionarAnexos(resolvidosPorNome)) return;
    if (anunciaImagem && await anexarImagensClipboardApi()) return;
    if (htmlTemImagem && await anexarImagensDoHtmlClipboard(htmlClipboard)) return;
    if (anunciaImagem && await anexarImagemClipboardNativo()) return;
    if (anunciaImagem) {
      toast('Não consegui ler a imagem do clipboard', 'erro');
      return;
    }
  } else if (anunciaImagem) {
    // GTK/WebKit2 no KDE Wayland pode anunciar image/png, mas devolver null em
    // getAsFile(). WhatsApp/WebView2 também pode anunciar só text/html com <img>.
    // Primeiro tenta as APIs web enquanto o gesto de Ctrl+V ainda está ativo;
    // depois cai no clipboard nativo do Windows/Linux.
    e.preventDefault();
    if (await anexarImagensClipboardApi()) return;
    if (htmlTemImagem && await anexarImagensDoHtmlClipboard(htmlClipboard)) return;
    if (await anexarImagemClipboardNativo()) return;
    toast('Não consegui ler a imagem do clipboard', 'erro');
    return;
  }

  if (!arquivos.length && !itens.length && !tipos.length) {
    // Algumas versões do WebKitGTK esvaziam todo o DataTransfer da imagem.
    // Consulta o compositor sem preventDefault: se o WebKit ainda souber fazer
    // alguma colagem nativa residual, ela não será bloqueada por este fallback.
    if (await anexarImagemClipboardNativo()) return;
  }

  const tipoUris = tipos.find(t => t === 'text/uri-list' || t === 'x-special/gnome-copied-files');
  if (!tipoUris) {
    const texto = e.clipboardData?.getData('text/plain') || '';
    const linhas = texto.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    const parecemCaminhos = linhas.length > 0 && linhas.every(x =>
      /^file:/i.test(x) || /^[A-Za-z]:[\\/]/.test(x) || /^\\\\[^\\]+\\/.test(x) || /^\//.test(x));
    if (parecemCaminhos) {
      e.preventDefault();
      const resolvidos = await tenta('resolver_arrastados', linhas, { __teto: 15000 }) || [];
      if (adicionarAnexos(resolvidos)) return;
      // Se o caminho parecia arquivo mas não existe mais, não engole o texto:
      // ele cai no composer como qualquer outra colagem.
    }
    // Dentro de um campo editável, o navegador sabe preservar seleção/cursor e
    // faz a colagem nativa. Fora dele, direciona o texto ao composer para Ctrl+V
    // funcionar em qualquer ponto do chat.
    const alvoEditavel = /^(INPUT|TEXTAREA)$/.test(e.target?.tagName) || e.target?.isContentEditable;
    if ((!alvoEditavel || parecemCaminhos) && texto) {
      const entrada = $('#entrada');
      if (!entrada) return;
      e.preventDefault();
      const colarNoCampoAtual = e.target === entrada;
      const inicio = colarNoCampoAtual ? (entrada.selectionStart ?? entrada.value.length) : entrada.value.length;
      const fim = colarNoCampoAtual ? (entrada.selectionEnd ?? inicio) : inicio;
      entrada.setRangeText(texto, inicio, fim, 'end');
      entrada.focus();
      ajustarEntrada();
    }
    return;
  }
  const bruto = e.clipboardData.getData(tipoUris) || '';
  const caminhos = bruto.split(/\r?\n/).map(x => x.trim())
    .filter(x => x && x !== 'copy' && x !== 'cut' && !x.startsWith('#'));
  if (!caminhos.length) return;
  e.preventDefault();
  const resolvidos = await tenta('resolver_arrastados', caminhos) || [];
  if (!adicionarAnexos(resolvidos)) toast('Não consegui localizar os arquivos copiados', 'erro');
});

/* Arrastar arquivos: usa os bytes do File em vez de tentar adivinhar o caminho
   pelo nome. Funciona vindo de qualquer pasta e também em Linux/WebKit. */
document.addEventListener('dragover', e => {
  if (ESTADO.demo || _naTelaCode || ESTADO.tela === 'cloud') return;
  if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
  e.preventDefault();
  document.body.classList.add('anexo-arrastando');
});
document.addEventListener('dragleave', e => {
  if (!e.relatedTarget) document.body.classList.remove('anexo-arrastando');
});
document.addEventListener('drop', async e => {
  document.body.classList.remove('anexo-arrastando');
  if (ESTADO.demo || _naTelaCode || ESTADO.tela === 'cloud') return;
  const arquivos = [...(e.dataTransfer?.files || [])];
  if (!arquivos.length) return;
  e.preventDefault();
  await anexarArquivosWeb(arquivos, 'arrastado');
});

/* Atalhos. Nenhum deles existia na interface antiga. */
document.addEventListener('keydown', e => {
  if (!$('#modal-player')?.hidden) return;
  const digitando = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName)
    || document.activeElement?.isContentEditable;

  if (e.ctrlKey && e.key.toLowerCase() === 'n') { e.preventDefault(); novaConversa(); return; }
  if (e.ctrlKey && e.key.toLowerCase() === 'h' && e.shiftKey) { e.preventDefault(); irPara('inicio', { forcar: true }); return; }
  if (e.ctrlKey && e.key.toLowerCase() === 'b') {
    e.preventDefault();
    if (ESTADO.tela !== 'config') $('#btn-sidebar').click();
    return;
  }
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'k') { e.preventDefault(); irPara('code', { forcar: true }); return; }
  if (e.ctrlKey && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    $(ESTADO.tela === 'config' ? '#cfg-busca' : '#busca')?.focus();
    return;
  }
  if (e.ctrlKey && e.key === ',') { e.preventDefault(); irPara('config'); return; }
  if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'd') { e.preventDefault(); irPara('cloud', { forcar: true }); return; }
  if (e.ctrlKey && e.altKey && e.code === 'Space') { e.preventDefault(); Player.playPause(); return; }
  if (e.ctrlKey && e.altKey && e.key === 'ArrowRight') { e.preventDefault(); Player.proxima({ manual: true }); return; }
  if (e.ctrlKey && e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); Player.anterior(true); return; }
  if (e.key === 'Escape' && !digitando) {
    if (ESTADO.tela === 'config') irPara(ESTADO.atual ? 'chat' : 'inicio');
    return;
  }
  // Digitar em qualquer lugar cai na caixa de texto.
  // No Emily Code NÃO: o foco é do terminal (#code-campo); puxar pra #entrada
  // (chat normal) roubaria a digitação quando o foco do terminal se perde.
  if (!digitando && !e.ctrlKey && !e.altKey && e.key.length === 1 &&
      !_naTelaCode && !['cloud', 'config', 'perfil'].includes(ESTADO.tela)) {
    const t = $('#entrada');
    if (t) { t.focus(); }
  }
});

/* ════════════════════════════════════════════════════════════════
   PARTIDA
   ════════════════════════════════════════════════════════════════ */

/* ════════════════════════════════════════════════════════════════
   COMANDOS DO PLAYER VINDOS DAS FERRAMENTAS (player_*)
   O Python manda 'player_comando' via _push; aqui a ação vira chamada
   ao objeto Player, que é quem realmente controla o áudio no iframe.
   ════════════════════════════════════════════════════════════════ */

async function playerComando(acao, dados) {
  try {
    switch (acao) {
      case 'tocar': {
        // A música já foi adicionada à playlist pelo Python (music_player).
        // Recarrega a playlist local e toca a mais nova.
        await Player.carregarPlaylist();
        const alvo = dados.video_id
          ? Player.playlist.findIndex(m => m.video_id === dados.video_id)
          : -1;
        Player.tocar(alvo >= 0 ? alvo : Player.playlist.length - 1);
        break;
      }
      case 'play_pause': Player.playPause(); break;
      case 'pausar':     Player.pausar(); break;
      case 'proxima':    Player.proxima({ manual: true }); break;
      case 'anterior':   Player.anterior(true); break;
      case 'volume':     Player.definirVolume(Number(dados.valor)); break;
      case 'loop':       Player.alternarLoop(); break;
      case 'aleatorio':  Player.alternarShuffle(); break;
      default: console.warn('[emily] player_comando desconhecido:', acao);
    }
  } catch (e) {
    console.error('[emily] playerComando falhou:', e);
  }
}

async function iniciar() {
  ligarTudo();
  ESTADO.vozTexto = Boolean(await tenta('voz_texto_estado'));
  const btnVozTexto = $('#btn-voz-texto');
  btnVozTexto?.classList.toggle('ativo', ESTADO.vozTexto);
  btnVozTexto?.setAttribute('aria-pressed', String(ESTADO.vozTexto));
  if (btnVozTexto) btnVozTexto.title = ESTADO.vozTexto
    ? 'Narração das respostas digitadas ligada' : 'Narrar respostas das mensagens digitadas';
  const demo = await tenta('estado_demo') || { ativo: false };
  aplicarModoDemo(demo);
  aplicarEstadoAgenteUI(await tenta('agente_ui_estado') || {});
  irPara('inicio', { forcar: true });
  document.body.classList.remove('carregando');

  const perfil = await tenta('perfil') || {};
  $('#perfil-nome').textContent = perfil.nome || 'Vitor';
  // O retrato da Emily vai pro chat e pro hero; a foto do usuário fica só
  // no canto da sidebar (perfil-av). Uma não contamina a outra.
  if (perfil.avatar) {
    _avatarEmily = perfil.avatar;
    const h = $('#hero-img'); if (h) h.src = perfil.avatar;
  }
  if (perfil.avatar_usuario) {
    $('#perfil-av').innerHTML = `<img src="${perfil.avatar_usuario}" alt="">`;
  } else {
    $('#perfil-av').textContent = (perfil.nome || 'V')[0].toUpperCase();
  }

  await recarregarConversas();
  carregarSeletores();
  // Restaura volume/loop/shuffle e a música pausada do boot anterior.
  Player.restaurar();
  $('#entrada')?.focus();

  // Relógio e medidores da tela de configurações, só quando ela está aberta.
  setInterval(async () => {
    if (ESTADO.tela !== 'config') return;
    const s = await tenta('sistema');
    if (!s) return;
    const cpu = $('#med-cpu'), ram = $('#med-ram'), hora = $('#med-hora');
    if (cpu) cpu.textContent = Math.round(s.cpu || 0) + '%';
    if (ram) ram.textContent = Math.round(s.ram || 0) + '%';
    if (hora) hora.textContent = s.hora || '--:--';
    const barras = $$('.barra-med i');
    if (barras[0]) barras[0].style.width = Math.max(2, s.cpu || 0) + '%';
    if (barras[1]) barras[1].style.width = Math.max(2, s.ram || 0) + '%';
  }, 3000);

  // Push é o caminho normal. Esta leitura leve recupera estado depois de reload,
  // suspensão da WebView ou algum evento perdido sem criar tráfego durante passos.
  setInterval(async () => {
    if (document.hidden) return;
    const estado = await tenta('agente_ui_estado');
    if (estado) aplicarEstadoAgenteUI(estado);
  }, 2500);

  // Só depois da janela montada e do perfil/conversas carregados.
  checarAtualizacaoAoAbrir();
}

if (document.readyState !== 'loading') iniciar();
else document.addEventListener('DOMContentLoaded', iniciar);











/* ════════════════════════════════════════════════════════════════
   MUSIC PLAYER
   Áudio via iframe embedado do YouTube (API IFrame oficial). O Python
   só fornece playlist e busca; o estado de reprodução vive aqui.
   ════════════════════════════════════════════════════════════════ */

const Player = {
  playlist: [],
  indice: -1,
  tocando: false,
  // loop: 0 = desligado · 1 = repete a playlist · 2 = repete a música atual
  loop: 1,
  shuffle: false,
  player: null,       // objeto YT.Player
  pronto: false,
  _historico: [],
  // Fila do shuffle: ordem embaralhada que se percorre até o fim antes de
  // reembaralhar. Garante que não repita música até passar a playlist toda.
  _filaShuffle: [],
  _posShuffle: -1,
  _timer: null,       // intervalo que atualiza seek/tempo
  _duracao: 0,
  _buscando: false,   // true enquanto o usuário arrasta o seek (não atualiza)
  _playlistAtivaSalva: 'default',
  _faixaAtual: null,
  _filaFavoritas: false,
  _videoEsperado: null,
  _minimizada: false,
  _mutado: false,
  _falhasTentadas: new Set(),
  _faixaConfirmada: false,
  _ignorarEventos: false,
  _trocaEm: 0,

  async carregarPlaylist() {
    const videoAtual = this._faixaAtual?.video_id || this._videoEsperado;
    this._filaFavoritas = false;
    const geral = await carregarGeral();
    this._playlistAtivaSalva = geral.ativa || 'default';
    this.playlist = (geral.playlists[this._playlistAtivaSalva]?.musicas) || [];
    this.indice = videoAtual
      ? this.playlist.findIndex(m => m.video_id === videoAtual)
      : Math.min(this.indice, this.playlist.length - 1);
    if (videoAtual && this.indice < 0) this._historico = [];
    if (!this.playlist.length) this.indice = -1;
    if (this.shuffle) this._embaralhar();
  },

  // Restaura volume, loop, shuffle e a música/posição salvas do boot anterior.
  async restaurar() {
    const est = await tenta('player_estado');
    await window.EmilyMusic?.pollOffline();
    if (!est) return;
    if (typeof est.volume === 'number') {
      const s = $('#player-vol');
      if (s) s.value = est.volume;
      this.definirVolume(est.volume, { persistir: false });
    }
    if (typeof est.loop === 'number') this.loop = est.loop;
    if (typeof est.shuffle === 'boolean') this.shuffle = est.shuffle;
    if (est.playlist) this._playlistAtivaSalva = est.playlist;
    this._pintaControles();

    // Se tinha uma música tocando antes, carrega o player pausado nela, no
    // exato segundo salvo (o onReady do _criarPlayer trata o _resumoRestaurado).
    if (est.video_id && est.posicao >= 0) {
      const g = await carregarGeral();
      if (g && g.playlists) {
        const alvo = (g.playlists[est.playlist] || g.playlists['default'] || {}).musicas || [];
        const idx = alvo.findIndex(m => m.video_id === est.video_id);
        if (idx >= 0) {
          this.playlist = alvo;
          this.indice = idx;
           this._faixaAtual = alvo[idx];
           this._videoEsperado = est.video_id;
          _playlistsGeral.ativa = est.playlist || 'default';
          this._resumoRestaurado = { video_id: est.video_id, posicao: est.posicao };
          this._pintaBarra();
          // Sobe o iframe (que estava ocioso) pra posicionar a música salva.
          if(window.EmilyMusicAudio?.restaurarLocal(est.video_id,est.posicao))return;
          this._carregarIframe();
        }
      }
    }
  },

  // Retoma o volume do slider — o bug antigo era hardcode 100 aqui, que
  // ignorava o volume escolhido a cada troca de música.
  _volumeAtual() {
    const s = $('#player-vol');
    return s ? Number(s.value) || 0 : 100;
  },

  _carregarIframe() {
    if (this.pronto || this._carregando) return;
    this._carregando = true;
    if (window.YT && YT.Player) {
      // API já carregada (reload, segunda chamada): cria direto, sem recarregar.
      this._criarPlayer();
      return;
    }
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
    window.onYouTubeIframeAPIReady = () => this._criarPlayer();
  },

  _criarPlayer() {
    this.player = new YT.Player('yt-host', {
      height: '180', width: '320',
      playerVars: { autoplay: 1, controls: 0, playsinline: 1, rel: 0 },
      events: {
        onReady: () => {
          if(window.EmilyMusicAudio?.localActive){window.EmilyMusicAudio.ytReady=true;return;}
          this.pronto = true;
          this._carregando = false;
          try {
            this.player.setVolume(this._volumeAtual());
            if (this._mutado || this._volumeAtual() === 0) this.player.mute();
            else this.player.unMute();
          } catch {}
          // Restaura a música que tocava antes do boot: carrega, posiciona no
          // exato segundo salvo e fica PAUSADA (não sai tocando sozinha).
          if (this._resumoRestaurado) {
            const r = this._resumoRestaurado;
            this._resumoRestaurado = null;
            try {
              this.player.loadVideoById(r.video_id);
              this.player.pauseVideo();
              setTimeout(() => {
                try {
                  this.player.seekTo(r.posicao, true);
                  this.player.pauseVideo();
                } catch {}
              }, 350);
              this.tocando = false;
              this._pintaControles();
            } catch {}
          }
          if (this._fila) { const f = this._fila; this._fila = null; f(); }
        },
        onStateChange: (e) => {
          // Reafirma audível ao entrar em playing/buffering.
          if (e.data === 1 || e.data === 3) {
            try {
              this.player.setVolume(this._volumeAtual());
              if (this._mutado || this._volumeAtual() === 0) this.player.mute();
              else if (this.player.isMuted()) this.player.unMute();
            } catch {}
          }
          this._estado(e.data);
        },
        onError: (e) => {
          if (this._ignorarEventos || window.EmilyMusicAudio?.localActive) return;
          console.warn('[PLAYER] erro do YouTube:', e.data);
          const video = this._videoCarregado();
          if (video && this._videoEsperado && video !== this._videoEsperado) return;
          this._marcarEstadoVisual('erro');
          this.proxima({ erro: true });
        },
      },
    });
  },

  // Toca com som garantido: unmute + volume do slider + play, na ordem.
  _darPlay() {
    try {
      this.player.unMute();
      this.player.setVolume(this._volumeAtual());
      this.player.playVideo();
    } catch {}
  },

  _videoCarregado() {
    try { return this.player?.getVideoData?.().video_id || ''; } catch { return ''; }
  },

  _estado(estado) {
    if (this._ignorarEventos) return;
    // 1 = tocando, 2 = pausado, 0 = terminou, 3 = buffering, 5 = parado (cued)
    const carregado = this._videoCarregado();
    // A API pode entregar ENDED/PAUSED da faixa antiga depois de loadVideoById.
    // Sem validar o id, esse callback tardio avançava duas músicas de uma vez.
    if (carregado && this._videoEsperado && carregado !== this._videoEsperado) return;
    if (estado === 0) {
      const desdeTroca = performance.now() - this._trocaEm;
      let terminouMesmo = false;
      try {
        const duracao = Number(this.player?.getDuration?.() || 0);
        const posicao = Number(this.player?.getCurrentTime?.() || 0);
        terminouMesmo = duracao > 0 && posicao >= duracao - Math.max(1.25, duracao * .01);
      } catch {}
      // Alguns embeds zeram a duração logo após ENDED. Nesse caso a faixa
      // confirmada + janela temporal é o fallback; posição conhecida vence.
      if (this._faixaConfirmada && (terminouMesmo || (this._duracao <= 0 && desdeTroca > 900))) {
        this.proxima({ natural: true });
      }
      return;
    }
    // Buffering (3) conta como "tocando" pro ícone: não faz sentido o botão
    // mostrar play enquanto a música está carregando pra tocar.
    this.tocando = estado === 1 || estado === 3;
    if (estado === 1) {
      this._faixaConfirmada = true;
      this._falhasTentadas.clear();
      this._iniciarTimer();
      this._marcarEstadoVisual('tocando');
    } else if (estado === 2 || estado === 3 || estado === 5) {
      this._pararTimer();
      this._marcarEstadoVisual(estado === 3 ? 'carregando' : 'pausado');
      if (estado === 2) this._persistir();
    }
    this._pintaControles();
    this._atualizarMediaSession();
  },

  // ── Seek bar / tempo ──────────────────────────────────────────
  _fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    const m = Math.floor(t / 60), s = Math.floor(t % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  },
  _atualizarTempo() {
    if (!this.player || !this.pronto || this.indice < 0) return;
    try {
      const dur = this.player.getDuration();
      const cur = this.player.getCurrentTime();
      if (dur > 0 && isFinite(dur)) {
        this._duracao = dur;
        const seek = $('#player-seek');
        if (seek && !this._buscando) {
          const pct = Math.min(100, (cur / dur) * 100);
          seek.value = pct;
          seek.style.setProperty('--seek', pct + '%');
        }
        const tCur = $('#player-time-cur');
        if (tCur) tCur.textContent = this._fmt(cur);
        const tDur = $('#player-time-dur');
        if (tDur) tDur.textContent = this._fmt(dur);
      }
    } catch {}
  },
  _iniciarTimer() {
    this._pararTimer();
    this._timer = setInterval(() => this._atualizarTempo(), 500);
    this._atualizarTempo();
  },
  _pararTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  // ── Shuffle: fila embaralhada de verdade ──────────────────────
  _embaralhar() {
    const fila = this.playlist.map((_, i) => i).filter(i => i !== this.indice);
    for (let i = fila.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [fila[i], fila[j]] = [fila[j], fila[i]];
    }
    this._filaShuffle = fila;
    this._posShuffle = -1;
  },
  _proximoShuffle() {
    if (this.playlist.length === 1) return 0;
    if (!this._filaShuffle.length) this._embaralhar();
    this._posShuffle += 1;
    if (this._posShuffle >= this._filaShuffle.length) {
      // Acabou a fila: reembaralha sem repetir a última faixa na emenda.
      const atual = this._filaShuffle[this._filaShuffle.length - 1];
      this._embaralhar();
      if (this._filaShuffle.length > 1 && this._filaShuffle[0] === atual) {
        [this._filaShuffle[0], this._filaShuffle[1]] = [this._filaShuffle[1], this._filaShuffle[0]];
      }
      this._posShuffle = 0;
    }
    return this._filaShuffle[this._posShuffle];
  },

  _zerarSeek() {
    const seek = $('#player-seek');
    if (seek) { seek.value = 0; seek.style.setProperty('--seek', '0%'); }
    const tCur = $('#player-time-cur');
    if (tCur) tCur.textContent = '0:00';
    const tDur = $('#player-time-dur');
    if (tDur) tDur.textContent = '0:00';
    this._duracao = 0;
  },

  tocar(indice, { registrarHistorico = true } = {}) {
    if (!this.playlist.length) return;
    if (indice == null) {
      indice = this.shuffle ? this._proximoShuffle() : 0;
    }
    indice = ((indice % this.playlist.length) + this.playlist.length) % this.playlist.length;
    if (registrarHistorico && this.indice >= 0 && this.indice !== indice) {
      this._historico.push(this.indice);
      if (this._historico.length > 100) this._historico.shift();
    }
    this.indice = indice;
    const m = this.playlist[this.indice];
    if (!m?.video_id) return;
    this._faixaAtual = m;
    if(m.origem)this._playlistAtivaSalva=m.origem;
    this._videoEsperado = m.video_id;
    this._faixaConfirmada = false;
    this._ignorarEventos = false;
    this._trocaEm = performance.now();
    this._carregarIframe();
    const iniciar = () => {
      // A fila de inicialização pode ter sido substituída antes da API ficar
      // pronta. Só a seleção mais recente tem autorização pra tocar.
      if (this._videoEsperado !== m.video_id) return;
      this.player.loadVideoById(m.video_id);
      this.player.setVolume(this._volumeAtual());
      if (this._mutado || this._volumeAtual() === 0) this.player.mute();
      else this.player.unMute();
      this.player.playVideo();
      this.tocando = true;
      this._zerarSeek();
      this._pintaBarra();
      this._pintaControles();
      this._pintaModal();
      this._marcarEstadoVisual('carregando');
      this._atualizarMediaSession();
      this._persistir();
    };
    if (this.pronto) iniciar();
    else this._fila = iniciar;
  },

  _repetirAtual() {
    // Preserva a fonte e o buffer: loadVideoById/audio.load descartam a
    // reprodução anterior e podem exigir outra requisição de mídia.
    const id = this.playlist[this.indice]?.video_id;
    if (!id) return;
    try {
      if (!this.pronto || !this.player || this._ignorarEventos ||
          this.player.getVideoData?.().video_id !== id) {
        this.tocar(this.indice, { registrarHistorico: false });
        return;
      }
      this._faixaConfirmada = false;
      this._trocaEm = performance.now();
      this.player.seekTo(0, true);
      this.player.playVideo();
      this.tocando = true;
      this._iniciarTimer();
      this._pintaControles();
      this._marcarEstadoVisual('tocando');
      this._atualizarMediaSession();
      this._persistir();
    } catch {
      this.tocar(this.indice, { registrarHistorico: false });
    }
  },

  proxima({ manual = false, natural = false, erro = false } = {}) {
    if (!this.playlist.length) return;
    this._pararTimer();
    if (natural && !erro && (this.loop === 2 || this.loop === 1 && this.playlist.length === 1)) {
      this._repetirAtual();
      return;
    }
    if (erro && this._videoEsperado) {
      this._falhasTentadas.add(this._videoEsperado);
      if (this._falhasTentadas.size >= this.playlist.length) {
        this.pausar();
        this._marcarEstadoVisual('erro');
        toast('Nenhuma faixa desta playlist pôde ser reproduzida', 'erro');
        return;
      }
    }
    let i;
    if (this.shuffle) {
      i = this._proximoShuffle();
    } else {
      i = this.indice + 1;
      if (i >= this.playlist.length) {
        if (natural && this.loop === 0 && !erro) { this.pausar(); return; }
        i = 0;
      }
    }
    this.tocar(i);
  },

  anterior(forcarFaixa = false) {
    if (!this.playlist.length) return;
    // Com mais de 3s, "anterior" reinicia a faixa — comportamento esperado
    // de players reais. Um segundo clique volta de fato no histórico.
    try {
      if (!forcarFaixa && (this.player?.getCurrentTime?.() || 0) > 3) {
        this.player.seekTo(0, true);
        return;
      }
    } catch {}
    if (this._historico.length) {
      return this.tocar(this._historico.pop(), { registrarHistorico: false });
    }
    this.tocar((this.indice - 1 + this.playlist.length) % this.playlist.length,
      { registrarHistorico: false });
  },

  playPause() {
    if (!this.player || !this.pronto || this.indice < 0) return;
    this.tocando ? this.player.pauseVideo() : this.player.playVideo();
  },

  pausar() {
    this._pararTimer();
    try { this.player && this.player.pauseVideo(); } catch {}
    this.tocando = false;
    this._marcarEstadoVisual('pausado');
    this._pintaControles();
    this._atualizarMediaSession();
  },

  alternarLoop() {
    // 0 → 1 (playlist) → 2 (música única) → 0
    this.loop = (this.loop + 1) % 3;
    this._pintaControles();
    this._persistir();
  },
  alternarShuffle() {
    this.shuffle = !this.shuffle;
    if (this.shuffle) this._embaralhar();
    this._pintaControles();
    this._persistir();
  },

  _marcarEstadoVisual(estado) {
    const barra = $('#player-barra');
    if (barra) barra.dataset.estado = estado;
    const sub = $('#player-sub');
    if (!sub) return;
    const base = this.playlist.length
      ? `${this.indice + 1} de ${this.playlist.length} · ${this._playlistAtivaSalva === 'default' ? 'Minha seleção' : this._playlistAtivaSalva === '__avulsa__' ? 'Reprodução avulsa' : this._playlistAtivaSalva}`
      : 'Emily Music';
    sub.textContent = estado === 'carregando' ? `Carregando · ${base}`
      : estado === 'erro' ? `Não foi possível tocar · ${base}`
        : estado === 'pausado' ? `Pausada · ${base}` : base;
  },

  _atualizarMediaSession() {
    if (!('mediaSession' in navigator)) return;
    const m = this._faixaAtual || this.playlist[this.indice];
    if (!m) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: m.titulo || 'Sem título', artist: 'Emily Music',
        album: this._playlistAtivaSalva || 'Playlist',
        artwork: m.thumb ? [{ src: m.thumb, sizes: '320x180' }] : [],
      });
      navigator.mediaSession.playbackState = this.tocando ? 'playing' : 'paused';
    } catch {}
  },

  // Persiste o estado atual no backend (volume, loop, shuffle, posição).
  _persistir() {
    const playlistNome = this._playlistAtivaSalva || _playlistsGeral.ativa || 'default';
    tenta('player_salvar_estado', {
      volume: this._mutado ? 0 : this._volumeAtual(),
      loop: this.loop,
      shuffle: this.shuffle,
      playlist: playlistNome,
      indice: this.indice,
      video_id: this.playlist[this.indice]?.video_id || null,
      posicao: this.player && this.pronto ? (this.player.getCurrentTime() || 0) : 0,
    });
  },

  fechar() {
    this._pararTimer();
    this._persistir();
    this._ignorarEventos = true;
    try { this.player && this.player.stopVideo(); } catch {}
    $('#player-barra').hidden = true;
    document.body.classList.remove('com-player');
    document.getElementById('player-resgate')?.remove();
    this._minimizada = false;
    this.tocando = false;
    this._pintaControles();
  },

  _pintaBarra() {
    const m = this.playlist[this.indice];
    if (!m) return;
    const capa = window.EmilyMusic?.offline.faixas[m.video_id]?.thumb || m.thumb;
    $('#player-thumb').src = capa;
    $('#player-thumb').alt = `Capa de ${m.titulo}`;
    const ambiente = $('#player-ambiente');
    if (ambiente) ambiente.src = capa;
    $('#player-titulo').textContent = m.titulo;
    this._marcarEstadoVisual(this.tocando ? 'tocando' : 'pausado');
    if (!this._minimizada) {
      $('#player-barra').hidden = false;
      document.body.classList.add('com-player');
      document.getElementById('player-resgate')?.remove();
    } else this._atualizarResgate();
  },

  _pintaControles() {
    const play = $('#player-play');
    if (!play) return;
    play.classList.toggle('tocando', this.tocando);
    play.classList.toggle('pausado', !this.tocando);
    play.setAttribute('aria-label', this.tocando ? 'Pausar' : 'Tocar');
    // Loop 3 estados: 0=off, 1=playlist (ativa+pontinho), 2=música (ativa+badge "1")
    const btnLoop = $('#player-loop');
    const badge = $('#loop-badge');
    if (this.loop === 0) {
      btnLoop.classList.remove('ativa');
      btnLoop.setAttribute('aria-pressed', 'false');
      btnLoop.title = 'Sem repetir';
      if (badge) badge.hidden = true;
    } else if (this.loop === 1) {
      btnLoop.classList.add('ativa');
      btnLoop.setAttribute('aria-pressed', 'true');
      btnLoop.title = 'Repetir playlist';
      if (badge) badge.hidden = true;
    } else {
      btnLoop.classList.add('ativa');
      btnLoop.setAttribute('aria-pressed', 'true');
      btnLoop.title = 'Repetir esta música';
      if (badge) badge.hidden = false;
    }
    // Shuffle on/off
    const btnShuf = $('#player-shuffle');
    btnShuf.classList.toggle('ativa', this.shuffle);
    btnShuf.setAttribute('aria-pressed', String(this.shuffle));
    btnShuf.title = this.shuffle ? 'Aleatório ligado' : 'Aleatório';
  },

  definirVolume(valor, { persistir = true } = {}) {
    try {
      valor = Math.max(0, Math.min(100, Math.round(Number(valor) || 0)));
      if (this.player && this.pronto) {
        this.player.setVolume(valor);
        if (valor > 0) { this.player.unMute(); this._mutado = false; }
        if (valor === 0) { this.player.mute(); this._mutado = true; }
      }
      const alto = $('#vol-ico-alto'), mudo = $('#vol-ico-mudo');
      if (alto && mudo) { alto.hidden = valor === 0; mudo.hidden = valor !== 0; }
      const s = $('#player-vol');
      if (s) { s.value = valor; s.style.setProperty('--vol', valor + '%'); }
      this._mutado = valor === 0;
      const pct = $('#player-vol-pct');
      if (pct) pct.textContent = valor + '%';
      if (persistir) this._persistir();
    } catch {}
  },

  minimizar() {
    $('#player-barra').hidden = true;
    document.body.classList.remove('com-player');
    this._minimizada = true;
    this._atualizarResgate();
  },

  _atualizarResgate() {
    if (!this._minimizada || !this._faixaAtual) return;
    let resgate = document.getElementById('player-resgate');
    if (!resgate) {
      resgate = document.createElement('button');
      resgate.id = 'player-resgate';
      resgate.type = 'button';
      resgate.onclick = () => {
        this._minimizada = false;
        $('#player-barra').hidden = false;
        document.body.classList.add('com-player');
        resgate.remove();
      };
      document.body.appendChild(resgate);
    }
    const m = this._faixaAtual;
    resgate.title = `Expandir player · ${m.titulo}`;
    resgate.setAttribute('aria-label', resgate.title);
    resgate.innerHTML = `<img src="${esc(m.thumb)}" alt=""><span class="player-resgate-eq" aria-hidden="true"><i></i><i></i><i></i></span>`;
  },

  _pintaModal() {
    if ($('#modal-player').hidden) return;
    desenharPlaylist();
  },
};

// Dados do modal de playlists (carregados do backend)
let _playlistsGeral = { playlists: {}, ativa: 'default', favoritos: {} };
let _somenteFavoritas = false;

async function carregarGeral() {
  const g = await tenta('playlist_geral');
  if (g) _playlistsGeral = g;
  return _playlistsGeral;
}

function desenharSidebar() {
  if(window.EmilyMusic){window.EmilyMusic.sidebar();return;}
  const nav = $('#pl-sidebar-lista');
  if (!nav) return;
  nav.innerHTML = '';
  for (const nome of Object.keys(_playlistsGeral.playlists)) {
    const dados = _playlistsGeral.playlists[nome];
    const qtd = dados.quantidade || (dados.musicas || []).length;
    const foto = dados.foto || '';
    const item = document.createElement('button');
    item.className = 'pl-sb-item' + (nome === _playlistsGeral.ativa ? ' ativa' : '');
    // Foto/icone
    const fotoEl = document.createElement('span');
    fotoEl.className = 'pl-sb-foto';
    if (foto) fotoEl.innerHTML = `<img src="${esc(foto)}" alt="">`;
    else fotoEl.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2z"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    item.appendChild(fotoEl);
    // Nome
    const nomeEl = document.createElement('span');
    nomeEl.className = 'pl-sb-nome';
    nomeEl.textContent = nome;
    item.appendChild(nomeEl);
    // Quantidade
    const count = document.createElement('span');
    count.className = 'pl-sb-count';
    count.textContent = qtd;
    item.appendChild(count);
    // Ações (renomear, foto, excluir)
    const acoes = document.createElement('span');
    acoes.className = 'pl-sb-acoes';
      // Renomear
      const ren = document.createElement('button');
      ren.title = 'Renomear';
      ren.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8" class="pbtn-mini"><path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>';
      ren.onclick = (ev) => { ev.stopPropagation(); abrirModalPlaylist(nome, dados); };
      acoes.appendChild(ren);
      // Foto (câmera)
      const fotoBtn = document.createElement('button');
      fotoBtn.title = 'Foto';
      fotoBtn.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>';
      fotoBtn.onclick = (ev) => { ev.stopPropagation(); abrirModalPlaylist(nome, dados); };
      acoes.appendChild(fotoBtn);
      // Excluir (só pra não-default — a padrão não se apaga)
      if (nome !== 'default') {
        const del = document.createElement('button');
        del.className = 'pl-sb-del';
        del.title = 'Apagar playlist';
        del.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>';
        del.onclick = async (ev) => {
          ev.stopPropagation();
          if (!confirm(`Apagar a playlist "${nome}"?`)) return;
          const ok = await tenta('playlist_apagar', nome);
          if (ok) {
            _playlistsGeral.ativa = 'default';
            await carregarGeral();
            await Player.carregarPlaylist();
            desenharSidebar();
            desenharPlaylist();
          }
        };
        acoes.appendChild(del);
      }
      item.appendChild(acoes);
    item.onclick = async () => {
      const ok = await tenta('playlist_selecionar', nome);
      if (ok) {
        _playlistsGeral.ativa = nome;
        await Player.carregarPlaylist();
        desenharSidebar();
        desenharPlaylist();
      }
    };
    nav.appendChild(item);
  }
}

// ── Modal de criar/editar playlist ──────────────────────────────
let _editandoPlaylist = null;
function abrirModalPlaylist(nome, dados) {
  _editandoPlaylist = nome ? { nome, foto: dados?.foto || '' } : null;
  const overlay = $('#pl-modal-overlay');
  if (!overlay) return;
  overlay.hidden = false;
  const titulo = $('#pl-modal-titulo');
  titulo.textContent = nome ? 'Editar playlist' : 'Nova playlist';
  const input = $('#pl-modal-nome');
  input.readOnly = nome === 'default';
  input.value = nome === 'default' ? 'Minha seleção' : (nome || '');
  input.focus();
  input.select();
  const confirmar = $('#pl-modal-confirmar');
  confirmar.textContent = nome ? 'Salvar' : 'Criar';
  const fotoImg = $('#pl-modal-foto-img');
  if (dados?.foto) fotoImg.innerHTML = `<img src="${esc(dados.foto)}" alt="">`;
  else fotoImg.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2z"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
  const fotoInput = $('#pl-modal-foto-input');
  if (fotoInput) fotoInput.value = '';
  overlay.classList.remove('fechando');
  overlay.classList.add('abrindo');
  setTimeout(() => overlay.classList.remove('abrindo'), 50);
}

function fecharModalPlaylist() {
  const overlay = $('#pl-modal-overlay');
  if (!overlay) return;
  overlay.classList.add('fechando');
  setTimeout(() => {
    overlay.hidden = true;
    overlay.classList.remove('fechando');
    _editandoPlaylist = null;
  }, 200);
}

function desenharPlaylist() {
  if(window.EmilyMusic){window.EmilyMusic.render();return;}
  const lista = $('#pl-lista');
  if (!lista) return;
  lista.innerHTML = '';
  const info = $('#pl-info');
  const exibidas = Player.playlist
    .map((m, indice) => ({ m, indice }))
    .filter(({ m }) => !_somenteFavoritas || !!_playlistsGeral.favoritos?.[m.video_id]);
  if (info) info.innerHTML = `<strong>${esc(_playlistsGeral.ativa)}</strong><span>${exibidas.length} faixa${exibidas.length === 1 ? '' : 's'}${_somenteFavoritas ? ' favorita' + (exibidas.length === 1 ? '' : 's') : ''}</span>`;
  if (!exibidas.length) {
    lista.innerHTML = `<div class="pl-vazia">${svg(_somenteFavoritas ? ICO.cerebro : ICO.musica)}<strong>${_somenteFavoritas ? 'Nenhuma favorita aqui' : 'Sua playlist está vazia'}</strong><span>${_somenteFavoritas ? 'Marque o coração de uma faixa para ela aparecer aqui.' : 'Busque uma música acima para começar.'}</span></div>`;
    return;
  }
  exibidas.forEach(({ m, indice: i }, posicao) => {
    const div = document.createElement('div');
    const atual = i === Player.indice;
    div.className = 'pl-item' + (atual ? ' tocando' : '');
    const marca = atual
      ? '<span class="pl-eq"><i></i><i></i><i></i></span>'
      : `<small>${posicao + 1}</small>`;
    div.innerHTML =
      `<img src="${esc(m.thumb)}" alt="">` +
      `<div class="pl-item-txt"><strong>${esc(m.titulo)}</strong>${marca}</div>`;
    div.onclick = () => { Player.tocar(i); };

    // Coração de favorito
    const fav = document.createElement('button');
    const ehFav = !!(_playlistsGeral.favoritos && _playlistsGeral.favoritos[m.video_id]);
    fav.className = 'pl-item-fav' + (ehFav ? ' ativo' : '');
    fav.title = ehFav ? 'Desfavoritar' : 'Favoritar';
    fav.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 21s-6.7-4.35-9.33-8.11C.9 10.2 1.9 6.5 4.9 5.3a5 5 0 017.1 1.9 5 5 0 017.1-1.9c3 1.2 4 4.9 2.23 7.59C18.7 16.65 12 21 12 21z"/></svg>';
    fav.onclick = async (ev) => {
      ev.stopPropagation();
      const novo = !ehFav;
      await tenta('playlist_favoritar', m.video_id, novo);
      if (_playlistsGeral.favoritos) {
        if (novo) _playlistsGeral.favoritos[m.video_id] = true;
        else delete _playlistsGeral.favoritos[m.video_id];
      }
      desenharPlaylist();
    };
    div.appendChild(fav);

    const del = document.createElement('button');
    del.className = 'icone-btn mini pl-item-del';
    del.title = 'Remover da playlist';
    del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      await tenta('playlist_remover', m.video_id);
      await carregarGeral();
      await Player.carregarPlaylist();
      desenharSidebar();
      desenharPlaylist();
    };
    div.appendChild(del);
    lista.appendChild(div);
  });
}

// ── Busca com prévia (resultados antes de adicionar) ────────────
let _debounceBusca = null;
async function buscarPreview(q) {
  if(window.EmilyMusic){return window.EmilyMusic.search(q);}
  const preview = $('#pl-preview');
  if (!preview) return;
  if (!q) { preview.hidden = true; preview.innerHTML = ''; return; }
  const erro = $('#pl-erro');
  if (erro) erro.hidden = true;
  preview.hidden = false;
  preview.innerHTML = '<p class="pl-prev-titulo">Buscando…</p>';
  const r = await tenta('playlist_buscar_preview', q);
  if (!r || r.erro) {
    preview.innerHTML = `<p class="pl-prev-titulo">${esc(r && r.erro ? r.erro : 'Sem resultados')}</p>`;
    return;
  }
  const res = r.resultados || [];
  preview.innerHTML = `<p class="pl-prev-titulo">${res.length} resultado${res.length > 1 ? 's' : ''} — clique pra adicionar</p>`;
  res.forEach(m => {
    const div = document.createElement('div');
    div.className = 'pl-prev-item';
    div.innerHTML =
      `<img src="${esc(m.thumb)}" alt="">` +
      `<div class="pl-prev-item-txt"><strong>${esc(m.titulo)}</strong></div>` +
      '<button class="pl-prev-add" title="Adicionar"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></button>';
    div.onclick = async () => {
      await tenta('playlist_adicionar', m.video_id, m.titulo, m.thumb);
      await carregarGeral();
      await Player.carregarPlaylist();
      desenharSidebar();
      desenharPlaylist();
      preview.hidden = true;
      preview.innerHTML = '';
    };
    preview.appendChild(div);
  });
}

function ligarPlayer() {
  // Instancia o modal de criar/editar playlist (template único, fora do palco)
  const tplModal = $('#tpl-modal-playlist');
  if (tplModal && !$('#pl-modal-overlay')) {
    document.body.appendChild(tplModal.content.cloneNode(true));
  }
  // Preenchimento do slider no boot (gradiente via CSS var --vol).
  const volSlider = $('#player-vol');
  if (volSlider) {
    volSlider.style.setProperty('--vol', volSlider.value + '%');
    const pct = $('#player-vol-pct');
    if (pct) pct.textContent = volSlider.value + '%';
  }
  const seekInit = $('#player-seek');
  if (seekInit) seekInit.style.setProperty('--seek', '0%');
  $('#btn-music').onclick = async () => {
    await carregarGeral();
    await Player.carregarPlaylist();
    $('#modal-player').hidden = false;
    desenharSidebar();
    desenharPlaylist();
    $('#pl-query').focus();
  };

  $('#pl-tocar-tudo').onclick = () => {
    const primeiro = Player.playlist.findIndex(m =>
      !_somenteFavoritas || !!_playlistsGeral.favoritos?.[m.video_id]);
    if (primeiro >= 0) Player.tocar(primeiro);
  };
  $('#pl-filtro-fav').onclick = (e) => {
    _somenteFavoritas = !_somenteFavoritas;
    e.currentTarget.classList.toggle('ativo', _somenteFavoritas);
    e.currentTarget.setAttribute('aria-pressed', String(_somenteFavoritas));
    desenharPlaylist();
  };

  $('#modal-player-fechar').onclick = () => { $('#modal-player').hidden = true; };
  $('#modal-player').onclick = (e) => {
    if (e.target.id === 'modal-player') $('#modal-player').hidden = true;
  };

  // Nova playlist — abre o modal bonito
  $('#pl-nova').onclick = () => abrirModalPlaylist('', {});

  // ── Modal de criar/editar playlist ──────────────────────────────
  // Foto: clique abre o seletor de arquivos
  const fotoModal = $('#pl-modal-foto');
  const fotoInput = $('#pl-modal-foto-input');
  if (fotoModal && fotoInput) {
    fotoModal.onclick = () => fotoInput.click();
    fotoInput.onchange = () => {
      const file = fotoInput.files && fotoInput.files[0];
      if (!file) return;
      if(!file.type.startsWith('image/') || file.size>5*1024*1024){toast('Escolha uma imagem de até 5 MB','erro');return;}
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUri = e.target.result;
        const img = $('#pl-modal-foto-img');
        if (img) img.innerHTML = `<img src="${dataUri}" alt="">`;
      };
      reader.readAsDataURL(file);
    };
  }
  // Fechar
  const fecharModal = () => fecharModalPlaylist();
  for (const el of $$('.pl-modal-fechar, #pl-modal-cancelar')) {
    if (el) el.onclick = fecharModal;
  }
  // Confirmar (criar ou salvar)
  $('#pl-modal-confirmar').onclick = async () => {
    const input = $('#pl-modal-nome');
    const nome = _editandoPlaylist?.nome === 'default' ? 'default' : (input.value || '').trim();
    if (!nome) return;
    // Pega a foto do data-uri que foi carregada
    const fotoImg = $('#pl-modal-foto-img');
    let foto = '';
    const img = fotoImg && fotoImg.querySelector('img');
    if (img) foto = img.src;
    if (_editandoPlaylist) {
      // Editar: renomear se mudou
      if (nome !== _editandoPlaylist.nome) {
        const r = await tenta('playlist_renomear', _editandoPlaylist.nome, nome);
        if (!r || r.erro) { alert(r?.erro || 'Não foi possível salvar. Tente novamente.'); return; }
      }
      // Foto se mudou
      if (foto !== _editandoPlaylist.foto) {
        await tenta('playlist_foto', nome, foto);
      }
    } else {
      // Criar nova
      const r = await tenta('playlist_criar', nome, foto);
      if (!r || r.erro) { alert(r?.erro || 'Não foi possível salvar. Tente novamente.'); return; }
    }
    if(window.EmilyMusic){
      if(_editandoPlaylist){if(Player._playlistAtivaSalva===_editandoPlaylist.nome)Player._playlistAtivaSalva=nome;for(const m of Player.playlist){if(m.origem===_editandoPlaylist.nome)m.origem=nome;}}
      window.EmilyMusic.view=nome;
      fecharModal();
      await window.EmilyMusic.refresh();
      window.EmilyMusic.go('playlist');
      return;
    }
    fecharModal();
    await carregarGeral();
    await Player.carregarPlaylist();
    desenharSidebar();
    desenharPlaylist();
  };
  // Enter no input confirma
  $('#pl-modal-nome').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#pl-modal-confirmar').click();
  });

  // Busca com prévia — o Enter busca, não adiciona direto.
  $('#pl-form').onsubmit = async (e) => {
    e.preventDefault();
    clearTimeout(_debounceBusca);
    const q = $('#pl-query').value.trim();
    if (!q) return;
    buscarPreview(q);
  };
  // Prévia enquanto digita (debounce pra não bater no YouTube a cada tecla).
  $('#pl-query').addEventListener('input', (e) => {
    const q = e.target.value.trim();
    if (_debounceBusca) clearTimeout(_debounceBusca);
    if (!q) {
      if(window.EmilyMusic){window.EmilyMusic.searchSerial++;window.EmilyMusic.go('inicio');}
      const preview = $('#pl-preview');
      if (preview) { preview.hidden = true; preview.innerHTML = ''; }
      return;
    }
    _debounceBusca = setTimeout(() => buscarPreview(q), 450);
  });

  // ── Seek bar ───────────────────────────────────────────────
  const seek = $('#player-seek');
  if (seek) {
    seek.addEventListener('input', () => {
      Player._buscando = true;
      const pct = Number(seek.value) || 0;
      seek.style.setProperty('--seek', pct + '%');
      if (Player._duracao > 0) {
        const tCur = $('#player-time-cur');
        if (tCur) tCur.textContent = Player._fmt(Player._duracao * pct / 100);
      }
    });
    seek.addEventListener('change', () => {
      Player._buscando = false;
      if (Player.player && Player.pronto) {
        const pct = Number(seek.value) || 0;
        const alvo = Player._duracao * pct / 100;
        try { Player.player.seekTo(alvo, true); } catch {}
      }
    });
  }

  $('#player-play').onclick = () => {
    // playVideo/pauseVideo direto aqui: o clique É o gesto que o Chromium
    // exige pra áudio — chamar via objeto indireto às vezes perde a janela
    // de ativação (medido: autoplay bloqueado sem isso).
    const p = Player.player;
    if (!p || !Player.pronto || Player.indice < 0) return;
    if (Player.tocando) { p.pauseVideo(); Player.tocando = false; }
    else {
      p.setVolume(Player._volumeAtual());
      if (Player._mutado) p.mute(); else p.unMute();
      p.playVideo(); Player.tocando = true;
    }
    Player._pintaControles();
  };
  $('#player-next').onclick = () => Player.proxima({ manual: true });
  $('#player-prev').onclick = () => Player.anterior();
  $('#player-loop').onclick = () => Player.alternarLoop();
  $('#player-shuffle').onclick = () => Player.alternarShuffle();
  $('#player-fechar').onclick = () => Player.fechar();
  $('#player-vol').oninput = (e) => Player.definirVolume(Number(e.target.value));
  $('#player-minimizar').onclick = () => Player.minimizar();
  $('#player-mute').onclick = () => {
    const slider = $('#player-vol');
    try {
      if (Player.player && Player.pronto) {
        if (Player.player.isMuted()) { Player.definirVolume(Number(slider.value) || 100); }
        else Player.player.mute();
        const mudo = Player.player.isMuted();
        Player._mutado = mudo;
        $('#vol-ico-alto').hidden = mudo;
        $('#vol-ico-mudo').hidden = !mudo;
        Player._persistir();
      } else {
        // sem player ainda: alterna só o ícone
        Player._mutado = !Player._mutado;
        const alto = $('#vol-ico-alto');
        alto.hidden = !alto.hidden;
        $('#vol-ico-mudo').hidden = !alto.hidden;
      }
    } catch {}
  };

  // Clique no bloco de faixa abre a biblioteca.
  $('#player-faixa').onclick = async () => {
    await Player.carregarPlaylist();
    $('#modal-player').hidden = false;
    desenharPlaylist();
  };

  window.EmilyMusic?.init();

  // Teclas de mídia e controles da tela bloqueada do Windows, quando a
  // WebView expõe Media Session.
  if ('mediaSession' in navigator) {
    const acoes = {
      play: () => Player.player?.playVideo?.(),
      pause: () => Player.pausar(),
      nexttrack: () => Player.proxima({ manual: true }),
      previoustrack: () => Player.anterior(true),
      seekto: d => { if (Number.isFinite(d.seekTime)) Player.player?.seekTo?.(d.seekTime, true); },
      seekforward: d => Player.player?.seekTo?.((Player.player?.getCurrentTime?.() || 0) + (d.seekOffset || 10), true),
      seekbackward: d => Player.player?.seekTo?.(Math.max(0, (Player.player?.getCurrentTime?.() || 0) - (d.seekOffset || 10)), true),
    };
    Object.entries(acoes).forEach(([nome, fn]) => {
      try { navigator.mediaSession.setActionHandler(nome, fn); } catch {}
    });
  }
}

// Liga junto com os outros botões no boot.
const _iniciarBase = typeof iniciar === 'function' ? iniciar : null;
document.addEventListener('DOMContentLoaded', () => {
  // ligarPlayer roda depois do boot principal; pequeno atraso garante DOM pronto.
  setTimeout(ligarPlayer, 50);
});
