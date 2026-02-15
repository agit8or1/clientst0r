"""
GraphQL Middleware for Client St0r
"""

from django.contrib.auth.models import AnonymousUser
from graphql import GraphQLError


class AuthenticationMiddleware:
    """Ensure user is authenticated for protected queries"""

    def resolve(self, next, root, info, **kwargs):
        if info.context.user.is_anonymous:
            # Allow introspection queries
            if info.field_name in ['__schema', '__type']:
                return next(root, info, **kwargs)

            # Check if this is a public query
            public_queries = ['login', 'register']
            if info.field_name not in public_queries:
                raise GraphQLError('Authentication required')

        return next(root, info, **kwargs)


class PermissionMiddleware:
    """Check user permissions for queries"""

    def resolve(self, next, root, info, **kwargs):
        # Add custom permission checks here
        return next(root, info, **kwargs)


class LoggingMiddleware:
    """Log GraphQL queries for debugging"""

    def resolve(self, next, root, info, **kwargs):
        # Log query execution
        print(f'GraphQL Query: {info.field_name}')
        return next(root, info, **kwargs)
