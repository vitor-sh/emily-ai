"""
navegador.py — Servidor WebSocket para controle do navegador via extensão Emily.

Porta: 8765
Protocolo: JSON bidirecional

Comandos suportados (enviados PARA a extensão):
  abrir_url        → abre uma URL (parâmetro: url)
  fechar_aba       → fecha a aba atual
  ler_pagina       → retorna o texto da página atual
  preencher_campo  → preenche um input (parâmetros: seletor, valor)
  clicar_elemento  → clica num elemento (parâmetro: seletor)
  scroll           → rola a página (parâmetros: direcao, quantidade)
  baixar_arquivo   → inicia download de uma URL (parâmetro: url)
  executar_js      → executa JS arbitrário (parâmetro: codigo)
  screenshot_aba   → recebe print da aba como base64

Dados recebidos DA extensão:
  Qualquer JSON enviado pela extensão (conteúdo de página, URL atual, resultado de ação, etc.)
"""

from __future__ import annotations

import asyncio
import json
import threading
import queue
from typing import Optional

# ─── Estado global ──────────────────────────────────────────────────────────
_loop: Optional[asyncio.AbstractEventLoop] = None
_clientes: set = set()
_lock_clientes = threading.Lock()

# Fila de comandos a serem enviados para a extensão
_fila_comandos: queue.Queue = queue.Queue()

# Última mensagem recebida da extensão (sem request_id — retrocompatibilidade)
_ultima_mensagem: Optional[dict] = None
_evento_resposta = threading.Event()

# Respostas indexadas por request_id (para chamadas aguardar_resposta=True)
_respostas_pendentes: dict = {}          # {request_id: threading.Event}
_resultados_por_id:   dict = {}          # {request_id: dict}
_lock_respostas = threading.Lock()
_contador_req = 0
_lock_contador = threading.Lock()


def _novo_request_id() -> str:
    global _contador_req
    with _lock_contador:
        _contador_req += 1
        return f"req_{_contador_req}"

# ─── Servidor WebSocket ──────────────────────────────────────────────────────

async def _handler(websocket):
    """Gerencia uma conexão da extensão."""
    global _ultima_mensagem

    with _lock_clientes:
        _clientes.add(websocket)

    print(f"[NAVEGADOR] Extensão conectada: {websocket.remote_address}")

    try:
        async def _enviar_pendentes():
            while True:
                await asyncio.sleep(0.05)
                try:
                    comando = _fila_comandos.get_nowait()
                    await websocket.send(json.dumps(comando, ensure_ascii=False))
                    print(f"[NAVEGADOR] Enviado: {comando}")
                except queue.Empty:
                    pass

        tarefa_envio = asyncio.ensure_future(_enviar_pendentes())

        async for mensagem_raw in websocket:
            try:
                dados = json.loads(mensagem_raw)
                _ultima_mensagem = dados

                # ── Roteamento por request_id (respostas específicas) ──
                rid = dados.get("request_id")
                if rid:
                    with _lock_respostas:
                        _resultados_por_id[rid] = dados
                        evento = _respostas_pendentes.get(rid)
                    if evento:
                        evento.set()
                    print(f"[NAVEGADOR] Resposta ID={rid}: {str(dados)[:150]}")
                else:
                    # Fallback: aciona o evento global (retrocompatibilidade)
                    _evento_resposta.set()
                    print(f"[NAVEGADOR] Recebido (sem ID): {str(dados)[:200]}")

            except json.JSONDecodeError:
                print(f"[NAVEGADOR] Mensagem inválida (não é JSON): {mensagem_raw[:100]}")

    except Exception as e:
        print(f"[NAVEGADOR] Conexão encerrada: {e}")
    finally:
        tarefa_envio.cancel()
        with _lock_clientes:
            _clientes.discard(websocket)
        print("[NAVEGADOR] Extensão desconectada.")


async def _iniciar_servidor_async():
    """Inicia o servidor WebSocket na porta 8765."""
    try:
        import websockets
        async with websockets.serve(_handler, "localhost", 8765):
            print("[NAVEGADOR] Servidor WebSocket rodando em ws://localhost:8765")
            await asyncio.Future()  # roda para sempre
    except Exception as e:
        print(f"[NAVEGADOR] Erro ao iniciar servidor WebSocket: {e}")


def _thread_servidor():
    """Roda o event loop assíncrono em uma thread daemon."""
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_iniciar_servidor_async())


def iniciar_servidor_websocket():
    """Inicia a thread daemon do servidor WebSocket. Chamado pelo main.py."""
    t = threading.Thread(target=_thread_servidor, daemon=True, name="EmillyNavegadorWS")
    t.start()
    print("[NAVEGADOR] Thread do servidor WebSocket iniciada.")


# ─── API pública para outros módulos ─────────────────────────────────────────

def enviar_comando_com_id(acao: str, timeout: float = 10.0, **kwargs) -> Optional[dict]:
    """
    Versão com request_id — garante que a resposta recebida é exatamente para ESTE comando,
    sem colisão com respostas de outros comandos em andamento.
    Usado pela pesquisa e por qualquer fluxo sequencial com múltiplas chamadas.
    """
    with _lock_clientes:
        if not _clientes:
            print(f"[NAVEGADOR] Nenhuma extensão conectada. Comando '{acao}' descartado.")
            return None

    rid = _novo_request_id()
    evento = threading.Event()

    with _lock_respostas:
        _respostas_pendentes[rid] = evento

    comando = {"acao": acao, "request_id": rid, **kwargs}
    _fila_comandos.put(comando)
    print(f"[NAVEGADOR] Comando com ID={rid}: {str(comando)[:120]}")

    chegou = evento.wait(timeout=timeout)

    with _lock_respostas:
        _respostas_pendentes.pop(rid, None)
        resultado = _resultados_por_id.pop(rid, None)

    if chegou and resultado:
        return resultado
    else:
        print(f"[NAVEGADOR] Timeout (ID={rid}) para '{acao}'.")
        return None


def enviar_comando(acao: str, aguardar_resposta: bool = False, timeout: float = 10.0, **kwargs) -> Optional[dict]:
    """
    Envia um comando JSON para a extensão do navegador.

    Parâmetros:
        acao              → nome da ação (ex: 'abrir_url', 'ler_pagina')
        aguardar_resposta → se True, bloqueia aguardando a resposta da extensão
        timeout           → tempo máximo de espera (segundos)
        **kwargs          → parâmetros extras do comando (ex: url='https://youtube.com')

    Retorna:
        dict com a resposta da extensão, ou None se sem resposta / sem cliente conectado.
    """
    with _lock_clientes:
        if not _clientes:
            print(f"[NAVEGADOR] Nenhuma extensão conectada. Comando '{acao}' descartado.")
            return None

    comando = {"acao": acao, **kwargs}

    if aguardar_resposta:
        _evento_resposta.clear()

    _fila_comandos.put(comando)
    print(f"[NAVEGADOR] Comando enfileirado: {comando}")

    if aguardar_resposta:
        chegou = _evento_resposta.wait(timeout=timeout)
        if chegou:
            return _ultima_mensagem
        else:
            print(f"[NAVEGADOR] Timeout aguardando resposta para '{acao}'.")
            return None

    return None


def esta_conectado() -> bool:
    """Retorna True se pelo menos uma extensão está conectada ao WebSocket."""
    with _lock_clientes:
        return len(_clientes) > 0


def obter_ultima_mensagem() -> Optional[dict]:
    """Retorna o último JSON recebido da extensão."""
    return _ultima_mensagem


# ─── Atalhos para ações comuns ────────────────────────────────────────────────

def abrir_url(url: str) -> None:
    """Abre uma URL na aba atual ou em nova aba."""
    enviar_comando("abrir_url", url=url)


def fechar_aba() -> None:
    """Fecha a aba atual do navegador."""
    enviar_comando("fechar_aba")


def ler_pagina(timeout: float = 8.0) -> Optional[dict]:
    """
    Solicita o conteúdo da página atual.
    Retorna dict com: texto, imagens (lista de {url, alt}), url, titulo
    ou None se falhar.
    """
    resposta = enviar_comando("ler_pagina", aguardar_resposta=True, timeout=timeout)
    if resposta and "texto" in resposta:
        return {
            "texto":   resposta.get("texto", ""),
            "imagens": resposta.get("imagens", []),
            "url":     resposta.get("url", ""),
            "titulo":  resposta.get("titulo", ""),
        }
    return None


def ler_pagina_texto(timeout: float = 8.0) -> Optional[str]:
    """Atalho: retorna só o texto da página (compatibilidade retroativa)."""
    dados = ler_pagina(timeout=timeout)
    return dados["texto"] if dados else None


def preencher_campo(seletor: str, valor: str) -> None:
    """Preenche um campo de input na página."""
    enviar_comando("preencher_campo", seletor=seletor, valor=valor)


def clicar_elemento(seletor: str) -> None:
    """Clica em um elemento da página."""
    enviar_comando("clicar_elemento", seletor=seletor)


def scroll(direcao: str = "baixo", quantidade: int = 300) -> None:
    """Rola a página (direcao: 'cima' ou 'baixo', quantidade em pixels)."""
    enviar_comando("scroll", direcao=direcao, quantidade=quantidade)


def obter_url_atual(timeout: float = 5.0) -> Optional[str]:
    """Retorna a URL da aba ativa no navegador."""
    resposta = enviar_comando("obter_url_atual", aguardar_resposta=True, timeout=timeout)
    if resposta and "url" in resposta:
        return resposta["url"]
    return None


def baixar_arquivo(url: str) -> None:
    """Inicia o download de uma URL pelo navegador."""
    enviar_comando("baixar_arquivo", url=url)


def executar_js(codigo: str, aguardar: bool = False, timeout: float = 8.0) -> Optional[dict]:
    """Executa JavaScript arbitrário na página atual."""
    return enviar_comando("executar_js", aguardar_resposta=aguardar, timeout=timeout, codigo=codigo)


def screenshot_aba(timeout: float = 10.0) -> Optional[str]:
    """Solicita um screenshot da aba atual como base64."""
    resposta = enviar_comando("screenshot_aba", aguardar_resposta=True, timeout=timeout)
    if resposta and "imagem" in resposta:
        return resposta["imagem"]
    return None


# ─── Pesquisa headless (Playwright — invisível, não afeta seu navegador) ─────

_DOMINIOS_BLOQUEADOS_HEADLESS = {
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "instagram.com", "facebook.com", "tiktok.com",
    "linkedin.com", "pinterest.com",
}

def _dominio_bloqueado_headless(url: str) -> bool:
    for dom in _DOMINIOS_BLOQUEADOS_HEADLESS:
        if dom in url:
            return True
    return False


def pesquisar_headless(
    query: str,
    n_sites: int = 3,
    timeout_pagina: float = 12.0,
    delay_entre_paginas: float = 1.0,
) -> Optional[dict]:
    """
    Faz uma pesquisa completa usando Playwright (Chromium headless — invisível).

    Estratégia:
      1. Brave Search API → obtém as URLs dos resultados (rápido, confiável)
      2. Playwright headless → visita cada site e lê o conteúdo completo real

    Não afeta nada no seu navegador — roda completamente em background.

    Retorna dict com:
      - "query":  a query original
      - "sites":  lista de {"url", "titulo", "conteudo"}
      - "total":  número de sites lidos com sucesso

    Retorna None se Playwright ou a Brave API não estiverem disponíveis.
    """
    import asyncio as _asyncio
    import os as _os
    import requests as _requests

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[HEADLESS] Playwright não está instalado.")
        return None

    # ── Etapa 1: Brave API para obter links (não usa navegador) ──
    brave_key = _os.getenv("BRAVE_API_KEY", "")
    if not brave_key:
        print("[HEADLESS] BRAVE_API_KEY não encontrada — headless indisponível.")
        return None

    try:
        resp = _requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
            params={"q": query, "count": n_sites + 4, "country": "BR"},
            timeout=10,
        )
        if not resp.ok:
            print(f"[HEADLESS] Brave API erro {resp.status_code}.")
            return None

        resultados_brave = resp.json().get("web", {}).get("results", [])
        urls_brutas = [r["url"] for r in resultados_brave if r.get("url")]
    except Exception as e:
        print(f"[HEADLESS] Erro ao consultar Brave API: {e}")
        return None

    # Filtra domínios bloqueados e duplicatas
    links: list = []
    vistos: set = set()
    for url in urls_brutas:
        if _dominio_bloqueado_headless(url):
            continue
        try:
            dominio = url.split("/")[2]
        except IndexError:
            dominio = url
        if dominio in vistos:
            continue
        vistos.add(dominio)
        links.append(url)
        if len(links) >= n_sites + 2:
            break

    if not links:
        print("[HEADLESS] Brave API não retornou URLs úteis.")
        return None

    print(f"[HEADLESS] {len(links)} links para visitar via Playwright: {links[:n_sites]}")

    # ── Etapa 2: Playwright para ler o conteúdo real de cada site ──
    async def _ler_sites():
        sites_coletados = []
        _LIMITE_SITE = 4000

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            for url in links:
                if len(sites_coletados) >= n_sites:
                    break
                try:
                    print(f"[HEADLESS] Visitando: {url[:70]}")
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=int(timeout_pagina * 1000),
                    )
                    await page.wait_for_timeout(int(delay_entre_paginas * 1000))

                    titulo = await page.title()
                    texto = await page.evaluate(
                        "() => document.body ? document.body.innerText : ''"
                    )
                    texto = (texto or "").strip()

                    if len(texto) < 150:
                        print(f"[HEADLESS] Conteúdo muito curto ({len(texto)} chars), pulando.")
                        continue

                    if len(texto) > _LIMITE_SITE:
                        texto = texto[:_LIMITE_SITE] + f"\n...[{len(texto) - _LIMITE_SITE:,} chars adicionais]"

                    sites_coletados.append({
                        "url":      url,
                        "titulo":   titulo,
                        "conteudo": texto,
                    })
                    print(f"[HEADLESS] Coletado: '{titulo[:55]}' ({len(texto)} chars)")

                except Exception as e:
                    print(f"[HEADLESS] Erro ao visitar {url}: {e}")
                    continue

            await browser.close()

        return {
            "query": query,
            "sites": sites_coletados,
            "total": len(sites_coletados),
        }

    try:
        return _asyncio.run(_ler_sites())
    except Exception as e:
        print(f"[HEADLESS] Erro geral ao ler sites: {e}")
        return None


def playwright_disponivel() -> bool:
    """Retorna True se o Playwright e o Chromium estão instalados."""
    try:
        import playwright  # noqa
        return True
    except ImportError:
        return False


# ─── Pesquisa via extensão do navegador ───────────────────────────────────────

_JS_EXTRAIR_LINKS_DDG = """
(function() {
    // DuckDuckGo HTML — extrai os hrefs dos resultados orgânicos
    var links = [];
    var anchors = document.querySelectorAll('.result__a');
    if (anchors.length === 0) {
        // fallback: tenta outros seletores
        anchors = document.querySelectorAll('a[href^="http"]');
    }
    for (var i = 0; i < anchors.length && links.length < 8; i++) {
        var href = anchors[i].href;
        // Ignora links internos do DDG e anúncios
        if (href && !href.includes('duckduckgo.com') && !href.includes('javascript:')) {
            links.push(href);
        }
    }
    return JSON.stringify(links);
})();
"""

_JS_EXTRAIR_LINKS_GOOGLE = """
(function() {
    var links = [];
    // Google: resultados ficam em divs com data-hveid, links no <a>
    var anchors = document.querySelectorAll('#search .g a[href^="http"]');
    if (anchors.length === 0) {
        // fallback genérico
        anchors = document.querySelectorAll('a[href^="http"]');
    }
    for (var i = 0; i < anchors.length && links.length < 8; i++) {
        var href = anchors[i].href;
        if (href && !href.includes('google.com') && !href.includes('javascript:')) {
            links.push(href);
        }
    }
    return JSON.stringify(links);
})();
"""

# Sites que bloqueiam bots / retornam conteúdo inútil
_DOMINIOS_BLOQUEADOS = {
    "youtube.com", "youtu.be", "twitter.com", "x.com",
    "instagram.com", "facebook.com", "tiktok.com",
    "reddit.com",  # reddit bloqueia scraping simples
    "linkedin.com", "pinterest.com",
}


def _dominio_bloqueado(url: str) -> bool:
    for dom in _DOMINIOS_BLOQUEADOS:
        if dom in url:
            return True
    return False


def pesquisar_e_coletar(
    query: str,
    n_sites: int = 3,
    timeout_pagina: float = 8.0,
    delay_entre_paginas: float = 1.5,
) -> Optional[dict]:
    """
    Faz uma pesquisa completa via navegador:
      1. Abre DuckDuckGo com a query
      2. Extrai os links dos resultados via JS
      3. Visita cada site e lê o conteúdo completo
      4. Retorna dict com:
         - "query":    a query original
         - "sites":    lista de {"url", "titulo", "conteudo"}
         - "total":    número de sites lidos com sucesso

    Retorna None se a extensão não estiver conectada.
    """
    import time
    import urllib.parse

    if not esta_conectado():
        print("[NAVEGADOR] pesquisar_e_coletar: extensão não conectada.")
        return None

    query_encoded = urllib.parse.quote_plus(query)
    url_busca = f"https://html.duckduckgo.com/html/?q={query_encoded}"

    print(f"[PESQUISA-NAV] Abrindo DuckDuckGo: {url_busca}")

    # Abre a página de busca (com request_id para aguardar confirmação de ok)
    enviar_comando_com_id("abrir_url", timeout=5.0, url=url_busca)
    time.sleep(2.5)  # aguarda a página renderizar no navegador

    # Extrai os links via JS (usa enviar_comando_com_id para evitar colisão de eventos)
    resposta_js = enviar_comando_com_id("executar_js", timeout=8.0, codigo=_JS_EXTRAIR_LINKS_DDG)
    links_raw = []

    if resposta_js and "resultado" in resposta_js:
        try:
            import json as _json
            links_raw = _json.loads(resposta_js["resultado"])
        except Exception as e:
            print(f"[PESQUISA-NAV] Erro ao parsear links: {e}")

    if not links_raw:
        print("[PESQUISA-NAV] Nenhum link extraído do DuckDuckGo, tentando Google...")
        enviar_comando_com_id("abrir_url", timeout=5.0, url=f"https://www.google.com/search?q={query_encoded}&hl=pt-BR")
        time.sleep(2.5)
        resposta_js2 = enviar_comando_com_id("executar_js", timeout=8.0, codigo=_JS_EXTRAIR_LINKS_GOOGLE)
        if resposta_js2 and "resultado" in resposta_js2:
            try:
                import json as _json
                links_raw = _json.loads(resposta_js2["resultado"])
            except Exception:
                pass

    # Filtra domínios bloqueados e duplicatas
    links = []
    vistos = set()
    for link in links_raw:
        if _dominio_bloqueado(link):
            continue
        dominio = link.split("/")[2] if link.startswith("http") else link
        if dominio in vistos:
            continue
        vistos.add(dominio)
        links.append(link)
        if len(links) >= n_sites + 2:  # pega alguns extras como reserva
            break

    print(f"[PESQUISA-NAV] {len(links)} links filtrados: {links[:n_sites]}")

    sites_coletados = []
    for url in links:
        if len(sites_coletados) >= n_sites:
            break

        print(f"[PESQUISA-NAV] Visitando: {url}")
        # Abre a URL com confirmação antes de ler o conteúdo
        enviar_comando_com_id("abrir_url", timeout=5.0, url=url)
        time.sleep(delay_entre_paginas)

        # Lê com request_id para não capturar resposta de outro comando
        resposta_pagina = enviar_comando_com_id("ler_pagina", timeout=timeout_pagina)
        if not resposta_pagina or "texto" not in resposta_pagina:
            print(f"[PESQUISA-NAV] Sem resposta de ler_pagina para: {url}")
            continue

        dados = {
            "texto":   resposta_pagina.get("texto", ""),
            "imagens": resposta_pagina.get("imagens", []),
            "url":     resposta_pagina.get("url", url),
            "titulo":  resposta_pagina.get("titulo", ""),
        }

        if not dados:
            print(f"[PESQUISA-NAV] Sem dados para: {url}")
            continue

        texto = dados.get("texto", "").strip()
        titulo = dados.get("titulo", "")

        # Ignora páginas com conteúdo muito curto (bloqueadas, erros, etc.)
        if len(texto) < 150:
            print(f"[PESQUISA-NAV] Conteúdo muito curto ({len(texto)} chars), pulando.")
            continue

        # Limita o conteúdo por site pra não explodir o contexto da LLM
        _LIMITE_SITE = 4000
        if len(texto) > _LIMITE_SITE:
            texto = texto[:_LIMITE_SITE] + f"\n...[{len(texto) - _LIMITE_SITE:,} chars adicionais]"

        sites_coletados.append({
            "url":      url,
            "titulo":   titulo,
            "conteudo": texto,
        })
        print(f"[PESQUISA-NAV] Coletado: '{titulo}' ({len(texto)} chars)")

    return {
        "query": query,
        "sites": sites_coletados,
        "total": len(sites_coletados),
    }
