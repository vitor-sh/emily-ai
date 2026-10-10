# Preparação da Emily pública

Esta pasta prepara um **rascunho separado de código-fonte**. Não publica no GitHub, não muda a Emily pessoal e não gera um instalador pronto.

## Gerar a cópia

Na pasta `minha-ia`:

```sh
python3 -m pytest public-release/test_exportar.py -q
python3 public-release/exportar.py --output public-release/output/Emily-Publica-Fonte.zip
```

O destino precisa ser novo. Para repetir, use outro nome. A exportação usa `manifesto.json`, uma lista explícita; novos arquivos precisam ser revisados e incluídos. Não copia pastas inteiras nem histórico Git.

O ZIP contém `EXPORTACAO.json` com hashes e alterações aplicadas somente à cópia. Credenciais conhecidas, certos dados pessoais, IDs Discord, caminhos inválidos e links simbólicos interrompem a operação antes da criação do pacote. Isso é uma barreira adicional, **não uma garantia de ausência de toda informação pessoal**.

## Decisões desta etapa

- GPLv3 para o código próprio, conforme escolha do autor; licenças de terceiros preservadas.
- Cada usuário configurará seus próprios provedores. A infraestrutura, as contas e as chaves pessoais do autor não serão compartilhadas.
- A Emily pessoal continua funcionando com os arquivos atuais.
- A cópia tem nome padrão neutro e não contém os apelidos e coadministradores do Discord. A voz Emily usa seu ID não secreto autorizado como padrão, com chave individual Fish. Escuta de calls, respostas por DM e administração começam desligadas nessa cópia.
- Assets, modelos, binários, instaladores antigos, APKs e dados de execução não entram nesta primeira exportação. Precisam de revisão própria.

## Próximos gates

Veja `modelo/RELEASE_CHECKLIST.md`. O fluxo de primeira configuração já foi implementado e validado com um serviço local de teste; veja `PRIMEIRO_INICIO.md`. Continuam pendentes a execução completa em máquinas limpas, assets licenciados, validação real de voz/Discord e builds públicos.

**Não use o ZIP antigo de fonte para Windows ou os builds pessoais como publicação pública.** Eles têm outra finalidade e podem carregar dados/configurações pessoais.
