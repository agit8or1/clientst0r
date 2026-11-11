"""One interface over the four kinds of object an Office file can belong to.

    target = office.targets.target_for(obj)          # from a model instance
    target = office.targets.resolve(kind_code, pk)   # from a URL (or Http404)

A Target answers: who may view it, who may edit it, what its current file is,
how to lock its row, and how to point it at a new stored file. Permission
rules reuse the ones the rest of the app already applies to the same object
(core.media_views for reads, docs.permissions / role flags for writes), so an
Office action never grants more than the page the file lives on.

URL kind codes: ``doc`` (docs.Document), ``att`` (files.Attachment),
``tkt`` (psa.TicketAttachment), ``ofi`` (office.OfficeFile).
"""
from __future__ import annotations

from django.http import Http404
from django.urls import reverse
from django.utils import timezone

from . import formats


def _has_perm_for_org(user, org_id, perm):
    from accounts.permission_utils import has_perm_for_org
    return has_perm_for_org(user, org_id, perm)


def _active(user):
    return bool(user and user.is_authenticated and user.is_active)


class Target:
    kind = ''       # FK field name on FileRevision / EditSession / QuarantinedSave
    code = ''       # URL code
    model_label = ''

    def __init__(self, obj):
        self.obj = obj

    # -- identity -------------------------------------------------------
    @property
    def pk(self):
        return self.obj.pk

    def __eq__(self, other):
        return isinstance(other, Target) and other.kind == self.kind and other.pk == self.pk

    def __hash__(self):
        return hash((self.kind, self.pk))

    def __repr__(self):
        return f'<Target {self.kind}:{self.pk}>'

    @property
    def organization_id(self):
        return self.obj.organization_id

    @property
    def organization(self):
        return self.obj.organization

    def fk(self):
        """Filter kwargs for rows pointing at this target."""
        return {self.kind: self.obj}

    def fk_id(self):
        return {f'{self.kind}_id': self.obj.pk}

    def label(self):
        return f'{self.code}:{self.pk} {self.filename}'[:255]

    # -- the current file -------------------------------------------------
    @property
    def file(self):
        return self.obj.file

    @property
    def filename(self) -> str:
        raise NotImplementedError

    @property
    def extension(self):
        return formats.extension(self.filename)

    @property
    def size(self):
        raise NotImplementedError

    def has_file(self):
        return bool(self.file and self.file.name)

    # -- permissions ------------------------------------------------------
    def can_view(self, user) -> bool:
        raise NotImplementedError

    def can_edit(self, user) -> bool:
        raise NotImplementedError

    # -- writes (called by office.storage only) --------------------------
    def lock(self):
        """Re-read the row with SELECT ... FOR UPDATE. Inside transaction.atomic."""
        manager = getattr(type(self.obj), '_base_manager')
        self.obj = manager.select_for_update().get(pk=self.obj.pk)
        return self

    def refresh(self):
        manager = getattr(type(self.obj), '_base_manager')
        self.obj = manager.get(pk=self.obj.pk)
        return self

    def point_at(self, name, size, mime, user):
        """Make `name` (a stored file) the target's current content. A
        queryset update: no model save(), so no side effects such as the
        Document text snapshot or the Attachment image optimiser."""
        raise NotImplementedError

    def rename(self, new_filename, user):
        raise NotImplementedError

    def create_copy(self, new_filename, user):
        """A new, empty target of the same kind and place (no file yet).
        Returns the new Target. Caller stores revision 1."""
        raise NotImplementedError

    # -- navigation ------------------------------------------------------
    def back_url(self):
        return reverse('office:target_detail', args=[self.code, self.pk])

    def office_url(self, name, *args):
        return reverse(f'office:{name}', args=[self.code, self.pk, *args])


class DocumentTarget(Target):
    kind, code, model_label = 'document', 'doc', 'docs.Document'

    @property
    def filename(self):
        stored = self.obj.file.name if self.obj.file else ''
        ext = formats.extension(stored) or formats.ext_for_mime(self.obj.file_type)
        return f'{self.obj.title}.{ext}' if ext else self.obj.title

    @property
    def size(self):
        return self.obj.file_size or 0

    def can_view(self, user):
        if not _active(user) or self.obj.organization_id is None:
            return False
        from core.media_views import _document
        return bool(_document(user, self.obj))

    def can_edit(self, user):
        from docs.permissions import can_edit
        return self.can_view(user) and can_edit(user, self.obj)

    def point_at(self, name, size, mime, user):
        from docs.models import Document
        Document.objects.filter(pk=self.obj.pk).update(
            file=name, file_size=size, file_type=mime,
            last_modified_by=user, updated_at=timezone.now())
        self.refresh()

    def rename(self, new_filename, user):
        from docs.models import Document
        title = new_filename
        ext = formats.extension(new_filename)
        if ext and ext == self.extension:
            title = new_filename[:-(len(ext) + 1)]
        Document.objects.filter(pk=self.obj.pk).update(
            title=title[:255], last_modified_by=user, updated_at=timezone.now())
        self.refresh()

    def create_copy(self, new_filename, user):
        return create_document(self.obj.organization, new_filename, user,
                               category=self.obj.category)

    def back_url(self):
        from core.org_handoff import with_org
        return with_org(reverse('docs:document_detail', args=[self.obj.slug]),
                        self.obj.organization_id)


class AttachmentTarget(Target):
    kind, code, model_label = 'attachment', 'att', 'files.Attachment'

    @property
    def filename(self):
        return self.obj.original_filename

    @property
    def size(self):
        return self.obj.file_size or 0

    def can_view(self, user):
        if not _active(user):
            return False
        from core.media_views import _files_attachment
        return bool(_files_attachment(user, self.obj))

    def can_edit(self, user):
        if not self.can_view(user):
            return False
        if not _has_perm_for_org(user, self.obj.organization_id, 'files_upload'):
            return False
        if self.obj.entity_type == 'password':
            return _has_perm_for_org(user, self.obj.organization_id, 'vault_edit')
        return True

    def point_at(self, name, size, mime, user):
        from files.models import Attachment
        Attachment.objects.filter(pk=self.obj.pk).update(
            file=name, file_size=size, content_type=mime, updated_at=timezone.now())
        self.refresh()

    def rename(self, new_filename, user):
        from files.models import Attachment
        Attachment.objects.filter(pk=self.obj.pk).update(
            original_filename=new_filename[:255], updated_at=timezone.now())
        self.refresh()

    def create_copy(self, new_filename, user):
        return create_attachment(self.obj.organization, self.obj.entity_type,
                                 self.obj.entity_id, new_filename, user)

    def back_url(self):
        from core.org_handoff import with_org
        a = self.obj
        if a.entity_type == 'asset':
            url = reverse('assets:asset_detail', args=[a.entity_id])
        elif a.entity_type == 'document':
            from docs.models import Document
            doc = Document.objects.filter(pk=a.entity_id, organization_id=a.organization_id).first()
            url = reverse('docs:document_detail', args=[doc.slug]) if doc else reverse('docs:document_list')
        else:
            return super().back_url()
        return with_org(url, a.organization_id)


class TicketAttachmentTarget(Target):
    kind, code, model_label = 'ticket_attachment', 'tkt', 'psa.TicketAttachment'

    @property
    def organization_id(self):
        return self.obj.ticket.organization_id

    @property
    def organization(self):
        return self.obj.ticket.organization

    @property
    def filename(self):
        return self.obj.filename

    @property
    def size(self):
        return self.obj.size_bytes or 0

    def can_view(self, user):
        if not _active(user):
            return False
        from core.media_views import _ticket_attachment
        return bool(_ticket_attachment(user, self.obj))

    def can_edit(self, user):
        # Ticket files are changed by technicians only; customers read them.
        from psa.visibility import is_msp_staff
        return (self.can_view(user) and is_msp_staff(user)
                and _has_perm_for_org(user, self.organization_id, 'files_upload'))

    def point_at(self, name, size, mime, user):
        from psa.models import TicketAttachment
        TicketAttachment.objects.filter(pk=self.obj.pk).update(
            file=name, size_bytes=size, content_type=mime)
        self.refresh()

    def rename(self, new_filename, user):
        from psa.models import TicketAttachment
        TicketAttachment.objects.filter(pk=self.obj.pk).update(filename=new_filename[:255])
        self.refresh()

    def create_copy(self, new_filename, user):
        from psa.models import TicketAttachment
        copy = TicketAttachment.objects.create(
            ticket=self.obj.ticket, uploaded_by=user, file='', filename=new_filename[:255],
            content_type=formats.mime_for(new_filename), size_bytes=0,
            is_internal=self.obj.is_internal)
        return TicketAttachmentTarget(copy)

    def back_url(self):
        from core.org_handoff import with_org
        return with_org(reverse('psa:ticket_detail', args=[self.obj.ticket.ticket_number]),
                        self.organization_id)


class OfficeFileTarget(Target):
    kind, code, model_label = 'office_file', 'ofi', 'office.OfficeFile'

    @property
    def filename(self):
        return self.obj.name

    @property
    def size(self):
        return self.obj.file_size or 0

    def can_view(self, user):
        if not _active(user):
            return False
        f = self.obj
        if f.purpose == 'diagnostic':
            return user.is_superuser
        if not f.is_active and not self.can_edit(user):
            return False
        if f.organization_id is None:
            from accounts.permission_utils import orgs_with_perm
            allowed = orgs_with_perm(user, 'docs_create')
            return allowed is None or bool(allowed)
        return _has_perm_for_org(user, f.organization_id, 'docs_view')

    def can_edit(self, user):
        if not _active(user):
            return False
        f = self.obj
        if user.is_superuser:
            return True
        if f.purpose == 'diagnostic' or f.organization_id is None:
            return False
        return _has_perm_for_org(user, f.organization_id, 'org_manage_settings')

    def point_at(self, name, size, mime, user):
        from .models import OfficeFile
        OfficeFile.objects.filter(pk=self.obj.pk).update(
            file=name, file_size=size, mime=mime, updated_at=timezone.now())
        self.refresh()

    def rename(self, new_filename, user):
        from .models import OfficeFile
        OfficeFile.objects.filter(pk=self.obj.pk).update(name=new_filename[:255],
                                                         updated_at=timezone.now())
        self.refresh()

    def create_copy(self, new_filename, user):
        from .models import OfficeFile
        f = self.obj
        copy = OfficeFile.objects.create(purpose=f.purpose, organization=f.organization,
                                         name=new_filename[:255], created_by=user,
                                         expires_at=f.expires_at)
        return OfficeFileTarget(copy)

    def back_url(self):
        if self.obj.purpose == 'template':
            return reverse('office:template_list')
        return reverse('office:settings')


ADAPTERS = {
    'document': DocumentTarget,
    'attachment': AttachmentTarget,
    'ticket_attachment': TicketAttachmentTarget,
    'office_file': OfficeFileTarget,
}
CODES = {cls.code: cls for cls in ADAPTERS.values()}


def target_for(obj) -> Target:
    label = obj._meta.label
    for cls in ADAPTERS.values():
        if cls.model_label == label:
            return cls(obj)
    raise TypeError(f'{label} is not an Office target')


def target_of(row):
    """The Target a FileRevision / EditSession / QuarantinedSave points at, or None."""
    for kind, cls in ADAPTERS.items():
        if getattr(row, f'{kind}_id', None):
            return cls(getattr(row, kind))
    return None


def _model_for(cls):
    from django.apps import apps
    return apps.get_model(cls.model_label)


def resolve(code, pk) -> Target:
    """Target for a URL kind code + pk; Http404 for unknown kinds or rows.

    Callers still check can_view / can_edit; a failed check must also be a
    404 so another tenant's file is indistinguishable from a missing one.
    """
    cls = CODES.get(code)
    if cls is None:
        raise Http404('Not found')
    model = _model_for(cls)
    qs = model._base_manager.all()
    if cls is TicketAttachmentTarget:
        qs = qs.select_related('ticket')
    obj = qs.filter(pk=pk).first()
    if obj is None:
        raise Http404('Not found')
    if cls is DocumentTarget and (obj.content_type != 'file' or obj.organization_id is None):
        # Office handling covers customer file documents; rich-text documents
        # and global KB articles keep their own editors.
        raise Http404('Not found')
    return cls(obj)


def resolve_for(user, code, pk, *, edit=False) -> Target:
    """`resolve` plus the permission check, both failing as Http404."""
    target = resolve(code, pk)
    if not target.can_view(user) or (edit and not target.can_edit(user)):
        raise Http404('Not found')
    return target


# ---------------------------------------------------------------------------
# Creating new, empty targets (the caller stores revision 1 right after)
# ---------------------------------------------------------------------------

def _unique_slug(org, title):
    from django.utils.text import slugify
    from docs.models import Document
    base = slugify(title)[:200] or 'document'
    slug, n = base, 1
    while Document.objects.filter(organization=org, slug=slug).exists():
        n += 1
        slug = f'{base}-{n}'
    return slug


def create_document(org, filename, user, *, category=None):
    """A new file Document in `org` with the org's publish rules applied."""
    from docs.models import Document
    from docs.permissions import can_publish_in_org
    title = filename
    ext = formats.extension(filename)
    if ext:
        title = filename[:-(len(ext) + 1)] or 'Untitled'
    doc = Document.objects.create(
        organization=org, title=title[:255], slug=_unique_slug(org, title),
        content_type='file', file_type=formats.mime_for(filename), file_size=0,
        category=category, created_by=user, last_modified_by=user,
        is_published=can_publish_in_org(user, org))
    return DocumentTarget(doc)


def create_attachment(org, entity_type, entity_id, filename, user):
    from files.models import Attachment
    att = Attachment(organization=org, entity_type=entity_type, entity_id=entity_id,
                     file='', original_filename=filename[:255], file_size=0,
                     content_type=formats.mime_for(filename), uploaded_by=user)
    # Model.save() only optimises images; an Office file passes straight through.
    att.save()
    return AttachmentTarget(att)
