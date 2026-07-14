import mss
import time
import base64
import ctypes
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

monitor_atual = 1  # Começa no monitor 1 por padrão

# Dimensões da imagem enviada para o modelo
GRADE_W = 1280
GRADE_H = 720
# Divisões da grade sobre a imagem (10x10 = células de 128x72)
GRADE_COLS = 10
GRADE_LINHAS = 10


def _desenhar_grade(imagem: Image.Image) -> Image.Image:
    """
    Desenha uma grade 10x10 sobre a imagem com identificadores de célula.
    As colunas são letras A-J e as linhas são números 0-9.
    Célula = LETRA + NÚMERO (ex: A0, B5, J9).
    """
    img = imagem.copy().convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    largura_celula = w / GRADE_COLS
    altura_celula = h / GRADE_LINHAS

    # Tenta carregar uma fonte legível; fallback pra fonte padrão
    try:
        fonte = ImageFont.truetype("arial.ttf", 16)
    except Exception:
        try:
            fonte = ImageFont.truetype("segoeui.ttf", 16)
        except Exception:
            fonte = ImageFont.load_default()

    # Linhas da grade
    for i in range(1, GRADE_COLS):
        x = int(i * largura_celula)
        draw.line([(x, 0), (x, h)], fill=(255, 0, 0, 90), width=1)
    for i in range(1, GRADE_LINHAS):
        y = int(i * altura_celula)
        draw.line([(0, y), (w, y)], fill=(255, 0, 0, 90), width=1)

    # Rótulos das células
    letras = "ABCDEFGHIJ"
    for lin in range(GRADE_LINHAS):
        for col in range(GRADE_COLS):
            cx = int(col * largura_celula + largura_celula / 2)
            cy = int(lin * altura_celula + altura_celula / 2)
            texto = f"{letras[col]}{lin}"
            # Fundo escuro semi-transparente pra melhorar leitura
            bbox = draw.textbbox((0, 0), texto, font=fonte)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle(
                [(cx - tw // 2 - 2, cy - th // 2 - 2), (cx + tw // 2 + 2, cy + th // 2 + 2)],
                fill=(0, 0, 0, 140)
            )
            draw.text((cx - tw // 2, cy - th // 2), texto, font=fonte, fill=(255, 255, 255, 255))

    return img


def celula_para_centro(celula: str) -> tuple[int, int]:
    """
    Converte identificador de célula (ex: "B3") em coordenadas centrais (x, y)
    na escala da imagem 1280x720.
    """
    celula = celula.strip().upper()
    if len(celula) < 2:
        return 0, 0

    letras = "ABCDEFGHIJ"
    col_char = celula[0]
    lin_str = celula[1:]

    if col_char not in letras or not lin_str.isdigit():
        return 0, 0

    col = letras.index(col_char)
    lin = int(lin_str)
    if not (0 <= lin < GRADE_LINHAS and 0 <= col < GRADE_COLS):
        return 0, 0

    largura_celula = GRADE_W / GRADE_COLS
    altura_celula = GRADE_H / GRADE_LINHAS
    x = int(col * largura_celula + largura_celula / 2)
    y = int(lin * altura_celula + altura_celula / 2)
    return x, y


def capturar_tela_com_grade():
    """Captura a tela atual, redimensiona e desenha a grade de precisão."""
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[monitor_atual]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = img.resize((GRADE_W, GRADE_H))
            img = _desenhar_grade(img)
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as e:
        print(f"[VISAO] Erro ao capturar tela com grade: {e}")
        return None



def _tela_bloqueada_pelo_uac() -> bool:
    """Detecta se o UAC (tela de permissão de administrador) está ativa."""
    try:
        # A janela do UAC é uma janela de sistema especial
        # Verificamos se existe uma janela do tipo UAC ou se o desktop está bloqueado
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Verifica se a estação de janela está bloqueada (UAC ativa)
        if kernel32.GetCurrentThreadId:
            hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
            if hdesk:
                return False  # placeholder, fallback abaixo

        # Método alternativo: procura por janelas do UAC conhecidas
        # A classe do UAC pode variar, mas geralmente é "#32770" ou "ConsentPromptDialog"
        hwnd = user32.FindWindowW("ConsentPromptDialog", None)
        if hwnd:
            return True

        hwnd = user32.FindWindowW("#32770", "Controle de Conta de Usuário")
        if hwnd:
            return True

        hwnd = user32.FindWindowW("#32770", "User Account Control")
        if hwnd:
            return True

    except Exception:
        pass
    return False


def capturar_tela():
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[monitor_atual]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = img.resize((1280, 720))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as e:
        # O UAC bloqueia a captura de tela. Não é um erro fatal, apenas retorna None.
        if _tela_bloqueada_pelo_uac():
            print("[VISAO] UAC ativo — captura de tela bloqueada. Aguardando permissão do usuário.")
        else:
            print(f"[VISAO] Erro ao capturar tela: {e}")
        return None

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
            try:
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                img = img.resize((1280, 720))
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)
                imagens.append(base64.b64encode(buffer.read()).decode("utf-8"))
            except Exception as e:
                print(f"[VISAO] Erro ao capturar sequência: {e}")
            time.sleep(intervalo)
    return imagens
