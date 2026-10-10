# Sons personalizados do xadrez

No xadrez, clique em **♫ Personalizar** e escolha o arquivo de cada efeito:
lance, captura, roque, promoção, xeque, xeque-mate, empate, início e fim por
desistência.
Clique em **Salvar sons**. Arquivos aceitos: MP3, WAV e OGG, até 1 MB e
5 segundos por efeito. Não precisa importar todos: os efeitos ausentes usam
a síntese original da Emily.

**Sons locais** alterna entre os arquivos importados e os sons originais.
**Som** continua silenciando todos os efeitos do tabuleiro.
**Remover sons locais** apaga os arquivos importados do armazenamento da Emily.

Os arquivos são guardados em `sons_xadrez_pessoais/pacote.json` na pasta de
dados deste PC, sem sincronização de preferências ou upload para o gateway.
O JSON contém os áudios em base64. A pasta é ignorada pelo Git e não está
entre as pastas publicadas pelos pacotes Windows. Ela também fica fora de
`web`, `static`, `img` e `assets`, que os instaladores empacotam.
No Fedora, a pasta padrão é `~/.local/share/emily/sons_xadrez_pessoais`.
No Windows, a pasta de dados normalmente é `%LOCALAPPDATA%/Emily`.

Não coloque áudios privados dentro de pastas da interface, nem os acrescente
manualmente a instaladores ou ao repositório. O `.gitignore` não remove
arquivos já rastreados, e não se aplica a cópias ou envios manuais.

Importar um arquivo não concede direitos sobre ele. Downloads de terceiros,
uso pessoal, compartilhamento com amigos ou não cobrar pelo app não
constituem, por si, uma autorização de reprodução/distribuição. Para publicar
a Emily, mantenha os sons originais ou use arquivos com licença apropriada.
Nenhum som do Chess.com acompanha esta funcionalidade.
