"""Teste visual do ícone OpenAI usado no seletor de modelos do chat."""
from pathlib import Path
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / 'web/editor-assets/openai-preto.svg'
CSS = ROOT / 'web/estilo.css'
APP = ROOT / 'web/app.js'


def test_openai_icon_rendered_in_chat_controls(tmp_path):
    root = ET.parse(SVG).getroot()
    assert root.attrib['viewBox'] == '100 100 411 411'
    assert root.find('{http://www.w3.org/2000/svg}path').attrib['fill'] == '#ede9e2'
    assert APP.read_text().count('openai-preto.svg?v=20261008-icone') == 3
    page_html = tmp_path / 'preview.html'
    svg_uri = SVG.as_uri()
    page_html.write_text(f'''<!doctype html><html><head><link rel="stylesheet" href="{CSS.as_uri()}">
    <style>body {{background:#171717;color:#ede9e2}} .popover-item {{background:#272727}} .cfg-visual-selector {{background:#272727;display:flex;align-items:center}} .cfg-visual-selector img {{width:20px;height:20px}}</style></head>
    <body><button class="pilula" id="sel-modelo"><img class="sel-modelo-marca marca-openai-preta" src="{svg_uri}">GPT</button>
    <div class="popover-modelos-chat"><button class="popover-item"><img class="pi-ico pi-marca pi-marca-openai" src="{svg_uri}">OpenAI</button></div>
    <div class="cfg-visual-selector"><img class="sel-marca marca-openai-preta" src="{svg_uri}">OpenAI nas configurações</div>
    </body></html>''', encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 420, 'height': 280}, device_scale_factor=2)
        page.goto(page_html.as_uri())
        for selector in ('#sel-modelo img', '.popover-modelos-chat img', '.cfg-visual-selector img'):
            img = page.locator(selector)
            result = img.evaluate('el => ({loaded: el.complete && el.naturalWidth > 0, width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height, bg: getComputedStyle(el).backgroundColor, pad: getComputedStyle(el).paddingLeft})')
            assert result['loaded'] and result['width'] >= 16 and result['height'] >= 16, (selector, result)
            assert result['bg'] == 'rgba(0, 0, 0, 0)' and result['pad'] == '0px', (selector, result)
            # Pixel do centro do símbolo: desenho claro, não um cartão opaco.
            pixels = img.screenshot()
            from io import BytesIO
            from PIL import Image
            image = Image.open(BytesIO(pixels)).convert('RGB')
            light = sum(1 for r, g, b in image.getdata() if r > 180 and g > 180 and b > 180)
            assert light > image.width * image.height * .10, (selector, light)
        page.screenshot(path=str(tmp_path / 'openai-icon-preview.png'))
        browser.close()
