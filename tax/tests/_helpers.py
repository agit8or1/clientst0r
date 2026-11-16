from datetime import date
from decimal import Decimal
from unittest import mock

import requests
from django.conf import settings as django_settings

from core.models import Organization

TEST_MIDDLEWARE = [
    m for m in django_settings.MIDDLEWARE
    if 'Enforce2FAMiddleware' not in m and 'AxesMiddleware' not in m
]


def make_org(name, slug, **addr):
    defaults = dict(street_address='1 Main St', city='San Francisco', state='CA', postal_code='94105',
                    country='United States')
    defaults.update(addr)
    return Organization.objects.create(name=name, slug=slug, **defaults)


def make_quote(org, client=None, lines=(('Laptop', '1', '1000.00'),), status='draft'):
    from psa.models import Quote, QuoteLineItem
    q = Quote.objects.create(organization=org, client_org=client or org, title='Q', status=status)
    for i, (d, qty, price) in enumerate(lines):
        QuoteLineItem.objects.create(quote=q, sort_order=i, description=d, quantity=Decimal(qty),
                                     unit_price=Decimal(price))
    q.recompute_totals()
    return q


def make_invoice(org, client=None, lines=(('Laptop', '1', '1000.00', 'manual'),), status='draft',
                 tax_rate='0'):
    from psa.models import Invoice, InvoiceLineItem
    inv = Invoice.objects.create(organization=org, client_org=client or org, title='I',
                                 invoice_date=date(2026, 11, 1), status=status, tax_rate=Decimal(tax_rate))
    for d, qty, price, source in lines:
        InvoiceLineItem.objects.create(invoice=inv, description=d, quantity=Decimal(qty),
                                       unit_price=Decimal(price), source=source)
    inv.recompute_totals()
    return inv


def response(status=200, body=None):
    r = mock.MagicMock()
    r.status_code = status
    r.content = b'{}' if body is not None else b''
    r.json.return_value = body
    return r


def patch_http(*responses, side_effect=None):
    """Patch every guarded-session request. Pass responses (returned in
    order) or side_effect (e.g. requests.Timeout())."""
    if side_effect is None:
        side_effect = list(responses)
    return mock.patch.object(requests.Session, 'request', side_effect=side_effect)


def provider_settings(org, mode, creds, **kw):
    from integrations.models import TaxConnection
    from tax.models import TaxSettings
    # Tax configuration is MSP-wide (one MSP per install); `org` names the connection only.
    conn = TaxConnection.objects.create(organization=None, provider_type=mode, name=f'{mode}-{org.slug}')
    conn.set_credentials(creds)
    conn.save()
    defaults = dict(origin_line1='9 Origin Rd', origin_city='Austin', origin_region='TX',
                    origin_postal_code='78701', origin_country='US')
    defaults.update(kw)
    return TaxSettings.objects.create(organization=None, mode=mode, connection=conn, **defaults)


AVALARA_CREDS = {'account_id': '1100', 'license_key': 'lk-secret', 'company_code': 'DEFAULT'}
TAXJAR_CREDS = {'api_key': 'tj-secret'}
