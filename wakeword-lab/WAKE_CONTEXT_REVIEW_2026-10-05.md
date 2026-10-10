# Wake word Emily — investigação de falsos disparos

## Situação

O usuário relata ativações frequentes em conversas espontâneas, inclusive sem dizer o nome. No aparelho conectado, `modo_rapido=false`: o caminho efetivo é o SpeechService/Vosk padrão. Nenhuma gravação do microfone foi iniciada durante esta investigação.

A gramática atual contém `emily`, `hey emily` e `[unk]`. A confiança da palavra dentro desse vocabulário limitado não mede, por si só, a intenção de chamar a assistente. O modo padrão rejeita palavras adicionais reconhecidas no mesmo endpoint, mas não verifica o início real da fala em PCM; o modo rápido já passa o início do candidato ao avaliador. Isso é uma possibilidade a testar, não a causa comprovada de todos os relatos.

## Reprodução e experimento local

156 clipes reservados (validation/testing) do corpus anterior. Rótulos de `Emily.` foram atualizados de negativo para positivo somente na avaliação: antes o prefixo Ei era obrigatório, agora não é. As três chamadas pessoais existentes são gravações antigas de Ei Emily (normal, rápida, baixa). Os áudios não foram enviados a serviços externos.

Política padrão atual: confiança mínima 0,70; nome com ao menos 0,18 s; prefixo opcional; regras de ordem, intervalo e duração equivalentes ao avaliador Kotlin. As decisões abaixo foram recalculadas por `analyze_wake_context.py`, não dependem da aceitação simplificada nos caches de replay.

| Grupo | Total | Atual aceita | Com confirmação por ASR geral |
|---|---:|---:|---:|
| Chamadas válidas | 81 | 74 | 50 |
| Não chamadas | 75 | 7 | 0 |
| Chamadas pessoais (incluídas acima) | 3 | 3 | 0 |

A segunda passagem usa o mesmo modelo small-en-us-0.15 sem gramática restrita, exigindo reconhecimento independente de emily com confiança 0,70 e sobreposição temporal com a palavra candidata. **Alternativa descartada**: elimina falsos disparos neste conjunto, mas perde as três chamadas pessoais e 24 chamadas aceitas anteriormente. Não foi aplicada ao Android.

Falso disparo reproduzido: o áudio sintético “E aí, como você está?” gera primeiro um endpoint emily com confiança 1,0 (1,77–2,16 s) e depois um endpoint [unk]. O app padrão ativa no primeiro endpoint. Os demais seis negativos aceitos são chamadas sintéticas de Emília. O corpus não contém a conversa espontânea sobre vagas relatada pelo usuário e não permite calcular falsos disparos por hora.

## Testes e reprodução

Seis testes do analisador passaram, incluindo rótulos atuais, regras de chamada, alinhamento temporal da confirmação, detecção explícita de chamadas pessoais perdidas e rejeição de comparações entre corpus diferentes.

```
wakeword-lab/.venv/bin/python -m unittest discover -s wakeword-lab -p test_analyze_wake_context.py -v
wakeword-lab/.venv/bin/python wakeword-lab/analyze_wake_context.py --baseline wakeword-lab/work/wake-context-current.json --full wakeword-lab/work/wake-context-full.json --output wakeword-lab/work/wake-context-comparison.json
```

Caches locais em `work/` contêm resultados do reconhecimento; não incluem cópias de áudios. São diagnóstico local, não pacote publicado.

## Próximo passo e limitações

O usuário vai enviar gravação com conversas parecidas com o falso disparo e várias chamadas naturais do nome, separando os grupos com silêncio. Esse material é necessário para testar rejeição de conversa e preservação das chamadas. Manter exemplos separados para avaliação; não ajustar parâmetros só para passar nas mesmas amostras usadas para escolher o filtro.

Não foram alterados APK, versão, limiar, modelo, permissões, assistente padrão ou tema. Nenhuma atualização foi publicada ou instalada para esta investigação. A escolha de outro detector/modelo ou de filtro contextual precisa demonstrar resultado nas novas amostras antes de mexer no comportamento que o usuário considerou bom. Identificar intenção em uma menção isolada idêntica ao chamado pode continuar ambíguo; não prometer ausência total de falsos positivos.

## Referências consultadas

- Diagnóstico oficial Vosk: https://alphacephei.com/vosk/accuracy
- Captura/endpoint do SpeechService: https://github.com/alphacep/vosk-api/blob/master/android/lib/src/main/java/org/vosk/android/SpeechService.java


## Implementação posterior aos quatro áudios pessoais

O filtro aplicado ao modo padrão usa apenas flags locais de fala e energia: verifica fala contínua antes do nome e continuação depois do nome (janela até 600 ms após o término, com margem de 120 ms). Mantém o limiar de 0,70 e duração mínima de 0,18 s. O modo rápido mantém suas regras, pois aceita comandos na mesma fala. Não há segundo modelo nem envio das gravações à rede.

Replay da classe Kotlin real: preservou todas as 93 chamadas que o baseline aceitou (74 do corpus e 19 dos áudios novos). Dos sete falsos disparos do corpus, rejeitou “E aí, como você está?”; seis chamadas sintéticas de Emília continuam ambíguas. As duas conversas pessoais tiveram zero disparos no baseline contínuo, portanto não demonstram redução da frequência relatada em uso real. A gravação distante tem oito chamadas; o baseline do PC aceita sete. Não foi reduzido o limiar do prefixo fraco para recuperar a oitava, pois ampliaria aceitação durante a investigação dos falsos positivos. A espera adicional no replay foi de 20–200 ms.

Android usa Vosk 0.3.47 e PC 0.3.45: o replay nativo do celular aceitou 11 das 12 chamadas próximas, tanto antes quanto depois do filtro. A validação deve comparar as duas políticas no mesmo runtime, sem atribuir essa diferença ao filtro.

O usuário confirmou que usa Forçar parada para interromper a escuta. Logs às 21:34:22 mostram a ação nas configurações do Android e remoção imediata do assistente; no Android 12 o papel de assistente também concede SYSTEM_ALERT_WINDOW. Foi acrescentado controle persistente “Ouvir chamadas de Emily” nas configurações de voz e “Pausar escuta” na notificação. Desligar libera microfone, modelo e wake lock, mantém o vínculo de assistente e não é revertido por reabrir o app, RESUME de uma conversa ou boot. Conversas manuais e avisos solicitados seguem seus próprios fluxos.

A instalação normal da versão 53 preservou o papel de assistente e overlay. O teste de instrumentação força a parada por desenho do runner; restaure a escolha confirmada pelo usuário ao terminar. 168 testes JVM passaram. Resultados finais no aparelho e publicação são registrados ao concluir a validação.

Fontes da remoção do papel e concessão do overlay:
- https://android.googlesource.com/platform/frameworks/base/+/android-12.0.0_r1/services/voiceinteraction/java/com/android/server/voiceinteraction/VoiceInteractionManagerService.java
- https://android.googlesource.com/platform/packages/modules/Permission/+/android-12.0.0_r1/PermissionController/res/xml/roles.xml


## Validação final

168 testes JVM passaram após a correção da disputa entre comandos atrasados de OFF/ON. No aparelho, passaram o contrato de atualização, reprodução acústica e pausa persistente: 11/11 chamadas próximas aceitas pelo baseline preservadas, 7/7 distantes preservadas; ambas as conversas tiveram 0/0; o falso “E aí…” foi 1 no baseline e 0 com o filtro. Pausa mantém papel e overlay, não é revertida pelo RESUME de conversas nem reabertura, e permite recarregar o modelo ao reativar. O runner Android exige início explícito da escuta durante instrumentação; restaurado o vínculo do assistente após finalizar. Os cinco PCM temporários copiados ao cache do telefone foram removidos; originais do usuário preservados. Versão 53 instalada com dados preservados.
