"""
AI-powered receipt OCR for vehicle expense tracking.

Vision extraction runs through whichever LLM provider the install has
configured (Settings → AI), via `docs.services.llm_providers`. This module
used to hardcode Anthropic, which meant an install running a local model
still sent every receipt image off-network.
"""
import logging

logger = logging.getLogger('vehicles')


def extract_receipt_data(image_file):
    """
    Extract structured data from a receipt image via the configured LLM.

    This used to build its own `anthropic.Anthropic(api_key=...)` client from
    `settings.ANTHROPIC_API_KEY`, with its own copy of the prompt, its own
    code-fence stripping and its own type coercion — a second implementation
    of what `docs.services.llm_providers` already does for Anthropic, OpenAI
    and Ollama through `LLMProvider.extract_receipt_fields`.

    The mobile app's receipt scanner (`api_mobile.views_receipts`) has always
    gone through that provider layer. This one did not, so the same receipt
    scanned in the web UI went to Anthropic no matter which provider the
    administrator had configured. On an install running Ollama — chosen
    precisely to keep data on the premises — every receipt image still left
    the network.

    Returns the same shape as before: {'success': bool, 'data': {...}} or
    {'success': False, 'error': str}.
    """
    from docs.services.llm_providers import get_configured_provider

    try:
        image_file.seek(0)
        image_bytes = image_file.read()
    except Exception as e:
        logger.error(f'[receipt_ocr] Failed to read image: {e}')
        return {'success': False, 'error': f'Could not read image file: {e}'}

    content_type = getattr(image_file, 'content_type', 'image/jpeg')
    if content_type not in ('image/jpeg', 'image/png', 'image/gif', 'image/webp'):
        content_type = 'image/jpeg'

    try:
        provider = get_configured_provider()
    except Exception as exc:
        logger.warning(f'[receipt_ocr] LLM provider load failed: {exc}')
        provider = None

    if provider is None:
        return {
            'success': False,
            'error': 'No LLM provider is configured. Set one in Settings → AI.',
        }

    try:
        result = provider.extract_receipt_fields(image_bytes, content_type)
    except Exception as exc:
        logger.error(f'[receipt_ocr] provider error: {exc}')
        return {'success': False, 'error': f'AI extraction failed: {exc}'}

    if not result.get('success'):
        return result

    # The provider layer speaks the shared receipt schema under 'extracted'
    # (amount_total / amount_tax / category_hint / line_items); the vehicle
    # receipt form speaks amount / tax_amount / category / description. The
    # mobile scanner maps between them the same way in
    # `api_mobile.views_receipts`. Mapping here keeps the form's contract intact.
    ex = result.get('extracted') or {}

    def _num(value, caster):
        if value is None:
            return None
        try:
            return caster(value)
        except (TypeError, ValueError):
            return None

    line_items = ex.get('line_items') or []
    description = ', '.join(str(i) for i in line_items)[:500] if line_items else None

    valid_categories = {
        'fuel', 'maintenance', 'repair', 'insurance',
        'registration', 'toll', 'cleaning', 'inspection', 'other',
    }
    category = ex.get('category_hint')
    if category not in valid_categories:
        category = 'other'

    return {'success': True, 'data': {
        'vendor': ex.get('vendor'),
        'date': ex.get('date'),
        'amount': _num(ex.get('amount_total'), float),
        'tax_amount': _num(ex.get('amount_tax'), float),
        'category': category,
        'odometer': _num(ex.get('odometer'), int),
        'description': description,
        # The shared schema carries no confidence field; the form treats a
        # missing value as "unknown" rather than claiming high confidence.
        'confidence': None,
        # Fuel-specific figures the old prompt never asked for, now available.
        'gallons': _num(ex.get('gallons'), float),
        'cost_per_gallon': _num(ex.get('cost_per_gallon'), float),
    }}
