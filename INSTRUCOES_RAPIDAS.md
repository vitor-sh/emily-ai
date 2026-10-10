> **Documento histórico (01/09/2026).** Descreve a primeira migração para o Linux.
> Vários arquivos citados aqui (`automacao_linux.py`, `terminal_linux.py`,
> `automacao_compat.py`, `main_bootstrap.py`) não existem mais. O guia atual é o
> [LINUX_README.md](LINUX_README.md).

# Instruções Rápidas - Inicializar Emily no Linux

## 1. Instalar Dependências do Sistema

```bash
# Fedora (seu sistema)
sudo dnf install -y wmctrl xdotool playerctl trash-cli xdg-utils webkit2gtk4.0 python3-gobject portaudio portaudio-devel
```

## 2. Instalar Dependências Python

```bash
cd "/home/Hiucksam/My Projects/Projeto Emily/minha-ia"
pip install -r requirements.txt
```

## 3. Testar Inicialização

```bash
python3 testes_manuais/test_emily_init.py
```

Este comando vai testar todos os módulos e reportar o status.

## 4. Iniciar a Emily

### Com Interface Gráfica (precisa de X11)
```bash
DISPLAY=:0 python3 main.py
```

### Sem Interface (modo headless)
```bash
python3 main.py
```

## Correções Aplicadas

✅ Criados módulos de compatibilidade Linux:
- `platform_compat.py` - Detecção de SO
- `terminal.py` - Terminal com portão de segurança (PowerShell no Windows, Bash no Linux)
- `automacao_linux.py` - Automação usando CLI tools
- `compat_imports.py` - Wrappers para keyboard, pyperclip, etc
- `automacao_compat.py` - Escolhe automaticamente Windows ou Linux
- `voz_compat.py` - Compatibilidade para voz.py

✅ Problemas corrigidos:
- Imports de bibliotecas Windows (win32*, keyboard, pyautogui)
- Automação do sistema usando CLI ao invés de win32 APIs
- Terminal usando Bash ao invés de PowerShell
- Interface gráfica funciona com pywebview (já instalado)

## Próxima Etapa (Necessária)

O `main.py` precisa ser modificado para usar os wrappers de compatibilidade.

Adicione no início do `main.py` (após os imports padrão):

```python
# Compatibilidade Linux
from platform_compat import is_linux, is_windows

if is_linux():
    import compat_imports
    # Substituir no sys.modules
    import sys
    sys.modules['keyboard'] = compat_imports.keyboard
    sys.modules['pyperclip'] = compat_imports.pyperclip
    sys.modules['pyautogui'] = compat_imports.pyautogui
    # Usar automacao_linux ao invés de automacao.py
    import automacao_compat as automacao
else:
    import keyboard
    import pyperclip
    import automacao
```

E substitua a linha:
```python
import automacao
```

Por:
```python
# (já importado acima com compatibilidade)
```

## Status Atual

🟢 Módulos de compatibilidade: **PRONTOS**
🟡 Teste de inicialização: **CRIADO** (execute `python3 testes_manuais/test_emily_init.py`)
🟡 Main.py: **PRECISA MODIFICAÇÃO** (instruções acima)

Após modificar o `main.py`, a Emily deve inicializar sem erros!
