"""
Guided service requests — form-schema handling for ServiceCatalogItem.

One schema drives three things: the staff catalog editor (validation of
what an admin defines), the portal request form (rendering + client-side
conditions), and server-side validation of what a customer submits.

Schema shape — a list of field dicts:

    {
      "key": "laptop_model",          # ^[a-z][a-z0-9_]*$, unique
      "label": "Laptop model",
      "type": "select",               # see FIELD_TYPES
      "required": true,
      "help": "Pick the closest match",
      "placeholder": "",
      "options": ["Standard", "Developer"],     # select / multiselect
      "show_if": {"field": "needs_laptop", "equals": true}
                 # or {"field": "role", "in": ["Sales", "Support"]}
    }

A field hidden by its `show_if` condition is never required and its value
is discarded, so a customer can't smuggle data through a hidden field.
"""
from __future__ import annotations

import datetime as _dt
import re

FIELD_TYPES = (
    'text', 'textarea', 'select', 'multiselect', 'date', 'checkbox',
    'email', 'user',
)
# Accepted for backward compatibility with legacy fields_json items.
LEGACY_ONLY_TYPES = ('number',)
ALL_TYPES = FIELD_TYPES + LEGACY_ONLY_TYPES

TYPE_LABELS = {
    'text': 'Short text',
    'textarea': 'Long text',
    'select': 'Pick one',
    'multiselect': 'Pick several',
    'date': 'Date',
    'checkbox': 'Yes / no',
    'email': 'Email address',
    'user': 'Person (name or email)',
    'number': 'Number',
}

KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,49}$')
MAX_FIELDS = 50
MAX_OPTIONS = 100
FIELD_PREFIX = 'f_'
# POST keys a portal submission may carry besides the schema fields.
ALLOWED_EXTRA_POST_KEYS = {'csrfmiddlewaretoken'}

MAX_LEN = {
    'text': 500, 'textarea': 10000, 'email': 254, 'user': 200,
    'select': 200, 'date': 10, 'number': 50,
}

_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def clean_text(value, max_len):
    """Strip control characters and cap length. HTML is escaped at render."""
    value = _CONTROL_RE.sub('', str(value or '')).strip()
    return value[:max_len]


class SchemaError(ValueError):
    pass


def _clean_show_if(raw, known_keys, own_key):
    if raw in (None, '', {}):
        return None
    if not isinstance(raw, dict):
        raise SchemaError(f'Field "{own_key}": show_if must be an object.')
    ctrl = str(raw.get('field') or '').strip()
    if not ctrl:
        raise SchemaError(f'Field "{own_key}": show_if needs a "field".')
    if ctrl == own_key:
        raise SchemaError(f'Field "{own_key}": show_if cannot reference itself.')
    if ctrl not in known_keys:
        raise SchemaError(
            f'Field "{own_key}": show_if references "{ctrl}", which must be '
            f'a field defined earlier in the form.')
    out = {'field': ctrl}
    if 'in' in raw and raw.get('in') not in (None, ''):
        vals = raw.get('in')
        if isinstance(vals, str):
            vals = [v.strip() for v in vals.split(',') if v.strip()]
        if not isinstance(vals, list) or not vals:
            raise SchemaError(f'Field "{own_key}": show_if "in" must be a list.')
        out['in'] = [clean_text(v, 200) for v in vals][:MAX_OPTIONS]
    elif 'equals' in raw:
        eq = raw.get('equals')
        if isinstance(eq, bool):
            out['equals'] = eq
        else:
            out['equals'] = clean_text(eq, 200)
    else:
        raise SchemaError(f'Field "{own_key}": show_if needs "equals" or "in".')
    return out


def normalize_schema(raw, *, allow_legacy_types=True):
    """Validate + normalise a schema definition. Raises SchemaError."""
    if raw in (None, ''):
        return []
    if not isinstance(raw, list):
        raise SchemaError('The form must be a list of fields.')
    if len(raw) > MAX_FIELDS:
        raise SchemaError(f'At most {MAX_FIELDS} fields are allowed.')
    allowed = ALL_TYPES if allow_legacy_types else FIELD_TYPES
    out = []
    seen = set()
    for i, f in enumerate(raw, start=1):
        if not isinstance(f, dict):
            raise SchemaError(f'Field #{i} must be an object.')
        key = str(f.get('key') or '').strip()
        label = clean_text(f.get('label'), 200)
        if not KEY_RE.match(key):
            raise SchemaError(
                f'Field #{i}: key "{key}" must start with a lowercase letter and '
                f'use only lowercase letters, digits and underscores.')
        if key in seen:
            raise SchemaError(f'Field key "{key}" is used twice.')
        if not label:
            raise SchemaError(f'Field "{key}" needs a label.')
        ftype = str(f.get('type') or 'text').strip()
        if ftype not in allowed:
            raise SchemaError(
                f'Field "{key}": invalid type {ftype!r}. Allowed: {", ".join(allowed)}.')
        field = {
            'key': key,
            'label': label,
            'type': ftype,
            'required': bool(f.get('required')),
        }
        help_text = clean_text(f.get('help'), 500)
        if help_text:
            field['help'] = help_text
        placeholder = clean_text(f.get('placeholder'), 200)
        if placeholder:
            field['placeholder'] = placeholder
        if ftype in ('select', 'multiselect'):
            opts = f.get('options') or []
            if isinstance(opts, str):
                opts = [o.strip() for o in opts.split('\n') if o.strip()]
            if not isinstance(opts, list):
                raise SchemaError(f'Field "{key}": options must be a list.')
            opts = [clean_text(o, 200) for o in opts if clean_text(o, 200)]
            # De-duplicate, keep order.
            opts = list(dict.fromkeys(opts))[:MAX_OPTIONS]
            if not opts:
                raise SchemaError(f'Field "{key}" needs at least one option.')
            field['options'] = opts
        show_if = _clean_show_if(f.get('show_if'), seen, key)
        if show_if:
            field['show_if'] = show_if
        seen.add(key)
        out.append(field)
    return out


def schema_from_legacy(fields_json):
    """Best-effort conversion of legacy fields_json into a form schema.
    Invalid entries are dropped rather than raising, since this runs on
    read for items that were never re-saved."""
    out = []
    seen = set()
    for f in fields_json or []:
        if not isinstance(f, dict):
            continue
        key = str(f.get('key') or '').strip()
        if not KEY_RE.match(key) or key in seen:
            continue
        ftype = f.get('type') or 'text'
        if ftype not in ALL_TYPES:
            ftype = 'text'
        field = {
            'key': key,
            'label': clean_text(f.get('label') or key, 200),
            'type': ftype,
            'required': bool(f.get('required')),
        }
        for attr, n in (('help', 500), ('placeholder', 200)):
            v = clean_text(f.get(attr), n)
            if v:
                field[attr] = v
        if ftype in ('select', 'multiselect'):
            opts = [clean_text(o, 200) for o in (f.get('options') or [])
                    if isinstance(o, (str, int, float)) and clean_text(o, 200)]
            if not opts:
                field['type'] = 'text'
            else:
                field['options'] = list(dict.fromkeys(opts))
        seen.add(key)
        out.append(field)
    return out


def legacy_fields_from_schema(schema):
    """Project a form schema onto the legacy fields_json shape the staff
    ticket form reads. Types the staff form doesn't know become text, and
    conditional fields lose `required` (the staff form has no conditions)."""
    legacy_types = {'text', 'email', 'date', 'number', 'textarea', 'select', 'checkbox'}
    out = []
    for f in schema or []:
        lf = {
            'key': f['key'],
            'label': f['label'],
            'type': f['type'] if f['type'] in legacy_types else 'text',
            'required': bool(f.get('required')) and not f.get('show_if'),
        }
        if f.get('help'):
            lf['help'] = f['help']
        placeholder = f.get('placeholder')
        if f['type'] == 'multiselect' and not placeholder:
            placeholder = 'One or more of: ' + ', '.join(f.get('options') or [])
        if placeholder:
            lf['placeholder'] = placeholder
        if lf['type'] == 'select':
            lf['options'] = list(f.get('options') or [])
        out.append(lf)
    return out


# ---------------------------------------------------------------------------
# Conditional visibility
# ---------------------------------------------------------------------------

def _matches(cond, value):
    """Does `value` (a cleaned answer) satisfy the show_if condition?"""
    if isinstance(value, list):
        values = [str(v) for v in value]
    elif isinstance(value, bool):
        values = ['true' if value else 'false', 'yes' if value else 'no']
    elif value in (None, ''):
        values = []
    else:
        values = [str(value)]
    if 'in' in cond:
        wanted = {str(v) for v in cond['in']}
        return any(v in wanted for v in values)
    eq = cond.get('equals')
    if isinstance(eq, bool):
        if isinstance(value, bool):
            return value is eq
        return (str(eq).lower() in [v.lower() for v in values]) or \
               (('yes' if eq else 'no') in [v.lower() for v in values])
    return str(eq) in values


def visible_keys(schema, values):
    """Keys of fields visible given `values`. A field whose controlling
    field is itself hidden is hidden too (schemas only reference earlier
    fields, so one pass in order resolves chains)."""
    visible = set()
    for f in schema:
        cond = f.get('show_if')
        if not cond:
            visible.add(f['key'])
            continue
        ctrl = cond.get('field')
        if ctrl in visible and _matches(cond, values.get(ctrl)):
            visible.add(f['key'])
    return visible


# ---------------------------------------------------------------------------
# Submission validation
# ---------------------------------------------------------------------------

def _clean_value(field, post):
    """Return (value, error) for one field from a QueryDict-like `post`."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    name = FIELD_PREFIX + field['key']
    ftype = field['type']
    if ftype == 'checkbox':
        raw = (post.get(name) or '').strip().lower()
        if raw and raw not in ('on', 'true', '1', 'yes'):
            return None, f'{field["label"]}: invalid value.'
        return bool(raw), None
    if ftype == 'multiselect':
        raw = [clean_text(v, MAX_LEN['select']) for v in post.getlist(name)]
        raw = [v for v in raw if v]
        opts = field.get('options') or []
        bad = [v for v in raw if v not in opts]
        if bad:
            return None, f'{field["label"]}: "{bad[0]}" is not one of the choices.'
        return list(dict.fromkeys(raw)), None
    if len(post.getlist(name)) > 1:
        return None, f'{field["label"]}: only one value is allowed.'
    value = clean_text(post.get(name), MAX_LEN.get(ftype, 500))
    if not value:
        return '', None
    if ftype == 'select':
        if value not in (field.get('options') or []):
            return None, f'{field["label"]}: "{value}" is not one of the choices.'
    elif ftype == 'email':
        try:
            validate_email(value)
        except ValidationError:
            return None, f'{field["label"]}: enter a valid email address.'
    elif ftype == 'date':
        try:
            value = _dt.date.fromisoformat(value).isoformat()
        except ValueError:
            return None, f'{field["label"]}: enter a date as YYYY-MM-DD.'
    elif ftype == 'number':
        try:
            float(value)
        except ValueError:
            return None, f'{field["label"]}: enter a number.'
    return value, None


def _is_empty(value):
    return value in (None, '', [], False)


def validate_submission(schema, post):
    """Validate a portal submission against `schema`.

    Returns (answers, errors). `answers` maps key → cleaned value for
    visible fields only. Unknown POST keys are an error, not ignored.
    """
    errors = []
    known = {FIELD_PREFIX + f['key'] for f in schema}
    unknown = sorted(k for k in post.keys()
                     if k not in known and k not in ALLOWED_EXTRA_POST_KEYS)
    if unknown:
        errors.append('The form contained unexpected fields: '
                      + ', '.join(clean_text(k, 60) for k in unknown[:5]) + '.')
        return {}, errors

    cleaned = {}
    for f in schema:
        value, err = _clean_value(f, post)
        if err:
            errors.append(err)
            value = None
        cleaned[f['key']] = value

    visible = visible_keys(schema, cleaned)
    answers = {}
    for f in schema:
        if f['key'] not in visible:
            continue  # hidden by condition: never required, value dropped
        value = cleaned.get(f['key'])
        if f.get('required') and _is_empty(value) and value is not None:
            errors.append(f'{f["label"]} is required.')
        if value is not None:
            answers[f['key']] = value
    return answers, errors


def display_value(field, value):
    if isinstance(value, bool) or field.get('type') == 'checkbox':
        return 'Yes' if value else 'No'
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return '' if value is None else str(value)


def answers_as_rows(schema, answers):
    """Ordered [{key, label, type, value, display}] for storage + display."""
    rows = []
    for f in schema:
        if f['key'] not in answers:
            continue
        v = answers[f['key']]
        rows.append({
            'key': f['key'], 'label': f['label'], 'type': f['type'],
            'value': v, 'display': display_value(f, v),
        })
    return rows


def template_values(rows):
    """{{key}} substitution values for default_subject / default_body."""
    return {r['key']: r['display'] for r in rows}


# ---------------------------------------------------------------------------
# Catalog availability
# ---------------------------------------------------------------------------

def portal_catalog_for(organization):
    """Active, portal-visible items available to `organization`."""
    from django.db.models import Q
    from psa.models import ServiceCatalogItem
    if organization is None:
        return ServiceCatalogItem.objects.none()
    return (ServiceCatalogItem.objects
            .filter(is_active=True, portal_visible=True)
            .exclude(exclude_organizations=organization)
            .filter(Q(include_organizations__isnull=True)
                    | Q(include_organizations=organization))
            .distinct()
            .order_by('category', 'sort_order', 'name'))


# ---------------------------------------------------------------------------
# Submission → ticket (+ approval, + workflow)
# ---------------------------------------------------------------------------

SERVICE_REQUEST_KEY = 'service_request'
APPROVAL_OBJECT_TYPE = 'psa.ServiceCatalogItem'


def answers_text(rows):
    """Readable "Label: value" lines for the ticket description."""
    lines = []
    for r in rows:
        if r['display'] == '':
            continue
        if r['type'] == 'textarea' and '\n' in r['display']:
            lines.append(f'{r["label"]}:')
            lines.append(r['display'])
        else:
            lines.append(f'{r["label"]}: {r["display"]}')
    return '\n'.join(lines).strip()


def _process_assignee(process, item):
    """ProcessExecution needs an assignee. The workflow's author is the most
    defensible default; fall back to whoever last published the catalog
    item. Returns None when neither is an active user."""
    for user in (getattr(process, 'created_by', None),
                 getattr(item, 'last_published_by', None)):
        if user is not None and user.is_active:
            return user
    return None


def submit_request(*, item, organization, user, answers):
    """Create the ticket for a validated portal submission.

    Uses the same Ticket.objects.create path as the plain portal form,
    with routing from the catalog item. Raises ValueError when PSA lookups
    (queue/type/priority/status) are missing. Returns the ticket.
    """
    from django.db import transaction
    from django.utils import timezone

    from psa.models import (
        PSAApproval, Queue, Ticket, TicketPriority, TicketStatus, TicketType,
    )

    schema = item.get_form_schema()
    rows = answers_as_rows(schema, answers)
    values = template_values(rows)
    readable = answers_text(rows)

    subject = item.render_template(item.default_subject, values).strip() \
        if item.default_subject else ''
    subject = clean_text(subject or item.name, 300)
    if item.default_body:
        description = item.render_template(item.default_body, values).strip()
        # The body template may not mention every field; keep all answers
        # readable in the description too.
        if readable and readable not in description:
            description = (description + '\n\n' + readable).strip()
    else:
        description = '\n\n'.join(p for p in (item.description, readable) if p)
    description = description[:50000]

    queue = item.default_queue if (item.default_queue and item.default_queue.is_active) \
        else Queue.objects.filter(is_active=True).first()
    ticket_type = item.default_type if (item.default_type and item.default_type.is_active) \
        else TicketType.objects.filter(is_active=True).first()
    priority = item.default_priority or TicketPriority.objects.order_by('sort_order').first()
    status = TicketStatus.objects.filter(slug='new').first()
    if not (queue and ticket_type and priority and status):
        raise ValueError('PSA is not configured')

    now = timezone.now()
    requester = user.get_full_name() or user.username
    with transaction.atomic():
        ticket = Ticket.objects.create(
            organization=organization,
            subject=subject, description=description,
            queue=queue, priority=priority, ticket_type=ticket_type,
            status=status, source='portal',
            visibility='client', client_can_view=True,
            requester_name=requester,
            requester_email=user.email or '',
            created_by=user,
        )
        record = {
            'catalog_item_id': item.pk,
            'catalog_item_slug': item.slug,
            'catalog_item_name': item.name,
            'category': item.category,
            'answers': rows,
            'expected_turnaround': item.turnaround_display,
            'expected_turnaround_hours': item.expected_turnaround_hours,
            'approval_required': item.needs_customer_approval,
            'submitted_at': now.isoformat(),
            'submitted_by_id': user.pk,
        }

        if item.needs_customer_approval:
            approval = PSAApproval.objects.create(
                organization=organization,
                kind='other',
                object_type=APPROVAL_OBJECT_TYPE,
                object_id=item.pk,
                object_repr=f'{item.name} — {ticket.ticket_number}'[:300],
                requested_by=user,
                request_comment=(f'Service request "{item.name}" from {requester}.'
                                 f'\n\n{readable}')[:5000],
                related_ticket=ticket,
                is_client_approval=True,
            )
            record['approval_id'] = approval.pk

        if item.process_template_id:
            record['process_execution_id'] = _start_process(
                item.process_template, item, ticket, user, now)

        ticket.custom_fields = dict(ticket.custom_fields or {})
        ticket.custom_fields[SERVICE_REQUEST_KEY] = record
        ticket.save(update_fields=['custom_fields', 'updated_at'])
    return ticket


def _start_process(process, item, ticket, user, now):
    """Start the item's workflow against the ticket. Staff-only notes go in
    an internal comment. Returns the execution id, or None if skipped."""
    from processes.models import ProcessExecution
    from psa.models import TicketComment

    usable = (not process.is_archived) and (
        process.is_global or process.is_template
        or process.organization_id == ticket.organization_id)
    assignee = _process_assignee(process, item) if usable else None
    if assignee is None:
        reason = ('the workflow is archived or belongs to another customer'
                  if not usable else 'there is no active user to assign it to')
        TicketComment.objects.create(
            ticket=ticket, is_internal=True, is_system=True, source='workflow',
            body=f'Service request workflow "{process.title}" was not started: {reason}.',
        )
        return None
    execution = ProcessExecution.objects.create(
        process=process,
        organization=ticket.organization,
        assigned_to=assignee,
        started_by=None,
        started_at=now,
        status='in_progress',
        native_psa_ticket=ticket,
        psa_note_internal=True,
        notes=(f'Started automatically by service request "{item.name}" '
               f'submitted in the portal by {user.get_full_name() or user.username}.'),
    )
    TicketComment.objects.create(
        ticket=ticket, is_internal=True, is_system=True, source='workflow',
        body=f'Launched workflow: **{process.title}** (execution #{execution.pk}) '
             f'from service request "{item.name}".',
    )
    return execution.pk


def service_request_record(ticket):
    """The stored service-request record on a ticket, or None."""
    cf = ticket.custom_fields
    data = cf.get(SERVICE_REQUEST_KEY) if isinstance(cf, dict) else None
    return data if isinstance(data, dict) else None
