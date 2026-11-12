"""Parsing the builder / template editor POST (plain form fields, so the page
also saves without JavaScript; the script only adds the editor, reordering
and autosave)."""
from __future__ import annotations

import re
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from . import permissions as perms
from .models import BILLING_FREQUENCIES, KINDS, SIGNING_ORDERS, ContractSigner
from .sanitize import plain_text


def _indexes(post, prefix):
    found = set()
    pat = re.compile(rf'^{prefix}-(\d+)-')
    for k in post.keys():
        m = pat.match(k)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def _int(post, name, errors, label, lo=0, hi=100000, blank=None):
    raw = (post.get(name) or '').strip()
    if raw == '':
        return blank
    if not raw.isdigit() or not lo <= int(raw) <= hi:
        errors.append(f'{label}: enter a whole number from {lo} to {hi}.')
        return blank
    return int(raw)


def _date(post, name, errors, label):
    raw = (post.get(name) or '').strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        errors.append(f'{label}: enter a date as YYYY-MM-DD.')
        return None


def _tri(post, name):
    v = post.get(name, '')
    return True if v == 'yes' else False if v == 'no' else None


def parse_sections(post):
    out = []
    for i in _indexes(post, 'section'):
        p = f'section-{i}-'
        if post.get(p + 'deleted') == '1':
            continue
        try:
            order = float(post.get(p + 'order') or i)
        except ValueError:
            order = i
        out.append((order, i, {'key': post.get(p + 'key', ''), 'title': post.get(p + 'title', ''),
                               'type': post.get(p + 'type', 'text'), 'body': post.get(p + 'body', ''),
                               'include': post.get(p + 'include') == 'on',
                               'optional': post.get(p + 'optional') == 'on'}))
    return [s for _o, _i, s in sorted(out, key=lambda t: (t[0], t[1]))]


def parse_line_items(post):
    out = []
    for i in _indexes(post, 'item'):
        p = f'item-{i}-'
        if post.get(p + 'deleted') == '1':
            continue
        out.append({'description': post.get(p + 'description', ''), 'kind': post.get(p + 'kind', 'one_time'),
                    'quantity': post.get(p + 'quantity', '1'), 'unit_price': post.get(p + 'unit_price', '0'),
                    'discount_percent': post.get(p + 'discount_percent', '0'),
                    'taxable': post.get(p + 'taxable') == 'on'})
    return out


def staff_choices(organization):
    from psa.visibility import msp_technicians
    return [u for u in msp_technicians() if perms.has(u, perms.VIEW, getattr(organization, 'pk', organization))]


def parse_contract(post, contract):
    """(data, errors) for services.save_draft."""
    from .content import normalize_line_items
    errors = []
    data = {}
    data['title'] = plain_text(post.get('title'), 255)
    if not data['title']:
        errors.append('Enter a title.')
    data['kind'] = post.get('kind') if post.get('kind') in dict(KINDS) else contract.kind
    cur = (post.get('currency') or 'USD').strip().upper()
    if not re.fullmatch(r'[A-Z]{3}', cur):
        errors.append('Currency: use a three-letter code such as USD.')
        cur = contract.currency
    data['currency'] = cur
    from decimal import Decimal, InvalidOperation
    try:
        tax = Decimal((post.get('tax_rate') or '0').strip())
        if not (Decimal('0') <= tax <= Decimal('100')):
            raise InvalidOperation
        data['tax_rate'] = tax.quantize(Decimal('0.001'))
    except InvalidOperation:
        errors.append('Tax rate: enter a percentage from 0 to 100.')
    data['payment_terms'] = plain_text(post.get('payment_terms'), 255)
    data['billing_frequency'] = post.get('billing_frequency') if post.get('billing_frequency') in dict(
        BILLING_FREQUENCIES) else contract.billing_frequency
    data['effective_date'] = _date(post, 'effective_date', errors, 'Effective date')
    data['duration_months'] = _int(post, 'duration_months', errors, 'Duration', 1, 600)
    data['expiration_date'] = _date(post, 'expiration_date', errors, 'Expiration date')
    if data['expiration_date'] is None and data['effective_date'] and data['duration_months']:
        from dateutil.relativedelta import relativedelta
        from datetime import timedelta
        data['expiration_date'] = data['effective_date'] + relativedelta(months=data['duration_months']) - \
            timedelta(days=1)
    data['renewal_terms'] = plain_text(post.get('renewal_terms'), 2000)
    data['auto_renew'] = post.get('auto_renew') == 'on'
    data['notice_period_days'] = _int(post, 'notice_period_days', errors, 'Notice period', 0, 3650)
    data['acceptance_deadline'] = _date(post, 'acceptance_deadline', errors, 'Acceptance deadline')
    data['require_email_verification'] = _tri(post, 'require_email_verification')
    data['require_countersignature'] = _tri(post, 'require_countersignature')
    data['require_internal_approval'] = _tri(post, 'require_internal_approval')
    data['reminders_enabled'] = _tri(post, 'reminders_enabled')
    data['signing_order'] = post.get('signing_order') if post.get('signing_order') in dict(SIGNING_ORDERS) else ''
    data['invitation_expiry_days'] = _int(post, 'invitation_expiry_days', errors, 'Link expiry', 1, 365)

    staff = {u.pk: u for u in staff_choices(contract.organization)}
    for f in ('owner', 'account_manager'):
        raw = post.get(f, '')
        data[f] = staff.get(int(raw)) if str(raw).isdigit() else None
        if raw and data[f] is None:
            errors.append(f'{f.replace("_", " ").title()}: choose a staff member who can see this customer.')
    data['notify_users'] = [staff[int(x)] for x in post.getlist('notify_users') if x.isdigit() and int(x) in staff]

    sections = parse_sections(post)
    if 'section-0-key' in post or sections or post.get('sections_present'):
        data['sections'] = sections
    item_errors = []
    items = parse_line_items(post)
    normalize_line_items(items, item_errors)
    errors += item_errors
    data['line_items'] = items

    signers = []
    for i in _indexes(post, 'signer'):
        p = f'signer-{i}-'
        if post.get(p + 'deleted') == '1':
            continue
        name = plain_text(post.get(p + 'name'), 200)
        email = (post.get(p + 'email') or '').strip()
        if not name and not email:
            continue
        role = post.get(p + 'role') if post.get(p + 'role') in dict(ContractSigner.ROLES) else ContractSigner.CLIENT
        user = None
        if role == ContractSigner.INTERNAL and str(post.get(p + 'user') or '').isdigit():
            user = staff.get(int(post.get(p + 'user')))
            if user is not None:
                name = name or (user.get_full_name() or user.username)
                email = email or user.email
        try:
            validate_email(email)
        except ValidationError:
            errors.append(f'Signer "{name or email}": enter a valid e-mail address.')
            continue
        if not name:
            errors.append(f'Signer {email}: enter a name.')
            continue
        signers.append({'role': role, 'name': name, 'email': email, 'title': plain_text(post.get(p + 'title'), 200),
                        'order': _int(post, p + 'order', errors, 'Signer order', 1, 99, blank=None) or (i + 1),
                        'user': user})
    data['signers'] = signers
    return data, errors


def parse_template(post):
    from .content import normalize_line_items, normalize_sections
    errors = []
    name = plain_text(post.get('name'), 200)
    if not name:
        errors.append('Enter a template name.')
    kind = post.get('kind') if post.get('kind') in dict(KINDS) else 'other'
    sections = normalize_sections(parse_sections(post), errors)
    items = normalize_line_items(parse_line_items(post), errors)
    defaults = {
        'payment_terms': plain_text(post.get('payment_terms'), 255),
        'billing_frequency': post.get('billing_frequency') if post.get('billing_frequency') in dict(
            BILLING_FREQUENCIES) else 'monthly',
        'renewal_terms': plain_text(post.get('renewal_terms'), 2000),
        'duration_months': _int(post, 'duration_months', errors, 'Duration', 1, 600),
        'notice_period_days': _int(post, 'notice_period_days', errors, 'Notice period', 0, 3650),
        'auto_renew': post.get('auto_renew') == 'on',
    }
    return {'name': name, 'kind': kind, 'description': plain_text(post.get('description'), 2000),
            'data': {'sections': sections, 'line_items': items, 'defaults': defaults}}, errors


def user_by_id(raw):
    if not str(raw or '').isdigit():
        return None
    return get_user_model().objects.filter(pk=int(raw), is_active=True).first()
