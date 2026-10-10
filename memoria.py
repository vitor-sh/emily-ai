"""
memoria.py — Sistema de memória inteligente da Emily
A Emily extrai fatos relevantes de QUALQUER conversa/ação automaticamente.
"""

import hashlib
import json
import os
import re
import threading
import datetime
import time
from typing import Any, Dict, List, Optional

from emily_paths import arquivo_dados

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARQUIVO  = str(arquivo_dados("memoria.json"))

# ──────────────────────────────────────────────────────────────
# Estrutura padrão da memória
# ──────────────────────────────────────────────────────────────
_ESTRUTURA_PADRAO: Dict[str, Any] = {
    "nome_usuario": os.getenv("EMILY_USUARIO", "Vitor"),
    "fatos":        [],          # lista de strings com fatos sobre o usuário
    "preferencias": {},          # {"jogos": [...], "apps": [...], ...}
    "pedidos_frequentes": {},    # {"organizar downloads": 3, ...}
    "ultima_atualizacao": "",
}

# Lock para evitar race conditions em gravações concorrentes
_lock = threading.RLock()   # reentrante: sync chama salvar_memoria dentro do lock


# ──────────────────────────────────────────────────────────────
# I/O
# ──────────────────────────────────────────────────────────────

def _memoria_vazia() -> Dict[str, Any]:
    # Cópia independente: dict() raso compartilhava a lista padrão de fatos
    # entre arquivos/sessões, e uma sync podia "vazar" fatos entre perfis.
    return {k: type(v)() if isinstance(v, (list, dict)) else v
            for k, v in _ESTRUTURA_PADRAO.items()}


def carregar_memoria() -> Dict[str, Any]:
    if not os.path.exists(ARQUIVO):
        return _memoria_vazia()
    try:
        with open(ARQUIVO, "r", encoding="utf-8") as f:
            dados = json.load(f)
        # Garante campos novos para versões antigas do arquivo
        for k, v in _ESTRUTURA_PADRAO.items():
            if k not in dados:
                dados[k] = v if not isinstance(v, (list, dict)) else type(v)()
        return dados
    except (json.JSONDecodeError, OSError):
        return _memoria_vazia()


def salvar_memoria(memoria: Dict[str, Any]) -> None:
    try:
        import modo_demo
        if modo_demo.ativo():
            return
    except Exception:
        pass
    with _lock:
        memoria["ultima_atualizacao"] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
        os.makedirs(os.path.dirname(ARQUIVO), exist_ok=True)
        temporario = ARQUIVO + ".tmp"
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(memoria, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, ARQUIVO)


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
    # Re-adicionar um fato apagado revive ele: tombstone fora.
    mem.get("apagados", {}).pop(_hash_fato(fato), None)
    salvar_memoria(mem)
    print(f"[MEMORIA] Novo fato salvo: {fato}")
    return True


def remover_fato(fato: str) -> bool:
    """Remove um fato exato da memória (e registra tombstone pra sincronização)."""
    mem = carregar_memoria()
    fatos = mem.get("fatos", [])
    if fato in fatos:
        fatos.remove(fato)
        mem["fatos"] = fatos
        apagados = mem.setdefault("apagados", {})
        apagados[_hash_fato(fato)] = time.time()
        _podar_apagados(apagados)
        salvar_memoria(mem)
        return True
    return False


def remover_fato_por_indice(idx: int) -> bool:
    mem = carregar_memoria()
    fatos = mem.get("fatos", [])
    if 0 <= idx < len(fatos):
        removido = fatos.pop(idx)
        mem["fatos"] = fatos
        apagados = mem.setdefault("apagados", {})
        apagados[_hash_fato(removido)] = time.time()
        _podar_apagados(apagados)
        salvar_memoria(mem)
        print(f"[MEMORIA] Fato removido: {removido}")
        return True
    return False


def listar_fatos() -> List[str]:
    return carregar_memoria().get("fatos", [])


# ─────────────────────────────────────────────────────────────
# Sincronização com o celular
# ─────────────────────────────────────────────────────────────

MAX_FATOS = 200            # teto de fatos (o celular usa o mesmo número)
TTL_APAGADOS = 30 * 24 * 3600   # tombstone de exclusão vale 30 dias


def _hash_fato(texto: str) -> str:
    """
    Chave estável de um fato: sha256 do texto aparado.
    O celular calcula O MESMO hash (MessageDigest SHA-256 em Kotlin) — os dois
    lados conversam por hash, e a exclusão viaja como tombstone {hash: quando}.
    """
    return hashlib.sha256((texto or "").strip().encode("utf-8")).hexdigest()


def _podar_apagados(apagados: Dict[str, float]) -> None:
    agora = time.time()
    for velho in [k for k, v in apagados.items() if v < agora - TTL_APAGADOS]:
        del apagados[velho]


def sincronizar_externa(fatos_externos: List[Any], apagados_externos: Dict[str, float]) -> Dict[str, Any]:
    """
    Une a memória daqui com a do celular em UMA chamada (empurra e puxa junto).

    Fatos só entram ou saem (nunca são editados), e cada fato do celular diz se
    foi CRIADO/EDITADO lá (local_novo=True) ou apenas importado daqui e intacto
    (local_novo=False). Isso resolve tudo SEM comparar relógios entre máquinas:

      - local_novo=True  → intenção explícita do usuário no celular: vence
        qualquer tombstone (revive) e entra se ainda não existir;
      - local_novo=False → o celular só reconfirma o que veio daqui: se o PC
        apagou (tombstone), continua apagado;
      - exclusões do celular chegam como tombstone {hash: quando} e são unidas
        aos daqui (30 dias de validade), apagando o fato nos dois lados.

    Determinístico, sem LLM. Devolve o ESTADO FINAL (o celular assume por
    inteiro e limpa as flags locais).
    """
    with _lock:
        mem = carregar_memoria()
        apagados = mem.setdefault("apagados", {})
        _podar_apagados(apagados)
        # 1) tombstones do celular: união, mantendo o mais recente por hash
        for h, quando in (apagados_externos or {}).items():
            apagados[h] = max(float(quando or 0), apagados.get(h, 0))
        _podar_apagados(apagados)

        atuais = list(mem.get("fatos", []))
        por_hash = {_hash_fato(f): f for f in atuais}
        # 2) fatos do celular
        for item in (fatos_externos or []):
            if isinstance(item, dict):
                texto = str(item.get("texto") or "").strip()
                local_novo = bool(item.get("local_novo"))
            else:
                texto = str(item or "").strip()
                local_novo = False
            if not texto:
                continue
            h = _hash_fato(texto)
            if local_novo:
                # intenção explícita no celular: vence tombstone e entra
                apagados.pop(h, None)
                if h not in por_hash:
                    atuais.append(texto)
                    por_hash[h] = texto
            else:
                # reconfirmação: só entra se NÃO estiver apagado
                if h in apagados:
                    continue
                if h not in por_hash:
                    atuais.append(texto)
                    por_hash[h] = texto
        # 3) exclusões: fato daqui que virou tombstone sai
        atuais = [f for f in atuais if _hash_fato(f) not in apagados]
        # 4) teto de segurança
        if len(atuais) > MAX_FATOS:
            atuais = atuais[-MAX_FATOS:]

        mem["fatos"] = atuais
        mem["apagados"] = apagados
        salvar_memoria(mem)
        return {"fatos": list(atuais), "apagados": dict(apagados)}

# ──────────────────────────────────────────────────────────────
# Pedidos frequentes
# ──────────────────────────────────────────────────────────────

def registrar_pedido(pedido: str) -> None:
    """Incrementa o contador de um tipo de pedido."""
    try:
        import modo_demo
        if modo_demo.ativo():
            return
    except Exception:
        pass
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

    nome = memoria.get("nome_usuario") or os.getenv("EMILY_USUARIO", "Vitor")
    linhas = [f"[O que você sabe sobre {nome}:]"]

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
    nome = os.getenv("EMILY_USUARIO", "Vitor")
    return f"""Analise esta conversa entre o usuário {nome} e sua assistente Emily.

CONTEXTO:
{contexto}

Sua tarefa é decidir se há ALGO REALMENTE RELEVANTE sobre {nome} que mereça ser lembrado a longo prazo. Por padrão, a resposta deve ser vazia ([]). Só extraia fatos se FOR realmente importante e DURÁVEL.

REGRAS RÍGIDAS — extraia APENAS se encaixar em UMA das categorias abaixo:

1. Dados biográficos dele: idade, profissão, cidade, onde estuda — algo PERMANENTE
2. Gostos e preferências FORTES: algo que ele ama ou odeia de verdade, não "até que gosto"
3. Preferências de comportamento DA EMILY: como ela deve agir ("não usa mais Kiro", "prefere respostas curtas")
4. Informações de saúde, alergias, limitações físicas
5. Algo que ele PEDIU EXPLICITAMENTE pra ser lembrado ("guarda aí", "lembra disso", "não esquece")

NÃO extraia NUNCA:
- Coisas triviais que ele disse uma vez só ("viu um vídeo", "ouviu uma música")
- O contexto imediato da conversa ("ele perguntou sobre X", "pediu pra tocar Y")
- Preferências passageiras ou hipotéticas
- Qualquer coisa que não seja um traço durável da personalidade, gosto ou vida dele

Responda SOMENTE com uma lista JSON de strings, sem explicações.
Se NÃO houver nada relevante, responda com: []"""


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


# Controla a frequência da extração automática: a cada N chamadas em que não
# houve pedido explícito, uma única tenta extrair. Sem isto, TODA resposta
# disparava uma chamada LLM de extração e acumulava fatos triviais.
_contador_extracao = {"n": 0}
_PASSOS_ENTRE_EXTRACOES = 6


def _deve_extrair_agora() -> bool:
    _contador_extracao["n"] += 1
    return _contador_extracao["n"] % _PASSOS_ENTRE_EXTRACOES == 0


def processar_conversa_async(usuario: str, emily: str) -> None:
    """
    Extrai fatos da conversa em background sem bloquear a UI.
    Chamado após cada resposta completa da Emily, mas só tenta a cada N
    mensagens (não em toda). O prompt já é rígido — por padrão devolve [].
    """
    if not _deve_extrair_agora():
        return

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
