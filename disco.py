"""
disco.py — varredura precisa de espaço em disco.

Por que este módulo existe
──────────────────────────
A Emily sabia achar UMA pasta (procurar_no_pc), mas não sabia responder "o que
está enchendo o disco?". E as ferramentas de armazenamento do Windows escondem
o que importa: o espaço que o sistema aloca — hiberfil, pagefile, pontos de
restauração em System Volume Information, cópias de sombra — não aparece num
Explorer comum, e é justamente onde mora o vilão invisível.

O que este módulo faz que o Explorer não faz de forma clara
───────────────────────────────────────────────────────────
1. Varre a árvore somando o tamanho REAL de cada pasta e arquivo, SEM pular os
   ocultos e SEM seguir junction/symlink (que causaria contagem dupla e laço).
2. Fecha a conta contra o espaço usado DE VERDADE do volume e NOMEIA o que a
   varredura não conseguiu medir — arquivos de sistema e pastas sem permissão.
   É o "não deixar passar o vilão escondido".

Nada aqui apaga sozinho. A varredura é só leitura. A limpeza (limpar) tem um
modo de PRÉVIA por padrão e só mexe no que é universalmente seguro.
"""

from __future__ import annotations

import heapq
import os
import shutil
import stat
import time
from typing import List, Optional, Tuple

# Atributo de reparse point (junction/symlink) no Windows. Pular esses é o que
# evita contar C:\Users\All Users (junction pra ProgramData) duas vezes e um
# laço infinito.
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

# Arquivos de sistema no raiz que valem nomear: são grandes, ocultos, e o Vitor
# não vê no Explorer. A varredura MEDE eles (scandir enxerga oculto), mas o
# relatório os separa porque eles se apagam de outro jeito, não na mão.
_SISTEMA = {
    "hiberfil.sys": "hibernação (desliga com: powercfg /h off)",
    "pagefile.sys": "memória virtual do Windows",
    "swapfile.sys": "memória virtual de apps da Store",
}

# Notas para pastas conhecidas que aparecem grandes mas NÃO se limpa na mão.
# A chave é comparada pelo fim do caminho (case-insensitive).
_NOTA_PASTA = {
    r"\windows\winsxs": "componentes do Windows; encolhe com "
                        "'Dism /Online /Cleanup-Image /StartComponentCleanup' (admin). "
                        "Parte é hardlink e ocupa menos disco do que parece",
    r"\windows\installer": "restos de instaladores do Windows; não apague na mão",
    r"\windows\softwaredistribution": "cache do Windows Update; pode limpar parando o serviço",
    r"\system volume information": "pontos de restauração e cópias de sombra (precisa de admin)",
}


def _nota_pasta(caminho: str) -> str:
    c = caminho.lower().rstrip("\\")
    for fim, nota in _NOTA_PASTA.items():
        if c.endswith(fim):
            return nota
    return ""


def _humano(n: int) -> str:
    """Bytes em tamanho legível, à moda brasileira (vírgula decimal)."""
    n = float(max(0, n))
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidade == "TB":
            txt = f"{n:.1f}".rstrip("0").rstrip(".") if unidade != "B" else f"{int(n)}"
            return f"{txt.replace('.', ',')} {unidade}"
        n /= 1024
    return f"{n:.1f} TB"


def _raiz(drive: str) -> str:
    """Normaliza 'C', 'c:', 'C:/' etc. para 'C:\\'."""
    d = (drive or "C").strip().strip('"').strip("\\/").rstrip(":")
    if not d:
        d = "C"
    return f"{d[0].upper()}:\\"


def _eh_reparse(entry: os.DirEntry) -> bool:
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & _REPARSE)
    except OSError:
        return False


def _pontos_pesados(pares: List[Tuple[int, str]], usado: int,
                    quantos: int) -> List[Tuple[int, str]]:
    """
    Dos folders medidos, os 'pontos que concentram espaço' — o lugar EXATO.

    Sem isto, a lista viraria C:\\, C:\\Users, C:\\Users\\x, ... a mesma coisa
    aninhada, cada nível repetindo o de cima. A regra: entre os folders grandes
    (acima de ~1% do usado), fica só quem NÃO tem um descendente também grande.
    Ou seja, desce até onde o espaço para de se concentrar e mostra ESSE ponto —
    "C:\\Users\\x\\AppData\\Local\\Docker — 40 GB", não o C:\\Users genérico.
    """
    limiar = max(500 * 1024**2, int(usado * 0.01))
    grandes = [(t, p) for t, p in pares if t >= limiar]
    caminhos = {p.rstrip("\\") + "\\" for _, p in grandes}
    folhas = []
    for t, p in grandes:
        pp = p.rstrip("\\") + "\\"
        tem_descendente_grande = any(o != pp and o.startswith(pp) for o in caminhos)
        if not tem_descendente_grande:
            folhas.append((t, p))
    return sorted(folhas, key=lambda x: -x[0])[:quantos]


def analisar(drive: str = "C", mostrar: int = 10) -> str:
    """
    Varre um drive e devolve um relatório do que está ocupando espaço.

    Só leitura. Segura contra o disco inteiro: pula reparse points, engole erro
    de permissão contando quantas pastas negaram acesso, e fecha a conta contra
    o espaço usado real do volume.
    """
    raiz = _raiz(drive)
    if not os.path.isdir(raiz):
        return (f"O drive {raiz} não existe ou não está acessível. "
                f"Me diga qual letra (C, D, ...) você quer que eu analise.")

    try:
        total, usado, livre = shutil.disk_usage(raiz)
    except OSError as e:
        return f"Não consegui ler o espaço do drive {raiz}: {e}"

    arquivos: List[Tuple[int, str]] = []   # min-heap dos maiores arquivos
    pastas: List[Tuple[int, str]] = []     # min-heap dos maiores folders
    topo: List[Tuple[int, str]] = []       # filhos diretos do raiz
    negados = [0]                          # pastas que negaram acesso
    N_ARQ, N_PASTA = 60, 250

    def _push(heaplist, size, path, limite):
        if size <= 0:
            return
        if len(heaplist) < limite:
            heapq.heappush(heaplist, (size, path))
        elif size > heaplist[0][0]:
            heapq.heapreplace(heaplist, (size, path))

    def _medir(caminho: str, prof: int) -> int:
        soma = 0
        try:
            it = os.scandir(caminho)
        except OSError:
            negados[0] += 1
            return 0
        with it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if _eh_reparse(entry):
                            continue
                        sub = _medir(entry.path, prof + 1)
                        soma += sub
                        _push(pastas, sub, entry.path, N_PASTA)
                        if prof == 0:
                            topo.append((sub, entry.name))
                    else:
                        try:
                            sz = entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
                        soma += sz
                        _push(arquivos, sz, entry.path, N_ARQ)
                        if prof == 0:
                            topo.append((sz, entry.name))
                except OSError:
                    negados[0] += 1
        return soma

    inicio = time.monotonic()
    varrido = _medir(raiz, 0)
    decorrido = time.monotonic() - inicio

    return _relatorio(raiz, total, usado, livre, varrido, decorrido,
                      arquivos, pastas, topo, negados[0], mostrar)


def _relatorio(raiz, total, usado, livre, varrido, decorrido,
               arquivos, pastas, topo, negados, mostrar) -> str:
    L: List[str] = []
    pct = (usado / total * 100) if total else 0
    L.append(f"Disco {raiz[:2]} — {_humano(total)} no total, "
             f"{_humano(usado)} usados ({pct:.0f}%), {_humano(livre)} livres.")
    if livre < 10 * 1024**3:
        L.append("⚠ Está apertado — menos de 10 GB livres.")

    # Panorama: os filhos diretos do raiz, do maior pro menor.
    L.append("\nOnde o espaço está (nível de cima):")
    for tam, nome in sorted(topo, key=lambda p: -p[0])[:mostrar]:
        if tam <= 0:
            continue
        nota = ""
        chave = nome.lower()
        if chave in _SISTEMA:
            nota = f"  ← {_SISTEMA[chave]}"
        L.append(f"  {_humano(tam):>10}  {nome}{nota}")

    # Pontos pesados fundo na árvore (o lugar exato onde o espaço concentra).
    pesados = _pontos_pesados(pastas, usado, mostrar)
    if pesados:
        L.append("\nPastas que concentram espaço (o ponto exato):")
        for tam, caminho in pesados:
            nota = _nota_pasta(caminho)
            sufixo = f"  ← {nota}" if nota else ""
            L.append(f"  {_humano(tam):>10}  {caminho}{sufixo}")

    if arquivos:
        L.append("\nMaiores arquivos:")
        for tam, caminho in sorted(arquivos, key=lambda p: -p[0])[:mostrar]:
            L.append(f"  {_humano(tam):>10}  {caminho}")

    # A conta que o Explorer não fecha: o que a varredura NÃO conseguiu medir.
    nao_medido = max(0, usado - varrido)
    L.append(f"\nA varredura mediu {_humano(varrido)} somando arquivo por arquivo.")
    if nao_medido > 512 * 1024**2:   # mediu MENOS que o usado: falta espaço escondido
        L.append(
            f"Sobraram {_humano(nao_medido)} que ela não vê item por item: é "
            "espaço que o Windows reserva e esconde — pontos de restauração "
            "(System Volume Information), cópias de sombra do sistema, e "
            f"arquivos travados/sem permissão ({negados} pasta(s) negaram "
            "acesso). Pra medir e mexer nisso precisa rodar como administrador "
            "(pontos de restauração se veem com 'vssadmin list shadowstorage')."
        )
    elif varrido > usado * 1.03:     # mediu MAIS que o usado: hardlinks
        L.append(
            "Medi mais do que o total usado porque o Windows usa HARDLINKS: o "
            "WinSxS e outras pastas de sistema apontam pros MESMOS arquivos, "
            "então aparecem somando o tamanho mas ocupam bem menos disco do que "
            f"parece. {negados} pasta(s) de sistema negaram acesso."
        )
    elif negados:
        L.append(f"({negados} pasta(s) de sistema negaram acesso; o resto "
                 "está todo contabilizado.)")

    L.append(f"\nVarredura levou {decorrido:.0f}s.")
    return "\n".join(L)


# ═════════════════════════════════════════════════════════════════
# LIMPEZA SEGURA
#
# Só mexe no que é UNIVERSALMENTE seguro apagar: as pastas de temporários e a
# lixeira. Nada de SoftwareDistribution, WinSxS, pontos de restauração — isso
# pode quebrar update/rollback e exige admin/DISM; a Emily NÃO faz por conta.
#
# Por padrão é PRÉVIA: só mede quanto dá pra liberar. Só apaga com confirmar=
# True, e mesmo assim engole arquivo travado (o que está em uso não vai).
# ═════════════════════════════════════════════════════════════════

def _alvos_temp() -> List[Tuple[str, str]]:
    alvos = []
    tmp = os.environ.get("TEMP") or os.environ.get("TMP")
    if tmp:
        alvos.append((tmp, "temporários do seu usuário"))
    win = os.environ.get("SystemRoot", r"C:\Windows")
    alvos.append((os.path.join(win, "Temp"), "temporários do Windows"))
    return [(p, rot) for p, rot in alvos if os.path.isdir(p)]


def _tamanho_de(caminho: str) -> int:
    soma = 0
    for base, _dirs, arqs in os.walk(caminho):
        for a in arqs:
            try:
                soma += os.path.getsize(os.path.join(base, a))
            except OSError:
                pass
    return soma


def _tamanho_lixeira() -> int:
    total = 0
    for letra in "CDEFGH":
        p = f"{letra}:\\$Recycle.Bin"
        if os.path.isdir(p):
            try:
                total += _tamanho_de(p)
            except OSError:
                pass
    return total


def _esvaziar_pasta(caminho: str) -> Tuple[int, int]:
    """Apaga o CONTEÚDO da pasta (não ela). Devolve (bytes_liberados, travados)."""
    liberado = travados = 0
    try:
        entradas = list(os.scandir(caminho))
    except OSError:
        return 0, 0
    for entry in entradas:
        try:
            if entry.is_dir(follow_symlinks=False):
                tam = _tamanho_de(entry.path)
                shutil.rmtree(entry.path, ignore_errors=False)
                liberado += tam
            else:
                tam = entry.stat(follow_symlinks=False).st_size
                os.remove(entry.path)
                liberado += tam
        except OSError:
            travados += 1
    return liberado, travados


def _esvaziar_lixeira() -> bool:
    try:
        import ctypes
        # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x01 | 0x02 | 0x04)
        return True
    except Exception:
        return False


def limpar(confirmar: bool = False) -> str:
    """
    Libera espaço dos temporários e da lixeira.

    confirmar=False (padrão): só mede e diz quanto dá pra liberar. É a prévia,
    pra o Vitor decidir. confirmar=True: apaga de verdade.
    """
    alvos = _alvos_temp()
    lixeira = _tamanho_lixeira()

    if not confirmar:
        L = ["Prévia — dá pra liberar sem risco (nada foi apagado ainda):"]
        total = 0
        for caminho, rot in alvos:
            t = _tamanho_de(caminho)
            total += t
            L.append(f"  {_humano(t):>10}  {rot}")
        L.append(f"  {_humano(lixeira):>10}  lixeira")
        total += lixeira
        L.append(f"\nTotal: cerca de {_humano(total)}. "
                 "Quer que eu limpe? (só isso é seguro; pontos de restauração e "
                 "arquivos de sistema eu não mexo sozinha.)")
        return "\n".join(L)

    L = ["Limpei:"]
    total = travados_tot = 0
    for caminho, rot in alvos:
        liberado, travados = _esvaziar_pasta(caminho)
        total += liberado
        travados_tot += travados
        L.append(f"  {_humano(liberado):>10}  {rot}")
    if _esvaziar_lixeira():
        total += lixeira
        L.append(f"  {_humano(lixeira):>10}  lixeira")
    L.append(f"\nLiberei cerca de {_humano(total)}.")
    if travados_tot:
        L.append(f"({travados_tot} arquivo(s) estavam em uso e ficaram — "
                 "reinicie e rode de novo se quiser pegar eles.)")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    print(analisar(sys.argv[1] if len(sys.argv) > 1 else "C"))



