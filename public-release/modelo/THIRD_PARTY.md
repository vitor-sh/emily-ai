# Dependências e recursos de terceiros

Inventário inicial; **não é uma auditoria completa nem uma autorização para redistribuir binários**.

| Componente | Situação inicial | Referência |
| --- | --- | --- |
| Código próprio Emily | GPL-3.0-only | LICENSE |
| PyQt6 | GPLv3 ou licença comercial; seguir caminho GPL | https://www.riverbankcomputing.com/software/pyqt/intro |
| chess.js na interface | Preservar aviso e conferir versão/licença fornecidos | web/vendor/chess-license.js |
| Stockfish | Binário ausente; GPL e fonte correspondente a revisar antes de redistribuir | https://stockfishchess.org/about/ |
| FFmpeg | Binário ausente; obrigações variam com a compilação | https://ffmpeg.org/legal.html |
| Arte, sprites, áudio e modelos | Excluídos nesta etapa; revisar origem/direitos | RELEASE_CHECKLIST.md |
| Fish/serviços de voz | Conta e voz do usuário; revisar termos e direitos sobre a voz | https://fish.audio/terms/ |

O arquivo de dependências descreve a instalação pessoal atual. É preciso revisar também as dependências transitivas e componentes nativos antes de publicar a versão instalável. Marcas e serviços externos não são licenciados pela GPL da Emily.

Recursos de música/YouTube precisam de avaliação própria dos termos e direitos dos conteúdos. Publicar código não resolve essas condições.
