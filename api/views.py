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

from accounts.permission_utils import (
    filter_by_org_perm, has_perm_for_org, orgs_with_perm, user_has_org_perm,
)
from audit.models import AuditLog
from core.client_ip import get_client_ip
from assets.models import Asset, Contact
from docs.models import Document
from vault.models import Password
from vault.permissions import (
    RevealDenied, can_access_password, consume_approval, gate_reveal,
)
from core.models import Tag, Organization

from .permissions import key_level_label, key_role_allows
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

    `view_perm` names the role flag (RoleTemplate / simple-role default) that
    gates reading this resource. It is applied on top of the key/session org
    scoping: a row is reachable only when its customer is both in scope AND a
    customer where the user holds `view_perm`. Every detail route and custom
    action goes through `get_object()` -> `get_queryset()`, so a row the user
    may not view answers 404 everywhere, not just on the list.
    """
    permission_classes = [IsAuthenticated]
    view_perm = None
    # Role flags for writes. Checked in the row's customer (and the target
    # customer on a move), and against the API key's Permission Level.
    create_perm = None
    edit_perm = None
    delete_perm = None

    def get_queryset(self):
        """Filter queryset to the org(s) resolved for this request."""
        base_queryset = super().get_queryset()
        if not hasattr(base_queryset.model, 'organization'):
            return base_queryset
        org_ids = resolve_scope_org_ids(self.request)
        return self.filter_view_perm(
            base_queryset.filter(organization_id__in=org_ids)
        )

    def filter_view_perm(self, queryset):
        """Narrow to customers where the user holds `view_perm`."""
        if not self.view_perm:
            return queryset
        if not key_role_allows(self.request, self.view_perm):
            return queryset.none()
        return filter_by_org_perm(queryset, self.request.user, self.view_perm)

    def require_perm(self, organization, perm, what):
        """403 unless both the API key's level (if any) and the user's role
        in `organization` grant `perm`."""
        if not perm:
            return
        if not key_role_allows(self.request, perm):
            raise PermissionDenied(
                f"This API key's permission level ({key_level_label(self.request)}) "
                f"does not allow {what}."
            )
        if not has_perm_for_org(self.request.user, organization, perm):
            raise PermissionDenied(f"You do not have permission to {what} here.")

    def check_tags(self, serializer, organization):
        """Tags attached through `tag_ids` must belong to the row's customer;
        the field accepted any tag id, so a row could carry (and echo back)
        another customer's tag."""
        tags = serializer.validated_data.get('tags')
        if tags and organization is not None and any(
                t.organization_id != organization.id for t in tags):
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'tag_ids': ["Tags must belong to the record's organization."]})

    def require_view_perm(self, organization):
        """403 unless the user holds `view_perm` in `organization`. Used on
        create / move so nobody writes rows into a customer they cannot read."""
        if self.view_perm and not has_perm_for_org(
            self.request.user, organization, self.view_perm
        ):
            raise PermissionDenied(
                "You do not have permission to view this module for the "
                "target organization."
            )

    def perform_create(self, serializer):
        """Set organization (param > body > primary, access-checked) + created_by."""
        kwargs = {}
        model = serializer.Meta.model
        if hasattr(model, 'organization'):
            kwargs['organization'] = resolve_create_org(self.request, serializer)
            self.require_view_perm(kwargs['organization'])
            self.require_perm(kwargs['organization'], self.create_perm, 'create this')
            self.check_tags(serializer, kwargs['organization'])
        if hasattr(model, 'created_by'):
            kwargs['created_by'] = self.request.user
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        """Set last_modified_by; block moving a row to an inaccessible org."""
        kwargs = {}
        instance_org = getattr(serializer.instance, 'organization', None)
        self.require_perm(instance_org, self.edit_perm, 'edit this')
        target_org = serializer.validated_data.get('organization')
        if target_org is not None and target_org.id not in set(
            accessible_org_ids(self.request)
        ):
            raise PermissionDenied(
                "You do not have access to the target organization for this object."
            )
        if target_org is not None:
            self.require_view_perm(target_org)
            self.require_perm(target_org, self.edit_perm, 'edit this')
        self.check_tags(serializer, target_org or instance_org)
        if hasattr(serializer.Meta.model, 'last_modified_by'):
            kwargs['last_modified_by'] = self.request.user
        serializer.save(**kwargs)

    def perform_destroy(self, instance):
        self.require_perm(getattr(instance, 'organization', None), self.delete_perm, 'delete this')
        instance.delete()


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
    view_perm = 'assets_view'
    create_perm = 'assets_create'
    edit_perm = 'assets_edit'
    delete_perm = 'assets_delete'
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
    API endpoint for contacts. Contacts live in the assets module, so they
    are governed by `assets_view`.
    """
    queryset = Contact.objects.all()
    view_perm = 'assets_view'
    create_perm = 'assets_create'
    edit_perm = 'assets_edit'
    delete_perm = 'assets_delete'
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
    view_perm = 'docs_view'
    create_perm = 'docs_create'
    edit_perm = 'docs_edit'
    delete_perm = 'docs_delete'
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['is_published', 'is_template', 'is_archived', 'category', 'content_type']
    search_fields = ['title', 'body']
    ordering_fields = ['title', 'created_at', 'updated_at']
    ordering = ['-updated_at']

    def _require_publish_if_changed(self, serializer, current):
        """Publishing or unpublishing through the `is_published` field needs
        `docs_publish`, like the publish action."""
        wanted = serializer.validated_data.get('is_published')
        if wanted is not None and wanted != current:
            org = (serializer.validated_data.get('organization')
                   or getattr(serializer.instance, 'organization', None)
                   or resolve_create_org(self.request, serializer))
            self.require_perm(org, 'docs_publish', 'publish or unpublish documents')

    def perform_create(self, serializer):
        self._require_publish_if_changed(serializer, False)
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._require_publish_if_changed(serializer, serializer.instance.is_published)
        super().perform_update(serializer)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a document."""
        document = self.get_object()
        self.require_perm(document.organization, 'docs_publish', 'publish documents')
        document.is_published = True
        document.save()
        return Response({'status': 'published'})

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """Archive a document."""
        document = self.get_object()
        self.require_perm(document.organization, 'docs_edit', 'archive documents')
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
    view_perm = 'vault_view'
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

    def filter_view_perm(self, queryset):
        """Org-scoped shared entries need `vault_view` in their customer; the
        caller's own personal (My Vault) entries stay visible regardless.
        Other users' personal entries are never visible."""
        user = self.request.user
        own_personal = Q(is_personal=True, personal_owner=user)
        allowed = orgs_with_perm(user, self.view_perm)
        if allowed is None:
            shared = Q(is_personal=False)
        else:
            shared = Q(is_personal=False, organization_id__in=allowed)
        return queryset.filter(shared | own_personal)

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

    def _require_key(self, perm, what):
        if not key_role_allows(self.request, perm):
            raise PermissionDenied(
                f"This API key's permission level ({key_level_label(self.request)}) "
                f"does not allow {what}."
            )

    def _key_reveal_denial(self):
        """RevealDenied when the API key's level may not see secrets."""
        if key_role_allows(self.request, 'vault_view_password'):
            return None
        return RevealDenied(
            403, f"This API key's permission level ({key_level_label(self.request)}) "
                 "does not allow revealing passwords.")

    def perform_create(self, serializer):
        self._require_key('vault_create', 'creating passwords')
        org = resolve_create_org(self.request, serializer)
        if not user_has_org_perm(self.request.user, org.id, 'vault_create'):
            raise PermissionDenied('You do not have permission to create passwords.')
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._require_key('vault_edit', 'editing passwords')
        if not can_access_password(self.request.user, serializer.instance, 'vault_edit'):
            raise PermissionDenied('You do not have permission to edit this password.')
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._require_key('vault_delete', 'deleting passwords')
        if not can_access_password(self.request.user, instance, 'vault_delete'):
            raise PermissionDenied('You do not have permission to delete this password.')
        super().perform_destroy(instance)

    def retrieve(self, request, *args, **kwargs):
        """Log password access on retrieve; ?reveal=true passes the reveal gate."""
        instance = self.get_object()
        revealing = request.query_params.get('reveal') == 'true'
        if revealing:
            denial = self._key_reveal_denial()
            if denial is not None:
                return self._denied(instance, denial, 'reveal')
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
        denial = self._key_reveal_denial()
        if denial is not None:
            return self._denied(password, denial, 'reveal')
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
        body = {'password': plaintext}
        if password.license_key:
            body['license_key'] = password.license_key
        return Response(body)

    @action(detail=True, methods=['get'])
    def otp(self, request, pk=None):
        """
        Generate OTP code.
        GET /api/passwords/{id}/otp/
        """
        password = self.get_object()
        denial = self._key_reveal_denial()
        if denial is not None:
            return self._denied(password, denial, 'otp')
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

    def _require_tag_admin(self):
        """Tag management is superuser-only in the web app (core.tag_views);
        the API let any member create, rename and delete tags."""
        if not self.request.user.is_superuser:
            raise PermissionDenied('Only superusers can manage tags.')
        if not key_role_allows(self.request, 'assets_edit'):
            raise PermissionDenied(
                f"This API key's permission level ({key_level_label(self.request)}) "
                "does not allow managing tags."
            )

    def perform_create(self, serializer):
        self._require_tag_admin()
        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._require_tag_admin()
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._require_tag_admin()
        super().perform_destroy(instance)


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
