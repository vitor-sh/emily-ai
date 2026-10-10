/* Nenhuma chave fica em localStorage, URL ou mensagens de diagnóstico. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let etapa = 0, provedor = '', recibo = '', ocupado = false, api = null, anterior = {}, salvo = false;
  const payload = () => ({nome: $('name').value, provedor, base: $('base').value,
    modelo: $('model').value, chave: $('key').value, manter_chave: !!anterior.tem_chave, voz: {ativa: $('voice-enabled').checked, chave: $('voice-key').value, id: $('voice-id').value, manter_chave: !!anterior.voz?.tem_chave}, microfone: {ativo: $('mic-enabled').checked, chave: $('mic-key').value, manter_chave: !!anterior.microfone?.tem_chave}, discord: {ativo: $('discord-enabled').checked, token: $('discord-token').value, canais: $('discord-channels').value, manter_token: !!anterior.discord?.tem_token}});
  function mensagem(id, texto, tipo = '') {
    const el = $(id); el.textContent = texto; el.className = `notice ${tipo}`; el.hidden = !texto;
  }
  function atualizar() {
    $('next').disabled = ocupado || !api || (etapa === 1 && !recibo) || (etapa === 2 && !$('consent').checked);
    $('back').disabled = ocupado; $('test').disabled = ocupado || !api;
    $('load-models').disabled = ocupado || !api;
    document.querySelectorAll('.provider, #name, #base, #key, #model, #voice-key, #voice-id, #voice-enabled, #voice-test, #mic-key, #mic-enabled, #mic-test, #discord-enabled, #discord-token, #discord-channels, #discord-test').forEach(el => { el.disabled = ocupado; });
    $('test').setAttribute('aria-busy', String(ocupado));
    $('test').querySelector('.spinner').hidden = !ocupado;
  }
  function invalidar() { recibo = ''; mensagem('connection-message', ''); atualizar(); }
  function mostrar(n) {
    etapa = n;
    document.querySelectorAll('.page').forEach(el => { el.hidden = true; });
    $(n === 3 ? 'page-done' : `page-${n}`).hidden = false;
    $('back').hidden = n === 0 || n === 3;
    $('footer-note').hidden = n !== 0 && n !== 3;
    $('counter').innerHTML = `${String(Math.min(n + 1, 3)).padStart(2, '0')} <span>/ 03</span>`;
    document.querySelectorAll('.steps li').forEach((el, i) => {
      el.classList.toggle('active', i === n); el.classList.toggle('passed', i < n);
      if (i === n) el.setAttribute('aria-current', 'step'); else el.removeAttribute('aria-current');
    });
    $('next').querySelector('span').textContent = ['Vamos começar', 'Revisar configuração', 'Salvar e continuar', 'Abrir minha Emily'][n];
    mensagem('global-message', ''); atualizar();
    window.scrollTo({top: 0, behavior: 'auto'});
    document.querySelector('.pages').scrollTop = 0;
    requestAnimationFrame(() => $(n === 3 ? 'page-done' : `page-${n}`).querySelector('h1').focus({preventScroll: true}));
  }
  function selecionar(id, restaurar = false) {
    if (ocupado) return;
    provedor = id; invalidar();
    document.querySelectorAll('.provider').forEach(el => el.setAttribute('aria-pressed', String(el.dataset.provider === id)));
    $('connection-fields').hidden = false; $('base-field').hidden = id !== 'custom';
    $('key-field').hidden = id === 'ollama'; $('help').hidden = id === 'custom';
    $('key').value = ''; $('key').type = 'password'; $('show-key').setAttribute('aria-pressed', 'false');
    $('show-key').setAttribute('aria-label', 'Mostrar chave');
    if (!restaurar) { $('model').value = ''; $('model-options').replaceChildren(); }
    const descricoes = {
      openrouter: 'Crie uma chave na sua conta OpenRouter e cole abaixo. Cada modelo tem suas próprias condições e custos.',
      openai: 'Use uma chave da plataforma de API da OpenAI. A assinatura do ChatGPT é separada do uso da API.',
      ollama: 'O Ollama precisa estar aberto com um modelo já instalado. Modelos locais usam a memória e o processamento do seu computador.',
      custom: 'Conecte um servidor compatível com OpenAI, como seu OmniRoute. Use o endereço e a chave fornecidos por ele.'
    };
    $('provider-description').textContent = descricoes[id];
    $('help').innerHTML = id === 'ollama' ? 'Onde instalar o Ollama <span>↗</span>' : 'Como conseguir minha chave <span>↗</span>';
    $('test-cost').textContent = id === 'ollama' ? 'O teste usa o modelo do seu servidor local. A primeira resposta pode demorar enquanto ele carrega.' : 'O teste envia uma mensagem curta à IA e pode consumir saldo do serviço.';
    const podeManter = anterior.tem_chave && anterior.provedor === id;
    $('key').placeholder = podeManter ? 'Deixe vazio para manter a chave salva' : 'Cole sua chave aqui';
    $('key-help').textContent = 'Salva apenas neste perfil. Não compartilhe o arquivo de configuração.';
  }
  async function chamar(metodo, ...args) {
    if (!api || ocupado) return;
    ocupado = true; atualizar();
    try { return await api[metodo](...args); }
    catch (_) { return {ok: false, mensagem: 'Não consegui concluir essa etapa. Tente novamente.'}; }
    finally { ocupado = false; atualizar(); }
  }
  $('next').addEventListener('click', async () => {
    if (ocupado || !api) return;
    if (etapa === 0) {
      const nome = $('name').value.trim();
      if (!nome) { mensagem('global-message', 'Antes de começar, me conta como posso te chamar.', 'error'); $('name').focus(); return; }
      mostrar(1);
    } else if (etapa === 1 && recibo) {
      $('review-name').textContent = $('name').value.trim().split(/\s+/)[0];
      $('review-user').textContent = $('name').value.trim();
      $('review-provider').textContent = anterior.provedores[provedor].nome;
      $('review-model').textContent = $('model').value.trim();
      mostrar(2);
    } else if (etapa === 2 && $('consent').checked) {
      const resultado = await chamar('concluir', payload(), recibo, true);
      if (resultado?.ok) { salvo = true; $('key').value = ''; $('voice-key').value = ''; $('mic-key').value = ''; $('discord-token').value = ''; $('voice-audio').pause(); $('voice-audio').removeAttribute('src'); mostrar(3); }
      else mensagem('global-message', resultado?.mensagem || 'Não consegui salvar. Tente novamente.', 'error');
    } else if (etapa === 3 && salvo) {
      const abriu = await chamar('abrir');
      if (!abriu) mensagem('global-message', 'Configuração salva. Feche esta janela e abra a Emily novamente.', 'ok');
    }
  });
  $('back').addEventListener('click', () => { if (!ocupado) mostrar(etapa - 1); });
  document.querySelectorAll('.provider').forEach(el => el.addEventListener('click', () => selecionar(el.dataset.provider)));
  for (const id of ['name', 'base', 'key', 'model']) $(id).addEventListener('input', invalidar);
  $('consent').addEventListener('change', atualizar);
  $('name').addEventListener('keydown', event => { if (event.key === 'Enter' && !ocupado) $('next').click(); });
  $('show-key').addEventListener('click', () => {
    const revelar = $('key').type === 'password'; $('key').type = revelar ? 'text' : 'password';
    $('show-key').setAttribute('aria-pressed', String(revelar));
    $('show-key').setAttribute('aria-label', revelar ? 'Ocultar chave' : 'Mostrar chave');
  });
  $('help').addEventListener('click', () => { if (api) api.ajuda(provedor); });
  $('load-models').addEventListener('click', async () => {
    mensagem('connection-message', 'Buscando os modelos disponíveis…');
    const resultado = await chamar('modelos', payload());
    if (resultado?.ok) {
      $('model-options').replaceChildren();
      for (const modelo of resultado.modelos) { const option = document.createElement('option'); option.value = modelo; $('model-options').append(option); }
      $('model-help').textContent = `${resultado.modelos.length} modelos encontrados. Digite para filtrar ou escolher.`;
      mensagem('connection-message', 'Lista carregada. Escolha um modelo e teste a conexão.'); $('model').focus();
    } else mensagem('connection-message', resultado?.mensagem || 'Não consegui carregar a lista.', 'error');
  });
  $('test').addEventListener('click', async () => {
    recibo = ''; mensagem('connection-message', 'Conectando e esperando uma resposta curta da IA…');
    const resultado = await chamar('testar', payload());
    if (resultado?.ok) { recibo = resultado.recibo; mensagem('connection-message', resultado.mensagem, 'ok'); }
    else mensagem('connection-message', resultado?.mensagem || 'Não consegui conectar.', 'error');
    atualizar();
  });
  $('voice-enabled').addEventListener('change', () => { $('voice-fields').hidden = !$('voice-enabled').checked; });
  for (const id of ['voice-key', 'voice-id']) $(id).addEventListener('input', () => { $('voice-audio').pause(); $('voice-audio').removeAttribute('src'); $('voice-audio').hidden = true; mensagem('voice-message', 'Ouça a amostra para conferir esta configuração.'); });
  $('voice-help').addEventListener('click', () => { if (api) api.ajuda('fish'); });
  $('voice-test').addEventListener('click', async () => {
    mensagem('voice-message', 'Preparando um oi… pode levar alguns segundos.');
    const resultado = await chamar('testar_voz', payload());
    if (resultado?.ok) {
      $('voice-audio').src = 'data:audio/mpeg;base64,' + resultado.audio;
      $('voice-audio').hidden = false;
      try { await $('voice-audio').play(); } catch (_) { /* Controles permitem ouvir manualmente. */ }
      mensagem('voice-message', 'Amostra pronta. Sua voz será ativada ao salvar.', 'ok');
    } else mensagem('voice-message', resultado?.mensagem || 'Não consegui preparar a voz.', 'error');
  });
  $('mic-enabled').addEventListener('change', () => { $('mic-fields').hidden = !$('mic-enabled').checked; });
  $('mic-help').addEventListener('click', () => { if (api) api.ajuda('groq'); });
  $('mic-test').addEventListener('click', async () => {
    mensagem('mic-message', 'Conferindo sua conta Groq…');
    const resultado = await chamar('testar_microfone', payload());
    mensagem('mic-message', resultado?.mensagem || 'Não consegui verificar o acesso.', resultado?.ok ? 'ok' : 'error');
  });
  $('discord-enabled').addEventListener('change', () => { $('discord-fields').hidden = !$('discord-enabled').checked; });
  $('discord-help').addEventListener('click', () => { if (api) api.ajuda('discord'); });
  $('discord-test').addEventListener('click', async () => {
    mensagem('discord-message', 'Conferindo seu bot…');
    const resultado = await chamar('testar_discord', payload());
    mensagem('discord-message', resultado?.mensagem || 'Não consegui conferir o bot.', resultado?.ok ? 'ok' : 'error');
  });
  async function conectar() {
    if (api || !window.pywebview?.api) return;
    api = window.pywebview.api;
    try {
      anterior = await api.estado();
      $('discord-enabled').checked = !!anterior.discord?.ativo;
      $('discord-fields').hidden = !$('discord-enabled').checked;
      $('discord-channels').value = (anterior.discord?.canais || []).join(', ');
      if (anterior.discord?.tem_token) $('discord-token').placeholder = 'Deixe vazio para manter o token salvo';
      $('mic-enabled').checked = !!anterior.microfone?.ativo;
      $('mic-fields').hidden = !$('mic-enabled').checked;
      if (anterior.microfone?.tem_chave) $('mic-key').placeholder = 'Deixe vazio para manter a chave salva';
      $('voice-enabled').checked = !!anterior.voz?.ativa;
      $('voice-fields').hidden = !$('voice-enabled').checked;
      $('voice-id').value = anterior.voz?.id || '1d5c6866f45a44a3aa8df65061908ab2';
      if (anterior.voz?.tem_chave) $('voice-key').placeholder = 'Deixe vazio para manter a chave salva';
      $('name').value = anterior.nome || '';
      $('base').value = anterior.base || '';
      $('model').value = anterior.modelo || '';
      if (anterior.provedor) selecionar(anterior.provedor, true);
      mensagem('global-message', anterior.refazer ? 'Sua configuração precisa ser refeita. Seus outros dados foram preservados.' : '');
    } catch (_) { mensagem('global-message', 'Não consegui carregar o perfil. Feche e abra esta janela novamente.', 'error'); api = null; }
    atualizar();
  }
  document.querySelectorAll('h1').forEach(el => el.setAttribute('tabindex', '-1'));
  window.addEventListener('pywebviewready', conectar);
  conectar(); atualizar();
  setTimeout(() => { if (!api) mensagem('global-message', 'Abra esta tela pelo aplicativo Emily para configurar sua conexão.'); }, 8000);
})();
