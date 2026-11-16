"""Django admin for pricing.

Access follows the pricing role permissions (not Django model permissions):
each admin names the permission that manages it. Install-wide rows (no
customer) are visible to staff holding the permission anywhere; rows scoped
to a customer only where the user holds it for that customer (client scope
applies). Internal cost fields are removed from
forms, list columns and inlines for anyone without
`pricing_view_internal_cost_rates`. Price changes made here are written to
PriceChangeHistory (by the models) and to the audit log.
"""
from django.contrib import admin

from accounts.permission_utils import orgs_with_perm

from . import permissions as perms
from .models import (
    BillingRule, ClientServicePlan, CustomerPriceOverride, LaborRole, PriceBook, PriceBookItem,
    PriceChangeHistory, PriceTier, RateCard, RateCardLine, ScheduledPriceChange, ServicePlan,
    ServicePlanEntitlement, ServicePlanItem,
)


def _audit(request, obj, action, description, extra=None):
    try:
        from audit.models import AuditLog
        AuditLog.objects.create(
            user=request.user, username=request.user.username, action=action,
            object_type=obj._meta.label, object_id=obj.pk, object_repr=str(obj)[:255],
            description=description, organization_id=getattr(obj, 'organization_id', None),
            path=request.path, extra_data=extra or {})
    except Exception:  # pragma: no cover - audit must never block the save
        import logging
        logging.getLogger(__name__).exception('pricing admin audit failed')


class PricingAdminMixin:
    """Gate by a pricing permission and the customer a row is scoped to."""
    manage_perm = perms.MANAGE_PRICE_BOOKS
    org_path = 'organization'          # lookup to the customer; NULL = install-wide
    cost_fields = ()                   # removed without view_internal_cost_rates
    tracked_fields = ()                # changes audited on save

    def _org_of(self, obj):
        if hasattr(obj, 'organization_id'):
            return obj.organization_id
        cur = obj
        for part in self.org_path.split('__'):
            cur = getattr(cur, part, None)
            if cur is None:
                return None
        return cur

    def _allowed_orgs(self, request):
        return orgs_with_perm(request.user, self.manage_perm)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        allowed = self._allowed_orgs(request)
        if allowed is None:
            return qs
        from django.db.models import Q
        scoped = Q(**{f'{self.org_path}__in': allowed})
        if perms.has(request.user, self.manage_perm):
            scoped |= Q(**{f'{self.org_path}__isnull': True})
        return qs.filter(scoped)

    def _may(self, request, obj=None):
        if not request.user.is_active or not request.user.is_staff:
            return False
        if obj is None:
            return perms.has(request.user, self.manage_perm)
        org = self._org_of(obj)
        return perms.has(request.user, self.manage_perm, org)

    def has_module_permission(self, request):
        return self._may(request)

    def has_view_permission(self, request, obj=None):
        return self._may(request, obj)

    def has_add_permission(self, request, obj=None):
        return self._may(request)

    def has_change_permission(self, request, obj=None):
        return self._may(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._may(request, obj)

    def _sees_costs(self, request, obj=None):
        org = self._org_of(obj) if obj is not None else None
        return perms.can_view_costs(request.user, org)

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or ())
        if not self._sees_costs(request, obj):
            excluded += [f for f in self.cost_fields if f not in excluded]
        return excluded

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if self._sees_costs(request, obj):
            return fields
        return [f for f in fields if f not in self.cost_fields]

    def get_list_display(self, request):
        cols = super().get_list_display(request)
        if self._sees_costs(request):
            return cols
        return [c for c in cols if c not in self.cost_fields]

    def get_list_filter(self, request):
        cols = super().get_list_filter(request)
        if self._sees_costs(request):
            return cols
        return [c for c in cols if c not in self.cost_fields]

    def get_search_fields(self, request):
        cols = super().get_search_fields(request)
        if self._sees_costs(request):
            return cols
        return [c for c in cols if c not in self.cost_fields]

    def save_model(self, request, obj, form, change):
        before = {}
        if change and obj.pk and self.tracked_fields:
            before = type(obj).objects.filter(pk=obj.pk).values(*self.tracked_fields).first() or {}
        if isinstance(obj, (PriceBookItem,)):
            obj.save(_changed_by=request.user, _history_source='admin')
        elif isinstance(obj, (CustomerPriceOverride, RateCardLine, ServicePlan)):
            obj.save(_changed_by=request.user)
        else:
            obj.save()
        diff = {f: {'from': str(before.get(f)), 'to': str(getattr(obj, f))}
                for f in self.tracked_fields if change and str(before.get(f)) != str(getattr(obj, f))}
        if not change:
            _audit(request, obj, 'create', f'Created {obj._meta.verbose_name} "{obj}"')
        elif diff:
            _audit(request, obj, 'update', f'Changed prices on {obj._meta.verbose_name} "{obj}"',
                   {'price_changes': diff})

    def delete_model(self, request, obj):
        _audit(request, obj, 'delete', f'Deleted {obj._meta.verbose_name} "{obj}"')
        super().delete_model(request, obj)


class CostGatedInline(PricingAdminMixin):
    def get_queryset(self, request):
        return admin.options.InlineModelAdmin.get_queryset(self, request)

    def has_add_permission(self, request, obj=None):
        return self._may(request, obj)

    def _org_of(self, obj):
        # Inlines receive the parent object.
        return getattr(obj, 'organization_id', None)


class PriceTierInline(CostGatedInline, admin.TabularInline):
    model = PriceTier
    extra = 0


class PriceBookItemInline(CostGatedInline, admin.TabularInline):
    model = PriceBookItem
    extra = 0
    fields = ('sku', 'name', 'item_type', 'pricing_model', 'cost', 'default_price', 'minimum_price',
              'is_active')
    cost_fields = ('cost',)
    show_change_link = True


@admin.register(PriceBook)
class PriceBookAdmin(PricingAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'organization', 'currency', 'is_active', 'is_default', 'updated_at')
    list_filter = ('is_active', 'currency')
    search_fields = ('name', 'organization__name')
    readonly_fields = ('copied_from', 'created_by', 'created_at', 'updated_at')
    inlines = [PriceBookItemInline]
    actions = ['duplicate_books']

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by_id is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description='Duplicate selected price books')
    def duplicate_books(self, request, queryset):
        for book in queryset:
            if self._may(request, book):
                copy = book.duplicate(user=request.user)
                _audit(request, copy, 'create', f'Duplicated price book "{book}" as "{copy}"')


@admin.register(PriceBookItem)
class PriceBookItemAdmin(PricingAdminMixin, admin.ModelAdmin):
    org_path = 'price_book__organization'
    cost_fields = PriceBookItem.COST_FIELDS
    tracked_fields = PriceBookItem.TRACKED_FIELDS
    list_display = ('sku', 'name', 'price_book', 'item_type', 'pricing_model', 'cost', 'default_price',
                    'minimum_price', 'is_active')
    list_filter = ('item_type', 'pricing_model', 'is_active', 'is_recurring', 'customer_visible')
    search_fields = ('sku', 'name', 'description', 'vendor_sku')
    inlines = [PriceTierInline]


@admin.register(CustomerPriceOverride)
class CustomerPriceOverrideAdmin(PricingAdminMixin, admin.ModelAdmin):
    org_path = 'client_org'
    cost_fields = ('markup_pct',)       # a markup reveals the cost relationship
    tracked_fields = ('unit_price', 'markup_pct')
    list_display = ('client_org', 'item', 'contract', 'unit_price', 'markup_pct', 'effective_from',
                    'effective_to', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('client_org__name', 'item__sku', 'item__name')

    def save_model(self, request, obj, form, change):
        # Below-minimum prices need pricing_approve_discounts; record the approver.
        item = obj.item
        if obj.unit_price is not None and item.minimum_price is not None and obj.unit_price < item.minimum_price:
            if perms.has(request.user, perms.APPROVE_DISCOUNTS, obj.organization_id):
                obj.approved_by = request.user
            else:
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied('A price below the item minimum needs discount approval.')
        super().save_model(request, obj, form, change)


@admin.register(ScheduledPriceChange)
class ScheduledPriceChangeAdmin(PricingAdminMixin, admin.ModelAdmin):
    org_path = 'item__price_book__organization'
    list_display = ('item', 'field', 'new_value', 'effective_date', 'applied_at', 'cancelled_at')
    list_filter = ('field',)
    readonly_fields = ('applied_at', 'created_by', 'created_at')
    actions = ['apply_now']

    def save_model(self, request, obj, form, change):
        if obj.field == 'cost' and not self._sees_costs(request, obj):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('Scheduling a cost change needs pricing_view_internal_cost_rates.')
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not self._sees_costs(request):
            qs = qs.exclude(field='cost')
        return qs

    @admin.action(description='Apply selected changes now')
    def apply_now(self, request, queryset):
        for change in queryset:
            if change.apply(user=request.user):
                _audit(request, change.item, 'update', f'Applied scheduled price change "{change}"')


@admin.register(PriceChangeHistory)
class PriceChangeHistoryAdmin(PricingAdminMixin, admin.ModelAdmin):
    list_display = ('changed_at', 'object_type', 'object_repr', 'field', 'old_value', 'new_value',
                    'changed_by_username', 'source')
    list_filter = ('object_type', 'field', 'source')
    search_fields = ('object_repr', 'changed_by_username')

    COST_HISTORY_FIELDS = ('cost', 'target_margin_pct', 'markup_pct')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not self._sees_costs(request):
            qs = qs.exclude(field__in=self.COST_HISTORY_FIELDS)
        return qs

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ServicePlanItemInline(CostGatedInline, admin.TabularInline):
    model = ServicePlanItem
    manage_perm = perms.MANAGE_SERVICE_PLANS
    extra = 0


class ServicePlanEntitlementInline(CostGatedInline, admin.TabularInline):
    model = ServicePlanEntitlement
    manage_perm = perms.MANAGE_SERVICE_PLANS
    extra = 0


@admin.register(ServicePlan)
class ServicePlanAdmin(PricingAdminMixin, admin.ModelAdmin):
    manage_perm = perms.MANAGE_SERVICE_PLANS
    tracked_fields = ServicePlan.PRICE_FIELDS
    list_display = ('name', 'organization', 'is_addon', 'monthly_price', 'per_user_price', 'per_device_price',
                    'is_active')
    list_filter = ('is_addon', 'is_active')
    search_fields = ('name', 'code')
    inlines = [ServicePlanItemInline, ServicePlanEntitlementInline]


@admin.register(ClientServicePlan)
class ClientServicePlanAdmin(PricingAdminMixin, admin.ModelAdmin):
    manage_perm = perms.MANAGE_SERVICE_PLANS
    org_path = 'client_org'
    list_display = ('client_org', 'plan', 'role', 'status', 'start_date', 'end_date')
    list_filter = ('role', 'status')
    search_fields = ('client_org__name', 'plan__name')


@admin.register(LaborRole)
class LaborRoleAdmin(PricingAdminMixin, admin.ModelAdmin):
    manage_perm = perms.MANAGE_LABOR_RATE_CARDS
    tracked_fields = ('default_bill_rate',)
    list_display = ('name', 'code', 'organization', 'default_bill_rate', 'is_active')
    search_fields = ('name', 'code')


class RateCardLineInline(CostGatedInline, admin.TabularInline):
    model = RateCardLine
    manage_perm = perms.MANAGE_LABOR_RATE_CARDS
    extra = 0


@admin.register(RateCard)
class RateCardAdmin(PricingAdminMixin, admin.ModelAdmin):
    manage_perm = perms.MANAGE_LABOR_RATE_CARDS
    org_path = 'client_org'
    list_display = ('name', 'scope', 'client_org', 'contract', 'effective_from',
                    'effective_to', 'is_active')
    list_filter = ('scope', 'is_active')
    search_fields = ('name', 'client_org__name')
    readonly_fields = ('scope',)
    inlines = [RateCardLineInline]

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for inst in instances:
            if isinstance(inst, RateCardLine):
                before = None
                if inst.pk:
                    before = RateCardLine.objects.filter(pk=inst.pk).values_list('hourly_rate', flat=True).first()
                inst.save(_changed_by=request.user)
                if before is not None and str(before) != str(inst.hourly_rate):
                    _audit(request, inst, 'update', f'Changed labor rate "{inst}"',
                           {'price_changes': {'hourly_rate': {'from': str(before), 'to': str(inst.hourly_rate)}}})
            else:
                inst.save()
        formset.save_m2m()


@admin.register(BillingRule)
class BillingRuleAdmin(PricingAdminMixin, admin.ModelAdmin):
    manage_perm = perms.MANAGE_LABOR_RATE_CARDS
    org_path = 'client_org'
    tracked_fields = ('travel_fee', 'dispatch_fee', 'emergency_premium_pct')
    list_display = ('name', 'client_org', 'contract', 'minimum_billable_minutes',
                    'increment_minutes', 'rounding_mode', 'is_active')
    list_filter = ('rounding_mode', 'is_active')
