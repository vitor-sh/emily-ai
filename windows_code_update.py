"""Atualiza módulos Python e recursos do Emily.exe pelo gateway privado.

O executável e as bibliotecas congeladas continuam no instalador. O runtime
hook do build Windows lê arquivos soltos em ``_internal`` antes do PYZ.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZipFile

import requests

PASTAS = frozenset({"web", "static", "img", "assets", "emily-gateway-service",
                    "memoria_unificada", "emily_cloud"})
EXTENSOES_RECURSOS = frozenset({".html", ".css", ".js", ".json", ".svg",
                                ".png", ".jpg", ".jpeg", ".gif", ".webp",
                                ".ico", ".woff", ".woff2", ".ttf", ".onnx",
                                ".rnnn", ".mp3", ".wav", ".ogg"})
TETO_ZIP = 100 * 1024 * 1024
TETO_EXTRAIDO = 220 * 1024 * 1024


def _internal() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent / "_internal"))


def _endpoint() -> str:
    from windows_update import _config
    return str(_config().get("update_url") or "").removesuffix("/windows/update") + "/windows/code-update"


def _headers() -> dict[str, str]:
    from windows_update import _token
    return {"Authorization": f"Bearer {_token()}"}


def _versao_local() -> int:
    try:
        return int(json.loads((_internal() / ".windows-code-version.json").read_text())["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def _relativo_seguro(nome: str) -> Path:
    puro = PurePosixPath(nome)
    partes = puro.parts
    if (not nome or "\\" in nome or ":" in nome or "\x00" in nome
            or "//" in nome or puro.is_absolute()
            or any(p in ("", ".", "..") or p.endswith((".", " ")) for p in partes)
            or any(p.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "LPT1"}
                   for p in partes)):
        raise ValueError(f"caminho inválido no pacote: {nome}")
    if len(partes) == 1:
        if not nome.endswith(".py") or nome in {"emily_bootstrap.py", "pyi_rhook_emily.py"}:
            raise ValueError(f"módulo não atualizável: {nome}")
    elif partes[0] not in PASTAS:
        raise ValueError(f"pasta não atualizável: {nome}")
    elif partes[0] in {"emily-gateway-service", "memoria_unificada", "emily_cloud"}:
        if puro.suffix != ".py":
            raise ValueError(f"arquivo de código inesperado: {nome}")
    elif puro.suffix.lower() not in EXTENSOES_RECURSOS:
        raise ValueError(f"recurso não atualizável: {nome}")
    return Path(*partes)


def _validar_manifesto(dados: dict) -> None:
    from windows_update import _config
    if (not isinstance(dados, dict) or not isinstance(dados.get("version"), int)
            or dados["version"] < 1 or str(dados.get("installer")) != str(_config().get("version"))):
        raise ValueError("versão do instalador incompatível com atualização de código")
    tamanho = dados.get("size")
    hashes = dados.get("files")
    if (not isinstance(tamanho, int) or not 0 < tamanho <= TETO_ZIP
            or not isinstance(hashes, dict) or not 0 < len(hashes) <= 5000):
        raise ValueError("manifesto de código inválido")
    for digest in [dados.get("sha256"), *hashes.values()]:
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("SHA-256 inválido")
        int(digest, 16)
    for nome in hashes:
        _relativo_seguro(nome)


def consultar(sessao: requests.Session | None = None) -> dict:
    from windows_update import _config, _token
    estado = {"em_pacote": True, "modo_windows": True, "origem_ok": True,
              "quantos": 0, "resumo": "", "pode_desfazer": False}
    if not _config().get("update_url") or not _token():
        return estado
    try:
        resposta = (sessao or requests.Session()).get(
            _endpoint(), headers=_headers(), timeout=(3, 6))
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados.get("ok"):
            return estado
        _validar_manifesto(dados)
        if dados["version"] > _versao_local():
            estado.update(quantos=1, resumo=f"código {dados['version']}",
                          versao_publicada=f"código {dados['version']}")
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError):
        pass
    return estado


def _extrair_validado(arquivo: Path, staging: Path, dados: dict) -> None:
    hashes = dados["files"]
    with ZipFile(arquivo) as pacote:
        entradas = [e for e in pacote.infolist() if not e.is_dir()]
        if len(entradas) != len(hashes) or {e.filename for e in entradas} != set(hashes):
            raise ValueError("lista de arquivos diferente do manifesto")
        if sum(e.file_size for e in entradas) > TETO_EXTRAIDO:
            raise ValueError("código extraído grande demais")
        for entrada in entradas:
            relativo = _relativo_seguro(entrada.filename)
            if (entrada.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("link simbólico no pacote")
            conteudo = pacote.read(entrada)
            if hashlib.sha256(conteudo).hexdigest() != hashes[entrada.filename]:
                raise ValueError(f"hash inválido: {entrada.filename}")
            if relativo.suffix == ".py":
                compile(conteudo, entrada.filename, "exec")
            alvo = staging / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(conteudo)


def _preflight(staging: Path) -> None:
    saida = staging.parent / "preflight.json"
    combinado = staging.parent / "preflight-combined"
    combinado.mkdir()
    # O hook do PyInstaller usa um único diretório de overrides. Durante o
    # ensaio ele precisa enxergar também patches já instalados, caso o novo
    # pacote contenha apenas alguns módulos.
    internal = _internal()
    for arquivo in internal.glob("*.py"):
        if arquivo.is_file() and not arquivo.is_symlink():
            shutil.copy2(arquivo, combinado / arquivo.name)
    for pasta in PASTAS & {"emily-gateway-service", "memoria_unificada", "emily_cloud"}:
        origem = internal / pasta
        if origem.is_dir() and not origem.is_symlink():
            for arquivo in origem.rglob("*.py"):
                if arquivo.is_file() and not arquivo.is_symlink():
                    alvo = combinado / arquivo.relative_to(internal)
                    alvo.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(arquivo, alvo)
    shutil.copytree(staging, combinado, dirs_exist_ok=True)
    ambiente = dict(os.environ, EMILY_PREFLIGHT="1",
                    EMILY_OVERRIDE_DIR=str(combinado), EMILY_PREFLIGHT_OUT=str(saida))
    execucao = subprocess.run([sys.executable], cwd=Path(sys.executable).parent,
                              env=ambiente, timeout=190, capture_output=True,
                              text=True, errors="replace")
    try:
        resultado = json.loads(saida.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("o ensaio da atualização não retornou um resultado") from None
    if execucao.returncode or resultado.get("rc"):
        raise RuntimeError("ensaio falhou: " + "; ".join(resultado.get("falhas") or [])[:500])


def _aplicar(staging: Path, dados: dict) -> None:
    internal = _internal()
    backup = internal / f"_windows_code_backup_{dados['version']}"
    if backup.exists():
        raise RuntimeError("backup dessa versão já existe; atualização incompleta")
    backup.mkdir(parents=True)
    escritos: list[tuple[Path, Path | None]] = []
    try:
        for nome in dados["files"]:
            relativo = _relativo_seguro(nome)
            alvo = internal / relativo
            if any(p.is_symlink() for p in (alvo, *alvo.parents) if p != internal.parent):
                raise ValueError("destino contém link simbólico")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            anterior = backup / relativo if alvo.exists() else None
            if anterior:
                anterior.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(alvo, anterior)
            temporario = alvo.with_name(alvo.name + ".code-update")
            shutil.copy2(staging / relativo, temporario)
            os.replace(temporario, alvo)
            escritos.append((alvo, anterior))
        marcador = internal / ".windows-code-version.json"
        temporario = marcador.with_suffix(".tmp")
        temporario.write_text(json.dumps({"version": dados["version"],
                                          "installer": dados["installer"]}), encoding="utf-8")
        os.replace(temporario, marcador)
    except BaseException:
        for alvo, anterior in reversed(escritos):
            if anterior is not None:
                shutil.copy2(anterior, alvo)
            else:
                alvo.unlink(missing_ok=True)
        shutil.rmtree(backup, ignore_errors=True)
        raise


def verificar_e_aplicar(sessao: requests.Session | None = None) -> bool:
    from windows_update import _config, _token, _windows_empacotado
    if not _windows_empacotado() or not _config().get("update_url") or not _token():
        return False
    sessao = sessao or requests.Session()
    try:
        resposta = sessao.get(_endpoint(), headers=_headers(), timeout=(3, 6))
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados.get("ok"):
            return False
        _validar_manifesto(dados)
        if dados["version"] <= _versao_local():
            return False
        with tempfile.TemporaryDirectory(prefix="emily-code-") as pasta:
            temporaria = Path(pasta)
            arquivo = temporaria / "codigo.zip"
            digest = hashlib.sha256()
            total = 0
            with sessao.get(_endpoint() + "/archive", headers=_headers(),
                            stream=True, timeout=(3, 120)) as remoto:
                remoto.raise_for_status()
                with arquivo.open("wb") as destino:
                    for bloco in remoto.iter_content(1024 * 1024):
                        total += len(bloco)
                        if total > dados["size"]:
                            raise ValueError("download maior que manifesto")
                        digest.update(bloco)
                        destino.write(bloco)
            if total != dados["size"] or digest.hexdigest() != dados["sha256"]:
                raise ValueError("integridade do download não confere")
            staging = temporaria / "stage"
            staging.mkdir()
            _extrair_validado(arquivo, staging, dados)
            _preflight(staging)
            _aplicar(staging, dados)
        subprocess.Popen([sys.executable], cwd=Path(sys.executable).parent, close_fds=True)
        print(f"[WINDOWS-CODE] atualizado para código {dados['version']}")
        return True
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError,
            RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[WINDOWS-CODE] atualização adiada: {type(exc).__name__}: {exc}")
        return False
