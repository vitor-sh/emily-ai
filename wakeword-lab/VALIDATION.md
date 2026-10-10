# Verificação técnica — 2026-10-04

Executado localmente em ambiente Python 3.11 separado da Emily, com uso de uma thread por biblioteca:

- 8 testes passaram: separação de falantes, presença das duas classes, licença não revisada, duplicação de voz, hash de áudio, alinhamento para quantização, escolha de métrica disponível e ausência de dados ambiente.
- Piper produziu 88 WAVs de quatro vozes brasileiras: 44 treino, 22 validação, 22 teste. O teste pequeno usa apenas duas variantes por frase positiva. Alguns modelos registram aviso de fonema nasal ausente; a pronúncia e a variedade das vozes precisam de revisão antes de um treino final.
- Características extraídas pelo microfrontend de referência do TensorFlow, mono PCM16 16 kHz, sem substituir por Mel comum.
- Treino de **20 passos somente para verificar o pipeline** concluído com exportação streaming quantizada: **35.344 bytes**.
- Inferência no artefato exportado executada em validação e teste com estado novo por arquivo. Saturação int8 e zero point conferidos com valores extremos.
- Notebook gerado com lista explícita de arquivos; suas células compilam como Python válido. Não contém caminhos pessoais, áudio privado ou configuração de API da Emily.

**Não é evidência de melhora na detecção.** O modelo de 20 passos teve recall zero no limiar selecionado e foi reprovado para uso. É esperado que um teste técnico tão curto não produza um detector treinado; o relatório identifica o artefato como `experimental_not_for_installation`, com `synthetic_only`. Não há medições reais de falsos acionamentos por hora, bateria ou latência Android.

Não foi alterado nem reinstalado o APK da Emily. O próximo passo é executar o treinamento maior no Colab e avaliar o resultado, ampliar diversidade de vozes e dados ambiente, antes de integrar ao serviço Android.

Compatibilidade corrigida durante a verificação: instalação editável do upstream para incluir `audio`/`layers`; atualização isolada de `attrs`; escolha de métrica realmente retornada pelo commit fixado; duração alinhada ao stride de quantização; bloqueio da retomada de checkpoint incompatível; ROC ambiente não exibida sem corpus real.

## Correção do bootstrap do Colab

Após relato do kernel Python 3.13, confirmada ausência de wheels CPython 3.13 nas versões fixadas de NumPy 2.0.2 e TensorFlow 2.18.1. O bootstrap agora cria um Python 3.11 gerenciado e ambiente virtual independente do kernel. Testado a partir de Python 3.14: baixou Python 3.11.13 e criou o ambiente com pip; a resolução das dependências neste interpretador também passou. Nove testes passaram, incluindo preservação de stderr e log legível em falha de instalação. Notebook regenerado e células verificadas por compilação.

CUDA é instalada no ambiente de treino quando há `nvidia-smi`, e a GPU reconhecida é impressa. Não há GPU neste PC: a execução completa na T4 do Colab ainda depende de confirmação no ambiente do usuário. Não foi modificado o APK nem treinado um novo detector nesta correção.


## Segunda rodada: diversidade Piper + Kokoro

- Configuração ampliada de quatro para **32 perfis**: quatro Piper e 28 Kokoro; sete perfis brasileiros no total, outros 25 sintetizados com fonemas pt-br. Perfis não comprovam falantes reais independentes. Inclui femininos nos três conjuntos.
- Preset completo planejado: **28.044 WAVs**, 25 perfis de treino, três de validação e quatro de teste; 36 frases negativas, silêncio e ruído dedicados. Esse preset completo ainda depende da execução no Colab.
- Lote técnico executado em CPU: **268 WAVs de todos os 32 perfis**, extração do microfrontend concluída e treino de 20 passos exportou TFLite streaming quantizado de **35.272 bytes**. Inferência em validação/teste concluiu e gerou sete relatórios por perfil. Recall zero: o artefato curto foi corretamente marcado `rejected_synthetic_evaluation`. Não comprova melhora nem deve ser instalado.
- **19 testes passaram**, incluindo preservação da chamada inteira, duração mínima balanceada, hash de origem, retomada bloqueada com parâmetros/áudio alterados e limiar que maximiza recall dentro do FPR permitido.
- Síntese Kokoro em CPU executada também pelo seletor novo: áudio válido de 24 kHz, reamostrado para 16 kHz na geração. Hash do modelo int8 verificado. O retorno de erro CUDA para CPU foi testado com simulação; **CUDA real não foi executado neste PC sem GPU**.
- Notebook tenta ONNX Runtime CUDA 12 e Kokoro float16 em GPU no Colab, reaproveitando bibliotecas NVIDIA do ambiente isolado; CPU int8 é alternativa. Cartão/catálogo Kokoro vêm de revisão fixa e os pesos/estilos têm SHA-256 fixado.
- Progresso por perfil e marcadores das etapas permitem retomar enquanto os arquivos temporários existirem. Nenhum backup automático em Drive: se a máquina Colab for apagada, esses arquivos se perdem.
- Células do notebook regenerado compilam e o pacote permite comparar SavedModel/pesos originais com TFLite, sem exportar áudio pessoal.

O APK, o detector em uso e as configurações da Emily permanecem inalterados. Ainda faltam treino completo, revisão de pronúncia dos perfis estrangeiros, conversas reais longas, comparação com chamadas reais e verificação no Android. A métrica streaming continua incluindo a inicialização; falsos positivos de silêncio/início não são descartados.
