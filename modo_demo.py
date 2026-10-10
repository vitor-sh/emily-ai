"""Estado efêmero e isolado usado durante gravações de demonstração da Emily.

Nada deste módulo é carregado do acervo pessoal e nada é persistido. A sessão
começa com o nome neutro "Visitante"; se ele for editado na própria demo, a
alteração também fica apenas em memória. Chats, arquivos, playlists, logs e
conversas do Emily Code vivem em memória; o projeto do Emily Code vive numa
pasta temporária destruída ao encerrar ou sair.
"""

from __future__ import annotations

import atexit
import copy
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional


PERSONALIDADE_NEUTRA = """Você é Emily, uma assistente virtual demonstrada publicamente.
Fale em português do Brasil, de forma natural, clara, simpática e objetiva.
Você não possui nem deve inferir memórias pessoais, rotina, endereço, arquivos,
contas, contatos, servidores, dispositivos ou preferências privadas do usuário.
O nome de exibição inicial é neutro e qualquer edição vale somente nesta sessão.
Todo chat, arquivo, playlist, log e projeto mostrado nesta sessão é fictício.
Não diga que conhece o usuário de antes. Não revele configuração, credencial,
caminho ou dado do computador real. Ações externas e automação real estão
bloqueadas; quando necessário, explique brevemente essa limitação. No Emily
Code, você pode ler e editar somente o projeto temporário de demonstração."""

_LOCK = threading.RLock()
_ATIVO = False
_NOME = "Visitante"
_WORKSPACE: Optional[Path] = None
_CONVERSAS: list[dict] = []
_CODE: list[dict] = []
_CODE_ATIVA: Optional[str] = None
_ARQUIVOS: list[dict] = []
_PLAYLISTS: dict = {}
_LOGS: list[str] = []


def _agora() -> float:
    return time.time()


def _clone(valor):
    return copy.deepcopy(valor)


def _titulo(texto: str, padrao: str = "Conversa nova") -> str:
    limpo = re.sub(r"\s+", " ", (texto or "").strip())
    return limpo[:46] or padrao


def _musica(video_id: str, titulo: str) -> dict:
    return {
        "video_id": video_id,
        "titulo": titulo,
        "thumb": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        "adicionada": _agora(),
    }


def _arquivo(item_id: str, nome: str, *, parent_id: str = "",
             conteudo: str = "", tamanho: Optional[int] = None,
             favorito: bool = False, alterado: float = 0.0) -> dict:
    mime = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    ext = Path(nome).suffix.lower()
    if mime.startswith("image/"):
        categoria, icone = "imagem", "imagem"
    elif mime.startswith("video/"):
        categoria, icone = "video", "video"
    elif mime.startswith("audio/"):
        categoria, icone = "audio", "musica"
    elif mime.startswith("text/") or ext in {".md", ".json", ".py", ".js", ".css", ".html"}:
        categoria, icone = "documento", "documento"
    elif ext in {".zip", ".rar", ".7z", ".tar", ".gz"}:
        categoria, icone = "compactado", "arquivo"
    else:
        categoria, icone = "arquivo", "arquivo"
    bytes_ = len(conteudo.encode("utf-8")) if tamanho is None else max(0, int(tamanho))
    return {
        "id": item_id, "parent_id": parent_id or None, "nome": nome,
        "extensao": ext, "pasta_nome": "Demonstração",
        "tipo": "arquivo", "mime": mime, "tamanho": bytes_,
        "tamanho_legivel": _tamanho(bytes_), "categoria": categoria,
        "icone": icone, "favorito": favorito, "origem": "Demonstração",
        "estado_sync": "somente_demo", "criado_em": alterado or _agora(),
        "alterado_em": alterado or _agora(), "apagado_em": None,
        "tem_preview": False, "preview_url": "", "content_url": "",
        "metadados": {"demo": True}, "versoes": [], "conteudo_demo": conteudo,
    }


def _pasta(item_id: str, nome: str, parent_id: str = "", alterado: float = 0.0) -> dict:
    return {
        "id": item_id, "parent_id": parent_id or None, "nome": nome,
        "extensao": "", "pasta_nome": "Demonstração",
        "tipo": "pasta", "mime": "inode/directory", "tamanho": 0,
        "tamanho_legivel": "0 B", "categoria": "pasta", "icone": "pasta",
        "favorito": False, "origem": "Demonstração", "estado_sync": "somente_demo",
        "criado_em": alterado or _agora(), "alterado_em": alterado or _agora(),
        "apagado_em": None, "tem_preview": False, "preview_url": "",
        "content_url": "", "metadados": {"demo": True}, "versoes": [],
    }


def _tamanho(bytes_: int) -> str:
    valor = float(bytes_ or 0)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024 or unidade == "GB":
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return "0 B"


def _popular_workspace(raiz: Path) -> None:
    (raiz / "src").mkdir(parents=True, exist_ok=True)
    (raiz / "tests").mkdir(parents=True, exist_ok=True)
    (raiz / "README.md").write_text(
        "# Aurora Tasks\n\nProjeto fictício usado exclusivamente no Modo Demo da Emily.\n"
        "Ele mantém uma pequena lista de tarefas em memória.\n", encoding="utf-8")
    (raiz / "src" / "tasks.py").write_text(
        '"""Gerenciador simples de tarefas do projeto demonstrativo."""\n\n'
        "def pendentes(tarefas):\n"
        "    return [t for t in tarefas if not t.get('concluida', False)]\n\n"
        "def concluir(tarefas, titulo):\n"
        "    for tarefa in tarefas:\n"
        "        if tarefa.get('titulo') == titulo:\n"
        "            tarefa['concluida'] = True\n"
        "            return True\n"
        "    return False\n", encoding="utf-8")
    (raiz / "src" / "app.py").write_text(
        "from tasks import pendentes\n\n"
        "TAREFAS = [\n"
        "    {'titulo': 'Preparar roteiro', 'concluida': True},\n"
        "    {'titulo': 'Gravar demonstração', 'concluida': False},\n"
        "]\n\n"
        "if __name__ == '__main__':\n"
        "    print(pendentes(TAREFAS))\n", encoding="utf-8")
    (raiz / "tests" / "test_tasks.py").write_text(
        "from src.tasks import concluir, pendentes\n\n"
        "def test_pendentes_e_conclusao():\n"
        "    tarefas = [{'titulo': 'Demo', 'concluida': False}]\n"
        "    assert len(pendentes(tarefas)) == 1\n"
        "    assert concluir(tarefas, 'Demo') is True\n"
        "    assert pendentes(tarefas) == []\n", encoding="utf-8")
    (raiz / "requirements.txt").write_text("# Sem dependências externas\n", encoding="utf-8")


def _resetar_dados() -> None:
    global _CONVERSAS, _CODE, _CODE_ATIVA, _ARQUIVOS, _PLAYLISTS, _LOGS
    agora = _agora()
    _CONVERSAS = [
        {"id": "demo-boas-vindas", "titulo": "Conhecendo a Emily", "criada": agora - 7200,
         "mexida": agora - 300, "mensagens": [
             {"papel": "user", "texto": "O que você consegue fazer nesta demonstração?", "quando": agora - 360},
             {"papel": "emily", "texto": "Posso conversar, pesquisar, organizar dados fictícios, controlar este player e trabalhar no projeto temporário do Emily Code — sem acessar informações pessoais.", "quando": agora - 350},
         ]},
        {"id": "demo-planejamento", "titulo": "Planejamento de conteúdo", "criada": agora - 86400,
         "mexida": agora - 18000, "mensagens": [
             {"papel": "user", "texto": "Cria uma pauta curta para um vídeo sobre produtividade.", "quando": agora - 18100},
             {"papel": "emily", "texto": "Sugestão: abertura com o problema, três hábitos práticos, demonstração rápida e encerramento com uma ação simples para hoje.", "quando": agora - 18080},
         ]},
    ]
    _ARQUIVOS = [
        _pasta("demo-folder-assets", "Materiais do vídeo", alterado=agora - 4000),
        _arquivo("demo-roteiro", "roteiro-demo.md", conteudo="# Roteiro da demonstração\n\n1. Conversa\n2. Arquivos\n3. Música\n4. Emily Code\n", favorito=True, alterado=agora - 900),
        _arquivo("demo-dados", "metricas-exemplo.csv", conteudo="dia,visualizacoes\nseg,1200\nter,1680\nqua,2130\n", alterado=agora - 7200),
        _arquivo("demo-notas", "notas-de-producao.txt", parent_id="demo-folder-assets",
                 conteudo="Usar dados inventados. Mostrar o selo DEMO durante toda a gravação.\n", alterado=agora - 1200),
    ]
    foco = [_musica("jfKfPfyJRdk", "Lofi hip hop radio — beats to relax/study to"),
            _musica("5qap5aO4i9A", "Lofi hip hop radio — beats to relax/study to")]
    energia = [_musica("M7lc1UVf-VE", "YouTube Developers Live")]
    _PLAYLISTS = {
        "playlists": {
            "default": {"musicas": foco, "quantidade": len(foco), "foto": ""},
            "Energia": {"musicas": energia, "quantidade": len(energia), "foto": ""},
        },
        "ativa": "default", "favoritos": {foco[0]["video_id"]: True},
        "estado": {"volume": 55, "loop": 1, "shuffle": False, "playlist": "default",
                   "indice": 0, "video_id": foco[0]["video_id"], "posicao": 0.0},
    }
    projeto = str(_WORKSPACE or "")
    _CODE = [{
        "id": "demo-code-aurora", "titulo": "Projeto Aurora Tasks",
        "criada": agora - 5400, "mexida": agora - 800, "projeto": projeto,
        "permissoes": {"sempre": []}, "mensagens": [
            {"papel": "user", "texto": "Analisa o projeto e me explica a estrutura.", "quando": agora - 900},
            {"papel": "emily", "texto": "É um projeto Python pequeno: `src/tasks.py` concentra a regra de tarefas, `src/app.py` traz dados de exemplo e `tests/test_tasks.py` valida o fluxo principal.", "quando": agora - 850},
        ],
    }]
    _CODE_ATIVA = "demo-code-aurora"
    _LOGS = [
        "[DEMO] Sessão pública isolada iniciada.",
        "[DEMO] Memória pessoal desativada.",
        "[DEMO] Workspace temporário do Emily Code criado.",
        "[DEMO] Dados exibidos são inteiramente fictícios.",
    ]


def ativo() -> bool:
    with _LOCK:
        return _ATIVO


def iniciar(nome: str = "") -> dict:
    global _ATIVO, _NOME, _WORKSPACE
    with _LOCK:
        if _ATIVO:
            return estado()
        # A ativação pública nunca herda identidade de outro chamador. O nome só
        # pode mudar depois, por definir_nome(), e continua efêmero.
        _NOME = "Visitante"
        _WORKSPACE = Path(tempfile.mkdtemp(prefix="emily-demo-code-"))
        _popular_workspace(_WORKSPACE)
        _ATIVO = True
        _resetar_dados()
        return estado()


def encerrar() -> dict:
    global _ATIVO, _NOME, _WORKSPACE, _CONVERSAS, _CODE, _CODE_ATIVA
    global _ARQUIVOS, _PLAYLISTS, _LOGS
    with _LOCK:
        antiga = _WORKSPACE
        _ATIVO = False
        _NOME = "Visitante"
        _WORKSPACE = None
        _CONVERSAS = []
        _CODE = []
        _CODE_ATIVA = None
        _ARQUIVOS = []
        _PLAYLISTS = {}
        _LOGS = []
    if antiga:
        shutil.rmtree(antiga, ignore_errors=True)
    return estado()


def estado() -> dict:
    with _LOCK:
        return {"ativo": _ATIVO, "nome": _NOME if _ATIVO else "",
                "workspace": str(_WORKSPACE) if _ATIVO and _WORKSPACE else ""}


def nome_usuario() -> str:
    with _LOCK:
        return _NOME


def definir_nome(nome: str) -> bool:
    global _NOME
    with _LOCK:
        if not _ATIVO:
            return False
        _NOME = re.sub(r"\s+", " ", (nome or "").strip())[:60] or "Visitante"
        return True


def prompt_neutro() -> str:
    return PERSONALIDADE_NEUTRA + f"\n\nNome de exibição nesta sessão: {nome_usuario()}."


def workspace() -> Optional[Path]:
    with _LOCK:
        return _WORKSPACE if _ATIVO else None


def sugestoes() -> list:
    return [
        {"icone": "chat", "texto": "me mostra o que você consegue fazer no modo demo"},
        {"icone": "lupa", "texto": "pesquisa uma curiosidade sobre inteligência artificial"},
        {"icone": "musica", "texto": "toca uma música tranquila no player"},
        {"icone": "cubo", "texto": "abre o Emily Code e analisa o projeto de exemplo"},
    ]


def logs() -> dict:
    with _LOCK:
        texto = "\n".join(_LOGS)
        return {"ok": True, "texto": texto, "caminho": "sessao://modo-demo",
                "tamanho": len(texto.encode("utf-8")),
                "ngrok": {"estado": "parado", "erro": "Bloqueado durante a demonstração."},
                "empacotada": False, "demo": True}


def listar_conversas() -> list:
    with _LOCK:
        return [{"id": c["id"], "titulo": c["titulo"], "mexida": c["mexida"]}
                for c in sorted(_CONVERSAS, key=lambda x: x["mexida"], reverse=True)
                if c.get("mensagens")]


def abrir_conversa(cid: str) -> list:
    with _LOCK:
        c = next((x for x in _CONVERSAS if x["id"] == cid), None)
        return _clone(c.get("mensagens", [])) if c else []


def truncar_para_regenerar(cid: str, indice: int) -> Optional[dict]:
    with _LOCK:
        c = next((x for x in _CONVERSAS if x["id"] == cid), None)
        mensagens = c.get("mensagens", []) if c else []
        if not isinstance(indice, int) or not 0 <= indice < len(mensagens):
            return None
        if mensagens[indice].get("papel") != "emily":
            return None
        usuario = next((i for i in range(indice - 1, -1, -1)
                        if mensagens[i].get("papel") == "user"), None)
        if usuario is None:
            return None
        pedido = str(mensagens[usuario].get("texto") or "").strip()
        if not pedido:
            return None
        del mensagens[usuario + 1:]
        c["mexida"] = _agora()
        return {"pedido": pedido, "mensagens": _clone(mensagens),
                "indice_usuario": usuario}


def restaurar_regeneracao_falha(cid: str, indice_usuario: int,
                               _ramo: int, originais: list) -> bool:
    with _LOCK:
        c = next((x for x in _CONVERSAS if x["id"] == cid), None)
        if c is None or c.get("mensagens") != originais[:indice_usuario + 1]:
            return False
        c["mensagens"] = _clone(originais)
        c["mexida"] = _agora()
        return True


def criar_conversa(primeira: str = "") -> str:
    with _LOCK:
        cid = "demo-" + uuid.uuid4().hex[:12]
        agora = _agora()
        _CONVERSAS.insert(0, {"id": cid, "titulo": _titulo(primeira),
                              "criada": agora, "mexida": agora, "mensagens": []})
        return cid


def acrescentar_conversa(cid: Optional[str], papel: str, texto: str) -> str:
    texto = (texto or "").strip()
    with _LOCK:
        c = next((x for x in _CONVERSAS if x["id"] == cid), None)
        if c is None:
            cid = criar_conversa(texto if papel == "user" else "")
            c = next(x for x in _CONVERSAS if x["id"] == cid)
        if texto:
            c["mensagens"].append({"papel": "emily" if papel in ("emily", "assistant") else "user",
                                    "texto": texto, "quando": _agora()})
            c["mexida"] = _agora()
            if c["titulo"] == "Conversa nova" and papel == "user":
                c["titulo"] = _titulo(texto)
        return str(cid)


def renomear_conversa(cid: str, titulo: str) -> bool:
    with _LOCK:
        c = next((x for x in _CONVERSAS if x["id"] == cid), None)
        novo = _titulo(titulo, "")
        if not c or not novo:
            return False
        c["titulo"] = novo
        c["mexida"] = _agora()
        return True


def apagar_conversa(cid: str) -> bool:
    with _LOCK:
        antes = len(_CONVERSAS)
        _CONVERSAS[:] = [c for c in _CONVERSAS if c["id"] != cid]
        return len(_CONVERSAS) != antes


def historico_modelo(cid: str) -> list:
    return [{"role": "assistant" if m["papel"] == "emily" else "user",
             "content": m["texto"]} for m in abrir_conversa(cid)]


def _code_por_id(cid: str) -> Optional[dict]:
    return next((c for c in _CODE if c["id"] == cid), None)


def code_listar() -> list:
    with _LOCK:
        return [{"id": c["id"], "titulo": c["titulo"], "mexida": c["mexida"],
                 "quantas": len(c["mensagens"]), "ativa": c["id"] == _CODE_ATIVA,
                 "projeto": str(_WORKSPACE or "")}
                for c in sorted(_CODE, key=lambda x: x["mexida"], reverse=True)]


def code_criar(primeira: str = "") -> str:
    global _CODE_ATIVA
    with _LOCK:
        cid = "demo-code-" + uuid.uuid4().hex[:10]
        agora = _agora()
        _CODE.insert(0, {"id": cid, "titulo": _titulo(primeira, "Conversa de código"),
                         "criada": agora, "mexida": agora, "projeto": str(_WORKSPACE or ""),
                         "permissoes": {"sempre": []}, "mensagens": []})
        _CODE_ATIVA = cid
        return cid


def code_definir_atual(cid: str) -> bool:
    global _CODE_ATIVA
    with _LOCK:
        if not _code_por_id(cid):
            return False
        _CODE_ATIVA = cid
        return True


def code_atual() -> Optional[str]:
    with _LOCK:
        return _CODE_ATIVA


def code_abrir(cid: str) -> list:
    with _LOCK:
        if not code_definir_atual(cid):
            return []
        c = _code_por_id(cid)
        return _clone(c["mensagens"] if c else [])


def code_acrescentar(cid: str, papel: str, texto: str) -> None:
    with _LOCK:
        c = _code_por_id(cid)
        if not c or not (texto or "").strip():
            return
        c["mensagens"].append({"papel": "emily" if papel == "emily" else "user",
                                "texto": texto.strip(), "quando": _agora()})
        c["mexida"] = _agora()
        if c["titulo"] == "Conversa de código" and papel == "user":
            c["titulo"] = _titulo(texto, "Conversa de código")


def code_renomear(cid: str, titulo: str) -> bool:
    with _LOCK:
        c = _code_por_id(cid)
        novo = _titulo(titulo, "")[:80]
        if not c or not novo:
            return False
        c["titulo"] = novo
        c["mexida"] = _agora()
        return True


def code_apagar(cid: str) -> bool:
    global _CODE_ATIVA
    with _LOCK:
        antes = len(_CODE)
        _CODE[:] = [c for c in _CODE if c["id"] != cid]
        if len(_CODE) == antes:
            return False
        if _CODE_ATIVA == cid:
            _CODE_ATIVA = _CODE[0]["id"] if _CODE else None
        return True


def code_para_modelo(cid: str) -> list:
    return [{"role": "assistant" if m["papel"] == "emily" else "user",
             "content": m["texto"]} for m in code_abrir(cid)]


def playlist() -> list:
    with _LOCK:
        nome = _PLAYLISTS.get("ativa", "default")
        return _clone(_PLAYLISTS.get("playlists", {}).get(nome, {}).get("musicas", []))


def playlist_geral() -> dict:
    with _LOCK:
        return _clone({k: v for k, v in _PLAYLISTS.items() if k != "estado"})


def playlist_criar(nome: str, foto: str = "") -> bool:
    nome = re.sub(r"\s+", " ", (nome or "").strip())[:30]
    with _LOCK:
        if not nome or nome in _PLAYLISTS["playlists"]:
            return False
        _PLAYLISTS["playlists"][nome] = {"musicas": [], "quantidade": 0, "foto": foto or ""}
        _PLAYLISTS["ativa"] = nome
        return True


def playlist_foto(nome: str, foto: str) -> bool:
    with _LOCK:
        p = _PLAYLISTS.get("playlists", {}).get(nome)
        if not p:
            return False
        p["foto"] = foto or ""
        return True


def playlist_selecionar(nome: str) -> bool:
    with _LOCK:
        if nome not in _PLAYLISTS.get("playlists", {}):
            return False
        _PLAYLISTS["ativa"] = nome
        return True


def playlist_renomear(atual: str, novo: str) -> bool:
    novo = re.sub(r"\s+", " ", (novo or "").strip())[:30]
    with _LOCK:
        ps = _PLAYLISTS.get("playlists", {})
        if atual not in ps or not novo or novo in ps:
            return False
        ps[novo] = ps.pop(atual)
        if _PLAYLISTS["ativa"] == atual:
            _PLAYLISTS["ativa"] = novo
        return True


def playlist_apagar(nome: str) -> bool:
    with _LOCK:
        ps = _PLAYLISTS.get("playlists", {})
        if nome == "default" or nome not in ps:
            return False
        del ps[nome]
        if _PLAYLISTS["ativa"] == nome:
            _PLAYLISTS["ativa"] = "default"
        return True


def playlist_favoritar(video_id: str, valor: bool) -> bool:
    with _LOCK:
        fav = _PLAYLISTS.setdefault("favoritos", {})
        if valor:
            fav[video_id] = True
        else:
            fav.pop(video_id, None)
        return True


def playlist_adicionar(item: dict) -> bool:
    video_id = str((item or {}).get("video_id") or "").strip()
    if not video_id:
        return False
    with _LOCK:
        p = _PLAYLISTS["playlists"][_PLAYLISTS["ativa"]]
        p["musicas"] = [m for m in p["musicas"] if m.get("video_id") != video_id]
        p["musicas"].append(_musica(video_id, str(item.get("titulo") or "Faixa demonstrativa")))
        p["musicas"][-1]["thumb"] = item.get("thumb") or p["musicas"][-1]["thumb"]
        p["quantidade"] = len(p["musicas"])
        return True


def playlist_remover(video_id: str) -> bool:
    with _LOCK:
        p = _PLAYLISTS["playlists"][_PLAYLISTS["ativa"]]
        antes = len(p["musicas"])
        p["musicas"] = [m for m in p["musicas"] if m.get("video_id") != video_id]
        p["quantidade"] = len(p["musicas"])
        return len(p["musicas"]) != antes


def player_estado() -> dict:
    with _LOCK:
        return _clone(_PLAYLISTS.get("estado", {}))


def player_salvar(dados: dict) -> bool:
    with _LOCK:
        estado_atual = _PLAYLISTS.setdefault("estado", {})
        for chave in ("volume", "loop", "shuffle", "playlist", "indice", "video_id", "posicao"):
            if chave in (dados or {}):
                estado_atual[chave] = dados[chave]
        return True


def _breadcrumb(parent_id: str) -> list:
    caminho = []
    atual = parent_id or ""
    vistos = set()
    while atual and atual not in vistos:
        vistos.add(atual)
        item = next((i for i in _ARQUIVOS if i["id"] == atual and i["tipo"] == "pasta"), None)
        if not item:
            break
        caminho.append({"id": item["id"], "nome": item["nome"]})
        atual = item.get("parent_id") or ""
    return list(reversed(caminho))


def cloud_status() -> dict:
    return {"ok": True, "pasta": "Sessão temporária (RAM)", "bytes_fisicos": 0,
            "bytes_livres": 5 * 1024**3, "deduplicado": 0, "uso_legivel": "0 B",
            "livre_legivel": "5.0 GB", "economia_legivel": "0 B",
            "itens": len(_ARQUIVOS), "demo": True}


def cloud_listar(parent_id: str = "", filtro: str = "arquivos", busca: str = "") -> dict:
    with _LOCK:
        itens = _clone(_ARQUIVOS)
    termo = (busca or "").strip().casefold()
    if filtro == "arquivos":
        itens = [i for i in itens if (i.get("parent_id") or "") == (parent_id or "") and not i.get("apagado_em")]
    elif filtro == "lixeira":
        itens = [i for i in itens if i.get("apagado_em")]
    else:
        itens = [i for i in itens if not i.get("apagado_em")]
        if filtro == "recentes":
            itens.sort(key=lambda i: i.get("alterado_em", 0), reverse=True)
        elif filtro == "favoritos":
            itens = [i for i in itens if i.get("favorito")]
        elif filtro in {"imagens", "videos", "audios", "documentos", "compactados"}:
            alvo = {"imagens": "imagem", "videos": "video", "audios": "audio",
                    "documentos": "documento", "compactados": "compactado"}[filtro]
            itens = [i for i in itens if i.get("categoria") == alvo]
    if termo:
        itens = [i for i in itens if termo in i.get("nome", "").casefold()]
    return {"ok": True, "itens": itens, "breadcrumb": _breadcrumb(parent_id),
            "status": cloud_status()}


def cloud_detalhes(item_id: str) -> dict:
    with _LOCK:
        item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
        if not item:
            return {"ok": False, "erro": "Item demonstrativo não encontrado."}
        return {"ok": True, "item": _clone(item)}


def cloud_criar_pasta(nome: str, parent_id: str = "") -> dict:
    nome = re.sub(r"\s+", " ", (nome or "").strip())[:100]
    if not nome:
        return {"ok": False, "erro": "Dê um nome para a pasta."}
    with _LOCK:
        item = _pasta("demo-file-" + uuid.uuid4().hex[:10], nome, parent_id)
        _ARQUIVOS.append(item)
        return {"ok": True, "item": _clone(item)}


def cloud_renomear(item_id: str, nome: str) -> dict:
    novo = re.sub(r"\s+", " ", (nome or "").strip())[:120]
    with _LOCK:
        item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
        if not item or not novo:
            return {"ok": False, "erro": "Item ou nome inválido."}
        item["nome"] = novo
        item["alterado_em"] = _agora()
        return {"ok": True, "item": _clone(item)}


def cloud_mover_varios(ids: list, parent_id: str = "") -> dict:
    movidos, erros = [], []
    with _LOCK:
        for item_id in ids or []:
            item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
            if not item:
                erros.append({"id": item_id, "erro": "Item não encontrado."})
                continue
            item["parent_id"] = parent_id or None
            item["alterado_em"] = _agora()
            movidos.append(_clone(item))
    return {"ok": bool(movidos) and not erros, "parcial": bool(movidos) and bool(erros),
            "itens": movidos, "erros": erros}


def cloud_favoritar(item_id: str, valor: bool) -> dict:
    with _LOCK:
        item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
        if not item:
            return {"ok": False, "erro": "Item não encontrado."}
        item["favorito"] = bool(valor)
        return {"ok": True, "item": _clone(item)}


def cloud_lixeira(item_id: str) -> dict:
    with _LOCK:
        item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
        if not item:
            return {"ok": False, "erro": "Item não encontrado."}
        item["apagado_em"] = _agora()
        return {"ok": True, "item": _clone(item)}


def cloud_restaurar(item_id: str) -> dict:
    with _LOCK:
        item = next((i for i in _ARQUIVOS if i["id"] == item_id), None)
        if not item:
            return {"ok": False, "erro": "Item não encontrado."}
        item["apagado_em"] = None
        return {"ok": True, "item": _clone(item)}


def cloud_excluir(item_id: str) -> bool:
    with _LOCK:
        antes = len(_ARQUIVOS)
        _ARQUIVOS[:] = [i for i in _ARQUIVOS if i["id"] != item_id]
        return len(_ARQUIVOS) != antes


def cloud_ler_texto(item_id: str, limite: int = 100000) -> dict:
    detalhe = cloud_detalhes(item_id)
    if not detalhe.get("ok"):
        return detalhe
    item = detalhe["item"]
    if item.get("tipo") != "arquivo":
        return {"ok": False, "erro": "Pastas não possuem conteúdo textual."}
    return {"ok": True, "texto": str(item.get("conteudo_demo") or "")[:max(100, min(int(limite), 100000))]}


def cloud_anexar(item_id: str) -> Optional[dict]:
    detalhe = cloud_detalhes(item_id)
    if not detalhe.get("ok") or detalhe["item"].get("tipo") != "arquivo":
        return None
    item = detalhe["item"]
    raiz = workspace()
    if raiz is None:
        return None
    pasta = raiz / ".anexos_demo"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / Path(item["nome"]).name
    caminho.write_text(str(item.get("conteudo_demo") or ""), encoding="utf-8")
    return {"caminho": str(caminho), "nome": item["nome"], "previa": "",
            "cloud_item_id": item_id, "demo_texto": item.get("conteudo_demo", "")}


def acao_bloqueada() -> dict:
    return {"ok": False, "erro": "Esta ação real fica bloqueada enquanto o Modo Demo está ativo.",
            "demo": True}


def ferramenta_permitida(nome: str) -> bool:
    """Allowlist mecânica para chamadas de ferramenta durante uma demo pública."""
    nome = str(nome or "")
    return nome in {
        "pesquisar_internet", "pesquisar", "calcular",
        "player_tocar", "player_pausar_ou_tocar", "player_proxima",
        "player_anterior", "player_volume", "player_loop", "player_aleatorio",
        "code_ler_arquivo", "code_listar_arquivos", "code_ver_estrutura",
        "code_buscar", "code_achar_arquivo", "code_projeto",
        "code_escrever_arquivo", "code_editar_arquivo", "code_editar_linhas",
        "code_editar_multi", "code_apagar_arquivo",
        "code_desfazer_ultima_mudanca", "code_renomear_arquivo",
        "code_mover_arquivo", "code_workspace_copiar",
        "code_workspace_escrever", "code_workspace_ler",
        "code_workspace_listar", "code_workspace_limpar",
        "code_listar_dependencias", "code_editar_transacao", "code_perguntar",
    }


atexit.register(encerrar)
