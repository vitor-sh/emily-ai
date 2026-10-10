# Detector “Ei, Emily” — laboratório isolado

Estado: **protótipo de treinamento, não detector aprovado**. O aplicativo continua usando seu detector atual.

## Executar sem gravar áudios

O notebook `ei-emily-colab.ipynb` é autossuficiente. Abra https://colab.research.google.com/ → **Arquivo → Fazer upload de notebook**, selecione esse arquivo, escolha uma GPU gratuita disponível e use **Executar tudo**. Ao finalizar, devolva o ZIP gerado para avaliar o candidato antes de instalar. Não precisa compartilhar Drive, adicionar chave de API ou enviar áudio pessoal.

O kernel do Colab pode usar Python 3.13 ou outra versão incompatível com TensorFlow 2.18/NumPy 2.0. O notebook cria automaticamente um Python 3.11 gerenciado pelo [uv](https://docs.astral.sh/uv/guides/install-python/) e um ambiente virtual separado; todas as etapas usam esse interpretador. A GPU é acessada pelos subprocessos de treino, com as [bibliotecas CUDA do TensorFlow](https://www.tensorflow.org/install/pip) instaladas no ambiente separado. A saída imprime a versão e as GPUs reconhecidas. Os erros de instalação mostram o motivo real e ficam em `setup.log`.

O treinamento gera automaticamente exemplos em português e frases que confundem o detector: “Emily”, “a Emily”, “e me liga”, “Ei, Siri”, etc. A segunda rodada combina **32 perfis sintéticos: quatro Piper e 28 Kokoro**, com sete perfis brasileiros no total. Os outros 25 usam fonemas pt-br em estilos estrangeiros: são variedade experimental de timbre, não 25 brasileiros novos. Há 25 perfis de treino, três de validação e quatro de teste, incluindo femininos nos três conjuntos. Não misturamos estilos nem contamos alterações de velocidade, ruído, volume ou reverberação como novos falantes. Evitamos as adaptações espanholas dos mesmos nomes e o perfil combinado af_heart; a independência de pessoas entre todos os estilos Kokoro não é comprovada. A confirmação final continua exigindo fala real de fontes adequadas. Não é necessário recrutar amigos para produzir centenas de gravações.

## Proteções do experimento

- Perfis separados entre treinamento, validação e teste. Nunca dividir aleatoriamente variações do mesmo perfil entre conjuntos; no Kokoro, perfis distintos não comprovam pessoas distintas.
- Seu áudio particular fica fora do pacote e do treinamento. A avaliação pessoal poderá ser feita localmente depois.
- WAV mono PCM16 a 16 kHz. Microfrontend de referência do TensorFlow: janela 30 ms, passo 10 ms, 40 canais e PCAN. Um espectrograma Mel comum no Android não é equivalente.
- O limiar é escolhido em validação; teste é medido depois, sem ajustar o limiar pela voz de teste.
- Inferência limpa o estado ao mudar de arquivo e usa a escala real de quantização, saturando entradas para evitar overflow.
- Fontes, cartões dos modelos, revisões e hashes são registrados. As fontes restritivas do notebook upstream **não são baixadas**.
- Nenhum script copia modelos para o app, mexe no microfone, APK, login ou configurações pessoais.

## Fontes e atribuição

Treinamento: [microWakeWord](https://github.com/kahrendt/microWakeWord), Apache-2.0, commit fixado em `voices.json`. A instalação precisa ser editável: a distribuição wheel deste commit não inclui as subpastas `audio`/`layers`.

Síntese: [Piper](https://github.com/OHF-Voice/piper1-gpl), GPLv3. [Modelos Piper](https://huggingface.co/rhasspy/piper-voices): conferir o MODEL_CARD de cada voz, não apenas a licença geral do repositório. Cadu, Faber e Jeff: [OHF Voice datasets](https://github.com/OHF-Voice/voice-datasets), CC0. Edresson: [TTS-Portuguese-Corpus, Edresson Casanova](https://github.com/Edresson/TTS-Portuguese-Corpus), CC-BY-4.0. Preservar os cartões e atribuições ao distribuir os futuros artefatos.

Os dados pré-processados `kahrendt/microwakeword` e parte dos dados do tutorial têm restrições não comerciais: este laboratório não os utiliza. Ainda não há um corpus ambiente real longo no experimento; portanto o relatório não estima falsos acionamentos por hora de conversas reais.

## Comandos locais

Use ambiente virtual separado, Python 3.11/3.12, espaço em disco e memória suficientes. Não usar `/tmp` para um ambiente grande em computadores onde `/tmp` é RAM. No Colab, o notebook realiza a instalação isolada na máquina temporária.

```bash
python -m unittest -v test_lab
python lab.py generate --work work/experiment --repetitions 96
python lab.py features --work work/experiment
python lab.py train --work work/experiment --steps 6000
python lab.py evaluate --work work/experiment
```

Para regenerar o notebook após mudar os scripts: `python build_notebook.py`.

## Antes de substituir Vosk

1. Candidato supera a referência em chamadas reais de falantes não presentes no treino, inclusive voz baixa/rápida; os três exemplos particulares são triagem, não comprovação geral.
2. Medir falsos acionamentos em horas de fala ambiente real, com menções à Emily e frases parecidas. Ruído sintético sozinho não substitui isso.
3. Conferir paridade do microfrontend Python/Android e TFLite quantizado.
4. Testar bateria, memória, tela desligada, áudio da própria Emily, cancelamento e retomada do microfone no aparelho.
5. Manter possibilidade de voltar ao detector anterior.

O Colab gratuito pode não oferecer GPU ou interromper a sessão. O pipeline não promete tempo de treinamento nem aprovação do primeiro modelo.

## Rodada diversa (v2)

- Cerca de **28.044 WAVs** no preset: positivos com três grafias, 36 frases negativas (incluindo nomes parecidos, menções e conversa), silêncio e ruído sintéticos. Vozes brasileiras de treino recebem mais exemplos.
- Até três sínteses por texto são reutilizadas com perturbações, para reduzir tempo; 28 mil arquivos não equivalem a 28 mil falas independentes. Prévia de cada perfil aparece no notebook.
- Fonte [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), Apache-2.0; wrapper [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx), MIT. Pesos/estilos têm SHA-256 fixado, cartão e catálogo são baixados em revisão fixada. Preservamos os créditos Koniwa e SIWIS no cartão oficial.
- A geração tenta Kokoro ONNX float16 em CUDA no Colab; se indisponível, usa int8 CPU com uma thread. Modelos são reaproveitados, sem PyTorch ou API paga. Piper permanece em CPU e TensorFlow usa a T4. O caminho CPU foi executado aqui; CUDA real exige conferência no Colab. Geração completa e extração podem demorar.
- Chamada inteira dentro da janela de treino, duração mínima balanceada entre classes, reverberação leve, banda reduzida, ruído e volume variável. Exemplos com chamadas longas/inválidas falham explicitamente; não cortar a fala silenciosamente.
- Otimizador: taxa 0,0003 e penalidade negativa 2, experimentais. O modelo não é aprovado por ter mais passos. O relatório mede recall/FPR por perfil e aceita somente limiar da validação. O máximo streaming inclui a inicialização: falsos positivos de início/silêncio continuam contando, não são ocultados.
- Use uma sessão nova do Colab e o notebook regenerado. A pasta é `work-v2-diverse`, separada da primeira rodada. O ZIP inclui SavedModel e pesos para diagnóstico. A geração retoma por perfil concluído, verificando hashes de áudio e parâmetros. Etapas concluídas são reutilizadas. Isso só funciona enquanto os arquivos da máquina temporária existirem; não há backup automático no Google Drive.
- Teste técnico reduzido: `python lab.py generate --work work/pilot --repetitions 1 --smoke`. **Esse preset não é treinamento de qualidade nem comprova melhora**.

Não integramos vozes comerciais clonadas, Fish API ou modelos com licença não comercial ao treino. O áudio pessoal continua reservado à avaliação local.
