# Validação da primeira preparação — 03/10/2026

## Executado

```text
python3 -m pytest public-release/test_exportar.py -q --tb=short
21 passed in 6.58s
```

O teste de integração gera o ZIP com os fontes reais, confere integridade ZIP e SHA-256 de cada arquivo e compila todos os arquivos Python da cópia sem executar a Emily. Os hashes dos fontes pessoais são conferidos antes/depois: exportar não modifica esses arquivos.

As verificações com projetos temporários cobrem: dados/arquivos não autorizados excluídos, caminhos que escapam da raiz, links simbólicos, credenciais conhecidas e literais, credencial em exemplo de configuração, endpoint Cloudflare pessoal, preservação de destino existente, interrupção sem pacote parcial e neutralização dos padrões Discord.

Também foi testado o `.gitignore` com o Git em um repositório temporário: libera somente o exemplo público, mantendo `.env`, `.env.local` e pacotes gerados ignorados.

## Artefato atual

`output/Emily-Publica-Fonte-Preparacao-03.zip` é o rascunho atual, com a primeira inicialização. Os `01` e `02` são etapas anteriores e não devem ser usados. Nenhum pacote foi publicado ou enviado para serviços externos.

São 173 arquivos de fonte + 8 documentos, além do relatório de exportação. A arte, os binários e os instaladores pessoais não estão incluídos.

## Primeira inicialização

Com um ambiente temporário de validação (incluindo python-dotenv/OpenAI SDK), foram executados:

```text
pytest testes/test_primeiro_inicio.py public-release/test_exportar.py testes/test_gateway_endpoint.py testes/test_memoria_unificada_integracao.py -k 'primeiro_inicio or exportar or endpoint or config_' -q --tb=short
53 passed, 20 deselected in 19.62s
node --check web/primeiro-inicio.js
exit 0
```

- API HTTP local real: listar modelos, recusar chave inválida, testar conversa e salvar/reabrir o perfil.
- Camada `llm.py` real + OpenAI SDK: chamada de conversa com a conta/modelo escolhidos, sem fallback para provedores privados.
- Interface Chromium real: etapas completas em 1080×760, 560×700 e 390×844; espaços no nome, modelos, invalidação de teste após editar, consentimento, persistência, sem erros JavaScript ou chave em localStorage.
- Capturas conferidas em `output/primeiro-inicio/`.
- Regressões selecionadas de leitura de configuração da memória e validação de endpoints.

Os testes não usam nem cobram APIs reais. Após separar também o caminho da memória unificada e evitar o seu aquecimento automático no modo público, os testes de perfil/roteamento e do ZIP real foram executados novamente.

## Limites da validação

- Não foi feita execução completa do app público nem validação nativa WebView2/GTK em máquinas limpas; ainda faltam assets e a auditoria geral das integrações.
- Não foram feitos builds Windows/Linux desta cópia.
- Scanner e compilação não substituem revisão humana, auditoria de dependências e teste em perfil limpo.
- O runtime recebeu condições explícitas para a entrada pública e suporte ao seu arquivo de configuração/perfil. Sem `EMILY_PUBLIC_MODE=1`, continua com o caminho pessoal anterior. Configurações pessoais, chaves, endpoints e serviços do autor não foram alterados.

## Assistentes Fish, Groq e Discord — 03/10/2026

Suite integrada: 52 testes passaram (primeiro início e exportação), incluindo três
viewports Chromium com opções expandidas e rolagem até salvar. Inclui o fluxo do bot por eventos simulados. Mais um teste isolado passou
para reabertura de perfil com todas as credenciais no tamanho máximo. Chamadas externas são simuladas;
nenhuma chave pessoal foi usada.

- Modelo gratuito explícito, ID da voz padrão, amostra MP3 limitada e sem redirects.
- Falha do SDK antigo não faz chamada sem backend no modo público.
- Credenciais individuais, invalidação após mudanças, remoção ao desativar e reabertura.
- Groq: chave e disponibilidade Whisper, sem captura no teste.
- Discord: token de bot e IDs válidos, filtro de canais/menções, sem DMs/admin/calls.
- Pacote real com varredura de segredos e compilação de todas as fontes Python.

Ainda não validado: janela nativa/full app, amostra Fish em conta nova, dispositivo
de microfone/atalho/transcrição e convite/permissões/resposta real no Discord.
