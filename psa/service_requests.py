"""
Guided service requests — form-schema handling for ServiceCatalogItem.

One schema drives four things: the staff form builder (validation of what
an admin defines), the portal request form (rendering + client-side
conditions, static/psa/js/request_form.js), server-side validation of what
a customer submits, and the immutable snapshot stored on the ticket.

Schema shape — a list of field dicts:

    {
      "key": "laptop_model",          # ^[a-z][a-z0-9_]*$, unique, stable:
                                      # independent of the label
      "label": "Laptop model",
      "type": "select",               # see FIELD_TYPES
      "required": true,
      "help": "Pick the closest match",
      "placeholder": "",
      "options": ["Standard", "Developer"],      # or [{"value", "label"}]
      "default": "Standard",
      "show_if": {"field": "needs_laptop", "equals": true},
      "required_if": {"field": "role", "op": "in", "value": ["Sales"]},
      "sensitive": true,              # kept out of the description,
                                      # subject and approval e-mails
      ...type-specific constraints (min, max, integer, max_length,
         not_in_past, max_files, allow_text, maps_to, requested_date)
    }

Conditions are declarative and bounded — never code:

    {"field": k, "equals": v}            legacy
    {"field": k, "in": [v, ...]}         legacy
    {"field": k, "op": OP, "value": v}   OP in CONDITION_OPS
    {"all": [cond, ...]} / {"any": [cond, ...]}   one level, at most
                                                  MAX_CONDITIONS simple
                                                  conditions

A condition may only reference an input field defined earlier in the form,
so dependencies always point backwards and can't form a cycle; an explicit
cycle check runs first anyway so a bad definition gets a clear message.

`heading` fields start a section: when a heading is hidden by its own
condition, every field up to the next heading is hidden too. `info` fields
show text only. Neither carries a value.

A field hidden by its condition is never required and its value is
discarded, so a customer can't smuggle data through a hidden field (and a
stale answer to a question that no longer applies is never stored).
"""
from __future__ import annotations

import datetime as _dt
import math
import re

FIELD_TYPES = (
    'text', 'textarea', 'email', 'tel', 'number', 'date', 'datetime',
    'select', 'multiselect', 'radio', 'checkbox', 'file',
    'contact', 'location', 'asset', 'user', 'heading', 'info',
)
# Accepted for backward compatibility with legacy fields_json items.
LEGACY_ONLY_TYPES = ()
ALL_TYPES = FIELD_TYPES + LEGACY_ONLY_TYPES

TYPE_LABELS = {
    'text': 'Short text',
    'textarea': 'Long text',
    'email': 'Email address',
    'tel': 'Telephone number',
    'number': 'Number',
    'date': 'Date',
    'datetime': 'Date and time (with time zone)',
    'select': 'Dropdown (pick one)',
    'multiselect': 'Checkbox group (pick several)',
    'radio': 'Radio buttons (pick one)',
    'checkbox': 'Checkbox (yes / no)',
    'file': 'File attachment',
    'contact': 'Person at the customer (lookup)',
    'location': "Customer's site / location",
    'asset': 'Device / asset (lookup)',
    'user': 'Person (name or email, free text)',
    'heading': 'Section heading',
    'info': 'Information text',
}

CHOICE_TYPES = ('select', 'multiselect', 'radio')
LOOKUP_TYPES = ('contact', 'location', 'asset')
DISPLAY_TYPES = ('heading', 'info')
# Free-entry types a secret could be typed into.
FREE_ENTRY_TYPES = ('text', 'textarea', 'number', 'tel', 'user')

KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,49}$')
MAX_FIELDS = 80
MAX_OPTIONS = 100
MAX_CONDITIONS = 5
MAX_FILES_PER_FIELD = 5
FIELD_PREFIX = 'f_'
TEXT_SUFFIX = '__text'   # free-text fallback of a contact / asset lookup
TZ_SUFFIX = '__tz'       # time zone of a datetime field
# POST keys a portal submission may carry besides the schema fields.
ALLOWED_EXTRA_POST_KEYS = {'csrfmiddlewaretoken', '_form_version', '_submission_token'}

CONDITION_OPS = ('equals', 'not_equals', 'in', 'not_in', 'is_set', 'not_set', 'contains')
OP_LABELS = {
    'equals': 'is', 'not_equals': 'is not', 'in': 'is one of', 'not_in': 'is none of',
    'is_set': 'is answered', 'not_set': 'is not answered', 'contains': 'includes',
}
URGENCY_VALUES = ('low', 'medium', 'high', 'critical')

MAX_LEN = {
    'text': 500, 'textarea': 10000, 'email': 254, 'user': 200, 'tel': 40,
    'select': 200, 'date': 10, 'number': 50, 'datetime': 16,
}

_CONTROL_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_TEL_RE = re.compile(r'^[0-9+()\-.\s/xXextEXT#*]{3,40}$')
_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$')
_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')

# Request forms collect requests; they must never collect credentials.
# Checked on the label, key and placeholder of free-entry fields only, so
# an info box saying "we will never ask for your password" or a "Password
# reset" option is fine.
SECRET_RE = re.compile(
    r'(pass\s*(word|code|phrase)|passwd|\bpwd\b|\bmfa\b|\b2fa\b|\botp\b|one[\s-]*time\s*(pass)?code|'
    r'verification\s*code|auth(entication|enticator)?\s*code|recovery\s*(code|key)|'
    r'backup\s*code|security\s*(question|answer)|\bpin\b|secret|private\s*key|'
    r'api\s*key|access\s*token)', re.I)


def clean_text(value, max_len):
    """Strip control characters and cap length. HTML is escaped at render."""
    value = _CONTROL_RE.sub('', str(value or '')).strip()
    return value[:max_len]


class SchemaError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def option_pairs(field):
    """[(value, label)] for a choice field; options are strings (value =
    label) or {"value", "label"} dicts."""
    out = []
    for o in field.get('options') or []:
        if isinstance(o, dict):
            out.append((str(o.get('value')), str(o.get('label') or o.get('value'))))
        else:
            out.append((str(o), str(o)))
    return out


def option_values(field):
    return [v for v, _ in option_pairs(field)]


def option_label(field, value):
    for v, label in option_pairs(field):
        if v == str(value):
            return label
    return str(value)


def _clean_options(key, opts):
    if isinstance(opts, str):
        opts = [o.strip() for o in opts.split('\n') if o.strip()]
    if not isinstance(opts, list):
        raise SchemaError(f'Field "{key}": options must be a list.')
    if len(opts) > MAX_OPTIONS:
        raise SchemaError(f'Field "{key}": at most {MAX_OPTIONS} options.')
    as_dicts = any(isinstance(o, dict) for o in opts)
    out, seen = [], set()
    for o in opts:
        if isinstance(o, dict):
            label = clean_text(o.get('label'), 200)
            value = clean_text(o.get('value'), 200) or label
            if not label:
                label = value
        elif isinstance(o, (str, int, float)) and not isinstance(o, bool):
            label = value = clean_text(o, 200)
        else:
            raise SchemaError(f'Field "{key}": each option must be text.')
        if not value:
            continue
        if value in seen:
            if as_dicts:
                raise SchemaError(f'Field "{key}": option value "{value}" is used twice.')
            continue  # plain string lists: de-duplicate, keep order
        seen.add(value)
        out.append({'value': value, 'label': label} if as_dicts else value)
    if not out:
        raise SchemaError(f'Field "{key}" needs at least one option.')
    return out


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------

def _simple_conditions(cond):
    if not cond:
        return []
    if 'all' in cond:
        return list(cond['all'])
    if 'any' in cond:
        return list(cond['any'])
    return [cond]


def condition_fields(cond):
    """Keys a (normalised) condition reads."""
    return [c.get('field') for c in _simple_conditions(cond) if c.get('field')]


def _clean_simple_condition(raw, by_key, own_key, what):
    if not isinstance(raw, dict):
        raise SchemaError(f'Field "{own_key}": {what} must be an object.')
    ctrl = str(raw.get('field') or '').strip()
    if not ctrl:
        raise SchemaError(f'Field "{own_key}": {what} needs a "field".')
    if ctrl == own_key:
        raise SchemaError(f'Field "{own_key}": {what} cannot reference itself.')
    target = by_key.get(ctrl)
    if target is None:
        raise SchemaError(
            f'Field "{own_key}": {what} references "{ctrl}", which must be '
            f'a field defined earlier in the form.')
    if target['type'] in DISPLAY_TYPES:
        raise SchemaError(f'Field "{own_key}": {what} cannot depend on a heading or information text.')

    # Legacy shapes are kept exactly as written.
    if 'op' not in raw:
        if 'in' in raw and raw.get('in') not in (None, ''):
            vals = raw.get('in')
            if isinstance(vals, str):
                vals = [v.strip() for v in vals.split(',') if v.strip()]
            if not isinstance(vals, list) or not vals:
                raise SchemaError(f'Field "{own_key}": {what} "in" must be a list.')
            return {'field': ctrl, 'in': [clean_text(v, 200) for v in vals][:MAX_OPTIONS]}
        if 'equals' in raw:
            eq = raw.get('equals')
            return {'field': ctrl, 'equals': eq if isinstance(eq, bool) else clean_text(eq, 200)}
        raise SchemaError(f'Field "{own_key}": {what} needs "equals", "in" or "op".')

    op = str(raw.get('op') or '').strip()
    if op not in CONDITION_OPS:
        raise SchemaError(f'Field "{own_key}": {what} operator {op!r} is not supported. '
                          f'Use one of: {", ".join(CONDITION_OPS)}.')
    out = {'field': ctrl, 'op': op}
    if op in ('is_set', 'not_set'):
        return out
    value = raw.get('value')
    if op in ('in', 'not_in'):
        if isinstance(value, str):
            value = [v.strip() for v in value.split(',') if v.strip()]
        if not isinstance(value, list) or not value:
            raise SchemaError(f'Field "{own_key}": {what} needs a list of values.')
        value = [clean_text(v, 200) for v in value][:MAX_OPTIONS]
        check = value
    else:
        if isinstance(value, bool):
            pass
        else:
            value = clean_text(value, 200)
            if value == '':
                raise SchemaError(f'Field "{own_key}": {what} needs a value.')
        check = [value]
    # A value compared against a choice field must be one of its options.
    if target['type'] in CHOICE_TYPES:
        allowed = set(option_values(target))
        bad = [v for v in check if str(v) not in allowed]
        if bad and op != 'contains' or (op == 'contains' and bad and target['type'] != 'multiselect'):
            raise SchemaError(f'Field "{own_key}": {what} value "{bad[0]}" is not an option of '
                              f'"{target["label"]}".')
    if target['type'] == 'checkbox' and op in ('equals', 'not_equals') and not isinstance(value, bool):
        lowered = str(value).lower()
        if lowered in ('true', 'yes', 'on', '1'):
            value = True
        elif lowered in ('false', 'no', 'off', '0'):
            value = False
        else:
            raise SchemaError(f'Field "{own_key}": {what} on a checkbox must be yes or no.')
    out['value'] = value
    return out


def _clean_condition(raw, by_key, own_key, what='show_if'):
    if raw in (None, '', {}, []):
        return None
    if not isinstance(raw, dict):
        raise SchemaError(f'Field "{own_key}": {what} must be an object.')
    for combo in ('all', 'any'):
        if combo in raw:
            parts = raw.get(combo)
            if not isinstance(parts, list) or not parts:
                raise SchemaError(f'Field "{own_key}": {what} "{combo}" must be a list of conditions.')
            if len(parts) > MAX_CONDITIONS:
                raise SchemaError(f'Field "{own_key}": at most {MAX_CONDITIONS} conditions.')
            cleaned = []
            for p in parts:
                if isinstance(p, dict) and ('all' in p or 'any' in p):
                    raise SchemaError(f'Field "{own_key}": conditions can only be one level deep.')
                cleaned.append(_clean_simple_condition(p, by_key, own_key, what))
            return {combo: cleaned}
    return _clean_simple_condition(raw, by_key, own_key, what)


def _find_cycle(raw_fields):
    """Detect a dependency cycle in raw (un-normalised) field dicts, before
    the ordering rule is applied. Returns the cycle as a key list or None."""
    deps = {}
    section = None
    for f in raw_fields:
        if not isinstance(f, dict):
            continue
        key = str(f.get('key') or '')
        refs = set()
        for attr in ('show_if', 'required_if'):
            c = f.get(attr)
            if isinstance(c, dict):
                for s in (c.get('all') or c.get('any') or [c]):
                    if isinstance(s, dict) and s.get('field'):
                        refs.add(str(s['field']))
        if f.get('type') == 'heading':
            section = key
        elif section:
            refs.add(section)
        deps[key] = refs
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {k: WHITE for k in deps}

    def visit(k, path):
        colour[k] = GREY
        for d in deps.get(k, ()):
            if d not in deps:
                continue
            if colour[d] == GREY:
                return path[path.index(d):] + [d] if d in path else [k, d]
            if colour[d] == WHITE:
                found = visit(d, path + [d])
                if found:
                    return found
        colour[k] = BLACK
        return None

    for k in deps:
        if colour[k] == WHITE:
            found = visit(k, [k])
            if found:
                return found
    return None


# ---------------------------------------------------------------------------
# Schema normalisation
# ---------------------------------------------------------------------------

def _int_attr(f, name, lo=None, hi=None, key=''):
    v = f.get(name)
    if v in (None, ''):
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise SchemaError(f'Field "{key}": {name} must be a whole number.')
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise SchemaError(f'Field "{key}": {name} must be between {lo} and {hi}.')
    return v


def _num_attr(f, name, key):
    v = f.get(name)
    if v in (None, ''):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise SchemaError(f'Field "{key}": {name} must be a number.')
    if not math.isfinite(v):
        raise SchemaError(f'Field "{key}": {name} must be a number.')
    return int(v) if v == int(v) else v


def _check_no_secret(field):
    if field['type'] not in FREE_ENTRY_TYPES:
        return
    for text in (field['label'], field['key'].replace('_', ' '), field.get('placeholder', '')):
        if text and SECRET_RE.search(text):
            raise SchemaError(
                f'Field "{field["label"]}" looks like it asks for a password, PIN or sign-in '
                f'code. Request forms must never collect passwords, MFA codes, recovery codes '
                f'or other secrets — ask for the account name instead and we will set '
                f'credentials up securely.')


def _clean_default(field, raw):
    """Validate a field default against its own type and options."""
    ftype = field['type']
    if raw in (None, '', []):
        return None
    if ftype == 'checkbox':
        return bool(raw) if not isinstance(raw, str) else raw.lower() in ('true', 'yes', 'on', '1')
    if ftype in ('select', 'radio'):
        v = clean_text(raw, 200)
        if v not in option_values(field):
            raise SchemaError(f'Field "{field["key"]}": default "{v}" is not one of its options.')
        return v
    if ftype == 'multiselect':
        vals = raw if isinstance(raw, list) else [raw]
        vals = [clean_text(v, 200) for v in vals]
        bad = [v for v in vals if v not in option_values(field)]
        if bad:
            raise SchemaError(f'Field "{field["key"]}": default "{bad[0]}" is not one of its options.')
        return list(dict.fromkeys(vals))
    if ftype == 'number':
        v = _num_attr({'d': raw}, 'd', field['key'])
        if field.get('min') is not None and v < field['min'] or \
                field.get('max') is not None and v > field['max']:
            raise SchemaError(f'Field "{field["key"]}": default is outside min / max.')
        return v
    if ftype == 'date':
        try:
            return _dt.date.fromisoformat(str(raw)).isoformat()
        except ValueError:
            raise SchemaError(f'Field "{field["key"]}": default must be a date (YYYY-MM-DD).')
    if ftype in ('text', 'textarea', 'tel', 'user', 'email'):
        v = clean_text(raw, MAX_LEN.get(ftype, 500))
        if field.get('max_length') and len(v) > field['max_length']:
            raise SchemaError(f'Field "{field["key"]}": default is longer than max length.')
        if ftype == 'email':
            from django.core.exceptions import ValidationError
            from django.core.validators import validate_email
            try:
                validate_email(v)
            except ValidationError:
                raise SchemaError(f'Field "{field["key"]}": default is not an email address.')
        return v
    raise SchemaError(f'Field "{field["key"]}": this field type cannot have a default.')


def normalize_schema(raw, *, allow_legacy_types=True):
    """Validate + normalise a schema definition. Raises SchemaError."""
    if raw in (None, ''):
        return []
    if not isinstance(raw, list):
        raise SchemaError('The form must be a list of fields.')
    if len(raw) > MAX_FIELDS:
        raise SchemaError(f'At most {MAX_FIELDS} fields are allowed.')
    cycle = _find_cycle(raw)
    if cycle:
        raise SchemaError('Circular condition: ' + ' → '.join(cycle)
                          + '. A question cannot depend on itself, directly or indirectly.')
    allowed = ALL_TYPES if allow_legacy_types else FIELD_TYPES
    out = []
    by_key = {}
    for i, f in enumerate(raw, start=1):
        if not isinstance(f, dict):
            raise SchemaError(f'Field #{i} must be an object.')
        key = str(f.get('key') or '').strip()
        label = clean_text(f.get('label'), 200)
        if not KEY_RE.match(key):
            raise SchemaError(
                f'Field #{i}: key "{key}" must start with a lowercase letter and '
                f'use only lowercase letters, digits and underscores.')
        if key in by_key:
            raise SchemaError(f'Field key "{key}" is used twice.')
        ftype = str(f.get('type') or 'text').strip()
        if ftype not in allowed:
            raise SchemaError(
                f'Field "{key}": invalid type {ftype!r}. Allowed: {", ".join(allowed)}.')
        if not label and ftype != 'info':
            raise SchemaError(f'Field "{key}" needs a label.')
        field = {'key': key, 'label': label, 'type': ftype}
        if ftype not in DISPLAY_TYPES:
            field['required'] = bool(f.get('required'))
        help_text = clean_text(f.get('help'), 2000 if ftype == 'info' else 500)
        if help_text:
            field['help'] = help_text
        if ftype == 'info' and not help_text and not label:
            raise SchemaError(f'Field "{key}": information text needs some text.')
        placeholder = clean_text(f.get('placeholder'), 200)
        if placeholder and ftype not in DISPLAY_TYPES:
            field['placeholder'] = placeholder
        if ftype in CHOICE_TYPES:
            field['options'] = _clean_options(key, f.get('options') or [])
        if f.get('sensitive') and ftype not in DISPLAY_TYPES:
            field['sensitive'] = True

        # Type-specific constraints.
        if ftype in ('text', 'textarea'):
            ml = _int_attr(f, 'max_length', 1, MAX_LEN[ftype], key)
            if ml:
                field['max_length'] = ml
        if ftype == 'number':
            for attr in ('min', 'max'):
                v = _num_attr(f, attr, key)
                if v is not None:
                    field[attr] = v
            if 'min' in field and 'max' in field and field['min'] > field['max']:
                raise SchemaError(f'Field "{key}": min is greater than max.')
            if f.get('integer'):
                field['integer'] = True
        if ftype in ('date', 'datetime'):
            if f.get('not_in_past'):
                field['not_in_past'] = True
            if f.get('requested_date'):
                field['requested_date'] = True
        if ftype == 'file':
            mf = _int_attr(f, 'max_files', 1, MAX_FILES_PER_FIELD, key) or 1
            field['max_files'] = mf
        if ftype in ('contact', 'asset'):
            field['allow_text'] = f.get('allow_text', True) is not False
        if f.get('maps_to'):
            if f.get('maps_to') != 'urgency' or ftype not in ('select', 'radio'):
                raise SchemaError(f'Field "{key}": only a dropdown or radio field can set the '
                                  f'ticket urgency.')
            bad = [v for v in option_values(field) if v not in URGENCY_VALUES]
            if bad:
                raise SchemaError(f'Field "{key}": urgency options must use the values '
                                  f'{", ".join(URGENCY_VALUES)} (labels can be anything).')
            field['maps_to'] = 'urgency'

        if ftype not in DISPLAY_TYPES:
            _check_no_secret(field)

        show_if = _clean_condition(f.get('show_if'), by_key, key, 'show_if')
        if show_if:
            field['show_if'] = show_if
        if ftype not in DISPLAY_TYPES:
            required_if = _clean_condition(f.get('required_if'), by_key, key, 'required_if')
            if required_if:
                field['required_if'] = required_if
            if 'default' in f and ftype not in ('file', 'contact', 'asset', 'location', 'datetime'):
                d = _clean_default(field, f.get('default'))
                if d is not None:
                    field['default'] = d
        by_key[key] = field
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
        if ftype not in ('text', 'email', 'date', 'number', 'textarea', 'select', 'checkbox',
                         'multiselect', 'user'):
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
    ticket form reads. Types the staff form doesn't know become text,
    display-only and file fields are left out, and conditional fields lose
    `required` (the staff form has no conditions)."""
    legacy_types = {'text', 'email', 'date', 'number', 'textarea', 'select', 'checkbox'}
    out = []
    for f in schema or []:
        if f['type'] in DISPLAY_TYPES or f['type'] == 'file':
            continue
        ftype = 'select' if f['type'] == 'radio' else f['type']
        lf = {
            'key': f['key'],
            'label': f['label'],
            'type': ftype if ftype in legacy_types else 'text',
            'required': (bool(f.get('required')) and not f.get('show_if')
                         and f['type'] not in LOOKUP_TYPES),
        }
        if f.get('help'):
            lf['help'] = f['help']
        placeholder = f.get('placeholder')
        if f['type'] == 'multiselect' and not placeholder:
            placeholder = 'One or more of: ' + ', '.join(label for _, label in option_pairs(f))
        if placeholder:
            lf['placeholder'] = placeholder
        if lf['type'] == 'select':
            lf['options'] = [label for _, label in option_pairs(f)]
        out.append(lf)
    return out


# ---------------------------------------------------------------------------
# Conditional visibility
# ---------------------------------------------------------------------------

def _value_strings(value):
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_value_strings(v) if isinstance(v, dict) else [str(v)])
        return out
    if isinstance(value, bool):
        return ['true' if value else 'false', 'yes' if value else 'no']
    if isinstance(value, dict):
        # A lookup answer matches on its id or its name; a time on its value.
        return [str(value[k]) for k in ('id', 'value', 'label', 'text', 'name')
                if value.get(k) not in (None, '')]
    if value in (None, ''):
        return []
    return [str(value)]


def _is_answered(value):
    return value not in (None, '', [], False, {})


def _matches(cond, value):
    """Does `value` (a cleaned answer) satisfy one simple condition?"""
    values = _value_strings(value)
    op = cond.get('op')
    if op is None:   # legacy shapes
        if 'in' in cond:
            wanted = {str(v) for v in cond['in']}
            return any(v in wanted for v in values)
        eq = cond.get('equals')
        if isinstance(eq, bool):
            if isinstance(value, bool):
                return value is eq
            lower = [v.lower() for v in values]
            return (str(eq).lower() in lower) or (('yes' if eq else 'no') in lower)
        return str(eq) in values
    target = cond.get('value')
    if op == 'is_set':
        return _is_answered(value)
    if op == 'not_set':
        return not _is_answered(value)
    if op in ('equals', 'not_equals'):
        if isinstance(target, bool):
            hit = (bool(value) is target) if isinstance(value, bool) or value in (None, '') \
                else (('yes' if target else 'no') in [v.lower() for v in values])
        else:
            hit = str(target) in values
        return hit if op == 'equals' else not hit
    if op in ('in', 'not_in'):
        wanted = {str(v) for v in target or []}
        hit = any(v in wanted for v in values)
        return hit if op == 'in' else not hit
    if op == 'contains':
        if isinstance(value, list):
            return str(target) in values
        return str(target).casefold() in ' '.join(values).casefold()
    return False


def condition_holds(cond, values, is_visible):
    """Evaluate a normalised condition. A condition on a field that is
    itself hidden is false (so chains of hidden questions collapse)."""
    if not cond:
        return True

    def one(c):
        ctrl = c.get('field')
        return bool(ctrl) and is_visible(ctrl) and _matches(c, values.get(ctrl))

    if 'all' in cond:
        return all(one(c) for c in cond['all'])
    if 'any' in cond:
        return any(one(c) for c in cond['any'])
    return one(cond)


def visibility(schema, values):
    """{key: visible?} for every field. Headings hide their section."""
    by_key = {f['key']: f for f in schema}
    section_of = {}
    current = None
    for f in schema:
        if f['type'] == 'heading':
            current = f['key']
            section_of[f['key']] = None
        else:
            section_of[f['key']] = current
    memo = {}

    def vis(key, depth=0):
        if key in memo:
            return memo[key]
        f = by_key.get(key)
        if f is None or depth > len(schema) + 1:
            return False
        memo[key] = False  # guard against any cycle in hand-edited data
        sec = section_of.get(key)
        ok = True
        if sec and not vis(sec, depth + 1):
            ok = False
        if ok and f.get('show_if'):
            ok = condition_holds(f['show_if'], values, lambda k: vis(k, depth + 1))
        memo[key] = ok
        return ok

    return {f['key']: vis(f['key']) for f in schema}


def visible_keys(schema, values):
    """Keys of fields visible given `values`. A field whose controlling
    field is itself hidden is hidden too."""
    return {k for k, v in visibility(schema, values).items() if v}


def is_required(field, values, vis):
    if field['type'] in DISPLAY_TYPES:
        return False
    if field.get('required'):
        return True
    cond = field.get('required_if')
    return bool(cond) and condition_holds(cond, values, lambda k: vis.get(k, False))


# ---------------------------------------------------------------------------
# Submission validation
# ---------------------------------------------------------------------------

class FormContext:
    """Who is submitting, for lookups and date checks. Built by the portal
    view from the server-side portal membership, never from the POST."""

    def __init__(self, organization=None, user=None, membership=None, today=None):
        self.organization = organization
        self.user = user
        self.membership = membership
        self.today = today

    def get_today(self):
        if self.today is not None:
            return self.today
        from django.utils import timezone
        return timezone.localdate()


def input_names(field):
    """POST names a field may use."""
    name = FIELD_PREFIX + field['key']
    if field['type'] in DISPLAY_TYPES:
        return set()
    if field['type'] in ('contact', 'asset'):
        return {name, name + TEXT_SUFFIX} if field.get('allow_text', True) else {name}
    if field['type'] == 'datetime':
        return {name, name + TZ_SUFFIX}
    return {name}


def _single(post, name, field):
    if len(post.getlist(name)) > 1:
        return None, f'{field["label"]}: only one value is allowed.'
    return post.get(name), None


def _clean_value(field, post, files=None, ctx=None):
    """Return (value, error) for one field from a QueryDict-like `post`."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    name = FIELD_PREFIX + field['key']
    ftype = field['type']
    label = field['label']
    if ftype in DISPLAY_TYPES:
        return None, None
    if ftype == 'checkbox':
        raw = (post.get(name) or '').strip().lower()
        if raw and raw not in ('on', 'true', '1', 'yes'):
            return None, f'{label}: invalid value.'
        return bool(raw), None
    if ftype == 'multiselect':
        raw = [clean_text(v, MAX_LEN['select']) for v in post.getlist(name)]
        raw = [v for v in raw if v]
        opts = option_values(field)
        bad = [v for v in raw if v not in opts]
        if bad:
            return None, f'{label}: "{bad[0]}" is not one of the choices.'
        return list(dict.fromkeys(raw)), None
    if ftype == 'file':
        return _clean_files(field, files)
    if ftype in LOOKUP_TYPES:
        return _clean_lookup(field, post, ctx)
    if ftype == 'datetime':
        return _clean_datetime(field, post, ctx)

    raw, err = _single(post, name, field)
    if err:
        return None, err
    value = clean_text(raw, field.get('max_length') or MAX_LEN.get(ftype, 500))
    if not value:
        return '', None
    if ftype in ('select', 'radio'):
        if value not in option_values(field):
            return None, f'{label}: "{value}" is not one of the choices.'
    elif ftype == 'email':
        try:
            validate_email(value)
        except ValidationError:
            return None, f'{label}: enter a valid email address.'
    elif ftype == 'tel':
        if not _TEL_RE.match(value) or sum(c.isdigit() for c in value) < 3:
            return None, f'{label}: enter a telephone number (digits, spaces, + ( ) - only).'
    elif ftype == 'date':
        try:
            d = _dt.date.fromisoformat(value)
        except ValueError:
            return None, f'{label}: enter a date as YYYY-MM-DD.'
        if field.get('not_in_past') and ctx is not None and d < ctx.get_today():
            return None, f'{label}: pick today or a later date.'
        value = d.isoformat()
    elif ftype == 'number':
        try:
            num = float(value)
        except ValueError:
            return None, f'{label}: enter a number.'
        if not math.isfinite(num):
            return None, f'{label}: enter a number.'
        if field.get('integer') and num != int(num):
            return None, f'{label}: enter a whole number.'
        if field.get('min') is not None and num < field['min']:
            return None, f'{label}: must be at least {field["min"]}.'
        if field.get('max') is not None and num > field['max']:
            return None, f'{label}: must be at most {field["max"]}.'
    elif ftype in ('text', 'textarea') and field.get('max_length') \
            and len(clean_text(raw, 100000)) > field['max_length']:
        return None, f'{label}: at most {field["max_length"]} characters.'
    return value, None


def _clean_datetime(field, post, ctx):
    name = FIELD_PREFIX + field['key']
    label = field['label']
    raw, err = _single(post, name, field)
    if err:
        return None, err
    tz_raw, err = _single(post, name + TZ_SUFFIX, field)
    if err:
        return None, err
    value = clean_text(raw, 16)
    tz = clean_text(tz_raw, 64)
    if not value:
        return '', None
    if not _DATETIME_RE.match(value):
        return None, f'{label}: enter a date and time.'
    try:
        naive = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None, f'{label}: enter a date and time.'
    from zoneinfo import ZoneInfo, available_timezones
    if not tz or tz not in available_timezones():
        return None, f'{label}: pick the time zone this time is in.'
    if field.get('not_in_past') and ctx is not None:
        from django.utils import timezone as djtz
        if naive.replace(tzinfo=ZoneInfo(tz)) < djtz.now():
            return None, f'{label}: pick a time that has not passed yet.'
    return {'value': value, 'tz': tz}, None


def _clean_files(field, files):
    from files import upload_rules
    label = field['label']
    name = FIELD_PREFIX + field['key']
    uploads = list(files.getlist(name)) if files is not None else []
    uploads = [u for u in uploads if getattr(u, 'name', '')]
    if not uploads:
        return [], None
    if len(uploads) > field.get('max_files', 1):
        return None, f'{label}: attach at most {field.get("max_files", 1)} file(s).'
    for u in uploads:
        fname = (u.name or '').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
        if u.size > upload_rules.MAX_FILE_SIZE:
            return None, f'{label}: "{clean_text(fname, 80)}" is larger than 25 MB.'
        if upload_rules.extension(fname) == 'svg':
            return None, f'{label}: "{clean_text(fname, 80)}" — SVG images cannot be attached here.'
        header = u.read(512)
        u.seek(0)
        problem = (upload_rules.check_name(fname)
                   or upload_rules.check_declared_type(fname, getattr(u, 'content_type', ''))
                   or upload_rules.check_magic(fname, header))
        if problem:
            return None, f'{label}: "{clean_text(fname, 80)}" — {problem}.'
    return uploads, None


def _clean_lookup(field, post, ctx):
    from psa import request_lookups
    name = FIELD_PREFIX + field['key']
    label = field['label']
    raw, err = _single(post, name, field)
    if err:
        return None, err
    raw = clean_text(raw, 20)
    text = ''
    if field['type'] in ('contact', 'asset') and field.get('allow_text', True):
        t, err = _single(post, name + TEXT_SUFFIX, field)
        if err:
            return None, err
        text = clean_text(t, 200)
    if raw:
        if not raw.isdigit():
            return None, f'{label}: pick one of the listed entries.'
        if ctx is None or ctx.organization is None:
            return None, f'{label}: this choice is not available.'
        obj = request_lookups.resolve(field, int(raw), ctx)
        if obj is None:
            # Unknown, another customer's, or outside what this person may see.
            return None, f'{label}: pick one of the listed entries.'
        return {'id': obj['id'], 'label': obj['label']}, None
    if text:
        return {'text': text}, None
    return '', None


def _is_empty(value):
    return value in (None, '', [], False)


def allowed_post_keys(schema):
    known = set(ALLOWED_EXTRA_POST_KEYS)
    for f in schema:
        known |= input_names(f)
    return known


def validate_submission(schema, post, files=None, context=None, field_errors=None):
    """Validate a portal submission against `schema` (the published form).

    Returns (answers, errors). `answers` maps key → cleaned value for
    visible fields only (file fields: a list of uploaded files). Unknown
    POST or FILES keys are an error, not ignored.
    """
    errors = []
    known = allowed_post_keys(schema)
    unknown = sorted(k for k in post.keys() if k not in known)
    file_names = {FIELD_PREFIX + f['key'] for f in schema if f['type'] == 'file'}
    if files is not None:
        unknown += sorted(k for k in files.keys() if k not in file_names)
    if unknown:
        errors.append('The form contained unexpected fields: '
                      + ', '.join(clean_text(k, 60) for k in unknown[:5]) + '.')
        return {}, errors

    cleaned = {}
    for f in schema:
        if f['type'] in DISPLAY_TYPES:
            continue
        value, err = _clean_value(f, post, files, context)
        if err:
            errors.append(err)
            if field_errors is not None:
                field_errors[f['key']] = err
            value = None
        cleaned[f['key']] = value

    vis = visibility(schema, cleaned)
    answers = {}
    for f in schema:
        if f['type'] in DISPLAY_TYPES or not vis.get(f['key']):
            continue  # hidden by condition: never required, value dropped
        value = cleaned.get(f['key'])
        if is_required(f, cleaned, vis) and _is_empty(value) and value is not None:
            errors.append(f'{f["label"]} is required.')
            if field_errors is not None:
                field_errors[f['key']] = f'{f["label"]} is required.'
        if value is not None:
            answers[f['key']] = value
    return answers, errors


def initial_values(schema):
    """Defaults for a fresh form, keyed by field key."""
    return {f['key']: f['default'] for f in schema if 'default' in f}


def display_value(field, value):
    ftype = field.get('type')
    if isinstance(value, bool) or ftype == 'checkbox':
        return 'Yes' if value else 'No'
    if ftype in CHOICE_TYPES:
        if isinstance(value, list):
            return ', '.join(option_label(field, v) for v in value)
        return '' if value in (None, '') else option_label(field, value)
    if ftype == 'date' and isinstance(value, str) and value:
        try:
            d = _dt.date.fromisoformat(value)
            return f'{d:%B} {d.day}, {d.year}'
        except ValueError:
            return value
    if ftype == 'datetime' and isinstance(value, dict):
        return f'{value.get("value", "").replace("T", " ")} ({value.get("tz", "")})'.strip()
    if ftype == 'file' and isinstance(value, list):
        return ', '.join(str(v.get('name') if isinstance(v, dict) else getattr(v, 'name', v))
                         for v in value)
    if isinstance(value, dict):
        if value.get('label'):
            return str(value['label'])
        if value.get('text'):
            return f'{value["text"]} (typed in)'
        return ''
    if isinstance(value, list):
        return ', '.join(str(v) for v in value)
    return '' if value is None else str(value)


def _json_value(field, value):
    """Answer value as stored (JSON-safe); uploaded files become names."""
    if field.get('type') == 'file' and isinstance(value, list):
        out = []
        for v in value:
            if isinstance(v, dict):
                out.append(v)
            else:
                out.append({'name': clean_text(getattr(v, 'name', ''), 255),
                            'size': getattr(v, 'size', 0)})
        return out
    return value


def answers_as_rows(schema, answers):
    """Ordered rows for storage + display. Each answered field gives
    {key, label, type, value, display[, sensitive, section]}; a section
    heading with at least one answer under it gives a heading row."""
    rows = []
    pending_heading = None
    for f in schema:
        if f['type'] == 'heading':
            pending_heading = {'key': f['key'], 'label': f['label'], 'type': 'heading',
                               'value': None, 'display': ''}
            continue
        if f['type'] == 'info' or f['key'] not in answers:
            continue
        if pending_heading is not None:
            rows.append(pending_heading)
            pending_heading = None
        v = _json_value(f, answers[f['key']])
        row = {
            'key': f['key'], 'label': f['label'], 'type': f['type'],
            'value': v, 'display': display_value(f, v),
        }
        if f.get('sensitive'):
            row['sensitive'] = True
        rows.append(row)
    return rows


def answer_rows(rows):
    """Rows that carry an answer (headings left out)."""
    return [r for r in rows if r.get('type') != 'heading']


def template_values(rows):
    """{{key}} substitution values for the subject / body templates.
    Sensitive answers substitute as blank so they never reach a subject
    line (which notification e-mails carry)."""
    return {r['key']: ('' if r.get('sensitive') else r['display']) for r in answer_rows(rows)}


def snapshot_schema(schema):
    """What a submission keeps of the form: labels, types, options."""
    keep = ('key', 'label', 'type', 'options', 'help', 'sensitive')
    return [{k: f[k] for k in keep if k in f} for f in schema]


# ---------------------------------------------------------------------------
# Catalog availability
# ---------------------------------------------------------------------------

def portal_catalog_for(organization, membership=None):
    """Published, enabled, portal-visible request types for `organization`.

    * MSP-wide items follow the include / exclude lists (exclude wins;
      an empty include list means every customer).
    * A customer's own copy is offered only to that customer, and while it
      is offered the MSP-wide item it was copied from is hidden for them.
    * Items for portal admins only are left out unless `membership` is a
      portal admin. With no membership given, audience isn't filtered
      (staff-side checks).
    """
    from django.db.models import Q
    from psa.models import ServiceCatalogItem
    if organization is None:
        return ServiceCatalogItem.objects.none()
    live = dict(is_active=True, portal_visible=True,
                lifecycle=ServiceCatalogItem.LIFECYCLE_PUBLISHED)
    overridden = (ServiceCatalogItem.objects
                  .filter(organization=organization, based_on__isnull=False, **live)
                  .values_list('based_on_id', flat=True))
    global_q = (Q(organization__isnull=True)
                & ~Q(exclude_organizations=organization)
                & (Q(include_organizations__isnull=True) | Q(include_organizations=organization)))
    qs = (ServiceCatalogItem.objects.filter(**live)
          .filter(global_q | Q(organization=organization))
          .exclude(pk__in=list(overridden)))
    if membership is not None and not (membership.is_org_admin and membership.is_active):
        qs = qs.exclude(portal_audience=ServiceCatalogItem.AUDIENCE_ORG_ADMINS)
    return qs.distinct().order_by('category', 'sort_order', 'name')


# ---------------------------------------------------------------------------
# Who approves (named approvers per request type and customer)
# ---------------------------------------------------------------------------

# Where the approver list came from (approvers_for()['source']).
SOURCE_NAMED = 'named'                    # the item's named approvers
SOURCE_ADMINS = 'admins'                  # no (current) names: org admins
SOURCE_REQUESTER_ONLY = 'requester_only'  # the requester is the only named
                                          # approver: org admins instead


def eligible_approver_memberships(organization):
    """Active memberships of `organization` whose people may be named as
    approvers: active users who are customer people, not MSP staff."""
    from accounts.models import Membership
    if organization is None:
        return Membership.objects.none()
    staff_ids = _msp_staff_ids()
    return (Membership.objects
            .filter(organization=organization, is_active=True, user__is_active=True)
            .exclude(user_id__in=staff_ids)
            .select_related('user')
            .order_by('user__first_name', 'user__last_name', 'user__username'))


def _msp_staff_ids():
    from django.contrib.auth.models import User
    from psa.visibility import msp_staff_q
    return set(User.objects.filter(msp_staff_q()).values_list('pk', flat=True))


def named_approver_rows(item, organization):
    """(current_users, departed_rows) for the item's named approvers at
    `organization`. Departed rows name someone who is no longer an active
    customer member there (left, deactivated, or now MSP staff); they are
    ignored for approval and flagged in the staff UI."""
    from psa.models import ServiceRequestApprover
    if item is None or getattr(item, 'pk', None) is None or organization is None:
        return [], []
    rows = list(ServiceRequestApprover.objects
                .filter(catalog_item=item, organization=organization)
                .select_related('user'))
    if not rows:
        return [], []
    eligible = set(eligible_approver_memberships(organization)
                   .values_list('user_id', flat=True))
    current = [r.user for r in rows if r.user_id in eligible]
    departed = [r for r in rows if r.user_id not in eligible]
    return current, departed


def _org_admins(organization):
    from django.contrib.auth.models import User
    return list(User.objects.filter(
        memberships__organization=organization, memberships__is_active=True,
        memberships__is_org_admin=True, is_active=True,
    ).distinct().order_by('first_name', 'last_name', 'username'))


def approvers_for(item, organization, requester=None):
    """Who may approve a service request for `item` at `organization`.

    Returns {'users': [...], 'source': SOURCE_*, 'departed': [rows]}.

    * Named approvers who are still active customer members there, minus
      the requester — any one of them approves.
    * If names are set but the requester is the only current one, the
      customer's org admins (minus the requester) approve instead.
    * No names (or everyone named has left): the customer's org admins,
      minus the requester — the original rule.

    When the request type explicitly allows self-approval
    (`approval_allow_self`), a requester who is otherwise eligible stays
    in the list.
    """
    requester_id = getattr(requester, 'pk', requester)
    allow_self = bool(getattr(item, 'approval_allow_self', False))
    current, departed = named_approver_rows(item, organization)
    if current:
        users = [u for u in current if allow_self or u.pk != requester_id]
        if users:
            return {'users': users, 'source': SOURCE_NAMED, 'departed': departed}
        source = SOURCE_REQUESTER_ONLY
    else:
        source = SOURCE_ADMINS
    users = [u for u in _org_admins(organization) if allow_self or u.pk != requester_id]
    return {'users': users, 'source': source, 'departed': departed}


def approval_catalog_item(approval):
    """The catalog item a service-request approval belongs to, or None."""
    from psa.models import ServiceCatalogItem
    if approval.object_type != APPROVAL_OBJECT_TYPE or not approval.object_id:
        return None
    return ServiceCatalogItem.objects.filter(pk=approval.object_id).first()


def approvers_for_approval(approval):
    return approvers_for(approval_catalog_item(approval), approval.organization,
                         approval.requested_by_id)


def can_approve_service_request(approval, user):
    """True when `user` may decide this service-request approval. The
    requester never may, unless the request type explicitly allows it."""
    if user is None or not getattr(user, 'pk', None):
        return False
    item = approval_catalog_item(approval)
    if approval.requested_by_id == user.pk and not getattr(item, 'approval_allow_self', False):
        return False
    return any(u.pk == user.pk for u in approvers_for(
        item, approval.organization, approval.requested_by_id)['users'])


def notify_approvers(approval, ticket, item, requester):
    """Email the people who can approve a new service request. Best-effort:
    a mail failure never blocks the submission. The e-mail names the
    request type and ticket only — the answers stay behind the portal
    sign-in. Returns the recipients."""
    from django.conf import settings as django_settings
    from django.urls import reverse

    from core.models import SystemSetting
    from psa.notifications import _send_email

    try:
        if not SystemSetting.get_settings().psa_portal_customer_approvals_enabled:
            return []
    except Exception:
        return []
    who = approvers_for(item, approval.organization, requester)['users']
    base = getattr(django_settings, 'SITE_URL', '').rstrip('/')
    url = base + reverse('portal:approvals_list')
    name = requester.get_full_name() or requester.username
    sent = []
    for user in who:
        if not user.email:
            continue
        ok, _ = _send_email(
            user,
            f'[{ticket.ticket_number}] Approval needed: {item.name}',
            f'{name} has asked for "{item.name}" ({ticket.ticket_number}) '
            f'and it needs your approval before work starts.\n\n'
            f'Review it in the portal: {url}\n',
        )
        if ok:
            sent.append(user)
    return sent


def on_approval_decided(approval, user, approved):
    """After a service-request approval is decided in the portal: record
    the outcome on the request, start a workflow that was waiting for the
    approval, and e-mail the requester (no answers in the e-mail)."""
    import logging
    from django.utils import timezone

    ticket = approval.related_ticket
    if ticket is None:
        return
    item = approval_catalog_item(approval)
    record = service_request_record(ticket) or {}
    record['approval_status'] = 'approved' if approved else 'denied'
    if approved and record.get('process_deferred') and item is not None \
            and item.process_template_id and not record.get('process_execution_id'):
        try:
            record['process_execution_id'] = _start_process(
                item.process_template, item, ticket, approval.requested_by or user,
                timezone.now())
        except Exception:
            logging.getLogger('psa').exception('Deferred service request workflow failed')
        record['process_deferred'] = False
    cf = dict(ticket.custom_fields or {})
    cf[SERVICE_REQUEST_KEY] = record
    ticket.custom_fields = cf
    ticket.save(update_fields=['custom_fields', 'updated_at'])
    requester = approval.requested_by
    if requester is not None and requester.email and requester.pk != getattr(user, 'pk', None):
        try:
            from django.conf import settings as django_settings
            from django.urls import reverse
            from psa.notifications import _send_email
            base = getattr(django_settings, 'SITE_URL', '').rstrip('/')
            url = base + reverse('portal:ticket_detail', args=[ticket.ticket_number])
            verdict = 'approved' if approved else 'declined'
            _send_email(
                requester,
                f'[{ticket.ticket_number}] Your request was {verdict}',
                f'Your request "{record.get("catalog_item_name") or ticket.subject}" '
                f'({ticket.ticket_number}) was {verdict}.\n\nSee it in the portal: {url}\n',
            )
        except Exception:
            logging.getLogger('psa').exception('Approval decision e-mail failed')


# ---------------------------------------------------------------------------
# Submission → ticket (+ attachments, approval, workflow)
# ---------------------------------------------------------------------------

SERVICE_REQUEST_KEY = 'service_request'
APPROVAL_OBJECT_TYPE = 'psa.ServiceCatalogItem'


class DuplicateSubmission(Exception):
    """The form token was already used: `submission` is the earlier one."""

    def __init__(self, submission):
        super().__init__('duplicate submission')
        self.submission = submission


def valid_token(token):
    return bool(token) and bool(_TOKEN_RE.match(token))


def answers_text(rows, *, include_sensitive=True):
    """Readable "Label: value" lines for the ticket description."""
    lines = []
    for r in rows:
        if r.get('type') == 'heading':
            continue
        if r['display'] == '' or (r.get('sensitive') and not include_sensitive):
            continue
        if r['type'] == 'textarea' and '\n' in r['display']:
            lines.append(f'{r["label"]}:')
            lines.append(r['display'])
        else:
            lines.append(f'{r["label"]}: {r["display"]}')
    return '\n'.join(lines).strip()


_SUBJECT_JUNK = re.compile(r'(\(\s*\)|\[\s*\])')
_SUBJECT_SEP = re.compile(r'\s*([—–:|,-])\s*(?=[—–:|,-]|$)')


def render_subject(pattern, values, *, item_name='', requester='', organization=''):
    """Subject from a {{key}} pattern; also {{request_type}}, {{requester}}
    and {{organization}}. A " — words {{key}}" fragment whose answer is
    blank is dropped, leftover separators and empty brackets are trimmed,
    and a pattern that leaves nothing readable falls back to
    "<request type> — <requester>"."""
    from psa.models import ServiceCatalogItem
    tokens = dict(values or {})
    tokens.setdefault('request_type', item_name)
    tokens.setdefault('requester', requester)
    tokens.setdefault('organization', organization)
    out = ''
    if pattern:
        # Drop "label {{blank}}" fragments separated by an em dash / pipe so
        # "— starts {{start}}" disappears when start is blank.
        def _drop(m):
            key = m.group(2)
            return '' if not str(tokens.get(key) or '').strip() else m.group(0)
        pat = re.sub(r'(\s[—–|]\s[^{}—–|]*?\{\{\s*([a-zA-Z0-9_]+)\s*\}\})', _drop, pattern)
        out = ServiceCatalogItem.render_template(pat, tokens)
    out = _CONTROL_RE.sub('', out).replace('\n', ' ').replace('\r', ' ')
    out = _SUBJECT_JUNK.sub('', out)
    out = re.sub(r'\s{2,}', ' ', out).strip()
    out = _SUBJECT_SEP.sub('', out).strip(' -—–:|,')
    if not re.search(r'[A-Za-z0-9]', out):
        out = f'{item_name} — {requester}' if requester else item_name
    return clean_text(out, 300)


def _process_assignee(process, item):
    """ProcessExecution needs an assignee. The workflow's author is the most
    defensible default; fall back to whoever last published the catalog
    item. Returns None when neither is an active user."""
    for user in (getattr(process, 'created_by', None),
                 getattr(item, 'last_published_by', None)):
        if user is not None and user.is_active:
            return user
    return None


def _default_assignee(item, organization):
    """(user, problem) — the item's default technician if they may work
    for this customer (same checks Ticket Routing uses)."""
    user = item.default_assignee if item.default_assignee_id else None
    if user is None:
        return None, ''
    try:
        from psa.routing.engine import _authorization_problem, customer_settings
        cust = customer_settings(organization)
        authorized = set()
        if cust is not None and cust.restrict_technicians:
            authorized = set(cust.authorized_technicians.values_list('pk', flat=True))
        problem = _authorization_problem(user, organization, cust, authorized)
    except Exception:  # noqa: BLE001
        problem = 'could not be checked'
    return (None, problem) if problem else (user, '')


def _save_attachments(ticket, user, schema, answers):
    """Store uploaded files as normal (customer-visible) ticket attachments
    and replace them in `answers` with {attachment_id, name, size}."""
    from psa.models import TicketAttachment
    from files import upload_rules
    for f in schema:
        if f['type'] != 'file' or not answers.get(f['key']):
            continue
        stored = []
        for u in answers[f['key']]:
            if isinstance(u, dict):
                stored.append(u)
                continue
            name = (u.name or 'attachment').rsplit('/', 1)[-1].rsplit('\\', 1)[-1]
            name = clean_text(name.replace('\x00', ''), 255) or 'attachment'
            att = TicketAttachment.objects.create(
                ticket=ticket, uploaded_by=user, file=u, filename=name,
                content_type=upload_rules.content_type_for(name), size_bytes=u.size,
                is_internal=False,
            )
            stored.append({'attachment_id': att.pk, 'name': name, 'size': u.size})
        answers[f['key']] = stored


def submit_request(*, item, organization, user, answers, token=None, version=None):
    """Create the ticket for a validated portal submission.

    Uses the same Ticket.objects.create path as the plain portal form,
    with routing from the catalog item. Raises ValueError when PSA lookups
    (queue/type/priority/status) are missing, DuplicateSubmission when the
    form token was already used. Returns the ticket.
    """
    from django.db import IntegrityError, transaction
    from django.utils import timezone

    from psa.models import (
        PSAApproval, Queue, ServiceRequestSubmission, Ticket, TicketComment,
        TicketPriority, TicketStatus, TicketType,
    )
    from psa.request_forms import ensure_version

    if version is None:
        version = ensure_version(item)
    schema = list(version.schema) if version is not None else item.get_form_schema()
    answers = dict(answers)

    queue = item.default_queue if (item.default_queue and item.default_queue.is_active) \
        else Queue.objects.filter(is_active=True).first()
    ticket_type = item.default_type if (item.default_type and item.default_type.is_active) \
        else TicketType.objects.filter(is_active=True).first()
    priority = item.default_priority or TicketPriority.objects.order_by('sort_order').first()
    status = TicketStatus.objects.filter(slug='new').first()
    if not (queue and ticket_type and priority and status):
        raise ValueError('PSA is not configured')

    token = token if valid_token(token) else None
    import uuid
    now = timezone.now()
    requester = user.get_full_name() or user.username
    assignee, assignee_problem = _default_assignee(item, organization)
    try:
        with transaction.atomic():
            # Claim the token first: a second POST with the same token hits
            # the unique constraint and gets the first ticket back.
            submission = ServiceRequestSubmission.objects.create(
                token=token or uuid.uuid4().hex,
                catalog_item=item, catalog_item_name=item.name[:120],
                organization=organization, submitted_by=user,
                form_version=version, form_version_number=getattr(version, 'number', None),
                schema_snapshot=snapshot_schema(schema),
            )
            rows_for_text = answers_as_rows(schema, answers)
            values = template_values(rows_for_text)
            readable = answers_text(rows_for_text, include_sensitive=False)
            has_sensitive = any(r.get('sensitive') for r in rows_for_text)
            pattern = (version.subject_pattern if version is not None and version.subject_pattern
                       else item.default_subject)
            subject = render_subject(pattern, values, item_name=item.name, requester=requester,
                                     organization=organization.name)
            if item.default_body:
                description = item.render_template(item.default_body, values).strip()
                # The body template may not mention every field; keep all answers
                # readable in the description too.
                if readable and readable not in description:
                    description = (description + '\n\n' + readable).strip()
            else:
                description = '\n\n'.join(p for p in (item.description, readable) if p)
            if has_sensitive:
                description += ('\n\nSome answers are kept out of this description; see '
                                'Request details on the ticket.')
            description = description.strip()[:50000]
            urgency = 'medium'
            for f in schema:
                if f.get('maps_to') == 'urgency' and answers.get(f['key']) in URGENCY_VALUES:
                    urgency = answers[f['key']]   # recorded only; priority stays policy

            ticket = Ticket.objects.create(
                organization=organization,
                subject=subject, description=description,
                queue=queue, priority=priority, ticket_type=ticket_type,
                status=status, source='portal',
                visibility='client', client_can_view=True,
                requester_name=requester,
                requester_email=user.email or '',
                created_by=user,
                urgency=urgency,
                assigned_to=assignee,
                assigned_team=(item.default_team.name[:100] if item.default_team_id else ''),
            )
            _save_attachments(ticket, user, schema, answers)
            rows = answers_as_rows(schema, answers)
            if assignee_problem:
                TicketComment.objects.create(
                    ticket=ticket, is_internal=True, is_system=True, source='workflow',
                    body=(f'Request type "{item.name}" names a default technician who was not '
                          f'assigned: {assignee_problem}.'),
                )
            record = {
                'catalog_item_id': item.pk,
                'catalog_item_slug': item.slug,
                'catalog_item_name': item.name,
                'category': item.category,
                'answers': rows,
                'form_version': getattr(version, 'number', None),
                'submission_id': submission.pk,
                'expected_turnaround': item.turnaround_display,
                'expected_turnaround_hours': item.expected_turnaround_hours,
                'approval_required': item.needs_customer_approval,
                'submitted_at': now.isoformat(),
                'submitted_by_id': user.pk,
            }

            approval = None
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
                record['approval_status'] = 'pending'

            if item.process_template_id:
                if approval is not None:
                    # Not approved work yet: the workflow starts on approval.
                    record['process_deferred'] = True
                    TicketComment.objects.create(
                        ticket=ticket, is_internal=True, is_system=True, source='workflow',
                        body=(f'Workflow "{item.process_template.title}" will start when the '
                              f'customer approves this request.'),
                    )
                else:
                    record['process_execution_id'] = _start_process(
                        item.process_template, item, ticket, user, now)

            ticket.custom_fields = dict(ticket.custom_fields or {})
            ticket.custom_fields[SERVICE_REQUEST_KEY] = record
            ticket.save(update_fields=['custom_fields', 'updated_at'])
            submission.ticket = ticket
            submission.original_answers = rows
            submission.answers = rows
            submission.save(update_fields=['ticket', 'original_answers', 'answers'])
    except IntegrityError:
        existing = (ServiceRequestSubmission.objects.filter(token=token).first()
                    if token else None)
        if existing is not None:
            raise DuplicateSubmission(existing)
        raise
    if approval is not None:
        try:
            notify_approvers(approval, ticket, item, user)
        except Exception:
            import logging
            logging.getLogger('psa').exception(
                'Service request approver notification failed')
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
