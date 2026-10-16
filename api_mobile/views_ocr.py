"""
Receipt OCR endpoint (v3.17.465).

Pre-fill helper for the fuel-log form: the mobile app uploads a receipt
photo, the server runs OCR + a regex parser, and returns extracted
`gallons` / `total_cost` / `station` / `date` so the form can pre-fill
empty fields. The user always reviews and submits — OCR is a hint, not
a write.

**Off by default.** Enable by setting:
  - `OCR_PROVIDER=cloudvision` in env
  - `GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json`

When unset, the endpoint returns 503 with `{detail: "OCR not configured"}`
so the mobile app degrades to manual entry. No crash, no log spam.

To plug in a different provider (AWS Textract, Tesseract, etc.), keep
the same response shape and add another branch in `_run_ocr()`.
"""
from __future__ import annotations

import logging
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from rest_framework import status as drf_status
from .authentication import MobileTokenAuthentication
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

logger = logging.getLogger('api_mobile.ocr')


def _ocr_provider() -> str:
    return (os.environ.get('OCR_PROVIDER') or '').strip().lower()


def _run_ocr_cloudvision(image_bytes: bytes) -> Optional[str]:
    """Returns the raw extracted text via Google Cloud Vision, or None
    on failure. The Cloud Vision SDK is imported lazily so a server
    without OCR configured doesn't pay the import cost."""
    try:
        from google.cloud import vision  # type: ignore
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        response = client.document_text_detection(image=image)
        if response.error.message:
            logger.warning('cloud vision error: %s', response.error.message)
            return None
        return response.full_text_annotation.text if response.full_text_annotation else None
    except Exception as exc:  # noqa: BLE001
        logger.warning('cloud vision failed: %s', exc)
        return None


def _run_ocr(image_bytes: bytes) -> Optional[str]:
    provider = _ocr_provider()
    if provider == 'cloudvision':
        return _run_ocr_cloudvision(image_bytes)
    # add other providers here (textract, tesseract) when needed
    return None


# Receipt regex parsers — best-effort, US fuel receipt formats.
# These are intentionally lenient since OCR text is noisy. A miss
# leaves the field unset rather than guessing wrong.
_GALLONS_RE = re.compile(
    r'(?i)(?:gal(?:lons?)?|qty|gallons\s*pumped)\s*[:=]?\s*(\d+(?:\.\d+)?)',
)
_TOTAL_RE = re.compile(
    r'(?i)(?:total|amount\s*due|amount|paid|grand\s*total)\s*[:=]?\s*\$?\s*(\d+(?:\.\d{2})?)',
)
_PRICE_PER_GAL_RE = re.compile(
    r'(?i)(?:price/gal|per\s*gal(?:lon)?|price\s*per\s*gallon|\$/gal)\s*[:=]?\s*\$?\s*(\d+(?:\.\d{1,3})?)',
)
# Date in YYYY-MM-DD, MM/DD/YYYY, MM-DD-YYYY
_DATE_RE = re.compile(
    r'\b(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\b',
)
# Station name: a heuristic — uppercase brand on its own line near top
_STATION_RE = re.compile(
    # Leading whitespace tolerant — OCR output often has indentation.
    r'^\s*(SHELL|BP|EXXON|CHEVRON|MOBIL|TEXACO|MARATHON|SUNOCO|CITGO|CONOCO|VALERO|76|PHILLIPS\s*66|SPEEDWAY|WAWA|COSTCO|SAM\'S\s*CLUB|KROGER|7-?ELEVEN)\b',
    re.IGNORECASE | re.MULTILINE,
)


def _parse_receipt_text(text: str) -> dict[str, Any]:
    """Extract fields from OCR'd receipt text. Returns only the fields
    we actually found — missing fields stay missing so the mobile
    pre-fill never overwrites with bogus guesses."""
    out: dict[str, Any] = {}

    g = _GALLONS_RE.search(text)
    if g:
        try:
            out['gallons'] = str(Decimal(g.group(1)))
        except InvalidOperation:
            pass

    p = _PRICE_PER_GAL_RE.search(text)
    if p:
        try:
            out['cost_per_gallon'] = str(Decimal(p.group(1)))
        except InvalidOperation:
            pass

    t = _TOTAL_RE.search(text)
    if t:
        try:
            out['total_cost'] = str(Decimal(t.group(1)))
        except InvalidOperation:
            pass

    d = _DATE_RE.search(text)
    if d:
        out['date_raw'] = d.group(1)

    s = _STATION_RE.search(text)
    if s:
        # Normalize spacing/casing
        out['station'] = ' '.join(s.group(1).split()).title()

    return out


@api_view(['GET'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
def ocr_status_view(request):
    """
    GET /api/mobile/v1/ocr/status/

    Diagnostic. Returns whether OCR is configured + whether the SDK is
    importable. Useful for "did I actually wire this up correctly" checks
    from the mobile app or curl. Never exposes the credential path itself.
    """
    provider = _ocr_provider()
    if not provider:
        return Response({
            'configured': False,
            'provider': None,
            'detail': 'Set OCR_PROVIDER env var to enable.',
        })
    sdk_ok = False
    sdk_error = None
    if provider == 'cloudvision':
        try:
            from google.cloud import vision  # noqa: F401  type: ignore
            sdk_ok = True
        except Exception as exc:
            sdk_error = f'{type(exc).__name__}: {exc}'
    return Response({
        'configured': True,
        'provider': provider,
        'sdk_loadable': sdk_ok,
        'sdk_error': sdk_error,
        'credentials_env_set': bool(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')),
    })


@api_view(['POST'])
@authentication_classes([MobileTokenAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def ocr_receipt_view(request):
    """
    POST /api/mobile/v1/ocr/receipt/  (multipart/form-data)

    Body: `photo` (file). Returns 200 with extracted fields, or
    503 `{detail: "OCR not configured"}` if `OCR_PROVIDER` env is unset.

    Field set in 200 response (any may be omitted if the parser
    couldn't find them):
      `{gallons, cost_per_gallon, total_cost, station, date_raw}`
    Plus `raw_text` (the full OCR output, useful for debugging the
    parser regexes against real receipts).
    """
    if not _ocr_provider():
        return Response(
            {'detail': 'OCR not configured. Set OCR_PROVIDER to enable.'},
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    photo = request.FILES.get('photo') if hasattr(request, 'FILES') else None
    if photo is None:
        return Response({'detail': 'photo file required'}, status=400)

    # Read into memory — receipt photos are small, 1–3 MB.
    try:
        image_bytes = photo.read()
    except Exception:
        return Response({'detail': 'could not read photo'}, status=400)

    text = _run_ocr(image_bytes)
    if not text:
        return Response(
            {'detail': 'OCR returned no text', 'extracted': {}},
            status=200,
        )

    extracted = _parse_receipt_text(text)
    return Response({
        'extracted': extracted,
        'raw_text': text[:2000],  # cap so the response stays small
    })
