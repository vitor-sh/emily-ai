/* Contrato do histórico compacto de ferramentas no chat normal. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'estilo.css'), 'utf8');

assert.match(app, /p\.className = 'progresso trabalhando aberto'/, 'trilha começa aberta durante a tarefa');
assert.doesNotMatch(app, /class="progresso-indicador"/, 'sem spinner genérico');
assert.match(app, /class="progresso-icone-simbolo"/, 'linha mostra o ícone da atividade');
assert.match(app, /class="progresso-historico"[^>]*aria-expanded="true" disabled/, 'a frase abre o histórico quando houver etapas');
assert.match(app, /class="progresso-seta"[^>]*hidden/, 'seta aparece quando houver etapas');
assert.match(app, /\.passo\.trabalhando:not\(\.fala\)/, 'linha acompanha a ação em execução');
assert.doesNotMatch(app, /class="progresso-ambiente"|class="progresso-ritmo"|class="passo-trilho"/, 'elementos decorativos antigos não devem voltar');
assert.match(app, /class="passo-status">Executando/, 'etapa precisa informar estado');
assert.match(app, /class="passo-tempo"/, 'etapa precisa informar duração');
assert.match(app, /typeof dados\.ok === 'boolean'/, 'resultado estruturado deve vencer heurística textual');
assert.match(app, /dados\.mudou === true/, 'alteração precisa de estado visual próprio');
assert.match(app, /_detalheArgumentos\(dados\.args\)/, 'argumentos devem ser legíveis, não JSON cru');
assert.match(app, /msg de-emily comentario-progresso/, 'comentário usa apresentação normal da Emily');
assert.match(app, /passos\.appendChild\(el\);\n      _atualizarResumoProgresso\(painel\)/, 'comentários devem manter a ordem no histórico');
assert.match(app, /\.passo\.trabalhando:not\(\.fala\)', passos\)\s*\.find/, 'resultado deve encontrar a primeira execução pendente');
assert.doesNotMatch(app, /class="passo-repeticao"/, 'cada repetição deve ter a própria linha');
assert.match(app, /painel\.dataset\.total/, 'contador deve preservar o total real de execuções');
assert.match(css, /Atividade das ferramentas no chat/, 'camada visual compacta precisa existir');
assert.match(css, /max-height: min\(310px, 44vh\)/, 'cartão aberto precisa ter altura limitada');
assert.match(css, /overflow: hidden auto/, 'muitas atividades devem rolar dentro do cartão');
assert.match(css, /\.progresso\.com-falha \.progresso-icone-simbolo/, 'falha precisa mudar o ícone');
assert.match(css, /\.progresso\.trabalhando \.progresso-rot[\s\S]*?animation: progresso-brilho/, 'frase ativa recebe brilho discreto');
assert.doesNotMatch(css, /\.progresso \{[^}]*border:/, 'a linha principal não deve voltar a ser um cartão');
assert.doesNotMatch(css, /prog-orbe|nucleo-respira|passo-pulso|barra-progresso-nova/, 'movimentos decorativos antigos não devem voltar');
assert.doesNotMatch(app, /class="img-prog-barra"|class="img-prog-passos"/, 'geração de imagem não deve simular progresso');
assert.match(app, /if \(tempoEl\) tempoEl\.textContent/, 'geração de imagem deve mostrar tempo real');
assert.match(css, /prefers-reduced-motion/, 'animações precisam respeitar movimento reduzido');

// Executa a lógica do cabeçalho com elementos mínimos. O navegador da Emily
// fornece o DOM; aqui conferimos as transições de estado sem abrir a janela.
const nomes = app.slice(app.indexOf('const _NOME_BONITO = {'), app.indexOf('function _detalheArgumentos'));
const argumentos = app.slice(app.indexOf('function _detalheArgumentos'), app.indexOf('function _contextoFerramenta'));
const contexto = app.slice(app.indexOf('function _contextoFerramenta'), app.indexOf('function _atualizarResumoProgresso'));
const resumo = app.slice(app.indexOf('function _atualizarResumoProgresso'), app.indexOf('function _trocarDetalhePasso'));
const detalhes = app.slice(app.indexOf('function _trocarDetalhePasso'), app.indexOf('function _criarProgresso'));
const finalizar = app.slice(app.indexOf('function _finalizarProgresso'), app.indexOf('function progresso(fase'));
const eventos = app.slice(app.indexOf('function progresso(fase'), app.indexOf('/* ── Geração de imagem'));
const ambiente = {
  ICO: new Proxy({}, { get: (_alvo, nome) => String(nome) }),
  ICO_GITHUB: 'github',
  svg: icone => `<svg>${icone}</svg>`,
  $: (seletor, raiz) => raiz.querySelector(seletor),
  $$: (seletor, raiz) => raiz.querySelectorAll(seletor),
  esc: texto => String(texto),
  requestAnimationFrame() {},
  rolarSePerto() {},
  _renderBolha() {},
  performance: { now: () => 1000 },
};
vm.runInNewContext(`${nomes}\n${argumentos}\n${contexto}\n${resumo}\n${detalhes}\n${finalizar}\n${eventos}\nglobalThis.ui = {
  nome: _nomeBonito, contexto: _contextoFerramenta,
  atualizar: _atualizarResumoProgresso, finalizar: _finalizarProgresso,
  progresso,
};`, ambiente);

assert.equal(ambiente.ui.nome('pesquisar_internet').ico, 'lupa');
assert.equal(ambiente.ui.nome('nuvem_exportar').ico, 'nuvem');
assert.equal(ambiente.ui.nome('github_ver_repo').ico, 'github');
assert.equal(ambiente.ui.nome('baixar_midia_da_aba').ico, 'globo');
assert.equal(ambiente.ui.nome('abrir_jogo').ico, 'jogo');
assert.equal(ambiente.ui.nome('code_git_status').rotulo, 'Verificando alterações no código');
assert.equal(ambiente.ui.nome('status_da_tv').ico, 'tv');
assert.equal(ambiente.ui.nome('criar_arquivo_txt').rotulo, 'Criando arquivo de texto');
assert.equal(ambiente.ui.contexto({ consulta: '  novidades   da Emily  ' }), 'novidades da Emily');
assert.equal(ambiente.ui.contexto({ site: '  https://youtube.com  ' }), 'https://youtube.com');

const titulo = { textContent: '' };
const icone = { innerHTML: '' };
const seta = { hidden: true };
const controle = { disabled: true, setAttribute() {}, querySelector: () => seta };
const nota = { textContent: 'Vou conferir mais uma coisa.' };
let ativa = [{ dataset: { nome: 'pesquisar_internet', contexto: 'novidades da Emily' } }];
let trabalhando = true;
const painel = {
  dataset: { total: '1', concluidas: '0', notas: '0', falhas: '0', ultimaFase: 'ferramenta' },
  classList: { contains: classe => classe === 'trabalhando' ? trabalhando : false },
  querySelector: seletor => ({
    '.passo.fala .passo-nota': nota,
    '.progresso-historico': controle,
    '.progresso-rot': titulo,
    '.progresso-icone-simbolo': icone,
  })[seletor] || null,
  querySelectorAll: seletor => seletor === '.passo.trabalhando:not(.fala)' ? ativa
    : seletor === '.passo.fala .passo-nota' ? [nota] : [],
};
ambiente.ui.atualizar(painel);
assert.equal(titulo.textContent, 'Pesquisando na internet · novidades da Emily');
assert.equal(icone.innerHTML, '<svg>lupa</svg>');
assert.equal(controle.disabled, false);
assert.equal(seta.hidden, false);

ativa = [];
painel.dataset.concluidas = '1';
painel.dataset.ultimaFase = 'resultado';
painel.dataset.ultimoNome = 'pesquisar_internet';
painel.dataset.ultimoContexto = 'novidades da Emily';
painel.dataset.ultimoOk = '1';
ambiente.ui.atualizar(painel);
assert.equal(titulo.textContent, 'Pesquisando na internet · novidades da Emily');
assert.equal(icone.innerHTML, '<svg>lupa</svg>');

painel.dataset.ultimaFase = 'fala';
ambiente.ui.atualizar(painel);
assert.equal(titulo.textContent, nota.textContent);

trabalhando = false;
painel.dataset.falhas = '1';
ambiente.ui.atualizar(painel);
assert.match(titulo.textContent, /^Concluiu com atenção por /);
assert.equal(icone.innerHTML, '<svg>x</svg>');

// Se o turno terminar sem o resultado da ferramenta, o histórico não deve
// marcar a ação como concluída com sucesso.
const statusPendente = { textContent: '' };
const iconePendente = { innerHTML: '', classList: { add() {} } };
const classesPendentes = new Set(['trabalhando']);
const passoPendente = {
  dataset: { pendentes: '1', falhas: '0', mudancas: '0' },
  classList: {
    remove: (...nomes) => nomes.forEach(nome => classesPendentes.delete(nome)),
    add: nome => classesPendentes.add(nome),
  },
  querySelector: seletor => ({ '.passo-status': statusPendente, '.passo-ico': iconePendente })[seletor] || null,
};
const classesPainel = new Set(['trabalhando']);
const painelPendente = {
  dataset: { total: '1', concluidas: '0', notas: '0', falhas: '0', mudancas: '0' },
  classList: {
    contains: nome => classesPainel.has(nome),
    remove: nome => classesPainel.delete(nome),
    add: nome => classesPainel.add(nome),
  },
  querySelector: painel.querySelector,
  querySelectorAll: seletor => seletor === '.passo.trabalhando' ? [passoPendente] : [],
};
ambiente.ui.finalizar(painelPendente);
assert.equal(statusPendente.textContent, 'Interrompido antes do resultado');
assert.equal(painelPendente.dataset.falhas, '1');
assert.match(titulo.textContent, /^Concluiu com atenção por /);
assert.equal(classesPendentes.has('falhou'), true);

console.log('ok: estados e detalhes preservados; agrupamento coberto pelo teste DOM');
