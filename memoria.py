import json
import os
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO = os.path.join(BASE_DIR, "memoria.json")


def carregar_memoria() -> Dict[str, Any]:
    if not os.path.exists(ARQUIVO):
        return {}

    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def salvar_memoria(memoria: Dict[str, Any]) -> None:
    with open(ARQUIVO, "w", encoding="utf-8") as f:
        json.dump(memoria, f, ensure_ascii=False, indent=2)


def lembrar_nome(memoria: Dict[str, Any]) -> str:
    if "nome_usuario" in memoria:
        return f"Oii {memoria['nome_usuario']}!"
    return "Oii! Qual é o seu nome?"


def formatar_para_prompt(memoria: Dict[str, Any]) -> str:
    if not memoria:
        return ""

    linhas = ["[O que você sabe sobre o Vitor:]"]

    if "nome_usuario" in memoria:
        linhas.append(f"- Nome: {memoria['nome_usuario']}")

    if "fatos" in memoria:
        for fato in memoria["fatos"]:
            linhas.append(f"- {fato}")

    return "\n".join(linhas)
