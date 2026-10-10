'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM}=require('jsdom');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/estilo.css','utf8');
const dom=new JSDOM('<body><style>'+css+'</style><div id="fluxo-in"><article id="digitando">...</article></div></body>',{runScripts:'outside-only',pretendToBeVisual:true});
const w=dom.window;
w.ICO=new Proxy({},{get:(_,name)=>String(name)});w.ICO_GITHUB='github';w.svg=()=>'<svg></svg>';w.esc=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
w.$=(s,r=w.document)=>r.querySelector(s);w.$$=(s,r=w.document)=>Array.from(r.querySelectorAll(s));
w.ESTADO={tela:'chat',progresso:null,falasProcesso:[]};
for(const name of ['irPara','emilyFecha','restaurarAberturaAutomaticaNavegador','_renderBolha','rolarSePerto','abrirPainelNavegador'])w[name]=()=>{};
w.digitando=ligado=>{if(!ligado)w.document.querySelector('#digitando')?.remove();};
// Usa o mesmo renderer Markdown do chat, não um substituto do teste.
const md=app.slice(app.indexOf('const _COD_NOME ='),app.indexOf('function _temMarkdown'));
// O bloco contém também utilitários de UI; selecione funções Markdown até o próximo bloco principal.
const end=app.indexOf('/*',app.indexOf('function destacar'));
w.eval(app.slice(app.indexOf('const _COD_NOME ='),end));
w._desenharMarkdown=(el,text)=>{el.innerHTML=w.markdown(text);};
w.eval('let _avatarEmily="/avatar.png";'+app.slice(app.indexOf('const _NOME_BONITO = {'),app.indexOf('/* ── Geração de imagem')));
w.progresso('inicio');w.progresso('fala',{texto:'Vou conferir o **ícone** e os estilos compartilhados.'});
assert.equal(w.document.querySelector('#digitando'),null);
for(let i=0;i<5;i++){
 w.progresso('ferramenta',{nome:'programacao_editar',args:{arquivo:'web/app.js'}});
 w.progresso('resultado',{nome:'programacao_editar',ok:i!==2,resultado:i===2?'falhou':'alterado'});
}
let groups=w.document.querySelectorAll('.grupo-ferramentas');assert.equal(groups.length,1);assert.equal(groups[0].querySelectorAll('.passo').length,5);assert.ok(groups[0].classList.contains('falhou'));
assert.ok(groups[0].querySelector('.grupo-detalhes').hidden);assert.equal(w.getComputedStyle(groups[0].querySelector('.grupo-linha .progresso-rot')).fontSize,'14px');
assert.equal(w.getComputedStyle(groups[0].querySelector('.grupo-detalhes .passo-ativo')).display,'none');
w.progresso('fala',{texto:'Achei a causa; vou testar o **segundo seletor**.'});
w.progresso('ferramenta',{nome:'programacao_editar',args:{arquivo:'web/app.js'}});
w.progresso('resultado',{nome:'programacao_editar',ok:true,resultado:'ok'});
w.progresso('ferramenta',{nome:'programacao_executar',args:{comando:'python3 -m pytest'}});
w.progresso('resultado',{nome:'programacao_executar',ok:true,resultado:'executando'});
w.progresso('ferramenta',{nome:'programacao_status'});
w.progresso('resultado',{nome:'programacao_status',ok:true,resultado:'passou'});
groups=w.document.querySelectorAll('.grupo-ferramentas');assert.equal(groups.length,3);assert.equal(groups[2].querySelectorAll('.passo').length,2);
const panel=w.document.querySelector('.progresso'),children=[...panel.querySelector('.progresso-passos').children];
assert.deepEqual(children.map(e=>e.className),['msg de-emily comentario-progresso','grupo-ferramentas falhou','msg de-emily comentario-progresso','grupo-ferramentas','grupo-ferramentas']);
assert.ok(children[0].querySelector('.msg-corpo strong'));assert.ok(children[0].querySelector('.msg-autor .av img'));
const detail=groups[0].querySelector('.passo-detalhe'),restart=w.document.createElement('button');restart.className='btn';let clicked=false;restart.onclick=()=>clicked=true;detail.appendChild(restart);
w.progresso('fim');assert.equal(w.document.querySelector('.progresso'),null);assert.equal(w.document.querySelector('.comentario-progresso'),null);w.ESTADO.acoesFimTarefa[0].click();assert.ok(clicked);
w.progresso('inicio');w.progresso('ferramenta',{nome:'programacao_ler'});assert.equal(w.document.querySelectorAll('.passo').length,1);
w.progresso('fim');w.progresso('inicio');
function step(nome){w.progresso('ferramenta',{nome});w.progresso('resultado',{nome,ok:true,resultado:'ok'});}
step('navegador_interno_abrir');step('navegador_interno_ler');step('navegador_interno_clicar');
assert.equal(w.document.querySelectorAll('.grupo-ferramentas').length,1);
assert.equal(w.document.querySelector('.grupo-linha .progresso-rot').textContent,'Usando o navegador');
for(let i=0;i<12;i++) step('categoria_'+i);
assert.equal(w.document.querySelectorAll('.grupo-ferramentas').length,6);
assert.equal(w.document.querySelectorAll('.passo').length,15,'detalhes de todas as execuções preservados');
assert.equal(w.document.querySelectorAll('.grupo-ferramentas')[5].dataset.categoria,'categoria_11');
w.progresso('fala',{texto:'Agora vou conferir o resultado.'});
for(let i=0;i<10;i++) step('outra_'+i);
assert.equal(w.document.querySelectorAll('.grupo-ferramentas').length,12,'cada comentário ganha seis linhas próprias');
assert.equal(w.document.querySelectorAll('.comentario-progresso').length,1);
w.progresso('fim');assert.equal(w.document.querySelector('.progresso'),null);
dom.window.close();console.log('ok: agrupamento, detalhes reais, avatar, Markdown, ordem e recolhimento');
