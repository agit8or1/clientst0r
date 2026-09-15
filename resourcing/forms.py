"""
ModelForms for the resourcing app. Bootstrap-ready widgets so the same
partials work for add + edit.
"""
from django import forms

from .models import (
    BillableTarget, Holiday, LeaveRequest, TechCostRate, UserSkill,
    UserCertification, WorkingHours,
)


_BS_CTRL = {'class': 'form-control'}
_BS_SELECT = {'class': 'form-select'}
_BS_CHECK = {'class': 'form-check-input'}


class UserSkillForm(forms.ModelForm):
    class Meta:
        model = UserSkill
        fields = ['name', 'proficiency', 'years_experience', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={**_BS_CTRL, 'placeholder': 'e.g. Active Directory, Azure, Networking'}),
            'proficiency': forms.Select(attrs=_BS_SELECT),
            'years_experience': forms.NumberInput(attrs={**_BS_CTRL, 'min': 0, 'max': 60}),
            'notes': forms.Textarea(attrs={**_BS_CTRL, 'rows': 2}),
        }


class UserCertificationForm(forms.ModelForm):
    class Meta:
        model = UserCertification
        fields = [
            'name', 'issuer', 'credential_id',
            'issued_at', 'expires_at',
            'verification_url', 'attachment',
        ]
        widgets = {
            'name': forms.TextInput(attrs=_BS_CTRL),
            'issuer': forms.TextInput(attrs=_BS_CTRL),
            'credential_id': forms.TextInput(attrs=_BS_CTRL),
            'issued_at': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'expires_at': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'verification_url': forms.URLInput(attrs=_BS_CTRL),
            'attachment': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }


class WorkingHoursForm(forms.ModelForm):
    class Meta:
        model = WorkingHours
        fields = ['weekday', 'start_time', 'end_time', 'is_active', 'notes']
        widgets = {
            'weekday': forms.Select(attrs=_BS_SELECT),
            'start_time': forms.TimeInput(attrs={**_BS_CTRL, 'type': 'time'}),
            'end_time': forms.TimeInput(attrs={**_BS_CTRL, 'type': 'time'}),
            'is_active': forms.CheckboxInput(attrs=_BS_CHECK),
            'notes': forms.TextInput(attrs={**_BS_CTRL, 'placeholder': 'Optional — e.g. "afternoon shift"'}),
        }


class HolidayForm(forms.ModelForm):
    """Holiday create/edit.

    Takes the request so the organization choices can be bounded by
    membership. Without that, the select listed every tenant, letting anyone
    with `resourcing_manage_holidays` create a holiday inside another client —
    or move an existing one there — regardless of which organizations they
    actually belong to.

    A NULL organization means "every tenant" (a national holiday). That option
    stays available only to cross-tenant users, because a member of one client
    should not be able to create or reassign a row that applies to all of them.
    """

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        if request is None:
            return

        from core.models import Organization
        from core.tenancy import accessible_org_ids, is_cross_tenant_user

        allowed = accessible_org_ids(request)
        field = self.fields.get('organization')
        if field is None:
            return
        if allowed is not None:
            field.queryset = Organization.objects.filter(id__in=allowed).order_by('name')
        if not is_cross_tenant_user(request):
            # Remove the blank "applies to every org" choice.
            field.required = True
            field.empty_label = None

    def clean_organization(self):
        """Re-check server-side: a narrowed queryset is a UI affordance, and
        the POSTed value still has to be verified."""
        org = self.cleaned_data.get('organization')
        request = getattr(self, 'request', None)
        if request is None:
            return org

        from core.tenancy import accessible_org_ids, is_cross_tenant_user
        if is_cross_tenant_user(request):
            return org
        allowed = accessible_org_ids(request)
        if org is None:
            raise forms.ValidationError(
                'Choose an organization. Holidays that apply to every '
                'organization can only be set by an administrator.'
            )
        if allowed is not None and org.id not in allowed:
            raise forms.ValidationError(
                'You do not have access to that organization.'
            )
        return org

    class Meta:
        model = Holiday
        fields = ['organization', 'name', 'date', 'is_recurring_yearly', 'notes']
        widgets = {
            'organization': forms.Select(attrs=_BS_SELECT),
            'name': forms.TextInput(attrs={**_BS_CTRL, 'placeholder': 'e.g. New Year\'s Day'}),
            'date': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'is_recurring_yearly': forms.CheckboxInput(attrs=_BS_CHECK),
            'notes': forms.TextInput(attrs=_BS_CTRL),
        }


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['leave_type', 'start_date', 'end_date', 'is_half_day', 'notes']
        widgets = {
            'leave_type': forms.Select(attrs=_BS_SELECT),
            'start_date': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'end_date': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'is_half_day': forms.CheckboxInput(attrs=_BS_CHECK),
            'notes': forms.Textarea(attrs={**_BS_CTRL, 'rows': 3,
                                           'placeholder': 'Optional — context for the approver'}),
        }


class BillableTargetForm(forms.ModelForm):
    class Meta:
        model = BillableTarget
        fields = ['target_hours_per_week', 'is_active', 'notes']
        widgets = {
            'target_hours_per_week': forms.NumberInput(attrs={**_BS_CTRL, 'min': '0', 'max': '60', 'step': '0.5'}),
            'is_active': forms.CheckboxInput(attrs=_BS_CHECK),
            'notes': forms.TextInput(attrs=_BS_CTRL),
        }


class TechCostRateForm(forms.ModelForm):
    class Meta:
        model = TechCostRate
        fields = ['rate_per_hour', 'effective_from', 'notes']
        widgets = {
            'rate_per_hour': forms.NumberInput(attrs={**_BS_CTRL, 'min': '0', 'step': '0.01',
                                                      'placeholder': 'e.g. 65.00'}),
            'effective_from': forms.DateInput(attrs={**_BS_CTRL, 'type': 'date'}),
            'notes': forms.TextInput(attrs={**_BS_CTRL,
                                            'placeholder': 'Optional — e.g. "annual raise", "promotion to T3"'}),
        }
