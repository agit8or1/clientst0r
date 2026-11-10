"""Canonical kind -> ClientSt0r model.

Every query here is scoped to ONE organization. ``get`` and ``matches``
never look outside it, so a record of another customer can neither be
matched, updated nor linked to.

Values are compared in a "stored" form (``dump``): what the database holds,
JSON-safe. Secret columns are compared as stored ciphertext; source secrets
as keyed fingerprints.
"""
from __future__ import annotations

import datetime
import decimal

from django.db import models

# kind -> Relationship.source_type/target_type string
RELATIONSHIP_TYPES = {'asset': 'asset', 'contact': 'contact', 'document': 'document',
                      'password': 'password', 'location': 'location'}
PASSWORD_RELATION_TYPES = {'asset', 'document', 'contact'}
ATTACHMENT_ENTITY_TYPES = {'asset', 'document', 'password', 'contact'}

SECRET_COLUMNS = {
    # canonical secret -> (stored column, setter)
    'password': ('encrypted_password', 'set_password'),
    'otp_secret': ('otp_secret', 'set_otp_secret'),
}


def dump(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [dump(v) for v in value]
    return str(value)


def _field(model, name):
    for f in model._meta.concrete_fields:
        if f.attname == name or f.name == name:
            return f
    raise KeyError(f'{model.__name__} has no field {name}')


def norm(model, name, value):
    """Source value -> the form it would be stored (and read back) in."""
    f = _field(model, name)
    if isinstance(f, models.GenericIPAddressField):
        return value or None
    if isinstance(f, (models.CharField, models.TextField)) and not isinstance(f, models.GenericIPAddressField):
        value = '' if value is None else str(value)
        if getattr(f, 'max_length', None):
            value = value[:f.max_length]
        return value
    if isinstance(f, models.BooleanField):
        return bool(value)
    if isinstance(f, models.JSONField):
        return dump(value)
    if value in ('', None):
        return None
    try:
        return dump(f.to_python(value))
    except Exception:
        return None


def current(obj, name):
    return dump(getattr(obj, _field(type(obj), name).attname))


class Spec:
    kind = ''
    app_label = ''
    model_name = ''
    fields = ()           # plain fields written from the source
    editable = ()         # fields an operator may override
    fk_roles = {}         # link role -> FK attname
    required_roles = ()   # link roles without which the record cannot exist
    role_kinds = {}       # link role -> allowed target kinds (None = any relatable)
    org_lookup = 'organization'

    @property
    def model(self):
        from django.apps import apps
        return apps.get_model(self.app_label, self.model_name)

    @property
    def target_model(self):
        return self.model_name

    def scoped(self, org):
        return self.model._base_manager.filter(**{self.org_lookup: org})

    def get(self, org, pk):
        if pk is None:
            return None
        return self.scoped(org).filter(pk=pk).first()

    def prepare(self, org, fields, target_pk=None):
        """Canonical fields -> proposed stored values (plus notes).
        ``target_pk``: the record this source record is already mapped to."""
        out = {}
        for name in self.fields:
            if name in fields:
                out[name] = norm(self.model, name, fields[name])
        return out, []

    def matches(self, org, proposed):
        return []

    def new(self, org, user):
        return self.model(organization=org)

    def label(self, obj):
        for attr in ('title', 'name', 'original_filename', 'ip_address', 'network'):
            v = getattr(obj, attr, None)
            if v:
                return str(v)
        return f'#{obj.pk}'

    def save_new(self, obj, staged, user):
        obj.save()


class LocationSpec(Spec):
    kind, app_label, model_name = 'location', 'locations', 'Location'
    fields = ('name', 'street_address', 'street_address_2', 'city', 'state', 'postal_code',
              'country', 'phone', 'notes', 'is_primary')
    editable = ('name', 'street_address', 'street_address_2', 'city', 'state', 'postal_code',
                'country', 'phone', 'notes')

    def prepare(self, org, fields, target_pk=None):
        out, notes = super().prepare(org, fields)
        if out.get('is_primary') and self.scoped(org).filter(is_primary=True).exclude(pk=target_pk).exists():
            # Location.save() would silently demote the existing primary
            # location - a change to a record the import does not own.
            out['is_primary'] = False
            notes.append('primary flag (customer already has a primary location)')
        return out, notes

    def matches(self, org, p):
        return list(self.scoped(org).filter(name__iexact=p.get('name', ''))[:5])


class ContactSpec(Spec):
    kind, app_label, model_name = 'contact', 'assets', 'Contact'
    fields = ('first_name', 'last_name', 'email', 'phone', 'title', 'notes')
    editable = fields
    role_kinds = {'location': {'location'}}

    def matches(self, org, p):
        qs = self.scoped(org)
        if p.get('email'):
            return list(qs.filter(email__iexact=p['email'])[:5])
        return list(qs.filter(first_name__iexact=p.get('first_name', ''),
                              last_name__iexact=p.get('last_name', ''))[:5])


class AssetSpec(Spec):
    kind, app_label, model_name = 'asset', 'assets', 'Asset'
    fields = ('name', 'asset_type', 'serial_number', 'asset_tag', 'manufacturer', 'model', 'hostname',
              'ip_address', 'mac_address', 'os_name', 'notes', 'custom_fields')
    editable = ('name', 'asset_type', 'serial_number', 'asset_tag', 'manufacturer', 'model',
                'hostname', 'ip_address', 'mac_address', 'os_name', 'notes')
    fk_roles = {'primary_contact': 'primary_contact_id'}
    role_kinds = {'primary_contact': {'contact'}, 'location': {'location'}}

    def matches(self, org, p):
        qs = self.scoped(org)
        if p.get('serial_number'):
            found = list(qs.filter(serial_number=p['serial_number'])[:5])
            if found:
                return found
        return list(qs.filter(name__iexact=p.get('name', ''))[:5])


class NetworkSpec(Spec):
    kind, app_label, model_name = 'network', 'monitoring', 'Subnet'
    fields = ('name', 'network', 'description', 'gateway', 'dns_servers', 'location', 'vlan_id')
    editable = ('name', 'description', 'gateway')
    role_kinds = {'location': {'location'}}

    def prepare(self, org, fields, target_pk=None):
        out, notes = super().prepare(org, fields)
        number = fields.get('_vlan_number')
        if number not in (None, ''):
            from monitoring.models import VLAN
            try:
                vlan = VLAN.objects.filter(organization=org, vlan_id=int(number),
                                           vlan_group__isnull=True).first()
            except (TypeError, ValueError):
                vlan = None
            if vlan:
                out['vlan_id'] = vlan.pk
            else:
                out['_vlan_missing'] = str(number)
        return out, notes

    def matches(self, org, p):
        return list(self.scoped(org).filter(network=p.get('network', ''))[:5])

    def new(self, org, user):
        obj = super().new(org, user)
        obj.dns_servers = []
        return obj


class IPAddressSpec(Spec):
    kind, app_label, model_name = 'ip_address', 'monitoring', 'IPAddress'
    fields = ('ip_address', 'status', 'hostname', 'description', 'notes')
    editable = ('status', 'hostname', 'description', 'notes')
    fk_roles = {'subnet': 'subnet_id', 'asset': 'asset_id'}
    required_roles = ('subnet',)
    role_kinds = {'subnet': {'network'}, 'asset': {'asset'}}
    org_lookup = 'subnet__organization'

    def matches(self, org, p, subnet_id=None):
        if not subnet_id:
            return []
        return list(self.scoped(org).filter(subnet_id=subnet_id, ip_address=p.get('ip_address'))[:5])

    def new(self, org, user):
        return self.model()


class PasswordSpec(Spec):
    kind, app_label, model_name = 'password', 'vault', 'Password'
    fields = ('title', 'username', 'url', 'notes')
    editable = ('title', 'username', 'url')
    role_kinds = {'resource': {'asset', 'document', 'contact', 'location'}}
    secret_fields = ('password', 'otp_secret')

    def scoped(self, org):
        return super().scoped(org).filter(is_personal=False)

    def matches(self, org, p):
        return list(self.scoped(org).filter(title__iexact=p.get('title', ''),
                                            username__iexact=p.get('username', ''))[:5])

    def new(self, org, user):
        return self.model(organization=org, created_by=user)


class DocumentSpec(Spec):
    kind, app_label, model_name = 'document', 'docs', 'Document'
    fields = ('title', 'body', 'content_type')
    editable = ('title',)

    def matches(self, org, p):
        return list(self.scoped(org).filter(title__iexact=p.get('title', ''))[:5])

    def new(self, org, user):
        return self.model(organization=org, created_by=user)

    def save_new(self, obj, staged, user):
        from imports.services.base import BaseImportService
        obj.slug = BaseImportService.unique_document_slug(obj.organization, obj.title)
        obj.save()


class WebsiteSpec(Spec):
    kind, app_label, model_name = 'website', 'monitoring', 'WebsiteMonitor'
    fields = ('name', 'url')
    editable = ('name',)

    def matches(self, org, p):
        return list(self.scoped(org).filter(url=p.get('url', ''))[:5])

    def new(self, org, user):
        # Imported monitors start disabled: the operator decides when
        # ClientSt0r starts polling a customer's site.
        return self.model(organization=org, is_enabled=False)


class RelationSpec(Spec):
    kind, app_label, model_name = 'relation', 'assets', 'Relationship'
    fields = ('relation_type', 'notes')
    editable = ('notes',)
    required_roles = ('from', 'to')
    role_kinds = {'from': set(RELATIONSHIP_TYPES), 'to': set(RELATIONSHIP_TYPES)}

    def matches(self, org, p, ends=None):
        if not ends:
            return []
        (fk, fid), (tk, tid) = ends
        return list(self.scoped(org).filter(
            source_type=RELATIONSHIP_TYPES[fk], source_id=fid,
            target_type=RELATIONSHIP_TYPES[tk], target_id=tid,
            relation_type=p.get('relation_type', 'related'))[:5])


class AttachmentSpec(Spec):
    kind, app_label, model_name = 'attachment', 'files', 'Attachment'
    fields = ('original_filename', 'description')
    editable = ('description',)
    required_roles = ('parent',)
    role_kinds = {'parent': ATTACHMENT_ENTITY_TYPES}

    def matches(self, org, p, parent=None, size=None):
        if not parent:
            return []
        kind, pk = parent
        return list(self.scoped(org).filter(entity_type=kind, entity_id=pk,
                                            original_filename=p.get('original_filename', ''),
                                            file_size=size or 0)[:5])

    def new(self, org, user):
        return self.model(organization=org, uploaded_by=user)


SPECS = {s.kind: s for s in (LocationSpec(), ContactSpec(), AssetSpec(), NetworkSpec(), IPAddressSpec(),
                             PasswordSpec(), DocumentSpec(), WebsiteSpec(), RelationSpec(),
                             AttachmentSpec())}
MODEL_TO_KIND = {s.model_name: s.kind for s in SPECS.values()}
