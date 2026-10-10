"""Busca de jogos, apps e pastas pelos discos do PC (ferramenta procurar_no_pc).

Saiu de ferramentas.py, que re-exporta _procurar_no_pc. O log mantém o
prefixo [FERRAMENTAS] de antes.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional


def _log(msg: str) -> None:
    print(f"[FERRAMENTAS] {msg}")


# Quantos candidatos devolver. Poucos pra não inflar o contexto, o bastante pra
# o modelo desambiguar "Elden Ring" de "Elden Ring Nightreign".
_MAX_CANDIDATOS = 8


# Profundidade da varredura por drive. Pasta de jogo raramente passa disso, e
# cada nível a mais multiplica o tempo.
_PROFUNDIDADE_VARREDURA = 4


# Nota que conta como acerto exato: o nome da pasta é igual ao que foi pedido.
# Abaixo disso vale varrer os discos, porque pode existir algo melhor.
_NOTA_EXATA = 0.95


# Teto de tempo da varredura de discos. Isso roda dentro de um turno de
# conversa; passar disso deixaria a Emily muda esperando o disco girar.
_SEGUNDOS_MAX_VARREDURA = float(os.getenv("EMILY_SEGUNDOS_BUSCA", "25"))


_PASTAS_IGNORADAS = {
    "windows", "system32", "syswow64", "winsxs", "$recycle.bin",
    "system volume information", "recovery", "perflogs", "boot",
    "appdata", "programdata", "node_modules", ".git", "__pycache__",
}


def _tokens_significativos(nome: str) -> List[str]:
    import automacao
    return [t for t in automacao._normalizar_nome_app(nome).split() if len(t) > 2]


def _pontuar_candidata(nome_buscado: str, nome_pasta: str) -> float:
    """
    Quão bem o nome da pasta atende o que foi pedido. 0 = descartar.

    Isso é deliberadamente mais rígido que o _combina do automacao. Lá a
    permissividade faz sentido: "abre o Elden Ring" é melhor abrir algo perto do
    que não abrir nada, e o Vitor vê o resultado na hora. Aqui não: a resposta
    vira uma afirmação da Emily ("achei em tal lugar"), então um falso positivo
    é uma mentira. Medido com a versão permissiva: procurar
    "zzzz_pasta_que_nao_existe_9999" devolvia uma pasta de curso de musculação.
    """
    import automacao

    alvo = automacao._normalizar_nome_app(nome_buscado)
    pasta = automacao._normalizar_nome_app(nome_pasta)
    if not alvo or not pasta:
        return 0.0

    if alvo == pasta:
        return 1.0

    tokens = _tokens_significativos(nome_buscado)
    # Exige que TODOS os termos pedidos apareçam. É o que separa acerto de
    # coincidência de letras.
    if tokens and all(t in pasta for t in tokens):
        # Nome mais curto é mais provável de ser exatamente o pedido: entre
        # "ELDEN RING" e "ELDEN RING NIGHTREIGN", o primeiro ganha.
        return 0.9 - min(0.35, (len(pasta) - len(alvo)) / 200.0)

    if alvo in pasta:
        return 0.7

    # O contrário — nome da pasta contido no que foi pedido — só vale se a
    # pasta representar boa parte do pedido. Sem essa trava, procurar
    # "zzzz_pasta_que_nao_existe_9999" casava com uma pasta chamada "ta",
    # porque "ta" está dentro de "pasta". Medido: devolvia 8 pastas de
    # tradução do VidHelper como se fossem o que o Vitor procurava.
    if pasta in alvo and len(pasta) >= max(4, len(alvo) * 0.6):
        return 0.7

    # Similaridade sozinha só vale se for realmente alta.
    sim = automacao._similaridade(alvo, pasta)
    return sim if sim >= 0.85 else 0.0


def _todos_os_drives() -> List[Path]:
    import automacao

    caminhos, vistos = [], set()
    for chave, caminho in automacao.DRIVE_MAP.items():
        if chave in automacao.DRIVES_BLOQUEADOS or str(caminho) in vistos:
            continue
        vistos.add(str(caminho))
        caminhos.append(caminho)
    return caminhos


def _drives_para_procurar(drive: Optional[str]):
    """
    Ordem em que os drives serão varridos. Devolve (lista_de_caminhos, erro).

    O drive pedido vira PRIORIDADE, não restrição: procura nele primeiro e
    continua nos outros se não achar. Isso importa porque o palpite costuma
    estar errado — medido, o Vitor disse "não é a C nem a E", o modelo chutou
    drive="D" e a pasta estava no H. Restringindo, a resposta teria sido "não
    achei" com a pasta existindo.
    """
    import automacao

    todos = _todos_os_drives()
    if not (drive and str(drive).strip()):
        return todos, None

    chave = str(drive).strip().lower().rstrip(":/\\")
    if chave in automacao.DRIVES_BLOQUEADOS:
        return [], f"Não posso mexer no drive {drive}."
    preferido = (automacao.DRIVE_MAP.get(chave)
                 or automacao.DRIVE_MAP.get(f"{chave}:"))
    if preferido is None:
        conhecidos = ", ".join(str(p) for p in todos)
        return [], (f"Não conheço o drive '{drive}'. Os que eu conheço: "
                    f"{conhecidos}. Pergunte ao Vitor qual é.")

    resto = [p for p in todos if str(p) != str(preferido)]
    return [preferido] + resto, None


def _candidatas_nos_launchers(nome: str) -> List[tuple]:
    """Pastas de jogo conhecidas pela Steam, Epic e GOG."""
    import automacao

    achadas = []
    try:
        for biblioteca in automacao._get_steam_libraries():
            try:
                for pasta in biblioteca.iterdir():
                    if not pasta.is_dir():
                        continue
                    nota = _pontuar_candidata(nome, pasta.name)
                    if nota > 0:
                        achadas.append((nota, pasta))
            except (OSError, PermissionError):
                continue
    except Exception as e:
        _log(f"varredura da Steam falhou: {e}")

    manifests = Path("C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests")
    if manifests.exists():
        try:
            for item in manifests.glob("*.item"):
                try:
                    dados = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
                local = dados.get("InstallLocation", "")
                exibicao = dados.get("DisplayName", "")
                if not local:
                    continue
                nota = max(_pontuar_candidata(nome, exibicao or ""),
                           _pontuar_candidata(nome, Path(local).name))
                if nota > 0 and Path(local).is_dir():
                    achadas.append((nota, Path(local)))
        except (OSError, PermissionError):
            pass

    return achadas


def _candidatas_no_drive(nome: str, raiz: Path, prazo: float) -> List[tuple]:
    """
    Varredura larga num drive, com profundidade e tempo limitados.

    O prazo existe porque isso roda dentro de um turno de conversa: se a
    varredura demorar, a Emily fica muda esperando o disco.
    """
    import automacao

    achadas = []

    def _andar(pasta: Path, profundidade: int) -> None:
        if profundidade == 0 or len(achadas) >= _MAX_CANDIDATOS * 3:
            return
        if time.monotonic() > prazo:
            return
        try:
            for sub in pasta.iterdir():
                try:
                    if not sub.is_dir():
                        continue
                except OSError:
                    continue
                if automacao._normalizar(sub.name) in _PASTAS_IGNORADAS:
                    continue
                nota = _pontuar_candidata(nome, sub.name)
                if nota > 0:
                    achadas.append((nota, sub))
                    # Achou: não desce mais nessa pasta, o que interessa é ela.
                    continue
                _andar(sub, profundidade - 1)
                if time.monotonic() > prazo:
                    return
        except (OSError, PermissionError):
            return

    _andar(raiz, _PROFUNDIDADE_VARREDURA)
    return achadas


def _procurar_no_pc(nome: str, drive: Optional[str] = None) -> str:
    """
    Descobre ONDE uma pasta está, sem abrir nada.

    Essa ferramenta existe porque faltava a capacidade inteira: o automacao já
    sabia varrer Steam, Epic, GOG, registro do Windows e Program Files, mas
    nada disso estava exposto ao tool calling. Quando o Vitor perguntou "não tô
    achando a pasta do Elden Ring, você acha pra mim?", o modelo não tinha
    ferramenta de busca e caiu no comando_do_pc, que escalou pro agente
    visual — que ficou clicando na tela às cegas.

    Devolve uma LISTA de candidatas em vez de um chute único, porque a
    desambiguação é do modelo: ele sabe que "Elden Ring sem ser o Nightreign"
    quer a pasta "ELDEN RING" e não a "ELDEN RING NIGHTREIGN". Com resposta
    única a ferramenta escolhia a errada e a Emily afirmava com convicção.
    """
    if not nome or not nome.strip():
        return "Preciso do nome da pasta ou do jogo pra procurar."
    nome = nome.strip()

    drives_alvo, erro = _drives_para_procurar(drive)
    if erro:
        return erro

    achadas = _candidatas_nos_launchers(nome)
    melhor = max((nota for nota, _ in achadas), default=0.0)

    # Varre os drives quando os launchers não deram NADA ou não deram um acerto
    # exato.
    #
    # A versão anterior pulava a varredura sempre que os launchers achassem
    # qualquer coisa, e isso deu errado exatamente no caso do Vitor: procurando
    # "Elden Ring", a Steam só tinha "ELDEN RING NIGHTREIGN" (nota 0,9, não
    # exata), a busca parava ali e devolvia o jogo errado — justo o que ele
    # havia excluído. A pasta certa estava em outro disco e nunca era vista.
    tentados = []
    if melhor < _NOTA_EXATA:
        prazo = time.monotonic() + _SEGUNDOS_MAX_VARREDURA
        for raiz in drives_alvo:
            try:
                if not raiz.exists():
                    continue
            except OSError:
                continue
            if time.monotonic() > prazo:
                _log("prazo da varredura estourou, parando por aqui")
                break
            tentados.append(str(raiz))
            _log(f"varrendo {raiz} procurando {nome!r}")
            achadas.extend(_candidatas_no_drive(nome, raiz, prazo))

    if not achadas:
        onde = f" Procurei nos launchers e em: {', '.join(tentados)}." if tentados else ""
        return (f"Não achei nenhuma pasta chamada '{nome}'.{onde} "
                f"Não invente um caminho: pergunte ao Vitor se o nome está "
                f"certo ou em que drive ele acha que está.")

    # Ordena por nota e tira caminho repetido.
    achadas.sort(key=lambda par: (-par[0], len(str(par[1]))))
    unicas, vistos = [], set()
    for nota, caminho in achadas:
        chave = str(caminho).lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        unicas.append((nota, caminho))
        if len(unicas) >= _MAX_CANDIDATOS:
            break

    if len(unicas) == 1:
        return f"Encontrei em: {unicas[0][1]}"

    linhas = "\n".join(f"- {caminho}" for _, caminho in unicas)
    return (f"Achei {len(unicas)} pastas que batem com '{nome}':\n{linhas}\n"
            f"Escolha a que corresponde ao que o Vitor pediu e diga o caminho "
            f"a ele. Se nenhuma servir, diga que não achou.")
