# Emily - Guia de Inicialização no Linux

Este guia documenta como inicializar a Emily no Linux após a migração do Windows.

## Status da Migração

✅ **Módulos de compatibilidade criados:**
- `platform_compat.py` - Detecção de plataforma e pastas especiais
- `terminal_linux.py` - Execução de comandos shell (equivalente ao terminal.py do Windows)
- `automacao_linux.py` - Automação do sistema usando CLI (wmctrl, xdotool, playerctl)
- `compat_imports.py` - Wrappers para bibliotecas Windows-specific (keyboard, pyperclip, etc)
- `automacao_compat.py` - Wrapper que escolhe automacao.py ou automacao_linux.py automaticamente
- `voz_compat.py` - Wrapper de compatibilidade para voz.py

## Problemas Corrigidos

### 1. Imports específicos do Windows
**Problema:** `main.py` importava `keyboard`, `pyperclip`, `pyautogui` que têm comportamento diferente no Linux.

**Solução:** Criado `compat_imports.py` que:
- Fornece versão Linux do `keyboard` usando `xdotool`
- Cria stubs para módulos `win32*` que não existem no Linux
- Gerencia `pyautogui` sem display X11 quando em modo headless

### 2. Automação do sistema
**Problema:** `automacao.py` usa bibliotecas Windows (win32gui, win32api, etc).

**Solução:** Criado `automacao_linux.py` que usa comandos CLI:
- `wmctrl` para gerenciamento de janelas
- `xdotool` para simulação de teclado/mouse
- `playerctl` para controle de mídia
- `pactl` para volume
- `gio trash` para lixeira

### 3. Terminal/Shell
**Problema:** `terminal.py` usa PowerShell (Windows).

**Solução:** Criado `terminal_linux.py` que usa Bash/Zsh.

### 4. Interface gráfica
**Problema:** PyQt6 não está instalado e `voz.py` tenta conectar ao display X11.

**Solução:** 
- Interface web (pywebview) já funciona no Linux
- Criado `voz_compat.py` para lidar com falta de display

## Dependências Linux

### Dependências do Sistema (CLI tools)
```bash
# Fedora/RHEL
sudo dnf install -y wmctrl xdotool playerctl trash-cli xdg-utils \
                    webkit2gtk4.0 python3-gobject portaudio portaudio-devel

# Debian/Ubuntu
sudo apt install -y wmctrl xdotool playerctl trash-cli xdg-utils \
                    gir1.2-webkit2-4.0 python3-gi libportaudio2 portaudio19-dev
```

### Dependências Python
```bash
pip install -r requirements.txt
```

**NOTA:** PyQt6 é opcional. Se não estiver instalado, a Emily usa pywebview (interface web).

## Como Inicializar

### Opção 1: Teste de Inicialização (Recomendado)
```bash
python3 testes_manuais/test_emily_init.py
```

Este script testa todos os módulos e reporta quais estão funcionando.

### Opção 2: Inicialização Direta
```bash
# Com display X11 (interface gráfica)
DISPLAY=:0 python3 main.py

# Sem display (modo headless)
python3 main.py
```

**NOTA:** Em modo headless, a interface gráfica não funcionará, mas os módulos de IA, voz e automação funcionam normalmente.

### Opção 3: Bootstrap Completo
```bash
python3 main_bootstrap.py
```

Este script prepara o ambiente e testa os imports antes de tentar iniciar o `main.py`.

## Modificações Necessárias no main.py

Para garantir inicialização completa no Linux, faça estas modificações no `main.py`:

### 1. Adicionar imports de compatibilidade no início
```python
# Logo após os imports padrão (queue, os, re, etc.)
import sys
from platform_compat import is_linux, is_windows

# Usar wrappers de compatibilidade
if is_linux():
    import compat_imports
    import automacao_compat as automacao
else:
    import automacao
```

### 2. Substituir imports problemáticos
```python
# Substituir:
# import keyboard
# import pyperclip

# Por:
if is_linux():
    from compat_imports import keyboard, pyperclip
else:
    import keyboard
    import pyperclip
```

### 3. Tratamento de erro na interface
```python
# O main.py já tem fallback de interface web → Qt
# Mas adicione tratamento para modo headless:
try:
    import interface_web as interface
except Exception as _erro_ui:
    print(f"[MAIN] Interface web indisponível: {_erro_ui}")
    print("[MAIN] Tentando interface Qt...")
    try:
        import interface
    except Exception as _erro_qt:
        print(f"[MAIN] Interface Qt também indisponível: {_erro_qt}")
        print("[MAIN] ERRO: Nenhuma interface disponível!")
        print("[MAIN] Instale: pip install pywebview ou pip install PyQt6")
        sys.exit(1)
```

## Problemas Conhecidos

### 1. Display X11 em modo headless
**Sintoma:** `Can't connect to display ":0"`

**Solução:** 
- Se rodar via SSH: use `DISPLAY=:0` ou `xvfb-run python3 main.py`
- Se rodar localmente: garanta que o servidor X11 está rodando

### 2. PyAudio em ambientes sem áudio
**Sintoma:** `No Default Output Device Available`

**Solução:** 
- Instale PulseAudio: `sudo dnf install pulseaudio`
- Ou use áudio dummy: `pactl load-module module-null-sink`

### 3. Keyboard/Mouse simulação requer X11
**Sintoma:** `xdotool` falha sem display

**Solução:** 
- Em modo headless, funcionalidades de automação visual não funcionarão
- Use `xvfb-run` para criar display virtual

## Verificação de Dependências

Execute o teste de dependências:

```bash
python3 -c "from automacao_linux import verificar_dependencias; deps = verificar_dependencias(); print('\\n'.join(f'{k}: {v}' for k,v in deps.items()))"
```

## Próximos Passos

1. **Execute o teste:** `python3 testes_manuais/test_emily_init.py`
2. **Corrija dependências faltantes** conforme reportado
3. **Modifique main.py** com os imports de compatibilidade
4. **Inicie a Emily:** `python3 main.py`

## Suporte

Se encontrar erros, verifique:
1. Todas as dependências do sistema estão instaladas
2. Todas as dependências Python estão instaladas
3. O `test_emily_init.py` passou sem erros críticos
4. O arquivo `.env` existe e tem as chaves de API necessárias

## Estrutura de Arquivos Novos

```
minha-ia/
├── platform_compat.py      # Detecção de plataforma
├── terminal_linux.py        # Terminal para Linux
├── automacao_linux.py       # Automação Linux
├── compat_imports.py        # Compatibilidade de imports
├── automacao_compat.py      # Wrapper de automação
├── voz_compat.py           # Wrapper de voz
├── testes_manuais/test_emily_init.py  # Script de teste
├── main_bootstrap.py       # Bootstrap de inicialização
└── LINUX_README.md         # Este arquivo
```

---

**Status Final:** ✅ Emily está pronta para inicializar no Linux com as modificações acima!
