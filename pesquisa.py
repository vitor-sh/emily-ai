"""
pesquisa.py — Módulo de pesquisa da Emily.

Estratégia de fallback automático (ordem de prioridade):
  1. Playwright headless → pesquisa_via_headless()
     - Chromium invisível, não afeta seu navegador nem suas abas
     - Sem limite de requisições, conteúdo real das páginas
  2. Extensão conectada (Brave/Chrome aberto) → pesquisa_via_extensao()
     - Abre DuckDuckGo na aba ativa, extrai links e conteúdo
     - Usado só se o Playwright não estiver disponível
  3. Brave Search API → pesquisa_via_brave()
     - Fallback final sem precisar de navegador
"""

from __future__ import annotations

import os
import re
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# Número de sites que a Emily vai visitar quando usar o navegador
_N_SITES_NAVEGADOR = 3


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


def pesquisa_via_headless(query: str) -> Optional[str]:
    """
    Faz a pesquisa usando Playwright (Chromium headless — completamente invisível).
    Não abre nada no seu navegador, não muda sua aba.
    É a opção preferida — sempre que disponível, usa essa.
    """
    try:
        import navegador as _nav
        if not _nav.playwright_disponivel():
            return None

        print(f"[PESQUISA] Usando Playwright headless para: '{query}'")
        dados = _nav.pesquisar_headless(query, n_sites=_N_SITES_NAVEGADOR)

        if not dados or dados.get("total", 0) == 0:
            print("[PESQUISA] Headless não retornou sites úteis.")
            return None

        return _formatar_contexto_sites(dados)

    except Exception as e:
        print(f"[PESQUISA] Erro na pesquisa headless: {e}")
        return None


def pesquisa_via_extensao(query: str) -> Optional[str]:
    """
    Faz a pesquisa usando a extensão do navegador (abre abas no seu Brave).
    Usado como fallback quando o Playwright não está disponível.
    """
    try:
        import navegador as _nav
        if not _nav.esta_conectado():
            return None

        print(f"[PESQUISA] Usando extensão do navegador para: '{query}'")
        dados = _nav.pesquisar_e_coletar(query, n_sites=_N_SITES_NAVEGADOR)

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

def _extrair_conteudo_pagina(url: str) -> Optional[str]:
    """
    Tenta extrair o conteúdo de texto de uma página web usando requests + BeautifulSoup.
    Fallback usado quando a extensão não está disponível.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }

        resp = requests.get(
            url,
            headers=headers,
            timeout=6,
            allow_redirects=True,
        )

        if not resp.ok:
            return None

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()

        texto = soup.get_text(separator=" ", strip=True)
        texto = re.sub(r"\s+", " ", texto).strip()

        if len(texto) < 200:
            return None

        return texto[:1500]

    except Exception:
        return None


def pesquisa_via_brave(query: str) -> str:
    """
    Faz a pesquisa usando a Brave Search API.
    Comportamento original — usado como fallback quando a extensão não está conectada.
    """
    query_limpa = _extrair_query(query).strip()
    if not query_limpa:
        return "Não entendi o que você quer pesquisar."

    if len(query_limpa) > 400:
        query_limpa = query_limpa[:400]

    print(f"[PESQUISA] Usando Brave API para: '{query_limpa}'")

    if not BRAVE_API_KEY:
        return "Erro: chave da API do Brave não encontrada no .env"

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }

    params = {
        "q": query_limpa,
        "count": 5,
        "country": "BR",
    }

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            timeout=10,
        )

        if response.status_code == 401:
            return "Erro: chave da API do Brave inválida ou expirada."
        elif response.status_code == 422:
            print(f"[PESQUISA] Erro 422 — query rejeitada: '{query_limpa}'")
            return "Não consegui pesquisar isso. Tenta reformular a pergunta."
        elif response.status_code == 429:
            return "Limite de requisições da API do Brave atingido. Tente novamente em alguns segundos."
        elif not response.ok:
            return f"A API do Brave retornou erro {response.status_code}."

        dados = response.json()
        resultados = dados.get("web", {}).get("results", [])

        if not resultados:
            return f"Não encontrei nada sobre '{query_limpa}'."

        linhas = [f"Resultados da pesquisa sobre '{query_limpa}':\n"]
        for i, r in enumerate(resultados, 1):
            titulo = r.get("title", "Sem título")
            descricao = r.get("description", "Sem descrição")
            url = r.get("url", "")
            linhas.append(f"{i}. {titulo}\n   {descricao}\n   {url}\n")

        resumo = "\n".join(linhas)

        # Tenta pegar conteúdo completo da 1ª página útil
        conteudo = None
        fonte_usada = None
        for r in resultados[:3]:
            url = r.get("url", "")
            titulo = r.get("title", "")
            if not url:
                continue
            conteudo = _extrair_conteudo_pagina(url)
            if conteudo:
                fonte_usada = titulo
                break

        if conteudo:
            resumo += f"\n\nConteúdo detalhado de '{fonte_usada}':\n\n{conteudo}"
        else:
            resumo += "\n\n(Não foi possível acessar o conteúdo completo das páginas.)"

        return resumo

    except requests.exceptions.Timeout:
        return "A pesquisa demorou demais e deu timeout."
    except requests.exceptions.ConnectionError:
        return "Sem conexão com a internet para pesquisar."
    except requests.exceptions.RequestException as e:
        return f"Erro ao pesquisar: {e}"
    except Exception as e:
        return f"Erro inesperado na pesquisa: {e}"


# ─────────────────────────────────────────────────────────────────
# PONTO DE ENTRADA PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def pesquisar(query: str) -> str:
    """
    Ponto de entrada principal da pesquisa.

    Estratégia de fallback automático (ordem de prioridade):
      1. Playwright headless   → invisível, não mexe no seu navegador
      2. Extensão conectada    → abre abas no Brave (só se Playwright falhar)
      3. Brave Search API      → fallback sem navegador
    """
    query_limpa = _extrair_query(query).strip()
    if not query_limpa:
        return "Não entendi o que você quer pesquisar."

    # ── 1. Playwright headless (preferido — completamente invisível) ──
    resultado_headless = pesquisa_via_headless(query_limpa)
    if resultado_headless:
        return resultado_headless

    # ── 2. Extensão do navegador (abre abas no Brave) ──
    resultado_ext = pesquisa_via_extensao(query_limpa)
    if resultado_ext:
        return resultado_ext

    # ── 3. Brave Search API (fallback final) ──
    print("[PESQUISA] Navegador/headless indisponíveis, usando Brave API como fallback.")
    return pesquisa_via_brave(query_limpa)
