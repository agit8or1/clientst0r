"""Asset photo uploads (v3.17.659).

A photo is never stored as uploaded. ``sanitize_photo`` checks the size,
decodes it with the allow-listed decoders only (core.image_safety), checks
the pixel count before decoding, applies the EXIF orientation, then re-encodes
it to a fresh JPEG (or PNG when it has transparency) no larger than
``MAX_EDGE`` pixels. Re-encoding drops every metadata block — EXIF, GPS
location, XMP, ICC comments — and anything appended to the original file.
"""
from __future__ import annotations

from django.core.files.base import ContentFile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000          # e.g. 8000 × 5000; checked before decoding
MAX_EDGE = 1600                  # stored size, longest side
ALLOWED = {'JPEG', 'MPO', 'PNG', 'WEBP', 'GIF'}


def sanitize_photo(uploaded) -> ContentFile:
    """A re-encoded copy of `uploaded`, or ValidationError."""
    from core.image_safety import sanitize_image
    return sanitize_image(
        uploaded, max_bytes=MAX_UPLOAD_BYTES, max_edge=MAX_EDGE, allowed=ALLOWED,
        max_pixels=MAX_PIXELS, messages={
            'size': f'Photos can be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.',
            'type': 'Upload a JPEG, PNG, WebP or GIF image.',
            'pixels': 'That image is too large. Use one under 40 megapixels.',
            'unreadable': 'The image could not be read.',
        })
