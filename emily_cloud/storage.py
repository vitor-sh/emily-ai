"""Migração segura do acervo da Emily Cloud entre discos/pastas."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import sqlite3
from pathlib import Path

from . import core, location


def _tamanho_arvore(pasta: Path) -> int:
    """Tamanho somado sem seguir links. `os.scandir` é bem mais rápido que
    `Path.rglob` em árvores com muitos objetos (cada importação cria 2+)."""
    total = 0
    pilha = [str(pasta)]
    while pilha:
        atual = pilha.pop()
        try:
            with os.scandir(atual) as entradas:
                for entrada in entradas:
                    try:
                        if entrada.is_symlink():
                            continue
                        if entrada.is_dir(follow_symlinks=False):
                            pilha.append(entrada.path)
                        elif entrada.is_file(follow_symlinks=False):
                            total += entrada.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _mesmo_caminho(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return a.absolute() == b.absolute()


def _validar_destino(destino: Path) -> tuple[Path, int]:
    origem = core.BASE.absolute()
    destino = Path(destino).expanduser().absolute()
    if _mesmo_caminho(origem, destino):
        raise ValueError("Essa já é a pasta usada pela Emily Cloud.")
    try:
        destino.relative_to(origem)
        raise ValueError("O novo armazenamento não pode ficar dentro da pasta atual.")
    except ValueError as exc:
        if "dentro" in str(exc):
            raise
    try:
        origem.relative_to(destino)
        raise ValueError("A pasta atual não pode ficar dentro do novo armazenamento.")
    except ValueError as exc:
        if "dentro" in str(exc):
            raise
    if destino.exists() and any(destino.iterdir()):
        raise ValueError("A pasta de destino precisa estar vazia. Escolha outra pasta.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    teste = destino.parent / f".emily-cloud-write-{secrets.token_hex(5)}"
    try:
        teste.write_bytes(b"ok")
    except OSError as exc:
        raise ValueError(f"A pasta escolhida não permite gravação: {exc}") from exc
    finally:
        teste.unlink(missing_ok=True)
    necessario = _tamanho_arvore(origem) + 64 * 1024 * 1024
    livre = shutil.disk_usage(destino.parent).free
    if livre < necessario:
        raise ValueError(
            f"Espaço insuficiente no destino: são necessários pelo menos {necessario} bytes.")
    return destino, necessario


def planejar(destino: str) -> dict:
    alvo, necessario = _validar_destino(Path(destino))
    uso = shutil.disk_usage(alvo.parent)
    origem_disponivel = location.disponivel(core.BASE)
    return {
        "ok": True, "origem": str(core.BASE), "destino": str(alvo),
        "modo": "migrar" if origem_disponivel else "novo",
        "origem_disponivel": origem_disponivel,
        "bytes_migrar": _tamanho_arvore(core.BASE) if origem_disponivel else 0,
        "bytes_necessarios": necessario,
        "bytes_livres": uso.free,
    }


def _copiar_banco(destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(core.DB, timeout=30) as origem, sqlite3.connect(destino, timeout=30) as copia:
        origem.backup(copia)
        resultado = copia.execute("PRAGMA integrity_check").fetchone()
        if not resultado or resultado[0] != "ok":
            raise RuntimeError("A cópia do catálogo SQLite não passou na verificação de integridade.")


def _copiar_pasta(origem: Path, destino: Path) -> None:
    if origem.is_dir():
        shutil.copytree(origem, destino, dirs_exist_ok=True, copy_function=shutil.copy2)
    else:
        destino.mkdir(parents=True, exist_ok=True)


def _validar_objetos(base: Path) -> tuple[int, int]:
    banco = base / "cloud.db"
    with sqlite3.connect(banco) as con:
        hashes = [r[0] for r in con.execute(
            "SELECT DISTINCT hash FROM items WHERE hash<>'' UNION SELECT DISTINCT hash FROM versions WHERE hash<>''")]
    total = 0
    for hash_ in hashes:
        caminho = base / "objects" / hash_[:2] / hash_
        if not caminho.is_file():
            raise RuntimeError(f"Objeto ausente depois da migração: {hash_}.")
        digest = hashlib.sha256()
        with caminho.open("rb") as arquivo:
            while bloco := arquivo.read(1024 * 1024):
                digest.update(bloco)
        if digest.hexdigest() != hash_:
            raise RuntimeError(f"Objeto corrompido depois da migração: {hash_}.")
        total += caminho.stat().st_size
    return len(hashes), total


def _ativar_novo(destino: Path, origem: Path, preferencia_anterior: dict) -> dict:
    """Ativa um acervo vazio quando o armazenamento anterior está offline."""
    publicado = False
    try:
        with core._LOCK, core._PREVIEW_LOCK:
            if destino.exists():
                destino.rmdir()  # já foi validado como vazio
            destino.mkdir(parents=False, exist_ok=False)
            publicado = True
            location.salvar(destino)
            core.reconfigurar_base(destino, garantir=True)
            estado = core.status()
            return {
                "ok": True, "modo": "novo", "origem": str(origem),
                "destino": str(destino), "origem_removida": False,
                "objetos_validados": 0, "bytes_validados": 0,
                "aviso": (
                    "Novo armazenamento vazio ativado. Os arquivos do local anterior "
                    "não foram copiados porque o disco está desconectado; eles continuam "
                    "no disco antigo."
                ),
                "status": estado,
            }
    except Exception:
        location.restaurar_dados(preferencia_anterior)
        if core.BASE.absolute() != origem:
            core.reconfigurar_base(origem, garantir=False)
        if publicado:
            shutil.rmtree(destino, ignore_errors=True)
        raise


def migrar(destino: str, permitir_novo: bool = False) -> dict:
    if location.origem_configuracao() == "ambiente":
        raise ValueError(
            "EMILY_CLOUD_DIR está definido no ambiente. Remova essa variável para trocar pela interface.")
    alvo, _ = _validar_destino(Path(destino))
    origem = core.BASE.absolute()
    preferencia_anterior = location.dados_salvos()
    origem_disponivel = location.disponivel(origem)
    if not origem_disponivel and not permitir_novo:
        raise FileNotFoundError(
            "O armazenamento anterior ficou indisponível. Escolha novamente o destino "
            "para confirmar a criação de uma Emily Cloud vazia; os arquivos antigos "
            "permanecerão no disco desconectado.")
    temporario = alvo.parent / f".{alvo.name}.migrando-{secrets.token_hex(6)}"
    publicado = False
    core._MIGRACAO_DONO = __import__("threading").get_ident()
    core._MIGRACAO.clear()
    location.iniciar_migracao(origem, alvo)
    try:
        if not origem_disponivel:
            return _ativar_novo(alvo, origem, preferencia_anterior)
        estado_antes = core.status()
        with core._LOCK, core._PREVIEW_LOCK:
            temporario.mkdir(parents=False, exist_ok=False)
            _copiar_banco(temporario / "cloud.db")
            _copiar_pasta(core.OBJECTS, temporario / "objects")
            _copiar_pasta(core.PREVIEWS, temporario / "previews")
            _copiar_pasta(core.STAGING, temporario / "staging")
            objetos, bytes_objetos = _validar_objetos(temporario)
            if alvo.exists():
                alvo.rmdir()  # já foi validado como vazio
            os.replace(temporario, alvo)
            publicado = True
            location.salvar(alvo)
            core.reconfigurar_base(alvo, garantir=True)
            estado_depois = core.status()
            chaves = ("itens", "arquivos", "lixeira", "bytes_logicos", "bytes_fisicos")
            if any(estado_antes[k] != estado_depois[k] for k in chaves):
                location.restaurar_dados(preferencia_anterior)
                core.reconfigurar_base(origem, garantir=True)
                shutil.rmtree(alvo, ignore_errors=True)
                raise RuntimeError("O catálogo mudou durante a migração; a origem foi restaurada.")
            removida = True
            aviso = ""
            try:
                shutil.rmtree(origem)
            except OSError as exc:
                removida = False
                aviso = f"O novo local já está ativo, mas não consegui apagar a pasta antiga: {exc}"
            return {
                "ok": True, "origem": str(origem), "destino": str(alvo),
                "origem_removida": removida, "aviso": aviso,
                "objetos_validados": objetos, "bytes_validados": bytes_objetos,
                "status": estado_depois,
            }
    except Exception:
        location.restaurar_dados(preferencia_anterior)
        if core.BASE.absolute() != origem:
            core.reconfigurar_base(origem, garantir=origem_disponivel)
        shutil.rmtree(temporario, ignore_errors=True)
        if publicado:
            shutil.rmtree(alvo, ignore_errors=True)
        raise
    finally:
        core._MIGRACAO_DONO = None
        core._MIGRACAO.set()
        location.finalizar_migracao()