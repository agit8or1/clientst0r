#!/usr/bin/env python3
"""
Build the Play Console FOREGROUND_SERVICE_LOCATION demo MP4.

v3.17.484 — pure-PIL synthetic frames (no Selenium / Expo bundle).
Same rendering approach as generate_location_demo_video.py but the
narration + an explicit simulated notification-shade frame focus on
the foreground-service lifecycle and the persistent notification —
the visual proof Play wants for an FGS_LOCATION declaration.

Output: /home/administrator/local_apps/play_publish/data/builds/fgs-demo.mp4
"""
from __future__ import annotations
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path('/home/administrator/local_apps/play_publish/data/builds/fgs-demo.mp4')
SCRATCH = Path('/tmp/fgs-demo-frames')
SCRATCH.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 1080, 1920
BG = (11, 18, 32)
SURFACE = (22, 27, 34)
ACCENT = (122, 167, 255)
SUCCESS = (16, 185, 129)
WARNING = (245, 158, 11)
DANGER = (239, 68, 68)
TEXT = (240, 243, 249)
MUTED = (139, 148, 158)


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
    img = Image.new('RGB', (WIDTH, HEIGHT), BG)
    d = ImageDraw.Draw(img)
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


def section_card(img, x, y, w, h, title=None, fill=SURFACE):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + w, y + h], radius=16, fill=fill,
                         outline=(48, 54, 61), width=2)
    if title:
        f = load_font(32, bold=True)
        d.text((x + 24, y + 20), title, font=f, fill=MUTED)


def screen_settings_on():
    """Settings screen with background location toggled ON (opt-in)."""
    img = base_screen()
    d = ImageDraw.Draw(img)
    d.text((50, 90), 'Settings', font=load_font(48, bold=True), fill=TEXT)
    section_card(img, 40, 180, WIDTH - 80, 220, title='LOCATION & PRIVACY')
    label_y = 240
    d.text((64, label_y), 'Background location',
           font=load_font(36, bold=True), fill=TEXT)
    d.text((64, label_y + 50), 'Auto-record on-site visits while clocked in',
           font=load_font(26), fill=MUTED)
    # Toggle ON
    sw_x, sw_y = WIDTH - 200, label_y + 8
    d.rounded_rectangle([sw_x, sw_y, sw_x + 110, sw_y + 60],
                         radius=30, fill=SUCCESS)
    d.ellipse([sw_x + 60, sw_y + 6, sw_x + 108, sw_y + 54],
              fill=(245, 245, 250))
    return img


def screen_timeclock_clockin():
    img = base_screen()
    d = ImageDraw.Draw(img)
    d.text((50, 90), 'Timeclock', font=load_font(48, bold=True), fill=TEXT)
    section_card(img, 40, 200, WIDTH - 80, 320)
    d.text((64, 230), 'Off the clock', font=load_font(40, bold=True), fill=MUTED)
    d.text((64, 290), 'Tap below to start your shift.',
           font=load_font(28), fill=TEXT)
    d.rounded_rectangle([240, 380, WIDTH - 240, 480],
                         radius=20, fill=ACCENT)
    d.text((460, 405), 'Clock In', font=load_font(44, bold=True),
           fill=(8, 13, 24))
    # Arrow pointing at the button
    d.text((280, 510), '▲ User taps Clock In',
           font=load_font(30, bold=True), fill=ACCENT)
    return img


def screen_timeclock_running():
    img = base_screen()
    d = ImageDraw.Draw(img)
    d.text((50, 90), 'Timeclock', font=load_font(48, bold=True), fill=TEXT)
    section_card(img, 40, 200, WIDTH - 80, 320, fill=(22, 51, 36))
    d.text((64, 230), 'On the clock', font=load_font(40, bold=True), fill=SUCCESS)
    d.text((64, 290), 'Foreground service running · type=location',
           font=load_font(26, bold=True), fill=ACCENT)
    d.text((64, 340), 'Persistent notification visible (see frame).',
           font=load_font(26), fill=TEXT)
    d.text((64, 380), 'Service stops when you Clock Out.',
           font=load_font(26), fill=MUTED)
    # Sample visits
    d.text((64, 440), '✓ Acme Corp — 1h 12m',
           font=load_font(28), fill=TEXT)
    d.text((64, 480), '✓ Globex — 47m',
           font=load_font(28), fill=TEXT)
    # Clock-out
    d.rounded_rectangle([240, 580, WIDTH - 240, 680],
                         radius=20, fill=DANGER)
    d.text((440, 605), 'Clock Out', font=load_font(44, bold=True),
           fill=TEXT)
    return img


def screen_timeclock_stopped():
    img = base_screen()
    d = ImageDraw.Draw(img)
    d.text((50, 90), 'Timeclock', font=load_font(48, bold=True), fill=TEXT)
    section_card(img, 40, 200, WIDTH - 80, 320)
    d.text((64, 230), 'Off the clock', font=load_font(40, bold=True), fill=MUTED)
    d.text((64, 290), 'Foreground service stopped.',
           font=load_font(28, bold=True), fill=SUCCESS)
    d.text((64, 340), 'Notification cleared.',
           font=load_font(28), fill=TEXT)
    d.text((64, 380), '8h 22m logged across 4 visits today.',
           font=load_font(28), fill=MUTED)
    return img


def screen_notification_shade():
    """Simulated Android notification shade with the persistent FGS notification."""
    img = Image.new('RGB', (WIDTH, HEIGHT), (24, 24, 28))
    d = ImageDraw.Draw(img)
    # Status bar
    d.rectangle([0, 0, WIDTH, 60], fill=(12, 12, 16))
    sb = load_font(28, bold=True)
    d.text((40, 16), '12:34', font=sb, fill=TEXT)
    d.text((WIDTH - 220, 16), '📶 ▮▮▮ 88%', font=sb, fill=TEXT)
    # Shade header
    d.text((40, 100), 'Ongoing', font=load_font(34, bold=True), fill=(180, 180, 200))

    # Notification card
    card_x, card_y = 30, 170
    card_w, card_h = WIDTH - 60, 410
    d.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                         radius=24, fill=(38, 40, 50))

    # App icon
    icon_x, icon_y = card_x + 40, card_y + 40
    d.rounded_rectangle([icon_x, icon_y, icon_x + 90, icon_y + 90],
                         radius=18, fill=(59, 130, 246))
    d.text((icon_x + 20, icon_y + 18), 'CS',
           font=load_font(44, bold=True), fill=TEXT)

    # App name + flag
    d.text((card_x + 160, card_y + 50),
           'Clientst0r', font=load_font(32, bold=True), fill=TEXT)
    d.text((card_x + 160, card_y + 92),
           'now', font=load_font(24), fill=(160, 160, 180))
    d.text((card_x + card_w - 240, card_y + 50),
           '● PERSISTENT', font=load_font(24, bold=True), fill=WARNING)

    # Title + body
    d.text((card_x + 40, card_y + 170),
           'Tracking your shift',
           font=load_font(40, bold=True), fill=TEXT)
    body_lines = [
        'Location used to log on-site visits',
        'to client geofences while clocked in.',
        'Tap to open Timeclock.',
    ]
    for i, line in enumerate(body_lines):
        d.text((card_x + 40, card_y + 230 + i * 42),
               line, font=load_font(30), fill=(220, 220, 235))

    # FGS-type badge
    badge_y = card_y + card_h - 70
    d.rounded_rectangle(
        [card_x + 40, badge_y, card_x + 460, badge_y + 50],
        radius=10, fill=(20, 60, 120), outline=(80, 130, 200), width=2,
    )
    d.text((card_x + 60, badge_y + 10),
           'TYPE: location · FGS',
           font=load_font(28, bold=True), fill=(180, 210, 255))

    # Explainer below
    expl_y = card_y + card_h + 80
    d.text((40, expl_y),
           'Android shows this notification',
           font=load_font(34, bold=True), fill=TEXT)
    d.text((40, expl_y + 48),
           'the entire time the foreground',
           font=load_font(34, bold=True), fill=TEXT)
    d.text((40, expl_y + 96),
           'service is running.',
           font=load_font(34, bold=True), fill=TEXT)

    return img


def main():
    title = make_title_card(
        ['Foreground Service', 'type=location'],
        sub='User-visible persistent notification · FGS_LOCATION declaration',
    )
    closing = make_title_card(
        ['Notification visible', 'while service runs.'],
        sub='Stops automatically at Clock Out',
    )

    frames = [
        (title, None, 4.0),
        (screen_settings_on(), [
            'Settings → Background location toggled ON',
            '(opt-in, default OFF).',
        ], 5.0),
        (screen_timeclock_clockin(), [
            'Tech taps Clock In.',
            'App starts an Android foreground service',
            'with type=location.',
        ], 5.0),
        (screen_notification_shade(), None, 7.0),
        (screen_timeclock_running(), [
            'Service runs only while clocked in.',
            'GPS → server geofence match',
            '→ TicketTimeEntry created.',
        ], 5.5),
        (screen_timeclock_stopped(), [
            'Tech taps Clock Out.',
            'Foreground service stops immediately.',
            'Persistent notification clears.',
        ], 5.0),
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
    """v3.17.484 — drive ffmpeg directly via the concat demuxer. See
    note in generate_location_demo_video.py for the moviepy v2 hang
    that motivated this approach."""
    import subprocess
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    concat_path = SCRATCH / 'concat.txt'
    with concat_path.open('w') as f:
        for path, hold in rendered:
            f.write(f"file '{path}'\n")
            f.write(f'duration {hold}\n')
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
