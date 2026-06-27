"""Compose the 1200x630 OG image for Heirloom.

Layout (left-aligned, dark library bg + cyan U logo):
+------------------------------------------------------------+
|                                                            |
|  [U]  AN UNBOUND INFOTECH PRODUCT                          |
|                                                            |
|       Heirloom                                             |
|       Build the version of yourself                        |
|       that gets to stay.                                   |
|                                                            |
|       A private archive of your voice, memories            |
|       and beliefs.  $79 lifetime.                          |
|                                                            |
+------------------------------------------------------------+
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1200, 630

# --- Background: dark library photo with deep gradient overlay ---
bg = Image.open("/tmp/og/bg.jpg").convert("RGB")
# Crop-to-fit 1200x630 (the photo is landscape, so just scale + center-crop)
ratio = max(W / bg.width, H / bg.height)
new = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
left = (new.width - W) // 2
top = (new.height - H) // 2
bg = new.crop((left, top, left + W, top + H))

# Darken + warm-tinted overlay
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(overlay)
# Strong gradient from left (very dark) to right (less dark) to make text legible
for x in range(W):
    # Left 70% is 88% dark; right 30% fades to 50%
    alpha = int(225 - (x / W) * 90)
    od.line([(x, 0), (x, H)], fill=(18, 17, 16, alpha))
# Soft accent vignette on top-right
od.ellipse((W - 600, -200, W + 200, 400), fill=(212, 163, 115, 28))
bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

draw = ImageDraw.Draw(bg)

# --- Fonts ---
SERIF = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"
SERIF_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"
SANS = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"

f_overline = ImageFont.truetype(MONO, 18)
f_brand = ImageFont.truetype(SERIF, 96)
f_tag1 = ImageFont.truetype(SERIF, 50)
f_tag2 = ImageFont.truetype(SERIF, 50)
f_sub = ImageFont.truetype(SANS, 22)
f_price = ImageFont.truetype(SANS_BOLD, 22)

# --- Unbound U logo (top-left) ---
LOGO_SIZE = 92
logo = Image.open("/tmp/og/unbound_logo.png").convert("RGBA")
# The supplied logo has a black square background; make the black transparent
# so the cyan U sits cleanly on our gradient.
px = logo.load()
for y in range(logo.height):
    for x in range(logo.width):
        r, g, b, a = px[x, y]
        if r < 25 and g < 25 and b < 25:
            px[x, y] = (0, 0, 0, 0)
logo = logo.resize((LOGO_SIZE, LOGO_SIZE), Image.LANCZOS)

X = 70  # left margin
Y_LOGO = 70

bg.paste(logo, (X, Y_LOGO), logo)

# Overline next to logo
draw.text(
    (X + LOGO_SIZE + 22, Y_LOGO + 32),
    "AN UNBOUND INFOTECH PRODUCT",
    fill=(212, 163, 115),  # accent
    font=f_overline,
)
draw.text(
    (X + LOGO_SIZE + 22, Y_LOGO + 56),
    "est. 2026  ·  heirloom.app",
    fill=(180, 170, 158),
    font=ImageFont.truetype(MONO, 14),
)

# --- Brand wordmark ---
draw.text(
    (X, Y_LOGO + LOGO_SIZE + 40),
    "Heirloom",
    fill=(245, 240, 230),
    font=f_brand,
)

# --- Two-line tagline ---
draw.text((X, 330), "Build the version of yourself", fill=(238, 232, 220), font=f_tag1)
# Italic-feel: use serif with accent color for the second half
draw.text((X, 388), "that gets to stay.", fill=(212, 163, 115), font=f_tag2)

# --- Sub-line ---
draw.text(
    (X, 470),
    "A private archive of your voice, memories, and beliefs.",
    fill=(200, 192, 178),
    font=f_sub,
)
draw.text(
    (X, 502),
    "A daily AI biographer.  A digital twin your family can sit with one day.",
    fill=(200, 192, 178),
    font=f_sub,
)

# --- Price chip (bottom-left) ---
chip_x, chip_y = X, 555
chip_text = "$79  ·  LIFETIME  ·  NO SUBSCRIPTION"
chip_font = ImageFont.truetype(MONO, 14)
# Measure text so the chip fits exactly
tw = draw.textlength(chip_text, font=chip_font)
chip_w, chip_h = int(tw) + 32, 38
# Pill background
draw.rounded_rectangle(
    (chip_x, chip_y, chip_x + chip_w, chip_y + chip_h),
    radius=4,
    fill=(212, 163, 115),
)
draw.text(
    (chip_x + 16, chip_y + 11),
    chip_text,
    fill=(18, 17, 16),
    font=chip_font,
)

# --- Save ---
out = bg.convert("RGB")
out.save("/app/frontend/public/og-image.jpg", "JPEG", quality=88, optimize=True)
print(f"WROTE /app/frontend/public/og-image.jpg ({out.size})")
