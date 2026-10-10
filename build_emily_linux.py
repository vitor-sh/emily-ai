"""
build_emily_linux.py
====================
Gera o executável Linux da Emily (Fedora testado; qualquer distro com os
pacotes abaixo serve).

Como usar:
    cd minha-ia
    python build_emily_linux.py

O resultado fica em:  dist/Emily/Emily   (pasta onedir)

O que este script faz de diferente do build_emily.py (que é o do Windows):
  - NADA de caminho 8.3 / ctypes.windll — no Linux o caminho é usado como é;
  - hidden imports de LINUX (webview.platforms.gtk, mss.linux, pynput._util.xlib),
    e nenhum módulo de Windows (win32api, pywintypes, edgechromium...);
  - TODOS os módulos da Emily entram no pacote automaticamente: o projeto usa
    __import__ dinâmico em vários lugares (discord_bot, ferramentas,
    ferramentas_vida), e o PyInstaller não enxerga esses imports;
  - runtime hook (pyi_rhook_emily.py) que fixa o cwd na pasta do executável,
    normaliza o PATH do ambiente gráfico e mantém um log unificado em
    ~/.emily_log.txt (inclusive quando há Konsole);
  - gera instalar_atalho.sh, pra Emily aparecer no menu de aplicativos do
    Fedora (GNOME) sem abrir terminal.

Uma vez por SO:  sudo dnf install python3-pip gcc  (e PyInstaller via pip)
Backends da janela (já presentes no Fedora 44 com GNOME):
  webkit2gtk4.1 + python3-gobject  → backend GTK do pywebview (o que é usado)
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

if not os.path.exists("main.py"):
    print("[ERRO] main.py não encontrado! Rode de dentro da pasta minha-ia/")
    sys.exit(1)

try:
    import PyInstaller  # noqa: F401
except ImportError:
    print("[ERRO] PyInstaller não instalado. Rode:")
    print("       pip install --user pyinstaller")
    sys.exit(1)

for pasta in ("build", "dist"):
    if os.path.exists(pasta):
        print(f"[BUILD] Limpando pasta antiga: {pasta}/")
        shutil.rmtree(pasta)

# ─────────────────────────────────────────────────────────────────
# ARQUIVOS E PASTAS NECESSÁRIOS EM TEMPO DE EXECUÇÃO
# Formato: ("origem", "destino_no_pacote") — entra só se existir.
#
# A interface web lê web/, img/ e os retratos DO DISCO em runtime
# (interface_web.py: DIR_BASE = dirname(__file__)) — no pacote onedir isso é
# a pasta _internal/, então os dados têm que estar lá como ARQUIVO, não
# embutidos no bytecode.
# ─────────────────────────────────────────────────────────────────
SEP = os.pathsep  # ":" no Linux

possiveis_dados = [
    ("web",    "web"),     # HTML/CSS/JS da janela (pasta inteira)
    ("static", "static"),  # servidor web do celular
    ("img",    "img"),     # GIFs do sprite por estado
    ("emilyimage.png", "."),   # retrato de perfil
    ("emily.gif",      "."),   # sprite animado
    (".env", "."),             # chaves de API (lidas do cwd pelo llm.py)
    ("requirements.txt", "."), # inventário de dependências (diagnóstico/update)
    ("assets", "assets"),      # modelos RNNoise e Silero VAD
    # Estado persistente que já existir entra junto
    ("memoria.json",      "."),
    ("agenda.json",       "."),
    ("vida_discord.json", "."),
    ("config.yaml",       "."),
    ("emily_cache.json",  "."),
]

dados_extras = []
for origem, destino in possiveis_dados:
    if os.path.exists(origem):
        dados_extras.append(f"{os.path.abspath(origem)}{SEP}{destino}")
        print(f"[BUILD] Incluindo: {origem} -> {destino}/")
    else:
        print(f"[BUILD] Ignorando (não existe): {origem}")

# O pacote Python do Playwright não inclui o executável do Chromium. A Emily
# usa o headless shell, então embutimos somente essa variante (sem copiar o
# Chromium completo, que aumentaria o pacote sem ser usado).
from playwright.sync_api import sync_playwright
with sync_playwright() as _playwright:
    _chromium = os.path.abspath(_playwright.chromium.executable_path)
_cache_browsers = os.path.dirname(os.path.dirname(os.path.dirname(_chromium)))
_revisao = os.path.basename(os.path.dirname(os.path.dirname(_chromium))).split("-", 1)[-1]
_headless = os.path.join(_cache_browsers, f"chromium_headless_shell-{_revisao}")
if not os.path.isdir(_headless):
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"], check=True)
if not os.path.isdir(_headless):
    raise RuntimeError(f"Chromium headless não encontrado em {_headless}")
dados_extras.append(f"{_headless}{SEP}playwright-browsers/chromium_headless_shell-{_revisao}")
print(f"[BUILD] Incluindo Chromium headless do Playwright: revisão {_revisao}")

# ─────────────────────────────────────────────────────────────────
# HIDDEN IMPORTS — MÓDULOS DA EMILY
#
# O main.py, discord_bot.py, ferramentas.py e ferramentas_vida.py usam
# __import__ com nome em string. O PyInstaller não segue isso: qualquer
# módulo esquecido vira NameError DENTRO do exe, na frente do Vitor. O scan
# abaixo pega todos os .py da raiz que não são teste nem script de build.
# ─────────────────────────────────────────────────────────────────
def _e_modulo_interno(nome_arquivo: str) -> bool:
    if not nome_arquivo.endswith(".py"):
        return False
    base = nome_arquivo[:-3]
    if base.startswith("_"):            # testes e sondas do projeto
        return False
    if base.startswith(("test_", "testar_", "testepython", "test_emily")):
        return False
    if base in ("build_emily", "build_emily_linux", "emily_bootstrap",
                "pyi_rhook_emily", "emily_teste_animacao",
                "diagnostico_whatsapp", "dividir_audio"):
        return False
    return True


hidden_imports = [
    base[:-3] for base in sorted(os.listdir("."))
    if _e_modulo_interno(base)
]
print(f"[BUILD] Módulos internos no pacote: {len(hidden_imports)}")
for m in hidden_imports:
    print(f"        - {m}")

# ─────────────────────────────────────────────────────────────────
# HIDDEN IMPORTS — BIBLIOTECAS QUE ESCOLHEM SUBMÓDULO EM RUNTIME
#
# webview.platforms.gtk : o pywebview escolhe o backend no boot (gi/WebKit2 do
#                         sistema — backend que funciona neste Fedora).
# mss.linux             : o mss importa o backend por SO.
# pynput._util.xlib etc.: o pynput também.
# dotenv                : python-dotenv (import dinâmico no llm.py).
# ─────────────────────────────────────────────────────────────────
hidden_imports += [
    # Memória unificada é importada sob demanda; o scan da raiz não inclui
    # pacotes em subpastas. Sem declarar, o updater copia o código mas o exe
    # continua sem o ChromaDB e desativa a memória ao primeiro uso.
    "memoria_unificada",
    "emily_cloud",
    "emily_cloud.core",
    "emily_cloud.service",
    "emily_cloud.integration",
    "emily_cloud.routes",
    "emily_cloud.archives",
    "emily_cloud.location",
    "emily_cloud.storage",
    # A integração do Hollow Knight é um pacote importado opcionalmente pelo
    # main.py. Declarar cada submódulo garante o fallback da Emily compilada
    # quando o gateway permanente não estiver instalado/ativo.
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
    "personalidade_emily",
    "webview.platforms.gtk",
    "mss.linux",
    "mss.tools",
    # O backend do agente importa pyautogui somente durante a sessão; sem
    # hidden import o pacote congelado pode não conter a entrada de mouse.
    "pyautogui",
    "pyscreeze",
    "pygetwindow",
    "pynput._util",
    # pynput >= 1.8 no Linux: backends X11 são _xorg (não _xlib).
    "pynput._util.xorg",
    "pynput.keyboard._xorg",
    "pynput.mouse._xorg",
    "dotenv",
    "dotenv.main",
    # selenium: o monitor de notificações importa o webdriver de forma tardia
    # e o PyInstaller não seguiu — sem isso, no exe ele quebra com
    # "No module named 'selenium.webdriver.chrome.webdriver'" (medido no
    # smoke test do build).
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.chrome.options",
    "selenium.webdriver.chrome.service",
    "selenium.webdriver.common.by",
]

# Pacotes com dados/plugins que o PyInstaller não pega sozinho.
collect_all = [
    "discord", "aiohttp", "watchdog", "webview", "pystray",
    "chromadb", "onnxruntime", "tokenizers", "playwright",
]

# ─────────────────────────────────────────────────────────────────
# MONTA OS ARGUMENTOS DO PYINSTALLER
# ─────────────────────────────────────────────────────────────────
args = [
    # O bootstrap fica congelado e importa main como módulo. Assim um main.py
    # solto em _internal pode vencer a versão embutida depois de uma atualização.
    "emily_bootstrap.py",
    "--name=Emily",
    "--onedir",
    # GUI. O log não se perde: o runtime hook grava em ~/.emily_log.txt e,
    # quando iniciado pelo terminal, também mantém a saída no terminal.
    "--noconsole",
    "--clean",
    "--log-level=WARN",
    f"--paths={SCRIPT_DIR}",
    f"--runtime-hook={os.path.join(SCRIPT_DIR, 'pyi_rhook_emily.py')}",
    "--noconfirm",
    "--upx-exclude=*",               # upx não vem no Fedora por padrão
]
for dado in dados_extras:
    args.append(f"--add-data={dado}")
for imp in hidden_imports:
    args.append(f"--hidden-import={imp}")
for pkg in collect_all:
    args.append(f"--collect-all={pkg}")

print("\n" + "=" * 60)
print("  Iniciando build da Emily (Linux)...")
print("  Demora alguns minutos; aguarde.")
print("=" * 60 + "\n")

resultado = subprocess.run([sys.executable, "-m", "PyInstaller"] + args)
if resultado.returncode != 0:
    print("\n[ERRO] O PyInstaller falhou — rode de novo trocando "
          "--log-level=WARN por INFO pra ver onde.")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# PÓS-BUILD: ATALHO NO MENU DE APLICATIVOS
#
# O instalar_atalho.sh GERA o .desktop com o caminho de ONDE a pasta estiver —
# assim o Vitor pode mover a pasta Emily pra onde quiser e rodar o instalador
# de lá de novo.
# ─────────────────────────────────────────────────────────────────
dist_emily = os.path.join(SCRIPT_DIR, "dist", "Emily")

# ── Registro da ORIGEM (pro botão "Atualizar agora" do atualizador) ──
# Linha 1: pasta do projeto. Linha 2: hash legado do main.py. Builds novos
# atualizam main normalmente, mas manter a segunda linha deixa o atualizador
# compatível com executáveis antigos.
_caminho_main = os.path.join(SCRIPT_DIR, "main.py")
with open(_caminho_main, "rb") as _f:
    _hash_main = hashlib.md5(_f.read()).hexdigest()
with open(os.path.join(dist_emily, "_internal", "origem_projeto.txt"),
          "w", encoding="utf-8") as _f:
    _f.write(f"{SCRIPT_DIR}\n{_hash_main}\n")

# ── Manifesto de hashes do EMBUTIDO (pro botão "Atualizar agora") ──
#
# O diff do atualizador compara a origem contra o que VALE no pacote:
# o override solto em _internal/ se existir, senão o código EMBUTIDO.
# O embutido não é hash-ável em runtime (está compilado dentro do PYZ),
# então o build grava aqui o md5 de cada módulo na hora de compilar.
#
# Sem isto, o estado comparava "arquivo solto existe?" — e num pacote
# recém-compilado NENHUM módulo é solto, então TODOS contavam como
# "novos": o botão mostrava ~54 mudanças eternas mesmo com o pacote
# recém-saído do forno, e recompilar nunca resolvia. Com o manifesto,
# pacote recém-compilado = 0 mudanças; só o que você editou DEPOIS do
# build aparece como pendência. (O atualizador aceita pacote sem o
# manifesto — cai no comportamento antigo —, então a primeira atualização
# exige esta versão nova do build uma vez.)
_manifesto_build = {}
for _mod in hidden_imports:
    _arq = os.path.join(SCRIPT_DIR, _mod + ".py")
    if os.path.isfile(_arq):
        with open(_arq, "rb") as _fh:
            _manifesto_build[_mod] = hashlib.md5(_fh.read()).hexdigest()
for _pacote in ("memoria_unificada", "hollow_knight_emily"):
    _raiz_pacote = os.path.join(SCRIPT_DIR, _pacote)
    if not os.path.isdir(_raiz_pacote):
        continue
    for _raiz, _dirs, _arquivos in os.walk(_raiz_pacote):
        _dirs[:] = [d for d in _dirs if d != "__pycache__"]
        for _nome in _arquivos:
            if not _nome.endswith(".py"):
                continue
            _arq = os.path.join(_raiz, _nome)
            _rel = os.path.relpath(_arq, SCRIPT_DIR)
            _partes = list(os.path.splitext(_rel)[0].split(os.sep))
            if _partes[-1] == "__init__":
                _partes.pop()
            _chave = ".".join(_partes)
            with open(_arq, "rb") as _fh:
                _manifesto_build[_chave] = hashlib.md5(_fh.read()).hexdigest()
with open(os.path.join(dist_emily, "_internal", "_atualizacao_base.json"),
          "w", encoding="utf-8") as _f:
    json.dump({"gerado": time.strftime("%d/%m/%Y %H:%M"),
               "modulos": _manifesto_build,
               "main_atualizavel": True,
               "entrypoint": "emily_bootstrap.py"},
              _f, ensure_ascii=False, sort_keys=True, indent=1)
print(f"[BUILD] Manifesto do embutido gravado "
      f"({len(_manifesto_build)} módulos) -> _internal/_atualizacao_base.json")

# O PyInstaller copia os dados com o modo padrão (644/755), então o .env e o
# config.yaml do pacote ficavam legíveis por qualquer usuário do sistema
# mesmo com o original em 600. Chave de API só pro dono.
for _segredo in (".env", "config.yaml"):
    _caminho_segredo = os.path.join(dist_emily, "_internal", _segredo)
    if os.path.isfile(_caminho_segredo):
        os.chmod(_caminho_segredo, 0o600)

instalador = """#!/usr/bin/env bash
# Instala a Emily no menu de aplicativos E no início da sessão (escondida na
# bandeja). Rode de dentro da pasta onde o Emily está:  ./instalar_atalho.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
ICONE="$DIR/_internal/emilyimage.png"
[ -f "$ICONE" ] || ICONE="$DIR/emilyimage.png"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS" "$HOME/.config/autostart"

# Exec com ASPAS: caminhos com espaço ("My Projects"...) quebram o lançador
# sem elas — o sistema tentava executar só a primeira parte do caminho.
cat > "$APPS/Emily.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Emily
Comment=A Emily — assistente pessoal
Exec="$DIR/Emily"
Path=$DIR
Icon=$ICONE
Terminal=false
Categories=Utility;AudioVideo;
StartupWMClass=Emily
EOF

# Início automático: sobe junto com a sessão, escondida na bandeja
# (EMILY_INICIAR_OCULTA=1). Pra remover: rm ~/.config/autostart/Emily.desktop
cat > "$HOME/.config/autostart/Emily.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Emily (segundo plano)
Comment=Emily iniciada junto com a sessão, escondida na bandeja
Exec=env EMILY_INICIAR_OCULTA=1 "$DIR/Emily"
Path=$DIR
Icon=$ICONE
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

chmod +x "$DIR/Emily"
command -v update-desktop-database >/dev/null 2>&1 && \\
    update-desktop-database "$APPS" 2>/dev/null || true

echo "[OK] Atalho no menu de aplicativos: $APPS/Emily.desktop"
echo "[OK] Início automático: ~/.config/autostart/Emily.desktop"
echo "     (a Emily sobe escondida na bandeja junto com a sessão;"
echo "      pra tirar do início automático:"
echo "      rm ~/.config/autostart/Emily.desktop)"
"""
with open(os.path.join(dist_emily, "instalar_atalho.sh"), "w",
          encoding="utf-8") as f:
    f.write(instalador)
os.chmod(os.path.join(dist_emily, "instalar_atalho.sh"), 0o755)

leia_me = """EMILY — versão empacotada (Linux)
=================================

Como rodar
  Duplo clique no 'Emily' (ou ./Emily no terminal).

Bandeja (tray)
  Fechar a janela (X) NÃO encerra a Emily: ela continua rodando em
  segundo plano, com o ícone ao lado do relógio. Clique no ícone pra
  'Abrir a Emily' ou 'Sair de verdade'.

Atualizar sem recompilar
  Configurações → Atualização → 'Atualizar agora e reiniciar'.
  Sincroniza main.py, os demais módulos, a interface e os recursos com a pasta
  do projeto. Se ela tiver sido movida, use 'Escolher pasta do projeto'.
  Módulos .py próprios atualizam normalmente. Instalar ou trocar a versão de
  uma dependência externa, especialmente nativa, ainda exige recompilação.

Início automático com o sistema
  ./instalar_atalho.sh   (rode de dentro desta pasta)
  Instala o atalho no menu de aplicativos E o início automático com a
  sessão (a Emily sobe escondida na bandeja).
  Pra tirar do início automático:
    rm ~/.config/autostart/Emily.desktop

Logs
  O botão 'Logs ao vivo' na tela inicial mostra terminal, erros e estado do
  ngrok. Tudo também fica em ~/.emily_log.txt. Pelo Konsole, a saída aparece
  nos dois lugares.

Dados que a Emily grava (memoria.json, agenda.json, uploads…)
  ficam AQUI dentro, ao lado do executável. Mova a pasta inteira
  se quiser levá-la pra outro lugar — e rode o instalar_atalho.sh
  de novo na pasta nova.

Importante
  O .env dentro de _internal/ tem as chaves de API. Não compartilhe
  esta pasta com ninguém.
"""
with open(os.path.join(dist_emily, "LEIA-ME.txt"), "w",
          encoding="utf-8") as f:
    f.write(leia_me)

print("\n" + "=" * 60)
print("  Build concluído!")
print(f"  Executável: {os.path.join(dist_emily, 'Emily')}")
print(f"  Atalho no menu: {os.path.join(dist_emily, 'instalar_atalho.sh')}")
print("  Logs (sem terminal): ~/.emily_log.txt")
print("=" * 60)
