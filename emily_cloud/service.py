"""Fachada de alto nível da Emily Cloud para UI, ferramentas e integrações."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Optional

from . import core


def tamanho_legivel(bytes_: int) -> str:
    valor = float(bytes_ or 0)
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if valor < 1024 or unidade == "TB":
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return "0 B"


def destino_conhecido(nome: str = "downloads") -> Path:
    bruto = (nome or "downloads").strip()
    caminho = Path(bruto).expanduser()
    if caminho.is_absolute():
        return caminho
    chave = bruto.lower()
    mapa = {
        "downloads": Path.home() / "Downloads",
        "download": Path.home() / "Downloads",
        "desktop": Path.home() / ("Desktop" if (Path.home() / "Desktop").exists() else "Área de Trabalho"),
        "area de trabalho": Path.home() / ("Desktop" if (Path.home() / "Desktop").exists() else "Área de Trabalho"),
        "área de trabalho": Path.home() / ("Desktop" if (Path.home() / "Desktop").exists() else "Área de Trabalho"),
        "documentos": Path.home() / ("Documents" if (Path.home() / "Documents").exists() else "Documentos"),
        "imagens": Path.home() / ("Pictures" if (Path.home() / "Pictures").exists() else "Imagens"),
        "videos": Path.home() / ("Videos" if (Path.home() / "Videos").exists() else "Vídeos"),
        "vídeos": Path.home() / ("Videos" if (Path.home() / "Videos").exists() else "Vídeos"),
        "musicas": Path.home() / ("Music" if (Path.home() / "Music").exists() else "Músicas"),
        "músicas": Path.home() / ("Music" if (Path.home() / "Music").exists() else "Músicas"),
    }
    if chave not in mapa:
        raise ValueError("Destino desconhecido. Use Downloads, Desktop, Documentos, Imagens, Vídeos ou Músicas.")
    return mapa[chave]


def item_ui(item: dict) -> dict:
    dado = dict(item)
    dado["tamanho_legivel"] = tamanho_legivel(dado.get("tamanho", 0))
    dado["categoria"] = categoria(dado)
    dado["icone"] = icone(dado)
    dado["preview_url"] = f"emily-cloud://preview/{dado['id']}" if dado.get("tem_preview") else ""
    dado["content_url"] = f"emily-cloud://content/{dado['id']}" if dado.get("tipo") == "arquivo" else ""
    # Caminho original é metadado interno; a interface trabalha sempre por ID.
    dado.get("metadados", {}).pop("caminho_original", None)
    return dado


def categoria(item: dict) -> str:
    if item.get("tipo") == "pasta":
        return "pasta"
    mime = item.get("mime", "")
    ext = Path(item.get("nome", "")).suffix.lower()
    if mime.startswith("image/"):
        return "imagem"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("text/") or mime == "application/pdf":
        return "documento"
    if ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"):
        return "compactado"
    if ext in (".exe", ".msi", ".bat", ".cmd", ".sh", ".appimage"):
        return "executavel"
    return "arquivo"


def icone(item: dict) -> str:
    return {
        "pasta": "pasta", "imagem": "imagem", "video": "video",
        "audio": "musica", "documento": "documento", "compactado": "arquivo",
        "executavel": "alerta", "arquivo": "arquivo",
    }[categoria(item)]


def listar(parent_id: Optional[str] = None, filtro: str = "arquivos",
           busca: str = "", limite: int = 200) -> dict:
    core.agendar_previews_pendentes()
    itens = core.listar(parent_id, filtro, busca, limite)
    enriquecidos = []
    for item in itens:
        try:
            if item["tipo"] == "arquivo":
                item["tem_preview"] = core.caminho_preview(item["id"]) is not None
            enriquecidos.append(item_ui(item))
        except (ValueError, FileNotFoundError):
            continue
    breadcrumb = []
    atual = parent_id
    vistos = set()
    while atual and atual not in vistos:
        vistos.add(atual)
        try:
            pasta = core.detalhes(atual)
        except ValueError:
            break
        breadcrumb.append({"id": pasta["id"], "nome": pasta["nome"]})
        atual = pasta.get("parent_id")
    breadcrumb.reverse()
    return {"ok": True, "itens": enriquecidos, "breadcrumb": breadcrumb,
            "status": status()}


def status() -> dict:
    dado = core.status()
    dado["uso_legivel"] = tamanho_legivel(dado["bytes_fisicos"])
    dado["livre_legivel"] = tamanho_legivel(dado["bytes_livres"])
    dado["economia_legivel"] = tamanho_legivel(dado["deduplicado"])
    return dado


def importar_varios(caminhos: list[str], parent_id: Optional[str] = None,
                    origem: str = "manual", url_origem: str = "") -> dict:
    itens, erros = [], []
    for caminho in caminhos or []:
        try:
            itens.append(item_ui(core.importar(
                caminho, parent_id=parent_id, origem=origem, url_origem=url_origem)))
        except Exception as exc:  # lote continua mesmo se um arquivo falhar
            erros.append({"caminho": os.path.basename(str(caminho)), "erro": str(exc)})
    return {"ok": bool(itens) and not erros, "itens": itens, "erros": erros}


def importar_e_sincronizar(caminhos: list[str], parent_id: Optional[str] = None,
                           sincronizar: bool = False, origem: str = "pedido_emily") -> dict:
    """Importa até 100 caminhos e, opcionalmente, sincroniza cada raiz com S3."""
    itens, erros, vistos = [], [], set()
    for bruto in (caminhos or [])[:100]:
        caminho = str(bruto or "").strip()
        chave = os.path.normcase(os.path.abspath(os.path.expanduser(caminho))) if caminho else ""
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        try:
            item = core.importar(caminho, parent_id=parent_id, origem=origem)
            registro = item_ui(item)
            if sincronizar:
                try:
                    registro["sync"] = core.sincronizar(item["id"])
                    registro = item_ui(core.detalhes(item["id"])) | {"sync": registro["sync"]}
                except Exception as exc:
                    registro["sync"] = {"ok": False, "erro": str(exc)}
                    erros.append({"caminho": os.path.basename(caminho), "erro": f"S3: {exc}",
                                  "item_id": item["id"]})
            itens.append(registro)
        except Exception as exc:
            erros.append({"caminho": os.path.basename(caminho), "erro": str(exc)})
    sincronizados = sum(
        1 for item in itens if item.get("estado_sync") == "sincronizado"
        or item.get("sync", {}).get("ok") is True)
    return {
        "ok": bool(itens) and not erros,
        "parcial": bool(itens) and bool(erros),
        "itens": itens, "erros": erros,
        "importados": len(itens), "sincronizados": sincronizados,
    }


def detalhes(item_id: str) -> dict:
    return item_ui(core.detalhes(item_id))


def criar_pasta(nome: str, parent_id: Optional[str] = None) -> dict:
    return item_ui(core.criar_pasta(nome, parent_id))


def renomear(item_id: str, nome: str) -> dict:
    return item_ui(core.renomear(item_id, nome))


def mover(item_id: str, parent_id: Optional[str] = None) -> dict:
    return item_ui(core.mover(item_id, parent_id))


def favoritar(item_id: str, valor: bool = True) -> dict:
    return item_ui(core.favoritar(item_id, valor))


def lixeira(item_id: str) -> dict:
    return item_ui(core.mover_para_lixeira(item_id))


def restaurar(item_id: str) -> dict:
    return item_ui(core.restaurar(item_id))


def excluir(item_id: str) -> bool:
    return core.excluir_definitivamente(item_id)


def exportar(item_id: str, destino: str = "downloads") -> dict:
    return core.exportar(item_id, str(destino_conhecido(destino)))


def ler_texto(item_id: str, max_chars: int = 40000) -> str:
    item = core.detalhes(item_id)
    mime = item.get("mime", "")
    permitidos = mime.startswith("text/") or Path(item["nome"]).suffix.lower() in (
        ".json", ".xml", ".yaml", ".yml", ".md", ".py", ".js", ".css", ".html",
        ".ini", ".cfg", ".toml", ".log", ".csv", ".kt", ".kts", ".java", ".ts",
        ".tsx", ".jsx", ".c", ".cc", ".cpp", ".h", ".hpp", ".sql", ".gradle",
        ".properties", ".conf", ".env",
    )
    if not permitidos:
        raise ValueError("Esse formato não é textual e não pode ser lido diretamente.")
    limite = max(100, min(int(max_chars), 100000))
    dados = core.caminho_conteudo(item_id).read_bytes()[: limite * 4]
    texto = dados.decode("utf-8", errors="replace")
    return texto[:limite]


def resumo_busca(texto: str) -> str:
    itens = core.buscar(texto, 20)
    if not itens:
        return f"Não encontrei nada na Emily Cloud com '{texto}'."
    linhas = [f"Encontrei {len(itens)} item(ns) na Emily Cloud:"]
    for item in itens:
        linhas.append(f"- ID {item['id']}: {item['nome']} ({categoria(item)}, {tamanho_legivel(item['tamanho'])})")
    return "\n".join(linhas)