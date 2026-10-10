"""
Secure Notes views - Encrypted messaging between users
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from .client_ip import get_client_ip
from .models import SecureNote
from .middleware import get_request_organization

# Wrong-password attempts allowed per note per client within the window.
NOTE_PASSWORD_MAX_FAILURES = 10
NOTE_PASSWORD_WINDOW_SECONDS = 900


def _note_password_ok(request, note, password):
    """Check a note's access password: hashed, constant-time, attempt-limited.

    Notes created before hashing hold the password in plaintext; those are
    compared in constant time and upgraded to a hash on the first success.
    Returns (ok, locked_out).
    """
    from django.contrib.auth.hashers import check_password, identify_hasher, make_password
    from django.core.cache import cache
    from django.utils.crypto import constant_time_compare

    key = f'securenote_pw_fail:{note.pk}:{get_client_ip(request)}'
    if cache.get(key, 0) >= NOTE_PASSWORD_MAX_FAILURES:
        return False, True

    stored = note.access_password or ''
    password = password or ''
    try:
        identify_hasher(stored)
        ok = bool(stored) and check_password(password, stored)
    except ValueError:
        ok = bool(stored) and constant_time_compare(password, stored)
        if ok:
            note.access_password = make_password(password)
            note.save(update_fields=['access_password'])

    if not ok:
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, NOTE_PASSWORD_WINDOW_SECONDS)
    return ok, False


@login_required
def secure_note_inbox(request):
    """
    List all received secure notes.
    """
    # Notes received by user that aren't deleted
    notes = SecureNote.objects.filter(
        recipients=request.user,
        is_deleted=False
    ).exclude(
        expires_at__lt=timezone.now()
    ).order_by('-created_at')

    # Mark unread count
    unread_count = notes.exclude(read_by=request.user).count()

    return render(request, 'core/secure_note_inbox.html', {
        'notes': notes,
        'unread_count': unread_count,
        'view': 'inbox',
    })


@login_required
def secure_note_sent(request):
    """
    List all sent secure notes.
    """
    notes = SecureNote.objects.filter(
        sender=request.user,
        is_deleted=False
    ).order_by('-created_at')

    return render(request, 'core/secure_note_inbox.html', {
        'notes': notes,
        'view': 'sent',
    })


@login_required
def secure_note_detail(request, pk):
    """
    View secure note details. Marks as read.
    """
    note = get_object_or_404(SecureNote, pk=pk)

    # Check permissions
    if not note.can_be_read_by(request.user):
        messages.error(request, 'You do not have permission to view this note.')
        return redirect('core:secure_note_inbox')

    # Check if expired
    if note.is_expired:
        messages.error(request, 'This note has expired.')
        return redirect('core:secure_note_inbox')

    # Check password if required
    if note.require_password and note.sender != request.user:
        if request.method == 'POST':
            ok, locked = _note_password_ok(request, note, request.POST.get('password'))
            if not ok:
                messages.error(request, 'Too many incorrect attempts. Try again later.'
                               if locked else 'Incorrect password.')
                return render(request, 'core/secure_note_password.html', {'note': note})
        else:
            return render(request, 'core/secure_note_password.html', {'note': note})

    # Mark as read (if recipient)
    if request.user != note.sender:
        note.mark_as_read(request.user)

    # Decrypt content
    try:
        decrypted_content = note.get_content()
    except Exception as e:
        messages.error(request, f'Error decrypting note: {str(e)}')
        decrypted_content = '[Unable to decrypt]'

    return render(request, 'core/secure_note_detail.html', {
        'note': note,
        'content': decrypted_content,
        'recipients': note.recipients.all(),
        'read_by': note.read_by.all(),
    })


@login_required
def secure_note_create(request):
    """
    Create and send a new secure note.
    Supports both traditional recipient-based sharing and link-only mode (Issue #47).
    """
    org = get_request_organization(request)

    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        recipient_ids = request.POST.getlist('recipients')
        expires_hours = request.POST.get('expires_hours')
        read_once = request.POST.get('read_once') == 'on'
        require_password = request.POST.get('require_password') == 'on'
        access_password = request.POST.get('access_password', '')
        link_only = request.POST.get('link_only') == 'on'
        label = request.POST.get('label', '')
        max_views = request.POST.get('max_views', '')

        # Validation
        if not title or not content:
            messages.error(request, 'Title and content are required.')
        elif not link_only and not recipient_ids:
            messages.error(request, 'Either select recipients or enable "Link Only" mode.')
        else:
            # Create note
            note = SecureNote(
                sender=request.user,
                organization=org,
                title=title,
                label=label,
                link_only=link_only,
                read_once=read_once,
                require_password=require_password,
                access_password=make_password(access_password) if require_password else ''
            )

            # Set expiration if provided
            if expires_hours:
                try:
                    hours = int(expires_hours)
                    from datetime import timedelta
                    note.expires_at = timezone.now() + timedelta(hours=hours)
                except ValueError:
                    pass

            # Set max_views if provided (Phase 3)
            if max_views:
                try:
                    note.max_views = int(max_views)
                except ValueError:
                    pass

            # Encrypt content
            note.set_content(content)

            # Generate access token for link-only mode
            if link_only:
                note.generate_access_token()

            note.save()

            # Add recipients (only if not link-only)
            if not link_only and recipient_ids:
                recipients = User.objects.filter(id__in=recipient_ids)
                note.recipients.set(recipients)
                messages.success(request, f'Secure note sent to {recipients.count()} recipient(s).')
            elif link_only:
                # Show the shareable link
                share_url = note.get_share_url(request)
                messages.success(request, f'Secret link created! Copy the link to share.')
                return redirect('core:secure_note_link_created', pk=note.pk)

            return redirect('core:secure_note_sent')

    # Get potential recipients (users in same org)
    if org:
        from accounts.models import Membership
        member_ids = Membership.objects.filter(
            organization=org,
            is_active=True
        ).exclude(user=request.user).values_list('user_id', flat=True)
        users = User.objects.filter(id__in=member_ids)
    else:
        users = User.objects.none()

    return render(request, 'core/secure_note_form.html', {
        'users': users,
    })


@login_required
def secure_note_delete(request, pk):
    """
    Delete secure note (mark as deleted).
    """
    note = get_object_or_404(SecureNote, pk=pk)

    # Only sender can delete
    if note.sender != request.user:
        messages.error(request, 'Only the sender can delete this note.')
        return redirect('core:secure_note_inbox')

    if request.method == 'POST':
        note.is_deleted = True
        note.save()
        messages.success(request, 'Note deleted.')
        return redirect('core:secure_note_sent')

    return render(request, 'core/secure_note_confirm_delete.html', {
        'note': note,
    })

@login_required
def secure_note_link_created(request, pk):
    """
    Show the created secret link after generation (Issue #47 Phase 1).
    """
    note = get_object_or_404(SecureNote, pk=pk, sender=request.user)

    if not note.link_only:
        messages.error(request, 'This note is not a link-only note.')
        return redirect('core:secure_note_sent')

    share_url = note.get_share_url(request)

    return render(request, 'core/secure_note_link_created.html', {
        'note': note,
        'share_url': share_url,
    })


@login_required
def secure_note_links_dashboard(request):
    """
    Management dashboard for link-only secret notes (Issue #47 Phase 2).
    Shows all active secret links created by the user with filtering and management.
    """
    # Get all link-only notes created by user
    notes = SecureNote.objects.filter(
        sender=request.user,
        link_only=True,
        is_deleted=False
    ).order_by('-created_at')

    # Filter by label if provided
    label_filter = request.GET.get('label', '')
    if label_filter:
        notes = notes.filter(label__icontains=label_filter)

    # Filter by status
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'active':
        notes = notes.filter(expires_at__gt=timezone.now()) | notes.filter(expires_at__isnull=True)
    elif status_filter == 'expired':
        notes = notes.filter(expires_at__lt=timezone.now())

    # Get all unique labels for filter dropdown
    all_labels = SecureNote.objects.filter(
        sender=request.user,
        link_only=True,
        is_deleted=False,
        label__isnull=False
    ).exclude(label='').values_list('label', flat=True).distinct()

    return render(request, 'core/secure_note_links_dashboard.html', {
        'notes': notes,
        'all_labels': all_labels,
        'label_filter': label_filter,
        'status_filter': status_filter,
    })


@login_required
def secure_note_analytics(request, pk):
    """
    View detailed analytics and access logs for a secret link (Issue #47 Phase 3).
    Only the sender can view analytics.
    """
    note = get_object_or_404(SecureNote, pk=pk, sender=request.user)

    if not note.link_only:
        messages.error(request, 'Analytics are only available for link-only notes.')
        return redirect('core:secure_note_sent')

    # Get all access logs for this note
    from .models import SecureNoteAccessLog
    access_logs = SecureNoteAccessLog.objects.filter(
        secure_note=note
    ).order_by('-accessed_at')

    # Calculate statistics
    total_views = access_logs.count()
    unique_ips = access_logs.values('ip_address').distinct().count()
    authenticated_views = access_logs.exclude(user__isnull=True).count()
    anonymous_views = access_logs.filter(user__isnull=True).count()

    return render(request, 'core/secure_note_analytics.html', {
        'note': note,
        'access_logs': access_logs,
        'total_views': total_views,
        'unique_ips': unique_ips,
        'authenticated_views': authenticated_views,
        'anonymous_views': anonymous_views,
    })


def secure_note_view_link(request, token):
    """
    View secure note via unique access token (Issue #47 Phase 1, 3).
    No login required - anyone with the link can access.
    Phase 3: Adds access logging and max views checking.
    """
    note = get_object_or_404(SecureNote, access_token=token, link_only=True)

    # Check if deleted
    if note.is_deleted:
        messages.error(request, 'This secret link has been deleted.')
        return render(request, 'core/secure_note_expired.html')

    # Check if expired
    if note.is_expired:
        messages.error(request, 'This secret link has expired.')
        return render(request, 'core/secure_note_expired.html')

    # Phase 3: Check if max views reached
    if note.max_views and note.read_count >= note.max_views:
        messages.error(request, 'This secret link has reached its maximum view limit.')
        return render(request, 'core/secure_note_expired.html')

    # Check password if required
    if note.require_password:
        if request.method == 'POST':
            ok, locked = _note_password_ok(request, note, request.POST.get('password'))
            if not ok:
                messages.error(request, 'Too many incorrect attempts. Try again later.'
                               if locked else 'Incorrect password.')
                return render(request, 'core/secure_note_password.html', {'note': note, 'is_link_access': True})
        else:
            return render(request, 'core/secure_note_password.html', {'note': note, 'is_link_access': True})

    # Phase 3: Log access
    from .models import SecureNoteAccessLog
    SecureNoteAccessLog.objects.create(
        secure_note=note,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        user=request.user if request.user.is_authenticated else None
    )

    # Mark as read (increment counter, but no user to track)
    note.read_count += 1
    note.save(update_fields=['read_count'])

    # Delete if read_once is enabled OR max_views reached
    if note.read_once or (note.max_views and note.read_count >= note.max_views):
        note.is_deleted = True
        note.save(update_fields=['is_deleted'])

    # Decrypt content
    try:
        decrypted_content = note.get_content()
    except Exception as e:
        messages.error(request, f'Error decrypting note: {str(e)}')
        decrypted_content = '[Unable to decrypt]'

    return render(request, 'core/secure_note_detail.html', {
        'note': note,
        'content': decrypted_content,
        'is_link_access': True,
        'read_once_warning': note.read_once,
    })
