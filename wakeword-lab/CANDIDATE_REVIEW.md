# Avaliação do primeiro treino Colab — 2026-10-04

## Resultado

**Candidato reprovado para instalação.** Os dois pacotes foram lidos sem executar código do ZIP. O TFLite dos dois pacotes coincide: 35.344 bytes, SHA-256 `4ae373e5bbdd9264ba69d0d78054e49e88e98870510f4c3693a38b3b7ea25b1c`.

Na avaliação recebida, validação e teste têm, cada um, 240 chamadas e 416 negativos. O limiar selecionado (0,95) rejeita todas as chamadas. Isso não é um detector funcional, mesmo com zero falsos positivos nesse limiar.

## Comparação entre formatos

Reconstruído MixedNet com a configuração do treino e os melhores pesos; executado também o SavedModel streaming original, com o microfrontend de referência e a mesma escala das características usadas no TFLite.

| Amostra sintética separada do treino | Float não streaming | Pico float streaming (média de 5 saídas) | Pico quantizado |
|---|---:|---:|---:|
| Chamada em voz de teste | 0,3503 | 0,5420 | aproximadamente 0,544 |
| Negativo “E me liga amanhã” | 0,2353 | 0,5421 | aproximadamente 0,544 |

O início com buffers vazios domina os picos dessas duas amostras. Desconsiderando as primeiras 25 saídas **somente para diagnóstico**, os picos float ainda ficam próximos: 0,4293 e 0,4333. Portanto, descartar a inicialização não basta para aprovar este candidato.

No áudio pessoal de avaliação, o pico float streaming foi 0,6235; o quantizado permaneceu próximo. Silêncio produziu pontuação quantizada aproximadamente 0,6523. Reduzir o limiar para aceitar chamadas pode aceitar silêncio e negativos. O áudio pessoal permanece privado e fora do notebook e do treinamento.

**Conclusão:** a conversão não explica o problema principal. Há baixa generalização no modelo original e uma limitação do avaliador, que usa o máximo de toda a sequência e inclui o transiente de inicialização.

## Registros do treino

O melhor checkpoint por loss é o passo 250: loss de validação 0,6263, recall 0,0042 e AUC 0,8177. No passo 3000: loss 3,2828, recall 0,0083 e AUC 0,6027. Aumentar os passos não é uma correção sustentada por esses registros.

A base possui somente duas vozes masculinas de treino, outra de validação e outra de teste. Usa ruído sintético leve, negativos curtos e não possui corpus de conversas longas ou negativos dedicados de silêncio. Esses fatores são hipóteses relevantes para a baixa generalização; esta comparação não isola uma causa única.

## Correções feitas na preparação

- Relatório reprova explicitamente candidatos sem recall, informa separação das classes e rejeita valores inválidos.
- O limiar continua escolhido só na validação, sem ajustar pela voz pessoal ou pela voz de teste.
- Próximos ZIPs incluem pesos e SavedModel por lista explícita de arquivos, permitindo comparar formatos sem pedir outro pacote. Não exportam áudio pessoal ou configurações da Emily.
- Treze testes automatizados passaram e as células do notebook foram compiladas.

## Trabalho necessário antes de outro treino e da integração

1. Ampliar falantes e pronúncias com vozes sintetizadas licenciadas, incluindo femininas, mantendo separação de falantes.
2. Incluir silêncio, ruído, frases parecidas e contextos de conversa; variar posicionamento das chamadas e duração dos negativos.
3. Avaliar detecção ao longo de sequências contínuas e a inicialização; medir recall e falsos acionamentos sem esconder os transientes.
4. Validar a revisão do pipeline em um treino pequeno antes de pedir outra execução completa no Colab.
5. Só depois comparar no Android, incluindo consumo e tela desligada.

O APK e o detector atual não foram alterados. Ainda não existe evidência de melhora deste microWakeWord sobre o detector atual nem medição confiável de falsos acionamentos por hora.
