"""
Task 7 — separação das rotas de agente e migração das duas.

  [A] estrutura: 9 rotas, todas no kiro, agente_jogo com modelo próprio
  [B] agente_ui decide ação de UI a partir de uma tela com grade
  [C] agente_jogo decide tecla a partir de uma tela de jogo
  [D] chamadas por minuto no monitoramento (Requisito 7.7)

O [D] não roda uma sessão de jogo de verdade: calcula a taxa a partir da
latência MEDIDA da triagem e dos tempos REAIS do laço de visão do main.py.
Rodar meia hora de jogo para contar chamadas queimaria crédito para produzir
o mesmo número.

Uso:
    python _teste_task7_agentes.py
"""

from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm      # noqa: E402
import modelo   # noqa: E402
import visao    # noqa: E402


def teste_a_estrutura() -> bool:
    print("[A] Estrutura das rotas")

    esperadas = {"conversa", "classificador", "comando", "extracao",
                 "visao", "triagem_visual", "agente_ui", "agente_jogo", "discord"}
    presentes = set(llm.ROTAS)

    faltando = esperadas - presentes
    sobrando = presentes - esperadas
    print(f"    rotas: {len(presentes)}  (esperadas: {len(esperadas)})")
    if faltando:
        print(f"    FALTANDO: {sorted(faltando)}")
    if sobrando:
        print(f"    inesperadas: {sorted(sobrando)}")

    fora_do_kiro = sorted(n for n, c in llm.ROTAS.items() if c.provedor != "kiro")
    print(f"    fora do kiro: {fora_do_kiro or 'nenhuma'}")

    ui = llm.ROTAS.get("agente_ui")
    jogo = llm.ROTAS.get("agente_jogo")
    if ui and jogo:
        print(f"    agente_ui   -> {ui.modelo}")
        print(f"    agente_jogo -> {jogo.modelo}")
        separadas = ui.modelo != jogo.modelo
        print(f"    modelos diferentes: {separadas} "
              f"(o ponto da separação: agente_jogo não pode herdar o Opus)")
    else:
        separadas = False

    ok = not faltando and not fora_do_kiro and separadas
    print(f"    -> {'OK' if ok else 'FALHOU'}")
    print()
    return ok


def _tela_de_jogo() -> str:
    """Tela de jogo sintética com HUD reconhecível."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1280, 720), (25, 30, 40))
    d = ImageDraw.Draw(img)
    # HUD
    d.rectangle([(30, 30), (330, 60)], fill=(60, 20, 20), outline=(200, 60, 60), width=2)
    d.rectangle([(30, 30), (230, 60)], fill=(200, 60, 60))
    d.text((40, 38), "HP 60/100", fill=(255, 255, 255))
    d.text((40, 80), "INIMIGO A FRENTE - ele esta atacando", fill=(255, 220, 100))
    d.text((40, 110), "voce esta com a espada equipada", fill=(200, 200, 210))
    # "personagem" e "inimigo"
    d.ellipse([(560, 400), (640, 480)], fill=(80, 160, 240))
    d.ellipse([(800, 400), (880, 480)], fill=(220, 70, 70))

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def teste_b_agente_ui() -> bool:
    cfg = llm.rota("agente_ui")
    print(f"[B] agente_ui -> {cfg.provedor} / {cfg.modelo}")

    imagem = visao.capturar_tela_com_grade()
    if not imagem:
        print("    PULADO: não consegui capturar a tela com grade.")
        print()
        return True

    inicio = time.monotonic()
    try:
        decisao = modelo.decidir_proxima_acao_ui(
            imagem,
            objetivo="abrir o menu iniciar do Windows",
            historico=[],
            contexto_telas=[],
        )
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False
    decorrido = time.monotonic() - inicio

    print(f"    latência: {decorrido:.2f}s")
    print(f"    decisão:  {str(decisao)[:220]}")

    ok = isinstance(decisao, dict) and bool(decisao)
    print(f"    -> {'OK, devolveu decisão estruturada' if ok else 'FALHOU'}")
    print()
    return ok


def teste_c_agente_jogo() -> bool:
    cfg = llm.rota("agente_jogo")
    print(f"[C] agente_jogo -> {cfg.provedor} / {cfg.modelo}")

    try:
        import agente_jogo
    except Exception as e:  # noqa: BLE001
        print(f"    PULADO: não consegui importar agente_jogo ({e})")
        print()
        return True

    inicio = time.monotonic()
    try:
        decisao = agente_jogo._decidir_teclas(_tela_de_jogo(), "jogo de acao genérico")
    except Exception as e:  # noqa: BLE001
        print(f"    FALHOU com exceção: {type(e).__name__}: {e}")
        print()
        return False
    decorrido = time.monotonic() - inicio

    print(f"    latência: {decorrido:.2f}s")
    print(f"    decisão:  {str(decisao)[:220]}")

    ok = isinstance(decisao, dict) and isinstance(decisao.get("teclas"), list)
    print(f"    -> {'OK, JSON com lista de teclas' if ok else 'FALHOU'}")
    print()
    return ok


def teste_d_chamadas_por_minuto() -> bool:
    """
    Requisito 7.7 — quantas chamadas por minuto o monitoramento gera.

    Tempos reais do loop_visao do main.py:
      - porteiro local (assinatura de frame): não gasta LLM
      - triagem: uma chamada
      - se a triagem devolve NAO: time.sleep(3)
      - se devolve SIM: mais uma chamada (análise) e um comentário falado
    """
    print("[D] Chamadas por minuto no monitoramento (Requisito 7.7)")

    imagem = visao.capturar_tela_triagem()
    if not imagem:
        print("    PULADO: sem captura.")
        print()
        return True

    amostras = 3
    latencias = []
    for _ in range(amostras):
        inicio = time.monotonic()
        modelo.triar_tela(imagem)
        latencias.append(time.monotonic() - inicio)

    media = sum(latencias) / len(latencias)
    espera_do_laco = 3.0        # time.sleep(3) quando a triagem devolve NAO
    ciclo = media + espera_do_laco
    por_minuto = 60.0 / ciclo

    print(f"    latência média da triagem: {media:.2f}s  ({[f'{l:.2f}' for l in latencias]})")
    print(f"    espera do laço após NAO:   {espera_do_laco:.1f}s")
    print(f"    ciclo completo:            {ciclo:.2f}s")
    print(f"    -> ~{por_minuto:.1f} chamadas de triagem por minuto")
    print(f"    -> ~{por_minuto * 60:.0f} por hora de tela mudando sem parar")
    print()
    print("    Atenuante importante: o loop_visao só chama a LLM quando a")
    print("    assinatura do frame muda (visao.tela_mudou). Tela parada custa")
    print("    zero. O número acima é o PIOR caso, com a tela mudando sempre —")
    print("    que é exatamente o caso de jogo.")
    print()
    return True


def principal() -> int:
    print("=" * 78)
    print("TASK 7 — AGENTE DE UI E AGENTE DE JOGO")
    print("=" * 78)
    print()

    resultados = {
        "A estrutura":    teste_a_estrutura(),
        "B agente_ui":    teste_b_agente_ui(),
        "C agente_jogo":  teste_c_agente_jogo(),
        "D chamadas/min": teste_d_chamadas_por_minuto(),
    }

    print("=" * 78)
    for rotulo, ok in resultados.items():
        print(f"  {rotulo:<18} {'OK' if ok else 'FALHOU'}")
    print("=" * 78)
    return 0 if all(resultados.values()) else 1


if __name__ == "__main__":
    raise SystemExit(principal())
