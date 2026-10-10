"""
resto_call.py — o que ela faz com o que ouviu na call.

O escuta_call.py entrega turnos de fala transcritos. Este módulo decide três
coisas em cima deles, e cada uma resolve um jeito específico de a função dar
errado:

  1. QUANDO FALAR (o gatilho).
     Numa call com cinco ou seis pessoas, responder a tudo é insuportável e
     responder só a comando é robótico. O gatilho é um chamado pelo nome no
     TEXTO já transcrito — nunca reconhecimento acústico de palavra-chave. Detector
     acústico não tem contexto de frase: "família", "e mil", tosse e o próprio
     áudio do jogo disparam ele. O nome no texto transcrito vem junto com a
     frase inteira, e aí dá pra decidir se era com ela ou sobre ela.

  2. QUANDO CONTINUAR FALANDO (modo conversa).
     Obrigar a dizer "Emily" em cada frase transforma conversa em consulta a
     terminal. Depois que ela responde alguém, esse alguém fica com a linha
     aberta por um tempo e pode continuar falando sem repetir o nome. A linha é
     POR PESSOA, não pela call: aberta pra call inteira, ela responderia todo
     mundo por quarenta e cinco segundos, que é exatamente o "informação demais"
     que se quer evitar.

  3. QUANDO NÃO FALAR (anti-eco).
     Esse é o que mata a função sem avisar. A voz dela sai do fone de um amigo,
     entra no microfone dele, volta transcrita, e ela responde a si mesma. Duas
     ou três voltas e a call está num laço. O bot não escuta o próprio áudio
     direto (voice_recv só recebe pacote dos outros), então o vazamento é sempre
     pelo microfone de alguém — e por isso a defesa é dupla: janela de mudo
     enquanto ela fala, e comparação do texto com o que ela acabou de dizer.
     Só a janela não basta (alguém pode falar por cima dela de verdade, e essa
     fala não pode ser jogada fora), e só a similaridade não basta (a
     transcrição do eco vem imperfeita e pode não parecer com o original).

  4. QUANDO A CONVERSA DEIXA DE SER COM ELA (freio de conversa).
     O modo conversa abre a linha com quem ela acabou de responder, e a linha
     aberta fazia ela responder TUDO que a pessoa dissesse em seguida — incluindo
     conversa com os outros e comentário aleatório de jogo. O freio roda ANTES
     do modelo (é de graça e instantâneo) e só no modo conversa: uma fala que
     não emenda em nada no que ela acabou de dizer nem pede nada a ela é
     ignorada. Duas falas ignoradas em sequência fecham a linha (o mesmo
     mecanismo da recusa do modelo), e chamar o nome dela sempre passa.

  5. O "CALA A BOCA" EM VOZ ALTA.
     "Emily, fica quieta", "cala a boca" e afins voltam ela pro modo inicial:
     só falar quando chamarem pelo nome. A ferramenta ficar_quieta_na_call já
     fazia isso, mas dependia de o modelo reconhecer o pedido — e um pedido
     dito em voz alta merece resposta imediata e garantida. Aqui é uma checagem
     local, com regras que evitam o falso positivo pior (ela calando porque
     DUAS OUTRAS pessoas estavam zoando entre si).

Nada aqui importa discord_bot no topo, e é de propósito: o discord_bot importa
este módulo pra ligar a escuta, e import no topo dos dois lados fecha o ciclo.
"""

from __future__ import annotations

import os
import queue
import random
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Optional

import escuta_call


# ═════════════════════════════════════════════════════════════════
# AJUSTES
# ═════════════════════════════════════════════════════════════════

def _num(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, padrao))
    except (TypeError, ValueError):
        return padrao


# Quanto tempo a linha fica aberta com quem ela acabou de responder. Quarenta e
# cinco segundos é o tempo de uma pessoa ouvir a resposta, pensar e emendar a
# próxima frase, sem ficar aberta tanto tempo que ela entre numa conversa que
# já mudou de assunto.
JANELA_CONVERSA = _num("EMILY_CALL_CONVERSA_SEG", 45.0)

# Sobra de mudo depois que o áudio dela termina. Existe porque o eco chega
# atrasado: sai da caixa, entra no microfone, e o turno só fecha depois do
# silêncio de 700 ms do escuta_call.
RABO_MUDO = _num("EMILY_CALL_RABO_MUDO", 1.5)

# Acima disso, uma fala dentro da janela de mudo é considerada eco da fala dela.
# Não é 0.9: a transcrição do eco vem degradada, com palavra faltando e
# pontuação diferente. Não é 0.5: aí frase curta de assunto parecido ("é isso
# mesmo") seria confundida com eco.
LIMIAR_ECO = _num("EMILY_CALL_LIMIAR_ECO", 0.68)

# Falas mais curtas que isso não passam pelo teste de similaridade — "sim",
# "não", "é" batem com qualquer coisa. Dentro da janela de mudo elas são
# descartadas direto, porque fala de uma palavra em cima dela quase nunca é
# fala de verdade.
MIN_PALAVRAS_ECO = int(_num("EMILY_CALL_MIN_PALAVRAS_ECO", 3))

# Quantas respostas podem estar esperando.
#
# Era 2, com o raciocínio de que fila maior faria ela responder coisa velha. O
# raciocínio estava certo e a solução estava errada: com o caminho de ferramenta,
# uma resposta leva alguns segundos, e duas vagas estouram fácil numa conversa
# animada. O log mostrou "fila cheia, deixei passar a fala de hiucksam" — ou
# seja, ele falou COM ela e foi ignorado, que é o pior resultado possível.
#
# Agora a fila é maior e o que protege contra resposta velha é a IDADE, conferida
# na hora de responder (IDADE_MAXIMA_FILA). Descartar por tempo é preciso;
# descartar por falta de vaga descarta o que chegou por último, que é justamente
# o mais recente.
MAX_FILA = int(_num("EMILY_CALL_MAX_FILA", 6))

# Fala que ficou esperando mais que isso não é respondida: o assunto já passou e
# responder agora soa como alguém acordando no meio da conversa.
IDADE_MAXIMA_FILA = _num("EMILY_CALL_IDADE_MAXIMA", 30.0)

# ── LOTE DE FALA (o conserto do "engasgo") ──────────────────────────
#
# Antes, CADA turno de fala que disparava o gatilho virava uma resposta na
# hora. Numa call movimentada isso empilhava: três pessoas falam em cima uma da
# outra, cada frase vira uma chamada de LLM, e a Emily respondia uma por uma com
# atraso crescente — o "engasgo" que o Vitor descreveu.
#
# A ideia: quando alguém dispara o gatilho, NÃO responde na hora. Junta as falas
# por uma janela curta de silêncio e responde UMA vez ao conjunto. É o "ouvir
# uns segundos e depois processar" — com dois freios pra não virar delay:
#
#   JANELA — silêncio que fecha o lote. Cada fala nova reinicia a contagem, então
#            enquanto o povo fala ela espera; quando dá uma pausa, ela responde.
#   TETO   — tempo máximo acumulando, mesmo que ninguém pare de falar. Sem isso,
#            uma pessoa falando sem parar seria respondida só quando calasse.
#
# A espera agora depende do tipo de fala. Uma pergunta direta já completa pode
# seguir cedo; um simples "Emily?" espera a pessoa completar; continuação de
# conversa fica no meio. O nome antigo continua servindo como fallback.
LOTE_JANELA = _num("EMILY_CALL_LOTE_JANELA", 1.0)
LOTE_JANELA_DIRETA = _num("EMILY_CALL_LOTE_DIRETO", 0.7)
LOTE_JANELA_CURTA = _num("EMILY_CALL_LOTE_CURTO", 1.3)
LOTE_JANELA_CONVERSA = _num("EMILY_CALL_LOTE_CONVERSA", 1.1)
LOTE_TETO = _num("EMILY_CALL_LOTE_TETO", 5.0)
INTERVALO_VIGIA_LOTE = _num("EMILY_CALL_LOTE_VIGIA", 0.05)

# Contexto efetivamente entregue ao modelo. A escuta guarda mais turnos do que
# isso; esta fatia limita custo e latência sem fazer a Emily esquecer o assunto
# depois de poucos segundos de conversa animada.
CONTEXTO_SEGUNDOS = _num("EMILY_CALL_CONTEXTO_SEGUNDOS", 600.0)
CONTEXTO_LINHAS = max(12, int(_num("EMILY_CALL_CONTEXTO_LINHAS", 40)))

# A call usa duas sínteses em paralelo, mas toca sempre na ordem. Isso permite
# uma resposta maior começar cedo sem abrir uma rajada agressiva contra a Fish.
TTS_PREFETCH_CALL = max(1, min(3, int(_num("EMILY_CALL_TTS_PREFETCH", 2))))

# Participação espontânea de baixa prioridade. Ela só é considerada depois de
# uma pausa real, com contexto de grupo, fila vazia e folga de cota. O sorteio é
# feito uma única vez por bloco de conversa, nunca a cada passagem do vigia.
INICIATIVA_ATIVA = os.getenv("EMILY_CALL_INICIATIVA", "1") not in (
    "0", "false", "nao")
INICIATIVA_COOLDOWN = _num("EMILY_CALL_INICIATIVA_COOLDOWN", 180.0)
INICIATIVA_MAX_HORA = max(0, int(_num("EMILY_CALL_INICIATIVA_MAX_HORA", 2)))
INICIATIVA_CHANCE = max(0.0, min(1.0, _num(
    "EMILY_CALL_INICIATIVA_CHANCE", 0.15)))
INICIATIVA_MIN_TURNOS = max(2, int(_num(
    "EMILY_CALL_INICIATIVA_MIN_TURNOS", 4)))
INICIATIVA_PAUSA = _num("EMILY_CALL_INICIATIVA_PAUSA", 4.0)
INICIATIVA_CONTEXTO_SEG = _num("EMILY_CALL_INICIATIVA_CONTEXTO_SEG", 150.0)

# ── FREIO DE CONVERSA (o "isso emenda no que eu acabei de falar?") ──────
#
# A linha de conversa aberta (JANELA_CONVERSA) fazia ela responder TUDO que
# vinha em seguida de quem ela tinha acabado de responder. Em call de grupo,
# a pessoa emenda a conversa com os outros e ela ia junto, respondendo coisas
# que não eram com ela.
#
# O freio roda no _responder, ANTES de qualquer custo (nem sinal de "ouvi",
# nem chamada de modelo), e SÓ no modo conversa — chamada pelo nome nunca
# passa por ele, que é o caso que sempre funcionou bem.
#
# Ele é intencionalmente conservador: só barra a fala que não tem MARCA de
# continuação nenhuma (nem pergunta de volta, nem resposta curta de diálogo,
# nem palavra de conteúdo em comum com a conversa recente). Marcar a fala como
# não-emenda incrementa calou_seguidas — o MESMO contador da recusa do modelo,
# então duas falas barradas em seguida fecham a linha e ela volta pro modo de
# só responder ao nome. O custo de barrar errado é baixo e recuperável (a
# pessoa chama pelo nome); o custo de não barrar é exatamente o comportamento
# que se quer consertar.
GATE_CONVERSA = os.getenv("EMILY_CALL_GATE_CONVERSA", "1") not in ("0", "false", "nao")

# Fração das palavras de conteúdo da fala que precisam aparecer na última
# fala DELA pra considerar a fala "emendada" com o que ela disse.
GATE_LIMIAR_PARECIDO = _num("EMILY_CALL_GATE_PARECIDO", 0.34)

# Fração das palavras de conteúdo da fala que precisam aparecer na conversa
# recente pra ela considerar a fala relacionada.
GATE_LIMIAR_SOLAPAMENTO = _num("EMILY_CALL_GATE_SOLAPAMENTO", 0.5)


# Sinal imediato de "te ouvi" — um "oi?" curto antes da resposta de verdade.
#
# DESLIGADO por padrão, e a razão é uso real. A ideia era tapar o buraco de
# alguns segundos entre a pergunta e a resposta. Na call ficou insuportável:
#
#   1. O sinal saía ANTES do modelo decidir se ia responder. Quando ele decidia
#      que a fala não era com ela, o que sobrava era um "oi?" solto respondendo
#      a nada.
#   2. Saía também em modo conversa, ou seja, em TODA frase de quem estava com
#      a linha aberta. Numa conversa de cinco frases, cinco "hum?" a mais.
#
# O código fica, e agora só dispara quando alguém chama o nome dela — nunca em
# continuação de conversa. Pra ligar: EMILY_CALL_SINAL=1.
SINAL_DE_OUVI = os.getenv("EMILY_CALL_SINAL", "0") not in ("0", "false", "nao")

ATIVO = os.getenv("EMILY_RESPONDER_CALL", "1") not in ("0", "false", "nao")


# ═════════════════════════════════════════════════════════════════
# O NOME DELA, COMO O WHISPER OUVE
# ═════════════════════════════════════════════════════════════════
#
# "Emily" numa call brasileira, com microfone ruim e jogo ao fundo, não chega
# escrito "Emily". Chega "Emilly", "Emili", "Emile", às vezes partido em duas
# palavras ("e mily"). A lista abaixo é de variantes INTEIRAS, de propósito:
# procurar só o pedaço "emil" pegaria "e milhões" com o espaço removido.

_VARIANTES = [
    "emily", "emilly", "emyly", "emili", "emilli", "emilie", "emilee",
    "emely", "emelly", "emeli", "emile", "emilê", "emiliy", "emiy",
    "emmily", "emmy", "emy", "emi",
]

# O nome dela partido em duas palavras ("e mily", "emi ly") só aparece se a
# busca for feita no texto sem espaço nenhum. E aí some a fronteira de palavra,
# que é justamente o que protege contra falso positivo — então essa segunda
# lista é bem mais curta que a primeira, e escolhida a dedo.
#
# Duas variantes saíram daqui por medirem falso positivo em fala normal:
#   "emile" casa em "custou E MIL E duzentos reais" -> "custouEMILEduzentos"
#   "emili" casa em "isso é de E MILIonário"        -> "issoedeEMILIonario"
# Preço de dinheiro e "milhão" aparecem toda hora numa call de Minecraft, e
# disparar o nome dela nisso é o falso positivo clássico.
#
# O que sobrou tem "y" ou "ly", que não se forma emendando palavra portuguesa.
_VARIANTES_JUNTAS = [
    "emily", "emilly", "emyly", "emmily", "emiliy",
    "emilie", "emilee", "emelly", "emely",
]


def _normalizar(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação. Só pra comparar."""
    t = unicodedata.normalize("NFD", (texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Os padrões são montados a partir das variantes JÁ NORMALIZADAS. Sem isso,
# "emilê" nunca casaria: a variante tem acento e o texto comparado não.
_RE_NOME = re.compile(
    r"\b(?:" + "|".join(sorted((_normalizar(v) for v in _VARIANTES),
                               key=len, reverse=True)) + r")\b"
)
_NOMES_NORMALIZADOS = frozenset(_normalizar(v) for v in _VARIANTES)
_NOMES_JUNTOS = frozenset(_normalizar(v) for v in _VARIANTES_JUNTAS)


def _posicoes_nome(texto: str) -> list[tuple[int, int]]:
    """Encontra variantes inteiras, inclusive erro leve do STT e nome partido."""
    palavras = _normalizar(texto).split()
    posicoes = []
    for i, palavra in enumerate(palavras):
        # Similaridade só com o nome canônico e limiar alto. Não aproxima
        # palavras comuns como "email", "família", "Emília" ou "Emílio".
        aproximado = (4 <= len(palavra) <= 7
                       and palavra not in {"email", "emilia", "emilio"}
                       and SequenceMatcher(None, palavra, "emily").ratio() >= 0.88)
        if palavra in _NOMES_NORMALIZADOS or aproximado:
            posicoes.append((i, i + 1))
        elif i + 1 < len(palavras):
            junto = palavra + palavras[i + 1]
            if junto in _NOMES_JUNTOS:
                posicoes.append((i, i + 2))
    return posicoes


def chamaram_ela(texto: str) -> bool:
    """O nome dela foi mencionado, mesmo que a fala seja sobre ela?"""
    return bool(_posicoes_nome(texto))


def chamada_direta(texto: str) -> bool:
    """Aceita vocativos; barra menções claramente em terceira pessoa."""
    palavras = _normalizar(texto).split()
    for inicio, fim in _posicoes_nome(texto):
        antes = palavras[inicio - 1] if inicio else ""
        depois = palavras[fim:]
        if antes in {"a", "o", "da", "do", "de", "na", "no", "pela",
                     "pelo", "sobre", "pra", "para", "com", "essa", "esse",
                     "minha", "nossa", "aquela", "aquele"}:
            continue
        # No início, "Emily entrou" e "Emily é incrível" são relatos sobre
        # ela. "Emily, você..." ou "Emily tá me ouvindo?" continuam chamadas.
        padrao_vocativo = (r"^\s*[\wÀ-ÿ]+\s+[\wÀ-ÿ]+\s*[,!?]"
                           if fim == 2 else r"^\s*[\wÀ-ÿ]+\s*[,!?]")
        inicio_vocativo = (inicio == 0 and bool(re.match(
            padrao_vocativo, texto)))
        if not inicio_vocativo and inicio == 0 and depois and depois[0] in {
            "entrou", "saiu", "falou", "disse", "fez", "jogou", "respondeu",
            "e", "eh", "esta", "estava", "ta", "tava",
        } and not any(p in {"voce", "tu", "ce", "me", "mim", "comigo", "ai"}
                      for p in depois):
            continue
        return True
    return False


def remover_vocativo_inicial(texto: str) -> str:
    """Retira só o chamado inicial para classificar o pedido pelo conteúdo."""
    if not chamada_direta(texto):
        return texto
    palavras = _normalizar(texto).split()
    for inicio, fim in _posicoes_nome(texto):
        if inicio == 0 or (inicio == 1 and palavras[0] in {
                "ei", "oi", "alo", "hey", "fala"}):
            return " ".join(palavras[fim:])
    return texto


def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalizar(a), _normalizar(b)).ratio()


# Palavras que não dizem nada sobre ASSUNTO. Existem pro freio de conversa
# olhar só conteúdo: sem isso, "cara, tipo, a gente tem que ver isso" casaria
# com qualquer coisa, porque "cara", "tipo" e "gente" estão em toda fala.
# Vocabulário de call de jogo em português, mantido curto de propósito — o que
# falta aqui é compensado pelo solapamento só contar palavra de 3+ letras.
_STOPWORDS = frozenset((
    "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "em", "no", "na", "nos", "nas", "por", "para", "pra", "pro", "com",
    "sem", "que", "qual", "quais", "quem", "quando", "onde", "como", "porque",
    "pois", "mas", "ou", "e", "nem", "se", "entao", "aí", "ai", "assim",
    "tambem", "também", "ja", "já", "so", "só", "muito", "muita", "pouco",
    "pouca", "mais", "menos", "bem", "tá", "ta", "tao", "tão", "ae", "aqui",
    "ali", "la", "lá", "agora", "hoje", "ontem", "amanhã", "amanha", "cara",
    "mano", "vei", "tipo", "gente", "pessoal", "kkk", "kkkk", "haha", "hehe",
    "rs", "opa", "eita", "quase", "coisa", "coisas", "acho", "achei",
    "talvez", "vamo", "vamos", "vou", "vai", "vao", "vão", "to", "tô",
    "tou", "estou", "esta", "está", "tava", "estava", "ser", "sou", "somos",
    "era", "fui", "tem", "tenho", "tinha", "ter", "ok", "blz", "beleza",
    "certo", "verdade", "sim", "nao", "não", "kk", "hum", "aha", "hmm", "hm",
    "ele", "ela", "eles", "elas", "isso", "isto", "esse", "essa", "meu",
    "minha", "seu", "sua", "teu", "tua", "nosso", "nossa", "dele", "dela",
    "eu", "tu", "voce", "você", "voces", "vocês", "vc", "vcs", "mim", "nós",
    "nos", "me", "te", "lhe", "ne", "né", "nada", "tudo", "todo", "toda",
    "todos", "todas", "outro", "outra", "sobre", "entre", "pela", "pelo",
))


def _palavras_de_conteudo(texto: str) -> list:
    """Palavras do texto que valem pra comparação de assunto."""
    return [p for p in _normalizar(texto).split()
            if len(p) >= 3 and p not in _STOPWORDS]


# Expressões de "cala a boca". A lista inteira é buscada sobre o texto
# NORMALIZADO, então não precisa de variante com acento.
_EXPRESSOES_SILENCIO = (
    "cala a boca", "cala boca", "cala essa boca", "cala a boquinha",
    "fecha a boca", "fica quieta", "fique quieta", "fica calada",
    "fica em silencio", "fica de boca fechada", "para de falar",
    "para de responder", "nao responde mais", "não responde mais",
    "para de se meter", "chega de falar", "chega de responder",
    "permanece em silencio", "silencio absoluto", "modo silencio",
    "modo calada", "entra no modo silencio",
)

# Palavras soltas que, com o NOME dela na frase, bastam ("Emily, silêncio!").
_GATILHOS_SOLTOS_SILENCIO = ("cala", "calada", "calado", "quieta", "quieto",
                             "silencio", "silêncio", "silencia", "shhh",
                             "shh", "chega")


def _comando_de_silencio(texto: str) -> bool:
    """
    Alguém pediu, EM VOZ ALTA, que a Emily fique em silêncio?

    É o "cala boca" da call: "Emily, fica quieta", "cala a boca", "silêncio",
    "para de falar". LOCAL e determinístico de propósito — um pedido desses
    dito em voz alta precisa ser obedecido na hora, sem depender de o modelo
    reconhecer e escolher a ferramenta (o passo que ele às vezes pula).

    DUAS camadas, pra equilibrar os dois erros possíveis:

      - Com o nome dela: qualquer expressão da lista, ou palavra solta do
        conjunto de gatilhos, vale. Quem fala "Emily, silêncio!" está falando
        COM ela por definição — e o único jeito de responder a isso é calar.
      - SEM o nome: só aceita se a frase for praticamente SÓ o pedido ("cala a
        boca" seco, "só silêncio agora"). Aí o máximo é 5 palavras. Evita o
        falso positivo pior: duas pessoas zoando entre si ("cala a boca aí e
        vai jogar") não podem silenciá-la — mandar ela calar sem ninguém ter
        falado com ela era exatamente o defeito que criou o laço antigo.
    """
    limpo = _normalizar(texto)
    if not limpo:
        return False

    palavras = limpo.split()
    if len(palavras) > 6:
        return False

    mencionou = chamaram_ela(texto)
    chamou = chamada_direta(texto)
    if mencionou and not chamou:
        return False

    # Com o nome dela: expressão inteira OU palavra solta COLADA ao nome
    # ("emily quieta", "silêncio emily"). COLADA, e não em qualquer lugar da
    # frase: "a emily tá quieta" é alguém FALANDO DELA, não mandando ela
    # calar — e era justamente esse tipo de frase que alimentava o laço do
    # "fico quieta" que a call já conhece.
    if chamou:
        if any(e in limpo for e in _EXPRESSOES_SILENCIO):
            return True
        nomes = ("emily", "emilly", "emyly", "emili", "emilee", "emely",
                 "emelly", "emeli", "emile", "emiliy", "emiy", "emmily",
                 "emmy", "emy", "emi")
        for i, p in enumerate(palavras):
            if p not in _GATILHOS_SOLTOS_SILENCIO:
                continue
            esq = palavras[i - 1] if i > 0 else ""
            direita = palavras[i + 1] if i + 1 < len(palavras) else ""
            if esq in nomes or direita in nomes:
                return True
        return False

    # Sem o nome: a frase tem que SER o pedido, quase nada além dele.
    if len(palavras) > 5:
        return False
    sem_preenchimento = [p for p in palavras
                         if p not in ("emily", "emilly", "emyly", "emili",
                                      "emy", "emi", "por", "favor", "pfv",
                                      "pf", "ai", "aí", "vae", "vai", "tá",
                                      "ta", "so", "só", "agora", "eh", "é",
                                      "ei", "oie", "oi", "ne", "né", "mano",
                                      "cara", "gente", "pessoal", "em",
                                      "modo", "o", "a", "ela", "de")]
    if not sem_preenchimento:
        return False
    if len(sem_preenchimento) > 3:
        return False
    # Grito seco de uma palavra: "SILÊNCIO!", "CALA!". Só quando a fala
    # inteira é isso (preenchimento à parte) — "silêncio" no meio de uma
    # frase qualquer não pode calar ninguém.
    if (len(sem_preenchimento) == 1
            and sem_preenchimento[0] in ("cala", "silencio")):
        return True
    return any(e in limpo for e in _EXPRESSOES_SILENCIO)


def _faz_sentido_com_a_conversa(turno, modo_conversa: bool) -> bool:
    """
    A fala emenda no que ela acabou de dizer? (RACIOCÍNIO ANTES DO MODELO)

    Só consultada no modo conversa — a linha aberta com quem ela respondeu há
    pouco. O problema: a linha aberta não é uma promessa de conversa, é uma
    APOSTA. Se a pessoa emendou papo com os outros ou comentou algo do jogo,
    responder seria exatamente o "ela fica se metendo" que incomoda.

    Devolve True (deixa passar) quando a fala tem QUALQUER uma destas marcas:

      1. É pergunta — com a linha aberta, quase toda pergunta é pra ela.
      2. É resposta curta de diálogo — "sim", "entendi", "boa", "é mesmo".
      3. É continuação por marcador — começa com "e", "mas", "porque"...
      4. Parece com o que ela acabou de dizer ("não, tipo, aquilo mesmo").
      5. Compartilha assunto com a conversa recente — metade ou mais das
         palavras de conteúdo da fala aparecem na transcrição recente, que
         JÁ CONTÉM a resposta dela (escuta_call.registrar_fala_dela).

    Sem marca nenhuma, devolve False: provavelmente conversa com outra
    pessoa. Não é decisão definitiva — quem decide se era com ela, no fim,
    continua sendo o modelo; isto aqui é o filtro de graça que evita gastar
    uma chamada de modelo (e paciência da call) em fala sem chance nenhuma.

    Chamada pelo nome NUNCA passa daqui: quem chama o nome quer falar com ela.
    """
    if not modo_conversa:
        return True

    texto = turno.texto or ""
    limpo = _normalizar(texto)
    if not limpo:
        return True

    # Chamou o nome dela: queres falar COM ela, ponto. O gatilho de nome já
    # teria classificado isso como chamada direta; a checagem aqui é a
    # segunda camada (o lote fundido pode trazer o nome numa linha).
    if chamada_direta(texto):
        return True

    # 1. Pergunta: marcador de continuidade mais forte que existe.
    if "?" in texto:
        return True
    interrogativos = ("o que", "oque", "que que", "quem", "quando", "onde",
                      "por que", "porque", "por quê", "pra que", "para que",
                      "como", "quanto", "qual", "quais", "voce", "você",
                      "vc", "tu", "sabe", "ne", "né", "viu", "certo")
    if any(limpo.startswith(i) for i in interrogativos):
        return True
    # "e você?", "e tu acha?", "e vc viu?"...
    if limpo.startswith(("e voce", "e você", "e vc", "e tu")):
        return True

    palavras = limpo.split()

    # 2. Resposta curta de diálogo: turno que só existe dentro de conversa.
    if len(palavras) <= 3:
        curtas = ("sim", "nao", "não", "ok", "blz", "beleza", "entendi",
                  "boa", "bom", "legal", "kkk", "kkkk", "kk", "rs", "haha",
                  "verdade", "mesmo", "é", "eh", "hum", "humm", "aham",
                  "aha", "pera", "peraí", "fala", "diz", "então", "entao",
                  "mostra", "manda", "vamo", "top", "demais", "sério",
                  "serio", "quero", "faz", "tenta", "po", "poxa", "uhum",
                  "mano", "juro", "eu", "acho", "sei")
        if all(p in curtas or len(p) <= 3 for p in palavras):
            return True

    # 3. Marcador de continuação: a frase emenda em discurso, não abre um.
    #    ("olha", "cara", "tipo" e "sabe" ficaram FORA de propósito: eles
    #    abrem tanto conversa com ela quanto conversa aleatória de jogo, e
    #    "olha o creeper ali" é exatamente o tipo de fala que se quer barrar.)
    conectores = ("e ", "mas ", "porque ", "pq ", "entao ", "então ",
                  "por isso ", "ai ", "aí ", "na real ", "na verdade ",
                  "na vdd ", "alias ", "aliás ", "inclusive ", "afinal ",
                  "ou seja ", "porém ", "porem ")
    if any(limpo.startswith(c) for c in conectores):
        return True

    conteudo = _palavras_de_conteudo(texto)

    # 4. Assunto em comum com o que ELA acabou de dizer ("não, o servidor
    #    que você falou"). Comparação por PALAVRA DE CONTEÚDO, não por
    #    SequenceMatcher de caracteres: duas frases médias em português
    #    qualquer batem 0,3~0,5 de ratio de caractere, e com limiar baixo a
    #    regra deixava passar fala aleatória (medido no teste). Palavra de
    #    conteúdo compartilhada é sinal de assunto, letra em comum não é.
    with _trava:
        ultima_dela = _est.ultima_fala_dela or ""
    if ultima_dela and conteudo:
        dela = _palavras_de_conteudo(ultima_dela)
        if dela:
            comuns = sum(1 for p in conteudo if p in set(dela))
            if comuns / len(conteudo) >= GATE_LIMIAR_PARECIDO:
                return True

    # 5. Assunto compartilhado com a conversa recente (a transcrição já tem
    #    as falas dela registradas, então "assunto da conversa" inclui o que
    #    ELA acabou de dizer).
    if conteudo:
        recente = escuta_call.transcricao_recente(segundos=90.0, limite=12)
        if recente:
            alvo = set(_normalizar(recente).split())
            tocadas = sum(1 for p in conteudo if p in alvo)
            if tocadas / len(conteudo) >= GATE_LIMIAR_SOLAPAMENTO:
                return True

    # Sem marca nenhuma de continuação: provavelmente conversa com os outros.
    return False


# ═════════════════════════════════════════════════════════════════
# ESTADO
# ═════════════════════════════════════════════════════════════════

@dataclass
class _Estado:
    ligado: bool = False
    # "Fica quieta" pediu silêncio, não surdez. Estado SEPARADO do `ligado` de
    # propósito, e a separação é o conserto de um defeito de uso real:
    #
    # antes, mandar ela ficar quieta desligava o módulo inteiro, e nada além de
    # sair e voltar pra call a trazia de volta. O Vitor mandou ela calar, depois
    # chamou "Emily, cê tá aí?" — a fala aparecia no terminal e ela ignorava,
    # pra sempre. Uma pessoa mandada calar não fica surda: ela para de se metar
    # na conversa, mas responde se você falar com ela de novo.
    #
    # Então, calada: o modo conversa não dispara (é ele que faz ela se meter), e
    # chamar o nome dela ainda dispara. Se ela decidir que a fala era com ela, o
    # silêncio acaba ali.
    silenciada: bool = False

    # Quantas vezes o silenciar() foi chamado. Incrementa SEMPRE, mesmo quando
    # ela já estava calada.
    #
    # Isso existe pra responder uma pergunta que o estado sozinho não responde:
    # "neste turno, ela executou a ferramenta de ficar quieta?". Sem saber isso,
    # os dois casos abaixo são indistinguíveis, porque em ambos silenciada
    # continua True do começo ao fim do turno:
    #   1. estava calada e respondeu normalmente  -> tem que voltar a falar
    #   2. estava calada e mandaram calar de novo -> tem que continuar calada
    #
    # É CONTADOR e não instante de tempo, e a diferença não é estilo. A primeira
    # versão guardava time.monotonic(), e o teste do laço falhou por causa disso:
    # no Windows o monotonic() tem resolução perto de 15 ms, então duas chamadas
    # próximas devolvem o MESMO valor, a marca não muda, e o código conclui que a
    # ferramenta não rodou. Numa call de verdade as falas são separadas por
    # segundos e o defeito não apareceria — ficaria escondido esperando o dia em
    # que duas falas chegassem juntas. Contador não tem resolução pra perder.
    silenciada_seq: int = 0

    # user_id -> quantas vezes seguidas ela decidiu não responder essa pessoa
    # estando com a linha de conversa aberta. Ver o uso no _responder.
    calou_seguidas: dict = field(default_factory=dict)
    # user_id -> instante (monotonic) em que a linha aberta com essa pessoa
    # expira.
    conversa: dict = field(default_factory=dict)
    # Até quando qualquer fala é suspeita de ser eco.
    mudo_ate: float = 0.0
    falando: bool = False
    ultima_fala_dela: str = ""
    ultima_resposta_em: float = 0.0

    # Contadores. "Ela não respondeu" é a reclamação que vai aparecer, e sem
    # esses números não tem como saber se o turno nem chegou, se o gatilho não
    # pegou, se o modelo decidiu não responder ou se o TTS falhou.
    ouvidos: int = 0
    gatilho_nome: int = 0
    gatilho_conversa: int = 0
    descartados_eco: int = 0
    descartados_fila: int = 0
    modelo_calou: int = 0
    respondidas: int = 0
    erros: int = 0
    ultimo_erro: str = ""

    # Falas barradas pelo freio de conversa (não emendavam com o que ela
    # acabou de dizer) e pedidos de silêncio cumpridos em voz alta.
    conversa_barradas: int = 0
    silencio_voz: int = 0
    espontaneas: int = 0


_est = _Estado()
_trava = threading.Lock()
_fila: "queue.Queue[tuple]" = queue.Queue(maxsize=MAX_FILA)
_thread: Optional[threading.Thread] = None
_parar = threading.Event()

# ── Estado do LOTE de fala ──────────────────────────────────────────
# As falas que dispararam o gatilho ficam AQUI acumulando, em vez de virar
# resposta na hora. O vigia (_vigiar_lote) fecha o lote quando dá uma pausa
# (LOTE_JANELA) ou quando o teto de tempo estoura (LOTE_TETO), e só então uma
# resposta única é enfileirada. É isto que tira o engasgo: várias frases
# faladas em sequência viram UMA ida ao modelo, não uma por frase.
_lote: list = []            # lista de (turno, modo_conversa)
_lote_primeiro: float = 0.0  # monotonic da primeira fala do lote (teto)
_lote_ultimo: float = 0.0    # monotonic da última fala do lote (janela)
_lote_trava = threading.Lock()
_thread_lote: Optional[threading.Thread] = None
_thread_iniciativa: Optional[threading.Thread] = None
_fala_trava = threading.Lock()

# Sequência muda a cada fala real. Uma iniciativa captura o número antes de
# pensar e confere de novo antes de tocar: se alguém falou nesse intervalo, a
# prioridade passou a ser da pessoa e o comentário é descartado.
_atividade_seq = 0
_ultima_atividade = 0.0
_iniciativa_avaliada_seq = -1
_iniciativas_hora: list[float] = []
_fala_local = threading.local()


class _TurnoLote:
    """
    Um 'turno' sintético que representa o lote inteiro de falas juntadas.

    Tem a mesma cara de um escuta_call.Turno no que o resto do módulo usa
    (user_id, nome, texto, inicio, fim), então passa por _responder e pelo
    worker sem tratamento especial.
    """
    __slots__ = ("user_id", "nome", "texto", "inicio", "fim",
                 "lote_espera", "enfileirado_em")

    def __init__(self, user_id, nome, texto, inicio, fim):
        self.user_id = user_id
        self.nome = nome
        self.texto = texto
        self.inicio = inicio
        self.fim = fim
        self.lote_espera = 0.0
        self.enfileirado_em = 0.0


# Injetados pelo discord_bot. Ficam aqui como função em vez de import porque
# este módulo precisa ser testável sem subir o bot inteiro.
_tocar_na_call: Optional[Callable[[bytes, int, int], bool]] = None
_tocar_stream_na_call: Optional[Callable] = None
_mandar_no_texto: Optional[Callable[[str], None]] = None
_quem_esta_na_call: Optional[Callable[[], str]] = None
_pensar: Optional[Callable] = None
_pensar_espontaneo: Optional[Callable] = None


def _log(msg: str) -> None:
    print(f"[Call] {msg}")


# ═════════════════════════════════════════════════════════════════
# LIGAÇÃO COM O MUNDO DE FORA
# ═════════════════════════════════════════════════════════════════

def definir_saidas(tocar=None, tocar_stream=None, mandar_texto=None,
                   quem_na_call=None, pensar=None,
                   pensar_espontaneo=None) -> None:
    """
    Diz a este módulo como falar na call, como escrever no chat e como pensar.

    tocar(pcm, taxa, canais) -> bool, e precisa BLOQUEAR até o áudio acabar. A
    janela de mudo do anti-eco depende de saber quando ela parou de falar; com
    uma função que retorna antes do fim, a janela fecharia no meio da fala e o
    eco entraria.

    tocar_stream(texto, cancelar_se=None) -> bool | None faz a mesma coisa, mas
    começa no primeiro chunk do TTS. ``None`` pede fallback para ``tocar``.

    pensar(user_id, nome, fala, transcricao, modo_conversa, quem_na_call) ->
    dict com "resposta" e "detalhe_texto". É o caminho COM ferramenta, que só o
    discord_bot consegue montar (ele tem o Member de verdade pra calcular
    permissão). Sem ele, cai no modelo.responder_na_call, que responde de
    cabeça e não executa nada — bom pra teste, ruim pra "o servidor tá on?".

    pensar_espontaneo(transcricao, quem_na_call) -> texto ou vazio. Esse caminho
    é separado justamente para nunca receber catálogo nem executar ferramenta.
    """
    global _tocar_na_call, _tocar_stream_na_call
    global _mandar_no_texto, _quem_esta_na_call, _pensar
    global _pensar_espontaneo
    if tocar is not None:
        _tocar_na_call = tocar
    if tocar_stream is not None:
        _tocar_stream_na_call = tocar_stream
    if mandar_texto is not None:
        _mandar_no_texto = mandar_texto
    if quem_na_call is not None:
        _quem_esta_na_call = quem_na_call
    if pensar is not None:
        _pensar = pensar
    if pensar_espontaneo is not None:
        _pensar_espontaneo = pensar_espontaneo


# ═════════════════════════════════════════════════════════════════
# O GATILHO
# ═════════════════════════════════════════════════════════════════

def _e_eco(turno) -> tuple[bool, str]:
    """Essa fala é a voz dela voltando pelo microfone de alguém?"""
    if turno.inicio >= _est.mudo_ate:
        return False, ""

    n_palavras = len(turno.texto.split())
    if n_palavras < MIN_PALAVRAS_ECO:
        return True, f"fala de {n_palavras} palavra(s) enquanto eu falava"

    if not _est.ultima_fala_dela:
        return False, ""

    razao = _parecido(turno.texto, _est.ultima_fala_dela)
    if razao >= LIMIAR_ECO:
        return True, f"{razao:.0%} parecida com o que eu acabei de falar"

    # Eco parcial: o microfone pegou só um trecho do que ela falou. A
    # similaridade da frase inteira fica baixa, mas o trecho aparece dentro da
    # fala dela quase igual.
    if n_palavras >= MIN_PALAVRAS_ECO:
        alvo = _normalizar(_est.ultima_fala_dela)
        pedaco = _normalizar(turno.texto)
        if pedaco and pedaco in alvo:
            return True, "trecho literal do que eu acabei de falar"

    return False, ""


def _obedecer_silencio(turno) -> None:
    """
    Cumpre o "cala a boca" dito em voz alta.

    silenciar() já faz o que o pedido quer: fecha as linhas de conversa, joga
    fora o lote e a fila de respostas pendentes, e deixa a escuta ligada — ela
    volta sozinho quando alguém chamar o nome dela e o modelo decidir que a
    fala é com ela. Exatamente o "modo do começo da call".

    A confirmação em voz alta sai só NA PRIMEIRA vez ("Já estou quieta." é o
    recado do silenciar() para os pedidos seguintes). Confirmar de novo quando
    já está quieta era o laço do "fico quieta" que a call já ouviu demais.

    A confirmação roda em thread própria porque ESTA função roda na thread de
    transcrição, que não pode esperar TTS e áudio tocarem — a mesma razão pela
    qual _ao_ouvir_turno só decide e o _trabalhar responde.
    """
    recado = silenciar()
    with _trava:
        _est.silencio_voz += 1
    _log(f"{turno.nome} pediu silêncio em voz alta; {recado}")
    if "Já estou quieta" in recado:
        return
    threading.Thread(target=_falar_na_call, args=("Tá bom, fico quieta.",),
                     name="call-cala-boca", daemon=True).start()


def _ao_ouvir_turno(turno) -> None:
    """
    Observador registrado no escuta_call. Roda na thread de transcrição.

    Tem que voltar rápido: essa thread é a que transcreve os outros turnos, e
    segurar ela aqui pra esperar o modelo e o TTS atrasaria tudo que vem
    depois. Então aqui só decide, e quem responde é outra thread.
    """
    global _atividade_seq, _ultima_atividade
    if not _est.ligado or not turno.texto:
        return

    # O "cala a boca" vem antes de TUDO, até antes do filtro de eco. Não é
    # resposta, é comando — e o momento mais comum de ele chegar é exatamente
    # ENQUANTO ela está falando (janela de mudo do anti-eco aberta), quando o
    # filtro de eco descartaria a fala como eco da própria voz dela. O custo
    # do teste é uma busca em texto normalizado: nada.
    if _comando_de_silencio(turno.texto):
        _obedecer_silencio(turno)
        return

    # Se a pessoa disse só "Emily" e completou a pergunta logo depois, a segunda
    # parte precisa entrar no mesmo lote mesmo antes de existir linha de conversa.
    # Sem isso o lote curto esperava, mas jogava fora justamente a continuação.
    with _lote_trava:
        continuacao_de_chamada = any(
            t.user_id == turno.user_id and not modo
            for t, modo in _lote
        )

    with _trava:
        _est.ouvidos += 1

        eco, motivo = _e_eco(turno)
        if eco:
            _est.descartados_eco += 1
            _log(f"descartei eco de {turno.nome} ({motivo}): {turno.texto[:60]}")
            return

        agora = time.monotonic()
        _atividade_seq += 1
        _ultima_atividade = agora

        # Limpa linhas vencidas antes de consultar, senão o dicionário cresce
        # com a call inteira.
        vencidas = [uid for uid, ate in _est.conversa.items() if ate <= agora]
        for uid in vencidas:
            _est.conversa.pop(uid, None)

        if chamada_direta(turno.texto):
            modo_conversa = False
            _est.gatilho_nome += 1
        elif _est.silenciada:
            # Calada, só nome vale. Continuação de conversa é justamente o que
            # ela foi mandada parar de fazer.
            return
        elif _est.conversa.get(turno.user_id, 0.0) > agora:
            modo_conversa = True
            _est.gatilho_conversa += 1
        elif continuacao_de_chamada:
            modo_conversa = True
            _est.gatilho_conversa += 1
        else:
            return

    # Em vez de enfileirar a resposta na hora, joga no LOTE. O vigia fecha o
    # lote depois de uma pausa e enfileira UMA resposta pro conjunto — é o que
    # tira o engasgo de responder frase por frase. Fora da _trava de propósito:
    # o lote tem trava própria e não precisa competir com a thread de escuta.
    _acumular_no_lote(turno, modo_conversa)

    _log(f"{'continuando com' if modo_conversa else 'chamada por'} "
         f"{turno.nome}: {turno.texto[:70]}")


# ═════════════════════════════════════════════════════════════════
# LOTE DE FALA — junta falas próximas em UMA resposta
# ═════════════════════════════════════════════════════════════════

def _acumular_no_lote(turno, modo_conversa: bool) -> None:
    """Guarda a fala no lote em aberto e (re)marca os tempos de janela/teto."""
    global _lote_primeiro, _lote_ultimo
    agora = time.monotonic()
    with _lote_trava:
        if not _lote:
            _lote_primeiro = agora
        _lote_ultimo = agora
        _lote.append((turno, modo_conversa))


def _janela_do_lote(itens: list) -> float:
    """Espera adequada ao conteúdo atual do lote."""
    diretas = [t for t, modo in itens if not modo]
    if not diretas:
        return LOTE_JANELA_CONVERSA
    # Havendo continuação, a pessoa já completou o simples "Emily?".
    if len(itens) > 1:
        return LOTE_JANELA_DIRETA
    limpa = _RE_NOME.sub("", _normalizar(diretas[0].texto)).strip()
    if len(limpa.split()) <= 2:
        return LOTE_JANELA_CURTA
    return LOTE_JANELA_DIRETA


def _fechar_lote() -> None:
    """
    Junta o que estiver no lote numa fala só e enfileira UMA resposta.

    Como o lote é fundido:
      - o texto vira as falas em ordem, prefixadas por quem falou, pra o modelo
        entender uma conversa de várias pessoas em vez de uma frase solta;
      - se ALGUÉM no lote chamou o nome dela, o lote inteiro é tratado como
        chamada direta (modo_conversa=False), porque a intenção mais forte manda;
      - o autor/█user_id usado é o de quem chamou (ou o último que falou), que é
        pra quem a resposta e a linha de conversa vão.
    """
    with _lote_trava:
        if not _lote:
            return
        espera_lote = max(0.0, time.monotonic() - _lote_ultimo)
        itens = list(_lote)
        _lote.clear()

    # Uma pessoa só, uma fala só: não precisa fundir nada, responde o turno cru.
    if len(itens) == 1:
        turno, modo_conversa = itens[0]
        setattr(turno, "lote_espera", espera_lote)
        _enfileirar_resposta(turno, modo_conversa)
        return

    # Fusão. Preserva a ordem de chegada (que é a ordem em que falaram).
    chamada_direta = any(not mc for _, mc in itens)
    # Autor da resposta: prioriza quem chamou o nome dela; senão, o último.
    turno_alvo = next((t for t, mc in itens if not mc), itens[-1][0])

    linhas = []
    for t, _ in itens:
        linhas.append(f"{t.nome}: {t.texto}")
    texto_fundido = "\n".join(linhas)

    inicio = min(t.inicio for t, _ in itens)
    fim = max(t.fim for t, _ in itens)

    turno_lote = _TurnoLote(
        user_id=turno_alvo.user_id,
        nome=turno_alvo.nome,
        texto=texto_fundido,
        inicio=inicio,
        fim=fim,
    )
    turno_lote.lote_espera = espera_lote
    _log(f"lote de {len(itens)} falas fundido; respondendo uma vez "
         f"(chamada direta={chamada_direta})")
    _enfileirar_resposta(turno_lote, modo_conversa=not chamada_direta)


def _enfileirar_resposta(turno, modo_conversa: bool) -> None:
    """Coloca na fila de resposta, tratando fila cheia sem travar."""
    try:
        setattr(turno, "enfileirado_em", time.monotonic())
        print(f"[CALL-LATENCIA] lote="
              f"{getattr(turno, 'lote_espera', 0.0):.3f}s")
        _fila.put_nowait((turno, modo_conversa))
    except queue.Full:
        with _trava:
            _est.descartados_fila += 1
        _log(f"fila cheia, deixei passar a fala de {turno.nome}")


def _vigiar_lote() -> None:
    """
    Fecha o lote quando dá uma pausa (janela) ou quando o teto estoura.

    Roda numa thread própria, conferindo a cada 0,2s. Barato: só olha dois
    timestamps. É o "espera uns segundos e processa junto" que o Vitor pediu,
    com o teto garantindo que ninguém falando sem parar segure a resposta pra
    sempre.
    """
    while not _parar.is_set():
        if _parar.wait(INTERVALO_VIGIA_LOTE):
            return
        with _lote_trava:
            if not _lote:
                continue
            agora = time.monotonic()
            silencio = agora - _lote_ultimo
            acumulado = agora - _lote_primeiro
            janela = _janela_do_lote(_lote)
            fecha = silencio >= janela or acumulado >= LOTE_TETO
        if fecha:
            try:
                _fechar_lote()
            except Exception as e:
                with _trava:
                    _est.erros += 1
                    _est.ultimo_erro = f"lote: {type(e).__name__}: {e}"
                _log(f"falhei ao fechar o lote: {type(e).__name__}: {e}")



# ═════════════════════════════════════════════════════════════════
# A RESPOSTA
# ═════════════════════════════════════════════════════════════════

# Fillers de "te ouvi". Curtos de propósito: é um sinal, não uma resposta.
_FILLERS = ["oi?", "fala.", "que que é?", "hum?", "diz."]
_cache_filler: dict = {}


def _gerar_voz(texto: str) -> tuple[bytes, int, int]:
    """Texto -> PCM cru, com a taxa e os canais que o Fish devolveu."""
    import voz as voz_module
    pcm = voz_module.gerar_audio_bytes(texto, para_call=True)
    # voz.py guarda o formato real do WAV nessas globais ao gerar. Ler daqui em
    # vez de assumir 44100 evita o áudio sair em câmera lenta ou acelerado se o
    # Fish mudar de taxa.
    taxa = getattr(voz_module, "_audio_sample_rate", 44100)
    canais = getattr(voz_module, "_audio_channels", 1)
    return pcm, taxa, canais


def _gerar_voz_segmento(texto: str) -> tuple[bytes, int, int]:
    """Versão isolada por thread para o prefetch das respostas longas."""
    import voz as voz_module
    pcm, taxa, canais, _largura = voz_module.gerar_audio_pacote(
        texto, para_call=True)
    return pcm, taxa, canais


def _segmentos_de_fala(texto: str) -> list[str]:
    """Unidades naturais, sem transformar cada vírgula numa requisição Fish."""
    try:
        import voz as voz_module
        partes = voz_module.segmentar_para_tts(
            texto, preservar_entonacao=True)
        return partes or ([texto.strip()] if texto and texto.strip() else [])
    except Exception as e:
        _log(f"não consegui segmentar a fala ({type(e).__name__}: {e}); "
             "usando uma unidade")
        return [texto.strip()] if texto and texto.strip() else []


def _falar_na_call(texto: str, guardar_como_dela: bool = True,
                   cancelar_se=None) -> bool:
    """
    Gera a voz e toca na call, segurando a janela de mudo em volta.

    A ordem importa. O mudo abre ANTES de gerar o áudio, não antes de tocar: o
    Fish leva um tempo pra responder, e nesse intervalo o microfone de quem
    ainda está ouvindo a fala anterior continua abrindo turno.
    """
    _fala_local.reproduzida = ""
    if _tocar_na_call is None:
        _log("ninguém me disse como tocar na call (definir_saidas não foi "
             "chamado)")
        return False

    # Uma resposta direta pode chegar enquanto uma iniciativa está terminando.
    # A trava impede dois players simultâneos; a iniciativa confere cancelar_se
    # entre segmentos e libera a vez assim que percebe a nova atividade.
    _fala_trava.acquire()
    with _trava:
        ultima_anterior = _est.ultima_fala_dela
        _est.falando = True
        # Teto generoso enquanto gera e toca; o valor final é corrigido no fim.
        # Respostas maiores agora são permitidas, então 60s já não cobre todos
        # os casos. O finally sempre reduz para o rabo real ao terminar.
        _est.mudo_ate = time.monotonic() + 300.0
        if guardar_como_dela:
            import modelo as modelo_module
            _est.ultima_fala_dela = modelo_module.remover_tags_fish(texto)

    inicio_tts = time.monotonic()
    try:
        partes = _segmentos_de_fala(texto)
        if not partes:
            return False

        # Caminho normal em produção: o Fish alimenta o FFmpeg da call conforme
        # sintetiza. A decisão do LLM continua completa/segura, mas o TTS deixa
        # de esperar o arquivo inteiro. Em testes e instalações antigas esta
        # saída não é injetada e todo o bloco legado abaixo continua valendo.
        if _tocar_stream_na_call is not None:
            resultado_stream = _tocar_stream_na_call(
                texto, cancelar_se=cancelar_se)
            if resultado_stream is not None:
                ok = bool(resultado_stream)
                if ok:
                    import modelo as modelo_module
                    _fala_local.reproduzida = modelo_module.remover_tags_fish(texto)
                return ok

        # Resposta curta: mantém exatamente o caminho antigo, inclusive para os
        # testes e para reduzir overhead de executor.
        if len(partes) == 1:
            pcm, taxa, canais = _gerar_voz(partes[0])
            if not pcm:
                _log("o TTS voltou vazio")
                return False
            if cancelar_se is not None and cancelar_se():
                _log("fala espontânea cancelada: alguém voltou a falar")
                return False
            primeiro_tts = time.monotonic() - inicio_tts
            print(f"[CALL-LATENCIA] primeiro_tts={primeiro_tts:.3f}s "
                  f"primeira_voz={primeiro_tts:.3f}s segmentos=1")
            ok = bool(_tocar_na_call(pcm, taxa, canais))
            if ok:
                import modelo as modelo_module
                _fala_local.reproduzida = modelo_module.remover_tags_fish(partes[0])
            return ok

        tocou = 0
        partes_tocadas = []
        primeiro = True
        executor = ThreadPoolExecutor(max_workers=TTS_PREFETCH_CALL,
                                      thread_name_prefix="call-tts")
        futuros = {}
        proximo = 0
        try:
            # Janela deslizante: nunca deixa mais que o prefetch configurado em
            # voo. Se uma iniciativa for cancelada, o restante nem é enviado.
            while proximo < min(TTS_PREFETCH_CALL, len(partes)):
                futuros[proximo] = executor.submit(
                    _gerar_voz_segmento, partes[proximo])
                proximo += 1
            for posicao in range(len(partes)):
                futuro = futuros.pop(posicao)
                try:
                    pcm, taxa, canais = futuro.result()
                except Exception as e:
                    _log(f"segmento {posicao + 1}/{len(partes)} falhou: "
                         f"{type(e).__name__}: {e}")
                    pcm = b""
                if cancelar_se is not None and cancelar_se():
                    _log("fala espontânea cancelada antes do próximo segmento")
                    break
                if pcm and primeiro:
                    primeiro_tts = time.monotonic() - inicio_tts
                    print(f"[CALL-LATENCIA] primeiro_tts={primeiro_tts:.3f}s "
                          f"primeira_voz={primeiro_tts:.3f}s "
                          f"segmentos={len(partes)}")
                    primeiro = False
                if pcm and _tocar_na_call(pcm, taxa, canais):
                    tocou += 1
                    import modelo as modelo_module
                    partes_tocadas.append(
                        modelo_module.remover_tags_fish(partes[posicao]))
                elif not pcm:
                    _log(f"segmento {posicao + 1}/{len(partes)} voltou vazio")
                if proximo < len(partes):
                    futuros[proximo] = executor.submit(
                        _gerar_voz_segmento, partes[proximo])
                    proximo += 1
        finally:
            for futuro in futuros.values():
                futuro.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        _fala_local.reproduzida = " ".join(partes_tocadas).strip()
        if tocou != len(partes):
            _log(f"toquei {tocou}/{len(partes)} segmentos da resposta")
        return tocou > 0
    except Exception as e:
        with _trava:
            _est.erros += 1
            _est.ultimo_erro = f"fala: {type(e).__name__}: {e}"
        _log(f"erro ao falar: {type(e).__name__}: {e}")
        return False
    finally:
        with _trava:
            _est.falando = False
            _est.mudo_ate = time.monotonic() + RABO_MUDO
            if guardar_como_dela:
                reproduzida = getattr(_fala_local, "reproduzida", "")
                _est.ultima_fala_dela = reproduzida or ultima_anterior
        _fala_trava.release()


def _sinalizar_que_ouviu() -> None:
    """
    Um "oi?" imediato, pra pessoa saber que foi ouvida.

    O filler é gerado uma vez por sessão e guardado: se fosse gerado a cada
    chamada, o sinal chegaria junto com a resposta e não sinalizaria nada.

    Ele NÃO entra no ultima_fala_dela. Se entrasse, o anti-eco passaria a
    comparar as falas seguintes com "oi?" em vez de com a resposta de verdade,
    e o eco da resposta passaria batido.
    """
    if not SINAL_DE_OUVI:
        return
    import random
    texto = random.choice(_FILLERS)
    try:
        if texto not in _cache_filler:
            _cache_filler[texto] = _gerar_voz(texto)
        pcm, taxa, canais = _cache_filler[texto]
        if pcm and _tocar_na_call is not None:
            with _trava:
                _est.mudo_ate = max(_est.mudo_ate, time.monotonic() + 3.0)
            _tocar_na_call(pcm, taxa, canais)
    except Exception as e:
        # Sinal é conforto, não função. Falhar aqui não pode impedir a resposta.
        _log(f"não consegui sinalizar que ouvi: {type(e).__name__}: {e}")


class _PlanejadorFalaCall:
    """Fala incremental da call: abre o Discord no primeiro 'responder: true'
    do stream do LLM e escreve o PCM frase a frase enquanto o modelo ainda
    gera o resto da resposta.

    É o ganho de latência da call: em vez de esperar o JSON fechar (~3-5s no
    qwen), a primeira frase vai pro TTS assim que fecha no texto — o mesmo
    que a interface faz. Anti-eco idêntico ao _falar_na_call: a trava de fala
    e a janela de mudo abrem ANTES do primeiro áudio, e a janela cresce
    conforme os chunks entram (o handle do Discord estende o mudo sozinho).
    """

    def __init__(self, parar_se=None):
        self._fila = queue.Queue()
        self._thread = None
        self._handle = None
        self._frases = []
        self._tocou = False
        self._abriu = False
        self._segura_trava = False
        self._decidiu = False
        self._texto = ""
        self.ultima_anterior = ""
        self._parar_se = parar_se

    # -- callbacks chamados DURANTE o stream do LLM ----------------------

    def ao_decidir(self, responder: bool) -> None:
        self._decidiu = True
        if not responder:
            return
        # Trava e janela de mudo aqui, não antes: decisão false não segura
        # nada — paridade com o legado, que só toca o estado quando fala.
        _fala_trava.acquire()
        self._segura_trava = True
        with _trava:
            self.ultima_anterior = _est.ultima_fala_dela
            _est.falando = True
            _est.mudo_ate = time.monotonic() + 300.0
        try:
            import voz
            import discord_bot
            self._handle = discord_bot.abrir_stream_pcm_discord(
                voz._taxa_saida(), voz.CANAIS_PCM_FISH, "")
        except Exception as e:
            _log(f"stream de voz da call indisponível: {type(e).__name__}: {e}")
            self._handle = None
        self._abriu = True
        if self._handle is not None:
            self._thread = threading.Thread(
                target=self._tocar, daemon=True, name="call-voz-stream")
            self._thread.start()

    def ao_frase(self, frase: str) -> None:
        frase = (frase or "").strip()
        if not frase:
            return
        self._texto += (" " if self._texto else "") + frase
        if self._handle is not None:
            self._fila.put(frase)

    # -- player ------------------------------------------------------------

    def _tocar(self) -> None:
        import voz
        while True:
            item = self._fila.get()
            if item is None:
                return
            if self._parar_se is not None and self._parar_se():
                continue  # drena o resto sem tocar
            try:
                tocou_esta = False
                for pedaco in voz.gerar_audio_stream(item, para_call=True):
                    if not pedaco or self._handle is None:
                        continue
                    self._handle.escrever(pedaco)
                    if not tocou_esta:
                        tocou_esta = True
                        if not self._tocou:
                            self._tocou = True
                            print("[CALL-LATENCIA] primeira voz saindo "
                                  "durante o stream")
                        self._frases.append(item)
            except Exception as e:
                _log(f"frase do stream falhou: {type(e).__name__}: {e}")

    # -- ciclo de vida chamado pelo _responder ----------------------------

    def finalizar(self, guardar_como_dela: bool) -> bool:
        """Fecha o player, restaura anti-eco/trava e devolve se tocou."""
        try:
            if self._thread is not None:
                self._fila.put(None)
                self._thread.join(timeout=120)
            if self._handle is not None:
                self._handle.fechar(esperar=self._tocou)
            return bool(self._tocou)
        finally:
            reproduzida = " ".join(self._frases).strip()
            _fala_local.reproduzida = reproduzida
            if self._segura_trava:
                with _trava:
                    _est.falando = False
                    _est.mudo_ate = time.monotonic() + RABO_MUDO
                    if guardar_como_dela:
                        _est.ultima_fala_dela = (
                            reproduzida or self.ultima_anterior)
                _fala_trava.release()
                self._segura_trava = False

    @property
    def tocou(self) -> bool:
        return self._tocou

    @property
    def abriu(self) -> bool:
        return self._abriu


def _responder(turno, modo_conversa: bool) -> None:
    # A transcrição da call é o contexto, e desde o conserto do
    # escuta_call.registrar_fala_dela ela inclui as RESPOSTAS dela. Isso é o que
    # impede ela de ficar presa: lendo "Emily (você): tô vendo aqui" no meio,
    # o modelo sabe que aquela pergunta já foi tratada e trata a próxima.
    #
    transcricao = escuta_call.transcricao_recente(
        segundos=CONTEXTO_SEGUNDOS, limite=CONTEXTO_LINHAS)
    inicio_resposta = time.monotonic()

    # O freio do modo conversa vem antes de qualquer custo: nem sinal de
    # "ouvi", nem chamada de modelo. Uma fala sem NENHUMA marca de continuação
    # com o que ela acabou de dizer é provavelmente conversa com os outros —
    # e responder isso é o "ela fica se metendo" que o silenciar() existiu pra
    # consertar. Duas barradas seguidas fecham a linha (o MESMO contador de
    # recusas do modelo), e chamar o nome dela sempre reabre.
    if modo_conversa and GATE_CONVERSA:
        if not _faz_sentido_com_a_conversa(turno, modo_conversa):
            with _trava:
                _est.conversa_barradas += 1
                seguidas = _est.calou_seguidas.get(turno.user_id, 0) + 1
                _est.calou_seguidas[turno.user_id] = seguidas
                if seguidas >= 2:
                    _est.conversa.pop(turno.user_id, None)
                    _est.calou_seguidas.pop(turno.user_id, None)
                    _log(f"{turno.nome} voltou a falar com os outros; fechei a "
                         f"conversa com ele")
            _log(f"não respondi {turno.nome} (a fala não emenda com o que eu "
                 f"acabei de dizer): {turno.texto[:60]}")
            return

    quem = ""
    if _quem_esta_na_call is not None:
        try:
            quem = _quem_esta_na_call() or ""
        except Exception:
            quem = ""

    # Só em chamada pelo nome. Em modo conversa isso virava um "hum?" por frase.
    if not modo_conversa:
        _sinalizar_que_ouviu()

    with _trava:
        estava_calada = _est.silenciada
        marca_silencio = _est.silenciada_seq

    # STREAMING DA CALL: a fala começa na primeira frase do stream do LLM,
    # não no fechamento do JSON. O planejador só entra em ação com o _pensar
    # real do discord_bot (o caminho com ferramentas ignora os callbacks e
    # cai no legado sozinho); mocks de teste com outra assinatura também não
    # recebem nada, e o comportamento fica byte a byte o de antes.
    planejador = None
    if (os.getenv("EMILY_CALL_STREAM", "1").strip() != "0"
            and _tocar_na_call is not None):
        planejador = _PlanejadorFalaCall(
            parar_se=lambda: _est.silenciada_seq != marca_silencio)

    resultado = None
    inicio_llm = time.monotonic()
    if _pensar is not None:
        try:
            kwargs = {}
            if planejador is not None and getattr(
                    _pensar, "__name__", "") == "_pensar_na_call":
                kwargs = {"ao_decidir": planejador.ao_decidir,
                          "ao_frase": planejador.ao_frase}
            resultado = _pensar(
                user_id=turno.user_id,
                nome=turno.nome,
                fala=turno.texto,
                transcricao=transcricao,
                modo_conversa=modo_conversa,
                quem_na_call=quem,
                **kwargs,
            )
        except Exception as e:
            with _trava:
                _est.erros += 1
                _est.ultimo_erro = f"pensar: {type(e).__name__}: {e}"
            _log(f"o caminho com ferramenta falhou ({type(e).__name__}: {e}); "
                 f"respondendo de cabeça")

    if resultado is None:
        import modelo as modelo_module
        kwargs = {}
        if (planejador is not None and not planejador.abriu
                and getattr(
                    modelo_module.responder_na_call, "__name__", ""
                ) == "responder_na_call"):
            # Se o _pensar já tinha aberto o player antes de falhar, o
            # fallback roda SEM callbacks: a segunda resposta não pode
            # empilhar em cima da primeira no mesmo handle.
            kwargs = {"ao_decidir": planejador.ao_decidir,
                      "ao_frase": planejador.ao_frase}
        resultado = modelo_module.responder_na_call(
            transcricao=transcricao,
            ultima_fala=turno.texto,
            nome_autor=turno.nome,
            modo_conversa=modo_conversa,
            quem_esta_na_call=quem,
            **kwargs,
        )
    fim_llm = time.monotonic()
    print(
        "[CALL-LATENCIA] "
        f"fila={max(0.0, inicio_resposta - getattr(turno, 'enfileirado_em', turno.fim)):.3f}s "
        f"llm={fim_llm - inicio_llm:.3f}s"
    )

    # Mandaram ela calar NESTE turno? Só a marca de tempo responde isso — ver o
    # comentário do campo silenciada_em.
    with _trava:
        mandaram_calar = _est.silenciada_seq != marca_silencio

    fala = (resultado.get("resposta") or "").strip()

    # Fecha o planejador ANTES de qualquer decisão: o join dele espera o TTS
    # e o playback terminarem, então o 'ok' abaixo é definitivo. Sem isso, um
    # primeiro áudio ainda sintetizando faria o legado falar a resposta DE
    # NOVO em cima do stream (fala dupla).
    ok = False
    if planejador is not None:
        ok = planejador.finalizar(
            guardar_como_dela=bool(resultado.get("responder")) and bool(fala))
        planejador = None
        if ok:
            print(f"[CALL-LATENCIA] total_resposta="
                  f"{time.monotonic() - inicio_resposta:.3f}s")

    if not ok and (not resultado.get("responder") or not fala):
        with _trava:
            _est.modelo_calou += 1
            # Duas vezes seguidas decidindo que não era com ela, com a linha
            # aberta, significa que a pessoa voltou a falar com os outros. Fechar
            # a linha aí economiza chamada de modelo e, mais importante, reduz a
            # chance de ela se meter numa conversa que não é dela — que é
            # justamente onde ela pegou a ferramenta de ficar quieta sem ninguém
            # ter pedido.
            #
            # Duas e não uma: pular uma fala é normal (alguém tossiu, alguém
            # completou a frase do outro) e não quer dizer que a conversa com ela
            # acabou.
            if modo_conversa:
                seguidas = _est.calou_seguidas.get(turno.user_id, 0) + 1
                _est.calou_seguidas[turno.user_id] = seguidas
                if seguidas >= 2:
                    _est.conversa.pop(turno.user_id, None)
                    _est.calou_seguidas.pop(turno.user_id, None)
                    _log(f"{turno.nome} voltou a falar com os outros; fechei a "
                         f"conversa com ele")
        _log(f"decidi não responder {turno.nome} (não era comigo)")
        return

    # A ferramenta de ficar quieta rodou com ela JÁ quieta. Nesse caso ela não
    # fala nada, e isso é o conserto do defeito mais visível de todos:
    #
    # calada, ela continuava sendo disparada por quem falasse o nome dela; o
    # modelo pegava a ferramenta de ficar quieta de novo; e a confirmação "fico
    # quieta" saía no áudio. Pior: falar desfazia o silêncio, a linha de conversa
    # reabria, e o ciclo recomeçava na fala seguinte. O Vitor ouviu isso como ela
    # repetindo "fico quieta" sem parar.
    #
    # Confirmar uma vez é educado; confirmar de novo é a própria coisa que ela
    # foi mandada parar de fazer.
    if mandaram_calar and estava_calada:
        _log(f"já estava quieta e me mandaram calar de novo; não vou repetir "
             f"'{fala[:40]}' em voz alta")
        return

    if not ok:
        # Legado: stream desligado, handle indisponível, decisão que chegou
        # tarde ou nada tocou — o caminho antigo inteiro, sem mudança.
        _fala_local.reproduzida = ""
        ok = _falar_na_call(fala)
        print(f"[CALL-LATENCIA] total_resposta="
              f"{time.monotonic() - inicio_resposta:.3f}s")

    if ok:
        # Entra na transcrição só depois de ter saído no áudio de verdade. Se o
        # TTS falhou, ela não falou nada, e registrar aqui faria ela acreditar
        # que já respondeu — a pessoa repetiria a pergunta e seria ignorada.
        try:
            escuta_call.registrar_fala_dela(
                getattr(_fala_local, "reproduzida", "") or fala)
        except Exception as e:
            _log(f"não consegui registrar minha fala: {e}")

    with _trava:
        if ok:
            _est.respondidas += 1
            _est.ultima_resposta_em = time.monotonic()
        _est.calou_seguidas.pop(turno.user_id, None)

        # Estava calada e resolveu responder: o silêncio acaba aqui.
        #
        # Três condições, e cada uma tapa um buraco diferente:
        #
        # - ter RESPONDIDO, não ter sido chamada. O nome dela aparece em conversa
        #   que não é com ela ("a Emily tá quieta agora"); ali o modelo devolve
        #   NADA_A_DIZER e a função nem chega aqui. Falar DELA não desfaz o
        #   silêncio, falar COM ela desfaz.
        #
        # - `not mandaram_calar`. Sem isso, a confirmação "fico quieta" desfazia
        #   o silêncio que ela tinha acabado de ligar — a resposta anulando o
        #   próprio comando. Era metade do laço que o Vitor ouviu.
        if _est.silenciada and not mandaram_calar:
            _est.silenciada = False
            _log(f"{turno.nome} falou comigo direto, então voltei a responder")

        # A linha de conversa NÃO abre quando o pedido foi pra ela calar. Abrir
        # ali seria deixar ela pronta pra responder a próxima frase de quem
        # acabou de mandar ela ficar quieta.
        if not mandaram_calar:
            # Abre mesmo se o áudio falhou: a pessoa falou com ela, e obrigar a
            # repetir o nome porque o TTS engasgou seria pior.
            _est.conversa[turno.user_id] = time.monotonic() + JANELA_CONVERSA

    detalhe = (resultado.get("detalhe_texto") or "").strip()
    if detalhe and _mandar_no_texto is not None:
        try:
            _mandar_no_texto(f"{turno.nome}, o resto do que eu ia falar na "
                             f"call:\n{detalhe}")
        except Exception as e:
            _log(f"não consegui mandar o detalhe no chat: {e}")


def _trabalhar() -> None:
    while not _parar.is_set():
        try:
            item = _fila.get(timeout=1.0)
        except queue.Empty:
            continue
        turno, modo_conversa = item

        # Descarta por IDADE, não por falta de vaga. A fala de dez segundos atrás
        # ainda vale; a de um minuto atrás não, e responder ela faz ela parecer
        # que acordou no meio da conversa.
        atraso = time.monotonic() - turno.fim
        if atraso > IDADE_MAXIMA_FILA:
            with _trava:
                _est.descartados_fila += 1
            _log(f"a fala de {turno.nome} esperou {atraso:.0f}s e ficou velha; "
                 f"deixei passar")
            continue

        try:
            _responder(turno, modo_conversa)
        except Exception as e:
            with _trava:
                _est.erros += 1
                _est.ultimo_erro = f"resposta: {type(e).__name__}: {e}"
            _log(f"falhei ao responder: {type(e).__name__}: {e}")


def _iniciativa_cancelada(seq: int) -> bool:
    """Uma fala real ou resposta direta ganhou prioridade desde a avaliação."""
    with _trava:
        mudou = (_atividade_seq != seq or not _est.ligado
                 or _est.silenciada)
    if mudou or not _fila.empty():
        return True
    with _lote_trava:
        return bool(_lote)


def _tentar_iniciativa() -> bool:
    """Avalia uma intervenção espontânea, com orçamento e cancelamento."""
    global _iniciativa_avaliada_seq

    if not INICIATIVA_ATIVA or _pensar_espontaneo is None:
        return False

    agora = time.monotonic()
    with _trava:
        seq = _atividade_seq
        if (not _est.ligado or _est.silenciada or _est.falando
                or seq <= 0 or seq == _iniciativa_avaliada_seq
                or agora - _ultima_atividade < INICIATIVA_PAUSA
                or agora - _est.ultima_resposta_em < INICIATIVA_COOLDOWN):
            return False
    if not _fila.empty():
        return False
    with _lote_trava:
        if _lote:
            return False

    turnos = escuta_call.turnos_recentes(
        segundos=INICIATIVA_CONTEXTO_SEG, limite=CONTEXTO_LINHAS)
    pessoas = {t.user_id for t in turnos if t.user_id != escuta_call.ID_DELA}
    if len(turnos) < INICIATIVA_MIN_TURNOS or len(pessoas) < 2:
        return False

    # Uma tentativa por bloco de conversa. Marca antes do sorteio/modelo para o
    # vigia não rerrolar a chance a cada meio segundo.
    with _trava:
        if _atividade_seq != seq:
            return False
        _iniciativa_avaliada_seq = seq

    if random.random() > INICIATIVA_CHANCE:
        return False

    corte_hora = agora - 3600.0
    _iniciativas_hora[:] = [t for t in _iniciativas_hora if t >= corte_hora]
    if INICIATIVA_MAX_HORA <= 0 or len(_iniciativas_hora) >= INICIATIVA_MAX_HORA:
        return False

    # Iniciativa é dispensável: se a rota está apertada, guarda a capacidade
    # para quem chamar a Emily diretamente.
    try:
        import llm
        import modelo
        if llm.folga_da_rota(modelo.ROTA_DISCORD) < 5:
            return False
    except Exception:
        pass

    transcricao = "\n".join(f"{t.nome}: {t.texto}" for t in turnos)
    quem = ""
    if _quem_esta_na_call is not None:
        try:
            quem = _quem_esta_na_call() or ""
        except Exception:
            pass
    try:
        fala = (_pensar_espontaneo(transcricao, quem) or "").strip()
    except Exception as e:
        _log(f"iniciativa falhou ao pensar: {type(e).__name__}: {e}")
        return False
    if not fala or _iniciativa_cancelada(seq):
        return False

    _fala_local.reproduzida = ""
    ok = _falar_na_call(
        fala, cancelar_se=lambda: _iniciativa_cancelada(seq))
    if not ok:
        return False
    try:
        escuta_call.registrar_fala_dela(
            getattr(_fala_local, "reproduzida", "") or fala)
    except Exception as e:
        _log(f"não consegui registrar iniciativa na transcrição: {e}")
    instante = time.monotonic()
    _iniciativas_hora.append(instante)
    with _trava:
        _est.espontaneas += 1
        _est.respondidas += 1
        _est.ultima_resposta_em = instante
    _log(f"entrei espontaneamente na conversa: {fala[:70]}")
    return True


def _vigiar_iniciativa() -> None:
    while not _parar.wait(0.5):
        try:
            _tentar_iniciativa()
        except Exception as e:
            with _trava:
                _est.erros += 1
                _est.ultimo_erro = f"iniciativa: {type(e).__name__}: {e}"
            _log(f"vigia de iniciativa falhou: {type(e).__name__}: {e}")


# ═════════════════════════════════════════════════════════════════
# API
# ═════════════════════════════════════════════════════════════════

def ligar() -> str:
    """Passa a responder o que a escuta entregar."""
    global _thread, _thread_lote, _thread_iniciativa

    if not ATIVO:
        return ("Minha resposta em call está desligada na configuração "
                "(EMILY_RESPONDER_CALL=0).")
    if _est.ligado:
        return "Já estou respondendo na call."

    escuta_call.observar(_ao_ouvir_turno)

    if _thread is None or not _thread.is_alive():
        _parar.clear()
        _thread = threading.Thread(target=_trabalhar, name="call-resposta",
                                   daemon=True)
        _thread.start()

    # Vigia do lote: fecha os lotes de fala por janela/teto e enfileira a
    # resposta única. Sem ele, as falas ficariam acumulando no lote pra sempre
    # e ela nunca responderia.
    if _thread_lote is None or not _thread_lote.is_alive():
        _thread_lote = threading.Thread(target=_vigiar_lote, name="call-lote",
                                        daemon=True)
        _thread_lote.start()

    if (INICIATIVA_ATIVA and
            (_thread_iniciativa is None or not _thread_iniciativa.is_alive())):
        _thread_iniciativa = threading.Thread(
            target=_vigiar_iniciativa, name="call-iniciativa", daemon=True)
        _thread_iniciativa.start()

    _est.ligado = True
    _est.silenciada = False
    _log("respondendo na call")
    return "Agora eu respondo quem me chamar na call."


def _limpar_lote() -> None:
    """Descarta o lote em aberto. Usado ao silenciar, desligar ou zerar."""
    with _lote_trava:
        _lote.clear()



def _esvaziar_fila() -> None:
    """Joga fora o que estava esperando resposta. Responder depois de ser
    mandada calar é exatamente o que ninguém quer."""
    while True:
        try:
            _fila.get_nowait()
        except queue.Empty:
            return


def silenciar() -> str:
    """
    "Fica quieta": para de se meter na conversa, sem ficar surda.

    A escuta continua, então "o que rolou na call?" segue funcionando. E ela
    volta a falar sozinha na hora em que alguém chamar o nome dela e falar com
    ela de verdade — ver o comentário do campo `silenciada`.
    """
    global _atividade_seq
    if not _est.ligado:
        return "Não estou numa call."

    # O contador sobe ANTES do atalho de "já estou quieta", e é de propósito:
    # quem chama precisa saber que a ferramenta rodou neste turno, inclusive
    # quando ela não mudou nada. É esse contador que o _responder usa pra não
    # desfazer o silêncio que acabou de ser pedido.
    with _trava:
        ja_estava = _est.silenciada
        _est.silenciada = True
        _est.silenciada_seq += 1
        _est.conversa.clear()
        _est.calou_seguidas.clear()
        _atividade_seq += 1

    if ja_estava:
        return "Já estou quieta."

    _limpar_lote()
    _esvaziar_fila()
    _log("fiquei quieta (continuo ouvindo; chamar meu nome me traz de volta)")

    return ("Parei de me meter na conversa. Continuo ouvindo, e se alguém me "
            "chamar pelo nome eu volto a falar.")


def voltar_a_falar() -> str:
    if not _est.ligado:
        return "Não estou numa call."
    with _trava:
        _est.silenciada = False
    _log("voltei a responder")
    return "Voltei a responder na call."


def desligar() -> str:
    """
    Desliga de verdade. É o caminho de SAIR da call, não o de calar a boca.

    Quem quer só silêncio usa o silenciar(): este aqui derruba o observador de
    fato e só volta com ligar().
    """
    global _atividade_seq
    if not _est.ligado:
        return "Não estava respondendo."
    _est.ligado = False
    with _trava:
        _est.silenciada = False
        _est.conversa.clear()
        _atividade_seq += 1
    _limpar_lote()
    _esvaziar_fila()
    _log("parei de responder na call")

    return "Parei de responder na call, mas continuo ouvindo."


def respondendo() -> bool:
    """Ligada E não calada — ou seja, vai responder se alguém chamar."""
    return _est.ligado and not _est.silenciada


def silenciada() -> bool:
    return _est.silenciada


def ligada() -> bool:
    """Está numa call com o módulo ativo, mesmo que calada.

    É isto que o anti-eco deve consultar, não o respondendo(): estando calada
    ela ainda pode falar por outro caminho (o "oi, cheguei", ou uma resposta
    pedida pelo chat), e essa voz ecoa igual.
    """
    return _est.ligado


def silenciar_por(segundos: float, texto: str = "") -> None:
    """
    Fecha a escuta por um tempo, pra fala dela que NÃO passou por aqui.

    A Emily fala na call por outros caminhos além deste módulo: o "oi, cheguei"
    de quando entra, e a resposta de quem falou com ela pelo chat de texto
    estando na call. Esses áudios ecoam do mesmo jeito, e sem avisar aqui o
    anti-eco não teria como saber que aquela voz era dela.
    """
    with _trava:
        _est.mudo_ate = max(_est.mudo_ate,
                            time.monotonic() + max(0.0, segundos) + RABO_MUDO)
        if texto:
            _est.ultima_fala_dela = texto


def zerar_conversa() -> None:
    """Fecha todas as linhas abertas. Usado ao entrar ou sair de call."""
    global _atividade_seq, _iniciativa_avaliada_seq, _ultima_atividade
    with _trava:
        _est.conversa.clear()
        _est.calou_seguidas.clear()
        _est.ultima_fala_dela = ""
        _est.mudo_ate = 0.0
        # Zero exige uma fala real antes de a iniciativa poder rodar. Além de
        # cancelar avaliações pendentes, impede comentário baseado em histórico
        # ainda recente da call anterior logo depois de reconectar.
        _atividade_seq = 0
        _iniciativa_avaliada_seq = -1
        _ultima_atividade = 0.0


def estado() -> str:
    agora = time.monotonic()
    with _trava:
        abertas = sum(1 for ate in _est.conversa.values() if ate > agora)
        if not _est.ligado:
            situacao = "não (não estou em call)"
        elif _est.silenciada:
            situacao = ("NÃO — me mandaram ficar quieta. Continuo ouvindo, e "
                        "volto a falar se alguém me chamar pelo nome")
        else:
            situacao = "sim"
        linhas = [
            f"Respondendo na call: {situacao}",
            f"Falando agora: {'sim' if _est.falando else 'não'}",
            f"Conversas abertas: {abertas}",
            f"Falas que chegaram: {_est.ouvidos}",
            f"  me chamaram pelo nome: {_est.gatilho_nome}",
            f"  continuação de conversa: {_est.gatilho_conversa}",
            f"  barradas por não emendar na conversa: {_est.conversa_barradas}",
            f"  pedidos de silêncio em voz alta: {_est.silencio_voz}",
            f"  descartadas como eco: {_est.descartados_eco}",
            f"  perdidas por fila cheia: {_est.descartados_fila}",
            f"  eu decidi não responder: {_est.modelo_calou}",
            f"Respostas faladas: {_est.respondidas}",
            f"  espontâneas: {_est.espontaneas}",
        ]
        if _est.ultima_fala_dela:
            linhas.append(f"Última coisa que eu falei: "
                          f"{_est.ultima_fala_dela[:100]}")
        if _est.erros:
            linhas.append(f"Erros: {_est.erros} — último: "
                          f"{_est.ultimo_erro[:120]}")
    return "\n".join(linhas)


# ═════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
#
# Roda sem Discord, sem Groq e sem Fish: só as decisões. É o que dá pra
# conferir antes de ter uma call de verdade na frente.
# ═════════════════════════════════════════════════════════════════

def _diagnosticar() -> int:
    falhas = 0

    def conferir(rotulo: str, obtido, esperado) -> None:
        nonlocal falhas
        ok = obtido == esperado
        if not ok:
            falhas += 1
        print(f"  {'ok  ' if ok else 'FALHA'} {rotulo}"
              + ("" if ok else f"  (deu {obtido!r}, esperava {esperado!r})"))

    print("=" * 66)
    print("  RESPOSTA EM CALL")
    print("=" * 66)
    print(f"    ativa:                {ATIVO}")
    print(f"    janela de conversa:   {JANELA_CONVERSA:.0f} s")
    print(f"    rabo de mudo:         {RABO_MUDO:.1f} s")
    print(f"    limiar de eco:        {LIMIAR_ECO:.2f}")
    print(f"    sinal de 'ouvi':      {SINAL_DE_OUVI}")
    print(f"    tamanho da fila:      {MAX_FILA}")

    print("\n-- o nome dela, como o Whisper escreve --")
    for fala in [
        "emily o servidor tá on?",
        "Emilly, você viu isso?",
        "ei emili vem cá",
        "EMILY",
        "e mily você tá aí",
        "emi, liga o servidor",
        "fala Emile",
        "a emily entrou na call agora",
    ]:
        conferir(f"pega em {fala!r}", chamaram_ela(fala), True)

    print("\n-- não pode disparar --")
    for fala in [
        "a família toda tá aqui",
        "custou e mil e duzentos reais",
        "isso vale mais de dez milhões",
        "vamo jogar hoje pessoal",
        "o emblema do time é bonito",
        "mano que emocionante",
        "",
        "eu vi um filme com a Amelia ontem",
    ]:
        conferir(f"ignora {fala!r}", chamaram_ela(fala), False)

    print("\n-- anti-eco --")

    class _T:
        def __init__(self, texto, inicio, uid=1, nome="Vitor"):
            self.texto, self.inicio = texto, inicio
            self.user_id, self.nome = uid, nome

    agora = time.monotonic()
    _est.ultima_fala_dela = "o servidor está ligado sim, entra que tá vazio"
    _est.mudo_ate = agora + 10.0

    conferir("eco quase igual é descartado",
             _e_eco(_T("o servidor está ligado sim entra que tá vazio",
                       agora + 1))[0], True)
    conferir("eco degradado é descartado",
             _e_eco(_T("o servidor tá ligado sim entra que ta vazio",
                       agora + 1))[0], True)
    conferir("trecho literal é descartado",
             _e_eco(_T("entra que tá vazio", agora + 1))[0], True)
    conferir("fala de uma palavra por cima é descartada",
             _e_eco(_T("sim", agora + 1))[0], True)
    conferir("fala DIFERENTE por cima dela passa",
             _e_eco(_T("cara eu vou almoçar agora volto depois",
                       agora + 1))[0], False)
    conferir("fora da janela de mudo passa, mesmo idêntica",
             _e_eco(_T("o servidor está ligado sim, entra que tá vazio",
                       agora + 20))[0], False)

    _est.mudo_ate = 0.0
    _est.ultima_fala_dela = ""

    print("\n-- limpeza pro TTS (modelo.py) --")
    try:
        import modelo as m
        casos = [
            ("kkkk vc é doido pq fez isso", "você é doido porque fez isso"),
            ("**mano** olha o `codigo` ali", "mano olha o codigo ali"),
            ("vsfd n acredito nisso krl", "vai se foder não acredito nisso caralho"),
            ("olha aqui https://github.com/vitor", "olha aqui o link"),
            ("tb acho ss", "também acho isso"),
        ]
        for entrada, esperado in casos:
            conferir(f"{entrada!r}", m.limpar_para_tts(entrada), esperado)

        longa = ("Primeiro você abre o painel. " * 30).strip()
        fala, resto = m.encurtar_para_call(longa)
        conferir("teto de segurança corta monólogo",
                 len(fala.split()) <= m._MAX_PALAVRAS_CALL, True)
        conferir("o excedente do monólogo sobra pro chat", bool(resto), True)

        curta = "tá ligado sim, entra lá"
        fala, resto = m.encurtar_para_call(curta)
        conferir("resposta curta vai inteira", (fala, resto), (curta, ""))
    except Exception as e:
        falhas += 1
        print(f"  FALHA não consegui testar o modelo.py: "
              f"{type(e).__name__}: {e}")

    print("\n-- estado --")
    print("    " + estado().replace("\n", "\n    "))

    print("\n" + "=" * 66)
    if falhas:
        print(f"{falhas} conferência(s) falharam.")
    else:
        print("Todas as conferências passaram. Falta a call de verdade.")
    return 1 if falhas else 0


if __name__ == "__main__":
    import sys
    sys.exit(_diagnosticar())
