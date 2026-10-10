# Experimento de estabilidade v3 — 2026-10-04

## Critério de adoção

O Android só deve receber um detector com melhora clara sobre o Vosk atual: reconhecimento de chamadas completas, rejeição de menções/nome isolado, estabilidade contínua, latência e consumo aceitáveis. Passar em testes sintéticos ou nas três chamadas pessoais não basta. Este experimento não autoriza instalar nada.

## Diagnóstico do ZIP de validação v2

Recebido `ei-emily-v2-validation-details.zip`, extraído com validação de caminhos e limites, 96 arquivos / 19.103.608 bytes. Características: 216 chamadas e 468 negativos, correspondentes ao manifesto recebido.

Melhor checkpoint pela perda da última janela: passo 2500, perda 0,2512, recall 95,37%, precisão 80,78%, AUC 0,9675. No passo 6000 a perda subiu para 0,4055 e recall caiu para 61,11%. Essas métricas não medem o filtro contínuo de cinco saídas usado na análise do detector.

Em janelas float de sequência já estabilizada, o checkpoint original alcançou apenas 9,72% de recall no melhor limiar com FPR por exemplo até 1% (0,85% observado). Compartilhar diretamente os pesos temporais da camada final reduziu o recall a 2,31% com o mesmo limite. Esse atalho foi descartado. Esses números excluem a inicialização e não substituem o relatório quantizado de sequência completa, que também reprovou o v2.

O alinhamento offline/streaming do original apresentou erro máximo de 3,6e-7. A hipótese de perda importante na conversão não foi confirmada; a posição temporal da chamada e a duração do pico continuam relevantes. Isso não prova uma única causa nem garante que pooling resolva.

Referência local Vosk 0.3.45 com modelo inglês do Android: aceitou uma das três chamadas pessoais. Não reproduz integralmente o VAD e a versão 0.3.47 do Android; portanto não constitui comparação final no aparelho.

## Comparação controlada preparada

`refine_streaming.py` reaproveita exclusivamente características de treino, pesos v2 e a validação existentes no Colab. Duas variantes recebem os mesmos exemplos e seed:

1. Arquitetura original com ajuste adicional.
2. Mesma base com média temporal antes da camada final, seguida de ajuste obrigatório.

Cada variante executa 1500 passos: aquecimento da camada final, depois ajuste da base. Reforço de negativos contendo nomes/menções, recortes negativos variados e variação positiva conservadora de até 30 ms (o gerador v2 adiciona pelo menos 60 ms de silêncio final). Não rotulamos janelas arbitrárias contendo apenas parte da chamada como positivas.

Checkpoints são escolhidos pela validação em sequência, usando a média de cinco saídas e recall dentro de até 1% de FPR por exemplo; não pela perda da última janela. Essa seleção float considera apenas janelas já estabilizadas. A avaliação final independente usa TFLite quantizado, sequências completas **incluindo inicialização**, recalibra somente pela validação e aplica o limiar às vozes de teste. Não reduzir o filtro ou ocultar a inicialização para aprovar um modelo.

O conjunto de teste não participa do ajuste nem da escolha de checkpoint; foi observado em relatórios anteriores, então não é um novo teste externo. O áudio pessoal fica fora do Colab/treinamento. Original e dados permanecem preservados; resultados usam pasta nova. Sem geração de vozes, instalação de dependências ou alteração do APK.

## Execução na sessão aberta

1. Abra `refine-colab-cell.py`, copie todo o conteúdo para uma célula nova do notebook existente.
2. Execute apenas essa célula. No upload, selecione `ei-emily-v3-refinement-tools.zip`.
3. Devolva o ZIP `work-v3-streaming-<data-hora>.zip` baixado ao final.

O pacote de ferramentas tem hash verificado antes de extrair/executar os quatro arquivos previstos. O runner exige GPU detectável pelo ambiente Python 3.11 existente. Não inicia pagamento ou usa Drive. Se o runtime antigo desaparecer, essas instruções param em vez de gerar novamente 28 mil exemplos sem aviso. Se interromper, uma nova execução usa outra pasta e não apaga resultados anteriores.

## Verificado localmente

- 24 testes automatizados passaram (20 existentes + 4 novos).
- Duas variantes realmente treinaram no corpus piloto local (2 passos cada, somente teste de execução).
- Variante com pooling convertida em SavedModel e TFLite quantizado de 34.512 bytes; avaliação completa executou e rejeitou corretamente o modelo piloto.
- Paridade offline/streaming da variante com pooling: erro máximo 5,96e-8.
- Célula Colab compilada e pacote gerado com hash.

Treino de 1500 passos na T4 e ganho real ainda **não verificados**. Os testes locais comprovam execução/conversão, não qualidade do futuro detector.

**Não alterados:** Android/Vosk, sensibilidade do celular, instalação atual da Emily, pesos recebidos e gravação privada. O v2 ainda não atende à exigência do usuário. Conversas reais longas, outros falantes reais e desempenho/bateria no aparelho continuam pendentes antes da adoção.
