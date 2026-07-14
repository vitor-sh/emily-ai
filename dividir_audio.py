"""
Divisor de áudio único em várias amostras - "Emily"
-----------------------------------------------------
Esse script resolve o problema de "ter vergonha de pedir 20 áudios
separados". Em vez disso, você pede só UM áudio (tipo um voice note
de WhatsApp de 20-30 segundos) onde a pessoa fala "Emily" várias vezes
seguidas, com uma pausinha entre cada vez. O script separa esse áudio
único automaticamente em várias amostras pequenas, prontas pro treino.

O QUE PEDIR PRA CADA PESSOA (copia e cola, é bem mais leve que pedir
20 áudios):

    "Ei, me ajuda com um teste aqui? Manda um áudio de uns 20-30
    segundos falando 'Emily... Emily... Emily...' várias vezes, com
    uma pausinha entre cada uma. Pode ser tipo uma palhaçada mesmo,
    é só pra um teste que eu tô fazendo aqui no projeto."

INSTALAR (uma vez só):
    pip install pydub
    (precisa também ter o "ffmpeg" instalado no sistema, que já é
    necessário pro resto do projeto)

COMO USAR:
    python dividir_audio.py audio_do_amigo.ogg joao
    python dividir_audio.py audio_da_amiga.m4a maria

O primeiro argumento é o arquivo de áudio (aceita .ogg, .mp3, .m4a,
.wav, praticamente qualquer formato comum, incluindo áudio de
WhatsApp). O segundo é o nome da pessoa, só pra organizar em pastas
separadas.

O resultado vai ficar em "amostras_pessoas/<nome>/emily_001.wav",
"emily_002.wav", etc.
"""

import sys
import os
from pydub import AudioSegment
from pydub.silence import split_on_silence

PASTA_BASE = "amostras_pessoas"
SAMPLE_RATE_SAIDA = 16000  # formato esperado pelo treino


def dividir_audio(caminho_arquivo: str, nome_pessoa: str):
    print(f"Lendo o áudio de '{nome_pessoa}'...")
    audio = AudioSegment.from_file(caminho_arquivo)

    duracao_s = len(audio) / 1000
    print(f"Duração total: {duracao_s:.1f} segundos")

    # Divide nos pontos de silêncio entre as falas
    pedacos = split_on_silence(
        audio,
        min_silence_len=350,             # pausa mínima pra considerar separação
        silence_thresh=audio.dBFS - 16,  # ajusta sozinho com base no volume médio
        keep_silence=120,                # mantém uma bordinha de silêncio
    )

    if len(pedacos) == 0:
        print("\n⚠ Não encontrei nenhuma pausa nesse áudio.")
        print("Dica: peça pra pessoa falar mais devagar, com pausas")
        print("mais claras entre cada 'Emily'.")
        return

    pasta_pessoa = os.path.join(PASTA_BASE, nome_pessoa)
    os.makedirs(pasta_pessoa, exist_ok=True)

    salvos = 0
    descartados = 0

    for i, pedaco in enumerate(pedacos):
        duracao_pedaco = len(pedaco) / 1000

        # Descarta pedaços muito curtos (provavelmente ruído, não fala)
        # ou muito longos (provavelmente duas falas coladas)
        if duracao_pedaco < 0.3:
            descartados += 1
            continue
        if duracao_pedaco > 2.5:
            print(f"  Aviso: pedaço {i+1} tem {duracao_pedaco:.1f}s, "
                  f"pode ser duas falas coladas. Mantendo, mas confira depois.")

        pedaco_ajustado = (
            pedaco
            .set_frame_rate(SAMPLE_RATE_SAIDA)
            .set_channels(1)
            .set_sample_width(2)  # garante 16-bit, formato padrão esperado no treino
        )

        salvos += 1
        caminho_saida = os.path.join(pasta_pessoa, f"emily_{salvos:03d}.wav")
        pedaco_ajustado.export(caminho_saida, format="wav")

    print(f"\nFeito! {salvos} amostras salvas em '{pasta_pessoa}/'")
    if descartados:
        print(f"({descartados} pedaços muito curtos foram ignorados)")

    if salvos < 10:
        print("\n⚠ Saíram poucas amostras. Se possível, peça um áudio um")
        print("pouco mais longo ou com mais repetições da pessoa.")


def main():
    if len(sys.argv) != 3:
        print("Uso: python dividir_audio.py <arquivo_de_audio> <nome_da_pessoa>")
        print("Exemplo: python dividir_audio.py audio_joao.ogg joao")
        sys.exit(1)

    caminho_arquivo = sys.argv[1]
    nome_pessoa = sys.argv[2]

    if not os.path.exists(caminho_arquivo):
        print(f"Arquivo não encontrado: {caminho_arquivo}")
        sys.exit(1)

    dividir_audio(caminho_arquivo, nome_pessoa)


if __name__ == "__main__":
    main()
