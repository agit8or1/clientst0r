"""Creating Office files: blank, from a template, copies and conversions.

Every function creates the target row with its organization first (so the
normal permission rules apply to it from the start), then stores revision 1
through office.storage, then returns the Target. Nothing is opened in an
editor before both steps succeed; if storing fails the empty row is removed.
"""
from __future__ import annotations

from pathlib import Path

from django.core.exceptions import PermissionDenied

from . import audit, formats, storage, targets

BLANK_DIR = Path(__file__).resolve().parent / 'templates_files'
NEW_FORMATS = ('docx', 'xlsx', 'pptx')
FORMAT_LABELS = {'docx': 'Word document', 'xlsx': 'Excel workbook', 'pptx': 'PowerPoint presentation'}


def blank_bytes(fmt) -> bytes:
    if fmt not in NEW_FORMATS:
        raise ValueError(f'unsupported format {fmt!r}')
    return (BLANK_DIR / f'blank.{fmt}').read_bytes()


def _perm(user, org, flag):
    from accounts.permission_utils import has_perm_for_org
    return bool(user and user.is_authenticated and user.is_active
                and has_perm_for_org(user, getattr(org, 'pk', org), flag))


def can_create_document(user, org) -> bool:
    return org is not None and _perm(user, org, 'docs_create')


def can_create_attachment(user, org) -> bool:
    return org is not None and _perm(user, org, 'files_upload')


def filename_for(title, ext) -> str:
    title = (title or '').strip() or 'Untitled'
    if formats.extension(title) == ext:
        title = title[:-(len(ext) + 1)] or 'Untitled'
    return storage.safe_filename(f'{title}.{ext}', fallback='Untitled')


def _store_or_discard(target, data, user, source, event, request, description, extra=None):
    try:
        rev = storage.store_initial(target, data, user=user, source=source,
                                    original_name=target.filename)
    except Exception:
        type(target.obj)._base_manager.filter(pk=target.pk).delete()
        raise
    target.refresh()
    audit.log(event, user=user, target=target, request=request, description=description,
              extra={'revision': rev.revision_number, 'sha256': rev.sha256, **(extra or {})})
    return target


def new_document(org, fmt, title, user, *, request=None, category=None):
    if not can_create_document(user, org):
        raise PermissionDenied('You cannot create documents for this organization.')
    name = filename_for(title, fmt)
    target = targets.create_document(org, name, user, category=category)
    return _store_or_discard(target, blank_bytes(fmt), user, 'create', 'create', request,
                             f'Created {FORMAT_LABELS[fmt].lower()} {name}')


def new_attachment(org, entity_type, entity_id, fmt, title, user, *, request=None):
    if not can_create_attachment(user, org):
        raise PermissionDenied('You cannot add files for this organization.')
    name = filename_for(title, fmt)
    target = targets.create_attachment(org, entity_type, entity_id, name, user)
    return _store_or_discard(target, blank_bytes(fmt), user, 'create', 'create', request,
                             f'Created {FORMAT_LABELS[fmt].lower()} {name} on '
                             f'{entity_type} #{entity_id}')


def template_document_bytes(template_target):
    rev = storage.ensure_current(template_target)
    if rev is None:
        raise storage.StorageError('The template has no content.')
    with storage.open_revision(rev) as fh:
        data = fh.read()
    ext = template_target.extension
    if ext in formats.TEMPLATE:
        return formats.template_to_document(data, ext), formats.EDITABLE_FOR_KIND[formats.TEMPLATE[ext]]
    return data, ext


def from_template(template_target, org, title, user, *, request=None):
    if template_target.obj.purpose != 'template' or not template_target.obj.is_active \
            or not template_target.can_view(user):
        raise PermissionDenied('Template not available.')
    if template_target.organization_id not in (None, getattr(org, 'pk', org)):
        raise PermissionDenied('Template not available.')
    if not can_create_document(user, org):
        raise PermissionDenied('You cannot create documents for this organization.')
    data, ext = template_document_bytes(template_target)
    name = filename_for(title or template_target.filename.rsplit('.', 1)[0], ext)
    target = targets.create_document(org, name, user)
    return _store_or_discard(target, data, user, 'copy', 'create', request,
                             f'Created {name} from template {template_target.filename}',
                             {'template': template_target.pk})


def can_copy(target, user) -> bool:
    if not target.can_view(user):
        return False
    if target.kind == 'document':
        return can_create_document(user, target.organization_id)
    return target.can_edit(user)


def copy_name(target):
    name = target.filename
    ext = formats.extension(name)
    stem = name[:-(len(ext) + 1)] if ext else name
    return storage.safe_filename(f'{stem} (copy).{ext}' if ext else f'{stem} (copy)')


def make_copy(target, user, *, new_name=None, request=None):
    if not can_copy(target, user):
        raise PermissionDenied('Not allowed')
    rev = storage.ensure_current(target, user)
    if rev is None:
        raise storage.StorageError('The file has no content yet.')
    name = storage.safe_filename(new_name) if new_name else copy_name(target)
    if formats.extension(name) != target.extension:
        name = filename_for(name, target.extension)
    copy = target.create_copy(name, user)
    with storage.open_revision(rev) as fh:
        data = fh.read()
    return _store_or_discard(copy, data, user, 'copy', 'copy', request,
                             f'Saved a copy of {target.filename} as {name}',
                             {'source_target': f'{target.code}:{target.pk}',
                              'source_revision': rev.revision_number})


def convert_to_copy(target, user, av, *, request=None):
    """Legacy / macro file -> a new copy in the matching OOXML format, through
    the provider's conversion. The original is never modified."""
    if not av.can_convert or not can_copy(target, user):
        raise PermissionDenied('Conversion is not available.')
    dest = formats.conversion_target(target.filename)
    rev = storage.ensure_current(target, user)
    data = av.provider.convert(av.instance, rev, dest, user=user)
    stem = target.filename[:-(len(target.extension) + 1)]
    copy = target.create_copy(filename_for(stem, dest), user)
    return _store_or_discard(copy, data, user, 'convert', 'convert', request,
                             f'Converted {target.filename} to a new .{dest} copy',
                             {'source_target': f'{target.code}:{target.pk}',
                              'source_revision': rev.revision_number,
                              'instance': av.instance.pk})
