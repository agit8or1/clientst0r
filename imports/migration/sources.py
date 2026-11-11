"""Staging: fetch ONE source organization into StagedRecord rows.

Nothing here writes outside the plan's own staging tables (and the staged
attachment files). Every record is checked against the requested source
organization on the client side too, so a source API that ignores a filter
parameter can never leak another customer's records into the plan.

Endpoints that fail are recorded on ``plan.unavailable`` with a kind:

    permission     401/403 - the API key may not read it
    api_gap        404/405 - the endpoint does not exist on this source
    not_supported  readable, but ClientSt0r has no mapping for it
    error          anything else
"""
from __future__ import annotations

import hashlib
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from files import upload_rules
from .redact import CONFIDENTIAL_FIELD_TYPES, REDACTED, fingerprint, scrub, sha256_json
from .transport import DownloadRejected, RequestsTransport, SourceUnavailable

logger = logging.getLogger('imports')


def attachment_max_bytes():
    return int(getattr(settings, 'IMPORT_ATTACHMENT_MAX_BYTES', upload_rules.MAX_FILE_SIZE))


def staging_max_bytes():
    return int(getattr(settings, 'IMPORT_STAGING_MAX_BYTES', 1024 * 1024 * 1024))


def record_hash(raw, secrets, blob_sha=''):
    return sha256_json({
        'raw': raw,
        'secrets': {k: fingerprint(v) for k, v in sorted((secrets or {}).items())},
        'blob': blob_sha,
    })


def compute_staging_hash(plan):
    """Recomputed from the staged content itself, not from stored hashes,
    so any change to a staged row (or its file) is detected."""
    rows = []
    for rec in plan.staged.order_by('source_type', 'source_id'):
        blob_sha = (rec.raw.get('_file') or {}).get('sha256', '')
        if rec.blob:
            try:
                with rec.blob.open('rb') as fh:
                    blob_sha = hashlib.sha256(fh.read()).hexdigest()
            except (OSError, ValueError):
                blob_sha = 'missing'
        rows.append([rec.source_type, rec.source_id, record_hash(rec.raw, rec.secret_data, blob_sha)])
    return sha256_json({
        'source_system': plan.source_system,
        'source_account': plan.source_account,
        'source_organization_id': plan.source_organization_id,
        'unavailable': plan.unavailable,
        'records': rows,
    })


class Stager:
    source_system = ''

    def __init__(self, plan, transport=None):
        self.plan = plan
        self.job = plan.import_job
        self.org_sid = str(plan.source_organization_id)
        self.transport = transport or RequestsTransport(self.job.source_url, self.auth_headers())
        self.unavailable = []
        self.records = {}  # (source_type, source_id) -> dict
        self.staged_bytes = 0
        # Called between requests by the background runner: keeps the
        # task lease alive and reports progress; raises if the lease is lost.
        self.heartbeat = lambda message='': None

    # -- helpers ----------------------------------------------------------
    def auth_headers(self):
        raise NotImplementedError

    def gap(self, source_type, kind, reason, count=None):
        entry = {'source_type': source_type, 'kind': kind, 'reason': reason}
        if count is not None:
            entry['count'] = count
        self.unavailable.append(entry)

    def put(self, source_type, raw, secrets=None, name='', blob=None):
        sid = str(raw.get('id'))
        self.records[(source_type, sid)] = {
            'raw': scrub(raw), 'secrets': secrets or {}, 'name': str(name or '')[:255], 'blob': blob}

    def has(self, source_type, source_id):
        return (source_type, str(source_id)) in self.records

    def collect(self, source_type, fn):
        """Run one endpoint, recording it as unavailable instead of failing."""
        self.heartbeat(f'fetching {source_type} ({len(self.records)} records so far)')
        try:
            return fn()
        except SourceUnavailable as exc:
            self.gap(source_type, exc.kind, str(exc))
            return None

    def download(self, url, file_name, declared_type, declared_size):
        """Return (bytes, content_type, '') or (None, '', reason)."""
        cap = attachment_max_bytes()
        reason = upload_rules.check_name(file_name)
        if reason:
            return None, '', reason
        try:
            size = int(declared_size or 0)
        except (TypeError, ValueError):
            size = 0
        if size > cap:
            return None, '', f'file exceeds the {cap // (1024 * 1024)}MB limit'
        if self.staged_bytes + max(size, 0) > staging_max_bytes():
            return None, '', 'staging size limit reached'
        if not url:
            return None, '', 'source did not provide a download URL'
        self.heartbeat(f'downloading attachment {file_name}')
        try:
            content, ctype = self.transport.get_bytes(url, cap)
        except DownloadRejected as exc:
            return None, '', str(exc)
        reason = upload_rules.check_file(file_name, content, declared_type or ctype, max_bytes=cap)
        if reason:
            return None, '', reason
        self.staged_bytes += len(content)
        return content, upload_rules.content_type_for(file_name), ''

    def stage_attachment(self, source_type, att_id, parent_type, parent_id, file_name,
                         declared_type, declared_size, url, description=''):
        content, ctype, reason = self.download(url, file_name, declared_type, declared_size)
        meta = {'file_name': file_name, 'declared_content_type': declared_type or '',
                'content_type': ctype, 'size': len(content) if content is not None else (declared_size or 0),
                'description': description}
        if content is not None:
            meta['sha256'] = hashlib.sha256(content).hexdigest()
        else:
            meta['rejected'] = reason
            meta['rejected_kind'] = 'invalid'
        raw = {'id': str(att_id), '_parent': {'source_type': parent_type, 'source_id': str(parent_id)},
               '_file': meta}
        self.put(source_type, raw, name=file_name, blob=content)

    # -- run --------------------------------------------------------------
    def fetch(self):
        raise NotImplementedError

    def stage(self):
        """Fetch everything, then replace the plan's staging in one transaction."""
        org_name = self.fetch()
        self.heartbeat(f'saving {len(self.records)} staged records')
        plan = self.plan
        with transaction.atomic():
            plan.delete_staged_files()
            plan.items.all().delete()
            plan.staged.all().delete()
            from imports.models import StagedRecord
            for (stype, sid), rec in sorted(self.records.items()):
                blob_sha = (rec['raw'].get('_file') or {}).get('sha256', '')
                row = StagedRecord(
                    plan=plan, source_type=stype, source_id=sid, display_name=rec['name'],
                    raw=rec['raw'], secret_data=rec['secrets'],
                    content_hash=record_hash(rec['raw'], rec['secrets'], blob_sha))
                if rec['blob'] is not None:
                    row.blob.save('staged', ContentFile(rec['blob']), save=False)
                row.save()
            plan.unavailable = self.unavailable
            if org_name:
                plan.source_organization_name = str(org_name)[:255]
            plan.staged_at = timezone.now()
            plan.status = 'staged'
            plan.reviewed_at = None
            plan.reviewed_plan_hash = plan.reviewed_staging_hash = ''
            plan.save()
            plan.staging_hash = compute_staging_hash(plan)
            plan.save(update_fields=['staging_hash'])
        return plan


class ITGlueStager(Stager):
    source_system = 'itglue'

    def auth_headers(self):
        return {'x-api-key': self.job.source_api_key, 'Content-Type': 'application/vnd.api+json',
                'Accept': 'application/vnd.api+json'}

    def paged(self, path, params=None):
        page = 1
        while True:
            q = dict(params or {})
            q.update({'page[number]': page, 'page[size]': 50})
            data = self.transport.get_json(path, q) or {}
            items = data.get('data') or []
            if not items:
                return
            yield from items
            if not ((data.get('links') or {}).get('next') or (data.get('meta') or {}).get('next-page')):
                return
            page += 1

    def ours(self, item):
        """Client-side organization check (never trust the filter alone)."""
        org = (item.get('attributes') or {}).get('organization-id')
        return org in (None, '') or str(org) == self.org_sid

    def collection(self, source_type, path, extra=None):
        params = {'filter[organization_id]': self.org_sid}
        params.update(extra or {})
        out = []
        for item in self.paged(path, params):
            if self.ours(item):
                out.append(item)
        return out

    def fetch(self):
        org = self.transport.get_json(f'/organizations/{self.org_sid}') or {}
        org_name = ((org.get('data') or {}).get('attributes') or {}).get('name', '')

        for stype, path in (('location', '/locations'), ('contact', '/contacts'),
                            ('configuration', '/configurations'), ('document', '/documents')):
            items = self.collect(stype, lambda p=path, s=stype: self.collection(s, p)) or []
            for item in items:
                self.put(stype, item, name=(item.get('attributes') or {}).get('name')
                         or ' '.join(filter(None, [(item.get('attributes') or {}).get('first-name'),
                                                   (item.get('attributes') or {}).get('last-name')])))

        passwords = self.collect('password', lambda: self.collection('password', '/passwords')) or []
        for item in passwords:
            self.stage_password(item)

        self.fetch_flexible_assets()

        # Domains (-> the website / domain expiry tracking model).
        domains = self.collect('domain', lambda: self.collection('domain', '/domains')) or []
        for item in domains:
            self.put('domain', item, name=(item.get('attributes') or {}).get('name'))

        # Related items of configurations (asset relationships).
        for (stype, sid) in [k for k in self.records if k[0] == 'configuration']:
            rel = self.collect('related_item', lambda sid=sid: list(
                self.paged(f'/configurations/{sid}/relationships/related_items')))
            for item in rel or []:
                item = dict(item)
                item['_parent'] = {'source_type': 'configuration', 'source_id': sid}
                self.put('related_item', item, name=(item.get('attributes') or {}).get('destination-name'))
            if rel is None:
                break  # one gap entry is enough; do not hammer a missing endpoint

        # Attachments on configurations, documents, passwords and imported flexible assets.
        paths = {'configuration': 'configurations', 'document': 'documents',
                 'password': 'passwords', 'flexible_asset': 'flexible_assets'}
        for (stype, sid) in sorted([k for k in self.records if k[0] in paths]):
            if stype == 'flexible_asset' and self.records[(stype, sid)]['raw'].get('_skip_attachments'):
                continue
            atts = self.collect('attachment', lambda s=stype, i=sid: list(
                self.paged(f'/{paths[s]}/{i}/relationships/attachments')))
            if atts is None:
                break
            for att in atts:
                a = att.get('attributes') or {}
                self.stage_attachment(
                    'attachment', att.get('id'), stype, sid,
                    a.get('attachment-file-name') or a.get('name') or f"attachment-{att.get('id')}",
                    a.get('attachment-content-type') or '', a.get('attachment-file-size'),
                    a.get('download-url') or a.get('attachment-url') or a.get('url'))
        return org_name

    def stage_password(self, item):
        attrs = dict(item.get('attributes') or {})
        secrets = {}
        if 'password' not in attrs:
            # The list endpoint can omit the value; the show endpoint returns
            # it when the API key may see it.
            try:
                detail = self.transport.get_json(f"/passwords/{item.get('id')}",
                                                 {'show_password': 'true'}) or {}
                attrs.update(((detail.get('data') or {}).get('attributes') or {}))
            except SourceUnavailable as exc:
                logger.info('IT Glue password %s value not readable: %s', item.get('id'), exc.kind)
        if attrs.get('password') not in (None, ''):
            secrets['password'] = str(attrs['password'])
        for key in ('otp-secret', 'otp_secret'):
            if attrs.get(key):
                secrets['otp_secret'] = str(attrs[key])
        raw = dict(item)
        raw['attributes'] = {k: v for k, v in attrs.items() if k not in ('password', 'otp-secret', 'otp_secret')}
        if 'password' not in secrets:
            raw['_value_unreadable'] = 'password value not returned by the source API (permissions)'
        self.put('password', raw, secrets, name=attrs.get('name'))

    def fetch_flexible_assets(self):
        types = self.collect('flexible_asset', lambda: list(self.paged('/flexible_asset_types')))
        if types is None:
            return
        from .normalize import itglue_flexible_kind
        for t in types:
            tname = (t.get('attributes') or {}).get('name', '')
            items = self.collect('flexible_asset', lambda tid=t.get('id'): self.collection(
                'flexible_asset', '/flexible_assets', {'filter[flexible_asset_type_id]': tid}))
            for item in items or []:
                item = dict(item)
                item['_type_name'] = tname
                if itglue_flexible_kind(tname, self.plan.type_overrides or {}) == 'skip':
                    item['_skip_attachments'] = True
                self.put('flexible_asset', item, name=(item.get('attributes') or {}).get('name'))


class HuduStager(Stager):
    source_system = 'hudu'

    def auth_headers(self):
        return {'x-api-key': self.job.source_api_key, 'Content-Type': 'application/json',
                'Accept': 'application/json'}

    def paged(self, path, key, params=None):
        page = 1
        while True:
            q = dict(params or {})
            q.update({'page': page, 'page_size': 100})
            data = self.transport.get_json(path, q) or {}
            items = data.get(key) if isinstance(data, dict) else data
            items = items or []
            if not items:
                return
            yield from items
            if len(items) < 100:
                return
            page += 1

    def ours(self, item):
        return str(item.get('company_id')) == self.org_sid

    def company_collection(self, path, key):
        return [i for i in self.paged(path, key, {'company_id': self.org_sid}) if self.ours(i)]

    def fetch(self):
        company = self.transport.get_json(f'/api/v1/companies/{self.org_sid}') or {}
        company = company.get('company', company)
        org_name = company.get('name', '')
        if any(company.get(k) for k in ('address_line_1', 'city', 'zip')):
            raw = dict(company)
            raw['id'] = self.org_sid
            self.put('company', raw, name=f"{org_name} - main address")

        for stype, path, key in (('asset', '/api/v1/assets', 'assets'),
                                 ('article', '/api/v1/articles', 'articles'),
                                 ('website', '/api/v1/websites', 'websites'),
                                 ('network', '/api/v1/networks', 'networks'),
                                 ('ip_address', '/api/v1/ip_addresses', 'ip_addresses')):
            items = self.collect(stype, lambda p=path, k=key: self.company_collection(p, k)) or []
            for item in items:
                if stype == 'asset':
                    item = self.blank_confidential(item)
                self.put(stype, item, name=item.get('name') or item.get('address') or item.get('url'))

        vlans = None
        if any(self.records[k]['raw'].get('vlan_id') for k in self.records if k[0] == 'network'):
            vlans = self.collect('vlan', lambda: {str(v.get('id')): v.get('vlan_id') for v in
                                                  self.company_collection('/api/v1/vlans', 'vlans')})
        for k in [k for k in self.records if k[0] == 'network']:
            raw = self.records[k]['raw']
            if raw.get('vlan_id') and vlans:
                raw['_vlan_number'] = vlans.get(str(raw['vlan_id']))

        pw = self.collect('asset_password', lambda: self.company_collection(
            '/api/v1/asset_passwords', 'asset_passwords')) or []
        for item in pw:
            item = dict(item)
            secrets = {}
            if item.get('password') not in (None, ''):
                secrets['password'] = str(item['password'])
            if item.get('otp_secret'):
                secrets['otp_secret'] = str(item['otp_secret'])
            item.pop('password', None)
            item.pop('otp_secret', None)
            self.put('asset_password', item, secrets, name=item.get('name'))

        procedures = self.collect('procedure', lambda: self.company_collection(
            '/api/v1/procedures', 'procedures')) or []
        tasks_gap = False
        for proc in procedures:
            proc = dict(proc)
            if not any(isinstance(proc.get(k), list) for k in
                       ('procedure_tasks', 'procedure_tasks_attributes', 'tasks')) and not tasks_gap:
                found = self.collect('procedure_task', lambda pid=proc.get('id'): [
                    t for t in self.paged('/api/v1/procedure_tasks', 'procedure_tasks', {'procedure_id': pid})
                    if str(t.get('procedure_id', pid)) == str(pid)])
                if found is None:
                    tasks_gap = True  # one gap entry is enough
                else:
                    proc['_tasks'] = found
            if tasks_gap and '_tasks' not in proc:
                proc['_tasks_unavailable'] = 'the source did not return the procedure tasks'
            self.put('procedure', proc, name=proc.get('name'))

        # Relations and uploads are account-wide lists: keep only those that
        # touch this company's staged records.
        from .normalize import hudu_type
        rels = self.collect('relation', lambda: list(self.paged('/api/v1/relations', 'relations'))) or []
        for rel in rels:
            ft, tt = hudu_type(rel.get('fromable_type')), hudu_type(rel.get('toable_type'))
            if (ft and self.has(ft, rel.get('fromable_id'))) or (tt and self.has(tt, rel.get('toable_id'))):
                self.put('relation', rel, name=f"{rel.get('fromable_type')} -> {rel.get('toable_type')}")

        uploads = self.collect('upload', lambda: list(self.paged('/api/v1/uploads', 'uploads'))) or []
        for up in uploads:
            ptype = hudu_type(up.get('uploadable_type'))
            if not ptype or not self.has(ptype, up.get('uploadable_id')):
                continue
            name = up.get('name') or f"upload-{up.get('id')}"
            if up.get('ext') and '.' not in name:
                name = f"{name}.{up['ext']}"
            self.stage_attachment('upload', up.get('id'), ptype, up.get('uploadable_id'), name,
                                  up.get('mime') or '', up.get('size'), up.get('url'))
        return org_name

    @staticmethod
    def blank_confidential(item):
        item = dict(item)
        for key in ('fields', 'asset_fields'):
            if isinstance(item.get(key), list):
                out = []
                for f in item[key]:
                    f = dict(f) if isinstance(f, dict) else f
                    if isinstance(f, dict) and str(f.get('field_type') or f.get('type') or '').lower().replace(
                            ' ', '') in CONFIDENTIAL_FIELD_TYPES and f.get('value'):
                        f['value'] = REDACTED
                    out.append(f)
                item[key] = out
        return item


def stager_for(plan, transport=None):
    if plan.source_system == 'itglue':
        return ITGlueStager(plan, transport)
    if plan.source_system == 'hudu':
        return HuduStager(plan, transport)
    raise ValueError('rehearsals support IT Glue and Hudu only')
