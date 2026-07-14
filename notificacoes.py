"""
notificacoes.py — Monitora o WhatsApp Web lendo o DOM direto pelo Selenium.

Conecta no Brave já aberto (remote debugging port 9222) e fica verificando
a lista de conversas a cada 3 segundos. Quando achar mensagem não lida,
chama o callback pra Emily avisar o Vitor por voz.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

_PORTA_DEBUG = 9222
_INTERVALO   = 3.0
_COOLDOWN_CONTATO = 60   # segundos entre avisos do mesmo contato

_callback_notificacao: Optional[Callable[[str, str, str], None]] = None
_ultimo_por_contato:   dict[str, float] = {}
_monitor_ativo  = False
_thread_monitor: Optional[threading.Thread] = None
_driver         = None


# ─────────────────────────────────────────────────────────────────
# PÚBLICO
# ─────────────────────────────────────────────────────────────────

def definir_callback(callback: Callable[[str, str, str], None]) -> None:
    """Registra a função chamada quando chega mensagem nova.
    Recebe: (app_nome, contato, mensagem)
    """
    global _callback_notificacao
    _callback_notificacao = callback


def iniciar_monitor() -> str:
    global _monitor_ativo, _thread_monitor
    if _monitor_ativo and _thread_monitor and _thread_monitor.is_alive():
        return "Já tô monitorando o WhatsApp, Vitor!"
    _monitor_ativo = True
    _thread_monitor = threading.Thread(target=_loop_monitor, daemon=True)
    _thread_monitor.start()
    return "Iniciando monitor do WhatsApp Web! Vou te avisar quando chegar mensagem."


def parar_monitor() -> str:
    global _monitor_ativo
    if not _monitor_ativo:
        return "Não tô monitorando o WhatsApp agora, Vitor!"
    _monitor_ativo = False
    return "Parei de monitorar o WhatsApp!"


def esta_ativo() -> bool:
    return _monitor_ativo and bool(_thread_monitor and _thread_monitor.is_alive())


# ─────────────────────────────────────────────────────────────────
# CONEXÃO COM O BRAVE
# ─────────────────────────────────────────────────────────────────

def _conectar_brave():
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        options = Options()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{_PORTA_DEBUG}")
        service = Service(ChromeDriverManager().install())
        driver  = webdriver.Chrome(service=service, options=options)
        print(f"[NOTIF] Conectado ao Brave!")
        return driver
    except Exception as e:
        print(f"[NOTIF] Não consegui conectar ao Brave: {e}")
        return None


def _ir_para_whatsapp(driver) -> bool:
    """Troca pra aba do WhatsApp Web, abre uma se não existir."""
    try:
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "web.whatsapp.com" in driver.current_url:
                return True
        # Não achou — abre numa aba nova
        driver.execute_script("window.open('https://web.whatsapp.com', '_blank');")
        time.sleep(4)
        for handle in driver.window_handles:
            driver.switch_to.window(handle)
            if "web.whatsapp.com" in driver.current_url:
                return True
        return False
    except Exception as e:
        print(f"[NOTIF] Erro ao navegar pro WhatsApp: {e}")
        return False


# ─────────────────────────────────────────────────────────────────
# LEITURA DO DOM — seletores confirmados pelo diagnóstico
# ─────────────────────────────────────────────────────────────────

# JavaScript que roda dentro do Brave e retorna as conversas não lidas.
# Usa data-testid que são estáveis entre atualizações do WhatsApp.
_JS_LER_NAO_LIDAS = """
const resultados = [];

// Cada conversa na lista tem data-testid="list-item-N"
const itens = document.querySelectorAll('[data-testid^="list-item-"]');

for (const item of itens) {
    try {
        // Badge de não lidas confirmado pelo diagnóstico:
        // aria-label="N mensagens não lidas"
        const badge = item.querySelector('[aria-label*="mensagens não lidas"], [aria-label*="mensagem não lida"], [aria-label*="unread message"]');
        if (!badge) continue;

        // Quantidade de mensagens não lidas
        const qtd = parseInt(badge.textContent.trim()) || 1;

        // Nome do contato — data-testid="cell-frame-title" confirmado no diagnóstico
        let contato = "";
        const tituloEl = item.querySelector('[data-testid="cell-frame-title"] span');
        if (tituloEl) {
            contato = tituloEl.getAttribute("title") || tituloEl.textContent.trim();
        }

        // Última mensagem — fica em cell-frame-secondary
        let mensagem = "";
        const secundario = item.querySelector('[data-testid="cell-frame-secondary"]');
        if (secundario) {
            // Remove spans de status (hora, ícone de entregue, etc.)
            // e pega só o texto principal
            const spans = secundario.querySelectorAll('span');
            for (const sp of spans) {
                const txt = sp.textContent.trim();
                // Ignora horas (ex: "14:32"), ícones vazios e textos muito curtos
                if (txt.length > 2 && !txt.match(/^\\d{1,2}:\\d{2}$/) && sp.children.length === 0) {
                    mensagem = txt;
                    break;
                }
            }
            // Fallback: pega todo o texto do secundário
            if (!mensagem) {
                mensagem = secundario.textContent.trim();
            }
        }

        if (contato) {
            resultados.push({ contato, mensagem, qtd });
        }
    } catch(e) {
        // ignora erros em itens individuais
    }
}

return resultados;
"""


def _ler_nao_lidas(driver) -> list[dict]:
    try:
        return driver.execute_script(_JS_LER_NAO_LIDAS) or []
    except Exception as e:
        print(f"[NOTIF] Erro ao ler DOM: {e}")
        return []


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def _em_cooldown(contato: str) -> bool:
    return (time.time() - _ultimo_por_contato.get(contato, 0)) < _COOLDOWN_CONTATO


def _registrar(contato: str) -> None:
    _ultimo_por_contato[contato] = time.time()


# ─────────────────────────────────────────────────────────────────
# LOOP PRINCIPAL
# ─────────────────────────────────────────────────────────────────

def _loop_monitor() -> None:
    global _driver, _monitor_ativo

    print("[NOTIF] Iniciando monitor do WhatsApp Web...")

    _driver = _conectar_brave()
    if not _driver:
        print("[NOTIF] Monitor encerrado: não consegui conectar ao Brave.")
        _monitor_ativo = False
        return

    if not _ir_para_whatsapp(_driver):
        print("[NOTIF] Monitor encerrado: não consegui abrir o WhatsApp Web.")
        _monitor_ativo = False
        return

    print("[NOTIF] Aguardando WhatsApp Web carregar...")
    time.sleep(5)
    print("[NOTIF] Monitor ativo! Verificando mensagens a cada 3s...")

    while _monitor_ativo:
        try:
            # Garante que ainda está na aba certa
            if "web.whatsapp.com" not in _driver.current_url:
                _ir_para_whatsapp(_driver)
                time.sleep(2)

            conversas = _ler_nao_lidas(_driver)

            for conversa in conversas:
                contato  = (conversa.get("contato") or "").strip()
                mensagem = (conversa.get("mensagem") or "").strip()
                qtd      = conversa.get("qtd", 1)

                if not contato:
                    continue

                if _em_cooldown(contato):
                    continue

                _registrar(contato)

                if len(mensagem) > 100:
                    mensagem = mensagem[:100] + "..."

                print(f"[NOTIF] ✓ {contato} ({qtd} msg): {mensagem[:60]}")

                if _callback_notificacao:
                    try:
                        _callback_notificacao("WhatsApp", contato, mensagem)
                    except Exception as e:
                        print(f"[NOTIF] Erro no callback: {e}")

        except Exception as e:
            err = str(e).lower()
            print(f"[NOTIF] Erro no loop: {e}")
            if "invalid session" in err or "no such window" in err:
                print("[NOTIF] Reconectando ao Brave...")
                time.sleep(3)
                _driver = _conectar_brave()
                if _driver:
                    _ir_para_whatsapp(_driver)

        time.sleep(_INTERVALO)

    print("[NOTIF] Monitor encerrado.")