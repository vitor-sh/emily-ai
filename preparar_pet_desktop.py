"""Extrai quadros das artes geradas para o pet do Fedora.

Só faz recorte, escala e alinhamento; os desenhos vêm das folhas PNG.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


BASE = Path(__file__).resolve().parent / "assets" / "desktop_pet_v2"
ESTADOS = {
    "idle": (3, 2, 220),
    "listening": (2, 2, 235),
    "speaking": (2, 2, 195),
    "thinking": (2, 2, 260),
    "working": (2, 2, 235),
    "idle_playful": (2, 2, 270),
    "idle_stretch": (2, 2, 280),
    "idle_sit": (3, 3, 310),
    "idle_ram": (3, 3, 285),
    "idle_star": (3, 3, 255),
}
LARGURA, ALTURA = 240, 260
ESTADOS_GERADOS_NOVOS = {"idle_sit", "idle_ram", "idle_star"}


def _remover_fragmentos_da_grade(quadro: Image.Image) -> Image.Image:
    """Remove sobras pequenas desconectadas das células vizinhas da folha."""
    largura, altura = quadro.size
    alpha = quadro.getchannel("A").tobytes()
    visitados = bytearray(largura * altura)
    remover = []
    for indice, valor in enumerate(alpha):
        if valor < 8 or visitados[indice]:
            continue
        componente = [indice]
        visitados[indice] = 1
        for pixel in componente:
            x, y = pixel % largura, pixel // largura
            for vizinho in (pixel - 1, pixel + 1, pixel - largura, pixel + largura):
                if (vizinho < 0 or vizinho >= len(alpha)
                        or abs(vizinho % largura - x) + abs(vizinho // largura - y) != 1
                        or visitados[vizinho] or alpha[vizinho] < 8):
                    continue
                visitados[vizinho] = 1
                componente.append(vizinho)
        if len(componente) < 400 and (
                min(p // largura for p in componente) <= 35
                or max(p // largura for p in componente) >= altura - 19):
            remover.extend(componente)
    if remover:
        pixels = quadro.load()
        for pixel in remover:
            pixels[pixel % largura, pixel // largura] = (0, 0, 0, 0)
    return quadro


def preparar(base: Path = BASE) -> dict:
    manifest = {"width": LARGURA, "height": ALTURA, "states": {}}
    quadros_por_estado = {}
    for estado, (colunas, linhas, duracao) in ESTADOS.items():
        folha = Image.open(base / f"{estado}_sheet.png").convert("RGBA")
        quadros = []
        imagens = []
        pasta = base / "frames" / estado
        pasta.mkdir(parents=True, exist_ok=True)
        for i in range(colunas * linhas):
            coluna, linha = i % colunas, i // colunas
            # O gerador pode entregar uma largura não divisível pela grade;
            # distribuir esse pixel evita cortar a última pose.
            x0, x1 = coluna * folha.width // colunas, (coluna + 1) * folha.width // colunas
            y0, y1 = linha * folha.height // linhas, (linha + 1) * folha.height // linhas
            celula = folha.crop((x0, y0, x1, y1))
            cw, ch = celula.size
            caixa = celula.getchannel("A").point(
                lambda valor: 255 if valor > 40 else 0).getbbox()
            if not caixa:
                raise ValueError(f"Quadro vazio: {estado}/{i + 1}")
            # A margem evita cortar os fios de cabelo sem conservar o espaço
            # inconsistente que a geração deixou em cada célula.
            margem = 5
            caixa = (max(0, caixa[0] - margem), max(0, caixa[1] - margem),
                     min(cw, caixa[2] + margem), min(ch, caixa[3] + margem))
            figura = celula.crop(caixa)
            escala = min(222 / figura.height, 228 / figura.width)
            figura = figura.resize((round(figura.width * escala),
                                    round(figura.height * escala)), Image.Resampling.LANCZOS)
            quadro = Image.new("RGBA", (LARGURA, ALTURA))
            quadro.alpha_composite(figura, ((LARGURA - figura.width) // 2,
                                             249 - figura.height))
            if estado in ESTADOS_GERADOS_NOVOS:
                quadro = _remover_fragmentos_da_grade(quadro)
            nome = f"{i + 1:02d}.png"
            quadro.save(pasta / nome, optimize=True)
            quadros.append(f"frames/{estado}/{nome}")
            imagens.append(quadro)
        manifest["states"][estado] = {"frames": quadros, "duration_ms": duracao}
        if estado == "idle_sit":
            # Repetir só o balanço das pernas; entrada e saída ocorrem uma vez.
            manifest["states"][estado]["loop_segment"] = [3, 6, 2]
        fundo = Image.new("RGBA", (LARGURA, ALTURA), "#262321")
        imagens_preview = [Image.alpha_composite(fundo, q).convert("RGB") for q in imagens]
        quadros_por_estado[estado] = imagens_preview
        imagens_preview[0].save(base / f"preview_{estado}.gif", save_all=True,
                                append_images=imagens_preview[1:], duration=duracao,
                                loop=0, optimize=True)
    largura_celula, altura_celula = LARGURA, ALTURA + 20
    painel = Image.new("RGB", (largura_celula * 9, altura_celula * len(ESTADOS)), "#262321")
    desenho = ImageDraw.Draw(painel)
    animacao = []
    duracoes = []
    for linha, (estado, (_, _, duracao)) in enumerate(ESTADOS.items()):
        quadros = quadros_por_estado[estado]
        for coluna, quadro in enumerate(quadros):
            x, y = coluna * largura_celula, linha * altura_celula
            desenho.text((x + 8, y + 3), f"{estado} {coluna + 1:02d}", fill="#c9c1bb")
            painel.paste(quadro, (x, y + 20))
        miolo = manifest["states"][estado].get("loop_segment")
        ordem = list(range(len(quadros)))
        if miolo:
            inicio, fim, vezes = miolo
            ordem = list(range(fim + 1)) + list(range(inicio, fim + 1)) * vezes + list(range(fim + 1, len(quadros)))
        animacao.extend(quadros[i] for i in ordem)
        duracoes.extend([duracao] * len(ordem))
    painel.save(base / "contact_sheet.jpg", quality=88)
    animacao[0].save(base / "preview_completo.gif", save_all=True,
                     append_images=animacao[1:], duration=duracoes,
                     loop=0, optimize=True)
    (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
                                               indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    dados = preparar()
    print({nome: len(item["frames"]) for nome, item in dados["states"].items()})
