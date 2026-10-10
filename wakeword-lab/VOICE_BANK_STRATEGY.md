# Estratégia após a reprovação do v3 — 2026-10-04

## Escolha

Continuar o caminho aberto do microWakeWord, mas revisar a fonte dos positivos e ampliar a avaliação com negativos reais antes de pedir outro treino grande. Não repetir o refinamento v3. O reforço de negativos diminuiu scores de nomes isolados, porém também perdeu chamadas pessoais; esse resultado não demonstra que a única deficiência era quantidade de vozes.

Duas frentes:

1. **Chamadas em português:** experimentar Qwen3-TTS VoiceDesign para criar referências novas; reutilizar cada referência com o Base 0.6B para manter o perfil nas frases. Ambos suportam português e têm licença Apache-2.0. O piloto não clona pessoas reais.
2. **Falas comuns que não devem ativar:** Common Voice português. A versão 27 registra 3.860 falantes, incluindo 624 declarados pt-BR. Esses áudios não necessariamente dizem “Ei, Emily”; servem para a frente negativa e sua avaliação. Vozes/horas de negativos não são vozes positivas comprovadas.

Não contar alterações de velocidade, pitch, ruído, descrições de sotaque ou réplicas como novos falantes. Perfis gerados não comprovam sotaques regionais nem identidades independentes. Uma auditoria acústica e auditiva deve preceder a escala.

## Piloto preparado

`voice_bank_pilot.py` gera 12 perfis solicitados, abrangendo descrições de seis regiões brasileiras, gêneros/idades/timbres variados. Cada perfil tem uma referência de fala normal, duas grafias da chamada e dois negativos (nome isolado e menção em conversa): 60 arquivos de áudio no total.

Modelos fixados:

- `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, revisão `5ecdb67327fd37bb2e042aab12ff7391903235d3`.
- `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, revisão `5d83992436eae1d760afd27aff78a71d676296fc`.
- Biblioteca `qwen-tts==0.1.1`; APIs conferidas contra o código oficial na revisão `022e286b98fbec7e1e916cb940cdf532cd9f488e`.

O piloto registra hash, seed, texto esperado, origem, duração e tempo efetivo de síntese. Recortes longos recebem alertas; não são acelerados ou cortados silenciosamente para caber no detector. WAVs para comparação ficam em mono PCM16 de 16 kHz. Referências mantêm o sample rate da síntese.

A auditoria usa Whisper small para transcrever e sinalizar prefixos ausentes, frases alteradas e inconsistências. Uma transcrição correta não comprova que o detector reconhecerá a chamada; uma transcrição errada também não prova fala inválida. A página `listening.html` acompanha os áudios para conferir isso.

Embeddings das referências são comparados; pares com cosseno acima de 0,95 são sinalizados como potencialmente muito semelhantes. Esse limiar é heurístico, não uma certificação de que as vozes restantes são pessoas distintas. Agrupar perfis semelhantes antes de futuras divisões de treino/validação/teste, para evitar vazamento entre conjuntos.

Não gera outro modelo wake-word, não usa a gravação pessoal e não altera Android/Emily. Saída: `work-source-pilot-12.zip`.

## Colab e retomada

Notebook: `ei-emily-voice-source-pilot.ipynb`. Para reaproveitar a sessão aberta, copiar `voice-source-colab-cell.py` inteiro para uma célula nova e executar só ela. A instalação usa `/content/emily-voice-source-pilot/.voicegen-venv` e não modifica o ambiente TensorFlow anterior.

Na T4, usa FP32 e SDPA para evitar o problema de sampling FP16 reportado em GPUs Turing. Em GPUs com BF16 nativo, usa BF16. Essa configuração ainda precisa ser testada no runtime real. Cada etapa roda em um subprocesso separado; os dois geradores e o transcritor não ficam carregados simultaneamente. Exige pelo menos 20 GiB livres antes dos downloads. Instala FFmpeg/SoX no ambiente temporário do Colab somente se ausentes.

A geração salva progresso a cada WAV e valida hashes ao retomar. Dependências/parâmetros/script alterados interrompem a retomada em vez de misturar resultados. O Colab gratuito pode interromper a execução ou não fornecer GPU; a perda da máquina temporária também apaga o banco. Não conecta Drive nem ativa plano pago.

## Escala após o piloto

Se a pronúncia, a diversidade efetiva e o custo medido forem aceitáveis, ampliar em lotes para aproximadamente 200 perfis, mantendo referências estáveis. O catálogo preparado permite até 216 descrições distintas; isso é um teto de perfis **solicitados**, não uma promessa de 216 vozes ou sotaques independentes. Usar o tempo medido na T4 para escolher tamanho de lote e sessões, em vez de prometer que cabe tudo numa sessão gratuita.

Antes do próximo treinamento completo:

- Revisar se as chamadas inteiras cabem no campo receptivo; ampliar janela/arquitetura se necessário.
- Auditar os recortes temporais positivos e evitar rotular partes incompletas como chamadas.
- Balancear falantes/perfis, sem a predominância de estilos estrangeiros do v2.
- Acrescentar negativos reais e reservar falantes/áudios para avaliação, sem selecionar limiar pela gravação pessoal.
- Comparar inicialização e streaming contínuo, além da última janela, no modelo quantizado final.
- Confrontar com Vosk no mesmo material e, somente com ganho convincente, medir no Android.

Dados públicos e sintéticos reduzem a coleta manual, mas não eliminam a validação final em pessoas reais. As três chamadas pessoais continuam reservadas a teste e são insuficientes para afirmar que funciona com todos.

## Outras opções consideradas

- Chatterbox Multilingual e pacote pt-BR: alternativa de síntese caso o Qwen não entregue pronúncia/custo aceitáveis. Licença MIT, suporte oficial a português. Não preparado um segundo gerador simultaneamente; precisamos primeiro medir o escolhido.
- Porcupine: detector pronto com português e integração Android, exige conta/AccessKey. Não integrar nem assumir que a distribuição pública cabe gratuitamente sem revisar os termos da conta/plano. Pode ser comparado depois, se o caminho aberto continuar falhando.
- Piper/Kokoro atuais: podem permanecer como fontes secundárias e conjuntos comparativos. Aumentar seus estilos/augmentações não basta para declarar centenas de vozes brasileiras novas.

## Fontes verificadas

- https://github.com/QwenLM/Qwen3-TTS
- https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
- https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base
- https://github.com/QwenLM/Qwen3-TTS/issues/43 (FP16 em Turing)
- https://mozilladatacollective.com/datasets/cmu5wui2w00e8nq07idithpm6
- https://github.com/resemble-ai/chatterbox
- https://picovoice.ai/docs/quick-start/porcupine-android/

Common Voice exige acesso pelas condições do portal; seu datasheet proíbe identificar os falantes e republicar o dataset. Não baixar de espelhos não oficiais nem incluir esses áudios em pacotes públicos do projeto. A utilização concreta deve respeitar essas condições. Não foi baixado nem preparado para clonagem de vozes reais.

## Verificação e limites atuais

30 testes automatizados passaram: testes existentes e testes do novo banco cobrindo descrições duplicadas, falta do “Ei”, chamada indevida em negativo, áudio inválido, duração, formato PCM/resampling, integridade na retomada e logs de erro reais do preparador. Notebook/célula compilados e assinaturas da API Qwen verificadas no código oficial.

**Ainda não verificado:** instalação completa das dependências no Colab, síntese efetiva na T4, custo de 200 perfis, sotaques/pronúncia dos novos áudios e ganho do detector. O PC atual não tem GPU e tem aproximadamente 2 GiB disponíveis de RAM; não carregamos modelos de bilhões de parâmetros nele.

**Não alterados:** detector Android/Vosk, APK, ambiente da Emily, pesos v2/v3 e corpus anterior. Motivo: nenhum candidato foi aprovado. O próximo treino completo está condicionado à auditoria da nova fonte de voz; não pedir outra rodada grande sobre dados ainda não validados.

## Correção da inicialização CUDA — 2026-10-04

A preparação original removia todo o `LD_LIBRARY_PATH` do subprocesso. Isso podia impedir a localização do driver NVIDIA mesmo com T4 selecionada. Corrigido: conservar caminhos do host, excluir somente caminhos conhecidos da `.training-venv` e diretórios de stubs, acrescentando diretórios de driver do Colab quando existentes. Não modificar `CUDA_VISIBLE_DEVICES` nem o ambiente do kernel.

A mensagem genérica “Selecione a T4” foi substituída por `voice_gpu_probe.py`, executado em subprocesso fresco antes dos imports Qwen/Whisper. Registra `nvidia-smi`, carga/inicialização de `libcuda`, erro real de inicialização PyTorch e uma operação CUDA pequena. Salva `gpu-diagnostics.json`, contendo somente versão/paths e variáveis GPU selecionadas, sem credenciais. Não reinstala o driver nem troca versão Torch às cegas.

`repair-voice-gpu-colab-cell.py` atualiza somente preparador, diagnóstico e testes na sessão existente, recarrega o módulo do kernel, aproveita dependências já instaladas e continua o piloto com os parâmetros anteriores. Se falhar no diagnóstico, baixa o JSON para investigar a causa. Banco de áudio, hashes, referências, ambiente TensorFlow anterior e modelo Android preservados.

31 testes automatizados passaram. O diagnóstico local registrou corretamente ausência de driver/PyTorch no host local. Células e notebook recompilados. O defeito do preparador foi corrigido; **a causa exata no runtime do usuário ainda precisa ser confirmada**, e não há alegação de síntese bem-sucedida na T4.
