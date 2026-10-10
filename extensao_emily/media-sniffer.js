/**
 * Observador passivo de mídia no mundo MAIN da página.
 *
 * Players baseados em MediaSource trocam a URL HTTP real por um blob:. Este
 * script roda antes do player, observa fetch/XHR e publica somente URLs candidatas
 * no DOM. Ele não lê cookies, não altera requisições e não interfere no TLS/DRM.
 */
(() => {
  "use strict";

  const NOME_META = "emily-media-observed";
  const LIMITE = 120;
  const LIMITE_JSON = 2 * 1024 * 1024;
  const observadas = new Map();
  const URL_MIDIA = /\.(?:m3u8|mpd|mp4|m4v|webm|mov|mkv|mp3|m4a|aac|ogg|oga|opus|wav|flac)(?:[?#]|$)|(?:^|[/?#&_.=-])(?:manifest|master|playlist|stream|videoplayback)(?:[/?#&_.=-]|$)/i;
  const TIPO_MIDIA = /^(?:video|audio)\/|(?:mpegurl|dash\+xml)/i;

  function urlAbsoluta(valor) {
    try {
      const bruto = valor instanceof Request ? valor.url : String(valor || "");
      const url = new URL(bruto, location.href).href;
      return /^https?:/i.test(url) ? url : "";
    } catch (_) {
      return "";
    }
  }

  function publicar() {
    const raiz = document.documentElement;
    if (!raiz) return;
    let meta = document.querySelector(`meta[name="${NOME_META}"]`);
    if (!meta) {
      meta = document.createElement("meta");
      meta.name = NOME_META;
      meta.dataset.emilyBridge = "media-v1";
      (document.head || raiz).appendChild(meta);
    }
    meta.content = JSON.stringify(Array.from(observadas.values()).slice(-LIMITE));
  }

  function registrar(valor, contentType = "", origem = "pagina", forcar = false) {
    const url = urlAbsoluta(valor);
    const tipo = String(contentType || "").toLowerCase();
    if (!url || (!forcar && !URL_MIDIA.test(url) && !TIPO_MIDIA.test(tipo))) return;
    observadas.delete(url);
    observadas.set(url, {
      url,
      content_type: tipo.substring(0, 160),
      origem,
      visto_em: Date.now(),
    });
    while (observadas.size > LIMITE) observadas.delete(observadas.keys().next().value);
    publicar();
  }

  function procurarUrlsEmTexto(texto, origem) {
    if (!texto || texto.length > LIMITE_JSON) return;
    const normalizado = texto.replace(/\\u002f/gi, "/").replace(/\\\//g, "/");
    const candidatas = normalizado.match(/(?:https?:\/\/|\/)[^\s"'<>]{1,2000}/gi) || [];
    for (const candidata of candidatas) {
      const limpa = candidata.replace(/[),}\]]+$/, "");
      if (URL_MIDIA.test(limpa)) registrar(limpa, "", origem, true);
    }
  }

  const fetchOriginal = window.fetch;
  if (typeof fetchOriginal === "function") {
    window.fetch = function (...args) {
      const urlPedida = args[0];
      registrar(urlPedida, "", "fetch");
      const promessa = Reflect.apply(fetchOriginal, this, args);
      promessa.then(resposta => {
        const tipo = resposta.headers?.get?.("content-type") || "";
        registrar(resposta.url || urlPedida, tipo, "fetch-resposta");
        const tamanho = Number(resposta.headers?.get?.("content-length") || 0);
        if (/json|javascript|text\/plain/i.test(tipo) && (!tamanho || tamanho <= LIMITE_JSON)) {
          resposta.clone().text().then(texto => procurarUrlsEmTexto(texto, "fetch-json")).catch(() => {});
        }
      }).catch(() => {});
      return promessa;
    };
  }

  const xhrOpen = XMLHttpRequest.prototype.open;
  const xhrSend = XMLHttpRequest.prototype.send;
  const URL_XHR = Symbol("emilyUrlMidia");
  XMLHttpRequest.prototype.open = function (metodo, url, ...restante) {
    this[URL_XHR] = urlAbsoluta(url);
    registrar(url, "", "xhr");
    return Reflect.apply(xhrOpen, this, [metodo, url, ...restante]);
  };
  XMLHttpRequest.prototype.send = function (...args) {
    this.addEventListener("loadend", () => {
      let tipo = "";
      try { tipo = this.getResponseHeader("content-type") || ""; } catch (_) { /* CORS */ }
      registrar(this.responseURL || this[URL_XHR], tipo, "xhr-resposta");
      if (/json|javascript|text\/plain/i.test(tipo)) {
        try { procurarUrlsEmTexto(this.responseText, "xhr-json"); } catch (_) { /* resposta binária */ }
      }
    }, { once: true });
    return Reflect.apply(xhrSend, this, args);
  };

  try {
    const observarPerformance = lista => {
      for (const entrada of lista.getEntries()) registrar(entrada.name, "", "performance");
    };
    new PerformanceObserver(observarPerformance).observe({ type: "resource", buffered: true });
  } catch (_) { /* navegador sem PerformanceObserver buffered */ }

  publicar();
})();