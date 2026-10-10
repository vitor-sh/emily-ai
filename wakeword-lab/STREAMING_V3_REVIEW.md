# Revisão dos modelos v3 — 2026-10-04

## Decisão

**Nenhuma das duas variantes está aprovada para substituir o Vosk no Android.** O objetivo é uma melhora clara no uso real. O v3 reduziu respostas a alguns negativos sintéticos, mas também perdeu chamadas legítimas, incluindo as três chamadas pessoais reservadas à avaliação.

## Integridade e execução

Arquivo recebido: `work-v3-streaming-20261004-191125.zip`, 27 arquivos, 24.226.740 bytes descompactados. Extração limitada, com rejeição de caminhos inseguros, duplicatas e links simbólicos. Nenhum script do pacote foi executado.

Os hashes do script de treino, manifesto e pesos de origem conferem com o experimento preparado localmente. Ambas as variantes completaram 1500 passos. Modelos quantizados conferidos:

- Original refinado: SHA-256 `58f3b86bd3a2a004ac5777a30156c598f2e27651462ca96fb5959a68e7bb12e5`, 35.280 bytes.
- Média temporal refinada: SHA-256 `349560d6dbac1a431af6bd299695f86f77a4af593eb983b5b0ca0176617c418b`, 34.584 bytes.

Os relatórios foram recalculados a partir das pontuações fornecidas; os limiares são escolhidos somente pela validação, não pela gravação pessoal nem pelo teste.

## Resultado da avaliação quantizada completa

| Variante | Limiar | Chamadas reconhecidas na validação | Negativos aceitos na validação | Chamadas reconhecidas no teste | Negativos aceitos no teste |
|---|---:|---:|---:|---:|---:|
| Original refinado | >0,96484375 | 45/216 (20,83%) | 4/468 (0,85%) | 96/288 (33,33%) | 0/624 |
| Média temporal refinada | >0,915625 | 42/216 (19,44%) | 3/468 (0,64%) | 88/288 (30,56%) | 0/624 |

FPR é por exemplo sintético; **não é taxa de falsos acionamentos por hora**. Zero aceitações nesses 624 negativos não demonstra zero falsos positivos em conversas reais.

Nos dois perfis de teste classificados como nativos PT-BR, ambas as variantes reconheceram apenas **6/144 chamadas (4,17%)**. Faber, perfil brasileiro da validação, teve 0/72. O resultado médio favorece perfis estrangeiros sintetizados com fonemas portugueses; o total de 32 perfis não comprova generalização para brasileiros.

O relatório automático usa `experimental_not_for_installation` quando existe algum reconhecimento dentro do limite sintético de FPR. Esse rótulo **não significa qualidade suficiente nem aprovação**. O reconhecimento continua baixo para o objetivo do usuário.

## Comparação local com a gravação pessoal

As três chamadas foram segmentadas exatamente como na análise anterior, com três segundos de contexto silencioso. Modelos novos avaliados em SavedModel float e TFLite quantizado, com o microfrontend de referência e média de cinco saídas. A gravação não foi enviada ao Colab nem usada no ajuste.

| Chamada | Original refinado, pico quantizado após contexto | Média temporal, pico quantizado após contexto |
|---|---:|---:|
| Normal | 0,0680 | 0,0828 |
| Rápida | 0,9453 | 0,7766 |
| Baixa | 0,5922 | 0,3445 |

Nenhuma supera o limiar selecionado na validação: **0/3 nas duas variantes**. A referência Vosk local anterior aceitou 1/3; a biblioteca local é 0.3.45, enquanto o Android usa 0.3.47 e VAD próprio. Não é uma comparação completa no aparelho, mas os novos modelos não demonstram sequer melhora nessas amostras disponíveis.

As pontuações não são probabilidades calibradas ou porcentagens de acerto. Não reduzir o limiar para encaixar essas três chamadas: isso seria calibração na gravação pessoal e aumentaria falsos positivos.

## O que o ajuste conseguiu e o que perdeu

Nos três exemplos locais de “Emily” isolada, o original v2 teve picos de 0,71/0,73/0,53. O original refinado caiu para 0,35/0,28/0,02; o modelo com média temporal para 0,19/0,14/0,04. Há evidência de rejeição melhor nesses exemplos, acompanhada de perda severa em chamadas legítimas.

Silêncio puro ficou baixo após estabilização. A diferença float/quantizado não explica a perda principal nas chamadas normais: ambos os formatos já apresentam pontuação baixa. A chamada rápida com pooling tem diferença adicional de quantização (pico float 0,8307 e quantizado 0,7766), mas ambos ficam abaixo do limiar.

A seleção em janelas float estabilizadas aumentou o recall de 9,72% para 34,72% no original e de 2,31% para 36,11% com pooling. Esse ganho intermediário não se traduziu em um detector aprovado na avaliação quantizada completa nem na gravação pessoal. Não atribuir toda a diferença a inicialização ou conversão sem um diagnóstico completo.

## Próximo caminho recomendado

Antes de pedir outro treino, auditar a pronúncia e diversidade efetiva dos positivos PT-BR e revisar a distribuição entre chamadas completas e negativos difíceis. Repetir somente mais passos ou reforçar a mesma penalização negativa não mostrou benefício suficiente.

Também falta uma base de conversas/sons reais para treinamento e avaliação de falsos acionamentos por hora, respeitando as licenças. A documentação oficial do microWakeWord prevê corpora de fala/sons ambientes separados dos exemplos sintéticos e avaliação streaming em áudio longo:

https://github.com/kahrendt/microWakeWord/blob/main/documentation/data_sources.md
https://github.com/kahrendt/microWakeWord

Usar dados públicos adequados pode reduzir a necessidade de coleta manual, mas não substitui a validação final com falantes reais. Não foi escolhido nem baixado um novo corpus nesta revisão; ainda é necessário verificar disponibilidade, português e permissões de redistribuição antes da próxima rodada.

## Verificação e preservação

Executadas 39 comparações locais (13 clipes × 3 modelos), nos formatos float e quantizado; calibração dos relatórios novos reproduzida. Evidências em `work/received-streaming-v3/local-review.json`; resultados recebidos preservados. Nenhuma alteração nos pesos.

**Não alterados:** APK, Vosk/sensibilidade do Android, instalação da Emily no PC, filtros de detecção e gravação privada. Motivo: os novos modelos não cumprem o objetivo. Não realizado teste de bateria/latência no aparelho porque ainda não há candidato com qualidade que justifique instalar. Não preparado outro treino às cegas com os mesmos dados, pois os resultados apontam a necessidade de revisar os dados e a distribuição primeiro.
