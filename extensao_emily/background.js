/**
 * background.js — Service Worker da extensão Emily Browser Bridge
 * Conecta ao WebSocket local da Emily (ws://localhost:8765)
 * e executa ações no navegador conforme comandos recebidos.
 */

const WS_URL = "ws://localhost:8765";
const KEEPALIVE_INTERVAL_MS = 20000; // 20s — obrigatório no MV3
const RECONNECT_DELAY_MS = 3000;

let ws = null;
let keepaliveTimer = null;
let reconectando = false;
let conectado = false;

// ─── Conexão WebSocket ────────────────────────────────────────────────────────

function conectar() {
  if (reconectando) return;
  reconectando = true;

  try {
    ws = new WebSocket(WS_URL);
  } catch (e) {
    console.error("[Emily] Erro ao criar WebSocket:", e);
    reconectando = false;
    agendarReconexao();
    return;
  }

  ws.onopen = () => {
    console.log("[Emily] Conectado à Emily em", WS_URL);
    conectado = true;
    reconectando = false;
    notificarStatus(true);
    iniciarKeepalive();
    // Avisa a Emily que a extensão conectou
    enviarParaEmily({ tipo: "extensao_conectada", versao: "1.0" });
  };

  ws.onmessage = (event) => {
    try {
      const comando = JSON.parse(event.data);
      console.log("[Emily] Comando recebido:", comando);
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
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(dados));
  }
}

// ─── Notifica o popup sobre o status da conexão ──────────────────────────────

function notificarStatus(estaConectado) {
  chrome.storage.local.set({ emily_conectado: estaConectado });
}

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
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length > 0) {
          await chrome.tabs.update(tabs[0].id, { url });
        } else {
          await chrome.tabs.create({ url });
        }
        responder({ tipo: "ok", acao, url });
        break;
      }

      // ── Fecha a aba atual ──
      case "fechar_aba": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length > 0) {
          await chrome.tabs.remove(tabs[0].id);
          responder({ tipo: "ok", acao });
        }
        break;
      }

      // ── Lê o texto da página (via content script, com fallback por executeScript) ──
      case "ler_pagina": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length === 0) {
          responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" });
          return;
        }
        const tab = tabs[0];

        // Aguarda a página terminar de carregar antes de ler
        if (tab.status === "loading") {
          await new Promise((resolve) => {
            const listener = (tabId, changeInfo) => {
              if (tabId === tab.id && changeInfo.status === "complete") {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
              }
            };
            chrome.tabs.onUpdated.addListener(listener);
            // Timeout de segurança: resolve após 5s mesmo sem evento
            setTimeout(resolve, 5000);
          });
        }

        // Função que coleta texto, imagens, url e titulo
        const coletarDadosPagina = () => {
          const texto = document.body?.innerText || document.body?.textContent || "";
          const imagens = [];
          const imgs = document.querySelectorAll("img");
          let count = 0;
          for (const img of imgs) {
            if (count >= 10) break;
            const src = img.src || img.getAttribute("src") || "";
            const alt = img.alt || "";
            if (src && src.startsWith("http") && img.naturalWidth > 50 && img.naturalHeight > 50) {
              imagens.push({ url: src, alt: alt.substring(0, 100) });
              count++;
            }
          }
          return {
            texto: texto.trim().substring(0, 500000),
            imagens,
            url: window.location.href,
            titulo: document.title,
          };
        };

        let dados = null;

        // Tenta via content script primeiro (já injetado)
        try {
          dados = await chrome.tabs.sendMessage(tab.id, { acao: "ler_pagina" });
        } catch (errMsg) {
          console.warn("[Emily] sendMessage falhou, tentando executeScript:", errMsg.message);
        }

        // Fallback: injeta e executa direto via scripting API
        if (!dados || !dados.texto) {
          try {
            const resultados = await chrome.scripting.executeScript({
              target: { tabId: tab.id },
              func: coletarDadosPagina,
            });
            dados = resultados?.[0]?.result || null;
          } catch (errScript) {
            console.error("[Emily] executeScript também falhou:", errScript);
            responder({ tipo: "erro", acao, mensagem: "Não foi possível ler a página: " + errScript.message });
            return;
          }
        }

        if (!dados) {
          responder({ tipo: "erro", acao, mensagem: "Não foi possível obter dados da página" });
          return;
        }

        responder({
          tipo: "ok",
          acao,
          texto:   dados.texto   || "",
          imagens: dados.imagens || [],
          url:     dados.url     || tab.url || "",
          titulo:  dados.titulo  || tab.title || "",
        });
        break;
      }

      // ── Preenche um campo de input ──
      case "preencher_campo": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: (seletor, valor) => {
            const el = document.querySelector(seletor);
            if (el) {
              el.focus();
              el.value = valor;
              el.dispatchEvent(new Event("input", { bubbles: true }));
              el.dispatchEvent(new Event("change", { bubbles: true }));
              return true;
            }
            return false;
          },
          args: [comando.seletor || "input", comando.valor || ""]
        });
        responder({ tipo: "ok", acao, seletor: comando.seletor });
        break;
      }

      // ── Clica em um elemento ──
      case "clicar_elemento": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: (seletor) => {
            const el = document.querySelector(seletor);
            if (el) { el.click(); return true; }
            return false;
          },
          args: [comando.seletor || "button"]
        });
        responder({ tipo: "ok", acao, seletor: comando.seletor });
        break;
      }

      // ── Rola a página ──
      case "scroll": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
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
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        responder({ tipo: "ok", acao, url: tabs[0].url || "" });
        break;
      }

      // ── Inicia download de uma URL ──
      case "baixar_arquivo": {
        const url = comando.url || "";
        if (!url) { responder({ tipo: "erro", acao, mensagem: "URL não informada" }); return; }
        await chrome.downloads.download({ url });
        responder({ tipo: "ok", acao, url });
        break;
      }

      // ── Executa JavaScript arbitrário ──
      case "executar_js": {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tabs.length === 0) { responder({ tipo: "erro", acao, mensagem: "Nenhuma aba ativa" }); return; }
        const codigo = comando.codigo || "";
        const resultados = await chrome.scripting.executeScript({
          target: { tabId: tabs[0].id },
          func: (js) => { return eval(js); },
          args: [codigo]
        });
        responder({ tipo: "ok", acao, resultado: resultados?.[0]?.result });
        break;
      }

      // ── Screenshot da aba como base64 ──
      case "screenshot_aba": {
        const windowId = chrome.windows.WINDOW_ID_CURRENT;
        const dataUrl = await chrome.tabs.captureVisibleTab(windowId, { format: "png" });
        // Remove o prefixo "data:image/png;base64," e manda só o base64
        const base64 = dataUrl.replace(/^data:image\/\w+;base64,/, "");
        responder({ tipo: "ok", acao, imagem: base64 });
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
