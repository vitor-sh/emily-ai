"""Política local e compartilhada para uso de ferramentas.

Mantido sem imports do restante da Emily para poder ser usado por modelo.py,
discord_bot.py e discord_admin.py sem dependências circulares.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


SEM_FERRAMENTA = "sem_ferramenta"
FERRAMENTA_OPCIONAL = "ferramenta_opcional"
FERRAMENTA_OBRIGATORIA = "ferramenta_obrigatoria"


@dataclass(frozen=True)
class ClassificacaoFerramenta:
    politica: str
    motivo: str

    @property
    def permite_ferramenta(self) -> bool:
        return self.politica != SEM_FERRAMENTA

    @property
    def exige_ferramenta(self) -> bool:
        return self.politica == FERRAMENTA_OBRIGATORIA

    @property
    def proibe_ferramenta(self) -> bool:
        return self.politica == SEM_FERRAMENTA


def normalizar(texto: str) -> str:
    bruto = unicodedata.normalize("NFD", str(texto or "").lower())
    sem_acentos = "".join(c for c in bruto if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9@#]+", " ", sem_acentos).strip()


_MARCADORES_MEMORIA = (
    "lembra que", "lembrar que", "guarda que", "guardar que", "anota que",
    "anotar que", "nao esquece que", "nao esqueca que",
)

_MARCADORES_CONSULTA_ATUAL = (
    "mais recente", "ultima noticia", "ultimas noticias", "noticia de hoje",
    "noticias sobre", "quanto custa", "qual o preco", "preco atual", "cotacao",
    "quem ganhou", "qual foi o resultado", "resultado do jogo", "qual o placar",
    "placar do jogo", "versao mais nova", "versao atual", "ultima versao",
    "lancou quando", "data de lancamento", "tempo hoje", "previsao do tempo",
    "o que esta acontecendo", "quem e o presidente", "quem e o governador",
    "quem e o prefeito",
)


def parece_pedido_de_memoria(texto: str) -> bool:
    """Pedido para guardar informação, não operação externa imediata."""
    t = normalizar(texto)
    return bool(t) and any(m in t for m in _MARCADORES_MEMORIA)


def parece_consulta_atual(texto: str) -> bool:
    """Pergunta cujo fato pode ter mudado e deve ser consultado."""
    t = normalizar(texto)
    return bool(t) and any(m in t for m in _MARCADORES_CONSULTA_ATUAL)


def parece_pergunta_factual(texto: str) -> bool:
    """Dúvida sobre fatos externos: pode precisar de busca, sem obrigá-la sempre."""
    t = normalizar(texto)
    if not t:
        return False
    if any(m in t for m in (
            "minha senha", "meu login", "meus dados pessoais", "meu endereco",
            "minha conta", "minha conversa", "meu arquivo")):
        return False
    if len(t) < 80 and any(t.startswith(m) for m in (
            "como voce esta", "como voce ta", "como voce vai",
            "como tu esta", "tudo bem", "o que voce acha",
            "como voce se sente")):
        return False
    # Opinião e desabafo também podem terminar uma mensagem longa com '?'.
    # Não são dúvidas factuais só por terem um ponto de interrogação.
    opiniao = any(m in t for m in (
        "o que voce acha", "o que tu acha", "o que ce acha",
        "o que vc acha", "tu acha que", "voce acha que",
        "qual sua opiniao", "qual a sua opiniao",
    ))
    tema_factual = any(m in t for m in (
        "benchmark", "desempenho", "preco", "cotacao", "noticia",
        "lancamento", "versao mais nova", "versao atual",
        "dados oficiais", "fonte oficial", "pesquise", "pesquisa",
    ))
    if opiniao and not tema_factual:
        return False
    return bool("?" in texto or re.match(
        r"^(qual|quais|quem|quando|onde|como|por que|porque|o que|quanto|quantos)\b", t)
        or any(m in t for m in (
        "queria saber", "me explica", "me conte", "me fala sobre",
        "me diga sobre", "me diz sobre", "sabe me dizer",
        "compare", "comparacao", "benchmark", "desempenho",
        "qualidade de", "diferenca entre", "informacoes sobre",
    )))


_CONTEXTO_SOCIAL_FUTURO = (
    "quando alguem", "quando outra pessoa", "quando entrar alguem",
    "quando entrar outra pessoa", "se alguem", "se outra pessoa",
    "se entrar alguem", "se entrar outra pessoa", "quando o pessoal",
    "quando a galera", "na frente de", "perto de outras pessoas",
)

_COMPORTAMENTOS_CONVERSACIONAIS = (
    "nao fala", "nao falar", "nao comenta", "nao comentar", "nao conta",
    "nao contar", "nao menciona", "nao mencionar", "nao fica falando",
    "nao ficar falando", "muda de assunto", "fica de boa", "ficar de boa",
    "fica quieta sobre", "guardar segredo", "guarda segredo", "entre nos",
    "so entre a gente", "assunto nosso", "coisas nossas", "conversa nossa",
)

_ACOES_EXTERNAS_CLARAS = (
    "apaga", "apagar", "deleta", "deletar", "remove", "remover", "cria",
    "criar", "edita", "editar", "renomeia", "renomear", "bane", "banir",
    "expulsa", "expulsar", "muta", "mutar", "fecha", "fechar", "abre",
    "abrir", "manda", "mandar", "manda mensagem", "enviar mensagem",
    "toca musica", "instala", "instalar", "desinstala", "desinstalar",
    "executa", "executar", "ativa", "ativar", "desativa", "desativar",
    "liga", "ligar", "desliga", "desligar", "silencia", "silenciar",
    "configura", "configurar", "salva", "salvar", "associa", "associar",
)

_OPORTUNIDADES_INICIATIVA = (
    "to triste", "estou triste", "to mal", "estou mal", "to ansioso",
    "estou ansioso", "to ansiosa", "estou ansiosa", "to entediado",
    "estou entediado", "to entediada", "estou entediada", "sem nada pra fazer",
    "queria ouvir uma musica", "queria escutar uma musica", "queria jogar algo",
)


def parece_oportunidade_de_iniciativa(texto: str) -> bool:
    """Sinal estreito de que uma ação simples opcional pode realmente ajudar."""
    t = normalizar(texto)
    return bool(t) and any(m in t for m in _OPORTUNIDADES_INICIATIVA)


def parece_instrucao_comportamental(texto: str) -> bool:
    """Regra de como a Emily deve conversar, inclusive num cenário futuro."""
    t = normalizar(texto)
    if not t or not any(m in t for m in _COMPORTAMENTOS_CONVERSACIONAIS):
        return False
    # "quando alguém entrar, apaga o canal" continua sendo ação externa.
    if any(
        (a in t if " " in a else re.search(rf"\b{re.escape(a)}\b", t))
        for a in _ACOES_EXTERNAS_CLARAS
    ):
        return False
    return (
        any(m in t for m in _CONTEXTO_SOCIAL_FUTURO)
        or any(m in t for m in (
            "nao fala", "nao ficar falando", "nao comenta", "nao conta",
            "nao menciona",
            "guarda segredo", "so entre a gente", "entre nos",
        ))
    )


def classificar(
    texto: str,
    *,
    acao_explicita: bool = False,
    consulta_explicita: bool = False,
    permitir_iniciativa: bool = False,
) -> ClassificacaoFerramenta:
    """Decide se ferramenta é proibida, opcional ou obrigatória no turno."""
    if parece_instrucao_comportamental(texto):
        return ClassificacaoFerramenta(
            SEM_FERRAMENTA, "instrucao_comportamental_conversacional")
    if parece_pedido_de_memoria(texto):
        return ClassificacaoFerramenta(
            SEM_FERRAMENTA, "pedido_de_memoria_sem_ferramenta_de_escrita")
    t = normalizar(texto)
    if "xadrez" in t:
        convite = re.search(r"\b(jogar|joga|jogamos|joguemos|partida|tabuleiro|bora|vamos|vamo|topa)\b", t)
        if convite and not re.search(r"\b(nao|nunca|como|aprender|aprendo|ensina|regras|historia|explica|significa)\b", t):
            return ClassificacaoFerramenta(FERRAMENTA_OBRIGATORIA, "convite_xadrez_integrado")
    if acao_explicita:
        return ClassificacaoFerramenta(
            FERRAMENTA_OBRIGATORIA, "acao_externa_explicita")
    if consulta_explicita:
        return ClassificacaoFerramenta(
            FERRAMENTA_OBRIGATORIA, "consulta_atual_explicita")
    if parece_pergunta_factual(texto):
        return ClassificacaoFerramenta(
            FERRAMENTA_OPCIONAL, "pergunta_factual_pode_exigir_pesquisa")
    if "xadrez" in t:
        return ClassificacaoFerramenta(FERRAMENTA_OPCIONAL, "conversa_sobre_xadrez")
    if permitir_iniciativa and parece_oportunidade_de_iniciativa(texto):
        return ClassificacaoFerramenta(
            FERRAMENTA_OPCIONAL, "iniciativa_autonoma_de_baixo_impacto")
    return ClassificacaoFerramenta(
        SEM_FERRAMENTA, "conversa_sem_operacao_externa")
