"""
GraphQL Schema for Client St0r API v2
Provides modern GraphQL API alongside REST API v1
"""

import graphene
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField
from graphql_jwt.decorators import login_required
from django.contrib.auth import get_user_model

from assets.models import Asset, AssetType
from vault.models import Password
from docs.models import Document, Diagram
from accounts.models import Organization
from locations.models import Location
from monitoring.models import WebsiteMonitor, Expiration

User = get_user_model()


# ===== Types =====

class UserType(DjangoObjectType):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name',
                 'is_staff', 'is_active', 'date_joined', 'last_login')


class OrganizationType(DjangoObjectType):
    asset_count = graphene.Int()
    password_count = graphene.Int()

    class Meta:
        model = Organization
        fields = (
            'id', 'name', 'slug', 'organization_type', 'description',
            'street_address', 'street_address_2', 'city', 'state',
            'postal_code', 'country', 'phone', 'email', 'website',
            'primary_contact_name', 'primary_contact_title',
            'primary_contact_email', 'primary_contact_phone',
            'created_at', 'updated_at', 'is_active',
        )

    def resolve_asset_count(self, info):
        return self.asset_set.count() if hasattr(self, 'asset_set') else 0

    def resolve_password_count(self, info):
        return self.password_set.count() if hasattr(self, 'password_set') else 0


class AssetTypeType(DjangoObjectType):
    class Meta:
        model = AssetType
        fields = (
            'id', 'name', 'slug', 'description', 'icon', 'color',
            'is_active', 'show_in_menu', 'created_at', 'updated_at',
        )


class AssetObjectType(DjangoObjectType):
    class Meta:
        model = Asset
        fields = (
            'id', 'name', 'asset_type', 'asset_tag', 'serial_number',
            'manufacturer', 'model', 'hostname', 'ip_address', 'mac_address',
            'is_rackmount', 'rack_units', 'port_count', 'custom_fields',
            'purchase_date', 'lifespan_years', 'notes',
            'created_at', 'updated_at', 'organization',
        )


class PasswordType(DjangoObjectType):
    # Metadata only: an allowlist, so ciphertext fields (encrypted_password,
    # otp_secret, ...) and any field added later are never exposed.
    class Meta:
        model = Password
        fields = (
            'id', 'title', 'username', 'url', 'password_type',
            'organization', 'created_at', 'updated_at',
        )


class DocumentType(DjangoObjectType):
    class Meta:
        model = Document
        fields = (
            'id', 'title', 'slug', 'body', 'content_type', 'is_published',
            'is_template', 'is_archived', 'is_global', 'organization',
            'created_at', 'updated_at',
        )


class DiagramType(DjangoObjectType):
    class Meta:
        model = Diagram
        fields = (
            'id', 'title', 'slug', 'description', 'diagram_xml',
            'diagram_type', 'is_global', 'is_published', 'is_template',
            'version_number', 'organization', 'created_at', 'updated_at',
        )


class LocationType(DjangoObjectType):
    class Meta:
        model = Location
        fields = (
            'id', 'name', 'location_type', 'street_address', 'street_address_2',
            'city', 'state', 'postal_code', 'country', 'latitude', 'longitude',
            'building_sqft', 'floors_count', 'year_built', 'is_primary',
            'status', 'notes', 'phone', 'email', 'website',
            'organization', 'is_shared', 'created_at', 'updated_at',
        )


class WebsiteMonitorType(DjangoObjectType):
    class Meta:
        model = WebsiteMonitor
        fields = (
            'id', 'name', 'url', 'check_interval_minutes', 'is_enabled',
            'status', 'last_checked_at', 'last_status_code', 'last_response_time_ms',
            'ssl_enabled', 'ssl_expires_at', 'ssl_warning_days',
            'domain_expires_at', 'domain_warning_days',
            'notify_on_down', 'notify_on_ssl_expiry', 'notify_on_domain_expiry',
            'organization', 'created_at', 'updated_at',
        )


class ExpirationType(DjangoObjectType):
    days_until_expiry = graphene.Int()

    class Meta:
        model = Expiration
        fields = (
            'id', 'name', 'expiration_type', 'expires_at', 'warning_days',
            'related_url', 'notes', 'auto_renew', 'notification_sent',
            'organization', 'created_at', 'updated_at',
        )

    def resolve_days_until_expiry(self, info):
        from datetime import date
        from django.utils import timezone
        if self.expires_at:
            delta = self.expires_at.date() - date.today()
            return delta.days
        return None


class DashboardStatsType(graphene.ObjectType):
    total_organizations = graphene.Int()
    total_assets = graphene.Int()
    total_passwords = graphene.Int()
    total_documents = graphene.Int()
    total_diagrams = graphene.Int()
    active_monitors = graphene.Int()


# ===== Scoping =====
#
# Every resolver is limited to the organizations the caller can reach in the
# web app (api.scoping), and every mutation checks the matching role
# capability on the target organization.

from django.db.models import Q
from graphql import GraphQLError

from accounts.permission_utils import user_has_org_perm
from api.scoping import _is_staff_user, _user_reach_ids


def _org_ids(info):
    return _user_reach_ids(info.context.user)


def _scoped(queryset, info, organization_id=None):
    org_ids = _org_ids(info)
    if organization_id is not None:
        if organization_id not in org_ids:
            return queryset.none()
        org_ids = [organization_id]
    return queryset.filter(organization_id__in=org_ids)


def _scoped_global(queryset, info, organization_id=None):
    """Org-scoped, plus published global (KB-wide) rows when no org is named."""
    scoped = Q(organization_id__in=_org_ids(info))
    if organization_id is not None:
        if organization_id not in _org_ids(info):
            return queryset.none()
        return queryset.filter(organization_id=organization_id)
    return queryset.filter(scoped | Q(is_global=True, is_published=True))


def _visible_passwords(info, organization_id=None):
    user = info.context.user
    queryset = _scoped(Password.objects.all(), info, organization_id)
    return queryset.filter(Q(is_personal=False) | Q(personal_owner=user))


def _get_or_none(queryset, pk):
    return queryset.filter(pk=pk).first()


def _require_org_perm(info, organization_id, perm_name):
    if not user_has_org_perm(info.context.user, organization_id, perm_name):
        raise GraphQLError('Permission denied')


def _visible_users(info):
    user = info.context.user
    if _is_staff_user(user):
        return User.objects.all()
    return User.objects.filter(
        memberships__organization_id__in=_org_ids(info),
        memberships__is_active=True,
    ).distinct()


# ===== Queries =====

class Query(graphene.ObjectType):
    # User queries
    me = graphene.Field(UserType)
    user = graphene.Field(UserType, id=graphene.Int())
    users = graphene.List(UserType)

    # Organization queries
    organization = graphene.Field(OrganizationType, id=graphene.Int())
    organizations = graphene.List(OrganizationType)
    my_organization = graphene.Field(OrganizationType)

    # Asset queries
    asset = graphene.Field(AssetObjectType, id=graphene.Int())
    assets = graphene.List(AssetObjectType, organization_id=graphene.Int())
    asset_types = graphene.List(AssetTypeType)

    # Password queries
    password = graphene.Field(PasswordType, id=graphene.Int())
    passwords = graphene.List(PasswordType, organization_id=graphene.Int())

    # Document queries
    document = graphene.Field(DocumentType, id=graphene.Int())
    documents = graphene.List(DocumentType, organization_id=graphene.Int())

    # Diagram queries
    diagram = graphene.Field(DiagramType, id=graphene.Int())
    diagrams = graphene.List(DiagramType, organization_id=graphene.Int())

    # Location queries
    location = graphene.Field(LocationType, id=graphene.Int())
    locations = graphene.List(LocationType)

    # Monitoring queries
    website_monitor = graphene.Field(WebsiteMonitorType, id=graphene.Int())
    website_monitors = graphene.List(WebsiteMonitorType, organization_id=graphene.Int())
    expirations = graphene.List(ExpirationType, organization_id=graphene.Int())
    expiring_soon = graphene.List(ExpirationType, days=graphene.Int(default_value=30))

    # Statistics
    dashboard_stats = graphene.Field(DashboardStatsType)

    @login_required
    def resolve_me(self, info):
        return info.context.user

    @login_required
    def resolve_user(self, info, id):
        return _get_or_none(_visible_users(info), id)

    @login_required
    def resolve_users(self, info):
        return _visible_users(info)

    @login_required
    def resolve_my_organization(self, info):
        return Organization.objects.filter(pk__in=_org_ids(info)).order_by('name').first()

    @login_required
    def resolve_organization(self, info, id):
        return Organization.objects.filter(pk__in=_org_ids(info), pk=id).first()

    @login_required
    def resolve_organizations(self, info):
        return Organization.objects.filter(pk__in=_org_ids(info))

    @login_required
    def resolve_asset(self, info, id):
        return _get_or_none(_scoped(Asset.objects.all(), info), id)

    @login_required
    def resolve_assets(self, info, organization_id=None):
        return _scoped(Asset.objects.all(), info, organization_id)

    @login_required
    def resolve_asset_types(self, info):
        return _scoped(AssetType.objects.all(), info)

    @login_required
    def resolve_password(self, info, id):
        return _get_or_none(_visible_passwords(info), id)

    @login_required
    def resolve_passwords(self, info, organization_id=None):
        return _visible_passwords(info, organization_id)

    @login_required
    def resolve_document(self, info, id):
        return _get_or_none(_scoped_global(Document.objects.all(), info), id)

    @login_required
    def resolve_documents(self, info, organization_id=None):
        return _scoped_global(Document.objects.all(), info, organization_id)

    @login_required
    def resolve_diagram(self, info, id):
        return _get_or_none(_scoped_global(Diagram.objects.all(), info), id)

    @login_required
    def resolve_diagrams(self, info, organization_id=None):
        return _scoped_global(Diagram.objects.all(), info, organization_id)

    @login_required
    def resolve_location(self, info, id):
        return _get_or_none(_scoped(Location.objects.all(), info), id)

    @login_required
    def resolve_locations(self, info):
        return _scoped(Location.objects.all(), info)

    @login_required
    def resolve_website_monitor(self, info, id):
        return _get_or_none(_scoped(WebsiteMonitor.objects.all(), info), id)

    @login_required
    def resolve_website_monitors(self, info, organization_id=None):
        return _scoped(WebsiteMonitor.objects.all(), info, organization_id)

    @login_required
    def resolve_expirations(self, info, organization_id=None):
        return _scoped(Expiration.objects.all(), info, organization_id)

    @login_required
    def resolve_expiring_soon(self, info, days=30):
        from datetime import timedelta
        from django.utils import timezone
        now = timezone.now()
        return _scoped(Expiration.objects.all(), info).filter(
            expires_at__lte=now + timedelta(days=days),
            expires_at__gte=now,
        ).order_by('expires_at')

    @login_required
    def resolve_dashboard_stats(self, info):
        org_ids = _org_ids(info)
        return DashboardStatsType(
            total_organizations=len(org_ids),
            total_assets=Asset.objects.filter(organization_id__in=org_ids).count(),
            total_passwords=_visible_passwords(info).count(),
            total_documents=Document.objects.filter(organization_id__in=org_ids).count(),
            total_diagrams=Diagram.objects.filter(organization_id__in=org_ids).count(),
            active_monitors=WebsiteMonitor.objects.filter(
                organization_id__in=org_ids, is_enabled=True,
            ).count(),
        )


# ===== Mutations =====

class CreateAsset(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        organization_id = graphene.Int(required=True)
        asset_type = graphene.String()
        serial_number = graphene.String()
        manufacturer = graphene.String()
        model = graphene.String()

    asset = graphene.Field(AssetObjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, name, organization_id, asset_type='other', **kwargs):
        _require_org_perm(info, organization_id, 'assets_create')
        if asset_type not in dict(Asset.ASSET_TYPES):
            return CreateAsset(asset=None, success=False, errors=['Unknown asset type'])
        asset = Asset.objects.create(
            name=name,
            asset_type=asset_type,
            organization_id=organization_id,
            created_by=info.context.user,
            **{key: value for key, value in kwargs.items() if value is not None}
        )
        return CreateAsset(asset=asset, success=True, errors=[])


class UpdateAsset(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)
        name = graphene.String()
        serial_number = graphene.String()
        manufacturer = graphene.String()
        model = graphene.String()

    asset = graphene.Field(AssetObjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, id, **kwargs):
        asset = _get_or_none(_scoped(Asset.objects.all(), info), id)
        if asset is None:
            return UpdateAsset(asset=None, success=False, errors=['Not found'])
        _require_org_perm(info, asset.organization_id, 'assets_edit')
        for key, value in kwargs.items():
            if value is not None:
                setattr(asset, key, value)
        asset.save()
        return UpdateAsset(asset=asset, success=True, errors=[])


class DeleteAsset(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, id):
        asset = _get_or_none(_scoped(Asset.objects.all(), info), id)
        if asset is None:
            return DeleteAsset(success=False, errors=['Not found'])
        _require_org_perm(info, asset.organization_id, 'assets_delete')
        asset.delete()
        return DeleteAsset(success=True, errors=[])


class CreateDocument(graphene.Mutation):
    class Arguments:
        title = graphene.String(required=True)
        content = graphene.String(required=True)
        organization_id = graphene.Int(required=True)

    document = graphene.Field(DocumentType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, title, content, organization_id):
        _require_org_perm(info, organization_id, 'docs_create')
        document = Document.objects.create(
            title=title,
            body=content,
            organization_id=organization_id,
            created_by=info.context.user
        )
        return CreateDocument(document=document, success=True, errors=[])


class Mutation(graphene.ObjectType):
    create_asset = CreateAsset.Field()
    update_asset = UpdateAsset.Field()
    delete_asset = DeleteAsset.Field()
    create_document = CreateDocument.Field()


# ===== Schema =====

schema = graphene.Schema(query=Query, mutation=Mutation)
