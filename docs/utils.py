"""
Utility functions for docs app
"""
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from django.core.files.base import ContentFile
import xml.etree.ElementTree as ET


def generate_diagram_thumbnail(diagram, width=300, height=200):
    """
    Generate a simple thumbnail for a diagram.
    Creates a placeholder image with diagram type and title.

    In a full implementation, this would:
    1. Use diagrams.net export API to generate PNG
    2. Resize to thumbnail dimensions
    3. Save to diagram.thumbnail field

    For now, creates a simple placeholder.
    """
    # Create a new image with a light background
    img = Image.new('RGB', (width, height), color=(240, 240, 240))
    draw = ImageDraw.Draw(img)

    # Draw border
    draw.rectangle([(0, 0), (width-1, height-1)], outline=(200, 200, 200), width=2)

    # Draw diagram type icon area (placeholder)
    icon_size = 60
    icon_x = (width - icon_size) // 2
    icon_y = 40
    draw.rectangle(
        [(icon_x, icon_y), (icon_x + icon_size, icon_y + icon_size)],
        outline=(150, 150, 150),
        width=2
    )

    # Add text
    try:
        # Try to use a system font
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
        font_type = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
    except:
        # Fallback to default font
        font_title = ImageFont.load_default()
        font_type = ImageFont.load_default()

    # Draw diagram type
    diagram_type_text = diagram.get_diagram_type_display()
    type_bbox = draw.textbbox((0, 0), diagram_type_text, font=font_type)
    type_width = type_bbox[2] - type_bbox[0]
    type_x = (width - type_width) // 2
    draw.text((type_x, 120), diagram_type_text, fill=(100, 100, 100), font=font_type)

    # Draw title (truncated if too long)
    title = diagram.title
    if len(title) > 30:
        title = title[:27] + "..."

    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    draw.text((title_x, 150), title, fill=(50, 50, 50), font=font_title)

    # Save to BytesIO
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    # Save to diagram thumbnail field
    filename = f"{diagram.slug}_thumb.png"
    diagram.thumbnail.save(filename, ContentFile(buffer.read()), save=False)

    return diagram


def generate_document_preview_image(document, width=300, height=200):
    """
    Generate a preview image for a document template.
    Creates a simple preview showing document icon and title.
    """
    # Create a new image
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Draw border
    draw.rectangle([(0, 0), (width-1, height-1)], outline=(220, 220, 220), width=2)

    # Draw document icon (simple rectangle)
    icon_width = 80
    icon_height = 100
    icon_x = (width - icon_width) // 2
    icon_y = 30

    # Document shape
    draw.rectangle(
        [(icon_x, icon_y), (icon_x + icon_width, icon_y + icon_height)],
        outline=(100, 100, 100),
        fill=(245, 245, 245),
        width=2
    )

    # Add some lines to represent text
    for i in range(4):
        line_y = icon_y + 20 + (i * 15)
        draw.line([(icon_x + 10, line_y), (icon_x + icon_width - 10, line_y)], fill=(180, 180, 180), width=2)

    # Try to use system font
    try:
        font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_label = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
    except:
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()

    # Draw "TEMPLATE" label
    template_text = "TEMPLATE"
    template_bbox = draw.textbbox((0, 0), template_text, font=font_label)
    template_width = template_bbox[2] - template_bbox[0]
    template_x = (width - template_width) // 2
    draw.text((template_x, 145), template_text, fill=(0, 120, 0), font=font_label)

    # Draw title (truncated if too long)
    title = document.title
    if len(title) > 28:
        title = title[:25] + "..."

    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    draw.text((title_x, 165), title, fill=(40, 40, 40), font=font_title)

    # Save to BytesIO
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer


def parse_diagram_xml_info(diagram_xml):
    """
    Parse diagram XML to extract basic information.
    Returns dict with node counts, edge counts, etc.
    """
    try:
        root = ET.fromstring(diagram_xml)

        # Count cells (nodes and edges in mxGraph)
        cells = root.findall('.//*[@value]')

        info = {
            'total_elements': len(cells),
            'has_content': len(cells) > 0,
        }

        return info
    except Exception as e:
        return {
            'total_elements': 0,
            'has_content': False,
            'error': str(e)
        }
