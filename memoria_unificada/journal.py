"""Journal append-only de falas e ações da memória unificada."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

from .config import ConfigMemoria, carregar_config
from .modelos import POOLS_VALIDOS, PRIVACIDADES_VALIDAS, EventoMemoria


STATUS_LOTE_VALIDOS = frozenset({"pending", "processing", "completed", "failed"})


def normalizar_busca(texto: str) -> str:
    """Minúsculas, sem acento e com espaços colapsados, só para BUSCA.

    O texto original do evento permanece intocado no banco; esta versão derivada
    alimenta a coluna texto_busca. É o que faz "programação" casar com uma
    consulta "programacao" sem depender do LIKE do SQLite, que ignora caixa
    apenas para ASCII.
    """
    limpo = unicodedata.normalize("NFD", str(texto or ""))
    limpo = "".join(c for c in limpo if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", limpo).casefold().strip()



class ErroJournal(RuntimeError):
    """Falha operacional do journal local."""


@dataclass(frozen=True)
class LoteExtracao:
    id: str
    owner_user_id: str
    privacy_scope: str
    memory_pool: str
    status: str
    criado_em: float
    atualizado_em: float
    tentativas: int
    ultimo_erro: str
    eventos: Tuple[EventoMemoria, ...]
    fatos_gerados_ids: Tuple[str, ...] = ()


class JournalMemoria:
    """Persiste eventos imutáveis e checkpoints de extração separados."""

    def __init__(
        self,
        config: Optional[ConfigMemoria] = None,
        caminho: Optional[Path] = None,
    ):
        self.config = config or carregar_config()
        self.caminho = Path(caminho or (self.config.pasta_dados / "journal.sqlite3"))
        self._lock = threading.RLock()
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    @contextmanager
    def _conectar(self) -> Iterator[sqlite3.Connection]:
        conexao = sqlite3.connect(self.caminho, timeout=10.0)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        conexao.execute("PRAGMA busy_timeout = 10000")
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()

    def _inicializar(self) -> None:
        try:
            with self._conectar() as conexao:
                conexao.execute("PRAGMA journal_mode = WAL")
                conexao.executescript("""
                    CREATE TABLE IF NOT EXISTS eventos (
                        id TEXT PRIMARY KEY,
                        owner_user_id TEXT NOT NULL,
                        papel TEXT NOT NULL,
                        texto TEXT NOT NULL,
                        canal TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        conversa_id TEXT NOT NULL DEFAULT '',
                        external_id TEXT NOT NULL DEFAULT '',
                        privacy_scope TEXT NOT NULL,
                        memory_pool TEXT NOT NULL,
                        texto_busca TEXT NOT NULL DEFAULT '',
                        inserido_em REAL NOT NULL
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS ux_evento_externo
                    ON eventos(owner_user_id, canal, external_id)
                    WHERE external_id <> '';

                    CREATE INDEX IF NOT EXISTS ix_eventos_dono_tempo
                    ON eventos(owner_user_id, timestamp DESC);

                    CREATE TABLE IF NOT EXISTS lotes_extracao (
                        id TEXT PRIMARY KEY,
                        owner_user_id TEXT NOT NULL,
                        privacy_scope TEXT NOT NULL,
                        memory_pool TEXT NOT NULL,
                        status TEXT NOT NULL,
                        criado_em REAL NOT NULL,
                        atualizado_em REAL NOT NULL,
                        tentativas INTEGER NOT NULL DEFAULT 0,
                        ultimo_erro TEXT NOT NULL DEFAULT '',
                        fatos_gerados_ids TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS ix_lotes_status
                    ON lotes_extracao(status, criado_em);

                    CREATE TABLE IF NOT EXISTS lote_eventos (
                        lote_id TEXT NOT NULL REFERENCES lotes_extracao(id),
                        evento_id TEXT NOT NULL REFERENCES eventos(id),
                        ordem INTEGER NOT NULL,
                        PRIMARY KEY(lote_id, evento_id),
                        UNIQUE(evento_id)
                    );
                """)
                # Migração idempotente: bancos criados antes da coluna derivada
                # de busca ganham ela preenchida; quem já tem, não paga nada.
                colunas = {linha["name"] for linha in conexao.execute(
                    "PRAGMA table_info(eventos)").fetchall()}
                if "texto_busca" not in colunas:
                    conexao.execute(
                        "ALTER TABLE eventos ADD COLUMN texto_busca "
                        "TEXT NOT NULL DEFAULT ''")
                pendentes = conexao.execute(
                    "SELECT id, texto FROM eventos WHERE texto_busca = ''"
                ).fetchall()
                if pendentes:
                    conexao.executemany(
                        "UPDATE eventos SET texto_busca = ? WHERE id = ?",
                        [(normalizar_busca(linha["texto"]), linha["id"])
                         for linha in pendentes],
                    )
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui inicializar {self.caminho}: {erro}") from erro

    @staticmethod
    def _dono(owner_user_id: str) -> str:
        dono = str(owner_user_id or "").strip()
        if not dono:
            raise ValueError("owner_user_id é obrigatório no journal")
        return dono

    @staticmethod
    def _valores(
        valores: Sequence[str], validos: frozenset, campo: str
    ) -> Tuple[str, ...]:
        saida = tuple(dict.fromkeys(str(v or "").strip() for v in valores))
        if not saida or any(v not in validos for v in saida):
            raise ValueError(f"{campo} inválido: {saida}")
        return saida

    @staticmethod
    def _evento_da_linha(linha: sqlite3.Row) -> EventoMemoria:
        return EventoMemoria(
            id=linha["id"],
            owner_user_id=linha["owner_user_id"],
            papel=linha["papel"],
            texto=linha["texto"],
            canal=linha["canal"],
            timestamp=float(linha["timestamp"]),
            conversa_id=linha["conversa_id"],
            external_id=linha["external_id"],
            privacy_scope=linha["privacy_scope"],
            memory_pool=linha["memory_pool"],
        )

    @staticmethod
    def _identidade_evento(evento: EventoMemoria) -> tuple:
        """Campos imutáveis; timestamp pode variar num retry do mesmo ID externo."""

        return (
            evento.owner_user_id, evento.papel, evento.texto, evento.canal,
            evento.conversa_id, evento.external_id, evento.privacy_scope,
            evento.memory_pool,
        )

    def adicionar(self, evento: EventoMemoria) -> Tuple[EventoMemoria, bool]:
        """Acrescenta sem alterar conteúdo existente; retorna (evento, criou)."""

        try:
            with self._lock, self._conectar() as conexao:
                existente_id = conexao.execute(
                    "SELECT * FROM eventos WHERE id = ?", (evento.id,)
                ).fetchone()
                if existente_id is not None:
                    existente = self._evento_da_linha(existente_id)
                    if self._identidade_evento(existente) != self._identidade_evento(evento):
                        raise ValueError(
                            f"o id de evento '{evento.id}' já existe com outro conteúdo"
                        )
                    return existente, False

                if evento.external_id:
                    externo = conexao.execute(
                        """SELECT * FROM eventos
                           WHERE owner_user_id = ? AND canal = ? AND external_id = ?""",
                        (evento.owner_user_id, evento.canal, evento.external_id),
                    ).fetchone()
                    if externo is not None:
                        existente = self._evento_da_linha(externo)
                        if self._identidade_evento(existente) != self._identidade_evento(evento):
                            raise ValueError(
                                f"external_id '{evento.external_id}' já existe "
                                "com outro conteúdo"
                            )
                        return existente, False

                conexao.execute(
                    """INSERT INTO eventos(
                           id, owner_user_id, papel, texto, canal, timestamp,
                           conversa_id, external_id, privacy_scope, memory_pool,
                           texto_busca, inserido_em
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        evento.id, evento.owner_user_id, evento.papel, evento.texto,
                        evento.canal, float(evento.timestamp), evento.conversa_id,
                        evento.external_id, evento.privacy_scope, evento.memory_pool,
                        normalizar_busca(evento.texto), time.time(),
                    ),
                )
                return evento, True
        except ValueError:
            raise
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui acrescentar evento: {erro}") from erro

    def adicionar_varios(
        self, eventos: Iterable[EventoMemoria]
    ) -> List[Tuple[EventoMemoria, bool]]:
        # Mantém a semântica de adicionar() e a ordem. Cada evento confirma sua
        # própria transação: um duplicado ruim não desfaz falas anteriores.
        return [self.adicionar(evento) for evento in eventos]

    def listar_recentes(
        self,
        owner_user_id: str,
        limite: int = 30,
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
        desde: Optional[float] = None,
    ) -> List[EventoMemoria]:
        dono = self._dono(owner_user_id)
        privacidades = self._valores(
            privacy_scopes, PRIVACIDADES_VALIDAS, "privacy_scope")
        grupos = self._valores(pools, POOLS_VALIDOS, "memory_pool")
        filtros = ["owner_user_id = ?"]
        params: List[object] = [dono]
        filtros.append(f"privacy_scope IN ({','.join('?' for _ in privacidades)})")
        params.extend(privacidades)
        filtros.append(f"memory_pool IN ({','.join('?' for _ in grupos)})")
        params.extend(grupos)
        if desde is not None:
            filtros.append("timestamp >= ?")
            params.append(float(desde))
        params.append(max(1, int(limite)))
        sql = (
            "SELECT * FROM eventos WHERE " + " AND ".join(filtros)
            + " ORDER BY timestamp DESC, rowid DESC LIMIT ?"
        )
        try:
            with self._conectar() as conexao:
                linhas = conexao.execute(sql, params).fetchall()
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui listar eventos: {erro}") from erro
        # API devolve cronológico para entrar diretamente em prompt/lote.
        return [self._evento_da_linha(linha) for linha in reversed(linhas)]

    def buscar_texto(
        self,
        owner_user_id: str,
        termos: Sequence[str],
        limite: int = 30,
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
        desde: Optional[float] = None,
        ate: Optional[float] = None,
    ) -> List[Tuple[EventoMemoria, float]]:
        """Eventos que casam com os termos (na versão normalizada de busca).

        Devolve (evento, fração_de_termos_casados) para o chamador pontuar.
        Casamento é OR entre termos: quem casa com mais termos sobe no rerank
        local, e a consulta não morre porque um termo era ruído.
        """

        dono = self._dono(owner_user_id)
        termos_limpos = []
        for termo in termos:
            normalizado = normalizar_busca(termo)
            if len(normalizado) >= 3 and normalizado not in termos_limpos:
                termos_limpos.append(normalizado)
        if not termos_limpos:
            return []
        privacidades = self._valores(
            privacy_scopes, PRIVACIDADES_VALIDAS, "privacy_scope")
        grupos = self._valores(pools, POOLS_VALIDOS, "memory_pool")
        filtros = ["owner_user_id = ?"]
        params: List[object] = [dono]
        filtros.append(f"privacy_scope IN ({','.join('?' for _ in privacidades)})")
        params.extend(privacidades)
        filtros.append(f"memory_pool IN ({','.join('?' for _ in grupos)})")
        params.extend(grupos)
        if desde is not None:
            filtros.append("timestamp >= ?")
            params.append(float(desde))
        if ate is not None:
            filtros.append("timestamp <= ?")
            params.append(float(ate))
        filtros.append(
            "(" + " OR ".join("texto_busca LIKE ?" for _ in termos_limpos) + ")")
        params.extend(f"%{termo}%" for termo in termos_limpos)
        params.append(max(1, int(limite)) * 4)  # margem pro rerank local
        sql = (
            "SELECT * FROM eventos WHERE " + " AND ".join(filtros)
            + " ORDER BY timestamp DESC LIMIT ?"
        )
        try:
            with self._conectar() as conexao:
                linhas = conexao.execute(sql, params).fetchall()
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui buscar por texto: {erro}") from erro
        total = len(termos_limpos)
        achados = []
        for linha in linhas:
            texto_busca = linha["texto_busca"] or normalizar_busca(linha["texto"])
            casados = sum(1 for termo in termos_limpos if termo in texto_busca)
            if casados:
                achados.append((self._evento_da_linha(linha), casados / total))
        achados.sort(key=lambda par: (-par[1], -par[0].timestamp, par[0].id))
        return achados[:max(1, int(limite))]

    def contar_nao_processados(
        self,
        owner_user_id: str,
        privacy_scope: str,
        memory_pool: str,
    ) -> int:
        dono = self._dono(owner_user_id)
        self._valores((privacy_scope,), PRIVACIDADES_VALIDAS, "privacy_scope")
        self._valores((memory_pool,), POOLS_VALIDOS, "memory_pool")
        try:
            with self._conectar() as conexao:
                linha = conexao.execute(
                    """SELECT COUNT(*) AS total FROM eventos e
                       WHERE e.owner_user_id = ? AND e.privacy_scope = ?
                         AND e.memory_pool = ?
                         AND NOT EXISTS (
                             SELECT 1 FROM lote_eventos le WHERE le.evento_id = e.id
                         )""",
                    (dono, privacy_scope, memory_pool),
                ).fetchone()
                return int(linha["total"])
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui contar eventos: {erro}") from erro

    def contar_eventos(self, owner_user_id: str) -> int:
        """Total de eventos do dono, de todos os escopos e pools."""
        dono = self._dono(owner_user_id)
        try:
            with self._conectar() as conexao:
                linha = conexao.execute(
                    "SELECT COUNT(*) AS total FROM eventos WHERE owner_user_id = ?",
                    (dono,),
                ).fetchone()
                return int(linha["total"])
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui contar eventos: {erro}") from erro

    def contar_lotes_recuperaveis(self, owner_user_id: str = "") -> int:
        """Pendentes/falhos, opcionalmente limitados ao dono, sem carregar eventos."""

        filtros = "WHERE status IN ('pending', 'failed')"
        params: Tuple[object, ...] = ()
        if str(owner_user_id or "").strip():
            filtros += " AND owner_user_id = ?"
            params = (self._dono(owner_user_id),)
        try:
            with self._conectar() as conexao:
                linha = conexao.execute(
                    f"SELECT COUNT(*) AS total FROM lotes_extracao {filtros}",
                    params,
                ).fetchone()
                return int(linha["total"])
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui contar lotes: {erro}") from erro

    def criar_lote(
        self,
        owner_user_id: str,
        privacy_scope: str,
        memory_pool: str,
        max_eventos: int,
        max_chars: int,
        minimo_eventos: int = 1,
    ) -> Optional[LoteExtracao]:
        """Reserva eventos ainda sem lote numa transação indivisível."""

        dono = self._dono(owner_user_id)
        self._valores((privacy_scope,), PRIVACIDADES_VALIDAS, "privacy_scope")
        self._valores((memory_pool,), POOLS_VALIDOS, "memory_pool")
        max_eventos = max(1, int(max_eventos))
        max_chars = max(1, int(max_chars))
        minimo_eventos = max(1, int(minimo_eventos))

        try:
            with self._lock, self._conectar() as conexao:
                conexao.execute("BEGIN IMMEDIATE")
                linhas = conexao.execute(
                    """SELECT e.* FROM eventos e
                       WHERE e.owner_user_id = ? AND e.privacy_scope = ?
                         AND e.memory_pool = ?
                         AND NOT EXISTS (
                             SELECT 1 FROM lote_eventos le WHERE le.evento_id = e.id
                         )
                       ORDER BY e.timestamp, e.rowid
                       LIMIT ?""",
                    (dono, privacy_scope, memory_pool, max_eventos),
                ).fetchall()

                escolhidas = []
                chars = 0
                for linha in linhas:
                    tamanho = len(linha["texto"])
                    if escolhidas and chars + tamanho > max_chars:
                        break
                    escolhidas.append(linha)
                    chars += tamanho
                if len(escolhidas) < minimo_eventos:
                    conexao.rollback()
                    return None

                agora = time.time()
                lote_id = uuid.uuid4().hex
                conexao.execute(
                    """INSERT INTO lotes_extracao(
                           id, owner_user_id, privacy_scope, memory_pool, status,
                           criado_em, atualizado_em
                       ) VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
                    (lote_id, dono, privacy_scope, memory_pool, agora, agora),
                )
                conexao.executemany(
                    "INSERT INTO lote_eventos(lote_id, evento_id, ordem) VALUES (?, ?, ?)",
                    [(lote_id, linha["id"], ordem)
                     for ordem, linha in enumerate(escolhidas)],
                )
                conexao.commit()
            return self.obter_lote(lote_id)
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui criar lote: {erro}") from erro

    def obter_lote(self, lote_id: str) -> Optional[LoteExtracao]:
        identificador = str(lote_id or "").strip()
        if not identificador:
            raise ValueError("lote_id é obrigatório")
        try:
            with self._conectar() as conexao:
                lote = conexao.execute(
                    "SELECT * FROM lotes_extracao WHERE id = ?", (identificador,)
                ).fetchone()
                if lote is None:
                    return None
                linhas = conexao.execute(
                    """SELECT e.* FROM eventos e
                       JOIN lote_eventos le ON le.evento_id = e.id
                       WHERE le.lote_id = ? ORDER BY le.ordem""",
                    (identificador,),
                ).fetchall()
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui obter lote: {erro}") from erro
        ids = tuple(filter(None, str(lote["fatos_gerados_ids"] or "").split(",")))
        return LoteExtracao(
            id=lote["id"], owner_user_id=lote["owner_user_id"],
            privacy_scope=lote["privacy_scope"], memory_pool=lote["memory_pool"],
            status=lote["status"], criado_em=float(lote["criado_em"]),
            atualizado_em=float(lote["atualizado_em"]),
            tentativas=int(lote["tentativas"]), ultimo_erro=lote["ultimo_erro"],
            eventos=tuple(self._evento_da_linha(linha) for linha in linhas),
            fatos_gerados_ids=ids,
        )

    def listar_lotes_recuperaveis(self, limite: int = 100) -> List[LoteExtracao]:
        """Pendentes e falhos sobrevivem ao restart e podem voltar à fila."""

        try:
            with self._conectar() as conexao:
                ids = [linha["id"] for linha in conexao.execute(
                    """SELECT id FROM lotes_extracao
                       WHERE status IN ('pending', 'failed')
                       ORDER BY criado_em LIMIT ?""",
                    (max(1, int(limite)),),
                ).fetchall()]
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui listar lotes: {erro}") from erro
        return [lote for lote in (self.obter_lote(i) for i in ids) if lote]

    def marcar_processando(self, lote_id: str, max_tentativas: int) -> bool:
        agora = time.time()
        try:
            with self._lock, self._conectar() as conexao:
                cursor = conexao.execute(
                    """UPDATE lotes_extracao
                       SET status = 'processing', tentativas = tentativas + 1,
                           atualizado_em = ?, ultimo_erro = ''
                       WHERE id = ? AND status IN ('pending', 'failed')
                         AND tentativas < ?""",
                    (agora, lote_id, max(1, int(max_tentativas))),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui reservar lote: {erro}") from erro

    def marcar_concluido(self, lote_id: str, fatos_ids: Iterable[str]) -> None:
        ids = tuple(dict.fromkeys(str(i or "").strip() for i in fatos_ids if str(i or "").strip()))
        self._marcar(lote_id, "completed", "", ",".join(ids))

    def marcar_falha(self, lote_id: str, erro: str) -> None:
        self._marcar(lote_id, "failed", str(erro or "")[:1000], None)

    def _marcar(
        self, lote_id: str, status: str, erro: str, fatos_ids: Optional[str]
    ) -> None:
        if status not in STATUS_LOTE_VALIDOS:
            raise ValueError(f"status de lote inválido: {status}")
        sets = "status = ?, atualizado_em = ?, ultimo_erro = ?"
        params: List[object] = [status, time.time(), erro]
        if fatos_ids is not None:
            sets += ", fatos_gerados_ids = ?"
            params.append(fatos_ids)
        params.extend([lote_id, "processing"])
        try:
            with self._lock, self._conectar() as conexao:
                cursor = conexao.execute(
                    f"UPDATE lotes_extracao SET {sets} WHERE id = ? AND status = ?",
                    params,
                )
                if cursor.rowcount != 1:
                    raise ValueError(
                        f"lote '{lote_id}' não está em processamento"
                    )
        except ValueError:
            raise
        except sqlite3.Error as sql_erro:
            raise ErroJournal(f"não consegui finalizar lote: {sql_erro}") from sql_erro

    def recuperar_interrompidos(self) -> int:
        """No boot, processing significa que o processo morreu no meio."""

        try:
            with self._lock, self._conectar() as conexao:
                cursor = conexao.execute(
                    """UPDATE lotes_extracao
                       SET status = 'failed', atualizado_em = ?,
                           ultimo_erro = 'processo interrompido durante extração'
                       WHERE status = 'processing'""",
                    (time.time(),),
                )
                return cursor.rowcount
        except sqlite3.Error as erro:
            raise ErroJournal(f"não consegui recuperar lotes: {erro}") from erro