#!/bin/bash
# Script de inicialização rápida da Emily no Linux

echo "================================"
echo "EMILY - Inicialização Linux"
echo "================================"
echo ""

# 1. Verificar se estamos no diretório correto
if [ ! -f "main.py" ]; then
    echo "❌ ERRO: Execute este script no diretório da Emily!"
    echo "   cd '/home/Hiucksam/My Projects/Projeto Emily/minha-ia'"
    exit 1
fi

echo "✓ Diretório correto"
echo ""

# 2. Testar imports básicos
echo "Testando módulos de compatibilidade..."
python3 -c "
import sys
sys.path.insert(0, '.')
import platform_compat
import compat_imports
import automacao_linux
print('✓ Módulos de compatibilidade OK')
" || {
    echo "❌ Erro ao carregar módulos de compatibilidade"
    exit 1
}

# 3. Executar teste completo
echo ""
echo "Executando teste completo de inicialização..."
python3 testes_manuais/test_emily_init.py

# 4. Resultado
if [ $? -eq 0 ]; then
    echo ""
    echo "================================"
    echo "✅ EMILY ESTÁ PRONTA!"
    echo "================================"
    echo ""
    echo "Para iniciar a Emily:"
    echo "  python3 main.py"
    echo ""
    echo "Nota: A interface gráfica requer DISPLAY configurado"
    echo "      Em ambiente headless, algumas funções visuais não funcionarão"
else
    echo ""
    echo "================================"
    echo "⚠️  HÁ PROBLEMAS A CORRIGIR"
    echo "================================"
    echo ""
    echo "Leia o output acima e corrija os erros reportados"
    echo "Consulte LINUX_README.md para detalhes"
fi
