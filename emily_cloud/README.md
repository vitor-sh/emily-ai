# Emily Cloud

Biblioteca local-first da Emily. Os bytes ficam endereçados por SHA-256, os
nomes e pastas são virtuais no SQLite e a sincronização S3 é opcional.

## Configuração

- `EMILY_CLOUD_DIR`: muda a pasta local do acervo.
- `EMILY_CLOUD_GUARDAR_DOWNLOADS=0`: não importa downloads iniciados pela Emily.
- `EMILY_CLOUD_DOWNLOADS_MODO=local|sincronizar|desligado`: define se downloads
  ficam só no acervo local ou também são enviados ao S3.
- `EMILY_PONTE_TOKEN`: habilita e protege as rotas HTTP `/cloud/*`. Sem token,
  elas retornam `503`; use `Authorization: Bearer <token>` em toda requisição.
- `EMILY_CLOUD_S3_ATIVO=1`: habilita sincronização e links temporários.
- `EMILY_CLOUD_S3_BUCKET`: bucket dedicado.
- `EMILY_CLOUD_S3_ENDPOINT`: endpoint opcional para S3 compatível.
- `EMILY_CLOUD_S3_REGION`: região opcional.
- `EMILY_CLOUD_S3_ACCESS_KEY` e `EMILY_CLOUD_S3_SECRET_KEY`: credenciais.
- `EMILY_CLOUD_S3_PREFIX`: prefixo dos objetos; padrão `emily-cloud`.

Nunca coloque token ou credenciais no código. Use `.env` local, que já é
ignorado pelo Git. Uploads HTTP são retomáveis em partes de até 8 MiB. Conteúdo
suporta `Range`, inclusive faixas de sufixo, para mídia grande.

Visualizadores usam URLs HMAC temporárias (até 6 horas) para players que não
conseguem enviar o header Bearer. ZIP e TAR podem ser inspecionados e extraídos
para dentro do próprio catálogo. A extração bloqueia caminhos absolutos/`..`,
links, dispositivos, entradas demais e expansão desproporcional.

## Celular

O app Android usa as mesmas rotas `/cloud/*` pela ponte LAN/Ngrok. Elas também
são registradas no `emily-gateway.service`, então a janela/processo da Emily
desktop não precisa estar aberto. A fonte de verdade continua sendo este mesmo
`cloud.db` e a pasta `objects`: alterações do PC e celular aparecem ao vivo nas
duas interfaces, sem replicar um segundo catálogo no telefone.

O celular suporta arquivos individuais, lotes e pastas recursivas, além de
listar, buscar, visualizar previews, abrir/baixar, criar pasta, renomear, mover,
favoritar, ler texto, exportar para o PC, sincronizar com S3, criar/revogar
links, usar a lixeira, restaurar e excluir definitivamente.

## Visualizadores e compactados

- Imagens: visualização interna com zoom.
- Vídeo e áudio: reprodução interna com pausa, busca e controle de volume.
- PDF: visualização por páginas no Android e pelo leitor PDF da WebView no PC.
- Texto/código: TXT, Markdown, JSON, XML, YAML, CSV, logs e extensões comuns de
  Python, JavaScript/TypeScript, Kotlin, Java, C/C++ e SQL.
- Compactados: navegação e extração total ou seletiva de ZIP, TAR, TAR.GZ,
  TAR.BZ2 e TAR.XZ. RAR e 7z permanecem com abertura no aplicativo do sistema.

Vídeos e áudios não são carregados inteiros na memória: os viewers usam
streaming com `Range`. No celular, a URL é assinada por HMAC e expira em até
6 horas; o token principal da ponte não é colocado na URL.

## Trocar o disco de armazenamento

Na interface desktop, o botão **Armazenamento** permite escolher qualquer pasta
gravável do PC, inclusive em outro SSD, HD ou unidade externa. Se for escolhida
a raiz de um disco ou uma pasta que já contém outros arquivos, a Emily cria uma
subpasta dedicada chamada `Emily Cloud`.

A migração copia o SQLite de forma consistente, valida a integridade do banco e
confere o SHA-256 de cada objeto antes de ativar o destino. Durante a operação,
novos acessos são pausados e o gateway permanente é reiniciado; o Android passa
a usar automaticamente o novo acervo, sem ajuste no celular.

A preferência fica fora do acervo, em `cloud-location.json`. Um marcador único
na pasta evita que um HD desmontado seja confundido com uma pasta vazia no disco
do sistema. Se a unidade estiver desconectada, o acervo atual fica indisponível,
mas o botão **Armazenamento** permite escolher outro local e iniciar uma Cloud
vazia. Nada é copiado nem apagado do disco offline; ao reconectá-lo, os dados
antigos continuam nele. Para uso permanente, configure o HD para montar sempre
no mesmo caminho/letra.

## Thumbnails de vídeo

Vídeos novos recebem uma capa WEBP gerada por FFmpeg durante a importação. Ao
abrir/listar a Cloud, vídeos antigos sem capa entram numa fila retroativa em
background. A mesma thumbnail é usada na interface do PC e no Android. Se o
FFmpeg ou o codec necessário não estiver disponível, o arquivo continua válido
e usa o ícone de vídeo como fallback.