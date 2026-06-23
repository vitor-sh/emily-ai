"""
diagnostico_whatsapp.py — Roda uma vez só pra descobrir os seletores certos.

Execute com: python diagnostico_whatsapp.py
Deixa o WhatsApp Web aberto no Brave com pelo menos UMA mensagem não lida.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import json

print("Conectando ao Brave...")
options = Options()
options.add_experimental_option("debuggerAddress", "127.0.0.1:9222")
service = Service(ChromeDriverManager().install())
driver = webdriver.Chrome(service=service, options=options)

# Vai pra aba do WhatsApp
for handle in driver.window_handles:
    driver.switch_to.window(handle)
    if "web.whatsapp.com" in driver.current_url:
        print(f"Aba do WhatsApp encontrada!")
        break

print(f"URL atual: {driver.current_url}\n")

# ── Teste 1: conta quantos role=listitem existem ──
resultado1 = driver.execute_script("""
    const itens = document.querySelectorAll('[role="listitem"]');
    return itens.length;
""")
print(f"[TESTE 1] role=listitem encontrados: {resultado1}")

# ── Teste 2: procura badges de não lidas por aria-label ──
resultado2 = driver.execute_script("""
    const todos = document.querySelectorAll('*');
    const badges = [];
    for (const el of todos) {
        const label = el.getAttribute('aria-label') || '';
        if (label.toLowerCase().includes('não lida') || 
            label.toLowerCase().includes('unread')) {
            badges.push({
                tag: el.tagName,
                label: label,
                texto: el.textContent.trim().substring(0, 50),
                classe: el.className.substring(0, 80)
            });
        }
    }
    return badges.slice(0, 10);
""")
print(f"\n[TESTE 2] Elementos com 'não lida/unread' no aria-label:")
for b in (resultado2 or []):
    print(f"  tag={b['tag']} | label='{b['label']}' | texto='{b['texto']}'")
    print(f"  classe: {b['classe']}")

# ── Teste 3: procura pelo painel lateral de conversas ──
resultado3 = driver.execute_script("""
    // Tenta achar o painel lateral de várias formas
    const tentativas = [
        document.querySelector('#pane-side'),
        document.querySelector('[data-testid="chat-list"]'),
        document.querySelector('[aria-label="Lista de chats"]'),
        document.querySelector('[aria-label="Chat list"]'),
        document.querySelector('[aria-label="Conversation list"]'),
    ];
    return tentativas.map((el, i) => ({
        indice: i,
        encontrado: !!el,
        tag: el ? el.tagName : null,
        filhos: el ? el.children.length : 0
    }));
""")
print(f"\n[TESTE 3] Painel lateral:")
for t in (resultado3 or []):
    print(f"  [{t['indice']}] encontrado={t['encontrado']} filhos={t['filhos']}")

# ── Teste 4: pega o HTML do painel lateral pra ver a estrutura ──
resultado4 = driver.execute_script("""
    const painel = document.querySelector('#pane-side') 
                || document.querySelector('[data-testid="chat-list"]');
    if (!painel) return "PAINEL NÃO ENCONTRADO";
    
    // Pega só o primeiro item da lista pra inspecionar
    const primeiro = painel.querySelector('[role="listitem"]') 
                  || painel.firstElementChild?.firstElementChild;
    if (!primeiro) return "NENHUM ITEM ENCONTRADO NO PAINEL";
    
    return primeiro.innerHTML.substring(0, 2000);
""")
print(f"\n[TESTE 4] HTML do primeiro item da lista (primeiros 2000 chars):")
print(resultado4)

# ── Teste 5: tenta achar qualquer elemento com número de não lidas ──
resultado5 = driver.execute_script("""
    // Procura spans/divs que contenham só um número pequeno (badge)
    const candidatos = [];
    const todos = document.querySelectorAll('span, div');
    for (const el of todos) {
        const txt = el.textContent.trim();
        // Badge de notificação: só número, entre 1 e 999
        if (/^\\d{1,3}$/.test(txt) && el.children.length === 0) {
            const rect = el.getBoundingClientRect();
            // Só elementos visíveis na tela
            if (rect.width > 0 && rect.width < 40 && rect.height > 0) {
                candidatos.push({
                    tag: el.tagName,
                    texto: txt,
                    classe: el.className.substring(0, 100),
                    dataTestId: el.getAttribute('data-testid') || '',
                    ariaLabel: el.getAttribute('aria-label') || ''
                });
            }
        }
    }
    return candidatos.slice(0, 15);
""")
print(f"\n[TESTE 5] Possíveis badges de notificação (números pequenos visíveis):")
for c in (resultado5 or []):
    print(f"  texto='{c['texto']}' | testid='{c['dataTestId']}' | label='{c['ariaLabel']}'")
    print(f"  classe: {c['classe'][:80]}")

# ── Teste 6: todos os data-testid do painel lateral ──
resultado6 = driver.execute_script("""
    const painel = document.querySelector('#pane-side')
                || document.querySelector('[data-testid="chat-list"]');
    if (!painel) return [];
    
    const testids = new Set();
    painel.querySelectorAll('[data-testid]').forEach(el => {
        testids.add(el.getAttribute('data-testid'));
    });
    return [...testids].slice(0, 30);
""")
print(f"\n[TESTE 6] data-testid encontrados no painel lateral:")
for tid in (resultado6 or []):
    print(f"  {tid}")

print("\n=== DIAGNÓSTICO CONCLUÍDO ===")
print("Copia todo esse output e manda pro Claude!")