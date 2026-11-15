"""Generate the application's own book icon using Pillow, without external assets."""
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
image = Image.new('RGBA', (1024, 1024), (0, 0, 0, 0))
d = ImageDraw.Draw(image)
d.rounded_rectangle((0, 0, 1023, 1023), radius=230, fill='#16786c')
d.polygon([(210, 280), (470, 330), (470, 760), (210, 710)], fill='#ffffff')
d.polygon([(530, 330), (810, 280), (810, 710), (530, 760)], fill='#e2f1e8')
d.line([(500, 340), (500, 775)], fill='#b4d7c8', width=10)
d.polygon([(675, 310), (735, 299), (735, 500), (705, 478), (675, 510)], fill='#e9bd76')
build = ROOT / 'build'
build.mkdir(exist_ok=True)
image.resize((256, 256), Image.Resampling.LANCZOS).save(build / 'icon.png')
image.save(build / 'icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
for density, size in [('mdpi',48),('hdpi',72),('xhdpi',96),('xxhdpi',144),('xxxhdpi',192)]:
    folder = ROOT / 'android/app/src/main/res' / ('mipmap-' + density)
    folder.mkdir(exist_ok=True)
    icon = image.resize((size, size), Image.Resampling.LANCZOS)
    icon.save(folder / 'ic_launcher.png')
    icon.save(folder / 'ic_launcher_round.png')
    foreground = Image.new('RGBA',(size*2,size*2),(0,0,0,0))
    foreground.alpha_composite(icon, (size//2,size//2))
    foreground.save(folder / 'ic_launcher_foreground.png')
