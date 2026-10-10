"""Adaptadores locais de embeddings, carregados somente quando usados."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from threading import Lock
from typing import List, Protocol, Sequence, runtime_checkable

from .config import ConfigMemoria


class ErroEmbeddings(RuntimeError):
    """O backend local não conseguiu produzir vetores utilizáveis."""


@runtime_checkable
class ProvedorEmbeddings(Protocol):
    @property
    def identificador(self) -> str:
        """Identidade estável persistida junto da coleção vetorial."""

    def gerar(self, textos: Sequence[str]) -> List[List[float]]:
        """Gera um vetor para cada texto, preservando a ordem."""


def validar_embeddings(
    embeddings: Sequence[Sequence[float]],
    quantidade_esperada: int,
) -> List[List[float]]:
    """Normaliza números e rejeita vetores vazios, divergentes ou inválidos."""

    if len(embeddings) != quantidade_esperada:
        raise ErroEmbeddings(
            f"backend devolveu {len(embeddings)} vetor(es) para "
            f"{quantidade_esperada} texto(s)"
        )
    saida: List[List[float]] = []
    dimensao = 0
    for indice, bruto in enumerate(embeddings):
        try:
            vetor = [float(valor) for valor in bruto]
        except (TypeError, ValueError) as erro:
            raise ErroEmbeddings(f"vetor {indice} contém valor não numérico") from erro
        if not vetor:
            raise ErroEmbeddings(f"vetor {indice} está vazio")
        if not all(math.isfinite(valor) for valor in vetor):
            raise ErroEmbeddings(f"vetor {indice} contém NaN ou infinito")
        if not any(valor != 0.0 for valor in vetor):
            raise ErroEmbeddings(f"vetor {indice} tem norma zero")
        if dimensao and len(vetor) != dimensao:
            raise ErroEmbeddings(
                f"dimensão divergente: vetor 0 tem {dimensao}, "
                f"vetor {indice} tem {len(vetor)}"
            )
        dimensao = len(vetor)
        saida.append(vetor)
    return saida


def _validar_textos(textos: Sequence[str]) -> List[str]:
    saida = [str(texto or "").strip() for texto in textos]
    if not saida:
        return []
    if any(not texto for texto in saida):
        raise ErroEmbeddings("não é possível gerar embedding de texto vazio")
    return saida


class ProvedorOllama:
    """Embeddings pelo Ollama local, via HTTP e sem dependência de SDK."""

    def __init__(self, modelo: str, base_url: str, timeout: float = 30.0,
                 token: str = ""):
        self.modelo = str(modelo or "").strip()
        self.base_url = str(base_url or "").rstrip("/")
        self.timeout = float(timeout)
        self.token = token
        if not self.modelo:
            raise ValueError("modelo Ollama não pode ser vazio")
        if not self.base_url:
            raise ValueError("URL do Ollama não pode ser vazia")
        if self.timeout <= 0:
            raise ValueError("timeout deve ser positivo")

    @property
    def identificador(self) -> str:
        return f"ollama:{self.modelo}"

    def gerar(self, textos: Sequence[str]) -> List[List[float]]:
        entradas = _validar_textos(textos)
        if not entradas:
            return []
        corpo = json.dumps({
            "model": self.modelo,
            "input": entradas,
            "truncate": True,
            # Pede pro Ollama MANTER o modelo carregado. Sem isto o Ollama
            # descarrega depois de 5 minutos de inatividade — e a PRÓXIMA
            # consulta de memória paga o cold-load de novo (medido: 10,4s na
            # primeira busca após a pausa, contra 0,1–0,4s aquecido). O TTFT
            # do turno inteiro pagava esse cold-load: logs reais mostram
            # prompt_memoria=8604ms e 9366ms em turnos isolados.
            "keep_alive": "30m",
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.base_url.endswith("/ollama") and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        requisicao = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=corpo,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                payload = json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", errors="replace")[:300]
            raise ErroEmbeddings(
                f"Ollama respondeu HTTP {erro.code}: {detalhe}"
            ) from erro
        except (urllib.error.URLError, TimeoutError, OSError) as erro:
            raise ErroEmbeddings(f"Ollama local indisponível: {erro}") from erro
        except json.JSONDecodeError as erro:
            raise ErroEmbeddings("Ollama devolveu JSON inválido") from erro

        return validar_embeddings(payload.get("embeddings") or [], len(entradas))


class ProvedorSentenceTransformers:
    """Backend opcional em CPU; o modelo só é carregado no primeiro uso."""

    def __init__(self, modelo: str):
        self.modelo = str(modelo or "").strip()
        if not self.modelo:
            raise ValueError("modelo sentence-transformers não pode ser vazio")
        self._instancia = None
        self._lock = Lock()

    @property
    def identificador(self) -> str:
        return f"sentence-transformers:{self.modelo}"

    def _carregar(self):
        if self._instancia is not None:
            return self._instancia
        with self._lock:
            if self._instancia is not None:
                return self._instancia
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as erro:
                raise ErroEmbeddings(
                    "backend sentence-transformers selecionado, mas o pacote "
                    "não está instalado"
                ) from erro
            try:
                self._instancia = SentenceTransformer(self.modelo, device="cpu")
            except Exception as erro:  # noqa: BLE001 - traduz erro do backend
                raise ErroEmbeddings(
                    f"não consegui carregar o modelo '{self.modelo}': {erro}"
                ) from erro
        return self._instancia

    def gerar(self, textos: Sequence[str]) -> List[List[float]]:
        entradas = _validar_textos(textos)
        if not entradas:
            return []
        try:
            vetores = self._carregar().encode(
                entradas,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            brutos = vetores.tolist()
        except ErroEmbeddings:
            raise
        except Exception as erro:  # noqa: BLE001 - traduz erro do backend
            raise ErroEmbeddings(f"falha gerando embeddings em CPU: {erro}") from erro
        return validar_embeddings(brutos, len(entradas))


def criar_provedor_embeddings(config: ConfigMemoria) -> ProvedorEmbeddings:
    if config.provedor_embeddings == "ollama":
        return ProvedorOllama(
            modelo=config.modelo_embeddings,
            base_url=config.ollama_url,
            timeout=config.timeout_embeddings,
            token=config.ollama_token,
        )
    if config.provedor_embeddings == "sentence-transformers":
        return ProvedorSentenceTransformers(config.modelo_embeddings)
    # ConfigMemoria já valida; fica defensivo para objetos construídos por fora.
    raise ValueError(f"provedor de embeddings inválido: {config.provedor_embeddings}")
