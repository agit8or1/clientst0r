"""
Broken assets.Relationship rows: an end (string type + integer id) that no
longer resolves to a record, or resolves to a different customer's record.

core.models.Relation (the ContentType-based generic relation) is not created
or read anywhere in the codebase, so it is not covered here.
"""
from collections import defaultdict
from dataclasses import dataclass

REASON_MISSING = 'missing'
REASON_OTHER_CUSTOMER = 'other_customer'
REASON_UNKNOWN_TYPE = 'unknown_type'

REASON_LABELS = {
    REASON_MISSING: 'Record no longer exists',
    REASON_OTHER_CUSTOMER: 'Record belongs to another customer',
    REASON_UNKNOWN_TYPE: 'Unknown record type',
}

_CHUNK = 500


def type_models():
    """Relationship.source_type / target_type string -> model."""
    from assets.models import Asset, Contact, Service
    from docs.models import Document
    from vault.models import Password
    return {
        'asset': Asset,
        'contact': Contact,
        'document': Document,
        'password': Password,
        'service': Service,
    }


@dataclass
class BrokenRelationship:
    relationship: object
    source_problem: str = ''
    target_problem: str = ''

    @property
    def problems(self):
        out = []
        if self.source_problem:
            out.append(f'Source {self.relationship.source_type} #{self.relationship.source_id}: '
                       f'{REASON_LABELS[self.source_problem].lower()}')
        if self.target_problem:
            out.append(f'Target {self.relationship.target_type} #{self.relationship.target_id}: '
                       f'{REASON_LABELS[self.target_problem].lower()}')
        return out

    @property
    def reasons(self):
        return {r for r in (self.source_problem, self.target_problem) if r}


def find_broken_relationships(org_ids=None):
    """Return [BrokenRelationship], ordered by customer then id.

    `org_ids=None` checks every customer. One query for the relationships
    plus one per referenced type (chunked), regardless of row count."""
    from assets.models import Relationship
    qs = Relationship.objects.select_related('organization').order_by('organization__name', 'id')
    if org_ids is not None:
        qs = qs.filter(organization_id__in=org_ids)
    rels = list(qs)

    wanted = defaultdict(set)
    for r in rels:
        wanted[r.source_type].add(r.source_id)
        wanted[r.target_type].add(r.target_id)

    models = type_models()
    owner = {}  # (type, id) -> organization_id
    for type_name, ids in wanted.items():
        model = models.get(type_name)
        if model is None:
            continue
        ids = sorted(ids)
        for i in range(0, len(ids), _CHUNK):
            for pk, org_id in model._base_manager.filter(
                    pk__in=ids[i:i + _CHUNK]).values_list('pk', 'organization_id'):
                owner[(type_name, pk)] = org_id

    def problem(rel, type_name, obj_id):
        if type_name not in models:
            return REASON_UNKNOWN_TYPE
        key = (type_name, obj_id)
        if key not in owner:
            return REASON_MISSING
        if owner[key] != rel.organization_id:
            return REASON_OTHER_CUSTOMER
        return ''

    out = []
    for r in rels:
        b = BrokenRelationship(r, problem(r, r.source_type, r.source_id),
                               problem(r, r.target_type, r.target_id))
        if b.reasons:
            out.append(b)
    return out


def deletable(broken, include_other_customer=False):
    """Rows safe to delete in bulk: an end is missing (or, when asked, an end
    belongs to another customer). Unknown types are never bulk-deleted —
    they may be a type this code doesn't know about yet."""
    allowed = {REASON_MISSING}
    if include_other_customer:
        allowed.add(REASON_OTHER_CUSTOMER)
    return [b for b in broken
            if b.reasons and REASON_UNKNOWN_TYPE not in b.reasons and b.reasons & allowed]
