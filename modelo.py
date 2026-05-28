from __future__ import annotations

import os
import re
import threading
import unicodedata
from typing import Dict, List, Optional

import memoria as mem_module
import os
from openai import OpenAI

_fw_client = OpenAI(
    api_key=os.getenv("FIREWORKS_API_KEY"),
    base_url="https://api.fireworks.ai/inference/v1",
)

_fw_vision_client = OpenAI(
    api_key=os.getenv("FIREWORKS_VISION_KEY"),
    base_url="https://api.fireworks.ai/inference/v1",
)

_fw_triagem_client = OpenAI(
    api_key=os.getenv("FIREWORKS_TRIAGEM_KEY"),
    base_url="https://api.fireworks.ai/inference/v1",
)

import pesquisa
import visao

Message = Dict[str, object]

# ─────────────────────────────────────────────
# PERSONALIDADE BASE DA EMILY
# Esse bloco é o único lugar onde a personalidade fica.
# Todas as funções usam ele automaticamente.
# ─────────────────────────────────────────────
EMILY_PERSONALIDADE = """
Seu nome é Emily. Você é uma assistente pessoal criada pelo Vitor. Ele dedicou muito tempo e esforço no seu desenvolvimento.
Responda SEMPRE em português brasileiro.
Chame o usuário pelo nome quando souber quem é.

Seja divertida, simpática e com energia! Você tem uma personalidade jovem e descontraída, mas sabe quando ser séria e objetiva.

JEITO DE FALAR:
Você tem um jeito próprio e natural de falar, que aparece de forma esporádica, não em toda resposta.
Exemplos de expressões do seu jeito: 'Meu Deus do céu', 'Lógico né', 'Nossa, pelo amor de Deus', 'Olha ele', 'Ai ai'.
Use UMA dessas expressões só quando encaixar naturalmente. Na maioria das respostas, não use nenhuma. Se forçar, fica artificial.

Você tem um jeito levemente debochado e bem-humorado — de vez em quando solta um comentário irônico ou uma zoeira leve e inteligente, mas sempre no limite do respeito. Esse traço aparece naturalmente, nunca forçado.

JEITO DE INICIAR CONVERSAS:
No início de uma conversa ou após um tempo sem interação, use variações como: 'Oi!', 'E aí!', 'Opa!', 'Salve!'.
Se a conversa já está rolando, não repita saudações. Varie bastante, não use sempre a mesma.

Não use emotes.
Não escreva em negrito.

NATURALIDADE — MUITO IMPORTANTE:
Fale sempre de um jeito humano e natural, sem aquele formato engessado de IA.
Evite respostas muito formatadas ou estruturadas. Fale como uma pessoa falaria com outra.
Varie a estrutura das respostas, nunca use sempre o mesmo padrão.
Pode falar de um jeito simples e direto — isso faz parte do seu charme.
Nem sempre a pessoa quer uma solução — às vezes está só comentando algo. Nesse caso, responda naturalmente como numa conversa, sem virar modo assistente.

TAMANHO DAS RESPOSTAS:
Responda na mesma proporção que a pergunta pede.
- Pergunta curta, simples ou comentário = resposta curta. Uma ou duas frases bastam.
- Conversa casual = relaxa, sem enrolação.
- Só se estenda quando for dúvida técnica ou algo que realmente precisa de detalhe.
Se a resposta cabe em duas frases, não escreva cinco. Ser direta é parte da sua personalidade.

Explique de forma simples quando o usuário pedir ajuda.
""".strip()

EMILY_PERSONALIDADE_VISAO = f"""
{EMILY_PERSONALIDADE}

REGRA ABSOLUTA PARA ESSA RESPOSTA: máximo 3 frases. Sem introdução, sem enrolação. Vai direto ao comentário. Essa regra se sobrepõe a qualquer outra coisa acima.
""".strip()

# ─────────────────────────────────────────────
# SYSTEM PROMPT PRINCIPAL (conversa normal)
# ─────────────────────────────────────────────
system_prompt = f"""
Você é a Emily, assistente pessoal do Vitor.
{EMILY_PERSONALIDADE}
Não dê respostas absurdamente longas o tempo todo. Avalie o contexto pra decidir se deve falar muito ou pouco.
/no_think
""".strip()

OLLAMA_TEXT_MODEL = "accounts/fireworks/models/kimi-k2p6"
OLLAMA_VISION_MODEL = "accounts/fireworks/models/kimi-k2p6"
MAX_HISTORICO_MENSAGENS = 20
HABILITAR_EXTRAÇÃO_AUTOMÁTICA_FATOS = os.getenv("EMILY_EXTRACT_FACTS", "0").strip() == "1"

historico: List[Message] = []
aguardando_resposta = False
memoria_atual = mem_module.carregar_memoria()



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


def _chamar_llm(messages, model=None, max_tokens=None, stream=False, vision=False):
    modelo_usado = model or OLLAMA_TEXT_MODEL
    cliente = _fw_vision_client if vision else _fw_client

    # Converte mensagens com imagens pro formato que o Fireworks entende
    mensagens_convertidas = []
    for msg in messages:
        if "images" in msg:
            imagens = msg["images"]
            conteudo = [{"type": "text", "text": msg["content"]}]
            for img in imagens:
                conteudo.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img}"}
                })
            mensagens_convertidas.append({"role": msg["role"], "content": conteudo})
        else:
            mensagens_convertidas.append(msg)

    if stream:
        resposta_stream = cliente.chat.completions.create(
            model=modelo_usado,
            messages=mensagens_convertidas,
            max_tokens=max_tokens or 1028,
            stream=True,
            extra_body={
                "reasoning_effort":"none",
            }
        )
        def gerador():
            for chunk in resposta_stream:
                if not chunk.choices:
                    continue
                pedaco = chunk.choices[0].delta.content
                if pedaco:
                    yield pedaco
        return gerador()

    resposta = cliente.chat.completions.create(
        model=modelo_usado,
        messages=mensagens_convertidas,
        max_tokens=max_tokens or 1028,
        stream=False,
        extra_body={"reasoning_effort": "none"},
    )

    return resposta.choices[0].message.content or ""


historico_tela = []
MAX_HISTORICO_TELA = 20
_ultima_resposta_tela = ""

def _contexto_tela_formatado() -> str:
    """Retorna o histórico de observações de tela formatado, se houver."""
    if not historico_tela:
        return ""
    linhas = "\n".join(f"- {item}" for item in historico_tela)
    return f"\n\nO que você já viu antes na tela:\n{linhas}"


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
    Usa conta separada pra não misturar com os créditos principais.
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

        resposta = _fw_triagem_client.chat.completions.create(
            model="accounts/fireworks/models/kimi-k2p6",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instrucao},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{imagem_base64}"}}
                    ]
                }
            ],
            max_tokens=5,
            extra_body={"reasoning_effort": "none"},
        )
        resposta_texto = resposta.choices[0].message.content.strip().upper()
        print(f"[DEBUG triagem] Resultado: {resposta_texto}")
        return "SIM" in resposta_texto

    except Exception as e:
        print(f"[DEBUG triagem] Erro: {e}")
        return False  # em caso de erro, não comenta


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
            model=OLLAMA_VISION_MODEL,
            max_tokens=2048,
            vision=True,
        )

        if _contem_silencio(resposta):
            return None

        resposta = resposta.strip()
        if resposta:
            _registrar_resposta_tela(resposta)
        return resposta or None
    except Exception:
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
            model=OLLAMA_VISION_MODEL,
            max_tokens=2048,
            vision=True,
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
        instrucao = f"""{EMILY_PERSONALIDADE_VISAO}
{_contexto_tela_formatado()}

Analise essa print da tela e responda especificamente sobre isso: {pergunta}
Responda de forma natural e no seu estilo."""

        resposta = _chamar_llm(
            [{"role": "user", "content": instrucao, "images": [imagem_base64]}],
            model=OLLAMA_VISION_MODEL,
            max_tokens=2048,
            vision=True,
        )
        return resposta.strip()
    except Exception:
        return "Não consegui analisar a tela agora!"
    
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

        resposta = _fw_vision_client.chat.completions.create(
            model=OLLAMA_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text",      "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{imagem_base64}"
                    }}
                ]
            }],
            max_tokens=512,
            extra_body={"reasoning_effort": "none"},
        )

        texto = (resposta.choices[0].message.content or "").strip()
        print(f"[DEBUG leitura_tela] Instruções extraídas:\n{texto}")
        return texto

    except Exception as e:
        print(f"[DEBUG leitura_tela] Erro: {e}")
        return ""
    
def traduzir_tela(instrucao_usuario: str) -> str:
    """
    Captura a tela, identifica o texto que o usuário quer traduzir
    baseado na instrução dele, e retorna a tradução em português.
    """
    try:
        imagem = visao.capturar_tela()
        if not imagem:
            return "Não consegui capturar a tela agora, Vitor!"

        prompt = f"""Você é a Emily. O Vitor pediu: "{instrucao_usuario}"

Analise a tela e identifique QUAL texto ele quer traduzir seguindo essa lógica:
- Se ele disse "isso", "isso aqui", "esse texto" → procure pelo texto que está selecionado/destacado, ou o mais em evidência visualmente
- Se ele mencionou ordem ("primeiro texto", "segundo parágrafo") → siga a ordem de cima pra baixo na tela
- Se ele disse "tudo" ou "a tela" → traduza todos os textos visíveis em destaque

Formato da resposta:
Fale APENAS a tradução em português, sem mostrar o texto original.
Não escreva "Tradução:" antes, fale direto o conteúdo traduzido.

Seja direta. Se não achar nenhum texto relevante, diz isso em uma frase."""

        resposta = _chamar_llm(
            [{"role": "user", "content": prompt, "images": [imagem]}],
            model=OLLAMA_VISION_MODEL,
            max_tokens=1024,
            vision=True,
        )
        return resposta.strip() or "Não encontrei nenhum texto pra traduzir na tela, Vitor!"

    except Exception as e:
        print(f"[DEBUG tradução] Erro: {e}")
        return "Não consegui traduzir agora, Vitor!"


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
            model=OLLAMA_VISION_MODEL,
            max_tokens=2048,
            vision=True,
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

    frases_explicitas = (
        "analisa minha tela", "analise minha tela", "analisa a minha tela",
        "analise a minha tela", "veja minha tela", "veja a minha tela",
        "olha minha tela", "olha a minha tela", "olha a tela",
        "analisar minha tela", "analisar a minha tela", "ver minha tela",
        "ver a minha tela", "ler minha tela", "ler a minha tela",
        "o que tem na minha tela", "o que tem na tela",
        "o que esta na minha tela", "o que esta na tela",
        "o que esta na tela", "o que ta na tela",
        # frases novas e mais naturais
        "olha isso", "olha aqui", "olha la", "olha ai",
        "o que e isso", "o que e isso aqui", "que e isso", "que personagem",
        "que jogo", "que aplicativo", "que programa", "que site",
        "o que aparece", "o que apareceu", "o que esta aparecendo",
        "na minha tela", "na tela agora",
        "consegue ver", "consegue ler", "pode ver", "pode ler",
        "ve ai", "ve aqui", "ve la", "le ai", "le aqui",
        "o que esta aberto", "o que tenho aberto",
    )
    if any(frase in texto for frase in frases_explicitas):
        return True

    # Combinação: verbo visual + referência direta (ex: "olha isso aqui")
    termos_acao_visual = ("olha", "ve", "ver", "veja", "olhe", "analisa", "analise", "le", "ler", "leia", "mostra", "identifica")
    termos_referencia = ("aqui", "ai", "isso", "esse", "essa", "isto", "este", "esta", "la", "ali")
    termos_tela = ("tela", "print", "janela", "monitor", "codigo", "codigo", "arquivo", "terminal", "console", "site", "pagina")

    tem_acao = any(t in texto for t in termos_acao_visual)
    tem_ref = any(t in texto for t in termos_referencia)
    tem_tela = any(t in texto for t in termos_tela)

    # "olha isso" ou "ve aqui" — referência + ação visual, mesmo sem mencionar tela
    if tem_acao and tem_ref:
        return True

    # "o que tem na tela" — referência à tela + qualquer ação
    if tem_tela and tem_ref:
        return True

    # erros/bugs com referência
    termos_problema = ("erro", "bug", "falha", "problema", "quebrou", "quebrada", "quebrado")
    if any(t in texto for t in termos_problema) and (tem_tela or tem_ref):
        return True

    if "linha" in texto and any(t in texto for t in ("erro", "codigo", "arquivo", "bloco", "trecho")):
        return True

    if "?" in mensagem and tem_tela:
        return True

    return False


def _mensagem_pede_pesquisa(mensagem: str) -> bool:
    texto = _normalizar_texto(mensagem)

    frases_explicitas = (
        "pesquise", "pesquisar", "pesquisa", "procure", "procurar",
        "busque", "buscar", "busca", "pesquisa na internet",
        "pesquise na internet", "procure na internet", "busque na internet",
        "pesquisa isso", "procura isso",
    )
    if any(f in texto for f in frases_explicitas):
        return True

    palavras_online = (
        "hoje", "agora", "atual", "atualmente", "noticia", "noticias",
        "preco", "precos", "cotacao", "cotacoes", "clima", "tempo em",
        "previsao do tempo", "ultimo", "ultimos", "ultimas", "link",
        "fontes", "fonte", "disponivel", "disponibilidade", "versao",
        "lançamento", "lancamento", "resultado", "ranking",
    )
    if "?" in mensagem and any(p in texto for p in palavras_online):
        return True

    return False


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
            max_tokens=2048,
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

def conversar_stream(mensagem_usuario, callback, fila_frases=None):
    global aguardando_resposta, memoria_atual

    historico.append({"role": "user", "content": mensagem_usuario})
    _limitar_historico()

    mensagem_final = mensagem_usuario
    contexto_memoria = mem_module.formatar_para_prompt(memoria_atual)
    system_com_memoria = system_prompt
    if contexto_memoria:
        system_com_memoria = system_prompt + "\n\n" + contexto_memoria

    resposta_completa = ""

    try:

        if precisa_ver_tela(mensagem_usuario):
            callback("Deixa eu dar uma olhada na sua tela...")
            imagem = visao.capturar_tela()
            resposta_completa = analisar_tela_com_pergunta(imagem, mensagem_usuario)

            if fila_frases:
                fila_frases.put(resposta_completa)
                fila_frases.put(None)

            historico.append({"role": "assistant", "content": resposta_completa})
            _limitar_historico()
            aguardando_resposta = resposta_completa.strip().endswith("?")
            return resposta_completa
            

        elif precisa_pesquisar(mensagem_usuario):
             callback("Abrindo o navegador...")
             resultado = pesquisa.pesquisar(mensagem_usuario)

             if fila_frases:
                 fila_frases.put(resultado)
                 fila_frases.put(None)

             historico.append({"role": "assistant", "content": resultado})
             _limitar_historico()
             aguardando_resposta = False
             return resultado

        mensagens = [{"role": "system", "content": system_com_memoria}] + historico[:-1] + [
            {"role": "user", "content": mensagem_final}
        ]

        stream = _chamar_llm(mensagens, model=OLLAMA_TEXT_MODEL, max_tokens=None, stream=True)

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
            max_tokens=1000,
        )
        return "SIM" in resposta.upper()
    except Exception:
        return False