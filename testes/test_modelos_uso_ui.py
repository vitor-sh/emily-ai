"""Integração visual do indicador de contexto (as cotas do Codex saíram das configurações)."""
import os
import pytest
from playwright.sync_api import sync_playwright

URL = os.environ.get('EMILY_PREVIEW_URL')  # prévia isolada; passar URL de uma sessão ativa


@pytest.mark.skipif(not URL, reason='Defina EMILY_PREVIEW_URL para executar o teste visual na prévia')
def test_contexto_e_cotas_em_telas_separadas():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 850}, service_workers='block')
            page.goto(URL, wait_until='networkidle')
            page.wait_for_function("window.pywebview && window.pywebview.api && !document.body.classList.contains('carregando') && document.querySelector('#btn-uso-contexto')")
            assert page.locator('#btn-uso-contexto').get_attribute('aria-label') == 'Uso do contexto: aguardando medição'
            page.evaluate("""() => {
              window.EmilyUsage.setContext({percent: 37.5,used:10000,effective_limit:258400});
            }""")
            button = page.locator('#btn-uso-contexto')
            assert button.get_attribute('aria-label') == 'Uso do contexto: aproximadamente 37.5%'
            assert button.evaluate("el => getComputedStyle(el).getPropertyValue('--contexto-progresso').trim()") == '37.5'
            assert button.locator('svg circle').count() == 2
            button.click()
            assert page.locator('#painel-uso-contexto').is_visible()
            assert '37.5%' in page.locator('#painel-uso-contexto').inner_text()
            assert 'tokens' not in page.locator('#painel-uso-contexto').inner_text()
            assert 'Codex' not in page.locator('#painel-uso-contexto').inner_text()
            page.keyboard.press('Escape')
            assert not page.locator('#painel-uso-contexto').is_visible()
            page.evaluate("irPara('config')")
            page.wait_for_selector('.cfg-nav-item[data-cfg-abrir="voz"]')
            # O uso da assinatura Codex saiu das configurações (10/10/2026).
            assert page.locator('.cfg-nav-item[data-cfg-abrir="modelos"]').count() == 0
            assert page.locator('#cfg-modelos-uso').count() == 0
            assert 'Codex' not in page.locator('#painel-uso-contexto').inner_text()
            page.screenshot(path='/tmp/emily-modelos-uso-test.png')
        finally:
            browser.close()
