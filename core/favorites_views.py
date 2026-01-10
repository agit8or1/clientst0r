"""
Favorites views - Universal favoriting system
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from .models import Favorite


@login_required
def favorite_toggle(request, content_type_id, object_id):
    """
    Toggle favorite status for any object (AJAX endpoint).
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
        # Add favorite
        from core.middleware import get_request_organization
        org = get_request_organization(request)

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

    # Group by content type
    favorites_by_type = {}
    for fav in favorites:
        type_name = fav.content_type.model
        if type_name not in favorites_by_type:
            favorites_by_type[type_name] = []
        favorites_by_type[type_name].append(fav)

    return render(request, 'core/favorite_list.html', {
        'favorites_by_type': favorites_by_type,
        'total_count': favorites.count(),
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
