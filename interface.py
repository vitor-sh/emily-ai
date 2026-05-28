"""
interface.py — Emily v2 (painel redesenhado)

"""

import os
import threading
import tkinter as tk
from PIL import Image, ImageTk

# ─── Caminhos ────────────────────────────────────────────────────
DIR_BASE = os.path.dirname(os.path.abspath(__file__))
DIR_IMG  = os.path.join(DIR_BASE, "img")

# ─── Sprite ──────────────────────────────────────────────────────
COR_TRANSP     = "#010101"
COR_TRANSP_RGB = (1, 1, 1)
SPRITE_W       = 200
SPRITE_H       = 200

# ─── Paleta de cores do painel ───────────────────────────────────
C = {
    # Estrutura
    "fundo":        "#0e0e1c",   # fundo principal
    "fundo2":       "#131325",   # fundo do chat
    "topo":         "#0b0b18",   # barra de título
    "borda":        "#1e1e3a",   # bordas e separadores
    "entrada":      "#16162e",   # fundo do campo de input
    # Acentos
    "destaque":     "#6366f1",   # indigo — cor principal
    "destaque2":    "#4f46e5",   # indigo mais escuro (hover)
    "ping":         "#818cf8",   # indigo claro (ícones, indicadores)
    # Texto
    "texto":        "#e2e8f0",   # texto principal
    "texto2":       "#94a3b8",   # texto secundário / placeholder
    "texto3":       "#475569",   # texto apagado
    # Status
    "verde":        "#34d399",   # aguardando / ouvindo
    "azul":         "#60a5fa",   # falando / pesquisando
    "vermelho":     "#f87171",   # gravando
    "amarelo":      "#fbbf24",   # monitorando
    "lilas":        "#a78bfa",   # transferindo
    # Mensagens — bolhas
    "emily_bub":    "#1a1a35",   # fundo bolha Emily
    "emily_borda":  "#2a2a50",   # borda bolha Emily
    "emily_txt":    "#c7d2fe",   # texto bolha Emily
    "user_bub":     "#312e81",   # fundo bolha usuário
    "user_borda":   "#4338ca",   # borda bolha usuário
    "user_txt":     "#e0e7ff",   # texto bolha usuário
    "nome_emily":   "#818cf8",   # label "Emily"
    "nome_user":    "#60a5fa",   # label "Você"
}

# ─── Informações de cada status ──────────────────────────────────
STATUS = {
    "aguardando":   (C["verde"],    "● Aguardando"),
    "ouvindo":      (C["verde"],    "● Ouvindo..."),
    "gravando":     (C["vermelho"], "◉ Gravando..."),
    "falando":      (C["azul"],     "● Falando..."),
    "monitorando":  (C["amarelo"],  "● Monitorando..."),
    "transferindo": (C["lilas"],    "● Transferindo..."),
    "abrindo_app":  (C["verde"],    "● Abrindo..."),
    "pesquisando":  (C["azul"],     "● Pesquisando..."),
}

# ─── Mapeamento estado → GIF ─────────────────────────────────────
ESTADO_PARA_GIF = {
    "aguardando":   ("idle",     "idle"),
    "ouvindo":      ("uping",    "idle"),
    "gravando":     ("uping",    "idle"),
    "falando":      ("talk",     "idle"),
    "monitorando":  ("screen",   "idle"),
    "transferindo": ("transfer", "idle"),
    "abrindo_app":  ("open",     "uping"),
    "pesquisando":  ("search",   "idle"),
}
GIF_TRANSICAO = "uping"

# ─── Tamanho do painel ───────────────────────────────────────────
PW      = 480    # largura
PH      = 660    # altura
MAX_MSG = 80     # máximo de mensagens no histórico visual


class JanelaEmily:
    def __init__(self, callback_texto=None, callback_trocar_monitor=None):
        self.callback_texto          = callback_texto
        self.callback_trocar_monitor = callback_trocar_monitor
        self.callback_visao          = None
        self.visao_ativa             = False

        self._estado      = "aguardando"
        self._painel_vis  = True
        self._msg_count   = 0
        self._em_buffer   = []
        self._em_falando  = False

        self._criar_sprite()
        self._criar_painel()

        self._gifs: dict = {}
        self._carregar_gifs()

        self._gif_atual   = "idle"
        self._fidx        = 0
        self._ftimer      = 0
        self._modo        = "loop"
        self._gif_apos    = None
        self._estado_apos = None

        self._tid = threading.get_ident()
        self.root.after(33, self._tick)

    # ═════════════════════════════════════════════════════════════
    # SPRITE  (janela transparente com o GIF da personagem)
    # ═════════════════════════════════════════════════════════════

    def _criar_sprite(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-transparentcolor", COR_TRANSP)
        self.root.wm_attributes("-topmost", True)
        self.root.configure(bg=COR_TRANSP)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        self._sx = sw - SPRITE_W - 16
        self._sy = sh - SPRITE_H - 280
        self.root.geometry(f"{SPRITE_W}x{SPRITE_H}+{self._sx}+{self._sy}")

        self._cv = tk.Canvas(
            self.root, width=SPRITE_W, height=SPRITE_H,
            bg=COR_TRANSP, highlightthickness=0,
        )
        self._cv.pack()
        self._img_id = self._cv.create_image(0, 0, anchor="nw")

        self._cv.bind("<ButtonPress-1>", self._spr_drag_ini)
        self._cv.bind("<B1-Motion>",     self._spr_drag_mov)
        self._cv.bind("<Button-3>", lambda _: self._toggle_painel())

    # ═════════════════════════════════════════════════════════════
    # PAINEL  (janela de conversa — redesenhada)
    # ═════════════════════════════════════════════════════════════

    def _criar_painel(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()

        px = sw - PW - 24
        py = sh - PH - 56

        self._painel = tk.Toplevel(self.root)
        self._painel.overrideredirect(True)
        self._painel.wm_attributes("-topmost", True)
        self._painel.configure(bg=C["borda"])
        self._painel.geometry(f"{PW}x{PH}+{px}+{py}")

        # Frame interno (1px borda via bg do Toplevel)
        inn = tk.Frame(self._painel, bg=C["fundo"])
        inn.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_barra_titulo(inn)
        self._build_chat(inn)
        self._build_input(inn)
        self._build_rodape(inn)

    # ── Barra de título ──────────────────────────────────────────

    def _build_barra_titulo(self, parent):
        bar = tk.Frame(parent, bg=C["topo"], height=52)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        # Avatar da Emily (círculo com "E")
        av_frame = tk.Frame(bar, bg=C["destaque"], width=32, height=32)
        av_frame.place_forget()  # vamos usar pack
        av_canvas = tk.Canvas(bar, width=34, height=34,
                               bg=C["topo"], highlightthickness=0)
        av_canvas.pack(side="left", padx=(14, 0), pady=9)
        av_canvas.create_oval(2, 2, 32, 32, fill=C["destaque"], outline="")
        av_canvas.create_text(17, 17, text="E", fill="white",
                               font=("Segoe UI", 11, "bold"))

        # Status de presença (bolinha verde)
        av_canvas.create_oval(22, 22, 30, 30,
                               fill=C["verde"], outline=C["topo"], width=2)

        # Nome e subtítulo
        info = tk.Frame(bar, bg=C["topo"])
        info.pack(side="left", padx=10, pady=10)
        tk.Label(info, text="Emily", fg=C["texto"],
                 bg=C["topo"], font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(info, text="assistente pessoal", fg=C["texto3"],
                 bg=C["topo"], font=("Segoe UI", 8)).pack(anchor="w")

        # Lado direito: status pill + botão fechar
        right = tk.Frame(bar, bg=C["topo"])
        right.pack(side="right", padx=(4, 14), pady=10)

        bx = tk.Label(right, text="✕", fg=C["texto3"], bg=C["topo"],
                       font=("Segoe UI", 12), cursor="hand2")
        bx.pack(side="right", padx=(8, 0))
        bx.bind("<Button-1>", lambda _: self._toggle_painel())
        bx.bind("<Enter>",    lambda _: bx.config(fg=C["vermelho"]))
        bx.bind("<Leave>",    lambda _: bx.config(fg=C["texto3"]))

        # Label de status inline (ao lado do botão fechar)
        self._status_lbl = tk.Label(
            right, text="● Aguardando",
            fg=C["verde"], bg=C["topo"],
            font=("Segoe UI", 8),
        )
        self._status_lbl.pack(side="right")

        # Separador
        tk.Frame(parent, bg=C["borda"], height=1).pack(fill="x")

        # Drag pela barra
        for w in (bar, info):
            w.bind("<ButtonPress-1>", self._pan_drag_ini)
            w.bind("<B1-Motion>",     self._pan_drag_mov)
        for filho in info.winfo_children():
            filho.bind("<ButtonPress-1>", self._pan_drag_ini)
            filho.bind("<B1-Motion>",     self._pan_drag_mov)

    # ── Área de chat ─────────────────────────────────────────────

    def _build_chat(self, parent):
        cf = tk.Frame(parent, bg=C["fundo2"])
        cf.pack(fill="both", expand=True)

        # Scrollbar fina e discreta
        sb = tk.Scrollbar(cf, width=4, bd=0, relief="flat",
                           bg=C["borda"], troughcolor=C["fundo2"],
                           activebackground=C["destaque"])
        sb.pack(side="right", fill="y", pady=6, padx=(0, 2))

        self._chat = tk.Text(
            cf,
            bg=C["fundo2"], fg=C["texto"],
            font=("Segoe UI", 10),
            relief="flat", bd=0,
            wrap="word",
            state="disabled",
            cursor="arrow",
            yscrollcommand=sb.set,
            spacing1=0, spacing3=0,
            padx=16, pady=12,
        )
        sb.config(command=self._chat.yview)
        self._chat.pack(side="left", fill="both", expand=True)

        # ── Tags para formatação das bolhas ──
        # Nome Emily
        self._chat.tag_configure(
            "enome",
            foreground=C["nome_emily"],
            font=("Segoe UI", 8, "bold"),
            spacing1=14,
            spacing3=2,
        )
        # Bolha Emily
        self._chat.tag_configure(
            "emsg",
            foreground=C["emily_txt"],
            font=("Segoe UI", 10),
            background=C["emily_bub"],
            lmargin1=10, lmargin2=10,
            rmargin=50,
            spacing1=4,
            spacing3=10,
        )
        # Nome usuário
        self._chat.tag_configure(
            "unome",
            foreground=C["nome_user"],
            font=("Segoe UI", 8, "bold"),
            spacing1=14,
            spacing3=2,
            justify="right",
        )
        # Bolha usuário
        self._chat.tag_configure(
            "umsg",
            foreground=C["user_txt"],
            font=("Segoe UI", 10),
            background=C["user_bub"],
            lmargin1=50, lmargin2=50,
            rmargin=10,
            spacing1=4,
            spacing3=10,
            justify="right",
        )
        # Tag para espaço entre grupos de mensagens
        self._chat.tag_configure("sep", spacing1=4, spacing3=4)

        # Mensagem inicial
        self._add_chat("emily", "Oi Vitor! Tô aqui, pode falar 😊")

    # ── Campo de entrada ─────────────────────────────────────────

    def _build_input(self, parent):
        # Separador acima do input
        tk.Frame(parent, bg=C["borda"], height=1).pack(fill="x")

        area = tk.Frame(parent, bg=C["fundo"], pady=10)
        area.pack(fill="x", padx=14)

        # Borda que muda de cor no foco
        self._borda_input = tk.Frame(area, bg=C["borda"], bd=0)
        self._borda_input.pack(fill="x")

        inner = tk.Frame(self._borda_input, bg=C["entrada"])
        inner.pack(fill="x", padx=1, pady=1)

        # Usa Text widget (multiline) em vez de Entry — mais robusto
        self.campo_texto = tk.Text(
            inner,
            bg=C["entrada"], fg=C["texto"],
            insertbackground=C["texto"],
            font=("Segoe UI", 10),
            relief="flat", bd=8,
            wrap="word",
            height=1,          # começa com 1 linha
            maxundo=50,
        )
        self.campo_texto.pack(side="left", fill="x", expand=True, pady=2)

        # ── Placeholder ──
        self._PH    = "Escreva uma mensagem..."
        self._ph_on = True
        self.campo_texto.insert("1.0", self._PH)
        self.campo_texto.config(fg=C["texto2"])

        self.campo_texto.bind("<FocusIn>",     self._ph_clear)
        self.campo_texto.bind("<FocusOut>",    self._ph_set)
        self.campo_texto.bind("<Return>",      self._enviar_enter)
        self.campo_texto.bind("<Shift-Return>", self._nova_linha)
        self.campo_texto.bind("<KeyRelease>",  self._ajustar_altura)
        self.campo_texto.bind("<FocusIn>",
            lambda _: self._borda_input.config(bg=C["destaque"]), add="+")
        self.campo_texto.bind("<FocusOut>",
            lambda _: self._borda_input.config(bg=C["borda"]),    add="+")

        # Botão enviar
        benvia = tk.Label(
            inner, text="↑",
            bg=C["destaque"], fg="white",
            font=("Segoe UI", 14, "bold"),
            cursor="hand2", width=3, pady=6,
        )
        benvia.pack(side="right", padx=(4, 2), pady=2)
        benvia.bind("<Button-1>", self._enviar_click)
        benvia.bind("<Enter>",    lambda _: benvia.config(bg=C["destaque2"]))
        benvia.bind("<Leave>",    lambda _: benvia.config(bg=C["destaque"]))

        # Dica de teclado
        tk.Label(
            area, text="Enter para enviar  ·  Shift+Enter para nova linha",
            fg=C["texto3"], bg=C["fundo"],
            font=("Segoe UI", 7),
        ).pack(pady=(3, 0))

    # ── Rodapé com botões ────────────────────────────────────────

    def _build_rodape(self, parent):
        tk.Frame(parent, bg=C["borda"], height=1).pack(fill="x")

        rod = tk.Frame(parent, bg=C["topo"], height=40)
        rod.pack(fill="x", side="bottom")
        rod.pack_propagate(False)

        self._mon_num = 2
        self.botao_monitor = tk.Button(
            rod, text="🖥  Monitor 2",
            bg=C["topo"], fg=C["texto2"],
            font=("Segoe UI", 8), relief="flat", cursor="hand2",
            activebackground=C["borda"], bd=0,
            command=self._trocar_monitor,
        )
        self.botao_monitor.pack(side="left", fill="both", expand=True,
                                padx=(8, 2), pady=8)

        tk.Frame(rod, bg=C["borda"], width=1).pack(side="left", fill="y", pady=8)

        self.botao_visao = tk.Button(
            rod, text="👁  Tela: OFF",
            bg=C["topo"], fg=C["texto2"],
            font=("Segoe UI", 8), relief="flat", cursor="hand2",
            activebackground=C["borda"], bd=0,
            command=self._toggle_visao,
        )
        self.botao_visao.pack(side="right", fill="both", expand=True,
                               padx=(2, 8), pady=8)

    # ═════════════════════════════════════════════════════════════
    # CARREGAMENTO DE GIFs  (igual ao original)
    # ═════════════════════════════════════════════════════════════

    def _compor_frame(self, img: Image.Image) -> ImageTk.PhotoImage:
        frame = img.convert("RGBA")
        if frame.width > SPRITE_W or frame.height > SPRITE_H:
            frame.thumbnail((SPRITE_W, SPRITE_H), Image.LANCZOS)
        fundo = Image.new("RGB", (SPRITE_W, SPRITE_H), COR_TRANSP_RGB)
        ox = (SPRITE_W - frame.width)  // 2
        oy = (SPRITE_H - frame.height) // 2
        fundo.paste(frame, (ox, oy), mask=frame.split()[3])
        return ImageTk.PhotoImage(fundo)

    def _carregar_gifs(self):
        if not os.path.exists(DIR_IMG):
            print(f"[INTERFACE] Pasta img/ não encontrada: {DIR_IMG}")
            return
        for arq in os.listdir(DIR_IMG):
            if not arq.lower().endswith(".gif"):
                continue
            nome = arq[:-4].lower()
            try:
                img = Image.open(os.path.join(DIR_IMG, arq))
                frames, durs = [], []
                try:
                    while True:
                        frames.append(self._compor_frame(img.copy()))
                        d = img.info.get("duration", 100)
                        durs.append(max(1, round(d / 33)))
                        img.seek(img.tell() + 1)
                except EOFError:
                    pass
                if frames:
                    self._gifs[nome] = (frames, durs)
                    print(f"[INTERFACE] '{nome}' — {len(frames)} frames")
            except Exception as e:
                print(f"[INTERFACE] Erro ao carregar '{arq}': {e}")

        if not self._gifs:
            print("[INTERFACE] Nenhum GIF encontrado em img/")
        elif "idle" not in self._gifs:
            k = next(iter(self._gifs))
            self._gifs["idle"] = self._gifs[k]
            print(f"[INTERFACE] idle.gif não achado, usando '{k}' como fallback")

    def _res_gif(self, estado: str) -> str:
        pref, fb = ESTADO_PARA_GIF.get(estado, ("idle", "idle"))
        for c in (pref, fb, "idle"):
            if c in self._gifs:
                return c
        return next(iter(self._gifs), "idle")

    # ═════════════════════════════════════════════════════════════
    # LOOP DE ANIMAÇÃO  (igual ao original)
    # ═════════════════════════════════════════════════════════════

    def _troca_gif(self, nome: str, modo: str = "loop",
                   gif_apos: str = None, estado_apos: str = None):
        if nome not in self._gifs:
            nome = self._res_gif("aguardando")
        self._gif_atual   = nome
        self._fidx        = 0
        self._ftimer      = 0
        self._modo        = modo
        self._gif_apos    = gif_apos
        self._estado_apos = estado_apos

    def _tick(self):
        if self._gif_atual not in self._gifs:
            self.root.after(33, self._tick)
            return
        frs, drs = self._gifs[self._gif_atual]
        tot = len(frs)
        self._ftimer += 1
        if self._ftimer >= drs[self._fidx % tot]:
            self._ftimer = 0
            nx = self._fidx + 1
            if nx >= tot:
                if self._modo == "uma_vez" and self._gif_apos:
                    if self._estado_apos:
                        self._estado = self._estado_apos
                    self._troca_gif(self._gif_apos)
                else:
                    self._fidx = 0
            else:
                self._fidx = nx
        self._cv.itemconfig(self._img_id, image=frs[self._fidx % tot])
        self.root.after(33, self._tick)

    # ═════════════════════════════════════════════════════════════
    # DRAG
    # ═════════════════════════════════════════════════════════════

    def _spr_drag_ini(self, e):
        self._dx, self._dy = e.x, e.y

    def _spr_drag_mov(self, e):
        nx = self.root.winfo_x() + e.x - self._dx
        ny = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{nx}+{ny}")
        self._sx, self._sy = nx, ny

    def _pan_drag_ini(self, e):
        self._pdx, self._pdy = e.x_root, e.y_root
        self._px0, self._py0 = self._painel.winfo_x(), self._painel.winfo_y()

    def _pan_drag_mov(self, e):
        nx = self._px0 + e.x_root - self._pdx
        ny = self._py0 + e.y_root - self._pdy
        self._painel.geometry(f"+{nx}+{ny}")

    # ═════════════════════════════════════════════════════════════
    # TOGGLE DO PAINEL
    # ═════════════════════════════════════════════════════════════

    def _toggle_painel(self):
        if self._painel_vis:
            self._painel.withdraw()
        else:
            self._painel.deiconify()
        self._painel_vis = not self._painel_vis

    # ═════════════════════════════════════════════════════════════
    # PLACEHOLDER DO INPUT  (versão corrigida para Text widget)
    # ═════════════════════════════════════════════════════════════

    def _ph_clear(self, _=None):
        if self._ph_on:
            self.campo_texto.delete("1.0", tk.END)
            self.campo_texto.config(fg=C["texto"])
            self._ph_on = False

    def _ph_set(self, _=None):
        conteudo = self.campo_texto.get("1.0", tk.END).strip()
        if not conteudo:
            self.campo_texto.delete("1.0", tk.END)
            self.campo_texto.insert("1.0", self._PH)
            self.campo_texto.config(fg=C["texto2"], height=1)
            self._ph_on = True

    def _nova_linha(self, _=None):
        """Shift+Enter: insere nova linha sem enviar."""
        self.campo_texto.insert(tk.INSERT, "\n")
        return "break"

    def _ajustar_altura(self, _=None):
        """Redimensiona o campo conforme o texto cresce (máx. 5 linhas)."""
        if self._ph_on:
            return
        linhas = int(self.campo_texto.index(tk.END).split(".")[0]) - 1
        nova = max(1, min(linhas, 5))
        self.campo_texto.config(height=nova)

    # ═════════════════════════════════════════════════════════════
    # HISTÓRICO DE CHAT
    # ═════════════════════════════════════════════════════════════

    def _add_chat(self, autor: str, texto: str):
        """
        Insere uma mensagem na área de chat.
        Só deve ser chamado na thread principal do tkinter.
        """
        self._chat.config(state="normal")
        self._msg_count += 1

        if self._msg_count > MAX_MSG:
            # Remove as primeiras 4 linhas (nome + msg + espaçamento)
            self._chat.delete("1.0", "5.0")

        if autor == "emily":
            self._chat.insert(tk.END, "Emily\n", "enome")
            self._chat.insert(tk.END, texto + "\n", "emsg")
        else:
            self._chat.insert(tk.END, "Você\n", "unome")
            self._chat.insert(tk.END, texto + "\n", "umsg")

        self._chat.config(state="disabled")
        self._chat.see(tk.END)

    def _add_chat_safe(self, autor: str, texto: str):
        """Versão thread-safe de _add_chat."""
        if threading.get_ident() == self._tid:
            self._add_chat(autor, texto)
        else:
            self.root.after(0, lambda: self._add_chat(autor, texto))

    def carregar_historico(self, mensagens: list):
        """
        Popula o chat com mensagens anteriores ao iniciar.

        Parâmetro:
            mensagens: lista de dicts com chaves "role" e "content"
                       role pode ser "user" ou "assistant"

        Exemplo de uso no main.py:
            janela.carregar_historico(memoria.get("historico", []))
        """
        def _carregar():
            self._chat.config(state="normal")
            # Limpa o chat antes de carregar (remove a msg de boas-vindas)
            self._chat.delete("1.0", tk.END)
            self._msg_count = 0

            for msg in mensagens:
                role   = msg.get("role", "")
                texto  = msg.get("content", "").strip()
                if not texto:
                    continue
                if role == "assistant":
                    self._chat.insert(tk.END, "Emily\n", "enome")
                    self._chat.insert(tk.END, texto + "\n", "emsg")
                elif role == "user":
                    self._chat.insert(tk.END, "Você\n", "unome")
                    self._chat.insert(tk.END, texto + "\n", "umsg")
                self._msg_count += 1

            # Se não havia mensagens, recoloca a mensagem inicial
            if self._msg_count == 0:
                self._chat.insert(tk.END, "Emily\n", "enome")
                self._chat.insert(tk.END, "Oi Vitor! Tô aqui, pode falar 😊\n", "emsg")

            self._chat.config(state="disabled")
            self._chat.see(tk.END)

        if threading.get_ident() == self._tid:
            _carregar()
        else:
            self.root.after(0, _carregar)

    # ═════════════════════════════════════════════════════════════
    # CALLBACKS DOS BOTÕES
    # ═════════════════════════════════════════════════════════════

    def _toggle_visao(self):
        self.visao_ativa = not self.visao_ativa
        if self.visao_ativa:
            self.botao_visao.config(text="👁  Tela: ON",  fg=C["amarelo"])
        else:
            self.botao_visao.config(text="👁  Tela: OFF", fg=C["texto2"])
        if self.callback_visao:
            self.callback_visao()

    def _trocar_monitor(self):
        if self.callback_trocar_monitor:
            novo = self.callback_trocar_monitor()
            self._mon_num = novo
            self.botao_monitor.config(text=f"🖥  Monitor {novo}")

    def _get_texto_input(self) -> str:
        """Pega o texto do campo, ignorando placeholder."""
        if self._ph_on:
            return ""
        return self.campo_texto.get("1.0", tk.END).strip()

    def _limpar_input(self):
        """Limpa o campo e restaura placeholder."""
        self.campo_texto.delete("1.0", tk.END)
        self._ph_set()

    def _enviar_enter(self, _=None):
        """Enter sem Shift → envia a mensagem."""
        texto = self._get_texto_input()
        if texto:
            self._limpar_input()
            self._add_chat("user", texto)
            if self.callback_texto:
                threading.Thread(
                    target=self.callback_texto, args=(texto,), daemon=True
                ).start()
        return "break"   # impede o Enter de inserir nova linha

    def _enviar_click(self, _=None):
        """Clique no botão ↑ → envia a mensagem."""
        texto = self._get_texto_input()
        if texto:
            self._limpar_input()
            self._add_chat("user", texto)
            if self.callback_texto:
                threading.Thread(
                    target=self.callback_texto, args=(texto,), daemon=True
                ).start()

    # ═════════════════════════════════════════════════════════════
    # STATUS  (API pública — chamado pelo main.py)
    # ═════════════════════════════════════════════════════════════

    def _sync_status(self, status: str, texto: str):
        """Atualiza painel e animação. Sempre executado na thread do tkinter."""
        estado_ant   = self._estado
        self._estado = status

        fg, lbl = STATUS.get(status, STATUS["aguardando"])
        self._status_lbl.config(text=lbl, fg=fg)

        # Voz → chat: adiciona fala do usuário quando reconhecida
        if status == "ouvindo" and texto and texto.startswith('Você disse: "'):
            msg = texto[len('Você disse: "'):]
            if msg.endswith('"'):
                msg = msg[:-1]
            if msg:
                self._add_chat("user", msg)

        # Buffer da resposta da Emily
        if status == "falando" and texto:
            self._em_falando = True
            self._em_buffer.append(texto)
        elif self._em_falando and status != "falando":
            resposta = " ".join(self._em_buffer).strip()
            if resposta:
                self._add_chat("emily", resposta)
            self._em_buffer.clear()
            self._em_falando = False

        # Lógica de animação GIF
        gif_alvo = self._res_gif(status)

        if status == "aguardando":
            self._troca_gif("idle")
        elif (estado_ant == "aguardando"
              and GIF_TRANSICAO in self._gifs
              and gif_alvo != GIF_TRANSICAO):
            self._troca_gif(
                GIF_TRANSICAO, modo="uma_vez",
                gif_apos=gif_alvo, estado_apos=status,
            )
        elif gif_alvo != self._gif_atual:
            self._troca_gif(gif_alvo)

    def atualizar_status(self, status: str, texto: str = ""):
        """Thread-safe. Chamado pelo main.py para mudar o estado da Emily."""
        if threading.get_ident() == self._tid:
            self._sync_status(status, texto)
        else:
            self.root.after(0, lambda: self._sync_status(status, texto))

    def iniciar(self):
        """Inicia o mainloop. Bloqueia até a janela ser fechada."""
        self.root.mainloop()