"""Atalho local do press to talk nos desktops Fedora e Windows."""

from __future__ import annotations

import re
import threading

PADRAO = "mb5"
_MOUSE = {"mb4": "Botão lateral 1", "mb5": "Botão lateral 2",
          "middle": "Botão do meio"}
_ESPECIAIS = {
    "space": "Espaço", "tab": "Tab", "enter": "Enter",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "pageup": "Page Up", "pagedown": "Page Down",
    "up": "Seta ↑", "down": "Seta ↓", "left": "Seta ←", "right": "Seta →",
}
_CAPTURA_LOCK = threading.Lock()
_CAPTURA_TOKEN = None
_CAPTURA_REQUISICAO = None
_CAPTURA_SEQUENCIA = 0
_REQUISICOES_CANCELADAS: set[str] = set()


def normalizar(valor: object) -> str | None:
    """Aceita uma tecla simples ou botão de mouse, sem combinações."""
    if not isinstance(valor, str):
        return None
    tecla = valor.strip().lower()
    if re.fullmatch(r"scan:[1-9]\d{0,4}", tecla):
        return tecla
    if re.fullmatch(r"mouse:27[2-9]", tecla):
        return tecla
    if tecla in _MOUSE or tecla in _ESPECIAIS:
        return tecla
    if re.fullmatch(r"f(?:[1-9]|1\d|2[0-4])", tecla):
        return tecla
    if re.fullmatch(r"[a-z0-9]", tecla):
        return tecla
    return None


def rotulo(tecla: str) -> str:
    if tecla.startswith("scan:"):
        return f"Tecla {tecla.split(':', 1)[1]}"
    if tecla.startswith("mouse:"):
        return {"272": "Botão esquerdo", "273": "Botão direito",
                "274": "Botão do meio", "275": "Botão lateral 1",
                "276": "Botão lateral 2", "277": "Botão avançar",
                "278": "Botão voltar", "279": "Botão extra"}.get(tecla.split(":", 1)[1], "Mouse")
    return _MOUSE.get(tecla) or _ESPECIAIS.get(tecla) or tecla.upper()


def atual() -> str:
    import preferencias

    return normalizar(preferencias.obter("tecla_ptt", PADRAO)) or PADRAO


def estado() -> dict:
    tecla = atual()
    import preferencias
    rotulo_salvo = preferencias.obter("tecla_ptt_rotulo", "")
    return {"tecla": tecla, "rotulo": rotulo_salvo or rotulo(tecla), "padrao": PADRAO}


def definir(valor: object) -> dict:
    tecla = normalizar(valor)
    if tecla is None:
        return {"ok": False, "erro": "Escolha uma tecla única ou um botão do mouse."}
    import preferencias

    preferencias.definir(tecla_ptt=tecla, tecla_ptt_rotulo="")
    preferencias.recarregar()  # confirma o valor no disco, inclusive se a gravação falhou
    return {"ok": atual() == tecla, **estado()}


def definir_capturada(tecla: str, nome: str) -> dict:
    """Persiste o código físico e o nome exibido, ambos locais ao computador."""
    tecla = normalizar(tecla)
    if tecla is None or not (tecla.startswith("scan:") or tecla.startswith("mouse:")):
        return {"ok": False, "erro": "Entrada física inválida."}
    import preferencias
    preferencias.definir(tecla_ptt=tecla, tecla_ptt_rotulo=str(nome)[:60])
    preferencias.recarregar()
    return {"ok": atual() == tecla, **estado()}


def capturando(token: int | None = None) -> bool:
    with _CAPTURA_LOCK:
        return _CAPTURA_TOKEN is not None and (token is None or _CAPTURA_TOKEN == token)


def requisicao_cancelada(requisicao: str | None) -> bool:
    with _CAPTURA_LOCK:
        return bool(requisicao and requisicao in _REQUISICOES_CANCELADAS)


def iniciar_captura(requisicao: str | None = None) -> int | None:
    global _CAPTURA_TOKEN, _CAPTURA_REQUISICAO, _CAPTURA_SEQUENCIA
    with _CAPTURA_LOCK:
        if _CAPTURA_TOKEN is not None or (requisicao and requisicao in _REQUISICOES_CANCELADAS):
            return None
        _CAPTURA_SEQUENCIA += 1
        _CAPTURA_TOKEN = _CAPTURA_SEQUENCIA
        _CAPTURA_REQUISICAO = requisicao
        return _CAPTURA_TOKEN


def finalizar_captura(token: int | None = None) -> None:
    global _CAPTURA_TOKEN, _CAPTURA_REQUISICAO
    with _CAPTURA_LOCK:
        if token is None or _CAPTURA_TOKEN == token:
            _CAPTURA_TOKEN = None
            _CAPTURA_REQUISICAO = None


def cancelar_captura(requisicao: str | None = None) -> None:
    global _CAPTURA_TOKEN, _CAPTURA_REQUISICAO
    with _CAPTURA_LOCK:
        if requisicao:
            _REQUISICOES_CANCELADAS.add(requisicao)
            if len(_REQUISICOES_CANCELADAS) > 100:
                _REQUISICOES_CANCELADAS.clear()
                _REQUISICOES_CANCELADAS.add(requisicao)
        if requisicao is None or _CAPTURA_REQUISICAO == requisicao:
            _CAPTURA_TOKEN = None
            _CAPTURA_REQUISICAO = None
