// sw.js — Service Worker da Emily Remote PWA
// Permite que o app seja instalável e carregue mais rápido

const CACHE = "emily-v1";
const ARQUIVOS = ["/", "/index.html", "/manifest.json"];

// Instala e guarda os arquivos em cache
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ARQUIVOS))
  );
  self.skipWaiting();
});

// Ativa e limpa caches antigos
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Requisições: tenta a rede primeiro, cai no cache se falhar
// (as chamadas /comando e /status sempre vão pra rede, nunca pro cache)
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);

  // Rotas da API: sempre vai pra rede, nunca intercepta
  if (url.pathname.startsWith("/comando") || url.pathname.startsWith("/status")) {
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then((r) => {
        // Atualiza o cache com a versão mais recente
        const clone = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, clone));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
