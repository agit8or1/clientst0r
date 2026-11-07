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
