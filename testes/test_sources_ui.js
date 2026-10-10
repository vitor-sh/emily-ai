/* O bloco de fontes mostra favicons, links e ignora URLs inválidas. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'estilo.css'), 'utf8');
const fonte = app.slice(app.indexOf('function fontesDaResposta('),
  app.indexOf('function _marcarMensagemEstruturada('));
let bloco;
const alvo = {
  querySelector: () => null,
  insertBefore: item => { bloco = item; },
};
const ambiente = {
  URL,
  Set,
  ICO: { seta: 'seta', globo: 'globo' },
  svg: icone => `<svg>${icone}</svg>`,
  esc: texto => String(texto).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]),
  document: { createElement: () => ({
    className: '', innerHTML: '', querySelectorAll: () => [],
  }) },
};
vm.runInNewContext(`${fonte}\nglobalThis.mostrar = fontesDaResposta;`, ambiente);
ambiente.mostrar(alvo, [
  { titulo: 'Página <oficial>', url: 'https://example.org/bench' },
  { titulo: 'Repetida', url: 'https://example.org/bench' },
  { titulo: 'Não abrir', url: 'javascript:alert(1)' },
  { titulo: 'Credencial', url: 'https://user:pass@example.org/secret' },
]);

assert.equal(bloco.className, 'msg-fontes');
assert.match(bloco.innerHTML, /Fontes · 1/);
assert.match(bloco.innerHTML, /https:\/\/example\.org\/favicon\.ico/);
assert.match(bloco.innerHTML, /href="https:\/\/example\.org\/bench"/);
assert.match(bloco.innerHTML, /Página &lt;oficial&gt;/);
assert.doesNotMatch(bloco.innerHTML, /javascript:|secret|Repetida/);
assert.match(css, /\.msg-fontes-lista/);
