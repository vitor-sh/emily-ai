"""Infraestrutura da memória unificada e persistente da Emily.

Este pacote é deliberadamente inerte durante o import: não abre banco, não
baixa modelo e não acessa a rede. A integração com os canais será feita em uma
fase posterior por meio de um serviço explícito.
"""

from .config import ConfigMemoria, carregar_config
from .embeddings import (
    ErroEmbeddings,
    ProvedorEmbeddings,
    ProvedorOllama,
    ProvedorSentenceTransformers,
    criar_provedor_embeddings,
)
from .modelos import (
    EVIDENCIAS_VALIDAS,
    POOLS_VALIDOS,
    PRIVACIDADES_VALIDAS,
    STATUS_VALIDOS,
    EventoMemoria,
    FatoMemoria,
    MemoriaEncontrada,
)
from .recuperacao import (
    ContextoMemoria,
    FatoPontuado,
    Lembrete,
    RecuperadorMemoria,
)
from .armazenamento import (
    ArmazenamentoMemoria,
    ErroArmazenamentoMemoria,
    ErroEsquemaMemoria,
)
from .extracao import ErroExtracao, ExtratorMemoria, ROTA_MEMORIA_EXTRACAO
from .journal import ErroJournal, JournalMemoria, LoteExtracao
from .servico import ResultadoRegistro, ServicoMemoria
from .worker import ProcessadorLote, WorkerExtracao, criar_worker_padrao
from .integracao import (
    PonteMemoria,
    dono_id,
    id_discord,
    ponte,
    ponte_ativa,
    ponte_completa,
)
from .migracao import MigradorMemoria

__all__ = [
    "ArmazenamentoMemoria",
    "ConfigMemoria",
    "ContextoMemoria",
    "EVIDENCIAS_VALIDAS",
    "ErroArmazenamentoMemoria",
    "ErroEmbeddings",
    "ErroEsquemaMemoria",
    "ErroExtracao",
    "ErroJournal",
    "EventoMemoria",
    "FatoMemoria",
    "FatoPontuado",
    "ExtratorMemoria",
    "JournalMemoria",
    "Lembrete",
    "LoteExtracao",
    "PonteMemoria",
    "MemoriaEncontrada",
    "MigradorMemoria",
    "POOLS_VALIDOS",
    "PRIVACIDADES_VALIDAS",
    "ProvedorEmbeddings",
    "ProvedorOllama",
    "ProvedorSentenceTransformers",
    "ProcessadorLote",
    "ROTA_MEMORIA_EXTRACAO",
    "ResultadoRegistro",
    "RecuperadorMemoria",
    "ServicoMemoria",
    "dono_id",
    "id_discord",
    "ponte",
    "ponte_ativa",
    "ponte_completa",
    "STATUS_VALIDOS",
    "WorkerExtracao",
    "carregar_config",
    "criar_provedor_embeddings",
    "criar_worker_padrao",
]