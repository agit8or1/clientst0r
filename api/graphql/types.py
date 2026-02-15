"""
Custom GraphQL Types for Client St0r
"""

import graphene


class DashboardStatsType(graphene.ObjectType):
    """Dashboard statistics"""
    total_organizations = graphene.Int()
    total_assets = graphene.Int()
    total_passwords = graphene.Int()
    total_documents = graphene.Int()
    total_diagrams = graphene.Int()
    active_monitors = graphene.Int()


class HealthCheckType(graphene.ObjectType):
    """System health check"""
    status = graphene.String()
    database = graphene.Boolean()
    cache = graphene.Boolean()
    version = graphene.String()
    uptime = graphene.String()


class SearchResultType(graphene.ObjectType):
    """Universal search result"""
    type = graphene.String()
    id = graphene.Int()
    title = graphene.String()
    description = graphene.String()
    url = graphene.String()
    organization_id = graphene.Int()
    organization_name = graphene.String()
