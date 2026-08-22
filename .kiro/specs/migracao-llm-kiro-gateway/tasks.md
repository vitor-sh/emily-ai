# Plano de Implementação: migracao-llm-kiro-gateway

Cada task é um incremento funcional e demonstrável. A ordem derruba risco cedo: o gateway
é validado isolado antes de qualquer código da Emily mudar, e a rota de conversa migra sozinha
antes das outras oito.

---

- [x] 1. Configurar e validar o gateway isolado, sem tocar no código da Emily
  - Criar `kiro_gateway/.env` com as quatro chaves críticas (`SERVER_HOST=127.0.0.1`,
    `FAKE_REASONING=false`, `WEB_SEARCH_ENABLED=false`, `AUTO_TRIM_PAYLOAD=true`), mais
    `PROXY_API_KEY` (senha nova), `KIRO_CREDS_FILE` apontando para o cache do Kiro IDE e
    `LOG_LEVEL=WARNING`
  - Instalar as dependências do gateway e confirmar que o único cruzamento com o
    `requirements.txt` da Emily é `python-dotenv`, já presente
  - Subir o gateway à mão e confirmar `GET /health`
  - Escrever `_teste_gateway_modelos.py`: lista `GET /v1/models` e registra os IDs exatos
    disponíveis na conta, confirmando `claude-opus-5` e `claude-sonnet-5` e verificando se
    existe algum Haiku para as rotas baratas
  - Testar `normalize_model_name` do gateway com os nomes novos, garantindo que passam sem
    precisar de alias
  - Escrever `_teste_gateway_smoke.py`: uma chamada `stream=True` medindo tempo até o
    primeiro pedaço, e uma chamada com imagem base64 confirmando visão
  - _Requisitos: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 6.4, 7.1_
  - _Demo: tokens do Claude chegando um a um no terminal, vindos do plano pago, e a lista
    real de modelos da conta impressa com os IDs confirmados_

  **Notas de execução (o que a Task 1 descobriu):**

  - **`profileArn` era um bloqueador não previsto no design.** A conta do Vitor é
    `authMethod: IdC`, `provider: Enterprise`, e NENHUM dos dois arquivos de cache
    (`kiro-auth-token.json` e o de nome com hash) traz `profileArn`. O gateway usa
    `auth_manager.profile_arn or PROFILE_ARN or ""` e não descobre sozinho, então todo
    `POST /v1/chat/completions` voltava `HTTP 400 profileArn is required for this request`
    enquanto o `GET /v1/models` funcionava normalmente. Resolvido varrendo os logs e
    configs do Kiro IDE (`_teste_achar_arn.py` achou dois ARNs) e testando qual respondia
    (`_teste_arn_qual_funciona.py`). O ativo é o que também aparece em `profile.json`.
    Está gravado em `PROFILE_ARN` no `kiro_gateway/.env`.
  - **O `/v1/models` não é autoridade, confirmado nos dois sentidos.** A conta lista 13
    modelos e NENHUM deles é `claude-sonnet-5` ou `claude-opus-5` — mas os dois respondem
    normalmente na chamada real, porque o `ModelResolver` é pass-through. A divisão de
    modelos aprovada segue sem alteração. O `llm.py` já documentava o caso inverso
    (modelo listado que devolve 404).
  - **`claude-haiku-4.5` existe na conta.** É o modelo das rotas baratas:
    `EMILY_KIRO_MODELO_BARATO="claude-haiku-4.5"`. O `auto` NÃO está disponível (só
    `auto-kiro`, o alias que o gateway cria para evitar conflito com o Cursor).
  - **Latência medida:** primeira chamada a `claude-sonnet-5` levou 4,98s (fria), depois
    1,75s a 2,8s nas seguintes. Streaming: 6 pedaços, **3,36s até o primeiro pedaço**,
    3,64s no total. Visão: 2,26s e 1.343 tokens de prompt numa imagem 480x160.
  - **Ponto de atenção para a Task 2:** 3,36s até o primeiro pedaço é a latência que o
    Vitor sente antes de a Emily começar a falar. Precisa ser comparado com o número do
    GLM no NIM antes de declarar a rota `conversa` migrada. Se for regressão grande,
    `claude-haiku-4.5` na rota `conversa` é a alternativa a medir.
  - **Nenhuma dependência nova foi instalada.** `fastapi`, `uvicorn`, `httpx`, `loguru`,
    `tiktoken` e `pydantic` já estavam no ambiente. Faltam só `pytest` e `hypothesis`,
    que a Task 3 vai precisar.
  - **`.gitignore` já cobre os segredos do gateway** (`.env`, `credentials.json`,
    `state.json`, `*.log`, `debug_logs/`) — antecipado da Task 10 para não deixar
    credencial rastreável no repositório.

- [x] 2. Registrar o provedor `kiro` no `llm.py` e migrar só a rota de conversa
  - Criar `ProvedorKiro(ProvedorOpenAI)` sobrescrevendo `chamar()` (não `_obter_cliente()`,
    que é cacheado e nunca religaria um gateway morto no meio da sessão)
  - Traduzir `ErroGateway` em `ErroConfiguracao` preservando a causa, para o retry de
    `chamar()` não repetir
  - Registrar `PROVEDORES["kiro"]` com `base_url` de `EMILY_KIRO_URL`, chave
    `KIRO_PROXY_API_KEY` e timeout de 300s por causa das rotas de visão
  - Acrescentar `KIRO_PROXY_API_KEY`, `EMILY_KIRO_URL`, `EMILY_KIRO_TIMEOUT` e
    `EMILY_KIRO_RPM` ao `.env` da Emily
  - Trocar apenas a rota `conversa` para `provedor="kiro"` e `MODELO_KIRO_CONVERSA`
  - Validar com `python llm.py`: seção [3] passando na rota de conversa e [3b] mostrando a
    Emily no personagem
  - Validar conversa real com `EMILY_TOOL_CALLING=0`, isolando o caminho de streaming puro
  - _Requisitos: 2.1, 2.4, 2.5, 4.1, 4.2, 6.5, 6.6_
  - _Demo: conversa por voz com a Emily respondendo pelo Claude Sonnet 5, com o TTS começando
    a falar antes de a resposta terminar_

  **Notas de execução:**

  - **`ProvedorKiro` tolera a ausência do `gateway.py`.** O módulo só existe a partir da
    Task 3, então `_garantir_gateway()` faz import lazy dentro de try/ImportError e avisa
    UMA vez ("gateway.py não encontrado: suba à mão"). Isso mantém o `llm.py` importável e
    o `python llm.py` funcionando, e é o que permitiu validar a Task 2 antes da Task 3.
  - **`RPM_KIRO=30` como balde próprio.** O limitador é por provedor. O plano pago não
    publica teto de RPM — o balde existe contra rajada acidental (o laço de triagem dispara
    de várias threads), não para respeitar limite conhecido.
  - **A latência assustou e depois se explicou.** Na pergunta longa ("explica o que é uma
    lista em Python"), o Claude levou 16,69s até o primeiro pedaço. Parecia regressão
    grave contra os 3,36s medidos na Task 1. Mas o GLM-5.2 no NIM, na MESMA pergunta,
    levou 26,22s. Ou seja, a migração **ganha 9,53s** ali. E no caminho real de conversa
    (teste [D], pergunta curta via `conversar_stream`), o total foi 3,56s com duas frases
    já na fila do TTS. Conclusão: TTFB cresce com o tamanho da resposta nos dois
    provedores; não é problema do gateway.
  - **Hipótese descartada com leitura de código:** suspeitei que `reasoning_effort="none"`
    estivesse LIGANDO o thinking, como a armadilha do `chat_template_kwargs` no NIM que já
    está documentada no `llm.py`. É o contrário: em
    `converters_openai.extract_thinking_config_from_openai`, `"none"` devolve
    `ThinkingConfig(enabled=False)` e é a AUSÊNCIA do parâmetro que devolve
    `enabled=True` com budget default. Ou seja, `RACIOCINIO_DESLIGADO` é exatamente o
    valor certo para o gateway, e mandar nada seria o erro.
  - **Personalidade passou intacta.** Resposta do Claude à provocação "deletei a pasta
    errada": *"Oi Vitor, calma aí. Deletou de onde, lixeira ainda tem ela ou já foi de
    vez? Me diz o caminho e se foi terminal ou pelo explorador que eu te ajudo a ver se
    rola recuperar."* Zero markdown, zero emoji, zero abertura proibida, tsundere no tom.
    O medo de o endpoint do Q Developer achatar a persona não se confirmou.
  - **`conversar_stream` sem alteração nenhuma.** Histórico foi de 0 para 2 mensagens, duas
    frases entraram na fila de TTS, `precisa_pesquisar` é heurística pura e
    `precisa_ver_tela` só chama LLM quando palavras de tela aparecem — então uma conversa
    comum exercita só a rota `conversa`, o que manteve a Task 2 isolada de verdade.
  - **Diagnóstico completo (`python llm.py`) ficou para a Task 5**, quando `diagnosticar()`
    é estendido. Rodá-lo agora exercitaria as sete rotas ainda no NIM e capturaria a tela
    sem necessidade. A rota migrada foi validada direto, que é o que as seções [3] e [3b]
    fariam.

- [x] 3. Criar o módulo `gateway.py` com ciclo de vida completo
  - Implementar `esta_no_ar()`, `garantir()`, `derrubar()`, `estado()` e `ErroGateway` com
    `motivo`, `detalhe` e `frase()`, conforme as pós-condições do design
  - Implementar `_ambiente_do_gateway()` removendo as chaves reservadas e os prefixos
    `KIRO_`/`ACCOUNT_`, para o `.env` da Emily não vencer silenciosamente o do gateway
  - Implementar `_interpretador()` na ordem `EMILY_GATEWAY_PYTHON` → `sys.executable` (se não
    frozen) → PATH, com `MOTIVO_SEM_PYTHON` quando nada resolve
  - Implementar `_classificar_morte()` lendo a cauda do log do subprocesso
  - Serializar com `RLock`, honrar `TTL_HEALTH` no caminho quente e registrar `derrubar` em
    `atexit` uma única vez
  - Testes de propriedade com `hypothesis`, sem rede, dublando `esta_no_ar` e `Popen`:
    Property 1 (um gateway sob concorrência), Property 2 (retorno implica no ar),
    Property 3 (gateway alheio sobrevive), Property 4 (ambiente não vaza)
  - _Requisitos: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 10.2_
  - _Demo: `python -c "import gateway; gateway.garantir()"` sobe o proxy sozinho, sem janela
    de terminal extra, e o processo desaparece ao sair_

  **Notas de execução:**

  - **42 testes de propriedade passando** em `testes/test_gateway_propriedades.py`, cobrindo
    as Properties 1 a 4 mais o `_interpretador` (Requisito 10.2) e os casos de borda do
    `garantir()`. Nenhum toca rede nem sobe processo: `esta_no_ar` e `_subir` são dublados.
  - **Ciclo real validado com `python gateway.py`**, nas duas metades. Com o gateway já no
    ar: `dono=False`, nada subido, nada derrubado (Property 3 na prática). Com a porta
    livre: subiu em 5,08s, `dono=True`, segunda chamada em 0,0000s pelo cache de TTL,
    derrubou, e o `derrubar()` repetido não levantou exceção.
  - **BUG REAL ENCONTRADO E CORRIGIDO — o gateway morria no boot.** O primeiro `python
    gateway.py` com a porta livre falhou com `UnicodeEncodeError`: o
    `print_startup_banner` do gateway imprime o emoji 👻, e como redirecionamos a saída do
    subprocesso para arquivo (necessário para o `_classificar_morte` ler a cauda do log), o
    stdout do filho deixa de ser terminal e o Python passa a usar a codificação local —
    cp1252 nesta máquina. Corrigido impondo `PYTHONIOENCODING=utf-8` e `PYTHONUTF8=1` no
    ambiente do filho. **Este bug atingiria a Emily empacotada de qualquer forma**, que roda
    sem console nenhum, então foi sorte encontrá-lo aqui e não na Task 10.
  - **A classificação de erro se provou no caso real.** A falha acima chegou como
    `ErroGateway(nao_subiu)` com a frase *"Vitor, meu gateway não subiu. Dá uma olhada no
    console que o erro tá lá"* e o traceback completo no detalhe. Foi exatamente o
    comportamento projetado: motivo declarado, frase falável, causa no console.
  - **O hypothesis achou uma contradição na Property 4** e ela foi refinada, não contornada.
    O caso `base={'PYTHONUTF8': ''}` mostrou que "preserva o valor de todas as chaves não
    reservadas" briga com "impõe UTF-8". Surgiu daí a terceira categoria de chave:
    reservada (removida para o `.env` do gateway poder valer), **imposta** (ditada por nós,
    em `AMBIENTE_IMPOSTO`), e o resto (preservado). O `design.md` foi atualizado.
  - **Health check usa `urllib` da stdlib**, não httpx nem requests. É caminho quente
    (roda em toda chamada de LLM, mesmo com o TTL) e um GET em localhost não justifica
    dependência de terceiro nem o custo de construir cliente.
  - **Saída do subprocesso vai para arquivo, não para PIPE.** Com PIPE, ninguém lê o buffer
    durante o polling de health e um gateway falante travaria quando o buffer enchesse. O
    arquivo também sobrevive ao processo, que é o que o `_classificar_morte` precisa.
  - **`pytest 9.1.1` e `hypothesis 6.165.1` instalados** como dependência de
    desenvolvimento.

- [x] 4. Ligar o auto-start e fazer a falha ser audível
  - Chamar `gateway.garantir()` no boot do `main.py`, antes de `automacao.inicializar()`, em
    try/except que não impede a Emily de subir
  - Chamar `garantir()` lazy dentro de `ProvedorKiro.chamar`, para religar um gateway que
    morreu no meio da sessão
  - Implementar `_frase_de_falha_de_gateway()` em `modelo.py` inspecionando `__cause__`, com
    import lazy de `gateway`, e usar em `conversar_stream` e `conversar_com_ferramentas`
  - Validar sabotando a credencial do Kiro (frase de login expirado) e ocupando a porta 8000
    com outro processo (frase de porta ocupada)
  - _Requisitos: 4.3, 4.4, 4.5, 4.6, 4.7_
  - _Demo: a Emily executa e o gateway sobe junto, invisível; com a credencial sabotada ela
    avisa por voz exatamente qual é o problema e continua funcionando no resto_

  **Notas de execução:**

  - **7 cenários validados** em `_teste_task4_falha_audivel.py`: credencial expirada, porta
    ocupada, pasta ausente, falha que não é de gateway, ausência de retry, gateway real
    funcionando, e sabotagem real de porta. Todos OK.
  - **`_frase_de_falha_de_gateway` caminha a cadeia de exceções** (`__cause__` e
    `__context__`, até 6 níveis) em vez de olhar só um nível. A cadeia esperada é
    `ErroConfiguracao -> ErroGateway`, mas depender da profundidade seria frágil.
  - **O retry se comportou exatamente como projetado, nos dois sentidos.** Falha de gateway:
    provedor acionado 1x, sem retry (porque vira `ErroConfiguracao`). Falha de transporte
    comum: 4 tentativas com backoff e frase genérica no fim. É a distinção que faz uma
    credencial expirada avisar em 2 segundos em vez de deixar a Emily muda por minutos.
  - **Auto-start provado por acidente, o que foi melhor que o teste planejado.** O cenário
    [F] rodou com o gateway derrubado (a Task 3 o encerrou), e o `garantir()` lazy dentro do
    `ProvedorKiro.chamar` subiu o proxy no meio do teste, respondeu a conversa, e o `atexit`
    derrubou ao sair. Ciclo completo sem ninguém pedir.
  - **A sabotagem real de porta encontrou uma fragilidade e ela foi corrigida.** Com a porta
    tomada, o `garantir()` não detectava `porta_ocupada`: seguia em frente, tentava subir,
    falhava, e classificava como `nao_subiu` — dando a frase inútil "olha o console" em vez
    da acionável "tem outra coisa usando a porta". Duas causas:
    1. **No teste:** o impostor era irrealista. Com `SO_REUSEADDR` o Windows PERMITE dois
       sockets na mesma porta (diferente do Linux), e com `listen(1)` sem nunca chamar
       `accept()` o backlog enchia com a conexão do health check, fazendo a sondagem
       seguinte ser recusada. Corrigido: sem `SO_REUSEADDR`, backlog de 16, e thread
       drenando o accept — como qualquer servidor real faz.
    2. **No código:** o `_porta_ocupada()` é best-effort e a classificação dependia só da
       cauda do log. O `_classificar_morte()` agora consulta a porta antes de desistir: se
       está ocupada agora, a causa provável é essa. Rede de segurança para a detecção que
       falhou.
  - **`main.py` sobe o gateway antes de `automacao.inicializar()`**, em try/except que
    engole qualquer exceção de propósito: emudecer interface, voz, Discord e automação por
    causa do LLM seria pior que a falha. A frase vai por `voz.falar`, e o `voz.falar` está
    em try/except próprio — se nem falar der, o console ainda tem o motivo.

- [x] 5. Migrar as rotas de texto restantes e validar cada consumidor
  - Migrar `classificador`, `discord`, `comando` e `extracao` para o provedor `kiro`
  - Medir a rota `classificador` com `max_tokens=16` em amostras reais de SIM/NAO; se voltar
    string vazia, aumentar o `max_tokens` da rota ou endurecer a instrução de formato, e
    registrar a medição em comentário junto aos números históricos do `llm.py`
  - Validar `memoria.py` (deduplicação semântica e extração de fatos), `automacao.py` (rota
    `comando` devolvendo JSON parseável e o resumo de página lida), `intencoes.py` e
    `discord_bot.py`
  - Estender `diagnosticar()` para exercitar todas as rotas da tabela ativa sem interromper
    nas falhas
  - _Requisitos: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 11.1, 11.2_
  - _Demo: a Emily classifica intenção, interpreta comando, grava fato na memória e responde
    no Discord, tudo pelo Kiro, com o diagnóstico verde nas rotas de texto_

  **Notas de execução:**

  - **O risco do `max_tokens=16` foi medido ANTES de migrar, e não se materializou.**
    `_teste_task5_orcamento_curto.py`, 3 amostras por combinação, temperatura 0: 24 de 24
    respostas limpas, zero vazias, decisão correta em todas. Cobriu os três orçamentos
    curtos que a Emily usa de verdade — 8 (`_llm_confirma_visao`), 10 (dedup do
    `memoria.py`) e 16 (default da rota) — nos dois modelos. Inclui o caso NEGATIVO ("me
    conta uma piada" -> NAO), que é o que pega classificador viciado em dizer sim.
    Funciona porque o `RACIOCINIO_DESLIGADO` manda `reasoning_effort='none'` e o gateway
    desliga o thinking: nenhum token é gasto antes da resposta. Requisito 5.3 não precisou
    ser acionado, e a medição está registrada em comentário no `llm.py`.
  - **Divisão de modelo dentro das rotas de texto.** `classificador` foi para
    `claude-haiku-4.5` porque é a rota que mais dispara (cada mensagem que mencione tela
    passa por ela). `comando`, `extracao` e `discord` ficaram no `claude-sonnet-5`: no
    `comando` um JSON malformado vira ação errada na máquina do Vitor, e no `discord` a
    personalidade importa tanto quanto na voz.
  - **Consumidores validados um por um** (`_teste_task5_consumidores.py`), porque cada um
    tem expectativa de formato diferente: classificador 3/3 incluindo o negativo; extração
    devolveu 2 fatos corretos ("Possui uma RTX 5090", "Joga Elden Ring diariamente");
    comando devolveu JSON limpo, sem cerca de código; Discord respondeu *"sei nao joao,
    aqui n tenho como saber isso kkk olha um app de previsão aí"* — abreviação e "kkk" no
    lugar, sem markdown nem emoji.
  - **A deduplicação semântica passou a funcionar de verdade.** O `_fato_ja_conhecido_llm`
    respondeu True para "curte Elden Ring" contra "gosta de jogar Elden Ring", e False para
    "tem um cachorro". Vale notar que, segundo os próprios comentários do `llm.py`, essa
    função **nunca rodou** antes da existência do `chamar_llm_simples` — o call site morria
    com AttributeError engolido por try/except.
  - **`intencoes.py` não usa LLM nenhum.** Só listas de palavra-chave
    (`PHRASES_*`/`WORDS_*`). O Requisito 5.7 é satisfeito por não haver nada a migrar ali —
    achado que vale registrar para ninguém procurar de novo.
  - **`diagnosticar()` estendido** com a seção [0] de estado do gateway (vem primeiro porque
    é pré-requisito de todas as rotas do provedor `kiro`) e com o resumo de rotas por
    provedor mais detecção de rota apontando para provedor não registrado. O relatório
    ganhou as chaves `gateway`, `rotas_por_provedor` e `rotas_orfas`.
  - **`python llm.py` verde nas 8 rotas.** Kiro: classificador 1,73s, discord 2,30s,
    extracao 2,48s, comando 3,14s, conversa 11,19s (a primeira, que inclui os ~5s de boot
    do gateway). NVIDIA, ainda não migradas: triagem_visual 0,59s, agente_ui 0,94s,
    visao 1,47s. Nenhum parâmetro de raciocínio rejeitado. Amostra de personalidade sem
    degradação — ela usou "Aiai Vitor", que é uma das expressões esporádicas do prompt.

- [x] 6. Migrar as rotas de visão com medição comparativa
  - Migrar `visao` e `triagem_visual` para o provedor `kiro`
  - Escrever `_bench_visao.py` com a metodologia já documentada no `llm.py`: captura 640x360,
    descrição em português, triagem SIM/NAO, medindo latência e tokens de prompt
  - Atualizar o bloco de comentário do `llm.py` que registra os números do nemotron e dos
    llama, acrescentando os números do Claude
  - Validar `triar_tela` e `triar_tela_jogo` com capturas controladas: SIM para evento
    marcante, NAO para cenário rotineiro
  - _Requisitos: 7.1, 7.2, 7.3, 7.4_
  - _Demo: "Emily, o que tá na minha tela?" respondido pelo Claude no estilo dela, com a
    tabela de latência e tokens atualizada no código_

  **Notas de execução:**

  - **O benchmark mediu os três modelos na MESMA captura, na mesma execução** — comparar
    telas diferentes não diria nada. Resultado (`_bench_visao.py`, 2 amostras, 640x360):

    | modelo | descrição | triagem | leitura |
    |---|---|---|---|
    | nvidia/nemotron-nano-12b-v2-vl | 4,62s | 0,58s | **ERRADA** |
    | claude-sonnet-5 | 10,09s | 2,63s | correta |
    | claude-haiku-4.5 | 3,34s | 2,12s | correta |

  - **O que decidiu a migração não foi latência, foi a leitura.** Na mesma tela (VS Code com
    o `CONTRIBUTING.md` do kiro-gateway aberto), o nemotron alucinou *"um chat em tempo real
    com vários usuários discutindo melhorias para uma plataforma de contribuição de
    código"* — leu o texto do arquivo e concluiu que era conversa entre pessoas. Os dois
    Claude descreveram certo, e o Sonnet nomeou o projeto. Para a Emily isso é a diferença
    entre comentar a tela e inventar a tela.
  - **Mudança de `raciocinio` que era fácil passar batido.** As rotas de visão no NIM usavam
    `RACIOCINIO_NORMAL`, que ali significa "não manda parâmetro nenhum" porque o nemotron
    rejeita `reasoning_effort='none'` com 400. No gateway do Kiro a semântica é INVERTIDA:
    `'none'` desliga o thinking e a ausência do parâmetro liga com budget default. Deixar
    `NORMAL` faria o Claude pensar antes de descrever a tela. As duas rotas foram para
    `RACIOCINIO_DESLIGADO`, e o comentário no `llm.py` explica a inversão.
  - **`visao` no Sonnet, `triagem_visual` no Haiku.** O Haiku lê certo e é 3x mais rápido na
    descrição (3,34s contra 10,09s), então está registrado no comentário como a troca a
    fazer se os 10s incomodarem — é uma linha de `.env` (`EMILY_KIRO_MODELO_VISAO`).
  - **O que a migração PERDEU, registrado honestamente no código:** a triagem era 0,58s e
    grátis no free tier do NIM; agora é 2,12s e consome crédito por disparo. Ela roda em
    laço durante o monitoramento de tela e de jogo, então é a primeira candidata a voltar
    pro nemotron se o crédito do mês apertar.
  - **Bloco de comentário do `llm.py` atualizado**, não substituído: a tabela histórica do
    NIM continua lá (é o registro de por que o nemotron foi escolhido), com a medição da
    migração logo abaixo.
  - **Validação funcional com gabarito** (`_teste_task6_visao.py`), usando capturas
    GERADAS em vez da tela real, porque teste sem resposta conhecida não verifica acerto:
    triagem deu SIM para erro fatal, NAO para bloco de notas, SIM para "VOCE MORREU", NAO
    para gameplay normal. A análise de tela leu "R$ 1.234,56" e respondeu no tom dela:
    *"Nada de milionário, mas também não é motivo pra pânico ainda."*
  - **Property 11 verificada sem rede:** o corpo montado pelo `ProvedorKiro` preserva o
    media type (`data:image/jpeg;base64,`) e os bytes base64 idênticos aos da entrada.

- [x] 7. Separar `agente_jogo` de `agente_ui` e migrar as duas
  - Criar a rota `agente_jogo` nas duas tabelas e a constante `ROTA_AGENTE_JOGO` em
    `modelo.py`
  - Trocar em `agente_jogo.py` a chamada que hoje usa `ROTA_AGENTE_UI` para a rota nova
  - Migrar `agente_ui` para `MODELO_KIRO_AGENTE_UI` (Opus 5)
  - Escrever `_bench_grade.py`: grade 10x10 desenhada na captura, 12 amostras, elementos
    conhecidos, contando acerto de linha e de coluna; comparar com os 12/12 do
    llama-3.2-90b registrados no `llm.py`
  - Se o resultado for pior que o histórico, manter `agente_ui` no provedor anterior e
    registrar o motivo com os números medidos
  - Contar chamadas por minuto numa sessão de monitoramento de jogo, para avaliar consumo
  - _Requisitos: 6.2, 6.3, 7.5, 7.6, 7.7_
  - _Demo: o agente de UI aponta e clica no lugar certo com Opus 5, o monitoramento de jogo
    roda no Sonnet 5, e a contagem de chamadas por minuto de cada um está na mão_

  **Notas de execução — MIGRAÇÃO DAS 9 ROTAS COMPLETA:**

  - **Benchmark de grade com gabarito exato** (`_bench_grade.py`): em vez de usar a tela real
    e chutar o que está em cada célula, o alvo (um círculo magenta) é DESENHADO numa célula
    escolhida, com a grade aplicada pela mesma `visao._desenhar_grade` que roda em
    produção. 12 alvos em cantos, bordas e centro — de propósito, porque modelo de visão
    erra mais na borda e na horizontal, e concentrar no meio daria número bonito e
    mentiroso.

    | modelo | exatos | linha | coluna | latência |
    |---|---|---|---|---|
    | meta/llama-3.2-90b-vision-instruct | 12/12 | 12/12 | 12/12 | 2,19s |
    | claude-opus-5 | 12/12 | 12/12 | 12/12 | 3,85s |
    | claude-sonnet-5 | 12/12 | 12/12 | 12/12 | 3,46s |

  - **O llama reproduziu exatamente os 12/12 históricos**, o que valida a metodologia do
    benchmark antes de usá-la para decidir qualquer coisa.
  - **O benchmark SATUROU, e isso está registrado como limitação.** Os três acertam tudo,
    então ele prova que o Opus não é pior (Requisito 7.5 satisfeito, migração autorizada),
    mas NÃO distingue Opus de Sonnet. O Sonnet empata a 1,3x de crédito contra 2,2x do
    Opus, e foi ligeiramente mais rápido. Separar os dois exigiria um alvo mais difícil que
    um círculo magenta — um botão pequeno entre elementos parecidos, que é o caso real. O
    Opus ficou como o Vitor pediu; a troca é `EMILY_KIRO_MODELO_AGENTE_UI`.
  - **`agente_jogo` ganhou rota própria, que era o ponto da task.** Antes usava
    `ROTA_AGENTE_UI` — inofensivo quando as duas apontavam pro mesmo modelo no NIM, e
    problema de custo assim que o `agente_ui` foi pro Opus a 2,2x: um monitoramento de jogo
    de meia hora gastaria crédito de Opus a cada poucos segundos sem precisar da precisão
    que justifica o Opus. O que se pede ali é uma tecla, não uma coordenada.
  - **Validação funcional das duas** (`_teste_task7_agentes.py`): o `agente_ui` decidiu
    `{"acao": "atalho", "texto": "win"}` para "abrir o menu iniciar" — decisão correta — em
    16,09s. O `agente_jogo` devolveu JSON válido com lista de teclas em 4,83s, tendo lido a
    tela certo (*"HP em 60/100, inimigo vermelho a frente atacando, espada equipada"*).
  - **Ponto de atenção sobre os 16,09s do Opus:** o laço do `agente_ui` tenta até 3 vezes por
    passo, e um objetivo de várias etapas multiplica isso. Somado ao empate no benchmark,
    é o segundo argumento a favor do Sonnet nessa rota se o agente parecer lento na prática.
  - **Requisito 7.7 medido, não estimado no ar:** ~9,6 chamadas de triagem por minuto
    (latência medida de 3,23s + `time.sleep(3)` real do `loop_visao`), o que dá ~578 por
    hora de tela mudando sem parar. **Atenuante que muda o cálculo:** o `loop_visao` só
    chama a LLM quando a assinatura do frame muda (`visao.tela_mudou`), então tela parada
    custa zero. O número é o pior caso — que é justamente o caso de jogo.

- [x] 8. Tool calling ponta a ponta no formato do gateway
  - Estender `_teste_fluxo.py` e `_teste_laco.py` para o formato real do gateway:
    `tool_calls` em chunk único no fim, argumentos completos, `finish_reason="tool_calls"`
  - Cobrir os cenários de preâmbulo vazio, só espaço em branco, curto, e maior que a janela
    de 80 caracteres, mais o caso de texto puro sem ferramenta
  - Testes de propriedade: Property 8 (ferramenta no fim é executada e o texto é exatamente
    o preâmbulo) e Property 9 (texto puro executa zero ferramentas)
  - Se a janela de decisão de `FluxoComFerramentas` virar só custo de latência nesse formato,
    ajustar com comentário explicando o porquê
  - Ligar `EMILY_TOOL_CALLING=1` e validar com pedido real de ação por voz
  - _Requisitos: 2.2, 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Demo: "Emily, abre o YouTube" — ela fala o preâmbulo e a ferramenta executa de fato,
    com o Claude decidindo qual chamar_

  **Notas de execução:**

  - **A premissa da task foi CONFIRMADA contra o gateway ao vivo**, não só por leitura de
    código. O cenário [C] do `_teste_task8_ferramenta_real.py` espia o stream cru e reporta:
    1 evento com `tool_calls`, 1 ferramenta nesse evento, **argumentos não fatiados entre
    deltas**. É exatamente o que o design previu lendo o `streaming_openai.py`. Esse teste
    fica no repositório como sentinela: se o gateway algum dia passar a fatiar como o NIM,
    ele avisa antes de alguém depurar uma Emily muda.
  - **`_teste_fluxo.py` foi de 5 para 11 cenários.** Os cinco antigos (formato NIM,
    `tool_call` fatiado entre deltas) ficaram intactos, porque o `EMILY_PROVEDOR_LLM=nvidia`
    continua sendo caminho válido. Os seis novos cobrem o formato do gateway: sem preâmbulo,
    só whitespace, preâmbulo curto, preâmbulo maior que a janela de 80 chars, duas
    ferramentas no MESMO chunk, e texto puro.
  - **`_teste_laco.py` foi de 6 para 11 casos**, com os cinco novos exercitando o laço real
    do `modelo.py` no formato do gateway.
  - **Properties 8 e 9 em `testes/test_ferramentas_propriedades.py`** (7 testes, hypothesis).
    O que os cenários escolhidos a dedo não cobrem e o gerador cobre: preâmbulo vazio, só
    quebra de linha, exatamente 80 caracteres (a borda da janela de decisão), texto com
    acento e emoji, e muitos pedaços minúsculos. Um dos testes é regressão específica do
    formato novo: os argumentos não podem ser concatenados duas vezes, porque o acumulador
    do `FluxoComFerramentas` foi escrito para o NIM (`args += fn.arguments`) e um chunk
    processado em dobro viraria `'{}{}'`, com o `args()` devolvendo `{}` em silêncio.
  - **A janela de 80 chars NÃO foi alterada.** Com o formato do gateway ela raramente
    dispara — mas quando dispara (preâmbulo curto), poupa uma volta, e removê-la quebraria
    o caminho do NIM que continua sendo o plano B. O teste
    `test_property8_qualquer_tamanho_de_preambulo` varre de 0 a 300 caracteres e prova que
    as duas saídas entregam o mesmo resultado, que era a dúvida real.
  - **Ponta a ponta com o Claude decidindo, contra o catálogo real de 40 ferramentas:** o
    pedido "que horas são agora?" fez o modelo escolher `hora_atual`, a ferramenta executou,
    e a Emily respondeu *"00h03. Já passou da meia-noite de novo, viu como você é né,
    Vitor."* Conversa pura ("kkkk você é muito engraçada mesmo") executou zero ferramentas e
    respondeu *"Kkkkk para, você vai me deixar convencida."*
  - **Ferramenta escolhida para o teste real foi `hora_atual`** de propósito: somente
    leitura, sem efeito colateral na máquina do Vitor, e com verificação objetiva contra o
    relógio do sistema.

- [x] 9. Chave de reversão por variável de ambiente
  - Montar `ROTAS_KIRO` e `ROTAS_NVIDIA` com o mesmo conjunto de nomes de rota, e
    `_resolver_tabela()` selecionando por `EMILY_PROVEDOR_LLM` com default `kiro`
  - Levantar `ErroConfiguracao` citando os valores aceitos em valor desconhecido, aceitando
    espaços nas pontas e qualquer caixa
  - Deixar cada modelo em variável própria (`EMILY_KIRO_MODELO_*`), porque o Opus 5 é preview
  - Fazer `diagnosticar()` imprimir a tabela ativa e o estado do gateway
  - Testes de propriedade: Property 5 (paridade das tabelas), Property 6 (seleção por env),
    Property 7 (modelo sobrescritível), Property 12 (diagnóstico cobre a tabela ativa)
  - _Requisitos: 6.1, 9.1, 9.2, 9.3, 9.4, 9.5, 11.3, 11.4_
  - _Demo: `EMILY_PROVEDOR_LLM=nvidia` devolve a Emily inteira para o NIM sem editar uma
    linha de código, e o diagnóstico diz qual tabela está no ar_

  **Notas de execução:**

  - **Duas tabelas separadas, não uma com o provedor trocado.** A razão é semântica, não
    estilo: as rotas de visão precisam de `RACIOCINIO_NORMAL` no NIM (porque o nemotron
    rejeita `reasoning_effort='none'` com 400) e de `RACIOCINIO_DESLIGADO` no Kiro (porque
    lá `'none'` é o que desliga o thinking). Uma tabela só com o campo `provedor` mudando
    levaria o valor errado de raciocínio junto.
  - **`_resolver_tabela` não cai no default em silêncio.** Valor desconhecido levanta
    `ErroConfiguracao` citando os aceitos. Se o Vitor digitar `nvida`, ele descobre na hora,
    e não três dias depois achando que tinha revertido. Espaço nas pontas e caixa são
    tolerados, porque valor de `.env` copiado à mão vem sujo e falhar por um espaço seria um
    jeito idiota de deixar a Emily muda.
  - **A rota `agente_jogo` no NIM aponta para o modelo de visão do agente**, que era o
    comportamento efetivo antes da separação — assim a reversão reproduz o passado em vez de
    inventar uma configuração que nunca existiu.
  - **35 testes de propriedade** em `testes/test_rotas_propriedades.py`, cobrindo as
    Properties 5, 6, 7 e 12. A suíte completa está em **84 testes** (42 gateway + 7
    ferramentas + 35 rotas), todos passando depois da reestruturação.
  - **BUG NO TESTE, encontrado pelo próprio teste.** Os 7 testes da Property 7 falharam
    apontando um bug no `llm.py` que não existia. O que denunciou foi o stdout capturado:
    `[LLM] tabela de rotas ATIVA: 'nvidia'` — o reload TINHA funcionado. A causa era o meu
    helper: `importlib.reload` muta o objeto de módulo **no lugar**, então o módulo
    "recarregado" e o `llm` importado no topo são o MESMO objeto, e o `finally` que
    restaurava o ambiente rodava ANTES de o valor chegar ao corpo do teste. "Retorna o
    módulo recarregado e depois desfaz" é impossível por construção. Virou gerenciador de
    contexto, e o motivo está escrito no docstring do helper para ninguém repetir.
  - **Property 7 assume pass-through de propósito:** qualquer nome de modelo é aceito sem
    validação nossa. Validar aqui bloquearia modelo novo que a conta já tem — foi exatamente
    o caso do `claude-sonnet-5`, que funciona sem aparecer no `/v1/models`.
  - **Reversão demonstrada de verdade:** `EMILY_PROVEDOR_LLM=nvidia python llm.py` mostrou
    `tabela ATIVA: 'nvidia'`, as 9 rotas no provedor `nvidia`, e chamadas reais respondendo.
  - **Dado colateral que reforça a migração:** nesse diagnóstico o GLM-5.2 no NIM levou
    46,26s na rota `conversa` e 38,41s no `classificador` — para responder "OK". As mesmas
    rotas no Kiro medem 1,73s a 3,14s. O caminho de reversão existe, mas o número de hoje
    diz que ele é plano B mesmo.
  - **`_teste_rotas_estrutura.py` foi removido:** era um script solto da Task 2 que nunca
    conseguiu rodar por causa do shell, e a Property 5 cobre a mesma verificação com mais
    rigor dentro do pytest.

- [x] 10. Empacotamento e documentação
  - Incluir a pasta `kiro_gateway` em `datas` do `Emily.spec`, pois o subprocesso precisa do
    código-fonte
  - Validar o caminho do interpretador em modo frozen com `EMILY_GATEWAY_PYTHON`
  - Acrescentar ao `.gitignore`: `kiro_gateway/.env`, `kiro_gateway/credentials.json`,
    `kiro_gateway/state.json` e `kiro_gateway/*.log`
  - Atualizar `BRIEFING-MIGRACAO.md` e `README.md` com a arquitetura nova, as variáveis de
    ambiente e o procedimento para quando a credencial do Kiro expirar
  - Manter as ferramentas de teste como dependência de desenvolvimento, fora do pacote
  - _Requisitos: 10.1, 10.2, 10.3, 10.4, 10.5_
  - _Demo: build limpo e o executável da Emily rodando com o gateway subindo sozinho_

  **Notas de execução:**

  - **A edição foi no `build_emily.py`, não no `Emily.spec`.** O spec é artefato gerado pelo
    PyInstaller (e está no `.gitignore` como `*.spec`); editá-lo direto seria sobrescrito no
    próximo build. Levei um minuto lendo os dois para descobrir qual era a fonte de verdade,
    e valeu.
  - **O `kiro_gateway` entra como DADO, por partes.** Como o gateway roda em subprocesso com
    outro interpretador, ele precisa dos arquivos no disco — bytecode embutido no exe não
    serve. Incluídos `kiro/`, `main.py`, `requirements.txt` e `.env`; ficaram fora os testes,
    a documentação traduzida e os logs de debug do gateway, que somam peso e não servem para
    servir requisição.
  - **`gateway` foi para `hiddenimports`, e isso não é decorativo.** O import é lazy, dentro
    de função, no `llm.py` e no `modelo.py` — de propósito, para os módulos continuarem
    carregáveis sem ele. O PyInstaller não enxerga import dentro de função, então sem essa
    linha o exe sairia sem o ciclo de vida do gateway e a Emily ficaria muda. Aproveitei para
    declarar `llm`, `ferramentas` e `navegador` também.
  - **Distinção que o `requirements.txt` agora explica:** `fastapi`, `uvicorn`, `httpx`,
    `loguru` e `tiktoken` NÃO são dependências da Emily, são do subprocesso. Empacotá-las no
    exe não faria diferença nenhuma — quem as importa é outro processo, com outro
    interpretador. Elas precisam estar instaladas no Python do sistema que o `gateway.py`
    vai usar.
  - **`pytest` e `hypothesis` declarados como dependência de desenvolvimento**, com o comando
    de rodar a suíte no comentário.
  - **README reescrito nas partes que a migração invalidou** — e ele estava defasado desde
    ANTES desta migração: ainda descrevia AWS Bedrock como LLM, duas migrações atrás.
    Atualizados: features, tabela de tecnologias, estrutura do projeto, instalação, `.env`,
    APIs necessárias e build. Seções novas: como a camada de LLM funciona (com a tabela de
    rotas), o que fazer quando a credencial do Kiro expira (com a tabela de frase → causa →
    ação), consumo de crédito, e como rodar os testes.
  - **`BRIEFING-MIGRACAO.md` marcado como histórico, não reescrito.** Ele documenta a
    migração Bedrock → NIM e explica decisões que continuam valendo (arquitetura do `llm.py`,
    tabela de rotas, limitador, grade do agente). Ganhou um aviso no topo apontando para a
    seção nova, e a seção "Migração 2 — NIM → Kiro" no fim, com as seis armadilhas
    encontradas, a configuração obrigatória do gateway e o balanço honesto do que se ganhou e
    do que se perdeu.
  - **Divergência registrada:** o briefing original dizia "não adicionar testes automatizados
    sem o Vitor pedir". O spec desta migração, aprovado por ele, pedia testes de propriedade
    explicitamente. A divergência está documentada no próprio briefing para não parecer que
    a regra foi ignorada por descuido.
  - **Verificação sem build completo** (`_teste_task10_build.py`, 5/5): os quatro caminhos de
    dados existem no script E no disco (o `build_emily.py` só imprime "Ignorando" e segue em
    frente quando o caminho está errado, então caminho errado não quebra o build — produz um
    exe que falha no primeiro uso); `gateway` está em `hiddenimports`; os segredos estão
    ignorados; e o `_interpretador()` com `sys.frozen` simulado escolheu o Python real em vez
    do `Emily.exe`.
  - **O build completo não foi rodado:** leva minutos e produz centenas de MB, e o que ele
    acrescentaria é confirmar que o PyInstaller resolve as dependências — o que esta task não
    mudou. Fica como último passo manual do Vitor: `python build_emily.py`, e depois rodar
    `dist/Emily/Emily.exe` com `EMILY_GATEWAY_PYTHON` apontando para o Python do sistema.
