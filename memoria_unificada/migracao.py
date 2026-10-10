"""Migração das memórias antigas para a memória unificada (Fase 6).

Regras da fase (decisões da Fase 0, mantidas):
- Fatos JÁ CURADOS (memoria.json e os fatos manuais do perfil do Discord)
  entram DIRETO como FatoMemoria — nada é re-extraído, então nada se perde.
  O tópico vem de um classificador por palavras-chave só pra preencher o
  metadata; o texto original é preservado integralmente.
- Históricos (conversas web, Emily Code, DMs) viram EventoMemoria com IDs
  determinísticos e passam pela extração normal (flush_grupo). O pool "code"
  mantém a promoção seletiva dos 5 tópicos técnicos; DMs ficam no namespace
  discord:<id> (ou no dono, quando a DM é dele) e nunca vazam pro contexto
  de outra pessoa.
- As fontes são 100% READ-ONLY: este módulo só lê JSON, nunca importa os
  módulos legados (que gravam) e nunca reescreve as fontes.
- Idempotente: IDs derivados de sha256(fonte, chave, papel, texto). Rodar
  duas vezes não duplica nada — journal e Chroma deduplicam pelo ID.

Uso: python migrar_memoria.py --dry-run  (relatório) | --executar (grava).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .armazenamento import ArmazenamentoMemoria
from .config import ConfigMemoria, carregar_config
from .embeddings import ProvedorEmbeddings, criar_provedor_embeddings
from .extracao import ExtratorMemoria
from .integracao import dono_id
from .journal import JournalMemoria
from .modelos import EventoMemoria, FatoMemoria
from .servico import ServicoMemoria
from .worker import ProcessadorLote
from emily_paths import arquivo_dados

# Fontes legadas. Nenhuma é escrita por este módulo.
CAMINHO_MEMORIA = arquivo_dados("memoria.json")
CAMINHO_MEMORIA_DISCORD = arquivo_dados("memoria_discord.json")
CAMINHO_CONVERSAS = Path.home() / ".emily_conversas.json"
CAMINHO_CODE = Path.home() / ".emily_code_conversas.json"
CAMINHO_DMS = Path.home() / ".emily_dm_historico.json"
CAMINHO_CONFIG_DISCORD = Path.home() / ".emily_discord.json"

FONTES_VALIDAS = ("memoria", "conversas", "code", "discord", "dms")

# Classificador de tópicos por palavras-chave, na ordem de prioridade.
# É heurística de metadata: o texto nunca é alterado.
_MAPA_TOPICOS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("health", (
        "saúde", "saude", "doen", "remédio", "remedio", "médic", "clinic",
        "hospital", "ansiedade", "depress", "alergia", "insônia", "insonia",
        "reméd", "psic")),
    ("relationship", (
        "namorad", "irmã", "irma", "irmão", "irmao", "mãe", "famíl", "famil",
        "primo", "prima", "amig", "gata", "gato", "cachorr", "namoro", "esposa",
        "marido", "filh")),
    ("strong_preference", (
        "gosta", "prefere", "favorit", "odeia", "detesta", "curte",
        "apaixonad", "viciad", "adora", "não suport", "nao suport")),
    ("project_context", (
        "emily", "projeto", "python", "código", "codigo", "programa",
        "discord.py", "mysql", "api", "servidor")),
    ("decision", ("decidiu", "decisão", "decisao", "escolheu", "optou")),
)

_IMPORTANCIA_POR_TOPICO = {
    "health": 9,
    "relationship": 8,
    "strong_preference": 7,
    "project_context": 7,
    "decision": 6,
    "biography": 6,
}


def _classificar_topico(texto: str) -> str:
    t = str(texto).casefold()
    for topico, palavras in _MAPA_TOPICOS:
        if any(palavra in t for palavra in palavras):
            return topico
    return "biography"


def _id_fato_migrado(fonte: str, chave: str) -> str:
    base = f"migracao:fato:{fonte}:{chave}"
    return "mig_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:28]


def _id_evento_migrado(
    owner: str, fonte: str, chave_externa: str, papel: str, texto: str
) -> str:
    base = "\x1f".join(("migracao", owner, fonte, chave_externa, papel, texto))
    return "evt_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:28]


def _ler_json(caminho: Path):
    """Leitura tolerante e SEMPRE read-only."""
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError, ValueError) as erro:
        print(f"[MIGRACAO] não consegui ler {caminho}: {erro}")
        return None


def _id_dono_discord() -> str:
    """ID do Discord do Vitor, lido da config do bot (read-only)."""
    dados = _ler_json(CAMINHO_CONFIG_DISCORD)
    if isinstance(dados, dict):
        valor = str(dados.get("usuario_id") or "").strip()
        if valor.isdigit():
            return valor
    return ""


def _normalizar_papel(papel_legado: str) -> str:
    return "user" if str(papel_legado or "").strip() == "user" else "assistant"


# ═════════════════════════════════════════════════════════════════
# COLETORES: leem uma fonte legada e devolvem objetos do modelo novo.
# Nenhum grava em lugar nenhum.
# ═════════════════════════════════════════════════════════════════

def _coletar_fatos_memoria(
    dono: str, dados: Optional[dict]
) -> Tuple[List[FatoMemoria], dict]:
    """memoria.json: fatos já curados entram DIRETO como FatoMemoria."""
    fatos: List[FatoMemoria] = []
    if not isinstance(dados, dict):
        return fatos, {"fatos": 0}
    agora = time.time()
    for indice, texto in enumerate(dados.get("fatos") or ()):
        texto = str(texto or "").strip()
        if len(texto) < 4:
            continue
        topico = _classificar_topico(texto)
        fatos.append(FatoMemoria(
            id=_id_fato_migrado("memoria", f"{indice}:{texto}"),
            owner_user_id=dono,
            texto=texto,
            importancia=_IMPORTANCIA_POR_TOPICO.get(topico, 6),
            criado_em=agora,
            atualizado_em=agora,
            canal_origem="web",
            sujeito=dono,
            topico=topico,
            confianca=1.0,
            evidence_role="user",
            privacy_scope="owner_private",
            memory_pool="general",
        ))
    return fatos, {"fatos": len(fatos)}


def _coletar_conversas(
    dono: str,
    dados: Optional[dict],
    *,
    fonte: str,
    canal: str,
    pool: str,
) -> Tuple[List[EventoMemoria], dict]:
    """Conversas web / Emily Code → eventos determinísticos do dono."""
    eventos: List[EventoMemoria] = []
    puladas = 0
    if not isinstance(dados, dict):
        return eventos, {"conversas": 0, "eventos": 0, "ignoradas": 0}
    for conversa in dados.get("conversas") or ():
        if not isinstance(conversa, dict):
            continue
        cid = str(conversa.get("id") or "").strip()
        mensagens = conversa.get("mensagens") or []
        if not cid or not mensagens:
            puladas += 1
            continue
        for indice, mensagem in enumerate(mensagens):
            texto = str((mensagem or {}).get("texto") or "").strip()
            if not texto:
                continue
            papel = _normalizar_papel((mensagem or {}).get("papel"))
            quando = float((mensagem or {}).get("quando") or 0.0)
            eventos.append(EventoMemoria(
                id=_id_evento_migrado(dono, fonte, f"{cid}:{indice}", papel, texto),
                owner_user_id=dono,
                papel=papel,
                texto=texto,
                canal=canal,
                timestamp=quando if quando else time.time(),
                conversa_id=cid,
                external_id=f"migracao:{fonte}:{cid}:{indice}",
                privacy_scope="owner_private",
                memory_pool=pool,
            ))
    return eventos, {
        "conversas": len(dados.get("conversas") or ()),
        "eventos": len(eventos),
        "ignoradas": puladas,
    }


def _coletar_dms(
    dono_discord: str,
    dono_canonico: str,
    dados: Optional[dict],
) -> Tuple[List[EventoMemoria], dict]:
    """DMs: cada pessoa é um namespace próprio (discord:<id>).

    A DM do próprio dono (ID igual ao usuario_id do bot) vai para o namespace
    canônico dele — é conversa DELE com a Emily, não de terceiro.
    """
    eventos: List[EventoMemoria] = []
    if not isinstance(dados, dict):
        return eventos, {"pessoas": 0, "eventos": 0}
    for uid, ficha in (dados.get("usuarios") or {}).items():
        alvo = (dono_canonico if str(uid) == dono_discord
                else f"discord:{uid}")
        for indice, mensagem in enumerate((ficha or {}).get("mensagens") or ()):
            texto = str((mensagem or {}).get("texto") or "").strip()
            if not texto:
                continue
            papel = "user" if (mensagem or {}).get("quem") == "pessoa" else "assistant"
            quando = float((mensagem or {}).get("quando") or 0.0)
            eventos.append(EventoMemoria(
                id=_id_evento_migrado(alvo, "dms", f"{uid}:{indice}", papel, texto),
                owner_user_id=alvo,
                papel=papel,
                texto=texto,
                canal="discord_dm",
                timestamp=quando if quando else time.time(),
                external_id=f"migracao:dms:{uid}:{indice}",
                privacy_scope="owner_private",
                memory_pool="general",
            ))
    return eventos, {"pessoas": len(dados.get("usuarios") or ()), "eventos": len(eventos)}


def _coletar_fatos_discord(
    dados: Optional[dict],
) -> Tuple[List[FatoMemoria], dict]:
    """Fatos curados do perfil do Discord: um namespace por membro.

    O conteúdo desses fatos é sobre a pessoa — vai para o namespace dela
    (discord:<id>), nunca para o do dono.
    """
    fatos: List[FatoMemoria] = []
    if not isinstance(dados, dict):
        return fatos, {"fatos": 0}
    agora = time.time()
    for uid, ficha in (dados.get("membros") or {}).items():
        nome = str((ficha or {}).get("nome") or uid).strip() or str(uid)
        for indice, texto in enumerate((ficha or {}).get("fatos") or ()):
            texto = str(texto or "").strip()
            if len(texto) < 4:
                continue
            fatos.append(FatoMemoria(
                id=_id_fato_migrado("discord", f"{uid}:{indice}:{texto}"),
                owner_user_id=f"discord:{uid}",
                texto=texto,
                importancia=6,
                criado_em=float((ficha or {}).get("visto_em") or agora),
                atualizado_em=float((ficha or {}).get("extraido_em") or agora),
                canal_origem="discord",
                sujeito=nome,
                topico="relationship",
                confianca=1.0,
                evidence_role="user",
                privacy_scope="owner_private",
                memory_pool="general",
            ))
    return fatos, {"fatos": len(fatos)}


# ═════════════════════════════════════════════════════════════════
# MIGRADOR
# ═════════════════════════════════════════════════════════════════

class MigradorMemoria:
    """Importa as memórias antigas para a unificada, sem tocar nas fontes.

    Componentes da infra (journal, Chroma, extrator) só são abertos quando
    `executar(seco=False)` roda — o modo seco (dry-run) é 100% leitura.
    """

    def __init__(
        self,
        config: Optional[ConfigMemoria] = None,
        chamar_extracao: Optional[Callable[..., str]] = None,
        provedor_embeddings: Optional[ProvedorEmbeddings] = None,
        dono: str = "",
    ):
        self.config = config or carregar_config()
        self.dono = str(dono or dono_id() or "vitor")
        self._chamar_extracao = chamar_extracao
        self._provedor_embeddings = provedor_embeddings

    @staticmethod
    def _limitar(eventos: List[EventoMemoria], limite: Optional[int]):
        """Mantém as MAIS RECENTES quando há teto — o velho já é ruído."""
        if limite is None or limite <= 0 or len(eventos) <= limite:
            return eventos
        ordenados = sorted(eventos, key=lambda e: e.timestamp, reverse=True)
        return sorted(ordenados[:limite], key=lambda e: e.timestamp)

    @staticmethod
    def _validar_fontes(fontes: Optional[Sequence[str]]) -> List[str]:
        if not fontes or "todas" in fontes or "todos" in fontes:
            return list(FONTES_VALIDAS)
        escolhidas = []
        for fonte in fontes:
            if fonte not in FONTES_VALIDAS:
                raise ValueError(
                    f"fonte desconhecida: {fonte}. Válidas: {FONTES_VALIDAS}")
            escolhidas.append(fonte)
        return escolhidas

    def planejar(
        self,
        fontes: Optional[Sequence[str]] = None,
        limite_eventos: Optional[int] = None,
    ) -> dict:
        """Lê as fontes e devolve o que seria migrado — SEM escrever nada."""
        escolhidas = self._validar_fontes(fontes)
        plano: dict = {
            "dono": self.dono,
            "dono_discord_id": _id_dono_discord(),
            "fontes": {},
            "fatos_diretos": [],
            "eventos": [],
        }

        if "memoria" in escolhidas:
            fatos, contagem = _coletar_fatos_memoria(
                self.dono, _ler_json(CAMINHO_MEMORIA))
            plano["fatos_diretos"].extend(fatos)
            plano["fontes"]["memoria"] = contagem

        if "discord" in escolhidas:
            fatos, contagem = _coletar_fatos_discord(
                _ler_json(CAMINHO_MEMORIA_DISCORD))
            plano["fatos_diretos"].extend(fatos)
            plano["fontes"]["discord"] = contagem

        if "conversas" in escolhidas:
            eventos, contagem = _coletar_conversas(
                self.dono, _ler_json(CAMINHO_CONVERSAS),
                fonte="conversas", canal="web", pool="general")
            eventos = self._limitar(eventos, limite_eventos)
            plano["eventos"].extend(eventos)
            plano["fontes"]["conversas"] = contagem

        if "code" in escolhidas:
            eventos, contagem = _coletar_conversas(
                self.dono, _ler_json(CAMINHO_CODE),
                fonte="code", canal="emily_code", pool="code")
            eventos = self._limitar(eventos, limite_eventos)
            plano["eventos"].extend(eventos)
            plano["fontes"]["code"] = contagem

        if "dms" in escolhidas:
            eventos, contagem = _coletar_dms(
                plano["dono_discord_id"], self.dono, _ler_json(CAMINHO_DMS))
            eventos = self._limitar(eventos, limite_eventos)
            plano["eventos"].extend(eventos)
            plano["fontes"]["dms"] = contagem

        return plano

    def executar(
        self,
        fontes: Optional[Sequence[str]] = None,
        *,
        seco: bool = False,
        limite_eventos: Optional[int] = None,
    ) -> dict:
        """Migra de verdade (ou só planeja, com seco=True)."""
        plano = self.planejar(fontes, limite_eventos)
        relatorio = {
            "seco": bool(seco),
            "dono": plano["dono"],
            "dono_discord_id": plano["dono_discord_id"],
            "fontes": plano["fontes"],
            "fatos_diretos": len(plano["fatos_diretos"]),
            "eventos": len(plano["eventos"]),
            "fatos_gravados": 0,
            "fatos_ja_existiam": 0,
            "lotes_extracao": 0,
            "erros": [],
        }
        if seco:
            return relatorio

        try:
            servico, armazenamento = self._abrir()
        except Exception as erro:  # noqa: BLE001 - o CLI mostra o erro na mão
            relatorio["erros"].append(f"não abri a infraestrutura: {erro}")
            return relatorio

        for fato in plano["fatos_diretos"]:
            try:
                if armazenamento.obter(fato.owner_user_id, fato.id) is not None:
                    relatorio["fatos_ja_existiam"] += 1
                    continue
                armazenamento.salvar(fato)
                relatorio["fatos_gravados"] += 1
            except Exception as erro:  # noqa: BLE001
                relatorio["erros"].append(f"fato {fato.id}: {erro}")

        grupos: Dict[Tuple[str, str, str], bool] = {}
        for evento in plano["eventos"]:
            try:
                servico.registrar_evento(evento)
            except Exception as erro:  # noqa: BLE001
                relatorio["erros"].append(f"evento {evento.id}: {erro}")
                continue
            chave = (evento.owner_user_id, evento.privacy_scope,
                     evento.memory_pool)
            grupos[chave] = True

        for dono_grupo, privacidade, pool in grupos:
            try:
                lotes = servico.flush_grupo(
                    dono_grupo, privacy_scope=privacidade, memory_pool=pool)
                relatorio["lotes_extracao"] += len(lotes)
            except Exception as erro:  # noqa: BLE001
                relatorio["erros"].append(
                    f"extração {dono_grupo}/{pool}: {erro}")

        return relatorio

    def _abrir(self) -> Tuple[ServicoMemoria, ArmazenamentoMemoria]:
        """Infra própria e síncrona (sem worker): cada lote processa na hora."""
        provedor = (
            self._provedor_embeddings or criar_provedor_embeddings(self.config))
        journal = JournalMemoria(self.config)
        armazenamento = ArmazenamentoMemoria(self.config, provedor)
        extrator = ExtratorMemoria(chamar_llm=self._chamar_extracao)
        processador = ProcessadorLote(
            journal, armazenamento, extrator,
            max_tentativas=self.config.tentativas_extracao)
        servico = ServicoMemoria(
            journal, processador, config=self.config, worker=None)
        return servico, armazenamento


__all__ = ["FONTES_VALIDAS", "MigradorMemoria"]
