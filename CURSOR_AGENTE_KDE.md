# Cursor da Emily no KDE

O agente visual usa temporariamente o tema Emily_Warm (laranja), derivado do Breeze Light instalado. Mantém os hotspots, tamanhos e animações existentes. Mouse e teclado seguem sendo os dispositivos normais da sessão.

A integração central em agente_ui.py atende a interface do PC e aos pedidos remotos que executam esse agente no PC. Não exige alteração do Android. A ativação ocorre durante a sessão ativa, incluindo análise; pausa, confirmação humana, cancelamento e estados finais devolvem o cursor original.

O módulo cursor_agente.py preserva o tema e tamanho anteriores, inclusive tamanho implícito, e respeita uma troca manual de tema durante a tarefa. Um lock entre processos evita salvar o cursor temporário como original. O vigia separado restaura após saída abrupta, inclusive SIGKILL. Se a ferramenta do KDE falhar, mantém o registro para recuperação posterior e o agente continua funcionando. O ambiente das ferramentas externas remove bibliotecas do PyInstaller.

Corrigida também a possibilidade de iniciar outra sessão no callback de conclusão antes de finalizar a limpeza da sessão anterior.

## Verificação em 2026-10-05

- 66 testes passaram: cursor, agente visual, interface web e navegador.
- KDE real: troca de tema, restauração do tema/tamanho, pausa, retomada e cancelamento.
- Processo separado morto com SIGKILL: vigia restaurou os valores originais.
- Executável PyInstaller real: importou os módulos, aplicou/restaurou o tema e concluiu sessão com backend de teste.
- Overrides instalados em dist/Emily/_internal, usados pelo atalho do PC.

## Fora desta alteração

Não foi criada seleção/importação de pacotes personalizados de cursor: o padrão é o tema quente. O Windows e outros ambientes gráficos não receberam alteração de cursor; esta implementação atende ao KDE usado neste PC.
