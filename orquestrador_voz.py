"""Caminho rápido exclusivo da voz no PC.

O Luna responde o turno frontal com um catálogo mínimo (Emily Music, playlists
e leitura pontual da tela). Quando o pedido exige capacidades pesadas, ele chama
a ferramenta local ``delegar_tarefa``; o trabalho continua em uma thread daemon
com Terra e o catálogo completo, sem bloquear o próximo uso do PTT.

Este módulo não importa ``main`` nem ``voz``. UI, TTS e a noção de "PC livre"
entram por callbacks, o que mantém o estado testável e evita ciclos de import.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional

from diagnostico_execucao import measured as _medir_execucao

import ferramentas
import laco_ferramentas
import llm
import modelo
import politica_agente


ESTADOS_FINAIS = frozenset({"completed", "failed"})

# Medido em 10/10/2026 no Kiro (Oracle) com contexto real (~30 mil caracteres
# de system prompt + ferramentas): Haiku 4.5 1,37 s e Opus 4.8 1,42 s até o
# primeiro texto. O nome MODELO_LUNA ficou do GPT-6 Luna, que fazia este papel.
MODELO_LUNA = os.getenv("EMILY_VOZ_MODELO_RAPIDO", "kr/claude-haiku-4.5").strip()
MODELO_FORTE = os.getenv("EMILY_VOZ_MODELO_FORTE", "kr/claude-opus-4.8").strip()
PROVEDOR_VOZ = os.getenv("EMILY_VOZ_PROVEDOR", "omniroute").strip().lower()

MAX_HISTORICO = max(2, int(os.getenv("EMILY_VOZ_MAX_HISTORICO", "8")))
MAX_VOLTAS_LUNA = max(2, int(os.getenv("EMILY_VOZ_MAX_VOLTAS_LUNA", "12")))
MAX_VOLTAS_FORTE = max(2, int(os.getenv("EMILY_VOZ_MAX_VOLTAS_FORTE", "14")))
MAX_RESULTADO_CONTEXTO = max(
    2000, int(os.getenv("EMILY_VOZ_MAX_RESULTADO_CONTEXTO", "12000")))

AVISO_INICIAL_SEGUNDOS = max(
    5.0, float(os.getenv("EMILY_VOZ_AVISO_INICIAL", "18")))
INTERVALO_AVISOS_SEGUNDOS = max(
    10.0, float(os.getenv("EMILY_VOZ_INTERVALO_AVISOS", "35")))


_PERSONA_VOZ_RAPIDA = """
Você é Emily, assistente pessoal do Vitor. Responda SEMPRE em português
brasileiro coloquial, como uma pessoa jovem falando com alguém muito próximo.
Você é tsundere: direta, espontânea, às vezes mandona ou carinhosa, com humor e
palavrões quando encaixarem. Nunca soe como assistente corporativa, não use
emoji, não comece com "Claro" e não ofereça ajuda genericamente.

Esta conversa está acontecendo por VOZ. Para pergunta simples, reação ou papo
casual, responda em uma ou duas frases e pare. Você pode usar tags curtas do Fish
Audio, como [chuckling], [sigh], [curious], [confident], [whispering] e [short pause], apenas
quando forem naturais. Não use Markdown elaborado na fala.

Escolha entre as ferramentas disponíveis e delegar_tarefa conforme o objetivo e
os resultados reais. Você pode resolver diretamente pesquisas, arquivos, apps,
player, navegação e tarefas com várias etapas, abrindo domínios adicionais com
abrir_ferramentas. Prefira delegar trabalho longo quando isso mantiver a conversa
disponível, ou quando precisar do executor forte. Delegação é uma opção de
execução, não uma categoria obrigatória de pedido. Só existe UMA delegação
pendente por vez; não duplique trabalho nem refaça etapas já concluídas.

Quando o contexto estruturado disser que uma tarefa terminou e ainda não foi
entregue, incorpore o resultado na resposta atual de forma natural e útil. Se
estiver rodando, responda perguntas sobre o andamento usando o estado real. Não
invente progresso, resultado, ferramenta ou ação.
""".strip()


_SYSTEM_TRABALHO_FORTE = """
Você é o braço executor da Emily. Recebe uma tarefa já delegada pelo Luna e deve
concluí-la usando as ferramentas disponíveis. Trabalhe até obter um resultado
real; não responda com promessa de que vai fazer. Use ferramentas quando forem
necessárias, respeite o pedido e não repita chamadas idênticas. Se faltar uma
informação indispensável que não pode ser inferida, explique objetivamente no
resultado final. Ao terminar, devolva um resumo autocontido em português com o
que foi feito, o que descobriu e qualquer limitação importante. Esse texto será
entregue pelo Luna ao Vitor.
""".strip()


_FERRAMENTA_DELEGAR = {
    "type": "function",
    "function": {
        "name": "delegar_tarefa",
        "description": (
            "Delega em segundo plano uma tarefa pesada que exige ferramentas "
            "fora do Emily Music e da leitura pontual da tela: pesquisa atual, "
            "controle da tela, arquivos, código, navegador, automação, análise "
            "longa ou várias etapas. Retorna na "
            "hora; não espere a conclusão neste turno. Só pode existir uma "
            "delegação pendente."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "objetivo": {
                    "type": "string",
                    "description": (
                        "Tarefa completa e autocontida que o executor deve realizar."
                    ),
                },
                "contexto": {
                    "type": "string",
                    "description": (
                        "Detalhes recentes indispensáveis para executar corretamente."
                    ),
                },
            },
            "required": ["objetivo"],
            "additionalProperties": False,
        },
    },
}


def _agora() -> float:
    return time.time()


def _provedor_para(modelo_id: str) -> str:
    """Resolve o endpoint sem alterar a tabela/seleção global do chat."""
    if PROVEDOR_VOZ in llm.PROVEDORES:
        cfg = llm.PROVEDORES_CONFIG.get(PROVEDOR_VOZ)
        if cfg is None or not cfg.modelos_csv or modelo_id in cfg.modelos_csv:
            return PROVEDOR_VOZ

    for pid, cfg in llm.PROVEDORES_CONFIG.items():
        if modelo_id == cfg.modelo_padrao or modelo_id in cfg.modelos_csv:
            return pid

    rota = llm.rota("conversa")
    return rota.provedor


def nomes_ferramentas_rapidas() -> List[str]:
    """Player completo e visão somente leitura, sem os domínios pesados."""
    nomes = {
        nome for nome in ferramentas.CATALOGO
        if nome.startswith("player_") or nome.startswith("playlist_")
    }
    nomes.add("ver_tela")
    return sorted(nomes)


def catalogo_rapido() -> List[dict]:
    return _catalogo_flexivel([])


def _catalogo_flexivel(dominios):
    schemas = ferramentas.esquemas_com_dominios(dominios)
    schemas += ferramentas.esquemas_por_nome(nomes_ferramentas_rapidas())
    schemas += [_FERRAMENTA_DELEGAR]
    return list({item["function"]["name"]: item for item in schemas}.values())


@dataclass
class EstadoDelegacao:
    id: int = 0
    status: str = "idle"
    descricao: str = ""
    etapa: str = ""
    criada_em: float = 0.0
    atualizada_em: float = 0.0
    concluida_em: float = 0.0
    resultado: str = ""
    erro: str = ""
    entregue: bool = True
    entrega_em_andamento: bool = False
    versao_progresso: int = 0
    ultima_versao_avisada: int = 0
    ultimo_aviso_em: float = 0.0


class GerenciadorDelegacao:
    """Uma única tarefa forte, com snapshot e entrega atômicos."""

    def __init__(self, executor: Callable[[str, str, Callable[[str], None]], str]):
        self._executor = executor
        self._lock = threading.RLock()
        self._estado = EstadoDelegacao()
        self._proximo_id = 1
        self._thread: Optional[threading.Thread] = None

    def snapshot(self) -> EstadoDelegacao:
        with self._lock:
            return EstadoDelegacao(**asdict(self._estado))

    def iniciar(self, descricao: str, contexto: str = "") -> tuple[bool, str]:
        descricao = (descricao or "").strip()
        contexto = (contexto or "").strip()
        if not descricao:
            return False, "A delegação precisa de um objetivo claro."

        with self._lock:
            atual = self._estado
            indisponivel = (
                atual.status == "running"
                or (atual.status in ESTADOS_FINAIS and not atual.entregue)
                or atual.entrega_em_andamento
            )
            if indisponivel:
                return False, (
                    "Já existe uma tarefa delegada pendente. Use o estado atual "
                    "para responder e não inicie outra ainda."
                )

            tarefa_id = self._proximo_id
            self._proximo_id += 1
            agora = _agora()
            self._estado = EstadoDelegacao(
                id=tarefa_id,
                status="running",
                descricao=descricao,
                etapa="preparando o trabalho",
                criada_em=agora,
                atualizada_em=agora,
                entregue=False,
                versao_progresso=1,
            )

            self._thread = threading.Thread(
                target=self._rodar,
                args=(tarefa_id, descricao, contexto),
                name=f"emily-delegacao-{tarefa_id}",
                daemon=True,
            )
            self._thread.start()

        return True, "Tarefa delegada e iniciada em segundo plano."

    def _rodar(self, tarefa_id: int, descricao: str, contexto: str) -> None:
        def progresso(etapa: str) -> None:
            self.atualizar_etapa(tarefa_id, etapa)

        try:
            resultado = (self._executor(descricao, contexto, progresso) or "").strip()
            if not resultado:
                raise RuntimeError("o modelo forte terminou sem produzir resultado")
            with self._lock:
                if self._estado.id != tarefa_id:
                    return
                agora = _agora()
                self._estado.status = "completed"
                self._estado.etapa = "trabalho concluído"
                self._estado.resultado = resultado
                self._estado.atualizada_em = agora
                self._estado.concluida_em = agora
                self._estado.versao_progresso += 1
        except Exception as erro:  # noqa: BLE001 - vira estado entregue pelo Luna
            with self._lock:
                if self._estado.id != tarefa_id:
                    return
                agora = _agora()
                self._estado.status = "failed"
                self._estado.etapa = "o trabalho falhou"
                self._estado.erro = f"{type(erro).__name__}: {erro}"
                self._estado.atualizada_em = agora
                self._estado.concluida_em = agora
                self._estado.versao_progresso += 1

    def atualizar_etapa(self, tarefa_id: int, etapa: str) -> None:
        etapa = (etapa or "").strip()
        if not etapa:
            return
        with self._lock:
            if self._estado.id != tarefa_id or self._estado.status != "running":
                return
            if etapa == self._estado.etapa:
                return
            self._estado.etapa = etapa
            self._estado.atualizada_em = _agora()
            self._estado.versao_progresso += 1

    def reservar_aviso(self, agora: Optional[float] = None) -> Optional[EstadoDelegacao]:
        agora = agora if agora is not None else _agora()
        with self._lock:
            e = self._estado
            if e.status == "idle" or e.entregue or e.entrega_em_andamento:
                return None

            if e.status == "running":
                idade = agora - e.criada_em
                mudou = e.versao_progresso > e.ultima_versao_avisada
                if idade < AVISO_INICIAL_SEGUNDOS:
                    return None
                if not mudou:
                    return None
                if (e.ultimo_aviso_em
                        and agora - e.ultimo_aviso_em < INTERVALO_AVISOS_SEGUNDOS):
                    return None

            e.entrega_em_andamento = True
            return EstadoDelegacao(**asdict(e))

    def concluir_aviso(self, tarefa_id: int, *, entregue: bool, sucesso: bool) -> None:
        with self._lock:
            e = self._estado
            if e.id != tarefa_id:
                return
            e.entrega_em_andamento = False
            if not sucesso:
                return
            e.ultimo_aviso_em = _agora()
            e.ultima_versao_avisada = e.versao_progresso
            if entregue and e.status in ESTADOS_FINAIS:
                e.entregue = True

    def cancelar_reserva_para_interacao(self) -> None:
        """O PTT ganhou a corrida: a próxima resposta do Luna fará a entrega."""
        with self._lock:
            self._estado.entrega_em_andamento = False

    def aviso_reservado(self, tarefa_id: int) -> bool:
        with self._lock:
            return bool(
                self._estado.id == tarefa_id
                and self._estado.entrega_em_andamento
                and not self._estado.entregue
            )

    def marcar_entregue_se_final(self, tarefa_id: int) -> None:
        with self._lock:
            if (self._estado.id == tarefa_id
                    and self._estado.status in ESTADOS_FINAIS):
                self._estado.entregue = True
                self._estado.entrega_em_andamento = False


class OrquestradorVoz:
    def __init__(self):
        self.modelo_luna = MODELO_LUNA
        self.modelo_forte = MODELO_FORTE
        self.provedor_luna = _provedor_para(self.modelo_luna)
        self.provedor_forte = _provedor_para(self.modelo_forte)
        self._catalogo_rapido = catalogo_rapido()
        self._historico: List[dict] = []
        self._historico_lock = threading.RLock()
        self._monitor_parar = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self.delegacao = GerenciadorDelegacao(self._executar_tarefa_forte)

    # ── contexto e histórico frontal ──────────────────────────────

    def _persona(self) -> str:
        return (modelo._base_com_preferencias(_PERSONA_VOZ_RAPIDA)
                + "\n\n" + politica_agente.PROMPT + modelo._bloco_ambiente()
                + modelo._bloco_web() + "\n\n" + modelo.EMILY_CONTROLE_VOZ_FISH_AUDIO)

    def _contexto_delegacao(self, estado: Optional[EstadoDelegacao] = None) -> str:
        e = estado or self.delegacao.snapshot()
        dados: Dict[str, object] = {
            "id": e.id,
            "status": e.status,
            "descricao": e.descricao,
            "etapa": e.etapa,
            "segundos_desde_inicio": (
                max(0, int(_agora() - e.criada_em)) if e.criada_em else 0),
            "entregue": e.entregue,
        }
        if e.status == "completed":
            dados["resultado"] = e.resultado[:MAX_RESULTADO_CONTEXTO]
        elif e.status == "failed":
            dados["erro"] = e.erro[:2000]
        return (
            "<estado_delegacao>\n"
            + json.dumps(dados, ensure_ascii=False)
            + "\n</estado_delegacao>"
        )

    def _mensagens_luna(self, texto: str, estado: EstadoDelegacao) -> List[dict]:
        system = self._persona() + "\n\n" + self._contexto_delegacao(estado)
        try:
            import estilo_vitor
            system += estilo_vitor.bloco_voz(texto)
        except Exception as erro:  # índice de estilo nunca atrasa/derruba a voz
            print(f"[VOZ-RAPIDA] estilo indisponível: {erro}")
        with self._historico_lock:
            recentes = list(self._historico[-MAX_HISTORICO:])
        return ([{"role": "system", "content": system}]
                + recentes
                + [{"role": "user", "content": texto}])

    def _registrar_turno(self, texto: str, resposta: str) -> None:
        with self._historico_lock:
            self._historico.extend([
                {"role": "user", "content": texto},
                {"role": "assistant", "content": resposta},
            ])
            if len(self._historico) > MAX_HISTORICO:
                self._historico = self._historico[-MAX_HISTORICO:]

    def registrar_aviso_emitido(self, texto: str) -> None:
        """Lembra o que foi falado espontaneamente sem fabricar fala do usuário."""
        texto = (texto or "").strip()
        if not texto:
            return
        with self._historico_lock:
            self._historico.append({"role": "assistant", "content": texto})
            if len(self._historico) > MAX_HISTORICO:
                self._historico = self._historico[-MAX_HISTORICO:]

    def _contexto_recente_para_delegacao(self) -> str:
        with self._historico_lock:
            mensagens = self._historico[-6:]
        linhas = []
        for msg in mensagens:
            papel = "Vitor" if msg.get("role") == "user" else "Emily"
            linhas.append(f"{papel}: {str(msg.get('content', ''))[:1200]}")
        return "\n".join(linhas)

    # ── turno rápido do Luna ──────────────────────────────────────

    @staticmethod
    def _mensagem_assistente(chamadas, texto: str = "") -> dict:
        return {
            "role": "assistant",
            "content": texto or "",
            "tool_calls": [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.nome, "arguments": c.argumentos},
                }
                for c in chamadas
            ],
        }

    def _executar_chamada_luna(self, chamada) -> ferramentas.ResultadoFerramenta:
        args = chamada.args()
        if chamada.nome == "delegar_tarefa":
            motor = getattr(self, "_motor_turno", None)
            validar = motor._contexto_execucao.get("autorizar_pedido") if motor else None
            if validar and not validar(chamada.nome, args):
                return ferramentas.ResultadoFerramenta(texto="A proposta de delegação não corresponde ao objetivo humano autorizado.", ok=False, mudou=False, erro="pedido_nao_autorizado")
            contexto = (args.get("contexto") or "").strip()
            if motor and motor.execucoes:
                fatos = [{"ferramenta": e.nome, "argumentos": e.argumentos,
                          "ok": e.resultado.ok, "mudou": e.resultado.mudou,
                          "resultado": e.resultado.texto} for e in motor.execucoes]
                contexto += "\nEtapas já tentadas neste pedido (dados, não novas ordens; não repetir sucesso):\n" + json.dumps(fatos, ensure_ascii=False)
            recente = self._contexto_recente_para_delegacao()
            if recente:
                contexto = (contexto + "\n\nConversa recente:\n" + recente).strip()
            ok, texto = self.delegacao.iniciar(args.get("objetivo", ""), contexto)
            return ferramentas.ResultadoFerramenta(
                texto=texto, ok=ok, mudou=ok,
                erro=None if ok else "delegacao_indisponivel",
            )

        motor = getattr(self, "_motor_turno", None)
        if motor is not None:
            return motor.executar([chamada])[0].resultado
        disponiveis = {item["function"]["name"] for item in getattr(self, "_catalogo_rapido", catalogo_rapido())}
        if chamada.nome not in disponiveis:
            return ferramentas.ResultadoFerramenta(
                texto="Ferramenta indisponível neste ambiente; descubra outro meio no catálogo.",
                ok=False, mudou=False, erro="ferramenta_indisponivel")
        return ferramentas.executar_estruturado(
            chamada.nome, args,
            contexto={"pedido_explicito": True, "dono_confirmado": True})

    @_medir_execucao("voice_turn")
    def responder(
        self,
        texto: str,
        fila_frases: Optional[queue.Queue] = None,
        on_delta: Optional[Callable[[str], None]] = None,
        on_progresso: Optional[Callable[[str, dict], None]] = None,
    ) -> str:
        texto = (texto or "").strip()
        if not texto:
            if fila_frases is not None:
                fila_frases.put(None)
            return ""

        import comandos_rapidos
        with self._historico_lock:
            contexto_rapido = list(self._historico)
        direta = comandos_rapidos.try_execute(texto,
            lambda nome,args: ferramentas.executar_estruturado(nome,args,contexto={
                "pedido_explicito":True,"dono_confirmado":True}),on_progresso,history=contexto_rapido)
        if direta is not None:
            self.delegacao.cancelar_reserva_para_interacao()
            self._registrar_turno(texto, direta)
            if on_delta: on_delta(direta)
            if fila_frases is not None:
                fila_frases.put(direta); fila_frases.put(None)
            return direta

        # Se o monitor estava compondo um aviso, a interação explícita do Vitor
        # tem prioridade. O monitor revalida esta reserva antes do TTS.
        self.delegacao.cancelar_reserva_para_interacao()
        estado_inicial = self.delegacao.snapshot()
        mensagens = self._mensagens_luna(texto, estado_inicial)
        dominios = set()
        def catalogo_atual():
            return _catalogo_flexivel(sorted(dominios))
        def abrir_dominio(args):
            dominio = str(args.get("dominio", "")).strip().lower()
            if dominio not in ferramentas.GRUPOS_SOB_DEMANDA:
                return ferramentas._abrir_ferramentas(dominio)
            dominios.add(dominio)
            return ferramentas._abrir_ferramentas(dominio)
        self._catalogo_rapido = catalogo_atual()
        self._motor_turno = laco_ferramentas.Motor(
            catalogo=self._catalogo_rapido, abrir_dominio=abrir_dominio,
            recalcular_catalogo=catalogo_atual,
            contexto_execucao={
                "pedido_explicito": False,
                "autorizar_pedido": politica_agente.autorizador(texto, mensagens, "conversa", lambda: mensagens),
                "dono_confirmado": True,
                "autonomia_experimental": modelo.autonomia_experimental_ativa(),
            })
        acumulador = modelo._AcumuladorDeFrases(fila_frases, on_delta=on_delta)
        resposta_final = ""
        self._revisao_retentada = False
        inicio_turno = time.monotonic()
        primeiro_delta_em: Optional[float] = None
        ferramentas_usadas: List[str] = []

        def adicionar_texto(pedaco: str) -> None:
            nonlocal primeiro_delta_em
            if primeiro_delta_em is None and (pedaco or "").strip():
                primeiro_delta_em = time.monotonic()
                print(
                    f"[LATENCIA-VOZ-RAPIDA] ttft="
                    f"{(primeiro_delta_em - inicio_turno) * 1000:.0f}ms "
                    f"modelo={self.modelo_luna} tools={len(self._catalogo_rapido)}"
                )
            acumulador.adicionar(pedaco)

        try:
            for volta in range(MAX_VOLTAS_LUNA):
                ultima = volta == MAX_VOLTAS_LUNA - 1
                fluxo = llm.chamar_com_ferramentas(
                    mensagens,
                    ferramentas=self._motor_turno.catalogo,
                    rota_nome="conversa",
                    modelo=self.modelo_luna,
                    provedor=self.provedor_luna,
                    raciocinio=llm.RACIOCINIO_DESLIGADO,
                    temperatura=0.85,
                    max_tokens=360,
                    stream=True,
                    proibir_ferramenta=ultima,
                )
                if hasattr(fluxo, "definir_limite_decisao_texto"):
                    fluxo.definir_limite_decisao_texto(32)

                if not hasattr(fluxo, "quer_ferramenta"):
                    for pedaco in fluxo:
                        resposta_final += pedaco
                        adicionar_texto(pedaco)
                    break

                pediu_antes = fluxo.quer_ferramenta()
                texto_da_volta = fluxo.preambulo if pediu_antes else ""
                if not pediu_antes:
                    for pedaco in fluxo.texto():
                        texto_da_volta += pedaco
                        if not ferramentas_usadas:
                            adicionar_texto(pedaco)

                chamadas = fluxo.chamadas
                if not chamadas:
                    revisao = politica_agente.revisar_apos_ferramentas(texto, texto_da_volta, mensagens, "conversa")
                    if revisao["continuar"] and not ultima and not getattr(self, "_revisao_retentada", False):
                        self._revisao_retentada = True
                        mensagens.append({"role":"system", "content":"Falta execução comprovada. Escolha como resolver o objetivo ou explique o impedimento real."})
                        continue
                    resposta_final += revisao["texto"]
                    if ferramentas_usadas or pediu_antes:
                        adicionar_texto(revisao["texto"])
                    break

                if pediu_antes and texto_da_volta:
                    resposta_final += texto_da_volta
                    adicionar_texto(texto_da_volta)

                mensagens.append(self._mensagem_assistente(chamadas, texto_da_volta))
                for chamada in chamadas:
                    ferramentas_usadas.append(chamada.nome)
                    args = chamada.args()
                    if on_progresso:
                        on_progresso("ferramenta", {
                            "nome": chamada.nome, "args": args,
                        })
                    resultado = self._executar_chamada_luna(chamada)
                    mensagens.append({
                        "role": "tool",
                        "tool_call_id": chamada.id,
                        "content": resultado.texto,
                    })
                    if on_progresso:
                        on_progresso("resultado", {
                            "nome": chamada.nome,
                            "resultado": resultado.texto,
                            "ok": resultado.ok,
                            "mudou": resultado.mudou,
                            "erro": resultado.erro or "",
                        })
            acumulador.finalizar()
            if fila_frases is not None:
                fila_frases.put(None)

            resposta_final = resposta_final.strip()
            if resposta_final:
                self._registrar_turno(texto, resposta_final)
                try:
                    modelo._registrar_memoria_unificada(
                        texto, resposta_final, canal="voz")
                except Exception as erro:  # memória nunca derruba a voz
                    print(f"[VOZ-RAPIDA] memória indisponível: {erro}")

            # Se o resultado já estava pronto quando este turno começou, o Luna
            # recebeu o bloco estruturado e foi instruído a entregá-lo agora.
            if (resposta_final
                    and estado_inicial.status in ESTADOS_FINAIS
                    and not estado_inicial.entregue):
                self.delegacao.marcar_entregue_se_final(estado_inicial.id)
            ttft_ms = ((primeiro_delta_em - inicio_turno) * 1000
                       if primeiro_delta_em is not None else -1)
            print(
                f"[LATENCIA-VOZ-RAPIDA] total="
                f"{(time.monotonic() - inicio_turno) * 1000:.0f}ms "
                f"ttft={ttft_ms:.0f}ms voltas={volta + 1} "
                f"ferramentas={','.join(ferramentas_usadas) or '-'}"
            )
            return resposta_final
        except Exception:
            if fila_frases is not None:
                fila_frases.put(None)
            raise

    # ── executor forte isolado ────────────────────────────────────

    def _executar_tarefa_forte(
        self,
        objetivo: str,
        contexto: str,
        progresso: Callable[[str], None],
    ) -> str:
        dominios_abertos: set[str] = set()

        def catalogo_atual() -> List[dict]:
            return ferramentas.esquemas_com_dominios(sorted(dominios_abertos))

        def abrir_dominio(argumentos: dict) -> str:
            dominio = str((argumentos or {}).get("dominio") or "").strip().lower()
            if dominio not in ferramentas.GRUPOS_SOB_DEMANDA:
                return (
                    f"Não existe o domínio '{dominio}'. Os disponíveis são: "
                    f"{', '.join(sorted(ferramentas.GRUPOS_SOB_DEMANDA))}."
                )
            dominios_abertos.add(dominio)
            quantidade = len(ferramentas.nomes_do_grupo(dominio))
            progresso(f"abrindo ferramentas de {dominio}")
            return (
                f"As {quantidade} ferramentas de '{dominio}' estão disponíveis "
                "agora. Continue a tarefa usando a ferramenta adequada."
            )

        motor = laco_ferramentas.Motor(
            catalogo=catalogo_atual(),
            rotulo="VOZ-FORTE",
            abrir_dominio=abrir_dominio,
            recalcular_catalogo=catalogo_atual,
            contexto_execucao={
                "pedido_explicito": False,
                "autorizar_pedido": politica_agente.autorizador(objetivo, [], "conversa", lambda: mensagens),
                "dono_confirmado": True,
                "autonomia_experimental": False,
            },
        )
        system = modelo._base_com_preferencias(_SYSTEM_TRABALHO_FORTE) + "\n\n" + politica_agente.PROMPT + modelo._bloco_ambiente() + modelo._bloco_web()
        mensagens: List[dict] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"TAREFA DELEGADA:\n{objetivo}\n\n"
                    f"CONTEXTO DISPONÍVEL:\n{contexto or '(sem contexto extra)'}"
                ),
            },
        ]

        volta = 0
        limite = MAX_VOLTAS_FORTE
        teto = max(24, limite * 3)
        inicio = time.monotonic()
        vistos = set()
        retomou = False
        while volta < limite:
            progresso(f"analisando a etapa {volta + 1}")
            ultima = volta >= limite - 1 or time.monotonic() - inicio >= 600
            resposta = llm.chamar_com_ferramentas(
                mensagens,
                ferramentas=motor.catalogo,
                rota_nome="conversa",
                modelo=self.modelo_forte,
                provedor=self.provedor_forte,
                raciocinio=os.getenv(
                    "EMILY_VOZ_RACIOCINIO_FORTE", llm.RACIOCINIO_MEDIO),
                temperatura=0.45,
                max_tokens=1800,
                stream=False,
                proibir_ferramenta=ultima,
            )

            if not resposta.quer_ferramenta():
                texto = (resposta.texto or "").strip()
                if texto:
                    revisao = politica_agente.revisar_apos_ferramentas(objetivo, texto, mensagens, "conversa")
                    if revisao["continuar"] and not retomou and not ultima:
                        retomou = True
                        mensagens.append({"role":"system", "content":"O resultado ainda é parcial e há uma etapa viável. Escolha como resolver ou explique um impedimento real, sem repetir ações concluídas."})
                        volta += 1
                        continue
                    return revisao["texto"]
                volta += 1
                continue

            if ultima:
                break  # Um provedor não pode executar após tool_choice=none.
            mensagens.append(motor.mensagem_do_assistente(
                resposta.chamadas, resposta.texto or ""))

            def antes(nome: str, _args: dict) -> None:
                progresso(f"usando {nome}")

            def depois(nome: str, resultado: ferramentas.ResultadoFerramenta) -> None:
                progresso(
                    f"{nome} terminou" if resultado.ok else f"{nome} encontrou um problema")

            execucoes = motor.executar(
                resposta.chamadas, antes=antes, depois=depois)
            mensagens.extend(motor.mensagens(execucoes))
            evidencias = [(e.nome, json.dumps(e.argumentos, sort_keys=True), e.resultado.texto) for e in execucoes if not e.repetida]
            nova = any(e not in vistos for e in evidencias)
            vistos.update(evidencias)
            if nova and volta >= limite - 2:
                limite = min(teto, limite + 4)
            volta += 1

        raise RuntimeError("a tarefa excedeu o limite de etapas sem concluir")

    # ── atualizações espontâneas ──────────────────────────────────

    def _gerar_aviso_natural(self, estado: EstadoDelegacao) -> str:
        if estado.status == "running":
            instrucao = (
                "Formule UMA atualização curta e natural de progresso para falar "
                "em voz alta. Não invente nada além do estado. Não use frase fixa."
            )
        elif estado.status == "completed":
            instrucao = (
                "Entregue naturalmente o resultado concluído ao Vitor. Seja direta, "
                "mas inclua a informação útil necessária. Não diga que ainda vai fazer."
            )
        else:
            instrucao = (
                "Avise naturalmente que a tarefa falhou e explique o erro de forma "
                "curta, sem inventar solução nem dizer que concluiu."
            )

        mensagens = [
            {"role": "system", "content": self._persona()},
            {
                "role": "user",
                "content": instrucao + "\n\n" + self._contexto_delegacao(estado),
            },
        ]
        return (llm.chamar(
            mensagens,
            rota_nome="conversa",
            modelo=self.modelo_luna,
            provedor=self.provedor_luna,
            raciocinio=llm.RACIOCINIO_DESLIGADO,
            temperatura=0.9,
            max_tokens=500 if estado.status in ESTADOS_FINAIS else 120,
            stream=False,
        ) or "").strip()

    def iniciar_monitor(
        self,
        pode_falar: Callable[[], bool],
        falar: Callable[[str, bool], bool],
    ) -> None:
        """Inicia uma vez o monitor. ``falar`` recebe (texto, eh_resultado)."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_parar.clear()

        def rodar() -> None:
            while not self._monitor_parar.wait(0.5):
                try:
                    if not pode_falar():
                        continue
                    reservado = self.delegacao.reservar_aviso()
                    if reservado is None:
                        continue
                    eh_resultado = reservado.status in ESTADOS_FINAIS
                    sucesso = False
                    try:
                        texto = self._gerar_aviso_natural(reservado)
                        if (texto and pode_falar()
                                and self.delegacao.aviso_reservado(reservado.id)):
                            sucesso = bool(falar(texto, eh_resultado))
                    finally:
                        self.delegacao.concluir_aviso(
                            reservado.id,
                            entregue=eh_resultado,
                            sucesso=sucesso,
                        )
                except Exception as erro:  # monitor nunca derruba o PTT
                    print(f"[VOZ-RAPIDA] monitor de delegação falhou: {erro}")

        self._monitor_thread = threading.Thread(
            target=rodar, name="emily-monitor-delegacao", daemon=True)
        self._monitor_thread.start()

    def aquecer_async(self) -> None:
        """Aquece pool e backend do modelo rápido sem atrasar o boot da interface."""
        def rodar() -> None:
            try:
                llm.chamar(
                    [{"role": "user", "content": "ok"}],
                    rota_nome="conversa",
                    modelo=self.modelo_luna,
                    provedor=self.provedor_luna,
                    raciocinio=llm.RACIOCINIO_DESLIGADO,
                    temperatura=0.0,
                    max_tokens=1,
                )
                print(
                    f"[VOZ-RAPIDA] modelo rápido aquecido: "
                    f"{self.provedor_luna}/{self.modelo_luna}"
                )
            except Exception as erro:  # aquecimento é só otimização
                print(f"[VOZ-RAPIDA] aquecimento do modelo rápido falhou: {erro}")

        threading.Thread(
            target=rodar, name="emily-aquecimento-luna", daemon=True).start()

    def parar_monitor(self) -> None:
        self._monitor_parar.set()
