"""
Task 6 — validação funcional das rotas de visão migradas.

O benchmark (_bench_visao.py) mediu latência e leitura. Aqui o alvo é
diferente: as funções do modelo.py se comportam como a Emily espera?

  [A] triar_tela com captura de EVENTO      -> SIM
  [B] triar_tela com captura ROTINEIRA      -> NAO
  [C] triar_tela_jogo com tela de morte     -> SIM
  [D] triar_tela_jogo com gameplay normal   -> NAO
  [E] analisar_tela_com_pergunta            -> responde a pergunta sobre a tela
  [F] a imagem chega intacta ao provedor    -> Property 11 do design

As capturas de A a D são GERADAS, não são a tela real: precisam ter
resposta conhecida para o teste ter gabarito. Tela real serve para medir
latência, não para verificar acerto.

Uso:
    python _teste_task6_visao.py
"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm      # noqa: E402
import modelo   # noqa: E402


def _tela(texto_principal: str, subtexto: str = "", fundo=(15, 15, 20),
          cor=(240, 240, 240)) -> str:
    """Gera uma captura sintética 640x360 com texto grande e legível."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 360), fundo)
    d = ImageDraw.Draw(img)
    # Fonte default é pequena; desenho o texto várias vezes deslocado para
    # engrossar, o que melhora muito a leitura por modelo de visão.
    for dx in range(2):
        for dy in range(2):
            d.text((60 + dx, 150 + dy), texto_principal, fill=cor)
    if subtexto:
        d.text((60, 200), subtexto, fill=(160, 160, 170))

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80)
    return base64.b64encode(buffer.getvalue()).decode()


# Cenários com gabarito conhecido.
TELA_EVENTO = _tela("ERRO FATAL: aplicacao travou", "Traceback (most recent call last):",
                    fundo=(30, 10, 10))
TELA_ROTINA = _tela("bloco de notas - documento sem titulo", "escrevendo texto normal aqui")
TELA_MORTE = _tela("VOCE MORREU", "pressione qualquer tecla para continuar",
                   fundo=(20, 0, 0), cor=(200, 40, 40))
TELA_GAMEPLAY = _tela("HP 100/100   MP 50/50", "andando pelo mapa, nada acontecendo")


def _cabecalho(rotulo: str, rota: str) -> None:
    cfg = llm.rota(rota)
    print(f"[{rotulo}] rota '{rota}' -> {cfg.provedor} / {cfg.modelo} "
          f"(raciocinio={cfg.raciocinio})")


def teste_triagem(rotulo: str, funcao, imagem: str, esperado: bool, descricao: str) -> bool:
    _cabecalho(rotulo, "triagem_visual")
    print(f"    cenário: {descricao}")
    obtido = funcao(imagem)
    print(f"    resultado: {obtido}  (esperado {esperado})")
    ok = obtido == esperado
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def teste_e_pergunta_sobre_tela() -> bool:
    _cabecalho("E", "visao")
    imagem = _tela("SALDO: R$ 1.234,56", "conta corrente")
    print("    cenário: tela com um valor conhecido, pergunta direta")
    resposta = modelo.analisar_tela_com_pergunta(imagem, "Que valor aparece na tela?")
    texto = (resposta or "").strip()
    print(f"    resposta: {texto[:180]!r}")

    ok = bool(texto) and ("1.234" in texto or "1234" in texto)
    print(f"    -> {'OK, leu o valor' if ok else 'FALHOU: não leu o valor'}")
    print()
    return ok


def teste_f_imagem_intacta() -> bool:
    """
    Property 11 do design: a imagem base64 chega intacta ao endpoint,
    preservando media type e bytes.

    Não faz chamada de rede: inspeciona o corpo que o provedor monta.
    """
    print("[F] Property 11 — imagem intacta no corpo montado")

    b64 = TELA_MORTE
    canonicas = llm.normalizar_mensagens(
        [{"role": "user", "content": "descreva", "images": [b64]}]
    )
    provedor = llm.PROVEDORES["kiro"]
    corpo = provedor._montar_mensagens(canonicas)

    partes = corpo[0]["content"]
    imagens = [p for p in partes if p.get("type") == "image_url"]
    print(f"    partes no conteúdo: {len(partes)}  (imagens: {len(imagens)})")

    if not imagens:
        print("    -> FALHOU: nenhuma parte de imagem no corpo")
        print()
        return False

    url = imagens[0]["image_url"]["url"]
    prefixo_ok = url.startswith("data:image/jpeg;base64,")
    bytes_ok = url.split(",", 1)[1] == b64
    print(f"    media type preservado: {prefixo_ok}")
    print(f"    bytes idênticos:       {bytes_ok} ({len(b64):,} chars)")

    ok = prefixo_ok and bytes_ok
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def principal() -> int:
    print("=" * 78)
    print("TASK 6 — ROTAS DE VISÃO MIGRADAS, VALIDAÇÃO FUNCIONAL")
    print("=" * 78)
    print()

    resultados = {
        "A triagem evento":   teste_triagem("A", modelo.triar_tela, TELA_EVENTO, True,
                                            "erro fatal com traceback na tela"),
        "B triagem rotina":   teste_triagem("B", modelo.triar_tela, TELA_ROTINA, False,
                                            "bloco de notas, nada acontecendo"),
        "C jogo morte":       teste_triagem("C", modelo.triar_tela_jogo, TELA_MORTE, True,
                                            "tela de VOCE MORREU"),
        "D jogo normal":      teste_triagem("D", modelo.triar_tela_jogo, TELA_GAMEPLAY, False,
                                            "HP cheio, andando pelo mapa"),
        "E pergunta tela":    teste_e_pergunta_sobre_tela(),
        "F imagem intacta":   teste_f_imagem_intacta(),
    }

    print("=" * 78)
    for rotulo, ok in resultados.items():
        print(f"  {rotulo:<20} {'OK' if ok else 'FALHOU'}")
    print("=" * 78)
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
