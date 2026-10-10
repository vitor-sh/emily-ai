"""Log único da Emily, visível no terminal e dentro da interface.

No Konsole/VS Code a saída continua aparecendo normalmente e também é copiada
para o arquivo. Pelo atalho gráfico, onde não existe terminal, o mesmo arquivo
recebe tudo. A interface lê somente a cauda e mascara credenciais comuns.
"""
from __future__ import annotations

import io
import os
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, TextIO

_LIMITE_ROTACAO = 5 * 1024 * 1024
_LIMITE_LEITURA = 512 * 1024
_lock = threading.RLock()
_configurado = False
_arquivo: Optional[TextIO] = None


def caminho_log() -> Path:
    personalizado = os.environ.get("EMILY_LOG_PATH", "").strip()
    return (Path(personalizado).expanduser() if personalizado
            else Path.home() / ".emily_log.txt")


def _mesmo_arquivo(stream, caminho: Path) -> bool:
    nome = getattr(stream, "name", None)
    if not isinstance(nome, (str, os.PathLike)):
        return False
    try:
        return Path(nome).expanduser().resolve() == caminho.resolve()
    except (OSError, RuntimeError):
        return False


class _Tee(io.TextIOBase):
    """Replica escrita no console original e no arquivo, com lock por linha."""

    def __init__(self, console, arquivo: TextIO) -> None:
        self.console = console
        self.arquivo = arquivo

    @property
    def encoding(self):
        return getattr(self.console, "encoding", None) or "utf-8"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        try:
            return bool(self.console and self.console.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        destino = self.console if self.console is not None else self.arquivo
        return destino.fileno()

    def write(self, texto) -> int:
        valor = str(texto)
        with _lock:
            if self.console is not None:
                try:
                    self.console.write(valor)
                    self.console.flush()
                except Exception:
                    pass
            try:
                self.arquivo.write(valor)
                self.arquivo.flush()
            except Exception:
                pass
        return len(valor)

    def flush(self) -> None:
        with _lock:
            for destino in (self.console, self.arquivo):
                try:
                    if destino is not None:
                        destino.flush()
                except Exception:
                    pass


def configurar() -> Path:
    """Ativa o tee uma vez e devolve o caminho do arquivo de log."""
    global _configurado, _arquivo
    caminho = caminho_log()
    with _lock:
        if _configurado:
            return caminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        try:
            if caminho.exists() and caminho.stat().st_size > _LIMITE_ROTACAO:
                anterior = caminho.with_suffix(caminho.suffix + ".1")
                anterior.unlink(missing_ok=True)
                caminho.replace(anterior)
        except OSError:
            pass
        _arquivo = open(caminho, "a", encoding="utf-8", errors="replace",
                        buffering=1)

        # Runtime hooks antigos já apontam stdout direto para este arquivo.
        # Não embrulhar nesse caso evita escrever duas vezes na mesma saída.
        stdout_antigo, stderr_antigo = sys.stdout, sys.stderr
        sys.stdout = (_arquivo if _mesmo_arquivo(stdout_antigo, caminho)
                      else _Tee(stdout_antigo, _arquivo))
        sys.stderr = (_arquivo if _mesmo_arquivo(stderr_antigo, caminho)
                      else _Tee(stderr_antigo, _arquivo))
        _configurado = True
    return caminho


_SEGREDOS = (
    (re.compile(r"(?im)^([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|CHAVE)[A-Z0-9_]*\s*=\s*)\S+"),
     r"\1***"),
    (re.compile(r"(?i)(Authorization\s*[:=]\s*Bearer\s+)[A-Za-z0-9._~+/=-]+"),
     r"\1***"),
    (re.compile(r"(?i)([?&](?:token|key|api_key|auth)=)[^&\s]+"), r"\1***"),
)


def mascarar_segredos(texto: str) -> str:
    saida = texto
    for padrao, troca in _SEGREDOS:
        saida = padrao.sub(troca, saida)
    return saida


def ler(limite: int = 240_000) -> Dict[str, object]:
    """Lê somente a cauda do log, nunca o arquivo inteiro sem limite."""
    caminho = caminho_log()
    limite = max(4_096, min(int(limite or 240_000), _LIMITE_LEITURA))
    try:
        tamanho = caminho.stat().st_size
        with open(caminho, "rb") as arquivo:
            cortado = tamanho > limite
            if cortado:
                arquivo.seek(-limite, os.SEEK_END)
            bruto = arquivo.read()
        texto = bruto.decode("utf-8", errors="replace")
        if cortado:
            primeira_quebra = texto.find("\n")
            if primeira_quebra >= 0:
                texto = texto[primeira_quebra + 1:]
            texto = "[… início antigo omitido …]\n" + texto
        return {
            "ok": True, "texto": mascarar_segredos(texto),
            "caminho": str(caminho), "tamanho": tamanho,
            "modificado": caminho.stat().st_mtime,
        }
    except FileNotFoundError:
        return {"ok": True, "texto": "", "caminho": str(caminho),
                "tamanho": 0, "modificado": 0}
    except OSError as e:
        return {"ok": False, "texto": f"Não consegui ler o log: {e}",
                "caminho": str(caminho), "tamanho": 0, "modificado": 0}


def limpar() -> bool:
    caminho = caminho_log()
    try:
        with _lock:
            # Truncar pelo caminho funciona mesmo com o descritor do tee aberto.
            with open(caminho, "w", encoding="utf-8"):
                pass
        return True
    except OSError:
        return False