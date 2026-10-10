"""
tela_stream.py — a tela do PC vista pelo celular.

TERRENO (medido nesta máquina, KDE Plasma 6.7 no Wayland):
  • mss (o capturador do visao.py) só enxerga XWayland: enumera os monitores
    direitinho (geometria e nomes) mas os pixels vêm PRETOS. Serve pra
    geometria, não serve pra imagem.
  • org.kde.KWin.ScreenShot2 por D-Bus: o KWin nega a processos quaisquer
    ("The process is not authorized") — só spectacle e o portal são autorizados.
  • spectacle -b -n -f -o arquivo.jpg: 1,1–1,7s por quadro, JPEG de 5632×2048
    (a mesa inteira, nos DOIS monitores, em pixels físicos).
  • xdg-desktop-portal Screenshot: não responde sem alguém clicando na tela.

Então a cadência realista aqui é ~1 quadro por segundo, e ela vem do
spectacle. O desenho que faz isso prestável:

    thread de captura (só vive enquanto tem gente olhando)
        spectacle → JPEG da mesa inteira → _ULTIMA (com trava)
    rota /tela/jpg?monitor=N
        recorta o monitor N da última captura (geometria lógica do mss ×
        escala física medida no próprio frame) → redimensiona → JPEG
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import threading
import time

import mss
from PIL import Image

# Cadência do spectacle e quanto tempo a thread vive sem ninguém olhando.
INTERVALO_CAPTURA = float(os.getenv("EMILY_TELA_INTERVALO", "1.15"))
VIDA_SEM_ESPECTADOR = float(os.getenv("EMILY_TELA_VIDA", "45"))

_PASTA = os.path.join(os.getenv("TMPDIR", "/tmp"), "emily_tela_stream")
os.makedirs(_PASTA, exist_ok=True)

_ULTIMA: dict = {"img": None, "w": 0, "h": 0, "ts": 0.0}
_TRAVA = threading.Lock()
_TRAVA_DEMANDA = threading.Lock()
# Serializa as chamadas do spectacle. Dois em paralelo não existem: o KDE só
# permite uma captura por vez e o segundo processo sai rc=0 SEM escrever nada —
# foi exatamente isso que a primeira versão desta função fazia, porque o laço
# da thread e a captura em linha da primeira demanda disputavam o spectacle.
_TRAVA_CAPTURA = threading.Lock()
_TRAVA_PONTUAL = threading.Lock()
_ultima_demanda = 0.0
_thread: threading.Thread | None = None
_ultimo_erro = ""
_aviso_erro_dado = False


def _capturar_uma_vez() -> Image.Image:
    """Um passe do spectacle: mesa inteira (todos os monitores), pixels físicos."""
    destino = os.path.join(_PASTA, f"quadro_{os.getpid()}_{threading.get_ident()}.jpg")
    with _TRAVA_CAPTURA:
        r = subprocess.run(
            ["spectacle", "-b", "-n", "-f", "-o", destino],
            capture_output=True, text=True, timeout=25)
        try:
            if r.returncode != 0 or not os.path.exists(destino):
                detalhe = (r.stderr or r.stdout or "")[:140].replace("\n", " ")
                raise RuntimeError(f"spectacle rc={r.returncode}: {detalhe}")
            with open(destino, "rb") as f:
                dados = f.read()
            return Image.open(io.BytesIO(dados))
        finally:
            try:
                os.remove(destino)
            except OSError:
                pass


def _loop() -> None:
    global _thread, _ultimo_erro
    while time.time() - _ultima_demanda < VIDA_SEM_ESPECTADOR:
        t0 = time.time()
        try:
            imagem = _capturar_uma_vez()
            with _TRAVA:
                _ULTIMA["img"] = imagem
                _ULTIMA["w"] = imagem.width
                _ULTIMA["h"] = imagem.height
                _ULTIMA["ts"] = time.time()
            _ultimo_erro = ""
        except Exception as e:  # noqa: BLE001
            _ultimo_erro = f"{type(e).__name__}: {e}"
        # O tempo que o spectacle levou já é a maior parte do intervalo.
        time.sleep(max(0.15, INTERVALO_CAPTURA - (time.time() - t0)))
    _thread = None


def _garantir_loop() -> None:
    global _thread, _ultima_demanda
    with _TRAVA_DEMANDA:
        _ultima_demanda = time.time()
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, name="tela-stream", daemon=True)
            _thread.start()


def _demandar() -> None:
    global _ultima_demanda
    with _TRAVA_DEMANDA:
        _ultima_demanda = time.time()


def _geometria() -> tuple[dict, list[dict]]:
    with mss.mss() as sct:
        mons = list(sct.monitors)
    return mons[0], mons[1:]  # [0] é a área virtual somada, não um monitor
def _nomes_kscreen() -> list[dict]:
    """Nome + modo atual de cada saída, do kscreen-doctor (sem códigos ANSI)."""
    try:
        r = subprocess.run(["kscreen-doctor", "-o"], capture_output=True,
                           text=True, timeout=10)
        limpo = re.sub(r"\x1b\[[0-9;]*m", "", r.stdout)
        saidas: list[dict] = []
        atual: dict | None = None
        for linha in limpo.splitlines():
            m = re.match(r".*Output:\s*\d+\s+(\S+)", linha)
            if m:
                atual = {"nome": m.group(1)}
                saidas.append(atual)
                continue
            if atual is not None:
                mm = re.search(r"(\d+)x(\d+)@\d+\.\d+\*", linha)
                if mm:
                    atual["largura"], atual["altura"] = int(mm.group(1)), int(mm.group(2))
        return saidas
    except Exception:
        return []


def listar_monitores() -> list[dict]:
    """Monitores na ordem HUMANA (esquerda→direita), com nome quando possível."""
    _, mons = _geometria()
    ks = _nomes_kscreen()
    usados: set[int] = set()
    lista = []
    for m in mons:
        nome = None
        for j, saida in enumerate(ks):
            if j in usados:
                continue
            if saida.get("largura") == m["width"] and saida.get("altura") == m["height"]:
                nome = saida["nome"]
                usados.add(j)
                break
        lista.append({"nome": nome, "left": m["left"], "top": m["top"],
                      "largura": m["width"], "altura": m["height"]})
    # Ordem humana: esquerda→direita; o número humano é atribuído DEPOIS da
    # ordenação — é a mesma lição que o visao.py já aprendeu com o mss.
    lista.sort(key=lambda item: (item["left"], item["top"]))
    for i, item in enumerate(lista, 1):
        item["indice"] = i
        item["nome"] = (f"Monitor {i} · {item['nome']}" if item["nome"]
                        else f"Monitor {i}")
    return lista


def capturar_jpeg(monitor: int = 1, largura: int = 900,
                  qualidade: int = 62, unico: bool = False) -> tuple[bytes, float]:
    """
    JPEG do monitor [monitor] (ordem humana). Devolve (bytes, idade_da_captura).
    Levanta ValueError/RuntimeError com mensagem curta quando não deu.
    """
    if unico:
        # Ferramentas pontuais (inclusive o monitoramento Android) não mantêm
        # um espectador artificial por 45 s. Reutiliza o mesmo quadro da mesa
        # para os vários monitores consultados numa única verificação.
        with _TRAVA_PONTUAL:
            with _TRAVA:
                imagem = _ULTIMA["img"]
                w_fis, h_fis, ts = _ULTIMA["w"], _ULTIMA["h"], _ULTIMA["ts"]
            if imagem is None or time.time() - ts > 8.0:
                imagem = _capturar_uma_vez()
                w_fis, h_fis, ts = imagem.width, imagem.height, time.time()
                with _TRAVA:
                    _ULTIMA.update(img=imagem, w=w_fis, h=h_fis, ts=ts)
    else:
        _demandar()
        _garantir_loop()
        with _TRAVA:
            imagem = _ULTIMA["img"]
            w_fis, h_fis, ts = _ULTIMA["w"], _ULTIMA["h"], _ULTIMA["ts"]

    if imagem is None:
        # Primeira demanda da sessão: a thread já foi despertada pelo
        # _garantir_loop e está capturando — esperar o quadro dela em vez de
        # disparar um spectacle concorrente (o segundo sai rc=0 sem arquivo).
        limite = time.time() + 6.0
        while imagem is None and time.time() < limite:
            time.sleep(0.25)
            with _TRAVA:
                imagem = _ULTIMA["img"]
                w_fis, h_fis, ts = _ULTIMA["w"], _ULTIMA["h"], _ULTIMA["ts"]
        if imagem is None:
            # A thread não entregou (ex.: spectacle travado) — tenta em linha,
            # agora protegido pela trava de captura.
            imagem = _capturar_uma_vez()
            w_fis, h_fis, ts = imagem.width, imagem.height, time.time()
            with _TRAVA:
                _ULTIMA.update(img=imagem, w=w_fis, h=h_fis, ts=ts)

    virtual, mons = _geometria()
    if monitor < 1 or monitor > len(mons):
        raise ValueError(f"monitor {monitor} não existe (há {len(mons)})")
    m = mons[monitor - 1]

    # O frame é em pixels FÍSICOS; a geometria do mss é LÓGICA. A escala entre
    # os dois se mede no próprio frame (1.6 na mesa dele) — nunca chutar.
    escala = w_fis / float(virtual["width"]) if virtual["width"] else 1.0
    caixa = (int(m["left"] * escala), int(m["top"] * escala),
             int((m["left"] + m["width"]) * escala),
             int((m["top"] + m["height"]) * escala))
    caixa = (max(0, caixa[0]), max(0, caixa[1]),
             min(w_fis, caixa[2]), min(h_fis, caixa[3]))
    if caixa[2] <= caixa[0] or caixa[3] <= caixa[1]:
        raise RuntimeError(f"geometria vazia pro monitor {monitor}")

    recorte = imagem.crop(caixa)
    if recorte.width > largura:
        recorte = recorte.resize(
            (largura, max(1, int(recorte.height * largura / recorte.width))))
    buf = io.BytesIO()
    recorte.convert("RGB").save(buf, "JPEG", quality=qualidade, optimize=False)
    return buf.getvalue(), max(0.0, time.time() - ts)


def estado() -> dict:
    with _TRAVA:
        img, ts = _ULTIMA["img"], _ULTIMA["ts"]
    _, mons = _geometria()
    return {
        "capturando": _thread is not None and _thread.is_alive(),
        "tem_frame": img is not None,
        "idade": round(time.time() - ts, 1) if ts else None,
        "tamanho": f"{_ULTIMA['w']}x{_ULTIMA['h']}" if img else None,
        "monitores": len(mons),
        "ultimo_erro": _ultimo_erro or None,
    }
