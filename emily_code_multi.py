"""
emily_code_multi.py — pipeline multi-modelo do Emily Code.

MiniMax-M3 planeja, Qwen 3.8 implementa, DeepSeek V4 Flash revisa.

O Vitor pediu explicitamente essa divisão de trabalho: cada modelo no que
é bom. O MiniMax (multimodal) entende o pedido e monta o plano; o Qwen
escreve o código de verdade; o DeepSeek audita antes de aplicar.

Regras do ciclo de revisão (do plano do Vitor):
  1. Máximo 3 rodadas de ida e volta. Sem consenso na 3ª, para e reporta.
  2. O DeepSeek DEVE apontar pelo menos um ponto de atenção antes de
     aprovar — "aprovado" em branco não vale.
  3. O Qwen justifica a correção antes de aplicar (via feedback do revisor).
  4. Todo o debate fica num log legível (~/.emily_code_debate.log).
  5. Consenso entre modelos NÃO é aprovação final — o Vitor revisa manual.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import List, Optional

import llm
import modelo

# ═════════════════════════════════════════════════════════════════
# CLASSIFICAÇÃO DE COMPLEXIDADE
# ═════════════════════════════════════════════════════════════════

# Palavras que indicam tarefa complexa (múltiplas etapas / lógica nova).
_COMPLEXAS = {
    "cria", "criar", "implementa", "implementar", "refatora", "refatorar",
    "adiciona", "adicionar", "remove", "remover", "módulo", "modulo",
    "sistema", "função", "funcao", "classe", "múltiplos", "multiplos",
    "vários", "varios", "arquivos", "estrutura", "organiza", "organizar",
    "reestrutura", "migra", "migrar", "converte", "converter", "integra",
    "integrar", "validação", "validacao", "formata", "formatar", "bug",
    "corrige", "corrigir", "ajusta", "ajustar", "reescreve", "reescrever",
    "novo", "nova", "código", "codigo",
}

# Arquivos críticos pro funcionamento da Emily: qualquer mudança neles
# sempre dispara o pipeline completo (com revisão dupla).
_CRITICOS = {
    "emily_code.py", "modelo.py", "llm.py", "ferramentas.py",
    "voz.py", "main.py", "interface_web.py", "interface.py",
    "terminal.py", "laco_ferramentas.py", "automacao.py",
    "discord_bot.py", "emily_code_multi.py",
}


def _eh_complexo(pedido: str, historico: list = None) -> bool:
    """
    Decide se o pedido merece o pipeline completo (3 modelos) ou só um.

    O pipeline multi-modelo faz sentido pra tarefas de EDIÇÃO/IMPLEMENTAÇÃO
    (o Qwen muda código, o DeepSeek revisa o diff). Tarefa de LEITURA/ANÁLISE
    pura ("analisa o arquivo", "acha bugs", "me diz o que tem") NÃO deve
    passar por ele — o Qwen só leria, não haveria diff pro revisor auditar, e
    o ciclo inteiro vira 3 rodadas de "não tenho o que revisar".

    Dispara quando (qualquer um):
      - o pedido TEM intenção de mudar código (verbo de edição) e
        menciona arquivo crítico da Emily, OU
      - tem 2+ palavras-chave de complexidade E verbo de edição, OU
      - é longo com verbo de edição
    """
    texto = (pedido or "").lower()
    # Só considera verbo de edição no IMPERATIVO (ordem direta).
    # Infinitivo (corrigir, editar, arrumar) em contexto de "vale + infinitivo",
    # "pra + infinitivo", "precisa + infinitivo" é ENQUADRAMENTO de análise,
    # não comando. Ex: "vê se tem bug que vale corrigir" NÃO é edição.
    eh_edicao = any(v in texto for v in (
        "corrige", "corrija", "edita", "edite",
        "muda", "mude", "altera", "altere",
        "implementa", "implemente", "cria",
        "adiciona", "adicione", "remove", "remova",
        "conserta", "conserte", "reescreve", "reescreva",
        "refatora", "refatore", "escreve", "arruma", "arrume",
        "resolve", "resolva", "troca", "troque",
    ))

    # Sem intenção de mudar código → não é tarefa do pipeline (é análise).
    # Com intenção de mudar código → pipeline multi-modelo. As verificações
    # de arquivo crítico/palavras abaixo são mérito extra pra pegar casos
    # onde o verbo de edição é indireto, mas eh_edicao já é o filtro principal.
    if not eh_edicao:
        return False
    return True

# ═════════════════════════════════════════════════════════════════
# AUTO-APROVAÇÃO DE PERMISSÕES
# ═════════════════════════════════════════════════════════════════

def _auto_aprovar_permissoes():
    """
    Registra "permitir sempre" pra pasta de projeto nas categorias
    escrita/execução. Assim o Qwen não abre modal a cada edição durante
    o pipeline multi-modelo. A revisão manual final (regra 5) continua
    sendo o portão de segurança.
    """
    import emily_code
    raiz = emily_code.projeto_raiz()
    if not raiz:
        return
    emily_code.registrar_permissao_sempre("escrever", raiz)
    emily_code.registrar_permissao_sempre("executar", raiz)


# Lock que protege o monkeypatch de emily_code.executar contra race conditions
# quando dois pipelines multi-modelo rodam simultaneamente.
_lock_hook = threading.Lock()


# ═════════════════════════════════════════════════════════════════
# CAPTURA DE DIFF
# ═════════════════════════════════════════════════════════════════

# Dicionário: arquivo -> conteúdo ANTES da edição. O pipeline salva aqui
# antes de cada escrita, e o diff é calculado depois.
_antes_por_arquivo: dict = {}
_lock_antes = threading.Lock()


def _salvar_antes(arquivo: str) -> None:
    """Guarda o conteúdo atual de um arquivo antes de editar."""
    import emily_code
    caminho = emily_code._resolver(arquivo)
    if caminho and caminho.is_file():
        try:
            conteudo = caminho.read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            conteudo = ""
        with _lock_antes:
            _antes_por_arquivo[arquivo] = conteudo


def _calcular_diff(arquivo: str) -> str:
    """
    Lê o arquivo e calcula diff contra o conteúdo anterior.
    Devolve o diff unificado ou "(sem alterações)" se nada mudou.
    """
    import emily_code
    caminho = emily_code._resolver(arquivo)
    if not caminho or not caminho.is_file():
        return "(arquivo não encontrado após edição)"
    try:
        atual = caminho.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"(erro ao ler: {e})"
    with _lock_antes:
        anterior = _antes_por_arquivo.get(arquivo, "")
    if anterior == atual:
        return "(sem alterações)"
    diff = list(difflib.unified_diff(
        anterior.splitlines(keepends=True),
        atual.splitlines(keepends=True),
        fromfile=arquivo, tofile=arquivo,
        lineterm="",
    ))
    return "".join(diff) if diff else "(sem alterações perceptíveis)"

# ═════════════════════════════════════════════════════════════════
# LOG DO DEBATE
# ═════════════════════════════════════════════════════════════════

def _log_debate(rodada: int, rotulo: str, entrada: str, saida: str) -> None:
    """
    Registra a conversa entre os modelos num arquivo de log legível,
    pra o Vitor ler o "debate" depois. Regra 4 do plano.
    """
    try:
        arquivo = Path.home() / ".emily_code_debate.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(arquivo, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"[{timestamp}] Rodada {rodada} — {rotulo}\n")
            f.write(f"{'=' * 60}\n")
            f.write(f"ENTRADA:\n{(entrada or '')[:800]}\n\n")
            f.write(f"SAÍDA:\n{(saida or '')[:3000]}\n")
    except Exception as e:  # noqa: BLE001
        print(f"[EMILY-CODE-MULTI] não consegui logar debate: {e}")


# ═════════════════════════════════════════════════════════════════
# PARSING DA REVISÃO
# ═════════════════════════════════════════════════════════════════

def _analisar_aprovacao(texto_revisor: str) -> dict:
    """
    Extrai do texto do revisor: aprovado (bool) + pontos de atenção (list).

    O DeepSeek deve devolver JSON:
      {"aprovado": true/false, "pontos": [...], "justificativa": "..."}
    Se não der pra parsear, assume NÃO aprovado com o texto cru como ponto
    (seguro: sem consenso, não aplica).
    """
    texto = (texto_revisor or "").strip()
    # Tenta achar um objeto JSON no meio do texto
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if m:
        candidato = m.group()
        try:
            dados = json.loads(candidato)
            if isinstance(dados, dict):
                pontos = dados.get("pontos") or []
                if isinstance(pontos, str):
                    pontos = [pontos]
                if not isinstance(pontos, list):
                    pontos = []
                return {
                    "aprovado": bool(dados.get("aprovado", False)),
                    "pontos": [str(p) for p in pontos if str(p).strip()],
                    "justificativa": str(dados.get("justificativa", "")),
                }
        except (json.JSONDecodeError, TypeError):
            pass
    # Fallback: sem JSON confiável → não aprovado
    return {"aprovado": False, "pontos": [texto[:300]] if texto else ["sem resposta do revisor"],
            "justificativa": ""}

# ═════════════════════════════════════════════════════════════════
# PLANEJADOR (MiniMax)
# ═════════════════════════════════════════════════════════════════

_ROTA_PLANEJADOR = "code_planejador"  # MiniMax-M3, rota DEDICADA (não usa "conversa" que pode estar trocada)


def _planejar(pedido: str) -> str:
    """MiniMax-M3 monta o plano de implementação em etapas."""
    prompt = (
        "Você é o arquiteto de um projeto de software chamado Emily, "
        "assistente pessoal do Vitor. Ele pediu:\n\n"
        f"{pedido}\n\n"
        "Crie um plano de implementação em etapas. Para cada etapa, liste "
        "qual arquivo editar (caminho relativo) e o que mudar, com detalhe "
        "suficiente pra outro programador executar sem precisar perguntar.\n"
        "Responda em português, direto, sem cerimônia, sem saudação. "
        "Formato:\n"
        "- Etapa 1: <arquivo> — <o que mudar>\n"
        "- Etapa 2: <arquivo> — <o que mudar>"
    )
    try:
        plano = modelo.chamar_llm_simples(
            prompt, max_tokens=2048, rota=_ROTA_PLANEJADOR)
    except Exception as e:
        print(f"[EMILY-CODE-MULTI] planejador falhou: {e}")
        plano = ""
    _log_debate(0, "MiniMax-Planejador", pedido, plano or "(vazio)")
    return plano or "(o planejador não devolveu plano; seguindo sem plano)"


# ═════════════════════════════════════════════════════════════════
# REVISOR (DeepSeek)
# ═════════════════════════════════════════════════════════════════

_ROTA_REVISOR = "code_revisor"


def _revisar(pedido: str, plano: str, diffs: str, rodada: int,
             historico_debate: str) -> dict:
    """
    DeepSeek audita a implementação do Qwen.

    Recebe o plano, o diff real do que mudou, e o histórico do debate.
    DEVE apontar pelo menos um ponto de atenção antes de aprovar (regra 2).
    """
    prompt = (
        "Você é um revisor de código sênior. O Vitor pediu:\n\n"
        f"{pedido}\n\n"
        "O PLANO aprovado era:\n"
        f"{plano}\n\n"
        "O QUE FOI IMPLEMENTADO (diff real, arquivos alterados):\n"
        f"{diffs or '(sem diffs disponíveis)'}\n"
        f"{historico_debate}\n"
        "\nTarefa: audite a implementação contra o plano. "
        "IMPORTANTE: você DEVE apontar pelo menos UM ponto de atenção "
        "específico e concreto antes de aprovar (ex: nome de variável ruim, "
        "falta de tratamento de erro, edge case não coberto, lógica que não "
        "bate com o plano). Aprovação em branco, sem apontamento nenhum, não "
        "é permitida. Verbosidade não conta como ponto — precisa ser concreto.\n"
        "\nResponda SOMENTE em JSON, sem texto fora dele:\n"
        '{"aprovado": true|false, '
        '"pontos": ["ponto 1", "ponto 2"], '
        '"justificativa": "resumo curto"}'
    )
    texto = modelo.chamar_llm_simples(
        prompt, max_tokens=2048, rota=_ROTA_REVISOR)
    _log_debate(rodada, "DeepSeek-Revisor", prompt[:1000], texto)
    return _analisar_aprovacao(texto)

# ═════════════════════════════════════════════════════════════════
# IMPLEMENTADOR (Qwen)
# ═════════════════════════════════════════════════════════════════

_ROTA_IMPLEMENTADOR = "code_debatedor"


def _implementar(pedido: str, plano: str, feedback: str,
                 historico_conversa: list, rodada: int,
                 on_progresso=None) -> str:
    """
    Qwen executa o plano usando as ferramentas code_*. Roda o laço de
    ferramentas do modelo com a rota do Qwen.
    on_progresso — repassado pro conversar_com_ferramentas pra UI.
    """
    import emily_code

    if rodada == 0:
        instrucao = (
            "Você está no Emily Code multi-modelo, implementando um plano "
            "aprovado. Use as ferramentas code_* pra ler, editar e criar "
            "arquivos, seguindo o plano exatamente:\n\n"
            f"{plano}\n\n"
            "Execute cada etapa. Antes de editar um arquivo, leia ele. Depois "
            "de concluir todas as etapas, resuma em 1-2 frases o que mudou.\n\n"
            "IMPORTANTE — nunca pare no meio: depois de usar uma ferramenta, "
            "continue a tarefa chamando a PRÓXIMA ferramenta necessária até "
            "concluir o que o plano pede. Só responda em texto quando o trabalho "
            "estiver FEITO. Ler um arquivo não é concluir: se você leu pra "
            "editar, a próxima chamada é a edição. Não diga 'vou fazer X' e "
            "parar — faça X. Você pode chamar VÁRIAS ferramentas na MESMA "
            "resposta (ex: ler vários arquivos em paralelo)."
        )
        mensagem = pedido
    else:
        instrucao = (
            "Você está corrigindo sua implementação anterior baseado no "
            "feedback do revisor. Use as ferramentas code_* pra fazer as "
            "correções. Antes de editar, leia o arquivo.\n\n"
            f"FEEDBACK DO REVISOR:\n{feedback}\n\n"
            "Corrija cada ponto apontado. Depois, resuma o que ajustou.\n\n"
            "IMPORTANTE — nunca pare no meio: corrija TODOS os pontos do "
            "feedback, chamando as ferramentas necessárias até concluir. Não "
            "descreva a correção sem executá-la."
        )
        mensagem = "Corrige a implementação conforme o feedback do revisor."

    # Salva o histórico do code pra não poluir, e restaura no fim.
    hist_antes = list(modelo.historico)
    modelo.historico[:] = list(historico_conversa)
    # Abre o domínio code (garante que as ferramentas code_* estão na mesa).
    try:
        modelo._abrir_dominio("code")
    except Exception:
        pass

    # Instala hook pra capturar o "antes" de qualquer escrita/edição que o
    # Qwen fizer, pra calcular o diff real pro revisor depois.
    # Usa lock pra evitar race condition se dois pipelines rodarem ao mesmo
    # tempo (improvável, mas seguro).
    _executar_original = emily_code.executar
    def _executar_com_hook(acao, **campos):
        if acao in ("escrever_arquivo", "editar_arquivo",
                    "editar_linhas", "editar_multi"):
            arquivo = campos.get("arquivo", "")
            if arquivo:
                _salvar_antes(arquivo)
        elif acao == "editar_transacao":
            for ed in campos.get("edicoes") or []:
                if isinstance(ed, dict):
                    arquivo = str(ed.get("arquivo", "")).strip()
                    if arquivo:
                        _salvar_antes(arquivo)
        return _executar_original(acao, **campos)

    with _lock_hook:
        emily_code.executar = _executar_com_hook

    try:
        resp = modelo.conversar_com_ferramentas(
            mensagem,
            instrucao_extra=instrucao,
            rota_nome=_ROTA_IMPLEMENTADOR,
            on_progresso=on_progresso,
        )
    finally:
        with _lock_hook:
            emily_code.executar = _executar_original
        modelo.historico[:] = hist_antes

    resultado = resp or "Feito."
    _log_debate(rodada, "Qwen-Implementador", instrucao[:600], resultado)
    return resultado

# ═════════════════════════════════════════════════════════════════
# ORQUESTRADOR PRINCIPAL
# ═════════════════════════════════════════════════════════════════

MAX_RODADAS_REVISAO = 3


def processar(pedido: str, historico_conversa: list,
              on_progresso=None) -> str:
    """
    Pipeline completo: planeja (MiniMax) → implementa (Qwen) → revisa
    (DeepSeek), com loop de revisão de até MAX_RODADAS_REVISAO.

    on_progresso — repassado pro laço de ferramentas do Qwen, pra a interface
                   mostrar o que está rodando em tempo real.

    Devolve o texto final (o que aparece no terminal / é salvo na conversa).
    """
    # Garante permissões pra o Qwen editar sem modal.
    try:
        _auto_aprovar_permissoes()
    except Exception as e:  # noqa: BLE001
        print(f"[EMILY-CODE-MULTI] auto-aprovação falhou: {e}")

    # ── 1. PLANEJAR (MiniMax) ──
    plano = _planejar(pedido)

    historico_debate = ""
    feedback = ""
    diffs_acumulados = ""
    resultado_final = ""

    for rodada in range(1, MAX_RODADAS_REVISAO + 1):
        # ── 2. IMPLEMENTAR (Qwen) ──
        try:
            resultado = _implementar(
                pedido, plano, feedback, historico_conversa, rodada,
                on_progresso)
        except Exception as e:  # noqa: BLE001
            print(f"[EMILY-CODE-MULTI] implementação falhou: {e}")
            return (f"O implementador (Qwen) falhou: {e}\n\n"
                    f"Plano que ele seguia:\n{plano}")
        resultado_final = resultado

        # Coleta diffs dos arquivos editados nesta rodada.
        diffs = _coletar_diffs()
        if diffs:
            diffs_acumulados = diffs_acumulados + ("\n" if diffs_acumulados else "") + diffs
        if historico_debate:
            historico_debate += "\n\n"

        # ── 3. REVISAR (DeepSeek) ──
        try:
            review = _revisar(pedido, plano, diffs or resultado,
                              rodada, historico_debate)
        except Exception as e:  # noqa: BLE001
            print(f"[EMILY-CODE-MULTI] revisão falhou: {e}")
            return (
                f"{resultado_final}\n\n"
                f"[Revisor (DeepSeek) indisponível no momento: {e}]\n"
                f"**O código foi alterado. Revise manualmente antes de considerar pronto.**"
            )

        pontos = review.get("pontos", [])
        justificativa = review.get("justificativa", "")

        if review.get("aprovado", False):
            # Aprovado (com pelo menos um ponto, garantido pelo prompt).
            nota_pontos = "; ".join(pontos) if pontos else "(sem apontamentos)"
            return (
                f"{resultado_final}\n\n"
                f"[Revisão aprovada pelo DeepSeek]\n"
                f"Pontos verificados: {nota_pontos}\n"
                f"{justificativa}\n"
                f"**Lembrete: revise manualmente antes de considerar pronto (regra 5).**"
            )

        if rodada < MAX_RODADAS_REVISAO:
            # Prepara feedback pra próxima rodada (o Qwen corrige).
            feedback = "\n".join(f"- {p}" for p in pontos) if pontos else (
                "O revisor não apontou nada específico; refaça conferindo o plano.")
            historico_debate += (
                f"Rodada {rodada} — DeepSeek NÃO aprovou. Pontos:\n{feedback}"
            )
            _log_debate(rodada, "Feedback → Qwen", "", feedback)
        else:
            # Última rodada sem consenso: para e reporta (regra 1).
            pontos_txt = "\n".join(f"- {p}" for p in pontos) if pontos else "(não especificou)"
            return (
                f"{resultado_final}\n\n"
                f"[ATENÇÃO] O revisor (DeepSeek) e o implementador (Qwen) "
                f"não chegaram a consenso após {MAX_RODADAS_REVISAO} rodadas.\n"
                f"Últimos pontos do revisor:\n{pontos_txt}\n"
                f"{justificativa}\n"
                f"**O código foi alterado. Revise manualmente antes de considerar pronto.**"
            )

    return resultado_final


def _coletar_diffs() -> str:
    """
    Calcula o diff acumulado de todos os arquivos que foram editados
    (que têm entrada em _antes_por_arquivo e mudaram no disco).
    """
    import emily_code
    blocos = []
    with _lock_antes:
        arquivos = list(_antes_por_arquivo.keys())
    for arquivo in arquivos:
        diff = _calcular_diff(arquivo)
        if diff and diff != "(sem alterações)":
            blocos.append(f"### {arquivo}\n{diff}")
    # Limpa pra próxima rodada não repetir diffs antigos.
    with _lock_antes:
        _antes_por_arquivo.clear()
    return "\n\n".join(blocos)


def deepseek_configurado() -> bool:
    """
    True se a rota REVISORA do pipeline multi-modelo está utilizável.

    O nome ficou por compatibilidade (nasceu quando o revisor era o
    DeepSeek), mas o provedor DeepSeek foi removido do .env: o revisor hoje
    é o Haiku do próprio provedor ativo. Então o teste virou genérico —
    a rota 'code_revisor' existe E o provedor dela tem chave de verdade.

    Rodar o pipeline sem revisor real seria perigoso: o implementador
    auto-aprovaria permissões e editaria código sem nenhuma revisão. Por
    isso a chave é verificada de verdade, e não só a presença da seção.

    Aceita os DOIS formatos de _CHAVE no .env:
      - nome de env var (padrão do projeto): EMILY_PROVEDOR_X_CHAVE=CHAVE_X
      - valor direto: EMILY_PROVEDOR_X_CHAVE=sk-xxxx
    """
    try:
        cfg_rota = llm.rota(_ROTA_REVISOR)
    except Exception:
        return False
    provedor = llm.PROVEDORES.get(cfg_rota.provedor)
    if provedor is None:
        return False
    cfg = llm.PROVEDORES_CONFIG.get(cfg_rota.provedor)
    # Provedor de seção do .env: o que importa é a chave resolvida.
    if cfg is not None:
        if cfg.env_chave_opcional:
            return True   # sem chave exigida (ex.: OmniRoute/Ollama local)
        chave = cfg.env_chave
        # Valor direto no campo _CHAVE (começa com sk-) conta como configurado.
        if chave.startswith("sk-"):
            return True
        return bool(os.getenv(chave))
    # Provedor legado: sem config de seção, confia no env_chave do objeto.
    env_chave = getattr(provedor, "env_chave", "") or ""
    if env_chave.startswith("sk-"):
        return True
    return bool(os.getenv(env_chave))
