"""
Normalizador de volume - "Emily"
-----------------------------------
Esse script pega uma pasta de gravações e cria uma cópia de cada
uma com o volume "turbinado" pro nível máximo seguro (sem distorcer).
É um teste rápido pra saber se volume baixo do microfone é o motivo
do modelo não estar reconhecendo sua voz.

INSTALAR (uma vez só):
    pip install pydub

COMO USAR:
    python normalizar_audio.py gravacoes_emily gravacoes_emily_normalizadas

Depois disso, teste o modelo na pasta NOVA (normalizada):
    python testar_modelo.py emily.onnx gravacoes_emily_normalizadas

Se o resultado melhorar bastante, confirma que o problema era volume.
"""

import sys
import os
import glob
from pydub import AudioSegment
from pydub.effects import normalize


def normalizar_pasta(pasta_entrada: str, pasta_saida: str):
    if not os.path.isdir(pasta_entrada):
        print(f"Pasta não encontrada: {pasta_entrada}")
        sys.exit(1)

    os.makedirs(pasta_saida, exist_ok=True)

    arquivos = sorted(glob.glob(os.path.join(pasta_entrada, "*.wav")))
    if not arquivos:
        print(f"Nenhum .wav encontrado em '{pasta_entrada}'")
        sys.exit(1)

    print(f"Encontrei {len(arquivos)} arquivos. Normalizando...\n")

    for caminho in arquivos:
        nome = os.path.basename(caminho)
        audio = AudioSegment.from_wav(caminho)

        pico_antes = audio.max_dBFS

        audio_normalizado = normalize(audio)  # leva o pico pro máximo seguro (~0 dBFS)

        pico_depois = audio_normalizado.max_dBFS

        caminho_saida = os.path.join(pasta_saida, nome)
        audio_normalizado.export(caminho_saida, format="wav")

        print(f"  {nome:25s}  pico antes: {pico_antes:6.1f} dBFS  ->  depois: {pico_depois:6.1f} dBFS")

    print(f"\nFeito! Arquivos normalizados salvos em '{pasta_saida}/'")


def main():
    if len(sys.argv) != 3:
        print("Uso: python normalizar_audio.py <pasta_entrada> <pasta_saida>")
        print("Exemplo: python normalizar_audio.py gravacoes_emily gravacoes_emily_normalizadas")
        sys.exit(1)

    normalizar_pasta(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
