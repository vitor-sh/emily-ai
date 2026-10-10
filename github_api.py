"""
github_api.py — Camada de acesso à API do GitHub da Emily.

Mesmo padrão do pesquisa.py: lê a token do .env, monta as chamadas REST e
devolve textos prontos pra ferramenta mostrar. Nenhuma lógica de "qual
ferramenta" aqui — isso é do ferramentas.py.

Requisitos:
- .env com GITHUB_TOKEN=<personal access token> (escopo repo pra ler/escrever,
  delete_repo pra apagar repositório, etc.)
"""

from __future__ import annotations

import base64
import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_TOKEN = (os.getenv("GITHUB_TOKEN") or os.getenv("BROXAS_GITHUB_TOKEN") or "").strip()
GITHUB_USUARIO = os.getenv("GITHUB_USUARIO", "").strip()

_BASE = "https://api.github.com"
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class ErroGitHub(Exception):
    """Erro da API do GitHub com mensagem pronta pro usuário."""


def configurado() -> bool:
    return bool(GITHUB_TOKEN)


def _cabecalhos() -> dict:
    return {**_HEADERS, "Authorization": f"Bearer {GITHUB_TOKEN}"}


def _api(method: str, path: str, corpo: Optional[dict] = None) -> dict:
    """Chamada REST com a token. Devolve o JSON da resposta ou {}."""
    if not configurado():
        raise ErroGitHub(
            "GitHub não configurado. Adicione GITHUB_TOKEN no .env "
            "(Personal Access Token) e reinicie a Emily."
        )
    url = _BASE + path
    try:
        resp = requests.request(
            method, url, headers=_cabecalhos(),
            json=corpo, timeout=30,
        )
    except requests.RequestException as e:
        raise ErroGitHub(f"Não consegui falar com o GitHub: {e}") from e

    if resp.status_code in (200, 201):
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {}
    if resp.status_code == 204:
        return {}

    try:
        msg = resp.json().get("message", "") or ""
    except ValueError:
        msg = ""
    if resp.status_code == 401:
        raise ErroGitHub("Token do GitHub inválida ou expirada. Confere o GITHUB_TOKEN no .env.")
    if resp.status_code == 403:
        raise ErroGitHub(
            f"GitHub negou acesso (403). "
            f"{msg or 'A token pode não ter o escopo pra essa ação.'}"
        )
    if resp.status_code == 404:
        raise ErroGitHub(f"Não achei isso no GitHub (404): {msg or path}")
    raise ErroGitHub(f"GitHub respondeu {resp.status_code}: {msg or 'erro desconhecido'}")


def _texto_de_item(item: dict) -> str:
    """Nome + descrição de um repo, numa linha legível."""
    nome = item.get("name") or item.get("full_name") or ""
    desc = (item.get("description") or "").strip()
    privado = " (privado)" if item.get("private") else ""
    return f"- {nome}{privado}" + (f": {desc}" if desc else "")


def _amigavel(func):
    """Captura ErroGitHub e devolve o texto — a ferramenta não pode levantar
    exceção (o laço contaria como 'falhou'). Token ausente, 403, 404, tudo vira
    uma resposta de texto clara pro Vitor."""
    from functools import wraps

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ErroGitHub as e:
            return str(e)
        except Exception as e:  # noqa: BLE001
            return f"Não consegui (erro inesperado): {type(e).__name__}: {e}"
    return wrapper


# ═════════════════════════════════════════════════════════════════
# REPOSITÓRIOS
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_repos() -> str:
    """Lista os repositórios do usuário autenticado."""
    dados = _api("GET", "/user/repos?per_page=100&sort=updated")
    if not dados:
        return "Você não tem nenhum repositório, ou o GitHub não devolveu nada."
    linhas = [_texto_de_item(item) for item in dados if isinstance(item, dict)]
    return "Seus repositórios:\n" + "\n".join(linhas)


@_amigavel
def ver_repo(repo: str) -> str:
    """Detalhes de um repositório específico (dono já incluído no nome)."""
    dados = _api("GET", f"/repos/{repo}")
    linhas = [
        f"Nome: {dados.get('full_name', repo)}",
        f"Descrição: {dados.get('description') or '(sem descrição)'}",
        f"Linguagem: {dados.get('language') or 'não definida'}",
        f"Stars: {dados.get('stargazers_count', 0)}  Forks: {dados.get('forks_count', 0)}",
        f"Criado: {dados.get('created_at', '?')[:10]}  Atualizado: {dados.get('updated_at', '?')[:10]}",
        f"URL: {dados.get('html_url', '')}",
        f"Padrão: {dados.get('default_branch', 'main')}  Privado: {bool(dados.get('private'))}",
    ]
    return "\n".join(linhas)


@_amigavel
def criar_repo(nome: str, descricao: str = "", privado: bool = False) -> str:
    corpo = {"name": nome, "private": bool(privado)}
    if descricao.strip():
        corpo["description"] = descricao.strip()
    dados = _api("POST", "/user/repos", corpo)
    url = dados.get("html_url", f"https://github.com/{nome}")
    visib = "privado" if dados.get("private") else "público"
    return f"Repositório '{nome}' criado ({visib}). {url}"


@_amigavel
def apagar_repo(repo: str) -> str:
    _api("DELETE", f"/repos/{repo}")
    return f"Repositório '{repo}' apagado do GitHub."


# ═════════════════════════════════════════════════════════════════
# ARQUIVOS E CONTEÚDO
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_arquivos(repo: str, caminho: str = "", ref: str = "") -> str:
    path = f"/repos/{repo}/contents"
    if caminho.strip():
        path += "/" + caminho.strip().strip("/")
    if ref.strip():
        path += "?ref=" + ref.strip()
    dados = _api("GET", path)
    if not dados:
        return f"'{caminho or '/'}' está vazio ou não existe no repo '{repo}'."
    linhas = []
    for item in (dados if isinstance(dados, list) else [dados]):
        if not isinstance(item, dict):
            continue
        tipo = "📁" if item.get("type") == "dir" else "📄"
        linhas.append(f"{tipo} {item.get('name', '')}")
    return (f"Conteúdo de '{caminho or '/'}' em '{repo}':\n" + "\n".join(linhas)) if linhas else \
        f"'{caminho or '/'}' não tem nada pra listar."


@_amigavel
def ler_arquivo(repo: str, caminho: str, ref: str = "") -> str:
    path = f"/repos/{repo}/contents/{caminho.strip().strip('/')}"
    if ref.strip():
        path += "?ref=" + ref.strip()
    dados = _api("GET", path)
    if not isinstance(dados, dict):
        return f"Não consegui ler '{caminho}'."
    if dados.get("type") == "file" and dados.get("content"):
        try:
            conteudo = base64.b64decode(dados["content"]).decode("utf-8", errors="replace")
        except Exception:
            conteudo = "(arquivo binário — não dá pra mostrar como texto)"
    else:
        conteudo = "(não é um arquivo de texto simples)"
    tamanho = dados.get("size", 0)
    return f"'{caminho}' em '{repo}' ({tamanho} bytes):\n\n{conteudo}"


@_amigavel
def escrever_arquivo(repo: str, caminho: str, conteudo: str,
                     mensagem: str = "", branch: str = "main") -> str:
    """Cria ou atualiza um arquivo. Lê o sha atual pra poder substituir."""
    path = f"/repos/{repo}/contents/{caminho.strip().strip('/')}"
    corpo: dict = {
        "message": mensagem.strip() or f"Atualiza {caminho}",
        "content": base64.b64encode(conteudo.encode("utf-8")).decode("utf-8"),
        "branch": branch.strip() or "main",
    }
    try:
        atual = _api("GET", path)
        if isinstance(atual, dict) and atual.get("sha"):
            corpo["sha"] = atual["sha"]
    except ErroGitHub:
        pass  # arquivo ainda não existe — cria sem sha
    dados = _api("PUT", path, corpo)
    commit = ""
    if isinstance(dados, dict) and dados.get("commit", {}).get("sha"):
        commit = dados["commit"]["sha"][:7]
    return f"Arquivo '{caminho}' salvo em '{repo}' (commit {commit})."


@_amigavel
def apagar_arquivo(repo: str, caminho: str, mensagem: str = "",
                   branch: str = "main") -> str:
    path = f"/repos/{repo}/contents/{caminho.strip().strip('/')}"
    atual = _api("GET", path)
    if not isinstance(atual, dict) or not atual.get("sha"):
        return f"Não achei o arquivo '{caminho}' em '{repo}'."
    corpo = {
        "message": mensagem.strip() or f"Apaga {caminho}",
        "sha": atual["sha"],
        "branch": branch.strip() or "main",
    }
    _api("DELETE", path, corpo)
    return f"Arquivo '{caminho}' apagado de '{repo}'."


@_amigavel
def ver_readme(repo: str) -> str:
    try:
        dados = _api("GET", f"/repos/{repo}/readme")
    except ErroGitHub as e:
        return f"{e}"
    if isinstance(dados, dict) and dados.get("content"):
        try:
            return base64.b64decode(dados["content"]).decode("utf-8", errors="replace")
        except Exception:
            return "(README não é texto simples)"
    return "(sem README)"


# ═════════════════════════════════════════════════════════════════
# COMMITS
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_commits(repo: str, branch: str = "") -> str:
    path = f"/repos/{repo}/commits?per_page=30"
    if branch.strip():
        path += "&sha=" + branch.strip()
    dados = _api("GET", path)
    if not isinstance(dados, list):
        return f"Não achei commits em '{repo}'."
    linhas = []
    for c in dados:
        if not isinstance(c, dict):
            continue
        sha = (c.get("sha") or "")[:7]
        msg = (c.get("commit", {}).get("message") or "").split("\n")[0]
        autor = (c.get("commit", {}).get("author", {}).get("name")) or "?"
        data = (c.get("commit", {}).get("author", {}).get("date") or "")[:10]
        linhas.append(f"{sha} {data} {autor}: {msg}")
    return f"Commits de '{repo}':\n" + "\n".join(linhas) if linhas else "Nenhum commit."


# ═════════════════════════════════════════════════════════════════
# BRANCHES
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_branches(repo: str) -> str:
    dados = _api("GET", f"/repos/{repo}/branches?per_page=100")
    if not isinstance(dados, list):
        return f"Não achei branches em '{repo}'."
    nomes = [b.get("name") for b in dados if isinstance(b, dict) and b.get("name")]
    return f"Branches de '{repo}':\n" + "\n".join(f"- {n}" for n in nomes) if nomes else "Sem branches."


@_amigavel
def criar_branch(repo: str, nome: str, de: str = "main") -> str:
    # Primeiro pega o sha do commit de onde a branch vai nascer.
    try:
        refs = _api("GET", f"/repos/{repo}/git/ref/heads/{de}")
    except ErroGitHub:
        refs = _api("GET", f"/repos/{repo}/git/ref/heads/main")
    sha = refs.get("object", {}).get("sha") if isinstance(refs, dict) else None
    if not sha:
        return f"Não achei a branch de origem '{de}' em '{repo}'."
    _api("POST", f"/repos/{repo}/git/refs",
         {"ref": f"refs/heads/{nome}", "sha": sha})
    return f"Branch '{nome}' criada em '{repo}' (a partir de '{de}')."


# ═════════════════════════════════════════════════════════════════
# PULL REQUESTS
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_prs(repo: str, estado: str = "open") -> str:
    dados = _api("GET", f"/repos/{repo}/pulls?state={estado}&per_page=30")
    if not isinstance(dados, list):
        return f"Não achei PRs em '{repo}'."
    linhas = []
    for p in dados:
        if not isinstance(p, dict):
            continue
        n = p.get("number")
        titulo = p.get("title") or "?"
        estado_txt = p.get("state", "?")
        linhas.append(f"#{n} [{estado_txt}] {titulo}")
    return f"PRs ({estado}) de '{repo}':\n" + "\n".join(linhas) if linhas else \
        f"Nenhuma PR {estado} em '{repo}'."


@_amigavel
def ver_pr(repo: str, numero: int) -> str:
    dados = _api("GET", f"/repos/{repo}/pulls/{numero}")
    if not isinstance(dados, dict):
        return f"Não achei a PR #{numero} em '{repo}'."
    linhas = [
        f"PR #{dados.get('number')}: {dados.get('title', '')}",
        f"Estado: {dados.get('state', '?')}",
        f"De {dados.get('head', {}).get('ref', '?')} → {dados.get('base', {}).get('ref', '?')}",
        f"Autor: {dados.get('user', {}).get('login', '?')}",
        f"Criada: {dados.get('created_at', '?')[:10]}",
    ]
    if dados.get("body"):
        linhas.append(f"\nDescrição:\n{dados['body']}")
    return "\n".join(linhas)


@_amigavel
def criar_pr(repo: str, titulo: str, head: str, base: str,
             corpo: str = "") -> str:
    payload = {"title": titulo, "head": head, "base": base}
    if corpo.strip():
        payload["body"] = corpo.strip()
    dados = _api("POST", f"/repos/{repo}/pulls", payload)
    url = dados.get("html_url", "") if isinstance(dados, dict) else ""
    return f"PR #{dados.get('number')} aberta em '{repo}': {titulo} {url}"


@_amigavel
def mesclar_pr(repo: str, numero: int) -> str:
    try:
        _api("PUT", f"/repos/{repo}/pulls/{numero}/merge")
    except ErroGitHub as e:
        return f"{e}"
    return f"PR #{numero} mesclada em '{repo}'."


@_amigavel
def fechar_pr(repo: str, numero: int) -> str:
    dados = _api("PATCH", f"/repos/{repo}/pulls/{numero}", {"state": "closed"})
    return f"PR #{numero} fechada em '{repo}'." if isinstance(dados, dict) else "Não consegui fechar a PR."


# ═════════════════════════════════════════════════════════════════
# ISSUES
# ═════════════════════════════════════════════════════════════════

@_amigavel
def listar_issues(repo: str, estado: str = "open") -> str:
    dados = _api("GET", f"/repos/{repo}/issues?state={estado}&per_page=30")
    if not isinstance(dados, list):
        return f"Não achei issues em '{repo}'."
    linhas = []
    for i in dados:
        if not isinstance(i, dict):
            continue
        if i.get("pull_request"):
            continue  # issues no GitHub incluem PRs; pula
        n = i.get("number")
        titulo = i.get("title") or "?"
        linhas.append(f"#{n} {titulo}")
    return f"Issues ({estado}) de '{repo}':\n" + "\n".join(linhas) if linhas else \
        f"Nenhuma issue {estado} em '{repo}'."


@_amigavel
def criar_issue(repo: str, titulo: str, corpo: str = "") -> str:
    payload = {"title": titulo}
    if corpo.strip():
        payload["body"] = corpo.strip()
    dados = _api("POST", f"/repos/{repo}/issues", payload)
    url = dados.get("html_url", "") if isinstance(dados, dict) else ""
    return f"Issue #{dados.get('number')} aberta em '{repo}': {titulo} {url}"


@_amigavel
def fechar_issue(repo: str, numero: int) -> str:
    dados = _api("PATCH", f"/repos/{repo}/issues/{numero}", {"state": "closed"})
    return f"Issue #{numero} fechada em '{repo}'." if isinstance(dados, dict) else "Não consegui fechar a issue."


@_amigavel
def comentar_issue(repo: str, numero: int, comentario: str) -> str:
    dados = _api("POST", f"/repos/{repo}/issues/{numero}/comments",
                 {"body": comentario})
    return f"Comentário adicionado na issue #{numero} de '{repo}'." if isinstance(dados, dict) else "Não consegui comentar."


# ═════════════════════════════════════════════════════════════════
# USUÁRIO
# ═════════════════════════════════════════════════════════════════

@_amigavel
def ver_usuario() -> str:
    dados = _api("GET", "/user")
    if not isinstance(dados, dict):
        return "Não consegui ver seu usuário do GitHub."
    linhas = [
        f"Login: {dados.get('login', '?')}",
        f"Nome: {dados.get('name') or '(sem nome)'}",
        f"Repos públicos: {dados.get('public_repos', 0)}  Seguidores: {dados.get('followers', 0)}",
        f"Perfil: {dados.get('html_url', '')}",
    ]
    return "\n".join(linhas)


@_amigavel
def listar_repos_usuario(usuario: str) -> str:
    """Repos de QUALQUER usuário do GitHub, não só o autenticado."""
    dados = _api("GET", f"/users/{usuario}/repos?per_page=100&sort=updated")
    if not isinstance(dados, list):
        return f"Não achei repositórios do usuário '{usuario}'."
    linhas = [_texto_de_item(item) for item in dados if isinstance(item, dict)]
    return f"Repositórios de '{usuario}':\n" + "\n".join(linhas) if linhas else \
        f"'{usuario}' não tem repositórios públicos."
