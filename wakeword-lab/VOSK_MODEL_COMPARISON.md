# Comparação isolada de modelos Vosk — 2026-10-04

## Decisão

Manter o modelo atual no Android. O modelo de 128 MB aumentou a detecção de chamadas sintéticas, mas também os disparos indevidos e o custo de processamento. O segundo modelo intermediário reduziu confusões com “Emília”, porém perdeu uma chamada real do usuário. Nenhum demonstrou uma melhora consistente suficiente para substituir o atual.

Não foram alterados os assets, os limiares ou a instalação da Emily. Não houve gasto nem envio de gravações pessoais a serviços externos.

## Comparação com exatamente as mesmas amostras reservadas

156 clipes: 57 chamadas sintéticas, 96 negativos e 3 chamadas pessoais (normal, rápida e baixa). Os clipes marcados como `training` nos bancos anteriores foram excluídos desta tabela.

| Modelo | Chamadas sintéticas aceitas | Negativos aceitos indevidamente | Chamadas pessoais aceitas | Tempo de processamento no PC | Pico de memória do processo |
|---|---:|---:|---:|---:|---:|
| Atual: small-en-us-0.15 | 36/57 | 6/96 | 2/3 | 23,1 s | 283 MiB |
| en-us-0.22-lgraph (128 MB) | 42/57 | 7/96 | 2/3 | 129,7 s | 478 MiB |
| daanzu-20200905-lgraph (129 MB) | 36/57 | 3/96 | 1/3 | 89,4 s | 356 MiB |

Os seis negativos aceitos pelo atual eram “Ei, Emília.”. O modelo de 128 MB aceitou esses seis e também “A Emily é uma assistente.”. O Daanzu aceitou três chamadas “Ei, Emília.”. Esses números não devem ser interpretados como uma taxa de falsos positivos em conversas comuns.

O atual e o de 128 MB reconheceram a chamada normal e a baixa, mas não a rápida. O Daanzu reconheceu somente a baixa. Nas chamadas rápidas, os dois primeiros modelos perderam o prefixo; relaxar apenas a confiança não recupera uma palavra ausente.

## Ensaio completo do atual e do modelo de 128 MB

388 clipes, aproximadamente 20,4 minutos de áudio original: 156 positivos sintéticos, 229 negativos e 3 positivos pessoais.

- Atual: 97/156 positivos sintéticos; 18/229 negativos aceitos; 2/3 pessoais.
- 128 MB: 103/156 positivos sintéticos; 28/229 negativos aceitos; 2/3 pessoais.
- Atual: 17 confusões com “Ei, Emília.” e uma com “Emily.”.
- 128 MB: 26 confusões com “Ei, Emília.”, uma com “Ei, amigo.” e uma com “A Emily é uma assistente.”.
- Excluindo os 32 negativos com “Ei, Emília.”: atual 1/197; 128 MB 2/197.

O segundo modelo foi testado apenas nas amostras reservadas. Como perdeu uma chamada pessoal e não melhorou a detecção sintética nesse conjunto, não foi necessário repetir os 232 clipes restantes.

## Método e limites

`compare_vosk.py` usa um reconhecedor novo por clipe, a mesma gramática `["hey emily", "[unk]"]` e o avaliador de candidatos equivalente ao modo padrão do Android: confiança do prefixo 0,85; confiança do nome 0,70; duração mínima do nome 0,27 s, com verificações de ordem, duração, intervalo e quantidade de palavras. Cada endpoint é avaliado separadamente. Todos os modelos recebem os mesmos 320 ms de silêncio inicial e 1,3 s final. Os bancos sintéticos têm hashes verificados e áudios duplicados são removidos.

- Vosk Python 0.3.45; o Android utiliza 0.3.47.
- CPU e memória medidas no PC, sob carga variável; não são benchmarks de bateria, latência ou memória do celular. A memória inclui Python, bibliotecas e dados do processo.
- O pipeline de microfone, VAD e modo rápido do Android não foi reproduzido. As medições não comprovam desempenho em uso contínuo.
- Cinco das 24 chamadas do piloto Qwen têm alertas de transcrição/pronúncia. Resultados sintéticos não equivalem a validação com pessoas e sotaques reais.
- Não se pode estimar falsos disparos por hora a partir deste corpus.
- A adição posterior de timestamps de endpoint não altera decisões, mas o relatório inicial do baseline não os possui; eles não foram usados para comparar latência de detecção.

Foi explorada uma grade de 36 combinações de confiança/duração exclusivamente na partição antiga `training`. As amostras pessoais e as reservadas não foram usadas para escolher limiares. A exploração não corrigiu o equilíbrio entre detecção e confusões do modelo de 128 MB; nenhum limiar foi aplicado ao app.

## Proveniência

Catálogo oficial: https://alphacephei.com/vosk/models

- Atual: assets existentes `../EmilyAPP2/app/src/main/assets/model-en-us`, README identifica small-en-us-0.15; cerca de 68 MB extraídos.
- 128 MB: https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip
  - SHA-256: `d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334`
  - 130.557.655 bytes de ZIP; 214.028.616 bytes extraídos; licença Apache 2.0 no catálogo.
- 129 MB: https://alphacephei.com/vosk/models/vosk-model-en-us-daanzu-20200905-lgraph.zip
  - SHA-256: `c1b52c219845fbd6ee51101395a2d9842bbfa1c43ce81b233c671039b508ecf2`
  - Licença AGPL no catálogo; usado somente no laboratório, sem redistribuição.

Os ZIPs foram verificados e extraídos com validação de caminhos. Resultados e modelos ficam em `work/vosk-comparison/`, que não faz parte do pacote público.

## Próximo passo e o que não foi feito

Não baixar modelos de 1,8 GB ou maiores neste PC com pouca RAM livre. Modelos grandes de reconhecimento geral também precisam de orçamento de memória/CPU adequado ao Android e não oferecem garantia de melhor detecção de wake word.

A alternativa mais útil é investigar os casos de prefixo perdido e as confusões com nomes semelhantes no pipeline atual, mantendo avaliação separada e os mesmos exemplos para comparar. Isso deve ser uma nova etapa controlada; os resultados deste ensaio não autorizam afrouxar o detector em produção.
