import mss
import time
import base64
import ctypes
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# ─────────────────────────────────────────────────────────────────
# NUMERAÇÃO DE MONITORES
#
# O mss enumera as telas na ordem que o Windows entrega, e essa ordem não tem
# nada a ver com o que a pessoa chama de "monitor 1". Medido nesta máquina:
#
#   mss.monitors[1] = DELL  1280x1024 em (1920,0)  is_primary=False
#   mss.monitors[2] = AOC   1920x1080 em (0,0)     is_primary=True
#
# Como monitor_atual começava em 1 e era usado direto como índice do mss, a
# Emily olhava para a tela SECUNDÁRIA desde sempre. E quando o Vitor pedia
# "troca pro monitor 1", ela ia justamente pra tela errada de novo. Daí ela
# descrever coisa que não estava em nenhum monitor que ele estava olhando.
#
# Agora monitor_atual é o número que a PESSOA usa, contando de 1, com o
# monitor primário sempre em primeiro. A tradução pro índice do mss acontece
# num só lugar: geometria_atual().
# ─────────────────────────────────────────────────────────────────

monitor_atual = 1  # número humano: 1 = monitor primário


def _indices_ordenados() -> list[int]:
    """
    Índices do mss em ordem humana: primário primeiro, depois os outros da
    esquerda pra direita. O índice 0 do mss é a área virtual somada de todas
    as telas, não um monitor, então fica fora.
    """
    try:
        with mss.mss() as sct:
            reais = [(i, m) for i, m in enumerate(sct.monitors) if i > 0]
    except Exception as e:
        print(f"[VISAO] Não consegui enumerar monitores: {e}")
        return [1]
    if not reais:
        return [1]
    reais.sort(key=lambda par: (
        0 if par[1].get("is_primary") else 1,
        par[1].get("left", 0),
        par[1].get("top", 0),
    ))
    return [i for i, _ in reais]


def geometria_atual() -> dict:
    """
    Geometria do monitor em uso, já traduzida do número humano pro mss.

    Todo mundo que precisa das coordenadas reais da tela deve usar isso, e
    não sct.monitors[visao.monitor_atual] — foi essa indexação direta que
    fazia a captura e os cliques irem pra tela errada.
    """
    ordem = _indices_ordenados()
    posicao = min(max(1, int(monitor_atual)), len(ordem)) - 1
    indice = ordem[posicao]
    with mss.mss() as sct:
        return dict(sct.monitors[indice])

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

    # Negrito de propósito: foi a fonte usada na medição de acerto da grade.
    try:
        fonte = ImageFont.truetype("arialbd.ttf", 16)
    except Exception:
        try:
            fonte = ImageFont.truetype("arial.ttf", 16)
        except Exception:
            try:
                fonte = ImageFont.truetype("segoeuib.ttf", 16)
            except Exception:
                fonte = ImageFont.load_default()

    # Linhas da grade. Espessura 2 e alfa 170 em vez de 1 e 90: o rótulo
    # precisa sobreviver ao reescalonamento que o encoder de visão do
    # modelo faz na imagem antes de olhar pra ela.
    for i in range(1, GRADE_COLS):
        x = int(i * largura_celula)
        draw.line([(x, 0), (x, h)], fill=(255, 0, 0, 170), width=2)
    for i in range(1, GRADE_LINHAS):
        y = int(i * altura_celula)
        draw.line([(0, y), (w, y)], fill=(255, 0, 0, 170), width=2)

    # Rótulos das células. Amarelo sobre caixa preta quase opaca: foi essa
    # combinação que mediu 12/12 de acerto de localização no teste, contra
    # o branco em alfa 140 que estava aqui antes.
    letras = "ABCDEFGHIJ"
    for lin in range(GRADE_LINHAS):
        for col in range(GRADE_COLS):
            cx = int(col * largura_celula + largura_celula / 2)
            cy = int(lin * altura_celula + altura_celula / 2)
            texto = f"{letras[col]}{lin}"
            bbox = draw.textbbox((0, 0), texto, font=fonte)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle(
                [(cx - tw // 2 - 5, cy - th // 2 - 5), (cx + tw // 2 + 5, cy + th // 2 + 5)],
                fill=(0, 0, 0, 215)
            )
            draw.text((cx - tw // 2, cy - th // 2), texto, font=fonte, fill=(255, 255, 0, 255))

    return img


def celula_para_centro(celula: str) -> tuple[int, int]:
    """
    Converte identificador de célula (ex: "B3") em coordenadas centrais (x, y)
    na escala da imagem 1280x720.
    """
    # Os modelos costumam devolver a célula com sujeira em volta: aspas,
    # ponto final ("H8."), crase, espaço. Medido de verdade: o
    # llama-3.2-11b responde 'H8.' e o 90b responde 'J1.'. Sem essa
    # limpeza a célula era descartada como inválida.
    celula = "".join(c for c in str(celula).upper() if c.isalnum())
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
    """
    Captura a tela atual, redimensiona e desenha a grade de precisão.

    Aqui o resize continua sendo o esticamento direto pra GRADE_W x GRADE_H, de
    propósito: o agente_ui converte célula da grade em coordenada real usando a
    proporção entre a imagem e o monitor. Um esticamento uniforme por eixo é
    invertível e o clique cai no lugar certo; encaixar com barras preras
    quebraria essa conta.
    """
    try:
        with mss.mss() as sct:
            monitor = geometria_atual()
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


def _reduzir_sem_distorcer(img: Image.Image, largura=1280, altura=720) -> Image.Image:
    """
    Encaixa a imagem dentro de largura x altura mantendo a proporção.

    Necessário porque o resize direto pra 1280x720 esmaga monitor que não é
    16:9. O monitor 1280x1024 desta máquina era comprimido 30% na vertical, e
    tela distorcida é exatamente o que faz modelo de visão errar o que está
    vendo. Aqui não há mapeamento de coordenada envolvido — isso é só pra
    olhar — então preservar a proporção é ganho puro.
    """
    img.thumbnail((largura, altura), Image.LANCZOS)
    return img


def capturar_tela():
    try:
        with mss.mss() as sct:
            monitor = geometria_atual()
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            img = _reduzir_sem_distorcer(img)
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

def listar_monitores() -> list[dict]:
    """Monitores disponíveis, numerados na ordem humana (1 = primário)."""
    try:
        ordem = _indices_ordenados()
        with mss.mss() as sct:
            saida = []
            for humano, indice in enumerate(ordem, start=1):
                m = sct.monitors[indice]
                saida.append({
                    "numero": humano,
                    "largura": m["width"],
                    "altura": m["height"],
                    "esquerda": m["left"],
                    "topo": m["top"],
                    "principal": bool(m.get("is_primary")),
                    "nome": m.get("name", ""),
                })
            return saida
    except Exception as e:
        print(f"[VISAO] Não consegui listar monitores: {e}")
        return []


def trocar_monitor(numero: int | None = None):
    """
    Escolhe qual monitor a captura usa.

    numero — monitor desejado, contando de 1. Se vier None, alterna pro
             próximo, que é o comportamento antigo.

    Aceitar o número é obrigatório, não conveniência: a ferramenta
    trocar_monitor sempre chamou isso com o número que o Vitor pediu, e como
    a função não aceitava argumento a chamada estourava TypeError. O
    ferramentas.executar transformava isso em "Argumentos inválidos", e a
    Emily dizia "a ferramenta tá dando erro" e continuava presa no mesmo
    monitor.

    Devolve o número do monitor em uso, ou uma string de erro se o pedido
    não existe — assim a Emily fala o motivo em vez de um erro técnico.
    """
    global monitor_atual

    monitores = listar_monitores()
    total = len(monitores)
    if total == 0:
        return "Não consegui enxergar nenhum monitor no sistema."

    if numero is None:
        monitor_atual = (monitor_atual % total) + 1
        return monitor_atual

    try:
        pedido = int(numero)
    except (TypeError, ValueError):
        return f"'{numero}' não é um número de monitor."

    if pedido < 1 or pedido > total:
        disponiveis = ", ".join(str(m["numero"]) for m in monitores)
        return (f"Não existe monitor {pedido}. Os que existem são: {disponiveis}. "
                f"Diga ao Vitor quais são as opções.")

    monitor_atual = pedido
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
        monitor = geometria_atual()
        for _ in range(quantidade):
            try:
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
                img = _reduzir_sem_distorcer(img)
                buffer = BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                buffer.seek(0)
                imagens.append(base64.b64encode(buffer.read()).decode("utf-8"))
            except Exception as e:
                print(f"[VISAO] Erro ao capturar sequência: {e}")
            time.sleep(intervalo)
    return imagens

# ─────────────────────────────────────────────────────────────────
# TRIAGEM DE BAIXO CUSTO
# A triagem só precisa decidir SIM/NAO — não precisa de resolução
# cheia. 640x360 custa ~307 tokens de imagem contra ~1229 de
# 1280x720, com a mesma taxa de acerto pra "aconteceu algo grande?".
# A resolução cheia continua sendo usada nas análises de verdade.
# ─────────────────────────────────────────────────────────────────

TRIAGEM_W = 640
TRIAGEM_H = 360
TRIAGEM_QUALIDADE = 70

# Lado da miniatura usada pra assinar o frame e comparar com o anterior.
ASSINATURA_LADO = 32

# Diferença média (0-255) entre duas assinaturas a partir da qual
# consideramos que a tela realmente mudou. Valor baixo porque a
# maior parte do ruído de compressão fica bem abaixo de 1.
LIMIAR_TELA_MUDOU = 2.0


def capturar_tela_triagem():
    """
    Captura a tela em resolução reduzida, só pra triagem SIM/NAO.
    Bem mais barato em tokens que capturar_tela().
    """
    try:
        with mss.mss() as sct:
            monitor = geometria_atual()
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            # Triagem só decide SIM/NAO, então o esticamento aqui é aceitável e
            # mantém o tamanho do payload previsível.
            img = img.resize((TRIAGEM_W, TRIAGEM_H))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=TRIAGEM_QUALIDADE)
            buffer.seek(0)
            return base64.b64encode(buffer.read()).decode("utf-8")
    except Exception as e:
        if _tela_bloqueada_pelo_uac():
            print("[VISAO] UAC ativo — captura de triagem bloqueada.")
        else:
            print(f"[VISAO] Erro ao capturar tela para triagem: {e}")
        return None


def assinatura_frame(imagem_base64: str):
    """
    Reduz um frame base64 a uma miniatura 32x32 em escala de cinza e
    devolve a lista de luminâncias. Serve pra comparar frames sem
    gastar chamada de LLM.
    Retorna None se não der pra processar.
    """
    if not imagem_base64:
        return None
    try:
        dados = base64.b64decode(imagem_base64)
        img = Image.open(BytesIO(dados)).convert("L")
        img = img.resize((ASSINATURA_LADO, ASSINATURA_LADO))
        return list(img.getdata())
    except Exception as e:
        print(f"[VISAO] Erro ao assinar frame: {e}")
        return None


def diferenca_assinaturas(assinatura_a, assinatura_b) -> float:
    """
    Diferença média absoluta entre duas assinaturas, de 0 a 255.
    Retorna 255.0 (diferença máxima) se alguma assinatura faltar,
    pra nunca suprimir um frame por falta de dado.
    """
    if not assinatura_a or not assinatura_b:
        return 255.0
    if len(assinatura_a) != len(assinatura_b):
        return 255.0
    total = sum(abs(a - b) for a, b in zip(assinatura_a, assinatura_b))
    return total / len(assinatura_a)


def tela_mudou(assinatura_anterior, assinatura_atual, limiar: float = LIMIAR_TELA_MUDOU) -> bool:
    """
    True se a tela mudou o suficiente pra valer uma chamada de LLM.
    Na primeira execução (sem assinatura anterior) sempre retorna True.
    """
    if assinatura_anterior is None:
        return True
    return diferenca_assinaturas(assinatura_anterior, assinatura_atual) >= limiar
