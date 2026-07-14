/**
 * content.js — Content Script da extensão Emily Browser Bridge
 * Escuta mensagens do background.js e responde com dados da página atual.
 */

chrome.runtime.onMessage.addListener((mensagem, sender, sendResponse) => {
  const acao = mensagem?.acao;

  if (acao === "ler_pagina") {
    // Retorna o texto legível da página (sem tags HTML)
    const texto = document.body?.innerText || document.body?.textContent || "";

    // Captura URLs de imagens visíveis na página (máximo 10)
    const imagens = [];
    const imgs = document.querySelectorAll("img");
    let count = 0;
    for (const img of imgs) {
      if (count >= 10) break;
      const src = img.src || img.getAttribute("src") || "";
      const alt = img.alt || "";
      // Só inclui imagens com URL http/https (ignora data:, blob:, etc.)
      if (src && src.startsWith("http") && img.naturalWidth > 50 && img.naturalHeight > 50) {
        imagens.push({ url: src, alt: alt.substring(0, 100) });
        count++;
      }
    }

    sendResponse({
      texto: texto.trim().substring(0, 500000),  // limita a 500k chars
      imagens: imagens,
      url: window.location.href,
      titulo: document.title,
    });
    return true; // indica resposta assíncrona
  }

  if (acao === "obter_url") {
    sendResponse({ url: window.location.href, titulo: document.title });
    return true;
  }

  if (acao === "obter_html") {
    const html = document.documentElement?.outerHTML || "";
    sendResponse({ html: html.substring(0, 100000) }); // limita a 100k chars
    return true;
  }

  // Para qualquer outra ação não reconhecida
  sendResponse({ erro: "Ação não reconhecida: " + acao });
  return true;
});
