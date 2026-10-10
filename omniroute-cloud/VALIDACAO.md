# Validação — 3 de outubro de 2026

## Conferido nesta máquina

- `docker.io/diegosouzapw/omniroute:3.8.51` existe no registro e foi executada
  isoladamente; versão interna conferida como 3.8.51.
- `caddy:2.10.2-alpine` executou `caddy validate` com o Caddyfile deste kit.
- Docker Compose 5.6.0, obtido do projeto oficial com SHA-256 conferido, validou
  `compose.yaml` via `config --quiet` usando segredos descartáveis.
- `CLOUD_CONTAINER_TEST=podman python3 -m unittest -v test_cloud.py`:
  **5 testes passaram**, última execução em 13,974 segundos.
- Instância real descartável: inicialização, proxy, painel inacessível,
  chat recusando chave ausente/inválida e retomada após reinício.
- Preparador: permissão 600, validação do domínio e proteção contra sobrescrita.
- Backup: retomada após falha de cópia e ausência de arquivo parcial.
- Verificador: detecta uma API que aceita pedidos sem autenticação.
- Containers/redes descartáveis foram removidos ao terminar.
- `systemctl --user is-active omniroute-emily.service`: **active** após testes.

## A conferir quando existir o VPS

- Instalação completa com Docker Engine no Ubuntu escolhido.
- DNS, emissão/renovação do certificado HTTPS e firewall externo.
- Cadastro/autorização dos provedores, aliases/modelos e geração autenticada.
- Consumo de RAM e latência usando o contexto real da Emily.
- Backup/recuperação dos dados reais em outra instância privada.
- Destino separado de inferência no Android, sem alterar a ponte dos comandos PC.

Nenhuma conta real, arquivo de configuração ativo ou banco local foi utilizado
pelos testes. Não houve contratação, publicação ou troca de endpoint.

## Implantação Oracle — 5 de outubro de 2026

- VM informada como E5 Flex, Ubuntu 24.04 x86-64, IP 163.176.97.174.
- Sistema reportou 2 processadores lógicos e cerca de 12 GB de RAM.
- Docker Engine 29.8.2 e Compose 5.6.0 instalados pelo repositório oficial;
  daemon habilitado no boot e hello-world passou.
- Stack deste kit iniciada; OmniRoute 3.8.51 saudável.
- `sudo CLOUD_CONTAINER_TEST=docker python3 -m unittest -v test_cloud.py`:
  5 testes passaram no servidor.
- DNS `emily-hiucksam.duckdns.org` aponta para a VM. Após liberar TCP 80/443
  na lista de segurança da Oracle, certificado Let's Encrypt emitido.
- Verificador passou na origem pública HTTPS: saúde 200, painel/admin 404,
  chat sem chave ou com chave inválida 401, catálogo com chave válida 200.
- Painel somente em loopback 20128, acessado por túnel local 21128.
- Chave de inferência própria gerada; segredos não foram registrados aqui.
- Backup inicial privado executado, serviço retomado e arquivo copiado para
  armazenamento privado fora da VM.
- Triagem de transporte: 5 chamadas /healthz pelo PC, mediana local 4,7 ms,
  nuvem 285,8 ms. Cada chamada abre conexão; inclui estabelecimento TLS na
  nuvem. Não mede primeira resposta do modelo nem conexão reutilizada.
- Pendente: novas autorizações dos provedores, comparação de geração real,
  teste de restauração, migração dos endpoints e caminho independente Android.
- Configuração ativa da Emily e contas locais permanecem sem alterações.

### Retorno OAuth Codex

- Corrigida a ausência do encaminhamento OAuth 1455: Compose publica apenas
  `127.0.0.1:1455:1455`, e túnel SSH conecta o loopback do PC ao da VM.
- Callback real iniciado pela API autenticada (`start-callback-server`, GET);
  acesso à raiz via túnel respondeu 404 esperado, comprovando conectividade.
- Verificador público HTTPS passou novamente após recriar o container.
- 4 testes unitários passaram; teste de container nessa execução local omitido.
- Login humano ainda precisa ser reiniciado para gerar um fluxo OAuth novo.

### Provedores e latência real

- Usuário concluiu novas autorizações Codex e Kiro na nuvem. Conjunto de contas
  ativas do Codex conferido igual ao local, sem registrar credenciais aqui.
- 24 gerações Codex concluídas sem erro: 6 por destino com Sol, 3 por destino
  com Luna e Astra. Perguntas curtas, limite solicitado de 128 tokens, esforço
  low, streaming, chamadas sequenciais alternando destino e novas conexões.
- Medianas em segundos (primeiro texto / resposta completa):

| Modelo | PC | Oracle |
| --- | --- | --- |
| GPT-6 Sol | 2,07 / 3,21 | 4,36 / 5,31 |
| GPT-6 Luna | 1,51 / 2,51 | 1,37 / 2,29 |
| GPT-6 Astra | 5,02 / 10,46 | 4,10 / 4,37 |

- Luna teve uma resposta Oracle de 9,79 s no total, apesar da mediana favorável.
  Amostra exploratória pequena, sem garantia sobre caudas de latência ou
  desempenho sob carga. Não equivale ao contexto longo real da Emily.
- Snapshot de uso durante a medição: OmniRoute ~419 MiB e 0,14% CPU;
  Caddy ~12 MiB. Não foi observado indício de saturação nesse snapshot.
- Haiku 4.5 e Sonnet 4.5 do Kiro passaram em geração autenticada real e
  verificador de proteção pública HTTPS.
- Endpoints da Emily ainda não migrados; preferência do modelo de conversa
  na nuvem solicitada ao usuário em razão da diferença observada no Sol.


## Integração PC e Android — 5 de outubro de 2026

- OpenAI/Codex e Kiro no `.env` ativo agora usam o HTTPS da Oracle e a chave
  privada criada para Emily. Provedor externo Claude preservado.
- Conversa padrão PC/Android: `cx/gpt-6-luna`, com escolha persistente e
  seletores mantidos. Agente visual PC permanece `cx/gpt-6-sol`.
- Delegação forte Android usa Sol por padrão, configurável pelo parâmetro
  existente de compilação; desligar delegação continua usando modelo do chat.
- Android 47 instalado por cima da versão 46, dados preservados. Credencial da
  nuvem provisionada apenas no armazenamento privado, fora do APK e do backup
  Android em nuvem. Campo de edição mascarado nas configurações.
- Antigo painel “Cérebro (modelos do PC)” substituído por “Modelos na nuvem”,
  com endereço HTTPS, chave e verificação autenticada. Tema quente mantido.
- Ponte PC LAN/Ngrok e sua autenticação preservadas para comandos, arquivos,
  busca, monitoramento, notificações e sincronização. Não são serviços Oracle.
- Três testes reais no aparelho passaram (7,189 s): catálogo/escolha/Luna SSE,
  remontagem de argumentos de ferramenta por SSE e Haiku não streaming.
- 147 testes Android unitários passaram; APK e APK de testes compilados.
- 62 testes Python de gateway, agente visual, GPT-6 e delegação passaram.
- Gateway PC realizou chamada de ferramenta via Oracle em 1,84 s e rodada
  seguinte com resposta; nenhum comando real foi executado por essa ferramenta.
- Sol visual na Oracle identificou corretamente uma imagem sintética azul.
- `omniroute-emily.service` desativado e parado; porta local 20128 fechada.
  Dependência de inicialização removida do gateway ativo e do arquivo fonte.
- Gateway permanente continua ativo. Testes de inferência acima realizados
  com o OmniRoute local desligado. Arquivos/serviços de distribuição das
  instâncias Windows/Linux e o modelo externo Claude não foram migrados.
- Esta VM E5 continua vinculada aos créditos do trial; não se torna Always
  Free com esta integração. A migração de hospedagem continua pendente para
  o término do trial.
