/**
 * background.js — Service Worker da extensão Emily Browser Bridge
 * Conecta ao WebSocket autenticado do gateway permanente da Emily.
 * e executa ações no navegador conforme comandos recebidos.
 */

const WS_URL_PADRAO = "ws://127.0.0.1:8765";
const CHAVE_CONFIG_PONTE = "emily_browser_bridge_config";
const KEEPALIVE_INTERVAL_MS = 20000; // 20s — obrigatório no MV3
const RECONNECT_DELAY_MS = 3000;
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const MAX_MEDIA_REQUESTS_PER_TAB = 120;
const CHAVE_DOWNLOADS_EMILY = "emily_downloads_pendentes";

let ws = null;
let keepaliveTimer = null;
let reconectando = false;
let conectado = false;
let autenticado = false;
let wsUrlAtual = WS_URL_PADRAO;
let wsTokenAtual = "";
const requisicoesMidiaPorAba = new Map();
const downloadsDaEmily = new Map();
let filaPersistenciaDownloads = Promise.resolve();

const downloadsCarregados = (async () => {
  try {
    const salvo = await chrome.storage.local.get([CHAVE_DOWNLOADS_EMILY]);
    const registros = salvo[CHAVE_DOWNLOADS_EMILY] || {};
    Object.entries(registros).forEach(([id, dados]) =>
      downloadsDaEmily.set(Number(id), dados));
  } catch (e) {
    console.warn("[Emily] Não consegui restaurar downloads acompanhados:", e);
  }
})();

function persistirDownloadsEmily() {
  const snapshot = Object.fromEntries(downloadsDaEmily);
  filaPersistenciaDownloads = filaPersistenciaDownloads
    .catch(() => {})
    .then(() => chrome.storage.local.set({ [CHAVE_DOWNLOADS_EMILY]: snapshot }));
  return filaPersistenciaDownloads;
}

function eventoDownload(registro, downloadId, item) {
  return {
    tipo: "download_concluido",
    evento_id: registro.evento_id,
    download_id: downloadId,
    caminho: item.filename,
    url: registro.url || item.finalUrl || item.url || "",
  };
}

function enviarDownloadPendente(downloadId, registro) {
  if (!registro?.concluido) return false;
  return enviarParaEmily(registro.concluido);
}

async function reconciliarDownloadsEmily() {
  await downloadsCarregados;
  const jaEnviados = new Set();
  for (const [downloadId, registro] of downloadsDaEmily) {
    if (registro.concluido) {
      enviarDownloadPendente(downloadId, registro);
      jaEnviados.add(downloadId);
      continue;
    }
    try {
      const [item] = await chrome.downloads.search({ id: downloadId });
      if (item?.state === "complete" && item.filename) {
        registro.concluido = eventoDownload(registro, downloadId, item);
        downloadsDaEmily.set(downloadId, registro);
      } else if (item?.state === "interrupted") {
        downloadsDaEmily.delete(downloadId);
      }
    } catch (e) {
      console.warn("[Emily] Não consegui reconciliar download", downloadId, e);
    }
  }
  await persistirDownloadsEmily();
  // Envia apenas o que ficou pendente nesta reconciliação. Os já enviados no
  // primeiro laço não podem repetir, senão cada reconexão duplica o evento.
  for (const [downloadId, registro] of downloadsDaEmily) {
    if (jaEnviados.has(downloadId)) continue;
    enviarDownloadPendente(downloadId, registro);
  }
}

async function confirmarDownloadCloud(eventoId, ok) {
  await downloadsCarregados;
  if (!eventoId || ok === false) return false;
  let removeu = false;
  for (const [downloadId, registro] of downloadsDaEmily) {
    if (registro.evento_id === eventoId) {
      downloadsDaEmily.delete(downloadId);
      removeu = true;
    }
  }
  if (removeu) await persistirDownloadsEmily();
  return removeu;
}

// Observa somente IDs criados pelo comando baixar_arquivo da Emily. Assim um
// download manual do usuário nunca entra no acervo sem ter sido solicitado.
chrome.downloads.onChanged.addListener(async delta => {
  await downloadsCarregados;
  if (!downloadsDaEmily.has(delta.id)) return;
  if (delta.state?.current === "interrupted") {
    downloadsDaEmily.delete(delta.id);
    await persistirDownloadsEmily();
    return;
  }
  if (delta.state?.current !== "complete") return;
  const origem = downloadsDaEmily.get(delta.id);
  try {
    const [item] = await chrome.downloads.search({ id: delta.id });
    if (item?.filename) {
      origem.concluido = eventoDownload(origem, delta.id, item);
      downloadsDaEmily.set(delta.id, origem);
      await persistirDownloadsEmily();
      enviarDownloadPendente(delta.id, origem);
    }
  } catch (e) {
    console.warn("[Emily] Não consegui informar o download concluído:", e);
  }
});

// Recursos de mídia vistos na rede. É observação passiva: a extensão não
// modifica, desbloqueia nem redireciona nenhuma requisição.
function pareceUrlDeMidia(url, tipoRecurso = "", contentType = "") {
  const u = (url || "").toLowerCase();
  const ct = (contentType || "").toLowerCase();
  return tipoRecurso === "media"
    || /\.(m3u8|mpd|mp4|m4v|webm|mov|mkv|mp3|m4a|aac|ogg|oga|opus|wav|flac)(?:[?#]|$)/i.test(u)
    || /^(video|audio)\//.test(ct)
    || /(application\/vnd\.apple\.mpegurl|application\/x-mpegurl|application\/dash\+xml)/.test(ct);
}

function guardarRequisicaoMidia(detalhes) {
  if (detalhes.tabId < 0) return;
  const headers = detalhes.responseHeaders || [];
  const contentType = headers.find(h => (h.name || "").toLowerCase() === "content-type")?.value || "";
  if (!pareceUrlDeMidia(detalhes.url, detalhes.type, contentType)) return;
  let lista = requisicoesMidiaPorAba.get(detalhes.tabId) || [];
  lista = lista.filter(item => item.url !== detalhes.url);
  lista.unshift({
    url: detalhes.url,
    tipo_recurso: detalhes.type || "",
    content_type: contentType,
    frame_id: detalhes.frameId,
    referer: /^https?:/i.test(detalhes.documentUrl || "") ? detalhes.documentUrl : "",
    initiator: /^https?:/i.test(detalhes.initiator || "") ? detalhes.initiator : "",
    visto_em: Date.now(),
  });
  requisicoesMidiaPorAba.set(detalhes.tabId, lista.slice(0, MAX_MEDIA_REQUESTS_PER_TAB));
}

chrome.webRequest.onResponseStarted.addListener(
  guardarRequisicaoMidia,
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);
chrome.tabs.onRemoved.addListener(tabId => requisicoesMidiaPorAba.delete(tabId));
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) requisicoesMidiaPorAba.delete(tabId);
});

// ─── Conexão WebSocket ────────────────────────────────────────────────────────

async function carregarConfigPonte() {
  try {
    const salvo = await chrome.storage.local.get([CHAVE_CONFIG_PONTE]);
    const cfg = salvo[CHAVE_CONFIG_PONTE] || {};
    const url = String(cfg.url || WS_URL_PADRAO).trim();
    wsUrlAtual = /^wss?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\/?$/i.test(url)
      ? url.replace(/\/$/, "")
      : WS_URL_PADRAO;
    wsTokenAtual = String(cfg.token || "").trim();
  } catch (_) {
    wsUrlAtual = WS_URL_PADRAO;
    wsTokenAtual = "";
  }
  return { url: wsUrlAtual, token_configurado: !!wsTokenAtual };
}

async function salvarConfigPonte(url, token) {
  const limpa = String(url || WS_URL_PADRAO).trim().replace(/\/$/, "");
  if (!/^wss?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(limpa)) {
    throw new Error("A ponte do navegador precisa usar localhost/127.0.0.1");
  }
  await chrome.storage.local.set({
    [CHAVE_CONFIG_PONTE]: { url: limpa, token: String(token || "").trim() },
  });
  wsUrlAtual = limpa;
  wsTokenAtual = String(token || "").trim();
  if (ws) try { ws.close(1000, "configuração alterada"); } catch (_) {}
  conectado = false;
  autenticado = false;
  reconectando = false;
  conectar();
}

async function conectar() {
  if (reconectando) return;
  reconectando = true;
  await carregarConfigPonte();

  try {
    ws = new WebSocket(wsUrlAtual);
  } catch (e) {
    console.error("[Emily] Erro ao criar WebSocket:", e);
    reconectando = false;
    agendarReconexao();
    return;
  }

  ws.onopen = async () => {
    console.log("[Emily] Socket aberto em", wsUrlAtual, "— autenticando");
    conectado = false;
    autenticado = false;
    reconectando = false;
    notificarStatus(false);
    iniciarKeepalive();
    ws.send(JSON.stringify({ tipo: "autenticar", token: wsTokenAtual }));
  };

  ws.onmessage = (event) => {
    try {
      const comando = JSON.parse(event.data);
      console.log("[Emily] Comando recebido:", comando);
      if (comando.tipo === "autenticado" && comando.ok === true) {
        autenticado = true;
        conectado = true;
        notificarStatus(true);
        enviarParaEmily({ tipo: "extensao_conectada", versao: EXTENSION_VERSION });
        reconciliarDownloadsEmily();
        return;
      }
      if (!autenticado) return;
      if (comando.tipo === "download_cloud_ack" && comando.evento_id) {
        confirmarDownloadCloud(comando.evento_id, comando.ok);
        return;
      }
      executarComando(comando);
    } catch (e) {
      console.error("[Emily] Erro ao processar mensagem:", e, event.data);
    }
  };

  ws.onerror = (err) => {
    console.warn("[Emily] Erro no WebSocket:", err);
  };

  ws.onclose = () => {
    console.warn("[Emily] WebSocket desconectado. Reconectando em", RECONNECT_DELAY_MS, "ms...");
    conectado = false;
    autenticado = false;
    reconectando = false;
    notificarStatus(false);
    pararKeepalive();
    agendarReconexao();
  };
}

function agendarReconexao() {
  setTimeout(() => {
    if (!conectado) conectar();
  }, RECONNECT_DELAY_MS);
}

// ─── Keepalive (necessário no MV3 — service worker fecha se ficar inativo) ───

function iniciarKeepalive() {
  pararKeepalive();
  keepaliveTimer = setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ tipo: "ping" }));
    } else {
      pararKeepalive();
    }
    // Força o service worker a continuar vivo
    chrome.runtime.getPlatformInfo(() => {});
  }, KEEPALIVE_INTERVAL_MS);
}

function pararKeepalive() {
  if (keepaliveTimer) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}

// ─── Envio de dados para a Emily ─────────────────────────────────────────────

function enviarParaEmily(dados) {
  if (autenticado && ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(dados));
    return true;
  }
  return false;
}

// ─── Notifica o popup sobre o status da conexão ──────────────────────────────

function notificarStatus(estaConectado) {
  chrome.storage.local.set({ emily_conectado: estaConectado });
}

// ─── Modo bastidor — a janela escondida onde a Emily trabalha ─────────────────
//
// Quando um comando vem com bastidor=true, ele age numa janela PRÓPRIA
// minimizada, em vez da aba ativa do Vitor. Mesma instalação, mesmo perfil,
// mesmos logins — só não aparece na cara dele e não rouba a aba que ele está
// usando. A janela é normal: se ele quiser espiar, é só restaurar.
// Os IDs sobrevivem ao service worker dormir via chrome.storage.session.

let bastidorWinId = null;
let bastidorTabId = null;

function salvarBastidor() {
  try {
    chrome.storage.session.set({ bastidorWinId, bastidorTabId });
  } catch (e) { /* sem storage.session: só perde o estado se o SW morrer */ }
}

async function restaurarBastidor() {
  if (bastidorTabId !== null || bastidorWinId !== null) return;
  try {
    const s = await chrome.storage.session.get(["bastidorWinId", "bastidorTabId"]);
    bastidorWinId = (typeof s.bastidorWinId === "number") ? s.bastidorWinId : null;
    bastidorTabId = (typeof s.bastidorTabId === "number") ? s.bastidorTabId : null;
  } catch (e) { /* segue com null */ }
}

// Garante a janela de bastidor e devolve a aba de trabalho dela.
// Revalida os IDs salvos: se o Vitor fechou a janela, cria outra na hora.
async function janelaBastidor() {
  await restaurarBastidor();
  if (bastidorWinId !== null) {
    try {
      return await chrome.windows.get(bastidorWinId);
    } catch (e) {
      bastidorWinId = null;
      bastidorTabId = null;
    }
  }
  const win = await chrome.windows.create({
    url: "about:blank",
    focused: false,
    state: "minimized",
    type: "normal",
  });
  bastidorWinId = win.id;
  bastidorTabId = (win.tabs && win.tabs[0]) ? win.tabs[0].id : null;
  salvarBastidor();
  return win;
}

async function abaBastidor() {
  const win = await janelaBastidor();
  if (bastidorTabId !== null) {
    try {
      return await chrome.tabs.get(bastidorTabId);
    } catch (e) { /* aba sumiu: pega a primeira da janela abaixo */ }
  }
  const abas = await chrome.tabs.query({ windowId: win.id });
  if (abas.length > 0) {
    bastidorTabId = abas[0].id;
    salvarBastidor();
    return abas[0];
  }
  return null;
}

// Resolve a ABA-ALVO de um comando: bastidor (janela escondida) quando o
// comando pedir, aba ativa do Vitor no resto — o comportamento de sempre.
// Devolve um ARRAY de abas (mesmo formato do tabs.query) pra os cases
// existentes continuarem usando tabs[0].
async function abaAlvo(comando) {
  if (typeof comando.tab_id === "number") {
    try {
      return [await chrome.tabs.get(comando.tab_id)];
    } catch (_) {
      throw new Error(`A aba ${comando.tab_id} não existe mais`);
    }
  }
  if (comando.bastidor) {
    const aba = await abaBastidor();
    if (!aba) throw new Error("Não consegui abrir a janela de bastidor");
    return [aba];
  }
  return chrome.tabs.query({ active: true, currentWindow: true });
}

function paginaRestrita(tab) {
  const url = tab?.url || "";
  return /^(chrome|edge|about|devtools|view-source|chrome-extension):/i.test(url)
    || /^https:\/\/(chromewebstore\.google\.com|microsoftedge\.microsoft\.com\/addons)/i.test(url);
}

function mensagemPaginaRestrita(tab) {
  return `O navegador não permite extensões nesta página (${tab?.url || "URL interna"}). `
    + "Abra um site http/https comum e tente novamente.";
}

async function aguardarAba(tabId, limiteMs = 8000) {
  const atual = await chrome.tabs.get(tabId);
  if (atual.status !== "loading") return atual;
  await new Promise(resolve => {
    let terminou = false;
    const finalizar = () => {
      if (terminou) return;
      terminou = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    const listener = (id, info) => {
      if (id === tabId && info.status === "complete") finalizar();
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(finalizar, limiteMs);
  });
  return chrome.tabs.get(tabId);
}

// IMPORTANTE: funções passadas a executeScript precisam ser autocontidas.
function coletarDocumentoCompleto() {
  const roots = [document];
  const visitados = new Set();
  for (let i = 0; i < roots.length; i++) {
    const root = roots[i];
    for (const el of root.querySelectorAll?.("*") || []) {
      if (el.shadowRoot && !visitados.has(el.shadowRoot)) {
        visitados.add(el.shadowRoot);
        roots.push(el.shadowRoot);
      }
    }
  }

  const pedacos = [];
  const principal = document.body?.innerText || document.body?.textContent || "";
  if (principal) pedacos.push(principal);
  for (const root of roots.slice(1)) {
    const t = root.textContent || "";
    if (t.trim()) pedacos.push(t);
  }
  const texto = pedacos.join("\n").replace(/\n{4,}/g, "\n\n\n").trim();

  const imagens = [];
  const vistos = new Set();
  for (const root of roots) {
    for (const img of root.querySelectorAll?.("img") || []) {
      if (imagens.length >= 20) break;
      const src = img.currentSrc || img.src || img.getAttribute("src") || "";
      if (!/^https?:/i.test(src) || vistos.has(src)) continue;
      if ((img.naturalWidth || 0) < 40 || (img.naturalHeight || 0) < 40) continue;
      vistos.add(src);
      imagens.push({ url: src, alt: (img.alt || "").trim().substring(0, 160) });
    }
  }

  const tituloBaixo = document.title.toLowerCase();
  const amostra = `${document.title}\n${texto.substring(0, 12000)}`.toLowerCase();
  let bloqueio = null;
  const desafioCloudflare = document.querySelector(
    '[id^="cf-chl"], .cf-challenge, iframe[src*="challenges.cloudflare.com"]');
  const widgetCaptcha = document.querySelector(
    '.g-recaptcha, .h-captcha, [data-sitekey], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"]');
  if (desafioCloudflare || /^(just a moment|attention required)/.test(tituloBaixo)
      || /checking your browser|verifying you are human/.test(amostra.substring(0, 3000))) {
    bloqueio = { tipo: "cloudflare", mensagem: "A página está pedindo uma verificação do Cloudflare. Conclua a verificação manualmente e me avise." };
  } else if (widgetCaptcha || /^(captcha|human verification)/.test(tituloBaixo)) {
    bloqueio = { tipo: "captcha", mensagem: "A página contém um CAPTCHA. Resolva-o manualmente e me avise para eu continuar." };
  } else if (/^(access denied|acesso negado|forbidden|request blocked)/.test(tituloBaixo)) {
    bloqueio = { tipo: "acesso_negado", mensagem: "O site negou o acesso. Não vou tentar contornar a proteção; abra ou autentique a página manualmente." };
  }
  const temSenha = roots.some(root => root.querySelector?.('input[type="password"]'));
  const pareceLogin = temSenha || /\b(sign in|log in|entrar|fazer login)\b/.test(amostra.substring(0, 8000));

  return {
    texto: texto.substring(0, 500000),
    imagens,
    url: location.href,
    titulo: document.title,
    bloqueio,
    parece_login: pareceLogin,
    shadow_roots: roots.length - 1,
  };
}

function coletarMidiasDocumento() {
  const roots = [document];
  for (let i = 0; i < roots.length; i++) {
    for (const el of roots[i].querySelectorAll?.("*") || []) {
      if (el.shadowRoot && !roots.includes(el.shadowRoot)) roots.push(el.shadowRoot);
    }
  }
  const itens = [];
  const vistos = new Set();
  const abs = valor => {
    if (!valor) return "";
    try { return new URL(valor, location.href).href; } catch (_) { return String(valor); }
  };
  const adicionar = item => {
    const url = abs(item.url);
    if (!url || vistos.has(url)) return;
    if (!/^(https?:|blob:)/i.test(url)) return;
    vistos.add(url);
    itens.push({
      titulo: (item.titulo || document.title || "Mídia sem título").trim().substring(0, 220),
      url,
      tipo: item.tipo || "video",
      origem: item.origem || "pagina",
      poster: abs(item.poster || ""),
      duracao: Number.isFinite(item.duracao) ? Math.round(item.duracao) : null,
      largura: item.largura || null,
      altura: item.altura || null,
      ativo: !!item.ativo,
      blob: url.startsWith("blob:"),
      drm: !!item.drm,
    });
  };

  let elementosMidia = 0;
  let temDrm = false;
  for (const root of roots) {
    for (const media of root.querySelectorAll?.("video, audio") || []) {
      elementosMidia++;
      const tipo = media.tagName.toLowerCase();
      const titulo = media.getAttribute("title") || media.getAttribute("aria-label")
        || media.closest?.("figure")?.querySelector?.("figcaption")?.innerText || document.title;
      const drm = !!(media.mediaKeys || media.webkitKeys);
      temDrm ||= drm;
      const base = {
        titulo, tipo, origem: "elemento", poster: media.poster || "",
        duracao: media.duration, largura: media.videoWidth, altura: media.videoHeight,
        ativo: !media.paused && !media.ended, drm,
      };
      adicionar({ ...base, url: media.currentSrc || media.src });
      for (const source of media.querySelectorAll("source[src]")) {
        adicionar({ ...base, url: source.src, origem: "source", tipo: source.type || tipo });
      }
    }

    const metas = [
      ["meta[property='og:video'],meta[property='og:video:url'],meta[property='og:video:secure_url']", "video"],
      ["meta[property='og:audio'],meta[property='og:audio:url'],meta[property='og:audio:secure_url']", "audio"],
      ["meta[name='twitter:player:stream']", "video"],
    ];
    for (const [seletor, tipo] of metas) {
      for (const meta of root.querySelectorAll?.(seletor) || []) {
        adicionar({ url: meta.content, tipo, origem: "metadados", titulo: document.title });
      }
    }
  }

  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const json = JSON.parse(script.textContent || "null");
      const fila = Array.isArray(json) ? [...json] : [json];
      while (fila.length) {
        const no = fila.shift();
        if (!no || typeof no !== "object") continue;
        if (Array.isArray(no)) { fila.push(...no); continue; }
        if (no.contentUrl || no.embedUrl) {
          adicionar({
            url: no.contentUrl || no.embedUrl,
            titulo: no.name || no.headline || document.title,
            tipo: String(no["@type"] || "").toLowerCase().includes("audio") ? "audio" : "video",
            origem: "json-ld",
            poster: Array.isArray(no.thumbnailUrl) ? no.thumbnailUrl[0] : no.thumbnailUrl,
          });
        }
        for (const valor of Object.values(no)) {
          if (valor && typeof valor === "object") fila.push(valor);
        }
      }
    } catch (_) { /* JSON-LD quebrado do próprio site */ }
  }

  for (const frame of document.querySelectorAll("iframe[src], embed[src]")) {
    const src = frame.src || frame.getAttribute("src") || "";
    if (/youtube|youtu\.be|vimeo|twitch|dailymotion|player|video/i.test(src)) {
      adicionar({
        url: src,
        titulo: frame.title || frame.getAttribute("aria-label") || document.title,
        tipo: "video",
        origem: "embed",
      });
    }
  }

  let linksDeVideo = 0;
  for (const link of document.querySelectorAll("a[href]")) {
    if (linksDeVideo >= 30) break;
    const href = link.href || "";
    const contexto = `${href} ${link.getAttribute("aria-label") || ""} ${link.className || ""}`;
    if (!/(youtube\.com\/watch|youtu\.be\/|vimeo\.com\/\d|tiktok\.com\/.+\/video\/|\/videos?\/|watch\?v=)/i.test(contexto)) continue;
    const ret = link.getBoundingClientRect();
    if (!ret.width && !ret.height) continue;
    const titulo = (link.getAttribute("title") || link.getAttribute("aria-label") || link.innerText || "").trim();
    adicionar({ url: href, titulo: titulo || document.title, tipo: "pagina", origem: "link-video" });
    linksDeVideo++;
  }

  for (const recurso of performance.getEntriesByType?.("resource") || []) {
    const url = recurso.name || "";
    if (/\.(m3u8|mpd|mp4|webm|m4a|mp3|aac|ogg|opus)(?:[?#]|$)/i.test(url)) {
      adicionar({ url, tipo: "stream", origem: "performance", titulo: document.title });
    }
  }

  // O sniffer MAIN-world começa em document_start e enxerga fetch/XHR antes de
  // bibliotecas como hls.js transformarem o stream HTTP em um blob: temporário.
  try {
    const observadas = JSON.parse(document.querySelector('meta[name="emily-media-observed"]')?.content || "[]");
    for (const recurso of Array.isArray(observadas) ? observadas : []) {
      adicionar({
        url: recurso.url,
        tipo: /audio/i.test(recurso.content_type || "") ? "audio" : "stream",
        origem: "sniffer",
        titulo: document.title,
        content_type: recurso.content_type || "",
      });
    }
  } catch (_) { /* snapshot parcial durante uma atualização do player */ }

  const plataforma = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|tiktok\.com|instagram\.com|facebook\.com|x\.com|twitter\.com)$/i.test(location.hostname);
  const rotaDeMidia = /youtu\.be\/[^/?#]+|youtube\.com\/(watch|shorts|live)\b|vimeo\.com\/(?:video\/)?\d+|tiktok\.com\/.+\/video\/|twitch\.tv\/(videos\/\d+|[^/?#]+$)|instagram\.com\/(reel|p)\/|(?:x|twitter)\.com\/.+\/status\//i.test(location.href);
  if (elementosMidia || (plataforma && rotaDeMidia)) {
    // A URL da página é normalmente a melhor entrada para o yt-dlp: mantém
    // metadados e deixa o extrator escolher os fluxos corretos.
    adicionar({
      url: location.href, titulo: document.title, tipo: "pagina",
      origem: "pagina", ativo: Array.from(document.querySelectorAll("video,audio")).some(m => !m.paused && !m.ended),
      drm: temDrm,
    });
  }

  return {
    url: location.href,
    titulo: document.title,
    navegador: (navigator.userAgentData?.brands || []).map(b => b.brand).join(", ") || navigator.userAgent,
    itens: itens.slice(0, 80),
    elementos: elementosMidia,
    drm_detectado: temDrm,
  };
}

async function executarTodosFrames(tabId, func, args = []) {
  try {
    return await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      func,
      args,
    });
  } catch (erroTodos) {
    console.warn("[Emily] Falha em todos os frames; tentando frame principal:", erroTodos.message);
    return chrome.scripting.executeScript({ target: { tabId }, func, args });
  }
}

async function primeiroFrameComSeletor(tabId, seletor) {
  const buscas = await executarTodosFrames(
    tabId,
    sel => {
      const roots = [document];
      for (let i = 0; i < roots.length; i++) {
        for (const no of roots[i].querySelectorAll?.("*") || []) {
          if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
        }
      }
      return roots.some(root => { try { return !!root.querySelector(sel); } catch (_) { return false; } });
    },
    [seletor]
  );
  return buscas.find(r => r.frameId === 0 && r.result)?.frameId
    ?? buscas.find(r => r.result)?.frameId
    ?? null;
}

async function descobrirMidiasAba(tab) {
  if (paginaRestrita(tab)) throw new Error(mensagemPaginaRestrita(tab));
  await aguardarAba(tab.id, 5000);
  const resultados = await executarTodosFrames(tab.id, coletarMidiasDocumento);
  const itens = [];
  const vistos = new Set();
  const adicionar = item => {
    const url = item?.url || "";
    if (!url || vistos.has(url)) return;
    vistos.add(url);
    itens.push({ ...item, frame_id: item.frame_id ?? 0 });
  };
  let drm = false;
  for (const r of resultados || []) {
    const dados = r.result || {};
    drm ||= !!dados.drm_detectado;
    for (const item of dados.itens || []) adicionar({
      ...item,
      frame_id: r.frameId,
      referer: item.referer || dados.url || "",
    });
  }
  const requisicoesRede = requisicoesMidiaPorAba.get(tab.id) || [];
  const requisicoesClaras = requisicoesRede.filter(req =>
    /\.(m3u8|mpd|mp4|m4v|webm|mov|mkv|mp3|m4a|aac|ogg|oga|opus|wav|flac)(?:[?#]|$)/i.test(req.url)
    || /(mpegurl|dash\+xml)/i.test(req.content_type || ""));
  // Fragmentos sem extensão podem ser milhares; se não houver manifesto ou
  // arquivo reconhecível, as cinco requisições mais recentes bastam como fallback.
  const redeParaCatalogo = requisicoesClaras.length ? requisicoesClaras : requisicoesRede.slice(0, 5);
  for (const req of redeParaCatalogo) {
    adicionar({
      titulo: tab.title || "Mídia detectada na rede",
      url: req.url,
      tipo: /audio/i.test(req.content_type) ? "audio" : (/m3u8|mpegurl|mpd|dash/i.test(req.url + req.content_type) ? "stream" : "video"),
      origem: "rede",
      content_type: req.content_type,
      ativo: true,
      blob: false,
      drm: false,
      frame_id: req.frame_id,
      referer: req.referer || req.initiator || "",
    });
  }
  const temFonteAtual = itens.some(item => ["pagina", "elemento", "source", "embed", "metadados", "json-ld"].includes(item.origem));
  if (temFonteAtual) {
    // Recomendações e cards são úteis numa página de listagem, mas numa página
    // com player real apenas poluem a escolha com vídeos que não estão ativos.
    for (let i = itens.length - 1; i >= 0; i--) {
      if (itens[i].origem === "link-video") {
        vistos.delete(itens[i].url);
        itens.splice(i, 1);
      }
    }
  }
  const plataformaComExtrator = /(^|\.)(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|tiktok\.com|instagram\.com|facebook\.com|x\.com|twitter\.com)$/i.test(
    (() => { try { return new URL(tab.url || "").hostname; } catch (_) { return ""; } })()
  );
  if (plataformaComExtrator && itens.some(item => item.origem === "pagina")) {
    for (let i = itens.length - 1; i >= 0; i--) {
      if (itens[i].origem !== "pagina") itens.splice(i, 1);
    }
  } else if (itens.some(item => item.origem === "pagina")) {
    // blob: não sobrevive fora da aba. A página ou uma fonte HTTP observada é
    // uma entrada muito mais confiável para o resolvedor local.
    for (let i = itens.length - 1; i >= 0; i--) {
      if (itens[i].blob) itens.splice(i, 1);
    }
    const fontesIndividuais = itens.filter(item =>
      ["elemento", "source", "embed", "metadados", "json-ld"].includes(item.origem)
      && /^https?:/i.test(item.url || ""));
    if (fontesIndividuais.length > 1) {
      for (let i = itens.length - 1; i >= 0; i--) {
        if (itens[i].origem === "pagina") itens.splice(i, 1);
      }
    }
  }
  // Página primeiro, depois o que está tocando, depois URLs diretas.
  itens.sort((a, b) => Number(b.origem === "pagina") - Number(a.origem === "pagina")
    || Number(b.ativo) - Number(a.ativo)
    || Number(a.blob) - Number(b.blob));
  const navegador = resultados.map(r => r.result?.navegador).find(Boolean) || "";
  return { url: tab.url || "", titulo: tab.title || "", navegador, itens: itens.slice(0, 80), drm_detectado: drm };
}

async function diagnosticoPopup() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0] || null;
  let midias = 0;
  let restrita = false;
  let erro = "";
  if (tab) {
    restrita = paginaRestrita(tab);
    if (!restrita) {
      try { midias = (await descobrirMidiasAba(tab)).itens.length; }
      catch (e) { erro = e.message || String(e); }
    }
  }
  return {
    conectado,
    versao: EXTENSION_VERSION,
    aba: tab ? { id: tab.id, titulo: tab.title || "", url: tab.url || "", restrita } : null,
    midias,
    erro,
  };
}

chrome.runtime.onMessage.addListener((mensagem, _sender, sendResponse) => {
  if (mensagem?.tipo === "POPUP_DIAGNOSTICO" || mensagem?.tipo === "POPUP_ATUALIZAR") {
    diagnosticoPopup().then(sendResponse).catch(e => sendResponse({ erro: e.message || String(e) }));
    return true;
  }
  if (mensagem?.tipo === "POPUP_ABRIR_DOWNLOADS") {
    chrome.tabs.create({ url: "chrome://downloads/", active: true })
      .then(() => sendResponse({ ok: true }))
      .catch(e => sendResponse({ erro: e.message || String(e) }));
    return true;
  }
  if (mensagem?.tipo === "POPUP_CONFIG_OBTER") {
    carregarConfigPonte().then(sendResponse).catch(e => sendResponse({ erro: e.message || String(e) }));
    return true;
  }
  if (mensagem?.tipo === "POPUP_CONFIG_SALVAR") {
    salvarConfigPonte(mensagem.url, mensagem.token)
      .then(() => sendResponse({ ok: true, url: wsUrlAtual }))
      .catch(e => sendResponse({ erro: e.message || String(e) }));
    return true;
  }
});

// ─── Executor de comandos ─────────────────────────────────────────────────────

async function executarComando(comando) {
  const acao = comando.acao;
  const requestId = comando.request_id || null;  // ecoa de volta se vier

  // Wrapper que injeta request_id automaticamente em todas as respostas
  const responder = (dados) => {
    const payload = requestId ? { ...dados, request_id: requestId } : dados;
    enviarParaEmily(payload);
  };

  try {
    switch (acao) {

      // ── Abre uma URL ──
      case "abrir_url": {
        const url = comando.url || "";
        if (!url) { responder({ tipo: "erro", acao, mensagem: "URL não informada" }); return; }
        if (!/^https?:\/\//i.test(url)) {
          responder({ tipo: "erro", acao, mensagem: "Só é permitido navegar para URL HTTP/HTTPS" });
          return;
        }
        if (comando.nova_aba) {
          await chrome.tabs.create({ url, active: comando.ativa !== false });
          responder({ tipo: "ok", acao, url, nova_aba: true });
          break;
        }
        const tabs = await abaAlvo(comando);
        if (tabs.length > 0) {
          await chrome.tabs.update(tabs[0].id, { url });
        } else {
          await chrome.tabs.create({ url });
        }
        responder({ tipo: "ok", acao, url });
        break;
      }

      // ── Procura e abre diretamente o primeiro vídeo real do YouTube ──
      case "abrir_youtube": {
        const busca = String(comando.busca || "").trim();
        if (!busca) { responder({ tipo: "erro", acao, mensagem: "Busca do YouTube não informada" }); return; }
        const urlBusca = `https://www.youtube.com/results?search_query=${encodeURIComponent(busca)}`;
        let tab;
        if (comando.nova_aba) {
          tab = await chrome.tabs.create({ url: urlBusca, active: comando.ativa !== false });
        } else {
          const tabs = await abaAlvo(comando);
          tab = tabs.length > 0
            ? await chrome.tabs.update(tabs[0].id, { url: urlBusca, active: comando.ativa !== false })
            : await chrome.tabs.create({ url: urlBusca, active: comando.ativa !== false });
        }
        tab = await aguardarAba(tab.id, 10000);
        let resultado = null;
        try {
          const executados = await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: () => {
              const seletores = [
                'ytd-video-renderer a#video-title[href*="/watch?v="]',
                'ytd-grid-video-renderer a#video-title[href*="/watch?v="]',
                'a#video-title-link[href*="/watch?v="]',
                'a[href*="/watch?v="]',
              ];
              for (const seletor of seletores) {
                const links = Array.from(document.querySelectorAll(seletor));
                const alvo = links.find(a => {
                  const href = a.href || a.getAttribute("href") || "";
                  return /youtube\.com\/watch\?v=[A-Za-z0-9_-]{6,}/i.test(href)
                    && !a.closest("ytd-promoted-video-renderer, ytd-display-ad-renderer");
                });
                if (alvo) {
                  return {
                    url: alvo.href,
                    titulo: (alvo.getAttribute("title") || alvo.textContent || "").trim().substring(0, 200),
                  };
                }
              }
              return null;
            },
          });
          resultado = executados[0]?.result || null;
        } catch (e) {
          console.warn("[Emily] Não consegui resolver vídeo direto do YouTube:", e);
        }
        if (resultado?.url) {
          await chrome.tabs.update(tab.id, { url: resultado.url, active: comando.ativa !== false });
          responder({
            tipo: "ok", acao, url: resultado.url, titulo: resultado.titulo || busca,
            aba_id: tab.id, video_encontrado: true,
          });
        } else {
          responder({
            tipo: "ok", acao, url: urlBusca, titulo: busca, aba_id: tab.id,
            video_encontrado: false, mensagem: "Busca aberta; nenhum vídeo direto foi identificado",
          });
        }
        break;
      }

      // ── Consulta o histórico da conta do YouTube; usa histórico local como fallback ──
      case "historico_youtube": {
        const busca = String(comando.busca || "").trim().toLocaleLowerCase("pt-BR");
        const limite = Math.max(1, Math.min(Number(comando.limite) || 10, 20));
        const videos = [];
        const vistos = new Set();
        let origem = "conta_youtube";
        let pareceLogin = false;

        // A janela de bastidor usa o mesmo perfil/login do navegador, mas não
        // altera nem rouba a aba que o Vitor está usando.
        try {
          const tab = await abaBastidor();
          if (tab?.id) {
            await chrome.tabs.update(tab.id, { url: "https://www.youtube.com/feed/history", active: false });
            await aguardarAba(tab.id, 10000);
            const executados = await chrome.scripting.executeScript({
              target: { tabId: tab.id },
              func: (busca, limite) => {
                const normalizar = texto => String(texto || "")
                  .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                  .toLocaleLowerCase("pt-BR");
                const vistos = new Set();
                const videos = [];
                const links = Array.from(document.querySelectorAll(
                  'ytd-video-renderer a#video-title[href*="/watch?v="], '
                  + 'ytd-rich-item-renderer a#video-title-link[href*="/watch?v="], '
                  + 'a#video-title[href*="/watch?v="]'
                ));
                for (const link of links) {
                  let url;
                  try { url = new URL(link.href || link.getAttribute("href"), location.origin); }
                  catch (_) { continue; }
                  const videoId = url.searchParams.get("v");
                  if (!videoId || !/^[A-Za-z0-9_-]{6,}$/.test(videoId)) continue;
                  const canonica = `https://www.youtube.com/watch?v=${videoId}`;
                  if (vistos.has(canonica)) continue;
                  const titulo = (link.getAttribute("title") || link.textContent || "Vídeo do YouTube")
                    .trim().substring(0, 200);
                  if (busca && !normalizar(`${titulo} ${canonica}`).includes(normalizar(busca))) continue;
                  vistos.add(canonica);
                  videos.push({ titulo, url: canonica });
                  if (videos.length >= limite) break;
                }
                const corpo = normalizar(document.body?.innerText || "").substring(0, 12000);
                const pareceLogin = /fazer login|sign in|acessar sua conta/.test(corpo);
                return { videos, parece_login: pareceLogin };
              },
              args: [busca, limite],
            });
            const conta = executados[0]?.result || {};
            pareceLogin = !!conta.parece_login;
            for (const video of conta.videos || []) {
              if (!video?.url || vistos.has(video.url)) continue;
              vistos.add(video.url);
              videos.push({ ...video, origem: "conta_youtube" });
              if (videos.length >= limite) break;
            }
          }
        } catch (e) {
          console.warn("[Emily] Histórico da conta do YouTube indisponível; usando histórico local:", e);
        }

        if (videos.length === 0) {
          origem = "historico_local";
          const inicio = Date.now() - 180 * 24 * 60 * 60 * 1000;
          const itens = await chrome.history.search({ text: busca, startTime: inicio, maxResults: 500 });
          for (const item of itens) {
            let url;
            try { url = new URL(item.url || ""); } catch (_) { continue; }
            const host = url.hostname.toLowerCase().replace(/^www\./, "");
            const videoId = host === "youtu.be"
              ? url.pathname.split("/").filter(Boolean)[0]
              : (host === "youtube.com" || host === "music.youtube.com") && url.pathname === "/watch"
                ? url.searchParams.get("v")
                : null;
            if (!videoId || !/^[A-Za-z0-9_-]{6,}$/.test(videoId)) continue;
            const canonica = `https://www.youtube.com/watch?v=${videoId}`;
            if (vistos.has(canonica)) continue;
            const titulo = String(item.title || "Vídeo do YouTube").replace(/\s+-\s+YouTube\s*$/i, "").trim();
            const alvoBusca = `${titulo} ${canonica}`.toLocaleLowerCase("pt-BR");
            if (busca && !alvoBusca.includes(busca)) continue;
            vistos.add(canonica);
            videos.push({
              titulo: titulo.substring(0, 200),
              url: canonica,
              ultima_visita_ms: Number(item.lastVisitTime || 0),
              visitas: Number(item.visitCount || 0),
              origem: "historico_local",
            });
            if (videos.length >= limite) break;
          }
        }
        responder({ tipo: "ok", acao, videos, quantidade: videos.length, origem, parece_login: pareceLogin });
        break;
      }

      // ── Fecha a aba atual ──
      case "fechar_aba": {
        const tabs = await abaAlvo(comando);
        if (tabs.length > 0) {
          await chrome.tabs.remove(tabs[0].id);
          responder({ tipo: "ok", acao, aba_id: tabs[0].id });
        }
        break;
      }

      // ── Fecha todas as outras abas preservando explicitamente a alvo ──
      case "fechar_outras_abas": {
        let preservar = null;
        if (typeof comando.tab_id === "number") {
          preservar = await chrome.tabs.get(comando.tab_id);
        } else {
          const ativas = await chrome.tabs.query({ active: true, currentWindow: true });
          preservar = ativas[0] || null;
        }
        if (!preservar?.id) {
          responder({ tipo: "erro", acao, mensagem: "Nenhuma aba alvo para preservar" });
          return;
        }
        const todas = await chrome.tabs.query({});
        const remover = todas.filter(t => t.id !== preservar.id).map(t => t.id);
        if (remover.length) await chrome.tabs.remove(remover);
        await chrome.tabs.update(preservar.id, { active: true });
        if (typeof preservar.windowId === "number") await chrome.windows.update(preservar.windowId, { focused: true });
        responder({ tipo: "ok", acao, preservada_id: preservar.id, fechadas: remover.length });
        break;
      }

      // ── Lê o texto da página (via content script, com fallback por executeScript) ──
      case "ler_pagina": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) {
          responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" });
          return;
        }
        let tab = tabs[0];
        if (paginaRestrita(tab)) {
          responder({ tipo: "erro", acao, restrita: true, mensagem: mensagemPaginaRestrita(tab) });
          return;
        }
        tab = await aguardarAba(tab.id);
        const resultados = await executarTodosFrames(tab.id, coletarDocumentoCompleto);
        if (!resultados?.length) {
          responder({ tipo: "erro", acao, mensagem: "Não foi possível obter dados da página" });
          return;
        }
        const principal = resultados.find(r => r.frameId === 0)?.result || resultados[0].result || {};
        const textos = [];
        const imagens = [];
        const urlsImagens = new Set();
        let bloqueio = principal.bloqueio || null;
        let pareceLogin = !!principal.parece_login;
        for (const r of resultados) {
          const dadosFrame = r.result || {};
          if (dadosFrame.texto) {
            textos.push(r.frameId === 0 ? dadosFrame.texto : `\n[FRAME ${r.frameId}]\n${dadosFrame.texto}`);
          }
          for (const img of dadosFrame.imagens || []) {
            if (imagens.length >= 30 || urlsImagens.has(img.url)) continue;
            urlsImagens.add(img.url);
            imagens.push(img);
          }
          bloqueio ||= dadosFrame.bloqueio || null;
          pareceLogin ||= !!dadosFrame.parece_login;
        }

        responder({
          tipo: "ok",
          acao,
          texto: textos.join("\n").substring(0, 500000),
          imagens,
          url: principal.url || tab.url || "",
          titulo: principal.titulo || tab.title || "",
          bloqueio,
          parece_login: pareceLogin,
          frames_lidos: resultados.length,
        });
        break;
      }

      // ── Preenche um campo de input ──
      case "preencher_campo": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const seletor = comando.seletor || "input";
        const frameId = await primeiroFrameComSeletor(tabs[0].id, seletor);
        if (frameId === null) {
          responder({ tipo: "erro", acao, seletor, mensagem: "Campo não encontrado em nenhum frame ou shadow root aberto" });
          return;
        }
        const resultados = await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id, frameIds: [frameId] },
          func:
          (seletor, valor) => {
            const roots = [document];
            for (let i = 0; i < roots.length; i++) {
              for (const no of roots[i].querySelectorAll?.("*") || []) {
                if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
              }
            }
            const el = roots.map(r => { try { return r.querySelector(seletor); } catch (_) { return null; } }).find(Boolean);
            if (el) {
              el.focus();
              const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              const desc = Object.getOwnPropertyDescriptor(proto, "value");
              if (desc?.set) desc.set.call(el, valor); else el.value = valor;
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              return true;
            }
            return false;
          },
          args: [seletor, comando.valor || ""],
        });
        const frame = resultados.find(r => r.result === true);
        responder(frame
          ? { tipo: "ok", acao, seletor, frame_id: frame.frameId }
          : { tipo: "erro", acao, seletor, mensagem: "Campo não encontrado em nenhum frame ou shadow root aberto" });
        break;
      }

      // ── Clica em um elemento ──
      case "clicar_elemento": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const seletor = comando.seletor || "button";
        const frameId = await primeiroFrameComSeletor(tabs[0].id, seletor);
        if (frameId === null) {
          responder({ tipo: "erro", acao, seletor, mensagem: "Elemento não encontrado em nenhum frame ou shadow root aberto" });
          return;
        }
        const resultados = await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id, frameIds: [frameId] },
          func:
          (seletor) => {
            const roots = [document];
            for (let i = 0; i < roots.length; i++) {
              for (const no of roots[i].querySelectorAll?.("*") || []) {
                if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
              }
            }
            const el = roots.map(r => { try { return r.querySelector(seletor); } catch (_) { return null; } }).find(Boolean);
            if (el) { el.scrollIntoView({ block: "center" }); el.click(); return true; }
            return false;
          },
          args: [seletor],
        });
        const frame = resultados.find(r => r.result === true);
        responder(frame
          ? { tipo: "ok", acao, seletor, frame_id: frame.frameId }
          : { tipo: "erro", acao, seletor, mensagem: "Elemento não encontrado em nenhum frame ou shadow root aberto" });
        break;
      }

      // ── Rola a página ──
      case "scroll": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const quantidade = comando.quantidade || 300;
        const direcao = (comando.direcao || "baixo").toLowerCase();
        const scrollY = direcao === "cima" ? -quantidade : quantidade;
        await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: (y) => { window.scrollBy({ top: y, behavior: "smooth" }); },
          args: [scrollY]
        });
        responder({ tipo: "ok", acao, direcao, quantidade });
        break;
      }

      // ── Retorna a URL da aba ativa ──
      case "obter_url_atual": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        responder({ tipo: "ok", acao, aba_id: tabs[0].id, titulo: tabs[0].title || "", url: tabs[0].url || "" });
        break;
      }

      // ── Fallback limitado para mídia HTML quando nenhum MPRIS responde ──
      case "controlar_midia": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        if (paginaRestrita(tabs[0])) { responder({ tipo: "erro", acao, mensagem: mensagemPaginaRestrita(tabs[0]) }); return; }
        const controle = String(comando.controle || "").toLowerCase();
        const permitidos = new Set(["tocar", "pausar", "alternar", "proxima", "anterior", "parar"]);
        if (!permitidos.has(controle)) {
          responder({ tipo: "erro", acao, mensagem: "Controle de mídia inválido" });
          return;
        }
        const resultados = await executarTodosFrames(tabs[0].id, (controle) => {
          const midias = Array.from(document.querySelectorAll("video,audio"));
          const alvo = midias.find(m => !m.paused) || midias.find(m => m.readyState > 0) || midias[0];
          if (!alvo) return { ok: false, motivo: "nenhuma mídia HTML encontrada" };
          if (controle === "tocar") alvo.play();
          else if (controle === "pausar") alvo.pause();
          else if (controle === "alternar") alvo.paused ? alvo.play() : alvo.pause();
          else if (controle === "parar") { alvo.pause(); alvo.currentTime = 0; }
          else {
            const seletor = controle === "proxima"
              ? '[aria-label*="Next" i], [aria-label*="Próxim" i], .ytp-next-button'
              : '[aria-label*="Previous" i], [aria-label*="Anterior" i]';
            const botao = document.querySelector(seletor);
            if (!botao) return { ok: false, motivo: "controle anterior/próxima não encontrado" };
            botao.click();
          }
          return { ok: true, pausada: alvo.paused, tempo: alvo.currentTime, duracao: alvo.duration || 0 };
        }, [controle]);
        const sucesso = resultados.find(r => r.result?.ok);
        responder(sucesso
          ? { tipo: "ok", acao, controle, ...sucesso.result, frame_id: sucesso.frameId }
          : { tipo: "erro", acao, mensagem: resultados[0]?.result?.motivo || "não consegui controlar a mídia" });
        break;
      }

      // ── Inicia download de uma URL ──
      case "baixar_arquivo": {
        const url = comando.url || "";
        if (!/^https?:\/\//i.test(url)) {
          responder({ tipo: "erro", acao, mensagem: "Download direto aceita apenas URL http/https. URLs blob: devem ser resolvidas pela página/plataforma." });
          return;
        }
        const downloadId = await chrome.downloads.download({ url, saveAs: !!comando.salvar_como });
        await downloadsCarregados;
        const iniciadoEm = Date.now();
        downloadsDaEmily.set(downloadId, {
          url, iniciadoEm, evento_id: `ext-${downloadId}-${iniciadoEm}`,
        });
        await persistirDownloadsEmily();
        responder({ tipo: "ok", acao, url, download_id: downloadId });
        break;
      }

      // ── Executa JavaScript arbitrário ──
      case "executar_js": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        if (paginaRestrita(tabs[0])) { responder({ tipo: "erro", acao, mensagem: mensagemPaginaRestrita(tabs[0]) }); return; }
        const codigo = comando.codigo || "";
        const alvo = { tabId: tabs[0].id };
        if (typeof comando.frame_id === "number") alvo.frameIds = [comando.frame_id];
        const resultados = await chrome.scripting.executeScript({
          target: alvo,
          func: js => {
            // Aceita tanto expressão ("document.title") quanto bloco com
            // "return ...", que é o formato documentado para a ferramenta.
            const codigoRecebido = String(js || "").trim();
            if (!codigoRecebido) return null;
            try { return eval(codigoRecebido); }
            catch (erroExpressao) {
              if (/Illegal return statement|Unexpected token 'return'|return not in function/i.test(String(erroExpressao))) {
                return eval(`(function(){${codigoRecebido}\n})()`);
              }
              throw erroExpressao;
            }
          },
          args: [codigo],
        });
        const uteis = (resultados || []).filter(r => r.result !== undefined && r.result !== null);
        const principal = uteis.find(r => r.frameId === 0) || uteis[0] || resultados?.[0];
        responder({
          tipo: "ok", acao,
          resultado: principal?.result,
          frame_id: principal?.frameId,
          resultados_frames: uteis.map(r => ({ frame_id: r.frameId, resultado: r.result })).slice(0, 30),
        });
        break;
      }

      // ── Screenshot da aba como base64 ──
      case "screenshot_aba": {
        if (comando.bastidor) {
          responder({ tipo: "erro", acao, mensagem:
            "Não dá pra tirar print da janela de bastidor (ela está escondida). "
            + "Use ler_pagina_navegador, que lê o TEXTO da página e funciona no bastidor." });
          return;
        }
        const windowId = chrome.windows.WINDOW_ID_CURRENT;
        const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
        // Remove o prefixo "data:image/png;base64," e manda só o base64
        const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, "");
        responder({ tipo: "ok", acao, imagem: base64 });
        break;
      }

      // ── Lê TODOS os formulários e campos visíveis da página ──
      case "ler_formularios": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (comando.bastidor) { const __aba = await abaBastidor(); if (__aba) { tabs.length = 0; tabs.push(__aba); } }
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const resultados = await executarTodosFrames(tabs[0].id,
          () => {
            const roots = [document];
            for (let i = 0; i < roots.length; i++) {
              for (const no of roots[i].querySelectorAll?.("*") || []) {
                if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
              }
            }
            const seletorDe = (el) => {
              if (el.id) return "#" + CSS.escape(el.id);
              if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
              const caminho = [];
              let no = el;
              while (no && no !== document.body && no.tagName && caminho.length < 5) {
                let seg = no.tagName.toLowerCase();
                if (no.parentNode) {
                  const irmaos = Array.from(no.parentNode.children).filter(c => c.tagName === no.tagName);
                  if (irmaos.length > 1) seg += ":nth-of-type(" + (irmaos.indexOf(no) + 1) + ")";
                }
                caminho.unshift(seg);
                no = no.parentNode;
              }
              return caminho.join(" > ");
            };
            const etiquetaDe = (el) => {
              if (el.id) {
                const lbl = el.getRootNode().querySelector?.('label[for="' + CSS.escape(el.id) + '"]');
                if (lbl) return lbl.innerText.trim().substring(0, 120);
              }
              const wrap = el.closest("label");
              if (wrap) return wrap.innerText.trim().substring(0, 120);
              if (el.getAttribute("aria-label")) return el.getAttribute("aria-label");
              if (el.placeholder) return el.placeholder;
              const grp = el.closest("fieldset");
              if (grp && grp.querySelector("legend")) return grp.querySelector("legend").innerText.trim().substring(0, 120);
              const ant = el.parentElement ? el.parentElement.innerText : "";
              return (ant.trim().split("\n")[0] || "").substring(0, 120);
            };
            const visivel = (el) => !!(el.offsetParent || el.getClientRects().length);
            const descrever = (el) => {
              const tipo = el.tagName === "INPUT" ? (el.type || "text") : el.tagName.toLowerCase();
              const dados = {
                seletor: seletorDe(el),
                tag: el.tagName.toLowerCase(),
                tipo: tipo === "password" ? "password" : tipo,
                rotulo: etiquetaDe(el),
                nome: el.name || "",
                obrigatorio: !!el.required,
                valor_atual: tipo === "password" ? "" : (el.value || "").substring(0, 200),
              };
              if (tipo === "select") {
                dados.opcoes = Array.from(el.options).map(o => o.text.trim()).filter(Boolean).slice(0, 30);
              }
              if (tipo === "checkbox" || tipo === "radio") {
                dados.marcado = !!el.checked;
                if (el.name) dados.valor_opcao = el.value || "";
              }
              return dados;
            };
            const todosFormularios = roots.flatMap(root => Array.from(root.querySelectorAll?.("form") || []));
            const formularios = todosFormularios.map((f, i) => ({
              indice: i,
              nome: f.name || f.id || "",
              campos: Array.from(f.querySelectorAll("input, textarea, select"))
                .filter(el => el.type !== "hidden" && visivel(el))
                .map(descrever),
              botao_enviar: (() => {
                const b = f.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
                return b ? seletorDe(b) : "";
              })(),
            }));
            const soltos = roots.flatMap(root => Array.from(root.querySelectorAll?.(
              'input, textarea, select, [contenteditable="true"], [role="textbox"]') || []))
              .filter(el => el.type !== "hidden" && visivel(el) && !el.closest("form"))
              .map(descrever);
            return {
              url: window.location.href,
              titulo: document.title,
              formularios: formularios.filter(f => f.campos.length > 0),
              campos_soltos: soltos,
            };
          }
        );
        const principal = resultados?.find(r => r.frameId === 0)?.result || resultados?.[0]?.result || null;
        if (principal) {
          const formularios = [];
          const camposSoltos = [];
          for (const r of resultados || []) {
            const dadosFrame = r.result || {};
            for (const f of dadosFrame.formularios || []) {
              formularios.push({
                ...f,
                campos: (f.campos || []).map(c => ({ ...c, frame_id: r.frameId })),
                indice_local: f.indice,
                indice: formularios.length,
                frame_id: r.frameId,
              });
            }
            for (const c of dadosFrame.campos_soltos || []) camposSoltos.push({ ...c, frame_id: r.frameId });
          }
          responder({
            tipo: "ok", acao,
            url: principal.url || tabs[0].url || "",
            titulo: principal.titulo || tabs[0].title || "",
            formularios,
            campos_soltos: camposSoltos,
            frames_lidos: resultados.length,
          });
        }
        else responder({ tipo: "erro", acao, mensagem: "Não consegui ler os formulários da página" });
        break;
      }

      // ── Preenche uma LISTA de campos de uma vez ──
      case "preencher_formulario": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (comando.bastidor) { const __aba = await abaBastidor(); if (__aba) { tabs.length = 0; tabs.push(__aba); } }
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        let campos = [];
        try { campos = JSON.parse(comando.campos_json || "[]"); }
        catch (e) { responder({ tipo: "erro", acao, mensagem: "campos_json inválido: " + e.message }); return; }
        if (!Array.isArray(campos) || campos.length === 0) {
          responder({ tipo: "erro", acao, mensagem: "Nenhum campo recebido para preencher" });
          return;
        }
        const preencherNoFrame = (json) => {
            const campos = JSON.parse(json);
            const roots = [document];
            for (let i = 0; i < roots.length; i++) {
              for (const no of roots[i].querySelectorAll?.("*") || []) {
                if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
              }
            }
            const setValor = (el, valor) => {
              if (el.isContentEditable) {
                el.textContent = valor;
                el.dispatchEvent(new InputEvent("input", { bubbles: true }));
                return true;
              }
              if (el.tagName === "SELECT") {
                const alvo = (valor == null ? "" : String(valor)).trim().toLowerCase();
                const opts = Array.from(el.options);
                const opt = opts.find(o => o.value.toLowerCase() === alvo)
                         || opts.find(o => o.text.trim().toLowerCase() === alvo);
                if (!opt) return false;
                el.value = opt.value;
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
              }
              if (el.type === "checkbox") {
                el.checked = valor === true || valor === "on" || valor === "true" || valor === "sim" || valor === 1;
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
              }
              if (el.type === "radio") {
                const grupo = el.getRootNode().querySelectorAll('input[type="radio"][name="' + CSS.escape(el.name) + '"]');
                const alvo = Array.from(grupo).find(r => (r.value || "").toLowerCase() === String(valor || "").toLowerCase());
                if (!alvo) return false;
                alvo.checked = true;
                alvo.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
              }
              // React-safe: usa o setter nativo do protótipo
              const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              const desc = Object.getOwnPropertyDescriptor(proto, "value");
              if (desc && desc.set) desc.set.call(el, valor); else el.value = valor;
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              return true;
            };
            return campos.map(c => {
              const el = roots.map(root => {
                try { return root.querySelector(c.seletor || ""); } catch (_) { return null; }
              }).find(Boolean);
              if (!el) return { seletor: c.seletor, ok: false, motivo: "campo não encontrado" };
              try {
                return { seletor: c.seletor, ok: setValor(el, c.valor), tag: el.tagName.toLowerCase() };
              } catch (e) {
                return { seletor: c.seletor, ok: false, motivo: String(e) };
              }
            });
          };
        const preenchidos = [];
        for (const campo of campos) {
          const seletor = campo.seletor || "";
          let frameId = typeof campo.frame_id === "number" ? campo.frame_id : null;
          if (frameId === null) frameId = await primeiroFrameComSeletor(tabs[0].id, seletor);
          if (frameId === null) {
            preenchidos.push({ seletor, ok: false, motivo: "campo não encontrado" });
            continue;
          }
          try {
            const execucao = await chrome.scripting.executeScript({
              target: { tabId: tabs[0].id, frameIds: [frameId] },
              func: preencherNoFrame,
              args: [JSON.stringify([campo])],
            });
            preenchidos.push({
              ...(execucao?.[0]?.result?.[0] || { seletor, ok: false, motivo: "sem resultado" }),
              frame_id: frameId,
            });
          } catch (e) {
            preenchidos.push({ seletor, ok: false, motivo: String(e), frame_id: frameId });
          }
        }
        responder({ tipo: "ok", acao, resultados: preenchidos });
        break;
      }

      // ── Envia (submit) um formulário da página ──
      case "submeter_formulario": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (comando.bastidor) { const __aba = await abaBastidor(); if (__aba) { tabs.length = 0; tabs.push(__aba); } }
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const indice = (typeof comando.indice === "number") ? comando.indice : null;
        const executarSubmit = (indice) => {
            const roots = [document];
            for (let i = 0; i < roots.length; i++) {
              for (const no of roots[i].querySelectorAll?.("*") || []) {
                if (no.shadowRoot && !roots.includes(no.shadowRoot)) roots.push(no.shadowRoot);
              }
            }
            const forms = roots.flatMap(root => Array.from(root.querySelectorAll?.("form") || []));
            let form = null;
            if (indice !== null && indice !== undefined && forms[indice]) {
              form = forms[indice];
            } else {
              form = forms.find(f => f.offsetParent && f.querySelector('button[type="submit"], input[type="submit"]'));
            }
            if (!form) return { ok: false, motivo: "nenhum formulário encontrado" };
            const btn = form.querySelector('button[type="submit"], input[type="submit"]');
            if (btn) { btn.click(); return { ok: true, via: "botão de enviar" }; }
            if (typeof form.requestSubmit === "function") { form.requestSubmit(); return { ok: true, via: "requestSubmit" }; }
            return { ok: false, motivo: "formulário sem botão de envio" };
          };
        const resultados = typeof comando.frame_id === "number"
          ? await chrome.scripting.executeScript({
              target: { tabId: tabs[0].id, frameIds: [comando.frame_id] },
              func: executarSubmit,
              args: [indice],
            })
          : await executarTodosFrames(tabs[0].id, executarSubmit, [indice]);
        const sucesso = resultados.find(r => r.result?.ok);
        const r = sucesso?.result || resultados?.[0]?.result || { ok: false, motivo: "sem resultado" };
        responder({ tipo: r.ok ? "ok" : "erro", acao, ...r, frame_id: sucesso?.frameId });
        break;
      }

      // ── Abre uma NOVA aba ──
      case "nova_aba": {
        const url = comando.url || "about:blank";
        if (url !== "about:blank" && !/^https?:\/\//i.test(url)) {
          responder({ tipo: "erro", acao, mensagem: "Só é permitido abrir URL HTTP/HTTPS" });
          return;
        }
        if (comando.bastidor) {
          // No bastidor, a "nova aba" nasce DENTRO da janela escondida e
          // vira a aba de trabalho dali — a aba do Vitor continua intocada.
          const win = await janelaBastidor();
          const aba = await chrome.tabs.create({
            url,
            windowId: win.id,
            active: false,
          });
          bastidorTabId = aba.id;
          salvarBastidor();
          responder({ tipo: "ok", acao, url, aba_id: aba.id });
          break;
        }
        const aba = await chrome.tabs.create({
          url,
          active: comando.ativa !== false,
        });
        responder({ tipo: "ok", acao, url, aba_id: aba.id });
        break;
      }

      // ── Lista as abas abertas (só quando a Emily pedir explicitamente) ──
      case "listar_abas": {
        const abas = await chrome.tabs.query({});
        responder({
          tipo: "ok",
          acao,
          abas: abas.slice(0, 50).map(t => ({
            id: t.id,
            titulo: (t.title || "").substring(0, 120),
            url: (t.url || "").substring(0, 200),
            ativa: !!t.active,
            janela_id: t.windowId,
            fixada: !!t.pinned,
          })),
        });
        break;
      }

      // ── Extrai os links visíveis da página (pra navegar/baixar) ──
      case "extrair_links": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const resultados = await executarTodosFrames(tabs[0].id,
          (limite) => {
            const vistos = new Set();
            const links = [];
            for (const a of document.querySelectorAll("a[href]")) {
              const href = a.href || "";
              if (!href.startsWith("http") || vistos.has(href)) continue;
              if (!(a.offsetParent || a.getClientRects().length)) continue;
              vistos.add(href);
              const texto = (a.innerText || a.getAttribute("aria-label") || "").trim().substring(0, 120);
              const ehDownload = /\.(zip|rar|7z|pdf|exe|msi|deb|rpm|dmg|tar|gz|iso|apk|mp3|mp4)(\?|$)/i.test(href);
              links.push({ texto, href, download: ehDownload });
              if (links.length >= limite) break;
            }
            return links;
          },
          [comando.limite || 100]
        );
        const links = [];
        const vistos = new Set();
        for (const frame of resultados || []) {
          for (const link of frame.result || []) {
            if (vistos.has(link.href)) continue;
            vistos.add(link.href);
            links.push({ ...link, frame_id: frame.frameId });
            if (links.length >= (comando.limite || 100)) break;
          }
        }
        responder({ tipo: "ok", acao, links });
        break;
      }

      // ── Descobre vídeo/áudio na aba e nos frames, sem tentar burlar DRM ──
      case "descobrir_midias": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const dados = await descobrirMidiasAba(tabs[0]);
        responder({ tipo: "ok", acao, ...dados });
        break;
      }

      // ── Estado compacto para o popup ──
      case "diagnostico": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const tab = tabs[0] || null;
        let totalMidias = 0;
        let restrita = false;
        let erro = "";
        if (tab) {
          restrita = paginaRestrita(tab);
          if (!restrita) {
            try { totalMidias = (await descobrirMidiasAba(tab)).itens.length; }
            catch (e) { erro = e.message || String(e); }
          }
        }
        responder({
          tipo: "ok", acao,
          conectado,
          versao: EXTENSION_VERSION,
          aba: tab ? { id: tab.id, titulo: tab.title || "", url: tab.url || "", restrita } : null,
          midias: totalMidias,
          erro,
        });
        break;
      }

      case "abrir_downloads": {
        await chrome.tabs.create({ url: "chrome://downloads/", active: true });
        responder({ tipo: "ok", acao });
        break;
      }

      // ── Histórico da aba (voltar / avançar / recarregar) ──
      case "navegar_historico": {
        const tabs = await abaAlvo(comando);
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const direcao = (comando.direcao || "voltar").toLowerCase();
        if (direcao === "voltar") await chrome.tabs.goBack(tabs[0].id);
        else if (direcao === "avancar") await chrome.tabs.goForward(tabs[0].id);
        else await chrome.tabs.reload(tabs[0].id);
        responder({ tipo: "ok", acao, direcao });
        break;
      }

      // ── Ping / keepalive da Emily ──
      case "ping": {
        enviarParaEmily({ tipo: "pong" });
        break;
      }

      default:
        console.warn("[Emily] Ação desconhecida:", acao);
        responder({ tipo: "erro", acao, mensagem: "Ação desconhecida: " + acao });
    }
  } catch (e) {
    console.error("[Emily] Erro ao executar ação '" + acao + "':", e);
    responder({ tipo: "erro", acao, mensagem: String(e) });
  }
}

// ─── Inicialização ────────────────────────────────────────────────────────────

conectar();

// Reconecta quando o service worker é ativado novamente pelo Chrome
chrome.runtime.onStartup.addListener(conectar);
chrome.runtime.onInstalled.addListener(() => {
  notificarStatus(false);
  conectar();
});
