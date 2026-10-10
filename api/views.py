"""
REST API Views for Client St0r
Provides full CRUD operations via RESTful API
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import PermissionDenied

from accounts.permission_utils import user_has_org_perm
from audit.models import AuditLog
from core.client_ip import get_client_ip
from assets.models import Asset, Contact
from docs.models import Document
from vault.models import Password
from vault.permissions import (
    RevealDenied, can_access_password, consume_approval, gate_reveal,
)
from core.models import Tag, Organization

from .scoping import (
    accessible_org_ids, resolve_scope_org_ids, resolve_create_org,
)
from .serializers import (
    AssetSerializer, ContactSerializer, DocumentSerializer,
    PasswordListSerializer, PasswordDetailSerializer,
    TagSerializer, OrganizationSerializer
)


class OrganizationScopedViewSet(viewsets.ModelViewSet):
    """
    Base viewset that scopes every request to the organization(s) the caller
    may address.

    Single-organization keys and web sessions behave exactly as before. Keys
    with a broader `scope` (issue #134), and any caller passing
    ``?organization=<id|slug|all>``, can read/write across multiple client
    organizations. See `api.scoping` for the resolution rules.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter queryset to the org(s) resolved for this request."""
        base_queryset = super().get_queryset()
        if not hasattr(base_queryset.model, 'organization'):
            return base_queryset
        org_ids = resolve_scope_org_ids(self.request)
        return base_queryset.filter(organization_id__in=org_ids)

    def perform_create(self, serializer):
        """Set organization (param > body > primary, access-checked) + created_by."""
        kwargs = {}
        model = serializer.Meta.model
        if hasattr(model, 'organization'):
            kwargs['organization'] = resolve_create_org(self.request, serializer)
        if hasattr(model, 'created_by'):
            kwargs['created_by'] = self.request.user
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        """Set last_modified_by; block moving a row to an inaccessible org."""
        kwargs = {}
        target_org = serializer.validated_data.get('organization')
        if target_org is not None and target_org.id not in set(
            accessible_org_ids(self.request)
        ):
            raise PermissionDenied(
                "You do not have access to the target organization for this object."
            )
        if hasattr(serializer.Meta.model, 'last_modified_by'):
            kwargs['last_modified_by'] = self.request.user
        serializer.save(**kwargs)


class AssetViewSet(OrganizationScopedViewSet):
    """
    API endpoint for assets.

    list: Get all assets
    create: Create new asset
    retrieve: Get single asset
    update: Update asset
    destroy: Delete asset

    Filtering: ?asset_type=server&is_active=true
    Search: ?search=hostname
    """
    queryset = Asset.objects.all()
    serializer_class = AssetSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # Asset doesn't have `is_active` or `location` columns — those were
    # carried over from an old model spec and crashed every list request
    # with `TypeError: 'Meta.fields' must not contain non-model field names`
    # until v3.17.193 caught it via the new api/ test suite.
    filterset_fields = ['asset_type', 'needs_reorder']
    # Phase 21 v3/v4 (v3.17.318): mac_address + ip_address join the
    # search field set so a tech who scans a MAC or IP barcode/QR
    # (or pastes one from a label scanner) finds the asset directly
    # via /api/assets/?search=<scanned-value>.
    search_fields = ['name', 'serial_number', 'model', 'manufacturer',
                     'mac_address', 'ip_address']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']


class ContactViewSet(OrganizationScopedViewSet):
    """
    API endpoint for contacts.
    """
    queryset = Contact.objects.all()
    serializer_class = ContactSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['first_name', 'last_name', 'email', 'phone']
    ordering_fields = ['last_name', 'first_name', 'created_at']
    ordering = ['last_name', 'first_name']


class DocumentViewSet(OrganizationScopedViewSet):
    """
    API endpoint for documents.

    Filtering: ?is_published=true&category=sop
    Search: ?search=server
    """
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_published', 'is_template', 'is_archived', 'category', 'content_type']
    search_fields = ['title', 'body']
    ordering_fields = ['title', 'created_at', 'updated_at']
    ordering = ['-updated_at']

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a document."""
        document = self.get_object()
        document.is_published = True
        document.save()
        return Response({'status': 'published'})

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a document."""
        document = self.get_object()
        document.is_archived = True
        document.save()
        return Response({'status': 'archived'})


class PasswordViewSet(OrganizationScopedViewSet):
    """
    API endpoint for passwords.

    SECURITY NOTICE:
    - List endpoint returns metadata only (no passwords)
    - Retrieve endpoint returns passwords only with ?reveal=true
    - All password access is logged for audit

    Filtering: ?password_type=otp&is_expired=false
    Search: ?search=github
    """
    queryset = Password.objects.all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['password_type']
    search_fields = ['title', 'username', 'url']
    ordering_fields = ['title', 'created_at', 'updated_at']
    ordering = ['title']

    def get_serializer_class(self):
        """Use different serializers for list vs detail."""
        if self.action == 'list':
            return PasswordListSerializer
        return PasswordDetailSerializer

    def get_queryset(self):
        """Org-scoped, minus other users' personal (My Vault) entries."""
        return super().get_queryset().filter(
            Q(is_personal=False) | Q(personal_owner=self.request.user)
        )

    def _denied(self, password, denial, channel):
        AuditLog.objects.create(
            organization=password.organization,
            user=self.request.user,
            action='reveal_blocked',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            description=f"API {channel} blocked: {denial.detail}",
            ip_address=get_client_ip(self.request),
            user_agent=self.request.META.get('HTTP_USER_AGENT', '')[:255],
            success=False,
        )
        body = {'error': denial.detail}
        if denial.requires_approval:
            body['requires_approval'] = True
        return Response(body, status=denial.status)

    def perform_create(self, serializer):
        org = resolve_create_org(self.request, serializer)
        if not user_has_org_perm(self.request.user, org.id, 'vault_create'):
            raise PermissionDenied('You do not have permission to create passwords.')
        super().perform_create(serializer)

    def perform_update(self, serializer):
        if not can_access_password(self.request.user, serializer.instance, 'vault_edit'):
            raise PermissionDenied('You do not have permission to edit this password.')
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        if not can_access_password(self.request.user, instance, 'vault_delete'):
            raise PermissionDenied('You do not have permission to delete this password.')
        super().perform_destroy(instance)

    def retrieve(self, request, *args, **kwargs):
        """Log password access on retrieve; ?reveal=true passes the reveal gate."""
        instance = self.get_object()
        revealing = request.query_params.get('reveal') == 'true'
        if revealing:
            try:
                gate_reveal(request, instance)
            except RevealDenied as denial:
                return self._denied(instance, denial, 'reveal')
        # Log against the row's own org — with multi-org keys the active row
        # may belong to a different client than the request's primary org.
        org = instance.organization

        # Log access
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='read',
            object_type='password',
            object_id=instance.id,
            object_repr=instance.title,
            description=f"Password '{instance.title}' accessed via API",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        serializer = self.get_serializer(instance)
        data = serializer.data
        if revealing:
            consume_approval(instance, request.user)
        return Response(data)

    @action(detail=True, methods=['post'])
    def reveal(self, request, pk=None):
        """
        Explicitly reveal password (alternative to ?reveal=true).
        POST /api/passwords/{id}/reveal/
        """
        password = self.get_object()
        org = password.organization
        try:
            gate_reveal(request, password)
        except RevealDenied as denial:
            return self._denied(password, denial, 'reveal')

        # Log password reveal
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='reveal',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            description=f"Password '{password.title}' revealed via API",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        plaintext = password.get_password()
        consume_approval(password, request.user)
        return Response({'password': plaintext})

    @action(detail=True, methods=['get'])
    def otp(self, request, pk=None):
        """
        Generate OTP code.
        GET /api/passwords/{id}/otp/
        """
        password = self.get_object()
        try:
            gate_reveal(request, password)
        except RevealDenied as denial:
            return self._denied(password, denial, 'otp')

        if password.password_type != 'otp':
            return Response(
                {'error': 'Not an OTP entry'},
                status=status.HTTP_400_BAD_REQUEST
            )

        otp_code = password.generate_otp()
        if not otp_code:
            return Response(
                {'error': 'OTP secret not configured'},
                status=status.HTTP_400_BAD_REQUEST
            )

        org = password.organization
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='read',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            description=f"OTP generated for '{password.title}' via API",
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        return Response({'otp': otp_code})


class TagViewSet(OrganizationScopedViewSet):
    """
    API endpoint for tags.
    """
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering = ['name']


class OrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for organizations (read-only).

    Returns every organization the caller may address — for a multi-org key
    (issue #134) this is the full client list, so a single-pane-of-glass
    consumer can discover which organizations to query.
    """
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Only show organizations the caller has access to."""
        return Organization.objects.filter(
            id__in=accessible_org_ids(self.request),
            is_active=True,
        ).distinct()
