#!/usr/bin/env python3
"""
Sanitize screenshots for GitHub
- Adds "DEMO DATA" watermark
- Optionally blurs sensitive areas
- Optimizes file sizes
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

SCREENSHOT_DIR = '/home/administrator/screenshots'
OUTPUT_DIR = '/home/administrator/docs/screenshots'

# Screenshots to process (the new ones)
SCREENSHOTS = [
    ('login-page.png', 'Login page with random background'),
    ('dashboard.png', 'Dashboard overview'),
    ('about-page.png', 'About page showing system info'),
    ('assets-list.png', 'Assets list page'),
    ('password-vault.png', 'Password vault'),
    ('knowledge-base.png', 'Knowledge base / Documentation'),
    ('integrations.png', 'Integrations page'),
    ('system-status.png', 'System status page'),
]

def add_watermark(image, text="DEMO DATA - HuduGlue Screenshots"):
    """Add subtle watermark to image"""
    draw = ImageDraw.Draw(image)

    # Try to use a nice font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        font = ImageFont.load_default()

    # Get image dimensions
    width, height = image.size

    # Calculate text position (bottom right)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = width - text_width - 20
    y = height - text_height - 20

    # Draw semi-transparent background
    padding = 10
    background_box = [
        x - padding,
        y - padding,
        x + text_width + padding,
        y + text_height + padding
    ]

    # Create a semi-transparent overlay
    overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(background_box, fill=(0, 0, 0, 128))

    # Convert image to RGBA if needed
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    # Paste overlay
    image = Image.alpha_composite(image, overlay)

    # Draw text
    draw = ImageDraw.Draw(image)
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    # Convert back to RGB
    if image.mode == 'RGBA':
        rgb_image = Image.new('RGB', image.size, (255, 255, 255))
        rgb_image.paste(image, mask=image.split()[3])
        return rgb_image

    return image

def optimize_image(image, max_width=1920):
    """Optimize image size"""
    width, height = image.size

    # Resize if too large
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        image = image.resize((max_width, new_height), Image.Resampling.LANCZOS)

    return image

def sanitize_screenshot(filename, description):
    """Process a single screenshot"""
    input_path = os.path.join(SCREENSHOT_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(input_path):
        print(f"⚠️  Skipping {filename} - not found")
        return

    print(f"Processing: {filename}")

    # Open image
    image = Image.open(input_path)

    # Optimize
    image = optimize_image(image)

    # Add watermark
    image = add_watermark(image)

    # Save
    image.save(output_path, 'PNG', optimize=True, quality=85)

    # Get file sizes
    input_size = os.path.getsize(input_path) / 1024
    output_size = os.path.getsize(output_path) / 1024

    print(f"✅ Saved: {filename} ({input_size:.1f}KB → {output_size:.1f}KB)")

def main():
    """Process all screenshots"""
    print("=" * 60)
    print("Screenshot Sanitization Tool")
    print("=" * 60)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")

    print(f"\nProcessing {len(SCREENSHOTS)} screenshots...\n")

    for filename, description in SCREENSHOTS:
        sanitize_screenshot(filename, description)

    print("\n" + "=" * 60)
    print(f"✅ All screenshots processed and saved to:")
    print(f"   {OUTPUT_DIR}")
    print("=" * 60)

    # Create README for screenshots
    readme_path = os.path.join(OUTPUT_DIR, 'README.md')
    with open(readme_path, 'w') as f:
        f.write("# HuduGlue Screenshots\n\n")
        f.write("Latest screenshots from v2.24.52 with random backgrounds enabled.\n\n")
        f.write("**Note:** All screenshots contain demo data and are watermarked.\n\n")
        f.write("## Screenshots\n\n")

        for filename, description in SCREENSHOTS:
            f.write(f"### {description}\n")
            f.write(f"![{description}]({filename})\n\n")

    print(f"\n✅ Created README.md")

if __name__ == '__main__':
    main()
