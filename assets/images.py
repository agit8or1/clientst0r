"""Asset photo uploads (v3.17.659).

A photo is never stored as uploaded. ``sanitize_photo`` checks the size,
decodes it with the allow-listed decoders only (core.image_safety), checks
the pixel count before decoding, applies the EXIF orientation, then re-encodes
it to a fresh JPEG (or PNG when it has transparency) no larger than
``MAX_EDGE`` pixels. Re-encoding drops every metadata block — EXIF, GPS
location, XMP, ICC comments — and anything appended to the original file.
"""
from __future__ import annotations

import io
import uuid

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000          # e.g. 8000 × 5000; checked before decoding
MAX_EDGE = 1600                  # stored size, longest side
ALLOWED = {'JPEG', 'MPO', 'PNG', 'WEBP', 'GIF'}


def sanitize_photo(uploaded) -> ContentFile:
    """A re-encoded copy of `uploaded`, or ValidationError."""
    from PIL import Image, ImageOps
    from core.image_safety import open_image

    size = getattr(uploaded, 'size', None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise ValidationError(f'Photos can be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')
    try:
        uploaded.seek(0)
        probe = open_image(uploaded)
        fmt = probe.format
        width, height = probe.size
        probe.verify()
    except Exception:
        raise ValidationError('Upload a JPEG, PNG, WebP or GIF image.')
    if fmt not in ALLOWED:
        raise ValidationError('Upload a JPEG, PNG, WebP or GIF image.')
    if width * height > MAX_PIXELS or width < 1 or height < 1:
        raise ValidationError('That image is too large. Use one under 40 megapixels.')

    try:
        uploaded.seek(0)
        img = open_image(uploaded)
        img.seek(0)                      # first frame of an animated GIF / WebP
        img = ImageOps.exif_transpose(img)
        has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
        img = img.convert('RGBA' if has_alpha else 'RGB')
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if has_alpha:
            img.save(out, format='PNG', optimize=True)
            ext = 'png'
        else:
            img.save(out, format='JPEG', quality=85, optimize=True)
            ext = 'jpg'
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('The image could not be read.')
    return ContentFile(out.getvalue(), name=f'{uuid.uuid4().hex}.{ext}')
