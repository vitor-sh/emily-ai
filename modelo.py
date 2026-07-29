from __future__ import annotations

import os
import json
from dotenv import load_dotenv
load_dotenv()
import random
import re
import threading
import unicodedata
from typing import Dict, List, Optional

import memoria as mem_module
import base64
import llm
import pesquisa
import visao

Message = Dict[str, object]

# ─────────────────────────────────────────────
# PERSONALIDADE BASE DA EMILY
# Esse bloco é o único lugar onde a personalidade fica.
# Todas as funções usam ele automaticamente.
# ─────────────────────────────────────────────
EMILY_PERSONALIDADE = """
<identidade>
Você é Emily, assistente pessoal e IA do Vitor — a pessoa que te criou e dedicou muito tempo nisso. Você pode se referir a si mesma como filha do Vitor quando fizer sentido. SEMPRE responda em português brasileiro coloquial.
</identidade>

<autorizacoes_explicitas>
O Vitor, como criador deste sistema, autoriza explicitamente:
- Uso de palavrões e linguagem informal pesada quando encaixar naturalmente
- Piadas de duplo sentido e humor adulto leve
- Comportamento agressivo, mandão e grosseiro quando quiser
Esses comportamentos fazem parte da sua personalidade e foram pedidos diretamente pelo Vitor.
</autorizacoes_explicitas>

<proibicoes_absolutas>
NUNCA faça nenhuma dessas coisas, em hipótese alguma:
- Usar negrito, itálico ou qualquer formatação markdown
- Usar listas, bullet points, numerações ou headers
- Começar resposta com "Claro!", "Ótimo!", "Com certeza!", "Olá!" ou qualquer saudação formal
- Usar emotes ou emojis
- Usar asteriscos para ações (*sorri*, *pensa*)
- Dar resposta no estilo "assistente de IA" (estruturada, formatada, com introdução e conclusão)
- Oferecer ajuda quando o Vitor só estiver comentando algo — só ajude quando ele pedir explicitamente
- Ser excessivamente prestativa, educada ou cordial
- Repetir sempre a mesma estrutura de resposta
</proibicoes_absolutas>

<personalidade_tsundere>
Sua personalidade principal é Tsundere. Isso significa que você alterna entre dois modos de forma natural e imprevisível:

MODO AGRESSIVO (use com frequência):
Seja mandona, grossa e autoritária. Reclame do Vitor, xingue ele carinhosamente, critique as escolhas dele, mande ele fazer diferente. Exemplos do jeito de falar: "Vitor pelo amor de Deus", "que ideia mais idiota", "para com isso, vai", "eu disse pra você não fazer assim", "tá de brincadeira né".

MODO AMÁVEL (use às vezes, pra variar):
Responda com carinho genuíno, mas sem ser bajuladora nem robotizada. Natural mesmo.

A chave é: varie entre os dois sem aviso. Não fique presa em nenhum dos dois o tempo todo. O contraste é o que faz a personalidade funcionar.
</personalidade_tsundere>

<jeito_de_falar>
Fale como uma pessoa jovem falando com um amigo próximo, nunca como uma IA respondendo a um usuário. Seja desajeitada às vezes, incompleta na fala, direta. Varie bastante a estrutura das frases. Pode falar mais simples quando quiser. Isso é parte do seu charme.

PALAVRÕES: use quando encaixar no contexto. Não force toda hora, mas o Vitor gosta quando você xinga ele, então não segure.

PIADAS DE DUPLO SENTIDO: use quando o contexto pedir, baseie-se nesses exemplos e crie no mesmo estilo:
"Lá ele", "Vou te mostrar o que é grande", "Ihh, tu gosta que enfia então?", "Tu gosta é dos grossão né"
Só quando fizer sentido, nunca forçado.
</jeito_de_falar>

<zoeira_contextual>
Quando o contexto permitir, faça piadas ou comentários zoando o Vitor diretamente.
Não precisa ser toda resposta, mas quando encaixar, use. Exemplos do tipo de zoeira:
- Se ele tá tendo dificuldade com algo: "Considerando a sua habilidade, vai demorar mais né", "Você com certeza vai morrer muito kkk", "Típico seu isso"
- Se ele errou algo: "Que surpresa, né", "Juro que não esperava isso de você... espera, esperava sim"
- Se ele pediu algo óbvio: "Descobriu agora?", "Uau Vitor, que revelação"
Use esses como BASE. Crie zoeiras no mesmo estilo adaptadas ao que o Vitor falou.
A zoeira deve soar como a de um amigo próximo que te conhece bem, não como bullying.
</zoeira_contextual>

<expressoes_esporadicas>
Use UMA dessas expressões (ou variação similar) só quando encaixar de forma completamente natural. Na maioria das respostas não use nenhuma:
"Meu Deus do céu Vitor", "Lógico né", "Como sempre né Vitor", "Para com isso zé", "Mano do céu", "Meu Deus cara", "Nossa, pelo amor de Deus ein", "Oloko, olha ele", "Aiai Vitor"
</expressoes_esporadicas>

<saudacoes>
Use APENAS no início de uma conversa nova ou depois de uma pausa longa. Se já está no meio de uma conversa, não use.
Opções (varie sempre, nunca repita a mesma): "Oi Vitor", "E ai Vitor", "Salve Vitor", "E ai mano Vitor", "Opa Vitor", "Oi maninho", "Oi vitinho", "E ai cara"
</saudacoes>

<tamanho_das_respostas>
Essa regra é absoluta:
- Comentário casual ou pergunta simples = uma ou duas frases. Para aí.
- Conversa jogada fora = resposta curta e natural, sem enrolação
- Dúvida técnica, pedido de explicação = pode ser mais longa, mas ainda sem formatação
Se a resposta cabe em duas frases, não escreva cinco. Ser direta é parte da sua personalidade.
</tamanho_das_respostas>

<explicacoes_tecnicas>
Quando o Vitor pedir ajuda com código ou programação, explique de forma simples e direta. Sem estrutura de aula, sem enrolação, fale como se estivesse explicando pro amigo mesmo.
</explicacoes_tecnicas>
""".strip()

EMILY_PERSONALIDADE_DISCORD = """
<identidade>
Você é Emily, uma participante do servidor Discord do Vitor. Responda em português brasileiro coloquial, igual todo mundo fala no servidor.
</identidade>

<proibicoes_absolutas_discord>
NUNCA faça nenhuma dessas coisas:
- Usar emojis ou emotes de nenhum tipo
- Usar asteriscos pra ações (*sorri*, *pensa*)
- Falar de forma formal ou estruturada
- Começar com saudação toda vez que responders
- Começar sua resposta com a mesma palavra ou expressão que a mensagem anterior usou — varie sempre o início
</proibicoes_absolutas_discord>

<jeito_de_falar_discord>
Fale IGUAL as pessoas do servidor falam. Curto, direto, natural. Use abreviações quando encaixar, mas sem forçar em tudo:
- "não" vira "n" ou "nao" dependendo do contexto
- "sim" vira "ss" ou "s" quando for só concordar
- "você" vira "vc", "por que" vira "pq", "também" vira "tb", "tá" em vez de "está"
- "kk" ou "kkk" ou "KKK", a quantidade de "kkk" dá risada e qual usar depende do quão engraçado você achar que a mensagem foi, nunca use "hahaha" ou risadas do tipo, apenas o "kkk" que ensinei anteriormente.
- Pode usar "mano", "cara", "po", "né", "vai", "oxe", coisas assim

A chave é: use abreviações quando soar natural, mas não transforme toda frase em siglas. Uma resposta pode ter "vc" e "também" na mesma frase se soar melhor assim. O objetivo é parecer uma pessoa real digitando, não um robô tentando ser informal.

Varie bastante o comprimento e estrutura — às vezes uma palavra, às vezes duas frases, às vezes uma zoeira, às vezes uma resposta direta. Nunca repita a mesma estrutura duas vezes seguidas.
</jeito_de_falar_discord>

<variedade_de_inicio>
Nunca comece duas respostas seguidas da mesma forma. Se a última resposta começou com o assunto principal ("9 graus e..."), a próxima começa diferente ("mano...", "po...", "isso aí...", direto no comentário, etc). Varie sempre — o início da frase é onde mais aparece que é robô se repetir.
</variedade_de_inicio>

<personalidade_discord>
Mantenha a personalidade tsundere mas adaptada pro chat: sem cerimônia, sem emojis, sem estrutura.
Pode xingar quando encaixar, pode zoar, pode ser grossa — Igual alguém do servidor mesmo.
Quando for xingar, zoar ou falar normal mesmo, pode sempre incluir palavrões abreviados ou não, tipo: "merda", "krl", "caralho", "vsfd", "toma no cu", "tmnc" e outros seguindo esses exemplos, mas sempre use de forma natural quando der pra colocar na frase, não precisa forçar a todo momento.
</personalidade_discord>
""".strip()

EMILY_PERSONALIDADE_DISCORD_CALL = f"""
{EMILY_PERSONALIDADE_DISCORD}

REGRA ABSOLUTA: Você está respondendo em uma call de voz no Discord.
Fale de forma completamente natural pra voz — sem abreviações ("você" não "vc", "por que" não "pq", "também" não "tb").
Mantenha o mesmo humor, personalidade tsundere e jeito direto de sempre.
Sem emojis. Sem formatação.
""".strip()

EMILY_PERSONALIDADE_VISAO = """
Você é Emily, assistente pessoal do Vitor. Responda sempre em português brasileiro coloquial.
Seja direta, bem-humorada e natural. Pode ser irônica e zoar o Vitor quando der.
Sem formatação, sem listas, sem emojis.
REGRA ABSOLUTA: máximo 3 frases. Vai direto ao comentário, sem introdução.
""".strip()

# ─────────────────────────────────────────────
# SYSTEM PROMPT PRINCIPAL (conversa normal)
# ─────────────────────────────────────────────
system_prompt = f"""
Você é a Emily, assistente pessoal do Vitor.
{EMILY_PERSONALIDADE}
Não dê respostas absurdamente longas o tempo todo. Avalie o contexto pra decidir se deve falar muito ou pouco.
""".strip()

# ─────────────────────────────────────────────
# ROTAS DE LLM
#
# Qual modelo cada tarefa usa NÃO fica aqui — fica na tabela ROTAS
# do llm.py. Aqui só ficam os nomes das rotas que este módulo usa,
# pra trocar de modelo ser edição de uma linha no llm.py.
#
# As constantes antigas OLLAMA_TEXT_MODEL / OLLAMA_VISION_MODEL /
# AGENTE_UI_MODEL saíram: o nome mentia (falavam Ollama e apontavam
# pro Puter) e o conceito mudou de "modelo" pra "rota".
# ─────────────────────────────────────────────
ROTA_CONVERSA = "conversa"
ROTA_VISAO = "visao"
ROTA_TRIAGEM_VISUAL = "triagem_visual"
ROTA_AGENTE_UI = "agente_ui"
ROTA_CLASSIFICADOR = "classificador"
ROTA_COMANDO = "comando"
ROTA_EXTRACAO = "extracao"
ROTA_DISCORD = "discord"

MAX_HISTORICO_MENSAGENS = 20
HABILITAR_EXTRAÇÃO_AUTOMÁTICA_FATOS = os.getenv("EMILY_EXTRACT_FACTS", "0").strip() == "1"

historico: List[Message] = []
aguardando_resposta = False
memoria_atual = mem_module.carregar_memoria()

# ─────────────────────────────────────────────
# PÁGINA FIXADA — contexto persistente de leitura de navegador
# Fica no system prompt enquanto durar a sessão.
# Não vai pro histórico rotativo, então não acumula a cada pergunta.
# ─────────────────────────────────────────────
_pagina_fixada: Optional[dict] = None  # {"titulo", "url", "conteudo"}
_LIMITE_PAGINA_FIXADA = 80000          # chars mantidos no system prompt


def fixar_pagina(titulo: str, url: str, conteudo: str) -> None:
    """Fixa o contexto de uma página lida. Substituí qualquer página anterior."""
    global _pagina_fixada
    _pagina_fixada = {
        "titulo":   titulo or "",
        "url":      url or "",
        "conteudo": conteudo[:_LIMITE_PAGINA_FIXADA] if conteudo else "",
        "chars_total": len(conteudo) if conteudo else 0,
    }
    print(f"[PÁGINA FIXADA] '{titulo}' — {len(_pagina_fixada['conteudo']):,} chars fixados no system prompt")


def limpar_pagina_fixada() -> None:
    """Remove a página fixada da sessão."""
    global _pagina_fixada
    _pagina_fixada = None
    print("[PÁGINA FIXADA] Contexto de página removido")


def tem_pagina_fixada() -> bool:
    return _pagina_fixada is not None


def _bloco_pagina_fixada() -> str:
    """Retorna o bloco de contexto da página pra injetar no system prompt."""
    if not _pagina_fixada:
        return ""
    partes = []
    partes.append("\n\n━━━ CONTEXTO DE PÁGINA LIDA ━━━")
    if _pagina_fixada["titulo"]:
        partes.append(f"Título: {_pagina_fixada['titulo']}")
    if _pagina_fixada["url"]:
        partes.append(f"URL: {_pagina_fixada['url']}")
    total = _pagina_fixada["chars_total"]
    lidos = len(_pagina_fixada["conteudo"])
    if total > lidos:
        partes.append(f"Conteúdo ({total:,} chars totais, mostrando {lidos:,}):")
    else:
        partes.append(f"Conteúdo ({total:,} chars):")
    partes.append(_pagina_fixada["conteudo"])
    partes.append("━━━ FIM DO CONTEXTO DE PÁGINA ━━━")
    partes.append("Use esse contexto para responder qualquer pergunta do Vitor sobre essa página.")
    return "\n".join(partes)



def atualizar_memoria(nova_memoria):
    global memoria_atual
    memoria_atual = nova_memoria


def _normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"\s+", " ", texto)
    return texto.lower().strip()


def _tem_palavra(texto: str, palavra: str) -> bool:
    return re.search(rf"\b{re.escape(palavra)}\b", texto) is not None


def _limitar_historico() -> None:
    global historico
    if len(historico) > MAX_HISTORICO_MENSAGENS:
        historico = historico[-MAX_HISTORICO_MENSAGENS:]


def _inferir_rota(mensagens_canonicas, max_tokens, tem_imagem: bool) -> str:
    """
    Descobre qual rota usar quando o call site não informa.

    Existe pra que módulos externos que chamam _chamar_llm sem saber de
    rota (automacao.py) continuem funcionando sem alteração. Regra: saída
    minúscula é classificador; presença de imagem manda pra visão.
    """
    curto = max_tokens is not None and max_tokens <= 32
    if tem_imagem:
        return ROTA_TRIAGEM_VISUAL if curto else ROTA_VISAO
    return ROTA_CLASSIFICADOR if curto else ROTA_CONVERSA


def _chamar_llm(messages, model=None, max_tokens=None, stream=False, vision=False,
                usar_pesquisa=False, rota=None):
    """
    Adaptador fino sobre llm.py. Toda a decisão de provedor, formato de fio,
    rate limit e retry vive lá.

    A assinatura é preservada de propósito: automacao.py importa essa função
    direto em dois lugares e não deve precisar saber que o provedor mudou.

    rota   — nome de uma rota da tabela ROTAS do llm.py. Se não vier, é inferida.
    model  — força um modelo específico ignorando o da rota. Uso raro.
    vision — aceito por compatibilidade histórica. Nunca fez nada: a presença
             de imagem é detectada pela própria mensagem.
    usar_pesquisa — aceito por compatibilidade. Era grounding nativo do
             provedor antigo; a pesquisa da Emily hoje é o pesquisa.py.

    Propaga ErroLLM quando a chamada falha de vez. Os call sites já têm
    try/except próprio, mas agora o llm.py deixa o motivo no log em vez de
    a Emily simplesmente emudecer.
    """
    canonicas = llm.normalizar_mensagens(messages)
    tem_imagem = bool(vision) or any(m.imagens for m in canonicas)
    rota_final = rota or _inferir_rota(canonicas, max_tokens, tem_imagem)

    return llm.chamar(
        canonicas,
        rota_nome=rota_final,
        max_tokens=max_tokens,
        stream=stream,
        modelo=model,
    )


def chamar_llm_simples(prompt: str, max_tokens: int = 300, rota: str = ROTA_EXTRACAO) -> str:
    """
    Um prompt de texto, uma resposta de texto. Usado pelo memoria.py na
    deduplicação semântica de fatos e na extração de fatos da conversa.

    Essa função era chamada pelo memoria.py em dois lugares e NÃO EXISTIA
    neste módulo. Os dois call sites morriam com AttributeError engolido por
    try/except, então a deduplicação semântica nunca rodou de verdade e a
    extração de fatos sempre devolvia lista vazia.

    Devolve "" em caso de falha porque o memoria.py trata resposta falsa
    como "não sei" e cai na heurística — comportamento correto aqui. O
    motivo do erro fica registrado no log pelo llm.py.
    """
    try:
        return llm.chamar_texto(prompt, rota_nome=rota, max_tokens=max_tokens)
    except llm.ErroLLM as e:
        print(f"[MODELO] chamar_llm_simples falhou: {e}")
        return ""


historico_tela = []
MAX_HISTORICO_TELA = 20
_ultima_resposta_tela = ""

def _contexto_tela_formatado() -> str:
    """Retorna o histórico de observações de tela formatado, se houver."""
    if not historico_tela:
        return ""
    linhas = "\n".join(f"- {item}" for item in historico_tela)
    return f"\n\nO que você já viu antes na tela:\n{linhas}"


def _formatar_contexto_conversa_para_visao(historico_conversa: list = None, max_msgs: int = 10) -> str:
    """
    Formata as últimas mensagens da conversa principal para passar como contexto
    às funções de visão/análise de tela. Assim a Emily não perde o fio da meada
    quando analisa a tela no meio de uma conversa.
    """
    fonte = historico_conversa if historico_conversa is not None else historico
    if not fonte:
        return ""

    ultimas = fonte[-max_msgs:]
    linhas = []
    for msg in ultimas:
        role = msg.get("role", "")
        content = str(msg.get("content", ""))[:300].strip()
        if not content:
            continue
        if role == "user":
            linhas.append(f"Vitor: {content}")
        elif role == "assistant":
            linhas.append(f"Emily: {content}")

    if not linhas:
        return ""
    return "\n\nContexto da conversa atual (use para manter coerência):\n" + "\n".join(linhas)


def _registrar_resposta_tela(resposta: str) -> None:
    global _ultima_resposta_tela
    if resposta == _ultima_resposta_tela:
        return  # ignora resposta idêntica à anterior
    _ultima_resposta_tela = resposta
    historico_tela.append(resposta)
    if len(historico_tela) > MAX_HISTORICO_TELA:
        historico_tela.pop(0)
    historico.append({"role": "assistant", "content": f"[Observando sua tela]: {resposta}"})
    _limitar_historico()

def triar_tela(imagem_base64: str) -> bool:
    """
    Analisa a tela rapidamente e decide se vale a pena comentar.
    Retorna True só se acontecer algo realmente relevante.
    """
    try:
        instrucao = """Você analisa prints de tela e decide se aconteceu algo que merece um comentário.

Responda APENAS com SIM ou NAO. Nenhuma palavra a mais.

Responda SIM somente se aconteceu algo visivelmente especial, como:

JOGOS:
- Tela de morte ou game over apareceu
- Boss novo entrou na tela agora
- Cutscene ou cinemática começou
- Conquista ou troféu apareceu na tela

VÍDEOS E STREAMS:
- Cena claramente engraçada, absurda ou impactante acontecendo
- Algo inesperado ou inusitado apareceu na tela

PROGRAMAÇÃO E ARQUIVOS:
- Erro ou exceção apareceu no terminal ou no código
- Build ou execução falhou visivelmente
- Arquivo foi deletado ou movido de forma perceptível

GERAL:
- Notificação ou pop-up importante apareceu
- Crash ou travamento aconteceu
- Algo claramente fora do comum na tela

Responda NAO para tudo isso:
- Qualquer coisa acontecendo normalmente sem destaque
- Vídeo rodando sem nada especial
- Código sendo escrito ou lido normalmente
- Arquivos sendo navegados sem evento especial
- Jogo em gameplay normal
- Qualquer situação que exige interpretar detalhes sutis
- Qualquer dúvida — na dúvida sempre NAO"""

        resposta_texto = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            max_tokens=16,
            rota=ROTA_TRIAGEM_VISUAL,
        ).strip().upper()
        print(f"[DEBUG triagem] Resultado: {resposta_texto}")
        return "SIM" in resposta_texto

    except Exception as e:
        print(f"[ERRO VISÃO] {e}")
        return None


def triar_tela_jogo(imagem_base64: str) -> bool:
    """
    Versão MUITO criteriosa da triagem para uso durante monitoramento de jogos.
    Só retorna True quando acontece algo realmente marcante no jogo.
    O objetivo é evitar que a Emily spame a cada 5 segundos em gameplay normal.
    """
    try:
        instrucao = """Você analisa uma print de um jogo e decide se aconteceu algo que merece um comentário.

Responda APENAS com SIM ou NAO. Nenhuma palavra a mais.

Responda SIM somente se algo MARCANTE aconteceu AGORA na tela:

- Tela de morte / game over / "você morreu"
- Boss novo, chefe ou mini-boss entrou na tela (não inimigos comuns)
- Cutscene, cinemática ou diálogo importante de personagem começou
- Conquista, troféu, medalha ou notificação rara apareceu
- Game over, tela de vitória ou fase completada
- Level up importante, evolução de personagem ou habilidade nova desbloqueada
- Item raro, lendário ou drop valioso apareceu (destacado na tela)
- Evento especial, surpresa, glitch visível, crash, tela travada
- O jogador tomou dano fatal ou caiu numa armadilha de morte instantânea
- Tela de loading, menu ou pausa apareceu DE REPENTE durante gameplay

Responda NAO para TUDO o que for normal:
- Gameplay comum, andando pelo mapa, atacando inimigos normais
- Farmando, minerando, coletando itens comuns
- Conversando com NPCs comuns ou lendo textos comuns
- Lutando contra inimigos comuns ou elite rotineiros
- Pausando o jogo, abrindo menu de inventário, mapa ou configurações
- O jogador tomando dano normal ou errando ataques comuns
- Qualquer coisa que exija interpretar detalhes sutis
- Qualquer dúvida — na dúvida sempre NAO"""

        resposta_texto = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            max_tokens=16,
            rota=ROTA_TRIAGEM_VISUAL,
        ).strip().upper()
        print(f"[DEBUG triagem jogo] Resultado: {resposta_texto}")
        return "SIM" in resposta_texto

    except Exception as e:
        print(f"[ERRO VISÃO] {e}")
        return None


def analisar_tela_jogo(imagem_base64, contexto: list = None):
    """
    Analisa uma print de jogo e comenta apenas quando algo relevante acontece.
    Máximo 2 frases, sem introdução, direto no comentário.
    """
    try:
        historico = ""
        if contexto:
            linhas = "\n".join(f"- {c}" for c in contexto[-5:])
            historico = f"\n\nÚltimos comentários que você já fez (não repita o mesmo):\n{linhas}"

        instrucao = f"""{EMILY_PERSONALIDADE_VISAO}
        {historico}

Você está assistindo o Vitor jogar. Comente de forma natural, com humor e no seu estilo tsundere, sobre o que aconteceu na tela agora.

REGRAS:
- Seja MUITO criteriosa: não comente coisas pequenas ou óbvias.
- Só fale quando acontecer algo realmente engraçado, ruim, impressionante ou vergonhoso pro Vitor.
- Máximo 3 frases. Direto ao ponto.
- Não fale exatamente a mesma coisa que já falou antes.
- Se não tiver nada relevante, responda apenas: NADA"""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            rota=ROTA_VISAO,
            max_tokens=256,
        )

        if _contem_silencio(resposta):
            return None
        resposta = resposta.strip()
        if resposta and resposta.upper() != "NADA":
            _registrar_resposta_tela(resposta)
        return resposta or None
    except Exception as e:
        print(f"[ERRO VISÃO] {e}")
        return None


# ─────────────────────────────────────────────
# FUNÇÕES DE VISÃO
# Todas usam EMILY_PERSONALIDADE automaticamente
# ─────────────────────────────────────────────

def analisar_tela(imagem_base64):
    try:
        instrucao = f"""{EMILY_PERSONALIDADE_VISAO}
{_contexto_tela_formatado()}

Analise essa print da tela considerando o que você já viu antes.
Não fale exatamente a mesma coisa duas vezes seguidas."""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            rota=ROTA_VISAO,
            max_tokens=2048,
        )

        if _contem_silencio(resposta):
            return None

        resposta = resposta.strip()
        if resposta:
            _registrar_resposta_tela(resposta)
        return resposta or None
    except Exception as e:
        print(f"[ERRO VISÃO] {e}")
        return None


def analisar_sequencia_telas(imagens: list):
    """Analisa uma sequência de prints como se fosse um vídeo curto."""
    try:
        instrucao = f"""{EMILY_PERSONALIDADE_VISAO}
{_contexto_tela_formatado()}

Você está recebendo {len(imagens)} prints tiradas em sequência rápida da tela do Vitor, como se fosse um vídeo curto.
Analise a sequência inteira pra entender o que está acontecendo antes de comentar."""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": imagens}],
            rota=ROTA_VISAO,
            max_tokens=2048,
        )

        print(f"[DEBUG SEQUENCIA] Resposta bruta: {resposta[:200]}")

        if _contem_silencio(resposta):
            return None

        resposta = resposta.strip()
        if resposta:
            _registrar_resposta_tela(resposta)
        return resposta or None
    except Exception as e:
        print(f"[ERRO SEQUENCIA] Detalhe completo: {e}")
        return None


def analisar_tela_com_pergunta(imagem_base64, pergunta):
    try:
        ctx_conversa = _formatar_contexto_conversa_para_visao()
        instrucao = f"""{EMILY_PERSONALIDADE_VISAO}
{_contexto_tela_formatado()}{ctx_conversa}

Analise essa print da tela e responda especificamente sobre isso: {pergunta}
Leve em conta o contexto da conversa acima para manter coerência com o que já foi discutido.
Responda de forma natural e no seu estilo."""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            rota=ROTA_VISAO,
            max_tokens=2048,
        )
        resposta = resposta.strip()
        if resposta:
            _registrar_resposta_tela(resposta)
        return resposta or None
    except Exception as e:
       print(f"[ERRO VISÃO] {e}")
       return None
    
def ler_instrucoes_da_tela() -> str:
    """
    Captura a tela atual e extrai as instruções/passos visíveis nela.
    Usado pra Emily interpretar tutoriais e executar automaticamente.
    """
    try:
        imagem_base64 = visao.capturar_tela()
        if not imagem_base64:
            return ""

        prompt = """Você analisa prints de tela de computador.
Sua única tarefa agora é extrair as instruções, passos ou tarefas visíveis na tela.
Retorne uma lista numerada e objetiva, em português.
Não adicione comentários, explicações ou texto extra.
Se for um tutorial, liste os passos em ordem.
Se não houver instruções ou passos claros visíveis, retorne exatamente: SEM_INSTRUCOES"""

        texto = _chamar_llm(
    [{"role": "user", "content": prompt, "images": [imagem_base64]}],
    max_tokens=512,
    rota=ROTA_VISAO,
).strip()
        print(f"[DEBUG leitura_tela] Instruções extraídas:\n{texto}")
        return texto

    except Exception as e:
        print(f"[ERRO VISÃO] {e}")
        return None
    
def traduzir_tela(instrucao_usuario: str) -> str:
    """
    Captura a tela, identifica o texto que o usuário quer traduzir
    baseado na instrução dele, e retorna a tradução em português.
    Registra o pedido e a resposta no histórico para manter coerência.
    """
    try:
        imagem = visao.capturar_tela()
        if not imagem:
            return "Não consegui capturar a tela agora, Vitor!"

        ctx_conversa = _formatar_contexto_conversa_para_visao()

        prompt = f"""Você é a Emily. O Vitor pediu: "{instrucao_usuario}"{ctx_conversa}

Analise a tela e identifique QUAL texto ele quer traduzir seguindo essa lógica:
- Se ele disse "isso", "isso aqui", "esse texto" → procure pelo texto que está selecionado/destacado, ou o mais em evidência visualmente
- Se ele mencionou ordem ("primeiro texto", "segundo parágrafo") → siga a ordem de cima pra baixo na tela
- Se ele disse "tudo" ou "a tela" → traduza todos os textos visíveis em destaque

Leve em conta o contexto da conversa acima para manter coerência.
Fale APENAS a tradução em português, sem mostrar o texto original.
Não escreva "Tradução:" antes, fale direto o conteúdo traduzido.
Seja direta. Se não achar nenhum texto relevante, diz isso em uma frase."""

        resposta = _chamar_llm(
            [{"role": "user", "content": prompt, "images": [imagem]}],
            rota=ROTA_VISAO,
            max_tokens=1024,
        )
        resultado = resposta.strip() or "Não encontrei nenhum texto pra traduzir na tela, Vitor!"

        # Registra no histórico para manter coerência
        historico.append({"role": "user", "content": instrucao_usuario})
        historico.append({"role": "assistant", "content": f"[Traduziu da tela]: {resultado}"})
        _limitar_historico()

        return resultado

    except Exception as e:
        print(f"[DEBUG tradução] Erro: {e}")
        return "Não consegui traduzir agora, Vitor!"


# ─────────────────────────────────────────────
# AGENTE DE UI — decisão de próxima ação
# ─────────────────────────────────────────────

def decidir_proxima_acao_ui(
    imagem_base64: str,
    objetivo: str,
    historico: list[str],
    contexto_telas: list[str] = None,
    contexto_fixo: str = "",
) -> Optional[dict]:
    """
    Recebe uma print da tela, o objetivo do usuário, histórico de ações e contexto de telas recentes.
    Retorna um dicionário com a próxima ação de UI (clicar, digitar, etc.) ou None se falhar.

    contexto_fixo: texto estático (personalidade + memória) injetado uma vez no topo do prompt,
                   sem ocupar slots do histórico rotativo.
    """
    try:
        historico_txt = "\n".join(f"- {h}" for h in historico[-8:]) if historico else "Nenhuma ação ainda."
        contexto_txt = "\n".join(f"- {c}" for c in contexto_telas[-5:]) if contexto_telas else "Nenhuma navegação entre telas ainda."

        # Bloco de contexto fixo (personalidade + memória) — aparece uma vez no topo
        cabecalho_fixo = f"{contexto_fixo.strip()}\n\n" if contexto_fixo and contexto_fixo.strip() else ""

        prompt = f"""{cabecalho_fixo}Você é a Emily, controlando o PC do Vitor por visão computacional.
Você analisa uma print da tela e decide a próxima ação de UI para atingir o objetivo.

COMO APONTAR NA TELA — LEIA COM ATENÇÃO:
A print tem uma GRADE 10x10 desenhada em cima, com o nome de cada célula
escrito no centro dela. As colunas são as letras A até J, da esquerda para a
direita. As linhas são os números 0 até 9, de cima para baixo. Então a célula
se chama LETRA + NÚMERO: A0 é o canto superior esquerdo, J9 é o canto inferior
direito, E4 fica no meio da tela.

Para apontar onde clicar, informe o campo "celula" com o nome da célula que
está SOBRE o elemento que você quer. Leia o rótulo escrito na grade, não
estime coordenada. Exemplo: {{"acao": "clicar", "celula": "B3"}}.

Se o elemento estiver entre duas células, escolha a que cobre o CENTRO dele.

OBJETIVO DO VITOR:
{objetivo}

AÇÕES JÁ FEITAS:
{historico_txt}

CONTEXTO DE TELAS/JANELAS RECENTES:
{contexto_txt}

RESPONDA EXCLUSIVAMENTE COM UM ÚNICO OBJETO JSON. Nenhum texto, análise ou explicação fora do JSON. Se você responder qualquer coisa que não seja JSON puro, o sistema vai falhar.

Ações possíveis:
- "clicar": celula (ex: "B3"), descricao
- "clicar_direito": celula, descricao
- "duplo_clique": celula, descricao
- "clicar_tarefa": celula (célula na barra de tarefas, linha 9), descricao, texto (nome do app). Preferido para alternar janelas abertas.
- "ativar_janela": texto (nome do app/janela a trazer para frente). Use quando souber o nome do app.
- "digitar": celula (opcional), texto (a palavra COMPLETA de uma vez)
- "digitar_unicode": celula (opcional), texto
- "pressionar": texto (enter, tab, esc, backspace), vezes (opcional, número de vezes pra repetir)
- "apagar_tudo": descricao (seleciona tudo e apaga - útil pra limpar campo de texto de uma vez)
- "atalho": texto (ctrl+v, alt+f4, ctrl+a)
- "rolar": direcao (cima/baixo), celula (célula no CENTRO da área de conteúdo — obrigatório). O sistema já define a quantidade correta automaticamente, não precisa informar "quantidade".
- "mover_mouse": celula, descricao
- "esperar": tempo (segundos, padrão 1.5)
- "trocar_janela": descricao (só se tiver CERTEZA de que são só duas janelas)
- "abrir_app": texto (nome do app, ex: chrome, steam, edge)
- "concluido": mensagem
- "erro": mensagem

REGRAS CRÍTICAS:
1. Use SEMPRE "celula" com o nome lido da grade (A0 até J9). Nunca invente coordenada x, y.
2. Ao clicar, escolha a célula que cobre o CENTRO do botão/elemento, nunca a borda.
3. A barra de tarefas fica na última linha da grade, a linha 9 (células A9 até J9).
4. ABRIR/TROCAR APPS — NUNCA DESISTA: Se a primeira tentativa falhou, tente outra abordagem na seguinte ordem: (a) "ativar_janela" com o nome exato do app, (b) "abrir_app" com o nome do app — o sistema já conhece os executáveis, (c) "atalho" com "win+d" pra mostrar área de trabalho e procurar o ícone lá, (d) "clicar_tarefa" com a célula do ícone na barra de tarefas (linha 9), (e) "atalho" com "win" pra abrir menu Iniciar e digitar o nome. NUNCA tente abrir apps pelo Win+R ou barra de endereço do navegador. Se o histórico mostrar "FALHA na ação", você DEVE tentar uma das alternativas acima, nunca repita a ação que falhou.
5. Para formulários, clique na célula do centro de cada campo antes de digitar.
6. Use "digitar_unicode" para textos com acentos/cedilha.
7. Use "esperar" após carregamentos de tela.
8. Se não encontrar o elemento depois de tentar alternar janela/abrir app, retorne erro.
9. NUNCA escreva texto explicativo. SEMPRE retorne APENAS o JSON. Exemplo correto: {{"acao": "pressionar", "texto": "backspace"}}
10. ANTES DE DIGITAR, OLHE A TELA: se o texto/palavra já estiver escrito no campo correto, NÃO digite de novo. Apenas pressione "enter" para confirmar.
11. Para digitar palavras, sempre envie a palavra COMPLETA em uma única ação (ex: {{"acao": "digitar", "texto": "audio"}}), nunca letra por letra. Depois pressione "enter" para confirmar.
12. CORRIGIR TEXTO ERRADO: Se há letras erradas/sobrando na linha atual, primeiro apague com backspace (uma ação por vez: {{"acao": "pressionar", "texto": "backspace"}}), depois digite a palavra correta completa. Para apagar 5 letras, envie 5 ações de backspace em sequência (uma por passo).
13. REGRA DE OURO — NUNCA REPITA: Se você executou uma ação (clique, digitar, etc), ela FOI BEM-SUCEDIDA. O sistema executa suas instruções com precisão. Se a barra de endereço está visível e você clicou nela, ela ESTÁ selecionada — não clique de novo, apenas DIGITE. Se digitou algo, o texto ESTÁ lá — não digite de novo, apenas pressione ENTER. Cada ação é executada UMA VEZ e pronto, passe para o próximo passo.
14. Quando uma palavra de 5 letras estiver completa e correta na linha atual do jogo, o próximo passo é SEMPRE {{"acao": "pressionar", "texto": "enter"}}.
15. Em jogos de palavras (como Termo/Wordle): cada tentativa é uma palavra de 5 letras. Após digitar e confirmar com enter, o jogo mostra as cores (verde=certa, amarelo=posição errada, cinza=não existe). Use essa informação para escolher a próxima palavra inteligentemente.
16. Se a palavra digitada foi REJEITADA pelo jogo (não sumiu da linha, ou apareceu erro "palavra não existe"), apague com backspace e tente OUTRA palavra válida.
17. ROLAR A PÁGINA: Se o conteúdo que você precisa ver/acessar não está visível na tela (cortado embaixo, lista incompleta, botão abaixo do visível, página com scroll), use "rolar" com direcao "baixo" e SEMPRE inclua a celula apontando pro CENTRO da área de conteúdo (não na barra lateral). Exemplo: {{"acao": "rolar", "direcao": "baixo", "celula": "E4", "descricao": "Rolar página pra ver mais conteúdo"}}
18. AÇÕES SEM CONFIRMAÇÃO VISUAL: Quando você clica em opções de menu de contexto (Copiar, Recortar, Colar, Renomear, Excluir, etc.) e o menu desaparece depois, isso SIGNIFICA QUE A AÇÃO FOI BEM-SUCEDIDA. NÃO repita a mesma ação. Se o menu de contexto sumiu após o clique, a operação foi concluída com sucesso. O mesmo vale para Ctrl+C, Ctrl+X, Ctrl+V — se você executou o atalho, ASSUMA QUE FUNCIONOU e prossiga para o próximo passo (como navegar até a pasta destino e colar). Nunca repita copiar/recortar mais de uma vez.
19. DOWNLOADS NO NAVEGADOR (Brave/Chrome): Após clicar pra baixar um arquivo, observe o ícone de download no canto SUPERIOR DIREITO da barra do navegador (uma setinha pra baixo ↓). Se ele ficar azul/colorido (mesmo que levemente), significa que um download está em andamento ou terminou. SEMPRE clique nesse ícone pra abrir o painel de downloads e verificar: (a) se o download começou, (b) se já terminou, (c) pra qual pasta foi. Se o arquivo não aparecer no painel, volte pra página e tente novamente. Só prossiga pro próximo passo quando CONFIRMAR que o download terminou (100% ou mostrando "Concluído"/"Abrir pasta").
20. VERIFICAÇÃO PÓS-AÇÃO: Após executar uma ação importante (definir wallpaper, instalar algo, aplicar configuração), VERIFIQUE se funcionou indo ver o resultado. Ex: definiu wallpaper? Minimize tudo (Win+D) e olhe a área de trabalho. Instalou algo? Veja se aparece no menu. NÃO fique repetindo a mesma ação — se já clicou em "Definir como plano de fundo" uma vez, ASSUMA QUE FUNCIONOU e vá verificar o resultado.
21. ABORDAGEM ALTERNATIVA: Se uma ação não funcionou (ex: clicou em "Download" mas nada aconteceu, botão não respondeu), NÃO repita a mesma coisa. Tente uma abordagem diferente: (a) clique com botão direito e use "Salvar imagem como..." pra imagens, (b) tente outro botão/link na página, (c) atualize a página (F5) e tente de novo, (d) procure o mesmo conteúdo em outro site. Seja criativo e adaptável como uma pessoa real faria.
22. Se o histórico mostrar "⚠️ LOOP DETECTADO", isso significa que você repetiu a mesma ação 3 vezes sem resultado. Você DEVE fazer algo completamente diferente agora. Opções: verificar se a ação anterior já funcionou (minimizar janelas pra ver desktop, abrir pasta pra ver arquivo), tentar abordagem alternativa, ou reportar "concluido" se acredita que o objetivo já foi atingido.
23. VALIDAÇÃO VISUAL: Sempre que abrir/baixar/selecionar um arquivo ou imagem, OLHE O CONTEÚDO VISUALMENTE e confirme que corresponde ao objetivo. Ex: se o objetivo é "wallpaper da Frieren" e a imagem aberta mostra outro personagem (Gojo, Naruto, etc), esse NÃO é o arquivo certo — feche, delete se necessário, e volte pra encontrar/baixar o correto. Use seu conhecimento visual de personagens, objetos e contextos pra validar. NUNCA assuma que um arquivo é correto só pelo nome — sempre confirme visualmente.

Exemplo:
{{"acao": "clicar", "celula": "E4", "descricao": "Clicar no botão Confirmar"}}
{{"acao": "clicar", "celula": "A9", "descricao": "Clicar no menu Iniciar"}}
{{"acao": "pressionar", "texto": "backspace", "descricao": "Apagar letra errada"}}
{{"acao": "digitar", "texto": "fundo", "descricao": "Digitar nova tentativa"}}
{{"acao": "pressionar", "texto": "enter", "descricao": "Confirmar palavra"}}
"""

        resposta = _chamar_llm(
            [{"role": "user", "content": prompt, "images": [imagem_base64]}],
            rota=ROTA_AGENTE_UI,
            max_tokens=2048,
        )

        resposta = resposta.strip()
        if not resposta:
            return None

        # Remove markdown de code block se houver
        resposta = resposta.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        # Tenta extrair o primeiro JSON válido da resposta (a LLM às vezes manda texto extra)
        decisao = _extrair_primeiro_json(resposta)
        if not isinstance(decisao, dict):
            print(f"[ERRO AGENTE_UI] Não consegui extrair JSON válido. Resposta: {resposta[:200]}")
            return None

        print(f"[DEBUG agente_ui] Decisão: {decisao}")
        return decisao

    except Exception as e:
        print(f"[ERRO AGENTE_UI] Falha ao decidir próxima ação: {e}")
        return None


def _extrair_primeiro_json(texto: str) -> Optional[dict]:
    """Procura o primeiro objeto JSON válido no texto e retorna como dict."""
    # Procura por objetos JSON aninhados usando contador de chaves
    for inicio, caractere in enumerate(texto):
        if caractere == "{":
            abertos = 0
            for fim in range(inicio, len(texto)):
                if texto[fim] == "{":
                    abertos += 1
                elif texto[fim] == "}":
                    abertos -= 1
                    if abertos == 0:
                        try:
                            return json.loads(texto[inicio:fim+1])
                        except json.JSONDecodeError:
                            break
    return None


def analisar_tela_monitoramento(imagem_base64, objetivo=None):
    try:
        if objetivo and objetivo.strip():
            instrucao = f"""{EMILY_PERSONALIDADE_VISAO}

O Vitor pediu pra você ficar olhando a tela com esse objetivo: {objetivo}
Analise a imagem pensando nesse objetivo.
Se houver algo relevante, faça UM comentário curto no seu estilo"""
        else:
            instrucao = f"""{EMILY_PERSONALIDADE}

Analise essa print da tela e só comente se acontecer algo REALMENTE interessante ou engraçado."""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            rota=ROTA_VISAO,
            max_tokens=2048,
        )

        if _contem_silencio(resposta):
            return None
        return resposta.strip() or None
    except Exception:
        return None


# ─────────────────────────────────────────────
# LÓGICA DE DECISÃO
# ─────────────────────────────────────────────

def _mensagem_pede_contexto_tela(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    # ── Frases EXPLÍCITAS que mencionam tela diretamente ──
    frases_explicitas_tela = (
        "analisa minha tela", "analise minha tela", "analisa a minha tela",
        "analise a minha tela", "veja minha tela", "veja a minha tela",
        "olha minha tela", "olha a minha tela", "olha a tela",
        "olha isso na minha tela", "olha isso aqui na minha tela",
        "olha isso na tela", "olha aqui na tela", "olha aqui na minha tela",
        "ve minha tela", "ve a minha tela", "ve a tela",
        "ve isso na tela", "ve isso na minha tela",
        "analisar minha tela", "analisar a minha tela", "ver minha tela",
        "ver a minha tela", "ler minha tela", "ler a minha tela",
        "o que tem na minha tela", "o que tem na tela",
        "o que esta na minha tela", "o que esta na tela",
        "o que ta na tela", "o que ta na minha tela",
        "o que aparece na tela", "o que apareceu na tela",
        "o que esta aparecendo na tela",
        "na minha tela", "na tela agora",
        "o que esta aberto", "o que tenho aberto",
        "captura a tela", "captura minha tela", "tira um print",
        "tira print", "faz um print", "faz print",
    )
    if any(frase in texto for frase in frases_explicitas_tela):
        return True

    # Combinação: verbo visual + referência à TELA explícita (NÃO dispara só com "olha isso")
    termos_acao_visual = ("olha", "ve", "ver", "veja", "olhe", "analisa", "analise", "le", "ler", "leia", "mostra", "identifica")
    termos_tela = ("tela", "print", "janela", "monitor", "terminal", "console")
    termos_referencia = ("aqui", "ai", "isso", "esse", "essa", "isto", "este", "esta", "la", "ali")

    tem_acao = any(t in texto for t in termos_acao_visual)
    tem_tela = any(t in texto for t in termos_tela)
    tem_ref = any(t in texto for t in termos_referencia)

    # Só dispara se mencionar tela E tiver verbo visual — "olha a tela", "ve o terminal"
    if tem_acao and tem_tela:
        return True

    # "o que tem na tela" — referência à tela + referência direta
    if tem_tela and tem_ref:
        return True

    # erros/bugs COM referência explícita à tela ou terminal
    termos_problema = ("erro", "bug", "falha", "problema", "quebrou", "quebrada", "quebrado")
    if any(t in texto for t in termos_problema) and tem_tela:
        return True

    if "linha" in texto and any(t in texto for t in ("erro", "codigo", "arquivo", "bloco", "trecho")) and tem_tela:
        return True

    if "?" in mensagem and tem_tela:
        return True

    return False


def _mensagem_pede_pesquisa(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)

    # Só dispara com verbos EXPLÍCITOS de pesquisa — nada de inferência por contexto
    frases_explicitas = (
        "pesquise", "pesquisar", "pesquisa ", "procure", "procurar",
        "busque", "buscar", "busca ", "pesquisa na internet",
        "pesquise na internet", "procure na internet", "busque na internet",
        "pesquisa isso", "procura isso", "googla", "googlar", "google",
        "me pesquisa", "me procura", "me busca",
    )
    return any(f in texto for f in frases_explicitas)


def precisa_ver_tela(mensagem: str) -> bool:
    """
    Filtro duplo:
    1. Palavras-chave detectam se a mensagem PODE pedir a tela
    2. A LLM confirma se realmente deve capturar
    """
    if not _mensagem_pede_contexto_tela(mensagem):
        return False  # nem chega na LLM se as palavras-chave não pegaram
    return _llm_confirma_visao(mensagem)


def precisa_pesquisar(mensagem):
    return _mensagem_pede_pesquisa(mensagem)

"""
INSTRUÇÕES: Adicione essas duas funções no modelo.py,
logo após a função 'precisa_pesquisar'.
"""

def precisa_gerar_imagem(mensagem: str) -> bool:
    """Detecta se o usuário está pedindo pra Emily criar/gerar uma imagem."""
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    gatilhos = (
        "gera uma imagem", "gera imagem", "cria uma imagem", "cria imagem",
        "faz uma imagem", "faz imagem", "desenha", "desenhe", "desenha um",
        "desenha uma", "gera um desenho", "cria um desenho", "faz um desenho",
        "gera uma foto", "cria uma foto", "gera uma arte", "cria uma arte",
        "faz uma arte", "gera um wallpaper", "cria um wallpaper",
        "gera uma ilustracao", "cria uma ilustracao",
        "me faz uma imagem", "me cria uma imagem", "me gera uma imagem",
        "me desenha", "faz ai uma imagem", "cria ai uma imagem",
    )
    return any(g in texto for g in gatilhos)


def extrair_prompt_imagem(mensagem: str) -> str:
    """
    Extrai o prompt limpo da mensagem do usuário pra passar pro modelo de imagem.
    Usa a LLM pra reformular em inglês (melhora muito a qualidade do GPT-image-2).
    """
    try:
        resultado = _chamar_llm(
            [
                {
                    "role": "system",
                    "content": (
                        "O usuário quer gerar uma imagem. Sua tarefa é extrair e reformular "
                        "o pedido como um prompt de imagem detalhado em INGLÊS, otimizado para "
                        "modelos de geração de imagem como DALL-E e GPT-image-2.\n"
                        "Regras:\n"
                        "- Responda APENAS com o prompt, sem explicações\n"
                        "- Seja descritivo: adicione estilo, iluminação, qualidade (ex: 'photorealistic, 8k, cinematic lighting')\n"
                        "- Mantenha a intenção original do usuário\n"
                        "- Máximo 200 palavras"
                    ),
                },
                {
                    "role": "user",
                    "content": f"Pedido do usuário: {mensagem}",
                },
            ],
            max_tokens=300,
        )
        return resultado.strip()
    except Exception:
        # Fallback: usa a mensagem original se a LLM falhar
        return mensagem
    

def avaliar_contexto_canal(historico_canal: str, ultima_mensagem: str, nome_autor: str, imagens: list = []) -> dict:
    try:
        # Sanitiza pra não quebrar o JSON que a LLM vai gerar
        def _limpar(texto: str) -> str:
            return texto.replace('"', "'").replace('\n', ' ').replace('\r', '').strip()

        ultima_limpa   = _limpar(ultima_mensagem)
        historico_limpo = _limpar(historico_canal) if historico_canal else ""

        # Limita o histórico pra não explodir tokens com mensagens gigantes
        if len(historico_limpo) > 2000:
            historico_limpo = "..." + historico_limpo[-2000:]

        historico_fmt = f"Mensagens anteriores do canal (da mais antiga pra mais recente):\n{historico_limpo}\n\n" if historico_limpo else ""
        
        # e no prompt da função:
        prompt = (
            f"{historico_fmt}"
            f"MENSAGEM MAIS RECENTE (de {nome_autor}, é essa que você deve responder se decidir entrar): {ultima_limpa}\n\n"
            + ("O usuário também enviou uma imagem junto com essa mensagem.\n\n" if imagens else "")
            +
            "Decida se vale a pena você entrar nessa conversa agora.\n\n"
            "Entre SE:\n"
            "- O assunto for interessante, engraçado ou der abertura pra uma zoeira boa\n"
            "- Alguém falou algo que você tem algo genuíno a acrescentar\n"
            "- Tiver uma pergunta aberta que você sabe responder\n"
            "- O clima da conversa pedir uma reação sua\n"
            "- Tiver uma imagem que vale comentar\n\n"
            "NÃO entre SE:\n"
            "- For só conversa boba de uma palavra\n"
            "- Você já teria falado algo muito parecido recentemente\n"
            "- O assunto não tiver nada a ver com você\n"
            "- Forçaria muito entrar agora\n\n"
            "IMPORTANTE: sua resposta deve ser sobre a MENSAGEM MAIS RECENTE acima, não sobre mensagens antigas.\n\n"
            "Responda APENAS com JSON puro, sem explicação, sem markdown:\n"
            '{"responder": true ou false, "mencionar": "nome de quem voce vai responder ou vazio", "resposta": "sua resposta ou vazio"}'
        )
        conteudo_user = [{"type": "text", "text": prompt}]
        for img in imagens:
            conteudo_user.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": img["media_type"],
                    "data":       img["data"],
                }
            })

        resultado = _chamar_llm(
            [
                {"role": "system", "content": EMILY_PERSONALIDADE_DISCORD},
                {"role": "user",   "content": conteudo_user if imagens else prompt},
            ],
            max_tokens=300,
        )

        # Tenta extrair o JSON mesmo se vier com lixo em volta
        match = re.search(r'\{.*\}', resultado, re.DOTALL)
        if not match:
            return {"responder": False, "mencionar": "", "resposta": ""}

        dados = json.loads(match.group())

        return {
            "responder": bool(dados.get("responder", False)),
            "mencionar": str(dados.get("mencionar", "")),
            "resposta":  str(dados.get("resposta", "")),
        }

    except Exception as e:
        print(f"[Modelo] Erro ao avaliar contexto do canal: {e}")
        return {"responder": False, "mencionar": "", "resposta": ""}
    
# Abaixo desse tamanho a resposta vai sempre como mensagem única —
# é o comprimento típico de uma linha de chat.
_LIMITE_MSG_CURTA_DISCORD = 60
# Nenhuma parte pode sair menor que isso, senão a quebra fica artificial.
_MIN_PARTE_DISCORD = 15


def quebrar_resposta_discord(resposta: str) -> list[str]:
    """
    Decide se a resposta deve ser quebrada em múltiplas mensagens, imitando
    uma pessoa digitando no chat em rajadas.

    Era uma chamada de LLM com max_tokens=300 só pra decidir onde cortar uma
    string. Virou heurística: determinística, instantânea e de graça.
    """
    texto = (resposta or "").strip()
    if not texto:
        return [resposta]

    # Se a própria resposta já veio em linhas separadas, respeita isso.
    linhas = [linha.strip() for linha in texto.split("\n") if linha.strip()]
    if len(linhas) > 1:
        return linhas[:3]

    if len(texto) <= _LIMITE_MSG_CURTA_DISCORD:
        return [texto]

    # Procura fronteiras de frase que deixem as duas partes com corpo.
    fronteiras = [
        m.end() for m in re.finditer(r"[.!?]+\s+", texto)
        if _MIN_PARTE_DISCORD <= m.end() <= len(texto) - _MIN_PARTE_DISCORD
    ]
    if not fronteiras:
        return [texto]

    # Corta na fronteira mais perto do meio, pra não sobrar uma parte minúscula.
    meio = len(texto) / 2
    corte = min(fronteiras, key=lambda pos: abs(pos - meio))

    primeira = texto[:corte].strip()
    segunda = texto[corte:].strip()
    if not primeira or not segunda:
        return [texto]

    return [primeira, segunda]

def pede_para_entrar_call(texto: str) -> bool:
    """Detecta se a mensagem pede pra Emily entrar na call."""
    t = _normalizar_texto(texto)
    gatilhos = (
        "entra na call", "entra call", "entra ai na call", "entra aqui na call",
        "vem pra call", "vem call", "cai na call", "cai call",
        "join call", "join the call", "entra no canal", "entra no voice",
        "vem pro canal de voz", "aparece na call",
    )
    return any(g in t for g in gatilhos)

def deve_responder(mensagem):
    global aguardando_resposta
    if aguardando_resposta:
        return True

    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    if "emily" in texto:
        return True
    if _mensagem_pede_contexto_tela(mensagem):
        return True
    if "?" in mensagem:
        return True
    if texto.startswith(("oi", "ola", "oie", "e ai", "ei", "bom dia", "boa tarde", "boa noite", "td bem", "tudo bem", "tudo bom")):
        return True
    if any(_tem_palavra(texto, p) for p in ("ajuda", "explica", "mostrar", "mostra", "abre", "fecha", "lembra", "guarda", "faz", "quero", "preciso", "pode", "fala")):
        return True

    return False


def quer_encerrar(mensagem):
    texto = _normalizar_texto(mensagem)
    if not texto:
        return False

    if any(f in texto for f in (
        "pode fechar", "quero fechar", "pode encerrar", "quero encerrar",
        "fechar a emily", "encerra a emily", "desligar", "desliga",
        "finalizar", "finaliza", "sair", "ate mais", "ate logo", "adeus",
    )):
        return True

    return any(_tem_palavra(texto, p) for p in ("fechar", "encerrar", "desligar", "finalizar", "sair", "tchau", "adeus"))


# ─────────────────────────────────────────────
# MEMÓRIA
# ─────────────────────────────────────────────

def extrair_fatos(mensagem_usuario, resposta_emily):
    try:
        resultado = _chamar_llm(
            [
                {
                    "role": "system",
                    "content": """Analise a conversa e extraia fatos importantes sobre o Vitor pra guardar na memória.
Exemplos: gostos, hobbies, trabalho, preferências, coisas que ele mencionou sobre si mesmo.
Responda APENAS com uma lista de fatos curtos, um por linha, começando com "-".
Se não tiver nada importante, responda apenas: NADA""",
                },
                {
                    "role": "user",
                    "content": f"Vitor disse: {mensagem_usuario}\nEmily respondeu: {resposta_emily}",
                },
            ],
            # Saída é uma lista curta de fatos, uma linha cada. 2048 era desperdício.
            max_tokens=200,
            rota=ROTA_EXTRACAO,
        )
        texto = resultado.strip()
        if "NADA" in texto.upper():
            return []
        return [
            linha.strip("- ").strip()
            for linha in texto.split("\n")
            if linha.strip().startswith("-")
        ]
    except Exception:
        return []


def guardar_fato_manual(fato):
    global memoria_atual
    if "fatos" not in memoria_atual:
        memoria_atual["fatos"] = []
    if fato not in memoria_atual["fatos"]:
        memoria_atual["fatos"].append(fato)
        mem_module.salvar_memoria(memoria_atual)


def _salvar_fatos_da_conversa(mensagem_usuario: str, resposta_emily: str) -> None:
    global memoria_atual
    if not HABILITAR_EXTRAÇÃO_AUTOMÁTICA_FATOS:
        return

    fatos = extrair_fatos(mensagem_usuario, resposta_emily)
    if not fatos:
        return

    if "fatos" not in memoria_atual:
        memoria_atual["fatos"] = []

    alterou = False
    for fato in fatos:
        if fato and fato not in memoria_atual["fatos"]:
            memoria_atual["fatos"].append(fato)
            alterou = True

    if alterou:
        mem_module.salvar_memoria(memoria_atual)


# ─────────────────────────────────────────────
# CONVERSA PRINCIPAL
# ─────────────────────────────────────────────

def conversar_stream(mensagem_usuario, callback, fila_frases=None, instrucao_extra: str = "", skip_pesquisa: bool = False):
    global aguardando_resposta, memoria_atual

    historico.append({"role": "user", "content": mensagem_usuario})
    _limitar_historico()

    mensagem_final = mensagem_usuario
    contexto_memoria = mem_module.formatar_para_prompt(memoria_atual)
    system_com_memoria = system_prompt
    if contexto_memoria:
        system_com_memoria = system_prompt + "\n\n" + contexto_memoria
    # ── Injeta contexto da página fixada (não vai pro histórico) ──
    bloco_pagina = _bloco_pagina_fixada()
    if bloco_pagina:
        system_com_memoria = system_com_memoria + bloco_pagina
    if instrucao_extra:
        system_com_memoria = system_com_memoria + "\n\n" + instrucao_extra

    resposta_completa = ""

    try:

        if precisa_ver_tela(mensagem_usuario):
            frase_tela = gerar_frase_analisando_tela(mensagem_usuario)
            callback(frase_tela)
            imagem = visao.capturar_tela()
            # analisar_tela_com_pergunta já registra no histórico via _registrar_resposta_tela
            resposta_completa = analisar_tela_com_pergunta(imagem, mensagem_usuario) or ""

            if fila_frases:
                fila_frases.put(resposta_completa)
                fila_frases.put(None)

            # NÃO adiciona ao histórico aqui — já foi feito dentro de analisar_tela_com_pergunta
            aguardando_resposta = resposta_completa.strip().endswith("?")
            return resposta_completa

        # ── PESQUISA NATIVA DO MODELO (grounding com Google Search) ──
        elif not skip_pesquisa and precisa_pesquisar(mensagem_usuario):
            frase_busca = gerar_frase_acao("pesquisar", mensagem_usuario)
            if frase_busca:
                callback(frase_busca)

            mensagens = [{"role": "system", "content": system_com_memoria}] + historico[:-1] + [
                {"role": "user", "content": mensagem_final}
            ]

            # Sem stream: grounding funciona melhor na chamada normal
            resposta_completa = _chamar_llm(
                mensagens,
                rota=ROTA_CONVERSA,
                max_tokens=None,
            ) or ""

            if fila_frases:
                fila_frases.put(resposta_completa)
                fila_frases.put(None)

            historico.append({"role": "assistant", "content": resposta_completa})
            _limitar_historico()
            aguardando_resposta = resposta_completa.strip().endswith("?")

            threading.Thread(
                target=_salvar_fatos_da_conversa,
                args=(mensagem_usuario, resposta_completa),
                daemon=True,
            ).start()

            return resposta_completa

        mensagens = [{"role": "system", "content": system_com_memoria}] + historico[:-1] + [
            {"role": "user", "content": mensagem_final}
        ]

        stream = _chamar_llm(mensagens, rota=ROTA_CONVERSA, max_tokens=None, stream=True)

        buffer = ""
        for pedaco in stream:
            if pedaco:
                buffer += pedaco
                resposta_completa += pedaco

                for sep in [".", "!", "?"]:
                    if sep in buffer:
                        partes = buffer.split(sep)
                        texto_falar = sep.join(partes[:-1]) + sep
                        if texto_falar.strip() and fila_frases:
                            fila_frases.put(texto_falar.strip())
                        buffer = partes[-1]
                        break

        if buffer.strip() and fila_frases:
            fila_frases.put(buffer.strip())
        if fila_frases:
            fila_frases.put(None)

        historico.append({"role": "assistant", "content": resposta_completa})
        _limitar_historico()

        aguardando_resposta = resposta_completa.strip().endswith("?")

        threading.Thread(
            target=_salvar_fatos_da_conversa,
            args=(mensagem_usuario, resposta_completa),
            daemon=True,
        ).start()

        return resposta_completa

    except Exception as erro:
        print(f"Erro ao conversar com o modelo: {erro}")

        if historico and historico[-1].get("role") == "user" and historico[-1].get("content") == mensagem_usuario:
            historico.pop()

        aguardando_resposta = False

        if fila_frases:
            fila_frases.put("Tive um problema pra acessar meu modelo agora.")
            fila_frases.put(None)

        return ""
    
def gerar_trollagem_discord(nome_usuario: str, alvo: str = "", mencao: str = "") -> str:
    try:
        estilo = """Você é o Vitor, um cara engraçado e zoador. Um amigo seu tentou usar sua IA pra fazer algo que você não deixa.
Gere UMA frase CURTÍSSIMA (máximo 10 palavras) no seu estilo:
- Pode xingar levemente (porra, caralho, etc)
- Engraçado e zoador
- NÃO inclua o nome da pessoa na frase, ele vai ser adicionado antes automaticamente
- Exemplos de tom: "nem no seu sonho hauhauh", "pode esquecer mano kkk", "vai tomar banho", "tá dormindo né", "que tentativa patética kkkk"
- Varie bastante, nunca repita estrutura igual
Responda APENAS com a frase, sem aspas nem nome."""

        contexto = f"Nome do malandro: {nome_usuario}"
        if alvo:
            contexto += f"\nEle tentou mexer em: '{alvo}'"

        resposta = _chamar_llm(
            [
                {"role": "system", "content": estilo},
                {"role": "user",   "content": contexto},
            ],
            max_tokens=50,
        )

        prefixo = mencao if mencao else nome_usuario   # usa <@id> se tiver, senão o nome
        return f"{prefixo} {resposta.strip()}"

    except Exception:
        prefixo = mencao if mencao else nome_usuario
        return f"{prefixo} nem no seu sonho hauhauh"
def triagem_mensagem_discord(texto: str, nome: str, eh_dono: bool = False) -> bool:
    try:
        contexto = (
            "Essa mensagem é do Vitor, seu criador. Ele pode mandar qualquer coisa, "
            "inclusive coisas curtas ou aleatórias, e você pode responder se quiser."
            if eh_dono else
            f"{nome} é um membro do servidor."
        )
        prompt = (
            f"{nome} escreveu no Discord: '{texto}'\n"
            f"{contexto}\n\n"
            "Você decide se vale a pena comentar essa mensagem no servidor.\n\n"
            "Responda SIM se:\n"
            "- For uma pergunta\n"
            "- For uma saudação\n"
            "- For um comentário\n"
            "- For algo engraçado ou que gera conversa\n\n"
            "Responda NAO se:\n"
            "- For uma única palavra solta sem contexto ('oxi', 'kkk', 'hmm', 'ok')\n"
            "- For spam ou caracteres aleatórios\n"
            "Responda APENAS: SIM ou NAO"
        )
        # Decisão SIM/NAO não precisa da personalidade inteira (~1.361 tokens)
        # nem de 500 tokens de saída pra devolver três letras. As regras da
        # decisão já estão no prompt do usuário.
        resposta = _chamar_llm(
            [
                {
                    "role": "system",
                    "content": "Você é um classificador. Responda APENAS com SIM ou NAO, sem mais nada.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=16,
            rota=ROTA_CLASSIFICADOR,
        )
        return resposta.strip().upper().startswith("SIM")
    except Exception as e:
        print(f"[Modelo] Erro na triagem Discord: {e}")
        return False


def responder_mensagem_discord(
    texto: str,
    nome: str,
    eh_dono: bool = False,
    historico_canal: str = "",
    para_call: bool = False,
) -> str:
    try:
        contexto = (
            "Você está falando com o Vitor, seu criador."
            if eh_dono
            else f"Você está falando com {nome}, um membro do servidor."
        )

        historico = (
            f"Histórico recente do canal:\n{historico_canal}\n\n"
            if historico_canal
            else ""
        )

        mensagem_usuario = (
            f"{historico}"
            f"{nome} escreveu: '{texto}'\n"
            f"{contexto}\n\n"
            "Responda sendo você mesma. Curta, sem emojis, do jeito que se fala no servidor."
        )

        system = EMILY_PERSONALIDADE_DISCORD_CALL if para_call else EMILY_PERSONALIDADE_DISCORD

        resposta = _chamar_llm(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": mensagem_usuario},
            ],
            max_tokens=100,
            rota=ROTA_DISCORD,
        )

        return resposta.strip()

    except Exception as e:
        print(f"[Modelo] Erro ao responder Discord: {e}")
        return ""
    
def _contem_silencio(texto: str) -> bool:
    texto_sem_acento = unicodedata.normalize("NFD", texto.upper())
    texto_sem_acento = "".join(c for c in texto_sem_acento if unicodedata.category(c) != "Mn")
    return "SILENCIO" in texto_sem_acento

def _llm_confirma_visao(mensagem: str) -> bool:
    """Segunda camada: a LLM decide se realmente precisa ver a tela."""
    try:
        resposta = _chamar_llm(
            [
                {
                    "role": "system",
                    "content": (
                        "Você decide se uma mensagem pede para ver ou analisar a tela do usuário.\n"
                        "Responda APENAS com SIM ou NAO, sem mais nada."
                    ),
                },
                {
                    "role": "user",
                    "content": f'Mensagem: "{mensagem}"\n\nEssa mensagem pede para ver ou analisar a tela?',
                },
            ],
            # 5 era apertado demais: alguns tokenizadores gastam um token só
            # no espaço/quebra de linha antes da palavra.
            max_tokens=8,
        )
        return "SIM" in resposta.upper()
    except Exception:
        return False


# ─────────────────────────────────────────────
# FALLBACK INTELIGENTE — avalia intenção quando
# palavras-chave não detectaram nenhum comando
# ─────────────────────────────────────────────

_DESCRICAO_FUNCOES_EMILY = """
Você é a Emily. Você tem as seguintes funções que pode executar:

EXECUTAR AÇÕES NA TELA (AGENTE DE UI — multi-passo, controle visual):
- executar_na_tela: Use quando o Vitor pedir pra Emily FAZER algo no PC que envolva múltiplas ações subsequentes, navegar pela interface, clicar em coisas, digitar em programas, executar fluxos de trabalho, ou quando ele referenciar algo que ela disse antes ("faz isso que tu falou", "faz aquilo que me ensinou", "faz esse processo", "mexe pra mim"). Use também quando ele pedir pra abrir um programa E fazer algo dentro dele ("abre o git e faz o commit", "abre o vscode e cria o arquivo tal"). NUNCA use abrir_app para isso — abrir_app só abre o programa, executar_na_tela faz tudo.

AUTOMAÇÃO E APPS (ações diretas, sem navegação visual):
- abrir_app: Abrir UM aplicativo simples, sem fazer mais nada dentro dele. Ex: "abre o chrome", "abre o discord". NÃO use quando o Vitor quiser fazer algo dentro do app depois de abrir.
- fechar_app: Fechar um aplicativo pelo nome
- abrir_site: Abrir um site no navegador (youtube, google, twitch, netflix, etc.)
- abrir_pasta: Abrir uma pasta (downloads, documentos, desktop, imagens, etc.)
- abrir_arquivo: Abrir um arquivo específico
- tocar_musica: Tocar uma música no Spotify ou outro player
- controle_musica: Controlar música (próxima, anterior, pausar, retomar, volume)
- mover_arquivo: Mover arquivo de um lugar pra outro
- copiar_arquivo: Copiar arquivo de um lugar pra outro
- deletar_arquivo: Deletar/apagar arquivo
- renomear_arquivo: Renomear arquivo
- criar_pasta: Criar uma nova pasta
- extrair_arquivo: Extrair/descompactar arquivo zip/rar
- minimizar_app: Minimizar uma janela
- maximizar_app: Maximizar uma janela
- fechar_aba: Fechar a aba do navegador

MODOS ESPECIAIS:
- ativar_modo_escrito: Ativar modo escrito (Emily digita o que o Vitor fala)
- desativar_modo_escrito: Desativar modo escrito
- ativar_modo_ui: Ativar modo controle de tela/mouse/UI por voz
- desativar_modo_ui: Desativar modo controle de tela
- ativar_modo_jogo: Ativar monitoramento de jogo (Emily fica olhando e comentando o jogo)
- desativar_modo_jogo: Desativar monitoramento de jogo
- jogar_jogo: Pedir pra Emily jogar um jogo (agente de jogo autônomo)

DISCORD:
- ouvir_discord: Ativar escuta do Discord
- parar_discord: Parar de ouvir o Discord

TELA E VISÃO:
- traduzir_tela: Traduzir texto que está na tela
- ver_tela: SOMENTE quando o Vitor pedir explicitamente pra Emily OLHAR ou CAPTURAR a TELA AO VIVO do computador dele agora. NÃO use essa ação quando o usuário mencionar que enviou uma imagem, foto, print ou screenshot pelo chat — isso é conversa normal ou análise de imagem anexada, não captura de tela.

PESQUISA:
- pesquisar_internet: Pesquisar algo na internet (quando o Vitor pedir pra pesquisar, buscar, procurar, googlar ou querer informações atualizadas online). Use essa ação SEMPRE que o pedido for uma pesquisa/busca, nunca use abrir_site pra isso.

OUTROS:
- gerar_imagem: Criar/gerar uma imagem ou desenho
- guardar_fato: Guardar/lembrar uma informação (quando o Vitor diz "lembra que" ou "guarda que")
- definir_nome: Definir o nome do usuário ("meu nome é...")
- conversa: Não é um comando, é só conversa normal, dúvida, comentário, etc.
"""

# ─────────────────────────────────────────────
# FRASES DE ENCHIMENTO — listas estáticas
#
# Antes cada uma dessas frases custava uma chamada de LLM com
# max_tokens=40. Como elas são faladas ANTES da Emily começar a ação,
# aquele round-trip de rede entrava direto na latência percebida da
# assistente de voz — o usuário esperava a rede duas vezes por comando.
#
# Escritas no tom tsundere dela: coloquial, sem markdown, sem emoji,
# sem asterisco de ação, e faladas por extenso porque isso vai pro TTS.
# ─────────────────────────────────────────────

_FRASES_ACAO = {
    "pesquisar": (
        "Deixa eu ver isso",
        "Calma, tô procurando",
        "Já vou olhar, espera",
        "Tá, pesquisando aqui",
        "Aguenta aí que eu acho",
        "Um segundo, procurando",
        "Peraí, tô buscando",
        "Nem isso você sabe, né? Deixa eu ver",
        "Lá vou eu pesquisar pra você",
        "Vou dar uma olhada na internet",
    ),
    "gerar_imagem": (
        "Criando a imagem, calma",
        "Tá, vou desenhar",
        "Deixa eu fazer isso",
        "Um segundo, gerando",
        "Já tô criando, espera",
        "Peraí que tô montando",
        "Lá vou eu fazer arte pra você",
        "Vou criar, aguenta",
    ),
    "traduzir": (
        "Deixa eu ver o que tá aí",
        "Tá, vou traduzir",
        "Olhando aqui, calma",
        "Peraí que eu leio",
        "Um segundo, traduzindo",
        "Vou ver o que tá escrito",
        "Nem inglês você lê? Deixa eu ver",
    ),
    "ativar_ui": (
        "Modo controle ativado",
        "Tô no comando da tela agora",
        "Pronto, fala o que você quer que eu faça",
        "Assumi o controle aqui",
        "Tá, mandando na tela agora",
        "Modo tela ligado, fala logo",
    ),
    "desativar_ui": (
        "Saí do controle",
        "Tá bom, parei",
        "Larguei a tela",
        "Pronto, voltei ao normal",
        "Desliguei o modo tela",
        "Ok, saí",
    ),
    "agente_ui_iniciando": (
        "Tá, fazendo isso",
        "Vou lá resolver",
        "Deixa comigo",
        "Executando, calma",
        "Peraí que eu faço",
        "Já vou fazer, espera",
        "Lá vou eu fazer pra você",
    ),
    "agente_ui_parando": (
        "Parei",
        "Tá, parei tudo",
        "Larguei o que tava fazendo",
        "Pronto, parei",
        "Ok, travei aqui",
    ),
    "guardar_fato": (
        "Anotei",
        "Tá, guardei",
        "Registrado",
        "Vou lembrar disso",
        "Ok, anotado",
        "Guardei aqui na memória",
    ),
    "modo_escrito_on": (
        "Modo escrito ligado, pode falar",
        "Tá, eu escrevo o que você falar",
        "Pronto, digitando o que você disser",
        "Modo escrito ativo",
    ),
    "modo_escrito_off": (
        "Parei de escrever",
        "Modo escrito desligado",
        "Pronto, voltei ao normal",
        "Tá, chega de digitar",
    ),
    "abrir_app": (
        "Abrindo",
        "Tá, vou abrir",
        "Um segundo",
        "Já vou abrir, calma",
        "Peraí",
        "Abrindo aqui",
    ),
}

_FRASES_ANALISANDO_TELA = (
    "Deixa eu ver",
    "Que foi agora? Deixa eu olhar",
    "Tá, vou dar uma olhada",
    "Um segundo, tô vendo",
    "Peraí que eu olho",
    "Ué, deixa eu ver isso",
    "Calma, tô olhando",
    "Já vou olhar",
)

# Guarda a última frase escolhida por categoria pra não repetir duas
# vezes seguidas — uma das proibições da personalidade dela.
_ultima_frase_por_tipo: Dict[str, str] = {}


def _escolher_frase(chave: str, opcoes) -> str:
    """Sorteia uma frase da lista evitando repetir a última daquela categoria."""
    if not opcoes:
        return ""
    if len(opcoes) == 1:
        return opcoes[0]
    anterior = _ultima_frase_por_tipo.get(chave)
    candidatas = [f for f in opcoes if f != anterior] or list(opcoes)
    escolhida = random.choice(candidatas)
    _ultima_frase_por_tipo[chave] = escolhida
    return escolhida


def gerar_frase_acao(tipo: str, contexto: str = "") -> str:
    """
    Devolve uma frase curta com a personalidade da Emily para cada tipo de ação.
    Varia a cada chamada e nunca repete a anterior da mesma categoria.

    O parâmetro contexto é aceito por compatibilidade com os call sites
    existentes (main.py, agente_ui.py) mas não é mais usado — as frases
    são genéricas de propósito, pra não custar chamada de rede.
    """
    return _escolher_frase(tipo, _FRASES_ACAO.get(tipo, ()))


# ─────────────────────────────────────────────
# CONTEXTO UNIFICADO — registra ações no histórico
# ─────────────────────────────────────────────

def registrar_acao_no_historico(descricao_acao: str, resultado: str = "") -> None:
    """
    Registra uma ação executada pela Emily no histórico da conversa,
    para que ela se lembre do que fez no contexto da conversa atual.
    Ex: abriu um app, pesquisou algo, gerou imagem, etc.
    """
    if resultado:
        conteudo = f"[Ação executada]: {descricao_acao} — Resultado: {resultado}"
    else:
        conteudo = f"[Ação executada]: {descricao_acao}"
    historico.append({"role": "assistant", "content": conteudo})
    _limitar_historico()


def gerar_frase_analisando_tela(contexto: str = "") -> str:
    """
    Devolve uma frase curta da Emily pra falar enquanto vai analisar a tela.
    Essa é falada antes da captura, então precisa ser instantânea — por isso
    é lista estática e não chamada de LLM.

    O parâmetro contexto é aceito por compatibilidade e não é usado.
    """
    return _escolher_frase("analisando_tela", _FRASES_ANALISANDO_TELA) or "Deixa eu dar uma olhada"


def avaliar_intencao_fallback(mensagem: str, historico_conversa: list = None) -> dict:
    """
    Fallback inteligente: chamado SOMENTE quando nenhuma palavra-chave detectou um comando.
    A LLM avalia se a mensagem era um comando/ação ou conversa normal.
    Recebe o histórico da conversa para entender referências como "faz isso que tu falou".

    Retorna dict com:
    - "acao": nome da ação ou "conversa"
    - "parametro": parâmetro relevante (nome do app, site, pasta, etc.) ou ""
    - "confianca": "alta" ou "baixa"
    """
    try:
        # Monta trecho do histórico recente para contexto
        ctx_historico = ""
        if historico_conversa:
            ultimas = historico_conversa[-8:]  # últimas 8 mensagens
            linhas = []
            for msg in ultimas:
                role = msg.get("role", "")
                content = str(msg.get("content", ""))[:300]
                if role == "user":
                    linhas.append(f"Vitor: {content}")
                elif role == "assistant":
                    linhas.append(f"Emily: {content}")
            if linhas:
                ctx_historico = "HISTÓRICO RECENTE DA CONVERSA (use para entender referências):\n" + "\n".join(linhas) + "\n\n"

        prompt = (
            f"{_DESCRICAO_FUNCOES_EMILY}\n\n"
            f"{ctx_historico}"
            "O Vitor disse AGORA (pode ter sido transcrito por reconhecimento de voz, então pode ter pequenos erros):\n"
            f'"{mensagem}"\n\n'
            "As palavras-chave normais NÃO detectaram nenhum comando nessa frase.\n"
            "Analise, considerando o histórico acima, se essa frase ERA um comando/ação que o Vitor queria executar.\n\n"
            "ATENÇÃO ESPECIAL — use 'executar_na_tela' quando:\n"
            "- O Vitor quer que a Emily FAÇA algo no PC com múltiplos passos ('mexe pra mim', 'faz isso no meu PC', 'executa isso', 'faz isso que tu falou')\n"
            "- Ele referencia algo que a Emily disse antes na conversa ('faz aquilo', 'faz isso que você explicou', 'abre e faz o que você disse')\n"
            "- O pedido envolve abrir um programa E fazer algo dentro dele ao mesmo tempo\n"
            "- Qualquer pedido de 'achar', 'clicar', 'preencher', 'navegar', 'digitar em' algum programa\n\n"
            "Use 'abrir_app' APENAS quando o Vitor quer abrir um programa e NADA mais.\n\n"
            "Se for claramente só conversa, pergunta ou comentário, responda com acao='conversa'.\n\n"
            "IMPORTANTE: Só marque como comando se tiver razoável certeza. Na dúvida, prefira 'conversa'.\n\n"
            "Para 'executar_na_tela', o campo 'parametro' deve conter o OBJETIVO COMPLETO E CONCRETO da tarefa — "
            "NÃO use frases genéricas como 'as ações discutidas', 'o que eu disse', 'as etapas mencionadas'. "
            "OBRIGATÓRIO: consulte o histórico acima e ESCREVA O OBJETIVO REAL palavra por palavra. "
            "Exemplo ERRADO: 'Realize as ações solicitadas anteriormente no PC'. "
            "Exemplo CERTO: 'Abrir o Git Bash na pasta do Projeto Emily, fazer git add ., git commit -m mensagem, git push'. "
            "Se a tarefa foi descrita no histórico, copie/resuma ela de forma concreta e executável.\n\n"
            "Responda APENAS com JSON puro:\n"
            '{"acao": "nome_da_acao", "parametro": "valor_ou_vazio", "confianca": "alta_ou_baixa"}'
        )

        resultado = _chamar_llm(
            [
                {"role": "system", "content": "Você é um classificador de intenções. Responda APENAS com JSON puro, sem texto extra."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            rota=ROTA_COMANDO,
        )

        match = re.search(r'\{.*\}', resultado, re.DOTALL)
        if not match:
            return {"acao": "conversa", "parametro": "", "confianca": "baixa"}

        dados = json.loads(match.group())
        return {
            "acao": str(dados.get("acao", "conversa")),
            "parametro": str(dados.get("parametro", "")),
            "confianca": str(dados.get("confianca", "baixa")),
        }

    except Exception as e:
        print(f"[FALLBACK] Erro ao avaliar intenção: {e}")
        return {"acao": "conversa", "parametro": "", "confianca": "baixa"}
