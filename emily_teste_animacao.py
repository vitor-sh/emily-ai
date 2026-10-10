"""
Script de TESTE para validar o pipeline de animação da Emily.

Reescrito para seguir a MESMA técnica já comprovada na sua interface.py
(classe SpriteGif): Canvas de tamanho fixo + composição sobre uma
cor-chave quase-preta, em vez de Label + magenta. Duas coisas que essa
versão corrige em relação à anterior:

  1. Cor-chave "#010101" (quase-preto) em vez de magenta puro — evita
     que sobras de borda apareçam como manchas coloridas, e é diferente
     o bastante de um preto puro "#000000" pra não apagar contornos
     pretos de verdade do desenho da Emily.

  2. Canvas de tamanho FIXO com a imagem centralizada dentro, em vez de
     redimensionar a janela com base na imagem carregada (isso causava
     uma janela de 1x1 pixel antes da primeira imagem existir).

O QUE ELE FAZ:
- Abre uma janela flutuante sem borda, com fundo transparente de verdade.
- Toca em loop os frames PNG de uma pasta, como um flipbook.
- Troca de animação em tempo real ao apertar uma tecla.

COMO USAR:
1. Crie pastas dentro de "animacoes/" com o nome de cada ação:
       animacoes/idle/frame_01.png, frame_02.png, ...
       animacoes/arrastar/frame_01.png, frame_02.png, ...
   (os PNGs já devem estar com fundo transparente, ex: saída do rembg)

2. Rode: python emily_teste_animacao.py

3. Com a janela em foco, aperte:
       1 -> toca a animação "idle"
       2 -> toca a animação "arrastar"
       3 -> toca a animação "uping" (se você criar essa pasta)
       ESC -> fecha
"""

import tkinter as tk
from pathlib import Path
from PIL import Image, ImageTk

PASTA_ANIMACOES = Path(__file__).parent / "animacoes"
FPS = 6  # frames por segundo -> ajuste conforme quantos frames você gerou

# Mesma escolha de cor da SpriteGif: quase-preto, não preto puro.
COR_CHAVE = "#010101"
COR_CHAVE_RGB = (1, 1, 1)

# Tamanho fixo do canvas. Se seus frames forem maiores que isso, aumente.
LARGURA, ALTURA = 260, 260


class EmilyOverlay:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", COR_CHAVE)
        self.root.configure(bg=COR_CHAVE)

        self.canvas = tk.Canvas(
            self.root, width=LARGURA, height=ALTURA,
            bg=COR_CHAVE, highlightthickness=0,
        )
        self.canvas.pack()
        self._img_id = self.canvas.create_image(0, 0, anchor="nw")

        self.animacoes: dict[str, list[ImageTk.PhotoImage]] = {}
        self.acao_atual = None
        self.indice_frame = 0

        self.carregar_animacoes()
        self.posicionar_janela()

        self.root.bind("<Key-1>", lambda e: self.mudar_acao("idle"))
        self.root.bind("<Key-2>", lambda e: self.mudar_acao("arrastar"))
        self.root.bind("<Key-3>", lambda e: self.mudar_acao("uping"))
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.focus_force()

        if self.animacoes:
            self.mudar_acao(next(iter(self.animacoes)))

    def _compor_frame(self, caminho_png: Path) -> ImageTk.PhotoImage:
        """Mesma lógica da SpriteGif._compor_frame: redimensiona se
        precisar, cria um canvas do tamanho fixo preenchido com a
        cor-chave, e cola a imagem original centralizada, usando o
        canal alpha como máscara de transparência."""
        fr = Image.open(caminho_png).convert("RGBA")
        if fr.width > LARGURA or fr.height > ALTURA:
            fr.thumbnail((LARGURA, ALTURA), Image.LANCZOS)

        fundo = Image.new("RGB", (LARGURA, ALTURA), COR_CHAVE_RGB)
        ox = (LARGURA - fr.width) // 2
        oy = (ALTURA - fr.height) // 2
        fundo.paste(fr, (ox, oy), mask=fr.split()[3])
        return ImageTk.PhotoImage(fundo)

    def carregar_animacoes(self):
        if not PASTA_ANIMACOES.exists():
            print(f"[AVISO] Pasta não encontrada: {PASTA_ANIMACOES}")
            print("Crie 'animacoes/idle/' com alguns PNGs pra testar.")
            return

        for pasta_acao in sorted(PASTA_ANIMACOES.iterdir()):
            if not pasta_acao.is_dir():
                continue
            frames = sorted(pasta_acao.glob("*.png"))
            if not frames:
                continue
            imagens = [self._compor_frame(f) for f in frames]
            self.animacoes[pasta_acao.name] = imagens
            print(f"[OK] Carregada ação '{pasta_acao.name}' com {len(imagens)} frames")

        if not self.animacoes:
            print("[AVISO] Nenhuma animação encontrada em animacoes/*/")

    def posicionar_janela(self):
        """Tamanho fixo (LARGURA x ALTURA), então não depende de nenhuma
        medição da imagem — evita o bug de janela 1x1."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - LARGURA - 40
        y = sh - ALTURA - 80
        self.root.geometry(f"{LARGURA}x{ALTURA}+{x}+{y}")

    def mudar_acao(self, nome_acao: str):
        """Esta é a função que, no futuro, a Emily vai chamar sozinha
        quando decidir mudar de comportamento."""
        if nome_acao not in self.animacoes:
            print(f"[IGNORADO] Ação '{nome_acao}' não tem pasta/frames carregados.")
            return
        if nome_acao == self.acao_atual:
            return
        print(f"[TROCA] Ação atual -> {nome_acao}")
        self.acao_atual = nome_acao
        self.indice_frame = 0

    def animar(self):
        if self.acao_atual and self.animacoes.get(self.acao_atual):
            frames = self.animacoes[self.acao_atual]
            tot = len(frames)
            self.canvas.itemconfig(self._img_id, image=frames[self.indice_frame % tot])
            self.indice_frame = (self.indice_frame + 1) % tot
        self.root.after(int(1000 / FPS), self.animar)


def main():
    root = tk.Tk()
    overlay = EmilyOverlay(root)
    overlay.animar()
    root.mainloop()


if __name__ == "__main__":
    main()