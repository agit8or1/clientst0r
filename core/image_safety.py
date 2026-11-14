"""Only decode the image formats the application accepts.

Pillow's ``Image.open`` ignores the filename and tries every registered
decoder on the bytes: an upload named ``logo.png`` that is really EPS, FPX,
TIFF, SPIDER, PCX, MIC, XBM … reaches that decoder. Django's ``ImageField``
validation calls ``Image.open`` the same way, so every avatar, logo, rack photo,
location image and attachment thumbnail is exposed to the whole decoder set —
including decoders with recent advisories (Ghostscript argument injection for
EPS, FlashPix heap overflow, TIFF out-of-bounds reads).

``restrict_decoders()`` runs once at startup (``core.apps``) and removes every
decoder outside ``ALLOWED_FORMATS`` from Pillow's registry, so a file in any
other format fails to open no matter what it is called. Encoders are untouched:
the application still writes PNG/JPEG/PDF.
"""
from __future__ import annotations

# What browsers display and what users upload. MPO is how Pillow opens
# multi-picture JPEGs from phones and cameras.
ALLOWED_FORMATS = frozenset({'PNG', 'JPEG', 'MPO', 'GIF', 'WEBP', 'BMP', 'ICO'})

_applied = False


def restrict_decoders():
    """Drop every Pillow decoder not in ALLOWED_FORMATS. Idempotent."""
    global _applied
    from PIL import Image
    Image.init()  # load every plugin now, so none is registered later
    for fmt in list(Image.OPEN):
        if fmt not in ALLOWED_FORMATS:
            Image.OPEN.pop(fmt, None)
    for fmt in list(Image.ID):
        if fmt not in ALLOWED_FORMATS:
            Image.ID.remove(fmt)
    _applied = True
    return sorted(Image.OPEN)


def open_image(fp):
    """Image.open limited to the allowed formats (works even before ready())."""
    from PIL import Image
    Image.init()
    # MPO has no opener of its own (the JPEG factory returns it), so only pass
    # formats Pillow can actually open.
    return Image.open(fp, formats=sorted(f for f in ALLOWED_FORMATS if f in Image.OPEN))


def sanitize_image(uploaded, *, max_bytes, max_edge, allowed, max_pixels=40_000_000,
                   messages=None):
    """A re-encoded copy of an uploaded image, or ValidationError.

    Checks the size, decodes with the allow-listed decoders only, checks the
    pixel count before decoding, applies the EXIF orientation, then writes a
    fresh JPEG (PNG when it has transparency) no larger than `max_edge`
    pixels under a random name. Re-encoding drops every metadata block and
    anything appended to the original file. Used for asset photos
    (assets.images) and portal branding (core.portal_settings_views).
    `messages` overrides the wording: keys size, type, pixels, unreadable.
    """
    import io
    import uuid

    from django.core.exceptions import ValidationError
    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    msg = {
        'size': f'Images can be at most {max_bytes // (1024 * 1024)} MB.',
        'type': 'Upload a PNG, JPEG or WebP image.',
        'pixels': 'That image is too large. Use one under 40 megapixels.',
        'unreadable': 'The image could not be read.',
    }
    msg.update(messages or {})

    size = getattr(uploaded, 'size', None)
    if size is not None and size > max_bytes:
        raise ValidationError(msg['size'])
    try:
        uploaded.seek(0)
        probe = open_image(uploaded)
        fmt = probe.format
        width, height = probe.size
        probe.verify()
    except Exception:
        raise ValidationError(msg['type'])
    if fmt not in allowed:
        raise ValidationError(msg['type'])
    if width * height > max_pixels or width < 1 or height < 1:
        raise ValidationError(msg['pixels'])

    try:
        uploaded.seek(0)
        img = open_image(uploaded)
        img.seek(0)                      # first frame of an animated GIF / WebP
        img = ImageOps.exif_transpose(img)
        has_alpha = img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info)
        img = img.convert('RGBA' if has_alpha else 'RGB')
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if has_alpha:
            img.save(out, format='PNG', optimize=True)
            ext = 'png'
        else:
            img.save(out, format='JPEG', quality=85, optimize=True)
            ext = 'jpg'
    except Exception:
        raise ValidationError(msg['unreadable'])
    return ContentFile(out.getvalue(), name=f'{uuid.uuid4().hex}.{ext}')
