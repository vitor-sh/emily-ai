from __future__ import annotations

import re
import unicodedata


PHRASES_PEDIR_ENCERRAMENTO = (
    "pode fechar a emily",
    "quero fechar a emily",
    "fechar a emily",
    "encerra a emily",
    "encerre a emily",
    "desligar a emily",
    "desliga a emily",
    "finalizar a emily",
    "finaliza a emily",
    "sair da emily",
    "pode encerrar a emily",
    "quero encerrar a emily",
    "tchau emily",
    "adeus emily",
    "até mais emily",
    "ate mais emily",
    "até logo emily",
    "ate logo emily",
)

WORDS_PEDIR_ENCERRAMENTO = (
    "sair",
    "tchau",
    "adeus",
)

PHRASES_CONFIRMACAO_POSITIVA = (
    "pode fechar",
    "pode encerrar",
    "pode desligar",
    "pode sair",
    "quero fechar",
    "quero encerrar",
)

WORDS_CONFIRMACAO_POSITIVA = (
    "sim",
    "pode",
    "quero",
    "isso",
    "claro",
    "beleza",
    "ok",
    "okay",
)

PHRASES_CONFIRMACAO_NEGATIVA = (
    "nao quero",
    "não quero",
    "melhor nao",
    "melhor não",
    "nao",
    "não",
)

WORDS_CONFIRMACAO_NEGATIVA = (
    "nao",
    "não",
    "nunca",
    "cancela",
    "cancelar",
    "fica",
    "continua",
    "continuar",
    "deixa",
    "para",
    "pare",
)


def _normalizar_texto(texto: str) -> str:
    if not texto:
        return ""

    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(caractere for caractere in texto if unicodedata.category(caractere) != "Mn")
    texto = re.sub(r"\s+", " ", texto)
    return texto.lower().strip()


def _tem_palavra(texto: str, palavra: str) -> bool:
    return re.search(rf"\b{re.escape(palavra)}\b", texto) is not None


def pede_encerramento(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    if any(frase in texto for frase in PHRASES_PEDIR_ENCERRAMENTO):
        return True

    if "emily" in texto:
        return any(
            _tem_palavra(texto, palavra)
            for palavra in (
                "fechar",
                "encerrar",
                "desligar",
                "finalizar",
                "sair",
            )
        )

    return any(_tem_palavra(texto, palavra) for palavra in WORDS_PEDIR_ENCERRAMENTO)


def confirma_encerramento(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    if any(frase in texto for frase in PHRASES_CONFIRMACAO_NEGATIVA):
        return False

    if any(frase in texto for frase in PHRASES_CONFIRMACAO_POSITIVA):
        return True

    return any(_tem_palavra(texto, palavra) for palavra in WORDS_CONFIRMACAO_POSITIVA)

    
# ──────────────────────────────────────────────
# MODO ESCRITO
# ──────────────────────────────────────────────

PHRASES_ATIVAR_MODO_ESCRITO = (
    "ativar modo escrito",
    "ativa modo escrito",
    "ativar o modo escrito",
    "ativa o modo escrito",
    "ligar modo escrito",
    "liga modo escrito",
    "iniciar modo escrito",
    "inicia modo escrito",
    "modo escrito ativar",
    "modo escrito ativa",
    "modo escrito on",
)

PHRASES_DESATIVAR_MODO_ESCRITO = (
    "desativar modo escrito",
    "desativa modo escrito",
    "desativar o modo escrito",
    "desativa o modo escrito",
    "desligar modo escrito",
    "desliga modo escrito",
    "parar modo escrito",
    "para modo escrito",
    "encerrar modo escrito",
    "encerra modo escrito",
    "modo escrito off",
    "modo escrito desativar",
    "modo escrito desativa",
)


def ativar_modo_escrito(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False
    return any(frase in texto for frase in PHRASES_ATIVAR_MODO_ESCRITO)


def desativar_modo_escrito(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False
    return any(frase in texto for frase in PHRASES_DESATIVAR_MODO_ESCRITO)

    return restante
