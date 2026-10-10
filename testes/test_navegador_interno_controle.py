"""Cliques em texto composto e separação do controle humano/Emily."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_texto_de_data_em_spans_separados_e_mouse_teclado_virtuais():
    import navegador_interno
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium Playwright indisponível: {exc}")
        try:
            pagina = browser.new_page(viewport={"width": 800, "height": 600})
            pagina.set_content("""
              <button hidden><span>SEX</span><span>02/10</span></button>
              <div class="cursor-pointer" onclick="this.dataset.selecionado='sim'">
                <span>SEX</span><span>02/10</span>
              </div>
              <input id="busca" aria-label="Busca">
            """)
            alvo = navegador_interno._localizar_texto_visivel(pagina, "SEX\n02/10")
            alvo.click()
            assert pagina.locator(".cursor-pointer").get_attribute("data-selecionado") == "sim"
            pagina.mouse.click(30, 50)
            pagina.locator("#busca").click()
            pagina.keyboard.insert_text("Resident Evil")
            assert pagina.locator("#busca").input_value() == "Resident Evil"
        finally:
            browser.close()


def test_comandos_da_emily_esperam_usuario_sair_sem_bloquear_comandos_humanos(monkeypatch):
    import navegador_interno

    class ThreadViva:
        def is_alive(self):
            return True

    fila = Queue()
    monkeypatch.setattr(navegador_interno, "_thread", ThreadViva())
    monkeypatch.setattr(navegador_interno, "_fila", fila)
    monkeypatch.setattr(navegador_interno, "_encerrando", False)
    monkeypatch.setattr(navegador_interno, "_revisao_usuario", 0)
    navegador_interno.definir_usuario_ativo(True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            agente = pool.submit(navegador_interno.comando, "clicar", 12, 18, "left", timeout=2)
            usuario = pool.submit(navegador_interno.comando, "estado", origem="usuario", timeout=2)
            operacao, _, futuro, origem = fila.get(timeout=1)
            assert (operacao, origem) == ("estado", "usuario")
            futuro.set_result({"ok": True, "origem": origem})
            assert usuario.result(timeout=1)["origem"] == "usuario"
            assert fila.empty()
            navegador_interno.definir_usuario_ativo(False)
            operacao, _, futuro, origem = fila.get(timeout=1)
            assert (operacao, origem) == ("clicar", "agente")
            futuro.set_result({"ok": True, "origem": origem})
            assert agente.result(timeout=1)["origem"] == "agente"
    finally:
        navegador_interno.definir_usuario_ativo(False)


def test_acao_planejada_antes_de_edicao_humana_e_descartada(monkeypatch):
    import navegador_interno

    class ThreadViva:
        def is_alive(self):
            return True

    fila = Queue()
    monkeypatch.setattr(navegador_interno, "_thread", ThreadViva())
    monkeypatch.setattr(navegador_interno, "_fila", fila)
    monkeypatch.setattr(navegador_interno, "_encerrando", False)
    monkeypatch.setattr(navegador_interno, "_revisao_usuario", 0)
    aguardando = Event()
    espera_original = navegador_interno._condicao.wait

    def registrar_espera(*args, **kwargs):
        aguardando.set()
        return espera_original(*args, **kwargs)

    monkeypatch.setattr(navegador_interno._condicao, "wait", registrar_espera)
    navegador_interno.definir_usuario_ativo(True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            agente = pool.submit(navegador_interno.comando, "clicar", 12, 18, "left", timeout=2)
            assert aguardando.wait(timeout=1)
            usuario = pool.submit(navegador_interno.comando, "mover", 30, 40,
                                  origem="usuario", timeout=2)
            operacao, _, futuro, origem = fila.get(timeout=1)
            assert (operacao, origem) == ("mover", "usuario")
            futuro.set_result({"ok": True})
            assert usuario.result(timeout=1)["ok"]
            navegador_interno.definir_usuario_ativo(False)
            resultado = agente.result(timeout=1)
            assert not resultado["ok"]
            assert "olhar o estado atual" in resultado["erro"]
            assert fila.empty()
    finally:
        navegador_interno.definir_usuario_ativo(False)
