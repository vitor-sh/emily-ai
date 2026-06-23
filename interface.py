"""
interface.py — Emily AI · Painel de Controle Moderno (PyQt6)
Design: Dark glassmorphism, tema roxo/azul, bordas iluminadas
"""

import os
import sys
import json
import threading
import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFrame, QScrollArea, QTextEdit,
    QSizePolicy, QGridLayout, QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import (
    Qt, QTimer, pyqtSignal, QObject, QPoint, QEvent,
)
from PyQt6.QtWidgets import QFileIconProvider
from PyQt6.QtCore import QFileInfo
from PyQt6.QtGui import (
    QFont, QColor, QPixmap, QPainter, QPen, QBrush,
    QPainterPath, QIcon, QCursor,
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


class ChatBubble(QFrame):
    def __init__(self, text, is_emily=True, parent=None):
        super().__init__(parent)
        bg = EMILY_BUB if is_emily else USER_BUB
        align = Qt.AlignmentFlag.AlignLeft if is_emily else Qt.AlignmentFlag.AlignRight
        bc = "#1a1a40" if is_emily else "#2a2060"
        outer = QVBoxLayout(self); outer.setContentsMargins(6,3,6,3); outer.setSpacing(2)
        nl = QLabel("Emily" if is_emily else "Você")
        nl.setFont(QFont("Segoe UI",8,QFont.Weight.Bold))
        nl.setStyleSheet(f"color:{PURPLE_LT if is_emily else PURPLE}; background:transparent;")
        nl.setAlignment(align); outer.addWidget(nl)
        bl = QLabel(text); bl.setWordWrap(True); bl.setFont(QFont("Segoe UI",9))
        bl.setStyleSheet(f"background:{bg}; color:{C_TEXT}; border:1px solid {bc}; border-radius:8px; padding:8px 12px;")
        bl.setAlignment(Qt.AlignmentFlag.AlignLeft); outer.addWidget(bl)


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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        bg = QFrame(self)
        bg.setObjectName("root_bg")
        bg.setStyleSheet(f"QFrame#root_bg {{ background:{BG_MAIN}; border:1.5px solid {BORDER_GLOW}; border-radius:4px; }}")
        outer.addWidget(bg)

        ml = QVBoxLayout(bg)
        ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        ml.addWidget(self._build_header())
        ml.addWidget(self._hsep())

        body = QWidget(); body.setStyleSheet(f"background:{BG_MAIN};")
        bl = QHBoxLayout(body); bl.setContentsMargins(0,0,0,0); bl.setSpacing(0)
        bl.addWidget(self._build_left_sidebar())
        bl.addWidget(self._vsep())
        bl.addWidget(self._build_center(), 1)
        bl.addWidget(self._vsep())
        bl.addWidget(self._build_right_sidebar())
        ml.addWidget(body, 1)

    def _hsep(self):
        f = QFrame(); f.setFixedHeight(1); f.setStyleSheet(f"background:{BORDER};"); return f

    def _vsep(self):
        f = QFrame(); f.setFixedWidth(1); f.setStyleSheet(f"background:{BORDER};"); return f

    # ── Header ─────────────────────────────────────────────────

    def _build_header(self):
        hdr = QFrame(); hdr.setFixedHeight(56)
        hdr.setStyleSheet(f"background:{BG_HEADER};")
        lay = QHBoxLayout(hdr); lay.setContentsMargins(16,0,16,0)

        av = QLabel(); av.setFixedSize(38,38)
        img_path = os.path.join(DIR_BASE, "emilyimage.png")
        if os.path.exists(img_path):
            src = QPixmap(img_path).scaled(38,38,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            out = QPixmap(38,38); out.fill(Qt.GlobalColor.transparent)
            pp = QPainter(out); pp.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath(); path.addEllipse(0,0,38,38); pp.setClipPath(path)
            ox = max(0,(src.width()-38)//2); oy = max(0,(src.height()-38)//2)
            pp.drawPixmap(0,0,src,ox,oy,38,38)
            pp.setPen(QPen(QColor(PURPLE),1.5)); pp.setBrush(Qt.BrushStyle.NoBrush)
            pp.drawEllipse(0,0,37,37); pp.end()
            av.setPixmap(out)
        else:
            av.setPixmap(_make_circle_pixmap(38,PURPLE,"E","#fff",14))
        av.setStyleSheet("background:transparent;")
        lay.addWidget(av); lay.addSpacing(10)

        nc = QVBoxLayout(); nc.setSpacing(1)
        n = QLabel("Emily"); n.setFont(QFont("Segoe UI",12,QFont.Weight.Bold))
        n.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        s = QLabel("IA Pessoal"); s.setFont(QFont("Segoe UI",7,QFont.Weight.Bold))
        s.setStyleSheet(f"color:{PURPLE_LT}; background:transparent;")
        nc.addWidget(n); nc.addWidget(s)
        lay.addLayout(nc); lay.addStretch()

        self._status_pill = QLabel("● Aguardando")
        self._status_pill.setFont(QFont("Segoe UI",8,QFont.Weight.Bold))
        self._status_pill.setStyleSheet(f"color:{C_GREEN}; background:{PURPLE_DIM}; border-radius:10px; padding:4px 14px;")
        lay.addWidget(self._status_pill); lay.addSpacing(12)

        # ── Botão maximizar/restaurar (NOVO) ──────────────────
        self._btn_max = QPushButton("□")
        self._btn_max.setFixedSize(28,28)
        self._btn_max.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_max.setToolTip("Maximizar / Restaurar")
        self._btn_max.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:13pt; }}"
            f"QPushButton:hover {{ color:{C_TEXT}; }}"
        )
        self._btn_max.clicked.connect(self._toggle_maximize)
        lay.addWidget(self._btn_max)

        # Minimizar
        bm = QPushButton("─"); bm.setFixedSize(28,28)
        bm.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bm.setStyleSheet(f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:13pt; }} QPushButton:hover {{ color:{C_TEXT}; }}")
        bm.clicked.connect(self.hide)
        lay.addWidget(bm)

        # Fechar (encerra a Emily completamente)
        bx = QPushButton("✕"); bx.setFixedSize(28,28)
        bx.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        bx.setToolTip("Encerrar Emily")
        bx.setStyleSheet(f"QPushButton {{ background:transparent; color:{C_TEXT3}; border:none; font-size:13pt; }} QPushButton:hover {{ color:{C_RED}; }}")
        bx.clicked.connect(self._encerrar_emily)
        lay.addWidget(bx)

        hdr.mousePressEvent   = self._drag_press
        hdr.mouseMoveEvent    = self._drag_move
        hdr.mouseReleaseEvent = self._drag_release
        return hdr

    def _toggle_maximize(self):
        """Alterna entre tela cheia (tela secundária) e janela normal."""
        if self._maximized:
            self._maximized = False
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.showNormal()
            self._btn_max.setText("□")
            self._btn_max.setToolTip("Maximizar (tela secundária)")
        else:
            self._maximized = True
            # Tenta usar a tela SECUNDÁRIA; se não existir, usa a primária
            screens = QApplication.screens()
            if len(screens) > 1:
                target_screen = screens[1]   # índice 1 = segunda tela
            else:
                target_screen = screens[0]   # fallback: única tela disponível
            screen_geo = target_screen.availableGeometry()
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint |
                Qt.WindowType.WindowStaysOnTopHint |
                Qt.WindowType.Tool
            )
            self.show()
            self.setGeometry(screen_geo)
            self._btn_max.setText("❐")
            self._btn_max.setToolTip("Restaurar")

    def _encerrar_emily(self):
        """Encerra a Emily completamente ao clicar no botão ✕."""
        QApplication.quit()

    # ── Sidebar esquerda ────────────────────────────────────────

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

        hr = QHBoxLayout()
        ht = QLabel("Conversas recentes"); ht.setFont(QFont("Segoe UI",10,QFont.Weight.Bold))
        ht.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        hr.addWidget(ht); hr.addStretch()
        pl = QPushButton("＋"); pl.setFixedSize(24,24)
        pl.setStyleSheet(f"background:transparent; color:{PURPLE_LT}; border:none; font-size:14pt;")
        hr.addWidget(pl); il.addLayout(hr)

        self._conv_lay = QVBoxLayout(); self._conv_lay.setSpacing(4)
        self._carregar_conversas(self._conv_lay); il.addLayout(self._conv_lay)

        vt = QLabel("Ver todas as conversas  ›")
        vt.setFont(QFont("Segoe UI",8))
        vt.setStyleSheet(f"color:{C_TEXT2}; background:transparent; padding:2px 4px;")
        il.addWidget(vt); il.addWidget(self._hsep())

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

        rod = QFrame(); rod.setFixedHeight(52)
        rod.setStyleSheet(f"background:{BG_SIDEBAR}; border-top:1px solid {BORDER};")
        rl = QHBoxLayout(rod); rl.setContentsMargins(12,0,12,0)
        for ico in ["⚙","🌙","ℹ"]:
            b = QPushButton(ico); b.setFixedSize(28,28)
            b.setFont(QFont("Segoe UI Emoji",11))
            b.setStyleSheet(f"background:transparent; color:{C_TEXT2}; border:none;")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            rl.addWidget(b)
        rl.addStretch()
        av2 = QLabel(); av2.setFixedSize(30,30)
        av2.setPixmap(_make_circle_pixmap(30,PURPLE_DIM,"V",PURPLE_LT,11))
        av2.setStyleSheet("background:transparent;")
        rl.addWidget(av2); rl.addSpacing(6)
        ui = QVBoxLayout(); ui.setSpacing(0)
        u1 = QLabel("Você"); u1.setFont(QFont("Segoe UI",9,QFont.Weight.Bold))
        u1.setStyleSheet(f"color:{C_TEXT}; background:transparent;")
        u2 = QLabel("Perfil pessoal"); u2.setFont(QFont("Segoe UI",7))
        u2.setStyleSheet(f"color:{C_TEXT2}; background:transparent;")
        ui.addWidget(u1); ui.addWidget(u2); rl.addLayout(ui)
        lay.addWidget(rod)
        return side

    def _carregar_conversas(self, container):
        conversas = []
        try:
            import modelo
            hist = getattr(modelo, "_historico", [])
            for i in range(0, len(hist), 2):
                u = hist[i].get("content","")
                a = hist[i+1].get("content","") if i+1 < len(hist) else ""
                conversas.append((u, a))
        except Exception:
            pass
        if not conversas:
            conversas = [("Como posso te ajudar?","Tô aqui, pode falar!")]

        now = datetime.datetime.now()
        icons_c = ["💬","🤔","🐛","💡","📝","📋"]
        for idx, (titulo, sub) in enumerate(conversas[:6]):
            if not titulo.strip(): continue
            card = QFrame()
            card.setStyleSheet(
                f"background:{PURPLE_GLOW}; border:1px solid {PURPLE}; border-radius:6px;"
                if idx == 0 else
                f"background:transparent; border:1px solid transparent; border-radius:6px;"
            )
            card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cly = QHBoxLayout(card); cly.setContentsMargins(8,8,8,8)
            ic = QLabel(icons_c[idx % len(icons_c)])
            ic.setFont(QFont("Segoe UI Emoji",10))
            ic.setStyleSheet(f"color:{PURPLE_LT}; background:transparent; border:none;")
            ic.setFixedWidth(18); cly.addWidget(ic)
            lft = QVBoxLayout(); lft.setSpacing(1)
            t1 = QLabel(titulo[:30]+("..." if len(titulo)>30 else ""))
            t1.setFont(QFont("Segoe UI",9,QFont.Weight.Bold))
            t1.setStyleSheet(f"color:{C_TEXT}; background:transparent; border:none;")
            t2 = QLabel(sub[:38]+("..." if len(sub)>38 else ""))
            t2.setFont(QFont("Segoe UI",7))
            t2.setStyleSheet(f"color:{C_TEXT2}; background:transparent; border:none;")
            lft.addWidget(t1); lft.addWidget(t2); cly.addLayout(lft,1)
            hora = QLabel(now.strftime("%H:%M")); hora.setFont(QFont("Segoe UI",7))
            hora.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            hora.setAlignment(Qt.AlignmentFlag.AlignTop); cly.addWidget(hora)
            container.addWidget(card)

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

    def _build_center(self):
        center = QWidget(); center.setStyleSheet(f"background:{BG_CENTER};")
        lay = QVBoxLayout(center); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)

        top = QWidget(); top.setStyleSheet(f"background:{BG_CENTER};")
        tl = QVBoxLayout(top); tl.setContentsMargins(0,18,0,10)
        tl.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        img_wrap = QWidget(); img_wrap.setFixedSize(190,190)
        img_wrap.setStyleSheet("background:transparent;")
        iw_lay = QVBoxLayout(img_wrap); iw_lay.setContentsMargins(10,10,10,10)

        self._emily_lbl = QLabel()
        self._emily_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._emily_lbl.setFixedSize(168,168)
        self._emily_lbl.setStyleSheet(f"background:{PURPLE_DIM}; border:2px solid {PURPLE}; border-radius:84px;")
        shdw = QGraphicsDropShadowEffect()
        shdw.setBlurRadius(32); shdw.setColor(QColor(PURPLE)); shdw.setOffset(0,0)
        self._emily_lbl.setGraphicsEffect(shdw)
        self._carregar_imagem_emily()
        iw_lay.addWidget(self._emily_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(img_wrap, alignment=Qt.AlignmentFlag.AlignHCenter)

        name_lbl = QLabel("Emily"); name_lbl.setFont(QFont("Segoe UI",22,QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color:{PURPLE_LT}; background:transparent;")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_lbl = QLabel("Sua assistente de IA pessoal"); sub_lbl.setFont(QFont("Segoe UI",9))
        sub_lbl.setStyleSheet(f"color:{C_TEXT2}; background:transparent;")
        sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_lbl = QLabel("Como posso te ajudar hoje?"); hint_lbl.setFont(QFont("Segoe UI",8))
        hint_lbl.setStyleSheet(f"color:{C_TEXT3}; background:transparent; font-style:italic;")
        hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(name_lbl); tl.addWidget(sub_lbl); tl.addWidget(hint_lbl)
        lay.addWidget(top)

        lay.addWidget(self._build_status_bar())
        lay.addWidget(self._hsep())
        lay.addWidget(self._build_chat_area(), 1)
        lay.addWidget(self._build_input_area())
        return center

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

    def _build_status_bar(self):
        bar = QFrame(); bar.setFixedHeight(48)
        bar.setStyleSheet(f"background:{BG_CARD}; border:1px solid {BORDER}; border-radius:8px; margin:6px 16px;")
        lay = QHBoxLayout(bar); lay.setContentsMargins(0,0,0,0); lay.setSpacing(0)
        self._status_dots = []
        estados = [("⏰","Aguardando"),("🎙","Ouvindo"),("💭","Pensando"),("🔊","Falando")]
        for i,(ic,nm) in enumerate(estados):
            if i>0:
                sp = QFrame(); sp.setFixedWidth(1); sp.setStyleSheet(f"background:{BORDER};"); lay.addWidget(sp)
            dot = QLabel(f"  {ic}  {nm}  ")
            dot.setFont(QFont("Segoe UI",8)); dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")
            lay.addWidget(dot,1); self._status_dots.append(dot)
        self._update_status_dots("aguardando")
        return bar

    def _update_status_dots(self, estado):
        idx = STATUS_TO_DOT.get(estado, 0)
        for i,dot in enumerate(self._status_dots):
            if i==idx:
                dot.setStyleSheet(f"color:{PURPLE_LT}; background:{PURPLE_DIM}; border:none; font-weight:bold; border-radius:4px;")
            else:
                dot.setStyleSheet(f"color:{C_TEXT3}; background:transparent; border:none;")

    def _build_chat_area(self):
        sc = QScrollArea(); sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sc.setStyleSheet(f"""
            QScrollArea {{ background:{BG_MAIN}; border:none; }}
            QScrollBar:vertical {{ width:4px; background:{BG_MAIN}; }}
            QScrollBar::handle:vertical {{ background:{BORDER}; border-radius:2px; }}
        """)
        self._chat_widget = QWidget(); self._chat_widget.setStyleSheet(f"background:{BG_MAIN};")
        self._chat_layout = QVBoxLayout(self._chat_widget)
        self._chat_layout.setContentsMargins(14,8,14,8); self._chat_layout.setSpacing(6)
        self._chat_layout.addStretch()
        sc.setWidget(self._chat_widget); self._chat_scroll = sc
        self._add_chat_msg("emily","Oi Vitor! Tô aqui, pode falar 😊")
        return sc

    def _build_input_area(self):
        area = QFrame()
        area.setStyleSheet(f"background:{BG_CENTER}; border-top:1px solid {BORDER};")
        lay = QVBoxLayout(area); lay.setContentsMargins(14,10,14,10); lay.setSpacing(0)

        box = QFrame()
        box.setStyleSheet(f"background:{BG_INPUT}; border:1px solid {BORDER}; border-radius:10px;")
        bl = QHBoxLayout(box); bl.setContentsMargins(6,5,6,5); bl.setSpacing(4)

        for ico,tip,fn in [("📎","Anexar arquivo",lambda:self._abrir_arquivo()),
                            ("🎁","Extras",None),("✨","Magia",None)]:
            b = QPushButton(ico); b.setFixedSize(30,30)
            b.setFont(QFont("Segoe UI Emoji",13)); b.setToolTip(tip)
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.setStyleSheet(f"background:transparent; color:{C_TEXT2}; border:none;")
            if fn: b.clicked.connect(fn)
            bl.addWidget(b)

        self._campo_texto = QTextEdit(); self._campo_texto.setFixedHeight(38)
        self._campo_texto.setFont(QFont("Segoe UI",10))
        self._campo_texto.setStyleSheet(f"QTextEdit {{ background:transparent; color:{C_TEXT}; border:none; padding:4px 2px; }}")
        self._campo_texto.setPlaceholderText("Digite sua mensagem...")
        self._campo_texto.installEventFilter(self)
        bl.addWidget(self._campo_texto, 1)

        self._btn_cam = QPushButton("📷"); self._btn_cam.setFixedSize(34,34)
        self._btn_cam.setFont(QFont("Segoe UI Emoji",13))
        self._btn_cam.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_cam.setStyleSheet(f"background:transparent; color:{C_TEXT2}; border:none;")
        self._btn_cam.clicked.connect(self._capturar_tela); bl.addWidget(self._btn_cam)

        self._btn_mic = QPushButton("🎤"); self._btn_mic.setFixedSize(38,38)
        self._btn_mic.setFont(QFont("Segoe UI Emoji",14))
        self._btn_mic.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_mic.setStyleSheet(f"QPushButton {{ background:{PURPLE}; color:white; border-radius:19px; border:none; }} QPushButton:hover {{ background:{PURPLE_DK}; }}")
        self._btn_mic.clicked.connect(self._ativar_ptt); bl.addWidget(self._btn_mic)

        self._btn_enviar = QPushButton("➤"); self._btn_enviar.setFixedSize(38,38)
        self._btn_enviar.setFont(QFont("Segoe UI",12,QFont.Weight.Bold))
        self._btn_enviar.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_enviar.setStyleSheet(f"QPushButton {{ background:{PURPLE}; color:white; border-radius:19px; border:none; }} QPushButton:hover {{ background:{PURPLE_DK}; }}")
        self._btn_enviar.clicked.connect(self._enviar); bl.addWidget(self._btn_enviar)
        lay.addWidget(box)
        return area

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
                    discord_bot._escuta_discord_ativa.set()
                    print("[Discord] Monitoramento de chats ATIVADO pela interface.")
                else:
                    discord_bot._escuta_discord_ativa.clear()
                    print("[Discord] Monitoramento de chats DESATIVADO pela interface.")
            except Exception as e:
                print(f"[Discord] toggle monitor: {e}")
        threading.Thread(target=_r, daemon=True).start()

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
        if status=="falando" and texto:
            self._em_falando=True; self._em_buffer.append(texto)
        elif self._em_falando and status!="falando":
            resp=" ".join(self._em_buffer).strip()
            if resp: self._add_chat_msg("emily",resp)
            self._em_buffer.clear(); self._em_falando=False

    def _add_chat_msg(self, autor, texto, sistema=False):
        bub = ChatBubble(texto, is_emily=(autor=="emily"))
        self._chat_layout.insertWidget(self._chat_layout.count()-1, bub)
        QTimer.singleShot(60, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()))

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
        if obj is self._campo_texto and event.type()==QEvent.Type.KeyPress:
            if event.key()==Qt.Key.Key_Return and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self._enviar(); return True
        return super().eventFilter(obj, event)

    def _enviar(self):
        txt = self._campo_texto.toPlainText().strip()
        if not txt: return
        self._campo_texto.clear(); self._add_chat_msg("user",txt)
        if getattr(self,"_callback_texto",None):
            threading.Thread(target=self._callback_texto,args=(txt,),daemon=True).start()

    def _abrir_arquivo(self):
        from PyQt6.QtWidgets import QFileDialog
        path,_ = QFileDialog.getOpenFileName(self,"Anexar arquivo","",
            "Imagens (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;Código (*.py *.js *.ts *.html *.css *.json *.txt *.md);;Todos (*.*)")
        if not path: return
        ext = os.path.splitext(path)[1].lower()
        if ext in (".png",".jpg",".jpeg",".gif",".bmp",".webp"):
            self._add_img_msg(path,"user")
        else:
            self._add_chat_msg("user",f"📎 {os.path.basename(path)}")
        if getattr(self,"_callback_arquivo",None):
            threading.Thread(target=self._callback_arquivo,args=(path,),daemon=True).start()

    def _ativar_ptt(self):
        def _r():
            try:
                import voz
                txt = voz.ouvir_ptt(callback_gravando=lambda: self.sig.status_changed.emit("gravando",""))
                if txt:
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

    def add_imagem_chat_safe(self, caminho: str, autor: str = "user"):
        self._sig.img_add.emit(caminho, autor)

    def mostrar_opcao_salvar(self, caminho: str):
        self._sig.salvar_imagem.emit(caminho)

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
