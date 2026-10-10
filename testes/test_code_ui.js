/* Contrato de isolamento do Emily Code no frontend, sem dependência de DOM. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const fonte = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');

assert.match(fonte, /emily_code_enviar', texto, cid\)/,
  'envio precisa carregar explicitamente o cid selecionado');
assert.match(fonte, /d\.cid && d\.cid !== _codeConversaAtiva/,
  'eventos de ferramenta precisam ser filtrados pela conversa de origem');
assert.match(fonte, /const eraPendente = !d\.cid \|\| _codePendentes\.has\(d\.cid\)/,
  'respostas repetidas precisam ser ignoradas');
assert.match(fonte, /if \(!_naTelaCode\) desenharConversas\(\)/,
  'recarga normal não pode redesenhar a sidebar do Code');
assert.match(fonte, /if \(_naTelaCode\) desenharConversas\(\)/,
  'recarga Code não pode redesenhar a sidebar normal');
assert.match(fonte, /const _unicasPorId = lista/,
  'a lista precisa deduplicar IDs antes de renderizar');
assert.match(fonte, /if \(tela !== 'code'\) \+\+_codeMontagem/,
  'sair do Code precisa cancelar montagens assíncronas antigas');
assert.match(fonte, /for \(const m of msgs\) codeRenderMensagem/,
  'histórico deve ser estático e não iniciar typings concorrentes');
assert.doesNotMatch(fonte, /_codeEscrevendo/,
  'lock global antigo não pode continuar no frontend');

console.log('ok: contrato de isolamento e deduplicação do Emily Code');