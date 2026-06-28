"""Compose the Stripe checkout product image for Heirloom.

Square 1024x1024 — Stripe shows it small (~150x150 in the sidebar), so the
composition is iconic: cyan U logo, serif "Heirloom" wordmark, tiny accent
"a continuation of you" line, gold "$79 LIFETIME" pill. Dark library bg with
strong vignette for readability.
"""
from PIL import Image, ImageDraw, ImageFont

S = 1024  # square

# --- Background: dark library, vignetted heavily so logo + text pop ---
bg = Image.open("/tmp/og/bg.jpg").convert("RGB")
ratio = max(S / bg.width, S / bg.height)
new = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
left = (new.width - S) // 2
top = (new.height - S) // 2
bg = new.crop((left, top, left + S, top + S))

# Strong dark vignette — radial-ish via overlaid ellipses
overlay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
# Base dim
od.rectangle((0, 0, S, S), fill=(14, 13, 12, 175))
# Slight accent glow top-right
od.ellipse((S - 720, -300, S + 220, 600), fill=(212, 163, 115, 22))
# Deep edge vignette
od.ellipse((-200, -200, S + 200, S + 200), outline=None, fill=(0, 0, 0, 0))
for i in range(60):
    a = int(2 + i * 1.4)
    pad = i * 5
    od.ellipse((-pad, -pad, S + pad, S + pad), outline=(0, 0, 0, a), width=2)
bg = Image.alpha_composite(bg.convert("RGBA"), overlay)
draw = ImageDraw.Draw(bg)

# --- Fonts ---
SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
MONO_BOLD = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"

f_brand = ImageFont.truetype(SERIF, 138)
f_tag = ImageFont.truetype(SERIF, 38)
f_overline = ImageFont.truetype(MONO_BOLD, 22)
f_chip = ImageFont.truetype(MONO_BOLD, 22)

# --- U logo (top center, large) ---
LOGO_SIZE = 270
logo = Image.open("/tmp/og/unbound_logo.png").convert("RGBA")
# Strip black background to alpha so it sits clean on the gradient
px = logo.load()
for y in range(logo.height):
    for x in range(logo.width):
        r, g, b, a = px[x, y]
        if r < 25 and g < 25 and b < 25:
            px[x, y] = (0, 0, 0, 0)
logo = logo.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)
bg.paste(logo, ((S - LOGO_SIZE) // 2, 175), logo)

# --- Overline ---
overline_text = "AN UNBOUND INFOTECH PRODUCT"
ow = draw.textlength(overline_text, font=f_overline)
draw.text(((S - ow) // 2, 480), overline_text, fill=(212, 163, 115), font=f_overline)

# --- Heirloom wordmark (centered) ---
brand_text = "Heirloom"
bw = draw.textlength(brand_text, font=f_brand)
draw.text(((S - bw) // 2, 525), brand_text, fill=(245, 240, 230), font=f_brand)

# --- Tagline ---
tag_text = "a continuation of you"
tw = draw.textlength(tag_text, font=f_tag)
draw.text(((S - tw) // 2, 700), tag_text, fill=(180, 170, 158), font=f_tag)

# --- $79 LIFETIME chip (bottom center) ---
chip_text = "$79  ·  LIFETIME  ·  ONE-TIME"
cw = draw.textlength(chip_text, font=f_chip)
chip_w = int(cw) + 56
chip_h = 56
chip_x = (S - chip_w) // 2
chip_y = 820
draw.rounded_rectangle(
    (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
    radius=4,
    fill=(212, 163, 115),
)
draw.text(
    (chip_x + 28, chip_y + 17),
    chip_text,
    fill=(18, 17, 16),
    font=f_chip,
)

out = bg.convert("RGB")
out.save("/app/frontend/public/stripe-checkout-image.jpg", "JPEG", quality=90, optimize=True)

import os
size_kb = os.path.getsize("/app/frontend/public/stripe-checkout-image.jpg") / 1024
print(f"WROTE /app/frontend/public/stripe-checkout-image.jpg ({out.size}, {size_kb:.0f} KB)")
