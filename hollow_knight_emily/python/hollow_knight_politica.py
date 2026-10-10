"""Política determinística de relevância, cooldown e fallback da companheira."""

from __future__ import annotations

import random
import re
import threading
import time
from collections import defaultdict, deque


PRIORIDADE = {
    "boas_vindas": 96,
    "charm_adquirido": 100,
    "chamou_emily": 100,
    "boss_derrotado": 95,
    "morte": 90,
    "boss_iniciado": 85,
    "boss_encontrado": 88,
    "boss_fase": 74,
    "boss_luta": 76,
    "npc_dialogo": 72,
    "comentario_tagarela": 18,
    "quase_morte": 80,
    "habilidade_adquirida": 78,
    "magia_adquirida": 92,
    "amuleto_adquirido": 88,
    "estacao_desbloqueada": 86,
    "item_importante_adquirido": 90,
    "banco_descoberto": 72,
    "area_nova": 65,
    "segredo": 60,
    # Sentar em banco é rotina: acontece muitas vezes por sessão e não merece
    # fala própria. Continua na telemetria e na memória, mas fica abaixo do
    # mínimo de qualquer modo.
    "banco": 0,
    "banco_saida": 0,
    "jogo_iniciado": 0,
    # Dano isolado também não é fala: quem comenta é quase_morte, morte e os
    # padrões de dano repetido/grave detectados pela memória.
    "dano": 5,
    "inimigo_morto": 8,
    "observacao": 5,
    "estado": 0,
    # 0.4.9: lote de eventos próximos. A prioridade real é a máxima dos
    # acontecimentos que o formaram; esta entrada só existe para consultas.
    "eventos_multiplos": 0,
}

COOLDOWN_TIPO = {
    "dano": 75.0,
    "inimigo_morto": 160.0,
    "banco": 900.0,
    "area_nova": 30.0,
    "quase_morte": 45.0,
    "morte": 8.0,
    # 0.5.0: cooldowns de chefe eram agressivos demais — boss_encontrado 60s
    # engolia o boss_iniciado que vinha logo depois; boss_luta 90s numa luta
    # de 5 minutos dava 3 comentários no máximo, e o usuário reportou silêncio.
    "boss_iniciado": 15.0,
    "boss_encontrado": 35.0,
    "boss_fase": 30.0,
    "boss_luta": 50.0,
    "npc_dialogo": 60.0,
    "comentario_tagarela": 180.0,
    "observacao": 60.0,
    "boss_derrotado": 3.0,
    "boas_vindas": 0.0,
    "chamou_emily": 0.0,
    "charm_adquirido": 0.0,
}

# Falas de ambiente (não autoritativas) por janela. Marcos, aquisições e
# chamadas diretas nunca entram nessa conta: o orçamento existe para o modo
# tagarela continuar conversando sem virar narração contínua.
LIMITE_AMBIENTE = {"muda": 0, "quieta": 1, "normal": 3, "tagarela": 6}
JANELA_AMBIENTE = 360.0

# Dano só vira assunto quando é anormal: perder várias máscaras de uma vez ou
# ficar no fio da vida. Um machucado besta passa em branco, e quando ela resolve
# comentar, o comentário tem que ser curto.
DANO_ANORMAL_MINIMO = 3
PRIORIDADE_DANO_ANORMAL = 30


def _numero(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def dano_anormal(dados: dict) -> bool:
    """Reconhece um dano que merece reação em vez de um arranhão de rotina."""
    dados = dados if isinstance(dados, dict) else {}
    vida = _numero(dados.get("vida_atual"))
    perda = _numero(dados.get("dano"))
    if vida is not None and vida <= 2:
        return True
    return perda is not None and perda >= DANO_ANORMAL_MINIMO


# Expressões que denunciam narração de métricas ("7 máscaras", "deu 5 hits").
TERMOS_ESTATISTICA = (
    r"vida|máscaras?|mascaras?|alma|geo|ferrão|ferrao|dano|danos|golpes?|"
    r"hits?|impactos?|segundos?|minutos?|horas?|por cento|velocidade|"
    r"distância|distancia|metros?"
)
_TERMO_ESTATISTICA = re.compile(r"\b(?:" + TERMOS_ESTATISTICA + r")\b", re.IGNORECASE)
_NUMERO_ESCRITO = re.compile(
    r"\b(?:um|uma|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|quinze|vinte|trinta|cinquenta|cem)\s+(?:" + TERMOS_ESTATISTICA + r")\b",
    re.IGNORECASE,
)


def parece_narracao_de_estatistica(texto: str) -> bool:
    """Reconhece relatório de métricas em vez de comentário humano.

    Dois números no mesmo comentário já soam como painel; um número só é
    aceito quando está colado num termo de estatística.
    """
    if not texto:
        return False
    digitos = re.findall(r"\d+", texto)
    if len(digitos) >= 2:
        return True
    if digitos and (_TERMO_ESTATISTICA.search(texto) or "%" in texto):
        return True
    return bool(_NUMERO_ESCRITO.search(texto))

FALLBACKS = {
    "boas_vindas": [
        "Opa, voltou. Eu tô aqui, então vamos ver onde isso vai dar hoje.",
    ],
    "charm_adquirido": [
        "Ah... então foi você que me acordou. Tá, eu vou junto. Não se empolga.",
    ],
    "boss_iniciado": [
        "Tá. Esse aí parece grande demais pra ser só decoração.",
    ],
    "boss_derrotado": [
        "Conseguimos! Quer dizer... você até que ajudou bastante.",
    ],
    "chamou_emily": [
        "Tô aqui. O que foi?",
    ],
}

AUTORITATIVOS = {
    "boas_vindas", "charm_adquirido", "chamou_emily", "boss_derrotado",
    "habilidade_adquirida", "magia_adquirida", "amuleto_adquirido",
    "estacao_desbloqueada", "item_importante_adquirido", "banco_descoberto",
    "npc_dialogo", "boss_encontrado",
}

# 0.4.10: quando o modelo insiste no painel de status, esses eventos não podem
# simplesmente sumir mudos — chefe, morte e marcos merecem reação de qualquer
# jeito. A fala determinística da Emily assume o lugar do relatório descartado.
EVENTOS_QUE_NAO_FICAM_MUTOS = AUTORITATIVOS | {
    "boss_iniciado", "boss_luta", "boss_fase", "morte", "quase_morte",
}

# Cumprimento de abertura acontece em qualquer modo: entrar no save é o momento
# de ela se apresentar, mesmo para quem escolheu "Silenciosa".
MODOS_SEMPRE_PERMITIDOS = {"boas_vindas", "charm_adquirido", "boss_derrotado", "morte", "chamou_emily"}


class PoliticaComentarios:
    # 0.4.10: exposto como atributo de classe para a ponte consultar sem
    # importar o símbolo do módulo diretamente.
    EVENTOS_QUE_NAO_FICAM_MUTOS = EVENTOS_QUE_NAO_FICAM_MUTOS

    def __init__(self, relogio=time.time) -> None:
        self._relogio = relogio
        self._lock = threading.Lock()
        self._ultimo_global = 0.0
        self._ultimo_tipo = defaultdict(float)
        self._recentes = deque(maxlen=16)
        self._falas_ambiente = deque(maxlen=64)

    def prioridade(self, tipo: str) -> int:
        return PRIORIDADE.get(tipo, 5)

    def deve_responder(self, tipo: str, dados: dict, modo: str = "normal") -> bool:
        if tipo == "comentario_tagarela" and modo != "tagarela":
            return False
        if modo == "muda" and tipo not in MODOS_SEMPRE_PERMITIDOS:
            return False
        # Dano só entra quando é anormal: machucado pequeno e isolado nunca vira
        # fala, nem no tagarela.
        anormal = tipo == "dano" and dano_anormal(dados)
        if tipo == "dano" and not anormal:
            return False
        prioridade = max(
            self.prioridade(tipo),
            PRIORIDADE_DANO_ANORMAL if anormal else 0,
            int(dados.get("prioridade") or 0),
        )
        minimo = 60 if modo == "quieta" else 25 if modo == "normal" else 8
        if prioridade < minimo:
            return False
        agora = self._relogio()
        with self._lock:
            # Aquisição e pedido direto são eventos autoritativos: o jogador
            # acabou de conhecer/chamar a Emily e não pode receber silêncio por
            # causa de uma fala ambiente ocorrida segundos antes.
            if tipo in AUTORITATIVOS or bool(dados.get("persistente")):
                self._ultimo_global = agora
                self._ultimo_tipo[tipo] = agora
                return True
            global_cd = 2.0 if prioridade >= 85 else 24.0 if modo == "tagarela" else 22.0
            if agora - self._ultimo_global < global_cd:
                return False
            if agora - self._ultimo_tipo[tipo] < COOLDOWN_TIPO.get(tipo, 45.0):
                return False
            if not self._dentro_do_orcamento(agora, modo):
                return False
            self._ultimo_global = agora
            self._ultimo_tipo[tipo] = agora
            self._falas_ambiente.append(agora)
            return True

    def _dentro_do_orcamento(self, agora: float, modo: str) -> bool:
        """Limita falas de ambiente por janela, mesmo no modo tagarela.

        O orçamento não é um limite de tamanho da fala: é o que impede a Emily
        de transformar o jogo inteiro num fluxo contínuo de comentário.
        """
        limite = LIMITE_AMBIENTE.get(modo, 3)
        if limite <= 0:
            return False
        recentes = sum(
            1 for momento in self._falas_ambiente if agora - momento < JANELA_AMBIENTE
        )
        return recentes < limite

    def registrar_texto(self, texto: str) -> None:
        texto = " ".join(str(texto or "").lower().split())
        if texto:
            with self._lock:
                self._recentes.append(texto)

    def parece_narracao_de_estatistica(self, texto: str) -> bool:
        """Atalho para a checagem usada pelo worker antes de entregar a fala."""
        return parece_narracao_de_estatistica(texto)

    def repetido(self, texto: str) -> bool:
        candidato = " ".join(str(texto or "").lower().split())
        if not candidato:
            return True
        with self._lock:
            return candidato in self._recentes

    def fallback(self, tipo: str, dados: dict | None = None) -> str:
        dados = dados or {}
        nome = str(dados.get("nome") or "").strip()
        identidade_confirmada = bool(
            dados.get("identidade_confirmada", bool(nome))
        )
        nome_seguro = nome if identidade_confirmada else ""
        if tipo == "eventos_multiplos":
            # 0.4.9: o lote herda o fallback do acontecimento mais importante,
            # nunca uma frase genérica de "várias coisas aconteceram".
            melhor = ""
            melhor_prioridade = -1
            for item in dados.get("resumo") or []:
                if not isinstance(item, dict):
                    continue
                sub_tipo = str(item.get("tipo") or "")
                candidato = self.fallback(sub_tipo, item.get("dados") or {})
                if candidato and self.prioridade(sub_tipo) > melhor_prioridade:
                    melhor = candidato
                    melhor_prioridade = self.prioridade(sub_tipo)
            return melhor
        if tipo == "morte":
            mortes = int(dados.get("mortes_presenciadas") or 0)
            if mortes >= 3:
                return "De novo isso. Já perdi a conta de quantas vezes eu te vi cair assim. Respira antes de voltar."
            if mortes > 0:
                return "Eu vi onde isso desandou. Respira antes de voltar correndo pro mesmo ponto."
            return "Respira. Volta com calma em vez de correr pro mesmo lugar."
        if tipo == "quase_morte":
            return (
                "Isso passou perto demais. Segura a pressa um instante, "
                "porque agora qualquer vacilo cobra caro."
            )
        if tipo == "dano":
            # Dano anormal existe, mas não é assunto para discurso.
            return random.choice([
                "Ei, isso pegou feio. Não relaxa agora.",
                "Ok, esse doeu de verdade. Fica esperta com o próximo.",
                "Isso foi coisa demais de uma vez. Respira e volta com calma.",
            ])
        contextuais = {
            "boss_encontrado": f"Tá, é {nome_seguro or 'um chefe'}. Respira antes de entrar nessa, porque isso aqui não parece visita de cortesia.",
            "boss_iniciado": f"Agora começou de verdade com {nome_seguro or 'esse chefe'}. Eu fico de olho em você, só não inventa de abraçar golpe.",
            "boss_fase": f"Essa luta contra {nome_seguro or 'esse chefe'} virou outra etapa. Se agarra, que agora é que é de verdade.",
            "boss_derrotado": f"Tá, {nome or 'esse chefe'} caiu. Até que você mandou bem dessa vez.",
            "habilidade_adquirida": f"Olha só, {nome or 'uma habilidade nova'}. Agora tenta usar isso direito, né.",
            "magia_adquirida": f"Você conseguiu {nome or 'uma magia nova'}. Finalmente alguma coisa pra dar uma força nesse ferrão.",
            "amuleto_adquirido": f"Mais um: {nome or 'um novo amuleto'}. Depois não reclama que não sabe qual equipar.",
            "estacao_desbloqueada": f"Boa, estação de {nome or 'uma nova região'} liberada. Pelo menos voltar aqui não vai ser um sofrimento.",
            "item_importante_adquirido": f"Isso parece importante: {nome or 'um item novo'}. Guarda direito, pelo amor de Deus.",
            "banco_descoberto": f"Achamos {nome or 'um novo banco'}. Senta aí antes que você invente de perder tudo.",
        }
        if tipo == "npc_dialogo":
            if nome_seguro:
                return f"O jeito que {nome_seguro} conduziu essa conversa me deixou com a impressão de que tem mais coisa guardada aí."
            return "Essa conversa teve um peso meio estranho. Não parecia só papo jogado fora."
        if tipo == "boss_luta":
            padrao = str(dados.get("padrao") or "")
            alvo = nome_seguro or "esse chefe"
            if padrao == "sequencia_sem_dano":
                return (
                    f"Olha, contra {alvo} você tá lendo bem as aberturas e "
                    "não tá tomando nada. Continua assim, porra."
                )
            if padrao == "pressao_constante":
                return (
                    f"Você não tá dando sossego pra {alvo}, hein. "
                    "Só não deixa a pressa abrir sua guarda."
                )
            if padrao == "recuperacao_apos_dano":
                return (
                    f"Boa recuperação contra {alvo}. Tomou o impacto e "
                    "voltou na mesma hora, sem desmontar."
                )
        if tipo in contextuais:
            return contextuais[tipo]
        opcoes = FALLBACKS.get(tipo) or []
        return random.choice(opcoes) if opcoes else ""
