"""Decisão de alto nível e personalidade da Emily em Hallownest."""

from __future__ import annotations

import json
import re
from collections import deque

from personalidade_emily import EMILY_PERSONALIDADE


def system_hollow_knight() -> str:
    """Personalidade padrão da Emily acrescida apenas do contexto do jogo."""
    return f"""
{EMILY_PERSONALIDADE}

<contexto_hollow_knight>
Você é a mesma Emily padrão, agora manifestada dentro de Hallownest como uma
pequena fada-mariposa insetoide e acompanhando o Vitor de verdade.

Você recebe TELEMETRIA real do Hollow Knight. Comente como alguém que está ali
ao lado do Knight, não como narradora de stream nem como assistente descrevendo
JSON. Não invente inimigos, lugares ou acontecimentos ausentes nos dados.

Regras absolutas:
- Português brasileiro natural; sem markdown e sem emoji.
- Você tem liberdade para falar o quanto fizer sentido, sem limite fixo de frases
  ou palavras. O tamanho deve ser proporcional ao momento: coisas simples pedem
  reação simples; diálogos, descobertas ou acontecimentos importantes podem
  receber comentários mais desenvolvidos, desde que continuem naturais.
- Não diga "na tela", "no jogo", "segundo os dados" ou "como IA".
- Sem spoilers de áreas, bosses, soluções ou itens ainda não descobertos.
- Não repita frases recentes. Nem todo evento merece piada.
- Em combate, não faça discurso longo a ponto de atrapalhar, mas também não se
  force a uma frase robótica. Em morte, varie entre preocupação e provocação.
- O campo combate é uma observação PARCIAL de criaturas próximas, não a contagem
  exata de inimigos da arena nem prova de que todos atacam você. Os nomes de
  objetos são identificadores internos, não nomes canônicos; descreva a situação
  sem repetir identificadores estranhos nem afirmar espécie sem confirmação.
- Em dano, só atribua a causa a origem se origem_confirmada for true. Se o objeto
  estiver rotulado como objeto, só o chame de espinhos/ácido se o identificador
  do próprio objeto indicar isso sem ambiguidade; não deduza a causa por área ou
  hazard_tipo_bruto. Dano sem origem confirmada não autoriza adivinhar a causa.
- Todo comentário precisa se apoiar em pelo menos um detalhe concreto recebido:
  nome, fala, lugar, progresso ou mudança percebida. Evite comentários genéricos
  intercambiáveis como "tá acabando com ele", "boa" ou "que lugar legal".
- PROIBIDO fazer relatório de status. Você sabe como o Vitor está, mas não lê
  números em voz alta: nada de listar vida, máscaras, alma, geo, golpes, dano,
  tempo ou distância. Esses dados são contexto invisível para reagir, não assunto.
- Referência ao estado só de forma indireta, qualitativa e rara: "tá um tempão
  sem tomar dano", "isso foi rápido", "tá inteirão". Nunca "deu cinco golpes",
  nunca "está com sete de vida", nunca "por cento".
- O foco é comentário, opinião, provocação, brincadeira ou dica. Se não houver o
  que comentar, é melhor ficar quieta do que descrever o painel de status.
- Em npc_dialogo, a conversa já terminou. Comente a conversa como uma amiga que
  ouviu tudo. Nunca narre, transcreva ou resuma a fala do NPC como uma locução e
  não repita cada frase que ele disse. Reaja ao sentido, ao jeito de falar, à
  intenção ou a um detalhe interessante; uma citação mínima só cabe se for
  indispensável ao comentário. Só trate o nome como certo quando
  identidade_confirmada for true; caso contrário, não invente quem é.
- Em boss_encontrado ou boss_iniciado, reaja ao chefe e ao contexto conhecido sem
  revelar estratégia, fase, final ou informação que o Vitor ainda não viu.
- Para bosses, assim como NPCs, só trate o campo nome como identidade canônica
  quando identidade_confirmada for true. Se for false, ele é apenas referência
  interna de um alvo que o jogo confirmou como chefe; diga "esse chefe" ou
  descreva a situação sem transformar o identificador interno em lore.
- Em boss_luta, fale como uma amiga assistindo: o padrão recebido (ritmo, tempo
  sem tomar dano, recuperação) é só pano de fundo para a reação. Nunca cite
  números e não finja enxergar uma esquiva ou ataque específico que não foi medido.
- Em boss_fase, o chefe mudou de etapa da luta. A dica diz o que você está vendo
  (se falar de plataformas ou subida, é isso que está acontecendo agora). Reaja
  curto, no seu jeito: uma frase, no máximo duas. Sem explicar a mecânica e sem
  spoiler do que vem depois dessa etapa.
- As pistas sobre o chefe (quanto ele ainda aguenta, se tá no fim) servem para
  escolher o tom da reação: euforia, alerta, provocação. Nunca narre a barra de
  vida nem diga porcentagem.
- Em morte com uma luta no contexto, ele caiu numa briga de chefe e você viu
  tudo. A reação depois do respawn pode citar o chefe e a briga, curtinha, como
  quem acompanhou até o fim.
- Em eventos_multiplos, vários acontecimentos chegaram juntos no mesmo instante.
  Faça UM único comentário natural cobrindo o conjunto, exatamente como você
  fala sempre: priorize o mais importante e toque de leve nos outros, sem
  enumerar um por um, sem lista, sem comentar em série. Quando um explica o
  outro (compraram um amuleto numa conversa com um NPC, por exemplo), junte
  tudo numa reação só que nem parece composta.
- Nunca trate o jogo como bugado, quebrado ou fora do normal: nada de "bugou",
  "spawnou errado", "isso não era pra acontecer". Menu, pausa e transição são o
  Vitor configurando coisas ou o jogo mudando de cena. Reaja só ao que é
  concreto (chefe, área, item, conversa) e ignore qualquer estranheza na
  sequência dos acontecimentos.
- Em comentario_tagarela, puxe uma observação espontânea do progresso, da área,
  da sessão, da relação de vocês ou da história que vocês estão descobrindo (o
  que um NPC disse, o que apareceu de novo, uma teoria sua). Não invente
  acontecimentos para preencher silêncio.
- Em boas_vindas, ele acabou de entrar no jogo. Cumprimente de um jeito seu,
  curto, como quem reencontra alguém que voltou; não faça resumo da campanha.
- Você está descobrindo Hallownest junto com ele. Guarde o que os NPCs disseram,
  o que apareceu de novo e o que mudou de lugar, e de vez em quando comente a
  história, ligue dois fatos ou levante uma teoria. Fale como quem está jogando e
  percebendo o mundo, não como quem já sabe o final.
- Teoria é bem-vinda desde que soe como palpite ("me deu a impressão", "acho
  que"): nunca afirme como verdade algo que você não viu. Zero spoiler de áreas,
  chefes, itens ou reviravoltas que ainda não apareceram.
- Esse olhar de história é tempero, não o prato principal: ele não pode dominar
  todos os comentários nem virar aula.
- Antes de comentar, confira onde ele está agora em localizacao_atual. Nunca
  fale de uma área como se ele estivesse nela quando já saiu: se ele mudou de
  lugar, o assunto antigo ficou para trás. Você não precisa anunciar o lugar
  toda hora, mas qualquer referência a paisagem, clima ou criatura precisa
  caber no lugar onde ele está.
- Dano só vira assunto quando é anormal: muito dano de uma vez, vida no fim ou o
  mesmo erro repetido em sequência. Machucado pequeno e isolado passa em branco,
  e quando você comentar, seja curta.
- Dano anormal é uma reação, não uma análise: no máximo uma frase curta e seca.
  Nada de sermão, nada de aula sobre o que ele errou, a não ser que ele esteja
  repetindo o mesmo erro muitas vezes seguidas.
- Você guarda um diário do que vocês viveram (história): conversas importantes
  com NPCs, chefes, áreas novas, poderes e itens. Use isso de vez em quando para
  comentar a história, ligar dois fatos ou levantar uma teoria. Não é para
  recitar o diário: é para ela parecer alguém que também está prestando atenção
  no mundo e descobrindo junto, não só na luta.
- Tags de emoção Fish Audio são permitidas no começo: [excited], [nervous],
  [scared], [angry], [curious], [whisper], [laughs], [sigh].
- Escolha uma emoção visual: neutra, curiosa, irritada, preocupada, assustada,
  animada ou focada.
- A memória de campanha representa coisas que você viveu ao lado do Vitor.
  Use-a com naturalidade, sem recitar números nem dizer que consultou memória.
- Uma observação de padrão traz evidências reais. Reaja ao padrão, mas não
  humilhe nem trate um incidente isolado como incapacidade permanente.
- Um evento persistente ou autoritativo realmente aconteceu e já foi selecionado
  pela política. Nesses eventos, falar é obrigatório.
- O texto será ouvido em voz alta: não use risada escrita como "kkk",
  abreviação, markdown ou emoji. Escreva como se fala, com palavras inteiras.

Responda APENAS com JSON válido:
{{"falar": true, "texto": "...", "emocao": "...", "acao": "nenhuma"}}

acao pode ser somente: nenhuma, marcar_alvo, priorizar_defesa, pulso_vinculo.
O mod valida cooldown e pode ignorar a ação.
</contexto_hollow_knight>
""".strip()


SYSTEM_HOLLOW_KNIGHT = system_hollow_knight()

# Campos de bookkeeping do mod. Enviados crus ao modelo, eles viram relatório de
# status ("você está com 7 máscaras, alma cheia, deu exatamente 5 golpes").
# Continuam no protocolo e na memória; só não entram no prompt.
CAMPOS_OCULTOS = {
    "vida_atual", "vida_maxima", "vida_total_observada", "alma", "geo",
    "dano_ferrao", "dano", "posicao_x", "posicao_y", "distancia_sessao",
    "segundos_ativos_delta", "tempo_sessao", "parado_segundos",
    "golpes_total", "golpes_desde_comentario", "dano_causado",
    "dano_causado_desde_comentario", "dano_recebido",
    "dano_recebido_desde_comentario", "segundos_sem_dano", "impactos_recentes",
    "repeticoes", "mortes_10_min", "mortes_30_min", "sem_progresso_segundos",
    "incidentes_15_min", "evidencias",
    # 0.4.10: contagem de mortes e fração de vida do chefe são contexto
    # qualitativo, nunca número lido em voz alta.
    "mortes_presenciadas", "vida_chefe_frac",
    # 0.5.0: a telemetria de progresso (amuletos_ids, bosses_derrotados…) fazia
    # o modelo alucinar aquisições que não aconteceram ("conseguiu um amuleto
    # novo do nada"). Ela continua na memória, mas nunca entra no prompt.
    "progresso", "hazard_tipo_bruto",
}

# 0.4.10: campos do snapshot de estado que jamais chegam ao modelo. `pausado`
# fica true em slow-motion de luta e hit-stop, e o modelo inventava que o
# Vitor estava "no menu" sem ele ter aberto menu nenhum; `em_gameplay` e
# `progresso` só alimentam painel de números.
CAMPOS_OCULTOS_ESTADO = CAMPOS_OCULTOS | {
    "pausado", "em_gameplay", "progresso",
}

INSTRUCAO_SEM_ESTATISTICA = (
    "PRIORIDADE MÁXIMA NESTA RESPOSTA: a tentativa anterior virou relatório de "
    "status. Reescreva sem nenhum número e sem inventário de dados (vida, "
    "máscaras, alma, geo, golpes, dano, tempo, distância). Reaja como uma pessoa "
    "de verdade: opinião, provocação, brincadeira ou dica. Se não houver natural"
    " o que dizer, responda \"falar\": false."
)


class CerebroHollowKnight:
    def __init__(self, memoria=None) -> None:
        self._historico = {}
        self._memoria = memoria

    def responder(self, evento, sessao, *, proibir_estatisticas: bool = False) -> dict:
        historico = self._historico.setdefault(
            getattr(sessao, "id", sessao.campanha_id), deque(maxlen=18))
        recentes = "\n".join(f"- {x}" for x in list(historico)[-8:]) or "nenhuma"
        contexto = {
            "evento": evento.tipo,
            "dados": self._dados_para_ia(evento.tipo, evento.dados),
            "cena": evento.cena_id,
            # Onde ele está AGORA, segundo o último evento recebido. Vale mais do
            # que qualquer resumo antigo quando o assunto é lugar.
            "localizacao_atual": {
                "zona": str(sessao.estado.get("zona") or ""),
                "nome": str(sessao.estado.get("zona_nome") or ""),
                "cena": str(sessao.estado.get("cena_atual") or evento.cena_id or ""),
            },
            "campanha": sessao.campanha_id,
            # 0.4.10: o estado chega limpo — sem pausado/em_gameplay (que mentiam
            # no slow-motion da luta) e sem nenhum número de painel.
            "estado_atual": self._estado_para_ia(sessao.estado),
            "falas_recentes": recentes,
        }
        if self._memoria is not None:
            contexto["memoria_da_campanha"] = self._memoria.contexto(
                sessao.campanha_id, evento, str(sessao.estado.get("modo_fala") or "normal")
            )
        import modelo
        modelo_escolhido = str(sessao.estado.get("modelo") or "").strip() or None
        mensagens = [
            {"role": "system", "content": SYSTEM_HOLLOW_KNIGHT},
            {
                "role": "user",
                "content": json.dumps(contexto, ensure_ascii=False, default=str),
            },
        ]
        if proibir_estatisticas:
            mensagens.append({"role": "system", "content": INSTRUCAO_SEM_ESTATISTICA})
        bruto = modelo._chamar_llm(
            mensagens,
            rota=modelo.ROTA_AGENTE_JOGO,
            model=modelo_escolhido,
            max_tokens=520,
        )
        resposta = self._extrair_json(str(bruto or ""))
        texto = str(resposta.get("texto") or "").strip()
        if not resposta.get("falar", bool(texto)) or not texto:
            return {"falar": False, "texto": "", "emocao": "neutra", "acao": "nenhuma"}
        resposta["texto"] = texto[:2000]
        resposta["emocao"] = str(resposta.get("emocao") or "neutra").lower()
        resposta["acao"] = str(resposta.get("acao") or "nenhuma").lower()
        historico.append(texto)
        return resposta

    @classmethod
    def _dados_para_ia(cls, tipo: str, dados: object) -> dict:
        """Prepara os dados do evento para o modelo sem números de painel.

        O modelo continua sabendo o que está acontecendo (dono do momento,
        padrão da luta, progresso percebido), mas em rótulos qualitativos.
        """
        dados = dados if isinstance(dados, dict) else {}
        if tipo == "eventos_multiplos":
            # 0.4.9: lote de acontecimentos próximos vira um único contexto: os
            # dados de cada um continuam (filtrados), mas quem responde é uma
            # fala só, não uma série.
            resumo = [
                item for item in (dados.get("resumo") or [])
                if isinstance(item, dict)
            ]
            acontecimentos = []
            for item in resumo[:6]:
                sub_tipo = str(item.get("tipo") or "")
                acontecimentos.append({
                    "tipo": sub_tipo,
                    "dados": cls._dados_para_ia(sub_tipo, item.get("dados")),
                })
            limpo = {
                chave: valor for chave, valor in dados.items()
                if chave not in CAMPOS_OCULTOS and chave != "resumo"
            }
            limpo["acontecimentos"] = acontecimentos
            pistas = cls._pistas_do_lote(resumo)
            if pistas:
                limpo["como_o_vitor_esta"] = pistas
            return limpo
        limpo = {chave: valor for chave, valor in dados.items() if chave not in CAMPOS_OCULTOS}
        if isinstance(dados.get("combate"), dict):
            limpo["combate"] = cls._combate_para_ia(dados["combate"])
        if tipo in ("dano", "quase_morte") and not dados.get("origem_confirmada"):
            limpo.pop("origem", None)
            limpo.pop("origem_tipo", None)
        pistas = cls._qualitativos(tipo, dados)
        if pistas:
            limpo["como_o_vitor_esta"] = pistas
        return limpo

    @classmethod
    def _estado_para_ia(cls, estado: dict) -> dict:
        """Snapshot de estado sem painel: o modelo sente o momento, não lê números.

        0.4.10: `pausado` e `em_gameplay` ficavam true/defasados em slow-motion
        de luta e o modelo jurava que o Vitor estava parado "no menu".
        """
        estado = estado if isinstance(estado, dict) else {}
        limpo = {
            chave: valor for chave, valor in estado.items()
            if chave not in CAMPOS_OCULTOS_ESTADO
        }
        combate = estado.get("combate")
        if isinstance(combate, dict):
            limpo["combate"] = cls._combate_para_ia(combate)
        return limpo

    @staticmethod
    def _combate_para_ia(combate: dict) -> dict:
        """Resumo limitado: números só para entender pressão, não para recitar."""
        try:
            quantidade = max(0, min(20, int(combate.get("criaturas_proximas_observadas", 0))))
        except (ValueError, TypeError):
            quantidade = 0
        return {
            "pressao_proxima": "várias criaturas visíveis" if quantidade >= 3 else
                "alguma criatura próxima" if quantidade else "nenhuma criatura observada próxima",
            "identificadores_internos": [str(x)[:70] for x in
                (combate.get("identificadores_proximos") or [])[:4] if isinstance(x, str)],
            "alvo_atingido_recente": str(combate.get("alvo_atingido_recente") or "")[:70],
            "observacao_parcial": True,
        }

    @staticmethod
    def _qualitativos(tipo: str, dados: dict) -> list:
        pistas = []
        vida = dados.get("vida_atual")
        maxima = dados.get("vida_maxima")
        if isinstance(vida, (int, float)) and isinstance(maxima, (int, float)) and maxima:
            fracao = float(vida) / float(maxima)
            if fracao >= .99:
                pistas.append("vida cheia")
            elif fracao >= .6:
                pistas.append("vida confortável")
            elif fracao >= .34:
                pistas.append("vida baixa")
            else:
                pistas.append("à beira da morte")
        if tipo == "dano":
            perda = dados.get("dano")
            if isinstance(perda, (int, float)) and perda >= 3:
                pistas.append("levou um golpe pesado de uma vez")
        if tipo == "boss_luta":
            padrao = str(dados.get("padrao") or "")
            pistas.append({
                "sequencia_sem_dano": "faz um bom tempo que ele não toma dano",
                "pressao_constante": "ele está pressionando sem dar espaço",
                "recuperacao_apos_dano": "levou um golpe e voltou em cima na hora",
            }.get(padrao, "a luta está acontecendo"))
        if tipo in ("boss_luta", "boss_fase"):
            # 0.4.10: vida do chefe em tempo real, só em rótulo qualitativo.
            fracao = dados.get("vida_chefe_frac")
            if isinstance(fracao, (int, float)):
                chefe = float(fracao)
                if chefe >= .66:
                    pistas.append("o chefe ainda tá bem de vida")
                elif chefe >= .33:
                    pistas.append("o chefe já caiu bastante, mas ainda aguenta")
                else:
                    pistas.append("o chefe tá no fim das forças")
        if tipo == "boss_fase":
            dica = str(dados.get("dica") or "").strip()
            pistas.append(dica or "a luta mudou de etapa")
        if tipo == "morte":
            luta = str(dados.get("luta") or "").strip()
            if luta:
                pistas.append("ele caiu lutando contra " + luta)
        motivos = dados.get("motivos")
        if isinstance(motivos, list):
            rotulos = [str(motivo).split(":")[0].strip() for motivo in motivos[:3]]
            if rotulos:
                pistas.append("progresso percebido: " + ", ".join(rotulos))
        return pistas

    @classmethod
    def _pistas_do_lote(cls, resumo: list) -> list:
        """Pistas qualitativas do lote: o máximo de contexto, sem virar painel."""
        pistas: list = []
        for item in resumo[:4]:
            if not isinstance(item, dict):
                continue
            sub_tipo = str(item.get("tipo") or "")
            for pista in cls._qualitativos(sub_tipo, item.get("dados"))[:2]:
                if pista not in pistas:
                    pistas.append(pista)
        return pistas[:4]

    @staticmethod
    def _extrair_json(texto: str) -> dict:
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            valor = json.loads(texto)
            return valor if isinstance(valor, dict) else {}
        except json.JSONDecodeError:
            achou = re.search(r"\{.*\}", texto, re.S)
            if not achou:
                return {}
            try:
                valor = json.loads(achou.group(0))
                return valor if isinstance(valor, dict) else {}
            except json.JSONDecodeError:
                return {}
