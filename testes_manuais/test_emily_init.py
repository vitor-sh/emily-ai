#!/usr/bin/env python3
"""
Script de teste para verificar se a Emily consegue inicializar sem erros.

Este script testa os imports críticos e verifica se os módulos carregam corretamente.
"""

import _raiz  # noqa: F401,E402 - raiz do projeto como cwd e no sys.path
import sys
import os

# Desabilitar tentativas de conectar ao display X11
os.environ['MPLBACKEND'] = 'Agg'
os.environ['DISPLAY'] = ''

print("="*70)
print("TESTE DE INICIALIZAÇÃO DA EMILY - LINUX")
print("="*70)
print()

# Adicionar diretório atual ao path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ══════════════════════════════════════════════════════════════════════════════
# FASE 1: Testar camada de compatibilidade
# ══════════════════════════════════════════════════════════════════════════════

print("FASE 1: Testando camada de compatibilidade...")
print("-" * 70)

try:
    import platform_compat
    print("✓ platform_compat carregado")
    print(f"  Sistema: {platform_compat.get_os_name()}")
    print(f"  Linux: {platform_compat.is_linux()}")
    print(f"  Windows: {platform_compat.is_windows()}")
except Exception as e:
    print(f"✗ Erro ao carregar platform_compat: {e}")
    sys.exit(1)

try:
    import compat_imports
    print("✓ compat_imports carregado")
    print(f"  keyboard: {type(compat_imports.keyboard).__name__}")
    print(f"  pyperclip: {type(compat_imports.pyperclip).__name__}")
except Exception as e:
    print(f"✗ Erro ao carregar compat_imports: {e}")
    sys.exit(1)

try:
    import terminal
    print("✓ terminal carregado (portão de segurança)")
    print(f"  Shell: {terminal._SHELL or terminal._POWERSHELL}")
    nivel = terminal.classificar("ls -la")
    print(f"  classificação 'ls -la': {nivel}")
except Exception as e:
    print(f"✗ Erro ao carregar terminal: {e}")
    sys.exit(1)

print()

# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: Testar módulos principais da Emily
# ══════════════════════════════════════════════════════════════════════════════

print("FASE 2: Testando módulos principais da Emily...")
print("-" * 70)

modulos_testar = [
    ('memoria', True),
    ('modelo', True),
    ('visao', True),
    ('discord_bot', True),
    ('navegador', True),
    ('pesquisa', True),
    ('voz', False),  # Pode falhar sem display
]

modulos_ok = []
modulos_falha = []

for nome_modulo, critico in modulos_testar:
    try:
        __import__(nome_modulo)
        print(f"✓ {nome_modulo}")
        modulos_ok.append(nome_modulo)
    except Exception as e:
        erro_str = str(e)[:100]
        if critico:
            print(f"✗ {nome_modulo} (CRÍTICO): {erro_str}")
            modulos_falha.append((nome_modulo, str(e)))
        else:
            print(f"⚠ {nome_modulo} (não crítico): {erro_str}")

print()

# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: Relatório Final
# ══════════════════════════════════════════════════════════════════════════════

print("RELATÓRIO FINAL")
print("="*70)
print()

print(f"Módulos carregados com sucesso: {len(modulos_ok)}/{len(modulos_testar)}")
print(f"Módulos com falha: {len(modulos_falha)}")

print()

if modulos_falha:
    print("MÓDULOS COM FALHA (detalhes):")
    print("-" * 70)
    for mod, erro in modulos_falha:
        print(f"\n{mod}:")
        print(f"  {erro}")
    print()
    print("STATUS: FALHA - Corrija os erros acima antes de iniciar a Emily")
    sys.exit(1)
else:
    print("STATUS: SUCESSO ✓")
    print()
    print("A Emily está pronta para inicializar no Linux!")
    print()
    print("PRÓXIMOS PASSOS:")
    print("  1. Instale dependências faltantes (se houver avisos acima)")
    print("  2. Configure DISPLAY se quiser usar interface gráfica")
    print("  3. Execute: python3 main.py")
    print()
    print("NOTA: A interface gráfica requer servidor X11 rodando")
    print("      Se estiver sem display, a Emily pode rodar em modo headless")
    print()
    sys.exit(0)
