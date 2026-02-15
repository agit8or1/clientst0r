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


class AssetSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=Tag.objects.all(), source='tags', required=False
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Asset
        fields = [
            'id', 'name', 'asset_type', 'serial_number', 'model', 'manufacturer',
            'location', 'notes', 'tags', 'tag_ids', 'is_active',
            'created_at', 'updated_at', 'created_by', 'created_by_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone', 'title',
            'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class DocumentSerializer(serializers.ModelSerializer):
    tags = TagSerializer(many=True, read_only=True)
    tag_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, queryset=Tag.objects.all(), source='tags', required=False
    )
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'slug', 'body', 'content_type', 'category',
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

    class Meta:
        model = Password
        fields = [
            'id', 'title', 'password_type', 'password_type_display',
            'username', 'url', 'tags', 'expires_at', 'is_expired',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'is_expired']


class PasswordDetailSerializer(serializers.ModelSerializer):
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
            'id', 'title', 'password_type', 'username', 'password', 'url',
            'otp_issuer', 'otp_code', 'notes', 'expires_at', 'tags', 'tag_ids',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'password', 'otp_code', 'created_at', 'updated_at']

    def get_password(self, obj):
        """Only return password if explicitly requested with reveal=true."""
        request = self.context.get('request')
        if request and request.query_params.get('reveal') == 'true':
            return obj.get_password()
        return '**********'

    def get_otp_code(self, obj):
        """Generate OTP code if password type is OTP."""
        if obj.password_type == 'otp':
            return obj.generate_otp()
        return None
