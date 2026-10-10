"""Benchmark opt-in do decisor visual real contra telas locais determinísticas.

Uso: python3 testes/benchmark_agente_visual_gpt6.py [--case calendario]
Faz chamadas pagas ao OmniRoute; não executa cliques no desktop.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import desktop_backend  # noqa: E402
import llm  # noqa: E402
import modelo  # noqa: E402


FONTE = "/usr/share/fonts/google-noto/NotoSans-Regular.ttf"
FONTE_NEGRITO = "/usr/share/fonts/google-noto/NotoSans-Bold.ttf"


def _fonte(tamanho: int, negrito: bool = False):
    try:
        return ImageFont.truetype(FONTE_NEGRITO if negrito else FONTE, tamanho)
    except OSError:
        return ImageFont.load_default()


def _texto(d, xy, valor, tamanho=20, cor="#ece8e2", negrito=False):
    d.text(xy, valor, font=_fonte(tamanho, negrito), fill=cor)


def tela(caso: str):
    img = Image.new("RGB", (1280, 800), "#17191d")
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1280, 58), fill="#272b32")
    if caso == "calendario":
        _texto(d, (36, 13), "Cinépolis Estação BH  ·  Resident Evil", 23, negrito=True)
        _texto(d, (58, 110), "Escolha o dia", 27, negrito=True)
        for i, (dia, data) in enumerate((("QUI", "01/10"), ("SEX", "02/10"), ("SÁB", "03/10"), ("DOM", "04/10"))):
            x = 420 + i * 113
            d.rounded_rectangle((x, 255, x + 86, 337), radius=12, fill="#30343b")
            _texto(d, (x + 19, 265), dia, 16)
            _texto(d, (x + 12, 292), data, 20, negrito=True)
        _texto(d, (60, 410), "Sessões disponíveis após escolher a data", 20)
        return img, "Clique no cartão SEX 02/10 para selecionar sexta-feira, 2 de outubro.", (533, 255, 619, 337)
    if caso == "arquivo":
        _texto(d, (36, 13), "Salvar arquivo", 23, negrito=True)
        _texto(d, (66, 132), "Nome:  notas.txt", 21)
        d.rounded_rectangle((46, 114, 1214, 175), radius=8, outline="#5e6269", width=2)
        _texto(d, (66, 225), "Pasta: Documentos / Emily", 21)
        d.rounded_rectangle((932, 708, 1039, 753), radius=8, fill="#41454b")
        d.rounded_rectangle((1054, 708, 1165, 753), radius=8, fill="#dc7850")
        _texto(d, (940, 718), "Cancelar", 18)
        _texto(d, (1074, 718), "Salvar", 18, negrito=True)
        return img, "Clique em Salvar para confirmar o arquivo notas.txt, sem clicar em Cancelar.", (1054, 708, 1165, 753)
    if caso == "lista":
        _texto(d, (36, 13), "Resultados da pesquisa", 23, negrito=True)
        for i, (nome, detalhe) in enumerate((("Resident Evil: Bem-vindo a Raccoon City", "Trailer oficial"), ("Resident Evil", "Filme completo · sessão de hoje"), ("Resident Evil 2", "Jogo · análise"))):
            y = 170 + i * 145
            d.rounded_rectangle((140, y, 1110, y + 120), radius=12, fill="#292c32")
            d.rounded_rectangle((160, y + 13, 305, y + 106), radius=8, fill="#4b3438")
            _texto(d, (337, y + 25), nome, 22, negrito=True)
            _texto(d, (337, y + 69), detalhe, 17, "#b7b8bb")
        return img, "Clique no resultado 'Resident Evil' que diz 'Filme completo · sessão de hoje', não no trailer nem no jogo.", (140, 315, 1110, 435)
    if caso == "controle":
        _texto(d, (36, 13), "Configurações de áudio", 23, negrito=True)
        _texto(d, (80, 225), "Saída de áudio", 23)
        _texto(d, (80, 362), "Ativar microfone", 23)
        _texto(d, (80, 492), "Redução de ruído", 23)
        for y in (229, 366, 496):
            d.rounded_rectangle((1042, y, 1094, y + 31), radius=16, fill="#494d54")
            d.ellipse((1047, y + 4, 1070, y + 27), fill="#e9e9e9")
        return img, "Clique no controle à direita de 'Ativar microfone', sem mexer nos outros controles.", (1042, 366, 1094, 397)
    if caso == "micro":
        _texto(d, (36, 13), "Permissões do navegador", 23, negrito=True)
        for i, nome in enumerate(("Câmera", "Microfone", "Notificações")):
            y = 276 + i * 58
            d.rounded_rectangle((80, y, 1170, y + 47), radius=8, fill="#282c33")
            _texto(d, (104, y + 12), nome, 18)
            for j in range(3):
                x = 1020 + j * 43
                d.rounded_rectangle((x, y + 10, x + 25, y + 35), radius=5, fill="#505760")
                if j == 0:  # lápis
                    d.line((x + 6, y + 29, x + 19, y + 16), fill="#f4f4f4", width=3)
                    d.polygon(((x + 4, y + 31), (x + 8, y + 30), (x + 5, y + 27)), fill="#f4f4f4")
                elif j == 1:  # excluir
                    d.line((x + 7, y + 17, x + 18, y + 28), fill="#f4f4f4", width=3)
                    d.line((x + 18, y + 17, x + 7, y + 28), fill="#f4f4f4", width=3)
                else:  # confirmar
                    d.line((x + 5, y + 23, x + 11, y + 29, x + 20, y + 17), fill="#f4f4f4", width=3)
        return img, "Clique no ícone de lápis da linha Microfone, não no X nem no check.", (1020, 344, 1045, 369)
    if caso == "datas_compactas":
        _texto(d, (36, 13), "Selecionar sessão", 23, negrito=True)
        _texto(d, (75, 165), "Resident Evil — Estação BH", 23, negrito=True)
        for i, (dia, data) in enumerate((("QUI", "01/10"), ("SEX", "02/10"), ("SÁB", "03/10"), ("DOM", "04/10"))):
            x = 680 + i * 77
            d.rounded_rectangle((x, 340, x + 63, 390), radius=5, fill="#3b4048")
            _texto(d, (x + 11, 344), dia, 13)
            _texto(d, (x + 5, 364), data, 14, negrito=True)
        return img, "Escolha a data SEX 02/10 no seletor compacto de sessões.", (757, 340, 820, 390)
    raise ValueError(caso)


def avaliar(decisao, alvo):
    if not isinstance(decisao, dict) or decisao.get("acao") not in {"clicar", "duplo_clique"}:
        return {"acertou": False, "erro_px": None, "ponto": None}
    col = str(decisao.get("celula", "")).upper()
    if len(col) < 2 or col[0] not in "ABCDEFGHIJ" or not col[1:].isdigit():
        return {"acertou": False, "erro_px": None, "ponto": None}
    try:
        x = (ord(col[0]) - ord("A") + float(decisao.get("offset_x")) / 100) * 128
        y = (int(col[1:]) + float(decisao.get("offset_y")) / 100) * 80
    except (ValueError, TypeError):
        return {"acertou": False, "erro_px": None, "ponto": None}
    x1, y1, x2, y2 = alvo
    return {"acertou": x1 <= x <= x2 and y1 <= y <= y2,
            "erro_px": round(math.hypot(x - (x1 + x2) / 2, y - (y1 + y2) / 2), 1),
            "ponto": [round(x, 1), round(y, 1)]}


def executar(caso, modelo_id, esforco):
    img, objetivo, alvo = tela(caso)
    captura = desktop_backend._imagem_para_grade_base64(img)
    chamar_original = llm.chamar
    rota = "agente_ui"
    temperatura_anterior = llm.rota(rota).temperatura
    llm.rota(rota).temperatura = None

    def chamar_benchmark(mensagens, **kwargs):
        kwargs.update(modelo=modelo_id, raciocinio=esforco,
                      max_tokens=8192, provedor="openai")
        return chamar_original(mensagens, **kwargs)

    llm.chamar = chamar_benchmark
    inicio = time.perf_counter()
    try:
        decisao = modelo.decidir_proxima_acao_ui(captura, objetivo, [], [], "")
        erro = None
    except Exception as exc:
        decisao, erro = None, f"{type(exc).__name__}: {exc}"
    finally:
        llm.chamar = chamar_original
        llm.rota(rota).temperatura = temperatura_anterior
    return {"caso": caso, "modelo": modelo_id, "esforco": esforco,
            "segundos": round(time.perf_counter() - inicio, 2),
            "decisao": decisao, "erro": erro, **avaliar(decisao, alvo)}


def executar_verificacao(modelo_id, esforco):
    """O anel está no X; mede se o modelo recoloca o ponto no lápis."""
    img, objetivo, alvo = tela("micro")
    imagens, mapa = desktop_backend._imagens_para_verificacao_base64(
        img, 1076, 357, {"left": 0, "top": 0, "width": 1280, "height": 800},
        retornar_mapa=True,
    )
    chamar_original = llm.chamar
    rota = llm.rota("agente_ui")
    temperatura_anterior = rota.temperatura
    rota.temperatura = None

    def chamar_benchmark(mensagens, **kwargs):
        kwargs.update(modelo=modelo_id, raciocinio=esforco,
                      max_tokens=8192, provedor="openai")
        return chamar_original(mensagens, **kwargs)

    llm.chamar = chamar_benchmark
    inicio = time.perf_counter()
    try:
        decisao = modelo.decidir_proxima_acao_ui(
            imagens, objetivo,
            ["VERIFICAÇÃO DE CLIQUE: marcador magenta proposto para o lápis da linha Microfone; ainda não cliquei."],
            [], "",
        )
        erro = None
    except Exception as exc:
        decisao, erro = None, f"{type(exc).__name__}: {exc}"
    finally:
        llm.chamar = chamar_original
        rota.temperatura = temperatura_anterior
    ponto = None
    if isinstance(decisao, dict) and decisao.get("acao") == "ajustar_clique_zoom":
        try:
            ponto = desktop_backend._coordenada_no_zoom(
                mapa, float(decisao["zoom_x"]), float(decisao["zoom_y"]))
        except (ValueError, TypeError, KeyError):
            pass
    elif isinstance(decisao, dict) and decisao.get("acao") == "clicar":
        ponto = avaliar(decisao, alvo)["ponto"]
    acertou = bool(ponto and alvo[0] <= ponto[0] <= alvo[2]
                   and alvo[1] <= ponto[1] <= alvo[3])
    return {"caso": "verificacao_micro", "modelo": modelo_id, "esforco": esforco,
            "segundos": round(time.perf_counter() - inicio, 2),
            "decisao": decisao, "erro": erro, "acertou": acertou, "ponto": ponto}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["calendario", "arquivo", "lista", "controle", "micro", "datas_compactas"])
    parser.add_argument("--verificacao", action="store_true", help="testar correção de um clique proposto no botão errado")
    parser.add_argument("--config", action="append", choices=["luna-alto", "luna-maximo", "sol-medio", "sol-alto"])
    parser.add_argument("--output", type=Path, help="JSONL salvo após cada chamada; permite retomar uma medição interrompida")
    op = parser.parse_args()
    configuracoes = {
        "luna-alto": ("cx/gpt-6-luna", "alto"),
        "luna-maximo": ("cx/gpt-6-luna", "maximo"),
        "sol-medio": ("cx/gpt-6-sol", "medio"),
        "sol-alto": ("cx/gpt-6-sol", "alto"),
    }
    casos = [op.case] if op.case else ["calendario", "arquivo", "lista", "controle", "micro", "datas_compactas"]
    configs = op.config or list(configuracoes)
    for caso in (["verificacao_micro"] if op.verificacao else casos):
        for config in configs:
            modelo_id, esforco = configuracoes[config]
            resultado = (executar_verificacao(modelo_id, esforco)
                         if op.verificacao else executar(caso, modelo_id, esforco))
            linha = json.dumps(resultado, ensure_ascii=False)
            if op.output:
                op.output.parent.mkdir(parents=True, exist_ok=True)
                with op.output.open("a", encoding="utf-8") as arquivo:
                    arquivo.write(linha + "\n")
                    arquivo.flush()
            print(linha, flush=True)
