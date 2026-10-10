"""Memória leve e persistente da campanha de Hollow Knight.

É propositalmente separada da memória unificada da Emily: usa somente SQLite,
telemetria do jogo e um perfil pessoal mínimo. Mantém uma linha do tempo por
slot, totais, áreas e padrões observáveis sem embeddings, ChromaDB ou extração
de fatos por LLM.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .hollow_knight_protocolo import EventoJogo


ARQUIVO_PADRAO = (
    Path.home() / ".local/share/emily/hollow_knight/memoria.sqlite3"
)
PERIGOS = {1: "espinhos", 2: "ácido", 3: "lava", 4: "abismo"}
# Marcos que contam a história que a Emily está descobrindo junto com o Vitor:
# conversas com NPCs, chefes, áreas, poderes e itens. Serve para ela comentar a
# história de vez em quando sem precisar garimpar o ruído de combate dos
# "recentes" (que num modo tagarela fica cheio de dano e inimigo morto).
TIPOS_HISTORIA = (
    "npc_dialogo", "boss_derrotado", "boss_encerrado", "area_nova",
    "magia_adquirida", "habilidade_adquirida", "item_importante_adquirido",
    "estacao_desbloqueada", "banco_descoberto", "charm_adquirido",
    "amuleto_adquirido",
)
LIMITE_HISTORIA = 6


def perfil_minimo() -> dict:
    """Lê só nome e instrução explícita curta; nunca avatar/conversas/memória."""
    caminho = Path(
        os.getenv(
            "EMILY_ARQUIVO_PREFERENCIAS",
            str(Path.home() / ".emily_preferencias.json"),
        )
    )
    dados = {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        if isinstance(bruto, dict):
            dados = bruto
    except (OSError, ValueError, TypeError):
        pass
    nome = str(dados.get("nome") or os.getenv("EMILY_USUARIO", "Vitor")).strip()
    extra = str(dados.get("personalidade_extra") or "").strip()[:600]
    return {
        "nome": nome[:80] or "Vitor",
        "base": (
            "É o criador da Emily e prefere proximidade, informalidade, "
            "zoeira contextual e apoio sincero sem tratamento genérico."
        ),
        "preferencia_explicita": extra,
    }


class MemoriaHollowKnight:
    def __init__(self, arquivo: Path | str | None = None, relogio=time.time) -> None:
        configurado = os.getenv("EMILY_HK_MEMORIA_ARQUIVO", "").strip()
        self.arquivo = Path(arquivo or configurado or ARQUIVO_PADRAO).expanduser()
        self._relogio = relogio
        self._lock = threading.RLock()
        self._preparar()

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.arquivo), timeout=8)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def _preparar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.arquivo.parent.chmod(0o700)
        except OSError:
            pass
        with self._lock, self._conectar() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS campanhas (
                    campanha_id TEXT PRIMARY KEY,
                    criada_em REAL NOT NULL,
                    atualizada_em REAL NOT NULL,
                    ultima_sessao_em REAL NOT NULL,
                    sessoes INTEGER NOT NULL DEFAULT 0,
                    tempo_jogo REAL NOT NULL DEFAULT 0,
                    eventos INTEGER NOT NULL DEFAULT 0,
                    mortes INTEGER NOT NULL DEFAULT 0,
                    danos INTEGER NOT NULL DEFAULT 0,
                    dano_total INTEGER NOT NULL DEFAULT 0,
                    inimigos INTEGER NOT NULL DEFAULT 0,
                    poderes INTEGER NOT NULL DEFAULT 0,
                    bancos INTEGER NOT NULL DEFAULT 0,
                    areas INTEGER NOT NULL DEFAULT 0,
                    ultima_area TEXT NOT NULL DEFAULT '',
                    ultima_cena TEXT NOT NULL DEFAULT '',
                    ultimo_progresso_em REAL NOT NULL,
                    vida_maxima INTEGER NOT NULL DEFAULT 0,
                    dano_ferrao INTEGER NOT NULL DEFAULT 0,
                    geo_maximo INTEGER NOT NULL DEFAULT 0,
                    maior_ociosidade REAL NOT NULL DEFAULT 0,
                    estado_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS sessoes (
                    sessao_id TEXT PRIMARY KEY,
                    campanha_id TEXT NOT NULL,
                    iniciada_em REAL NOT NULL,
                    ultimo_contato REAL NOT NULL,
                    ultimo_tempo_jogo REAL NOT NULL DEFAULT 0,
                    versao_mod TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(campanha_id) REFERENCES campanhas(campanha_id)
                );
                CREATE TABLE IF NOT EXISTS eventos (
                    numero INTEGER PRIMARY KEY AUTOINCREMENT,
                    chave TEXT UNIQUE NOT NULL,
                    campanha_id TEXT NOT NULL,
                    ocorrido_em REAL NOT NULL,
                    tipo TEXT NOT NULL,
                    cena_id TEXT NOT NULL DEFAULT '',
                    dados_json TEXT NOT NULL DEFAULT '{}',
                    resumo TEXT NOT NULL DEFAULT '',
                    importancia INTEGER NOT NULL DEFAULT 0,
                    derivado INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(campanha_id) REFERENCES campanhas(campanha_id)
                );
                CREATE INDEX IF NOT EXISTS idx_eventos_campanha_tempo
                    ON eventos(campanha_id, ocorrido_em DESC);
                CREATE INDEX IF NOT EXISTS idx_eventos_campanha_tipo_tempo
                    ON eventos(campanha_id, tipo, ocorrido_em DESC);
                CREATE TABLE IF NOT EXISTS eventos_processados (
                    chave TEXT PRIMARY KEY,
                    campanha_id TEXT NOT NULL,
                    ocorrido_em REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS areas (
                    campanha_id TEXT NOT NULL,
                    area TEXT NOT NULL,
                    primeira_vez REAL NOT NULL,
                    ultima_vez REAL NOT NULL,
                    visitas INTEGER NOT NULL DEFAULT 0,
                    mortes INTEGER NOT NULL DEFAULT 0,
                    danos INTEGER NOT NULL DEFAULT 0,
                    inimigos INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(campanha_id, area),
                    FOREIGN KEY(campanha_id) REFERENCES campanhas(campanha_id)
                );
                CREATE TABLE IF NOT EXISTS padroes (
                    campanha_id TEXT NOT NULL,
                    padrao TEXT NOT NULL,
                    ultimo_em REAL NOT NULL,
                    nivel INTEGER NOT NULL DEFAULT 0,
                    ocorrencias INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(campanha_id, padrao),
                    FOREIGN KEY(campanha_id) REFERENCES campanhas(campanha_id)
                );
                """
            )
            self._migrar_perigos_nao_confirmados(con)
            self._migrar_poderes_automaticos(con)
        try:
            self.arquivo.chmod(0o600)
        except OSError:
            pass

    def registrar_sessao(self, sessao, configuracao: dict | None = None) -> None:
        agora = self._relogio()
        campanha = str(sessao.campanha_id or "save-desconhecido")[:120]
        with self._lock, self._conectar() as con:
            con.execute(
                """INSERT INTO campanhas(
                       campanha_id, criada_em, atualizada_em, ultima_sessao_em,
                       ultimo_progresso_em)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(campanha_id) DO UPDATE SET
                       atualizada_em=excluded.atualizada_em""",
                (campanha, agora, agora, agora, agora),
            )
            con.execute(
                """INSERT OR REPLACE INTO sessoes(
                       sessao_id,campanha_id,iniciada_em,ultimo_contato,
                       ultimo_tempo_jogo,versao_mod)
                   VALUES(?,?,?,?,0,?)""",
                (sessao.id, campanha, agora, agora, str(sessao.versao_mod or "")[:40]),
            )

    def registrar_eventos(self, sessao, eventos: list[EventoJogo]) -> list[EventoJogo]:
        if not eventos:
            return []
        derivados: list[EventoJogo] = []
        with self._lock, self._conectar() as con:
            for evento in eventos:
                derivados.extend(self._registrar_evento(con, sessao, evento))
            self._limitar_retencao(con, sessao.campanha_id)
        return derivados

    def _registrar_evento(self, con, sessao, evento: EventoJogo) -> list[EventoJogo]:
        agora = min(max(float(evento.criado_em or self._relogio()), 0), self._relogio() + 60)
        campanha = str(sessao.campanha_id or "save-desconhecido")[:120]
        dados = dict(evento.dados or {})
        chave_evento = f"{campanha}:{evento.id}"
        novo = con.execute(
            "INSERT OR IGNORE INTO eventos_processados(chave,campanha_id,ocorrido_em) VALUES(?,?,?)",
            (chave_evento, campanha, agora),
        ).rowcount > 0
        if not novo:
            return []
        anterior = con.execute(
            "SELECT * FROM campanhas WHERE campanha_id=?", (campanha,)
        ).fetchone()
        if anterior is None:
            con.execute(
                """INSERT INTO campanhas(
                       campanha_id,criada_em,atualizada_em,ultima_sessao_em,
                       ultimo_progresso_em)
                   VALUES(?,?,?,?,?)""",
                (campanha, agora, agora, agora, agora),
            )
            con.execute(
                """INSERT OR IGNORE INTO sessoes(
                       sessao_id,campanha_id,iniciada_em,ultimo_contato,
                       ultimo_tempo_jogo,versao_mod)
                   VALUES(?,?,?,?,0,?)""",
                (sessao.id, campanha, agora, agora, str(sessao.versao_mod or "")[:40]),
            )
            anterior = con.execute(
                "SELECT * FROM campanhas WHERE campanha_id=?", (campanha,)
            ).fetchone()
        estado_antigo = self._json(anterior["estado_json"])
        area = self._area(evento, dados, estado_antigo)
        importancia = self._importancia(evento.tipo, dados)
        resumo = self._resumir(evento.tipo, dados, area)
        if evento.tipo == "jogo_iniciado":
            pausa = max(0.0, agora - float(anterior["ultima_sessao_em"]))
            dados["pausa_desde_ultima_sessao"] = round(pausa, 1)
            if self._int(anterior["sessoes"]) == 0:
                resumo = "A Emily começou a acompanhar esta campanha."
            elif pausa >= 4 * 3600:
                resumo = f"Retornou à campanha após {self._duracao(pausa)}."
            else:
                resumo = "Uma nova sessão de jogo começou."
        guardar = evento.tipo != "estado" or self._deve_guardar_snapshot(
            con, campanha, agora, dados, estado_antigo
        )
        inseriu = True
        if guardar:
            inseriu = self._inserir_evento(
                con, chave_evento, campanha, agora, evento.tipo,
                evento.cena_id, dados, resumo, importancia, 0,
            )
        if not inseriu:
            return []

        atual = dict(estado_antigo)
        if evento.tipo == "estado":
            atual.update(dados)
        if area:
            atual["area"] = area
        progresso, motivos = self._detectar_progresso(
            con, campanha, evento, dados, anterior, area
        )
        self._atualizar_totais(
            con, sessao, evento, dados, anterior, atual, area, agora, progresso
        )
        saida = []
        # Eventos explícitos como área/boss/charm já são comentáveis por conta
        # própria. A observação derivada serve para progressos silenciosos que
        # aparecem num snapshot: vida, ferrão ou habilidade nova.
        if progresso and motivos and evento.tipo == "estado":
            saida += self._observacao(
                con, sessao, evento, "progresso_percebido", 45,
                "A Emily percebeu progresso concreto na campanha.",
                {"motivos": motivos}, cooldown=90,
            )
        progresso_antigo = self._json(estado_antigo.get("progresso"))
        progresso_atual = self._json(dados.get("progresso"))
        if evento.tipo == "estado" and progresso_atual and not progresso_antigo:
            # A 0.4.3 não enviava este retrato. Registra o estado conhecido na
            # atualização, sem fingir que cada aquisição acabou de acontecer.
            self._inserir_evento(
                con,
                f"{campanha}:reconciliacao-progresso-v044",
                campanha,
                agora,
                "progresso_reconciliado",
                evento.cena_id,
                {"progresso": progresso_atual, "nao_retroativo": True},
                "Estado atual de progresso reconhecido após atualização do rastreador.",
                30,
                1,
            )
        if evento.tipo in {"dano", "quase_morte"}:
            saida += self._padroes_dano(con, sessao, evento, dados, agora, area)
        elif evento.tipo == "morte":
            saida += self._padroes_morte(con, sessao, evento, agora, area)
        elif evento.tipo == "estado":
            saida += self._padroes_estado(con, sessao, evento, dados, agora, anterior)
        return saida

    def _atualizar_totais(
        self, con, sessao, evento, dados, anterior, estado, area, agora, progresso
    ) -> None:
        tipo = evento.tipo
        morte = 1 if tipo == "morte" else 0
        dano = 1 if tipo in {"dano", "quase_morte"} else 0
        inimigo = 1 if tipo == "inimigo_morto" else 0
        poder = 1 if tipo == "poder_usado" else 0
        banco = 1 if tipo == "banco" else 0
        inicio = 1 if tipo == "jogo_iniciado" else 0
        dano_total = max(0, self._int(dados.get("dano"))) if dano else 0
        vida_max = max(self._int(anterior["vida_maxima"]), self._int(dados.get("vida_maxima")))
        ferrao = max(self._int(anterior["dano_ferrao"]), self._int(dados.get("dano_ferrao")))
        geo = max(self._int(anterior["geo_maximo"]), self._int(dados.get("geo")))
        ocioso = max(0.0, self._float(dados.get("parado_segundos")))
        delta_tempo = 0.0
        if tipo == "estado":
            tempo = max(0.0, self._float(dados.get("tempo_sessao")))
            delta_tempo = max(
                0.0, min(self._float(dados.get("segundos_ativos_delta")), 30.0)
            )
            con.execute(
                "UPDATE sessoes SET ultimo_tempo_jogo=?,ultimo_contato=? WHERE sessao_id=?",
                (tempo, agora, sessao.id),
            )
        con.execute(
            """UPDATE campanhas SET
                   atualizada_em=?, eventos=eventos+?, tempo_jogo=tempo_jogo+?,
                   sessoes=sessoes+?,
                   ultima_sessao_em=CASE WHEN ? THEN ? ELSE ultima_sessao_em END,
                   mortes=mortes+?, danos=danos+?, dano_total=dano_total+?,
                   inimigos=inimigos+?, poderes=poderes+?, bancos=bancos+?,
                   ultima_area=?, ultima_cena=?,
                   ultimo_progresso_em=CASE WHEN ? THEN ? ELSE ultimo_progresso_em END,
                   vida_maxima=?, dano_ferrao=?, geo_maximo=?,
                   maior_ociosidade=MAX(maior_ociosidade,?), estado_json=?
               WHERE campanha_id=?""",
            (
                agora, 1 if tipo != "estado" else 0, delta_tempo, inicio,
                inicio, agora, morte, dano,
                dano_total, inimigo, poder, banco, area or anterior["ultima_area"],
                evento.cena_id or anterior["ultima_cena"], 1 if progresso else 0,
                agora, vida_max, ferrao, geo, ocioso,
                json.dumps(estado, ensure_ascii=False, separators=(",", ":")),
                sessao.campanha_id,
            ),
        )
        if area:
            nova = con.execute(
                "SELECT 1 FROM areas WHERE campanha_id=? AND area=?",
                (sessao.campanha_id, area),
            ).fetchone() is None
            con.execute(
                """INSERT INTO areas(
                       campanha_id,area,primeira_vez,ultima_vez,visitas,mortes,danos,inimigos)
                   VALUES(?,?,?,?,1,?,?,?)
                   ON CONFLICT(campanha_id,area) DO UPDATE SET
                       ultima_vez=excluded.ultima_vez,
                       visitas=areas.visitas+CASE WHEN ? THEN 1 ELSE 0 END,
                       mortes=areas.mortes+excluded.mortes,
                       danos=areas.danos+excluded.danos,
                       inimigos=areas.inimigos+excluded.inimigos""",
                (
                    sessao.campanha_id, area, agora, agora, morte, dano, inimigo,
                    1 if tipo == "area_nova" and not nova else 0,
                ),
            )
            total = con.execute(
                "SELECT COUNT(*) FROM areas WHERE campanha_id=?", (sessao.campanha_id,)
            ).fetchone()[0]
            con.execute(
                "UPDATE campanhas SET areas=? WHERE campanha_id=?",
                (total, sessao.campanha_id),
            )

    def _detectar_progresso(self, con, campanha, evento, dados, anterior, area):
        motivos = []
        if evento.tipo in {
            "charm_adquirido", "boss_derrotado", "habilidade_adquirida",
            "magia_adquirida", "amuleto_adquirido", "estacao_desbloqueada",
            "item_importante_adquirido", "banco_descoberto",
        }:
            motivos.append(evento.tipo)
        if evento.tipo == "area_nova" and area:
            existe = con.execute(
                "SELECT 1 FROM areas WHERE campanha_id=? AND area=?",
                (campanha, area),
            ).fetchone()
            if not existe:
                motivos.append(f"nova área: {area}")
        vida = self._int(dados.get("vida_maxima"))
        if vida > self._int(anterior["vida_maxima"]) > 0:
            motivos.append("vida máxima aumentou")
        ferrao = self._int(dados.get("dano_ferrao"))
        if ferrao > self._int(anterior["dano_ferrao"]) > 0:
            motivos.append("ferrão ficou mais forte")
        habilidades_antes = self._json(
            self._json(anterior["estado_json"]).get("habilidades")
        )
        habilidades_agora = self._json(dados.get("habilidades"))
        novas = sorted(
            nome for nome, ativa in habilidades_agora.items()
            if bool(ativa) and not bool(habilidades_antes.get(nome))
        )
        if habilidades_antes and novas:
            motivos.extend(f"nova habilidade: {nome}" for nome in novas)
        return bool(motivos), motivos

    def _padroes_dano(self, con, sessao, evento, dados, agora, area):
        grave = self._int(dados.get("dano")) >= 2 or self._int(dados.get("vida_atual")) <= 3
        if not grave:
            # Um daninho isolado não é assunto. Só vale a pena falar quando o
            # impacto é grande ou quando ele está repetindo erro demais.
            return []
        recentes = self._contar(con, sessao.campanha_id, {"dano", "quase_morte"}, agora - 90)
        prioridade = 0
        if recentes >= 6:
            prioridade = 65
        elif recentes >= 4:
            prioridade = 32
        saida = []
        if prioridade:
            saida += self._observacao(
                con, sessao, evento, "danos_repetidos", prioridade,
                "Levou vários impactos em pouco tempo.",
                {"impactos_recentes": recentes, "area": area}, cooldown=150,
            )
        perigo = self._int(dados.get("perigo"))
        if bool(dados.get("origem_confirmada")) and perigo in PERIGOS:
            iguais = self._contar_perigo(
                con, sessao.campanha_id, perigo, agora - 240
            )
            prioridade = 70 if iguais >= 5 else 48 if iguais >= 3 else 0
            if prioridade:
                nome = PERIGOS.get(perigo, f"perigo {perigo}")
                saida += self._observacao(
                    con, sessao, evento, f"perigo_repetido_{perigo}", prioridade,
                    f"O mesmo perigo ambiental ({nome}) voltou a acertar ele agora há pouco.",
                    {"perigo": nome, "repeticoes": iguais, "area": area}, cooldown=300,
                )
        return saida

    def _padroes_morte(self, con, sessao, evento, agora, area):
        m10 = self._contar(con, sessao.campanha_id, {"morte"}, agora - 600)
        m30 = self._contar(con, sessao.campanha_id, {"morte"}, agora - 1800)
        prioridade = 78 if m30 >= 5 else 58 if m30 >= 3 else 34 if m10 >= 2 else 0
        if not prioridade:
            return []
        return self._observacao(
            con, sessao, evento, "mortes_repetidas", prioridade,
            f"A campanha acumulou muitas mortes na última meia hora.",
            {"mortes_10_min": m10, "mortes_30_min": m30, "area": area}, cooldown=300,
        )

    def _padroes_estado(self, con, sessao, evento, dados, agora, anterior):
        if (
            not bool(dados.get("em_gameplay", True))
            or bool(dados.get("no_banco"))
            or bool(dados.get("pausado"))
        ):
            return []
        saida = []
        parado = max(0.0, self._float(dados.get("parado_segundos")))
        for limite, prioridade in ((180, 66), (90, 34), (45, 12)):
            if parado >= limite:
                saida += self._observacao(
                    con, sessao, evento, f"ocioso_{limite}", prioridade,
                    "Ficou praticamente parado por bastante tempo.",
                    {"parado_segundos": round(parado, 1)}, cooldown=max(600, limite * 4),
                )
                break
        sem_progresso = agora - float(anterior["ultimo_progresso_em"])
        dificuldades = self._contar(
            con, sessao.campanha_id, {"dano", "quase_morte", "morte"}, agora - 900
        )
        prioridade = 0
        if sem_progresso >= 3600 and dificuldades >= 4:
            prioridade = 68
        elif sem_progresso >= 1800 and dificuldades >= 3:
            prioridade = 42
        elif sem_progresso >= 900 and dificuldades >= 3:
            prioridade = 15
        if prioridade:
            saida += self._observacao(
                con, sessao, evento, "dificuldade_sem_progresso", prioridade,
                "Há bastante tempo sem progresso evidente, com dificuldade recente.",
                {"sem_progresso_segundos": round(sem_progresso),
                 "incidentes_15_min": dificuldades}, cooldown=900,
            )
        return saida

    def _observacao(
        self, con, sessao, base, padrao, prioridade, resumo, evidencias, cooldown
    ) -> list[EventoJogo]:
        agora = self._relogio()
        linha = con.execute(
            "SELECT ultimo_em,nivel FROM padroes WHERE campanha_id=? AND padrao=?",
            (sessao.campanha_id, padrao),
        ).fetchone()
        if (
            linha
            and agora - float(linha["ultimo_em"]) < cooldown
            and prioridade <= int(linha["nivel"])
        ):
            return []
        con.execute(
            """INSERT INTO padroes(campanha_id,padrao,ultimo_em,nivel,ocorrencias)
               VALUES(?,?,?,?,1)
               ON CONFLICT(campanha_id,padrao) DO UPDATE SET
                   ultimo_em=excluded.ultimo_em,
                   nivel=MAX(padroes.nivel,excluded.nivel),
                   ocorrencias=padroes.ocorrencias+1""",
            (sessao.campanha_id, padrao, agora, prioridade),
        )
        dados = {
            "padrao": padrao,
            "prioridade": prioridade,
            "resumo": resumo,
            "evidencias": evidencias,
        }
        evento = EventoJogo(
            id=f"mem-{padrao}-{int(agora * 1000)}",
            sessao_id=sessao.id,
            cena_id=base.cena_id,
            tipo="observacao",
            dados=dados,
            criado_em=agora,
        )
        self._inserir_evento(
            con, f"{sessao.campanha_id}:{evento.id}", sessao.campanha_id, agora,
            "observacao", evento.cena_id, dados, resumo, prioridade, 1,
        )
        return [evento]

    def contexto(self, campanha_id: str, evento=None, modo: str = "normal") -> dict:
        limite = {"muda": 5, "quieta": 8, "normal": 12, "tagarela": 18}.get(modo, 12)
        with self._lock, self._conectar() as con:
            campanha = con.execute(
                "SELECT * FROM campanhas WHERE campanha_id=?", (campanha_id,)
            ).fetchone()
            if not campanha:
                return {
                    "perfil_jogador": perfil_minimo(),
                    "campanha": {},
                    "recentes": [],
                    "historia": [],
                }
            recentes = con.execute(
                """SELECT ocorrido_em,tipo,resumo,importancia FROM eventos
                   WHERE campanha_id=? AND (tipo!='estado' OR importancia>0)
                     AND dados_json NOT LIKE '%\"automatico\":true%'
                   ORDER BY ocorrido_em DESC LIMIT ?""",
                (campanha_id, limite),
            ).fetchall()
            # Diário da história, independente do limite do modo: sem isso, uma
            # sessão cheia de combate empurra as conversas com NPC para fora dos
            # "recentes" e a Emily esquece o que descobriu do mundo.
            consulta_historia = (
                "SELECT ocorrido_em,tipo,resumo FROM eventos WHERE campanha_id=?"
                " AND tipo IN (" + ",".join("?" * len(TIPOS_HISTORIA)) + ")"
                " AND dados_json NOT LIKE '%\"automatico\":true%'"
                " ORDER BY ocorrido_em DESC LIMIT ?"
            )
            historia = con.execute(
                consulta_historia, (campanha_id, *TIPOS_HISTORIA, LIMITE_HISTORIA)
            ).fetchall()
            areas = con.execute(
                """SELECT area,mortes,danos,visitas FROM areas WHERE campanha_id=?
                   ORDER BY (mortes*4+danos) DESC, ultima_vez DESC LIMIT 4""",
                (campanha_id,),
            ).fetchall()
            agora = self._relogio()
            return {
                "perfil_jogador": perfil_minimo(),
                "campanha": {
                    "sessoes": campanha["sessoes"],
                    "tempo_acompanhado": self._duracao(campanha["tempo_jogo"]),
                    "areas_conhecidas": campanha["areas"],
                    "ultima_area": campanha["ultima_area"],
                    "mortes": campanha["mortes"],
                    "danos": campanha["danos"],
                    "inimigos_derrotados": campanha["inimigos"],
                    "poderes_da_emily": campanha["poderes"],
                    "maior_tempo_parado": self._duracao(campanha["maior_ociosidade"]),
                    "tempo_sem_progresso_evidente": self._duracao(
                        max(0, agora - campanha["ultimo_progresso_em"])
                    ),
                },
                "areas_com_mais_dificuldade": [dict(a) for a in areas if a["mortes"] or a["danos"]],
                "recentes": [
                    {
                        "ha": self._duracao(max(0, agora - r["ocorrido_em"])),
                        "tipo": r["tipo"], "resumo": r["resumo"],
                    }
                    for r in recentes
                ],
                "historia": [
                    {
                        "ha": self._duracao(max(0, agora - h["ocorrido_em"])),
                        "tipo": h["tipo"], "resumo": h["resumo"],
                    }
                    for h in historia
                ],
            }

    def resumo(self, campanha_id: str) -> dict:
        contexto = self.contexto(campanha_id, modo="quieta")
        return {"arquivo": str(self.arquivo), **contexto}

    def _deve_guardar_snapshot(self, con, campanha, agora, dados, anterior):
        ultimo = con.execute(
            "SELECT ocorrido_em,dados_json FROM eventos WHERE campanha_id=? AND tipo='estado' ORDER BY ocorrido_em DESC LIMIT 1",
            (campanha,),
        ).fetchone()
        if not ultimo or agora - float(ultimo["ocorrido_em"]) >= 30:
            return True
        antigo = self._json(ultimo["dados_json"])
        chaves = (
            "vida_maxima", "dano_ferrao", "zona", "no_banco",
            "habilidades", "progresso",
        )
        return any(antigo.get(k) != dados.get(k) for k in chaves)

    def _migrar_perigos_nao_confirmados(self, con) -> None:
        """Corrige rótulos da 0.4.3 sem apagar os impactos realmente ocorridos."""
        linhas = con.execute(
            "SELECT numero,tipo,dados_json FROM eventos "
            "WHERE tipo IN ('dano','quase_morte','observacao')"
        ).fetchall()
        for linha in linhas:
            dados = self._json(linha["dados_json"])
            if linha["tipo"] in {"dano", "quase_morte"}:
                if "perigo" not in dados or "origem_confirmada" in dados:
                    continue
                dados["hazard_tipo_bruto"] = self._int(dados.pop("perigo"))
                dados["origem_confirmada"] = False
                resumo = "Sofreu dano de origem não confirmada."
            elif str(dados.get("padrao") or "").startswith("perigo_repetido_"):
                dados["padrao"] = "impactos_origem_nao_confirmada"
                evidencias = self._json(dados.get("evidencias"))
                evidencias.pop("perigo", None)
                dados["evidencias"] = evidencias
                resumo = "Houve impactos repetidos cuja origem não foi confirmada."
                dados["resumo"] = resumo
            else:
                continue
            con.execute(
                "UPDATE eventos SET dados_json=?,resumo=? WHERE numero=?",
                (
                    json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                    resumo,
                    linha["numero"],
                ),
            )
        # O padrão antigo dependia exclusivamente do número bruto do hook.
        con.execute("DELETE FROM padroes WHERE padrao LIKE 'perigo_repetido_%'")

    def _migrar_poderes_automaticos(self, con) -> None:
        """Marca a telemetria ruidosa da 0.4.3 sem apagar seu histórico."""
        linhas = con.execute(
            "SELECT numero,dados_json FROM eventos WHERE tipo='poder_usado'"
        ).fetchall()
        for linha in linhas:
            dados = self._json(linha["dados_json"])
            if "automatico" in dados:
                continue
            if str(dados.get("poder") or "") not in {"faisca_teimosa", "eco_de_alma"}:
                continue
            dados["automatico"] = True
            con.execute(
                "UPDATE eventos SET dados_json=? WHERE numero=?",
                (
                    json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                    linha["numero"],
                ),
            )

    def _inserir_evento(
        self, con, chave, campanha, quando, tipo, cena, dados, resumo, importancia, derivado
    ) -> bool:
        cursor = con.execute(
            """INSERT OR IGNORE INTO eventos(
                   chave,campanha_id,ocorrido_em,tipo,cena_id,dados_json,
                   resumo,importancia,derivado)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                chave, campanha, quando, tipo, cena or "",
                json.dumps(dados, ensure_ascii=False, default=str, separators=(",", ":")),
                resumo[:500], int(importancia), int(bool(derivado)),
            ),
        )
        return cursor.rowcount > 0

    def _contar(self, con, campanha, tipos, desde):
        marcas = ",".join("?" for _ in tipos)
        return con.execute(
            f"SELECT COUNT(*) FROM eventos WHERE campanha_id=? AND tipo IN ({marcas}) AND ocorrido_em>=? AND derivado=0",
            (campanha, *sorted(tipos), desde),
        ).fetchone()[0]

    def _contar_perigo(self, con, campanha, perigo, desde):
        linhas = con.execute(
            """SELECT dados_json FROM eventos WHERE campanha_id=?
               AND tipo IN ('dano','quase_morte') AND ocorrido_em>=? AND derivado=0""",
            (campanha, desde),
        ).fetchall()
        return sum(self._int(self._json(r[0]).get("perigo")) == perigo for r in linhas)

    def _limitar_retencao(self, con, campanha):
        maximo = max(1000, int(os.getenv("EMILY_HK_MAX_EVENTOS", "12000")))
        con.execute(
            """DELETE FROM eventos WHERE campanha_id=? AND numero NOT IN (
                   SELECT numero FROM eventos WHERE campanha_id=?
                   ORDER BY ocorrido_em DESC LIMIT ?)
               AND ocorrido_em < ?""",
            (campanha, campanha, maximo, self._relogio() - 30 * 86400),
        )
        con.execute(
            "DELETE FROM eventos_processados WHERE campanha_id=? AND ocorrido_em<?",
            (campanha, self._relogio() - 2 * 86400),
        )
        con.execute(
            "DELETE FROM sessoes WHERE campanha_id=? AND ultimo_contato<?",
            (campanha, self._relogio() - 30 * 86400),
        )

    @staticmethod
    def _area(evento, dados, estado):
        if evento.tipo == "area_nova":
            return str(
                dados.get("cena") or dados.get("zona")
                or evento.cena_id.split(":", 1)[0]
            ).strip()[:120]
        return str(
            dados.get("zona") or dados.get("cena") or estado.get("zona")
            or estado.get("area") or evento.cena_id.split(":", 1)[0]
        ).strip()[:120]

    @staticmethod
    def _importancia(tipo, dados):
        base = {
            "morte": 90, "boss_derrotado": 95, "boss_iniciado": 85,
            "boss_encontrado": 88, "boss_luta": 76, "npc_dialogo": 72,
            "comentario_tagarela": 18,
            "quase_morte": 80, "charm_adquirido": 100, "area_nova": 65, "boas_vindas": 96,
            "magia_adquirida": 92, "amuleto_adquirido": 88,
            "estacao_desbloqueada": 86, "item_importante_adquirido": 90,
            "habilidade_adquirida": 82, "banco_descoberto": 72,
            "progresso_reconciliado": 30,
            "banco": 5, "banco_saida": 5, "dano": 6, "inimigo_morto": 8,
            "poder_usado": 15, "jogo_iniciado": 20, "estado": 0,
        }.get(tipo, 10)
        return max(base, MemoriaHollowKnight._int(dados.get("prioridade")))

    @staticmethod
    def _resumir(tipo, dados, area):
        if tipo == "area_nova": return f"Entrou em {area or 'uma nova área'}."
        if tipo == "morte": return f"Morreu em {area or 'Hallownest'}."
        if tipo in {"dano", "quase_morte"}:
            perigo = MemoriaHollowKnight._int(dados.get("perigo"))
            if bool(dados.get("origem_confirmada")) and perigo in PERIGOS:
                return f"Sofreu dano de {PERIGOS[perigo]} em {area or 'Hallownest'}."
            origem = str(dados.get("origem") or "").strip()[:70]
            if bool(dados.get("origem_confirmada")) and origem:
                tipo_origem = "criatura" if dados.get("origem_tipo") == "criatura" else "objeto"
                return f"Sofreu dano de {tipo_origem} observado ({origem}) em {area or 'Hallownest'}."
            return f"Sofreu dano de origem não confirmada em {area or 'Hallownest'}."
        if tipo == "inimigo_morto": return f"Derrotou {dados.get('inimigo') or 'um inimigo'} em {area}."
        if tipo == "npc_dialogo":
            nome = (
                dados.get("nome")
                if bool(dados.get("identidade_confirmada", bool(dados.get("nome"))))
                else "um personagem"
            ) or "um personagem"
            fala = str(dados.get("fala") or "").strip()[:260]
            return f"Conversou com {nome}: {fala}" if fala else f"Conversou com {nome}."
        nome_boss = (
            dados.get("nome")
            if bool(dados.get("identidade_confirmada", bool(dados.get("nome"))))
            else "um chefe"
        ) or "um chefe"
        if tipo == "boss_encontrado": return f"Encontrou {nome_boss} em {area or 'uma arena'} ainda sem resultado definido."
        if tipo == "boss_iniciado": return f"Começou uma luta contra {nome_boss} em {area or 'uma arena'}."
        if tipo == "boss_luta":
            rotulo = {
                "sequencia_sem_dano": "um bom tempo sem tomar dano",
                "pressao_constante": "pressão sem dar espaço",
                "recuperacao_apos_dano": "recuperação depois de levar um golpe",
            }.get(str(dados.get("padrao") or ""), "o ritmo da luta")
            return f"Durante a luta contra {nome_boss}, acompanhou {rotulo}."
        if tipo == "comentario_tagarela":
            return f"Momento de acompanhamento espontâneo em {dados.get('zona') or area or 'Hallownest'}, com progresso atual disponível."
        if tipo == "poder_usado": return f"Emily usou {dados.get('poder') or 'um poder'}."
        if tipo == "banco": return f"Descansou em um banco de {area}."
        if tipo == "banco_saida": return f"Saiu do banco e retomou a exploração em {area}."
        if tipo == "charm_adquirido": return "Encontrou e formou o Vínculo de Emily."
        if tipo == "amuleto_adquirido": return f"Adquiriu {dados.get('nome') or 'um novo amuleto'}."
        if tipo == "estacao_desbloqueada": return f"Desbloqueou a estação de {dados.get('nome') or area}."
        if tipo == "item_importante_adquirido": return f"Adquiriu {dados.get('nome') or 'um item importante'}."
        if tipo == "magia_adquirida": return f"Aprendeu {dados.get('nome') or 'uma nova magia'}."
        if tipo == "habilidade_adquirida": return f"Conquistou {dados.get('nome') or 'uma nova habilidade'}."
        if tipo == "boss_derrotado": return f"Derrotou {dados.get('nome') or 'um chefe'} em {area or 'Hallownest'}."
        if tipo == "banco_descoberto": return f"Descobriu {dados.get('nome') or 'um novo banco'} em {area or 'Hallownest'}."
        if tipo == "progresso_reconciliado": return "Estado atual de progresso reconhecido após atualização do rastreador."
        if tipo == "jogo_iniciado": return "A campanha foi carregada."
        if tipo == "boas_vindas": return "A Emily percebeu que o Vitor entrou no jogo e falou com ele."
        if tipo == "estado": return f"Continuou explorando {area}."
        return str(dados.get("resumo") or tipo.replace("_", " "))[:500]

    @staticmethod
    def _json(valor):
        if isinstance(valor, dict): return dict(valor)
        try:
            dado = json.loads(valor or "{}")
            return dado if isinstance(dado, dict) else {}
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def _int(valor):
        try: return int(valor or 0)
        except (TypeError, ValueError): return 0

    @staticmethod
    def _float(valor):
        try: return float(valor or 0)
        except (TypeError, ValueError): return 0.0

    @staticmethod
    def _duracao(segundos):
        segundos = max(0, int(float(segundos or 0)))
        if segundos >= 3600: return f"{segundos // 3600}h {(segundos % 3600) // 60}min"
        if segundos >= 60: return f"{segundos // 60}min {segundos % 60}s"
        return f"{segundos}s"
