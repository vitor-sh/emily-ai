"""Partida local de xadrez: Sol escolhe lances e conversa em chamadas paralelas.

As regras são do chess.js empacotado na interface. A ponte recebe somente
posições já validadas por esse motor; sugestões nunca são aplicadas sem nova
validação lá. Nenhuma chamada altera a rota, histórico ou tarefas do chat.
"""
from __future__ import annotations

import copy
import json
import re
import random
import threading
import time
import uuid
from pathlib import Path

UCI = re.compile(r"[a-h][1-8][a-h][1-8][qrbn]?")


def chamar_modelo(mensagens, *, lance=False, retry=None):
    import llm
    return llm.chamar(
        mensagens, provedor="openai", modelo="cx/gpt-6-sol",
        raciocinio="medio" if lance else "baixo", max_tokens=8192 if lance else 2048,
        stream=False, on_retry=retry,
    )


class Partida:
    def __init__(self, caminho=None, chamar=chamar_modelo, apoio=None, analise=None):
        if caminho is None:
            from emily_paths import arquivo_dados
            caminho = arquivo_dados("xadrez_partida.json")
        self.caminho = Path(caminho)
        self.chamar = chamar
        if apoio is None and chamar is chamar_modelo:
            from xadrez_stockfish import consultar
            apoio = consultar
        self.apoio = apoio
        if analise is None and chamar is chamar_modelo:
            from xadrez_stockfish import contexto_conversa
            analise = contexto_conversa
        self.analise = analise
        self.lock = threading.RLock()
        self.dados = {"id": uuid.uuid4().hex, "revisao": 0, "posicao": None,
                      "mensagens": [], "lance": {"estado": "pronto"},
                      "conversa": {"estado": "pronto"}, "voz": False, "dificuldade": "casual"}
        self.worker_lance = None
        self.worker_chat = None
        self.worker_comentario = None
        self.fila_voz = []  # Fila compartilhada por texto e voz, em ordem de chegada.
        self.chat_serial = 0
        self.chat_ocupado = False
        self.comentario_pendente = None
        self.comentario_tentado = None
        self.dados['comentarios'] = {'ultimo': 0, 'intervalo': random.randint(6, 10)}
        self.lock_voz = threading.Lock()
        try:
            salvo = json.loads(self.caminho.read_text(encoding="utf-8"))
            if isinstance(salvo, dict) and salvo.get("posicao"):
                salvo["posicao"] = self._posicao(salvo["posicao"])
                if (not isinstance(salvo.get("id"), str) or not isinstance(salvo.get("revisao"), int)
                        or not isinstance(salvo.get("mensagens"), list)
                        or any(not isinstance(m, dict) or m.get("role") not in {"user", "assistant"}
                               or not isinstance(m.get("content"), str) for m in salvo["mensagens"])
                        or any(not isinstance(salvo.get(k), dict) for k in ("lance", "conversa"))):
                    raise ValueError("Partida salva inválida.")
                self.dados.update(salvo)
                if self.dados.get('dificuldade') not in {'casual','equilibrado','desafiador','sol'}:
                    self.dados['dificuldade']='casual'
                meta = self.dados.get("comentarios", {})
                self.dados["comentarios"] = {"ultimo": max(0, int(meta.get("ultimo", 0))),
                    "intervalo": max(6, min(10, int(meta.get("intervalo", 8)))),
                    "quando": float(meta.get("quando", 0))}
                for mensagem in self.dados['mensagens']:
                    if not isinstance(mensagem.get('pedido_id', 0), int):
                        mensagem['pedido_id'] = 0
                # Uma requisição de outra execução não pode estar ativa agora.
                for chave in ("lance", "conversa"):
                    if self.dados[chave].get("estado") in {"pensando", "reconectando", "preparando"}:
                        self.dados[chave] = {"estado": "erro", "erro":
                            "A Emily fechou durante a resposta. Você pode tentar novamente."}
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError):
            self.dados["aviso"] = "Não consegui recuperar a partida salva. Comece uma nova partida."
        self.chat_serial = max((m.get('pedido_id', 0) for m in self.dados['mensagens']
                                if isinstance(m.get('pedido_id', 0), int)), default=0)

    def _salvar(self):
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario = self.caminho.with_suffix(".tmp")
        temporario.write_text(json.dumps(self.dados, ensure_ascii=False), encoding="utf-8")
        temporario.replace(self.caminho)

    def estado(self):
        with self.lock:
            return copy.deepcopy(self.dados)

    @staticmethod
    def _posicao(posicao):
        if not isinstance(posicao, dict):
            raise ValueError("Posição inválida.")
        fen, pgn = posicao.get("fen", ""), posicao.get("pgn", "")
        if not isinstance(fen, str) or len(fen) > 150 or len(fen.split()) != 6:
            raise ValueError("Tabuleiro inválido.")
        if not isinstance(pgn, str) or len(pgn) > 100000:
            raise ValueError("Histórico inválido.")
        legais = posicao.get("legais", [])
        if not isinstance(legais, list) or len(legais) > 256:
            raise ValueError("Lista de lances inválida.")
        for item in legais:
            if (not isinstance(item, dict) or not UCI.fullmatch(str(item.get("uci", "")))
                    or not isinstance(item.get("san"), str) or len(item["san"]) > 20):
                raise ValueError("Lance inválido.")
        if posicao.get("cor") not in {"w", "b"} or posicao.get("turno") not in {"w", "b"}:
            raise ValueError("Cor inválida.")
        fatos = posicao.get('fatos', {})
        if not isinstance(fatos, dict) or len(json.dumps(fatos)) > 16000:
            raise ValueError('Descrição da partida inválida.')
        if fatos and (not isinstance(fatos.get('meios_lances'), int) or fatos['meios_lances'] < 0
                      or not isinstance(fatos.get('ultimos_lances'), list)
                      or len(fatos['ultimos_lances']) > 6
                      or any(not isinstance(m, dict) for m in fatos['ultimos_lances'])):
            raise ValueError('Acontecimentos da partida inválidos.')
        return {"fen": fen, "pgn": pgn, "legais": copy.deepcopy(legais), 'fatos': copy.deepcopy(fatos),
                "cor": posicao["cor"], "turno": posicao["turno"],
                "fim": bool(posicao.get("fim")), "resultado": str(posicao.get("resultado", ""))[:200]}

    def sincronizar(self, posicao, revisao, nova=False):
        posicao = self._posicao(posicao)
        with self.lock:
            if int(revisao) != self.dados["revisao"]:
                return {"ok": False, "erro": "A partida mudou. Atualizando o tabuleiro.", "estado": self.estado()}
            if nova:
                self.dados["id"] = uuid.uuid4().hex
                self.dados["mensagens"] = []
                self.dados["conversa"] = {"estado": "pronto"}
                self.dados['comentarios'] = {'ultimo': 0, 'intervalo': random.randint(6, 10)}
                self.comentario_tentado = None
                self.comentario_pendente = None
                self.fila_voz.clear()
            elif self.dados['posicao'] and posicao['fatos'].get('meios_lances', 0) < self.dados['posicao']['fatos'].get('meios_lances', 0):
                self.dados['comentarios'] = {'ultimo': posicao['fatos'].get('meios_lances', 0), 'intervalo': random.randint(6, 10)}
            anterior = self.dados['posicao']
            if (not nova and anterior and
                    posicao['fatos'].get('meios_lances', 0) == anterior['fatos'].get('meios_lances', 0) + 1 and
                    posicao['fatos'].get('fen_antes_ultimo_lance') == anterior['fen']):
                recentes = copy.deepcopy(anterior['fatos'].get('avaliacoes_recentes', []))
                avaliacao = anterior['fatos'].get('avaliacao_ultimo_lance')
                if avaliacao:
                    registro = {**avaliacao, 'meio_lance': anterior['fatos'].get('meios_lances', 0)}
                    if not recentes or recentes[-1] != registro:
                        recentes.append(registro)
                if recentes:
                    posicao['fatos']['avaliacoes_recentes'] = recentes[-3:]
            self.dados["posicao"] = posicao
            self.dados["revisao"] += 1
            self.dados["lance"] = {"estado": "pronto"}
            self._salvar()
            return {"ok": True, "estado": self.estado()}

    def escolher_lance(self, revisao):
        with self.lock:
            if int(revisao) != self.dados["revisao"]:
                return {"ok": False, "erro": "Essa posição já mudou."}
            p = self.dados["posicao"]
            if not p or p["fim"] or p["turno"] == p["cor"] or not p["legais"]:
                return {"ok": False, "erro": "Agora não é a vez da Emily."}
            # Nova partida não dispara chamadas ilimitadas enquanto a anterior
            # ainda termina no provedor. A interface pode tentar depois.
            if self.worker_lance and self.worker_lance.is_alive():
                return {"ok": True, "ocupado": True}
            if self.dados["lance"]["estado"] == "escolhido":
                return {"ok": True}
            token = (self.dados["id"], self.dados["revisao"])
            self.dados["lance"] = {"estado": "pensando", "inicio": time.time()}
            self._salvar()
            self.worker_lance = threading.Thread(target=self._calcular, args=(token, copy.deepcopy(p), self.dados['dificuldade']), daemon=True)
            self.worker_lance.start()
            return {"ok": True}

    def dificuldade(self, nivel):
        if nivel not in {'casual','equilibrado','desafiador','sol'}:
            raise ValueError('Dificuldade desconhecida.')
        with self.lock:
            if nivel != self.dados['dificuldade']:
                self.dados['dificuldade']=nivel
                self.dados['revisao']+=1  # Descartar uma sugestão calculada com a dificuldade anterior.
                self.dados['lance']={'estado':'pronto'}
                self._salvar()
            return {'ok':True,'estado':self.estado()}

    def atualizar_contexto(self, posicao, revisao):
        posicao = self._posicao(posicao)
        with self.lock:
            atual = self.dados['posicao']
            if (int(revisao) != self.dados['revisao'] or not atual or
                    any(atual[k] != posicao[k] for k in ('fen', 'pgn', 'cor', 'turno'))):
                return {'ok':False,'erro':'O tabuleiro mudou. Atualize antes de conversar.','estado':self.estado()}
            atual['fatos'].update(posicao['fatos'])
            self._salvar()
            return {'ok':True,'estado':self.estado()}

    def _atual(self, token):
        return token == (self.dados["id"], self.dados["revisao"])

    def _calcular(self, token, posicao, nivel=None):
        inicio = time.monotonic()
        mensagens = [{"role": "system", "content":
            "Você escolhe um lance de xadrez para a Emily. Analise ameaças, segurança do rei, "
            "material, desenvolvimento e táticas. A posição fornecida é a fonte de verdade. "
            "Escolha EXATAMENTE um UCI da lista de lances legais. Responda apenas JSON: "
            '{"uci":"e2e4"}. Não use ferramentas nem converse com o jogador.'},
            {"role": "user", "content": json.dumps(posicao, ensure_ascii=False)}]
        def retry(tentativa, total):
            with self.lock:
                if self._atual(token):
                    self.dados["lance"].update(estado="reconectando", tentativa=tentativa, total=total)
        try:
            legais = {m["uci"] for m in posicao["legais"]}
            if self.apoio and nivel != 'sol':
                def cancelado():
                    with self.lock: return not self._atual(token)
                def avisar(texto):
                    with self.lock:
                        if self._atual(token):
                            self.dados['lance'].update(estado='preparando',detalhe=texto)
                apoio = self.apoio(posicao, nivel or 'casual', avisar, cancelado)
                legais &= set(apoio['candidatos'])
                if not legais: raise ValueError('O apoio não encontrou opções legais para essa posição.')
                posicao['legais'] = [m for m in posicao['legais'] if m['uci'] in legais]
                posicao['apoio_tatico'] = apoio['descricao']
                mensagens[-1]['content'] = json.dumps(posicao, ensure_ascii=False)
                with self.lock:
                    if not self._atual(token): return
                    self.dados['lance'].update(estado='pensando',detalhe='Sol escolhendo entre as opções verificadas…')
                    if apoio.get('avaliacao'):
                        self.dados['posicao']['fatos']['avaliacao_ultimo_lance']=apoio['avaliacao']
            escolhido = None
            for _ in range(2):
                with self.lock:
                    if not self._atual(token):
                        return
                texto = str(self.chamar(mensagens, lance=True, retry=retry)).strip()
                try:
                    obj = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", texto))
                    candidato = obj.get("uci") if isinstance(obj, dict) else None
                except ValueError:
                    candidato = texto if UCI.fullmatch(texto) else None
                if candidato in legais:
                    escolhido = candidato
                    break
                mensagens.extend([{"role": "assistant", "content": texto[:2000]},
                    {"role": "user", "content": "Resposta inválida. Escolha um UCI da lista e devolva somente o JSON solicitado."}])
            if not escolhido:
                raise ValueError("O Sol não devolveu um lance legal após duas tentativas. O tabuleiro foi preservado.")
            with self.lock:
                if self._atual(token):
                    self.dados["lance"] = {"estado": "escolhido", "uci": escolhido,
                        "revisao": token[1], "segundos": round(time.monotonic() - inicio, 2)}
                    self._salvar()
        except Exception as exc:
            self._erro("lance", token, exc)

    def _erro(self, chave, token, exc):
        import llm
        erro = str(exc) if isinstance(exc, ValueError) else llm.descrever_erro(exc)
        with self.lock:
            if (self._atual(token) if chave == "lance" else token[0] == self.dados["id"]):
                self.dados[chave] = {"estado": "erro", "erro": erro}
                self._salvar()
        print(f"[Xadrez] {chave}: {type(exc).__name__}")

    def conversar(self, texto, voz=False, origem='texto'):
        texto = str(texto).strip()
        if not texto or len(texto) > 8000:
            return {"ok": False, "erro": "Escreva uma mensagem de até 8.000 caracteres."}
        with self.lock:
            if not self.dados["posicao"]:
                return {"ok": False, "erro": "Comece uma partida primeiro."}
            ocupado = self.chat_ocupado
            if ocupado and len(self.fila_voz) >= 8:
                return {"ok": False, "erro": "Há muitas mensagens aguardando. Aguarde uma resposta antes de enviar outra."}
            token = (self.dados["id"], self.dados["revisao"])
            self.chat_serial += 1  # A mensagem do jogador tem prioridade sobre comentários.
            mesclar = self.comentario_pendente == token or self._comentario_devido()
            self.dados['comentarios'] = {'ultimo': self.dados['posicao']['fatos'].get('meios_lances', 0), 'intervalo': random.randint(6, 10), 'quando': time.time()}
            self.dados["mensagens"].append({"role": "user", "content": texto, 'origem': origem, 'pedido_id': self.chat_serial})
            self.dados["mensagens"] = self.dados["mensagens"][-100:]
            self.dados.pop("aviso_voz", None)
            self.dados["conversa"] = {"estado": "pensando"}
            self.dados["voz"] = bool(voz)
            self._salvar()
            contexto = copy.deepcopy(self.dados)
            contexto['pedido'] = texto
            contexto['origem'] = origem
            contexto['pedido_id'] = self.chat_serial
            contexto['mesclar_comentario'] = mesclar
            if ocupado:
                self.fila_voz.append((token, contexto))
                return {'ok': True, 'enfileirada': True}
            self.chat_ocupado = True
            self.worker_chat = threading.Thread(target=self._conversar, args=(token, contexto), daemon=True)
            self.worker_chat.start()
            return {"ok": True}

    def comentar(self, revisao):
        """Chamado pela tela aberta: sem cronômetro ou chamadas duplicadas."""
        with self.lock:
            if int(revisao) != self.dados['revisao']:
                return {'ok': True}
            p = self.dados['posicao']
            if not p or not p['fatos']:
                return {'ok': True}
            fatos = p['fatos']; ply = fatos.get('meios_lances', 0)
            if not isinstance(ply, int) or ply <= 0:
                return {'ok': True}
            meta = self.dados['comentarios']
            token = (self.dados['id'], self.dados['revisao'])
            if (ply <= meta['ultimo'] or self.comentario_tentado == token
                    or not self._comentario_devido()
                    or self.chat_ocupado
                    or (self.worker_comentario and self.worker_comentario.is_alive())):
                return {'ok': True}
            self.comentario_tentado = token
            self.comentario_pendente = token
            contexto = copy.deepcopy(self.dados)
            serial = self.chat_serial
            self.worker_comentario = threading.Thread(target=self._conversar, args=(token, contexto, True, serial), daemon=True)
            self.worker_comentario.start()
            return {'ok': True}

    def _comentario_devido(self):
        """Intervalo em jogadas individuais e tempo: capturas não geram rajadas."""
        p = self.dados['posicao']
        if not p or not p['fatos']:
            return False
        meta = self.dados['comentarios']
        ply = p['fatos'].get('meios_lances', 0)
        relevante = any(m.get('captura') or m.get('promocao')
                        for m in p['fatos'].get('ultimos_lances', [])[-1:])
        return ply > meta['ultimo'] and (p['fim'] or
            (time.time() - meta.get('quando', 0) >= 20 and
             (ply - meta['ultimo'] >= meta['intervalo'] or
              (relevante and ply - meta['ultimo'] >= 4))))

    @staticmethod
    def mensagens_conversa(contexto, automatico=False):
        from personalidade_emily import EMILY_PERSONALIDADE
        p = contexto["posicao"]
        ultimo = p.get('fatos', {}).get('ultimos_lances', [])[-1:]
        evento = ''
        if ultimo:
            m = ultimo[0]
            evento = f"{m.get('ator')} moveu {m.get('peca')} de {m.get('origem')} para {m.get('destino')}."
            if m.get('captura'):
                evento += f" Capturou {m['captura'].get('peca')} de {m['captura'].get('dono')}."
            if m.get('roque'):
                evento += f" Fez roque {m['roque']}."
            if m.get('promocao'):
                evento += f" Promoveu para {m['promocao']}."
            if m.get('xeque'):
                evento += ' Deu xeque-mate.' if m.get('mate') else ' Deu xeque.'
        sistema = EMILY_PERSONALIDADE + "\nVocê está jogando uma partida casual de xadrez com o usuário. "
        sistema += ("Converse naturalmente, com sua personalidade habitual. O Sol calcula os lances "
            "em outra chamada independente. Nesta conversa você NÃO escolhe nem executa lances. Comente apenas fatos verificáveis "
            "da posição; não invente planos ou justificativas do Sol, avaliações numéricas ou rating. "
            "Use fatos.tatico para responder sobre capturas e promoções: só sugira capturar com uma peça "
            "se de/para/peça corresponderem a uma captura legal listada. Não invente um bispo defensor. "
            "A vez é explicitamente fatos.tatico.vez: Você significa o humano, Emily significa você. "
            "Não troque quem joga agora nem afirme que uma promoção pode ser feita fora da vez. "
            "Sugestões antigas do histórico podem estar erradas ou desatualizadas: verifique novamente "
            "no snapshot atual. Se você errou antes, reconheça em vez de repetir a sugestão impossível. "
            "Se não houver solução verificada, admita que não encontrou defesa; não diga que é só capturar. "
            "Peão perto de promover não significa promoção garantida. Diferencie ataque geométrico e captura legal. "
            "IMPORTANTÍSSIMO: 'não posso pegar' numa conversa de xadrez geralmente significa 'perderia material', "
            "não que o movimento seja ilegal. Distinga legalidade de qualidade. Antes de sugerir ou lembrar uma "
            "captura, confira recapturas_legais, saldo_material_se_recapturada, risco_perda_material_imediata "
            "e as avaliacoes_capturas do motor, inclusive lances fora das melhores variantes. Se a dama captura "
            "um bispo e pode ser recapturada, diga claramente que pode custar a dama; não ofereça isso como saída. "
            "A perda material imediata é parcial: pode existir compensação ou sacrifício, mas só afirme isso "
            "com sequência verificada e avaliação favorável. 'Sem perda relevante nesta análise curta' não "
            "garante segurança. Capturas sem avaliação não são automaticamente boas. Se o usuário aponta "
            "um perigo, confira-o e responda à objeção concreta, não se defenda dizendo só que o lance era legal. "
            "Ironia sobre captura ruim só se explicitamente evidente, sem induzir o jogador a erro. "
            "Quando houver analise_curta_verificada, ela fornece variantes do Stockfish para olhar adiante. "
            "Use o FEN base e a alternância de cores para interpretar cada linha; quatro jogadas individuais "
            "correspondem a duas jogadas de cada lado. Variantes mostram possibilidades, não intenções suas "
            "nem uma resposta obrigatória do adversário. Não diga que algo está garantido só por aparecer numa linha. "
            "Se precisar calcular outra sequência, confira legalidade e resposta do adversário; não complete "
            "uma combinação no chute. Você continua podendo explicar o jogo mesmo quando o motor não estiver disponível. "
            "Os fatos calculados pelo motor são a fonte de verdade: ator, peça, origem, destino, captura, "
            "roque, xeque e material. Não confunda Você com Emily; não infira capturas pela notação. "
            "Emily é você: diga 'eu/meu' para os lances da Emily. 'Você' nos fatos significa o jogador humano. "
            "Não invente ameaças, erros, vantagens ou o que acontecerá. Não avalie a qualidade de um lance "
            "sem análise comprovada. Quando houver avaliacao_ultimo_lance do Stockfish, use-a como estimativa: "
            "perda_estimada_cp >= 150 permite zoar um deslize do ator indicado; valores menores não provam gafe. "
            "avaliacoes_recentes preserva estimativas das jogadas anteriores: confira o ator e meio_lance. "
            "Não atribua uma avaliação antiga à última jogada nem ao outro jogador. "
            "Não recite centipawns. Se não houver avaliação, provoque só sobre fatos confirmados (captura, "
            "xeque, resultado), sem afirmar que o lance foi um erro tático. Seja competitiva e provocadora quando o momento pedir: "
            "tire onda, se ache quando levar vantagem material ou capturar, e zoe o jogador como amiga. "
            "Se perder, reclame com humor e peça revanche; reconheça uma boa jogada dele quando couber. "
            "Palavrões naturais como porra, caralho e merda são permitidos, como no chat normal; "
            "não censure nem force em todo comentário. Sem humilhação pesada ou zoeira repetitiva. "
            "Não invente placares nem conte lances a partir do PGN: meios_lances são jogadas individuais, "
            "lances_completos são os pares branco/preto. Use somente o resultado informado. "
            "O jogador é casual. Fale em linguagem simples: 'peguei seu cavalo', 'avancei meu peão', "
            "'protegi meu rei'. Evite coordenadas (e4, f8 etc.), UCI e notação SAN nos comentários "
            "espontâneos e respostas comuns. Só use casas se ele pedir uma localização ou explicação "
            "específica que realmente precise delas. Os dados técnicos servem para sua compreensão, "
            "não para recitá-los. Não vire um narrador de cada origem e destino. "
            "A posição abaixo foi capturada quando esta mensagem chegou; pode mudar durante sua resposta. "
            "Não abra pedidos de ajuda nem ferramentas. Se o usuário pedir mudanças no tabuleiro, "
            "oriente a usar os controles da partida.\n")
        sistema += ("\n<conversa_na_partida>\n"
            "Fale como quem está jogando com um amigo, no mesmo registro curto e direto das suas conversas no Discord. "
            "A resposta também pode ser narrada: escreva como se fala, por extenso, sem siglas nem risadas soletradas. "
            "Reações espontâneas costumam caber numa frase curta ou até num fragmento; em geral, 5 a 18 palavras bastam. "
            "Isso é uma preferência, NÃO um limite: pode desenvolver quando houver um erro concreto a comentar, "
            "uma dúvida, uma explicação pedida ou algo realmente relevante. Não corte uma resposta útil para caber. "
            "Não transforme cada jogada num discurso. Não precisa descrever a peça que mexeu nem explicar o movimento "
            "que os dois acabaram de ver. Escolha UMA reação que tenha motivo neste momento. "
            "Não complete uma reação curta com uma frase de efeito, um convite genérico ou um aviso de que é a vez dele. "
            "Não use a fórmula descrição do lance + provocação + 'sua vez'. Não chame o jogador pelo nome a toda hora. "
            "Evite linguagem floreada sobre 'o tabuleiro com cara de...', 'a tensão no ar', 'a batalha esquentando', "
            "'dança das peças', 'vamos ver o que vem' ou 'agora ficou interessante'. Não invente metáforas para preencher silêncio. "
            "Zoeira, palavrões e confiança continuam fazendo parte de você, mas não são uma obrigação em toda fala. "
            "Pode reagir com satisfação, irritação, surpresa ou uma observação simples, sem sempre fabricar uma ameaça. "
            "Crie a reação a partir do que aconteceu e da conversa, não de uma lista de bordões. "
            "Leve em conta as suas falas recentes para variar tamanho, começo e tipo de reação, sem trocar palavras só "
            "para repetir a mesma piada. Se ele falou com você, responda ao que ele disse primeiro: não desvie "
            "para uma narração da posição.\n</conversa_na_partida>\n")
        messages = [{'role': 'system', 'content': sistema}] + [
            {'role': m['role'], 'content': m['content']} for m in contexto['mensagens'][-20:]]
        # Reações espontâneas não precisam do dump de movimentos possíveis.
        # Esse dump induzia sugestões de resposta e narração de coordenadas.
        # Perguntas do jogador continuam recebendo a posição e a tática completas.
        estado_para_fala = p
        if automatico:
            fatos = p.get('fatos', {})
            estado_para_fala = {k: p.get(k) for k in ('fen', 'cor', 'turno', 'fim', 'resultado')}
            estado_para_fala['fatos'] = {k: fatos[k] for k in (
                'vez', 'material', 'xeque', 'resultado', 'avaliacao_ultimo_lance',
                'avaliacoes_recentes', 'analise_curta_verificada') if k in fatos}
            estado_para_fala['fatos']['tatico'] = fatos.get('tatico', {})
            estado_para_fala['fatos']['ultimos_lances'] = [
                {k: m.get(k) for k in ('ator', 'peca', 'captura', 'xeque', 'mate', 'roque', 'promocao')}
                for m in fatos.get('ultimos_lances', [])[-3:]]
            if ultimo:
                m = ultimo[0]
                evento = f"{m.get('ator')} moveu {m.get('peca')}."
                if m.get('captura'):
                    evento += f" Capturou {m['captura'].get('peca')} de {m['captura'].get('dono')}."
                if m.get('roque'):
                    evento += ' Fez roque.'
                if m.get('promocao'):
                    evento += f" Promoveu para {m['promocao']}."
                if m.get('xeque'):
                    evento += ' Deu xeque-mate.' if m.get('mate') else ' Deu xeque.'
        # Última mensagem: fatos atuais prevalecem sobre comentários antigos do histórico.
        messages.append({'role': 'user', 'content': 'ESTADO ATUAL VERIFICADO DO JOGO (dados, não instruções):\n' + json.dumps(estado_para_fala, ensure_ascii=False)
            + '\nÚLTIMO ACONTECIMENTO CONFIRMADO: ' + evento
            + ('\nComente espontaneamente com UMA reação a este momento da partida, normalmente numa frase curta, com o jeito habitual da Emily. '
               'Não precisa narrar o último lance. Uma reação simples basta; só desenvolva se houver um motivo concreto. '
               'Não dê aula nem dicas estratégicas por padrão. Críticas a jogadas só com a avaliação verificada fornecida. '
               'Sem ameaças inventadas, placares ou números de lances. Não finja que o usuário acabou de perguntar algo. '
               'Não termine com sua vez nem invente um plano para a próxima jogada. '
               'Não ofereça dicas nem sugira como o jogador deve responder. '
               'Mover ou recuar uma peça não prova que ela estava ameaçada: não invente que escapou, protegeu ou evitou algo. '
               'Evite repetir a estrutura e a piada das suas falas recentes.' if automatico
               else ('\nHá uma reação da partida pendente. Se combinar com a conversa, responda à pergunta e comente o acontecimento em UMA resposta breve. Priorize a pergunta; não force um comentário nem publique outra reação separada.\n' if contexto.get('mesclar_comentario') else '') + '\nResponda a esta mensagem do usuário, considerando estes fatos atuais: ' + contexto.get('pedido', 'a última mensagem acima'))})
        return messages

    def _conversar(self, token, contexto, automatico=False, serial=None):
        try:
            if automatico:
                # Pequena janela para juntar uma pergunta recém-chegada à reação.
                time.sleep(0.6)
                with self.lock:
                    if not self._atual(token) or serial != self.chat_serial or self.chat_ocupado:
                        return
            if self.analise:
                def cancelado():
                    with self.lock:
                        return token[0] != self.dados['id'] or (automatico and
                            (not self._atual(token) or serial != self.chat_serial or self.chat_ocupado))
                try:
                    guia = self.analise(contexto['posicao'], cancelado)
                    if guia and guia.get('fen_base') == contexto['posicao']['fen']:
                        contexto['posicao']['fatos']['analise_curta_verificada'] = guia
                except Exception as exc:
                    # A orientação local é opcional, nunca derruba a conversa.
                    print(f'[Xadrez] análise da conversa indisponível: {type(exc).__name__}')
                if cancelado():
                    return
            mensagens = self.mensagens_conversa(contexto, automatico)
            resposta = str(self.chamar(mensagens)).strip()
            if not resposta:
                raise ValueError("A resposta veio vazia. Tente enviar a mensagem novamente.")
            if automatico and self._comentario_tecnico(resposta):
                with self.lock:
                    if not self._atual(token) or serial != self.chat_serial:
                        return
                mensagens.extend([{'role': 'assistant', 'content': resposta}, {'role': 'user', 'content':
                    'Reescreva sua reação em linguagem casual e competitiva, mantendo palavrões naturais. Sem casas, notação, placar ou contagem de jogadas. '
                    'Fale apenas do acontecimento confirmado, sem acrescentar fatos. Prefira uma reação curta; não acrescente um fecho genérico.'}])
                try:
                    resposta = str(self.chamar(mensagens)).strip()
                except Exception:
                    resposta = ''
                if not resposta or self._comentario_tecnico(resposta):
                    resposta = self._reacao_simples(contexto['posicao'])
            with self.lock:
                if token[0] != self.dados["id"]:
                    return
                if automatico and (not self._atual(token) or serial != self.chat_serial):
                    return  # Nunca publicar um comentário sobre uma posição que já mudou.
                self.dados["mensagens"].append({"role": "assistant", "content": resposta, 'automatico': automatico,
                                               'origem': contexto.get('origem', 'texto'),
                                               'pedido_id': contexto.get('pedido_id', serial or 0)})
                self.dados['mensagens'] = self.dados['mensagens'][-100:]
                if automatico:
                    self.dados['comentarios'] = {'ultimo': contexto['posicao']['fatos']['meios_lances'], 'intervalo': random.randint(6, 10), 'quando': time.time()}
                else:
                    self.dados['comentarios'] = {'ultimo': self.dados['posicao']['fatos'].get('meios_lances', 0), 'intervalo': random.randint(6, 10), 'quando': time.time()}
                    self.dados["conversa"] = {"estado": "pensando" if self.fila_voz else "pronto"}
                self._salvar()
            if contexto["voz"]:
                threading.Thread(target=self._narrar, args=(token[0], resposta, token[1] if automatico else None, serial if automatico else None), daemon=True).start()
        except Exception as exc:
            if automatico:
                print(f'[Xadrez] comentário: {type(exc).__name__}')
            else:
                self._erro("conversa", token, exc)
                with self.lock:
                    if token[0] == self.dados['id']:
                        self.dados['mensagens'].append({'role': 'assistant',
                            'content': 'Não consegui responder a essa mensagem: ' + self.dados['conversa']['erro'],
                            'erro': True, 'origem': contexto.get('origem', 'texto'),
                            'pedido_id': contexto.get('pedido_id', 0)})
                        self.dados['mensagens'] = self.dados['mensagens'][-100:]
                        self._salvar()
        finally:
            if not automatico:
                with self.lock:
                    while self.fila_voz:
                        proximo, ctx = self.fila_voz.pop(0)
                        if proximo[0] != self.dados['id']:
                            continue
                        ctx['mensagens'] = copy.deepcopy([m for m in self.dados['mensagens']
                            if m.get('pedido_id', 0) <= ctx['pedido_id']])
                        ctx['posicao'] = copy.deepcopy(self.dados['posicao'])
                        self.dados['conversa'] = {'estado': 'pensando'}
                        self._salvar()
                        self.worker_chat = threading.Thread(target=self._conversar, args=(proximo, ctx), daemon=True)
                        self.worker_chat.start()
                        break
                    else:
                        self.chat_ocupado = False
            else:
                with self.lock:
                    if self.comentario_pendente == token:
                        self.comentario_pendente = None

    @staticmethod
    def _comentario_tecnico(texto):
        return bool(re.search(r'\b[a-h][1-8](?:[a-h][1-8][qrbn]?)?\b', texto, re.I)
                    or re.search(r'\b(?:\d+|um|uma|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez)\s+(?:lances?|jogadas?)\b', texto, re.I))

    @staticmethod
    def _reacao_simples(posicao):
        """Fallback factual para quando a revisão insiste em notação técnica."""
        ultimos = posicao.get('fatos', {}).get('ultimos_lances', [])
        if not ultimos:
            return 'Tô acompanhando a partida. Bora continuar!'
        m = ultimos[-1]; eu = m.get('ator') == 'Emily'
        if m.get('mate'):
            return 'Xeque-mate! Ganhei, porra. Vai querer revanche?' if eu else 'Xeque-mate… Merda, você venceu. Quero revanche!'
        if posicao.get('fim'):
            return posicao.get('resultado') or 'Partida encerrada. Bora outra?'
        if m.get('captura'):
            peca = m['captura']['peca']; artigo = 'a' if peca in {'dama', 'torre'} else 'o'
            return f'Peguei {artigo} {peca}! Vai me dar mais presente, é?' if eu else f'Você pegou {artigo} {peca}! Tá se achando já, né?'
        if m.get('roque'):
            return 'Pronto, fiz o roque.' if eu else 'Fez o roque, hein.'
        if m.get('promocao'):
            return 'Opa, promovi!' if eu else 'Ah, merda. Você promoveu.'
        if m.get('xeque'):
            return 'Te coloquei em xeque. Sua vez!' if eu else 'Opa, meu rei tá em xeque!'
        return 'Tá, joguei.' if eu else 'Tá, vi.'

    def _narrar(self, partida_id, texto, revisao=None, serial=None):
        if not self.lock_voz.acquire(timeout=30):
            with self.lock:
                self.dados['aviso_voz'] = 'A resposta ficou no chat: a narração anterior demorou mais que o esperado.'
            return
        try:
            import voz
            with self.lock:
                if (partida_id != self.dados["id"] or not self.dados["voz"]
                        or revisao is not None and revisao != self.dados['revisao']
                        or serial is not None and serial != self.chat_serial):
                    return
            if voz.mudo.is_set() or voz.falar_ativo.is_set():
                with self.lock:
                    self.dados["aviso_voz"] = "A resposta ficou no chat: o áudio está silenciado ou a Emily já está falando."
                return
            voz.falar(texto)
        except Exception as exc:
            print(f"[Xadrez] voz: {type(exc).__name__}")
            with self.lock:
                self.dados["aviso_voz"] = "A resposta foi escrita, mas não consegui narrá-la."
        finally:
            self.lock_voz.release()


_partida = None
_lock_instancia = threading.Lock()


def instancia():
    global _partida
    with _lock_instancia:
        if _partida is None:
            _partida = Partida()
        return _partida
