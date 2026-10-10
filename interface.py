"""
interface.py — Emily AI · Painel de Controle Moderno (PyQt6)
Design: Dark glassmorphism, tema roxo/azul, bordas iluminadas

LEGADO: a instalação padrão usa interface_web.py. Este módulo existe somente
como fallback e para o modo explícito EMILY_UI=qt; novas funções da interface
principal devem ser implementadas na interface web.
"""

import os
import re
import sys
import json
import threading
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QTextEdit,
    QSizePolicy, QGridLayout, QGraphicsDropShadowEffect, QScrollBar,
    QStackedWidget,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QPoint, QEvent, QMimeData,
    QByteArray, QBuffer, QIODevice,
)
from PyQt6.QtWidgets import QFileIconProvider
from PyQt6.QtCore import QFileInfo
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QPainter, QPen, QBrush,
    QPainterPath, QIcon, QCursor, QDragEnterEvent, QDropEvent, QClipboard,
)

if getattr(sys, 'frozen', False):
    # PyInstaller --onedir: arquivos de dados ficam em _internal/ (sys._MEIPASS)
    DIR_BASE = sys._MEIPASS
else:
    DIR_BASE = os.path.dirname(os.path.abspath(__file__))

DIR_IMG = os.path.join(DIR_BASE, "img")

BG_MAIN      = "#080812"
BG_CARD      = "#0e0e1c"
BG_SIDEBAR   = "#0a0a17"
BG_INPUT     = "#111122"
BG_HEADER    = "#0d0d1f"
BG_CENTER    = "#0b0b18"
PURPLE       = "#7c4fff"
PURPLE_DK    = "#5a35c7"
PURPLE_LT    = "#a07eff"
PURPLE_DIM   = "#1a1340"
PURPLE_GLOW  = "#2d1a6e"
BORDER       = "#1a1a35"
BORDER_GLOW  = "#7c4fff"
# Linha estrutural (barra lateral | conversa, cabeçalho, rodapé do input).
# Separada do BORDER de propósito: #1a1a35 é bom pra contorno de cartão, que já
# tem fundo próprio pra se destacar, e some quando é só uma linha de 1px entre
# duas áreas quase da mesma cor. Era literalmente invisível na tela do Vitor.
DIVISOR      = "#2a2a50"
C_TEXT       = "#e8e8f8"
C_TEXT2      = "#8888aa"
C_TEXT3      = "#44445a"
C_GREEN      = "#3dd68c"
C_RED        = "#f4706a"
C_YELLOW     = "#f0b429"
C_CYAN       = "#5babf5"
C_BLUE       = "#4f8fff"
C_LILAC      = "#c197fc"
EMILY_BUB    = "#0f0f28"
USER_BUB     = "#1a1540"

STATUS_MAP = {
    "aguardando":   (C_GREEN,   "● Aguardando"),
    "ouvindo":      (C_GREEN,   "● Ouvindo..."),
    "gravando":     (C_RED,     "◉ Gravando..."),
    "falando":      (C_CYAN,    "● Falando..."),
    "monitorando":  (C_YELLOW,  "● Monitorando..."),
    "transferindo": (C_LILAC,   "● Transferindo..."),
    "abrindo_app":  (C_GREEN,   "● Abrindo..."),
    "pesquisando":  (C_CYAN,    "● Pesquisando..."),
    "gerando":      (C_LILAC,   "● Gerando imagem..."),
    "pensando":     (PURPLE_LT, "● Pensando..."),
}

STATUS_TO_DOT = {
    "aguardando": 0, "ouvindo": 1, "gravando": 1,
    "pensando": 2, "falando": 3, "monitorando": 3,
    "pesquisando": 2, "gerando": 2, "transferindo": 3,
}

# (glob_ou_path_exe, nome_display, cmd_key, bg_fallback, letra_fallback)
APP_DATA = [
    (r"C:\Users\conti\AppData\Local\Discord\app-*\Discord.exe",
     "Discord", "discord", "#5865F2", "D"),
    (r"C:\Program Files (x86)\Steam\steam.exe",
     "Steam",   "steam",   "#171a21", "S"),
    (r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
     "Brave",   "brave",   "#FB542B", "B"),
]

def _icone_app(exe_pattern: str, fallback_bg: str, fallback_letra: str,
               size: int = 38) -> QPixmap:
    """
    Tenta extrair o ícone do executável via QFileIconProvider.
    Suporta glob (para pastas de versão tipo Discord\app-1.x\).
    Retorna QPixmap circular de 'size' px; fallback = círculo colorido com letra.
    """
    import glob as _glob
    exe_path = ""
    if "*" in exe_pattern:
        matches = sorted(_glob.glob(exe_pattern), reverse=True)
        if matches:
            exe_path = matches[0]
    else:
        if os.path.exists(exe_pattern):
            exe_path = exe_pattern

    if exe_path:
        try:
            provider = QFileIconProvider()
            icon = provider.icon(QFileInfo(exe_path))
            if not icon.isNull():
                src = icon.pixmap(size, size)
                out = QPixmap(size, size)
                out.fill(Qt.GlobalColor.transparent)
                pp = QPainter(out)
                pp.setRenderHint(QPainter.RenderHint.Antialiasing)
                clip = QPainterPath()
                clip.addEllipse(0, 0, size, size)
                pp.setClipPath(clip)
                pp.drawPixmap(0, 0, src)
                pp.end()
                return out
        except Exception as e:
            print(f"[ICON] {exe_pattern}: {e}")

    # fallback: círculo colorido com letra
    return _make_circle_pixmap(size, fallback_bg, fallback_letra, "#ffffff",
                               font_size=8 if len(fallback_letra) > 1 else 13)

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def btn_style(bg=PURPLE, hover=PURPLE_DK, radius=6):
    return f"""
        QPushButton {{
            background: {bg};
            color: white;
            border: none;
            border-radius: {radius}px;
            padding: 5px 12px;
            font-weight: bold;
            font-size: 8pt;
        }}
        QPushButton:hover {{ background: {hover}; }}
        QPushButton:pressed {{ background: {PURPLE_DK}; }}
    """

def _make_circle_pixmap(size, bg_color, text="", text_color="#ffffff", font_size=12):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QBrush(QColor(bg_color)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(0, 0, size, size)
    if text:
        p.setPen(QPen(QColor(text_color)))
        p.setFont(QFont("Segoe UI", font_size, QFont.Weight.Bold))
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pix

# ═══════════════════════════════════════════════════════════════
# FakeRoot — compatibilidade com main.py
# ═══════════════════════════════════════════════════════════════

class _FakeRoot:
    def __init__(self, app):
        self._app = app
    def destroy(self):
        self._app.quit()
    def after(self, ms, fn):
        QTimer.singleShot(ms, fn)
    def winfo_screenwidth(self):
        return QApplication.primaryScreen().size().width()
    def winfo_screenheight(self):
        return QApplication.primaryScreen().size().height()

# ═══════════════════════════════════════════════════════════════
# Sinalizador thread-safe
# ═══════════════════════════════════════════════════════════════

class StatusSignaler(QObject):
    status_changed = pyqtSignal(str, str)
    chat_add       = pyqtSignal(str, str, bool)
    img_add        = pyqtSignal(str, str)
    salvar_imagem  = pyqtSignal(str)
    # ↓ CORREÇÃO DO CRASH: emitido da thread tkinter, executado na thread Qt
    toggle_painel  = pyqtSignal()
    # Progresso das ferramentas. Sinal, e não chamada direta, pelo mesmo motivo
    # do toggle_painel: quem emite é a thread do laço de ferramentas, e widget
    # do Qt só pode ser tocado na thread do Qt.
    progresso      = pyqtSignal(str, object)

# ═══════════════════════════════════════════════════════════════
# Sprite GIF flutuante (tkinter)
# ═══════════════════════════════════════════════════════════════

class SpriteGif:
    def __init__(self):
        import tkinter as tk
        try:
            from tkinterdnd2 import TkinterDnD
            self._root = TkinterDnD.Tk()
        except Exception:
            self._root = tk.Tk()

        COR = "#010101"
        W, H = 200, 200
        self._root.overrideredirect(True)
        self._root.wm_attributes("-transparentcolor", COR)
        self._root.wm_attributes("-topmost", True)
        self._root.configure(bg=COR)

        sw = self._root.winfo_screenwidth()
        sh = self._root.winfo_screenheight()
        self._root.geometry(f"{W}x{H}+{sw-W-16}+{sh-H-280}")

        self._cv = tk.Canvas(self._root, width=W, height=H, bg=COR, highlightthickness=0)
        self._cv.pack()
        self._img_id = self._cv.create_image(0, 0, anchor="nw")
        self._cv.bind("<ButtonPress-1>", self._drag_ini)
        self._cv.bind("<B1-Motion>",     self._drag_mov)
        self._cv.bind("<Button-3>",      self._toggle_cb_ev)

        self._dx = self._dy = 0
        self._toggle_cb = None
        self._gifs: dict = {}
        self._cur = "idle"
        self._fidx = self._ftimer = 0
        self._modo = "loop"
        self._gif_apos = None
        self._W, self._H = W, H
        self._COR_RGB = (1, 1, 1)

        try:
            from PIL import Image, ImageTk
            self._Image = Image; self._ImageTk = ImageTk
            self._carregar_gifs()
        except Exception as e:
            print(f"[SPRITE] PIL: {e}")

        self._root.after(33, self._tick)

    def _compor_frame(self, img):
        from PIL import Image
        fr = img.convert("RGBA")
        if fr.width > self._W or fr.height > self._H:
            fr.thumbnail((self._W, self._H), Image.LANCZOS)
        fundo = Image.new("RGB", (self._W, self._H), self._COR_RGB)
        ox = (self._W - fr.width) // 2
        oy = (self._H - fr.height) // 2
        fundo.paste(fr, (ox, oy), mask=fr.split()[3])
        return self._ImageTk.PhotoImage(fundo)

    def _carregar_gifs(self):
        if not os.path.exists(DIR_IMG):
            return
        for arq in os.listdir(DIR_IMG):
            if not arq.lower().endswith(".gif"):
                continue
            nome = arq[:-4].lower()
            try:
                img = self._Image.open(os.path.join(DIR_IMG, arq))
                frames, durs = [], []
                try:
                    while True:
                        frames.append(self._compor_frame(img.copy()))
                        durs.append(max(1, round(img.info.get("duration", 100) / 33)))
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass
                if frames:
                    self._gifs[nome] = (frames, durs)
            except Exception as e:
                print(f"[SPRITE] {arq}: {e}")
        if self._gifs and "idle" not in self._gifs:
            self._gifs["idle"] = self._gifs[next(iter(self._gifs))]

    def _tick(self):
        if self._cur in self._gifs:
            frs, drs = self._gifs[self._cur]
            tot = len(frs)
            self._ftimer += 1
            if self._ftimer >= drs[self._fidx % tot]:
                self._ftimer = 0
                nx = self._fidx + 1
                if nx >= tot:
                    if self._modo == "uma_vez" and self._gif_apos:
                        self._cur = self._gif_apos; self._gif_apos = None
                        self._modo = "loop"; self._fidx = 0
                    else:
                        self._fidx = 0
                else:
                    self._fidx = nx
            self._cv.itemconfig(self._img_id, image=frs[self._fidx % tot])
        self._root.after(33, self._tick)

    def trocar_gif(self, nome, modo="loop", gif_apos=None):
        if nome not in self._gifs:
            nome = next(iter(self._gifs), "idle")
        self._cur = nome; self._fidx = 0; self._ftimer = 0
        self._modo = modo; self._gif_apos = gif_apos

    def _drag_ini(self, e): self._dx, self._dy = e.x, e.y
    def _drag_mov(self, e):
        nx = self._root.winfo_x() + e.x - self._dx
        ny = self._root.winfo_y() + e.y - self._dy
        self._root.geometry(f"+{nx}+{ny}")
    def _toggle_cb_ev(self, e):
        if self._toggle_cb:
            self._toggle_cb()

# ═══════════════════════════════════════════════════════════════
# Widgets custom
# ═══════════════════════════════════════════════════════════════

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = False
        self.setFixedSize(44, 24)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(PURPLE if self._state else BORDER)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 3, 44, 18, 9, 9)
        p.setBrush(QBrush(QColor("white")))
        p.drawEllipse(25 if self._state else 2, 1, 22, 22)
        p.end()
    def mousePressEvent(self, e):
        self._state = not self._state; self.update(); self.toggled.emit(self._state)
    def set_state(self, s):
        self._state = s; self.update()


class GaugeDial(QWidget):
    def __init__(self, parent=None, color=PURPLE, label=""):
        super().__init__(parent)
        self._pct = 0; self._color = color; self._label = label
        self.setFixedSize(70, 70)
    def set_value(self, pct):
        self._pct = max(0, min(100, pct)); self.update()
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy, r = 35, 35, 28
        pen = QPen(QColor(BORDER), 5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx-r, cy-r, r*2, r*2)
        if self._pct > 0:
            ap = QPen(QColor(self._color), 5)
            ap.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(ap)
            p.drawArc(cx-r, cy-r, r*2, r*2, 90*16, int(-self._pct/100*5760))
        p.setPen(QPen(QColor(self._color)))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        p.drawText(p.window(), Qt.AlignmentFlag.AlignCenter, f"{int(self._pct)}%")
        p.end()


class AppTile(QFrame):
    clicked = pyqtSignal()
    def __init__(self, icon_pixmap: QPixmap, name: str, parent=None):
        """
        icon_pixmap — QPixmap já pronto (circular, 38×38).
        name        — label exibido embaixo do ícone.
        """
        super().__init__(parent)
        self.setFixedSize(80, 76)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._ns = f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:10px;"
        self._hs = f"background:#15152a; border:1.5px solid {PURPLE}; border-radius:10px;"
        self.setStyleSheet(self._ns)
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 8, 8, 6); lay.setSpacing(4)
        ic = QLabel(); ic.setFixedSize(38, 38)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet("background:transparent; border:none;")
        ic.setPixmap(icon_pixmap)
        lay.addWidget(ic, alignment=Qt.AlignmentFlag.AlignCenter)
        nm = QLabel(name); nm.setFont(QFont("Segoe UI", 7))
        nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nm.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        lay.addWidget(nm)
    def mousePressEvent(self, e): self.clicked.emit()
    def enterEvent(self, e): self.setStyleSheet(self._hs)
    def leaveEvent(self, e): self.setStyleSheet(self._ns)


# ═══════════════════════════════════════════════════════════════
# CHAT
# ═══════════════════════════════════════════════════════════════

_RE_CODE = re.compile(r"`([^`\n]+)`")
_RE_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_RE_ITAL = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")


def _para_rich(texto: str) -> str:
    """
    Markdown mínimo -> HTML do Qt, com escape ANTES de qualquer coisa.

    Escapar primeiro não é zelo: a Emily manda resultado de ferramenta no chat, e
    resultado tem '<' e '>' de verdade (faixa de versão de mod, trecho de XML).
    Sem escape o Qt engole o pedaço como se fosse tag e o texto desaparece da
    tela sem erro nenhum no log.
    """
    from html import escape
    s = escape(texto)
    s = _RE_CODE.sub(
        rf'<span style="background:{PURPLE_DIM}; color:{PURPLE_LT}; '
        rf'font-family:Consolas,\'Cascadia Mono\',monospace;">&#8202;\1&#8202;</span>',
        s)
    s = _RE_BOLD.sub(r"<b>\1</b>", s)
    s = _RE_ITAL.sub(r"<i>\1</i>", s)
    return s.replace("\n", "<br>")


def _normalizar_fala(texto: str) -> str:
    """
    Deixa a frase comparável: minúscula, sem pontuação, espaço único.

    Serve pra saber se uma frase que voltou do TTS já está no cartão. Comparar a
    string crua não funciona: o acumulador de frases do modelo.py entrega o
    texto cortado em sentenças e com a pontuação normalizada, então o pedaço que
    volta nunca é byte a byte igual ao que foi mostrado.
    """
    limpo = re.sub(r"[^\w\s]", " ", (texto or "").lower())
    return " ".join(limpo.split())


# Corta em ponto, exclamação, interrogação, reticência e quebra de linha,
# GUARDANDO a pontuação junto (senão remontar o texto perde os pontos).
_RE_SENTENCA = re.compile(r"[^.!?…\n]+[.!?…]*")


def _sentencas(texto: str) -> list:
    """
    Quebra um texto nas frases dele.

    Existe porque a comparação frase-a-frase é a única que funciona nos dois
    caminhos: o TTS entrega a fala dela cortada em sentenças, e o modelo, na volta
    depois da ferramenta, às vezes repete a própria frase de abertura no meio da
    resposta final. Comparar o texto inteiro não pegaria nem um nem outro.
    """
    return [p.strip() for p in _RE_SENTENCA.findall(texto or "") if p.strip()]


_cache_avatar: dict = {}


def _avatar_emily(size: int = 26) -> QPixmap:
    """Foto da Emily, redonda, em cache. Cai num círculo com 'E' se não achar."""
    if size in _cache_avatar:
        return _cache_avatar[size]
    candidatos = [
        os.path.join(DIR_BASE, "emilyimage.png"),
        os.path.join(DIR_BASE, "emily.png"),
        os.path.join(DIR_BASE, "emily.jpg"),
        os.path.join(DIR_IMG, "emilyimage.png"),
        os.path.join(DIR_IMG, "emily.png"),
    ]
    saida = None
    for path in candidatos:
        if not os.path.exists(path):
            continue
        try:
            src = QPixmap(path)
            if src.isNull():
                continue
            sc = src.scaled(size, size,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation)
            if sc.width() > size or sc.height() > size:
                sc = sc.copy(max(0, (sc.width()-size)//2),
                             max(0, (sc.height()-size)//2), size, size)
            out = QPixmap(size, size)
            out.fill(Qt.GlobalColor.transparent)
            pp = QPainter(out)
            pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            clip = QPainterPath(); clip.addEllipse(0, 0, size, size)
            pp.setClipPath(clip); pp.drawPixmap(0, 0, sc); pp.end()
            saida = out
            break
        except Exception as e:
            print(f"[AVATAR] {path}: {e}")
    if saida is None:
        saida = _make_circle_pixmap(size, PURPLE_DIM, "E", PURPLE_LT,
                                    max(8, size // 2 - 3))
    _cache_avatar[size] = saida
    return saida


class ChatBubble(QFrame):
    """
    Uma mensagem do chat.

    OS DOIS LADOS SÃO DIFERENTES DE PROPÓSITO
    ─────────────────────────────────────────
    Balão é só do Vitor. A fala dela é texto corrido, sem caixa, ocupando a
    largura da coluna — como o Claude e o ChatGPT fazem, e por um motivo prático:
    a resposta dela é longa e cheia de lista e caminho de arquivo, e balão em
    volta de parágrafo comprido só aperta a leitura. O que o Vitor escreve é
    curto, então cabe num balão e o balão marca de quem é.

    O ERRO QUE ESTAVA AQUI
    ──────────────────────
    A versão anterior fazia `addWidget(corpo, 0)` seguido de `addStretch(1)`. Com
    fator de esticamento 0, o QLabel com wordWrap recebe o MÍNIMO que ele pede —
    e o mínimo de um label com quebra de linha é mais ou menos a palavra mais
    longa. Resultado: a fala dela quebrava em torres de quatro palavras dentro de
    uma tela vazia de 900px. Não era falta de espaço, era o espaço não sendo
    entregue. A fala dela agora vai com fator 1 e SEM stretch competindo.

    E o balão do Vitor não pode usar esticamento (senão ele atravessa a tela
    mesmo com duas palavras), então a largura dele é MEDIDA com QFontMetrics:
    texto curto ganha balão justo, texto longo bate no teto e quebra.
    """
    # Teto do balão do Vitor. Fica bem abaixo da coluna (900) de propósito: em
    # janela no tamanho mínimo a coluna útil chega a ~460, e balão maior que isso
    # vazaria pra fora da área rolável, que não tem barra horizontal.
    LARGURA_MAX = 440

    def __init__(self, text, is_emily=True, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(2, 7, 2, 7)
        raiz.setSpacing(11)

        corpo = QFrame()
        corpo.setStyleSheet("background:transparent; border:none;")
        cl = QVBoxLayout(corpo)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)

        cabeca = QLabel(
            f"{'Emily' if is_emily else 'Você'}"
            f"  ·  {datetime.datetime.now().strftime('%H:%M')}")
        cabeca.setFont(QFont("Segoe UI", 8))
        cabeca.setStyleSheet(
            f"color:{PURPLE_LT if is_emily else C_TEXT2}; "
            f"background:transparent; border:none;")

        txt = QLabel(_para_rich(text))
        txt.setTextFormat(Qt.TextFormat.RichText)
        txt.setWordWrap(True)
        txt.setFont(QFont("Segoe UI", 10))
        txt.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        txt.setCursor(QCursor(Qt.CursorShape.IBeamCursor))

        av = QLabel()
        av.setFixedSize(26, 26)
        av.setStyleSheet("background:transparent; border:none;")
        av.setPixmap(_avatar_emily(26) if is_emily
                     else _make_circle_pixmap(26, PURPLE_DIM, "V", PURPLE_LT, 10))

        cl.addWidget(cabeca)
        cl.addWidget(txt)

        topo = Qt.AlignmentFlag.AlignTop
        if is_emily:
            # Sem balão: só texto, na largura toda da coluna.
            txt.setStyleSheet(
                f"background:transparent; color:{C_TEXT}; border:none; "
                f"padding:1px 0 2px 0; line-height:172%;")
            txt.setAlignment(Qt.AlignmentFlag.AlignLeft |
                             Qt.AlignmentFlag.AlignTop)
            cabeca.setAlignment(Qt.AlignmentFlag.AlignLeft)
            raiz.addWidget(av, 0, topo)
            raiz.addWidget(corpo, 1, topo)   # fator 1: recebe o espaço todo
        else:
            txt.setStyleSheet(
                f"background:{USER_BUB}; color:{C_TEXT}; border:1px solid #2b2166;"
                f" border-radius:14px; border-bottom-right-radius:5px;"
                f" padding:10px 14px; line-height:152%;")
            txt.setFixedWidth(self._largura_do_balao(text, txt.font()))
            cabeca.setAlignment(Qt.AlignmentFlag.AlignRight)
            raiz.addStretch(1)
            raiz.addWidget(corpo, 0, topo)
            raiz.addWidget(av, 0, topo)

    @classmethod
    def _largura_do_balao(cls, texto: str, fonte: QFont) -> int:
        """
        Largura de um balão que serve o texto sem sobrar nem faltar.

        Mede a linha mais larga; some o padding; corta no teto. Sem esta medida o
        balão fica do tamanho da palavra mais longa (ver a explicação na classe).
        """
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(fonte)
        linhas = (texto or " ").split("\n")
        maior = max(fm.horizontalAdvance(l) for l in linhas)
        return max(96, min(cls.LARGURA_MAX, maior + 34))


class Spinner(QWidget):
    """
    Arco girando, desenhado à mão.

    QPainter em vez de GIF ou de ciclo de caractere porque caractere pula (o
    espaçamento de cada glifo é diferente) e GIF não acompanha a cor do tema.
    """

    def __init__(self, size: int = 14, color: str = PURPLE_LT, parent=None):
        super().__init__(parent)
        self._sz = size
        self._cor = QColor(color)
        self._ang = 0
        self.setFixedSize(size, size)
        self.setStyleSheet("background:transparent;")
        self._t = QTimer(self)
        self._t.timeout.connect(self._passo)
        self._t.start(30)

    def _passo(self):
        self._ang = (self._ang + 11) % 360
        self.update()

    def parar(self):
        self._t.stop()

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        caneta = QPen(self._cor, 2.0)
        caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(caneta)
        m = 2
        p.drawArc(m, m, self._sz - 2 * m, self._sz - 2 * m,
                  -self._ang * 16, 105 * 16)
        p.end()


# Ícone por TIPO de ação, casado por palavra no nome da ferramenta.
#
# Casar por palavra, e não por nome exato, é o que impede isto de virar lista pra
# manter desatualizada: ferramenta nova nasce com um ícone razoável sem ninguém
# tocar aqui.
#
# A ORDEM é a parte que se erra. O primeiro que casar ganha, e a primeira versão
# estava ordenada por assunto — resultado: 'deletar_arquivo_mc' pegava 📄 de
# "arquivo" antes de 🗑 de "deletar", e 'procurar_mod_launcher_mc' pegava 🚀.
# O ícone comunica O QUE ELA ESTÁ FAZENDO, então VERBO vence SUBSTANTIVO, e
# verbo que dá medo (apagar) vem antes de todos.
_ICONES_PASSO = (
    # 1. o que não tem volta
    ("deletar", "🗑"), ("apagar", "🗑"), ("remover", "🗑"),
    # 2. mover bytes
    ("backup", "💾"),
    ("baixar", "⬇"), ("download", "⬇"), ("instalar", "⬇"),
    # 3. olhar
    ("procurar", "🔍"), ("buscar", "🔍"), ("pesquis", "🔍"),
    # 4. o assunto principal deste projeto
    ("modpack", "📦"), ("pack", "📦"), ("curadoria", "📦"),
    ("launcher", "🚀"), ("publica", "🚀"),
    ("mod", "🧩"),
    # 5. Discord e gente
    ("cargo", "🏷"), ("canal", "💬"), ("membro", "👤"), ("jogador", "👤"),
    ("console", "⌨"), ("comando", "⌨"),
    # 6. web e tela
    ("site", "🌐"), ("navegador", "🌐"), ("pagina", "🌐"),
    ("tela", "🖼"), ("imagem", "🖼"), ("visao", "👁"),
    # 7. memória e anotação
    ("memoria", "🧠"), ("fato", "🧠"), ("lembrar", "🧠"),
    ("regra", "📜"), ("anotar", "📝"), ("escrever", "📝"), ("editar", "📝"),
    # 8. arquivo genérico, depois dos verbos que agem sobre ele
    ("pasta", "📁"), ("arquivo", "📄"),
    # 9. verbos de leitura, que são o caso mais comum e o menos informativo
    ("status", "📊"), ("listar", "📋"), ("conferir", "🔎"), ("comparar", "⚖"),
    ("discord", "💬"), ("mensagem", "💬"),
    ("servidor", "🖥"), ("jogo", "🎮"), ("_mc", "🎮"),
    ("abrir", "↗"),
)


def _icone_de(nome_ferramenta: str) -> str:
    n = (nome_ferramenta or "").lower()
    for palavra, ico in _ICONES_PASSO:
        if palavra in n:
            return ico
    return "•"


class LinhaPasso(QFrame):
    """Um passo do painel: gira enquanto roda, vira ✓ ou ! quando fecha."""

    def __init__(self, texto: str, icone: str = "•", parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(7)

        self.spin = Spinner(13)
        self._ico = QLabel("")
        self._ico.setFixedSize(13, 13)
        self._ico.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ico.setStyleSheet("background:transparent; border:none;")
        self._ico.hide()

        self._tipo = QLabel(icone)
        self._tipo.setFont(QFont("Segoe UI Emoji", 9))
        self._tipo.setFixedWidth(16)
        self._tipo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tipo.setStyleSheet("background:transparent; border:none;")

        self._lbl = QLabel(texto)
        self._lbl.setFont(QFont("Segoe UI", 9))
        self._lbl.setWordWrap(True)
        self._lbl.setStyleSheet(
            f"color:{C_TEXT2}; background:transparent; border:none;")

        lay.addWidget(self.spin, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._ico, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._tipo, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._lbl, 1)

        # Estado explícito, e NÃO self.spin.isVisible().
        #
        # isVisible() é falso enquanto a janela ancestral não está na tela — o
        # widget existe, só não foi pintado. Usar pintura como lógica fazia o
        # painel nunca fechar passo nenhum durante a montagem da tela, e aí
        # nenhum ✓ aparecia. Estado é estado; visibilidade é desenho.
        self._aberto = True

    def aberto(self) -> bool:
        return self._aberto

    def concluir(self, problema: bool = False):
        self._aberto = False
        self.spin.parar()
        self.spin.hide()
        self._ico.setText("!" if problema else "✓")
        cor = C_YELLOW if problema else C_GREEN
        self._ico.setStyleSheet(
            f"color:{cor}; background:transparent; border:none;")
        self._ico.show()
        self._lbl.setStyleSheet(
            f"color:{C_YELLOW if problema else C_TEXT2}; "
            f"background:transparent; border:none;")


class LinhaFala(QFrame):
    """
    Uma frase que a Emily escreveu no meio do trabalho, dentro do cartão.

    "Ué, deixa eu conferir isso" não é passo de ferramenta e não pode virar um:
    ela não tem ✓ nem !, não conta como passo e não tem spinner. É narração — o
    que ela está pensando entre uma ação e outra —, então o desenho é outro: aspa
    lilás na margem e texto claro, sem ícone competindo com os passos.
    """

    def __init__(self, texto: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 3, 0, 3)
        lay.setSpacing(8)

        marca = QFrame()
        marca.setFixedWidth(2)
        marca.setStyleSheet(f"background:{PURPLE}; border:none; border-radius:1px;")
        lay.addWidget(marca)

        self._lbl = QLabel(_para_rich(texto))
        self._lbl.setTextFormat(Qt.TextFormat.RichText)
        self._lbl.setWordWrap(True)
        self._lbl.setFont(QFont("Segoe UI", 9))
        self._lbl.setStyleSheet(
            f"color:{C_TEXT}; background:transparent; border:none; "
            f"line-height:140%;")
        lay.addWidget(self._lbl, 1)


class PainelProgresso(QFrame):
    """
    O cartão que mostra, passo a passo, o que a Emily está fazendo.

    Usa o MESMO vocabulário do painel do Discord (progresso_discord.rotulo): o
    nome da função nunca aparece aqui. 'analisar_mods_da_pasta_mc' é nome de
    código; quem lê isto é o Vitor.

    Fala e passo dividem UMA lista, na ordem em que chegaram. Foi o pedido — a
    frase dela vem antes do detalhe da ferramenta, não depois — e uma lista só é
    o que garante isso: duas seções separadas voltariam a agrupar por tipo e
    perderiam a ordem do que aconteceu.
    """
    MAX_LINHAS = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:11px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 10, 13, 10)
        lay.setSpacing(6)

        topo = QFrame()
        topo.setStyleSheet("background:transparent; border:none;")
        topo.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        topo.mousePressEvent = self._clique_no_topo
        tl = QHBoxLayout(topo)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(9)
        self._spin_topo = Spinner(14, PURPLE)
        self._titulo = QLabel("Trabalhando nisso…")
        self._titulo.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        self._titulo.setStyleSheet(
            f"color:{PURPLE_LT}; background:transparent; border:none;")
        self._seta = QLabel("")
        self._seta.setFont(QFont("Segoe UI", 8))
        self._seta.setStyleSheet(
            f"color:{C_TEXT3}; background:transparent; border:none;")
        tl.addWidget(self._spin_topo, 0, Qt.AlignmentFlag.AlignVCenter)
        tl.addWidget(self._titulo, 1)
        tl.addWidget(self._seta, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(topo)

        # Corpo separado do topo pra poder sumir inteiro quando o cartão colapsa.
        self._corpo = QWidget()
        self._corpo.setStyleSheet("background:transparent; border:none;")
        self._itens = QVBoxLayout(self._corpo)
        self._itens.setContentsMargins(3, 1, 0, 0)
        self._itens.setSpacing(1)
        lay.addWidget(self._corpo)

        self._linhas: list = []   # só os passos de ferramenta
        self._tudo: list = []     # passos e falas, pra poda
        self._total = 0
        self._problemas = 0
        self._colapsado = False

    # ── conteúdo ────────────────────────────────────────────────

    def _guardar(self, w):
        self._tudo.append(w)
        self._itens.addWidget(w)
        if len(self._tudo) > self.MAX_LINHAS:
            velho = self._tudo.pop(0)
            if velho in self._linhas:
                self._linhas.remove(velho)
            velho.setParent(None)
            velho.deleteLater()

    def fala(self, texto: str):
        texto = (texto or "").strip()
        if not texto:
            return
        self._guardar(LinhaFala(texto))

    def passo(self, texto: str, icone: str = "•"):
        # Passo novo fecha o anterior: dois ícones girando ao mesmo tempo dá a
        # impressão errada de duas coisas em paralelo.
        self._fechar(False)
        self._total += 1
        linha = LinhaPasso(texto, icone)
        self._linhas.append(linha)
        self._guardar(linha)

    def resultado(self, problema: bool):
        if problema:
            self._problemas += 1
        self._fechar(problema)

    def _fechar(self, problema: bool):
        for linha in reversed(self._linhas):
            if linha.aberto():
                linha.concluir(problema)
                return

    def vazio(self) -> bool:
        """Sem passo de ferramenta. Fala sozinha não sustenta um cartão."""
        return self._total == 0

    def teve_problema(self) -> bool:
        return self._problemas > 0

    # ── fim ─────────────────────────────────────────────────────

    def finalizar(self):
        self._fechar(False)
        self._spin_topo.parar()
        self._spin_topo.hide()
        passos = f"{self._total} passo" + ("" if self._total == 1 else "s")
        if self._problemas:
            self._titulo.setText(f"Feito, com {self._problemas} ressalva"
                                 + ("" if self._problemas == 1 else "s")
                                 + f" · {passos}")
            self._titulo.setStyleSheet(
                f"color:{C_YELLOW}; background:transparent; border:none;")
        else:
            self._titulo.setText(f"Pronto · {passos}")
            self._titulo.setStyleSheet(
                f"color:{C_GREEN}; background:transparent; border:none;")

    def colapsar(self):
        """
        Vira uma tira de uma linha, clicável.

        Some o passo a passo, fica o motivo. O cartão inteiro só desaparece
        quando deu tudo certo; com ressalva, sumir esconderia justamente a parte
        que o Vitor precisa ver depois.
        """
        self._colapsado = True
        self._corpo.setVisible(False)
        self._seta.setText("▾")

    def _clique_no_topo(self, _e):
        self._colapsado = not self._colapsado
        self._corpo.setVisible(not self._colapsado)
        self._seta.setText("▾" if self._colapsado else "▴")


class IndicadorDigitando(QFrame):
    """Três pontinhos pulsando, do jeito que todo chat de IA faz."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(9)

        av = QLabel()
        av.setFixedSize(26, 26)
        av.setStyleSheet("background:transparent; border:none;")
        av.setPixmap(_avatar_emily(26))
        lay.addWidget(av, 0, Qt.AlignmentFlag.AlignVCenter)

        # Sem balão, igual à fala dela. Os pontinhos ocupam o lugar do texto que
        # vai chegar; enquadrar eles numa caixa que a mensagem seguinte não tem
        # fazia a linha pular quando o texto aparecia.
        caixa = QFrame()
        caixa.setStyleSheet("background:transparent; border:none;")
        cl = QHBoxLayout(caixa)
        cl.setContentsMargins(1, 8, 8, 8)
        cl.setSpacing(6)
        self._pontos = []
        for _ in range(3):
            d = QLabel("●")
            d.setFont(QFont("Segoe UI", 8))
            d.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            cl.addWidget(d)
            self._pontos.append(d)
        lay.addWidget(caixa, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)

        self._i = 0
        self._t = QTimer(self)
        self._t.timeout.connect(self._passo)
        self._t.start(280)

    def _passo(self):
        for j, d in enumerate(self._pontos):
            aceso = j == (self._i % 3)
            d.setStyleSheet(
                f"color:{PURPLE_LT if aceso else C_TEXT3};"
                f" background:transparent; border:none;")
        self._i += 1

    def parar(self):
        self._t.stop()


class LinhaConversa(QFrame):
    """
    Uma conversa na barra lateral.

    O × só aparece no hover. Botão de apagar sempre visível numa lista de 80
    linhas é um campo minado: um clique torto e o histórico foi.
    """
    abrir = pyqtSignal(str)
    apagar = pyqtSignal(str)

    def __init__(self, meta: dict, ativa: bool = False, parent=None):
        super().__init__(parent)
        self._cid = meta.get("id", "")
        self._ativa = ativa
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._pintar(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 6, 0)
        lay.setSpacing(4)

        self._lbl = QLabel(meta.get("titulo") or "Conversa")
        self._lbl.setFont(QFont("Segoe UI", 9))
        self._lbl.setStyleSheet(
            f"color:{C_TEXT if ativa else C_TEXT2}; background:transparent; "
            f"border:none;")
        # Elide por conta própria: QLabel não corta com "…" sozinho, e sem isso
        # título longo empurra o × pra fora da barra.
        self._lbl.setMinimumWidth(10)
        self._titulo_cheio = meta.get("titulo") or "Conversa"
        self.setToolTip(self._titulo_cheio)
        lay.addWidget(self._lbl, 1)

        self._x = QPushButton("×")
        self._x.setFixedSize(20, 20)
        self._x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._x.setToolTip("Apagar esta conversa")
        self._x.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT3}; "
            f"border:none; font-size:12pt; border-radius:5px; }}"
            f"QPushButton:hover {{ background:{C_RED}; color:#fff; }}")
        self._x.clicked.connect(self._pedir_apagar)
        self._x.hide()
        lay.addWidget(self._x)

    def _pintar(self, hover: bool):
        fundo = PURPLE_DIM if (hover or self._ativa) else "transparent"
        borda = PURPLE if self._ativa else "transparent"
        self.setStyleSheet(
            f"background:{fundo}; border:1px solid {borda}; border-radius:7px;")

    def enterEvent(self, e):
        self._pintar(True)
        self._x.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._pintar(False)
        self._x.hide()
        super().leaveEvent(e)

    def resizeEvent(self, e):
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._lbl.font())
        self._lbl.setText(fm.elidedText(
            self._titulo_cheio, Qt.TextElideMode.ElideRight,
            max(20, self._lbl.width())))
        super().resizeEvent(e)

    def _pedir_apagar(self):
        self.apagar.emit(self._cid)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.abrir.emit(self._cid)
        super().mousePressEvent(e)


class MacroRow(QFrame):
    play_clicked  = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked  = pyqtSignal()
    def __init__(self, icon_pix, name, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:6px;")
        lay = QHBoxLayout(self); lay.setContentsMargins(8,6,8,6); lay.setSpacing(6)
        if icon_pix:
            il = QLabel(); il.setPixmap(icon_pix); il.setFixedSize(22,22)
            il.setScaledContents(True); il.setStyleSheet("background:transparent; border:none;")
            lay.addWidget(il)
        nm = QLabel(name); nm.setFont(QFont("Segoe UI",9))
        nm.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        lay.addWidget(nm, 1)
        for txt, color, sig in [("▶",C_GREEN,self.play_clicked),
                                  ("⏸",C_YELLOW,self.pause_clicked),
                                  ("⏹",C_RED,self.stop_clicked)]:
            b = QPushButton(txt); b.setFixedSize(26,26)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(f"""
                QPushButton {{ background:{PURPLE_DIM}; color:{color}; border:1px solid {BORDER}; border-radius:4px; font-size:10pt; }}
                QPushButton:hover {{ background:#1e1450; border-color:{PURPLE}; }}
            """)
            b.clicked.connect(sig); lay.addWidget(b)

# ═══════════════════════════════════════════════════════════════
# PAINEL PRINCIPAL
# ═══════════════════════════════════════════════════════════════

class PainelEmily(QWidget):
    def __init__(self, signaler: StatusSignaler):
        super().__init__()
        self.sig = signaler
        self._monitor_dl_ativo = False
        self._drag_pos = QPoint()
        self._dragging = False
        self._em_buffer = []
        self._em_falando = False
        self._maximized = False
        self._digitando = None      # IndicadorDigitando vivo, se houver
        self._painel_prog = None    # PainelProgresso vivo, se houver
        self._falas_no_cartao = ""   # tudo que foi pro cartão, normalizado
        self._frases_no_cartao = set()  # e frase por frase, pra casar exato
        self._sidebar_aberta = True
        self._status_dots = []      # a barra de 4 estados saiu; ver _build_ui
        self._conversa_id = ""      # conversa aberta; "" = nenhuma ainda
        self._carregando = False    # True enquanto redesenha do disco
        self._setup_window()
        self._build_ui()
        self._connect_signals()
        self._start_timers()

    def _setup_window(self):
        screen = QApplication.primaryScreen().size()
        W = min(1360, max(920, int(screen.width() * 0.92)))
        H = min(830, int(screen.height() * 0.90))
        self.resize(W, H)
        self.move(max(0,(screen.width()-W)//2), max(0,(screen.height()-H)//2))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setStyleSheet(f"QWidget {{ background:{BG_MAIN}; }}")

    def _build_ui(self):
        """
        Esqueleto novo: barra de título fina, barra lateral e um PALCO de páginas.

        O layout velho era três colunas fixas ao mesmo tempo — memória à esquerda,
        conversa espremida no meio, atalhos à direita. O chat ficava com ~350px de
        largura útil e a fala da Emily empilhava em torres de duas palavras.
        Agora a conversa é a tela, e o resto mora em Configurações.
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        bg = QFrame(self)
        bg.setObjectName("root_bg")
        bg.setStyleSheet(
            f"QFrame#root_bg {{ background:{BG_MAIN}; "
            f"border:1px solid {BORDER}; border-radius:10px; }}")
        outer.addWidget(bg)

        ml = QVBoxLayout(bg)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        ml.addWidget(self._build_barra_titulo())

        linha_topo = QFrame()
        linha_topo.setFixedHeight(1)
        linha_topo.setStyleSheet(f"background:{DIVISOR}; border:none;")
        ml.addWidget(linha_topo)

        corpo = QWidget()
        corpo.setStyleSheet("background:transparent;")
        cl = QHBoxLayout(corpo)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._sidebar = self._build_sidebar()
        cl.addWidget(self._sidebar)

        # Linha de 1px entre a barra lateral e a conversa. Antes eu contava com a
        # diferença de fundo (#0a0a17 contra #0b0b18) pra marcar a divisão — um
        # ponto de diferença em cada canal, o que não marca nada.
        self._linha_sidebar = QFrame()
        self._linha_sidebar.setFixedWidth(1)
        self._linha_sidebar.setStyleSheet(f"background:{DIVISOR}; border:none;")
        cl.addWidget(self._linha_sidebar)

        # O palco. Três páginas: início, conversa e configurações.
        #
        # Configurações como PÁGINA, e não como janela flutuante, de propósito:
        # janela solta em app sem moldura precisa de posicionamento à mão e
        # aparece atrás da principal na hora errada. Página não tem esse problema.
        self._palco = QStackedWidget()
        self._palco.setStyleSheet(f"background:{BG_CENTER};")
        self._pag_inicio = self._build_pagina_inicio()
        self._pag_chat = self._build_pagina_chat()
        self._pag_config = self._build_pagina_config()
        self._palco.addWidget(self._pag_inicio)
        self._palco.addWidget(self._pag_chat)
        self._palco.addWidget(self._pag_config)
        cl.addWidget(self._palco, 1)

        ml.addWidget(corpo, 1)

        # O input nasce no início e é MOVIDO entre as páginas, em vez de existir
        # duas vezes. Duas caixas significariam dois lugares guardando os
        # arquivos anexados, e anexar numa e enviar pela outra perderia o anexo.
        self._mover_input("inicio")
        self._recarregar_conversas()

    # ── Barra de título ─────────────────────────────────────────

    def _build_barra_titulo(self):
        barra = QFrame()
        barra.setFixedHeight(46)
        barra.setStyleSheet(f"background:{BG_HEADER}; border:none; "
                            f"border-top-left-radius:10px; "
                            f"border-top-right-radius:10px;")
        barra.mousePressEvent = self._drag_press
        barra.mouseMoveEvent = self._drag_move
        barra.mouseReleaseEvent = self._drag_release
        lay = QHBoxLayout(barra)
        lay.setContentsMargins(9, 0, 9, 0)
        lay.setSpacing(6)

        self._btn_sidebar = self._botao_barra("☰", "Mostrar/esconder a barra lateral")
        self._btn_sidebar.clicked.connect(self._alternar_sidebar)
        lay.addWidget(self._btn_sidebar)
        lay.addSpacing(4)

        av = QLabel()
        av.setFixedSize(24, 24)
        av.setPixmap(_avatar_emily(24))
        av.setStyleSheet("background:transparent; border:none;")
        lay.addWidget(av)

        nome = QLabel("Emily")
        nome.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        nome.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        lay.addWidget(nome)

        lay.addStretch(1)

        self._status_pill = QLabel("● Aguardando")
        self._status_pill.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        self._status_pill.setStyleSheet(
            f"color:{C_GREEN}; background:{PURPLE_DIM}; border-radius:9px; "
            f"padding:4px 12px;")
        lay.addWidget(self._status_pill)
        lay.addSpacing(6)

        # Os três botões, e a diferença entre eles importa:
        #
        #   —  esconde a JANELA (o sprite na tela reabre com um clique)
        #   ▢  maximiza
        #   ✕  ENCERRA A EMILY inteira, de propósito
        #
        # O ✕ voltou a encerrar porque era o que ele fazia antes e é o que o Vitor
        # usa pra desligar sem ir no terminal dar Ctrl+C. Eu tinha ligado o ✕ no
        # hide() quando refiz a barra de título, e junto com ele foi embora o
        # único jeito de encerrar pela interface.
        for texto, dica, fn in (
            ("—", "Esconder a janela (clique no sprite pra voltar)", self.hide),
            ("▢", "Maximizar / restaurar", self._alternar_maximizar),
            ("✕", "ENCERRAR a Emily (fecha tudo)", self._encerrar_emily),
        ):
            b = self._botao_barra(texto, dica, perigo=(texto == "✕"))
            b.clicked.connect(fn)
            lay.addWidget(b)
        return barra

    def _encerrar_emily(self):
        """
        Desliga a Emily inteira, não só a janela.

        Pede o quit ao Qt: isso faz o app.exec() retornar, o JanelaEmily.iniciar()
        chegar no sys.exit() e o atexit do main.py rodar o encerrar_tudo() — que é
        quem para o monitor de notificações e desconecta a voz do Discord. Ou
        seja, a saída limpa passa por aqui.

        E tem o cinto de segurança. O encerrar_tudo() fala com o Discord, e
        chamada de rede na saída pode pendurar; se isso acontecer o processo fica
        vivo sem janela nenhuma e o Vitor volta a precisar de Ctrl+C — que é
        exatamente o que ele não quer. O timer garante a saída em 6s, tempo folgado
        pra desconexão normal. Daemon, pra ele mesmo não segurar o processo.
        """
        print("[INTERFACE] Encerrando a Emily pelo botão da janela.")
        try:
            self.hide()
        except Exception:
            pass

        def _forcar():
            print("[INTERFACE] O encerramento demorou; saindo à força.")
            os._exit(0)

        socorro = threading.Timer(6.0, _forcar)
        socorro.daemon = True
        socorro.start()

        QApplication.quit()

    def _botao_barra(self, texto, dica="", perigo=False):
        b = QPushButton(texto)
        b.setFixedSize(28, 28)
        b.setToolTip(dica)
        b.setFont(QFont("Segoe UI", 10))
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        hover = C_RED if perigo else PURPLE_DIM
        cor_hover = "#fff" if perigo else C_TEXT
        b.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT2}; "
            f"border:none; border-radius:7px; }}"
            f"QPushButton:hover {{ background:{hover}; color:{cor_hover}; }}")
        return b

    def _alternar_maximizar(self):
        if self._maximized:
            self.showNormal()
        else:
            self.showMaximized()
        self._maximized = not self._maximized

    def _alternar_sidebar(self):
        # Estado explícito, e NÃO isVisible().
        #
        # Mesma pegadinha do LinhaPasso: isVisible() é falso enquanto a janela
        # ancestral não está na tela, então com a janela escondida (Emily
        # minimizada no ícone, que é o normal aqui) o primeiro clique "mostrava"
        # uma barra que já estava mostrada e o botão parecia não funcionar.
        self._sidebar_aberta = not getattr(self, "_sidebar_aberta", True)
        self._sidebar.setVisible(self._sidebar_aberta)
        # A linha divisória vai junto: linha solta na borda esquerda da tela, sem
        # nada do outro lado, fica com cara de defeito.
        if getattr(self, "_linha_sidebar", None) is not None:
            self._linha_sidebar.setVisible(self._sidebar_aberta)

    # ── Barra lateral ───────────────────────────────────────────

    def _build_sidebar(self):
        side = QWidget()
        side.setFixedWidth(236)
        side.setStyleSheet(f"background:{BG_SIDEBAR}; border:none;")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(9)

        nova = QPushButton("  ✚   Nova conversa")
        nova.setFixedHeight(38)
        nova.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        nova.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        nova.setStyleSheet(
            f"QPushButton {{ background:{PURPLE}; color:#fff; border:none; "
            f"border-radius:9px; text-align:left; padding-left:12px; }}"
            f"QPushButton:hover {{ background:{PURPLE_DK}; }}")
        nova.clicked.connect(self._nova_conversa)
        lay.addWidget(nova)

        titulo = QLabel("RECENTES")
        titulo.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        titulo.setStyleSheet(
            f"color:{C_TEXT3}; background:transparent; border:none; "
            f"letter-spacing:1px;")
        lay.addSpacing(4)
        lay.addWidget(titulo)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rolagem.setStyleSheet(
            f"QScrollArea {{ background:transparent; border:none; }}"
            f"QScrollBar:vertical {{ width:3px; background:transparent; }}"
            f"QScrollBar::handle:vertical {{ background:{BORDER}; "
            f"border-radius:1px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}")
        interno = QWidget()
        interno.setStyleSheet("background:transparent;")
        self._lista_conversas = QVBoxLayout(interno)
        self._lista_conversas.setContentsMargins(0, 0, 0, 0)
        self._lista_conversas.setSpacing(2)
        self._lista_conversas.addStretch(1)
        rolagem.setWidget(interno)
        lay.addWidget(rolagem, 1)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{DIVISOR}; border:none;")
        lay.addWidget(sep)

        cfg = QPushButton("  ⚙   Configurações")
        cfg.setFixedHeight(34)
        cfg.setFont(QFont("Segoe UI", 9))
        cfg.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cfg.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT2}; "
            f"border:none; border-radius:8px; text-align:left; "
            f"padding-left:10px; }}"
            f"QPushButton:hover {{ background:{PURPLE_DIM}; color:{C_TEXT}; }}")
        cfg.clicked.connect(self._abrir_config)
        lay.addWidget(cfg)

        rodape = QFrame()
        rodape.setStyleSheet("background:transparent; border:none;")
        rl = QHBoxLayout(rodape)
        rl.setContentsMargins(4, 2, 4, 2)
        rl.setSpacing(8)
        eu = QLabel()
        eu.setFixedSize(26, 26)
        eu.setPixmap(_make_circle_pixmap(26, PURPLE_DIM, "V", PURPLE_LT, 10))
        eu.setStyleSheet("background:transparent; border:none;")
        rl.addWidget(eu)
        col = QVBoxLayout()
        col.setSpacing(0)
        n1 = QLabel("Vitor")
        n1.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        n1.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        n2 = QLabel("IA pessoal")
        n2.setFont(QFont("Segoe UI", 7))
        n2.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
        col.addWidget(n1)
        col.addWidget(n2)
        rl.addLayout(col, 1)
        lay.addWidget(rodape)
        return side

    def _recarregar_conversas(self):
        """Redesenha a lista da barra lateral a partir do disco."""
        try:
            import conversas
            itens = conversas.listar()
        except Exception as e:
            print(f"[INTERFACE] não listei as conversas: {e}")
            itens = []

        while self._lista_conversas.count() > 1:
            item = self._lista_conversas.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        if not itens:
            vazio = QLabel("Nada por aqui ainda.")
            vazio.setFont(QFont("Segoe UI", 8))
            vazio.setStyleSheet(
                f"color:{C_TEXT3}; background:transparent; border:none; "
                f"padding:6px 8px;")
            self._lista_conversas.insertWidget(0, vazio)
            return

        for meta in itens:
            linha = LinhaConversa(meta, ativa=(meta["id"] == self._conversa_id))
            linha.abrir.connect(self._abrir_conversa)
            linha.apagar.connect(self._apagar_conversa)
            self._lista_conversas.insertWidget(
                self._lista_conversas.count() - 1, linha)

    # ── Páginas ─────────────────────────────────────────────────

    def _build_pagina_inicio(self):
        pag = QWidget()
        pag.setStyleSheet(f"background:{BG_CENTER};")
        lay = QVBoxLayout(pag)
        lay.setContentsMargins(28, 20, 28, 26)
        lay.setSpacing(0)
        lay.addStretch(3)

        self._emily_lbl = QLabel()
        self._emily_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._emily_lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self._carregar_imagem_emily()
        lay.addSpacing(18)

        ola = QLabel("Oi, Vitor.")
        ola.setFont(QFont("Segoe UI", 22, QFont.Weight.Light))
        ola.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        ola.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ola)

        sub = QLabel("No que a gente mexe agora?")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color:{C_TEXT2}; background:transparent;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(22)

        # Onde o input entra quando estamos no início.
        self._slot_input_inicio = QVBoxLayout()
        self._slot_input_inicio.setContentsMargins(0, 0, 0, 0)
        caixa = QWidget()
        caixa.setMaximumWidth(720)
        caixa.setStyleSheet("background:transparent;")
        caixa.setLayout(self._slot_input_inicio)
        lay.addWidget(caixa, 0, Qt.AlignmentFlag.AlignCenter)

        lay.addSpacing(14)
        lay.addWidget(self._build_sugestoes(), 0, Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(4)
        return pag

    def _build_sugestoes(self):
        w = QWidget()
        w.setMaximumWidth(720)
        w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        for ico, frase in (
            ("🧩", "analisa a pasta de mods aí e me diz o que tem de bom"),
            ("📊", "como tá o servidor de Minecraft?"),
            ("🚀", "o que tá pendente no launcher?"),
        ):
            b = QPushButton(f"  {ico}   {frase}")
            b.setFixedHeight(38)
            b.setFont(QFont("Segoe UI", 9))
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(
                f"QPushButton {{ background:{BG_CARD}; color:{C_TEXT2}; "
                f"border:1px solid {BORDER}; border-radius:9px; "
                f"text-align:left; padding-left:12px; }}"
                f"QPushButton:hover {{ background:{PURPLE_DIM}; "
                f"color:{C_TEXT}; border-color:{PURPLE}; }}")
            b.clicked.connect(lambda _, f=frase: self._enviar_frase(f))
            lay.addWidget(b)
        return w

    def _enviar_frase(self, frase):
        self._campo_texto.setPlainText(frase)
        self._enviar()

    def _build_pagina_chat(self):
        pag = QWidget()
        pag.setStyleSheet(f"background:{BG_CENTER};")
        lay = QVBoxLayout(pag)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Cabeçalho, conversa e caixa de texto passam pelo MESMO _na_coluna(), com
        # a mesma proporção. Antes o título tinha margem fixa de 18px enquanto as
        # bolhas ficavam numa coluna centralizada: as três coisas começavam em
        # três lugares diferentes, e era isso o "espaço desigual".
        cab = QFrame()
        cab.setFixedHeight(46)
        cab.setStyleSheet(f"background:{BG_CENTER}; border:none; "
                          f"border-bottom:1px solid {DIVISOR};")
        cl = QVBoxLayout(cab)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        faixa = QWidget()
        faixa.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(faixa)
        hl.setContentsMargins(2, 0, 2, 0)
        hl.setSpacing(8)
        self._titulo_chat = QLabel("Conversa")
        self._titulo_chat.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._titulo_chat.setStyleSheet(
            f"color:{C_TEXT}; background:transparent; border:none;")
        hl.addWidget(self._titulo_chat, 1)
        cl.addWidget(self._na_coluna(faixa))
        lay.addWidget(cab)

        lay.addWidget(self._build_chat_area(), 1)

        rodape = QFrame()
        rodape.setStyleSheet(f"background:{BG_CENTER}; border:none; "
                             f"border-top:1px solid {DIVISOR};")
        rl = QVBoxLayout(rodape)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        centro = QWidget()
        centro.setStyleSheet("background:transparent;")
        self._slot_input_chat = QVBoxLayout(centro)
        self._slot_input_chat.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self._na_coluna(centro))
        lay.addWidget(rodape)
        return pag

    LARGURA_COLUNA = 900

    def _na_coluna(self, dentro: QWidget) -> QWidget:
        """
        Centraliza um widget numa coluna de largura máxima.

        A proporção 1:6:1 é a mesma nos três usos (cabeçalho, conversa, input), e
        é isso que faz as três se alinharem na vertical em qualquer largura de
        janela. Trocar por margem fixa num deles quebra o alinhamento — foi o que
        aconteceu.
        """
        fora = QWidget()
        fora.setStyleSheet("background:transparent;")
        hl = QHBoxLayout(fora)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        dentro.setMaximumWidth(self.LARGURA_COLUNA)
        hl.addStretch(1)
        hl.addWidget(dentro, 6)
        hl.addStretch(1)
        return fora

    def _build_pagina_config(self):
        """
        Configurações reaproveita as DUAS colunas antigas inteiras.

        Não reescrevi memória, apps, automação, modos, macros e sistema: eles
        funcionam, e reescrever só pra mudar de lugar seria trocar código testado
        por código novo sem ganho nenhum. Eles saíram da frente da conversa, que
        era o pedido, e continuam existindo do jeito que estavam.
        """
        pag = QWidget()
        pag.setStyleSheet(f"background:{BG_CENTER};")
        lay = QVBoxLayout(pag)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        cab = QFrame()
        cab.setFixedHeight(46)
        cab.setStyleSheet(f"background:{BG_CENTER}; border:none; "
                          f"border-bottom:1px solid {DIVISOR};")
        hl = QHBoxLayout(cab)
        hl.setContentsMargins(14, 0, 18, 0)
        hl.setSpacing(10)
        voltar = QPushButton("←  Voltar")
        voltar.setFixedHeight(30)
        voltar.setFont(QFont("Segoe UI", 9))
        voltar.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        voltar.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT2}; "
            f"border:none; border-radius:8px; padding:0 10px; }}"
            f"QPushButton:hover {{ background:{PURPLE_DIM}; color:{C_TEXT}; }}")
        voltar.clicked.connect(self._fechar_config)
        hl.addWidget(voltar)
        t = QLabel("Configurações")
        t.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        t.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        hl.addWidget(t)
        hl.addStretch(1)
        lay.addWidget(cab)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setStyleSheet(
            f"QScrollArea {{ background:{BG_CENTER}; border:none; }}"
            f"QScrollBar:vertical {{ width:5px; background:transparent; }}"
            f"QScrollBar::handle:vertical {{ background:{BORDER}; "
            f"border-radius:2px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}")
        interno = QWidget()
        interno.setStyleSheet(f"background:{BG_CENTER};")
        il = QHBoxLayout(interno)
        il.setContentsMargins(18, 16, 18, 18)
        il.setSpacing(16)
        il.addWidget(self._build_right_sidebar(), 0, Qt.AlignmentFlag.AlignTop)
        il.addWidget(self._build_left_sidebar(), 0, Qt.AlignmentFlag.AlignTop)
        il.addStretch(1)
        rolagem.setWidget(interno)
        lay.addWidget(rolagem, 1)
        return pag

    # ── Navegação ───────────────────────────────────────────────

    def _mover_input(self, onde: str):
        """Move a ÚNICA caixa de input entre início e conversa."""
        if not hasattr(self, "_area_input"):
            self._area_input = self._build_input_area()
        alvo = (self._slot_input_inicio if onde == "inicio"
                else self._slot_input_chat)
        alvo.addWidget(self._area_input)
        self._area_input.show()
        try:
            self._campo_texto.setFocus()
        except Exception:
            pass

    def _abrir_config(self):
        self._palco.setCurrentWidget(self._pag_config)

    def _fechar_config(self):
        self._palco.setCurrentWidget(
            self._pag_chat if self._conversa_id else self._pag_inicio)

    def _ir_para_chat(self):
        """Sai do início e entra na conversa em tela cheia."""
        if self._palco.currentWidget() is self._pag_chat:
            return
        self._mover_input("chat")
        self._palco.setCurrentWidget(self._pag_chat)

    def _nova_conversa(self):
        """
        Volta pro início com o chat limpo.
        
        Não cria a conversa no disco agora: quem cria é a primeira mensagem. Sem
        isso, clicar 'Nova conversa' e desistir deixaria uma linha vazia na
        lista — e clicar cinco vezes deixaria cinco.
        """
        self._conversa_id = ""
        self._limpar_chat()
        self._encerrar_progresso()
        self._mover_input("inicio")
        self._palco.setCurrentWidget(self._pag_inicio)
        self._recarregar_conversas()
        try:
            import modelo
            modelo.definir_historico([])
        except Exception as e:
            print(f"[INTERFACE] não limpei o contexto do modelo: {e}")

    def _limpar_chat(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            w = item.widget() if item else None
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._digitando = None
        self._painel_prog = None

    def _abrir_conversa(self, cid: str):
        """Carrega uma conversa guardada, no chat E no contexto da Emily."""
        try:
            import conversas
            mensagens = conversas.abrir(cid)
            titulo = next((c["titulo"] for c in conversas.listar()
                           if c["id"] == cid), "Conversa")
        except Exception as e:
            print(f"[INTERFACE] não abri a conversa: {e}")
            return

        self._conversa_id = cid
        self._limpar_chat()
        self._carregando = True
        try:
            for m in mensagens:
                self._add_chat_msg(
                    "emily" if m.get("papel") == "emily" else "user",
                    m.get("texto", ""))
        finally:
            self._carregando = False

        self._titulo_chat.setText(titulo)
        self._ir_para_chat()
        self._recarregar_conversas()

        # Reabrir uma conversa também devolve o CONTEXTO pra Emily. Sem isso ela
        # veria o histórico na tela e não saberia do que o Vitor está falando.
        try:
            import conversas as _c
            import modelo
            modelo.definir_historico(_c.para_o_modelo(cid))
        except Exception as e:
            print(f"[INTERFACE] não restaurei o contexto: {e}")

    def _apagar_conversa(self, cid: str):
        try:
            import conversas
            conversas.apagar(cid)
        except Exception as e:
            print(f"[INTERFACE] não apaguei a conversa: {e}")
            return
        if cid == self._conversa_id:
            self._nova_conversa()
        else:
            self._recarregar_conversas()

    def _hsep(self):
        f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background:{BORDER};"); return f

    def _vsep(self):
        f = QFrame(); f.setFixedWidth(1); f.setStyleSheet(f"background:{BORDER};"); return f

    # ── Coluna de memória (mora dentro de Configurações) ────────
    #
    # Era a sidebar esquerda do layout velho. O nome ficou; o lugar mudou.

    def _build_left_sidebar(self):
        side = QWidget(); side.setFixedWidth(275)
        side.setStyleSheet(f"background:{BG_SIDEBAR};")
        lay = QVBoxLayout(side); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        sc = QScrollArea(); sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet(f"""
            QScrollArea {{ background:{BG_SIDEBAR}; border:none; }}
            QScrollBar:vertical {{ width:4px; background:{BG_SIDEBAR}; }}
            QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:2px; }}
        """)
        inner = QWidget(); inner.setStyleSheet(f"background:{BG_SIDEBAR};")
        il = QVBoxLayout(inner); il.setContentsMargins(12,14,12,10); il.setSpacing(10)

        # A lista falsa de "Conversas recentes" saiu daqui. Ela montava cartões a
        # partir dos pares do histórico do modelo, com hora sempre igual a agora e
        # sem poder abrir nada. Agora existe a lista de VERDADE na barra lateral,
        # e duas listas de conversa na mesma tela — uma clicável e uma não — era
        # justamente a bagunça que o Vitor pediu pra arrumar.

        mh = QHBoxLayout()
        ml_lbl = QLabel("🧠 Memória"); ml_lbl.setFont(QFont("Segoe UI",10,QFont.Weight.Bold))
        ml_lbl.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        mh.addWidget(ml_lbl); mh.addStretch()
        am = QPushButton("＋ Adicionar")
        am.setStyleSheet(f"background:transparent; color:{PURPLE_LT}; border:none; font-size:8pt;")
        am.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        am.clicked.connect(self._abrir_dialogo_adicionar_fato)
        mh.addWidget(am); il.addLayout(mh)

        # container que segura o grid — permite limpeza e reconstrução
        self._mem_container = QWidget()
        self._mem_container.setStyleSheet("background:transparent;")
        self._mem_grid = QGridLayout(self._mem_container)
        self._mem_grid.setSpacing(4)
        self._carregar_memoria()
        il.addWidget(self._mem_container)
        il.addStretch()

        # timer: atualiza o painel de memória a cada 10 s
        self._mem_timer = QTimer(self)
        self._mem_timer.setInterval(10_000)
        self._mem_timer.timeout.connect(self._carregar_memoria)
        self._mem_timer.start()
        sc.setWidget(inner); lay.addWidget(sc, 1)

        # O rodapé com "Você / Perfil pessoal" e os três ícones sem função saiu:
        # o perfil agora vive no pé da barra lateral de verdade, e os ícones não
        # faziam nada.
        return side

    def _carregar_memoria(self):
        """Limpa e reconstrói o grid de memória com os fatos atuais."""
        # Limpa widgets existentes no grid
        while self._mem_grid.count():
            item = self._mem_grid.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        fatos = []
        try:
            import memoria as _mem
            fatos = _mem.listar_fatos()
        except Exception:
            pass

        icons  = ["❤","💻","⭐","🌙","✅","📌","🔖","🧩","🎯","💡"]
        colors = [C_RED, C_BLUE, C_YELLOW, PURPLE_LT, C_GREEN, C_CYAN,
                  C_LILAC, C_TEXT2, C_YELLOW, C_GREEN]

        if not fatos:
            vazio = QLabel("Nenhum fato salvo ainda.")
            vazio.setFont(QFont("Segoe UI", 8))
            vazio.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            vazio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._mem_grid.addWidget(vazio, 0, 0, 1, 2)
            return

        for i, fato in enumerate(fatos[:8]):
            card = QFrame(); card.setFixedSize(118, 105)
            card.setStyleSheet(
                f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:6px;")
            cl = QVBoxLayout(card); cl.setContentsMargins(7, 5, 7, 5); cl.setSpacing(2)

            top_row = QHBoxLayout(); top_row.setContentsMargins(0,0,0,0)
            ic = QLabel(icons[i % len(icons)])
            ic.setFont(QFont("Segoe UI Emoji", 11))
            ic.setStyleSheet(f"color:{colors[i%len(colors)]}; background:transparent; border:none;")
            top_row.addWidget(ic); top_row.addStretch()

            # Botão deletar (×) no canto superior direito do card
            del_btn = QPushButton("×"); del_btn.setFixedSize(16, 16)
            del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_btn.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:11pt; }}"
                f"QPushButton:hover {{ color:{C_RED}; }}")
            del_btn.clicked.connect(lambda _, idx=i: self._deletar_fato(idx))
            top_row.addWidget(del_btn)
            cl.addLayout(top_row)

            tx = QLabel(fato[:60] + ("…" if len(fato) > 60 else ""))
            tx.setFont(QFont("Segoe UI", 7)); tx.setWordWrap(True)
            tx.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
            cl.addWidget(tx); cl.addStretch()
            self._mem_grid.addWidget(card, i // 2, i % 2)

    def _deletar_fato(self, idx: int):
        """Remove um fato pelo índice e recarrega o painel."""
        try:
            import memoria as _mem
            _mem.remover_fato_por_indice(idx)
        except Exception as e:
            print(f"[MEMORIA] Erro ao deletar fato: {e}")
        self._carregar_memoria()

    def _abrir_dialogo_adicionar_fato(self):
        """Abre um mini-diálogo inline para adicionar um fato manualmente."""
        from PyQt6.QtWidgets import QDialog, QLineEdit, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle("Adicionar fato à memória")
        dlg.setFixedSize(380, 140)
        dlg.setStyleSheet(f"""
            QDialog {{ background:{BG_CARD}; border:1px solid {BORDER}; border-radius:10px; }}
            QLabel  {{ color:{C_TEXT}; background:transparent; }}
            QLineEdit {{
                background:{BG_INPUT}; color:{C_TEXT};
                border:1px solid {BORDER}; border-radius:6px;
                padding:6px 10px; font-size:10pt;
            }}
            QLineEdit:focus {{ border-color:{PURPLE}; }}
            QPushButton {{
                background:{PURPLE}; color:white; border:none;
                border-radius:6px; padding:6px 16px; font-weight:bold;
            }}
            QPushButton:hover {{ background:{PURPLE_DK}; }}
            QPushButton[text="Cancelar"] {{
                background:{BORDER}; color:{C_TEXT2};
            }}
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16,14,16,14); lay.setSpacing(10)

        lbl = QLabel("O que a Emily deve lembrar?")
        lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lay.addWidget(lbl)

        campo = QLineEdit()
        campo.setPlaceholderText("Ex: Gosta de café forte pela manhã")
        campo.setFont(QFont("Segoe UI", 10))
        lay.addWidget(campo)

        btns = QDialogButtonBox()
        btn_ok     = QPushButton("Salvar")
        btn_cancel = QPushButton("Cancelar")
        btns.addButton(btn_ok,     QDialogButtonBox.ButtonRole.AcceptRole)
        btns.addButton(btn_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        lay.addWidget(btns)

        campo.setFocus()

        if dlg.exec() == QDialog.DialogCode.Accepted:
            fato = campo.text().strip()
            if fato:
                try:
                    import memoria as _mem
                    adicionado = _mem.adicionar_fato(fato)
                    if adicionado:
                        self._carregar_memoria()
                except Exception as e:
                    print(f"[MEMORIA] Erro ao adicionar fato: {e}")

    # ── Centro ─────────────────────────────────────────────────

    # O _build_center antigo foi removido: ele montava avatar, barra de 4
    # estados, chat e input numa coluna só, e era a razão do chat ter ~350px de
    # largura útil. O avatar virou a página de início; o chat virou tela cheia.

    def _carregar_imagem_emily(self):
        candidatos = [
            os.path.join(DIR_BASE, "emilyimage.png"),
            os.path.join(DIR_BASE, "emily.png"),
            os.path.join(DIR_BASE, "emily.jpg"),
            os.path.join(DIR_IMG, "emilyimage.png"),
            os.path.join(DIR_IMG, "emily.png"),
        ]
        SZ = 160
        for path in candidatos:
            if not os.path.exists(path): continue
            try:
                src = QPixmap(path)
                if src.isNull(): continue
                sc = src.scaled(SZ, SZ,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                ox = max(0,(sc.width()-SZ)//2); oy = max(0,(sc.height()-SZ)//2)
                if sc.width()>SZ or sc.height()>SZ:
                    sc = sc.copy(ox,oy,SZ,SZ)
                out = QPixmap(SZ,SZ); out.fill(Qt.GlobalColor.transparent)
                pp = QPainter(out); pp.setRenderHint(QPainter.RenderHint.Antialiasing)
                clip = QPainterPath(); clip.addEllipse(0,0,SZ,SZ)
                pp.setClipPath(clip); pp.drawPixmap(0,0,sc); pp.end()
                self._emily_lbl.setFixedSize(SZ,SZ)
                self._emily_lbl.setPixmap(out)
                self._emily_lbl.setStyleSheet(
                    f"background:transparent; border:2.5px solid {PURPLE}; border-radius:{SZ//2}px;")
                return
            except Exception as ex:
                print(f"[IMG] {path}: {ex}")
        self._emily_lbl.setPixmap(_make_circle_pixmap(160,PURPLE_DIM,"E","#fff",50))
        self._emily_lbl.setFixedSize(160,160)

    # A _build_status_bar foi removida: a tira de quatro estados
    # (Aguardando/Ouvindo/Pensando/Falando) ocupava 48px de altura pra dizer o
    # que a pílula da barra de título diz num canto. O que ela fazia de útil —
    # mostrar o estado — continua; o que ela fazia de ruim — comer altura do chat
    # e deixar três rótulos apagados na tela o tempo todo — não.

    def _update_status_dots(self, estado):
        # A barra de 4 estados saiu do layout novo (o estado agora é a pílula da
        # barra de título). A função fica, tolerante a lista vazia, porque o
        # _on_status_changed chama ela a cada mudança e quebrar aqui derrubaria
        # TODA atualização de status.
        if not getattr(self, "_status_dots", None):
            return
        idx = STATUS_TO_DOT.get(estado, 0)
        for i,dot in enumerate(self._status_dots):
            if i==idx:
                dot.setStyleSheet(f"color:{PURPLE_LT}; background:{PURPLE_DIM}; border:none; font-weight:bold; border-radius:4px;")
            else:
                dot.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")

    def _build_chat_area(self):
        sc = QScrollArea(); sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Mesmo fundo da página (BG_CENTER, não BG_MAIN): eram dois tons de quase
        # preto diferentes um dentro do outro, e a costura aparecia como uma
        # faixa mais clara na beirada do chat.
        sc.setStyleSheet(f"""
            QScrollArea {{ background:{BG_CENTER}; border:none; }}
            QScrollBar:vertical {{ width:6px; background:transparent; margin:4px 2px; }}
            QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:3px;
                                          min-height:30px; }}
            QScrollBar::handle:vertical:hover {{ background:{PURPLE_DIM}; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
            QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
        """)
        self._chat_widget = QWidget()
        self._chat_widget.setStyleSheet(f"background:{BG_CENTER};")

        # Coluna centralizada com teto de largura, pelo mesmo _na_coluna() que o
        # cabeçalho e o input usam — é o que mantém os três alinhados.
        fora = QVBoxLayout(self._chat_widget)
        fora.setContentsMargins(0, 16, 0, 16)
        fora.setSpacing(0)
        coluna = QWidget()
        coluna.setStyleSheet("background:transparent;")
        self._chat_layout = QVBoxLayout(coluna)
        self._chat_layout.setContentsMargins(0, 0, 0, 0)
        self._chat_layout.setSpacing(2)
        self._chat_layout.addStretch()
        fora.addWidget(self._na_coluna(coluna))

        sc.setWidget(self._chat_widget); self._chat_scroll = sc
        # Nenhuma mensagem de boas-vindas aqui.
        #
        # Duas razões. A saudação já é a página de início ("Oi, Vitor. No que a
        # gente mexe agora?"), e repetir ela como bolha era ruído. E a técnica:
        # _add_chat_msg agora GRAVA no disco, então uma bolha criada durante a
        # montagem da tela criava uma conversa vazia chamada "Conversa nova" a
        # cada boot da Emily.
        return sc

    # ── Área de preview de arquivos/imagens pendentes ──────────

    def _build_preview_area(self):
        """Área horizontal rolável com thumbnails dos arquivos pendentes."""
        self._preview_scroll = QScrollArea()
        self._preview_scroll.setFixedHeight(72)
        self._preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._preview_scroll.setWidgetResizable(True)
        self._preview_scroll.setStyleSheet(f"""
            QScrollArea {{ background:transparent; border:none; }}
            QScrollBar:horizontal {{ height:3px; background:{BG_INPUT}; }}
            QScrollBar::handle:horizontal {{ background:{BORDER}; border-radius:2px; }}
        """)
        self._preview_inner = QWidget()
        self._preview_inner.setStyleSheet("background:transparent;")
        self._preview_hlay = QHBoxLayout(self._preview_inner)
        self._preview_hlay.setContentsMargins(0,4,0,4)
        self._preview_hlay.setSpacing(6)
        self._preview_hlay.addStretch()
        self._preview_scroll.setWidget(self._preview_inner)
        self._preview_scroll.setVisible(False)   # escondido até ter arquivos
        return self._preview_scroll

    def _build_input_area(self):
        # Inicializa a lista de arquivos pendentes
        self._arquivos_pendentes = []   # lista de dicts: {id, path, is_image, widget}
        self._prox_arq_id = 0

        area = QFrame()
        area.setStyleSheet("background:transparent; border:none;")
        lay = QVBoxLayout(area)
        lay.setContentsMargins(20, 10, 20, 14)
        lay.setSpacing(7)

        # ── Área de preview (aparece acima do input quando há arquivos) ──
        lay.addWidget(self._build_preview_area())

        # ── Caixa de input ──
        #
        # Uma caixa só, arredondada, com os ícones alinhados EMBAIXO. Alinhar em
        # cima era o que fazia o 📎 subir junto quando o texto crescia pra duas
        # linhas, e era metade da sensação de "espaçamento bugado".
        self._caixa_input = QFrame()
        self._caixa_input.setObjectName("caixa_input")
        self._pintar_caixa_input(False)
        self._caixa_input.setAcceptDrops(True)
        self._caixa_input.dragEnterEvent = self._drag_enter_input
        self._caixa_input.dropEvent = self._drop_input
        bl = QHBoxLayout(self._caixa_input)
        bl.setContentsMargins(9, 7, 9, 7)
        bl.setSpacing(3)

        embaixo = Qt.AlignmentFlag.AlignBottom

        self._btn_anexo = self._botao_input(
            "📎", "Anexar arquivo (ou Ctrl+V pra colar imagem)")
        self._btn_anexo.clicked.connect(self._abrir_arquivo)
        bl.addWidget(self._btn_anexo, 0, embaixo)

        # Os botões "🎁 Extras" e "✨ Magia" saíram: os dois eram enfeite com
        # tooltip e nenhum clique ligado em nada. Ícone que não faz nada é pior
        # que ícone nenhum, porque ensina o Vitor a desconfiar dos outros.

        self._campo_texto = QTextEdit()
        self._campo_texto.setFixedHeight(34)
        self._campo_texto.setFont(QFont("Segoe UI", 10))
        # SÓ TEXTO PURO. Este é o conserto do "fica todo preto bugado quando eu
        # copio e colo".
        #
        # QTextEdit aceita rich text por padrão, então Ctrl+V de qualquer lugar
        # (navegador, Word, outro chat) traz o HTML original junto — inclusive a
        # COR do texto e o fundo de onde ele veio. Texto que era preto sobre
        # branco na origem chega preto sobre o nosso fundo quase preto e some.
        # A folha de estilo não salva: cor inline no documento ganha do
        # stylesheet do widget. Recusando rich text, a colagem entra como texto e
        # herda a cor do tema.
        self._campo_texto.setAcceptRichText(False)
        self._campo_texto.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._campo_texto.setStyleSheet(
            f"QTextEdit {{ background:transparent; color:{C_TEXT}; border:none; "
            f"padding:6px 4px; selection-background-color:{PURPLE}; }}")
        self._campo_texto.setPlaceholderText("Fala com a Emily…")
        self._campo_texto.installEventFilter(self)
        # Cresce com o texto até um teto, como em qualquer chat de IA. Sem isso a
        # mensagem de três linhas rola dentro de uma fresta de 38px.
        self._campo_texto.textChanged.connect(self._ajustar_altura_input)
        bl.addWidget(self._campo_texto, 1)

        self._btn_cam = self._botao_input("📷", "Ligar/desligar a visão da tela")
        self._btn_cam.clicked.connect(self._capturar_tela)
        bl.addWidget(self._btn_cam, 0, embaixo)

        self._btn_mic = self._botao_input("🎤", "Falar (push to talk)",
                                         destaque=True)
        self._btn_mic.clicked.connect(self._ativar_ptt)
        bl.addWidget(self._btn_mic, 0, embaixo)

        self._btn_enviar = self._botao_input("➤", "Enviar (Enter)",
                                            destaque=True)
        self._btn_enviar.clicked.connect(self._enviar)
        bl.addWidget(self._btn_enviar, 0, embaixo)

        lay.addWidget(self._caixa_input)

        dica = QLabel("Enter envia · Shift+Enter quebra linha · Ctrl+V cola imagem")
        dica.setFont(QFont("Segoe UI", 7))
        dica.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dica.setStyleSheet(
            f"color:{C_TEXT3}; background:transparent; border:none;")
        lay.addWidget(dica)
        return area

    def _botao_input(self, texto, dica="", destaque=False):
        """Botão redondo da barra de digitação. Um lugar só define o tamanho."""
        b = QPushButton(texto)
        b.setFixedSize(32, 32)
        b.setToolTip(dica)
        b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        b.setFont(QFont("Segoe UI Emoji" if not texto.isascii() else "Segoe UI",
                        11 if not texto.isascii() else 10,
                        QFont.Weight.Bold))
        if destaque:
            b.setStyleSheet(
                f"QPushButton {{ background:{PURPLE}; color:#fff; border:none; "
                f"border-radius:16px; }}"
                f"QPushButton:hover {{ background:{PURPLE_DK}; }}"
                f"QPushButton:pressed {{ background:{PURPLE_DK}; }}")
        else:
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{C_TEXT2}; "
                f"border:none; border-radius:16px; }}"
                f"QPushButton:hover {{ background:{PURPLE_DIM}; color:{C_TEXT}; }}")
        return b

    def _pintar_caixa_input(self, focada: bool):
        """Anel roxo quando o cursor está na caixa. Custa nada e situa."""
        self._caixa_input.setStyleSheet(
            f"QFrame#caixa_input {{ background:{BG_INPUT}; "
            f"border:1px solid {PURPLE if focada else BORDER}; "
            f"border-radius:16px; }}")

    def _ajustar_altura_input(self):
        """Altura do campo acompanha o texto, entre uma linha e ~5."""
        try:
            doc = self._campo_texto.document()
            doc.setTextWidth(self._campo_texto.viewport().width())
            alta = int(doc.size().height()) + 14
            self._campo_texto.setFixedHeight(max(34, min(122, alta)))
        except Exception:
            pass

    # ── Gerenciamento de arquivos pendentes ─────────────────────

    def _adicionar_arquivo_pendente(self, path: str):
        """Adiciona um arquivo à fila de staging e cria seu card de preview."""
        if len(self._arquivos_pendentes) >= 10:
            return  # limite de 10 arquivos
        arq_id = self._prox_arq_id
        self._prox_arq_id += 1
        ext = os.path.splitext(path)[1].lower()
        is_image = ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")

        item = {"id": arq_id, "path": path, "is_image": is_image, "widget": None}
        self._arquivos_pendentes.append(item)

        # ── Cria o card de preview ──
        card = QFrame()
        card.setFixedSize(62, 62)
        card.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid {PURPLE}; border-radius:8px;")
        card.setObjectName(f"arq_card_{arq_id}")

        cl = QVBoxLayout(card); cl.setContentsMargins(3,3,3,3); cl.setSpacing(2)

        if is_image:
            pix = QPixmap(path).scaled(
                54, 42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            img_lbl = QLabel(); img_lbl.setPixmap(pix)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet("background:transparent; border:none;")
            cl.addWidget(img_lbl, 1)
        else:
            icon_map = {
                ".pdf": "📄", ".py": "🐍", ".js": "📜", ".ts": "📜",
                ".html": "🌐", ".css": "🎨", ".json": "📋",
                ".txt": "📃", ".md": "📃", ".zip": "🗜", ".rar": "🗜",
            }
            ico_lbl = QLabel(icon_map.get(ext, "📎"))
            ico_lbl.setFont(QFont("Segoe UI Emoji", 18))
            ico_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ico_lbl.setStyleSheet("background:transparent; border:none;")
            cl.addWidget(ico_lbl, 1)

        # Nome do arquivo truncado
        nome_lbl = QLabel(os.path.basename(path)[:9] + ("…" if len(os.path.basename(path)) > 9 else ""))
        nome_lbl.setFont(QFont("Segoe UI", 6))
        nome_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nome_lbl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        cl.addWidget(nome_lbl)

        # Botão X (overlay no canto superior direito)
        btn_x = QPushButton("✕", card)
        btn_x.setFixedSize(16, 16)
        btn_x.move(46, 0)
        btn_x.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_x.setStyleSheet(
            f"QPushButton {{ background:{C_RED}; color:white; border-radius:8px; "
            f"border:none; font-size:8pt; font-weight:bold; }}"
            f"QPushButton:hover {{ background:#c0392b; }}")
        btn_x.clicked.connect(lambda _, aid=arq_id: self._remover_arquivo_pendente(aid))

        item["widget"] = card

        # Insere antes do stretch
        count = self._preview_hlay.count()
        self._preview_hlay.insertWidget(count - 1, card)
        self._atualizar_preview_visibilidade()

    def _remover_arquivo_pendente(self, arq_id: int):
        """Remove um arquivo pendente pelo id e destrói seu widget."""
        for i, item in enumerate(self._arquivos_pendentes):
            if item["id"] == arq_id:
                w = item.get("widget")
                if w:
                    self._preview_hlay.removeWidget(w)
                    w.setParent(None)
                    w.deleteLater()
                self._arquivos_pendentes.pop(i)
                break
        self._atualizar_preview_visibilidade()

    def _atualizar_preview_visibilidade(self):
        """Mostra ou esconde a preview area conforme houver arquivos pendentes."""
        tem = len(self._arquivos_pendentes) > 0
        self._preview_scroll.setVisible(tem)
        # Atualiza visual do botão de anexo
        self._btn_anexo.setStyleSheet(
            f"background:transparent; color:{PURPLE_LT if tem else C_TEXT2}; border:none;"
        )

    def _limpar_arquivos_pendentes(self):
        """Remove todos os arquivos pendentes e limpa a área de preview."""
        for item in self._arquivos_pendentes:
            w = item.get("widget")
            if w:
                self._preview_hlay.removeWidget(w)
                w.setParent(None)
                w.deleteLater()
        self._arquivos_pendentes.clear()
        self._atualizar_preview_visibilidade()

    # ── Drag & Drop na caixa de input ───────────────────────────

    def _drag_enter_input(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def _drop_input(self, e):
        if e.mimeData().hasUrls():
            for url in e.mimeData().urls():
                path = url.toLocalFile()
                if path and os.path.isfile(path):
                    self._adicionar_arquivo_pendente(path)
            e.acceptProposedAction()
        elif e.mimeData().hasImage():
            self._colar_imagem_do_clipboard_mime(e.mimeData())
            e.acceptProposedAction()

    # ── Clipboard paste (Ctrl+V) ────────────────────────────────

    def _colar_imagem_do_clipboard_mime(self, mime: QMimeData):
        """Salva a imagem do clipboard/drag como arquivo temporário e adiciona ao staging."""
        pix = QPixmap()
        if not pix.loadFromData(mime.data("image/png")):
            img = mime.imageData()
            if img is None:
                return
            pix = QPixmap.fromImage(img)
        if pix.isNull():
            return
        import tempfile, time as _time
        tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads_emily")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"clipboard_{int(_time.time()*1000)}.png")
        pix.save(tmp_path, "PNG")
        self._adicionar_arquivo_pendente(tmp_path)

    # ── Sidebar direita ─────────────────────────────────────────

    def _build_right_sidebar(self):
        side = QWidget(); side.setFixedWidth(290)
        side.setStyleSheet(f"background:{BG_SIDEBAR};")
        sc = QScrollArea(); sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet(f"""
            QScrollArea {{ background:{BG_SIDEBAR}; border:none; }}
            QScrollBar:vertical {{ width:4px; background:{BG_SIDEBAR}; }}
            QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:2px; }}
        """)
        inner = QWidget(); inner.setStyleSheet(f"background:{BG_SIDEBAR};")
        lay = QVBoxLayout(inner); lay.setContentsMargins(10,10,10,10); lay.setSpacing(6)
        lay.addWidget(self._sec("Apps Rápidos")); lay.addWidget(self._build_apps()); lay.addWidget(self._hsep())
        lay.addWidget(self._sec("Automação")); lay.addWidget(self._build_automacao()); lay.addWidget(self._hsep())
        lay.addWidget(self._sec("Modos",plus=True)); lay.addWidget(self._build_modos()); lay.addWidget(self._hsep())
        lay.addWidget(self._sec("Macros",plus=True)); lay.addWidget(self._build_macros()); lay.addWidget(self._hsep())
        lay.addWidget(self._sec("TV")); lay.addWidget(self._build_tv()); lay.addWidget(self._hsep())
        lay.addWidget(self._sec("Sistema")); lay.addWidget(self._build_sistema())
        lay.addStretch(); sc.setWidget(inner)
        ol = QVBoxLayout(side); ol.setContentsMargins(0,0,0,0); ol.addWidget(sc)
        return side

    def _sec(self, title, plus=False):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(2,4,2,0)
        lb = QLabel(title); lb.setFont(QFont("Segoe UI",10,QFont.Weight.Bold))
        lb.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        lay.addWidget(lb); lay.addStretch()
        if plus:
            p = QPushButton("＋"); p.setFixedSize(22,22)
            p.setStyleSheet(f"background:transparent; color:{PURPLE_LT}; border:none; font-size:13pt;")
            lay.addWidget(p)
        return w

    def _build_apps(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        g = QGridLayout(w); g.setSpacing(5); g.setContentsMargins(0,0,0,0)
        for i, (exe, nm, key, bg, lt) in enumerate(APP_DATA):
            pix  = _icone_app(exe, bg, lt, size=38)
            tile = AppTile(pix, nm)
            tile.clicked.connect(
                lambda k=key: threading.Thread(target=self._abrir_app, args=(k,), daemon=True).start()
            )
            g.addWidget(tile, i // 3, i % 3)
        return w

    def _abrir_app(self, key):
        try:
            import automacao; automacao.executar_comando(f"abre o {key}")
        except Exception as e: print(f"[APP] {key}: {e}")

    def _build_automacao(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        def row(ic,txt,arrow=True,right=None):
            f = QFrame()
            f.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:6px;")
            f.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            rl = QHBoxLayout(f); rl.setContentsMargins(10,9,10,9)
            il = QLabel(ic); il.setFont(QFont("Segoe UI Emoji",13))
            il.setStyleSheet("background:transparent; border:none;"); rl.addWidget(il)
            tl = QLabel(txt); tl.setFont(QFont("Segoe UI",9))
            tl.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;"); rl.addWidget(tl,1)
            if right: rl.addWidget(right)
            elif arrow:
                ar = QLabel("›"); ar.setFont(QFont("Segoe UI",16))
                ar.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;"); rl.addWidget(ar)
            return f
        r1 = row("📁","Organizar Downloads")
        r1.mousePressEvent = lambda e: threading.Thread(target=self._cmd_organizar,daemon=True).start()
        lay.addWidget(r1)

        self._toggle_sw = ToggleSwitch(); self._toggle_sw.set_state(self._monitor_dl_ativo)
        self._toggle_sw.toggled.connect(self._toggle_monitor)
        lay.addWidget(row("📊","Monitorar Downloads",arrow=False,right=self._toggle_sw))

        # Toggle monitoramento Discord ─────────────────────────
        discord_inicial = self._discord_monitor_ativo()
        self._toggle_discord = ToggleSwitch()
        self._toggle_discord.set_state(discord_inicial)
        self._toggle_discord.toggled.connect(self._toggle_discord_monitor)
        lay.addWidget(row("💬","Monitorar Discord",arrow=False,right=self._toggle_discord))

        try:
            import preferencias
            autonomia_inicial = bool(preferencias.obter("autonomia_experimental", False))
        except Exception:
            autonomia_inicial = False
        self._toggle_autonomia = ToggleSwitch()
        self._toggle_autonomia.set_state(autonomia_inicial)
        self._toggle_autonomia.toggled.connect(self._toggle_autonomia_experimental)
        lay.addWidget(row("⚡", "Autonomia experimental", arrow=False,
                          right=self._toggle_autonomia))

        # O mesmo trio da interface web. São independentes de propósito: dá pra
        # comparar Whisper cru, RNNoise, loudnorm e Silero sem editar o .env.
        for atributo, chave, icone, rotulo in (
            ("_toggle_audio_denoise", "audio_preprocess_denoise", "🎙️",
             "Redução de ruído (RNNoise)"),
            ("_toggle_audio_normalize", "audio_preprocess_normalize", "🔊",
             "Normalizar volume"),
            ("_toggle_audio_vad", "audio_preprocess_vad", "✂️",
             "Cortar silêncio (Silero VAD)"),
        ):
            try:
                ligado = bool(preferencias.obter(chave, True))
            except Exception:
                ligado = True
            toggle = ToggleSwitch()
            toggle.set_state(ligado)
            toggle.toggled.connect(
                lambda on, chave=chave: self._toggle_audio_preprocess(chave, on))
            setattr(self, atributo, toggle)
            lay.addWidget(row(icone, rotulo, arrow=False, right=toggle))

        lay.addWidget(row("📂","Atalhos de Pastas"))
        return w

    def _discord_monitor_ativo(self) -> bool:
        """Lê o estado atual do Event _escuta_discord_ativa."""
        try:
            import discord_bot
            return discord_bot._escuta_discord_ativa.is_set()
        except Exception:
            return False

    def _toggle_discord_monitor(self, on: bool):
        """Ativa/desativa o monitoramento de chats do Discord."""
        def _r():
            try:
                import discord_bot
                if on:
                    discord_bot.ativar_escuta_discord()
                else:
                    discord_bot.desativar_escuta_discord()
            except Exception as e:
                print(f"[Discord] toggle monitor: {e}")
        threading.Thread(target=_r, daemon=True).start()

    def _toggle_autonomia_experimental(self, on: bool):
        try:
            import preferencias
            preferencias.definir(autonomia_experimental=bool(on))
            print(f"[AUTONOMIA] modo experimental {'ATIVADO' if on else 'DESATIVADO'} pela interface.")
        except Exception as e:
            print(f"[AUTONOMIA] não salvei preferência: {e}")

    def _toggle_audio_preprocess(self, chave: str, on: bool):
        try:
            import preferencias
            preferencias.definir(**{chave: bool(on)})
            print(f"[AUDIO-PRE] {chave} {'ATIVADO' if on else 'DESATIVADO'} pela interface.")
        except Exception as e:
            print(f"[AUDIO-PRE] não salvei {chave}: {e}")

    def _cmd_organizar(self):
        try:
            import automacao; automacao._organizar_downloads_fn()
        except Exception as e: print(f"[AUTO] {e}")

    def _toggle_monitor(self, on):
        self._monitor_dl_ativo = on
        def _r():
            try:
                import automacao
                if on: automacao.iniciar_monitor_downloads()
                else:  automacao.parar_monitor_downloads()
            except Exception as e: print(f"[AUTO] monitor: {e}")
        threading.Thread(target=_r,daemon=True).start()

    def _build_modos(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        modos = []
        try:
            p = Path.home()/".emily_modos.json"
            if p.exists():
                dados = json.loads(p.read_text(encoding="utf-8"))
                for k,v in dados.items():
                    modos.append((v.get("nome",k),v.get("descricao",""),k))
        except Exception: pass
        if not modos:
            modos = [("Gameplay","Otimizado para jogos","gameplay"),("Programação","Focado em desenvolvimento","programacao")]
        icons_m = [
            _make_circle_pixmap(28,"#5865F2","🎮","#fff",10),
            _make_circle_pixmap(28,"#007ACC","</>","#fff",7),
            _make_circle_pixmap(28,"#1DB954","📚","#fff",10),
            _make_circle_pixmap(28,PURPLE_DK,"🎨","#fff",10),
        ]
        for i,(nome,desc,chave) in enumerate(modos[:4]):
            f = QFrame()
            f.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:6px;")
            fl = QHBoxLayout(f); fl.setContentsMargins(10,8,10,8); fl.setSpacing(8)
            ic = QLabel(); ic.setFixedSize(28,28); ic.setScaledContents(True)
            ic.setStyleSheet("background:transparent; border:none;")
            ic.setPixmap(icons_m[i%len(icons_m)]); fl.addWidget(ic)
            info = QVBoxLayout(); info.setSpacing(1)
            n = QLabel(nome); n.setFont(QFont("Segoe UI",9,QFont.Weight.Bold))
            n.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
            d = QLabel(desc[:36]); d.setFont(QFont("Segoe UI",7))
            d.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
            info.addWidget(n); info.addWidget(d); fl.addLayout(info,1)
            btn = QPushButton("Ativar"); btn.setFixedSize(62,26)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(btn_style())
            btn.clicked.connect(lambda _,k=chave,b=btn: threading.Thread(target=self._ativar_modo,args=(k,b),daemon=True).start())
            fl.addWidget(btn); lay.addWidget(f)
        return w

    def _ativar_modo(self, chave, btn_w):
        try:
            import automacao; automacao._ativar_modo(chave)
            def _u():
                btn_w.setText("✓ Ativo"); btn_w.setStyleSheet(btn_style(bg=C_GREEN,hover=C_GREEN))
                QTimer.singleShot(3000, lambda: (btn_w.setText("Ativar"), btn_w.setStyleSheet(btn_style())))
            QTimer.singleShot(0,_u)
        except Exception as e: print(f"[MODO] {e}")

    def _build_macros(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        macros = []
        try:
            p = Path.home()/".emily_speedruns.json"
            if p.exists():
                dados = json.loads(p.read_text(encoding="utf-8"))
                for k,v in dados.items():
                    macros.append((v.get("nome",k),k))
        except Exception: pass
        if not macros:
            macros = [("Iniciar stream","1"),("Backup projetos","2"),("Limpar sistema","3")]
        icons_s = ["📡","💾","🧹","⚡"]
        for i,(nome,num) in enumerate(macros[:4]):
            ic_pix = _make_circle_pixmap(22,PURPLE_DIM,icons_s[i%len(icons_s)],PURPLE_LT,9)
            mr = MacroRow(ic_pix,nome)
            mr.play_clicked.connect(lambda n=num: threading.Thread(target=self._iniciar_speedrun,args=(n,),daemon=True).start())
            mr.pause_clicked.connect(lambda: threading.Thread(target=self._pausar_speedrun,daemon=True).start())
            mr.stop_clicked.connect(lambda: threading.Thread(target=self._parar_speedrun,daemon=True).start())
            lay.addWidget(mr)
        return w

    def _iniciar_speedrun(self,n):
        try:
            import automacao; automacao.iniciar_speedrun(str(n))
        except Exception as e: print(f"[MACRO] play: {e}")

    def _pausar_speedrun(self):
        try:
            import automacao; automacao.pausar_speedrun()
        except Exception as e: print(f"[MACRO] pause: {e}")

    def _parar_speedrun(self):
        try:
            import automacao; automacao.parar_speedrun()
        except Exception as e: print(f"[MACRO] stop: {e}")

    # ── Seção TV (dispositivos salvos, pareamento e conexão) ─────

    def _build_tv(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(w); lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)

        topo = QHBoxLayout(); topo.setContentsMargins(0,0,0,0)
        topo.addStretch()
        add = QPushButton("＋ Adicionar")
        add.setStyleSheet(f"background:transparent; color:{PURPLE_LT}; border:none; font-size:8pt;")
        add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        add.clicked.connect(self._tv_dialogo_adicionar)
        topo.addWidget(add)
        lay.addLayout(topo)

        # container que segura a lista — permite limpar e reconstruir
        self._tv_container = QWidget()
        self._tv_container.setStyleSheet("background:transparent;")
        self._tv_layout = QVBoxLayout(self._tv_container)
        self._tv_layout.setContentsMargins(0,0,0,0)
        self._tv_layout.setSpacing(4)
        lay.addWidget(self._tv_container)

        self._tv_status_lbl = QLabel("")
        self._tv_status_lbl.setFont(QFont("Segoe UI", 8))
        self._tv_status_lbl.setWordWrap(True)
        self._tv_status_lbl.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
        lay.addWidget(self._tv_status_lbl)

        self._carregar_tv()
        return w

    def _carregar_tv(self):
        """Limpa e reconstrói a lista de TVs a partir do controle_tv."""
        while self._tv_layout.count():
            item = self._tv_layout.takeAt(0)
            wdg = item.widget() if item else None
            if wdg is not None:
                wdg.setParent(None)
                wdg.deleteLater()
        try:
            import controle_tv as tv
            dispositivos = tv.listar_dispositivos()
        except Exception as e:
            aviso = QLabel(f"Controle de TV indisponível: {e}")
            aviso.setWordWrap(True)
            aviso.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            self._tv_layout.addWidget(aviso)
            return
        if not dispositivos:
            vazio = QLabel("Nenhuma TV salva. Adicione o IP dela.")
            vazio.setFont(QFont("Segoe UI", 8))
            vazio.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            self._tv_layout.addWidget(vazio)
            return
        for d in dispositivos:
            self._tv_layout.addWidget(self._tv_row(d))

    def _tv_row(self, d: dict) -> QFrame:
        """Card de uma TV salva: clique conecta; ✎ edita; × remove."""
        card = QFrame()
        selecionada = bool(d.get("ativa"))
        card.setStyleSheet(
            f"background:{BG_CARD}; border:1px solid "
            f"{PURPLE if selecionada else BORDER}; border-radius:8px;")
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rl = QHBoxLayout(card); rl.setContentsMargins(9,7,7,7); rl.setSpacing(6)

        cl = QVBoxLayout(); cl.setContentsMargins(0,0,0,0); cl.setSpacing(1)
        tl = QLabel(d.get("nome") or "TV")
        tl.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        tl.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        cl.addWidget(tl)
        tipo = f" · {d['tipo']}" if d.get("tipo") else ""
        pareada = "pareada" if d.get("pareada") else "não pareada"
        sub = QLabel(f"{d.get('ip','')}{tipo} · {pareada}")
        sub.setFont(QFont("Segoe UI", 8))
        sub.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        cl.addWidget(sub)
        rl.addLayout(cl, 1)

        # clique no corpo (nome/IP) conecta; os botões ficam por cima
        card.mousePressEvent = lambda _e, did=d["id"]: self._tv_conectar(did)

        ed = QPushButton("✎"); ed.setFixedSize(20, 20)
        ed.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:10pt; }}"
            f"QPushButton:hover {{ color:{PURPLE_LT}; }}")
        ed.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ed.setToolTip("Editar nome, IP e tipo")
        ed.clicked.connect(lambda _, did=d["id"]: self._tv_dialogo_editar(did))
        rl.addWidget(ed)

        rm = QPushButton("×"); rm.setFixedSize(20, 20)
        rm.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:11pt; }}"
            f"QPushButton:hover {{ color:{C_RED}; }}")
        rm.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        rm.setToolTip("Remover da lista")
        rm.clicked.connect(lambda _, did=d["id"]: self._tv_remover(did))
        rl.addWidget(rm)
        return card

    def _tv_thread(self, alvo, *args):
        """Roda um método do controle_tv fora da UI e devolve o resultado."""
        import controle_tv as tv
        return getattr(tv, alvo)(*args)

    def _tv_conectar(self, id_dispositivo: str):
        """Conecta fora da thread da UI; o resultado volta por QTimer.singleShot."""
        self._tv_status("Conectando…")
        def trabalho():
            import controle_tv as tv
            r = tv.conectar_dispositivo(id_dispositivo)
            def atualizar():
                if r.get("ok"):
                    self._tv_status(r.get("mensagem", "Conectada ✓"), ok=True)
                elif r.get("precisa_parear"):
                    self._tv_status("Precisa parear — confirme o IP em ✎ e use "
                                    "'Parear na TV'.")
                else:
                    self._tv_status(r.get("mensagem", "Falhou"), erro=True)
                self._carregar_tv()
            QTimer.singleShot(0, atualizar)
        threading.Thread(target=trabalho, daemon=True).start()

    def _tv_status(self, texto: str, ok: bool = False, erro: bool = False):
        cor = C_GREEN if ok else (C_RED if erro else C_TEXT2)
        self._tv_status_lbl.setStyleSheet(
            f"color:{cor}; background:transparent; border:none;")
        self._tv_status_lbl.setText(texto)

    def _tv_dialogo_adicionar(self):
        dlg, f_nome, f_ip, f_tipo, botoes = self._tv_dialogo_campos(None)
        from PyQt6.QtWidgets import QPushButton

        def salvar_e_fechar(quer_parear: bool):
            nome, ip, tipo = f_nome.text().strip(), f_ip.text().strip(), f_tipo.text().strip()
            if not ip:
                self._tv_status("Informe o IP da TV.", erro=True)
                return
            try:
                import controle_tv as tv
                d = tv.salvar_dispositivo(nome, ip, tipo)
            except ValueError as e:
                self._tv_status(str(e), erro=True)
                return
            dlg.accept()
            self._carregar_tv()
            if quer_parear:
                self._tv_parear(d["id"])
            else:
                self._tv_status(f"TV salva: {d['nome']} ({d['ip']})", ok=True)

        b_parear = QPushButton("Salvar e parear")
        b_parear.setProperty("secundario", True)
        b_parear.clicked.connect(lambda: salvar_e_fechar(True))
        botoes.addWidget(b_parear)
        b_salvar = QPushButton("Salvar")
        b_salvar.clicked.connect(lambda: salvar_e_fechar(False))
        botoes.addWidget(b_salvar)
        dlg.layout().addLayout(botoes)
        dlg.exec()

    def _tv_dialogo_editar(self, id_dispositivo: str):
        import controle_tv as tv
        d = tv._achar_dispositivo(id_dispositivo)
        if not d:
            self._tv_status("Dispositivo não encontrado.", erro=True)
            return
        dlg, f_nome, f_ip, f_tipo, botoes = self._tv_dialogo_campos(d)
        from PyQt6.QtWidgets import QPushButton

        def salvar():
            try:
                tv.editar_dispositivo(id_dispositivo, f_nome.text(),
                                      f_ip.text(), f_tipo.text())
            except ValueError as e:
                self._tv_status(str(e), erro=True)
                return
            dlg.accept()
            self._carregar_tv()
            self._tv_status("TV atualizada ✓", ok=True)

        b_parear = QPushButton("Parear na TV")
        b_parear.setProperty("secundario", True)
        b_parear.setToolTip("A TV vai mostrar um código; digite-o no próximo passo")
        b_parear.clicked.connect(lambda: (dlg.accept(), self._tv_parear(id_dispositivo)))
        botoes.addWidget(b_parear)
        b_salvar = QPushButton("Salvar")
        b_salvar.clicked.connect(salvar)
        botoes.addWidget(b_salvar)
        dlg.layout().addLayout(botoes)
        dlg.exec()

    def _tv_remover(self, id_dispositivo: str):
        import controle_tv as tv
        r = tv.remover_dispositivo(id_dispositivo)
        if r.startswith("ERRO"):
            self._tv_status(r, erro=True)
        else:
            self._tv_status("TV removida da lista.", ok=True)
        self._carregar_tv()

    def _tv_parear(self, id_dispositivo: str):
        """Fluxo em duas etapas: pede o código à TV; o Vitor digita; a
        conclusão roda fora da thread da UI."""
        self._tv_status("Pedindo código à TV…")
        def trabalho():
            import controle_tv as tv
            r = tv.iniciar_pareamento(id_dispositivo)
            if not r.get("ok"):
                QTimer.singleShot(0, lambda: self._tv_status(r.get("mensagem", "Falhou"), erro=True))
                return
            def pedir_codigo():
                codigo = self._tv_dialogo_codigo()
                if not codigo:
                    self._tv_status("Pareamento cancelado")
                    return
                self._tv_concluir_pareamento(codigo)
            QTimer.singleShot(0, pedir_codigo)
        threading.Thread(target=trabalho, daemon=True).start()

    def _tv_dialogo_codigo(self) -> str:
        """Pede o código que a TV está mostrando. RODA NA UI THREAD."""
        from PyQt6.QtWidgets import (QDialog, QLineEdit, QDialogButtonBox,
                                     QPushButton)
        dlg = QDialog(self)
        dlg.setWindowTitle("Código da TV")
        dlg.setFixedSize(320, 150)
        dlg.setStyleSheet(f"""
            QDialog {{ background:{BG_CARD}; border:1px solid {BORDER}; border-radius:10px; }}
            QLabel  {{ color:{C_TEXT}; background:transparent; }}
            QLineEdit {{
                background:{BG_INPUT}; color:{C_TEXT};
                border:1px solid {BORDER}; border-radius:6px;
                padding:6px 10px; font-size:12pt;
            }}
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)
        lb = QLabel("Digite o código que aparece na tela da TV:")
        lb.setWordWrap(True)
        lay.addWidget(lb)
        campo = QLineEdit()
        campo.setPlaceholderText("ex: 123456")
        campo.setMaxLength(6)
        lay.addWidget(campo)
        linha = QDialogButtonBox()
        b_ok = QPushButton("Confirmar")
        b_cancel = QPushButton("Cancelar")
        linha.addButton(b_ok, QDialogButtonBox.ButtonRole.AcceptRole)
        linha.addButton(b_cancel, QDialogButtonBox.ButtonRole.RejectRole)
        b_ok.clicked.connect(dlg.accept)
        b_cancel.clicked.connect(dlg.reject)
        lay.addWidget(linha)
        aceito = dlg.exec() == QDialog.DialogCode.Accepted
        return campo.text().strip() if aceito else ""

    def _tv_concluir_pareamento(self, codigo: str):
        self._tv_status("Concluindo pareamento…")
        def trabalho():
            import controle_tv as tv
            r = tv.concluir_pareamento(codigo)
            def atualizar():
                self._tv_status(r.get("mensagem", ""), ok=bool(r.get("ok")),
                                erro=not r.get("ok"))
                self._carregar_tv()
            QTimer.singleShot(0, atualizar)
        threading.Thread(target=trabalho, daemon=True).start()



    def _tv_dialogo_campos(self, d: dict | None):
        """Diálogo com Nome/IP/Tipo (tudo editável). Devolve os três campos."""
        from PyQt6.QtWidgets import QDialog, QLineEdit, QDialogButtonBox, QLabel
        dlg = QDialog(self)
        novo = d is None
        dlg.setWindowTitle("Adicionar TV" if novo else "Editar TV")
        dlg.setFixedSize(400, 260)
        dlg.setStyleSheet(f"""
            QDialog {{ background:{BG_CARD}; border:1px solid {BORDER}; border-radius:10px; }}
            QLabel  {{ color:{C_TEXT}; background:transparent; }}
            QLineEdit {{
                background:{BG_INPUT}; color:{C_TEXT};
                border:1px solid {BORDER}; border-radius:6px;
                padding:6px 10px; font-size:10pt;
            }}
            QLineEdit:focus {{ border-color:{PURPLE}; }}
            QPushButton {{
                background:{PURPLE}; color:white; border:none;
                border-radius:6px; padding:6px 16px; font-weight:bold;
            }}
            QPushButton:hover {{ background:{PURPLE_DK}; }}
            QPushButton[secundario="true"] {{
                background:{BORDER}; color:{C_TEXT2}; font-weight:normal;
            }}
        """)
        lay = QVBoxLayout(dlg); lay.setContentsMargins(16,14,16,14); lay.setSpacing(8)

        dica = QLabel("IP local da TV, e nome/tipo como você quiser chamar.\n"
                      "O tipo é editável caso a detecção não acerte.")
        dica.setFont(QFont("Segoe UI", 8))
        dica.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        lay.addWidget(dica)

        def campo(rotulo: str, valor: str, placeholder: str) -> QLineEdit:
            lb = QLabel(rotulo); lb.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            lb.setStyleSheet("background:transparent;")
            lay.addWidget(lb)
            ed = QLineEdit(valor)
            ed.setPlaceholderText(placeholder)
            lay.addWidget(ed)
            return ed

        campo_nome = campo("Nome", (d or {}).get("nome", ""), "ex: TV da Sala")
        campo_ip   = campo("IP", (d or {}).get("ip", ""), "ex: 192.168.0.15")
        campo_tipo = campo("Tipo da TV", (d or {}).get("tipo", ""),
                           "ex: TCL Android TV (opcional, editável)")
        botoes = QHBoxLayout()
        botoes.addStretch()
        return dlg, campo_nome, campo_ip, campo_tipo, botoes




    def _build_sistema(self):
        w = QWidget(); w.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(0,4,0,8); lay.setSpacing(6)
        # CPU
        cc = QFrame(); cc.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px;")
        cl = QVBoxLayout(cc); cl.setContentsMargins(6,8,6,8); cl.setSpacing(2)
        ctl = QLabel("CPU"); ctl.setFont(QFont("Segoe UI",8,QFont.Weight.Bold))
        ctl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        ctl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cpu_gauge = GaugeDial(color=PURPLE)
        cl.addWidget(ctl); cl.addWidget(self._cpu_gauge,alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(cc)
        # RAM
        rc = QFrame(); rc.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px;")
        rl = QVBoxLayout(rc); rl.setContentsMargins(6,8,6,8); rl.setSpacing(2)
        rtl = QLabel("RAM"); rtl.setFont(QFont("Segoe UI",8,QFont.Weight.Bold))
        rtl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        rtl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ram_gauge = GaugeDial(color=C_CYAN)
        rl.addWidget(rtl); rl.addWidget(self._ram_gauge,alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(rc)
        # Hora
        hc = QFrame(); hc.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px;")
        hl = QVBoxLayout(hc); hl.setContentsMargins(6,8,6,8); hl.setSpacing(2)
        htl = QLabel("Hora atual"); htl.setFont(QFont("Segoe UI",7))
        htl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        htl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hora_lbl = QLabel("00:00:00"); self._hora_lbl.setFont(QFont("Segoe UI",13,QFont.Weight.Bold))
        self._hora_lbl.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
        self._hora_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._data_lbl = QLabel(""); self._data_lbl.setFont(QFont("Segoe UI",7))
        self._data_lbl.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
        self._data_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(htl); hl.addWidget(self._hora_lbl); hl.addWidget(self._data_lbl)
        lay.addWidget(hc,1)
        return w

    # ── Sinais e timers ─────────────────────────────────────────

    def _connect_signals(self):
        self.sig.status_changed.connect(self._on_status_changed)
        self.sig.chat_add.connect(self._add_chat_msg)
        self.sig.img_add.connect(self._add_img_msg)
        self.sig.salvar_imagem.connect(self._show_salvar_imagem)
        # ↓ CORREÇÃO DO CRASH: toggle_painel é emitido da thread tkinter
        #   mas conectado aqui na thread Qt → executa toggle_visible com segurança
        self.sig.toggle_painel.connect(self.toggle_visible)
        self.sig.progresso.connect(self._on_progresso)

    def _start_timers(self):
        self._t_sys = QTimer(self); self._t_sys.timeout.connect(self._update_system); self._t_sys.start(2000)
        self._t_hr  = QTimer(self); self._t_hr.timeout.connect(self._update_hora);   self._t_hr.start(1000)

    def _update_system(self):
        try:
            import psutil
            self._cpu_gauge.set_value(psutil.cpu_percent(interval=None))
            self._ram_gauge.set_value(psutil.virtual_memory().percent)
        except Exception: pass

    def _update_hora(self):
        now = datetime.datetime.now()
        self._hora_lbl.setText(now.strftime("%H:%M:%S"))
        self._data_lbl.setText(now.strftime("%d/%m/%Y"))

    def _on_status_changed(self, status, texto):
        cor, lbl = STATUS_MAP.get(status,(C_GREEN,"● Aguardando"))
        self._status_pill.setText(lbl)
        self._status_pill.setStyleSheet(f"color:{cor}; background:{PURPLE_DIM}; border-radius:10px; padding:4px 14px;")
        self._update_status_dots(status)
        if status=="ouvindo" and texto and texto.startswith('Você disse: "'):
            msg = texto[len('Você disse: "'):].rstrip('"')
            if msg: self._add_chat_msg("user",msg)
        if status == "falando" and texto:
            self._em_falando = True
            # Se essa frase já apareceu no cartão de progresso, ela NÃO entra na
            # bolha final. É o mesmo texto chegando por dois caminhos: pelo
            # progresso (na hora, na ordem certa) e pelo TTS (depois de gerar o
            # áudio). Sem isto o Vitor lê "deixa eu conferir" duas vezes, e a
            # segunda vez fora de ordem — foi exatamente a reclamação.
            if not self._ja_esta_no_cartao(texto):
                self._em_buffer.append(texto)
        elif self._em_falando and status != "falando":
            # Segunda passada, agora FRASE POR FRASE. A primeira (lá em cima)
            # descarta o item inteiro do TTS quando ele já está no cartão; esta
            # limpa o que sobrou dentro de um texto misturado — o caso comum é o
            # modelo repetir a própria frase de abertura no começo da resposta
            # final, e aí o item do TTS traz "Ué, deixa eu conferir. Achei 362
            # mods." e não pode ser jogado fora inteiro.
            resp = self._sem_o_que_ja_apareceu(" ".join(self._em_buffer))
            if resp:
                self._add_chat_msg("emily", resp)
            self._em_buffer.clear()
            self._em_falando = False

    # ── Memória do que já apareceu no cartão de progresso ───────

    def _anotar_fala_do_cartao(self, texto: str):
        """Registra uma narração pra ela não aparecer de novo na bolha final."""
        self._falas_no_cartao += " " + _normalizar_fala(texto)
        for frase in _sentencas(texto):
            n = _normalizar_fala(frase)
            if n:
                self._frases_no_cartao.add(n)

    def _esquecer_falas_do_cartao(self):
        self._falas_no_cartao = ""
        self._frases_no_cartao = set()

    def _ja_esta_no_cartao(self, texto: str) -> bool:
        """
        Esse texto já foi mostrado como narração no cartão?

        Duas medidas, e as duas são necessárias. A igualdade de frase pega o
        pedaço que o TTS devolve cortado. A busca por trecho pega a frase que
        chegou junto com outra, mas só a partir de 10 caracteres: abaixo disso um
        "ok" ou um "pronto" casaria dentro de qualquer coisa e comeria texto que o
        Vitor precisa ler.
        """
        alvo = _normalizar_fala(texto)
        if not alvo:
            return False
        if alvo in self._frases_no_cartao:
            return True
        return len(alvo) >= 10 and alvo in self._falas_no_cartao

    def _sem_o_que_ja_apareceu(self, texto: str) -> str:
        """Tira do texto as frases que já estão no cartão de progresso."""
        texto = (texto or "").strip()
        if not texto or not self._falas_no_cartao:
            return texto
        sobrou = [f for f in _sentencas(texto) if not self._ja_esta_no_cartao(f)]
        limpo = " ".join(sobrou).strip()
        # Se NADA sobrou, devolve o texto original. O cartão desaparece no fim do
        # turno, então cortar tudo deixaria a ação terminando em silêncio, sem
        # nenhuma resposta na tela. Ler a mesma frase duas vezes é chato; a Emily
        # agir e não dizer nada é o bug que eu passei a semana consertando.
        return limpo or texto

    def _garantir_conversa(self, primeira: str = "") -> str:
        """
        A conversa no disco nasce na PRIMEIRA mensagem, não no clique em 'Nova'.

        Assim clicar 'Nova conversa' e desistir não deixa rastro na lista.
        """
        if self._conversa_id:
            return self._conversa_id
        try:
            import conversas
            self._conversa_id = conversas.criar(primeira)
            if primeira:
                self._titulo_chat.setText(conversas.titulo_de(primeira))
        except Exception as e:
            print(f"[INTERFACE] não criei a conversa: {e}")
        return self._conversa_id

    def _add_chat_msg(self, autor, texto, sistema=False):
        # Corta o que já apareceu no cartão de progresso. Fica AQUI, e não só no
        # flush do _on_status_changed, porque este é o ponto único por onde toda
        # bolha passa: o add_mensagem_emily e qualquer caminho futuro herdam a
        # garantia sem ninguém ter que lembrar. É idempotente, então filtrar duas
        # vezes não muda nada.
        if autor == "emily" and not self._carregando:
            texto = self._sem_o_que_ja_apareceu(texto)

        bub = ChatBubble(texto, is_emily=(autor=="emily"))
        self._inserir_no_chat(bub)

        # Grava no histórico, MENOS quando estamos redesenhando o que veio do
        # disco — senão abrir uma conversa duplicaria cada mensagem dela.
        if self._carregando or sistema:
            return
        nova = not self._conversa_id
        self._garantir_conversa(texto if autor == "user" else "")
        try:
            import conversas
            conversas.acrescentar(self._conversa_id, autor, texto)
        except Exception as e:
            print(f"[INTERFACE] não gravei a mensagem: {e}")
        # Redesenha a lista só quando ela muda de verdade: conversa nova, ou
        # mensagem do Vitor (que mexe na ordem e pode definir o título).
        if nova or autor == "user":
            self._recarregar_conversas()

    # ── Progresso das ferramentas ───────────────────────────────
    #
    # O desenho segue o que o Claude e o ChatGPT fazem, e a ordem importa: os
    # pontinhos aparecem na hora (a espera existe desde o primeiro token), e o
    # cartão de passos só nasce quando uma ferramenta REALMENTE roda. Criar o
    # cartão sempre encheria o chat de "Pronto · 0 passos" em conversa comum.

    def _inserir_no_chat(self, w):
        """Insere acima do stretch final e rola pro fim."""
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, w)
        QTimer.singleShot(60, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()))

    def _rolar_pro_fim(self):
        QTimer.singleShot(60, lambda: self._chat_scroll.verticalScrollBar()
                          .setValue(self._chat_scroll.verticalScrollBar().maximum()))

    def _garantir_cartao(self) -> "PainelProgresso":
        """Cria o cartão de progresso na primeira fala ou no primeiro passo."""
        if self._painel_prog is None:
            self._painel_prog = PainelProgresso()
            # Antes dos pontinhos: o cartão é histórico, os pontinhos são o
            # "agora". Invertido, o "agora" ficaria no meio.
            idx = self._chat_layout.count() - 1
            if getattr(self, "_digitando", None) is not None:
                idx = self._chat_layout.indexOf(self._digitando)
            self._chat_layout.insertWidget(idx, self._painel_prog)
        return self._painel_prog

    def _on_progresso(self, fase, dados):
        try:
            dados = dados or {}
            if fase == "inicio":
                self._encerrar_progresso()
                self._esquecer_falas_do_cartao()
                self._digitando = IndicadorDigitando()
                self._inserir_no_chat(self._digitando)
                return

            if fase == "fala":
                # A fala dela entra no CARTÃO, junto do que ela está fazendo, em
                # vez de virar uma bolha solta. Era o pedido: "isso são
                # atualizações que ela mesmo gera pra me manter informado, então
                # tem que encaixar junto da atualização visual das ferramentas".
                texto = (dados.get("texto") or "").strip()
                if not texto:
                    return
                self._garantir_cartao().fala(texto)
                self._anotar_fala_do_cartao(texto)
                self._rolar_pro_fim()
                return

            if fase == "ferramenta":
                import progresso_discord
                texto = progresso_discord.rotulo(
                    dados.get("nome", ""), dados.get("args"))
                self._garantir_cartao().passo(
                    texto, _icone_de(dados.get("nome", "")))
                self._rolar_pro_fim()
                return

            if fase == "resultado":
                import progresso_discord
                if self._painel_prog is not None:
                    self._painel_prog.resultado(
                        progresso_discord.parece_problema(dados.get("resultado", "")))
                return

            if fase == "fim":
                self._encerrar_progresso()
        except Exception as e:
            # O painel é enfeite: se ele quebrar, quebra sozinho. Nunca pode
            # transformar "montou o modpack" em erro na cara do Vitor.
            print(f"[PROGRESSO] {fase} falhou: {e}")

    def _encerrar_progresso(self):
        alvo = getattr(self, "_digitando", None)
        if alvo is not None:
            alvo.parar()
            alvo.setParent(None)
            alvo.deleteLater()
            self._digitando = None
        painel = getattr(self, "_painel_prog", None)
        if painel is not None:
            # Deu tudo certo: o cartão SOME e sobra só a resposta dela.
            # "depois que ela concluir uma ação, some tudo que tava ali, a
            # atualização e aparece só a mensagem dela no lugar. Isso é
            # importante pra não ficar poluindo o chat."
            #
            # A exceção é ressalva. Aí ele encolhe pra uma tira clicável em vez
            # de sumir: sumir sempre apagaria o único registro do que falhou, e
            # meia hora depois ninguém sabe mais por que o mod não entrou.
            if painel.vazio() or not painel.teve_problema():
                painel.setParent(None)
                painel.deleteLater()
            else:
                painel.finalizar()
                painel.colapsar()
            self._painel_prog = None
        self._esquecer_falas_do_cartao()

    def _add_img_msg(self, caminho, autor):
        try:
            pix = QPixmap(caminho).scaled(240,160,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
            fr = QFrame(); fr.setStyleSheet(f"background:{EMILY_BUB if autor=='emily' else USER_BUB}; border-radius:8px;")
            fl = QVBoxLayout(fr); fl.setContentsMargins(8,4,8,4)
            nl = QLabel("Emily" if autor=="emily" else "Você")
            nl.setFont(QFont("Segoe UI",8,QFont.Weight.Bold))
            nl.setStyleSheet(f"color:{PURPLE_LT if autor=='emily' else PURPLE}; background:transparent; border:none;")
            il = QLabel(); il.setPixmap(pix); il.setStyleSheet("background:transparent; border:none;")
            fl.addWidget(nl); fl.addWidget(il)
            self._chat_layout.insertWidget(self._chat_layout.count()-1, fr)
            QTimer.singleShot(60, lambda: self._chat_scroll.verticalScrollBar().setValue(
                self._chat_scroll.verticalScrollBar().maximum()))
        except Exception:
            self._add_chat_msg(autor, f"📎 {os.path.basename(caminho)}")

    def _show_salvar_imagem(self, caminho):
        fr = QFrame(); fr.setStyleSheet(f"background:{EMILY_BUB}; border-radius:8px;")
        fl = QHBoxLayout(fr); fl.setContentsMargins(10,8,10,8)
        bs = QPushButton("💾  Salvar imagem"); bs.setStyleSheet(btn_style())
        bd = QPushButton("🗑  Descartar")
        bd.setStyleSheet(f"QPushButton {{ background:{BORDER}; color:{C_TEXT2}; border-radius:6px; padding:5px 10px; }} QPushButton:hover {{ color:{C_TEXT}; }}")
        fl.addWidget(bs); fl.addWidget(bd); fl.addStretch()
        def salvar():
            from PyQt6.QtWidgets import QFileDialog; import shutil
            dest,_ = QFileDialog.getSaveFileName(self,"Salvar imagem",os.path.basename(caminho),"PNG (*.png);;Todos (*.*)")
            if dest: shutil.copy2(caminho,dest); bs.setText("✅  Salvo!"); bs.setEnabled(False); bd.hide()
        def descartar():
            try: os.remove(caminho)
            except: pass
            fr.setParent(None)
        bs.clicked.connect(salvar); bd.clicked.connect(descartar)
        self._chat_layout.insertWidget(self._chat_layout.count()-1, fr)
        QTimer.singleShot(60, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()))

    def eventFilter(self, obj, event):
        if obj is self._campo_texto:
            if event.type() == QEvent.Type.FocusIn:
                self._pintar_caixa_input(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._pintar_caixa_input(False)

            # Enter sem Shift → enviar
            if event.type() == QEvent.Type.KeyPress:
                if (event.key() == Qt.Key.Key_Return
                        and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                    self._enviar()
                    return True

            # Ctrl+V → intercepta se tiver imagem no clipboard
            if event.type() == QEvent.Type.KeyPress:
                if (event.key() == Qt.Key.Key_V
                        and (event.modifiers() & Qt.KeyboardModifier.ControlModifier)):
                    clipboard = QApplication.clipboard()
                    mime = clipboard.mimeData()
                    if mime and (mime.hasImage() or mime.hasFormat("image/png")
                                 or mime.hasFormat("image/bmp")):
                        self._colar_imagem_do_clipboard_mime(mime)
                        return True   # consome o evento, não insere texto
                    # sem imagem → deixa o paste de texto normal acontecer

        return super().eventFilter(obj, event)

    def _enviar(self):
        txt = self._campo_texto.toPlainText().strip()
        tem_arquivos = len(getattr(self, "_arquivos_pendentes", [])) > 0

        if not txt and not tem_arquivos:
            return
        if txt:
            import estilo_vitor
            estilo_vitor.coletar(txt, "escrita", "qt")

        # Mandar mensagem tira a tela do início e joga a conversa em tela cheia.
        # É o que o Vitor pediu, e é o que resolve a fala dela empilhando: aqui
        # a bolha tem 640px pra usar em vez de 350.
        self._ir_para_chat()

        # ── 1) Envia arquivos do staging ──
        if tem_arquivos:
            arquivos_snap = list(self._arquivos_pendentes)

            # Mostra no chat: imagens primeiro, depois arquivos genéricos
            for arq in arquivos_snap:
                if arq["is_image"]:
                    self._add_img_msg(arq["path"], "user")
                else:
                    self._add_chat_msg("user", f"📎 {os.path.basename(arq['path'])}")

            # Se tiver texto junto, mostra também
            if txt:
                self._add_chat_msg("user", txt)

            self._campo_texto.clear()
            self._limpar_arquivos_pendentes()

            # Repassa cada arquivo ao callback
            for arq in arquivos_snap:
                path = arq["path"]
                if getattr(self, "_callback_arquivo", None):
                    threading.Thread(
                        target=self._callback_arquivo,
                        args=(path,),
                        daemon=True
                    ).start()

            # Se tiver texto também, passa ao callback de texto
            if txt and getattr(self, "_callback_texto", None):
                threading.Thread(
                    target=self._callback_texto,
                    args=(txt,),
                    daemon=True
                ).start()
            return

        # ── 2) Só texto ──
        self._campo_texto.clear()
        self._add_chat_msg("user", txt)
        if getattr(self, "_callback_texto", None):
            threading.Thread(target=self._callback_texto, args=(txt,), daemon=True).start()

    def _abrir_arquivo(self):
        """Abre o seletor de arquivo e adiciona ao staging (preview) em vez de enviar direto."""
        from PyQt6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Anexar arquivo(s)", "",
            "Imagens (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;"
            "Código (*.py *.js *.ts *.html *.css *.json *.txt *.md);;"
            "Documentos (*.pdf *.doc *.docx);;"
            "Compactados (*.zip *.rar *.7z);;"
            "Todos (*.*)"
        )
        for path in paths:
            if path:
                self._adicionar_arquivo_pendente(path)

    def _ativar_ptt(self):
        def _r():
            try:
                import voz
                txt = voz.ouvir_ptt(callback_gravando=lambda: self.sig.status_changed.emit("gravando",""))
                if txt:
                    import estilo_vitor
                    estilo_vitor.coletar(txt, "fala", "ptt_qt")
                    self.sig.chat_add.emit("user",txt,False)
                    if getattr(self,"_callback_texto",None): self._callback_texto(txt)
            except Exception as e: print(f"[PTT] {e}")
        threading.Thread(target=_r,daemon=True).start()

    def _capturar_tela(self):
        self._visao_ativa = not getattr(self,"_visao_ativa",False)
        self._btn_cam.setStyleSheet(
            f"background:transparent; color:{C_YELLOW if self._visao_ativa else C_TEXT2}; border:none;")
        if getattr(self,"_callback_visao",None): self._callback_visao()

    def _drag_press(self, e):
        # Drag desabilitado quando maximizado
        if self._maximized: return
        if e.button()==Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint(); self._dragging=True

    def _drag_move(self, e):
        if self._dragging and e.buttons()==Qt.MouseButton.LeftButton:
            d = e.globalPosition().toPoint()-self._drag_pos
            self.move(self.x()+d.x(), self.y()+d.y())
            self._drag_pos = e.globalPosition().toPoint()

    def _drag_release(self, e): self._dragging=False

    def toggle_visible(self):
        """Sempre chamado na thread Qt (via sinal toggle_painel). Thread-safe."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()


# ═══════════════════════════════════════════════════════════════
# JanelaEmily — API pública compatível com main.py
# ═══════════════════════════════════════════════════════════════

class JanelaEmily:
    def __init__(self, callback_texto=None, callback_trocar_monitor=None):
        self.callback_texto          = callback_texto
        self.callback_trocar_monitor = callback_trocar_monitor
        self.callback_visao          = None
        self.callback_arquivo        = None
        self.visao_ativa             = False

        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")

        self._sig    = StatusSignaler()
        self._painel = PainelEmily(self._sig)
        self._painel._callback_texto   = self._on_texto
        self._painel._callback_visao   = self._on_visao
        self._painel._callback_arquivo = self._on_arquivo
        self._painel.show()

        self.root        = _FakeRoot(self._app)
        self._estado     = "aguardando"
        self._em_buffer  = []
        self._em_falando = False
        self._sprite     = None
        self._iniciar_sprite()

    def _iniciar_sprite(self):
        def _run():
            try:
                self._sprite = SpriteGif()
                # ↓ CORREÇÃO DO CRASH: emite sinal em vez de chamar toggle_visible diretamente
                #   O sinal cruza a fronteira de threads de forma segura via Qt event loop
                self._sprite._toggle_cb = lambda: self._sig.toggle_painel.emit()
                import time
                while True:
                    try: self._sprite._root.update()
                    except: break
                    time.sleep(0.033)
            except Exception as e:
                print(f"[SPRITE] {e}")
        threading.Thread(target=_run, daemon=True).start()

    def _on_texto(self, texto):
        if self.callback_texto: self.callback_texto(texto)

    def _on_visao(self):
        self.visao_ativa = not self.visao_ativa
        if self.callback_visao: self.callback_visao()

    def _on_arquivo(self, caminho):
        if self.callback_arquivo: self.callback_arquivo(caminho)

    def atualizar_status(self, status: str, texto: str = ""):
        self._sig.status_changed.emit(status, texto)
        if self._sprite:
            gif_map = {
                "aguardando":"idle","ouvindo":"uping","gravando":"uping",
                "falando":"talk","monitorando":"screen","transferindo":"transfer",
                "abrindo_app":"open","pesquisando":"search","gerando":"search","pensando":"search",
            }
            g = gif_map.get(status,"idle")
            try:
                self._sprite.trocar_gif(g if g in self._sprite._gifs else "idle")
            except: pass

    def progresso_evento(self, fase: str, dados: dict = None):
        """
        Ponto único que o modelo.py chama pra mostrar o que está rolando.

        Mesma assinatura do painel do Discord (fase, dados), então os dois lados
        consomem o MESMO evento e não existe um segundo formato pra manter.

        Nunca levanta: é chamado de dentro do laço de ferramentas, e enfeite que
        estoura exceção viraria ação que não acontece.
        """
        try:
            self._sig.progresso.emit(fase, dados or {})
        except Exception as e:
            print(f"[PROGRESSO] não consegui emitir '{fase}': {e}")

    def add_imagem_chat_safe(self, caminho: str, autor: str = "user"):
        self._sig.img_add.emit(caminho, autor)

    def mostrar_opcao_salvar(self, caminho: str):
        self._sig.salvar_imagem.emit(caminho)

    def add_mensagem_emily(self, texto: str):
        """
        Põe uma bolha da Emily no chat, sem passar pelo status.

        O caminho normal da fala dela é atualizar_status('falando', frase), que o
        painel junta numa bolha só quando o status muda. Isto existe pra quando
        alguém tem a resposta final na mão e quer ela na tela mesmo que o TTS não
        tenha rodado — texto digitado com a voz muda, por exemplo.
        """
        if texto and texto.strip():
            self._sig.chat_add.emit("emily", texto.strip(), False)

    def add_mensagem_usuario(self, texto: str):
        """Mostra no chat a frase reconhecida pelo push-to-talk."""
        if texto and texto.strip():
            self._sig.chat_add.emit("user", texto.strip(), False)

    def carregar_historico(self, mensagens: list):
        def _do():
            for msg in mensagens:
                role  = msg.get("role","")
                texto = msg.get("content","").strip()
                if not texto: continue
                if role=="assistant": self._sig.chat_add.emit("emily",texto,False)
                elif role=="user":    self._sig.chat_add.emit("user",texto,False)
        QTimer.singleShot(100, _do)

    def _add_chat_safe(self, autor: str, texto: str, sistema: bool = False):
        self._sig.chat_add.emit(autor, texto, sistema)

    def iniciar(self):
        sys.exit(self._app.exec())
