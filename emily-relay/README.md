# Ponte Emily na Oracle

Endereço fixo: `https://emily-hiucksam.duckdns.org/bridge`.

## Conectar um celular

No painel do PC, abra as configurações de conexão e gere um código para dispositivo. Também é possível abrir o atalho **Parear dispositivo Emily** no menu de aplicativos.

No Android: **Configurações → Emily do PC → Código de conexão**. O código dura dez minutos e pode ser usado uma única vez. Cada dispositivo recebe uma credencial própria; não é necessário informar URL, IP ou token.

## Serviços

- PC: `emily-gateway.service` executa as ferramentas; `emily-oracle-link.service` mantém a conexão SSH de saída e reconecta automaticamente.
- Oracle: `emily-relay.service` autentica os dispositivos e encaminha as requisições. Caddy oferece HTTPS e acessa o relay por socket privado.
- `emily-ngrok.service` está desativado. O executável foi preservado para eventual reversão.

Controle, arquivos e ferramentas do PC precisam que ele esteja ligado e conectado à internet. Os modelos na nuvem e os APKs publicados continuam acessíveis quando a ponte do PC está desligada.

## Atualizações Android

`EmilyAPP2/publicar_atualizacao.py` publica o APK na Oracle com `publicar_oracle.py`. A transferência é dividida em partes retomáveis; tamanho e SHA-256 são conferidos antes da publicação atômica do manifesto. Versões publicadas são imutáveis. No celular, o instalador também confere hash, versão, pacote e assinatura.

A credencial de publicação é exclusiva do administrador e fica no arquivo privado `~/.config/emily-cloud-oracle/relay-upload-key.json`. Nunca distribuir esse arquivo nem as chaves SSH de administração.

## Administração e recuperação

Na Oracle, executar com o Python de `/home/ubuntu/emily-relay/.venv/bin/python`:

```text
/home/ubuntu/emily-relay/relay.py list
/home/ubuntu/emily-relay/relay.py revoke --id ID_DO_DISPOSITIVO
```

Esses comandos listam ou revogam dispositivos sem exibir suas credenciais. A revogação também bloqueia o acesso aos modelos pela ponte.

O estado privado fica em `/home/ubuntu/.config/emily-relay/config.json` e `/home/ubuntu/emily-relay/data/devices.sqlite`. Os APKs e o manifesto ficam em `/home/ubuntu/emily-relay/data/updates`. O backup inicial do estado está em `~/.config/emily-cloud-oracle/relay-backup` no PC; atualizar esse backup após novos pareamentos ou revogações. O backup do OmniRoute não inclui esse estado da ponte.

Em uma recuperação, parar o relay antes de substituir o banco e a configuração, manter proprietário `ubuntu` e permissões privadas e então reiniciar o serviço. Preservar também as configurações de Caddy/Compose e a autorização SSH restrita para o túnel. Os APKs podem ser republicados a partir dos arquivos de build preservados no PC.

A VM E5 usa os créditos do trial. A ponte precisa de hospedagem ativa após o fim do trial; esta implementação não transforma a VM em Always Free.

## Verificação desta migração

Versão Android 48 instalada. Foram aprovados 147 testes unitários Android, 63 testes Python do PC, seis testes do relay e testes reais de pareamento, modelos e atualização. Com o túnel do PC parado, o celular baixou o APK completo de 144.219.933 bytes e validou hash, versão e assinatura; depois a conexão com o PC foi restabelecida. Requisições sem credencial são recusadas.

Esta etapa migra a conexão e a distribuição de atualizações deste PC/Android. Ferramentas e dados locais continuam no PC; outras cópias de distribuição e instaladores Windows/Linux precisam de uma etapa própria de migração.
