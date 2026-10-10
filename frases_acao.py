"""Frases curtas que a Emily fala enquanto executa uma ação ("já vou ver...").

Saiu de modelo.py, que re-exporta gerar_frase_acao e _escolher_frase.
"""
from __future__ import annotations

import random
from typing import Dict


_FRASES_ACAO = {
    "analisando_disco": (
        "Deixa eu varrer o disco, isso demora um pouco",
        "Tá, vou vasculhar tudo aí, aguenta",
        "Peraí que eu meço o que tá pesando",
        "Um minuto, tô mapeando o disco inteiro",
        "Vou cavar fundo pra achar o que tá enchendo",
        "Calma que eu conto byte por byte",
    ),
    "limpando_disco": (
        "Tá, tô limpando o lixo agora",
        "Deixa eu esvaziar essa tralha",
        "Peraí que eu libero o espaço",
        "Mandando os temporários pro além",
    ),
    "executando_terminal": (
        "Peraí, vou rodar isso aqui no terminal",
        "Deixa eu resolver isso por comando",
        "Tá, um segundo que eu executo aqui",
        "Vou fazer isso direto no terminal",
    ),
    "cancelando_terminal": (
        "Tá, matando o comando agora",
        "Peraí que eu interrompo isso",
        "Cancelando, segura",
    ),
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
    "code": (
        "Deixa eu mexer nisso aí",
        "Tá, vou fuçar no projeto",
        "Peraí que vou de código",
        "Modo programadora ativado",
        "Segura que eu edito isso",
        "Já vou abrir esse arquivo",
        "Vou escrever código, não me interrompe",
        "Deixa comigo, isso é trabalho pra mim",
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
    "mexendo_na_tv": (
        "Mandando pra TV",
        "Tá, mexo na TV aqui",
        "Um segundo, comando a TV",
        "Já vou mexer na TV",
        "Peraí que vou na TV",
    ),
}


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
