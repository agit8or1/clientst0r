#!/usr/bin/env python3
"""
Generate the 1024×500 Play Console feature graphic for Clientst0r Mobile.

Composition:
  - Dark navy backdrop matching the app's #0b1220
  - Brand text on the left ("Clientst0r" + tagline)
  - Mini dashboard mockup (cropped from the captured phone screenshot)
    on the right inside a phone-frame outline
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WORKTREE = Path('/home/administrator/.dev-worktree')
OUT_DIR = WORKTREE / 'docs' / 'mobile-screenshots'
OUT_FILE = OUT_DIR / 'feature-graphic.png'

BG = (11, 18, 32)           # #0b1220 — app background
ACCENT = (122, 167, 255)    # app's hyperlink blue
HEADING = (240, 243, 249)
MUTED = (155, 170, 200)
PILL = (31, 36, 51)


def find_font(*candidates) -> str:
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates_bold = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]
    candidates_reg = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    path = find_font(*(candidates_bold if bold else candidates_reg))
    if path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(path, size=size)


def main() -> int:
    img = Image.new('RGB', (1024, 500), BG)

    # Subtle radial-ish gradient on the right half so the device pops.
    overlay = Image.new('RGB', (1024, 500), BG)
    od = ImageDraw.Draw(overlay)
    # Soft accent glow on the right
    for i, alpha in enumerate(range(0, 60, 4)):
        od.ellipse([
            800 - i * 6, 100 - i * 4,
            1100 + i * 6, 400 + i * 4,
        ], outline=(20 + i, 30 + i, 60 + i))
    img = Image.blend(img, overlay, 0.4)

    draw = ImageDraw.Draw(img)

    # ---- Left column: brand + tagline ----
    title_font = load_font(64, bold=True)
    tag_font = load_font(22, bold=False)
    pill_font = load_font(16, bold=True)

    draw.text((48, 110), 'Clientst0r', font=title_font, fill=HEADING)
    draw.text((48, 192), 'Self-hosted IT management', font=tag_font, fill=MUTED)
    draw.text((48, 222), 'for MSPs and IT teams', font=tag_font, fill=MUTED)

    # Feature pills
    pills = ['Tickets', 'Assets', 'Vault', 'Vehicles', 'Compliance']
    x = 48
    y = 320
    for p in pills:
        # measure text
        bbox = draw.textbbox((0, 0), p, font=pill_font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        pad_x, pad_y = 14, 8
        draw.rounded_rectangle(
            [x, y, x + w + pad_x * 2, y + h + pad_y * 2 + 4],
            radius=16,
            fill=PILL,
            outline=ACCENT,
            width=1,
        )
        draw.text((x + pad_x, y + pad_y), p, font=pill_font, fill=ACCENT)
        x += w + pad_x * 2 + 10

    # ---- Right column: phone mockup ----
    phone_src = OUT_DIR / 'phone' / 'dashboard.png'
    if phone_src.exists():
        ph = Image.open(phone_src).convert('RGB')
        # Crop to the top portion which is the most visually-dense (skip the
        # mostly-empty footer).
        ph = ph.crop((0, 0, ph.width, min(ph.height, 1800)))
        # Fit into a phone frame ~280×500. Maintain aspect.
        target_h = 440
        target_w = int(ph.width * (target_h / ph.height))
        ph = ph.resize((target_w, target_h), Image.LANCZOS)

        # Build a rounded-corner frame
        frame_w = target_w + 16
        frame_h = target_h + 16
        frame_x = 1024 - frame_w - 40
        frame_y = (500 - frame_h) // 2

        # Outer phone bezel
        draw.rounded_rectangle(
            [frame_x, frame_y, frame_x + frame_w, frame_y + frame_h],
            radius=20,
            fill=(0, 0, 0),
            outline=ACCENT,
            width=2,
        )
        # Paste the screenshot inside the bezel
        img.paste(ph, (frame_x + 8, frame_y + 8))

    img.save(OUT_FILE, 'PNG', optimize=True)
    print(f'Saved {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} KB)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
