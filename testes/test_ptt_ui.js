/* Captura de uma tecla por vez e indicação na seção Voz. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const app = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(__dirname, '..', 'web', 'estilo.css'), 'utf8');
assert.match(app, /id="cfg-ptt-tecla"/, 'controle aparece nas configurações');
assert.match(app, /tenta\('ptt_tecla_capturar', requisicao, \{ __teto: 30000 \}\)/,
  'captura nativa aceita códigos físicos inclusive símbolos e modificadores');
assert.match(app, /tenta\('ptt_tecla_cancelar', requisicao\)/, 'modal pode cancelar a captura');
assert.doesNotMatch(app, /data-ptt-tecla=/, 'não há lista fixa de botões');
assert.doesNotMatch(css, /\.ptt-captura-opcoes/, 'estilo da lista fixa foi removido');
assert.match(css, /\.progresso \{\s*width: min\(620px, 100%\); margin: 3px 0 9px;/,
  'linha de progresso começa no mesmo recuo do chat');
console.log('ok: captura PTT e alinhamento do progresso');
