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
        fields = '__all__'

    def resolve_asset_count(self, info):
        return self.asset_set.count() if hasattr(self, 'asset_set') else 0

    def resolve_password_count(self, info):
        return self.password_set.count() if hasattr(self, 'password_set') else 0


class AssetTypeType(DjangoObjectType):
    class Meta:
        model = AssetType
        fields = '__all__'


class AssetObjectType(DjangoObjectType):
    class Meta:
        model = Asset
        fields = '__all__'


class PasswordType(DjangoObjectType):
    # Don't expose the actual password value
    class Meta:
        model = Password
        exclude = ('password', 'totp_secret')


class DocumentType(DjangoObjectType):
    class Meta:
        model = Document
        fields = '__all__'


class DiagramType(DjangoObjectType):
    class Meta:
        model = Diagram
        fields = '__all__'


class LocationType(DjangoObjectType):
    class Meta:
        model = Location
        fields = '__all__'


class WebsiteMonitorType(DjangoObjectType):
    class Meta:
        model = WebsiteMonitor
        fields = '__all__'


class ExpirationType(DjangoObjectType):
    days_until_expiry = graphene.Int()

    class Meta:
        model = Expiration
        fields = '__all__'

    def resolve_days_until_expiry(self, info):
        from datetime import date
        if self.expiration_date:
            delta = self.expiration_date - date.today()
            return delta.days
        return None


class DashboardStatsType(graphene.ObjectType):
    total_organizations = graphene.Int()
    total_assets = graphene.Int()
    total_passwords = graphene.Int()
    total_documents = graphene.Int()
    total_diagrams = graphene.Int()
    active_monitors = graphene.Int()


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
        return User.objects.get(pk=id)

    @login_required
    def resolve_users(self, info):
        return User.objects.all()

    @login_required
    def resolve_my_organization(self, info):
        user = info.context.user
        return getattr(user, 'organization', None)

    @login_required
    def resolve_organization(self, info, id):
        return Organization.objects.get(pk=id)

    @login_required
    def resolve_organizations(self, info):
        user = info.context.user
        if user.is_superuser:
            return Organization.objects.all()
        if hasattr(user, 'organization'):
            return Organization.objects.filter(pk=user.organization.pk)
        return Organization.objects.none()

    @login_required
    def resolve_asset(self, info, id):
        return Asset.objects.get(pk=id)

    @login_required
    def resolve_assets(self, info, organization_id=None):
        queryset = Asset.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_asset_types(self, info):
        return AssetType.objects.all()

    @login_required
    def resolve_password(self, info, id):
        return Password.objects.get(pk=id)

    @login_required
    def resolve_passwords(self, info, organization_id=None):
        queryset = Password.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_document(self, info, id):
        return Document.objects.get(pk=id)

    @login_required
    def resolve_documents(self, info, organization_id=None):
        queryset = Document.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_diagram(self, info, id):
        return Diagram.objects.get(pk=id)

    @login_required
    def resolve_diagrams(self, info, organization_id=None):
        queryset = Diagram.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_location(self, info, id):
        return Location.objects.get(pk=id)

    @login_required
    def resolve_locations(self, info):
        return Location.objects.all()

    @login_required
    def resolve_website_monitor(self, info, id):
        return WebsiteMonitor.objects.get(pk=id)

    @login_required
    def resolve_website_monitors(self, info, organization_id=None):
        queryset = WebsiteMonitor.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_expirations(self, info, organization_id=None):
        queryset = Expiration.objects.all()
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)
        return queryset

    @login_required
    def resolve_expiring_soon(self, info, days=30):
        from datetime import date, timedelta
        cutoff_date = date.today() + timedelta(days=days)
        return Expiration.objects.filter(
            expiration_date__lte=cutoff_date,
            expiration_date__gte=date.today()
        ).order_by('expiration_date')

    @login_required
    def resolve_dashboard_stats(self, info):
        user = info.context.user

        # Get user's organization
        if user.is_superuser:
            orgs = Organization.objects.all()
        elif hasattr(user, 'organization'):
            orgs = Organization.objects.filter(pk=user.organization.pk)
        else:
            orgs = Organization.objects.none()

        return DashboardStatsType(
            total_organizations=orgs.count(),
            total_assets=Asset.objects.filter(organization__in=orgs).count(),
            total_passwords=Password.objects.filter(organization__in=orgs).count(),
            total_documents=Document.objects.filter(organization__in=orgs).count(),
            total_diagrams=Diagram.objects.filter(organization__in=orgs).count(),
            active_monitors=WebsiteMonitor.objects.filter(
                organization__in=orgs,
                is_active=True
            ).count() if hasattr(WebsiteMonitor, 'is_active') else 0,
        )


# ===== Mutations =====

class CreateAsset(graphene.Mutation):
    class Arguments:
        name = graphene.String(required=True)
        asset_type_id = graphene.Int(required=True)
        organization_id = graphene.Int(required=True)
        description = graphene.String()
        serial_number = graphene.String()
        manufacturer = graphene.String()
        model = graphene.String()

    asset = graphene.Field(AssetObjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, name, asset_type_id, organization_id, **kwargs):
        try:
            asset = Asset.objects.create(
                name=name,
                asset_type_id=asset_type_id,
                organization_id=organization_id,
                created_by=info.context.user,
                **kwargs
            )
            return CreateAsset(asset=asset, success=True, errors=[])
        except Exception as e:
            return CreateAsset(asset=None, success=False, errors=[str(e)])


class UpdateAsset(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)
        name = graphene.String()
        description = graphene.String()
        serial_number = graphene.String()
        manufacturer = graphene.String()
        model = graphene.String()
        is_active = graphene.Boolean()

    asset = graphene.Field(AssetObjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, id, **kwargs):
        try:
            asset = Asset.objects.get(pk=id)
            for key, value in kwargs.items():
                if value is not None:
                    setattr(asset, key, value)
            asset.save()
            return UpdateAsset(asset=asset, success=True, errors=[])
        except Exception as e:
            return UpdateAsset(asset=None, success=False, errors=[str(e)])


class DeleteAsset(graphene.Mutation):
    class Arguments:
        id = graphene.Int(required=True)

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, id):
        try:
            asset = Asset.objects.get(pk=id)
            asset.delete()
            return DeleteAsset(success=True, errors=[])
        except Exception as e:
            return DeleteAsset(success=False, errors=[str(e)])


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
        try:
            document = Document.objects.create(
                title=title,
                content=content,
                organization_id=organization_id,
                created_by=info.context.user
            )
            return CreateDocument(document=document, success=True, errors=[])
        except Exception as e:
            return CreateDocument(document=None, success=False, errors=[str(e)])


class Mutation(graphene.ObjectType):
    create_asset = CreateAsset.Field()
    update_asset = UpdateAsset.Field()
    delete_asset = DeleteAsset.Field()
    create_document = CreateDocument.Field()


# ===== Schema =====

schema = graphene.Schema(query=Query, mutation=Mutation)
