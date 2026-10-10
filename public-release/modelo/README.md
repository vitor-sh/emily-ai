# Emily

Assistente pessoal com interface de conversa, voz, memória e ferramentas de automação.

**Estado: preparação da versão pública. Este pacote não é uma versão instalável validada.** Recursos da versão pessoal ainda dependem de assets, configuração e integrações que estão sendo separados.

## O que está sendo preparado

- Conversa e voz com provedores configurados pelo usuário.
- Automação do computador, navegação e ferramentas de código.
- Memória, música e integrações opcionais.
- Windows e Linux, com validação por sistema ainda pendente.

O uso de APIs pode ter custo conforme o provedor. Não é fornecido acesso às contas, ao servidor ou às credenciais do autor.

## Antes de executar ou distribuir

Leia [a lista de validação](RELEASE_CHECKLIST.md), [privacidade](PRIVACY.md), [segurança](SECURITY.md) e [licenças de terceiros](THIRD_PARTY.md). Não execute os módulos de automação em um computador principal apenas para experimentar o código.

Com as dependências instaladas, `python emily_public.py` abre a configuração inicial guiada. Escolha seu nome, provedor, chave e modelo; teste a conexão antes de concluir. Na revisão, você pode ativar Fish Audio, microfone Groq/Whisper e um bot Discord próprio, com passos guiados e credenciais individuais. Para revisar, use `python emily_public.py --configurar`.

Essa entrada usa um perfil separado da instalação pessoal, não lê o `.env` do autor e começa por texto; microfone e bot Discord só iniciam se forem ativados explicitamente no assistente. O fluxo foi validado com uma API local de teste. A execução completa e a janela nativa em máquinas limpas ainda precisam ser conferidas. Nenhum instalador é fornecido nesta etapa.

`.env.example` serve como referência para desenvolvedores; o usuário não precisa editar esse arquivo para usar o assistente de configuração.

## Licença

O código próprio da Emily nesta preparação é disponibilizado sob GPL versão 3 (`GPL-3.0-only`); veja [LICENSE](LICENSE). Arquivos de terceiros mantêm suas licenças. Esta escolha não concede direitos sobre marcas, serviços, vozes, músicas ou assets ausentes do pacote.

## Contribuições

Por enquanto esta cópia é um rascunho local. O repositório, o canal de relatos e as instruções de desenvolvimento serão definidos antes da publicação. Nunca inclua chaves, transcrições, memórias ou dados de outras pessoas em relatos de erro.
