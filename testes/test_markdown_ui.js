/* Contrato executável do Markdown rico usado nas mensagens da Emily. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const inicio = app.indexOf('const esc =');
const fim = app.indexOf('/* ════════════════════════════════════════════════════════════════\n   TOASTS');
assert.ok(inicio >= 0 && fim > inicio, 'não encontrou o módulo Markdown no app.js');

const contexto = {};
vm.createContext(contexto);
vm.runInContext(`${app.slice(inicio, fim)}\nthis.renderizar = markdown;`, contexto);

const resposta = [
  'Pesquisei e o ponto principal é **bem simples**.',
  '',
  '## Comparação',
  '',
  '| Modelo | Velocidade | Preço |',
  '|:---|---:|:---:|',
  '| GLM | 90 tokens/s | $0.10/M |',
  '| Claude | 70 tokens/s | $3/M |',
  '',
  '### O que mudou',
  '',
  '- O contexto aumentou.',
  '- A qualidade ficou **melhor**.',
  '',
  '> O preço ainda pesa na decisão.',
  '',
  '---',
  '',
  '#### Veredito',
  '',
  'Vai de GLM no uso diário.',
].join('\n');

const html = contexto.renderizar(resposta);
assert.match(html, /<h2>Comparação<\/h2>/);
assert.match(html, /<h3>O que mudou<\/h3>/);
assert.match(html, /<h4>Veredito<\/h4>/);
assert.match(html, /class="md-tabela-wrap"/);
assert.match(html, /<table class="md-tabela">/);
assert.match(html, /<th class="al-esq">Modelo<\/th>/);
assert.match(html, /<th class="al-dir">Velocidade<\/th>/);
assert.match(html, /<th class="al-centro">Preço<\/th>/);
assert.match(html, /<ul><li>O contexto aumentou\.<\/li>/);
assert.match(html, /<blockquote>O preço ainda pesa na decisão\.<\/blockquote>/);
assert.match(html, /<hr>/);
assert.doesNotMatch(html, /## Comparação|\| Modelo \|/);

const conversa = contexto.renderizar('Tá bom, eu vejo isso com você depois.');
assert.equal(conversa, '<p>Tá bom, eu vejo isso com você depois.</p>');

const colado = contexto.renderizar('Texto normal. #### Título recuperado\n\nConteúdo.');
assert.match(colado, /<p>Texto normal\.<\/p><h4>Título recuperado<\/h4>/);

const seguro = contexto.renderizar('| Item | Valor |\n|---|---|\n| <script> | **ok** |');
assert.doesNotMatch(seguro, /<script>/);
assert.match(seguro, /&lt;script&gt;/);

const pipeEscapado = contexto.renderizar('| Expressão |\n|---|\n| `a | b` e c\\|d |');
assert.match(pipeEscapado, /<code>a \| b<\/code> e c\|d/);

console.log('ok: títulos, tabelas, listas, citações e conversa simples');