"""
Core utilities
"""
from django.db import models


def ancestor_org_ids(organization):
    """
    Phase 18 v2 (v3.17.252): return the set of organization IDs walking
    UPWARD from `organization` via `Organization.parent`. Includes self.
    Walks up to 5 levels deep. Used to find ancestors whose shared
    infrastructure should propagate down to the requesting org.
    """
    if organization is None:
        return set()
    seen = {organization.pk}
    node = organization.parent
    for _ in range(5):
        if node is None or node.pk in seen:
            break
        seen.add(node.pk)
        node = node.parent
    return seen


def descendant_org_ids(organization):
    """
    Phase 18 (v3.17.240): return the set of organization IDs visible
    when scoping to `organization` — i.e. the org itself plus all
    descendants reachable via `Organization.parent`.

    Walks up to 5 levels deep (defense against accidental cycles) and
    breaks early once a level produces no new IDs. Returns a set so
    callers can use it in `__in=` filters.

    Lazy import on Organization to avoid a circular import at module
    load time (core.utils is imported very early in the boot sequence).
    """
    from .models import Organization
    if organization is None:
        return set()
    # Accepts an Organization or a bare primary key, so callers that already
    # hold an id (core.tenancy) do not have to re-fetch the row just to walk
    # the tree.
    root_pk = organization.pk if hasattr(organization, 'pk') else organization
    seen = {root_pk}
    frontier = [root_pk]
    for _ in range(5):
        children = list(
            Organization.objects.filter(parent_id__in=frontier)
                                 .values_list('pk', flat=True)
        )
        new = [pk for pk in children if pk not in seen]
        if not new:
            break
        seen.update(new)
        frontier = new
    return seen


class OrganizationQuerySet(models.QuerySet):
    """
    QuerySet that filters by organization automatically.
    """
    def for_organization(self, organization, *, include_descendants=True):
        """
        Filter rows to those owned by `organization`. When
        `include_descendants=True` (default, Phase 18), also include
        rows owned by any descendant via `Organization.parent`.

        Pass `include_descendants=False` for legacy strict scoping when
        a caller needs to address the org alone.
        """
        if include_descendants:
            ids = descendant_org_ids(organization)
            return self.filter(organization_id__in=ids)
        return self.filter(organization=organization)


class OrganizationManager(models.Manager):
    """
    Manager that provides organization filtering.
    """
    def get_queryset(self):
        return OrganizationQuerySet(self.model, using=self._db)

    def for_organization(self, organization, *, include_descendants=True):
        return self.get_queryset().for_organization(
            organization, include_descendants=include_descendants,
        )
