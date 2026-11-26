"""Build sanitized, responsive WebP screenshots + OG image for the site.
Source: Twin Box screenshots of the R8 look update (demo-empty archive).
The signed-in username in the top-right corner is painted over."""
import sys, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
SRC = sys.argv[1] if len(sys.argv) > 1 else '/workspace/heirloom-r8/shots/v3'
OUT = os.path.join(os.path.dirname(__file__), '..', 'assets', 'img')
os.makedirs(OUT, exist_ok=True)

def clean(im):
    im = im.convert('RGB')
    w, h = im.size
    d = ImageDraw.Draw(im)
    if w >= 1400:  # desktop: menu bar username, top-right
        s = w / 1440
        bar = im.getpixel((int(1000 * s), int(5 * s)))
        d.rectangle([int(1260 * s), 0, w, int(30 * s)], fill=bar)
    return im

def emit(name, src, widths, crop=None):
    im = clean(Image.open(os.path.join(SRC, src)))
    if crop: im = im.crop(crop)
    for wd in widths:
        r = im.resize((wd, round(im.height * wd / im.width)), Image.LANCZOS)
        r.save(os.path.join(OUT, f'{name}-{wd}.webp'), 'WEBP', quality=78, method=6)
    print(name, im.size)
    return im

desk = {'twin': 'after_twin_desk.png', 'today': 'after_today_desk.png', 'memory': 'after_memory_desk.png',
        'reminders': 'after_reminders_desk.png'}
ims = {k: emit(k, v, [720, 1200, 1440]) for k, v in desk.items()}
for k, v in {'phone-twin': 'after_twin_phone.png', 'phone-today': 'after_today_phone.png'}.items():
    emit(k, v, [260, 390])

# OG image 1200x630
F = '/usr/share/fonts/truetype/sand-box/google'
CG = '/tmp/cg500.ttf'
if not os.path.exists(CG):
    os.system(f'python3 -m fontTools.varLib.instancer "{F}/Cormorant Garamond/CormorantGaramond-VariableFont_wght.ttf" wght=500 -o {CG} -q')
serif = ImageFont.truetype(CG, 76)
sans = ImageFont.truetype(f'{F}/Manrope/Manrope-VariableFont_wght.ttf', 28)
small = ImageFont.truetype(f'{F}/Manrope/Manrope-VariableFont_wght.ttf', 22)
for f in (sans, small): f.set_variation_by_axes([560])
og = Image.new('RGB', (1200, 630), (18, 17, 16))
shot = ims['twin'].resize((720, 450), Image.LANCZOS)
mask = Image.new('L', shot.size, 255)
og.paste(shot, (560, 150), mask)
d = ImageDraw.Draw(og)
d.rectangle([558, 148, 1281, 601], outline=(212, 163, 115), width=2)
# fade the left edge of the screenshot
grad = Image.new('L', (200, 630))
for x in range(200): ImageDraw.Draw(grad).line([(x, 0), (x, 630)], fill=int(255 * (1 - x / 200)))
og.paste(Image.new('RGB', (200, 630), (18, 17, 16)), (556, 0), grad)
d.text((64, 70), 'HEIRLOOM UNBOUND', font=small, fill=(212, 163, 115))
d.multiline_text((64, 120), 'Your stories,\nin your voice.\nKept at home.', font=serif, fill=(240, 233, 222), spacing=6)
d.multiline_text((64, 410), 'A fully local AI twin for your family.\nNo cloud AI. Never invents a memory.', font=sans, fill=(190, 180, 168), spacing=10)
d.text((64, 560), 'by Unbound Infotech', font=small, fill=(140, 130, 120))
og.save(os.path.join(OUT, 'og-image.jpg'), 'JPEG', quality=86, optimize=True, progressive=True)
print('og done')
