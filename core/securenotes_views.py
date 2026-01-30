"""
Secure Notes views - Encrypted messaging between users
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.utils import timezone
from django.db.models import Q
from .models import SecureNote
from .middleware import get_request_organization


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
            password = request.POST.get('password')
            # Check password (simplified - should use proper password hashing)
            if password != note.access_password:
                messages.error(request, 'Incorrect password.')
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
                access_password=access_password if require_password else ''
            )

            # Set expiration if provided
            if expires_hours:
                try:
                    hours = int(expires_hours)
                    from datetime import timedelta
                    note.expires_at = timezone.now() + timedelta(hours=hours)
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


def secure_note_view_link(request, token):
    """
    View secure note via unique access token (Issue #47 Phase 1).
    No login required - anyone with the link can access.
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

    # Check password if required
    if note.require_password:
        if request.method == 'POST':
            password = request.POST.get('password')
            # Check password (simplified - should use proper password hashing)
            if password != note.access_password:
                messages.error(request, 'Incorrect password.')
                return render(request, 'core/secure_note_password.html', {'note': note, 'is_link_access': True})
        else:
            return render(request, 'core/secure_note_password.html', {'note': note, 'is_link_access': True})

    # Mark as read (increment counter, but no user to track)
    note.read_count += 1
    note.save(update_fields=['read_count'])

    # Delete if read_once is enabled
    if note.read_once:
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
