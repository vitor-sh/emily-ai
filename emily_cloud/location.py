"""Preferência persistente da localização física da Emily Cloud.

O arquivo de preferência fica fora do acervo para continuar acessível depois de
uma migração. ``EMILY_CLOUD_DIR`` permanece como override explícito (e é usado
pelos testes), mas a interface grava normalmente ``cloud-location.json``.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import secrets
from pathlib import Path


MARCADOR = ".emily-cloud-storage.json"


def arquivo_config() -> Path:
    override = os.getenv("EMILY_CLOUD_LOCATION_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.getenv("APPDATA") or os.getenv("LOCALAPPDATA")
                    or Path.home() / "AppData/Roaming")
        return base / "Emily" / "cloud-location.json"
    base = Path(os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "emily" / "cloud-location.json"


def pasta_original_padrao() -> Path:
    if os.name == "nt":
        base = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData/Local")
        return base / "Emily" / "Cloud"
    base = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "emily" / "cloud"


def dados_salvos() -> dict:
    try:
        dado = json.loads(arquivo_config().read_text(encoding="utf-8"))
        return dado if isinstance(dado, dict) else {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}


def pasta_salva() -> Path | None:
    bruto = str(dados_salvos().get("pasta") or "").strip()
    return Path(bruto).expanduser() if bruto else None


def pasta_ativa() -> Path:
    definida = os.getenv("EMILY_CLOUD_DIR", "").strip()
    if definida:
        return Path(definida).expanduser()
    return pasta_salva() or pasta_original_padrao()


def origem_configuracao() -> str:
    if os.getenv("EMILY_CLOUD_DIR", "").strip():
        return "ambiente"
    return "interface" if pasta_salva() else "padrao"


def salvar(pasta: Path, storage_id: str = "") -> Path:
    destino = Path(pasta).expanduser().absolute()
    if not destino.is_dir():
        raise ValueError("A pasta de armazenamento ainda não existe.")
    storage_id = str(storage_id or secrets.token_hex(16))
    marcador = destino / MARCADOR
    marcador.write_text(json.dumps({"storage_id": storage_id}, ensure_ascii=False),
                         encoding="utf-8")
    _salvar_dados({"pasta": str(destino), "storage_id": storage_id})
    return destino


def _salvar_dados(dados: dict) -> None:
    """Grava atomicamente a preferência sem acessar o disco configurado.

    Separar esta etapa permite restaurar uma preferência cujo HD está offline
    caso a ativação de um novo armazenamento falhe no meio do processo.
    """
    config = arquivo_config()
    config.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=".cloud-location-", suffix=".tmp",
                                      dir=str(config.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as arquivo:
            json.dump(dict(dados), arquivo, ensure_ascii=False, indent=2)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, config)
    finally:
        try:
            os.unlink(temporario)
        except OSError:
            pass


def restaurar_dados(dados: dict) -> None:
    """Restaura exatamente uma preferência anterior, mesmo com o HD offline."""
    if dados:
        _salvar_dados(dados)
    else:
        limpar()


def disponivel(pasta: Path) -> bool:
    """Impede recriar no SSD uma pasta de HD que foi desmontado."""
    if origem_configuracao() != "interface":
        return True
    dados = dados_salvos()
    salvo = pasta_salva()
    if salvo is None or salvo.absolute() != Path(pasta).expanduser().absolute():
        return False
    if not salvo.is_dir():
        return False
    esperado = str(dados.get("storage_id") or "")
    if not esperado:  # compatibilidade com preferência antiga sem marcador
        return True
    try:
        marcador = json.loads((salvo / MARCADOR).read_text(encoding="utf-8"))
        return str(marcador.get("storage_id") or "") == esperado
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False


def limpar() -> None:
    arquivo_config().unlink(missing_ok=True)


def arquivo_migracao() -> Path:
    return arquivo_config().with_name("cloud-migration.lock")


def iniciar_migracao(origem: Path, destino: Path) -> None:
    trava = arquivo_migracao()
    trava.parent.mkdir(parents=True, exist_ok=True)
    trava.write_text(json.dumps({
        "pid": os.getpid(), "inicio": time.time(),
        "origem": str(origem), "destino": str(destino),
    }, ensure_ascii=False), encoding="utf-8")


def finalizar_migracao() -> None:
    arquivo_migracao().unlink(missing_ok=True)


def migracao_ativa() -> bool:
    trava = arquivo_migracao()
    if not trava.is_file():
        return False
    try:
        dado = json.loads(trava.read_text(encoding="utf-8"))
        # Trava órfã de mais de 24 h não pode inutilizar a Cloud para sempre.
        if time.time() - float(dado.get("inicio") or 0) > 24 * 3600:
            trava.unlink(missing_ok=True)
            return False
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return True
    return True