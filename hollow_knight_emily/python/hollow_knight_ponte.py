"""Servidor loopback que conecta o mod de Hollow Knight à Emily real."""

from __future__ import annotations

import hmac
import os
import queue
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Callable

from flask import Flask, Response, jsonify, request

from .hollow_knight_audio import empacotar_wav, gerar_pcm_fish, gerar_wav_fish
from .hollow_knight_cerebro import CerebroHollowKnight
from .hollow_knight_modelos import gravar_catalogo, normalizar_modelo
from .hollow_knight_memoria import MemoriaHollowKnight
from .hollow_knight_politica import PoliticaComentarios
from .hollow_knight_protocolo import EstadoPonte, EventoJogo, VERSAO_PROTOCOLO


HOST = "127.0.0.1"
PORTA_PADRAO = 57124
RAIZ = Path(__file__).resolve().parents[1]
RUNTIME = RAIZ / "runtime"
JOGO_PADRAO = Path.home() / ".local/share/Steam/steamapps/common/Hollow Knight"
TOKEN_NO_MOD = Path(
    os.getenv(
        "EMILY_HK_TOKEN_ARQUIVO",
        str(
            JOGO_PADRAO
            / "hollow_knight_Data/Managed/Mods/EmilyCompanion/emily-hk-token.txt"
        ),
    )
)
CATALOGO_RUNTIME = RUNTIME / "modelos.json"
CATALOGO_NO_MOD = TOKEN_NO_MOD.parent / "emily-hk-modelos.json"


class _AudioEmFluxo:
    """Buffer crescente lido pelo endpoint enquanto o TTS ainda está ativo."""

    def __init__(self, taxa: int = 44100, canais: int = 1, largura: int = 2):
        self.criado_em = time.time()
        self.taxa = taxa
        self.canais = canais
        self.largura = largura
        self._pedacos: list[bytes] = []
        self._concluido = False
        self._condicao = threading.Condition()

    def adicionar(self, pedaco: bytes) -> None:
        if not pedaco:
            return
        with self._condicao:
            self._pedacos.append(bytes(pedaco))
            self._condicao.notify_all()

    def finalizar(self) -> None:
        with self._condicao:
            self._concluido = True
            self._condicao.notify_all()

    def iterar(self):
        indice = 0
        while True:
            with self._condicao:
                while indice >= len(self._pedacos) and not self._concluido:
                    self._condicao.wait(timeout=1.0)
                if indice < len(self._pedacos):
                    pedaco = self._pedacos[indice]
                    indice += 1
                elif self._concluido:
                    return
                else:
                    continue
            yield pedaco

    def wav(self, timeout: float = 45.0) -> bytes:
        limite = time.monotonic() + timeout
        with self._condicao:
            while not self._concluido:
                restante = limite - time.monotonic()
                if restante <= 0:
                    return b""
                self._condicao.wait(timeout=min(1.0, restante))
            pcm = b"".join(self._pedacos)
        return empacotar_wav(
            pcm, taxa=self.taxa, canais=self.canais, largura=self.largura)


class PonteHollowKnight:
    def __init__(
        self,
        token: str | None = None,
        *,
        cerebro=None,
        gerador_audio: Callable[[str], bytes] | None = None,
        gerador_audio_stream: Callable | None = None,
        normalizador_modelo: Callable[[object], str] | None = None,
        gravador_catalogo: Callable[..., dict] | None = None,
        pronto: Callable[[], bool] | None = None,
        memoria: MemoriaHollowKnight | None = None,
        origem: str = "desktop",
    ) -> None:
        self.token = token or _token_compartilhado() or secrets.token_urlsafe(32)
        self.estado = EstadoPonte()
        self.politica = PoliticaComentarios()
        self._politicas_sessao: dict[str, PoliticaComentarios] = {}
        self.memoria = memoria
        self.cerebro = cerebro or CerebroHollowKnight(memoria=memoria)
        # ``None`` preserva a resolução dinâmica do fallback, útil tanto para
        # hot updates quanto para testes que substituem gerar_wav_fish.
        self._gerador_audio = gerador_audio
        self._gerador_audio_stream = gerador_audio_stream
        self._normalizador_modelo = normalizador_modelo or normalizar_modelo
        self._gravador_catalogo = gravador_catalogo or gravar_catalogo
        self._pronto = pronto or (lambda: True)
        self.origem = str(origem or "desktop")
        self.app = Flask("emily_hollow_knight")
        self._fila: queue.Queue = queue.Queue(maxsize=80)
        self._fila_prioritaria: queue.Queue = queue.Queue(maxsize=40)
        self._fila_audio: queue.Queue = queue.Queue(maxsize=30)
        self._audios: dict[str, tuple[float, bytes]] = {}
        self._audios_stream: dict[str, _AudioEmFluxo] = {}
        self._audios_lock = threading.Lock()
        self._parar = threading.Event()
        self._thread_worker: threading.Thread | None = None
        self._thread_audio: threading.Thread | None = None
        self._thread_servidor: threading.Thread | None = None
        self._lotes: dict[str, dict] = {}
        self._lotes_lock = threading.Lock()
        self._thread_lotes: threading.Thread | None = None
        self._servidor = None
        self._registrar_rotas()

    def _autorizado(self) -> bool:
        recebido = request.headers.get("Authorization", "")
        # Builds antigos da Emily escreviam um token novo antes de descobrir
        # que a porta 57124 já estava ocupada pelo serviço permanente. Aceitar
        # também os tokens locais atualmente gravados faz a reconciliação sem
        # expor segredo na rede (a ponte continua bindada só em 127.0.0.1).
        tokens = {self.token, *_tokens_compartilhados()}
        return any(
            token and hmac.compare_digest(recebido, f"Bearer {token}")
            for token in tokens
        )

    def _exigir_token(self):
        if not self._autorizado():
            return jsonify({"ok": False, "erro": "token inválido"}), 401
        return None

    def _registrar_rotas(self) -> None:
        app = self.app

        @app.get("/v1/hollow-knight/status")
        def status():
            negado = self._exigir_token()
            if negado:
                return negado
            disponivel = bool(self._pronto())
            return jsonify({
                "ok": disponivel,
                "online": disponivel,
                "origem": self.origem,
                **self.estado.resumo(),
            }), 200 if disponivel else 503

        @app.post("/v1/hollow-knight/sessao")
        def sessao():
            negado = self._exigir_token()
            if negado:
                return negado
            if not self._pronto():
                return jsonify({
                    "ok": False,
                    "online": False,
                    "origem": self.origem,
                    "erro": "cérebro da Emily indisponível",
                }), 503
            corpo = request.get_json(silent=True) or {}
            criada = self.estado.criar_sessao(
                corpo.get("campanha_id", ""), corpo.get("versao_mod", "")
            )
            configuracao = self._normalizar_configuracao(corpo.get("configuracao"))
            self.estado.atualizar_estado(criada.id, configuracao)
            self._politicas_sessao[criada.id] = PoliticaComentarios()
            if self.memoria is not None:
                try:
                    self.memoria.registrar_sessao(criada, configuracao)
                except Exception as erro:
                    print(
                        "[HOLLOW-KNIGHT] memória não registrou a sessão: "
                        f"{type(erro).__name__}: {erro}"
                    )
            self.estado.enfileirar_comando(
                criada.id,
                "configuracao",
                {
                    **configuracao,
                    "protocolo": VERSAO_PROTOCOLO,
                },
                ttl=120,
            )
            return jsonify({
                "ok": True,
                "sessao_id": criada.id,
                "protocolo": VERSAO_PROTOCOLO,
                "configuracao": configuracao,
            })

        @app.post("/v1/hollow-knight/eventos")
        def eventos():
            negado = self._exigir_token()
            if negado:
                return negado
            if not self._pronto():
                return jsonify({"ok": False, "online": False,
                                "erro": "cérebro da Emily indisponível"}), 503
            corpo = request.get_json(silent=True) or {}
            sessao_id = str(corpo.get("sessao_id") or "")
            sessao_atual = self.estado.obter(sessao_id)
            if not sessao_atual:
                return jsonify({"ok": False, "erro": "sessão inexistente"}), 404
            configuracao = None
            if "configuracao" in corpo:
                configuracao = self._normalizar_configuracao(corpo.get("configuracao"))
                self.estado.atualizar_estado(sessao_id, configuracao)
            itens = corpo.get("eventos") or []
            if not isinstance(itens, list) or len(itens) > 40:
                return jsonify({"ok": False, "erro": "lote de eventos inválido"}), 400
            try:
                convertidos = [EventoJogo.de_json(sessao_id, item) for item in itens]
                aceitos = self.estado.receber_eventos(sessao_id, convertidos)
            except (TypeError, ValueError) as erro:
                return jsonify({"ok": False, "erro": str(erro)}), 400
            derivados = []
            if self.memoria is not None:
                try:
                    derivados = self.memoria.registrar_eventos(sessao_atual, aceitos)
                    derivados = self.estado.receber_eventos(sessao_id, derivados)
                except Exception as erro:
                    print(
                        "[HOLLOW-KNIGHT] memória não registrou eventos: "
                        f"{type(erro).__name__}: {erro}"
                    )
                    derivados = []
            enfileirados = 0
            for evento in aceitos:
                if self._agendar(evento):
                    enfileirados += 1
            for evento in derivados:
                if self._agendar(evento):
                    enfileirados += 1
            return jsonify({
                "ok": True,
                "aceitos": len(aceitos),
                "observacoes": len(derivados),
                "agendados": enfileirados,
                "configuracao": configuracao,
            })

        @app.get("/v1/hollow-knight/comandos")
        def comandos():
            negado = self._exigir_token()
            if negado:
                return negado
            if not self._pronto():
                return jsonify({"ok": False, "online": False,
                                "erro": "cérebro da Emily indisponível"}), 503
            sid = request.args.get("sessao_id", "")
            try:
                desde = max(0, int(request.args.get("desde", "0")))
                comandos = self.estado.comandos_desde(
                    sid, desde, request.args.get("cena_id", "")
                )
            except (KeyError, ValueError):
                return jsonify({"ok": False, "erro": "sessão ou sequência inválida"}), 404
            return jsonify({"ok": True, "comandos": comandos})

        @app.post("/v1/hollow-knight/confirmar")
        def confirmar():
            negado = self._exigir_token()
            if negado:
                return negado
            corpo = request.get_json(silent=True) or {}
            try:
                self.estado.confirmar(
                    str(corpo.get("sessao_id") or ""), int(corpo.get("sequencia") or 0)
                )
            except (KeyError, ValueError):
                return jsonify({"ok": False, "erro": "confirmação inválida"}), 404
            return jsonify({"ok": True})

        @app.get("/v1/hollow-knight/audio/<audio_id>")
        def audio(audio_id: str):
            negado = self._exigir_token()
            if negado:
                return negado
            with self._audios_lock:
                item = self._audios.get(audio_id)
                fluxo = self._audios_stream.get(audio_id)
            if not item and fluxo is not None:
                wav = fluxo.wav()
                if wav:
                    item = (time.time(), wav)
                    with self._audios_lock:
                        self._audios[audio_id] = item
                else:
                    # O PCM terminou vazio e o worker está gerando o WAV de
                    # fallback sob o mesmo ID. O cliente chega aqui logo após o
                    # EOF do stream; espere a publicação em vez de responder 404
                    # numa corrida de poucos milissegundos/segundos.
                    limite_fallback = time.monotonic() + 30.0
                    while time.monotonic() < limite_fallback:
                        with self._audios_lock:
                            item = self._audios.get(audio_id)
                        if item:
                            break
                        time.sleep(0.05)
            if not item or time.time() - item[0] > 300:
                return jsonify({"ok": False, "erro": "áudio inexistente"}), 404
            resposta = Response(item[1], mimetype="audio/wav")
            resposta.headers["Cache-Control"] = "no-store"
            return resposta

        @app.get("/v1/hollow-knight/audio-stream/<audio_id>")
        def audio_stream(audio_id: str):
            negado = self._exigir_token()
            if negado:
                return negado
            with self._audios_lock:
                fluxo = self._audios_stream.get(audio_id)
            if fluxo is None or time.time() - fluxo.criado_em > 300:
                return jsonify({"ok": False, "erro": "stream inexistente"}), 404
            resposta = Response(fluxo.iterar(), mimetype="application/octet-stream")
            resposta.headers["Cache-Control"] = "no-store"
            resposta.headers["X-Emily-Sample-Rate"] = str(fluxo.taxa)
            resposta.headers["X-Emily-Channels"] = str(fluxo.canais)
            resposta.headers["X-Emily-Sample-Width"] = str(fluxo.largura)
            resposta.headers["X-Accel-Buffering"] = "no"
            return resposta

        @app.get("/v1/hollow-knight/memoria")
        def memoria():
            negado = self._exigir_token()
            if negado:
                return negado
            if self.memoria is None:
                return jsonify({"ok": False, "erro": "memória dedicada desativada"}), 503
            sid = request.args.get("sessao_id", "")
            sessao_atual = self.estado.obter(sid)
            campanha = (
                sessao_atual.campanha_id if sessao_atual
                else request.args.get("campanha_id", "")
            )
            if not campanha:
                return jsonify({"ok": False, "erro": "campanha ausente"}), 400
            try:
                return jsonify({"ok": True, **self.memoria.resumo(campanha)})
            except Exception as erro:
                return jsonify({
                    "ok": False,
                    "erro": f"memória indisponível: {type(erro).__name__}",
                }), 503

    def _normalizar_configuracao(self, bruto: object) -> dict:
        dados = bruto if isinstance(bruto, dict) else {}
        modo = str(dados.get("modo_fala") or os.getenv("EMILY_HK_MODO_FALA", "normal"))
        if modo not in {"muda", "quieta", "normal", "tagarela"}:
            modo = "normal"
        try:
            volume = max(0.0, min(2.0, float(dados.get("volume", os.getenv("EMILY_HK_VOLUME", "0.9")))))
        except (TypeError, ValueError):
            volume = 0.9
        voz = dados.get("voz", True)
        return {
            "modo_fala": modo,
            "modelo": self._normalizador_modelo(dados.get("modelo")),
            "voz": voz if isinstance(voz, bool) else True,
            "volume": volume,
        }

    # Eventos que falam do LUGAR em si: se o Vitor já saiu daquela sala/região, o
    # comentário nasceu velho e não deve começar. Os demais (NPC, chefe, dano)
    # são sobre algo que continua fazendo sentido na região onde ele está.
    EVENTOS_DO_LUGAR = ("area_nova", "comentario_tagarela")
    EVENTOS_INDEPENDENTES_DE_ZONA = (
        "boas_vindas", "morte", "charm_adquirido", "chamou_emily",
    )

    # 0.4.9: acontecimentos próximos viram UM comentário. O lote espera uma
    # janela curta por irmãos (amuleto comprado na conversa com o NPC, chefe que
    # entra logo depois de outra coisa...) e despeja como "eventos_multiplos",
    # gerando uma única chamada de modelo e uma única fala, em vez de empilhar
    # comentários atrasados. Momentos únicos não esperam por ninguém.
    TIPO_LOTE = "eventos_multiplos"
    JANELA_LOTE = 2.0
    MAX_EVENTOS_LOTE = 5
    EVENTOS_FORA_DO_LOTE = ("boas_vindas", "morte", "chamou_emily")
    URGENTES = (
        "boas_vindas", "banco_descoberto", "npc_dialogo", "boss_encontrado",
        "boss_iniciado", "boss_luta", "boss_derrotado", "morte",
        "quase_morte", "chamou_emily",
    )

    @classmethod
    def _mesma_area(cls, evento, sessao) -> bool:
        """O comentário ainda faz sentido no lugar onde ele está agora?

        Uma fala nascida para a Encruzilhada não deve ser entregue quando o Vitor
        já está no Caminho Verde: o modelo escreveu sobre um lugar que não é mais
        o dele. A região é sempre comparada; a cena (sala) só importa para os
        eventos que falam da paisagem.
        """
        dados = evento.dados if isinstance(evento.dados, dict) else {}
        zona_evento = str(dados.get("zona") or "").strip()
        zona_agora = str(sessao.estado.get("zona") or "").strip()
        if zona_evento and zona_agora and zona_evento != zona_agora:
            return False
        if evento.tipo not in cls.EVENTOS_DO_LUGAR:
            return True
        if not evento.cena_id or not sessao.cena_id:
            return True
        cena_agora = str(sessao.estado.get("cena_atual") or sessao.cena_id or "")
        return evento.cena_id == cena_agora

    def _agendar(self, evento: EventoJogo) -> bool:
        sessao = self.estado.obter(evento.sessao_id)
        if not sessao:
            return False
        if evento.tipo == "comentario_tagarela" and self.estado.tem_fala_pendente(evento.sessao_id):
            return False
        modo = str(sessao.estado.get("modo_fala") or os.getenv("EMILY_HK_MODO_FALA", "normal"))
        if modo not in {"muda", "quieta", "normal", "tagarela"}:
            modo = "normal"
        politica = self._politicas_sessao.setdefault(evento.sessao_id, PoliticaComentarios())
        if not politica.deve_responder(evento.tipo, evento.dados, modo):
            if bool(evento.dados.get("persistente")):
                print(f"[HOLLOW-KNIGHT] marco não agendado pela política: {evento.tipo}")
            return False
        try:
            prioridade = max(
                politica.prioridade(evento.tipo),
                int(evento.dados.get("prioridade") or 0),
            )
            # 0.4.9: momentos únicos não esperam por irmãos; o resto entra na
            # janela de lote para virar um comentário único em vez de fila
            # empilhada de falas atrasadas.
            # No modo silencioso, um marco obrigatório não pode ser incorporado
            # a um lote chamado eventos_multiplos (que o filtro do worker barra).
            if modo == "muda" and evento.tipo in {
                "boas_vindas", "charm_adquirido", "boss_derrotado", "morte", "chamou_emily",
            }:
                return self._enfileirar_evento(evento, prioridade)
            if evento.tipo in self.EVENTOS_FORA_DO_LOTE:
                return self._enfileirar_evento(evento, prioridade)
            return self._registrar_no_lote(evento, prioridade)
        except queue.Full:
            print(f"[HOLLOW-KNIGHT] fila cheia; evento não agendado: {evento.tipo}")
            return False

    def _enfileirar_evento(
        self, evento: EventoJogo, prioridade: int, urgente: bool = False,
    ) -> bool:
        destino = self._fila_prioritaria if (
            bool(evento.dados.get("persistente"))
            or urgente
            or evento.tipo in self.URGENTES
            or prioridade >= 70
        ) else self._fila
        destino.put_nowait(evento)
        if bool(evento.dados.get("persistente")):
            nome = str(evento.dados.get("nome") or evento.dados.get("charm") or "")[:100]
            print(f"[HOLLOW-KNIGHT] marco agendado: {evento.tipo} | {nome}")
        return True

    def _registrar_no_lote(self, evento: EventoJogo, prioridade: int) -> bool:
        if self.JANELA_LOTE <= 0:
            # Janela desligada: comportamento antigo, enfileiramento direto.
            return self._enfileirar_evento(evento, prioridade)
        with self._lotes_lock:
            lote = self._lotes.get(evento.sessao_id)
            if lote is None:
                lote = {
                    "prazo": time.monotonic() + self.JANELA_LOTE,
                    "itens": [],
                }
                self._lotes[evento.sessao_id] = lote
            if len(lote["itens"]) >= self.MAX_EVENTOS_LOTE:
                # Lote já está cheio: não segura mais nada, vai solto na fila.
                return self._enfileirar_evento(evento, prioridade)
            lote["itens"].append((evento, prioridade))
        if bool(evento.dados.get("persistente")):
            nome = str(evento.dados.get("nome") or evento.dados.get("charm") or "")[:100]
            print(f"[HOLLOW-KNIGHT] marco entrou no lote: {evento.tipo} | {nome}")
        return True

    def _flusher_lotes(self) -> None:
        while not self._parar.is_set():
            agora = time.monotonic()
            prontos = []
            with self._lotes_lock:
                for sid, lote in list(self._lotes.items()):
                    if agora >= lote["prazo"] or len(lote["itens"]) >= self.MAX_EVENTOS_LOTE:
                        prontos.append((sid, self._lotes.pop(sid)))
            for sid, lote in prontos:
                try:
                    self._despejar_lote(sid, lote["itens"])
                except Exception as erro:  # noqa: BLE001
                    print(
                        "[HOLLOW-KNIGHT] falha ao fechar lote de eventos: "
                        f"{type(erro).__name__}: {erro}"
                    )
            self._parar.wait(0.1)

    def _despejar_lote(self, sessao_id: str, itens: list) -> None:
        if not itens:
            return
        if len(itens) == 1:
            evento, prioridade = itens[0]
            self._enfileirar_evento(evento, prioridade)
            return
        ultimo = itens[-1][0]
        persistente = any(bool(e.dados.get("persistente")) for e, _ in itens)
        prioridade = max(p for _, p in itens)
        urgente = any(e.tipo in self.URGENTES for e, _ in itens)
        dados = {
            "resumo": [
                {"tipo": e.tipo, "dados": e.dados} for e, _ in itens
            ],
            "persistente": persistente,
            "prioridade": prioridade,
        }
        zona = str(ultimo.dados.get("zona") or "").strip()
        if zona:
            dados["zona"] = zona
        lote = EventoJogo(
            id="lote-" + secrets.token_hex(6),
            sessao_id=sessao_id,
            cena_id=ultimo.cena_id,
            tipo=self.TIPO_LOTE,
            dados=dados,
        )
        self._enfileirar_evento(lote, prioridade, urgente)
        print(
            "[HOLLOW-KNIGHT] lote de eventos: "
            + ", ".join(e.tipo for e, _ in itens)
        )

    def _deve_validar_zona(self, evento: EventoJogo) -> bool:
        """A fala de região vale só se nenhum pedaço do lote for independente."""
        if evento.tipo in self.EVENTOS_INDEPENDENTES_DE_ZONA:
            return False
        if evento.tipo == self.TIPO_LOTE:
            for item in evento.dados.get("resumo") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("tipo") or "") in self.EVENTOS_INDEPENDENTES_DE_ZONA:
                    return False
        return True

    def _worker(self) -> None:
        while not self._parar.is_set():
            try:
                evento = self._fila_prioritaria.get_nowait()
            except queue.Empty:
                try:
                    evento = self._fila.get(timeout=0.12)
                except queue.Empty:
                    self._limpar_audios()
                    continue
            sessao = self.estado.obter(evento.sessao_id)
            if not sessao:
                continue
            # Uma fala enfileirada antes de mudar o modo não pode furar a
            # preferência atual do jogador. Marcos autoritativos permanecem.
            modo = str(sessao.estado.get("modo_fala") or "normal")
            if (evento.tipo == "comentario_tagarela" and modo != "tagarela"):
                continue
            if (modo == "muda" and evento.tipo not in
                    {"boas_vindas", "charm_adquirido", "boss_derrotado", "morte", "chamou_emily"}):
                continue
            if not evento.dados.get("persistente") and not self._mesma_area(evento, sessao):
                continue
            politica = self._politicas_sessao.setdefault(evento.sessao_id, PoliticaComentarios())
            modelo_inicio = str(sessao.estado.get("modelo") or "")
            resposta = None
            try:
                resposta = self.cerebro.responder(evento, sessao)
            except Exception as erro:  # LLM indisponível: críticos ainda falam
                print(f"[HOLLOW-KNIGHT] cérebro indisponível: {type(erro).__name__}: {erro}")
            texto = str((resposta or {}).get("texto") or "").strip()
            if texto and politica.parece_narracao_de_estatistica(texto):
                resposta = self._reescrever_sem_estatisticas(evento, sessao, resposta)
                texto = str((resposta or {}).get("texto") or "").strip()
            if not texto:
                texto = politica.fallback(evento.tipo, evento.dados) if (
                    evento.tipo in politica.EVENTOS_QUE_NAO_FICAM_MUTOS
                    or evento.dados.get("persistente")) else ""
                resposta = {"emocao": "preocupada", "acao": "nenhuma"}
                if bool(evento.dados.get("persistente")) and texto:
                    print(f"[HOLLOW-KNIGHT] fallback usado para marco: {evento.tipo}")
            if texto and politica.parece_narracao_de_estatistica(texto):
                # Última barreira: sem comentário humano disponível, silêncio é
                # melhor do que relatório de vida, alma, golpes ou tempo.
                print(
                    "[HOLLOW-KNIGHT] fala descartada por narração de "
                    f"estatística: {evento.tipo}"
                )
                texto = ""
                # 0.4.10: chefe, morte e marcos não podiam sumir mudos porque o
                # modelo virou painel — foi exatamente o caso da Radiância no
                # Panteão. A fala determinística da Emily assume o lugar.
                if (evento.tipo in politica.EVENTOS_QUE_NAO_FICAM_MUTOS
                        or bool(evento.dados.get("persistente"))):
                    texto = politica.fallback(evento.tipo, evento.dados)
            if not texto or politica.repetido(texto):
                if bool(evento.dados.get("persistente")):
                    motivo = "sem texto" if not texto else "texto repetido"
                    print(f"[HOLLOW-KNIGHT] marco sem entrega: {evento.tipo} | {motivo}")
                continue
            # Uma resposta ficou velha enquanto o modelo pensava: não a leve à
            # próxima sala. Eventos sem cena (aquisição/boot) continuam válidos.
            sessao_agora = self.estado.obter(evento.sessao_id)
            persistente = bool(evento.dados.get("persistente"))
            if (sessao_agora and modelo_inicio != str(sessao_agora.estado.get("modelo") or "")
                    and not persistente):
                continue
            if not sessao_agora or (not persistente and not self._mesma_area(evento, sessao_agora)):
                continue
            # Trocar de região invalida o assunto antigo: ela não pode comentar a
            # Encruzilhada Esquecida como se ele ainda estivesse lá. Marcos
            # (aquisição, morte, saudação) sobrevivem à troca de área.
            if not persistente:
                zona_evento = str(evento.dados.get("zona") or "").strip()
                zona_agora = str(sessao_agora.estado.get("zona") or "").strip()
                if zona_evento and zona_agora and zona_evento != zona_agora:
                    continue
            zona_fala = str(
                evento.dados.get("zona") or sessao_agora.estado.get("zona") or ""
            ).strip()
            validar_zona = bool(zona_fala and self._deve_validar_zona(evento))
            politica.registrar_texto(texto)
            voz_prevista = bool(sessao_agora.estado.get("voz", True))
            dados = {
                "texto": texto,
                "emocao": str((resposta or {}).get("emocao") or "neutra"),
                "acao": str((resposta or {}).get("acao") or "nenhuma"),
                "audio_id": "",
                "voz_prevista": voz_prevista,
                "persistente": persistente,
                # Última barreira no mod: se esta fala ficar pronta na fila e o
                # Vitor mudar de região antes de ela COMEÇAR, ela será descartada.
                # Depois de iniciada, a fala sempre termina normalmente.
                "zona": zona_fala,
                "validar_zona": validar_zona,
            }
            command_scene = "*" if persistente else evento.cena_id
            fala = self.estado.enfileirar_comando(
                evento.sessao_id, "fala", dados,
                cena_id=command_scene,
                ttl=90 if persistente else 25,
            )
            if voz_prevista:
                try:
                    self._fila_audio.put_nowait((
                        evento.sessao_id, command_scene, texto, persistente,
                        fala.sequencia,
                    ))
                except queue.Full:
                    self.estado.enfileirar_comando(
                        evento.sessao_id, "audio",
                        {"audio_id": "", "fala_sequencia": fala.sequencia},
                        cena_id=command_scene, ttl=90 if persistente else 25,
                    )
                    print(f"[HOLLOW-KNIGHT] fila de áudio cheia; fala descartada sem sobrepor: {evento.tipo}")
            if persistente:
                print(f"[HOLLOW-KNIGHT] fala de marco entregue: {evento.tipo}")

    def _reescrever_sem_estatisticas(self, evento, sessao, resposta: dict | None) -> dict:
        """Pede uma segunda versão ao cérebro quando a primeira virou painel.

        Só devolve a nova resposta se ela realmente fugir do relatório; caso
        contrário mantém a original para o filtro seguinte decidir.
        """
        try:
            nova = self.cerebro.responder(evento, sessao, proibir_estatisticas=True)
        except TypeError:
            # Cérebros de teste/legado sem o parâmetro novo.
            return resposta or {}
        except Exception as erro:  # noqa: BLE001
            print(
                "[HOLLOW-KNIGHT] reescrita sem estatística falhou: "
                f"{type(erro).__name__}: {erro}"
            )
            return resposta or {}
        if isinstance(nova, dict):
            texto_novo = str(nova.get("texto") or "").strip()
            if texto_novo and not self.politica.parece_narracao_de_estatistica(texto_novo):
                print(f"[HOLLOW-KNIGHT] fala reescrita sem estatística: {evento.tipo}")
                return nova
        return resposta or {}

    def _worker_audio(self) -> None:
        while not self._parar.is_set():
            try:
                sessao_id, cena_id, texto, persistente, fala_sequencia = self._fila_audio.get(timeout=0.15)
            except queue.Empty:
                continue
            sessao = self.estado.obter(sessao_id)
            if not sessao:
                continue
            if cena_id != "*" and sessao.cena_id and cena_id != sessao.cena_id:
                continue
            audio_id = ""
            publicou_stream = False
            try:
                if bool(sessao.estado.get("voz", True)):
                    if self._gerador_audio_stream is not None or self._gerador_audio is None:
                        audio_id = secrets.token_urlsafe(12)
                        fluxo = _AudioEmFluxo()
                        with self._audios_lock:
                            self._audios_stream[audio_id] = fluxo
                        # O mod novo abre o endpoint agora, antes do primeiro
                        # chunk. Builds antigos chamam /audio e esperam o WAV.
                        self.estado.enfileirar_comando(
                            sessao_id, "audio", {
                                "audio_id": audio_id,
                                "fala_sequencia": fala_sequencia,
                                "streaming": True,
                                "sample_rate": fluxo.taxa,
                                "channels": fluxo.canais,
                                "sample_width": fluxo.largura,
                            },
                            cena_id=cena_id, ttl=90 if persistente else 25,
                        )
                        publicou_stream = True
                        try:
                            gerador_stream = (
                                self._gerador_audio_stream or gerar_pcm_fish)
                            for pedaco in gerador_stream(texto):
                                fluxo.adicionar(pedaco)
                        finally:
                            fluxo.finalizar()
                        wav = fluxo.wav(timeout=0)
                        if not wav:
                            # O mod já recebeu o comando de stream. Se nenhum
                            # chunk veio, ele pede /audio; prepare o WAV legado
                            # sob o mesmo ID para esse fallback ser transparente.
                            gerador_fallback = self._gerador_audio or gerar_wav_fish
                            wav = gerador_fallback(texto)
                        if wav:
                            with self._audios_lock:
                                self._audios[audio_id] = (time.time(), wav)
                    else:
                        wav = self._gerador_audio(texto)
                        if wav:
                            audio_id = secrets.token_urlsafe(12)
                            with self._audios_lock:
                                self._audios[audio_id] = (time.time(), wav)
            except Exception as erro:
                print(f"[HOLLOW-KNIGHT] TTS indisponível: {type(erro).__name__}: {erro}")
            sessao_agora = self.estado.obter(sessao_id)
            if not sessao_agora or (
                cena_id != "*" and sessao_agora.cena_id and cena_id != sessao_agora.cena_id
            ):
                continue
            if not publicou_stream:
                self.estado.enfileirar_comando(
                    sessao_id, "audio", {
                        "audio_id": audio_id,
                        "fala_sequencia": fala_sequencia,
                    },
                    cena_id=cena_id, ttl=90 if persistente else 25,
                )

    def _iniciar_workers(self) -> None:
        self._parar.clear()
        if not self._thread_worker or not self._thread_worker.is_alive():
            self._thread_worker = threading.Thread(
                target=self._worker, name="emily-hk-cerebro", daemon=True
            )
            self._thread_worker.start()
        if not self._thread_lotes or not self._thread_lotes.is_alive():
            self._thread_lotes = threading.Thread(
                target=self._flusher_lotes, name="emily-hk-lotes", daemon=True
            )
            self._thread_lotes.start()
        if not self._thread_audio or not self._thread_audio.is_alive():
            self._thread_audio = threading.Thread(
                target=self._worker_audio, name="emily-hk-audio", daemon=True
            )
            self._thread_audio.start()

    def _limpar_audios(self) -> None:
        limite = time.time() - 300
        with self._audios_lock:
            antigos = [chave for chave, item in self._audios.items() if item[0] < limite]
            for chave in antigos:
                self._audios.pop(chave, None)
            streams_antigos = [
                chave for chave, item in self._audios_stream.items()
                if item.criado_em < limite
            ]
            for chave in streams_antigos:
                self._audios_stream.pop(chave, None)

    def _gravar_token(self) -> None:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        runtime_token = RUNTIME / "token.txt"
        runtime_token.write_text(self.token, encoding="utf-8")
        try:
            runtime_token.chmod(0o600)
        except OSError:
            pass
        try:
            TOKEN_NO_MOD.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_NO_MOD.write_text(self.token, encoding="utf-8")
            try:
                TOKEN_NO_MOD.chmod(0o600)
            except OSError:
                pass
        except OSError as erro:
            print(f"[HOLLOW-KNIGHT] não gravei token junto do mod: {erro}")

    def iniciar(self, porta: int | None = None) -> None:
        if self._thread_servidor and self._thread_servidor.is_alive():
            return
        from werkzeug.serving import make_server

        porta_final = int(os.getenv("EMILY_HK_PORTA", PORTA_PADRAO)) if porta is None else int(porta)
        self._servidor = make_server(
            HOST, porta_final, self.app,
            threaded=True,
        )
        # Só publica token/catálogo depois de adquirir a porta. Assim uma Emily
        # desktop aberta ao mesmo tempo que o serviço permanente não troca a
        # credencial do mod e depois falha com "address already in use".
        self._gravar_token()
        self._gravador_catalogo(CATALOGO_RUNTIME, CATALOGO_NO_MOD)
        self._iniciar_workers()
        self._thread_servidor = threading.Thread(
            target=self._servidor.serve_forever,
            name="emily-hk-ponte",
            daemon=True,
        )
        self._thread_servidor.start()
        print(f"[HOLLOW-KNIGHT] ponte local em http://{HOST}:{self._servidor.server_port}")

    def encerrar(self) -> None:
        self._parar.set()
        if self._servidor is not None:
            self._servidor.shutdown()
        if self._thread_lotes:
            self._thread_lotes.join(timeout=2)
        if self._thread_worker:
            self._thread_worker.join(timeout=2)
        if self._thread_audio:
            self._thread_audio.join(timeout=2)
        if self._thread_servidor:
            self._thread_servidor.join(timeout=2)


_PONTE: PonteHollowKnight | None = None


def _ler_token(caminho: Path) -> str:
    try:
        return caminho.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _token_compartilhado() -> str:
    """Reutiliza a credencial já instalada em vez de trocá-la a cada processo."""
    tokens = _tokens_compartilhados()
    return tokens[0] if tokens else ""


def _tokens_compartilhados() -> list[str]:
    tokens = []
    for token in (
        str(os.getenv("EMILY_HK_TOKEN") or "").strip(),
        _ler_token(RUNTIME / "token.txt"),
        _ler_token(TOKEN_NO_MOD),
    ):
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def servico_externo_ativo(porta: int | None = None) -> bool:
    """Detecta outra ponte pela porta, mesmo se o upstream estiver sem internet."""
    porta_final = int(os.getenv("EMILY_HK_PORTA", PORTA_PADRAO)) if porta is None else int(porta)
    try:
        with socket.create_connection((HOST, porta_final), timeout=0.35):
            return True
    except OSError:
        return False


def iniciar() -> PonteHollowKnight | None:
    global _PONTE
    if os.getenv("EMILY_HK_ATIVO", "1").strip() == "0":
        return None
    if _PONTE is None and servico_externo_ativo():
        print("[HOLLOW-KNIGHT] ponte permanente já está ativa; usando o serviço externo")
        return None
    if _PONTE is None:
        from .hollow_knight_permanente import CerebroHollowKnightPermanente, SaudeOmniRoute

        memoria = MemoriaHollowKnight()
        cfg = os.getenv
        saude = SaudeOmniRoute(cfg)
        _PONTE = PonteHollowKnight(
            memoria=memoria,
            cerebro=CerebroHollowKnightPermanente(cfg, saude, memoria=memoria),
            pronto=saude.pronto,
        )
        _PONTE.iniciar()
    return _PONTE


def encerrar() -> None:
    global _PONTE
    if _PONTE is not None:
        _PONTE.encerrar()
        _PONTE = None
