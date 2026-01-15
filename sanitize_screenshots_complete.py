#!/usr/bin/env python3
"""
Sanitize complete screenshots for GitHub
- Adds "DEMO DATA" watermark
- Optimizes file sizes
"""
import os
from PIL import Image, ImageDraw, ImageFont

SCREENSHOT_DIR = '/home/administrator/screenshots_complete'
OUTPUT_DIR = '/home/administrator/docs/screenshots'

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

def sanitize_screenshot(filename):
    """Process a single screenshot"""
    input_path = os.path.join(SCREENSHOT_DIR, filename)
    output_path = os.path.join(OUTPUT_DIR, filename)

    if not os.path.exists(input_path):
        print(f"⚠️  Skipping {filename} - not found")
        return False

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
    return True

def main():
    """Process all screenshots"""
    print("=" * 60)
    print("Screenshot Sanitization Tool - Complete Set")
    print("=" * 60)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Created output directory: {OUTPUT_DIR}")

    # Get all PNG files from source directory
    screenshots = sorted([f for f in os.listdir(SCREENSHOT_DIR) if f.endswith('.png')])

    print(f"\nProcessing {len(screenshots)} screenshots...\n")

    successful = 0
    failed = 0

    for filename in screenshots:
        if sanitize_screenshot(filename):
            successful += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"✅ Successfully processed: {successful}")
    if failed > 0:
        print(f"⚠️  Failed: {failed}")
    print(f"   Output directory: {OUTPUT_DIR}")
    print("=" * 60)

if __name__ == '__main__':
    main()
