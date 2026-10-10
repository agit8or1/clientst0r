"""
REST API Serializers for Client St0r
"""
from rest_framework import serializers
from django.contrib.auth.models import User
from assets.models import Asset, Contact
from docs.models import Document
from vault.models import Password
from core.models import Organization, Tag


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']
        read_only_fields = ['id']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'slug', 'color']
        read_only_fields = ['id', 'slug']


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'description', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']


class OrganizationScopedSerializerMixin(serializers.ModelSerializer):
    """
    Surfaces the owning organization on every API resource (issue #134) so a
    single-pane-of-glass consumer can tell which client a row belongs to, and
    optionally target a client on create via the writable `organization` field.
    Access to the requested org is enforced server-side in the viewset.
    """
    organization = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False
    )
    organization_name = serializers.CharField(
        source='organization.name', read_only=True
    )


class AssetSerializer(OrganizationScopedSerializerMixin):
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=Tag.objects.all(), source='tags', required=False
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Asset
        # `location` and `is_active` were carried over from an older Asset
        # spec and crashed every list/detail request with
        # `ImproperlyConfigured: Field name 'location' is not valid for
        # model 'Asset'`. Removed in v3.17.193 alongside the matching fix
        # in AssetViewSet.filterset_fields.
        fields = [
            'id', 'organization', 'organization_name',
            'name', 'asset_type', 'serial_number', 'model', 'manufacturer',
            'hostname', 'ip_address', 'notes', 'tags', 'tag_ids',
            'needs_reorder', 'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']


class ContactSerializer(OrganizationScopedSerializerMixin):
    class Meta:
        model = Contact
        fields = [
            'id', 'organization', 'organization_name',
            'first_name', 'last_name', 'email', 'phone', 'title',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class DocumentSerializer(OrganizationScopedSerializerMixin):
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=Tag.objects.all(), source='tags', required=False
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'organization', 'organization_name',
            'title', 'slug', 'body', 'content_type', 'category',
            'is_published', 'is_template', 'is_archived',
            'tags', 'tag_ids', 'created_at', 'updated_at',
            'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at', 'created_by']


class PasswordListSerializer(serializers.ModelSerializer):
    """
    Limited serializer for password list (no actual password data).
    """
    tags = TagSerializer(many=True, read_only=True)
    password_type_display = serializers.CharField(source='get_password_type_display', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Password
        fields = [
            'id', 'organization', 'organization_name',
            'title', 'password_type', 'password_type_display',
            'username', 'url', 'tags', 'expires_at', 'is_expired',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at', 'is_expired']


class PasswordDetailSerializer(OrganizationScopedSerializerMixin):
    """
    Detailed serializer - requires special permission to access password field.
    """
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=Tag.objects.all(), source='tags', required=False
    )
    password = serializers.SerializerMethodField()
    otp_code = serializers.SerializerMethodField()

    class Meta:
        model = Password
        fields = [
            'id', 'organization', 'organization_name',
            'title', 'password_type', 'username', 'password', 'url',
            'otp_issuer', 'otp_code', 'notes', 'expires_at', 'tags', 'tag_ids',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'password', 'otp_code', 'created_at', 'updated_at']

    def _revealing(self):
        """True only for GET /api/passwords/<id>/?reveal=true, which
        PasswordViewSet.retrieve has already passed through the reveal gate.
        Create/update responses never carry secrets."""
        request = self.context.get('request')
        view = self.context.get('view')
        return bool(
            request and view is not None
            and getattr(view, 'action', None) == 'retrieve'
            and request.query_params.get('reveal') == 'true'
        )

    def get_password(self, obj):
        """Only return password if explicitly requested with reveal=true."""
        if self._revealing():
            return obj.get_password()
        return '**********'

    def get_otp_code(self, obj):
        """Current OTP code, under the same rule as the password."""
        if obj.password_type == 'otp' and self._revealing():
            return obj.generate_otp()
        return None
