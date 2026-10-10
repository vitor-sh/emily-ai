"""Armazenamento persistente de fatos consolidados no ChromaDB."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .config import ConfigMemoria, carregar_config
from .embeddings import ProvedorEmbeddings, criar_provedor_embeddings
from .modelos import (
    POOLS_VALIDOS,
    PRIVACIDADES_VALIDAS,
    STATUS_VALIDOS,
    FatoMemoria,
    MemoriaEncontrada,
)


VERSAO_ESQUEMA = 1


class ErroArmazenamentoMemoria(RuntimeError):
    """Falha operacional da camada persistente."""


class ErroEsquemaMemoria(ErroArmazenamentoMemoria):
    """Coleção foi criada por esquema ou modelo de embedding incompatível."""


def _textos_unicos(valores: Iterable[str], validos: frozenset, campo: str) -> List[str]:
    saida = []
    for valor in valores:
        limpo = str(valor or "").strip()
        if limpo not in validos:
            raise ValueError(f"{campo} inválido: {limpo}")
        if limpo not in saida:
            saida.append(limpo)
    if not saida:
        raise ValueError(f"ao menos um {campo} é obrigatório")
    return saida


class ArmazenamentoMemoria:
    """Fachada segura da coleção de fatos.

    A construção é explícita e toda operação de leitura/mutação recebe o dono.
    Isso impede que uma consulta sem filtro exponha DMs ou memórias de terceiros.
    """

    def __init__(
        self,
        config: Optional[ConfigMemoria] = None,
        provedor_embeddings: Optional[ProvedorEmbeddings] = None,
        cliente=None,
    ):
        self.config = config or carregar_config()
        self.provedor_embeddings = (
            provedor_embeddings or criar_provedor_embeddings(self.config)
        )
        self._lock = threading.RLock()

        try:
            if cliente is None:
                import chromadb

                self.config.pasta_chroma.mkdir(parents=True, exist_ok=True)
                cliente = chromadb.PersistentClient(path=str(self.config.pasta_chroma))
            self._cliente = cliente
            self._colecao = cliente.get_or_create_collection(
                name=self.config.nome_colecao,
                embedding_function=None,
                metadata={
                    "hnsw:space": "cosine",
                    "schema_version": VERSAO_ESQUEMA,
                    "embedding_id": self.provedor_embeddings.identificador,
                },
            )
            self._validar_colecao()
        except ErroEsquemaMemoria:
            raise
        except ImportError as erro:
            modulo = getattr(erro, "name", "") or "chromadb"
            raise ErroArmazenamentoMemoria(
                f"dependência vetorial ausente no runtime: {modulo}. "
                "Recompile a Emily com ChromaDB incluído"
            ) from erro
        except Exception as erro:  # noqa: BLE001 - fronteira do Chroma
            raise ErroArmazenamentoMemoria(
                f"não consegui abrir o ChromaDB em {self.config.pasta_chroma}: {erro}"
            ) from erro

    @property
    def pasta(self) -> Path:
        return self.config.pasta_chroma

    def _validar_colecao(self) -> None:
        metadata = self._colecao.metadata or {}
        versao = int(metadata.get("schema_version", 0) or 0)
        if versao != VERSAO_ESQUEMA:
            raise ErroEsquemaMemoria(
                f"coleção usa schema {versao}; esta versão exige {VERSAO_ESQUEMA}"
            )
        gravado = str(metadata.get("embedding_id") or "")
        atual = self.provedor_embeddings.identificador
        if gravado != atual:
            raise ErroEsquemaMemoria(
                f"coleção usa embeddings '{gravado}', mas a configuração pediu "
                f"'{atual}'. Reindexe em outra coleção em vez de misturar vetores."
            )

    @staticmethod
    def _dono(owner_user_id: str) -> str:
        dono = str(owner_user_id or "").strip()
        if not dono:
            raise ValueError("owner_user_id é obrigatório em toda operação")
        return dono

    @staticmethod
    def _onde(
        owner_user_id: str,
        status: Optional[Sequence[str]] = ("active",),
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
    ) -> dict:
        dono = ArmazenamentoMemoria._dono(owner_user_id)
        clausulas = [{"owner_user_id": {"$eq": dono}}]
        if status is not None:
            estados = _textos_unicos(status, STATUS_VALIDOS, "status")
            clausulas.append({"status": {"$in": estados}})
        privacidades = _textos_unicos(
            privacy_scopes, PRIVACIDADES_VALIDAS, "privacy_scope")
        grupos = _textos_unicos(pools, POOLS_VALIDOS, "memory_pool")
        clausulas.append({"privacy_scope": {"$in": privacidades}})
        clausulas.append({"memory_pool": {"$in": grupos}})
        return {"$and": clausulas}

    def salvar(self, fato: FatoMemoria) -> FatoMemoria:
        embedding = self.provedor_embeddings.gerar([fato.texto])[0]
        try:
            with self._lock:
                # IDs são globais dentro da coleção. Um ID determinístico de
                # migração não pode sobrescrever por acidente a memória de
                # outra pessoa, mesmo que o chamador tenha montado o fato.
                existente = self._colecao.get(
                    ids=[fato.id], include=["metadatas"])
                if existente["ids"]:
                    dono_existente = str(
                        (existente["metadatas"][0] or {}).get("owner_user_id") or ""
                    )
                    if dono_existente != fato.owner_user_id:
                        raise ValueError(
                            f"o id '{fato.id}' já pertence a outro usuário"
                        )
                self._colecao.upsert(
                    ids=[fato.id],
                    embeddings=[embedding],
                    documents=[fato.texto],
                    metadatas=[fato.para_metadata()],
                )
            return fato
        except ValueError:
            # Colisão de ID entre donos é violação do contrato de isolamento.
            raise
        except Exception as erro:  # noqa: BLE001 - fronteira do Chroma
            raise ErroArmazenamentoMemoria(f"não consegui salvar o fato: {erro}") from erro

    def obter(self, owner_user_id: str, fato_id: str) -> Optional[FatoMemoria]:
        dono = self._dono(owner_user_id)
        identificador = str(fato_id or "").strip()
        if not identificador:
            raise ValueError("fato_id é obrigatório")
        try:
            resultado = self._colecao.get(
                ids=[identificador],
                where={"owner_user_id": {"$eq": dono}},
                include=["documents", "metadatas"],
            )
        except Exception as erro:  # noqa: BLE001
            raise ErroArmazenamentoMemoria(f"não consegui obter o fato: {erro}") from erro
        if not resultado["ids"]:
            return None
        return FatoMemoria.de_registro(
            resultado["ids"][0],
            resultado["documents"][0],
            resultado["metadatas"][0] or {},
        )

    def buscar(
        self,
        owner_user_id: str,
        consulta: str,
        limite: int = 12,
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
    ) -> List[MemoriaEncontrada]:
        self._dono(owner_user_id)
        texto = str(consulta or "").strip()
        if not texto:
            return []
        limite = max(1, int(limite))
        if self._colecao.count() == 0:
            return []
        embedding = self.provedor_embeddings.gerar([texto])[0]
        try:
            resultado = self._colecao.query(
                query_embeddings=[embedding],
                n_results=min(limite, self._colecao.count()),
                where=self._onde(
                    owner_user_id,
                    status=("active",),
                    privacy_scopes=privacy_scopes,
                    pools=pools,
                ),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as erro:  # noqa: BLE001
            raise ErroArmazenamentoMemoria(f"não consegui buscar memórias: {erro}") from erro

        encontrados = []
        ids = (resultado.get("ids") or [[]])[0]
        documentos = (resultado.get("documents") or [[]])[0]
        metadatas = (resultado.get("metadatas") or [[]])[0]
        distancias = (resultado.get("distances") or [[]])[0]
        for fato_id, documento, metadata, distancia in zip(
            ids, documentos, metadatas, distancias
        ):
            distancia_float = float(distancia)
            encontrados.append(MemoriaEncontrada(
                fato=FatoMemoria.de_registro(
                    fato_id, str(documento or ""), metadata or {}),
                distancia=distancia_float,
                relevancia=max(0.0, min(1.0, 1.0 - distancia_float)),
            ))
        return encontrados

    def listar(
        self,
        owner_user_id: str,
        limite: int = 100,
        offset: int = 0,
        status: Optional[Sequence[str]] = ("active",),
        privacy_scopes: Sequence[str] = ("owner_private", "public"),
        pools: Sequence[str] = ("general", "code"),
    ) -> List[FatoMemoria]:
        # Validação é erro de contrato do chamador, não falha operacional do
        # Chroma. Deve continuar como ValueError e nunca ser mascarada.
        onde = self._onde(
            owner_user_id,
            status=status,
            privacy_scopes=privacy_scopes,
            pools=pools,
        )
        limite = max(1, int(limite))
        offset = max(0, int(offset))
        try:
            resultado = self._colecao.get(
                where=onde,
                limit=limite,
                offset=offset,
                include=["documents", "metadatas"],
            )
        except Exception as erro:  # noqa: BLE001
            raise ErroArmazenamentoMemoria(f"não consegui listar memórias: {erro}") from erro
        fatos = [
            FatoMemoria.de_registro(fato_id, str(documento or ""), metadata or {})
            for fato_id, documento, metadata in zip(
                resultado["ids"], resultado["documents"], resultado["metadatas"]
            )
        ]
        return sorted(fatos, key=lambda fato: fato.atualizado_em, reverse=True)

    def _mudar_estado(
        self,
        owner_user_id: str,
        fato_id: str,
        status: str,
        superseded_by: str = "",
    ) -> FatoMemoria:
        if status not in STATUS_VALIDOS:
            raise ValueError(f"status inválido: {status}")
        with self._lock:
            atual = self.obter(owner_user_id, fato_id)
            if atual is None:
                raise KeyError(f"fato não encontrado para esse usuário: {fato_id}")
            alterado = atual.com_estado(status, superseded_by)
            try:
                # update sem documento preserva o embedding existente.
                self._colecao.update(
                    ids=[alterado.id],
                    metadatas=[alterado.para_metadata()],
                )
            except Exception as erro:  # noqa: BLE001
                raise ErroArmazenamentoMemoria(
                    f"não consegui mudar o estado do fato: {erro}"
                ) from erro
            return alterado

    def esquecer(self, owner_user_id: str, fato_id: str) -> FatoMemoria:
        return self._mudar_estado(owner_user_id, fato_id, "forgotten")

    def superseder(
        self,
        owner_user_id: str,
        fato_antigo_id: str,
        fato_novo: FatoMemoria,
    ) -> FatoMemoria:
        dono = self._dono(owner_user_id)
        if fato_novo.owner_user_id != dono:
            raise ValueError("fato novo pertence a outro usuário")
        with self._lock:
            antigo = self.obter(dono, fato_antigo_id)
            if antigo is None:
                raise KeyError(f"fato antigo não encontrado: {fato_antigo_id}")
            self.salvar(fato_novo)
            self._mudar_estado(dono, antigo.id, "superseded", fato_novo.id)
        return fato_novo

    def contar(self, owner_user_id: str) -> int:
        """Conta somente fatos acessíveis ao dono, nunca a coleção inteira."""

        return len(self.listar(owner_user_id, limite=max(1, self._colecao.count()), status=None))