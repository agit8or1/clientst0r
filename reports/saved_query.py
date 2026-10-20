"""
Phase 26 v1 (v3.17.246) — Saved Query helpers.

The model is in `reports.models.SavedQuery`. This module owns the
allow-list of which model fields are queryable + how to build a Django
ORM filter from the saved JSON. Allow-listing is the security boundary
— a user can NOT save a query that filters on, say, an arbitrary
related model's field. They get exactly what `MODEL_CONFIG` exposes.
"""
from django.db.models import Q


# Per-target metadata.
#   model: import path used by `apps.get_model`.
#   filterable_fields: dict of {field_name: type}. Type is one of:
#       'str'  → equals / contains
#       'int'  → equals / gt / gte / lt / lte
#       'date' → gt / gte / lt / lte
#       'bool' → equals
#       'fk'   → equals on the FK pk
#   columns: list of field names safe to render in the result table.
MODEL_CONFIG = {
    'psa.Ticket': {
        'label': 'PSA Tickets',
        'filterable_fields': {
            'subject': 'str',
            'description': 'str',
            'assigned_to__username': 'str',
            'organization__name': 'str',
            'priority__code': 'str',
            'status__slug': 'str',
            'queue__name': 'str',
            'is_internal': 'bool',
            'sla_breached_response': 'bool',
            'sla_breached_resolution': 'bool',
            'created_at': 'date',
            'closed_at': 'date',
        },
        'columns': [
            'ticket_number', 'subject', 'organization__name',
            'priority__code', 'status__name', 'queue__name',
            'assigned_to__username', 'created_at', 'closed_at',
        ],
        'default_sort': '-created_at',
    },
    'assets.Asset': {
        'label': 'Assets',
        'filterable_fields': {
            'name': 'str',
            'asset_type': 'str',
            'organization__name': 'str',
            'serial_number': 'str',
            'vendor': 'str',
            'warranty_expiry': 'date',
            'purchase_date': 'date',
        },
        'columns': [
            'name', 'asset_type', 'organization__name',
            'serial_number', 'vendor', 'warranty_expiry', 'purchase_date',
        ],
        'default_sort': 'name',
    },
    'vault.Password': {
        'label': 'Vault Passwords',
        'filterable_fields': {
            'title': 'str',
            'username': 'str',
            'password_type': 'str',
            'organization__name': 'str',
            'is_personal': 'bool',
            'requires_reveal_approval': 'bool',
            'expires_at': 'date',
        },
        'columns': [
            'title', 'username', 'password_type', 'organization__name',
            'expires_at', 'requires_reveal_approval',
        ],
        'default_sort': 'title',
    },
    # Phase 26 v2 (v3.17.251): expand to invoicing + time entries.
    'psa.Invoice': {
        'label': 'Invoices',
        'filterable_fields': {
            'invoice_number': 'str',
            'title': 'str',
            'status': 'str',
            'client_org__name': 'str',
            'organization__name': 'str',
            'invoice_date': 'date',
            'due_date': 'date',
            'requires_approval': 'bool',
        },
        'columns': [
            'invoice_number', 'client_org__name', 'title', 'status',
            'invoice_date', 'due_date', 'subtotal', 'total', 'amount_paid',
        ],
        'default_sort': '-invoice_date',
    },
    'psa.TicketTimeEntry': {
        'label': 'Time Entries',
        'filterable_fields': {
            'user__username': 'str',
            'ticket__ticket_number': 'str',
            'ticket__organization__name': 'str',
            'is_billable': 'bool',
            'started_at': 'date',
            'ended_at': 'date',
            'notes': 'str',
        },
        'columns': [
            'started_at', 'user__username', 'ticket__ticket_number',
            'ticket__organization__name', 'duration_minutes',
            'is_billable', 'notes',
        ],
        'default_sort': '-started_at',
        # Tenant scope: `TicketTimeEntry` has no direct organization FK;
        # scope via the parent ticket. Default for other targets is the
        # plain `organization` field.
        'org_filter': 'ticket__organization',
    },
}

OPERATORS_BY_TYPE = {
    'str': ['equals', 'contains', 'startswith'],
    'int': ['equals', 'gt', 'gte', 'lt', 'lte'],
    'date': ['gt', 'gte', 'lt', 'lte'],
    'bool': ['equals'],
    'fk': ['equals'],
}

OP_TO_LOOKUP = {
    'equals': '',
    'contains': '__icontains',
    'startswith': '__istartswith',
    'gt': '__gt',
    'gte': '__gte',
    'lt': '__lt',
    'lte': '__lte',
}


def get_model(target_model):
    """Resolve the target_model string to a Django model class, or None."""
    from django.apps import apps
    if target_model not in MODEL_CONFIG:
        return None
    try:
        app_label, model_name = target_model.split('.')
        return apps.get_model(app_label, model_name)
    except (ValueError, LookupError):
        return None


def build_filter(target_model, filters):
    """
    Build a `Q` from a list of `{field, op, value}` dicts. Bad / unknown
    fields are silently dropped — we do NOT want a saved query to error
    out because the model's schema changed; just skip stale filters.

    Returns Q() (matches everything) if the filter list is empty/invalid.
    """
    config = MODEL_CONFIG.get(target_model)
    if not config:
        return Q()
    allowed = config['filterable_fields']
    q = Q()
    for f in filters or []:
        if not isinstance(f, dict):
            continue
        field = f.get('field')
        op = f.get('op') or 'equals'
        value = f.get('value')
        if field not in allowed:
            continue
        if op not in OPERATORS_BY_TYPE.get(allowed[field], []):
            continue
        ftype = allowed[field]
        # Cast value to the expected python type. Strings stay strings.
        if ftype == 'bool':
            value = str(value).lower() in ('1', 'true', 'yes', 'on')
        elif ftype == 'int':
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        elif value is None or value == '':
            continue
        lookup = field + OP_TO_LOOKUP[op]
        q &= Q(**{lookup: value})
    return q


# Role view flags applied to a saved query's rows when it runs for a user.
VIEW_PERMS = {
    'assets.Asset': 'assets_view',
    'vault.Password': 'vault_view',
}


def _scope_for_user(target_model, qs, user):
    """Apply the module view flag and, for vault entries, hide other users'
    personal (My Vault) entries. Until v3.17.618 a vault query listed every
    entry's title and username, personal ones included."""
    from django.db.models import Q
    from accounts.permission_utils import orgs_with_perm

    perm = VIEW_PERMS.get(target_model)
    if target_model == 'vault.Password':
        allowed = orgs_with_perm(user, perm)
        shared = Q(is_personal=False) if allowed is None else Q(
            is_personal=False, organization_id__in=allowed)
        return qs.filter(shared | Q(is_personal=True, personal_owner=user))
    if perm:
        allowed = orgs_with_perm(user, perm)
        if allowed is not None:
            qs = qs.filter(organization_id__in=allowed)
    return qs


def execute(saved_query, *, organization=None, user=None):
    """
    Run a `SavedQuery` and return (model, queryset). Tenant scope:
    if `organization` is provided, scope using the model's `org_filter`
    config (defaults to `organization`). Some models — TicketTimeEntry —
    scope through a relation (`ticket__organization`) instead. With `user`,
    rows are also limited to what that user's role may view.
    """
    model = get_model(saved_query.target_model)
    if model is None:
        return None, model.objects.none() if model else []
    qs = model.objects.all()
    if user is not None:
        qs = _scope_for_user(saved_query.target_model, qs, user)
    if organization is not None:
        cfg = MODEL_CONFIG.get(saved_query.target_model, {})
        org_field = cfg.get('org_filter', 'organization')
        try:
            qs = qs.filter(**{org_field: organization})
        except Exception:
            pass
    qs = qs.filter(build_filter(saved_query.target_model, saved_query.filters or []))
    sort = saved_query.sort_by or MODEL_CONFIG[saved_query.target_model]['default_sort']
    try:
        qs = qs.order_by(sort)
    except Exception:
        pass
    return model, qs


def render_columns(saved_query):
    cfg = MODEL_CONFIG.get(saved_query.target_model)
    if not cfg:
        return []
    if saved_query.columns:
        return [c for c in saved_query.columns if c in cfg['columns']]
    return list(cfg['columns'])
