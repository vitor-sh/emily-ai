"""
Teste de Wake Word para a Emily, usando sherpa-onnx (100% offline, gratuito).

O que esse script faz:
- Liga o microfone e escuta em tempo real
- Quando alguém fala "EMILY", imprime uma mensagem na tela
- Não precisa de internet, conta, chave de API ou treino de modelo

------------------------------------------------------------
PASSO 1 - Instalar as dependências (uma vez só):

    pip install sherpa-onnx sounddevice numpy

------------------------------------------------------------
PASSO 2 - Baixar o modelo (uma vez só):

Baixe e extraia este arquivo na mesma pasta deste script:
https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2

No Windows, dá pra extrair .tar.bz2 com o 7-Zip.
No final, você deve ter uma pasta chamada:
    sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/
na mesma pasta deste arquivo test_wakeword.py.

------------------------------------------------------------
PASSO 3 - Criar o arquivo da palavra-chave (uma vez só):

Crie um arquivo chamado "keywords_raw.txt" (nesta mesma pasta) com este
conteúdo (só a palavra, em letras maiúsculas):

    EMILY

Depois rode este comando no terminal pra converter pro formato que o
sherpa-onnx entende:

    sherpa-onnx-cli text2token \
        --tokens sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/tokens.txt \
        --tokens-type bpe \
        --bpe-model sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01/bpe.model \
        keywords_raw.txt keywords.txt

Isso vai gerar o arquivo "keywords.txt", que é o que o script abaixo usa.

------------------------------------------------------------
PASSO 4 - Rodar o teste:

    python test_wakeword.py

Fale "Emily" perto do microfone e veja se ela detecta. Ctrl+C pra parar.

------------------------------------------------------------
DICA: se ela não disparar nunca, AUMENTE o KEYWORDS_THRESHOLD (ex: 0.4).
Se ela disparar sozinha sem você falar nada, DIMINUA o KEYWORDS_THRESHOLD
(ex: 0.15). É um equilíbrio entre "não reconhecer" e "reconhecer demais".
"""

import sherpa_onnx
import sounddevice as sd
import numpy as np

# --- Ajuste esses caminhos se você organizar as pastas diferente ---
MODEL_DIR = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
KEYWORDS_FILE = "keywords.txt"

SAMPLE_RATE = 16000  # taxa de amostragem que o modelo espera

# Quanto MENOR esse número, mais fácil a wake word disparar
# (mas também aumenta a chance de disparar sem querer)
KEYWORDS_THRESHOLD = 0.25


def criar_detector() -> sherpa_onnx.KeywordSpotter:
    """Carrega o modelo de keyword spotting (só precisa ser feito uma vez)."""
    return sherpa_onnx.KeywordSpotter(
        tokens=f"{MODEL_DIR}/tokens.txt",
        encoder=f"{MODEL_DIR}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        decoder=f"{MODEL_DIR}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
        joiner=f"{MODEL_DIR}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
        keywords_file=KEYWORDS_FILE,
        num_threads=2,
        provider="cpu",
        keywords_threshold=KEYWORDS_THRESHOLD,
    )


def main():
    detector = criar_detector()
    stream = detector.create_stream()

    print("Escutando... fale 'Emily' para testar (Ctrl+C para parar)\n")

    def callback(indata, frames, time_info, status):
        if status:
            print(status)

        audio = indata[:, 0].astype(np.float32)
        stream.accept_waveform(SAMPLE_RATE, audio)

        # Decodifica enquanto houver frames suficientes acumulados
        while detector.is_ready(stream):
            detector.decode_stream(stream)

        palavra_detectada = detector.get_result(stream)
        if palavra_detectada:
            print(f">>> Wake word detectada: '{palavra_detectada}'  (Emily acordou!)")
            # Reseta o stream pra poder detectar de novo na próxima vez
            detector.reset_stream(stream)

    with sd.InputStream(
        channels=1,
        dtype="float32",
        samplerate=SAMPLE_RATE,
        callback=callback,
    ):
        try:
            while True:
                sd.sleep(200)
        except KeyboardInterrupt:
            print("\nTeste finalizado.")


if __name__ == "__main__":
    main()
