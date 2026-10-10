/* Markdown da resposta em andamento deve ter a mesma estrutura do histórico. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const trecho = (inicio, fim) => app.slice(app.indexOf(inicio), app.indexOf(fim));
const sanitizador = trecho('function textoVisivelSemTagsDeVoz(', '/* Estado do saneamento incremental.');
const markdown = trecho('const _COD_NOME = {', '/* ════════════════════════════════════════════════════════════════\n   TOASTS');
const textoBolha = trecho('function _textoLimpoDaBolha()', 'function _renderBolha()');
const renderBolha = trecho('function _renderBolha()', 'function emilyEscreve(');
const respostaFinal = trecho('function emilyRespostaFinal(', '/* Espera de resposta:');
const corpo = { innerHTML: '' };
const bolha = {
  isConnected: true,
  querySelector: seletor => seletor === '.msg-corpo' ? corpo : null,
  classList: { add() {}, remove() {} },
};
let criadas = 0;
const estado = {
  textoStream: '', ditoNoCartao: '', falasProcesso: [],
  vozPrefixoFiel: false, emilyAberta: null, emilyBolhaDoTurno: bolha,
};
const ambiente = {
  ESTADO: estado,
  TAGS_VOZ_FISH: new Set(['speaking softly']),
  PADRAO_TAG_VOZ_LIVRE: /^(?:speaking|sighing)/i,
  ICO: { copiar: 'copiar' }, svg: () => '<svg></svg>',
  destacar: texto => texto,
  esc: texto => String(texto).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]),
  novaMsg: () => { criadas++; return bolha; },
  fontesDaResposta() {}, rolarSePerto() {}, digitando() {}, _recolherAtividade() {},
  _desenharMarkdown: (alvo, texto) => { alvo.innerHTML = ambiente.renderizar(texto); },
};
vm.runInNewContext(`${sanitizador}\n${markdown}\n${textoBolha}\n${renderBolha}\n${respostaFinal}\n`
  + `globalThis.renderizar=markdown; globalThis.limpar=_textoLimpoDaBolha;`
  + `globalThis.desenhar=_renderBolha; globalThis.finalizar=emilyRespostaFinal;`, ambiente);

const resposta = 'Resumo\n\n| Área | Sol | Astra |\n|---|---|---|\n'
  + '| Código | Bom | Ótimo |\n\n```python\n    valor = 1\n```';
estado.textoStream = resposta;
estado.ditoNoCartao = resposta;
const aoVivo = ambiente.limpar();
assert.match(aoVivo, /\|---\|---\|---\|/);
assert.match(ambiente.renderizar(aoVivo), /<table class="md-tabela">/);
assert.match(ambiente.renderizar(aoVivo), /    valor = 1/);

// Ao sair e voltar do estado "falando", o stream continua na mesma bolha.
ambiente.desenhar();
assert.equal(criadas, 0);
assert.equal(estado.emilyAberta, bolha);

// Uma mudança de status pode fechar o cursor antes de chegar o evento final.
// O texto definitivo deve reformar a mesma mensagem, sem criar duplicata.
estado.emilyAberta = null;
ambiente.finalizar(resposta);
assert.equal(criadas, 0);
assert.match(corpo.innerHTML, /<table class="md-tabela">/);
assert.equal(estado.emilyBolhaDoTurno, null);

// Falha de áudio: o prefixo retido aparece mesmo sem frase falada.
const fala = trecho('function emilyEscreve(', 'function emilyDelta(');
vm.runInNewContext(`${fala}\nglobalThis.falar=emilyEscreve;`, ambiente);
estado.respostaFinalTexto = '';
estado.emilyBolhaDoTurno = bolha;
ambiente.falar('', 'Texto **preservado** ');
assert.equal(estado.textoStream, 'Texto **preservado** ');
assert.match(corpo.innerHTML, /<strong>preservado<\/strong>/);
ambiente.finalizar('Texto **preservado** final.');
const antesTardio = criadas;
ambiente.falar('Texto **preservado** final.');
assert.equal(criadas, antesTardio, 'status atrasado não deve criar outra resposta');
