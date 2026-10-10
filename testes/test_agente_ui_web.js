/* Contrato estático do painel global do agente visual. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const raiz = path.join(__dirname, '..');
const app = fs.readFileSync(path.join(raiz, 'web', 'app.js'), 'utf8');
const css = fs.readFileSync(path.join(raiz, 'web', 'estilo.css'), 'utf8');
const html = fs.readFileSync(path.join(raiz, 'web', 'index.html'), 'utf8');

for (const id of [
  'btn-tela', 'agente-ui-painel', 'agente-ui-form-iniciar', 'agente-ui-pausar',
  'agente-ui-retomar', 'agente-ui-cancelar', 'agente-ui-form-mensagem',
]) assert.match(html, new RegExp(`id="${id}"`), `faltou #${id}`);

assert.match(app, /case 'agente_ui':\s+aplicarEstadoAgenteUI\(d\)/,
  'eventos Python -> JS precisam atualizar o painel');
assert.match(app, /tenta\('agente_ui_estado'\)/,
  'estado precisa ser recuperável após reload ou evento perdido');
assert.match(app, /comandoAgenteUI\('agente_ui_iniciar', objetivo\)/,
  'painel precisa iniciar tarefa pela ponte');
assert.match(app, /comandoAgenteUI\('agente_ui_mensagem', mensagem\)/,
  'painel precisa enviar orientação ao vivo');
assert.match(html, /id="agente-ui-painel" hidden/,
  'painel do agente precisa iniciar totalmente oculto');
assert.match(html, /id="btn-tela"[^>]+aria-controls="agente-ui-painel"/,
  'botão de monitor precisa controlar o painel do agente');
assert.match(app, /\$\('#btn-tela'\)\.onclick\s*=\s*e\s*=>[\s\S]*definirPainelAgenteUI/,
  'botão de monitor precisa abrir e fechar o agente visual');
assert.doesNotMatch(app, /\$\('#btn-tela'\)\.onclick[^\n]*capturar_tela/,
  'botão de monitor não deve mais iniciar a captura antiga');
assert.match(app, /painel\.hidden = !aberto/,
  'fechar o painel precisa removê-lo visualmente da interface');
assert.match(app, /if \(e\.key === 'Escape'/,
  'Escape precisa fechar o popover do agente');
assert.match(app, /if \(ESTADO\.agenteUI\) aplicarEstadoAgenteUI\(ESTADO\.agenteUI\)/,
  'alternar demo precisa repintar bloqueios do agente');
assert.match(css, /\.agente-ui-painel\s*\{/,
  'painel precisa de estilo próprio');
assert.match(css, /--agente-ui-bottom/,
  'painel precisa ser ancorado dinamicamente acima do botão');
assert.match(css, /prefers-reduced-motion[\s\S]*agente-ui-painel/,
  'animação do agente precisa respeitar movimento reduzido');

console.log('ok: contrato do painel global do agente visual');
