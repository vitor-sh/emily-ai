# Piloto Qwen de 12 perfis — 2026-10-04

## Integridade e geração

Recebido `work-source-pilot-12.zip`: 75 arquivos, 8.327.180 bytes descompactados. Extração isolada com limites de tamanho, validação de caminhos e rejeição de links. Verificados os hashes dos 60 WAVs e 12 embeddings. Não executado nenhum conteúdo do ZIP.

12 referências sintéticas, 24 chamadas positivas, 24 negativos (nome isolado e menção). Síntese registrada: 616,64 segundos, cerca de 10,3 minutos. Não inclui instalação/downloads/Whisper. A projeção linear para 200 perfis com as mesmas quatro frases é 2,85 horas de síntese; não garante duração total ou disponibilidade do Colab.

Whisper transcreveu o prefixo/nome conforme esperado em 19/24 positivos. Cinco alertas precisam de escuta humana; não representam cinco erros confirmados de pronúncia. Uma chamada tem 15,28 segundos de arquivo e só 1,94 segundos de atividade, com silêncio excessivo. Corrigida a auditoria estrutural para sinalizar silêncio inicial/final acima de um segundo e duração total de chamadas acima de quatro segundos. WAVs originais preservados; nenhuma chamada foi automaticamente cortada ou aprovada.

40/66 pares de embeddings excedem a heurística de similaridade 0,95. Não prova vozes duplicadas nem diversidade suficiente: o encoder e o texto comum podem influenciar a medida. Descrições de seis regiões não comprovam sotaques reais. A escuta humana ainda está pendente.

## Comparação dos detectores existentes

48 frases, estado reiniciado em cada áudio, contexto inicial de três segundos e um segundo final; médias de cinco saídas para microWakeWord. Limiares previamente escolhidos na validação dos candidatos, sem recalibrar no piloto.

| Detector | Chamadas aceitas | Negativos aceitos |
| --- | --- | --- |
| v2 quantizado | 0/24 | 0/24 |
| v3 original refinado quantizado | 0/24 | 0/24 |
| v3 pooled refinado quantizado | 0/24 | 0/24 |
| Vosk offline com regras de confiança/duração | 17/24 | 0/24 |

No subconjunto de 19 positivos sem alerta de ASR, microWakeWord permaneceu em 0/19 e Vosk em 13/19. Esse subconjunto não é confirmação humana de qualidade.

Vosk Python 0.3.45 versus Android 0.3.47: VAD ao vivo e o filtro de início relativo ao VAD não foram reproduzidos. A comparação é diagnóstico local, não certificação de desempenho Android. 24 negativos curtos são insuficientes para medir falsos acionamentos por hora.

Resultados completos: `work/received-source-pilot-12/detector-review.json`, `structural-review.json`. O piloto evidencia falha de generalização dos candidatos anteriores, não melhora do detector novo. Não baixar limiar para forçar sucesso, nem ampliar centenas de perfis antes da escuta e da avaliação de diversidade.

## Escuta e correções

A célula de reparo CUDA baixava o ZIP, mas não exibia os controles de áudio. Corrigida essa omissão. `preview-voice-source-colab-cell.py` apenas reproduz os áudios existentes, sem instalar ou gerar nada. Prévia local: `work/received-source-pilot-12/preview-12-calls.wav`; mantém todo o início e no mínimo um segundo após o último som detectável. Originais completos continuam em `listening.html`.

Notebook reconstruído usa nova pasta `work-source-pilot-12-audit2`, porque a alteração do script muda sua assinatura. Não reexecutar o notebook completo para ouvir o piloto recebido: usar a célula de prévia ou a página extraída. Sessões antigas e arquivos originais não foram modificados.

32 testes passaram. Scripts/células compilados; análises executadas sobre todos os WAVs e modelos quantizados. Geração nova na GPU não executada localmente.

## Próxima etapa e itens preservados

Confirmar pelo ouvido prefixo, naturalidade e diferenças entre vozes. Depois preparar banco maior com auditoria por amostra, negativos reais, divisão por referência de voz sem vazamento e revisão das janelas de treinamento. Melhorar diversidade é parte do caminho; não é garantia isolada de sucesso.

Não alterados: APK/detector Android atual, Emily PC, gravação pessoal, pesos v2/v3 e corpus de treinamento anterior. Nenhum candidato demonstrou a melhora exigida. Não iniciado treino massivo nem baixado Common Voice: qualidade/diversidade do piloto e acesso oficial a negativos reais ainda precisam ser resolvidos.
