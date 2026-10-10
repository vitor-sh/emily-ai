# GPT-6 no agente visual da Emily — 30/09/2026

Foram chamadas as rotas reais `cx/gpt-6-luna` e `cx/gpt-6-sol` pelo OmniRoute local, usando o prompt real de `modelo.decidir_proxima_acao_ui`. Cada modelo recebeu a mesma captura PNG de 1280×800 com a grade 10×10 que o agente usa. O teste mediu tempo de parede até devolver uma ação JSON e converteu célula + offsets para pixels. Acerto significa que o ponto caiu dentro do elemento pedido. Nenhum clique foi executado no desktop.

| Modelo e raciocínio | Cliques corretos | Média por decisão | Mediana |
| --- | ---: | ---: | ---: |
| GPT-6 Luna · alto | 5/5 | 8,24 s | 8,31 s |
| GPT-6 Luna · máximo | 5/5 | 7,96 s | 7,55 s |
| GPT-6 Sol · médio | 5/5 | **6,37 s** | **6,81 s** |
| GPT-6 Sol · alto | 5/5 | 8,15 s | 8,14 s |

As cinco telas incluíram um botão Salvar junto de Cancelar, uma lista de resultados parecidos, uma data compacta, um controle pequeno e um ícone de lápis de 25×25 px ao lado de dois outros ícones. A imagem de teste foi inspecionada antes das medições. A primeira rodada usou uma fonte ausente no Fedora; esses resultados foram descartados e os cinco casos foram repetidos com uma fonte existente e ícones desenhados diretamente.

Na verificação anterior ao clique, o marcador magenta foi colocado de propósito no **X** ao lado do lápis. O Sol médio corrigiu para o lápis em **2/2** tentativas (6,45 s e 5,75 s). O Luna máximo tentou corrigir, mas apontou para a linha acima/abaixo em **0/2** (8,80 s e 11,69 s). Esse teste pesa mais na escolha porque um clique no lugar errado é o problema relatado pelo usuário.

**Escolha aplicada:** GPT-6 Sol com raciocínio médio para decidir ações e auditar a conclusão. O modelo do chat permanece independente. O Astra não foi testado, para preservar o limite solicitado. Os dados brutos estão em `agente_visual_gpt6_2026-09-30.jsonl`; o script reproduzível é `testes/benchmark_agente_visual_gpt6.py`.

Limite da medição: são telas sintéticas locais, com uma amostra pequena por configuração. A latência inclui o OmniRoute e varia com rede/carga. A medição demonstra acerto de coordenadas e correção de alvo nesses cenários; tarefas completas em sites/apps reais ainda exigem validação de uso.
