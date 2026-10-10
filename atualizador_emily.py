"""
atualizador_emily.py — o botão "Atualizar" da Emily empacotada.

Arquitetura (por que atualizar sem recompilar funciona)
────────────────────────────────────────────────────────
O executável tem DUAS camadas:

  1. O MOTOR — bibliotecas pesadas (numpy, discord.py, selenium, aiohttp,
     PyQt do sistema...). Fica embutido no pacote e só muda com recompilação.
  2. O CÓDIGO da Emily — main.py, os .py internos, web/, static/, img/, assets/
     e .env.
     ATUALIZÁVEIS em tempo real: o runtime hook instala um import finder que
     dá prioridade aos .py soltos dentro de _internal/ sobre o código embutido
     no pacote. Sobrescrever o arquivo lá = atualizar a Emily.

O botão "Atualizar agora" (nas Configurações) faz, nesta ordem:
  1. Lê o código da pasta do projeto (a origem registrada no build);
  2. Copia só o que mudou pra um diretório de ensaio (staging);
  3. Valida DE VERDADE antes de aplicar: sintaxe de cada .py + um preflight
     que roda o próprio executável importando todos os módulos — se você
     adicionou uma biblioteca nova que não existe no pacote, ele AVISA
     "precisa recompilar" em vez de deixar a Emily quebrada na próxima aberta;
  4. Aplica com backup do que sobrescreveu (o "Desfazer" restaura) e reinicia
     a Emily sozinho (os.execv — substitui o processo inteiro, limpo).

Builds novos congelam somente um bootstrap mínimo e carregam main.py como um
módulo sombreável. Assim o main também atualiza. Pacotes feitos antes dessa
migração continuam seguros: o atualizador reconhece o formato antigo, avisa que
o main ainda precisa de uma última recompilação e atualiza todo o resto.

O diff do estado (o "N mudanças" do botão)
──────────────────────────────────────────
O que vale pra um módulo é: o override solto em _internal/ se existir, senão
o código EMBUTIDO. O embutido não é hash-ável em runtime (está compilado no
PYZ), então o build grava o md5 de cada módulo em
_internal/_atualizacao_base.json (manifesto do build). Sem esse manifesto,
um pacote recém-compilado contava TODOS os módulos como "novos" — as "54
mudanças" eternas que apareciam mesmo depois de recompilar. O pacote sem o
manifesto cai no comportamento antigo (compatível), e a primeira atualização
aplicada com sucesso também conserta o estado sozinha (os overrides passam a
existir e a bater com a origem).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Pastas e arquivos NÃO-.py que acompanham o código na atualização.
_ASSETS = ("web", "static", "img", "assets")
_PACOTES_CODIGO = ("memoria_unificada", "emily_cloud")
_ARQUIVOS_RAIZ = ("emilyimage.png", "emily.gif", ".env", "requirements.txt")
_REGISTRO_ORIGEM = "origem_projeto.txt"
_MANIFESTO = "_atualizacao_manifest.json"
_STAGING = "_staging_atualizacao"
_BACKUP = "_atualizacao_backup"
# Hashes do código EMBUTIDO, gravados pelo build em _internal/. É a segunda
# metade do diff: o estado compara a origem contra o que VALE no pacote —
# o override solto se existir, senão o embutido (que não é hash-ável em
# runtime, porque está compilado dentro do PYZ).
_ARQUIVO_BASE = "_atualizacao_base.json"
TAM_STAGING_RELA = _STAGING  # subpasta de _internal; o finder ignora subpastas
# Teto do ENSAIO (o subprocesso que importa tudo de verdade), em segundos.
# O clique do botão tem teto PRÓPRIO no JS (maior que este) — os dois são
# independentes de propósito: o JS não pode abortar o que o Python valida.
TETO_PREFLIGHT = 180


_base_cache: Dict[str, Tuple[float, Dict[str, str]]] = {}


def _base_embutida() -> Dict[str, str]:
    """{nome_módulo: md5} do código embutido no build. {} se não houver."""
    internal = _caminho_internal()
    if internal is None:
        return {}
    caminho = internal / _ARQUIVO_BASE
    try:
        quando = caminho.stat().st_mtime
    except OSError:
        return {}
    # Cache curto por mtime: o estado chama isto por MÓDULO (54× na
    # varredura) e o arquivo é estático do build.
    em_cache = _base_cache.get(str(caminho))
    if em_cache and em_cache[0] == quando:
        return em_cache[1]
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        mods = bruto.get("modulos")
        saida = {str(k): str(v) for k, v in mods.items()} if isinstance(mods, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError):
        saida = {}
    _base_cache[str(caminho)] = (quando, saida)
    return saida


def _metadados_base() -> Dict:
    """Metadados completos do build; aceita manifestos antigos sem flags."""
    internal = _caminho_internal()
    if internal is None:
        return {}
    try:
        bruto = json.loads((internal / _ARQUIVO_BASE).read_text(encoding="utf-8"))
        return bruto if isinstance(bruto, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _main_atualizavel() -> bool:
    """True quando o executável usa emily_bootstrap em vez de main congelado."""
    return _metadados_base().get("main_atualizavel") is True


def _hash_do_que_vale(alvo: Path, nome_base: str) -> str:
    """
    Hash do código que de fato roda pra esse módulo.

    Override solto em _internal/ vence o embutido (o finder do runtime hook
    dá prioridade a ele); sem override, vale o embutido — e aí a referência
    é o hash gravado no build. Assim um pacote recém-compilado não conta os
    ~54 módulos como "novos": sem arquivo solto, o comparado é o embutido,
    que é IGUAL à origem da época do build.
    """
    if alvo.exists():
        return _hash_arquivo(alvo)
    return _base_embutida().get(nome_base, "")


def _nome_modulo(relativo: Path) -> str:
    """Caminho Python relativo no formato usado pelo manifesto/import."""

    partes = list(relativo.with_suffix("").parts)
    if partes and partes[-1] == "__init__":
        partes.pop()
    return ".".join(partes)


def _log(msg: str) -> None:
    print(f"[ATUALIZADOR] {msg}")


def em_pacote() -> bool:
    return bool(getattr(sys, "frozen", False))


def _caminho_pacote() -> Optional[Path]:
    """Pasta do executável (dist/Emily). None quando roda do código-fonte."""
    if not em_pacote():
        return None
    return Path(sys.executable).resolve().parent


def _caminho_internal() -> Optional[Path]:
    pacote = _caminho_pacote()
    if pacote is None:
        return None
    return pacote / "_internal"


def _parece_projeto(caminho: Path) -> bool:
    """Evita aceitar como origem uma pasta qualquer que apenas exista."""
    try:
        return (caminho.is_dir()
                and (caminho / "main.py").is_file()
                and (caminho / "atualizador_emily.py").is_file())
    except OSError:
        return False


def _gravar_origem(origem: Path) -> bool:
    """Persiste uma origem válida; mantém a segunda linha para pacotes antigos."""
    internal = _caminho_internal()
    if internal is None:
        return False
    registro = internal / _REGISTRO_ORIGEM
    hash_main = _hash_arquivo(origem / "main.py")
    try:
        registro.write_text(f"{origem.resolve()}\n{hash_main}\n", encoding="utf-8")
        return True
    except OSError as e:
        _log(f"não consegui registrar a origem {origem}: {e}")
        return False


def definir_origem_projeto(caminho: str) -> str:
    """Define manualmente a origem usada pelo botão de atualização."""
    texto = os.path.expandvars(os.path.expanduser(str(caminho or "").strip()))
    if not texto:
        return "Escolha uma pasta de projeto."
    candidata = Path(texto).resolve()
    if not _parece_projeto(candidata):
        return ("Essa pasta não parece ser o projeto da Emily: preciso encontrar "
                "main.py e atualizador_emily.py nela.")
    if not _gravar_origem(candidata):
        return "Não consegui salvar a pasta escolhida dentro do pacote."
    _log(f"origem definida manualmente: {candidata}")
    return f"OK Origem definida: {candidata}"


def _candidatas_origem(registrada: Optional[Path]) -> List[Path]:
    """Origens possíveis, em ordem, sem varrer o disco inteiro."""
    candidatas: List[Path] = []

    def adicionar(valor) -> None:
        if not valor:
            return
        try:
            caminho = Path(valor).expanduser().resolve()
        except (OSError, RuntimeError, TypeError):
            return
        if caminho not in candidatas:
            candidatas.append(caminho)

    adicionar(os.environ.get("EMILY_PROJECT_DIR"))
    adicionar(registrada)
    pacote = _caminho_pacote()
    if pacote:
        # Layout normal: <projeto>/dist/Emily/Emily. Também cobre o pacote
        # colocado diretamente dentro do projeto ou um nível abaixo.
        adicionar(pacote)
        for pai in pacote.parents:
            adicionar(pai)
    return candidatas


def origem_projeto() -> Optional[Path]:
    """Origem registrada, via env ou recuperada do layout do pacote."""
    internal = _caminho_internal()
    if internal is None:
        return None
    registro = internal / _REGISTRO_ORIGEM
    registrada: Optional[Path] = None
    try:
        primeira = registro.read_text(encoding="utf-8").splitlines()[0].strip()
        registrada = Path(primeira) if primeira else None
    except (OSError, IndexError):
        pass

    for candidata in _candidatas_origem(registrada):
        if not _parece_projeto(candidata):
            continue
        if candidata != registrada:
            _gravar_origem(candidata)
            _log(f"origem recuperada automaticamente: {candidata}")
        return candidata
    # Retorna o caminho inválido registrado para a UI conseguir diagnosticá-lo.
    return registrada


def _hash_do_main_na_origem() -> str:
    origem = origem_projeto()
    if not origem:
        return ""
    return _hash_arquivo(origem / "main.py")


def _hash_arquivo(caminho: Path) -> str:
    try:
        return hashlib.md5(caminho.read_bytes()).hexdigest()
    except OSError:
        return ""


# ─────────────────────────────────────────────────────────────────
# O QUE COMPÕE UMA ATUALIZAÇÃO
#
# .py internos (mesmo filtro do build) + main.py nos builds com bootstrap + as
# pastas de assets e arquivos de raiz. Em pacotes legados, main continua fora
# e o estado pede uma última recompilação de migração.
# ─────────────────────────────────────────────────────────────────

def _modulo_interno(nome_arquivo: str) -> bool:
    """Mesmo critério do build_emily_linux (testes/scripts de fora)."""
    if not nome_arquivo.endswith(".py"):
        return False
    base = nome_arquivo[:-3]
    if base.startswith("_"):
        return False
    if base.startswith(("test_", "testar_", "testepython", "test_emily")):
        return False
    if base in ("build_emily", "build_emily_linux", "emily_bootstrap",
                "emily_teste_animacao", "diagnostico_whatsapp",
                "dividir_audio", "pyi_rhook_emily", "interface"):
        # O build padrão contém só a WebView; PyQt6 da interface legada não
        # faz parte do pacote e falha no ensaio de imports se for sobrescrito.
        return False
    return True


def _itens_da_origem(origem: Path) -> List[Path]:
    """Caminhos (relativos à origem) que compõem uma atualização."""
    itens: List[Path] = []
    for nome in sorted(os.listdir(origem)):
        if _modulo_interno(nome) and (nome != "main.py" or _main_atualizavel()):
            itens.append(Path(nome))
    for pacote in _PACOTES_CODIGO:
        pasta_pacote = origem / pacote
        if pasta_pacote.is_dir():
            itens.extend(
                caminho.relative_to(origem)
                for caminho in sorted(pasta_pacote.rglob("*.py"))
                if "__pycache__" not in caminho.parts
            )
    for pasta in _ASSETS:
        pasta_origem = origem / pasta
        if pasta_origem.is_dir():
            for raiz, _, arquivos in os.walk(pasta_origem):
                for arquivo in arquivos:
                    caminho = Path(raiz) / arquivo
                    # RELATIVO à origem — absoluto aqui faria o diff comparar
                    # o arquivo com ele mesmo (bug pego pelo teste).
                    itens.append(caminho.relative_to(origem))
    for nome in _ARQUIVOS_RAIZ:
        if (origem / nome).is_file():
            itens.append(Path(nome))
    return itens


def _staging_dir() -> Optional[Path]:
    internal = _caminho_internal()
    return internal / _STAGING if internal else None


def _backup_dir() -> Optional[Path]:
    internal = _caminho_internal()
    return internal / _BACKUP if internal else None


def _manifesto_path() -> Optional[Path]:
    internal = _caminho_internal()
    return internal / _MANIFESTO if internal else None


def _ler_manifesto() -> Dict:
    caminho = _manifesto_path()
    if not caminho:
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _gravar_manifesto(dados: Dict) -> None:
    caminho = _manifesto_path()
    if not caminho:
        return
    try:
        caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    except OSError as e:
        _log(f"não gravei o manifesto: {e}")


def _pode_desfazer() -> bool:
    manifesto = _ler_manifesto()
    return bool(manifesto.get("arquivos"))


# ─────────────────────────────────────────────────────────────────
# ESTADO (o que a UI mostra)
# ─────────────────────────────────────────────────────────────────

def estado_atualizacao() -> Dict:
    internal = _caminho_internal()
    origem = origem_projeto()
    estado: Dict = {
        "em_pacote": em_pacote(),
        "origem": str(origem or ""),
        "origem_ok": bool(origem and _parece_projeto(origem)),
        "novos": [], "mudados": [], "removidos": [], "assets": [],
        "quantos": 0, "resumo": "",
        "main_mudou": False,
        "ultima": (_ler_manifesto().get("quando_legivel") or ""),
        "pode_desfazer": _pode_desfazer(),
    }
    if not (internal and origem and estado["origem_ok"]):
        return estado

    # Pacotes com bootstrap tratam main como qualquer outro módulo. Nos
    # legados, compara o hash do entry point congelado e pede a recompilação.
    if not _main_atualizavel():
        registro = internal / _REGISTRO_ORIGEM
        try:
            hash_build = registro.read_text(encoding="utf-8").splitlines()[1].strip()
        except (OSError, IndexError):
            hash_build = ""
        hash_agora = _hash_do_main_na_origem()
        estado["main_mudou"] = bool(hash_build and hash_agora
                                    and hash_build != hash_agora)

    novos, mudados, removidos, assets = [], [], [], []
    for relativo in _itens_da_origem(origem):
        alvo = internal / relativo
        if relativo.suffix == ".py":
            base = _nome_modulo(relativo)
            if not alvo.exists() and not _base_embutida():
                # Sem manifesto do build não dá pra comparar com o embutido:
                # fica o comportamento antigo (conta como novo), que é o
                # falso "54 mudanças" — o build novo resolve isso na raiz.
                novos.append(str(relativo))
            elif _hash_do_que_vale(alvo, base) != _hash_arquivo(origem / relativo):
                mudados.append(str(relativo))
        else:
            if (not alvo.exists()
                    or _hash_arquivo(alvo) != _hash_arquivo(origem / relativo)):
                assets.append(str(relativo))
    # Overrides que sumiram da origem: fantasma vencendo o código embutido.
    for nome in sorted(os.listdir(internal)):
        caminho = internal / nome
        if (caminho.is_file() and nome != "main.py" and nome.endswith(".py")
                and _modulo_interno(nome) and not (origem / nome).exists()):
            removidos.append(nome)

    estado["novos"], estado["mudados"] = novos, mudados
    estado["removidos"], estado["assets"] = removidos, assets
    total = len(novos) + len(mudados) + len(removidos) + len(assets)
    estado["quantos"] = total
    partes = []
    if novos:
        partes.append(f"{len(novos)} novo(s)")
    if mudados:
        partes.append(f"{len(mudados)} alterado(s)")
    if removidos:
        partes.append(f"{len(removidos)} removido(s)")
    if assets:
        partes.append(f"{len(assets)} recurso(s)")
    estado["resumo"] = ", ".join(partes)
    return estado


# ─────────────────────────────────────────────────────────────────
# PREFLIGHT — o "ensaio geral" da atualização
#
# Roda o próprio executável com os módulos novos no lugar (via
# EMILY_OVERRIDE_DIR) e importa TUDO. Se alguma biblioteca nova não existir
# no pacote, falha AQUI — a Emily atual nunca é colocada em risco.
# ─────────────────────────────────────────────────────────────────

def _comando_preflight() -> Tuple[List[str], Dict[str, str], str]:
    """Comando, ambiente e cwd do ensaio. No exe, o próprio executável roda
    de novo (o preflight do main); no fonte (testes/dev), um subprocess com
    o mesmo redirect de teclado/clipboard que o main faz, a partir da pasta
    do projeto real (onde compat_imports e o atualizador vivem)."""
    ambiente = dict(os.environ)
    if getattr(sys, "frozen", False):
        return [sys.executable], ambiente, str(_caminho_pacote())
    comando = [
        sys.executable, "-c",
        "import sys, compat_imports as _c; "
        "sys.modules['keyboard'] = _c.keyboard; "
        "sys.modules['pyperclip'] = _c.pyperclip; "
        "import atualizador_emily as a; sys.exit(a.rodar_preflight())",
    ]
    return comando, ambiente, str(Path(__file__).resolve().parent)


def _falha_pre_existente(nome: str, pasta: str,
                         exc_original: BaseException) -> bool:
    """
    O módulo já quebrava de algum jeito no pacote sem os overrides?

    True = o EMBUTIDO também falha ao importar — o módulo já está morto no
    pacote de hoje (ex.: interface.py importa PyQt6 que nunca fez parte do
    pacote Linux), e a atualização não pode ficar refém disso pra sempre.
    False = o embutido importa limpo e a versão nova quebra — aí sim é culpa
    da atualização (biblioteca nova → precisa recompilar).

    Não compara a MENSAGEM do erro de propósito: o embutido pode ser um
    código mais velho que quebra num lugar diferente. "Já quebrava" é o
    que importa, não "quebra exatamente igual".

    Exceção: se o módulo NEM EXISTE no embutido (arquivo novo), não há
    "antes" — a versão nova é a única que existe, e se ela quebra, bloqueia
    mesmo (depois de aplicada ela também quebraria).
    """
    # Cópias, não referências: sys.path é alterado in-place logo abaixo. Guardar
    # a própria lista fazia o diretório removido continuar ausente na restauração.
    salvo_meta = list(sys.meta_path)
    salvo_path = list(sys.path)
    try:
        # Desliga o override: no exe, fora os finders que apontam pra pasta;
        # no fonte, a própria pasta sai do sys.path. O que sobrar é o
        # EMBUTIDO — exatamente o que roda hoje.
        sys.meta_path = [f for f in sys.meta_path
                         if getattr(f, "_pasta", None) != pasta]
        while pasta in sys.path:
            sys.path.remove(pasta)
        sys.modules.pop(nome, None)
        try:
            __import__(nome)
            return False   # embutido importou: a quebra é da versão nova
        except ModuleNotFoundError as e:
            # O PRÓPRIO módulo ausente ≠ dependência ausente: arquivo novo
            # não tem versão embutida pra comparar — a quebra é da versão
            # nova e tem que bloquear. Faltou DEPENDÊNCIA (name ≠ nome) é
            # que é quebra que já existia no pacote.
            return getattr(e, "name", "") != nome
        except BaseException:  # noqa: BLE001
            return True    # embutido existe e quebra: pré-existente
        finally:
            sys.modules.pop(nome, None)
    finally:
        sys.meta_path = salvo_meta
        sys.path = salvo_path


def rodar_preflight() -> int:
    """Importa todos os módulos do diretório de override. 0 = ok, 1 = falha."""
    pasta = (os.environ.get("EMILY_OVERRIDE_DIR")
             or str(_caminho_internal() or ""))
    if not pasta or not os.path.isdir(pasta):
        print("[PREFLIGHT] sem diretório de override; nada a validar")
        return 0
    # No exe quem dá prioridade ao override é o finder do runtime hook; no
    # subprocess do modo fonte não existe finder, então sys.path faz o papel.
    if not getattr(sys, "frozen", False) and pasta not in sys.path:
        sys.path.insert(0, pasta)
    nomes = sorted(
        f[:-3] for f in os.listdir(pasta)
        if f != "main.py" and f.endswith(".py") and _modulo_interno(f))
    for pacote in _PACOTES_CODIGO:
        if (Path(pasta) / pacote / "__init__.py").is_file():
            nomes.append(pacote)
    falhas: List[str] = []
    for nome in nomes:
        try:
            __import__(nome)
        except BaseException as e:  # noqa: BLE001 — qualquer falha desqualifica
            if _falha_pre_existente(nome, pasta, e):
                # Já quebrava no pacote de hoje (ex.: a UI antiga PyQt que o
                # exe nem usa). Bloquear a atualização por isso pra sempre
                # era o travamento que o Vitor via: recompilar não criava a
                # biblioteca no pacote e o ensaio falhava igual.
                print(f"[PREFLIGHT] pré-existente (ignorado): "
                      f"{nome}: {type(e).__name__}: {e}")
            else:
                falhas.append(f"{nome}: {type(e).__name__}: {e}")
    # main tem efeitos colaterais de aplicação ao importar (threads, Discord,
    # janela). Ele já passou pelo compile() do staging; aqui verificamos seus
    # imports sem executá-lo. Imports dinâmicos continuam cobertos pelos outros
    # módulos importados acima e pelo boot real após a atualização.
    main_staging = Path(pasta) / "main.py"
    if main_staging.is_file():
        try:
            import ast
            import importlib.util
            arvore = ast.parse(main_staging.read_text(encoding="utf-8"), "main.py")
            # Só imports realmente executados no topo. Imports opcionais dentro
            # de funções não devem bloquear uma atualização sem serem usados.
            for no in arvore.body:
                if isinstance(no, ast.Import):
                    modulos = [apelido.name.split(".")[0] for apelido in no.names]
                elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                    modulos = [no.module.split(".")[0]]
                else:
                    continue
                for modulo in modulos:
                    if modulo == "main" or modulo in sys.modules:
                        continue
                    try:
                        encontrado = importlib.util.find_spec(modulo)
                    except (ImportError, AttributeError, ValueError) as e:
                        falhas.append(
                            f"main.py -> {modulo}: {type(e).__name__}: {e}")
                    else:
                        if encontrado is None:
                            falhas.append(
                                f"main.py -> {modulo}: ModuleNotFoundError")
        except (OSError, SyntaxError) as e:
            falhas.append(f"main.py: {type(e).__name__}: {e}")
    # O resultado também vai pra ARQUIVO quando o pai pediu. No exe com
    # --noconsole, stdout pode ir pro log; o arquivo atravessa o redirecionamento.
    destino = os.environ.get("EMILY_PREFLIGHT_OUT")
    total_validado = len(nomes) + (1 if main_staging.is_file() else 0)
    if destino:
        try:
            Path(destino).write_text(json.dumps(
                {"rc": 1 if falhas else 0, "falhas": falhas[:8],
                 "total": total_validado},
                ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            print(f"[PREFLIGHT] não gravei o resultado em arquivo: {e}")
    if falhas:
        for falha in falhas:
            print(f"[PREFLIGHT] FALHOU {falha}")
        print(f"[PREFLIGHT] {len(falhas)} módulo(s) com problema de "
              f"{total_validado}")
        return 1
    print(f"[PREFLIGHT] ok — {total_validado} módulos validados")
    return 0


# ─────────────────────────────────────────────────────────────────
# APLICAR / DESFAZER
# ─────────────────────────────────────────────────────────────────

def _copiar_com_pastas(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(origem, destino)


def aplicar_atualizacao(reiniciar: bool = True) -> str:
    """Valida e aplica o código da pasta do projeto sobre o pacote."""
    internal = _caminho_internal()
    origem = origem_projeto()
    if not em_pacote() or not internal:
        return ("Rodando do código-fonte: aqui as mudanças já valem ao "
                "reiniciar a Emily.")
    if not origem or not _parece_projeto(origem):
        return (f"Não achei a pasta do projeto "
                f"({origem or 'origem não registrada'}). A atualização "
                f"precisa dela.")

    estado = estado_atualizacao()
    if estado["quantos"] == 0 and not estado["main_mudou"]:
        return "OK Tudo em dia — não havia nada pra atualizar."
    if estado["main_mudou"]:
        _log("main.py mudou em um pacote legado: faça uma última recompilação "
             "para migrar ao bootstrap (o resto atualiza normal).")

    staging = internal / _STAGING
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)

    # 1) Copia só o que MUDOU pro ensaio. O mesmo critério do estado: o que
    #    vale é o override solto se existir, senão o embutido (manifesto do
    #    build). Módulo igual ao embutido NÃO vai pro ensaio — sem isto o
    #    aplicar copiaria os 54 de novo mesmo quando o estado mostra 2.
    pendentes: List[Tuple[str, Path]] = []
    for relativo in _itens_da_origem(origem):
        alvo = internal / relativo
        if relativo.suffix == ".py":
            mudou = (_hash_do_que_vale(alvo, _nome_modulo(relativo))
                     != _hash_arquivo(origem / relativo))
        else:
            mudou = (not alvo.exists()
                     or _hash_arquivo(alvo) != _hash_arquivo(origem / relativo))
        if not mudou:
            continue
        _copiar_com_pastas(origem / relativo, staging / relativo)
        pendentes.append((str(relativo), alvo))
    for nome in estado["removidos"]:
        pendentes.append((nome, internal / nome))

    # 2) Sintaxe de cada .py novo (falha barata e clara). Itens de REMOÇÃO
    #    não existem no staging — não há o que validar neles.
    for rel, _alvo in pendentes:
        if not rel.endswith(".py"):
            continue
        fonte = staging / rel
        if not fonte.exists():
            continue
        try:
            compile(fonte.read_text(encoding="utf-8"), rel, "exec")
        except SyntaxError as e:
            shutil.rmtree(staging, ignore_errors=True)
            return (f"O arquivo {rel} tem erro de sintaxe "
                    f"(linha {e.lineno}); corrigindo, a atualização passa.")

    # 2b) O ensaio precisa do MESMO contexto que a Emily terá depois: o .env
    #     é lido no import do llm (pelo __file__ do módulo), então ele vai pro
    #     ensaio também — senão o preflight falha por provedor ausente mesmo
    #     a atualização estando perfeita (falso positivo medido no teste).
    if not (staging / ".env").exists() and (origem / ".env").is_file():
        _copiar_com_pastas(origem / ".env", staging / ".env")

    # 3) Preflight: o executável inteiro importa com os módulos novos.
    comando, ambiente, cwd_ensaio = _comando_preflight()
    ambiente["EMILY_PREFLIGHT"] = "1"
    ambiente["EMILY_OVERRIDE_DIR"] = str(staging)
    # O resultado do ensaio também vem por ARQUIVO: no exe com --noconsole
    # o runtime hook desvia o stdout do filho pro log em ~/.emily_log.txt e
    # o pipe chega vazio — era o "Detalhes: sem detalhes" de sempre. O
    # arquivo não depende de stdout e atravessa qualquer redirecionamento.
    resultado_ensaio = internal / "_atualizacao_preflight.json"
    ambiente["EMILY_PREFLIGHT_OUT"] = str(resultado_ensaio)
    try:
        resultado_ensaio.unlink()
    except OSError:
        pass
    try:
        ensaio = subprocess.run(
            comando, env=ambiente, capture_output=True, text=True,
            timeout=TETO_PREFLIGHT, cwd=cwd_ensaio)
    except subprocess.TimeoutExpired:
        shutil.rmtree(staging, ignore_errors=True)
        return (f"NOK O ensaio de importação passou de {int(TETO_PREFLIGHT)}s; "
                "não apliquei nada (a Emily atual segue intacta).")

    # Lê e LIMPA o resultado por arquivo (só existe se o ensaio o gravou).
    falhas_ensaio: List[str] = []
    try:
        bruto = json.loads(resultado_ensaio.read_text(encoding="utf-8"))
        falhas_ensaio = [str(x) for x in (bruto.get("falhas") or [])]
    except (OSError, json.JSONDecodeError):
        pass
    try:
        resultado_ensaio.unlink()
    except OSError:
        pass

    if ensaio.returncode != 0:
        shutil.rmtree(staging, ignore_errors=True)
        # Prefere o resultado do arquivo; pipe vazio não é mais sinônimo de
        # "sem detalhes".
        detalhes: List[str] = falhas_ensaio
        if not detalhes:
            linhas = (ensaio.stdout or ensaio.stderr or "").strip().splitlines()
            detalhes = linhas[-3:] if linhas else []
        if not detalhes:
            detalhes = ["sem detalhes"]
        cauda = " · ".join(detalhes[:2])[:220]
        return ("Não apliquei: essa atualização precisa de RECOMPILAÇÃO "
                f"(provável biblioteca nova no projeto). Detalhes: {cauda}")

    # 4) Backup do que já existia (o "Desfazer" restaura exatamente isto).
    backup = internal / _BACKUP
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True)
    arquivos_aplicados: List[Dict[str, str]] = []
    for rel, alvo in pendentes:
        entrada = {"relativo": rel,
                   "antes": "existe" if alvo.exists() else "novo"}
        if alvo.exists():
            _copiar_com_pastas(alvo, backup / rel)
        arquivos_aplicados.append(entrada)

    # 5) Aplica de verdade e limpa o ensaio.
    for rel, _alvo in pendentes:
        origem_item = staging / rel
        destino_item = internal / rel
        if origem_item.exists():
            _copiar_com_pastas(origem_item, destino_item)
        else:  # removido da origem: o override fantasma sai de cena
            try:
                destino_item.unlink()
            except OSError:
                pass
    shutil.rmtree(staging, ignore_errors=True)

    agora = time.strftime("%d/%m %H:%M")
    _gravar_manifesto({
        "quando": time.time(),
        "quando_legivel": agora,
        "origem": str(origem),
        "arquivos": arquivos_aplicados,
        "main_mudou": estado["main_mudou"],
    })
    total = len(arquivos_aplicados)
    _log(f"atualização aplicada ({total} arquivo(s)) — reiniciando")
    aviso = (" (main.py também mudou: este pacote antigo precisa de uma última "
             "recompilação para passar a atualizá-lo pelo botão.)"
             if estado["main_mudou"] else "")
    if reiniciar:
        threading.Timer(2.0, _reiniciar).start()
    return (f"OK Atualização aplicada: {total} arquivo(s). "
            f"A Emily vai reiniciar agora.{aviso}")


def desfazer_atualizacao(reiniciar: bool = True) -> str:
    """Volta ao estado anterior: restaura backups e remove overrides novos."""
    internal = _caminho_internal()
    manifesto = _ler_manifesto()
    arquivos = manifesto.get("arquivos") or []
    if not internal or not arquivos:
        return "Não há atualização pra desfazer."
    backup = internal / _BACKUP
    restaurados = 0
    for entrada in arquivos:
        rel = entrada.get("relativo", "")
        if not rel:
            continue
        alvo = internal / rel
        era_novo = entrada.get("antes") == "novo"
        salvo = backup / rel
        if era_novo or not salvo.exists():
            try:
                alvo.unlink()
            except OSError:
                pass
        elif salvo.exists():
            _copiar_com_pastas(salvo, alvo)
        restaurados += 1
    try:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        manifest = _manifesto_path()
        if manifest and manifest.exists():
            manifest.unlink()
    except OSError:
        pass
    _log(f"atualização desfeita ({restaurados} arquivo(s))")
    if reiniciar:
        threading.Timer(2.0, _reiniciar).start()
    return (f"OK Desfeito: {restaurados} arquivo(s) voltaram. "
            f"A Emily vai reiniciar agora.")


def _reiniciar() -> None:
    """Reinicia a Emily: substitui o processo inteiro, sem vestígio."""
    _log("reiniciando o processo…")
    # O execv herda o ambiente. As variáveis EMILY_PROVEDOR_* vêm do .env (que
    # esta atualização pode ter trocado) e load_dotenv não sobrescreve o que já
    # existe: sem isto, a Emily reabria com o provedor e os modelos da execução
    # anterior (10/10/2026: seletor vazio depois de trocar o Codex pelo Kiro).
    for _nome in [n for n in os.environ if n.startswith("EMILY_PROVEDOR_")]:
        os.environ.pop(_nome, None)
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv[1:])
    except OSError as e:
        _log(f"não consegui reiniciar sozinha ({e}); feche e abra de novo")

