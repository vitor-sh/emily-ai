"""
Teste de precisão - modelo "Emily" treinado
----------------------------------------------
Esse script pega o modelo .onnx que saiu do treino no Colab e testa
ele contra suas gravações reais, contando quantas ele reconheceu
certinho. No final, mostra uma taxa de acerto de verdade (não um
chute).

INSTALAR (uma vez só, é rapidinho e leve):
    pip install openwakeword

COMO USAR:
    python testar_modelo.py emily.onnx gravacoes_emily

O primeiro argumento é o caminho do arquivo .onnx que você baixou do
Colab. O segundo é a pasta com suas gravações (a mesma pasta
"gravacoes_emily" que o gravar_voz.py criou, com os emily_001.wav,
emily_002.wav, etc.)
"""

import sys
import os
import glob
from openwakeword.model import Model

# Score mínimo para considerar que o modelo "reconheceu" a palavra.
# Pode ajustar esse número depois de ver os resultados.
LIMIAR = 0.30

# Caminhos dos modelos auxiliares (compartilhados, não é o seu "emily.onnx").
# Baixe-os de:
#   https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx
#   https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx
# e coloque na MESMA pasta deste script (ajuste o caminho abaixo se colocar em outro lugar).
CAMINHO_MELSPEC = "melspectrogram.onnx"
CAMINHO_EMBEDDING = "embedding_model.onnx"


def testar(caminho_modelo: str, pasta_gravacoes: str):
    if not os.path.exists(caminho_modelo):
        print(f"Modelo não encontrado: {caminho_modelo}")
        sys.exit(1)

    if not os.path.isdir(pasta_gravacoes):
        print(f"Pasta de gravações não encontrada: {pasta_gravacoes}")
        sys.exit(1)

    if not os.path.exists(CAMINHO_MELSPEC) or not os.path.exists(CAMINHO_EMBEDDING):
        print("Faltam os arquivos auxiliares 'melspectrogram.onnx' e/ou")
        print("'embedding_model.onnx' nesta pasta. Baixe-os dos links no")
        print("topo deste script e coloque na mesma pasta do testar_modelo.py.")
        sys.exit(1)

    print(f"Carregando o modelo '{caminho_modelo}'...")
    modelo = Model(
        wakeword_model_paths=[caminho_modelo],
        melspec_onnx_model_path=CAMINHO_MELSPEC,
        embedding_onnx_model_path=CAMINHO_EMBEDDING,
    )

    # O nome do modelo dentro do dicionário de resultados é o nome
    # do arquivo sem a extensão (ex: "emily" para "emily.onnx")
    nome_modelo = os.path.splitext(os.path.basename(caminho_modelo))[0]

    arquivos = sorted(glob.glob(os.path.join(pasta_gravacoes, "*.wav")))

    if not arquivos:
        print(f"Nenhum arquivo .wav encontrado em '{pasta_gravacoes}'")
        sys.exit(1)

    print(f"Encontrei {len(arquivos)} gravações. Testando uma por uma...\n")

    acertos = 0
    scores_de_todos = []

    for caminho_wav in arquivos:
        nome_arquivo = os.path.basename(caminho_wav)

        # Roda o modelo no arquivo inteiro, simulando um stream de áudio
        predicoes = modelo.predict_clip(caminho_wav)

        # Pega o maior score entre todos os "pedacinhos" do áudio
        score_maximo = max(
            (p.get(nome_modelo, 0.0) for p in predicoes),
            default=0.0,
        )
        scores_de_todos.append(score_maximo)

        reconheceu = score_maximo >= LIMIAR
        if reconheceu:
            acertos += 1

        marca = "OK " if reconheceu else "X  "
        print(f"  {marca} {nome_arquivo:30s} score: {score_maximo:.3f}")

        modelo.reset()  # limpa o estado interno antes do próximo arquivo

    total = len(arquivos)
    taxa = (acertos / total) * 100

    media_score = sum(scores_de_todos) / len(scores_de_todos)

    print("\n" + "=" * 50)
    print(f"RESULTADO FINAL")
    print("=" * 50)
    print(f"Reconheceu corretamente: {acertos} de {total} ({taxa:.1f}%)")
    print(f"Score médio geral: {media_score:.3f}")
    print(f"Limiar usado: {LIMIAR}")

    if taxa >= 85:
        print("\n>>> Ótimo resultado! Esse modelo já está pronto pra usar.")
    elif taxa >= 60:
        print("\n>>> Resultado razoável. Vale tentar diminuir o LIMIAR")
        print("    no topo do script (ex: 0.35) e rodar de novo.")
    else:
        print("\n>>> Resultado baixo. Precisamos conversar sobre os")
        print("    próximos passos antes de usar esse modelo.")


def main():
    if len(sys.argv) != 3:
        print("Uso: python testar_modelo.py <modelo.onnx> <pasta_de_gravacoes>")
        print("Exemplo: python testar_modelo.py emily.onnx gravacoes_emily")
        sys.exit(1)

    testar(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()