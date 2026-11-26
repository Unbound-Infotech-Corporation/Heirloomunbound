#!/usr/bin/env python3
"""Self-hosted brand fonts: Cormorant Garamond 500 (+italic) with lining figures as default, Manrope variable.
Latin subset, woff2. Needs fonttools + brotli and the Google Fonts TTFs (FONT_DIR)."""
import os, subprocess
from fontTools.ttLib import TTFont
F = os.environ.get('FONT_DIR', '/usr/share/fonts/truetype/sand-box/google')
OUT = os.path.join(os.path.dirname(__file__), '..', 'public', 'assets', 'fonts')
U = 'U+0020-007E,U+00A0-00FF,U+2013,U+2014,U+2018,U+2019,U+201C,U+201D,U+2026,U+2022,U+2192,U+00B7,U+2212,U+2264,U+2265,U+00D7'
DIG = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
def run(*a): subprocess.run(a, check=True)
for src, name in [(f'{F}/Cormorant Garamond/CormorantGaramond-VariableFont_wght.ttf', 'cormorant-500'),
                  (f'{F}/Cormorant Garamond/CormorantGaramond-Italic-VariableFont_wght.ttf', 'cormorant-500i')]:
    tmp = f'/tmp/{name}.ttf'
    run('python3', '-m', 'fontTools.varLib.instancer', src, 'wght=500', '-o', tmp, '-q')
    f = TTFont(tmp); go = set(f.getGlyphOrder())
    for t in f['cmap'].tables:
        if t.isUnicode():
            for i, n in enumerate(DIG):
                if n + '.lf' in go: t.cmap[0x30 + i] = n + '.lf'   # lining figures by default
    f.save(tmp)
    run('pyftsubset', tmp, f'--unicodes={U}', '--flavor=woff2', '--layout-features=kern,liga', f'--output-file={OUT}/{name}.woff2')
run('pyftsubset', f'{F}/Manrope/Manrope-VariableFont_wght.ttf', f'--unicodes={U}', '--flavor=woff2', '--layout-features=kern,liga', f'--output-file={OUT}/manrope-var.woff2')
print('fonts ok')
