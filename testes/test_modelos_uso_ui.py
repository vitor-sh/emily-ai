"""Integração visual do indicador de contexto e das cotas nas configurações."""
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
            page.wait_for_selector('.cfg-nav-item[data-cfg-abrir="modelos"]')
            page.locator('.cfg-nav-item[data-cfg-abrir="modelos"]').click()
            page.wait_for_selector('#cfg-modelos-uso', timeout=15000)
            page.evaluate("""() => {
              window.EmilyUsage.setContext({percent: 60});
              // Amostra de cotas via mesma rotina de renderização usada pela ponte.
              window.EmilyUsage.setUsage({accounts:[{label:'Conta',windows:[
                {label:'5 horas',used_percent:9,resets_at:'2026-10-08T06:30:08'},
                {label:'Semanal',used_percent:1,resets_at:'2026-10-15T01:30:08'}
              ]}],updated_at:1791434916});
            }""")
            panel = page.locator('#cfg-modelos-uso')
            assert panel.is_visible()
            assert '5 horas' in panel.inner_text() and 'Semanal' in panel.inner_text()
            assert len(panel.locator('[role=progressbar]').all()) == 2
            assert panel.locator('[role=progressbar]').nth(0).get_attribute('aria-valuenow') == '9'
            assert panel.locator('[role=progressbar]').nth(1).get_attribute('aria-valuenow') == '1'
            assert 'Codex' not in page.locator('#painel-uso-contexto').inner_text()
            page.screenshot(path='/tmp/emily-modelos-uso-test.png')
        finally:
            browser.close()
