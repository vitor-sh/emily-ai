"""
build_emily.py
==============
Rode esse script de DENTRO da pasta minha-ia/ para gerar o Emily.exe

Como usar:
    cd minha-ia
    python build_emily.py

O executável vai ficar em:  dist/Emily/Emily.exe
"""

import PyInstaller.__main__
import shutil
import os
import sys
import subprocess

def caminho_curto(path: str) -> str:
    """Converte um caminho longo com caracteres especiais para o formato 8.3 do Windows."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.kernel32.GetShortPathNameW(path, buf, 512)
        resultado = buf.value
        return resultado if resultado else path
    except Exception:
        return path

def caminho_curto_dir(path: str) -> str:
    """
    Converte APENAS o diretório para caminho 8.3, preservando o nome original do arquivo/pasta.
    Isso evita que 'emilyimage.png' vire 'EMILYI~1.PNG' no dist.
    """
    parent = os.path.dirname(path)
    name   = os.path.basename(path)
    short_parent = caminho_curto(parent)
    return os.path.join(short_parent, name)

# ─────────────────────────────────────────────────────────────────
# GARANTE QUE ESTÁ RODANDO DE DENTRO DA PASTA minha-ia/
# ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)
print(f"[BUILD] Pasta de trabalho: {os.getcwd()}")

# Verifica se o main.py existe aqui
if not os.path.exists("main.py"):
    print("[ERRO] main.py não encontrado! Rode o script de dentro da pasta minha-ia/")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# LIMPA BUILDS ANTERIORES
# ─────────────────────────────────────────────────────────────────
for pasta in ["build", "dist"]:
    if os.path.exists(pasta):
        print(f"[BUILD] Limpando pasta antiga: {pasta}/")
        shutil.rmtree(pasta)

# ─────────────────────────────────────────────────────────────────
# ARQUIVOS E PASTAS NECESSÁRIOS EM TEMPO DE EXECUÇÃO
# Formato: ("caminho_origem", "pasta_destino_no_exe")
# ─────────────────────────────────────────────────────────────────
SEP = os.pathsep  # ";" no Windows, ":" no Linux/Mac

dados_extras = []

possiveis_dados = [
    # Interface — pasta de GIFs e imagens do sprite
    ("img",              "img"),
    # Servidor web — HTML da interface mobile
    ("static",           "static"),
    # Imagem de perfil da Emily no painel
    ("emilyimage.png",   "."),
    # GIF da Emily (usado pelo sprite tkinter)
    ("emily.gif",        "."),
    # Variáveis de ambiente (chaves de API, etc.)
    (".env",             "."),
    # Memória persistente da Emily
    ("memoria.json",     "."),
    # Cache de comandos (gerado em uso, mas inclui se já existir)
    ("emily_cache.json", "."),
    # Modelos pequenos de pré-processamento de áudio (RNNoise + Silero VAD)
    ("assets",            "assets"),

    # ── A INTERFACE ────────────────────────────────────────────────
    # A tela é HTML/CSS/JS lido do disco em tempo de execução, então tem
    # que existir como ARQUIVO ao lado do exe — não serve estar embutido
    # no bytecode. É o mesmo motivo do static/ do servidor do celular.
    ("web/index.html", "web"),
    ("web/estilo.css", "web"),
    ("web/app.js",     "web"),
    ("web/editor.js", "web"),
    ("web/editor-core.js", "web"),
    ("web/editor.css", "web"),
    ("web/editor-layout.json", "web"),
    ("web/editor-panel.html", "web"),
    ("web/editor-panel.js", "web"),
    ("web/editor-controls.js", "web"),
    ("web/dark-controls.js", "web"),
    ("web/dark-controls.css", "web"),
    ("web/cloud.css",  "web"),
    ("web/cloud.js",   "web"),

]

for origem, destino in possiveis_dados:
    abs_origem = os.path.abspath(origem)
    if os.path.exists(abs_origem):
        # Usa caminho_curto_dir para converter APENAS o diretório pai para 8.3,
        # preservando o nome original do arquivo (evita EMILYI~1.PNG, ENV~1, etc.)
        short_origem = caminho_curto_dir(abs_origem)
        dados_extras.append(f"{short_origem}{SEP}{destino}")
        print(f"[BUILD] Incluindo: {origem} -> {destino}/")
    else:
        print(f"[BUILD] Ignorando (não encontrado): {origem}")

# ─────────────────────────────────────────────────────────────────
# HIDDEN IMPORTS
# Libs que o PyInstaller não detecta sozinho por importação dinâmica
# ─────────────────────────────────────────────────────────────────
hidden_imports = [

    # ── Módulos internos da Emily (todos precisam ser declarados) ──
    "automacao",
    "interface",
    "intencoes",
    "memoria",
    "modelo",
    "personalidade_emily",
    "modo_demo",
    "classificacao_ferramentas",
    "notificacoes",
    "pesquisa",
    "servidor",
    "visao",
    "voz",
    "audio_preprocessing",
    "discord_bot",
    "agente_ui",
    "agente_jogo",
    "hollow_knight_emily",
    "hollow_knight_emily.python",
    "hollow_knight_emily.python.hollow_knight_audio",
    "hollow_knight_emily.python.hollow_knight_cerebro",
    "hollow_knight_emily.python.hollow_knight_memoria",
    "hollow_knight_emily.python.hollow_knight_modelos",
    "hollow_knight_emily.python.hollow_knight_permanente",
    "hollow_knight_emily.python.hollow_knight_politica",
    "hollow_knight_emily.python.hollow_knight_protocolo",
    "hollow_knight_emily.python.hollow_knight_ponte",
    "memoria_unificada",
    "emily_cloud",
    "emily_cloud.core",
    "emily_cloud.service",
    "emily_cloud.integration",
    "emily_cloud.routes",
    "emily_cloud.archives",
    "emily_cloud.location",
    "emily_cloud.storage",
    "ferramentas_cloud",
    # llm e ferramentas: o PyInstaller acha os dois pela cadeia de imports do
    # modelo.py, mas declarar é barato e eles são o coração do projeto.
    "llm",
    "ferramentas",
    "laco_ferramentas",
    "navegador",
    # A interface web e a antiga. As duas entram: o EMILY_UI=qt precisa
    # que a antiga exista no exe, e o import dela no main.py é condicional
    # (o PyInstaller não enxerga import dentro de if).
    "interface_web",
    "editor_interface",
    "editor_assistant",
    "editor_assets",
    "publicar_windows_codigo",
    "windows_update",
    "interface",
    # O pywebview escolhe o backend em tempo de execução, por import
    # dinâmico. Sem declarar, o exe sobe sem a WebView2 e a janela não abre.
    "webview",
    "webview.platforms.edgechromium",
    "clr_loader",
    "pythonnet",

    # ── PyQt6 (interface gráfica principal) ──
    "PyQt6",
    "PyQt6.QtWidgets",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.sip",

    # ── tkinter + tkinterdnd2 (sprite GIF flutuante) ──
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinterdnd2",

    # ── PIL / Pillow (imagens, GIFs, stream de tela) ──
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "PIL.ImageFilter",
    "PIL._imaging",

    # ── pynput (mouse PTT) ──
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",
    "pynput._util",
    "pynput._util.win32",
    "pynput.keyboard._win32",
    "pynput.mouse._win32",

    # ── pyaudio (microfone para gravação de voz) ──
    "pyaudio",

    # ── keyboard (atalhos globais, PTT, modo escrito) ──
    "keyboard",

    # ── mouse (controle de mouse por atalhos) ──
    "mouse",

    # ── pyperclip (clipboard para modo escrito e agente UI) ──
    "pyperclip",

    # ── speech_recognition (reconhecimento de voz local) ──
    "speech_recognition",

    # ── fish_audio_sdk (TTS — voz da Emily) ──
    "fish_audio_sdk",

    # ── groq (transcrição de áudio via Whisper) ──
    "groq",
    "groq._utils",
    "groq._models",

    # ── openai (gerador de imagens e cliente alternativo) ──
    "openai",
    "openai.types",
    "openai._client",
    "openai.resources",
    "openai.resources.images",

    # ── boto3 / botocore (AWS Bedrock — modelo de IA principal) ──
    "boto3",
    "boto3.session",
    "botocore",
    "botocore.session",
    "botocore.credentials",
    "botocore.config",
    "botocore.endpoint",
    "botocore.parsers",
    "botocore.serialize",
    "botocore.signers",
    "s3transfer",

    # ── mss (captura de tela) ──
    "mss",
    "mss.windows",
    "mss.tools",

    # ── pyautogui + pygetwindow (agente UI — controla mouse/teclado) ──
    "pyautogui",
    "pygetwindow",

    # ── flask (servidor web para controle pelo celular) ──
    "flask",
    "flask.templating",
    "flask.json",
    "werkzeug",
    "werkzeug.serving",
    "werkzeug.routing",
    "jinja2",
    "jinja2.ext",
    "click",

    # ── discord.py (bot do Discord) ──
    "discord",
    "discord.ext",
    "discord.ext.commands",
    "discord.ext.voice_recv",
    "discord.gateway",
    "discord.http",
    "discord.voice_client",

    # ── aiohttp (download de imagens do Discord) ──
    "aiohttp",
    "aiohttp.connector",
    "aiohttp.client",

    # ── selenium + webdriver_manager (monitoramento WhatsApp) ──
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.chrome",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.common.by",
    "webdriver_manager",
    "webdriver_manager.chrome",

    # ── watchdog (monitoramento da pasta de Downloads) ──
    "watchdog",
    "watchdog.observers",
    "watchdog.events",

    # ── python-dotenv (carregamento do .env) ──
    "dotenv",
    "dotenv.main",

    # ── pywin32 (integração com Windows — operações de arquivo, registro) ──
    "win32api",
    "win32con",
    "win32gui",
    "win32com",
    "win32com.client",
    "win32com.shell",
    "win32com.shell.shell",
    "pywintypes",
    "pythoncom",

    # ── winreg (leitura do registro para pastas especiais) ──
    "winreg",

    # ── requests (chamadas HTTP genéricas) ──
    "requests",
    "requests.adapters",
    "requests.auth",
    "requests.packages",
    "urllib3",

    # ── send2trash (lixeira do Windows) ──
    "send2trash",

    # ── ctypes (baixo nível Windows — operações de shell) ──
    "ctypes",
    "ctypes.wintypes",

    # ── Stdlib que o PyInstaller às vezes perde ──
    "json",
    "threading",
    "subprocess",
    "queue",
    "wave",
    "io",
    "base64",
    "asyncio",
    "pathlib",
    "re",
    "unicodedata",
    "webbrowser",
    "difflib",
    "datetime",
    "glob",
    "struct",
]

# ─────────────────────────────────────────────────────────────────
# PACOTES QUE PRECISAM DE --collect-all
# (têm dados ou plugins que o PyInstaller não pega automaticamente)
# ─────────────────────────────────────────────────────────────────
collect_all = [
    "PyQt6",
    "boto3",
    "botocore",
    "discord",
    "fish_audio_sdk",
    "groq",
    "pyautogui",
    "pygetwindow",
    "watchdog",
    "selenium",
    "webdriver_manager",
    "aiohttp",
    # Memória vetorial: importada sob demanda e com extensões/dados próprios.
    "chromadb",
    "onnxruntime",
    "tokenizers",
]

# ─────────────────────────────────────────────────────────────────
# MONTA OS ARGUMENTOS DO PYINSTALLER
# ─────────────────────────────────────────────────────────────────
args = [
    "main.py",                       # arquivo principal
    "--name=Emily",                  # nome do executável
    "--onedir",                      # pasta única (mais fácil debugar que --onefile)
    "--noconsole",                   # sem janela de terminal (GUI puro)
    "--clean",                       # limpa cache do PyInstaller antes de buildar
    "--log-level=WARN",              # só mostra warnings e erros no log
    f"--paths={SCRIPT_DIR}",         # adiciona a pasta minha-ia/ ao sys.path
    "--noconfirm",                   # não pergunta antes de sobrescrever
]

# Adiciona os arquivos de dados
for dado in dados_extras:
    args.append(f"--add-data={dado}")

# Adiciona os hidden imports
for imp in hidden_imports:
    args.append(f"--hidden-import={imp}")

# Adiciona os collect-all (garante que dados dos pacotes são incluídos)
for pkg in collect_all:
    args.append(f"--collect-all={pkg}")

# ─────────────────────────────────────────────────────────────────
# INICIA O BUILD
# ─────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("  Iniciando build da Emily...")
print("  Isso pode demorar alguns minutos, aguarde!")
print("="*60 + "\n")

PyInstaller.__main__.run(args)

print("\n" + "="*60)
print("  Build concluído!")
print(f"  Executável em: {os.path.join(SCRIPT_DIR, 'dist', 'Emily', 'Emily.exe')}")
print("="*60)
