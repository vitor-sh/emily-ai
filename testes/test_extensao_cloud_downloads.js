'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const raiz = path.resolve(__dirname, '..');
const fonte = fs.readFileSync(path.join(raiz, 'extensao_emily', 'background.js'), 'utf8');
const inicio = fonte.indexOf('const CHAVE_DOWNLOADS_EMILY');
const fim = fonte.indexOf('// Recursos de mídia vistos na rede.');
assert.ok(inicio >= 0 && fim > inicio, 'bloco de persistência não encontrado');

function evento() {
  const listeners = [];
  return {
    addListener(fn) { listeners.push(fn); },
    async disparar(dados) { for (const fn of listeners) await fn(dados); },
  };
}

function criarVida(storage, downloads, enviados) {
  const onChanged = evento();
  const chrome = {
    runtime: { getManifest: () => ({ version: 'teste' }) },
    storage: { local: {
      async get(chaves) {
        const saida = {};
        for (const chave of chaves) if (chave in storage) saida[chave] = storage[chave];
        return structuredClone(saida);
      },
      async set(dados) { Object.assign(storage, structuredClone(dados)); },
    } },
    downloads: {
      onChanged,
      async search({ id }) { return downloads[id] ? [structuredClone(downloads[id])] : []; },
    },
  };
  const contexto = {
    chrome, console, Map, Promise, Object, Number, structuredClone,
    enviarParaEmily(dados) { enviados.push(structuredClone(dados)); return true; },
  };
  vm.createContext(contexto);
  const bloco = fonte.slice(inicio, fim) + `
globalThis.__cloudTeste = {
  downloadsDaEmily, downloadsCarregados, persistirDownloadsEmily,
  reconciliarDownloadsEmily, confirmarDownloadCloud
};`;
  vm.runInContext(bloco, contexto, { filename: 'downloads@background.js' });
  return { api: contexto.__cloudTeste, onChanged };
}

(async () => {
  const storage = {};
  const downloads = {
    7: { id: 7, state: 'complete', filename: '/tmp/feito.zip', url: 'https://a.invalid/x' },
    99: { id: 99, state: 'complete', filename: '/tmp/manual.zip', url: 'https://manual.invalid' },
  };

  // Vida 1: download da Emily termina sem backend conectado. A conclusão fica
  // persistida; o download manual 99 nunca entra no mapa.
  const enviados1 = [];
  const vida1 = criarVida(storage, downloads, enviados1);
  await vida1.api.downloadsCarregados;
  vida1.api.downloadsDaEmily.set(7, {
    url: downloads[7].url, iniciadoEm: 123, evento_id: 'ext-7-123',
  });
  await vida1.api.persistirDownloadsEmily();
  await vida1.onChanged.disparar({ id: 7, state: { current: 'complete' } });
  await vida1.onChanged.disparar({ id: 99, state: { current: 'complete' } });
  assert.equal(Object.keys(storage.emily_downloads_pendentes).length, 1);
  assert.equal(storage.emily_downloads_pendentes['7'].concluido.evento_id, 'ext-7-123');

  // Vida 2: simula suspensão/reinício. Restaura do storage, reenvia ao conectar
  // e só apaga depois do ACK positivo.
  const enviados2 = [];
  const vida2 = criarVida(storage, downloads, enviados2);
  await vida2.api.downloadsCarregados;
  await vida2.api.reconciliarDownloadsEmily();
  assert.equal(enviados2.length, 1);
  assert.equal(enviados2[0].tipo, 'download_concluido');
  assert.equal(enviados2[0].evento_id, 'ext-7-123');
  assert.equal(await vida2.api.confirmarDownloadCloud('ext-7-123', false), false);
  assert.equal(Object.keys(storage.emily_downloads_pendentes).length, 1);
  assert.equal(await vida2.api.confirmarDownloadCloud('ext-7-123', true), true);
  assert.deepEqual(storage.emily_downloads_pendentes, {});
  console.log('extensão cloud downloads: OK');
})().catch(erro => { console.error(erro); process.exitCode = 1; });