"""Gera os dois estados visuais da Emily para o mod de Hollow Knight.

O estado ativo parte da referência em perspectiva salva em ``art/``. As duas
asas visíveis são isoladas e rotacionadas ao redor das próprias articulações.
O ciclo combina três batidas de asa com flutuação, balanço, impulso e uma
deformação elástica sutil do corpo para evitar uma aparência estática.

O estado de banco preserva os 24 frames exportados do rig antigo. Assim, a
animação frontal aprovada em gameplay continua existindo, mas apenas enquanto
o Cavaleiro estiver sentado em um banco.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


RAIZ = Path(__file__).resolve().parents[2]
PASTA_MOD = RAIZ / "hollow_knight_emily"
ENTRADA_BANCO = PASTA_MOD / ".cache" / "emily-idle-raw"
REFERENCIA_ATIVA = PASTA_MOD / "art" / "emily_hk_referencia_expectativa.png"
SAIDA = PASTA_MOD / "mod" / "Assets"
PREVIAS = PASTA_MOD / "art" / "previews"

FRAME_COUNT = 24
COLUNAS = 4
LINHAS = 6
FPS = 12
PPU = 180

RECORTE_BANCO = (16, 88, 496, 424)
CELULA_BANCO = (240, 168)
CELULA_ATIVA = (216, 192)

# Regiões desenhadas sobre a referência 1254x1254. Os pivôs ficam exatamente
# nas junções das asas com o tórax, para que a batida não pareça uma rotação da
# personagem inteira.
POLIGONO_ASA_SUPERIOR = (
    (388, 445), (438, 437), (502, 462), (558, 512), (610, 580),
    (660, 650), (664, 714), (626, 729), (576, 715), (526, 697),
    (478, 677), (438, 647), (408, 607), (391, 554),
)
POLIGONO_ASA_INFERIOR = (
    (388, 700), (438, 677), (498, 672), (558, 688), (626, 710),
    (642, 730), (594, 768), (531, 785), (465, 781), (407, 751),
)
PIVO_ASA_SUPERIOR = (648, 694)
PIVO_ASA_INFERIOR = (632, 710)
PIVO_CORPO = (704, 713)
ALPHA_VISIVEL = 8


def _salvar_png_como_bytes(imagem: Image.Image, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(caminho, format="PNG", optimize=True)


def _bbox_visivel(imagem: Image.Image) -> tuple[int, int, int, int] | None:
    """Ignora o halo alpha=1 presente nas bordas do PNG de referência."""
    alpha = imagem.getchannel("A")
    mascara = alpha.point(lambda valor: 255 if valor >= ALPHA_VISIVEL else 0)
    return mascara.getbbox()


def _mascara_poligono(tamanho: tuple[int, int], pontos: tuple[tuple[int, int], ...]) -> Image.Image:
    mascara = Image.new("L", tamanho, 0)
    ImageDraw.Draw(mascara).polygon(pontos, fill=255)
    return mascara


def _aplicar_mascara(imagem: Image.Image, mascara: Image.Image) -> Image.Image:
    resultado = imagem.copy()
    resultado.putalpha(ImageChops.multiply(imagem.getchannel("A"), mascara))
    return resultado


def _remover_mascaras(imagem: Image.Image, *mascaras: Image.Image) -> Image.Image:
    uniao = Image.new("L", imagem.size, 0)
    for mascara in mascaras:
        uniao = ImageChops.lighter(uniao, mascara)
    resultado = imagem.copy()
    resultado.putalpha(ImageChops.multiply(imagem.getchannel("A"), ImageChops.invert(uniao)))
    return resultado


def _rotacionar_camada(camada: Image.Image, graus: float, pivo: tuple[int, int]) -> Image.Image:
    return camada.rotate(
        graus,
        resample=Image.Resampling.BICUBIC,
        center=pivo,
        expand=False,
    )


def _transformar_personagem(
    imagem: Image.Image,
    graus: float,
    deslocamento: tuple[int, int],
    escala: tuple[float, float],
) -> Image.Image:
    escala_x, escala_y = escala
    pivo_x, pivo_y = PIVO_CORPO
    deformada = imagem.transform(
        imagem.size,
        Image.Transform.AFFINE,
        (
            1.0 / escala_x,
            0.0,
            pivo_x - pivo_x / escala_x,
            0.0,
            1.0 / escala_y,
            pivo_y - pivo_y / escala_y,
        ),
        resample=Image.Resampling.BICUBIC,
    )
    inclinada = deformada.rotate(
        graus,
        resample=Image.Resampling.BICUBIC,
        center=PIVO_CORPO,
        expand=False,
    )
    resultado = Image.new("RGBA", imagem.size, (0, 0, 0, 0))
    resultado.alpha_composite(inclinada, deslocamento)
    return resultado


def _normalizar_frames(
    frames: list[Image.Image],
    celula: tuple[int, int],
    margem: int,
) -> list[Image.Image]:
    caixas = [_bbox_visivel(frame) for frame in frames]
    if any(caixa is None for caixa in caixas):
        raise RuntimeError("A animação gerou um frame vazio.")
    uniao = (
        min(caixa[0] for caixa in caixas if caixa),
        min(caixa[1] for caixa in caixas if caixa),
        max(caixa[2] for caixa in caixas if caixa),
        max(caixa[3] for caixa in caixas if caixa),
    )
    recorte = (
        max(0, uniao[0] - margem),
        max(0, uniao[1] - margem),
        min(frames[0].width, uniao[2] + margem),
        min(frames[0].height, uniao[3] + margem),
    )
    largura, altura = recorte[2] - recorte[0], recorte[3] - recorte[1]
    escala = min(celula[0] / largura, celula[1] / altura)
    tamanho = (max(1, round(largura * escala)), max(1, round(altura * escala)))

    normalizados: list[Image.Image] = []
    for frame in frames:
        personagem = frame.crop(recorte).resize(tamanho, Image.Resampling.LANCZOS)
        destino = Image.new("RGBA", celula, (0, 0, 0, 0))
        destino.alpha_composite(
            personagem,
            ((celula[0] - tamanho[0]) // 2, (celula[1] - tamanho[1]) // 2),
        )
        normalizados.append(destino)
    return normalizados


def _frames_ativos() -> list[Image.Image]:
    if not REFERENCIA_ATIVA.is_file():
        raise RuntimeError(f"Referência ativa não encontrada: {REFERENCIA_ATIVA}")
    referencia = Image.open(REFERENCIA_ATIVA).convert("RGBA")
    if referencia.size != (1254, 1254):
        raise RuntimeError(f"Dimensão inesperada na referência ativa: {referencia.size}")
    if referencia.getchannel("A").getextrema() != (0, 255):
        raise RuntimeError("A referência ativa não possui transparência completa.")

    mascara_superior = _mascara_poligono(referencia.size, POLIGONO_ASA_SUPERIOR)
    mascara_inferior = _mascara_poligono(referencia.size, POLIGONO_ASA_INFERIOR)
    mascara_inferior = ImageChops.subtract(mascara_inferior, mascara_superior)
    asa_superior = _aplicar_mascara(referencia, mascara_superior)
    asa_inferior = _aplicar_mascara(referencia, mascara_inferior)
    corpo = _remover_mascaras(referencia, mascara_superior, mascara_inferior)

    frames: list[Image.Image] = []
    for indice in range(FRAME_COUNT):
        fase_ciclo = indice / FRAME_COUNT * math.tau
        fase_asas = fase_ciclo * 3.0
        impulso = math.cos(fase_asas)
        angulo_superior = (
            math.sin(fase_asas) * 12.5
            + math.sin(fase_asas * 2.0 + 0.35) * 1.6
        )
        angulo_inferior = (
            math.sin(fase_asas - 0.48) * 8.5
            + math.sin(fase_asas * 2.0 - 0.15) * 1.1
        )
        quadro = Image.new("RGBA", referencia.size, (0, 0, 0, 0))
        quadro.alpha_composite(
            _rotacionar_camada(asa_superior, angulo_superior, PIVO_ASA_SUPERIOR)
        )
        quadro.alpha_composite(
            _rotacionar_camada(asa_inferior, angulo_inferior, PIVO_ASA_INFERIOR)
        )
        quadro.alpha_composite(corpo)
        inclinacao = (
            math.sin(fase_ciclo + 0.65) * 2.0
            + math.sin(fase_asas + 0.2) * 0.4
        )
        deslocamento_x = round(
            math.sin(fase_ciclo) * 5.0
            + math.sin(fase_asas + 0.4) * 1.5
        )
        deslocamento_y = round(
            math.sin(fase_ciclo - 0.3) * 8.0
            - impulso * 2.5
        )
        escala_x = 1.0 + impulso * 0.012
        escala_y = 1.0 - impulso * 0.018
        frames.append(
            _transformar_personagem(
                quadro,
                inclinacao,
                (deslocamento_x, deslocamento_y),
                (escala_x, escala_y),
            )
        )

    return _normalizar_frames(frames, CELULA_ATIVA, margem=18)


def _frames_banco() -> list[Image.Image]:
    caminhos = sorted(ENTRADA_BANCO.glob("frame_*.png"))
    if len(caminhos) != FRAME_COUNT:
        raise RuntimeError(
            f"Esperados {FRAME_COUNT} frames em {ENTRADA_BANCO}, encontrados {len(caminhos)}."
        )
    frames: list[Image.Image] = []
    for caminho in caminhos:
        imagem = Image.open(caminho).convert("RGBA")
        if imagem.size != (512, 512):
            raise RuntimeError(f"Dimensão inesperada em {caminho}: {imagem.size}")
        if imagem.getchannel("A").getextrema() != (0, 255):
            raise RuntimeError(f"Canal alpha inválido em {caminho}")
        frames.append(imagem.crop(RECORTE_BANCO).resize(CELULA_BANCO, Image.Resampling.LANCZOS))
    return frames


def _montar_sheet(frames: list[Image.Image], celula: tuple[int, int]) -> Image.Image:
    sheet = Image.new("RGBA", (celula[0] * COLUNAS, celula[1] * LINHAS), (0, 0, 0, 0))
    for indice, frame in enumerate(frames):
        sheet.alpha_composite(
            frame,
            ((indice % COLUNAS) * celula[0], (indice // COLUNAS) * celula[1]),
        )
    return sheet


def _salvar_previas(
    nome: str,
    frames: list[Image.Image],
    indices: tuple[int, int, int, int],
) -> None:
    PREVIAS.mkdir(parents=True, exist_ok=True)
    largura = sum(frames[i].width for i in indices)
    preview = Image.new("RGBA", (largura, max(frames[i].height for i in indices)), (0, 0, 0, 0))
    x = 0
    for indice in indices:
        preview.alpha_composite(frames[indice], (x, 0))
        x += frames[indice].width
    preview.save(PREVIAS / f"Emily{nome}Preview.png", optimize=True)


def _salvar_gif(nome: str, frames: list[Image.Image]) -> None:
    PREVIAS.mkdir(parents=True, exist_ok=True)
    # GIF armazena a duração em centésimos de segundo. A sequência 80/80/90 ms
    # repete oito vezes e fecha os 24 frames em exatamente 2 segundos (12 FPS).
    duracoes = [80 if indice % 3 != 2 else 90 for indice in range(FRAME_COUNT)]
    frames[0].save(
        PREVIAS / f"Emily{nome}.gif",
        save_all=True,
        append_images=frames[1:],
        duration=duracoes,
        loop=0,
        disposal=2,
        transparency=0,
        optimize=False,
    )


def _metadados(
    nome: str,
    frames: list[Image.Image],
    celula: tuple[int, int],
    sheet: Image.Image,
    origem: str,
) -> dict[str, object]:
    caixas = [_bbox_visivel(frame) for frame in frames]
    uniao = (
        min(caixa[0] for caixa in caixas if caixa),
        min(caixa[1] for caixa in caixas if caixa),
        max(caixa[2] for caixa in caixas if caixa),
        max(caixa[3] for caixa in caixas if caixa),
    )
    return {
        "estado": nome,
        "frames": FRAME_COUNT,
        "fps": FPS,
        "duracao_segundos": FRAME_COUNT / FPS,
        "colunas": COLUNAS,
        "linhas": LINHAS,
        "celula_pixels": list(celula),
        "spritesheet_pixels": list(sheet.size),
        "pivo_normalizado": [0.5, 0.5],
        "pixels_por_unidade": PPU,
        "bounds_visuais_pixels": list(uniao),
        "tamanho_visual_unidades": [
            round((uniao[2] - uniao[0]) / PPU, 4),
            round((uniao[3] - uniao[1]) / PPU, 4),
        ],
        "origem": origem,
    }


def processar() -> None:
    ativos = _frames_ativos()
    banco = _frames_banco()
    sheet_ativo = _montar_sheet(ativos, CELULA_ATIVA)
    sheet_banco = _montar_sheet(banco, CELULA_BANCO)

    _salvar_png_como_bytes(sheet_ativo, SAIDA / "EmilyActive.png.bytes")
    _salvar_png_como_bytes(sheet_banco, SAIDA / "EmilyBench.png.bytes")

    primeiro = ativos[0]
    bbox = _bbox_visivel(primeiro)
    if bbox is None:
        raise RuntimeError("Primeiro frame ativo ficou vazio.")
    personagem = primeiro.crop(bbox)
    personagem.thumbnail((112, 112), Image.Resampling.LANCZOS)
    icone = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    icone.alpha_composite(
        personagem,
        ((icone.width - personagem.width) // 2, (icone.height - personagem.height) // 2),
    )
    _salvar_png_como_bytes(icone, SAIDA / "EmilyCharm.png.bytes")

    metadados = {
        "ativo": _metadados(
            "ativo",
            ativos,
            CELULA_ATIVA,
            sheet_ativo,
            "art/emily_hk_referencia_expectativa.png",
        ),
        "banco": _metadados(
            "banco",
            banco,
            CELULA_BANCO,
            sheet_banco,
            ".cache/emily-idle-raw/frame_*.png",
        ),
        "alternancia": "PlayerData.atBench",
        "orientacao": "HeroController.cState.facingRight",
        "movimento_ativo": {
            "batidas_de_asa_por_ciclo": 3,
            "componentes": [
                "asas_articuladas",
                "flutuacao_vertical",
                "balanco_horizontal",
                "inclinacao",
                "impulso_elastico",
            ],
        },
    }
    (SAIDA / "EmilyVisual.json").write_text(
        json.dumps(metadados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _salvar_previas("Active", ativos, (0, 2, 4, 6))
    _salvar_previas("Bench", banco, (0, 6, 12, 18))
    _salvar_gif("Active", ativos)
    _salvar_gif("Bench", banco)

    ativo = metadados["ativo"]["tamanho_visual_unidades"]
    sentado = metadados["banco"]["tamanho_visual_unidades"]
    print(
        f"Arte processada: ativo={ativo[0]:.3f}x{ativo[1]:.3f}, "
        f"banco={sentado[0]:.3f}x{sentado[1]:.3f} unidades, "
        f"{FRAME_COUNT} frames por estado a {FPS} FPS"
    )


if __name__ == "__main__":
    processar()