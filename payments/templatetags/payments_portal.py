from django import template

register = template.Library()


@register.filter
def portal_can_bill(request):
    """Whether the active portal membership is a billing contact."""
    try:
        from payments.portal_views import can_bill
        return can_bill(request)
    except Exception:  # pragma: no cover - never break the portal layout
        return False
