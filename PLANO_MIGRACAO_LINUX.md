# Plano de Migração Emily: Windows → Linux

**Data:** 31/08/2026  
**Sistema Alvo:** Fedora 44  
**Abordagem:** Integração com terminal Linux como camada universal de automação

---

## 🎯 Estratégia Geral

Ao invés de reimplementar cada funcionalidade Windows manualmente, vamos usar **comandos CLI do Linux via subprocess**. O terminal Linux é universal e pode fazer 99% do que a Emily fazia no Windows.

### Vantagens desta abordagem:
1. **Universal** - Funciona em qualquer distro Linux
2. **Poderoso** - CLI Linux tem ferramentas para tudo
3. **Manutenível** - Comandos CLI são estáveis e bem documentados
4. **Rápido de implementar** - Muitas ferramentas já estão instaladas
5. **Fallbacks automáticos** - Podemos detectar qual Desktop Environment e adaptar

---

## 📋 Mapeamento Completo: Windows → Linux

### 1. GERENCIAMENTO DE JANELAS

| Funcionalidade | Windows (win32gui) | Linux (CLI) | Pacote Fedora |
|---|---|---|---|
| Listar janelas abertas | `win32gui.EnumWindows()` | `wmctrl -l` ou `xdotool search --class ""` | `wmctrl` ou `xdotool` |
| Minimizar janela | `win32gui.ShowWindow(hwnd, SW_MINIMIZE)` | `wmctrl -i -r <id> -b add,hidden` | `wmctrl` |
| Maximizar janela | `win32gui.ShowWindow(hwnd, SW_MAXIMIZE)` | `wmctrl -i -r <id> -b add,maximized_vert,maximized_horz` | `wmctrl` |
| Fechar janela | `win32gui.SendMessage(hwnd, WM_CLOSE)` | `wmctrl -i -c <id>` ou `xdotool windowkill <id>` | `wmctrl` |
| Focar janela | `win32gui.SetForegroundWindow(hwnd)` | `wmctrl -i -a <id>` ou `xdotool windowactivate <id>` | `wmctrl` |
| Mover janela | `win32gui.MoveWindow()` | `wmctrl -i -r <id> -e 0,x,y,w,h` | `wmctrl` |
| Obter título da janela | `win32gui.GetWindowText(hwnd)` | `wmctrl -l` ou `xdotool getwindowname <id>` | `wmctrl` |
| Obter PID da janela | `win32process.GetWindowThreadProcessId()` | `xdotool getwindowpid <id>` | `xdotool` |

**Comando de instalação:**
```bash
sudo dnf install wmctrl xdotool
```

---

### 2. GERENCIAMENTO DE PROCESSOS

| Funcionalidade | Windows | Linux (CLI) | Já instalado? |
|---|---|---|---|
| Listar processos | `win32process`, `tasklist` | `ps aux` ou `pgrep -a` | ✅ Sim |
| Matar processo por PID | `win32api.TerminateProcess()` | `kill <pid>` ou `kill -9 <pid>` | ✅ Sim |
| Matar processo por nome | `taskkill /IM nome.exe` | `pkill nome` ou `killall nome` | ✅ Sim |
| Verificar se processo existe | `win32process` | `pgrep -x nome` (retcode 0 = existe) | ✅ Sim |
| Obter PID por nome | `win32process` | `pgrep -x nome` ou `pidof nome` | ✅ Sim |

---

### 3. ABRIR APLICATIVOS E ARQUIVOS

| Funcionalidade | Windows | Linux (CLI) | Já instalado? |
|---|---|---|---|
| Abrir app com app padrão | `subprocess.Popen(["cmd", "/c", "start", arquivo])` | `xdg-open arquivo` | ✅ Sim |
| Abrir URL no navegador | `webbrowser.open()` (funciona) ou `start url` | `xdg-open url` | ✅ Sim |
| Executar programa | `subprocess.Popen([caminho])` | `subprocess.Popen([caminho])` | ✅ Sim |
| Abrir terminal | `cmd.exe` | `gnome-terminal` ou `konsole` ou `xfce4-terminal` | Detectar DE |

**Detecção de Desktop Environment:**
```python
DE = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
# "gnome" → gnome-terminal
# "kde" → konsole
# "xfce" → xfce4-terminal
# fallback → xterm
```

---

### 4. DESCOBRIR PROGRAMAS INSTALADOS

| Windows | Linux (CLI) |
|---|---|
| Ler Registry (`winreg`) | Ler arquivos `.desktop` |
| `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall` | `/usr/share/applications/*.desktop` |
| `%PROGRAMFILES%`, `%PROGRAMFILES(X86)%` | `/usr/bin/`, `/usr/local/bin/`, `/opt/`, `~/.local/bin/` |

**Implementação:**
```python
import os
from pathlib import Path
import configparser

def listar_aplicativos_linux():
    """Lista aplicativos instalados lendo arquivos .desktop"""
    apps = {}
    desktop_dirs = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        Path.home() / ".local/share/applications",
        "/var/lib/flatpak/exports/share/applications",  # Flatpak
        Path.home() / ".local/share/flatpak/exports/share/applications"
    ]
    
    for desktop_dir in desktop_dirs:
        if not Path(desktop_dir).exists():
            continue
        for desktop_file in Path(desktop_dir).glob("*.desktop"):
            try:
                config = configparser.ConfigParser(interpolation=None)
                config.read(desktop_file, encoding='utf-8')
                name = config.get("Desktop Entry", "Name", fallback=None)
                exec_cmd = config.get("Desktop Entry", "Exec", fallback=None)
                if name and exec_cmd:
                    apps[name.lower()] = exec_cmd.split()[0]  # Primeiro token do Exec
            except:
                continue
    return apps
```

**Caminhos de programas comuns:**
```python
PROGRAMAS_LINUX = {
    # Navegadores
    "chrome": "/usr/bin/google-chrome-stable",
    "firefox": "/usr/bin/firefox",
    "brave": "/usr/bin/brave-browser",
    "edge": "/usr/bin/microsoft-edge",
    
    # Comunicação
    "discord": "/usr/bin/discord",
    "telegram": "/usr/bin/telegram-desktop",
    "slack": "/usr/bin/slack",
    
    # Mídia
    "spotify": "/usr/bin/spotify",
    "vlc": "/usr/bin/vlc",
    
    # Jogos
    "steam": "/usr/bin/steam",
    
    # Gerenciador de arquivos (detectar DE)
    "nautilus": "/usr/bin/nautilus",  # GNOME
    "dolphin": "/usr/bin/dolphin",    # KDE
    "thunar": "/usr/bin/thunar",      # XFCE
    "nemo": "/usr/bin/nemo",          # Cinnamon
    
    # Editores de texto
    "gedit": "/usr/bin/gedit",
    "kate": "/usr/bin/kate",
    "code": "/usr/bin/code",
    "vscode": "/usr/bin/code",
    
    # Utilitários
    "calculadora": "/usr/bin/gnome-calculator",
    "calc": "/usr/bin/gnome-calculator",
}
```

---

### 5. PASTAS ESPECIAIS

| Windows | Linux |
|---|---|
| `winreg` para descobrir Desktop, Documents, Downloads | Variáveis de ambiente XDG |

**Implementação:**
```python
import os
from pathlib import Path

def obter_pastas_especiais_linux():
    """Retorna as pastas especiais do Linux usando XDG"""
    home = Path.home()
    
    # Tentar ler do ~/.config/user-dirs.dirs primeiro
    user_dirs = {}
    user_dirs_file = home / ".config/user-dirs.dirs"
    if user_dirs_file.exists():
        with open(user_dirs_file) as f:
            for line in f:
                if line.startswith("XDG_"):
                    key, value = line.strip().split("=", 1)
                    # Remove aspas e substitui $HOME
                    value = value.strip('"').replace("$HOME", str(home))
                    user_dirs[key] = Path(value)
    
    # Fallbacks padrão
    return {
        "desktop": user_dirs.get("XDG_DESKTOP_DIR", home / "Desktop"),
        "documents": user_dirs.get("XDG_DOCUMENTS_DIR", home / "Documents"),
        "downloads": user_dirs.get("XDG_DOWNLOAD_DIR", home / "Downloads"),
        "music": user_dirs.get("XDG_MUSIC_DIR", home / "Music"),
        "pictures": user_dirs.get("XDG_PICTURES_DIR", home / "Pictures"),
        "videos": user_dirs.get("XDG_VIDEOS_DIR", home / "Videos"),
    }
```

---

### 6. SIMULAÇÃO DE TECLADO/MOUSE

| Funcionalidade | Windows | Linux (CLI) | Pacote |
|---|---|---|---|
| Pressionar tecla | `ctypes.windll.user32.keybd_event` | `xdotool key <tecla>` | `xdotool` |
| Digitar texto | `pyautogui.write()` | `xdotool type "texto"` | `xdotool` |
| Clicar mouse | `pyautogui.click()` | `xdotool click 1` | `xdotool` |
| Mover mouse | `pyautogui.moveTo()` | `xdotool mousemove x y` | `xdotool` |
| Scroll | `pyautogui.scroll()` | `xdotool click 4` (up) ou `5` (down) | `xdotool` |

**Nota:** `pyautogui` também funciona no Linux, então pode continuar usando. `xdotool` é alternativa CLI.

---

### 7. CLIPBOARD (Área de Transferência)

| Windows | Linux | Já instalado? |
|---|---|---|
| `win32clipboard` | `pyperclip` (já tem no projeto!) | ✅ Sim |
| `ctypes.windll` | `xclip` ou `xsel` (CLI) | Instalar se necessário |

**Implementação:**
```python
import pyperclip  # Já está no projeto

# Funciona no Linux automaticamente!
pyperclip.copy("texto")
texto = pyperclip.paste()
```

---

### 8. CONTROLE DE MÍDIA

| Funcionalidade | Windows | Linux (CLI) | Pacote |
|---|---|---|---|
| Play/Pause | APIs Windows Media | `playerctl play-pause` | `playerctl` |
| Próxima música | APIs Windows Media | `playerctl next` | `playerctl` |
| Música anterior | APIs Windows Media | `playerctl previous` | `playerctl` |
| Volume +/- | APIs Windows | `pactl set-sink-volume @DEFAULT_SINK@ +5%` | ✅ Já instalado |
| Mute/Unmute | APIs Windows | `pactl set-sink-mute @DEFAULT_SINK@ toggle` | ✅ Já instalado |

**Comando de instalação:**
```bash
sudo dnf install playerctl
```

---

### 9. OPERAÇÕES DE ARQUIVO

| Funcionalidade | Windows | Linux |
|---|---|---|
| Mover arquivo | `ctypes.windll.shell32.SHFileOperationW` | `shutil.move()` (já funciona) |
| Copiar arquivo | `ctypes.windll.shell32.SHFileOperationW` | `shutil.copy2()` (já funciona) |
| Deletar arquivo | `ctypes.windll.shell32` (para lixeira) | `subprocess.run(["gio", "trash", arquivo])` |
| Esvaziar lixeira | `ctypes.windll.shell32.SHEmptyRecycleBinW` | `rm -rf ~/.local/share/Trash/files/*` |
| Extrair ZIP | `zipfile` (já funciona) | `zipfile` (já funciona) |

**Para lixeira (trash):**
```python
import subprocess

def enviar_para_lixeira_linux(caminho):
    """Move arquivo para lixeira usando gio trash"""
    try:
        subprocess.run(["gio", "trash", caminho], check=True)
        return True
    except:
        # Fallback: trash-cli
        try:
            subprocess.run(["trash-put", caminho], check=True)
            return True
        except:
            return False
```

---

### 10. NOTIFICAÇÕES DO SISTEMA

| Windows | Linux (CLI) | Já instalado? |
|---|---|---|
| `win10toast` ou APIs Windows | `notify-send` | ✅ Sim |

**Implementação:**
```python
import subprocess

def notificar_linux(titulo, mensagem, icone=None):
    """Envia notificação usando notify-send"""
    cmd = ["notify-send", titulo, mensagem]
    if icone:
        cmd.extend(["--icon", icone])
    subprocess.run(cmd)
```

---

### 11. TERMINAL/SHELL

| Windows | Linux |
|---|---|
| PowerShell (`terminal.py` inteiro) | Bash/Zsh |
| `powershell.exe -Command` | `bash -c` |
| Cmdlets do PowerShell | Comandos Unix padrão |

**Criar `terminal_linux.py`:**
```python
import subprocess
import os

class TerminalLinux:
    def __init__(self):
        self.shell = os.environ.get("SHELL", "/bin/bash")
    
    def executar(self, comando):
        """Executa comando no shell padrão do usuário"""
        result = subprocess.run(
            [self.shell, "-c", comando],
            capture_output=True,
            text=True
        )
        return result.stdout, result.stderr, result.returncode
    
    def executar_async(self, comando):
        """Executa comando em background"""
        return subprocess.Popen(
            [self.shell, "-c", comando],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
```

---

## 🔧 Pacotes Necessários no Fedora

```bash
# Gerenciamento de janelas e automação
sudo dnf install wmctrl xdotool

# Controle de mídia
sudo dnf install playerctl

# Interface gráfica (pywebview com GTK)
sudo dnf install webkit2gtk4.0 python3-gobject

# Áudio (PyAudio)
sudo dnf install portaudio portaudio-devel

# Screenshots (se mss tiver problema com Wayland)
sudo dnf install gnome-screenshot

# Clipboard CLI (opcional, pyperclip já funciona)
sudo dnf install xclip

# Lixeira (fallback se gio não funcionar)
sudo dnf install trash-cli

# Utilitários de desktop
sudo dnf install xdg-utils
```

---

## 📝 Arquivos a Criar/Modificar

### ✅ Criar novos:
1. `platform_compat.py` - Camada de abstração de SO
2. `terminal_linux.py` - Equivalente do terminal.py para Bash
3. `automacao_linux.py` - Implementações Linux das funções de automação

### 🔧 Modificar existentes:
1. `automacao.py` - Adicionar detecção de SO e delegar para `automacao_linux.py`
2. `voz.py` - Adaptar keyboard para não precisar de root
3. `visao.py` - Remover detecção UAC, adaptar fontes
4. `agente_ui.py` - Usar caminhos Linux de programas
5. `interface_web.py` - Remover dwmapi do Windows
6. `main.py` - Importar módulos certos baseado em SO

---

## 🎯 Ordem de Implementação

### Fase 1: Base (CRÍTICO)
1. ✅ Criar `platform_compat.py` - Detector de SO e abstrações básicas
2. ✅ Criar `terminal_linux.py` - Shell Bash
3. ✅ Adaptar `automacao.py` - Integrar comandos Linux via subprocess

### Fase 2: Funcionalidades Core
4. Adaptar `voz.py` - Keyboard sem root
5. Adaptar `visao.py` - Fontes Linux
6. Adaptar `agente_ui.py` - Caminhos Linux

### Fase 3: Interface e Integrações
7. Adaptar `interface_web.py` - Remover APIs Windows
8. Testar `servidor.py` - Verificar se funciona no Linux
9. Testar `discord_bot.py` - Verificar compatibilidade

### Fase 4: Polimento
10. Documentar limitações Linux
11. Criar script de instalação de dependências
12. Testar cada funcionalidade

---

## 🚀 Próximo Passo

Vou começar implementando **Fase 1** agora:
1. Criar `platform_compat.py` com detecção de SO
2. Criar `terminal_linux.py` com comandos Bash
3. Adaptar `automacao.py` para usar comandos Linux

Pronto para começar?
