#!/usr/bin/env python3
"""Package the approved artwork for Android launchers without redrawing it."""
from pathlib import Path
from PIL import Image, ImageDraw
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'design/icon-variants/emily-music-symbolic-neon-v1.png'
RES = ROOT / 'app/src/main/res'
OUTPUT = ROOT / 'output/imagegen'
BACKGROUND = '#100e0a'


def main():
    art = Image.open(SOURCE).convert('RGB')
    assert art.width == art.height and art.width >= 1024
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE, OUTPUT / 'emily-music-icon-original.png')
    shutil.copy2(ROOT / 'design/icon-variants/SYMBOLIC-NEON-PROMPT.md', OUTPUT / 'emily-music-icon-prompt.txt')
    # 108dp adaptive layer; keep the head inside the central 66dp viewport.
    size, content = 432, 256
    layer = Image.new('RGB', (size, size), BACKGROUND)
    offset = (size - content) // 2
    layer.paste(art.resize((content, content), Image.Resampling.LANCZOS), (offset, offset))
    layer.save(RES / 'drawable-nodpi/music_launcher_foreground.png')
    # Android tints alpha only: an opaque photograph would become a solid square.
    alpha = layer.convert('L').point(lambda value: max(0, min(255, (value - 38) * 5)))
    mono = Image.new('RGBA', (size, size), 'white')
    mono.putalpha(alpha)
    mono.save(RES / 'drawable-nodpi/music_launcher_monochrome.png')
    viewport = layer.crop((84, 84, 348, 348))
    for density, pixels in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
        folder = RES / f'mipmap-{density}'
        icon = viewport.resize((pixels,pixels), Image.Resampling.LANCZOS).convert('RGBA')
        icon.save(folder / 'ic_music_launcher.png')
        mask = Image.new('L', (pixels*4,pixels*4))
        ImageDraw.Draw(mask).ellipse((0,0,pixels*4-1,pixels*4-1),fill=255)
        icon.putalpha(mask.resize((pixels,pixels),Image.Resampling.LANCZOS))
        icon.save(folder / 'ic_music_launcher_round.png')
    preview = Image.new('RGB',(768,384),'#252525')
    preview.paste(viewport.resize((320,320)),(32,32))
    rounded = viewport.resize((320,320)).convert('RGBA')
    mask = Image.new('L',(320,320))
    ImageDraw.Draw(mask).ellipse((0,0,319,319),fill=255)
    preview.paste(rounded,(416,32),mask)
    preview.save(OUTPUT / 'emily-music-icon-preview.png')
    assets = ROOT / 'app/src/main/assets/music'
    art.resize((128,128),Image.Resampling.LANCZOS).save(assets / 'emily-music-icon.png')
    for file in RES.glob('mipmap-anydpi-v33/ic_music_launcher*.xml'):
        file.write_text(file.read_text().replace('<monochrome android:drawable="@drawable/music_launcher_foreground" />', '<monochrome android:drawable="@drawable/music_launcher_monochrome" />'))
    (RES / 'values/music_launcher_colors.xml').write_text(f'<resources><color name="music_launcher_background">{BACKGROUND}</color></resources>\n')
    with Image.open(RES / 'drawable-nodpi/music_launcher_monochrome.png') as img:
        assert img.getchannel('A').getextrema() == (0,255)
    for file in [RES / 'drawable-nodpi/music_launcher_foreground.png', *RES.glob('mipmap-*/ic_music_launcher*.png')]:
        with Image.open(file) as img:
            img.load()
            assert img.width == img.height
    print('Adaptive, monochrome, 10 density icons and header asset validated.')

if __name__ == '__main__':
    main()
