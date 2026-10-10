"""
laco_ferramentas.py — o motor que EXECUTA as ferramentas que o modelo pediu.

Por que esse arquivo existe
───────────────────────────
A Emily tinha CINCO laços de tool calling: conversa por voz (345 linhas),
administração do Discord (350), chat do jogo, e duas variantes de "obrigar
ferramenta". Cada um repetia a mesma mecânica — montar o turno do assistente com
os tool_calls, travar repetição idêntica, executar, devolver o resultado, decidir
se algo mudou.

Repetir não seria tão grave se as cópias fossem iguais. Elas DIVERGIRAM:

  - o laço de voz registrava o que foi executado pra lembrar no turno seguinte;
    o do Discord não registrava nada.
  - o laço do Discord decidia se a ação mudou algo no mundo (é o que alimenta a
    máquina de promessa); o de voz não decidia — qualquer ferramenta contava
    como ação.
  - o freio de repetição idêntica existia nos dois, com mensagens diferentes.

Ou seja: cada laço tinha metade dos consertos que o outro já tinha. Este módulo
é a mecânica, uma vez. A POLÍTICA de cada caminho (o que falar, quando obrigar
ferramenta, como emitir no TTS ou no chat, qual personalidade) fica no modelo.py,
onde ela pertence — porque ali as diferenças são de propósito.

O que ele NÃO faz
─────────────────
Não chama o modelo, não decide quantas voltas dar, não fala nada. Recebe as
chamadas que o modelo pediu, executa, e devolve o que aconteceu.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import ferramentas


# ═════════════════════════════════════════════════════════════════
# ASSINATURA DE CHAMADA — o freio de repetição
# ═════════════════════════════════════════════════════════════════

def assinatura_argumentos(argumentos_json: str) -> str:
    """
    Forma canônica dos argumentos, pra comparar duas chamadas.

    Compara o VALOR, não o texto: '{"a":1,"b":2}' e '{"b":2, "a":1}' são a mesma
    chamada, e sem normalizar o freio deixaria passar a repetição.
    """
    try:
        dados = json.loads(argumentos_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return (argumentos_json or "").strip()
    if isinstance(dados, dict):
        return json.dumps(dados, sort_keys=True, ensure_ascii=False)
    return json.dumps(dados, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════
# O QUE ACONTECEU COM UMA CHAMADA
# ═════════════════════════════════════════════════════════════════

@dataclass
class Execucao:
    """Uma chamada de ferramenta e o que saiu dela."""
    nome: str
    id_chamada: str
    argumentos: dict
    resultado: ferramentas.ResultadoFerramenta
    # A chamada foi barrada porque era idêntica a uma que já rodou neste turno.
    repetida: bool = False
    # A chamada era abrir_ferramentas: mexeu no catálogo, não no mundo.
    escalonou: bool = False

    @property
    def agiu(self) -> bool:
        """Mudou algo no mundo? Escalonar e repetir não contam."""
        if self.repetida or self.escalonou:
            return False
        return self.resultado.ok and self.resultado.mudou

    def mensagem(self) -> dict:
        """O turno 'tool' que volta pro modelo."""
        return {"role": "tool", "tool_call_id": self.id_chamada,
                "content": self.resultado.texto}


# ═════════════════════════════════════════════════════════════════
# PARALELISMO — deliberadamente conservador
#
# Ferramenta deste projeto quase sempre MEXE no computador do Vitor: abre app,
# move arquivo, clica, manda mensagem. Rodar duas dessas ao mesmo tempo é pedir
# pra duas threads disputarem o mouse, e a ordem em que ele pediu ("maximiza e
# depois clica") deixa de ser respeitada.
#
# Então o default é SEQUENCIAL, e paralelo é opt-in por ferramenta
# (Ferramenta.paralelizavel). Só entra aí ferramenta que:
#   1. só LÊ (não muda estado nenhum), e
#   2. gasta tempo esperando rede ou modelo — senão não há o que ganhar.
#
# Onde isso paga: "pesquisa quanto custa uma 5090 e olha o que tem na minha
# tela" hoje é 2s + 3s em série. Em paralelo é max(2s, 3s).
#
# A ordem do histórico é preservada de qualquer forma: o resultado volta na
# posição original, mesmo tendo sido executado fora de ordem.
# ═════════════════════════════════════════════════════════════════

# Quantas ferramentas paralelizáveis rodam de uma vez. Baixo de propósito: o
# limitador de taxa do llm.py é por rota, e disparar seis chamadas de visão
# juntas só faz cinco delas esperarem ficha com a thread parada.
MAX_PARALELAS = 3


def _pode_paralelizar(nome: str) -> bool:
    f = ferramentas.CATALOGO.get(nome)
    return bool(f and getattr(f, "paralelizavel", False))


# ═════════════════════════════════════════════════════════════════
# O MOTOR
# ═════════════════════════════════════════════════════════════════

class Motor:
    """
    Executa as ferramentas de um turno e guarda o que aconteceu.

    Um Motor por turno de conversa. Ele é dono de três coisas que antes viviam
    soltas em variáveis locais de cada laço:

      - o catálogo ativo (que muda quando um domínio é aberto)
      - as chamadas já executadas (o freio de repetição)
      - o veredito acumulado: usou ferramenta? mudou algo no mundo?
    """

    def __init__(
        self,
        catalogo: List[dict],
        rotulo: str = "MOTOR",
        abrir_dominio: Optional[Callable[[dict], str]] = None,
        recalcular_catalogo: Optional[Callable[[], List[dict]]] = None,
        registrar_acao: Optional[Callable[[str, dict, str], None]] = None,
        contexto_execucao: Optional[dict] = None,
    ):
        """
        catalogo            — o que está na mesa agora
        abrir_dominio       — trata abrir_ferramentas; None desliga o
                              escalonamento (é o caso do Discord e do jogo, que
                              já recebem o catálogo certo de fora)
        recalcular_catalogo — chamado depois de abrir um domínio, pra o motor
                              saber a nova mesa
        registrar_acao      — grava a ação pro turno seguinte lembrar
        """
        self.catalogo = list(catalogo)
        self.rotulo = rotulo
        self._abrir_dominio = abrir_dominio
        self._recalcular = recalcular_catalogo
        self._registrar_acao = registrar_acao
        self._contexto_execucao = dict(contexto_execucao or {})

        self.ja_executadas: Set[Tuple[str, str]] = set()
        self.execucoes: List[Execucao] = []
        self._revisao_navegador = 0

    # ── Veredito do turno ─────────────────────────────────────────

    @property
    def usou_ferramenta(self) -> bool:
        """Rodou alguma ferramenta de verdade? Escalonar não conta."""
        return any(not e.escalonou and not e.repetida for e in self.execucoes)

    @property
    def agiu(self) -> bool:
        """
        Mudou algo no mundo?

        É este booleano que a máquina de promessa lê. Quando ele mente pra
        'sim', o pedido do Vitor é marcado como cumprido e a cobrança do turno
        seguinte não acontece — o pedido morre calado. Por isso ele sai de
        ResultadoFerramenta.ok/mudou, que é fato, e não de reconhecer o
        português do resultado.
        """
        return any(e.agiu for e in self.execucoes)

    @property
    def ultimo_resultado(self) -> str:
        """Texto da última ferramenta que rodou de verdade."""
        for e in reversed(self.execucoes):
            if not e.escalonou:
                return e.resultado.texto or ""
        return ""

    @property
    def falhas(self) -> List[Execucao]:
        return [e for e in self.execucoes
                if not e.escalonou and not e.repetida and not e.resultado.ok]

    # ── Montagem do turno ─────────────────────────────────────────

    @staticmethod
    def mensagem_do_assistente(chamadas: Sequence, preambulo: str = "") -> dict:
        """
        O turno do assistente que PEDIU as ferramentas.

        O preâmbulo vai no content de propósito: se o turno do assistente for
        com content vazio, o modelo perde a própria frase e na volta seguinte
        repete o que já disse.
        """
        import base64

        tool_calls = []
        for c in chamadas:
            assinatura = getattr(c, "thought_signature", None)
            tool_calls.append({
                "id": c.id,
                "type": "function",
                "function": {"name": c.nome, "arguments": c.argumentos},
                "thought_signature": (base64.b64encode(assinatura).decode()
                                      if assinatura else None),
            })
        return {"role": "assistant", "content": preambulo or "",
                "tool_calls": tool_calls}

    # ── Execução ──────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        print(f"[{self.rotulo}] {msg}")

    def _barrar_repetida(self, c) -> Optional[Execucao]:
        """
        Barra só a chamada IDÊNTICA (mesmo nome E mesmos argumentos).

        Nome igual com argumento diferente é sequência legítima e passa: "abre o
        site A e o site B" precisa de abrir_site duas vezes. A versão antiga
        chaveava só pelo nome e fazia metade do pedido.
        """
        if c.nome in {"programacao_status", "programacao_ler", "programacao_buscar", "programacao_diff", "programacao_arquivos", "programacao_listar", "programacao_comparar", "programacao_atualizar", "programacao_resolver", "programacao_previa", "programacao_aplicar", "programacao_publicar"}:
            return None
        argumentos = assinatura_argumentos(c.argumentos)
        if c.nome == "programacao_executar" or (c.nome == "programacao_android" and c.args().get("operacao") == "compilar"):
            # Mesmo teste após corrigir a cópia é trabalho novo, não duplicação.
            try:
                import programacao
                folder, data = programacao.load(c.args().get("sessao"))
                argumentos = programacao.revision(folder, data) + ':' + argumentos
            except (OSError, ValueError, TypeError, KeyError):
                pass
        # A mesma leitura em uma página NOVA é uma ação diferente. Antes,
        # navegador_interno_ler({}) era barrado para o resto do turno após a
        # primeira visita, mesmo depois de abrir outro site.
        if c.nome in {"navegador_interno_ler", "navegador_interno_ver"}:
            argumentos = f"{self._revisao_navegador}:{argumentos}"
        elif (c.nome == "navegador_interno_interagir"
              and c.args().get("acao") in {"aguardar", "rolar"}):
            # Esperar ou rolar novamente depois que a página mudou é uma nova
            # observação/posição, não um duplo clique perigoso.
            argumentos = f"{self._revisao_navegador}:{argumentos}"
        assinatura = (c.nome, argumentos)
        if assinatura not in self.ja_executadas:
            self.ja_executadas.add(assinatura)
            return None

        self._log(f"'{c.nome}' com os mesmos argumentos já rodou neste turno, "
                  f"recusando repetição.")
        return Execucao(
            nome=c.nome, id_chamada=c.id, argumentos=c.args(), repetida=True,
            resultado=ferramentas.ResultadoFerramenta(
                texto=(f"Essa chamada de '{c.nome}' com esses mesmos argumentos "
                       f"já foi feita neste pedido. Se ainda falta alguma coisa "
                       f"do que foi pedido, chame a ferramenta certa pra isso; "
                       f"se não falta nada, responda agora."),
                ok=False, mudou=False, erro="repetida"),
        )

    def _escalonar(self, c) -> Execucao:
        """abrir_ferramentas: muda a mesa, não o mundo."""
        argumentos = c.args()
        texto = self._abrir_dominio(argumentos)
        if self._recalcular:
            self.catalogo = list(self._recalcular())
        return Execucao(nome=c.nome, id_chamada=c.id, argumentos=argumentos,
                        escalonou=True,
                        resultado=ferramentas.ResultadoFerramenta(
                            texto=texto, ok=True, mudou=False))

    def _executar_uma(self, c) -> Execucao:
        argumentos = c.args()
        if callable(self._contexto_execucao.get("autorizar_pedido")) and c.nome not in {
                item.get("function", {}).get("name") for item in self.catalogo}:
            return Execucao(nome=c.nome, id_chamada=c.id, argumentos=argumentos,
                resultado=ferramentas.ResultadoFerramenta(texto="Ferramenta fora do catálogo autorizado deste turno. Abra o domínio disponível ou escolha outro meio.", ok=False, mudou=False, erro="fora_do_catalogo"))
        resultado = ferramentas.executar_estruturado(
            c.nome, argumentos, contexto=self._contexto_execucao)
        if self._registrar_acao:
            try:
                self._registrar_acao(c.nome, argumentos, resultado.texto)
            except Exception as e:  # noqa: BLE001
                # Registro é memória, não ação. Se ele falhar, a ferramenta já
                # rodou — derrubar o turno aqui seria trocar um esquecimento por
                # uma falha visível.
                self._log(f"não consegui registrar a ação {c.nome}: {e}")
        return Execucao(nome=c.nome, id_chamada=c.id, argumentos=argumentos,
                        resultado=resultado)

    def executar(
        self,
        chamadas: Sequence,
        antes=None,
        depois=None,
    ) -> List[Execucao]:
        """
        Executa as chamadas de UMA resposta do modelo, na ordem pedida.

        antes(nome, argumentos)  — chamado antes de cada execução (aviso falado,
                                   painel de progresso)
        depois(nome, resultado)  — chamado depois de cada execução

        Devolve as execuções na ORDEM ORIGINAL, mesmo quando um trecho rodou em
        paralelo. Ordem é o que o Vitor percebe: ele pediu A e depois B.
        """
        pendentes = list(chamadas)
        saida: List[Execucao] = []

        i = 0
        while i < len(pendentes):
            c = pendentes[i]
            self._log(f"Ferramenta pedida: {c.nome}({c.argumentos})")

            barrada = self._barrar_repetida(c)
            if barrada is not None:
                saida.append(barrada)
                i += 1
                continue

            if c.nome == "abrir_ferramentas" and self._abrir_dominio:
                saida.append(self._escalonar(c))
                i += 1
                continue

            # Junta o trecho de chamadas paralelizáveis que começa aqui. Só
            # vale a pena se houver pelo menos duas: uma sozinha em thread é
            # overhead sem ganho.
            bloco = []
            j = i
            while j < len(pendentes) and _pode_paralelizar(pendentes[j].nome):
                if pendentes[j].nome == "abrir_ferramentas":
                    break
                bloco.append(pendentes[j])
                j += 1

            if len(bloco) >= 2:
                nomes = ", ".join(x.nome for x in bloco)
                self._log(f"rodando {len(bloco)} em paralelo: {nomes}")
                for x in bloco:
                    if antes:
                        antes(x.nome, x.args())
                with ThreadPoolExecutor(max_workers=min(MAX_PARALELAS, len(bloco))) as pool:
                    resultados = list(pool.map(self._executar_uma, bloco))
                for exec_ in resultados:
                    if depois:
                        depois(exec_.nome, exec_.resultado)
                saida.extend(resultados)
                i = j
                continue

            if antes:
                antes(c.nome, c.args())
            execucao = self._executar_uma(c)
            if (execucao.resultado.ok and execucao.resultado.mudou
                    and c.nome in {"navegador_interno_abrir", "navegador_interno_interagir"}):
                self._revisao_navegador += 1
            if depois:
                depois(execucao.nome, execucao.resultado)
            saida.append(execucao)
            i += 1

        self.execucoes.extend(saida)
        return saida

    def mensagens(self, execucoes: Sequence[Execucao]) -> List[dict]:
        """Os turnos 'tool' que voltam pro modelo, na ordem."""
        return [e.mensagem() for e in execucoes]




