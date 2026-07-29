---
inclusion: always
---

# Projeto Emily — contexto base

Assistente pessoal em Python para Windows, criada pelo Vitor. Roda no PC dele com voz,
visão de tela, automação do sistema operacional, integração com Discord e controle remoto
pelo celular.

Fale em português brasileiro com o Vitor. O código, comentários e nomes de função do
projeto são em português — **mantenha essa convenção** ao escrever código novo.

## Plataforma e restrições de ambiente

- **Windows 11.** O projeto é Windows-only e não roda em Linux/macOS: usa `mss`,
  `pyautogui`, `keyboard`, `pygetwindow`, `ctypes.windll`, caminhos do registro e
  `SHFileOperation`.
- **Hardware:** i5-8400 + RX580 8GB. **Não sugira rodar LLM local.** Não cabe modelo com
  visão em 8GB de VRAM AMD via ROCm no Windows, e a latência inviabilizaria o agente de UI.
  A estratégia é sempre API.
- Empacotamento via `build_emily.py` (PyInstaller).
- **Não existe `requirements.txt`** apesar do README mandar rodar `pip install -r requirements.txt`.

## Mapa de arquivos

| Arquivo | Responsabilidade | Linhas |
|---|---|---|
| `automacao.py` | Automação do SO: abrir/fechar apps, arquivos, pastas, Steam, modos, speedruns | 6227 |
| `modelo.py` | **Camada de LLM** + personalidade + prompts. Ponto central da migração | 1658 |
| `interface.py` | UI em PyQt | 1497 |
| `main.py` | Orquestração, loops de voz e visão, roteamento de intenção | 1405 |
| `agente_ui.py` | Agente de UI multi-passo: controla o PC por visão | 888 |
| `discord_bot.py` | Bot de Discord (texto + call de voz) | 807 |
| `build_emily.py` | Build PyInstaller | 350 |
| `memoria.py` | Memória persistente e extração de fatos | 338 |
| `servidor.py` | Flask para controle pelo celular via ngrok | 292 |
| `voz.py` | TTS e STT | 278 |
| `notificacoes.py` | Notificações | 252 |
| `visao.py` | Captura de tela e **grade de precisão** | 196 |
| `pesquisa.py` | Busca na internet | 189 |
| `intencoes.py` | Detecção de intenção por palavra-chave | 152 |

⚠️ **`main.py` importa `gerador_imagem` e `agente_jogo`, que não estão no repositório.**
Isso é **intencional**: os dois estão no `.gitignore` sob "funcionalidades em desenvolvimento
(ainda não prontas)". Existem apenas na máquina do Vitor. Consequência prática: o `main.py`
roda no PC dele, mas **um clone limpo do repo não sobe**. Ao trabalhar aqui, tratar esses
dois módulos como caixa-preta existente — não recriar, não remover os imports.

## Camada de LLM

Tudo passa por **`_chamar_llm()` em `modelo.py:214`**. É o único ponto de saída para o
provedor — é lá que a migração acontece. `automacao.py:38` importa essa função privada
diretamente (`from modelo import _chamar_llm as _modelo_llm`), e `memoria.py` usa o wrapper
`chamar_llm_simples()` (`modelo.py:298`).

Modelos declarados em `modelo.py:178-180`. Os nomes `OLLAMA_TEXT_MODEL` e
`OLLAMA_VISION_MODEL` são resquício de uma fase antiga com Ollama — hoje apontam para
Bedrock. Há um `/no_think` no `system_prompt` (`modelo.py:171`) que era do Qwen e não faz
nada no Claude.

### Todos os pontos de chamada

**Precisam de visão (VLM):**

| Função | Local | Observação |
|---|---|---|
| `triar_tela` | `modelo.py:337` | SIM/NAO, `max_tokens=16` |
| `triar_tela_jogo` | `modelo.py:391` | SIM/NAO, `max_tokens=16` |
| `analisar_tela_jogo` | `modelo.py:438` | |
| `analisar_tela` | `modelo.py:484` | |
| `analisar_sequencia_telas` | `modelo.py:511` | envia várias imagens |
| `analisar_tela_com_pergunta` | `modelo.py:541` | |
| `ler_instrucoes_da_tela` | `modelo.py:560` | |
| `traduzir_tela` | `modelo.py:589` | |
| `decidir_proxima_acao_ui` | `modelo.py:629` | **núcleo do agente de UI** |
| `analisar_tela_monitoramento` | `modelo.py:762` | |
| `avaliar_contexto_canal` | `modelo.py:937` | visão só quando há imagem |

**Só texto:**

| Função | Local | Tipo |
|---|---|---|
| `conversar_stream` | `modelo.py:1171` | conversa principal, streaming — **onde a personalidade importa** |
| `_interpretar_com_llm` | `automacao.py:3341` | comando → JSON |
| `avaliar_intencao_fallback` | `modelo.py:1585` | classificador de intenção |
| `_llm_confirma_visao` | `modelo.py:1383` | SIM/NAO, `max_tokens=5` |
| `triagem_mensagem_discord` | `modelo.py:1300` | SIM/NAO |
| `responder_mensagem_discord` | `modelo.py:1335` | |
| `quebrar_resposta_discord` | `modelo.py:1010` | decide se divide mensagem |
| `gerar_trollagem_discord` | `modelo.py:1271` | |
| `extrair_fatos` | `modelo.py:1106` | memória |
| `extrair_prompt_imagem` | `modelo.py:903` | reescreve prompt em inglês |
| `gerar_frase_acao` | `modelo.py:1515` | frase de espera, `max_tokens=40` |
| `gerar_frase_analisando_tela` | `modelo.py:1557` | frase de espera, `max_tokens=40` |
| dedup / extração de memória | `memoria.py:87` e `memoria.py:272` | via `chamar_llm_simples` |

## Drivers de custo e de requisições

Números medidos, não estimados. Imagem no Claude ≈ `largura × altura / 750`, então
1280×720 ≈ **1.229 tokens**.

1. **`loop_visao` (`main.py:1292`) — o maior de longe.** Ciclo de ~4,5s (`sleep(3)` +
   captura de 2 frames + latência) chamando `triar_tela` com imagem cheia. Dá ~13
   chamadas/min ≈ 1,33M tokens de input/hora. No Sonnet a $3/M isso era **~$4/hora de
   monitoramento**, e a grande maioria das respostas é `NAO`.
   Existe `COOLDOWN_VISAO = 10` (`main.py:94`) que só pausa após uso do usuário.

2. **`_interpretar_com_llm` (`automacao.py:3341`).** O `system_content` das linhas
   3347–3756 tem 410 linhas / 28.624 caracteres ≈ **8.178 tokens**, reenviados integralmente
   a cada comando. Existe cache de resultado (`_llm_cache_get`/`_llm_cache_set`) que só
   ajuda em mensagens idênticas. O prompt é 100% estático → candidato ideal a prompt caching.

3. **`decidir_proxima_acao_ui` (`modelo.py:629`).** ~5.600 tokens de input por passo
   (prompt de 23 regras + personalidade + memória + imagem), com `MAX_PASSOS = 50`
   (`agente_ui.py:55`) e retry de 3x quando o JSON vem inválido.

4. **Chamadas que não deveriam existir.** `gerar_frase_acao` e
   `gerar_frase_analisando_tela` usam um modelo de fronteira para produzir frases de
   enchimento tipo "Deixa eu ver..." — além do custo, adicionam um round-trip de rede
   **antes de cada ação**, o que piora a latência percebida de uma assistente de voz.
   `quebrar_resposta_discord` gasta uma chamada para decidir se divide uma mensagem.

5. **`max_tokens` mal calibrados.** `triagem_mensagem_discord` usa 500 para devolver
   SIM/NAO e manda a personalidade inteira (~1.361 tokens) junto. `extrair_fatos` usa 2048
   para devolver duas linhas.

## Dívida técnica conhecida

- 🔴 **Zero tratamento de erro de transporte.** Não existe retry, backoff nem tratamento de
  `429`/throttling em `_chamar_llm`. Todas as chamadas estão embrulhadas em
  `except: return None` ou `except: return ""`, então falha de rede ou rate limit vira
  **falha silenciosa** — a Emily simplesmente para de responder sem log útil. Isso é a
  causa mais provável de bug difícil de diagnosticar no projeto.
- 🔴 **`memoria.json` está exposto no repositório público, com dados pessoais do Vitor.**
  Atenção à pegadinha: o arquivo **já está listado no `.gitignore`**, mas continua
  **rastreado pelo git** (`git ls-files` confirma) — `.gitignore` não desrastreia arquivo já
  commitado. Ou seja, a proteção que parece existir não está funcionando. Corrigir exige
  `git rm --cached memoria.json` + commit, e reescrita de histórico para apagar as versões
  antigas. Reescrever histórico é destrutivo: **só fazer com autorização explícita do Vitor.**
  **Nunca reproduza o conteúdo desse arquivo em código, documentação, prompt ou mensagem.**
- 🟡 **Grade de precisão construída e nunca ligada.** `visao.py` tem
  `capturar_tela_com_grade()` (linha 94) e `celula_para_centro()` (linha 66), e
  `agente_ui.py` já aceita a ação `clicar_celula` (linhas 252 e 258). Mas nada disso é
  chamado: o `agente_ui` usa `visao.capturar_tela()` e o prompt pede `x, y` cru em
  1280×720. Ligar a grade é a alavanca mais forte para o agente de UI funcionar com um
  modelo menos capaz.
- 🟡 O parâmetro `vision=` de `_chamar_llm` é aceito e nunca usado.
- 🟡 `intencoes.py` tem código morto: um `return restante` órfão no fim do arquivo com
  variável inexistente, e código inalcançável depois do `return` em `confirma_encerramento`.
- 🟡 `from openai import OpenAI` em `modelo.py` está importado e não usado.

## Personalidade da Emily

O texto integral vive em `modelo.py` nas constantes `EMILY_PERSONALIDADE`,
`EMILY_PERSONALIDADE_DISCORD`, `EMILY_PERSONALIDADE_DISCORD_CALL` e
`EMILY_PERSONALIDADE_VISAO`. É o coração do projeto para o Vitor — **qualquer mudança de
modelo é avaliada primeiro por "a personalidade segurou?"**.

Restrições que importam em engenharia (o prompt as trata como absolutas):

- Português brasileiro coloquial, sempre.
- **Sem markdown, sem negrito, sem itálico, sem listas, sem headers.**
- **Sem emoji e sem asteriscos de ação.**
- Sem saudação formal no início ("Claro!", "Olá!").
- Tom tsundere, alternando entre agressivo e amável de forma imprevisível.
- Respostas curtas por padrão: comentário casual = uma ou duas frases.
- Variar a estrutura e o início das frases; nunca repetir o mesmo padrão.
- A variante de Discord usa abreviação de chat ("vc", "pq", "tb", "kkk").
- A variante de call de voz **não** usa abreviação, porque vai para TTS.

`automacao.py:10` também importa `EMILY_PERSONALIDADE`, então a constante é compartilhada
entre módulos.

## Convenções ao trabalhar neste repo

- Código, nomes e comentários em português.
- Não adicionar testes automatizados sem o Vitor pedir.
- Segredos vêm de `.env` via `python-dotenv` (`load_dotenv()` no topo de `modelo.py`).
  Nunca hardcode chave de API, nunca imprima o valor de variável de ambiente em log.
- Ao mexer em prompt de personalidade, preservar as restrições da seção acima.
