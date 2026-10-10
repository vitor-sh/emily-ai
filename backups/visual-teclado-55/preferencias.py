"""
preferencias.py — as escolhas do usuário que sobrevivem a fechar a Emily.

Por que este módulo existe
──────────────────────────
Nome, foto, modelo do cérebro, nível de raciocínio e a personalidade extra
eram fixos no código ou vinham só de variável de ambiente. O Vitor quer mexer
nisso pela interface e que fique salvo. Este arquivo guarda essas prefs num
único JSON, com a MESMA gravação atômica do conversas.py: escreve num tmp e só
então substitui o original (os.replace), pra um fechamento no meio da escrita
não corromper o arquivo inteiro.

O que este módulo NÃO faz
─────────────────────────
Não aplica nada. Não fala com o llm.py nem com o modelo.py. Só guarda e devolve
os valores — quem lê e aplica (trocar o modelo da rota, montar o system prompt
com o nome certo) é quem chama. Assim dá pra testar sem subir a Emily inteira.
"""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from tecla_ptt import PADRAO as TECLA_PTT_PADRAO

# Fica na casa do usuário, igual ao histórico de conversas: é dado dele, não
# entra no repositório nem morre num git clean.
ARQUIVO = Path(os.getenv("EMILY_ARQUIVO_PREFERENCIAS",
                         str(Path.home() / ".emily_preferencias.json")))

# Modelo padrão casa com a tabela ativa, não com uma tabela fixa: quando o
# Vitor troca EMILY_PROVEDOR_LLM no .env, uma preferência velha apontando pro
# modelo do provedor ANTIGO sobrescreveria o novo na inicialização (main.py
# aplica prefs sobre a rota) e a Emily falharia com 400 "not a valid model ID"
# — medido de verdade na migração claude -> openrouter.
def _modelo_padrao() -> str:
    try:
        import llm
        return llm.rota("conversa").modelo
    except Exception:
        return os.getenv("EMILY_CLAUDE_MODELO", "claude-opus-4-8")


# Provedor padrão = o que o .env diz ser o ativo. None significa "não persisti
# nenhum provedor nas prefs; usa o do .env". Importar llm aqui seria ciclo
# (llm importa preferencias? não, mas a inicialização de llm já consulta .env
# via load_dotenv(), e a leitura repetida de TABELA_ATIVA a cada chamada de
# preferencias garante que se a Emily trocou de provedor em runtime, o default
# acompanha).
def _provedor_padrao() -> Optional[str]:
    try:
        import llm
        return llm.TABELA_ATIVA
    except Exception:
        return None


_PADROES: Dict[str, Any] = {
    "nome": os.getenv("EMILY_USUARIO", "Vitor"),
    "avatar": "",
    "avatar_usuario": "",
    "provedor": None,           # None = usar o provedor ativo do .env
    "modelo": _modelo_padrao(),
    "raciocinio": "baixo",
    "personalidade_extra": "",
    "espiadinha": False,        # comentário espontâneo de vez em quando
    "autonomia_experimental": False,  # iniciativas práticas de baixo impacto
    "voz_delegacao_rapida": True,  # PTT do PC: Luna + delegação; False usa o modelo selecionado
    "tecla_ptt": TECLA_PTT_PADRAO,  # hardware local: não sincronizar entre computadores
    "tecla_ptt_rotulo": "",        # nome da tecla física no teclado deste PC
    "pet_desktop_ativo": True,     # mascote local do Fedora; não sincronizar
    "pet_desktop_tamanho": 100,   # percentual local: 50 a 130
    "audio_preprocess_denoise": True,     # RNNoise antes do Whisper
    "audio_preprocess_normalize": True,   # loudnorm antes do Whisper
    "audio_preprocess_vad": True,         # Silero corta silêncio antes do Whisper
    "volume_voz": 1.0,          # fator do volume da voz (0 a 1.5; 1.0 = o TTS cru)
    "modelo_discord": "",       # override do modelo das respostas no Discord
    "monitor_discord_host": "",  # um único desktop acompanha o Discord
}

# Configurações locais como emily_code_projeto/permissões não atravessam PCs.
SINCRONIZAVEIS = frozenset(_PADROES) - {"tecla_ptt", "tecla_ptt_rotulo",
                                      "pet_desktop_ativo", "pet_desktop_tamanho"}

# Modelos válidos POR PROVEDOR. Uma preferência salva só é aplicada na
# inicialização se o (provedor, modelo) bater com o que está registrado e a
# lista de modelos do provedor aceita. É o mesmo problema do _modelo_padrao,
# no sentido contrário: pref salva de outro provedor não pode vazar pra este.
def _provedores_validos() -> set:
    try:
        import llm
        return set(llm.PROVEDORES)
    except Exception:
        return set()


def _modelos_validos_para(provedor: str) -> set:
    """Modelos aceitos por um provedor específico. Lista vazia = não dá pra
    validar (llm não carregou); nesse caso _validar() aceita tudo na dúvida."""
    if not provedor:
        return set()
    try:
        import llm
        modelos = llm._modelos_provedor(provedor)  # noqa: SLF001 — helper interno, não reexportar
        return {m["id"] for m in modelos} | {llm.ROTAS["conversa"].modelo}
    except Exception:
        return set()


def _validar_provedor_e_modelo(provedor: Optional[str], modelo: str) -> Tuple[Optional[str], str]:
    """
    Devolve (provedor, modelo) válidos a partir do que veio das prefs.

    Regras:
      - provedor vazio/None vira o provedor ativo do .env (passa adiante).
      - provedor não registrado é descartado (volta pro ativo do .env).
      - modelo vazio vira o modelo padrão do provedor escolhido.
      - modelo de OUTRO provedor é descartado (volta pro default do provedor).
    """
    ativos = _provedores_validos()
    pid = (provedor or "").strip().lower() or None
    if pid is not None and pid not in ativos:
        # provedor salvo é de uma sessão anterior com .env diferente
        pid = _provedor_padrao()

    if pid is None:
        pid = _provedor_padrao()

    modelos_ok = _modelos_validos_para(pid or "")
    if not modelo or (modelos_ok and modelo not in modelos_ok):
        # modelo salvo é de outro provedor OU não está na lista do ativo
        try:
            import llm
            modelo = llm.rota("conversa").modelo
        except Exception:
            modelo = os.getenv("EMILY_CLAUDE_MODELO", "claude-opus-4-8")
    return pid, modelo


def provedor_valido(provedor: str) -> bool:
    """True se o provedor está registrado em llm.PROVEDORES."""
    if not provedor:
        return False
    ativos = _provedores_validos()
    return not ativos or provedor in ativos


def modelo_valido(modelo: str, provedor: Optional[str] = None) -> bool:
    """
    True se o modelo pode ser aplicado na tabela ativa (ou no provedor
    passado, se informado). Lista vazia = não dá pra validar; aceita.
    """
    if not modelo:
        return False
    pid = provedor or _provedor_padrao()
    validos = _modelos_validos_para(pid or "")
    return not validos or modelo in validos

_lock = threading.RLock()
_cache: Dict[str, Any] | None = None
_cache_id: tuple[str, int] | None = None


@contextmanager
def _bloqueio_entre_processos():
    """Serializa alterações da janela e do gateway que usam o mesmo JSON."""
    caminho = ARQUIVO.with_name(ARQUIVO.name + ".lock")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a+b") as trava:
        if os.name == "nt":
            import msvcrt
            if trava.tell() == 0:
                trava.write(b"0")
                trava.flush()
            trava.seek(0)
            msvcrt.locking(trava.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                trava.seek(0)
                msvcrt.locking(trava.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(trava.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(trava.fileno(), fcntl.LOCK_UN)


def _id_arquivo() -> tuple[str, int]:
    try:
        return str(ARQUIVO), ARQUIVO.stat().st_mtime_ns
    except OSError:
        return str(ARQUIVO), -1


def _arquivo_revisoes() -> Path:
    return ARQUIVO.with_name(ARQUIVO.stem + "_sync.json")


def _ler_revisoes() -> Dict[str, float]:
    try:
        dados = json.loads(_arquivo_revisoes().read_text(encoding="utf-8"))
        return {k: float(v) for k, v in dados.items()
                if k in SINCRONIZAVEIS and isinstance(v, (int, float))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _salvar_revisoes(dados: Dict[str, float]) -> None:
    caminho = _arquivo_revisoes()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(temporario, caminho)


def _log(msg: str) -> None:
    print(f"[PREFERENCIAS] {msg}")


def _carregar() -> Dict[str, Any]:
    global _cache, _cache_id
    with _lock:
        arquivo_id = _id_arquivo()
        if _cache is not None and _cache_id == arquivo_id:
            return _cache
        dados: Dict[str, Any] = {}
        try:
            with open(ARQUIVO, encoding="utf-8") as f:
                lido = json.load(f)
            if isinstance(lido, dict):
                dados = lido
            else:
                raise ValueError("formato inesperado")
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, ValueError, OSError) as e:
            # Prefs corrompidas não podem impedir a Emily de abrir. Começa dos
            # padrões — perder a preferência é chato, não abrir é pior.
            _log(f"não consegui ler as preferências ({e}); usando padrões")
        # Padrões preenchem o que faltar, sem apagar o que já existe.
        completo = dict(_PADROES)
        completo.update({k: v for k, v in dados.items() if v is not None})
        # Provedor + modelo salvos são validados juntos: se o provedor sumiu
        # do .env ou o modelo é de outro provedor, cai no default. Sem isso,
        # a Emily abria com 400 "not a valid model ID" — medido de verdade na
        # migração claude -> openrouter.
        provedor_salvo = completo.get("provedor")
        modelo_salvo = completo.get("modelo", "")
        provedor_usar, modelo_usar = _validar_provedor_e_modelo(
            provedor_salvo, modelo_salvo)
        if provedor_usar != provedor_salvo or modelo_usar != modelo_salvo:
            _log(f"preferência (provedor='{provedor_salvo}', modelo='{modelo_salvo}') "
                 f"ajustada para (provedor='{provedor_usar}', modelo='{modelo_usar}')")
        completo["provedor"] = provedor_usar
        completo["modelo"] = modelo_usar
        _cache = completo
        _cache_id = arquivo_id
        return _cache


def _salvar(mudancas: Dict[str, Any]) -> bool:
    """Grava só os campos alterados, sem transformar padrões em edições."""
    global _cache, _cache_id
    with _lock:
        tmp = ARQUIVO.with_suffix(".tmp")
        try:
            try:
                dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
                if not isinstance(dados, dict):
                    dados = {}
            except (OSError, ValueError):
                dados = {}
            dados.update(mudancas)
            ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, ARQUIVO)
            _cache = None
            _cache_id = None
            return True
        except OSError as e:
            _log(f"não consegui gravar: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            return False


# ═════════════════════════════════════════════════════════════════
# API
# ═════════════════════════════════════════════════════════════════

def carregar() -> Dict[str, Any]:
    """Todas as preferências (cópia, pra ninguém mexer no cache por fora)."""
    return dict(_carregar())


def obter(chave: str, padrao: Any = None) -> Any:
    """Uma preferência. Cai no padrão de fábrica e depois no 'padrao' passado."""
    dados = _carregar()
    if chave in dados:
        return dados[chave]
    return _PADROES.get(chave, padrao)


def definir(**campos: Any) -> bool:
    """
    Muda uma ou mais preferências e grava na hora.

    Ignora valor None (é 'não mexe nisso', não 'apaga'). String é usada como
    veio; quem valida conteúdo (modelo existe? nível é aceito?) é quem aplica.
    Retorna False se não conseguiu persistir a alteração.
    """
    with _lock, _bloqueio_entre_processos():
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                dados = {}
        except (OSError, ValueError):
            dados = {}
        revisoes = {k: item["quando"] for k, item in exportar_sync().items()}
        mudancas: Dict[str, Any] = {}
        mudados: list[str] = []
        for chave, valor in campos.items():
            if valor is not None and (chave not in dados or dados[chave] != valor):
                mudancas[chave] = valor
                if chave in SINCRONIZAVEIS:
                    mudados.append(chave)
        if not mudancas:
            return True
        if not _salvar(mudancas):
            return False
        agora = time.time()
        for chave in mudados:
            revisoes[chave] = agora
        try:
            _salvar_revisoes(revisoes)
        except OSError as exc:
            _log(f"preferência salva, mas revisão de sync não gravada: {exc}")
            return False
        return True


def exportar_sync() -> Dict[str, Dict[str, Any]]:
    """Exporta somente valores persistidos e versões por campo."""
    with _lock:
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
            if not isinstance(dados, dict):
                return {}
            mtime = ARQUIVO.stat().st_mtime
        except (OSError, ValueError):
            return {}
        revisoes = _ler_revisoes()
        return {k: {"valor": v, "quando": revisoes.get(k, mtime)}
                for k, v in dados.items() if k in SINCRONIZAVEIS}


def mesclar_sync(campos: Dict[str, Dict[str, Any]], *, forcar: bool = False) -> list[str]:
    """Aplica campos remotos mais recentes sem tocar preferências locais."""
    with _lock, _bloqueio_entre_processos():
        atuais = exportar_sync()
        dados = _carregar()
        revisoes = {k: item["quando"] for k, item in atuais.items()}
        alterados: list[str] = []
        mudancas: Dict[str, Any] = {}
        revisoes_mudaram = False
        for chave, item in campos.items():
            if chave not in SINCRONIZAVEIS or not isinstance(item, dict):
                continue
            try:
                quando = float(item["quando"])
                valor = item["valor"]
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 < quando and (forcar or quando < time.time() + 86400)):
                continue
            padrao = _PADROES[chave]
            if isinstance(padrao, bool) and not isinstance(valor, bool):
                continue
            if isinstance(padrao, float) and (
                    isinstance(valor, bool) or not isinstance(valor, (int, float))):
                continue
            if isinstance(padrao, str) and not isinstance(valor, str):
                continue
            if padrao is None and valor is not None and not isinstance(valor, str):
                continue
            if isinstance(valor, str) and len(valor) > (1_500_000 if chave.startswith("avatar") else 100_000):
                continue
            if forcar and atuais.get(chave) == {"valor": valor, "quando": quando}:
                continue
            if not forcar and quando <= float(atuais.get(chave, {}).get("quando", 0)):
                continue
            if chave.startswith("avatar") and valor and (
                    not isinstance(valor, str) or not valor.startswith("data:image/")):
                continue
            if dados.get(chave) != valor:
                dados[chave] = valor
                alterados.append(chave)
            mudancas[chave] = valor
            revisoes[chave] = quando
            revisoes_mudaram = True
        if revisoes_mudaram:
            if not _salvar(mudancas):
                return []
            _salvar_revisoes(revisoes)
        return alterados


def recarregar() -> None:
    """Joga o cache fora. Pra teste e pra quem editar o arquivo à mão."""
    global _cache, _cache_id
    with _lock:
        _cache = None
        _cache_id = None


_observador: threading.Thread | None = None


def observar_alteracoes(callback, intervalo: float = 3.0) -> None:
    """Reage a preferências recebidas pelo gateway em outro processo."""
    global _observador
    if _observador is not None and _observador.is_alive():
        return

    def ciclo() -> None:
        anterior = _id_arquivo()
        while True:
            time.sleep(max(1.0, intervalo))
            atual = _id_arquivo()
            if atual == anterior:
                continue
            anterior = atual
            try:
                recarregar()
                callback(carregar())
            except Exception as exc:
                _log(f"não apliquei preferência externa: {type(exc).__name__}: {exc}")

    _observador = threading.Thread(target=ciclo, name="emily-preferencias", daemon=True)
    _observador.start()


if __name__ == "__main__":
    import sys
    print("arquivo:", ARQUIVO, "| existe:", ARQUIVO.exists())
    for k, v in carregar().items():
        amostra = v if k != "avatar" else (f"<data-uri {len(v)} chars>" if v else "")
        print(f"  {k:20s} = {amostra!r}")
    sys.exit(0)
