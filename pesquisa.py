"""Pesquisa web profunda e invisível da Emily.

O fluxo comum nunca abre Brave, Chrome, aba ou janela do usuário:
  1. Brave LLM Context extrai trechos relevantes de várias páginas.
  2. Brave Web Search amplia consultas/páginas e traz snippets alternativos.
  3. Requests + BeautifulSoup lê, em paralelo, páginas ainda pouco cobertas.
  4. Playwright *headless* pode complementar como último recurso invisível.

A extensão continua disponível para interação explícita com páginas e sessões
logadas, mas não participa do fallback automático de pesquisa informacional.
"""

from __future__ import annotations

import os
import re
import html
import ipaddress
import socket
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
import requests
from typing import Any, Optional
from dotenv import load_dotenv

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
_BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
_BRAVE_CONTEXT_URL = "https://api.search.brave.com/res/v1/llm/context"
_BRAVE_LOCK = threading.Lock()
_BRAVE_ULTIMA_CHAMADA = 0.0
_BRAVE_INTERVALO_MINIMO = 1.05

# Tetos de fontes distintas. A busca para antes quando a evidência já basta.
_N_SITES_NAVEGADOR = 5
_N_SITES_MAXIMO = 16
_CATALOGO_MODELOS_OPENAI = "https://developers.openai.com/api/docs/models"


def _n_sites_por_profundidade(profundidade: str, n_sites: Optional[int] = None) -> int:
    """
    Decide o teto de sites, não uma meta a ser preenchida.

    - n_sites explícito (chamada direta): usa esse, limitado ao teto.
    - profundidade 'rapida'  -> 5
    - profundidade 'profunda'-> 12 (até 16)
    - profundidade 'normal' ou vazio -> 8
    """
    if n_sites is not None:
        return max(3, min(int(n_sites), _N_SITES_MAXIMO))
    prof = (profundidade or "normal").strip().lower()
    if "rapid" in prof or "rápid" in prof:
        return 5
    if "profund" in prof:
        return 12
    return 8


# ─────────────────────────────────────────────────────────────────
# EXTRAÇÃO DE QUERY
# ─────────────────────────────────────────────────────────────────

def _extrair_query(texto: str) -> str:
    """Remove prefixos de pesquisa da mensagem pra deixar só a query limpa."""
    texto = re.sub(
        r"^(pesquisa|pesquise|busca|busque|procura|procure|pesquisa sobre|"
        r"pesquisa a respeito de|pesquisa por|busca por|procura por|"
        r"me fala sobre|me conta sobre|o que é|o que são|"
        r"quem é|quem são|como funciona|como fazer|"
        r"qual é|quais são|onde fica|quando foi|"
        r"por que|porque|pra que|para que|"
        r"me explica|me explique|explica|explique|"
        r"preciso saber sobre|preciso de informação sobre|"
        r"informação sobre|informações sobre|"
        r"faz uma pesquisa|faz uma busca|pesquisa rápida|"
        r"na internet|na web|no google|na web sobre)\s+",
        "",
        texto,
        flags=re.IGNORECASE,
    ).strip()
    return texto


# ─────────────────────────────────────────────────────────────────
# PESQUISA VIA NAVEGADOR (principal)
# ─────────────────────────────────────────────────────────────────

def _formatar_contexto_sites(dados: dict) -> str:
    """
    Converte o resultado de pesquisar_e_coletar() em uma string de contexto
    formatada para a LLM.
    """
    query = dados.get("query", "")
    sites = dados.get("sites", [])
    total = dados.get("total", 0)

    if not sites:
        return f"Não consegui coletar conteúdo de nenhum site para a pesquisa sobre '{query}'."

    linhas = [f"Pesquisa sobre: '{query}' — {total} site(s) consultados\n"]

    for i, site in enumerate(sites, 1):
        titulo  = site.get("titulo", "Sem título")
        url     = site.get("url", "")
        conteudo = site.get("conteudo", "")
        linhas.append(f"--- Fonte {i}: {titulo} ---")
        linhas.append(f"URL: {url}")
        linhas.append(conteudo)
        linhas.append("")  # linha em branco entre fontes

    return "\n".join(linhas)


def pesquisa_via_headless(query: str, n_sites: int = _N_SITES_NAVEGADOR) -> Optional[str]:
    """
    Faz a pesquisa usando Playwright (Chromium headless — completamente invisível).
    Não abre nada no seu navegador, não muda sua aba.
    É a opção preferida — sempre que disponível, usa essa.
    """
    try:
        import navegador as _nav
        if not _nav.playwright_disponivel():
            return None

        print(f"[PESQUISA] Usando Playwright headless para: '{query}' ({n_sites} sites)")
        dados = _nav.pesquisar_headless(query, n_sites=n_sites)

        if not dados or dados.get("total", 0) == 0:
            print("[PESQUISA] Headless não retornou sites úteis.")
            return None

        return _formatar_contexto_sites(dados)

    except Exception as e:
        print(f"[PESQUISA] Erro na pesquisa headless: {e}")
        return None


def pesquisa_via_extensao(query: str, n_sites: int = _N_SITES_NAVEGADOR) -> Optional[str]:
    """
    Faz a pesquisa usando a extensão do navegador (abre abas no seu Brave).
    Usado como fallback quando o Playwright não está disponível.
    """
    try:
        import navegador as _nav
        if not _nav.esta_conectado():
            return None

        print(f"[PESQUISA] Usando extensão do navegador para: '{query}' ({n_sites} sites)")
        dados = _nav.pesquisar_e_coletar(query, n_sites=n_sites)

        if not dados or dados.get("total", 0) == 0:
            print("[PESQUISA] Extensão não retornou sites úteis.")
            return None

        return _formatar_contexto_sites(dados)

    except Exception as e:
        print(f"[PESQUISA] Erro na pesquisa via extensão: {e}")
        return None


# Mantém o nome antigo por compatibilidade
def pesquisa_via_navegador(query: str) -> Optional[str]:
    """Alias retrocompatível para pesquisa_via_extensao."""
    return pesquisa_via_extensao(query)


# ─────────────────────────────────────────────────────────────────
# PESQUISA VIA BRAVE API (fallback)
# ─────────────────────────────────────────────────────────────────

def _extrair_conteudo_pagina(url: str, limite: int = 5000) -> Optional[str]:
    """
    Extrai conteúdo por HTTP, sem navegador e sem interface visível.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    try:
        url = _validar_url_publica(url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }

        resp = None
        for _ in range(6):
            resp = requests.get(
                url, headers=headers, timeout=(4, 9), allow_redirects=False)
            if resp.status_code not in {301, 302, 303, 307, 308}:
                break
            destino = resp.headers.get("Location", "")
            if not destino:
                return None
            url = _validar_url_publica(urljoin(url, destino))
        if resp is None or resp.status_code in {301, 302, 303, 307, 308}:
            return None

        if not resp.ok:
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        raiz = soup.find("main") or soup.find("article") or soup.body or soup
        texto = raiz.get_text(separator=" ", strip=True)
        texto = html.unescape(re.sub(r"\s+", " ", texto)).strip()

        if len(texto) < 200:
            return None

        return texto[:max(800, int(limite))]

    except Exception:
        return None


def _validar_url_publica(url: str) -> str:
    """Bloqueia SSRF: a coleta HTTP só acessa endereços públicos HTTP(S)."""
    canonica = _url_canonica(url)
    if not canonica:
        raise ValueError("URL inválida ou local")
    parsed = urlsplit(canonica)
    host = (parsed.hostname or "").lower().rstrip(".")
    try:
        enderecos = {info[4][0] for info in socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except socket.gaierror as exc:
        raise ValueError("Servidor não localizado") from exc
    if not enderecos:
        raise ValueError("Servidor sem endereço")
    for endereco in enderecos:
        if not ipaddress.ip_address(endereco).is_global:
            raise ValueError("URL aponta para rede local ou reservada")
    return canonica


def _env_bool(nome: str, padrao: bool) -> bool:
    valor = os.getenv(nome)
    if valor is None:
        return padrao
    return valor.strip().lower() not in {"0", "false", "nao", "não", "off"}


def _perfil_pesquisa(profundidade: str, n_sites: Optional[int] = None) -> dict:
    """Orçamento adaptativo: aprofunda sem criar laço infinito ou custo oculto."""
    alvo = _n_sites_por_profundidade(profundidade, n_sites)
    prof = (profundidade or "normal").strip().lower()
    if "rapid" in prof or "rápid" in prof:
        return {
            "nome": "rápida", "alvo": alvo, "inicio": min(3, alvo), "tokens": 5500,
            "paginas_busca": 1, "variantes": 1, "paginas_http": 2,
            "min_fontes": 2, "min_chars": 1500,
        }
    if "profund" in prof:
        return {
            "nome": "profunda", "alvo": alvo, "inicio": min(6, alvo), "tokens": 18000,
            "paginas_busca": 3, "variantes": 3, "paginas_http": 7,
            "min_fontes": min(5, alvo), "min_chars": 4200,
        }
    return {
        "nome": "normal", "alvo": alvo, "inicio": min(5, alvo), "tokens": 10500,
        "paginas_busca": 2, "variantes": 2, "paginas_http": 4,
        "min_fontes": min(3, alvo), "min_chars": 2700,
    }


def _cabecalhos_brave() -> dict:
    return {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
    }


def _limitar_query_brave(query: str) -> str:
    """O Brave aceita no máximo 400 caracteres e 50 palavras por consulta."""
    palavras = re.sub(r"\s+", " ", str(query or "")).strip().split(" ")[:50]
    return " ".join(palavras)[:400].strip()


def _brave_get(url: str, *, params: dict, timeout: tuple[int, int]):
    """GET com ritmo global e retentativas curtas para 429/erros transitórios."""
    global _BRAVE_ULTIMA_CHAMADA
    ultima = None
    for tentativa in range(3):
        with _BRAVE_LOCK:
            espera = _BRAVE_INTERVALO_MINIMO - (time.monotonic() - _BRAVE_ULTIMA_CHAMADA)
            if espera > 0:
                time.sleep(espera)
            ultima = requests.get(
                url, headers=_cabecalhos_brave(), params=params, timeout=timeout)
            _BRAVE_ULTIMA_CHAMADA = time.monotonic()
        if ultima.status_code not in {429, 500, 502, 503, 504}:
            return ultima
        if tentativa < 2:
            retry_after = ultima.headers.get("Retry-After", "")
            try:
                atraso = max(float(retry_after), 1.0)
            except (TypeError, ValueError):
                atraso = 1.0 * (2 ** tentativa)
            time.sleep(min(atraso, 4.0))
    return ultima


def _url_canonica(url: str) -> str:
    """Remove fragmentos e rastreadores para deduplicar a mesma página."""
    try:
        p = urlsplit((url or "").strip())
        if (p.scheme not in {"http", "https"} or not p.netloc
                or p.username or p.password):
            return ""
        host = p.hostname.lower() if p.hostname else ""
        if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local"):
            return ""
        query = [
            (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_")
            and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
        ]
        caminho = re.sub(r"/{2,}", "/", p.path or "/")
        if caminho != "/":
            caminho = caminho.rstrip("/")
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), caminho,
                           urlencode(query, doseq=True), ""))
    except Exception:
        return ""


def _dominio(url: str) -> str:
    try:
        host = (urlsplit(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _texto_limpo(valor: Any) -> str:
    if isinstance(valor, dict):
        valor = (valor.get("text") or valor.get("snippet")
                 or valor.get("description") or valor.get("content") or "")
    texto = html.unescape(re.sub(r"<[^>]+>", " ", str(valor or "")))
    return re.sub(r"\s+", " ", texto).strip()


def _juntar_trechos(valores: Any, limite: int = 6000) -> str:
    if isinstance(valores, (str, dict)):
        valores = [valores]
    vistos: set[str] = set()
    partes: list[str] = []
    for valor in valores or []:
        trecho = _texto_limpo(valor)
        chave = trecho.lower()
        if len(trecho) < 30 or chave in vistos:
            continue
        vistos.add(chave)
        partes.append(trecho)
        if sum(len(p) for p in partes) >= limite:
            break
    return "\n".join(partes)[:limite]


def _adicionar_fonte(fontes: dict[str, dict], *, url: str, titulo: str = "",
                     conteudo: str = "", origem: str = "") -> None:
    canonica = _url_canonica(url)
    if not canonica:
        return
    atual = fontes.get(canonica)
    novo = {
        "url": canonica,
        "titulo": _texto_limpo(titulo) or _dominio(canonica) or "Sem título",
        "conteudo": _juntar_trechos(conteudo),
        "origens": [origem] if origem else [],
    }
    if atual is None:
        fontes[canonica] = novo
        return
    if len(novo["titulo"]) > len(atual.get("titulo", "")):
        atual["titulo"] = novo["titulo"]
    combinado = _juntar_trechos(
        [atual.get("conteudo", ""), novo.get("conteudo", "")], limite=6500)
    atual["conteudo"] = combinado
    for item in novo["origens"]:
        if item not in atual["origens"]:
            atual["origens"].append(item)


def _fontes_do_contexto(dados: dict, fontes: dict[str, dict]) -> int:
    """Aceita o formato atual do LLM Context e variações retrocompatíveis."""
    antes = len(fontes)
    grounding = dados.get("grounding") or {}
    grupos = grounding.values() if isinstance(grounding, dict) else []
    for grupo in grupos:
        itens = grupo if isinstance(grupo, list) else [grupo]
        for item in itens:
            if not isinstance(item, dict):
                continue
            _adicionar_fonte(
                fontes,
                url=item.get("url", ""),
                titulo=item.get("title") or item.get("name") or "",
                conteudo=(item.get("snippets") or item.get("content")
                          or item.get("description") or ""),
                origem="Brave LLM Context",
            )
    # Alguns releases expõem uma lista plana de resultados.
    for item in dados.get("results") or []:
        if isinstance(item, dict):
            _adicionar_fonte(
                fontes, url=item.get("url", ""),
                titulo=item.get("title", ""),
                conteudo=item.get("snippets") or item.get("description") or "",
                origem="Brave LLM Context",
            )
    return len(fontes) - antes


def _consultar_contexto_brave(query: str, perfil: dict,
                              fontes: dict[str, dict]) -> tuple[bool, str]:
    try:
        resposta = _brave_get(
            _BRAVE_CONTEXT_URL,
            params={
                "q": _limitar_query_brave(query),
                "country": "BR",
                "search_lang": "pt-br",
                "count": min(50, max(perfil["inicio"] * 2, 6)),
                "maximum_number_of_urls": min(50, max(perfil["inicio"], 3)),
                "maximum_number_of_tokens": perfil["tokens"],
                "maximum_number_of_tokens_per_url": 2600,
                "context_threshold_mode": "balanced",
                "enable_source_metadata": "true",
                "spellcheck": "true",
            },
            timeout=(5, 30),
        )
        if resposta.status_code in {401, 403}:
            return False, "A chave/plano do Brave não autorizou o LLM Context."
        if resposta.status_code == 429:
            return False, "O limite de requisições do Brave foi atingido."
        if not resposta.ok:
            return False, f"LLM Context retornou HTTP {resposta.status_code}."
        adicionadas = _fontes_do_contexto(resposta.json(), fontes)
        print(f"[PESQUISA] LLM Context adicionou {adicionadas} fonte(s).")
        return adicionadas > 0, ""
    except requests.exceptions.Timeout:
        return False, "LLM Context excedeu o tempo de resposta."
    except requests.exceptions.RequestException as e:
        return False, f"Falha de rede no LLM Context: {e}"
    except Exception as e:
        return False, f"Resposta inválida do LLM Context: {e}"


def _consultar_web_brave(query: str, offset: int,
                         fontes: dict[str, dict], *,
                         freshness: str = "", idioma: str = "pt-br"
                         ) -> tuple[bool, bool, str]:
    try:
        params = {
            "q": _limitar_query_brave(query), "count": 20, "offset": offset,
            "country": "US" if idioma == "en" else "BR",
            "search_lang": idioma,
            "ui_lang": "en-US" if idioma == "en" else "pt-BR",
            "extra_snippets": "true", "spellcheck": "true",
        }
        if freshness:
            params["freshness"] = freshness
        resposta = _brave_get(
            _BRAVE_WEB_URL,
            params=params,
            timeout=(5, 18),
        )
        if resposta.status_code == 429:
            return False, False, "O limite de requisições do Brave foi atingido."
        if not resposta.ok:
            return False, False, f"Web Search retornou HTTP {resposta.status_code}."
        dados = resposta.json()
        resultados = dados.get("web", {}).get("results", [])
        antes = len(fontes)
        for item in resultados:
            trechos = [item.get("description", ""), *(item.get("extra_snippets") or [])]
            _adicionar_fonte(
                fontes, url=item.get("url", ""), titulo=item.get("title", ""),
                conteudo=trechos, origem=f"Brave Web Search (página {offset + 1})",
            )
        mais = bool((dados.get("query") or {}).get("more_results_available"))
        return len(fontes) > antes, mais, ""
    except requests.exceptions.Timeout:
        return False, False, "Web Search excedeu o tempo de resposta."
    except requests.exceptions.RequestException as e:
        return False, False, f"Falha de rede no Web Search: {e}"
    except Exception as e:
        return False, False, f"Resposta inválida do Web Search: {e}"


def _variantes_query(query: str) -> list[str]:
    """Expansões conservadoras, usadas apenas se a cobertura inicial for fraca."""
    candidatas = [
        query,
        f"{query} detalhes fontes dados",
        f"{query} comparação análise",
    ]
    saida: list[str] = []
    for item in candidatas:
        item = re.sub(r"\s+", " ", item).strip()[:400]
        if item and item.lower() not in {x.lower() for x in saida}:
            saida.append(item)
    return saida


def _consulta_modelos_openai(query: str) -> bool:
    """Reconhece o assunto, sem fixar nomes ou versões de modelos no código."""
    q = query.casefold()
    return "openai" in q and bool(re.search(r"\b(?:modelos?|models?|gpt)\b", q))


def _buscar_catalogo_oficial_openai(fontes: dict[str, dict]) -> bool:
    """Lê o catálogo atual da própria fabricante antes de ranquear terceiros."""
    conteudo = _extrair_conteudo_pagina(_CATALOGO_MODELOS_OPENAI, limite=7000)
    if not conteudo:
        return False
    _adicionar_fonte(
        fontes, url=_CATALOGO_MODELOS_OPENAI,
        titulo="Catálogo oficial de modelos da OpenAI",
        conteudo=conteudo, origem="Página oficial",
    )
    return True


_TERMOS_GENERICOS = {
    "a", "as", "o", "os", "um", "uma", "de", "da", "das", "do", "dos",
    "e", "em", "no", "na", "nos", "nas", "com", "para", "por", "que",
    "qual", "quais", "como", "quando", "onde", "quem", "quanto",
    "sobre", "entre", "mais", "menos", "muito", "foi", "sao", "esta",
    "me", "min", "eu", "voce", "quero", "saber", "pode", "fazer",
    "pesquisa", "pesquisar", "busca", "buscar", "informacao", "informacoes",
    "the", "and", "for", "with", "from", "about", "what", "which",
}


def _palavras_normais(texto: str) -> list[str]:
    sem_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", sem_acentos)


def _termos_da_consulta(query: str) -> list[str]:
    termos: list[str] = []
    for termo in _palavras_normais(query):
        if len(termo) < 3 or termo in _TERMOS_GENERICOS or termo in termos:
            continue
        termos.append(termo)
    return termos[-12:]


def _relevancia_fonte(fonte: dict, termos: list[str]) -> int:
    if not fonte.get("conteudo"):
        return 0
    if not termos:
        return 1
    palavras = set(_palavras_normais(
        str(fonte.get("titulo", "")) + " " + str(fonte.get("conteudo", ""))[:3200]))
    acertos = sum(any(p == t or (len(t) >= 5 and p.startswith(t[:5]))
                      for p in palavras) for t in termos)
    return acertos if acertos >= (1 if len(termos) <= 2 else 2) else 0


def _cobertura(fontes: dict[str, dict], query: str = "",
               limite: int = _N_SITES_MAXIMO) -> tuple[int, int, int]:
    termos = _termos_da_consulta(query)
    validas = sorted(
        (f for f in fontes.values() if _relevancia_fonte(f, termos)),
        key=lambda f: len(f.get("conteudo", "")), reverse=True)
    selecionadas: list[dict] = []
    dominios: set[str] = set()
    for fonte in validas:
        dominio = _dominio(fonte["url"])
        if dominio not in dominios:
            selecionadas.append(fonte)
            dominios.add(dominio)
        if len(selecionadas) >= limite:
            break
    if len(selecionadas) < limite:
        restantes = [f for f in validas if f not in selecionadas]
        selecionadas.extend(restantes[:limite - len(selecionadas)])
    return len(selecionadas), len({_dominio(f["url"]) for f in selecionadas}), sum(
        min(len(f.get("conteudo", "")), 1800) for f in selecionadas)


def _cobertura_suficiente(fontes: dict[str, dict], perfil: dict,
                          query: str = "") -> bool:
    fontes_ok, dominios, caracteres = _cobertura(fontes, query, perfil["alvo"])
    return (
        fontes_ok >= perfil["min_fontes"]
        and dominios >= perfil["min_fontes"]
        and caracteres >= perfil["min_chars"]
    )


def _enriquecer_via_http(fontes: dict[str, dict], perfil: dict,
                        query: str = "") -> None:
    termos = _termos_da_consulta(query)
    candidatos = [
        f for f in fontes.values()
        if len(f.get("conteudo", "")) < 900
    ]
    candidatos.sort(key=lambda f: _relevancia_fonte(f, termos), reverse=True)
    candidatos = candidatos[:perfil["paginas_http"]]
    if not candidatos:
        return
    limite = 4200 if perfil["nome"] == "profunda" else 2800
    with ThreadPoolExecutor(max_workers=min(5, len(candidatos))) as pool:
        futuros = {
            pool.submit(_extrair_conteudo_pagina, fonte["url"], limite): fonte
            for fonte in candidatos
        }
        for futuro in as_completed(futuros):
            fonte = futuros[futuro]
            try:
                conteudo = futuro.result()
            except Exception:
                conteudo = None
            if conteudo:
                fonte["conteudo"] = _juntar_trechos(
                    [fonte.get("conteudo", ""), conteudo], limite=6000)
                if "HTTP invisível" not in fonte["origens"]:
                    fonte["origens"].append("HTTP invisível")


def _complementar_headless(query: str, perfil: dict,
                            fontes: dict[str, dict]) -> None:
    if not _env_bool("EMILY_PESQUISA_HEADLESS", True):
        return
    try:
        import navegador as _nav
        if not _nav.playwright_disponivel():
            return
        dados = _nav.pesquisar_headless(
            query, n_sites=min(5, perfil["alvo"]),
            timeout_pagina=10.0, delay_entre_paginas=0.2)
        for site in (dados or {}).get("sites", []):
            _adicionar_fonte(
                fontes, url=site.get("url", ""), titulo=site.get("titulo", ""),
                conteudo=site.get("conteudo", ""), origem="Playwright headless",
            )
    except Exception as e:
        print(f"[PESQUISA] Complemento headless indisponível: {e}")


def _selecionar_fontes(fontes: dict[str, dict], perfil: dict,
                       query: str = "") -> list[dict]:
    """Devolve só a evidência útil necessária, respeitando o teto do perfil."""
    oficial_openai = _consulta_modelos_openai(query)
    termos = _termos_da_consulta(query)

    def prioridade(fonte: dict) -> tuple[bool, int, int]:
        dominio = _dominio(fonte["url"])
        oficial = oficial_openai and dominio in {
            "developers.openai.com", "platform.openai.com", "openai.com"}
        return bool(oficial), _relevancia_fonte(fonte, termos), len(fonte.get("conteudo", ""))

    todas = sorted((f for f in fontes.values() if f.get("conteudo")),
                   key=prioridade, reverse=True)
    relevantes = [f for f in todas if _relevancia_fonte(f, termos)
                  or (oficial_openai and _dominio(f["url"]) in {
                      "developers.openai.com", "platform.openai.com", "openai.com"})]
    candidatas = relevantes or todas
    escolhidas: list[dict] = []
    dominios: set[str] = set()
    for fonte in candidatas:
        dominio = _dominio(fonte["url"])
        if dominio in dominios:
            continue
        escolhidas.append(fonte)
        dominios.add(dominio)
        if (len(escolhidas) >= perfil["alvo"] or _cobertura_suficiente(
                {f["url"]: f for f in escolhidas}, perfil, query)):
            return escolhidas
    for fonte in candidatas:
        if fonte not in escolhidas:
            escolhidas.append(fonte)
            if (len(escolhidas) >= perfil["alvo"] or _cobertura_suficiente(
                    {f["url"]: f for f in escolhidas}, perfil, query)):
                break
    return escolhidas


def _formatar_pesquisa_profunda(query: str, perfil: dict, fontes: dict[str, dict],
                                consultas: list[str], avisos: list[str]) -> str:
    selecionadas = _selecionar_fontes(fontes, perfil, query)
    if not selecionadas:
        detalhe = "; ".join(dict.fromkeys(a for a in avisos if a))
        return (f"Não encontrei fontes úteis para '{query}'."
                + (f" Detalhes: {detalhe}" if detalhe else ""))

    total_chars = sum(len(f.get("conteudo", "")) for f in selecionadas)
    linhas = [
        f"PESQUISA WEB INVISÍVEL — profundidade {perfil['nome']}",
        f"Pergunta pesquisada: {query}",
        (f"Cobertura: {len(selecionadas)} fontes de "
         f"{len({_dominio(f['url']) for f in selecionadas})} sites, "
         f"{total_chars} caracteres úteis coletados."),
        "Consultas executadas: " + " | ".join(consultas),
        "",
        "Compare as fontes, destaque concordâncias e divergências e não trate "
        "um único site como confirmação. Para versões e lançamentos atuais, "
        "priorize fontes oficiais e confira se elas sustentam os nomes citados. "
        "Se a evidência for parcial, diga isso e não complete com memória. "
        "Se já responde à pergunta, responda agora; outra pesquisa só faz "
        "sentido para uma lacuna específica.",
        "",
    ]
    por_fonte = 1800 if perfil["nome"] == "profunda" else 1350
    for indice, fonte in enumerate(selecionadas, 1):
        limite_fonte = max(por_fonte, 3000) if (
            _consulta_modelos_openai(query)
            and _dominio(fonte["url"]) == "developers.openai.com"
        ) else por_fonte
        linhas.extend([
            f"--- Fonte {indice}: {fonte['titulo']} ---",
            f"Site: {_dominio(fonte['url'])}",
            f"URL: {fonte['url']}",
            f"Coleta: {', '.join(fonte.get('origens') or ['Brave'])}",
            fonte.get("conteudo", "")[:limite_fonte],
            "",
        ])
    if avisos:
        linhas.append("Avisos técnicos (não invalidam as fontes acima): "
                      + "; ".join(dict.fromkeys(a for a in avisos if a)))
    return "\n".join(linhas)


def extrair_fontes_do_resultado(resultado: str) -> list[dict[str, str]]:
    """Metadados reais da pesquisa para os links abaixo da resposta no PC."""
    fontes: list[dict[str, str]] = []
    vistas: set[str] = set()
    padrao = re.compile(
        r"^--- Fonte \d+: (.+?) ---\s*\n(?:Site: [^\n]*\n)?URL: (https?://[^\s]+)",
        re.MULTILINE,
    )
    for titulo, url in padrao.findall(resultado or ""):
        canonica = _url_canonica(url)
        if not canonica or canonica in vistas:
            continue
        vistas.add(canonica)
        fontes.append({"titulo": _texto_limpo(titulo)[:160], "url": canonica})
        if len(fontes) >= _N_SITES_MAXIMO:
            break
    return fontes


def pesquisa_invisivel(query: str, profundidade: str = "normal",
                       n_sites: Optional[int] = None) -> str:
    """Pipeline adaptativo multi-site que nunca usa a extensão do navegador."""
    query_limpa = _extrair_query(query).strip()[:400]
    if not query_limpa:
        return "Não entendi o que você quer pesquisar."
    if not BRAVE_API_KEY:
        return "Erro: chave da API do Brave não encontrada no .env"

    perfil = _perfil_pesquisa(profundidade, n_sites)
    fontes: dict[str, dict] = {}
    consultas: list[str] = []
    avisos: list[str] = []
    print(f"[PESQUISA] Busca invisível {perfil['nome']}: '{query_limpa}'")

    consultas.append(query_limpa)
    _, aviso = _consultar_contexto_brave(query_limpa, perfil, fontes)
    if aviso:
        avisos.append(aviso)

    # Muitos trechos antigos podem satisfazer a contagem de caracteres sem
    # responder qual é a versão ATUAL. Confere a fonte primária nesse caso.
    if _consulta_modelos_openai(query_limpa):
        if not _buscar_catalogo_oficial_openai(fontes):
            consulta_oficial = "OpenAI latest models site:developers.openai.com"
            consultas.append(consulta_oficial)
            _, _, aviso = _consultar_web_brave(
                consulta_oficial, 0, fontes, idioma="en")
            if aviso:
                avisos.append(aviso)
    else:
        # Para outras perguntas temporais, uma busca com recência complementa
        # o contexto mesmo quando ele já trouxe bastante texto antigo.
        import classificacao_ferramentas as cf
        if cf.parece_consulta_atual(query_limpa):
            _, _, aviso = _consultar_web_brave(
                query_limpa, 0, fontes, freshness="py")
            if aviso:
                avisos.append(aviso)

    if not _cobertura_suficiente(fontes, perfil, query_limpa):
        variantes = _variantes_query(query_limpa)[:perfil["variantes"]]
        for variante in variantes:
            if variante not in consultas:
                consultas.append(variante)
            mais = True
            for offset in range(perfil["paginas_busca"]):
                if offset and not mais:
                    break
                adicionou, mais, aviso = _consultar_web_brave(
                    variante, offset, fontes)
                if aviso:
                    avisos.append(aviso)
                    break
                if _cobertura_suficiente(fontes, perfil, query_limpa):
                    break
                if not adicionou and not mais:
                    break
            if _cobertura_suficiente(fontes, perfil, query_limpa):
                break

    if not _cobertura_suficiente(fontes, perfil, query_limpa):
        _enriquecer_via_http(fontes, perfil, query_limpa)
    if not _cobertura_suficiente(fontes, perfil, query_limpa):
        _complementar_headless(query_limpa, perfil, fontes)

    return _formatar_pesquisa_profunda(
        query_limpa, perfil, fontes, consultas, avisos)


def pesquisa_via_brave(query: str) -> str:
    """
    Compatibilidade com chamadas antigas: pesquisa rápida pelo pipeline invisível.
    """
    return pesquisa_invisivel(query, profundidade="rapida")


# ─────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA PRINCIPAL
# ─────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────
# PESQUISA DE COMANDO (leve) — descobrir como instalar/executar algo
#
# Diferença da pesquisar(): esta é OTIMIZADA PRA LEVEZA — uma única
# chamada de API de busca, sem abrir navegador, sem visitar páginas. Os
# snippets dos resultados já podem trazer o comando adequado ao sistema.
# Existe pra Emily nunca inventar comando de instalação: quando ela não
# tem certeza, pesquisa aqui primeiro.
# ─────────────────────────────────────────────────────────────────

def _distro_id() -> str:
    """ID da distro (ex.: 'fedora', 'ubuntu'). Vazio fora do Linux."""
    if os.name != "posix":
        return ""
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("ID="):
                    return linha.split("=", 1)[1].strip().strip('"').strip(chr(39)).lower()
    except OSError:
        pass
    return ""


def pesquisar_comando(software: str) -> str:
    """
    Descobre o comando de terminal pra instalar/executar `software` no
    sistema atual. LEVE: uma chamada de busca, snippets only. Devolve texto
    com os candidatos a comando e a fonte — NÃO executa nada.
    """
    software = (software or "").strip()
    if not software:
        return "Me diz o nome do programa ou coisa que você quer instalar."

    windows = os.name == "nt"
    distro = "" if windows else _distro_id()
    if windows:
        query = f"how to install {software} on Windows 11 official winget PowerShell command"
        sistema = "Windows 11"
        orientacao = "Use apenas um comando que as fontes confirmem para Windows 11"
    elif distro:
        query = f"how to install {software} on {distro} terminal command {distro}"
        sistema = f"Linux ({distro})"
        orientacao = "Use o comando que fizer sentido pra distro atual"
    else:
        query = f"how to install {software} linux terminal command"
        sistema = "Linux"
        orientacao = "Use o comando que fizer sentido pra distro atual"

    if not BRAVE_API_KEY:
        # Sem chave de API: cai na pesquisa normal em modo rápido.
        return pesquisar(query, "rapida")

    try:
        resposta = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={"q": query, "count": 5},
            timeout=10,
        )
        if resposta.status_code == 429:
            return "Limite da API de busca atingido; tenta de novo em alguns segundos."
        if not resposta.ok:
            return f"A busca retornou erro {resposta.status_code}."

        resultados = resposta.json().get("web", {}).get("results", [])
        if not resultados:
            return f"Não achei nada sobre como instalar '{software}'."

        linhas = [
            f"Como instalar/executar {software} no {sistema} — "
            "comandos encontrados na web (confira a fonte antes de executar):",
            "",
        ]
        for i, r in enumerate(resultados, 1):
            titulo = r.get("title", "Sem título")
            desc = r.get("description", "")
            url = r.get("url", "")
            linhas.append(f"{i}. {titulo}")
            if desc:
                linhas.append(f"   {desc}")
            if url:
                linhas.append(f"   fonte: {url}")
        linhas.append("")
        linhas.append(
            f"{orientacao} e execute via "
            "executar_terminal (com confirmação do Vitor se for instalar/"
            "desinstalar). Se nenhum resultado trouxer um comando claro, "
            "diga que não achou em vez de inventar."
        )
        return "\n".join(linhas)

    except requests.exceptions.Timeout:
        return "A busca de comando demorou demais (timeout)."
    except requests.exceptions.ConnectionError:
        return "Sem internet pra pesquisar o comando."
    except Exception as e:
        return f"Erro na busca de comando: {e}"


def pesquisar(query: str, profundidade: str = "normal",
              n_sites: Optional[int] = None) -> str:
    """
    Pesquisa adaptativa e totalmente invisível.

    A extensão nunca é chamada aqui. Ela continua reservada para tarefas
    explícitas de navegador, como agir numa página logada ou na aba atual.
    """
    return pesquisa_invisivel(query, profundidade=profundidade, n_sites=n_sites)
