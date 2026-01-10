"""
Core utilities
"""
from django.db import models


class OrganizationQuerySet(models.QuerySet):
    """
    QuerySet that filters by organization automatically.
    """
    def for_organization(self, organization):
        return self.filter(organization=organization)


class OrganizationManager(models.Manager):
    """
    Manager that provides organization filtering.
    """
    def get_queryset(self):
        return OrganizationQuerySet(self.model, using=self._db)

    def for_organization(self, organization):
        return self.get_queryset().for_organization(organization)
