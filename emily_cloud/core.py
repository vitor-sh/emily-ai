"""Núcleo persistente e seguro da Emily Cloud.

Os metadados vivem em SQLite e os bytes em armazenamento endereçado por SHA-256.
Mover/renomear é instantâneo, conteúdo repetido ocupa espaço uma vez e excluir
um item não remove um objeto ainda referenciado por outra versão/item.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Iterable, Optional

from . import location


_LOCK = threading.RLock()
_PREVIEW_LOCK = threading.RLock()
_MIGRACAO = threading.Event()
_MIGRACAO.set()
_MIGRACAO_DONO: int | None = None
_PREVIEW_THREAD = None
_PREVIEW_FALHOU: set[str] = set()
_CHUNK = 1024 * 1024
_NOME_INVALIDO = re.compile(r"[\x00-\x1f<>:\"/\\|?*]")


def _pasta_padrao() -> Path:
    return location.pasta_ativa()


BASE = _pasta_padrao()
DB = BASE / "cloud.db"
OBJECTS = BASE / "objects"
PREVIEWS = BASE / "previews"
STAGING = BASE / "staging"


def reconfigurar_base(pasta: Path, garantir: bool = True) -> Path:
    """Troca os caminhos usados por este processo depois de uma migração."""
    global BASE, DB, OBJECTS, PREVIEWS, STAGING
    anteriores = BASE, DB, OBJECTS, PREVIEWS, STAGING
    nova = Path(pasta).expanduser().absolute()
    BASE, DB = nova, nova / "cloud.db"
    OBJECTS, PREVIEWS, STAGING = nova / "objects", nova / "previews", nova / "staging"
    try:
        if garantir:
            _garantir()
    except Exception:
        BASE, DB, OBJECTS, PREVIEWS, STAGING = anteriores
        raise
    _PREVIEW_FALHOU.clear()
    return BASE


def _garantir() -> None:
    if not location.disponivel(BASE):
        raise FileNotFoundError(
            f"O disco da Emily Cloud não está disponível: {BASE}. Conecte/monte o disco e tente novamente.")
    for pasta in (BASE, OBJECTS, PREVIEWS, STAGING):
        pasta.mkdir(parents=True, exist_ok=True)
    with _conexao() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            parent_id TEXT REFERENCES items(id),
            nome TEXT NOT NULL,
            tipo TEXT NOT NULL CHECK(tipo IN ('arquivo','pasta')),
            mime TEXT NOT NULL DEFAULT '',
            tamanho INTEGER NOT NULL DEFAULT 0,
            hash TEXT NOT NULL DEFAULT '',
            origem TEXT NOT NULL DEFAULT 'manual',
            url_origem TEXT NOT NULL DEFAULT '',
            favorito INTEGER NOT NULL DEFAULT 0,
            criado_em REAL NOT NULL,
            alterado_em REAL NOT NULL,
            apagado_em REAL,
            parent_antes_lixeira TEXT,
            estado_sync TEXT NOT NULL DEFAULT 'local',
            remote_key TEXT NOT NULL DEFAULT '',
            metadados TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_items_parent ON items(parent_id, apagado_em);
        CREATE INDEX IF NOT EXISTS idx_items_nome ON items(nome COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_items_hash ON items(hash);
        CREATE TABLE IF NOT EXISTS versions (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            hash TEXT NOT NULL,
            tamanho INTEGER NOT NULL,
            criado_em REAL NOT NULL,
            origem TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            tipo TEXT NOT NULL,
            estado TEXT NOT NULL,
            item_id TEXT,
            progresso REAL,
            erro TEXT NOT NULL DEFAULT '',
            criado_em REAL NOT NULL,
            alterado_em REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shares (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            remote_key TEXT NOT NULL,
            url TEXT NOT NULL DEFAULT '',
            criado_em REAL NOT NULL,
            expira_em REAL NOT NULL,
            revogado_em REAL
        );
        """)


def _conexao() -> sqlite3.Connection:
    if threading.get_ident() != _MIGRACAO_DONO:
        limite = time.monotonic() + 120
        while (not _MIGRACAO.is_set()) or location.migracao_ativa():
            if time.monotonic() >= limite:
                raise RuntimeError("A migração da Emily Cloud ainda não terminou.")
            time.sleep(.1)
    BASE.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _nome_seguro(nome: str, padrao: str = "Arquivo") -> str:
    nome = _NOME_INVALIDO.sub("_", str(nome or "")).strip().strip(".")
    return (nome or padrao)[:240]


def _linha(row) -> Optional[dict]:
    if row is None:
        return None
    dado = dict(row)
    dado["favorito"] = bool(dado.get("favorito"))
    try:
        dado["metadados"] = json.loads(dado.get("metadados") or "{}")
    except (TypeError, json.JSONDecodeError):
        dado["metadados"] = {}
    dado["extensao"] = Path(dado["nome"]).suffix.lower() if dado["tipo"] == "arquivo" else ""
    return dado


def _item(con: sqlite3.Connection, item_id: str, incluir_apagado: bool = True):
    sql = "SELECT * FROM items WHERE id=?"
    if not incluir_apagado:
        sql += " AND apagado_em IS NULL"
    return con.execute(sql, (str(item_id),)).fetchone()


def _validar_pasta(con: sqlite3.Connection, parent_id: Optional[str]) -> Optional[str]:
    if parent_id in (None, "", "raiz"):
        return None
    row = _item(con, str(parent_id), incluir_apagado=False)
    if row is None or row["tipo"] != "pasta":
        raise ValueError("A pasta de destino não existe.")
    return str(parent_id)


def _nome_livre(con: sqlite3.Connection, parent_id: Optional[str], nome: str,
                ignorar_id: str = "") -> str:
    base = _nome_seguro(nome)
    raiz, ext = os.path.splitext(base)
    candidato, numero = base, 2
    while con.execute(
        "SELECT 1 FROM items WHERE parent_id IS ? AND nome=? COLLATE NOCASE "
        "AND apagado_em IS NULL AND id<>?", (parent_id, candidato, ignorar_id)
    ).fetchone():
        candidato = f"{raiz} ({numero}){ext}"
        numero += 1
    return candidato


def _hash_e_copiar(origem: Path, temporario: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    tamanho = 0
    with origem.open("rb") as entrada, temporario.open("xb") as saida:
        while bloco := entrada.read(_CHUNK):
            digest.update(bloco)
            saida.write(bloco)
            tamanho += len(bloco)
        saida.flush()
        os.fsync(saida.fileno())
    return digest.hexdigest(), tamanho


def _objeto(hash_: str) -> Path:
    return OBJECTS / hash_[:2] / hash_


def _ffmpeg() -> str:
    definido = os.getenv("EMILY_FFMPEG", "").strip()
    if definido and Path(definido).is_file():
        return definido
    encontrado = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if encontrado:
        return encontrado
    bases = [Path(sys.executable).resolve().parent, Path(__file__).resolve().parents[1]]
    for base in bases:
        for relativo in ("ffmpeg.exe", "ffmpeg", "bin/ffmpeg.exe", "bin/ffmpeg"):
            candidato = base / relativo
            if candidato.is_file():
                return str(candidato)
    return ""


def _preview_video(item_id: str, objeto: Path, destino: Path) -> str:
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return ""
    temporario = STAGING / f"preview-{item_id}-{uuid.uuid4().hex}.jpg"
    webp_tmp = STAGING / f"preview-{item_id}-{uuid.uuid4().hex}.webp"
    filtros = "thumbnail=60,scale=720:480:force_original_aspect_ratio=decrease"
    for posicao in ("1", "0"):
        try:
            resultado = subprocess.run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", posicao,
                "-i", str(objeto), "-frames:v", "1", "-vf", filtros,
                "-q:v", "3", str(temporario),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=30, check=False)
            if resultado.returncode == 0 and temporario.is_file() and temporario.stat().st_size:
                from PIL import Image
                with Image.open(temporario) as imagem:
                    imagem.convert("RGB").save(webp_tmp, "WEBP", quality=82, method=4)
                os.replace(webp_tmp, destino)
                return str(destino)
        except Exception as exc:
            print(f"[EMILY-CLOUD] frame de vídeo {item_id} falhou: {exc}")
        finally:
            temporario.unlink(missing_ok=True)
            webp_tmp.unlink(missing_ok=True)
    return ""


def _criar_preview(item_id: str, objeto: Path, mime: str) -> str:
    if not (mime.startswith("image/") or mime.startswith("video/")):
        return ""
    destino = PREVIEWS / f"{item_id}.webp"
    with _PREVIEW_LOCK:
        if destino.is_file():
            return str(destino)
        try:
            if mime.startswith("video/"):
                return _preview_video(item_id, objeto, destino)
            from PIL import Image, ImageOps
            temporario = STAGING / f"preview-{item_id}-{uuid.uuid4().hex}.webp"
            with Image.open(objeto) as imagem:
                imagem = ImageOps.exif_transpose(imagem)
                imagem.thumbnail((720, 480))
                if imagem.mode not in ("RGB", "RGBA"):
                    imagem = imagem.convert("RGBA" if "transparency" in imagem.info else "RGB")
                imagem.save(temporario, "WEBP", quality=82, method=4)
            os.replace(temporario, destino)
            return str(destino)
        except Exception as exc:  # preview nunca invalida o arquivo original
            print(f"[EMILY-CLOUD] preview de {item_id} falhou: {exc}")
            return ""
        finally:
            if "temporario" in locals():
                temporario.unlink(missing_ok=True)


def agendar_previews_pendentes(limite: int = 12) -> None:
    """Gera em background capas dos vídeos antigos que ainda não possuem thumb."""
    global _PREVIEW_THREAD
    if _PREVIEW_THREAD is not None and _PREVIEW_THREAD.is_alive():
        return

    def executar() -> None:
        try:
            with _conexao() as con:
                rows = con.execute(
                    "SELECT id,hash,mime FROM items WHERE tipo='arquivo' AND mime LIKE 'video/%' "
                    "AND apagado_em IS NULL ORDER BY alterado_em DESC LIMIT 500").fetchall()
            gerados = 0
            for row in rows:
                item_id = str(row["id"])
                if item_id in _PREVIEW_FALHOU or (PREVIEWS / f"{item_id}.webp").is_file():
                    continue
                objeto = _objeto(str(row["hash"]))
                if not objeto.is_file() or not _criar_preview(item_id, objeto, str(row["mime"])):
                    _PREVIEW_FALHOU.add(item_id)
                gerados += 1
                if gerados >= max(1, int(limite)):
                    break
        except Exception as exc:
            print(f"[EMILY-CLOUD] geração retroativa de previews falhou: {exc}")

    _PREVIEW_THREAD = threading.Thread(target=executar, daemon=True,
                                       name="EmilyCloudPreviews")
    _PREVIEW_THREAD.start()


def criar_pasta(nome: str, parent_id: Optional[str] = None) -> dict:
    _garantir()
    agora = time.time()
    with _LOCK, _conexao() as con:
        parent_id = _validar_pasta(con, parent_id)
        nome = _nome_livre(con, parent_id, nome)
        item_id = uuid.uuid4().hex
        con.execute(
            "INSERT INTO items(id,parent_id,nome,tipo,criado_em,alterado_em) "
            "VALUES(?,?,?,'pasta',?,?)", (item_id, parent_id, nome, agora, agora))
        con.commit()
    return detalhes(item_id)


def importar(caminho: str, parent_id: Optional[str] = None, nome: str = "",
             origem: str = "manual", url_origem: str = "",
             evento_id: str = "") -> dict:
    """Importa arquivo ou pasta. O original é preservado."""
    _garantir()
    fonte = Path(caminho).expanduser()
    if not fonte.exists() or fonte.is_symlink():
        raise ValueError("Arquivo inexistente ou link simbólico não permitido.")
    if fonte.is_dir():
        pasta = criar_pasta(nome or fonte.name, parent_id)
        erros = []
        for filho in sorted(fonte.iterdir(), key=lambda p: p.name.lower()):
            if filho.is_symlink():
                continue
            try:
                importar(str(filho), pasta["id"], origem=origem, url_origem=url_origem)
            except (OSError, ValueError) as exc:
                erros.append(f"{filho.name}: {exc}")
        pasta = detalhes(pasta["id"])
        pasta["erros"] = erros
        return pasta
    if not fonte.is_file():
        raise ValueError("Esse tipo de item não pode ser armazenado.")

    # Eventos da extensão podem ser reenviados até receberem ACK. O ID lógico
    # determinístico torna a importação idempotente mesmo se a conexão cair
    # depois do commit e antes da confirmação chegar ao navegador.
    evento_id = str(evento_id or "").strip()[:200]
    item_evento_id = hashlib.sha256(
        f"emily-cloud-evento:{evento_id}".encode("utf-8")).hexdigest()[:32] if evento_id else ""
    if item_evento_id:
        with _LOCK, _conexao() as con:
            existente = _item(con, item_evento_id)
        if existente is not None:
            return detalhes(item_evento_id)

    temporario = STAGING / f"{uuid.uuid4().hex}.part"
    try:
        hash_, tamanho = _hash_e_copiar(fonte, temporario)
        destino = _objeto(hash_)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK:
            if destino.exists():
                temporario.unlink(missing_ok=True)
            else:
                os.replace(temporario, destino)
        agora = time.time()
        mime = mimetypes.guess_type(nome or fonte.name)[0] or "application/octet-stream"
        with _LOCK, _conexao() as con:
            parent_id = _validar_pasta(con, parent_id)
            nome_final = _nome_livre(con, parent_id, nome or fonte.name)
            item_id = item_evento_id or uuid.uuid4().hex
            existente = _item(con, item_id) if item_evento_id else None
            if existente is not None:
                return detalhes(item_id)
            meta = {"caminho_original": str(fonte.absolute())}
            if evento_id:
                meta["evento_id"] = evento_id
            try:
                con.execute(
                    "INSERT INTO items(id,parent_id,nome,tipo,mime,tamanho,hash,origem,"
                    "url_origem,criado_em,alterado_em,metadados) "
                    "VALUES(?,?,?,'arquivo',?,?,?,?,?,?,?,?)",
                    (item_id, parent_id, nome_final, mime, tamanho, hash_,
                     _nome_seguro(origem, "manual"), str(url_origem or "")[:4000],
                     agora, agora, json.dumps(meta, ensure_ascii=False)))
            except sqlite3.IntegrityError:
                # Outra thread concluiu o mesmo evento entre as duas checagens.
                if item_evento_id and _item(con, item_evento_id) is not None:
                    return detalhes(item_evento_id)
                raise
            con.execute(
                "INSERT INTO versions(id,item_id,hash,tamanho,criado_em,origem) "
                "VALUES(?,?,?,?,?,?)",
                (uuid.uuid4().hex, item_id, hash_, tamanho, agora, origem))
        _criar_preview(item_id, destino, mime)
        return detalhes(item_id)
    finally:
        temporario.unlink(missing_ok=True)


def listar(parent_id: Optional[str] = None, filtro: str = "arquivos",
           busca: str = "", limite: int = 200) -> list[dict]:
    _garantir()
    limite = max(1, min(int(limite), 500))
    filtro = (filtro or "arquivos").lower()
    clausulas, args = [], []
    if filtro == "lixeira":
        clausulas.append("apagado_em IS NOT NULL")
    else:
        clausulas.append("apagado_em IS NULL")
    if filtro in ("arquivos", "pasta"):
        clausulas.append("parent_id IS ?")
        args.append(None if parent_id in (None, "", "raiz") else str(parent_id))
    elif filtro == "favoritos":
        clausulas.append("favorito=1")
    elif filtro == "imagens":
        clausulas.append("mime LIKE 'image/%'")
    elif filtro == "videos":
        clausulas.append("mime LIKE 'video/%'")
    elif filtro == "audios":
        clausulas.append("mime LIKE 'audio/%'")
    elif filtro == "documentos":
        clausulas.append("(mime LIKE 'text/%' OR mime LIKE 'application/pdf%' OR mime LIKE '%document%')")
    elif filtro == "compactados":
        clausulas.append("lower(nome) GLOB '*.zip' OR lower(nome) GLOB '*.rar' OR lower(nome) GLOB '*.7z' OR lower(nome) GLOB '*.tar*'")
    if busca.strip():
        clausulas.append("nome LIKE ? COLLATE NOCASE")
        args.append(f"%{busca.strip()}%")
    ordem = "COALESCE(apagado_em, alterado_em) DESC" if filtro in ("recentes", "lixeira") else "tipo DESC, nome COLLATE NOCASE"
    sql = f"SELECT * FROM items WHERE {' AND '.join(f'({c})' for c in clausulas)} ORDER BY {ordem} LIMIT ?"
    args.append(limite)
    with _conexao() as con:
        return [_linha(r) for r in con.execute(sql, args).fetchall()]


def buscar(texto: str, limite: int = 100) -> list[dict]:
    return listar(filtro="busca", busca=texto, limite=limite)


def detalhes(item_id: str) -> dict:
    _garantir()
    with _conexao() as con:
        row = _item(con, item_id)
        if row is None:
            raise ValueError("Item não encontrado.")
        dado = _linha(row)
        if row["parent_id"]:
            pai = _item(con, row["parent_id"])
            dado["pasta_nome"] = pai["nome"] if pai else ""
        else:
            dado["pasta_nome"] = "Meus arquivos"
        dado["versoes"] = [dict(v) for v in con.execute(
            "SELECT id,hash,tamanho,criado_em,origem FROM versions WHERE item_id=? ORDER BY criado_em DESC",
            (item_id,)).fetchall()]
        dado["tem_preview"] = (PREVIEWS / f"{item_id}.webp").is_file()
        return dado


def caminho_conteudo(item_id: str) -> Path:
    item = detalhes(item_id)
    if item["tipo"] != "arquivo" or not item["hash"]:
        raise ValueError("Esse item não possui conteúdo de arquivo.")
    caminho = _objeto(item["hash"])
    if not caminho.is_file():
        raise FileNotFoundError("O conteúdo local desse arquivo não está disponível.")
    return caminho


def caminho_preview(item_id: str) -> Optional[Path]:
    detalhes(item_id)  # valida o ID, sem aceitar caminho vindo de fora
    caminho = PREVIEWS / f"{item_id}.webp"
    return caminho if caminho.is_file() else None


def renomear(item_id: str, nome: str) -> dict:
    with _LOCK, _conexao() as con:
        row = _item(con, item_id, incluir_apagado=False)
        if row is None:
            raise ValueError("Item não encontrado.")
        nome = _nome_livre(con, row["parent_id"], nome, ignorar_id=item_id)
        con.execute("UPDATE items SET nome=?,alterado_em=? WHERE id=?", (nome, time.time(), item_id))
    return detalhes(item_id)


def _descendente(con: sqlite3.Connection, item_id: str, parent_id: str) -> bool:
    atual = parent_id
    while atual:
        if atual == item_id:
            return True
        row = _item(con, atual)
        atual = row["parent_id"] if row else None
    return False


def mover(item_id: str, parent_id: Optional[str]) -> dict:
    with _LOCK, _conexao() as con:
        row = _item(con, item_id, incluir_apagado=False)
        if row is None:
            raise ValueError("Item não encontrado.")
        parent_id = _validar_pasta(con, parent_id)
        if parent_id and _descendente(con, item_id, parent_id):
            raise ValueError("Uma pasta não pode ser movida para dentro dela mesma.")
        nome = _nome_livre(con, parent_id, row["nome"], ignorar_id=item_id)
        con.execute("UPDATE items SET parent_id=?,nome=?,alterado_em=? WHERE id=?",
                    (parent_id, nome, time.time(), item_id))
    return detalhes(item_id)


def favoritar(item_id: str, valor: bool = True) -> dict:
    with _LOCK, _conexao() as con:
        if _item(con, item_id, incluir_apagado=False) is None:
            raise ValueError("Item não encontrado.")
        con.execute("UPDATE items SET favorito=?,alterado_em=? WHERE id=?",
                    (1 if valor else 0, time.time(), item_id))
    return detalhes(item_id)


def _filhos_recursivos(con: sqlite3.Connection, item_id: str) -> list[str]:
    ids, fila = [item_id], [item_id]
    while fila:
        atual = fila.pop()
        filhos = [r[0] for r in con.execute("SELECT id FROM items WHERE parent_id=?", (atual,))]
        ids.extend(filhos)
        fila.extend(filhos)
    return ids


def mover_para_lixeira(item_id: str) -> dict:
    agora = time.time()
    with _LOCK, _conexao() as con:
        row = _item(con, item_id, incluir_apagado=False)
        if row is None:
            raise ValueError("Item não encontrado.")
        ids = _filhos_recursivos(con, item_id)
        con.execute("UPDATE items SET parent_antes_lixeira=? WHERE id=?", (row["parent_id"], item_id))
        con.executemany("UPDATE items SET apagado_em=?,alterado_em=? WHERE id=?",
                        [(agora, agora, i) for i in ids])
    return detalhes(item_id)


def restaurar(item_id: str) -> dict:
    with _LOCK, _conexao() as con:
        row = _item(con, item_id)
        if row is None or row["apagado_em"] is None:
            raise ValueError("Item não está na lixeira.")
        parent = row["parent_antes_lixeira"]
        if parent and _item(con, parent, incluir_apagado=False) is None:
            parent = None
        ids = _filhos_recursivos(con, item_id)
        con.executemany("UPDATE items SET apagado_em=NULL,alterado_em=? WHERE id=?",
                        [(time.time(), i) for i in ids])
        nome = _nome_livre(con, parent, row["nome"], ignorar_id=item_id)
        con.execute("UPDATE items SET parent_id=?,nome=?,parent_antes_lixeira=NULL WHERE id=?",
                    (parent, nome, item_id))
    return detalhes(item_id)


def excluir_definitivamente(item_id: str) -> bool:
    objetos = []
    with _LOCK, _conexao() as con:
        row = _item(con, item_id)
        if row is None or row["apagado_em"] is None:
            raise ValueError("Somente itens da lixeira podem ser excluídos definitivamente.")
        ids = _filhos_recursivos(con, item_id)
        marcadores = ",".join("?" for _ in ids)
        objetos = [r[0] for r in con.execute(
            f"SELECT DISTINCT hash FROM items WHERE id IN ({marcadores}) AND hash<>''", ids)]
        con.execute(f"DELETE FROM items WHERE id IN ({marcadores})", ids)
        restantes = {r[0] for r in con.execute("SELECT DISTINCT hash FROM items WHERE hash<>''")}
    for hash_ in objetos:
        if hash_ not in restantes:
            _objeto(hash_).unlink(missing_ok=True)
    for i in ids:
        (PREVIEWS / f"{i}.webp").unlink(missing_ok=True)
    return True


def exportar(item_id: str, destino: str, nome: str = "") -> dict:
    item = detalhes(item_id)
    alvo = Path(destino).expanduser()
    alvo.mkdir(parents=True, exist_ok=True)
    if item["tipo"] == "arquivo":
        final = alvo / _nome_seguro(nome or item["nome"])
        if final.exists():
            raiz, ext = final.stem, final.suffix
            n = 2
            while final.exists():
                final = alvo / f"{raiz} ({n}){ext}"
                n += 1
        shutil.copy2(caminho_conteudo(item_id), final)
        return {"ok": True, "caminho": str(final), "itens": 1}
    pasta_final = alvo / _nome_seguro(nome or item["nome"], "Pasta")
    pasta_final.mkdir(exist_ok=True)
    total = 0
    for filho in listar(parent_id=item_id):
        total += exportar(filho["id"], str(pasta_final)).get("itens", 0)
    return {"ok": True, "caminho": str(pasta_final), "itens": total}


def _config_s3() -> dict:
    return {
        "ativo": os.getenv("EMILY_CLOUD_S3_ATIVO", "0").strip() == "1",
        "endpoint_url": os.getenv("EMILY_CLOUD_S3_ENDPOINT") or None,
        "bucket": os.getenv("EMILY_CLOUD_S3_BUCKET", "").strip(),
        "region_name": os.getenv("EMILY_CLOUD_S3_REGION") or None,
        "aws_access_key_id": os.getenv("EMILY_CLOUD_S3_ACCESS_KEY") or None,
        "aws_secret_access_key": os.getenv("EMILY_CLOUD_S3_SECRET_KEY") or None,
        "prefix": os.getenv("EMILY_CLOUD_S3_PREFIX", "emily-cloud").strip("/"),
    }


def _s3():
    cfg = _config_s3()
    if not cfg["ativo"] or not cfg["bucket"]:
        raise RuntimeError("A sincronização S3 da Emily Cloud não está configurada.")
    import boto3
    kwargs = {k: cfg[k] for k in (
        "endpoint_url", "region_name", "aws_access_key_id", "aws_secret_access_key"
    ) if cfg[k]}
    return boto3.client("s3", **kwargs), cfg


def sincronizar(item_id: str) -> dict:
    item = detalhes(item_id)
    if item["tipo"] != "arquivo":
        feitos = [sincronizar(f["id"]) for f in listar(parent_id=item_id)]
        return {"ok": all(f.get("ok") for f in feitos), "itens": len(feitos)}
    cliente, cfg = _s3()
    chave = f"{cfg['prefix']}/objects/{item['hash']}"
    with _LOCK, _conexao() as con:
        con.execute("UPDATE items SET estado_sync='enviando' WHERE id=?", (item_id,))
    try:
        cliente.upload_file(str(caminho_conteudo(item_id)), cfg["bucket"], chave,
                            ExtraArgs={"ContentType": item["mime"]})
        with _LOCK, _conexao() as con:
            con.execute("UPDATE items SET estado_sync='sincronizado',remote_key=?,alterado_em=? WHERE id=?",
                        (chave, time.time(), item_id))
        return {"ok": True, "item": detalhes(item_id)}
    except Exception:
        with _LOCK, _conexao() as con:
            con.execute("UPDATE items SET estado_sync='erro' WHERE id=?", (item_id,))
        raise


def compartilhar(item_id: str, horas: int = 24) -> dict:
    item = detalhes(item_id)
    if item["tipo"] != "arquivo":
        raise ValueError("Compartilhamento de pasta ainda não está disponível.")
    if item["estado_sync"] != "sincronizado":
        sincronizar(item_id)
        item = detalhes(item_id)
    cliente, cfg = _s3()
    share_id = secrets.token_urlsafe(18)
    chave = f"{cfg['prefix']}/shares/{share_id}/{_nome_seguro(item['nome'])}"
    cliente.copy_object(Bucket=cfg["bucket"], Key=chave,
                        CopySource={"Bucket": cfg["bucket"], "Key": item["remote_key"]},
                        ContentType=item["mime"], MetadataDirective="REPLACE")
    horas = max(1, min(int(horas), 24 * 7))
    expira = time.time() + horas * 3600
    url = cliente.generate_presigned_url("get_object", Params={
        "Bucket": cfg["bucket"], "Key": chave,
        "ResponseContentDisposition": f'attachment; filename="{item["nome"]}"',
    }, ExpiresIn=horas * 3600)
    with _LOCK, _conexao() as con:
        con.execute("INSERT INTO shares(id,item_id,remote_key,url,criado_em,expira_em) VALUES(?,?,?,?,?,?)",
                    (share_id, item_id, chave, url, time.time(), expira))
    return {"ok": True, "id": share_id, "url": url, "expira_em": expira}


def listar_compartilhamentos(item_id: str = "") -> list[dict]:
    _garantir()
    sql = "SELECT s.*,i.nome FROM shares s JOIN items i ON i.id=s.item_id"
    args = []
    if item_id:
        sql += " WHERE s.item_id=?"
        args.append(item_id)
    sql += " ORDER BY s.criado_em DESC"
    with _conexao() as con:
        return [dict(r) for r in con.execute(sql, args)]


def revogar_compartilhamento(share_id: str) -> bool:
    cliente, cfg = _s3()
    with _LOCK, _conexao() as con:
        row = con.execute("SELECT * FROM shares WHERE id=? AND revogado_em IS NULL", (share_id,)).fetchone()
        if row is None:
            raise ValueError("Compartilhamento não encontrado ou já revogado.")
        cliente.delete_object(Bucket=cfg["bucket"], Key=row["remote_key"])
        con.execute("UPDATE shares SET revogado_em=? WHERE id=?", (time.time(), share_id))
    return True


def status() -> dict:
    _garantir()
    with _conexao() as con:
        total = con.execute("SELECT COUNT(*) FROM items WHERE apagado_em IS NULL").fetchone()[0]
        arquivos = con.execute("SELECT COUNT(*) FROM items WHERE tipo='arquivo' AND apagado_em IS NULL").fetchone()[0]
        lixeira = con.execute("SELECT COUNT(*) FROM items WHERE apagado_em IS NOT NULL").fetchone()[0]
        logico = con.execute("SELECT COALESCE(SUM(tamanho),0) FROM items WHERE apagado_em IS NULL").fetchone()[0]
        hashes = [r[0] for r in con.execute("SELECT DISTINCT hash FROM items WHERE hash<>''")]
        sincronizados = con.execute("SELECT COUNT(*) FROM items WHERE estado_sync='sincronizado' AND apagado_em IS NULL").fetchone()[0]
    fisico = sum(_objeto(h).stat().st_size for h in hashes if _objeto(h).is_file())
    uso = shutil.disk_usage(BASE)
    cfg = _config_s3()
    return {
        "ok": True, "pasta": str(BASE), "itens": total, "arquivos": arquivos,
        "lixeira": lixeira, "bytes_logicos": logico, "bytes_fisicos": fisico,
        "bytes_livres": uso.free, "deduplicado": max(0, logico - fisico),
        "s3_ativo": bool(cfg["ativo"] and cfg["bucket"]),
        "sincronizados": sincronizados,
    }


try:
    _garantir()
except FileNotFoundError as exc:
    # Um HD removível/desmontado não pode impedir o módulo e as rotas de
    # carregarem. As requisições recebem 503 até o mesmo armazenamento voltar.
    print(f"[EMILY-CLOUD] armazenamento configurado indisponível: {exc}")