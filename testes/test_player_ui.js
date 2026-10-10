/* Teste isolado da máquina de navegação do player — sem DOM e sem YouTube. */
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const appPath = path.join(__dirname, '..', 'web', 'app.js');
const fonte = fs.readFileSync(appPath, 'utf8');
const inicio = fonte.indexOf('const Player = {');
const fim = fonte.indexOf('// Dados do modal de playlists', inicio);
assert.ok(inicio >= 0 && fim > inicio, 'objeto Player não encontrado em app.js');

let agora = 10_000;
const contexto = {
  console,
  navigator: {},
  performance: { now: () => agora },
  setInterval: () => 1,
  clearInterval: () => {},
  setTimeout: fn => { fn(); return 1; },
  clearTimeout: () => {},
  tenta: () => Promise.resolve(true),
  toast: () => {},
  _playlistsGeral: { ativa: 'default', favoritos: {} },
  desenharPlaylist: () => {},
  $: () => null,
};
vm.createContext(contexto);
const bloco = fonte.slice(inicio, fim).replace('const Player =', 'globalThis.Player =');
vm.runInContext(bloco, contexto, { filename: 'Player@app.js' });
const Player = contexto.Player;

const faixas = ['aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'].map((video_id, i) => ({
  video_id, titulo: `Faixa ${i + 1}`, thumb: `capa-${i + 1}.jpg`,
}));

function preparar(indice = 0) {
  Player.playlist = faixas.map(x => ({ ...x }));
  Player.indice = indice;
  Player.tocando = true;
  Player.loop = 1;
  Player.shuffle = false;
  Player.pronto = true;
  Player._historico = [];
  Player._filaShuffle = [];
  Player._posShuffle = -1;
  Player._falhasTentadas = new Set();
  Player._faixaAtual = Player.playlist[indice];
  Player._videoEsperado = Player.playlist[indice].video_id;
  Player._faixaConfirmada = true;
  Player._ignorarEventos = false;
  Player._trocaEm = agora - 5_000;
  Player._duracao = 100;
  Player._carregarIframe = () => {};
  Player._pintaBarra = () => {};
  Player._pintaControles = () => {};
  Player._pintaModal = () => {};
  Player._marcarEstadoVisual = () => {};
  Player._atualizarMediaSession = () => {};
  Player._persistir = () => {};
  Player._zerarSeek = () => {};
  Player._pararTimer = () => {};
  Player.player = {
    carregado: Player._videoEsperado,
    cargas: 0, reproducoes: 0,
    loadVideoById(id) { this.cargas++; this.carregado = id; },
    getVideoData() { return { video_id: this.carregado }; },
    tempo: 0,
    getCurrentTime() { return this.tempo; },
    getDuration() { return 100; },
    setVolume() {}, unMute() {}, mute() {}, playVideo() { this.reproducoes++; }, pauseVideo() {}, seekTo(t) { this.tempo = t; },
  };
}

preparar(0);
Player.loop = 2;
Player.proxima({ manual: true });
assert.equal(Player.indice, 1, 'próxima manual deve ignorar repetir-faixa');

preparar(1);
Player.loop = 2;
Player.proxima({ natural: true });
assert.equal(Player.indice, 1, 'fim natural deve repetir a mesma faixa');
assert.equal(Player.player.cargas, 0, 'repetição não deve recarregar a fonte');
assert.equal(Player.player.tempo, 0);
assert.equal(Player.player.reproducoes, 1);
assert.equal(Player._duracao, 100, 'repetição preserva a duração conhecida');
Player._estado(0);
assert.equal(Player.player.reproducoes, 1, 'ENDED atrasado não reinicia duas vezes');

preparar(0);
Player.playlist = [Player.playlist[0]];
Player.shuffle = true;
assert.equal(Player._proximoShuffle(), 0);
Player.proxima({ natural: true });
assert.equal(Player.player.cargas, 0, 'playlist com uma faixa também preserva o buffer');
assert.equal(Player.player.reproducoes, 1);

preparar(0);
Player.loop = 2;
Player.proxima({ natural: true, erro: true });
assert.equal(Player.indice, 1, 'erro não deve repetir o mesmo stream quebrado');

preparar(0);
Player.loop = 2;
Player.player.carregado = 'bbbbbbbbbbb';
Player.proxima({ natural: true });
assert.equal(Player.player.cargas, 1, 'fonte diferente deve carregar a faixa correta');

preparar(2);
Player.loop = 0;
let pausou = false;
const pausarReal = Player.pausar;
Player.pausar = () => { pausou = true; Player.tocando = false; };
Player.proxima({ natural: true });
assert.equal(pausou, true, 'fim da playlist sem loop deve pausar');
assert.equal(Player.indice, 2, 'fim sem loop não deve voltar à primeira faixa');
Player.pausar = pausarReal;

preparar(0);
Player.tocar(2);
assert.deepEqual([...Player._historico], [0], 'seleção deve guardar a faixa anterior');
Player.anterior(true);
assert.equal(Player.indice, 0, 'anterior deve voltar pelo histórico');
assert.deepEqual([...Player._historico], [], 'voltar não deve recolocar a faixa no histórico');

preparar(0);
let avancos = 0;
const proximaReal = Player.proxima;
Player.proxima = () => { avancos += 1; };
Player._trocaEm = agora;
Player._estado(0);
assert.equal(avancos, 0, 'ENDED imediato da faixa antiga deve ser ignorado');
agora += 1_000;
Player.player.tempo = 100;
Player._estado(0);
assert.equal(avancos, 1, 'ENDED confirmado da faixa atual deve avançar uma vez');
Player.proxima = proximaReal;

// O botão de resgate precisa ser removido por fechar(), mesmo se a barra já
// estiver minimizada. DOM mínimo só para esta regressão visual.
let resgateRemovido = false;
const resgate = { remove() { resgateRemovido = true; } };
contexto.document = {
  getElementById: id => id === 'player-resgate' ? resgate : null,
  body: { classList: { remove() {} } },
};
contexto.$ = () => ({
  hidden: false,
  classList: { add() {}, remove() {}, toggle() {} },
  setAttribute() {},
});
preparar(0);
Player._minimizada = true;
Player._persistir = () => {};
Player.fechar();
assert.equal(resgateRemovido, true, 'fechar deve remover o resgate minimizado');
assert.equal(Player._minimizada, false, 'fechar deve limpar o estado minimizado');

console.log('ok: navegação, loop, histórico e evento atrasado do player');