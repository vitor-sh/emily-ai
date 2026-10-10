"""Fatiamento da resposta do modelo em frases faladas, em streaming.

_AcumuladorDeFrases recebe os deltas do LLM e solta frases completas numa fila
assim que fecham, pra o TTS começar a falar antes da resposta terminar.
_ParserRespostaCall faz o mesmo para o JSON da call de voz, liberando frases
só depois de "responder": true. Saiu de modelo.py, que re-exporta os dois.
"""
from __future__ import annotations

import json
import queue
import re

from fish_voz_texto import DirecaoDaFala


class _ParserRespostaCall:
    """Máquina de estados do JSON da call, alimentada pelos chunks do stream.

    É o que permite falar ANTES do JSON fechar: cada frase completa do campo
    "resposta" é liberada no instante em que o modelo a termina, e o TTS da
    call começa enquanto o resto ainda está sendo gerado.

    FRASE SÓ SAI DEPOIS de aparecer `"responder": true` no buffer — nada é
    falado que a decisão depois desmentiria. Se vier `false`, nada sai e o
    caminho legado (que nunca tocou nada) segue idêntico ao de antes.
    """

    _RE_DECISAO = re.compile(r'"responder"\s*:\s*(true|false)', re.I)
    _RE_ABRE_RESPOSTA = re.compile(r'"resposta"\s*:\s*"', re.I)

    # Teto de streaming: a fala da call é curta por natureza (o prompt pede
    # e o encurtar_para_call frearia no legado). Depois disso o resto vira
    # detalhe_texto no chat — mesmo comportamento do caminho antigo.
    MAX_FRASES = 4
    MAX_CHARS = 420

    def __init__(self, ao_decidir, ao_frase):
        self._ao_decidir = ao_decidir
        self._ao_frase = ao_frase
        self._buffer = ""
        self._decidido = None
        self._em_resposta = False
        self._fechado = False
        self._bruto = ""          # valor do campo resposta, com escapes
        self._decodificado = ""   # valor já convertido, acumulado
        self._frases = []
        # Reusa o MESMO acumulador do chat/voz: frase fecha em pontuação e a
        # primeira cláusula curta sai cedo — é o que faz a voz começar logo.
        self._fila_interna = queue.Queue()
        self._acumulador = _AcumuladorDeFrases(self._fila_interna)

    @staticmethod
    def _decodificar_seguro(bruto: str) -> str:
        """Converte o pedaço de valor JSON (sem aspas) pra texto real.

        O fim do bruto pode cair no meio de um escape ('\\', '\\u00e') e o
        json.loads reclama; aí corta até antes da última barra — o resto
        volta no próximo chunk. Nunca levanta: parse incremental não pode
        derrubar a resposta inteira por causa de um pedaço pendente.
        """
        tentativa = bruto
        while tentativa:
            try:
                return json.loads('"' + tentativa + '"')
            except Exception:
                barra = tentativa.rfind("\\")
                if barra < 0:
                    return tentativa
                tentativa = tentativa[:barra]
        return ""

    def _drenar_fila(self) -> None:
        # Não confere _fechado aqui de propósito: o dreno FINAL acontece
        # DEPOIS de fechar (senão a última frase nunca sairia). O teto de
        # frases abaixo já basta pra parar no limite.
        while True:
            try:
                frase = self._fila_interna.get_nowait()
            except queue.Empty:
                return
            if not frase or not frase.strip():
                continue
            if len(self._frases) >= self.MAX_FRASES:
                self._fechado = True
                return
            self._frases.append(frase)
            try:
                self._ao_frase(frase)
            except Exception as erro:
                print(f"[Modelo] callback de frase falhou: {erro}")

    def _fechar_valor(self, bruto_final: str) -> None:
        """Fim do valor da resposta: solta o rabo e para de processar."""
        texto = self._decodificar_seguro(bruto_final)
        delta = texto[len(self._decodificado):]
        if delta:
            self._decodificado = texto
            self._acumulador.adicionar(delta)
        self._fechado = True
        self._acumulador.finalizar()
        self._drenar_fila()

    def _processar_valor(self, bruto_novo: str) -> None:
        self._bruto += bruto_novo
        # Aspa de fechamento: a primeira NÃO escapada TERMINA o valor. O que
        # vem depois dela é o resto do JSON ('detalhe_texto' etc.) e nunca
        # pode virar fala.
        fim = None
        for i, ch in enumerate(self._bruto):
            if ch == '"':
                antes = self._bruto[:i]
                if (not antes.endswith("\\")) or antes.endswith("\\\\"):
                    fim = i
                    break
        if fim is not None:
            self._fechar_valor(self._bruto[:fim])
            return
        if len(self._frases) >= self.MAX_FRASES:
            self._fechado = True
            return
        texto = self._decodificar_seguro(self._bruto)
        delta = texto[len(self._decodificado):]
        if not delta:
            return
        if len(self._decodificado) + len(delta) > self.MAX_CHARS:
            self._fechado = True
            return
        self._decodificado = texto
        self._acumulador.adicionar(delta)
        self._drenar_fila()

    def alimentar(self, pedaco: str) -> None:
        if self._fechado or not pedaco:
            return
        self._buffer += pedaco
        if self._decidido is None:
            m = self._RE_DECISAO.search(self._buffer)
            if not m:
                return
            self._decidido = m.group(1).lower() == "true"
            try:
                self._ao_decidir(self._decidido)
            except Exception as erro:
                print(f"[Modelo] callback de decisão falhou: {erro}")
            if not self._decidido:
                return
        if not self._em_resposta:
            m = self._RE_ABRE_RESPOSTA.search(self._buffer)
            if not m:
                return
            self._em_resposta = True
            sobra = self._buffer[m.end():]
            self._buffer = ""
            self._processar_valor(sobra)
            return
        self._processar_valor(pedaco)

    def finalizar(self) -> None:
        """Fim do stream: fecha o valor aberto e solta o rabo da frase."""
        if self._fechado:
            return
        if self._decidido is None:
            # Nem decidiu (resposta quebrada/cortada): o caminho legado cuida
            # do texto completo; nada saiu por aqui.
            self._fechado = True
            return
        if self._em_resposta:
            # Stream cortou antes da aspa de fechamento: o que acumulou é fala.
            self._fechar_valor(self._bruto)
        else:
            self._fechado = True

    @property
    def frases(self) -> list:
        return list(self._frases)


# Era 160 junto de corte em TODA vírgula após só 42 caracteres. Isso criava
# muitos áudios de 1–2 segundos; cada item custa uma requisição separada ao Fish
# Audio e o tocador alcançava o gerador, ficando mudo enquanto a próxima
# requisição terminava. 220 dá tempo para o áudio atual cobrir a síntese do
# seguinte sem transformar parágrafo sem pontuação numa unidade gigante.
_MAX_CHARS_SEM_PONTUACAO = 220


class _AcumuladorDeFrases:
    """
    Junta os pedaços do stream e entrega ao TTS só frases completas.

    Isso é obrigatório, não é otimização: o voz.falar_stream faz UMA
    requisição de TTS por item da fila. Enfileirar delta cru do modelo
    ("espe", "rou", "qu", "e") gera um áudio por fragmento, e a Emily sai
    falando picado e ininteligível, com o texto quebrado no meio das
    palavras. O conversar_stream original já acumulava por frase; o laço de
    ferramentas tinha perdido esse cuidado.
    """

    # Frases curtas demais são o pior dos dois mundos no Fish: levam quase o
    # mesmo overhead de rede de uma frase normal e acabam de tocar antes de a
    # próxima ficar pronta. Reticências curtas eram especialmente ruins:
    # "É, eu imagino..." virava um áudio isolado e a voz freiava logo depois.
    _SEPARADORES = ".!?\n"
    # Vírgula NÃO fecha unidade: fala natural usa muitas, e cada corte é uma
    # requisição Fish separada. Ponto-e-vírgula/dois-pontos só antecipam a
    # primeira unidade quando ela já tem corpo suficiente.
    _SEPARADORES_CLAUSULA = ";:"
    _MIN_CHARS_FRASE = 52
    # Uma cláusula longa ainda pode liberar SOMENTE a primeira fala cedo. Depois
    # disso, esperar ponto final produz unidades maiores e mantém o prefetch do
    # TTS à frente do player em vez de abrir uma requisição a cada vírgula.
    # 64 mantém o início rápido numa oração já substancial (o comportamento
    # histórico do stream) e, combinado com _MIN_CHARS_FRASE=52, impede o corte
    # patológico em "É, eu imagino...". A primeira unidade costuma ficar entre
    # 70–130 caracteres: áudio suficiente para cobrir o prefetch da próxima.
    _MIN_CHARS_PRIMEIRA_CLAUSULA = 64

    def __init__(self, fila_frases, on_delta=None):
        self.fila = fila_frases
        self.buffer = ""
        self.on_delta = on_delta
        self._enfileiradas = 0
        self._direcao_fish = DirecaoDaFala()

    @staticmethod
    def _comprimento_falavel(texto: str) -> int:
        """Caracteres de fala, sem contar tags de entonação do Fish."""
        sem_tags = re.sub(r"\[[^\]\r\n]{1,80}\]", "", texto or "")
        return sum(1 for c in sem_tags if c.isalnum())

    def _enfileirar(self, texto: str) -> None:
        texto = texto.strip()
        # Trecho só de pontuação não é frase. Sem esse filtro, "mano... ou
        # zoando" virava três itens de fila, sendo dois só o caractere ".", e
        # cada um custava uma requisição de TTS.
        if not any(c.isalnum() for c in texto):
            return
        if self.fila is not None:
            texto_fala = self._direcao_fish.aplicar(texto)
            if texto_fala:
                self.fila.put(texto_fala)
        self._enfileiradas += 1

    def _proximo_corte(self) -> int:
        """
        Posição do primeiro separador que realmente fecha uma frase.

        Ponto entre dígitos NÃO fecha frase: "PCIe 5.0" era cortado em
        "PCIe 5." + "0 pra aproveitar", e o TTS lia os dois pedaços como
        coisas separadas. Mesmo problema com "R$ 2.500" e "versão 3.11".
        """
        em_tag = False
        for i, ch in enumerate(self.buffer):
            if ch == "[":
                em_tag = True
            elif ch == "]":
                em_tag = False
            if em_tag:
                continue
            if ch not in self._SEPARADORES + self._SEPARADORES_CLAUSULA:
                continue
            if ch in self._SEPARADORES_CLAUSULA:
                # Depois que a primeira unidade já saiu, vírgula não corta mais:
                # o áudio seguinte fecha em ponto e fica longo o bastante para a
                # síntese da próxima unidade acontecer durante a reprodução.
                if self._enfileiradas:
                    continue
                if self._comprimento_falavel(self.buffer[:i]) < self._MIN_CHARS_PRIMEIRA_CLAUSULA:
                    continue
                # Não corte em horário/razão ("10:30") nem sem o caractere
                # seguinte disponível; espere mais um delta para decidir.
                if ch == ":" and i > 0 and self.buffer[i - 1].isdigit():
                    if i == len(self.buffer) - 1 or self.buffer[i + 1].isdigit():
                        continue
                if i == len(self.buffer) - 1:
                    return -1
            if ch == "." and i > 0 and self.buffer[i - 1].isdigit():
                if i == len(self.buffer) - 1:
                    # Ainda não chegou o caractere seguinte: não dá pra saber
                    # se é fim de frase ou decimal. Espera o próximo pedaço.
                    return -1
                if self.buffer[i + 1].isdigit():
                    continue
            if ch == ".":
                # Só o ÚLTIMO ponto da reticência pode fechar a unidade.
                if i + 1 < len(self.buffer) and self.buffer[i + 1] == ".":
                    continue
            # Não gere áudio minúsculo no começo de uma resposta longa. Se a
            # resposta inteira for curta, finalizar() a entrega imediatamente no
            # fim do stream; esta espera só agrupa pontuação precoce com o trecho
            # seguinte que já está chegando.
            if self._comprimento_falavel(self.buffer[:i]) < self._MIN_CHARS_FRASE:
                if i == len(self.buffer) - 1:
                    return -1
                continue
            return i
        return -1

    def adicionar(self, pedaco: str) -> None:
        if not pedaco:
            return
        if self.on_delta:
            try:
                self.on_delta(pedaco)
            except Exception as e:
                print(f"[MODELO] Falha ao publicar delta visual: {e}")
        self.buffer += pedaco

        # Solta cada frase completa que já fechou.
        while True:
            corte = self._proximo_corte()
            if corte == -1:
                break
            # Engole a pontuação repetida que vem junto ("...", "!!", "?!"),
            # senão a reticência viraria uma "frase" só de pontos.
            fim = corte + 1
            while fim < len(self.buffer) and self.buffer[fim] in self._SEPARADORES:
                fim += 1
            self._enfileirar(self.buffer[:fim])
            self.buffer = self.buffer[fim:]

        # Frase muito longa sem pontuação: solta no último espaço.
        if self._comprimento_falavel(self.buffer) >= _MAX_CHARS_SEM_PONTUACAO:
            espaco = self.buffer.rfind(" ")
            aberto = self.buffer.rfind("[", 0, espaco)
            fechado = self.buffer.rfind("]", 0, espaco)
            if aberto > fechado:
                espaco = self.buffer.rfind(" ", 0, aberto)
            if espaco > 0:
                self._enfileirar(self.buffer[:espaco])
                self.buffer = self.buffer[espaco + 1:]

    def finalizar(self) -> None:
        self._enfileirar(self.buffer)
        self.buffer = ""
