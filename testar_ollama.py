"""
Script para testar modelos do Ollama: velocidade de resposta e tool calling.

Como usar:
1. Deixe o Ollama rodando em segundo plano (ele abre sozinho depois de instalado,
   ou rode 'ollama serve' no terminal).
2. Rode: pip install ollama
3. Ajuste a variável MODELO abaixo com o nome do modelo que você baixou
   (ex: "qwen3:8b", "llama3.1:8b", "gemma4:e4b").
4. Rode este arquivo: python testar_ollama.py
"""

import time
import ollama

# ------------------ CONFIGURAÇÃO ------------------
MODELO = "qwen3.5:9b"  # troque aqui pelo modelo que você quer testar

# Fixamos o contexto aqui pra não depender do slider do app do Ollama.
# 4096 é de sobra pra conversa normal + tool calling.
OPCOES = {"num_ctx": 4096}

PERGUNTAS_DE_TESTE = [
    "Explique em 2 frases o que é inteligência artificial.",
    "Quanto é 156 vezes 34?",
    "Escreva uma lista com 3 ideias de nomes para um assistente virtual.",
]


def aquecer_modelo():
    """Carrega o modelo na VRAM antes de medir tempo de verdade,
    pra não misturar tempo de carregamento com tempo de resposta."""
    print(f"Aquecendo o modelo {MODELO} (carregando na memória)...")
    inicio = time.time()
    ollama.chat(
        model=MODELO,
        messages=[{"role": "user", "content": "oi"}],
        options=OPCOES,
    )
    print(f"Modelo carregado em {time.time() - inicio:.2f}s (isso só acontece 1x)\n")


# ------------------ TESTE 1: VELOCIDADE DE CONVERSA NORMAL ------------------
def testar_velocidade():
    print("=" * 60)
    print(f"TESTE DE VELOCIDADE - Modelo: {MODELO}")
    print("=" * 60)

    for pergunta in PERGUNTAS_DE_TESTE:
        print(f"\nPergunta: {pergunta}")
        inicio = time.time()

        resposta = ollama.chat(
            model=MODELO,
            messages=[{"role": "user", "content": pergunta}],
            options=OPCOES,
            think=False,  # desliga o "pensamento" do modelo -> resposta mais rápida e mais previsível
        )

        fim = time.time()
        tempo_total = fim - inicio

        texto_resposta = resposta["message"]["content"]
        # Ollama devolve estatísticas de tokens gerados
        tokens_gerados = resposta.get("eval_count", 0)
        tempo_geracao_ns = resposta.get("eval_duration", 1)  # em nanossegundos
        tokens_por_segundo = (
            tokens_gerados / (tempo_geracao_ns / 1_000_000_000)
            if tempo_geracao_ns
            else 0
        )

        print(f"Resposta: {texto_resposta[:200]}...")
        print(f"Tempo total: {tempo_total:.2f}s")
        print(f"Velocidade: {tokens_por_segundo:.1f} tokens/segundo")

        # Referência simples pra você entender o resultado:
        if tokens_por_segundo >= 25:
            print("Avaliação: RÁPIDO — ótimo pra uso em tempo real 🚀")
        elif tokens_por_segundo >= 10:
            print("Avaliação: OK — dá pra usar, mas não é instantâneo 👍")
        else:
            print("Avaliação: LENTO — considere um modelo menor ⚠️")


# ------------------ TESTE 2: TOOL CALLING (chamada de ferramentas) ------------------
def testar_tool_calling():
    print("\n" + "=" * 60)
    print("TESTE DE TOOL CALLING (importante pra Emily)")
    print("=" * 60)

    # Definimos uma "ferramenta" falsa de exemplo: pegar a previsão do tempo
    ferramentas = [
        {
            "type": "function",
            "function": {
                "name": "obter_previsao_tempo",
                "description": "Obtém a previsão do tempo para uma cidade",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cidade": {
                            "type": "string",
                            "description": "Nome da cidade",
                        }
                    },
                    "required": ["cidade"],
                },
            },
        }
    ]

    pergunta = "Qual é a previsão do tempo em Belo Horizonte hoje?"
    print(f"\nPergunta: {pergunta}")

    inicio = time.time()
    resposta = ollama.chat(
        model=MODELO,
        messages=[{"role": "user", "content": pergunta}],
        tools=ferramentas,
        options=OPCOES,
    )
    tempo_total = time.time() - inicio

    print(f"Tempo de resposta: {tempo_total:.2f}s")

    tool_calls = resposta["message"].get("tool_calls")
    if tool_calls:
        print("✅ O modelo CONSEGUIU chamar a ferramenta corretamente!")
        for chamada in tool_calls:
            print(f"   Função chamada: {chamada['function']['name']}")
            print(f"   Argumentos: {chamada['function']['arguments']}")
    else:
        print("⚠️ O modelo NÃO chamou nenhuma ferramenta.")
        print(f"   Resposta em texto: {resposta['message']['content']}")


# ------------------ RODAR OS TESTES ------------------
if __name__ == "__main__":
    aquecer_modelo()
    testar_velocidade()
    testar_tool_calling()

    print("\n" + "=" * 60)
    print("Dica: se a velocidade ficou baixa ou o tool calling falhou,")
    print("tente um modelo menor (ex: qwen3:4b) e rode este script de novo.")
    print("=" * 60)