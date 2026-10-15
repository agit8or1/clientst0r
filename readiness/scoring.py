"""
Readiness scoring — a pure read over documents, assets, contacts, vault
metadata and relationships. Nothing here writes.

    evaluate(org)              -> OrgReadiness for one customer
    evaluate_many(orgs)        -> {org_id: OrgReadiness}

`evaluate_many` loads everything it needs for all the given customers in a
fixed number of queries (one or two per data source, and only for the
sources the active requirements actually use), then scores in Python. The
query count does not grow with the number of customers, assets or
requirements.

Status per requirement:
    met             the rule holds
    unmet           the rule doesn't hold
    excepted        it doesn't hold, but an active StandardException covers it
    not_applicable  nothing to check (e.g. no assets of that type)

Score = weight(met + excepted) / weight(met + unmet + excepted). A standard
(or customer) with no applicable weight has score None.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import DocumentationStandard, StandardException, StandardRequirement as R
from .params import asset_field_choices, asset_field_column, split_alternatives

MET = 'met'
UNMET = 'unmet'
EXCEPTED = 'excepted'
NOT_APPLICABLE = 'not_applicable'


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Record:
    kind: str            # document | asset | contact | credential
    id: int
    label: str
    url: str
    note: str = ''       # e.g. which asset fields are missing


@dataclass
class Fix:
    label: str
    url: str


@dataclass
class RequirementResult:
    requirement: R
    status: str
    weight: int
    explanation: str
    records: list = field(default_factory=list)
    fix: Optional[Fix] = None
    owner: object = None             # auth.User or None
    exception: Optional[StandardException] = None

    @property
    def owner_label(self):
        if self.owner is None:
            return 'Unassigned'
        return self.owner.get_full_name() or self.owner.username


@dataclass
class StandardResult:
    standard: DocumentationStandard
    results: list = field(default_factory=list)

    @property
    def applicable_weight(self):
        return sum(r.weight for r in self.results if r.status != NOT_APPLICABLE)

    @property
    def satisfied_weight(self):
        return sum(r.weight for r in self.results if r.status in (MET, EXCEPTED))

    @property
    def score(self):
        total = self.applicable_weight
        return None if not total else round(100.0 * self.satisfied_weight / total, 1)

    @property
    def unmet(self):
        return [r for r in self.results if r.status == UNMET]


@dataclass
class OrgReadiness:
    organization: object
    standards: list = field(default_factory=list)

    @property
    def applicable_weight(self):
        return sum(s.applicable_weight for s in self.standards)

    @property
    def satisfied_weight(self):
        return sum(s.satisfied_weight for s in self.standards)

    @property
    def score(self):
        total = self.applicable_weight
        return None if not total else round(100.0 * self.satisfied_weight / total, 1)

    @property
    def unmet(self):
        return [(s, r) for s in self.standards for r in s.results if r.status == UNMET]


# ---------------------------------------------------------------------------
# Bulk data loading
# ---------------------------------------------------------------------------

class _Data:
    """Everything the requirements need, for a set of customers, loaded
    lazily per source in bulk."""

    def __init__(self, org_ids, standards):
        self.org_ids = list(org_ids)
        self.standards = standards
        self._cache = {}

    def _get(self, key, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    # -- documents ----------------------------------------------------------
    @property
    def documents(self):
        """{org_id: [doc dict]} — published, non-archived, non-draft,
        non-template documents owned by the customer."""
        def load():
            from django.contrib.auth import get_user_model
            from docs.models import Document
            base = Document.objects.filter(
                organization_id__in=self.org_ids, is_published=True,
                is_archived=False, is_draft=False, is_template=False)
            rows = list(base.values(
                'id', 'organization_id', 'title', 'slug', 'owner_id',
                'category__name', 'category__slug',
                'last_reviewed_at', 'updated_at', 'published_at'))
            tags = defaultdict(set)
            for t in Document.tags.through.objects.filter(
                    document__in=base).values('document_id', 'tag__name', 'tag__slug'):
                tags[t['document_id']].update(
                    {(t['tag__name'] or '').lower(), (t['tag__slug'] or '').lower()})
            owner_ids = {r['owner_id'] for r in rows if r['owner_id']}
            owners = get_user_model().objects.in_bulk(owner_ids) if owner_ids else {}
            out = defaultdict(list)
            for r in rows:
                r['tags'] = tags.get(r['id'], set())
                r['owner'] = owners.get(r['owner_id'])
                out[r['organization_id']].append(r)
            return out
        return self._get('documents', load)

    @property
    def document_ids(self):
        """{org_id: set(doc ids)} — every non-archived document, for
        resolving relationship ends."""
        def load():
            from docs.models import Document
            out = defaultdict(set)
            for doc_id, org_id in Document.objects.filter(
                    organization_id__in=self.org_ids, is_archived=False
            ).values_list('id', 'organization_id'):
                out[org_id].add(doc_id)
            return out
        return self._get('document_ids', load)

    # -- contacts -----------------------------------------------------------
    @property
    def contacts(self):
        def load():
            from assets.models import Contact
            out = defaultdict(list)
            for c in Contact.objects.filter(organization_id__in=self.org_ids).values(
                    'id', 'organization_id', 'first_name', 'last_name', 'title'):
                out[c['organization_id']].append(c)
            return out
        return self._get('contacts', load)

    # -- vault metadata (never secrets) -------------------------------------
    @property
    def credentials(self):
        def load():
            from vault.models import Password
            base = Password.objects.filter(
                organization_id__in=self.org_ids, is_personal=False)
            tags = defaultdict(set)
            for t in Password.tags.through.objects.filter(password__in=base).values(
                    'password_id', 'tag__name', 'tag__slug'):
                tags[t['password_id']].update(
                    {(t['tag__name'] or '').lower(), (t['tag__slug'] or '').lower()})
            out = defaultdict(list)
            # Only id / org / title: the encrypted columns are never selected.
            for p in base.values('id', 'organization_id', 'title'):
                p['tags'] = tags.get(p['id'], set())
                out[p['organization_id']].append(p)
            return out
        return self._get('credentials', load)

    # -- assets -------------------------------------------------------------
    def _asset_needs(self):
        """(asset types needed or None for all, extra columns) across the
        active asset requirements."""
        types, columns, all_types = set(), set(), False
        for s in self.standards:
            for req in s.requirements.all():
                if req.kind not in (R.KIND_ASSET_FIELDS, R.KIND_RELATIONSHIP_PRESENT):
                    continue
                t = _asset_type_for(req, s)
                if t:
                    types.add(t)
                else:
                    all_types = True
                if req.kind == R.KIND_ASSET_FIELDS:
                    columns.update(asset_field_column(f) for f in req.params.get('fields', []))
        return (None if all_types else types), columns

    @property
    def assets(self):
        """{org_id: [asset dict]} for the asset types the requirements use."""
        def load():
            from assets.models import Asset
            types, columns = self._asset_needs()
            qs = Asset.objects.filter(organization_id__in=self.org_ids)
            if types is not None:
                qs = qs.filter(asset_type__in=types)
            cols = {'id', 'organization_id', 'name', 'asset_type', 'primary_contact_id',
                    'profile_document_id', 'ai_document_id'} | columns
            out = defaultdict(list)
            for a in qs.values(*sorted(cols)):
                out[a['organization_id']].append(a)
            return out
        return self._get('assets', load)

    @property
    def asset_types_present(self):
        """{org_id: set(asset_type)} — for asset-type scoped standards."""
        def load():
            from assets.models import Asset
            out = defaultdict(set)
            for org_id, t in Asset.objects.filter(
                    organization_id__in=self.org_ids).values_list(
                    'organization_id', 'asset_type').distinct():
                out[org_id].add(t)
            return out
        return self._get('asset_types_present', load)

    @property
    def asset_links(self):
        """{asset_id: {'document', 'contact'}} — kinds an asset is linked to
        through a live Relationship (either direction)."""
        def load():
            from assets.models import Relationship
            out = defaultdict(set)
            rows = Relationship.objects.filter(organization_id__in=self.org_ids).filter(
                Q(source_type='asset') | Q(target_type='asset')).values(
                'organization_id', 'source_type', 'source_id', 'target_type', 'target_id')
            for r in rows:
                org = r['organization_id']
                for a_side, other in (('source', 'target'), ('target', 'source')):
                    if r[f'{a_side}_type'] != 'asset':
                        continue
                    kind, other_id = r[f'{other}_type'], r[f'{other}_id']
                    if kind == 'document' and other_id in self.document_ids.get(org, ()):
                        out[r[f'{a_side}_id']].add('document')
                    elif kind == 'contact' and other_id in self._contact_ids(org):
                        out[r[f'{a_side}_id']].add('contact')
            return out
        return self._get('asset_links', load)

    def _contact_ids(self, org_id):
        key = ('contact_ids', org_id)
        if key not in self._cache:
            self._cache[key] = {c['id'] for c in self.contacts.get(org_id, ())}
        return self._cache[key]

    # -- exceptions ---------------------------------------------------------
    def exceptions(self, now):
        def load():
            out = {}
            qs = StandardException.objects.active(now).filter(
                organization_id__in=self.org_ids,
                standard__in=[s.pk for s in self.standards])
            for e in qs.order_by('created_at'):
                out[(e.organization_id, e.standard_id, e.requirement_id)] = e
            return out
        return self._get('exceptions', load)


def _asset_type_for(req, standard):
    t = (req.params or {}).get('asset_type')
    if t:
        return t
    if standard.scope == DocumentationStandard.SCOPE_ASSET_TYPE:
        return standard.scope_value
    return ''


# ---------------------------------------------------------------------------
# Wording helpers
# ---------------------------------------------------------------------------

def _doc_criteria(params):
    parts = []
    if params.get('tag'):
        parts.append(f'tagged "{params["tag"]}"')
    if params.get('category'):
        parts.append(f'in category "{params["category"]}"')
    if params.get('title_contains'):
        alts = split_alternatives(params['title_contains'])
        parts.append('titled like ' + ' or '.join(f'"{a}"' for a in alts))
    return ', '.join(parts)


def _why(req):
    d = (req.description or '').strip()
    return f' Why it matters: {d}' if d else ''


def _plural(n, word, plural=None):
    return f'{n} {word if n == 1 else (plural or word + "s")}'


def _asset_type_label(t):
    if not t:
        return ''
    from assets.models import Asset
    return dict(Asset.ASSET_TYPES).get(t, t)


def _days_ago(dt, now):
    return max(0, (now - dt).days)


def _matches_text(text, pattern):
    text = (text or '').lower()
    return any(a.lower() in text for a in split_alternatives(pattern))


def _doc_matches(doc, params):
    if params.get('tag') and params['tag'].lower() not in doc['tags']:
        return False
    if params.get('category'):
        want = params['category'].lower()
        if want not in {(doc['category__name'] or '').lower(), (doc['category__slug'] or '').lower()}:
            return False
    if params.get('title_contains') and not _matches_text(doc['title'], params['title_contains']):
        return False
    return True


def _doc_record(doc):
    return Record('document', doc['id'], doc['title'],
                  reverse('docs:document_detail', kwargs={'slug': doc['slug']}))


def _doc_fix(req):
    p = req.params
    alts = split_alternatives(p.get('title_contains', ''))
    q = {'title': alts[0] if alts else req.title}
    if p.get('category'):
        q['category'] = p['category']
    if p.get('tag'):
        q['tags'] = p['tag']
    return Fix('Create the document', reverse('docs:document_create') + '?' + urlencode(q))


# ---------------------------------------------------------------------------
# Requirement checks — each returns (status, explanation, records, fix, owner)
# ---------------------------------------------------------------------------

def _check_document_exists(req, std, org, data, now):
    docs = [d for d in data.documents.get(org.pk, ()) if _doc_matches(d, req.params)]
    crit = _doc_criteria(req.params)
    if docs:
        return (MET, f'Found {_plural(len(docs), "published document")} {crit}.',
                [_doc_record(d) for d in docs], None, docs[0]['owner'])
    return (UNMET, f'No published document {crit} exists for {org.name}.{_why(req)}',
            [], _doc_fix(req), None)


def _fresh_anchor(doc, basis):
    if basis == 'reviewed':
        return doc['last_reviewed_at']
    stamps = [s for s in (doc['last_reviewed_at'], doc['updated_at']) if s]
    return max(stamps) if stamps else None


def _check_document_fresh(req, std, org, data, now):
    p = req.params
    docs = [d for d in data.documents.get(org.pk, ()) if _doc_matches(d, p)]
    crit = _doc_criteria(p)
    limit = p['max_age_days']
    verb = 'reviewed' if p.get('basis') == 'reviewed' else 'reviewed or updated'
    if not docs:
        return (UNMET, f'No published document {crit} exists, so there is nothing '
                       f'{verb} in the last {limit} days.{_why(req)}',
                [], _doc_fix(req), None)
    cutoff = now - timedelta(days=limit)
    dated = sorted(((_fresh_anchor(d, p.get('basis')), d) for d in docs),
                   key=lambda x: (x[0] is not None, x[0] or now), reverse=True)
    newest_at, newest = dated[0]
    rec = _doc_record(newest)
    if newest_at and newest_at >= cutoff:
        return (MET, f'"{newest["title"]}" was {verb} {_plural(_days_ago(newest_at, now), "day")} '
                     f'ago (limit {limit} days).', [rec], None, newest['owner'])
    if newest_at is None:
        msg = f'"{newest["title"]}" has never been reviewed (limit {limit} days).'
    else:
        msg = (f'The most recent matching document, "{newest["title"]}", was last {verb} '
               f'{_plural(_days_ago(newest_at, now), "day")} ago; the limit is {limit} days.')
    return (UNMET, msg + _why(req), [rec],
            Fix('Review the document', rec.url), newest['owner'])


def _check_document_owner(req, std, org, data, now):
    docs = [d for d in data.documents.get(org.pk, ()) if _doc_matches(d, req.params)]
    crit = _doc_criteria(req.params)
    if not docs:
        return (UNMET, f'No published document {crit} exists, so nobody owns it.{_why(req)}',
                [], _doc_fix(req), None)
    orphans = [d for d in docs if not d['owner_id']]
    if not orphans:
        return (MET, f'{"The matching document has" if len(docs) == 1 else f"All {len(docs)} matching documents have"} '
                     f'an owner.', [_doc_record(d) for d in docs], None, docs[0]['owner'])
    titles = ', '.join(f'"{d["title"]}"' for d in orphans[:5])
    return (UNMET, f'{len(orphans)} of {_plural(len(docs), "matching document")} '
                   f'{"has" if len(orphans) == 1 else "have"} no owner: {titles}.{_why(req)}',
            [_doc_record(d) for d in orphans],
            Fix('Assign an owner', reverse('docs:document_edit', kwargs={'slug': orphans[0]['slug']})),
            None)


def _assets_in_scope(req, std, org, data):
    t = _asset_type_for(req, std)
    assets = data.assets.get(org.pk, ())
    return t, [a for a in assets if not t or a['asset_type'] == t]


def _is_empty(v):
    return v is None or v == '' or v == [] or v == {}


def _check_asset_fields(req, std, org, data, now):
    t, assets = _assets_in_scope(req, std, org, data)
    noun = f'{_asset_type_label(t)} asset' if t else 'asset'
    if not assets:
        return (NOT_APPLICABLE, f'{org.name} has no {noun}s on record, so this does not apply.',
                [], None, None)
    labels = dict(asset_field_choices())
    fields = req.params['fields']
    missing = []
    for a in assets:
        gaps = [f for f in fields if _is_empty(a.get(asset_field_column(f)))]
        if gaps:
            missing.append((a, gaps))
    wanted = ', '.join(labels.get(f, f).lower() for f in fields)
    if not missing:
        return (MET, f'All {_plural(len(assets), noun)} have {wanted} filled in.', [], None, None)
    records = [Record('asset', a['id'], a['name'],
                      reverse('assets:asset_edit', kwargs={'pk': a['id']}),
                      'missing ' + ', '.join(labels.get(f, f).lower() for f in gaps))
               for a, gaps in missing]
    return (UNMET, f'{len(missing)} of {_plural(len(assets), noun)} '
                   f'{"is" if len(missing) == 1 else "are"} missing some of: {wanted}.{_why(req)}',
            records, Fix('Fill in the asset', records[0].url), None)


def _check_contact_role(req, std, org, data, now):
    p = req.params
    found = [c for c in data.contacts.get(org.pk, ()) if _matches_text(c['title'], p['title_contains'])]
    need = p.get('min_count', 1)
    alts = ' or '.join(f'"{a}"' for a in split_alternatives(p['title_contains']))
    records = [Record('contact', c['id'], f'{c["first_name"]} {c["last_name"]}'.strip(),
                      reverse('assets:contact_detail', kwargs={'pk': c['id']}), c['title'])
               for c in found]
    if len(found) >= need:
        return (MET, f'{_plural(len(found), "contact")} with a title like {alts}.',
                records, None, None)
    have = 'no contact' if not found else f'only {_plural(len(found), "contact")}'
    return (UNMET, f'{org.name} has {have} with a title like {alts}; '
                   f'{need} needed.{_why(req)}', records,
            Fix('Add the contact', reverse('assets:contact_create') + '?' +
                urlencode({'title': split_alternatives(p['title_contains'])[0]})), None)


def _check_credential_reference(req, std, org, data, now):
    p = req.params
    found = []
    for c in data.credentials.get(org.pk, ()):
        if p.get('title_contains') and not _matches_text(c['title'], p['title_contains']):
            continue
        if p.get('tag') and p['tag'].lower() not in c['tags']:
            continue
        found.append(c)
    parts = []
    if p.get('title_contains'):
        parts.append('titled like ' + ' or '.join(f'"{a}"' for a in split_alternatives(p['title_contains'])))
    if p.get('tag'):
        parts.append(f'tagged "{p["tag"]}"')
    crit = ', '.join(parts)
    records = [Record('credential', c['id'], c['title'],
                      reverse('vault:password_detail', kwargs={'pk': c['id']})) for c in found]
    if found:
        return (MET, f'A vault entry {crit} is on record.', records, None, None)
    q = {}
    alts = split_alternatives(p.get('title_contains', ''))
    if alts:
        q['title'] = alts[0]
    return (UNMET, f'No vault entry {crit} exists for {org.name}.{_why(req)}', [],
            Fix('Add the vault entry', reverse('vault:password_create') + ('?' + urlencode(q) if q else '')),
            None)


def _check_relationship_present(req, std, org, data, now):
    t, assets = _assets_in_scope(req, std, org, data)
    noun = f'{_asset_type_label(t)} asset' if t else 'asset'
    if not assets:
        return (NOT_APPLICABLE, f'{org.name} has no {noun}s on record, so this does not apply.',
                [], None, None)
    kinds = set(req.params.get('target_kinds') or ('document', 'contact'))
    doc_ids = data.document_ids.get(org.pk, set())
    unlinked = []
    for a in assets:
        linked = set(data.asset_links.get(a['id'], ()))
        if a['primary_contact_id']:
            linked.add('contact')
        if (a['profile_document_id'] in doc_ids) or (a['ai_document_id'] in doc_ids):
            linked.add('document')
        if not (linked & kinds):
            unlinked.append(a)
    what = ' or '.join(sorted(kinds))
    if not unlinked:
        return (MET, f'All {_plural(len(assets), noun)} are linked to a {what}.', [], None, None)
    records = [Record('asset', a['id'], a['name'], reverse('assets:asset_detail', kwargs={'pk': a['id']}))
               for a in unlinked]
    first = unlinked[0]
    return (UNMET, f'{len(unlinked)} of {_plural(len(assets), noun)} '
                   f'{"is" if len(unlinked) == 1 else "are"} not linked to any {what}.{_why(req)}',
            records,
            Fix('Link it', reverse('assets:relationship_create') + '?' +
                urlencode({'source_type': 'asset', 'source_id': first['id']})), None)


CHECKS = {
    R.KIND_DOCUMENT_EXISTS: _check_document_exists,
    R.KIND_DOCUMENT_FRESH: _check_document_fresh,
    R.KIND_DOCUMENT_OWNER: _check_document_owner,
    R.KIND_ASSET_FIELDS: _check_asset_fields,
    R.KIND_CONTACT_ROLE: _check_contact_role,
    R.KIND_CREDENTIAL_REFERENCE: _check_credential_reference,
    R.KIND_RELATIONSHIP_PRESENT: _check_relationship_present,
}


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def active_standards():
    return list(DocumentationStandard.objects.filter(is_active=True)
                .prefetch_related('requirements').order_by('name'))


def standard_applies(standard, org, data):
    if standard.scope == DocumentationStandard.SCOPE_ORG_TYPE:
        return (org.organization_type or '') == standard.scope_value
    if standard.scope == DocumentationStandard.SCOPE_ASSET_TYPE:
        return standard.scope_value in data.asset_types_present.get(org.pk, ())
    return True


def evaluate_many(orgs, standards=None, now=None):
    """Score every customer in `orgs` against `standards` (default: every
    active standard). Returns {org_id: OrgReadiness}."""
    orgs = list(orgs)
    now = now or timezone.now()
    if standards is None:
        standards = active_standards()
    data = _Data([o.pk for o in orgs], standards)
    exceptions = data.exceptions(now) if standards and orgs else {}
    out = {}
    for org in orgs:
        readiness = OrgReadiness(org)
        for std in standards:
            if not standard_applies(std, org, data):
                continue
            sres = StandardResult(std)
            whole = exceptions.get((org.pk, std.pk, None))
            for req in std.requirements.all():
                status, explanation, records, fix, owner = CHECKS[req.kind](req, std, org, data, now)
                exc = None
                if status == UNMET:
                    exc = exceptions.get((org.pk, std.pk, req.pk)) or whole
                    if exc is not None:
                        status = EXCEPTED
                        until = (f' until {exc.expires_at:%Y-%m-%d}' if exc.expires_at else '')
                        explanation = f'{explanation} Accepted exception{until}: {exc.reason}'
                        fix = None
                sres.results.append(RequirementResult(
                    requirement=req, status=status, weight=req.weight,
                    explanation=explanation, records=records, fix=fix,
                    owner=owner, exception=exc))
            readiness.standards.append(sres)
        out[org.pk] = readiness
    return out


def evaluate(org, standards=None, now=None):
    """Score one customer. See module docstring."""
    return evaluate_many([org], standards=standards, now=now)[org.pk]
