"""
memoria.py — Sistema de memória inteligente da Emily
A Emily extrai fatos relevantes de QUALQUER conversa/ação automaticamente.
"""

import json
import os
import re
import threading
import datetime
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO  = os.path.join(BASE_DIR, "memoria.json")

# ──────────────────────────────────────────────────────────────
# Estrutura padrão da memória
# ──────────────────────────────────────────────────────────────
_ESTRUTURA_PADRAO: Dict[str, Any] = {
    "nome_usuario": "Vitor",
    "fatos":        [],          # lista de strings com fatos sobre o usuário
    "preferencias": {},          # {"jogos": [...], "apps": [...], ...}
    "pedidos_frequentes": {},    # {"organizar downloads": 3, ...}
    "ultima_atualizacao": "",
}

# Lock para evitar race conditions em gravações concorrentes
_lock = threading.Lock()


# ──────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────

def carregar_memoria() -> Dict[str, Any]:
    if not os.path.exists(ARQUIVO):
        return dict(_ESTRUTURA_PADRAO)
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        # Garante campos novos para versões antigas do arquivo
        for k, v in _ESTRUTURA_PADRAO.items():
            if k not in dados:
                dados[k] = v if not isinstance(v, (list, dict)) else type(v)()
        return dados
    except (json.JSONDecodeError, OSError):
        return dict(_ESTRUTURA_PADRAO)


def salvar_memoria(memoria: Dict[str, Any]) -> None:
    with _lock:
        memoria["ultima_atualizacao"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        with open(ARQUIVO, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────
# CRUD de fatos
# ──────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────
# Deduplicação semântica via LLM
# ──────────────────────────────────────────────────────────────

def _fato_ja_conhecido_llm(novo_fato: str, fatos_existentes: List[str]) -> bool:
    """
    Pergunta ao LLM se a informação contida em `novo_fato` já está coberta
    por algum dos `fatos_existentes`. Retorna True se for duplicata semântica.
    Usado como filtro antes de persistir um fato novo.
    """
    if not fatos_existentes:
        return False
    try:
        import modelo as mdl
        lista = "\n".join(f"- {f}" for f in fatos_existentes[:30])
        prompt = f"""Você é um verificador de duplicatas em uma memória pessoal.

FATOS JÁ SALVOS:
{lista}

NOVO FATO CANDIDATO:
"{novo_fato}"

Tarefa: o novo fato transmite alguma informação que JÁ ESTÁ coberta (mesmo que com palavras diferentes) por algum dos fatos salvos?

Responda SOMENTE com: SIM ou NÃO"""
        resposta = mdl.chamar_llm_simples(prompt, max_tokens=10)
        if resposta:
            return resposta.strip().upper().startswith("SIM")
    except Exception as e:
        print(f"[MEMORIA] LLM dedup falhou, usando heurística: {e}")
    return False


def _fato_duplicado_heuristico(fato_lower: str, fatos: List[str]) -> bool:
    """Fallback rápido: verifica sobreposição de palavras (80%)."""
    palavras_novo = set(fato_lower.split())
    for f in fatos:
        palavras_exist = set(f.lower().split())
        if palavras_novo and palavras_exist:
            intersect = palavras_novo & palavras_exist
            ratio = len(intersect) / max(len(palavras_novo), len(palavras_exist))
            if ratio >= 0.80:
                return True
    return False


def adicionar_fato(fato: str, usar_llm: bool = True) -> bool:
    """
    Adiciona um fato à memória somente se ele trouxer informação NOVA.

    Fluxo de deduplicação (duas camadas):
    1. Heurística rápida: sobreposição de palavras ≥ 80%  → descarta
    2. LLM semântico    : pergunta se a info já é conhecida → descarta se SIM
    """
    fato = fato.strip()
    if not fato:
        return False

    mem   = carregar_memoria()
    fatos = mem.get("fatos", [])

    # ── Camada 1: heurística rápida (evita chamada LLM desnecessária) ──
    if _fato_duplicado_heuristico(fato.lower(), fatos):
        print(f"[MEMORIA] Duplicata heurística, ignorado: {fato}")
        return False

    # ── Camada 2: checagem semântica via LLM ──────────────────────────
    if usar_llm and fatos:
        if _fato_ja_conhecido_llm(fato, fatos):
            print(f"[MEMORIA] Duplicata semântica (LLM), ignorado: {fato}")
            return False

    fatos.append(fato)
    mem["fatos"] = fatos
    salvar_memoria(mem)
    print(f"[MEMORIA] Novo fato salvo: {fato}")
    return True


def remover_fato(fato: str) -> bool:
    """Remove um fato exato da memória."""
    mem = carregar_memoria()
    fatos = mem.get("fatos", [])
    if fato in fatos:
        fatos.remove(fato)
        mem["fatos"] = fatos
        salvar_memoria(mem)
        return True
    return False


def remover_fato_por_indice(idx: int) -> bool:
    mem = carregar_memoria()
    fatos = mem.get("fatos", [])
    if 0 <= idx < len(fatos):
        removido = fatos.pop(idx)
        mem["fatos"] = fatos
        salvar_memoria(mem)
        print(f"[MEMORIA] Fato removido: {removido}")
        return True
    return False


def listar_fatos() -> List[str]:
    return carregar_memoria().get("fatos", [])


# ──────────────────────────────────────────────────────────────
# Pedidos frequentes
# ──────────────────────────────────────────────────────────────

def registrar_pedido(pedido: str) -> None:
    """Incrementa o contador de um tipo de pedido."""
    if not pedido:
        return
    mem = carregar_memoria()
    pf  = mem.get("pedidos_frequentes", {})
    chave = pedido.strip().lower()[:60]
    pf[chave] = pf.get(chave, 0) + 1
    mem["pedidos_frequentes"] = pf
    # Se o usuário pediu ≥3 vezes a mesma coisa, cria um fato automático
    if pf[chave] == 3:
        adicionar_fato(f"Costuma pedir com frequência: '{chave}'")
    salvar_memoria(mem)


# ──────────────────────────────────────────────────────────────
# Formatação para prompt do modelo
# ──────────────────────────────────────────────────────────────

def formatar_para_prompt(memoria: Optional[Dict[str, Any]] = None) -> str:
    if memoria is None:
        memoria = carregar_memoria()
    if not memoria:
        return ""

    linhas = ["[O que você sabe sobre o Vitor:]"]

    if memoria.get("nome_usuario"):
        linhas.append(f"- Nome: {memoria['nome_usuario']}")

    fatos = memoria.get("fatos", [])
    if fatos:
        for fato in fatos[:20]:   # máximo 20 fatos no prompt
            linhas.append(f"- {fato}")

    prefs = memoria.get("preferencias", {})
    for categoria, itens in prefs.items():
        if itens:
            linhas.append(f"- Preferências em {categoria}: {', '.join(str(i) for i in itens[:5])}")

    pedidos = memoria.get("pedidos_frequentes", {})
    top = sorted(pedidos.items(), key=lambda x: x[1], reverse=True)[:3]
    for pedido, cnt in top:
        if cnt >= 2:
            linhas.append(f"- Pedido frequente ({cnt}x): {pedido}")

    return "\n".join(linhas) if len(linhas) > 1 else ""


def lembrar_nome(memoria: Optional[Dict[str, Any]] = None) -> str:
    if memoria is None:
        memoria = carregar_memoria()
    if "nome_usuario" in memoria and memoria["nome_usuario"]:
        return f"Oii {memoria['nome_usuario']}!"
    return "Oii! Qual é o seu nome?"


# ──────────────────────────────────────────────────────────────
# Extração INTELIGENTE de fatos via LLM
# ──────────────────────────────────────────────────────────────

def _prompt_extracao(contexto: str) -> str:
    return f"""Analise esta conversa/ação entre o usuário Vitor e sua assistente Emily.

CONTEXTO:
{contexto}

Sua tarefa é extrair APENAS fatos pessoais relevantes sobre o Vitor que merecem ser lembrados a longo prazo.

Exemplos do que vale guardar:
- Gostos, preferências, hobbies (ex: "Gosta de jogos de RPG")
- Habilidades, profissão, área de estudo (ex: "Programa em Python")
- Hábitos recorrentes (ex: "Costuma trabalhar à noite")
- Informações pessoais relevantes (ex: "Tem um monitor ultrawide")
- Preferências de comportamento da Emily (ex: "Prefere respostas diretas")

NÃO extraia:
- Coisas triviais ou de uma só vez
- Comandos técnicos pontuais
- Perguntas que não revelam preferência
- Fatos sobre terceiros que não sejam relevantes pro Vitor

Responda SOMENTE com uma lista JSON de strings, sem explicações.
Se não houver nada relevante, responda com: []

Exemplo de resposta válida:
["Gosta de jogos de RPG e estratégia", "Programa em Python e JavaScript"]"""


def extrair_fatos_da_conversa(usuario: str, emily: str) -> List[str]:
    """
    Chama o LLM para extrair fatos relevantes de uma troca de mensagens.
    Roda em thread separada para não bloquear a conversa.
    """
    try:
        import modelo as mdl
        contexto = f"Usuário: {usuario}\nEmily: {emily}"
        prompt   = _prompt_extracao(contexto)

        resposta = mdl.chamar_llm_simples(prompt, max_tokens=300)
        if not resposta:
            return []

        # Tenta parsear JSON da resposta
        match = re.search(r'\[.*?\]', resposta, re.DOTALL)
        if not match:
            return []

        fatos = json.loads(match.group())
        if isinstance(fatos, list):
            return [str(f).strip() for f in fatos if str(f).strip()]
        return []
    except Exception as e:
        print(f"[MEMORIA] Erro ao extrair fatos: {e}")
        return []


def extrair_fatos_de_acao(tipo_acao: str, detalhes: str) -> List[str]:
    """
    Extrai fatos a partir de ações como abrir apps, organizar downloads, etc.
    Mais leve — usa heurísticas diretas sem chamar LLM.
    """
    fatos = []
    tipo  = tipo_acao.lower()
    det   = detalhes.lower()

    # Apps abertos com frequência
    apps_conhecidos = {
        "discord": "Usa o Discord com frequência",
        "spotify": "Ouve música pelo Spotify",
        "steam":   "Joga jogos na Steam",
        "vscode":  "Desenvolve software no VS Code",
        "brave":   "Usa o navegador Brave",
    }
    for app, fato in apps_conhecidos.items():
        if app in det:
            fatos.append(fato)

    return fatos


def processar_conversa_async(usuario: str, emily: str) -> None:
    """
    Extrai fatos da conversa em background sem bloquear a UI.
    Chamado após cada resposta completa da Emily.
    """
    def _worker():
        fatos = extrair_fatos_da_conversa(usuario, emily)
        novos = 0
        for fato in fatos:
            if adicionar_fato(fato):
                novos += 1
        if novos:
            print(f"[MEMORIA] {novos} fato(s) novo(s) extraído(s) da conversa.")
    threading.Thread(target=_worker, daemon=True).start()


def processar_acao_async(tipo_acao: str, detalhes: str) -> None:
    """Registra pedido frequente e extrai fatos de ações em background."""
    registrar_pedido(f"{tipo_acao}: {detalhes}"[:60])

    def _worker():
        fatos = extrair_fatos_de_acao(tipo_acao, detalhes)
        for fato in fatos:
            adicionar_fato(fato)
    threading.Thread(target=_worker, daemon=True).start()
