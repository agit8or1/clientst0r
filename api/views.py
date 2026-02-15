"""
REST API Views for Client St0r
Provides full CRUD operations via RESTful API
"""
from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404

from core.middleware import get_request_organization
from audit.models import AuditLog
from assets.models import Asset, Contact
from docs.models import Document
from vault.models import Password
from core.models import Tag, Organization

from .serializers import (
    AssetSerializer, ContactSerializer, DocumentSerializer,
    PasswordListSerializer, PasswordDetailSerializer,
    TagSerializer, OrganizationSerializer
)


class OrganizationScopedViewSet(viewsets.ModelViewSet):
    """
    Base viewset that automatically filters by organization.
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Filter queryset by current organization."""
        org = get_request_organization(self.request)
        base_queryset = super().get_queryset()
        if hasattr(base_queryset.model, 'organization'):
            return base_queryset.filter(organization=org)
        return base_queryset

    def perform_create(self, serializer):
        """Automatically set organization and created_by on create."""
        org = get_request_organization(self.request)
        kwargs = {}
        if hasattr(serializer.Meta.model, 'organization'):
            kwargs['organization'] = org
        if hasattr(serializer.Meta.model, 'created_by'):
            kwargs['created_by'] = self.request.user
        serializer.save(**kwargs)

    def perform_update(self, serializer):
        """Automatically set last_modified_by on update."""
        kwargs = {}
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
    filterset_fields = ['asset_type', 'is_active', 'location']
    search_fields = ['name', 'serial_number', 'model', 'manufacturer']
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

    def retrieve(self, request, *args, **kwargs):
        """Log password access on retrieve."""
        instance = self.get_object()
        org = get_request_organization(request)

        # Log access
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='read',
            object_type='password',
            object_id=instance.id,
            object_repr=instance.title,
            details=f"Password '{instance.title}' accessed via API",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def reveal(self, request, pk=None):
        """
        Explicitly reveal password (alternative to ?reveal=true).
        POST /api/passwords/{id}/reveal/
        """
        password = self.get_object()
        org = get_request_organization(request)

        # Log password reveal
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='reveal',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            details=f"Password '{password.title}' revealed via API",
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )

        return Response({
            'password': password.get_password()
        })

    @action(detail=True, methods=['get'])
    def otp(self, request, pk=None):
        """
        Generate OTP code.
        GET /api/passwords/{id}/otp/
        """
        password = self.get_object()

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

        org = get_request_organization(request)
        AuditLog.objects.create(
            organization=org,
            user=request.user,
            action='read',
            object_type='password',
            object_id=password.id,
            object_repr=password.title,
            details=f"OTP generated for '{password.title}' via API",
            ip_address=request.META.get('REMOTE_ADDR'),
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
    Users can only see organizations they belong to.
    """
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Only show organizations user has access to."""
        return Organization.objects.filter(
            memberships__user=self.request.user,
            is_active=True
        ).distinct()
