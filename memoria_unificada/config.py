"""Configuração sem efeitos colaterais da memória unificada."""

from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


def _candidatos_env() -> tuple[Path, ...]:
    """Locais estáveis do .env, independentes do diretório de execução.

    No código-fonte, ``config.py`` fica em ``<projeto>/memoria_unificada``. No
    pacote onedir, os módulos e recursos ficam em ``_internal`` e o usuário pode
    manter o .env tanto ali quanto ao lado do executável. Variáveis já exportadas
    continuam tendo precedência porque o carregamento nunca usa ``override``.
    """

    modulo = Path(__file__).resolve()
    candidatos = []
    if getattr(sys, "frozen", False):
        candidatos.append(Path(sys.executable).resolve().parent / ".env")
    candidatos.append(modulo.parent.parent / ".env")
    if getattr(sys, "frozen", False):
        candidatos.append(Path(getattr(
            sys, "_MEIPASS", modulo.parent.parent)) / ".env")
    # Mantém a ordem e elimina caminhos repetidos.
    return tuple(dict.fromkeys(candidatos))


def _valores_env() -> dict[str, str]:
    """Lê .env sem poluir ``os.environ`` de outros subsistemas."""

    valores: dict[str, str] = {}
    candidatos = (Path(os.environ["EMILY_CONFIG_FILE"]),) if os.getenv("EMILY_CONFIG_FILE") else _candidatos_env()
    for caminho in candidatos:
        if caminho.is_file():
            for nome, valor in dotenv_values(caminho).items():
                if valor is not None and nome not in valores:
                    valores[nome] = str(valor)
    return valores


def _env(nome: str, padrao: str, valores_arquivo: dict[str, str]) -> str:
    """Ambiente exportado vence arquivo; arquivo vence o padrão."""

    if nome in os.environ:
        return os.environ[nome]
    return valores_arquivo.get(nome, padrao)


def _env_bool(
    nome: str, padrao: bool = False, valores_arquivo: dict[str, str] | None = None,
) -> bool:
    valor = _env(nome, "", valores_arquivo or {}) if (
        nome in os.environ or nome in (valores_arquivo or {})) else None
    if valor is None:
        return padrao
    return valor.strip().lower() in {"1", "true", "sim", "yes", "on"}


def _pasta_dados_padrao() -> Path:
    if os.name == "nt":
        from emily_paths import pasta_dados
        return pasta_dados() / "memoria_unificada"
    base = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "emily" / "memoria_unificada"


@dataclass(frozen=True)
class ConfigMemoria:
    """Ajustes da infraestrutura; nenhum recurso é aberto ao instanciar."""

    habilitada: bool = False
    pasta_dados: Path = field(default_factory=_pasta_dados_padrao)
    nome_colecao: str = "emily_memoria_v1"
    provedor_embeddings: str = "ollama"
    modelo_embeddings: str = "embeddinggemma"
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_token: str = ""
    timeout_embeddings: float = 30.0
    eventos_por_extracao: int = 6
    max_eventos_por_lote: int = 20
    max_chars_por_lote: int = 12000
    tentativas_extracao: int = 3
    fila_maxima: int = 100
    # ── Recuperação (Fase 3) ─────────────────────────────────────────
    # score = w_rel*relevância + w_imp*(importância/10) + w_rec*recência,
    # com recência = 0.5 ** (idade_horas / meia_vida_horas).
    peso_relevancia: float = 0.60
    peso_importancia: float = 0.25
    peso_recencia: float = 0.15
    meia_vida_horas: float = 336.0          # 14 dias
    candidatos_semanticos: int = 40         # quantos o Chroma devolve antes do rerank
    orcamento_prompt: int = 1500            # teto de caracteres injetados
    max_por_topico: int = 2                 # diversidade: teto por tópico
    eventos_recentes: int = 8               # camada 1: últimas trocas sempre carregadas
    janela_recente_horas: float = 72.0      # camada 2: janela de busca textual
    min_score_fato: float = 0.20            # piso pra não poluir o contexto

    def __post_init__(self) -> None:
        pasta = Path(self.pasta_dados).expanduser()
        object.__setattr__(self, "pasta_dados", pasta)

        provedor = self.provedor_embeddings.strip().lower()
        if provedor not in {"ollama", "sentence-transformers"}:
            raise ValueError(
                "EMILY_MEMORIA_EMBEDDINGS deve ser 'ollama' ou "
                "'sentence-transformers'"
            )
        object.__setattr__(self, "provedor_embeddings", provedor)

        nome_colecao = self.nome_colecao.strip()
        if len(nome_colecao) < 3:
            raise ValueError("nome da coleção deve ter ao menos 3 caracteres")
        object.__setattr__(self, "nome_colecao", nome_colecao)

        if not self.modelo_embeddings.strip():
            raise ValueError("modelo de embeddings não pode ser vazio")
        if self.timeout_embeddings <= 0:
            raise ValueError("timeout de embeddings deve ser positivo")
        for nome in (
            "eventos_por_extracao", "max_eventos_por_lote", "max_chars_por_lote",
            "tentativas_extracao", "fila_maxima", "candidatos_semanticos",
            "orcamento_prompt", "max_por_topico", "eventos_recentes",
        ):
            if int(getattr(self, nome)) <= 0:
                raise ValueError(f"{nome} deve ser positivo")
        if self.meia_vida_horas <= 0:
            raise ValueError("meia_vida_horas deve ser positivo")
        if self.janela_recente_horas <= 0:
            raise ValueError("janela_recente_horas deve ser positivo")
        if not 0.0 <= self.min_score_fato <= 1.0:
            raise ValueError("min_score_fato deve estar entre 0 e 1")
        soma_pesos = self.peso_relevancia + self.peso_importancia + self.peso_recencia
        if soma_pesos <= 0:
            raise ValueError("a soma dos pesos de recuperação deve ser positiva")
        if abs(soma_pesos - 1.0) > 0.05:
            raise ValueError(
                "os pesos de recuperação devem somar ~1.0 "
                f"(soma atual: {soma_pesos:.2f})"
            )

    @property
    def pasta_chroma(self) -> Path:
        return self.pasta_dados / "chroma"

    @property
    def identificador_embeddings(self) -> str:
        return f"{self.provedor_embeddings}:{self.modelo_embeddings.strip()}"


def carregar_config() -> ConfigMemoria:
    """Lê .env + ambiente no momento da chamada, facilitando testes e rollback."""

    valores = _valores_env()
    padrao = _pasta_dados_padrao()
    ollama_padrao = "http://127.0.0.1:11434"
    if os.name == "nt" and "EMILY_OLLAMA_URL" not in os.environ and "EMILY_OLLAMA_URL" not in valores:
        try:
            raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
            manifesto = json.loads((raiz / "windows-release.json").read_text(encoding="utf-8"))
            gateway = str(manifesto.get("sync_url") or "").rstrip("/")
            if gateway.startswith("https://"):
                ollama_padrao = gateway + "/ollama"
        except (OSError, ValueError, TypeError):
            pass
    return ConfigMemoria(
        habilitada=_env_bool("EMILY_MEMORIA_UNIFICADA", False, valores),
        pasta_dados=Path(_env("EMILY_MEMORIA_PASTA", str(padrao), valores)),
        nome_colecao=_env("EMILY_MEMORIA_COLECAO", "emily_memoria_v1", valores).strip(),
        provedor_embeddings=_env("EMILY_MEMORIA_EMBEDDINGS", "ollama", valores),
        modelo_embeddings=_env("EMILY_MEMORIA_MODELO_EMBEDDINGS", "embeddinggemma", valores),
        ollama_url=_env("EMILY_OLLAMA_URL", ollama_padrao, valores).rstrip("/"),
        ollama_token=_env("EMILY_PONTE_TOKEN", "", valores),
        timeout_embeddings=float(_env("EMILY_MEMORIA_TIMEOUT_EMBEDDINGS", "30", valores)),
        eventos_por_extracao=int(_env("EMILY_MEMORIA_EVENTOS_POR_EXTRACAO", "6", valores)),
        max_eventos_por_lote=int(_env("EMILY_MEMORIA_MAX_EVENTOS_LOTE", "20", valores)),
        max_chars_por_lote=int(_env("EMILY_MEMORIA_MAX_CHARS_LOTE", "12000", valores)),
        tentativas_extracao=int(_env("EMILY_MEMORIA_TENTATIVAS_EXTRACAO", "3", valores)),
        fila_maxima=int(_env("EMILY_MEMORIA_FILA_MAXIMA", "100", valores)),
        peso_relevancia=float(_env("EMILY_MEMORIA_PESO_RELEVANCIA", "0.60", valores)),
        peso_importancia=float(_env("EMILY_MEMORIA_PESO_IMPORTANCIA", "0.25", valores)),
        peso_recencia=float(_env("EMILY_MEMORIA_PESO_RECENCIA", "0.15", valores)),
        meia_vida_horas=float(_env("EMILY_MEMORIA_MEIA_VIDA_HORAS", "336", valores)),
        candidatos_semanticos=int(_env("EMILY_MEMORIA_CANDIDATOS", "40", valores)),
        orcamento_prompt=int(_env("EMILY_MEMORIA_ORCAMENTO_PROMPT", "1500", valores)),
        max_por_topico=int(_env("EMILY_MEMORIA_MAX_POR_TOPICO", "2", valores)),
        eventos_recentes=int(_env("EMILY_MEMORIA_EVENTOS_RECENTES", "8", valores)),
        janela_recente_horas=float(_env("EMILY_MEMORIA_JANELA_RECENTE_HORAS", "72", valores)),
        min_score_fato=float(_env("EMILY_MEMORIA_MIN_SCORE_FATO", "0.20", valores)),
    )
