"""
Favorites views - Universal favoriting system
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST
from .models import Favorite


# What can be favorited, and the role flag that decides whether the user may
# see it. Until the roles & permissions program the toggle accepted any
# content type and id, and the favorites page printed the object's name — so
# a user could read the title of another customer's password, a ticket
# subject or a user name by favoriting a guessed id.
FAVORITABLE = {
    ('vault', 'password'): 'vault_view',
    ('assets', 'asset'): 'assets_view',
    # A client itself: visible when the user may switch to it.
    ('core', 'organization'): None,
}


def _may_see(request, obj):
    """True when the user may see `obj` right now (re-checked on every
    list render, so revoked access drops the entry from the page)."""
    if obj is None:
        return False
    key = (obj._meta.app_label, obj._meta.model_name)
    if key not in FAVORITABLE:
        return False
    perm = FAVORITABLE[key]
    user = request.user
    if key == ('core', 'organization'):
        from core.client_switcher import authorized_organizations
        return authorized_organizations(request).filter(pk=obj.pk).exists()
    if getattr(obj, 'is_personal', False):
        return getattr(obj, 'personal_owner_id', None) == user.pk
    org_id = getattr(obj, 'organization_id', None)
    if org_id is None:
        return False
    from core.tenancy import accessible_org_ids
    from accounts.permission_utils import orgs_with_perm
    reach = accessible_org_ids(request)
    if reach is not None and org_id not in reach:
        return False
    allowed = orgs_with_perm(user, perm)
    return allowed is None or org_id in allowed


@login_required
@require_POST
def favorite_toggle(request, content_type_id, object_id):
    """
    Toggle favorite status for a password or asset (AJAX endpoint). POST
    only; adding needs the object to exist and be visible to the user.
    Removing your own favorite is always allowed.
    """
    content_type = get_object_or_404(ContentType, id=content_type_id)

    # Check if already favorited
    favorite = Favorite.objects.filter(
        user=request.user,
        content_type=content_type,
        object_id=object_id
    ).first()

    if favorite:
        # Remove favorite
        favorite.delete()
        favorited = False
        message = 'Removed from favorites'
    else:
        # Add favorite — only something this user may see. Unknown, foreign
        # and forbidden objects get the same 404.
        model = content_type.model_class()
        obj = model._default_manager.filter(pk=object_id).first() if model else None
        if not _may_see(request, obj):
            raise Http404
        org = obj if model._meta.model_name == 'organization' else obj.organization

        Favorite.objects.create(
            user=request.user,
            organization=org,
            content_type=content_type,
            object_id=object_id
        )
        favorited = True
        message = 'Added to favorites'

    # Return JSON for AJAX or redirect for non-AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'favorited': favorited,
            'message': message
        })
    else:
        messages.success(request, message)
        return redirect(request.META.get('HTTP_REFERER', '/'))


@login_required
def favorite_list(request):
    """
    Show all of user's favorites organized by type.
    """
    favorites = Favorite.objects.filter(
        user=request.user
    ).select_related('content_type').prefetch_related('content_object')

    # Group by content type. Only objects the user may still see are shown:
    # the name of anything else is not printed.
    favorites = [fav for fav in favorites if _may_see(request, fav.content_object)]
    favorites_by_type = {}
    for fav in favorites:
        type_name = fav.content_type.model
        if type_name not in favorites_by_type:
            favorites_by_type[type_name] = []
        favorites_by_type[type_name].append(fav)

    return render(request, 'core/favorite_list.html', {
        'favorites_by_type': favorites_by_type,
        'total_count': len(favorites),
    })


@login_required
def favorite_check(request, content_type_id, object_id):
    """
    Check if object is favorited (AJAX).
    """
    is_favorited = Favorite.objects.filter(
        user=request.user,
        content_type_id=content_type_id,
        object_id=object_id
    ).exists()

    return JsonResponse({
        'favorited': is_favorited
    })
