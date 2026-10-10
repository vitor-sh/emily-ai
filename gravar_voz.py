"""
Gravador de amostras de voz - "Emily"
---------------------------------------
Esse script grava você falando "Emily" várias vezes e salva cada
gravação como um arquivo .wav separado, já no formato certo
(16kHz, mono) pra usar depois no treino do modelo.

INSTALAR (uma vez só):
    pip install sounddevice numpy

COMO USAR:
    python gravar_voz.py

A cada "Aperte ENTER", você aperta enter, espera o "GRAVANDO...",
fala "Emily" naturalmente, e pronto - ele salva e já pergunta a
próxima.

DICAS PRA VARIAR (importante pro modelo aprender bem):
- Varie a distância do microfone (perto, médio, longe)
- Varie o tom (normal, com pressa, mais animado, mais calmo, sussurrando)
- Grave em momentos diferentes do dia (voz muda com cansaço)
- De vez em quando deixe um som de fundo tocando baixinho (TV, música)
- Tente também falar igual você falaria se realmente estivesse chamando
  a Emily no dia a dia (não precisa "caprichar" na pronúncia)

META: pelo menos 50 gravações. Se conseguir 100+, melhor ainda.
Você pode fechar o script e rodar de novo depois para continuar
de onde parou (ele não sobrescreve os arquivos já salvos).
"""

import sounddevice as sd
import numpy as np
import wave
import os

PASTA_SAIDA = "gravacoes_emily"
SAMPLE_RATE = 16000      # taxa de amostragem esperada pelos modelos de wake word
DURACAO_SEGUNDOS = 2.0   # duração de cada gravação


def proximo_numero_disponivel(pasta: str) -> int:
    """Olha os arquivos já existentes e descobre de onde continuar."""
    if not os.path.exists(pasta):
        return 1
    existentes = [f for f in os.listdir(pasta) if f.startswith("emily_") and f.endswith(".wav")]
    if not existentes:
        return 1
    numeros = [int(f.replace("emily_", "").replace(".wav", "")) for f in existentes]
    return max(numeros) + 1


def salvar_wav(caminho: str, audio: np.ndarray, sample_rate: int):
    """Salva um array de áudio (float32, -1 a 1) como .wav PCM 16-bit."""
    audio_int16 = np.clip(audio, -1.0, 1.0)
    audio_int16 = (audio_int16 * 32767).astype(np.int16)

    with wave.open(caminho, "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_int16.tobytes())


def gravar_uma_amostra() -> np.ndarray:
    n_amostras = int(DURACAO_SEGUNDOS * SAMPLE_RATE)
    audio = sd.rec(n_amostras, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()  # espera a gravação terminar
    return audio[:, 0]


def main():
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    contador = proximo_numero_disponivel(PASTA_SAIDA)

    ja_gravadas = contador - 1
    print(f"Você já tem {ja_gravadas} gravações salvas em '{PASTA_SAIDA}/'.")
    print("Vamos continuar gravando. Pressione Ctrl+C quando quiser parar.\n")

    try:
        while True:
            input(f"[{contador}] Aperte ENTER e fale 'Emily' quando aparecer GRAVANDO... ")
            print("    GRAVANDO...")
            audio = gravar_uma_amostra()
            print("    (gravação finalizada)")

            caminho = os.path.join(PASTA_SAIDA, f"emily_{contador:03d}.wav")
            salvar_wav(caminho, audio, SAMPLE_RATE)
            print(f"    Salvo: {caminho}\n")

            contador += 1

            if contador - 1 == 50:
                print(">>> Você bateu a meta minima de 50! Pode continuar pra deixar ainda melhor. <<<\n")

    except KeyboardInterrupt:
        total = contador - 1
        print(f"\nFinalizado! Você tem {total} gravações no total na pasta '{PASTA_SAIDA}/'.")


if __name__ == "__main__":
    main()
