"""
Authorized serving of uploaded files (everything under MEDIA_ROOT).

Until v3.17.599 /media/ was either a 404 (native installs: Django's static()
helper is a no-op with DEBUG=False and the host nginx has no /media/ location)
or world-readable (Docker: nginx aliased /media/ straight to the volume). Now
every /media/<path> request lands here:

  1. The path is normalised and must resolve inside MEDIA_ROOT.
  2. The owning row is found by matching the stored file name against
     MEDIA_REGISTRY — one entry per FileField / ImageField in the project.
  3. That entry's rule decides whether the requesting user may read it.
     A file no registered row claims is a 404: fail closed.

Only branding that renders on unauthenticated pages is public. Everything
else needs a login; anonymous requests are sent to the login page *before*
any lookup result is revealed, so the redirect is not an existence oracle.
A logged-in user who may not read a file gets the same 404 as a missing file.

Templates keep using `{{ obj.field.url }}` — the URL is unchanged, only the
thing answering it is.
"""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from django.apps import apps
from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import FieldDoesNotExist
from django.http import FileResponse, Http404, HttpResponseNotModified
from django.utils.http import content_disposition_header, http_date
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_safe
from django.views.static import was_modified_since


# ---------------------------------------------------------------------------
# Who is the user?
# ---------------------------------------------------------------------------

def is_msp_staff(user) -> bool:
    """MSP staff: superuser, Django is_staff, or a STAFF-type profile."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile = getattr(user, 'profile', None)
    check = getattr(profile, 'is_staff_user', None)
    return bool(check()) if callable(check) else False


def _membership_org_ids(user, include_descendants=True) -> set:
    """Customers the user belongs to through an active Membership.

    Cached on the user object, which lives for one request.
    """
    attr = '_media_org_ids_desc' if include_descendants else '_media_org_ids'
    cached = getattr(user, attr, None)
    if cached is not None:
        return cached
    ids = set(user.memberships.filter(
        is_active=True, organization__is_active=True,
    ).values_list('organization_id', flat=True))
    if include_descendants:
        from core.utils import descendant_org_ids
        expanded = set()
        for org_id in ids:
            expanded |= descendant_org_ids(org_id)
        ids = expanded
    setattr(user, attr, ids)
    return ids


def _can_reach_org(user, org_id) -> bool:
    """Staff reach every customer; anyone else needs a membership."""
    if is_msp_staff(user):
        return True
    return org_id is not None and org_id in _membership_org_ids(user)


def _has_perm_somewhere(user, perm) -> bool:
    from accounts.permission_utils import orgs_with_perm
    allowed = orgs_with_perm(user, perm)
    return allowed is None or bool(allowed)


def _has_perm_for_org(user, org_id, perm) -> bool:
    from accounts.permission_utils import has_perm_for_org
    return has_perm_for_org(user, org_id, perm)


# ---------------------------------------------------------------------------
# Per-model rules. Each takes (user, obj) and returns True to allow.
# ---------------------------------------------------------------------------

def _allow_public(user, obj):
    return True


def _staff_only(user, obj):
    return is_msp_staff(user)


def _owner_or_staff(user, obj):
    return obj.user_id == user.pk or is_msp_staff(user)


def _ticket_attachment(user, att):
    """Staff: every ticket (as psa `_scoped_ticket_qs`). Customer users get
    what the portal shows them: a client-visible ticket of a customer they
    belong to, and never an internal attachment or one on an internal note."""
    if is_msp_staff(user):
        return True
    if att.is_internal:
        return False
    if att.comment_id and att.comment.is_internal:
        return False
    ticket = att.ticket
    if not ticket.client_can_view:
        return False
    return ticket.organization_id in _membership_org_ids(user, include_descendants=False)


def _ticket_expense_receipt(user, expense):
    """Expense receipts are MSP-internal financial records."""
    return is_msp_staff(user)


def _document(user, doc, *, template_preview=False):
    org_id = doc.organization_id
    if not doc.is_published or getattr(doc, 'is_draft', False):
        # Unpublished / draft content: staff with docs reach only.
        return is_msp_staff(user) and _has_perm_for_org(user, org_id, 'docs_view')
    if org_id is None:
        if template_preview and doc.is_template:
            # Template thumbnails decorate the "new from template" picker that
            # every docs_view holder sees.
            return _has_perm_somewhere(user, 'docs_view')
        # Global KB: only every-customer reach (has_perm_for_org(None)).
        return _has_perm_for_org(user, None, 'docs_view')
    return _has_perm_for_org(user, org_id, 'docs_view')


def _document_file(user, doc):
    return _document(user, doc)


def _document_preview(user, doc):
    return _document(user, doc, template_preview=True)


def _diagram(user, diagram):
    org_id = diagram.organization_id
    if not diagram.is_published:
        return is_msp_staff(user) and _has_perm_for_org(user, org_id, 'docs_view')
    if diagram.is_global:
        # diagram_detail serves global diagrams to every customer user.
        return _has_perm_somewhere(user, 'docs_view')
    return _has_perm_for_org(user, org_id, 'docs_view')


def _location(user, loc):
    if is_msp_staff(user):
        return True
    mine = _membership_org_ids(user)
    if loc.organization_id is not None and loc.organization_id in mine:
        return True
    return loc.associated_organizations.filter(pk__in=mine).exists()


def _organization_logo(user, org):
    return _can_reach_org(user, org.pk)


def _rack(user, rack):
    return _can_reach_org(user, rack.organization_id)


def _rack_child(user, obj):
    return _rack(user, obj.rack)


def _files_attachment(user, att):
    if not _has_perm_for_org(user, att.organization_id, 'files_view'):
        return False
    if att.entity_type == 'password':
        return _has_perm_for_org(user, att.organization_id, 'vault_view')
    return True


def _generated_report(user, report):
    """Mirrors reports.views.generated_download."""
    from accounts.permission_utils import user_has_perm
    if not user_has_perm(user, 'reports_view_dashboards'):
        return False
    if user.is_superuser:
        return True
    return report.organization_id in _membership_org_ids(user, include_descendants=False)


def _profile_owner_or_staff(user, profile):
    return profile.user_id == user.pk or is_msp_staff(user)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MediaRule:
    model: str                 # "app_label.ModelName"
    field: str
    authorize: Callable
    prefixes: tuple = ()       # upload_to prefixes, for picking candidates fast
    public: bool = False       # served to anonymous visitors
    filename_attr: str = ''    # attribute holding the original upload name


MEDIA_REGISTRY = (
    # PSA
    MediaRule('psa.TicketAttachment', 'file', _ticket_attachment,
              ('psa/',), filename_attr='filename'),
    MediaRule('psa.TicketExpense', 'receipt_file', _ticket_expense_receipt,
              ('psa/expenses/',)),
    # Documents + diagrams
    MediaRule('docs.Document', 'file', _document_file, ('documents/files/',)),
    MediaRule('docs.Document', 'preview_image', _document_preview, ('documents/previews/',)),
    MediaRule('docs.Diagram', 'png_export', _diagram, ('diagrams/png/',)),
    MediaRule('docs.Diagram', 'svg_export', _diagram, ('diagrams/svg/',)),
    MediaRule('docs.Diagram', 'thumbnail', _diagram, ('diagrams/thumbnails/',)),
    # Locations
    MediaRule('locations.Location', 'satellite_image', _location, ('locations/satellite/',)),
    MediaRule('locations.Location', 'street_view_image', _location, ('locations/street/',)),
    MediaRule('locations.Location', 'area_map_image', _location, ('locations/maps/',)),
    MediaRule('locations.Location', 'property_diagram', _location, ('locations/diagrams/',)),
    # Organizations + system branding
    MediaRule('core.Organization', 'logo', _organization_logo, ('organizations/logos/',)),
    MediaRule('core.SystemSetting', 'custom_logo', _allow_public, ('branding/',), public=True),
    MediaRule('core.SystemSetting', 'background_image', _allow_public,
              ('branding/backgrounds/',), public=True),
    MediaRule('core.SystemSetting', 'geoip_map_background_image', _staff_only,
              ('branding/geoip/',)),
    # Users
    MediaRule('accounts.UserProfile', 'avatar', _profile_owner_or_staff, ('avatars/',)),
    MediaRule('accounts.UserProfile', 'background_image', _profile_owner_or_staff,
              ('backgrounds/',)),
    MediaRule('resourcing.UserCertification', 'attachment', _owner_or_staff,
              ('certifications/',)),
    # Generic attachments: <org_id>/<entity_type>/<entity_id>/<uuid>.<ext>
    MediaRule('files.Attachment', 'file', _files_attachment,
              ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9'),
              filename_attr='original_filename'),
    # Imports, racks, reports
    MediaRule('imports.ImportJob', 'source_file', _staff_only, ('imports/',)),
    MediaRule('monitoring.Rack', 'closet_diagram', _rack, ('rack_diagrams/',)),
    MediaRule('monitoring.RackDevice', 'photo', _rack_child, ('rack_devices/',)),
    MediaRule('monitoring.RackResource', 'photo', _rack_child, ('rack_resources/',)),
    MediaRule('reports.GeneratedReport', 'file', _generated_report, ('reports/',)),
)


def _model_for(rule):
    try:
        model = apps.get_model(rule.model)
        model._meta.get_field(rule.field)
    except (LookupError, FieldDoesNotExist):
        return None
    return model


def find_owner(name):
    """(rule, obj) for the first registered row whose field stores `name`.

    Rules whose upload prefix matches are tried first; the rest follow so a
    row saved under an older upload_to is still found. None when unclaimed.
    """
    likely = [r for r in MEDIA_REGISTRY if name.startswith(r.prefixes)]
    rest = [r for r in MEDIA_REGISTRY if r not in likely]
    for rule in likely + rest:
        model = _model_for(rule)
        if model is None:
            continue
        manager = getattr(model, '_base_manager', model.objects)
        obj = manager.filter(**{rule.field: name}).first()
        if obj is not None:
            return rule, obj
    return None, None


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def resolve_under_media_root(name):
    """Absolute Path for a stored name, or Http404 if it escapes MEDIA_ROOT."""
    if not name or '\x00' in name:
        raise Http404('File not found')
    root = Path(settings.MEDIA_ROOT).resolve()
    try:
        full = (root / name).resolve()
        full.relative_to(root)
    except (ValueError, OSError):
        raise Http404('File not found')
    if not full.is_file():
        raise Http404('File not found')
    return full


def stream_file(request, full_path, stored_name, download_name=None, *, public=False):
    """FileResponse with safe type / disposition headers.

    The type comes from the stored name (what is on disk), the disposition
    name from the original upload name when we have one.
    """
    stat = full_path.stat()
    if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'), stat.st_mtime):
        return HttpResponseNotModified()

    from files.views import _delivery_type

    download_name = download_name or posixpath.basename(stored_name)
    content_type, inline = _delivery_type(stored_name)
    is_svg = stored_name.lower().endswith('.svg')
    if is_svg:
        # SVG still renders in <img> (diagram exports), but opened directly it
        # downloads, and the CSP sandbox stops any embedded script.
        content_type = 'image/svg+xml'

    response = FileResponse(open(full_path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(not inline, download_name)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Last-Modified'] = http_date(stat.st_mtime)
    response['Cache-Control'] = 'public, max-age=3600' if public else 'private, max-age=300'
    if not inline:
        response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response


def _normalise(path):
    """Reject anything but a plain relative path; return it canonicalised."""
    if not path or '\x00' in path or '\\' in path or path.startswith('/'):
        return None
    parts = path.split('/')
    if any(p in ('', '.', '..') for p in parts):
        return None
    return posixpath.normpath(path)


@require_safe
@xframe_options_sameorigin   # document_detail embeds PDFs in an iframe
def serve_media(request, path):
    name = _normalise(path)
    if name is None:
        raise Http404('File not found')

    rule, obj = find_owner(name)
    if rule is not None and rule.public:
        return stream_file(request, resolve_under_media_root(name), name, public=True)

    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    if rule is None or not request.user.is_active or not rule.authorize(request.user, obj):
        raise Http404('File not found')

    full = resolve_under_media_root(name)
    download_name = getattr(obj, rule.filename_attr, '') if rule.filename_attr else ''
    return stream_file(request, full, name, download_name or None)
