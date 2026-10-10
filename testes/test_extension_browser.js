const fs = require("fs");
const path = require("path");
const assert = require("assert");

const root = path.resolve(__dirname, "..", "extensao_emily");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
const background = fs.readFileSync(path.join(root, "background.js"), "utf8");
const content = fs.readFileSync(path.join(root, "content.js"), "utf8");

assert.strictEqual(manifest.manifest_version, 3);
assert.ok(manifest.permissions.includes("scripting"));
assert.ok(manifest.permissions.includes("webRequest"));
assert.ok(manifest.permissions.includes("favicon"));
assert.ok(manifest.permissions.includes("history"));
assert.ok(manifest.host_permissions.includes("<all_urls>"));
assert.strictEqual(manifest.content_scripts[0].all_frames, true);
for (const tamanho of ["16", "32", "48", "128"]) {
  const relativo = manifest.icons[tamanho];
  assert.ok(relativo, `ícone ${tamanho} ausente no manifest`);
  assert.ok(fs.existsSync(path.join(root, relativo)), `arquivo do ícone ${tamanho} ausente`);
}

for (const recurso of ["descobrir_midias", "drm_detectado", "allFrames", "POPUP_DIAGNOSTICO"]) {
  assert.ok(background.includes(recurso), `background sem ${recurso}`);
}
assert.ok(background.includes("Illegal return statement"), "executor JS não aceita bloco com return");
assert.ok(content.includes("MutationObserver"), "content script sem suporte a SPA");
assert.ok(content.includes("shadowRoot"), "content script sem shadow DOM aberto");
assert.ok(background.includes('const WS_URL_PADRAO = "ws://127.0.0.1:8765"'), "ponte não está presa ao loopback");
assert.ok(background.includes('tipo: "autenticar", token: wsTokenAtual'), "handshake autenticado ausente");
assert.ok(background.indexOf("if (!autenticado) return") < background.indexOf("executarComando(comando)"),
  "comando pode ser executado antes da autenticação");
assert.ok(background.includes("request_id: requestId"), "respostas não ecoam request_id");
assert.ok(background.includes('case "fechar_outras_abas"'), "fechamento preservando alvo ausente");
assert.ok(background.includes("t.id !== preservar.id"), "fechamento não preserva a aba explícita");
assert.ok(background.includes("Só é permitido navegar para URL HTTP/HTTPS"), "navegação não restringe esquema");
assert.ok(background.includes('case "controlar_midia"'), "fallback limitado de mídia ausente");
assert.ok(background.includes("const permitidos = new Set"), "fallback de mídia não usa lista permitida");
assert.ok(background.includes('case "abrir_youtube"'), "abertura direta do YouTube ausente");
assert.ok(background.includes('case "historico_youtube"'), "consulta ao histórico do YouTube ausente");
assert.ok(background.includes("https://www.youtube.com/feed/history"), "histórico da conta do YouTube ausente");
assert.ok(background.includes("await abaBastidor()"), "histórico da conta não usa bastidor");
assert.ok(background.includes("chrome.history.search"), "histórico não usa a API local do navegador");
assert.ok(background.includes("https://www.youtube.com/watch?v=${videoId}"), "histórico não normaliza URL de vídeo");
assert.ok(background.includes("Download direto aceita apenas URL http/https"), "download direto não restringe esquema");
assert.ok(!background.includes("chrome.debugger"), "extensão ganhou acesso de depuração arbitrária");
console.log("OK: autenticação, correlação, abas, YouTube, histórico, mídia, downloads, manifest, SPA e ícones");