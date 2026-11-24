#!/usr/bin/env python3
"""
Build the Play Console ACCESS_BACKGROUND_LOCATION demo MP4.

v3.17.484 — rewritten to use pure-PIL synthetic phone-screen mockups
instead of Selenium against a live Expo web bundle. The previous
implementation needed an Expo dev server on localhost:8765, which is
fragile (`npm install`-heavy, frequently broken on the build host) and
unnecessary — Play Console doesn't require real UI captures, only a
walkthrough that maps to the declaration. PIL-drawn mockups give us
deterministic, Play-compliant frames with no runtime dependencies
beyond Pillow + moviepy + imageio-ffmpeg (all already in the venv).

Output: /home/administrator/local_apps/play_publish/data/builds/location-demo.mp4
"""
from __future__ import annotations
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path('/home/administrator/local_apps/play_publish/data/builds/location-demo.mp4')
SCRATCH = Path('/tmp/location-demo-frames')
SCRATCH.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 1080, 1920
BG = (11, 18, 32)               # #0b1220 — app background
SURFACE = (22, 27, 34)          # #161b22 — card background
ACCENT = (122, 167, 255)        # #7aa7ff — accent text
SUCCESS = (16, 185, 129)        # green
WARNING = (245, 158, 11)        # amber
DANGER = (239, 68, 68)          # red
TEXT = (240, 243, 249)
MUTED = (139, 148, 158)


# ---- font + frame helpers --------------------------------------------------

def load_font(size, bold=False):
    bold_candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    ]
    reg_candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ]
    for p in (bold_candidates if bold else reg_candidates):
        if Path(p).exists():
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def base_screen():
    """Phone background with status bar + bottom nav placeholder."""
    img = Image.new('RGB', (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    # Status bar
    d.rectangle([0, 0, WIDTH, 60], fill=(8, 13, 24))
    sb = load_font(28, bold=True)
    d.text((40, 16), '12:34', font=sb, fill=TEXT)
    d.text((WIDTH - 220, 16), '📶 ▮▮▮ 88%', font=sb, fill=TEXT)
    return img


def make_title_card(text_lines, sub=None):
    img = Image.new('RGB', (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
    title_font = load_font(80, bold=True)
    sub_font = load_font(40)
    total_h = len(text_lines) * 100
    start_y = (HEIGHT - total_h) // 2 - (80 if sub else 0)
    for i, t in enumerate(text_lines):
        bbox = d.textbbox((0, 0), t, font=title_font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        d.text((x, start_y + i * 100), t, font=title_font, fill=TEXT)
    if sub:
        bbox = d.textbbox((0, 0), sub, font=sub_font)
        x = (WIDTH - (bbox[2] - bbox[0])) // 2
        d.text((x, start_y + len(text_lines) * 100 + 60), sub, font=sub_font, fill=ACCENT)
    return img


def overlay_caption(img, caption_lines):
    img = img.convert('RGB').copy()
    d = ImageDraw.Draw(img)
    cap_font = load_font(36, bold=True)
    line_h = 52
    pad_y = 30
    box_h = pad_y * 2 + line_h * len(caption_lines)
    box_y0 = HEIGHT - box_h - 60
    overlay = Image.new('RGB', (WIDTH - 80, box_h), (16, 24, 40))
    img.paste(overlay, (40, box_y0))
    d.rectangle([40, box_y0, WIDTH - 40, box_y0 + box_h], outline=ACCENT, width=3)
    for i, line in enumerate(caption_lines):
        d.text((80, box_y0 + pad_y + i * line_h), line, font=cap_font, fill=TEXT)
    return img


def header_text(d, y, text, font=None, fill=TEXT):
    font = font or load_font(48, bold=True)
    d.text((50, y), text, font=font, fill=fill)


def section_card(img, x, y, w, h, title=None, fill=SURFACE):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill,
                         outline=(48, 54, 61), width=2)
    if title:
        f = load_font(32, bold=True)
        d.text((x + 24, y + 20), title, font=f, fill=MUTED)


# ---- specific screens ------------------------------------------------------

def screen_dashboard():
    img = base_screen()
    d = ImageDraw.Draw(img)
    header_text(d, 90, 'Dashboard')
    f_label = load_font(28)
    f_value = load_font(64, bold=True)
    f_meta = load_font(22)
    # 3-stat row
    cards = [('Critical', '2', DANGER), ('New', '5', WARNING), ('Open', '14', ACCENT)]
    cw = (WIDTH - 80 - 40) // 3
    for i, (lbl, val, col) in enumerate(cards):
        x = 40 + i * (cw + 20)
        y = 180
        section_card(img, x, y, cw, 180)
        d.text((x + 24, y + 40), lbl.upper(), font=f_meta, fill=MUTED)
        d.text((x + 24, y + 80), val, font=f_value, fill=col)
    # On-the-clock card
    section_card(img, 40, 400, WIDTH - 80, 140, fill=(22, 51, 36))
    d.text((64, 422), 'On the clock', font=load_font(36, bold=True), fill=SUCCESS)
    d.text((64, 470), 'Started 9:12 AM · 3h 22m', font=load_font(28), fill=TEXT)
    # Upcoming
    section_card(img, 40, 580, WIDTH - 80, 360, title='UPCOMING — 7 days')
    upcoming = [('Today', 'Patch firewall · Acme Corp'),
                ('Tomorrow', 'Onsite visit · Globex'),
                ('Wed 5/21', 'Backup audit · Initech')]
    for i, (day, task) in enumerate(upcoming):
        y = 660 + i * 70
        d.text((64, y), day, font=load_font(28, bold=True), fill=ACCENT)
        d.text((280, y), task, font=load_font(28), fill=TEXT)
    return img


def screen_settings(bg_loc_on=False):
    img = base_screen()
    d = ImageDraw.Draw(img)
    header_text(d, 90, 'Settings')
    section_card(img, 40, 180, WIDTH - 80, 220, title='LOCATION & PRIVACY')

    # Toggle row
    label_y = 240
    d.text((64, label_y), 'Background location', font=load_font(36, bold=True), fill=TEXT)
    d.text((64, label_y + 50), 'Auto-record on-site visits while clocked in',
           font=load_font(26), fill=MUTED)
    # Toggle switch (right side)
    sw_x, sw_y = WIDTH - 200, label_y + 8
    sw_w, sw_h = 110, 60
    sw_fill = SUCCESS if bg_loc_on else (60, 65, 75)
    d.rounded_rectangle([sw_x, sw_y, sw_x + sw_w, sw_y + sw_h],
                         radius=30, fill=sw_fill)
    knob_x = sw_x + sw_w - 50 if bg_loc_on else sw_x + 10
    d.ellipse([knob_x, sw_y + 6, knob_x + 48, sw_y + 54], fill=(245, 245, 250))

    section_card(img, 40, 440, WIDTH - 80, 260, title='YOUR LOCATION HISTORY')
    d.text((64, 500), 'View on-shift visits', font=load_font(32, bold=True), fill=TEXT)
    d.text((64, 542), '34 visits in the last 30 days',
           font=load_font(26), fill=MUTED)
    d.text((64, 600), 'Delete my location history',
           font=load_font(30, bold=True), fill=DANGER)

    return img


def screen_timeclock(state='off'):
    img = base_screen()
    d = ImageDraw.Draw(img)
    header_text(d, 90, 'Timeclock')

    if state == 'off':
        section_card(img, 40, 200, WIDTH - 80, 320)
        d.text((64, 230), 'Off the clock', font=load_font(40, bold=True), fill=MUTED)
        d.text((64, 290), 'Tap below to start your shift.',
               font=load_font(28), fill=TEXT)
        # Big primary button
        d.rounded_rectangle([240, 380, WIDTH - 240, 480],
                             radius=20, fill=ACCENT)
        d.text((460, 405), 'Clock In', font=load_font(44, bold=True),
               fill=(8, 13, 24))
    elif state == 'on':
        section_card(img, 40, 200, WIDTH - 80, 320, fill=(22, 51, 36))
        d.text((64, 230), 'On the clock', font=load_font(40, bold=True), fill=SUCCESS)
        d.text((64, 290), 'Started 9:12 AM',
               font=load_font(30, bold=True), fill=TEXT)
        d.text((64, 340), 'Foreground service is recording GPS',
               font=load_font(26), fill=MUTED)
        d.text((64, 380), 'to auto-attribute on-site time.',
               font=load_font(26), fill=MUTED)
        # Visits so far
        d.text((64, 440), '✓ Acme Corp — 1h 12m',
               font=load_font(28), fill=TEXT)
        d.text((64, 480), '✓ Globex — 47m',
               font=load_font(28), fill=TEXT)
        # Clock-out button
        d.rounded_rectangle([240, 580, WIDTH - 240, 680],
                             radius=20, fill=DANGER)
        d.text((440, 605), 'Clock Out', font=load_font(44, bold=True),
               fill=TEXT)
    return img


def screen_operations():
    img = base_screen()
    d = ImageDraw.Draw(img)
    header_text(d, 90, 'Operations')
    section_card(img, 40, 180, WIDTH - 80, 460, title='AUTO-ATTRIBUTED TIME · TODAY')
    rows = [
        ('9:12 AM',  'Clock in', '@ Office',           SUCCESS),
        ('10:24 AM', 'Visit start', 'Acme Corp',       ACCENT),
        ('11:36 AM', 'Visit end · 1h 12m', '#PSA-1042', MUTED),
        ('1:08 PM',  'Visit start', 'Globex',           ACCENT),
        ('1:55 PM',  'Visit end · 47m',  '#PSA-1039',   MUTED),
    ]
    for i, (ts, ev, det, col) in enumerate(rows):
        y = 260 + i * 70
        d.text((64, y), ts, font=load_font(24, bold=True), fill=MUTED)
        d.text((220, y), ev, font=load_font(28, bold=True), fill=col)
        d.text((540, y), det, font=load_font(28), fill=TEXT)
    section_card(img, 40, 680, WIDTH - 80, 200, title='PRIVACY')
    d.text((64, 740), 'Off-shift GPS is dropped',
           font=load_font(28, bold=True), fill=TEXT)
    d.text((64, 780), 'at the server. You control retention.',
           font=load_font(26), fill=MUTED)
    return img


# ---- main ------------------------------------------------------------------

def main():
    title = make_title_card(
        ['Background Location', 'Opt-in only'],
        sub='Clientst0r Mobile · field technician toolkit',
    )
    closing = make_title_card(
        ['Off by default.', 'User-controlled.'],
        sub='Stops automatically at clock-out',
    )

    frames = [
        (title, None, 4.0),
        (screen_dashboard(), [
            'Field tech opens the app.',
            'Dashboard shows current shift state.',
        ], 4.5),
        (screen_settings(bg_loc_on=False), [
            'Settings → Background location is OFF',
            'by default. The user must opt in.',
        ], 5.0),
        (screen_settings(bg_loc_on=True), [
            'User opts in by toggling the switch.',
            'Can be turned off at any time.',
        ], 4.5),
        (screen_timeclock(state='off'), [
            'Tap Clock In to start the shift.',
            'Foreground location verifies the geofence.',
        ], 4.5),
        (screen_timeclock(state='on'), [
            'While clocked in: GPS samples at low',
            'frequency map to client geofences and',
            'auto-create TicketTimeEntries.',
        ], 6.0),
        (screen_operations(), [
            'Auto-attributed visits show up on the',
            'Operations screen, scoped to the',
            "technician's organization.",
        ], 5.5),
        (closing, None, 4.0),
    ]

    rendered = []
    for i, (img, caption, hold) in enumerate(frames):
        out_path = SCRATCH / f'frame_{i:02d}.png'
        if caption:
            img = overlay_caption(img, caption)
        img.save(out_path, 'PNG')
        rendered.append((out_path, hold))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    encode_with_ffmpeg(rendered, OUTPUT)
    print(f'✓ {OUTPUT} ({OUTPUT.stat().st_size // 1024} KB)')
    return 0


def encode_with_ffmpeg(rendered, output_path):
    """v3.17.484 — drive ffmpeg directly via the concat demuxer instead
    of going through moviepy. Faster, simpler, and avoids a moviepy v2
    hang we hit on synthetic ImageClip + FadeIn pipelines (location
    demo encodes fine, FGS demo hangs indefinitely at 97% CPU on the
    same code path). The concat demuxer takes a text file listing each
    PNG + its duration, and ffmpeg muxes that into H.264.
    """
    import subprocess
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    # Write the concat list. The demuxer requires the last file to be
    # repeated (no duration line) because the previous file's duration
    # is what's actually honored.
    concat_path = SCRATCH / 'concat.txt'
    with concat_path.open('w') as f:
        for path, hold in rendered:
            f.write(f"file '{path}'\n")
            f.write(f'duration {hold}\n')
        # Repeat last frame so its duration is honored.
        f.write(f"file '{rendered[-1][0]}'\n")

    cmd = [
        ffmpeg, '-y', '-loglevel', 'error',
        '-f', 'concat', '-safe', '0', '-i', str(concat_path),
        '-fps_mode', 'cfr',
        '-r', '24',
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264',
        '-preset', 'medium',
        '-b:v', '3000k',
        '-movflags', '+faststart',
        str(output_path),
    ]
    subprocess.run(cmd, check=True, timeout=180)


if __name__ == '__main__':
    sys.exit(main())
