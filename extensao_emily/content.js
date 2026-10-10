/**
 * Emily — content script leve, isolado da página.
 *
 * Mantém um snapshot atualizado em páginas SPA e em iframes. A coleta completa
 * continua no background via chrome.scripting, que não é bloqueado pela CSP
 * normal dos sites e possui fallback seguro para o frame principal.
 */
(() => {
  "use strict";

  let snapshot = null;
  let timer = null;
  let sujo = true;

  function rootsAbertos() {
    const roots = [document];
    for (let i = 0; i < roots.length; i++) {
      for (const el of roots[i].querySelectorAll?.("*") || []) {
        if (el.shadowRoot && !roots.includes(el.shadowRoot)) roots.push(el.shadowRoot);
      }
    }
    return roots;
  }

  function atualizarSnapshot() {
    const roots = rootsAbertos();
    const textos = [];
    const midias = [];
    for (const root of roots) {
      const texto = root === document
        ? (document.body?.innerText || document.body?.textContent || "")
        : (root.textContent || "");
      if (texto.trim()) textos.push(texto);
      for (const media of root.querySelectorAll?.("video,audio") || []) {
        midias.push({
          tipo: media.tagName.toLowerCase(),
          url: media.currentSrc || media.src || "",
          ativo: !media.paused && !media.ended,
          duracao: Number.isFinite(media.duration) ? Math.round(media.duration) : null,
          drm: !!(media.mediaKeys || media.webkitKeys),
        });
      }
    }
    snapshot = {
      texto: textos.join("\n").trim().substring(0, 500000),
      url: location.href,
      titulo: document.title,
      midias,
      shadow_roots: roots.length - 1,
      atualizado_em: Date.now(),
    };
    sujo = false;
  }

  function agendar() {
    // Páginas como YouTube e feeds alteram o DOM sem parar. Revarrer o documento
    // inteiro a cada mutação consumia CPU sem benefício: o snapshot é atualizado
    // sob demanda, e eventos de mídia/rota recebem um debounce separado.
    sujo = true;
  }

  function agendarEventoImportante() {
    sujo = true;
    clearTimeout(timer);
    timer = setTimeout(atualizarSnapshot, 250);
  }

  atualizarSnapshot();
  const observador = new MutationObserver(agendar);
  if (document.documentElement) {
    observador.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "href", "title", "aria-label"],
    });
  }
  window.addEventListener("popstate", agendarEventoImportante);
  window.addEventListener("hashchange", agendarEventoImportante);
  document.addEventListener("play", agendarEventoImportante, true);
  document.addEventListener("loadedmetadata", agendarEventoImportante, true);

  chrome.runtime.onMessage.addListener((mensagem, _sender, sendResponse) => {
    if (mensagem?.acao === "snapshot_pagina" || mensagem?.acao === "ler_pagina") {
      if (sujo || !snapshot || snapshot.url !== location.href) atualizarSnapshot();
      sendResponse(snapshot);
      return true;
    }
    sendResponse({ erro: "Ação não reconhecida: " + String(mensagem?.acao || "") });
    return true;
  });
})();
