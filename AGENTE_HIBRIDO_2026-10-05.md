# Agente visual com ferramentas e checkpoints

## Correções

O executor já aceitava a ação ferramenta, mas o prompt não recebia catálogo/schema e a saída de sucesso era descartada. Agora o catálogo geral real entra na decisão, outros domínios são carregados por abrir_ferramentas e os resultados completos (limitados a 6 KB por chamada) ficam disponíveis nos passos seguintes. Verificações de clique não carregam esse catálogo. Sessões visuais recursivas e modos que disputam o desktop são excluídos.

O agente usa pesquisa, terminal, arquivos, extração e navegador junto com mouse/teclado, sempre dentro do objetivo. Perguntas usam o cartão existente no PC e a ponte com o Android. Respostas livres são distintas de confirmações sensíveis. Flags de autorização do terminal vindas do modelo são removidas; confirmação real se aplica ao mesmo comando. Cancelamento do terminal atinge o processo da própria tarefa.

## Limites

- Padrão: 100 passos por janela e checkpoint de 15 minutos de tempo ativo, renováveis com progresso recente. O objetivo e o histórico continuam na mesma sessão.
- Esperas por ferramentas, perguntas e pausas são descontadas, inclusive quando sobrepostas.
- Ações visuais contam como progresso após mudança da captura; a mudança ainda precisa ser interpretada e validada. Uma captura diferente não é prova de conclusão.
- Após 3 minutos sem progresso, cinco falhas/loops consecutivos, falta de progresso no checkpoint ou três auditorias finais sem prova, o modo adaptativo pede orientação antes de continuar.
- Limites explícitos continuam disponíveis com renovar_limites=False ou EMILY_AGENTE_UI_RENOVAR_LIMITES=0.
- Sucesso gráfico exige prova na tela; objetivos sem interface podem ser comprovados por ferramentas. Downloads iniciados/comandos apenas enviados não bastam.

## Verificação e instalação

- 111 testes Python passaram (agente, navegador, cursor, ferramentas, voz e terminal); inclui ZIP real, cancelamento real de shell e resposta pela ponte.
- 159 testes Android JVM passaram e APK 52 compilado/publicado na Oracle com hash validado.
- Modelo real extraiu ZIP temporário, verificou manifest.txt pelo terminal e concluiu em três passos, com auditoria final. Registro: benchmarks/agente_hibrido_2026-10-05.json.
- Executável PyInstaller real testado com extração, terminal, catálogo e renovação de passos. Ensaio isolado usa a configuração privada da instalação em diretório temporário protegido, removido ao terminar.
- Overrides instalados em dist/Emily/_internal; Emily reiniciada normalmente com agente parado. Endpoint autenticado confirmou pronta, 100 passos e protocolo de perguntas.
- Hashes dos seis módulos alterados conferidos na versão ativa da Oracle.

## Não alterado / não validado

Lumafly e mods reais não foram instalados: o pedido foi corrigir o agente e não especificou qual mod instalar. A validação usou uma pasta temporária. Não houve teste físico do Android 52 nem instalação por USB, pois nenhum aparelho estava conectado; atualização está disponível pelo app. Não foram alteradas as permissões, o tema quente, a voz ou a wake word do celular.
