import mss
import time
import base64
from io import BytesIO
from PIL import Image

monitor_atual = 1  # Começa no monitor 1 por padrão

def capturar_tela():
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_atual]
        screenshot = sct.grab(monitor)
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        img = img.resize((1280, 720))
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")

def trocar_monitor():
    global monitor_atual
    with mss.mss() as sct:
        total = len(sct.monitors) - 1
    monitor_atual = (monitor_atual % total) + 1
    return monitor_atual

def capturar_sequencia_telas(quantidade=5, intervalo=1.0):
    """Tira várias prints em sequência rápida e retorna uma lista de imagens base64."""
    imagens = []
    for _ in range(quantidade):
        imagens.append(capturar_tela())
        time.sleep(intervalo)
    return imagens

def capturar_sequencia_telas_rapida(quantidade=3, intervalo=0.6):
    imagens = []
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_atual]
        for _ in range(quantidade):
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = img.resize((1280, 720))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            imagens.append(base64.b64encode(buffer.read()).decode("utf-8"))
            time.sleep(intervalo)
    return imagens