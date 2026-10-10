"""
sprite_flutuante.py — o bonequinho animado, arrastável, sempre no topo.

Por que é um PROCESSO separado, e não uma thread
────────────────────────────────────────────────
A interface antiga rodava este sprite (a classe SpriteGif) numa thread de
fundo, ao lado do Qt. Funcionava porque o loop do Qt tolerava um Tk em thread
secundária. A interface nova usa pywebview, cujo motor (WebView2) toma a thread
principal com um message pump próprio — e o Tk, criado numa thread de fundo,
TRAVA: o interpretador Tcl é preso à thread que o criou e o ImageTk conversando
com ele de outra thread deadlocka.

Dois loops de GUI não cabem numa thread. A saída limpa é dar a cada um o SEU
processo, cada um dono da sua thread principal. Este arquivo é esse processo: um
Tk de verdade, com mainloop de verdade.

Protocolo (linha a linha, texto puro)
─────────────────────────────────────
  recebe no stdin :  "gif <nome>"   troca o gif exibido (idle, talk, ...)
                     "quit"          encerra
  escreve no stdout: "toggle"        o Vitor clicou com o botão direito

O interface_web.py sobe isto com subprocess, alimenta o stdin quando o estado
da Emily muda, e lê o stdout numa thread pra saber quando mostrar/esconder a
janela principal.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk

DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_IMG = os.path.join(DIR_BASE, "img")

COR_CHAVE = "#010101"   # cor pintada como transparente pela janela
LADO = 200
FPS = 30

# Quantos frames, no máximo, guardar por gif.
#
# idle.gif tem 244 frames e transfer.gif tem 183. Compor CADA um num
# PhotoImage 200x200 custava ~9,5s de boot só do sprite — ele só aparecia
# dez segundos depois da janela. Um sprite de canto não precisa de 244
# quadros: amostrando pra ~72, a animação continua fluida, cobre o loop
# inteiro (a amostragem é uniforme, não os 72 primeiros) e o boot cai pra ~3s.
MAX_FRAMES = 72


class Sprite:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)               # sem borda
        self.root.wm_attributes("-transparentcolor", COR_CHAVE)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=COR_CHAVE)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        # Canto inferior direito, acima da barra de tarefas — onde ela sempre ficou.
        self.root.geometry(f"{LADO}x{LADO}+{sw - LADO - 16}+{sh - LADO - 280}")

        self.cv = tk.Canvas(self.root, width=LADO, height=LADO,
                            bg=COR_CHAVE, highlightthickness=0)
        self.cv.pack()
        self.img_id = self.cv.create_image(0, 0, anchor="nw")

        self.cv.bind("<ButtonPress-1>", self._pega)
        self.cv.bind("<B1-Motion>", self._arrasta)
        self.cv.bind("<Button-3>", lambda e: self._emitir("toggle"))

        self._dx = self._dy = 0
        self._gifs: dict = {}
        self._cur = "idle"
        self._fidx = self._ftimer = 0
        self._alvo = queue.Queue()   # trocas de gif pedidas pelo stdin
        self._parar = threading.Event()  # pedido de encerrar, vindo de outra thread

        self._carregar_gifs()
        self._ouvir_stdin()
        self.root.after(int(1000 / FPS), self._tick)

    # ── Imagens ───────────────────────────────────────────────────

    def _compor(self, img):
        """Frame do gif centrado num fundo da cor-chave, virando PhotoImage."""
        from PIL import Image, ImageTk
        fr = img.convert("RGBA")
        if fr.width > LADO or fr.height > LADO:
            fr.thumbnail((LADO, LADO), Image.LANCZOS)
        fundo = Image.new("RGB", (LADO, LADO), (1, 1, 1))
        ox, oy = (LADO - fr.width) // 2, (LADO - fr.height) // 2
        fundo.paste(fr, (ox, oy), mask=fr.split()[3])
        return ImageTk.PhotoImage(fundo)

    def _carregar_gifs(self):
        if not os.path.isdir(DIR_IMG):
            return
        try:
            from PIL import Image
        except Exception as e:
            print(f"[SPRITE] PIL ausente: {e}", file=sys.stderr, flush=True)
            return
        for arq in os.listdir(DIR_IMG):
            if not arq.lower().endswith(".gif"):
                continue
            nome = arq[:-4].lower()
            try:
                img = Image.open(os.path.join(DIR_IMG, arq))
                total = getattr(img, "n_frames", 1)
                # Passo de amostragem: 1 = guarda todos, 4 = um a cada quatro.
                passo = max(1, -(-total // MAX_FRAMES))   # ceil(total / MAX)
                frames, duracoes = [], []
                acumulado = 0.0
                for i in range(total):
                    img.seek(i)
                    dur = img.info.get("duration", 100)
                    acumulado += dur
                    if i % passo == 0:
                        frames.append(self._compor(img.copy()))
                        # A duração do frame guardado absorve a dos pulados,
                        # pra o loop levar o mesmo tempo do gif original.
                        duracoes.append(max(1, round(acumulado / (1000 / FPS))))
                        acumulado = 0.0
                if frames:
                    self._gifs[nome] = (frames, duracoes)
            except Exception as e:
                print(f"[SPRITE] {arq}: {e}", file=sys.stderr, flush=True)
        if self._gifs and "idle" not in self._gifs:
            self._gifs["idle"] = self._gifs[next(iter(self._gifs))]

    # ── Animação ──────────────────────────────────────────────────

    def _tick(self):
        # Encerrar tem que acontecer AQUI, na thread do Tk. Chamar destroy()
        # (ou after()) da thread que lê o stdin não é thread-safe e não acorda
        # o mainloop — foi o que segurava o processo depois do "quit".
        if self._parar.is_set():
            try:
                self.root.destroy()
            except Exception:
                pass
            return

        # Aplica a última troca de gif pedida pelo stdin (uma por tick basta).
        try:
            while True:
                nome = self._alvo.get_nowait()
                if nome in self._gifs and nome != self._cur:
                    self._cur, self._fidx, self._ftimer = nome, 0, 0
        except queue.Empty:
            pass

        if self._cur in self._gifs:
            frames, duracoes = self._gifs[self._cur]
            total = len(frames)
            self._ftimer += 1
            if self._ftimer >= duracoes[self._fidx % total]:
                self._ftimer = 0
                self._fidx = (self._fidx + 1) % total
            self.cv.itemconfig(self.img_id, image=frames[self._fidx % total])

        self.root.after(int(1000 / FPS), self._tick)

    # ── Arrastar e clicar ─────────────────────────────────────────

    def _pega(self, e):
        self._dx, self._dy = e.x, e.y

    def _arrasta(self, e):
        nx = self.root.winfo_x() + e.x - self._dx
        ny = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{nx}+{ny}")

    @staticmethod
    def _emitir(msg: str):
        try:
            sys.stdout.write(msg + "\n")
            sys.stdout.flush()
        except Exception:
            pass

    # ── Canal com o processo pai ──────────────────────────────────

    def _ouvir_stdin(self):
        def _ler():
            # readline() em laço, e NÃO `for linha in sys.stdin`: a iteração de
            # arquivo do Python usa um buffer de leitura-adiante que segura a
            # linha até o buffer encher, então o "quit" chegava tarde. readline
            # respeita a fronteira da linha na hora.
            while True:
                try:
                    linha = sys.stdin.readline()
                except Exception:
                    break
                if not linha:            # stdin fechou = o pai morreu
                    break
                partes = linha.strip().split(None, 1)
                if not partes:
                    continue
                cmd = partes[0]
                if cmd == "quit":
                    break
                if cmd == "gif" and len(partes) > 1:
                    self._alvo.put(partes[1].strip().lower())
            self._fechar()
        threading.Thread(target=_ler, daemon=True).start()

    def _fechar(self):
        # Só sinaliza; quem chama destroy() é o _tick, na thread do Tk.
        self._parar.set()

    def rodar(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        Sprite().rodar()
    except Exception as e:  # noqa: BLE001
        print(f"[SPRITE] morreu: {type(e).__name__}: {e}", file=sys.stderr, flush=True)