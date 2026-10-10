"""Empacota a MESMA interface de Music do desktop com adaptação móvel/nativa."""
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parent
DEST=ROOT/'EmilyAPP2/app/src/main/assets/music'

def preparar():
    DEST.mkdir(parents=True,exist_ok=True)
    html=(ROOT/'web/index.html').read_text()
    content=html[html.index('<div class="player-barra"'):html.index('<!-- O composer é UM só')]
    template=html[html.index('<template id="tpl-modal-playlist"'):html.index('<template id="tpl-chat"')]
    app=(ROOT/'web/app.js').read_text()
    player=app[app.index('const Player = {'):app.index('// Liga junto com os outros botões no boot.')]
    (DEST/'player.js').write_text(player)
    for name in ('estilo.css','emily-music.css','emily-music.js'):(DEST/name).write_bytes((ROOT/'web'/name).read_bytes())
    (DEST/'index.html').write_text('''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Emily Music</title><link rel="stylesheet" href="estilo.css"><link rel="stylesheet" href="emily-music.css"><link rel="stylesheet" href="mobile.css"></head><body><button id="btn-music" hidden></button><div id="music-toast" role="status"></div>'''+content+template+'''<script src="bridge.js"></script><script src="player.js"></script><script src="emily-music.js"></script><script src="native-player.js"></script><script src="mobile-ui.js"></script></body></html>''')

if __name__=='__main__':preparar()
