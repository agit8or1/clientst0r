"""
Who may publish, edit and own documents.

Org documents use the per-customer role flags (`docs_edit`, `docs_publish`)
on the document's own organization, the way the rest of the app reads them
(`accounts.permission_utils.has_perm_for_org`). Global KB articles belong to
no customer — their `organization` is only a placeholder — so they use the
KB flags (`kb_edit_articles`, `kb_publish_articles`) with the same reach the
global KB views already grant.
"""
from accounts.permission_utils import has_perm_for_org, orgs_with_perm, user_has_perm

ORG_PERMS = {'edit': 'docs_edit', 'publish': 'docs_publish'}
KB_PERMS = {'edit': 'kb_edit_articles', 'publish': 'kb_publish_articles'}


def _django_staff_without_role(user):
    """Django `is_staff` users who are not profile-type staff have no global
    role template to consult; like MSP staff with no global role, they have
    always had full reach (`require_write` passes them everywhere)."""
    if not user.is_staff:
        return False
    profile = getattr(user, 'profile', None)
    return not (profile is not None and profile.is_staff_user())


def _kb_perm(user, perm):
    """Global KB reach: superusers, MSP staff whose global role grants it (or
    who have no global role), or MSP staff with a membership whose role
    grants it — the same reach `require_kb_perm` gives the global KB views.
    Customer users never reach the global KB (v3.17.625)."""
    if orgs_with_perm(user, perm) is None:
        return True
    from psa.visibility import is_msp_staff
    if not is_msp_staff(user):
        return False
    return user_has_perm(user, perm)


def _doc_perm(user, document, action):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if _django_staff_without_role(user):
        return True
    if document.is_global:
        return _kb_perm(user, KB_PERMS[action])
    return has_perm_for_org(user, document.organization_id, ORG_PERMS[action])


def can_publish(user, document):
    """Publish, approve or reject `document`."""
    return _doc_perm(user, document, 'publish')


def can_edit(user, document):
    """Edit, restore a version of, or (un)archive `document`."""
    return _doc_perm(user, document, 'edit')


def can_publish_in_org(user, organization):
    """Publish a new org document in `organization` (uploads / imports)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if _django_staff_without_role(user):
        return True
    return has_perm_for_org(user, organization, 'docs_publish')


def eligible_owners(organization=None, *, include_org_members=True):
    """Users who may own a document: MSP staff, plus active members of the
    document's organization (none for a global KB article)."""
    from django.contrib.auth.models import User
    from django.db.models import Q

    q = Q(is_superuser=True) | Q(is_staff=True) | Q(profile__user_type='staff')
    if include_org_members and organization is not None:
        q |= Q(memberships__organization=organization, memberships__is_active=True)
    return User.objects.filter(is_active=True).filter(q).distinct().order_by('username')


def apply_publish_rules(document, user, *, requested_publish, was_live):
    """Decide a document's publish state after a create/edit form save.

    Returns a user-facing note when the requested state was not granted,
    otherwise None. Rules:
      * Templates are not reader-facing; untouched here.
      * `requires_approval`: every edit takes the document offline into a
        draft; it goes live only through submit-for-review -> approve.
      * With publish permission, the "Published" checkbox is honoured.
      * Without it: editing a live document keeps it live (docs_edit covers
        changing live content), anything else saves as a draft.
    """
    if document.is_template:
        return None
    if document.requires_approval:
        document.is_published = False
        if document.is_draft:
            return 'Saved. The document stays in the approval queue.'
        if requested_publish or was_live:
            return ('This document requires approval: your changes were saved '
                    'as a draft. Submit it for review to publish.')
        return None
    if can_publish(user, document):
        if requested_publish is not None:
            document.is_published = bool(requested_publish)
        if document.is_published:
            document.is_draft = False
        return None
    if was_live:
        document.is_published = True
        return None
    document.is_published = False
    if document.is_draft:
        # Already submitted; it stays in the approval queue.
        return None
    return ('Saved as a draft. You do not have permission to publish — '
            'submit it for review when it is ready.')


# ---------------------------------------------------------------------------
# Customer users and internal documentation
# ---------------------------------------------------------------------------
# Organizations are the MSP's customers. MSP technicians (psa.visibility
# .is_msp_staff) see every document their role reaches. Anyone else with a
# membership is a *customer user*, and gets the same rule as the customer
# portal and as tickets (v3.17.600): never internal-only documentation.
#
# For a customer user a document is visible when
#   * staff marked it "Visible in customer portal" (`is_client_visible`), or
#   * a customer-side user wrote it (`created_by` is not MSP staff) — their
#     own organization's content was never internal to the MSP;
# and never when it is a global KB article (the global KB is staff-only
# since v3.17.625; its rows carry a placeholder organization). Internal
# blocks inside a visible article are stripped (`body_html_for`).

def is_customer_user(user):
    from psa.visibility import is_msp_staff
    return not is_msp_staff(user)


def customer_document_q(prefix=''):
    """Q for documents a customer user may see (see above)."""
    from django.contrib.auth.models import User
    from django.db.models import Q
    from psa.visibility import msp_staff_q
    staff_ids = User.objects.filter(msp_staff_q()).values('pk')
    authored_by_customer = (Q(**{f'{prefix}created_by__isnull': False})
                            & ~Q(**{f'{prefix}created_by__in': staff_ids}))
    return ((Q(**{f'{prefix}is_client_visible': True}) | authored_by_customer)
            & Q(**{f'{prefix}is_global': False}))


def visible_documents(qs, user):
    """Narrow a Document queryset to what `user` may see as a reader. MSP
    staff are unchanged (their org / flag scoping is applied by the caller)."""
    if not is_customer_user(user):
        return qs
    return qs.filter(customer_document_q())


def customer_may_see(user, document):
    """Single-row `visible_documents`."""
    if not is_customer_user(user):
        return True
    if document.is_global:
        return False
    if document.is_client_visible:
        return True
    author = document.created_by
    if author is None:
        return False
    from psa.visibility import is_msp_staff
    return not is_msp_staff(author)


def body_html_for(user, document):
    """Rendered body for `user`: customers never get internal-only blocks."""
    if is_customer_user(user):
        return document.render_for_client()
    return document.render_markdown()


def can_delete(user, document):
    """Delete `document`. Org documents need `docs_delete` in the document's
    own customer (before this release `@require_write` — any *_create flag —
    was the only gate, so Editors, whose role has docs_delete off, could
    delete). Global KB articles are deleted by superusers only, as on the
    global KB's own delete page."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if document.is_global:
        return False
    if _django_staff_without_role(user):
        return True
    return has_perm_for_org(user, document.organization_id, 'docs_delete')


def can_create_in_org(user, organization):
    """Create, upload or import a document (or template, diagram) in
    `organization`: `docs_create` there."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or _django_staff_without_role(user):
        return True
    return has_perm_for_org(user, organization, 'docs_create')


def can_edit_in_org(user, organization, action='edit'):
    """`docs_edit` / `docs_delete` in `organization`, for rows without the
    publish life cycle (diagrams, templates)."""
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser or _django_staff_without_role(user):
        return True
    return has_perm_for_org(user, organization, 'docs_delete' if action == 'delete' else 'docs_edit')


def customer_authored(document):
    author = document.created_by
    if author is None:
        return False
    from psa.visibility import is_msp_staff
    return not is_msp_staff(author)


def may_see_full_source(user, document):
    """The raw body (editor, version history, diffs, full exports) includes
    internal-only blocks. Customer users get it only for documents a
    customer-side user wrote; for MSP-written articles they get the
    stripped, rendered copy."""
    if not is_customer_user(user):
        return True
    return not document.is_global and customer_authored(document)


def body_source_for(user, document):
    """What the API returns as `body`: the raw source, or for a customer
    user reading an MSP-written article the rendered customer copy (HTML,
    internal-only blocks removed)."""
    if may_see_full_source(user, document):
        return document.body
    return document.render_for_client()
