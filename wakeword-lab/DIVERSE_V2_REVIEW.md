# Revisão do candidato diverso v2 — 2026-10-04

## Decisão

**Não instalar no Android.** O treinamento produziu 28.044 exemplos e 32 perfis, mas ainda não há limiar com reconhecimento útil e FPR por exemplo de validação até 1%. O resultado melhora sobre o primeiro candidato, sem alcançar o objetivo de substituir o detector.

Arquivo recebido: `ei-emily-diverse-v2-candidate.zip`. Extração com limites de tamanho, rejeição de caminhos absolutos, travessia e links simbólicos; nenhum código do ZIP foi executado. SHA-256 TFLite confirmado: `a5f6c7c4b3ccc6fcdda8563a0acd4f226bc6be81e25d5c463f3308e3a0dc6c0b`, 35.344 bytes.

## Avaliação recebida

| Conjunto | Chamadas | Negativos | Recall em 0,95 | FPR em 0,95 | Rank AUC |
|---|---:|---:|---:|---:|---:|
| Validação | 216 | 468 | 35,2% | 10,5% | 0,662 |
| Teste | 288 | 624 | 65,3% | 11,1% | 0,861 |

FPR é por exemplo sintético, **não falsos acionamentos por hora nem taxa esperada em uso real**. A diferença de desempenho entre perfis permanece grande. “Emily” sozinha acionou em 35,7% dos exemplos dessa frase em 0,95; “Ei, Emílio” em 32,1%. Silêncio puro local ficou baixo após estabilização, mas houve um negativo de background aceito no relatório recebido.

O calibrador foi corrigido para testar fronteiras reais da validação, incluindo valores acima de 0,95. Isso não aprovou o modelo: o único ponto aceitável para até 1% de FPR rejeita todas as chamadas. O conjunto de teste e a voz pessoal não foram usados para escolher limiar.

## Áudio pessoal, reservado à avaliação

Pontuações quantizadas com média de cinco saídas e três segundos de contexto silencioso antes de cada segmento:

| Chamada | Pontuação |
|---|---:|
| Normal | 0,8633 |
| Rápida | 0,9875 |
| Baixa | 0,8492 |

Essas pontuações **não são porcentagens de acerto ou probabilidades calibradas**. Em 0,95 só a rápida supera o limiar. Usar um limiar menor para aceitar as três também aumenta os falsos positivos; não calibramos pela gravação pessoal. O arquivo permanece local, fora do treinamento e do notebook.

## Conversão e estabilidade temporal

Comparados pesos originais, SavedModel streaming e TFLite com o mesmo microfrontend de referência. As pontuações float e quantizadas são próximas; há diferenças de quantização, mas elas não explicam a reprovação principal.

Uma chamada de Faber atingiu 0,8647 instantaneamente no streaming float, mas o pico da média de cinco saídas caiu para 0,4477. Esse exemplo sugere reconhecimento restrito a poucas posições temporais, insuficientemente estável para o filtro de detecção.

Na comparação entre janelas offline e streaming float, respeitando o stride e o quadro final não utilizado pela primeira convolução, o erro máximo foi **3,6 × 10⁻⁷**. Portanto, comparar apenas a última janela offline com o máximo da média streaming pode induzir um diagnóstico falso de erro na conversão. Neste teste alinhado, a conversão está correta.

## Próximo experimento

Investigar estabilidade e supervisão em janelas temporais variadas, reforçar rejeição do nome isolado e menções à Emily e selecionar checkpoints pela detecção em sequência. Não basta aumentar passos, baixar limiar ou reduzir a média indiscriminadamente. Se os dados ainda existirem no Colab, reutilizar características/áudios para reduzir tempo e custo de outra geração.

A escolha entre alteração da supervisão temporal e da arquitetura requer comparação controlada; esta revisão não afirma que uma dessas alterações já resolveu o problema. Ainda falta avaliação de conversas reais longas, falantes reais adicionais e integração Android.

## Verificação das alterações

20 testes automatizados passaram. Incluem a calibração de scores saturados acima de 0,95 e proteção contra escolha de limiar a partir do conjunto de teste. Notebook regenerado e células compiladas.

**Não alterados:** APK, detector atual, sensibilidade, média da detecção no celular e pesos recebidos. Motivo: o candidato ainda não cumpre a meta de falsos positivos, e mudanças nos filtros poderiam mascarar essa falha. Os artefatos recebidos foram preservados.
