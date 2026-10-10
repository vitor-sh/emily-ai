"""Atualização do pacote Windows por instalador completo publicado no gateway."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

from emily_paths import arquivo_dados


def _config() -> dict:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    caminho = base / "windows-release.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        if os.name == "nt":
            from emily_remote import gateway_fedora
            salvo = gateway_fedora()
            if salvo:
                dados["sync_url"] = salvo
                dados["update_url"] = salvo + "/windows/update"
        return dados
    except (OSError, ValueError):
        return {}


def _versao(valor: str) -> tuple[int, ...]:
    partes = str(valor).split(".")
    if not 2 <= len(partes) <= 4 or any(not p.isdigit() for p in partes):
        raise ValueError("versão inválida")
    return tuple(int(p) for p in partes)


def _token() -> str:
    if os.getenv("EMILY_PONTE_TOKEN"):
        return os.environ["EMILY_PONTE_TOKEN"]
    from dotenv import dotenv_values
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(dotenv_values(base / ".env").get("EMILY_PONTE_TOKEN") or "")


def _windows_empacotado() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def consultar(sessao: requests.Session | None = None) -> dict:
    cfg = _config()
    atual = str(cfg.get("version") or "")
    base = str(cfg.get("update_url") or "").rstrip("/")
    estado = {"em_pacote": True, "modo_windows": True, "origem_ok": bool(base),
              "versao": atual, "versao_publicada": "", "quantos": 0,
              "resumo": "", "pode_desfazer": False}
    if not base:
        estado["erro"] = "endereço de atualização não configurado"
        return estado
    try:
        resposta = (sessao or requests.Session()).get(
            base, headers={"Authorization": f"Bearer {_token()}"}, timeout=(3, 5))
        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get("ok"):
            publicada = str(dados["version"])
            estado["versao_publicada"] = publicada
            estado["quantos"] = int(_versao(publicada) > _versao(atual))
            estado["resumo"] = f"versão {publicada}"
        else:
            estado["erro"] = str(dados.get("erro") or "feed indisponível")
    except (requests.RequestException, OSError, ValueError, KeyError) as exc:
        estado["erro"] = f"não consegui consultar o gateway: {type(exc).__name__}"
    if not estado["quantos"]:
        try:
            import windows_code_update
            codigo = windows_code_update.consultar(sessao)
            if codigo.get("quantos"):
                estado.update(codigo)
                estado.pop("erro", None)
        except Exception as exc:
            print(f"[WINDOWS-UPDATE] consulta de código adiada: {exc}")
    return estado


def _verificar_codigo(sessao: requests.Session) -> bool:
    try:
        import windows_code_update
        return windows_code_update.verificar_e_aplicar(sessao)
    except Exception as exc:
        print(f"[WINDOWS-UPDATE] código adiado: {type(exc).__name__}: {exc}")
        return False


def verificar_e_instalar(sessao: requests.Session | None = None) -> bool:
    """Retorna True só quando o instalador foi validado e iniciado."""
    if not _windows_empacotado():
        return False
    cfg = _config()
    base = str(cfg.get("update_url") or "").rstrip("/")
    if not base or not base.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        return False
    token = _token()
    if not token:
        return False
    sessao = sessao or requests.Session()
    headers = {"Authorization": f"Bearer {token}"}
    temporario = None
    try:
        resposta = sessao.get(base, headers=headers, timeout=(3, 5))
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados.get("ok") or _versao(dados["version"]) <= _versao(cfg["version"]):
            return _verificar_codigo(sessao)
        tamanho = int(dados["size"])
        esperado = str(dados["sha256"]).lower()
        if not 0 < tamanho <= 2 * 1024 ** 3 or len(esperado) != 64:
            raise ValueError("metadados do instalador inválidos")
        int(esperado, 16)
        destino = arquivo_dados("updates") / f"Emily-Setup-{dados['version']}.exe"
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".download")
        baixado = 0
        digest = hashlib.sha256()
        with sessao.get(base + "/installer", headers=headers, stream=True,
                        timeout=(3, 120)) as remoto:
            remoto.raise_for_status()
            with temporario.open("wb") as saida:
                for bloco in remoto.iter_content(1024 * 1024):
                    if not bloco:
                        continue
                    baixado += len(bloco)
                    if baixado > tamanho:
                        raise ValueError("download maior que o manifesto")
                    digest.update(bloco)
                    saida.write(bloco)
        if baixado != tamanho or digest.hexdigest() != esperado:
            raise ValueError("integridade do instalador não confere")
        os.replace(temporario, destino)
        subprocess.Popen([str(destino), "/VERYSILENT", "/SUPPRESSMSGBOXES",
                          "/NORESTART", "/CLOSEAPPLICATIONS"],
                         close_fds=True)
        print(f"[WINDOWS-UPDATE] instalando versão {dados['version']}")
        return True
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[WINDOWS-UPDATE] atualização adiada: {type(exc).__name__}: {exc}")
        return False
    finally:
        if temporario is not None:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
