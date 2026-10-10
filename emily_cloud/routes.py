"""Rotas HTTP autenticadas da Emily Cloud para celular/gateway."""

from __future__ import annotations

import hmac
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request, stream_with_context

from . import archives, core, location, service


blueprint = Blueprint("emily_cloud", __name__, url_prefix="/cloud")
_LOCK = threading.RLock()
_PARTE_MAX = 8 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def _sessoes() -> Path:
    return core.STAGING / "uploads"


def _token() -> str:
    return os.getenv("EMILY_PONTE_TOKEN", "").strip()


def _autorizado() -> bool:
    esperado = _token()
    if not esperado:  # Cloud jamais fica pública por configuração omitida
        return False
    return hmac.compare_digest(
        request.headers.get("Authorization", ""), f"Bearer {esperado}")


def _assinatura_viewer(item_id: str, expira: int) -> str:
    mensagem = f"emily-cloud-viewer:{item_id}:{int(expira)}".encode("utf-8")
    return hmac.new(_token().encode("utf-8"), mensagem, hashlib.sha256).hexdigest()


def _viewer_autorizado() -> bool:
    if not _token():
        return False
    if request.method != "GET" or request.endpoint != "emily_cloud.cloud_content":
        return False
    try:
        item_id = str(request.view_args.get("item_id") or "")
        expira = int(request.args.get("exp", "0"))
        assinatura = request.args.get("sig", "")
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(item_id and expira >= int(time.time()) and expira <= int(time.time()) + 24 * 3600
                and hmac.compare_digest(assinatura, _assinatura_viewer(item_id, expira)))


@blueprint.before_request
def _exigir_token():
    if not (_autorizado() or _viewer_autorizado()):
        if not _token():
            return jsonify({
                "ok": False,
                "erro": "Emily Cloud remota desativada: configure EMILY_PONTE_TOKEN.",
            }), 503
        return jsonify({"ok": False, "erro": "token inválido"}), 401
    if location.migracao_ativa():
        return jsonify({"ok": False, "erro": "Emily Cloud mudando de armazenamento; tente novamente em instantes."}), 503, {"Retry-After": "5"}
    if not location.disponivel(core.BASE):
        return jsonify({
            "ok": False,
            "erro": "O disco configurado para a Emily Cloud não está disponível. Conecte ou monte o disco no PC.",
        }), 503, {"Retry-After": "15"}
    return None


def _erro(exc: Exception, codigo: int = 400):
    return jsonify({"ok": False, "erro": str(exc)}), codigo


def _item_http(item: dict) -> dict:
    """Troca URIs internas da WebView por endpoints HTTP autenticados."""
    dado = dict(item)
    item_id = dado.get("id", "")
    dado["preview_url"] = f"/cloud/preview/{item_id}" if dado.get("tem_preview") else ""
    dado["content_url"] = (
        f"/cloud/content/{item_id}" if dado.get("tipo") == "arquivo" else "")
    return dado


@blueprint.get("/status")
def cloud_status():
    return jsonify(service.status())


@blueprint.get("/items")
def cloud_items():
    try:
        dados = service.listar(
            request.args.get("parent") or None,
            request.args.get("filtro", "arquivos"),
            request.args.get("busca", ""),
            int(request.args.get("limite", 200)),
        )
        dados["itens"] = [_item_http(item) for item in dados["itens"]]
        return jsonify(dados)
    except (TypeError, ValueError) as exc:
        return _erro(exc)


@blueprint.get("/items/<item_id>")
def cloud_item(item_id: str):
    try:
        return jsonify({"ok": True, "item": _item_http(service.detalhes(item_id))})
    except ValueError as exc:
        return _erro(exc, 404)


@blueprint.post("/folders")
def cloud_folder():
    corpo = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "item": service.criar_pasta(
            str(corpo.get("nome") or ""), corpo.get("parent_id") or None)})
    except ValueError as exc:
        return _erro(exc)


@blueprint.post("/import-paths")
def cloud_import_paths():
    """Importa caminhos que existem NO PC.

    É o equivalente HTTP das ferramentas ``nuvem_guardar_arquivo`` e
    ``nuvem_guardar_varios``. O celular usa isto quando o Vitor pede pelo chat
    para guardar um caminho do computador; arquivos do próprio celular usam o
    upload retomável em partes, não este endpoint.
    """
    corpo = request.get_json(silent=True) or {}
    caminhos = corpo.get("caminhos") or []
    if isinstance(caminhos, str):
        caminhos = [caminhos]
    if not isinstance(caminhos, list):
        return _erro(ValueError("caminhos precisa ser uma lista."))
    try:
        return jsonify(service.importar_e_sincronizar(
            [str(c) for c in caminhos[:100]],
            corpo.get("parent_id") or None,
            bool(corpo.get("sincronizar", False)),
            origem="pedido_celular",
        ))
    except (TypeError, ValueError) as exc:
        return _erro(exc)


@blueprint.patch("/items/<item_id>")
def cloud_editar(item_id: str):
    corpo = request.get_json(silent=True) or {}
    try:
        item = service.detalhes(item_id)
        if "nome" in corpo:
            item = service.renomear(item_id, str(corpo["nome"]))
        if "parent_id" in corpo:
            item = service.mover(item_id, corpo.get("parent_id") or None)
        if "favorito" in corpo:
            item = service.favoritar(item_id, bool(corpo["favorito"]))
        return jsonify({"ok": True, "item": item})
    except ValueError as exc:
        return _erro(exc)


@blueprint.delete("/items/<item_id>")
def cloud_apagar(item_id: str):
    try:
        permanente = request.args.get("permanente") == "1"
        if permanente:
            core.excluir_definitivamente(item_id)
            return jsonify({"ok": True, "permanente": True})
        return jsonify({"ok": True, "item": service.lixeira(item_id)})
    except ValueError as exc:
        return _erro(exc)


@blueprint.post("/items/<item_id>/restaurar")
def cloud_restaurar(item_id: str):
    try:
        return jsonify({"ok": True, "item": service.restaurar(item_id)})
    except ValueError as exc:
        return _erro(exc)


@blueprint.get("/items/<item_id>/texto")
def cloud_texto(item_id: str):
    try:
        limite = int(request.args.get("limite", 40000))
        return jsonify({"ok": True, "texto": service.ler_texto(item_id, limite)})
    except (TypeError, ValueError, FileNotFoundError) as exc:
        return _erro(exc, 404 if isinstance(exc, (ValueError, FileNotFoundError)) else 400)


@blueprint.get("/items/<item_id>/viewer")
def cloud_viewer(item_id: str):
    """Devolve URL assinada curta para players que não aceitam header Bearer."""
    try:
        item = service.detalhes(item_id)
        if item["tipo"] != "arquivo":
            raise ValueError("Pastas não possuem visualização de arquivo.")
        expira = int(time.time()) + 6 * 3600
        caminho = f"/cloud/content/{quote(item_id)}?exp={expira}&sig={_assinatura_viewer(item_id, expira)}"
        import gateway_endpoint
        endpoint = gateway_endpoint.obter()
        base = endpoint["url"] if endpoint.get("modo") == "oracle" else request.url_root.rstrip("/")
        return jsonify({"ok": True, "item": _item_http(item),
                        "caminho": caminho,
                        "url": base + caminho,
                        "expira_em": expira})
    except ValueError as exc:
        return _erro(exc, 404)


@blueprint.get("/items/<item_id>/archive")
def cloud_archive(item_id: str):
    try:
        return jsonify(archives.listar(item_id))
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _erro(exc, 404 if isinstance(exc, FileNotFoundError) else 400)


@blueprint.post("/items/<item_id>/extract")
def cloud_extract(item_id: str):
    corpo = request.get_json(silent=True) or {}
    entradas = corpo.get("entradas")
    if entradas is not None and not isinstance(entradas, list):
        return _erro(ValueError("entradas precisa ser uma lista."))
    try:
        return jsonify(archives.extrair(item_id, corpo.get("parent_id") or None, entradas))
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _erro(exc, 404 if isinstance(exc, FileNotFoundError) else 400)


@blueprint.post("/items/<item_id>/sincronizar")
def cloud_sincronizar(item_id: str):
    try:
        return jsonify(core.sincronizar(item_id))
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        return _erro(exc)


@blueprint.post("/items/<item_id>/compartilhar")
def cloud_compartilhar(item_id: str):
    corpo = request.get_json(silent=True) or {}
    try:
        horas = int(corpo.get("horas", 24))
        return jsonify(core.compartilhar(item_id, horas))
    except (TypeError, ValueError, RuntimeError, FileNotFoundError) as exc:
        return _erro(exc)


@blueprint.post("/items/<item_id>/exportar")
def cloud_exportar(item_id: str):
    """Exporta o item para uma pasta DO PC (Downloads por padrão)."""
    corpo = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, **service.exportar(
            item_id, str(corpo.get("destino") or "downloads"))})
    except (ValueError, FileNotFoundError, OSError) as exc:
        return _erro(exc)


@blueprint.get("/shares")
def cloud_shares():
    try:
        agora = time.time()
        itens = []
        for share in core.listar_compartilhamentos(request.args.get("item_id", "")):
            dado = dict(share)
            dado["ativo"] = not dado.get("revogado_em") and float(dado.get("expira_em") or 0) > agora
            itens.append(dado)
        return jsonify({"ok": True, "links": itens})
    except (TypeError, ValueError, RuntimeError) as exc:
        return _erro(exc)


@blueprint.delete("/shares/<share_id>")
def cloud_revogar_share(share_id: str):
    try:
        return jsonify({"ok": bool(core.revogar_compartilhamento(share_id))})
    except (ValueError, RuntimeError) as exc:
        return _erro(exc)


def _arquivo_response(caminho: Path, nome: str, mime: str, download: bool = False):
    tamanho = caminho.stat().st_size
    faixa = request.headers.get("Range", "")
    inicio, fim, status = 0, tamanho - 1, 200
    if faixa:
        achado = re.fullmatch(r"bytes=(\d*)-(\d*)", faixa.strip())
        if not achado:
            return Response(status=416, headers={"Content-Range": f"bytes */{tamanho}"})
        if achado.group(1):
            inicio = int(achado.group(1))
            fim = min(int(achado.group(2) or tamanho - 1), tamanho - 1)
        elif achado.group(2):
            quantidade = min(int(achado.group(2)), tamanho)
            inicio, fim = tamanho - quantidade, tamanho - 1
        if inicio > fim or inicio >= tamanho:
            return Response(status=416, headers={"Content-Range": f"bytes */{tamanho}"})
        status = 206
    comprimento = max(0, fim - inicio + 1)

    def gerar():
        restante = comprimento
        with caminho.open("rb") as arquivo:
            arquivo.seek(inicio)
            while restante:
                bloco = arquivo.read(min(256 * 1024, restante))
                if not bloco:
                    break
                restante -= len(bloco)
                yield bloco

    nome = str(nome).replace('"', "_").replace("\r", "_").replace("\n", "_")
    nome_ascii = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    nome_ascii = nome_ascii.replace("\\", "_") or "arquivo"
    disposicao = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes", "Content-Length": str(comprimento),
        "Cache-Control": "private, no-store",
        "Content-Disposition": (
            f'{disposicao}; filename="{nome_ascii}"; filename*=UTF-8\'\'{quote(nome)}'),
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {inicio}-{fim}/{tamanho}"
    return Response(stream_with_context(gerar()), status=status,
                    mimetype=mime or "application/octet-stream", headers=headers)


@blueprint.get("/content/<item_id>")
def cloud_content(item_id: str):
    try:
        item = core.detalhes(item_id)
        return _arquivo_response(core.caminho_conteudo(item_id), item["nome"],
                                 item["mime"], request.args.get("download") == "1")
    except ValueError as exc:
        return _erro(exc, 404)
    except FileNotFoundError as exc:
        return _erro(exc, 410)


@blueprint.get("/preview/<item_id>")
def cloud_preview(item_id: str):
    try:
        caminho = core.caminho_preview(item_id)
        if caminho is None:
            return _erro(ValueError("Preview não disponível."), 404)
        return _arquivo_response(caminho, f"{item_id}.webp", "image/webp")
    except ValueError as exc:
        return _erro(exc, 404)


def _sessao(upload_id: str) -> tuple[Path, dict]:
    if not _ID.fullmatch(upload_id):
        raise ValueError("ID de upload inválido.")
    pasta = _sessoes() / upload_id
    try:
        meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Upload não encontrado.") from exc
    return pasta, meta


@blueprint.post("/uploads")
def upload_iniciar():
    corpo = request.get_json(silent=True) or {}
    nome = core._nome_seguro(corpo.get("nome"), "Arquivo")
    try:
        tamanho = max(0, int(corpo.get("tamanho") or 0))
    except (TypeError, ValueError):
        return _erro(ValueError("Tamanho inválido."))
    upload_id = secrets.token_urlsafe(18)
    pasta = _sessoes() / upload_id
    pasta.mkdir(parents=True, exist_ok=False)
    meta = {
        "nome": nome, "tamanho": tamanho,
        "parent_id": corpo.get("parent_id") or None,
        "criado_em": time.time(), "partes": [],
    }
    (pasta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True, "upload_id": upload_id, "parte_max": _PARTE_MAX})


@blueprint.put("/uploads/<upload_id>/parts/<int:numero>")
def upload_parte(upload_id: str, numero: int):
    try:
        with _LOCK:
            pasta, meta = _sessao(upload_id)
            if numero < 0 or numero > 100000:
                raise ValueError("Número da parte inválido.")
            conteudo = request.stream.read(_PARTE_MAX + 1)
            if len(conteudo) > _PARTE_MAX:
                return _erro(ValueError("Parte maior que 8 MiB."), 413)
            temporario = pasta / f"{numero:06d}.tmp"
            final = pasta / f"{numero:06d}.part"
            temporario.write_bytes(conteudo)
            os.replace(temporario, final)
            meta["partes"] = sorted(set(meta.get("partes", [])) | {numero})
            (pasta / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return jsonify({"ok": True, "numero": numero, "bytes": len(conteudo)})
    except ValueError as exc:
        return _erro(exc, 404)


@blueprint.post("/uploads/<upload_id>/complete")
def upload_concluir(upload_id: str):
    try:
        with _LOCK:
            pasta, meta = _sessao(upload_id)
            partes = sorted(pasta.glob("*.part"))
            esperado = int(meta.get("tamanho") or 0)
            if not partes and esperado != 0:
                raise ValueError("Nenhuma parte foi enviada.")
            numeros = [int(parte.stem) for parte in partes]
            if numeros != list(range(len(partes))):
                raise ValueError("Há partes ausentes no upload; reenvie antes de concluir.")
            junto = pasta / "completo.upload"
            total = 0
            with junto.open("wb") as saida:
                for parte in partes:
                    with parte.open("rb") as entrada:
                        shutil.copyfileobj(entrada, saida, 1024 * 1024)
                    total += parte.stat().st_size
            if esperado and total != esperado:
                junto.unlink(missing_ok=True)
                raise ValueError(f"Upload incompleto: recebi {total} de {esperado} bytes.")
            item = core.importar(str(junto), meta.get("parent_id"), nome=meta["nome"],
                                origem="celular")
            shutil.rmtree(pasta, ignore_errors=True)
        return jsonify({"ok": True, "item": service.item_ui(item)})
    except ValueError as exc:
        return _erro(exc)


@blueprint.delete("/uploads/<upload_id>")
def upload_cancelar(upload_id: str):
    try:
        with _LOCK:
            pasta, _ = _sessao(upload_id)
            shutil.rmtree(pasta, ignore_errors=True)
        return jsonify({"ok": True})
    except ValueError as exc:
        return _erro(exc, 404)


def registrar(app) -> None:
    if "emily_cloud" not in app.blueprints:
        app.register_blueprint(blueprint)