"""
AI model profiles and customer AI policies for Ticket AI Assist.

Security administrators only. API keys are write-only: a key typed here is
sealed to the AI gateway's public key at once and can't be shown again, by
this page or anything else in the web app. An Ollama profile's address
reaches the gateway only after a protected change approves it.
"""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from audit.models import AuditLog
from core.models import Organization

from .models import AIBusinessPolicy, AIModelProfile
from .services import gateway_keys


def _admin(user):
    return user.is_authenticated and user.is_active and user.is_superuser


class ProfileForm(forms.ModelForm):
    api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
                              help_text='Write-only. Leave blank to keep the stored key.')
    clear_key = forms.BooleanField(required=False, label='Remove the stored key')

    class Meta:
        model = AIModelProfile
        fields = ['name', 'provider', 'model', 'enabled', 'economical', 'base_url', 'credential_owner',
                  'owner_organization', 'owner_user', 'assigned_organizations', 'input_price_per_1k',
                  'output_price_per_1k', 'max_output_tokens']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from tech_access.resolver import is_technician
        self.fields['owner_user'].queryset = get_user_model().objects.filter(
            pk__in=[u.pk for u in get_user_model().objects.filter(is_active=True) if is_technician(u)])
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-check-input' if isinstance(f.widget, forms.CheckboxInput)
                                      else 'form-select' if isinstance(f.widget, (forms.Select, forms.SelectMultiple))
                                      else 'form-control')

    def clean(self):
        c = super().clean()
        owner = c.get('credential_owner')
        if owner == AIModelProfile.OWNER_COMPANY and not c.get('owner_organization'):
            self.add_error('owner_organization', 'A company key belongs to one customer.')
        if owner == AIModelProfile.OWNER_TECHNICIAN and not c.get('owner_user'):
            self.add_error('owner_user', "A technician key names the technician.")
        if c.get('provider') == 'ollama' and not c.get('base_url'):
            self.add_error('base_url', 'Ollama needs its address.')
        return c


class PolicyForm(forms.ModelForm):
    class Meta:
        model = AIBusinessPolicy
        fields = ['analysis_enabled', 'compare_enabled', 'allowed_profiles', 'default_profile',
                  'allow_technician_credentials', 'local_only', 'daily_budget_cents']

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-check-input' if isinstance(f.widget, forms.CheckboxInput)
                                      else 'form-select' if isinstance(f.widget, (forms.Select, forms.SelectMultiple))
                                      else 'form-control')


def _status():
    configured = gateway_keys.configured()
    mode = gateway_keys.mode()
    if not configured:
        text = 'No gateway key pair yet: run manage.py ai_gateway_keygen. API keys cannot be stored until then.'
    elif mode == 'worker':
        text = ('Isolated: provider keys are opened only by the AI gateway worker, which runs without the '
                'vault master key.')
    else:
        text = ('Not isolated: the web app opens provider keys itself (AI_GATEWAY_MODE=in_process). Set '
                'AI_GATEWAY_MODE=worker and run the ai_gateway_worker service to isolate them.')
    return {'configured': configured, 'mode': mode, 'text': text}


@login_required
@user_passes_test(_admin)
def profiles(request):
    edit = AIModelProfile.objects.filter(pk=request.GET.get('edit')).first() if request.GET.get('edit') else None
    if request.method == 'POST' and request.POST.get('action') == 'profile':
        edit = AIModelProfile.objects.filter(pk=request.POST.get('pk')).first() if request.POST.get('pk') else None
        form = ProfileForm(request.POST, instance=edit)
        if form.is_valid():
            before = edit.base_url if edit else None
            profile = form.save(commit=False)
            try:
                if form.cleaned_data.get('clear_key'):
                    profile.sealed_api_key = ''
                elif form.cleaned_data.get('api_key'):
                    profile.set_api_key(form.cleaned_data['api_key'])
            except gateway_keys.GatewayKeyError as e:
                messages.error(request, str(e))
                return redirect(request.path)
            if before is not None and before != profile.base_url:
                # A new address is unapproved until a protected change says otherwise.
                profile.approved_destination, profile.local_approved = '', False
            profile.save()
            form.save_m2m()
            AuditLog.log(user=request.user, action='update' if edit else 'create', object_type='ai_model_profile',
                         object_id=profile.pk, object_repr=profile.name, description=f'AI profile {profile.name} saved',
                         extra_data={'provider': profile.provider, 'model': profile.model,
                                     'key_changed': bool(form.cleaned_data.get('api_key') or form.cleaned_data.get('clear_key'))})
            messages.success(request, f'{profile.name} saved.')
            return redirect(request.path)
    else:
        form = ProfileForm(instance=edit)
    if request.method == 'POST' and request.POST.get('action') == 'approve_destination':
        from tech_access.services import propose_destination
        profile = get_object_or_404(AIModelProfile, pk=request.POST.get('pk'), provider='ollama')
        try:
            change = propose_destination(profile, request.user, request)
            messages.warning(request, f'Protected change #{change.pk} created. Confirm it under Settings → '
                                      'Security → Technician Access; a second administrator approves it.')
        except ValueError as e:
            messages.error(request, str(e))
        return redirect(request.path)
    return render(request, 'psa_ai/profiles.html', {
        'profiles': AIModelProfile.objects.prefetch_related('assigned_organizations'),
        'form': form, 'edit': edit, 'gateway': _status(),
        'organizations': Organization.objects.filter(is_active=True).order_by('name'),
        'policies': {p.organization_id: p for p in AIBusinessPolicy.objects.prefetch_related('allowed_profiles')},
    })


@login_required
@user_passes_test(_admin)
def policy(request, org_id):
    org = get_object_or_404(Organization, pk=org_id)
    instance = AIBusinessPolicy.objects.filter(organization=org).first() or AIBusinessPolicy(organization=org)
    form = PolicyForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        p = form.save()
        AuditLog.log(user=request.user, action='update', organization=org, object_type='ai_business_policy',
                     object_id=p.pk, object_repr=f'AI policy for {org.name}', description=f'AI policy for {org.name} saved',
                     extra_data={'analysis': p.analysis_enabled, 'compare': p.compare_enabled,
                                 'local_only': p.local_only, 'budget_cents': p.daily_budget_cents,
                                 'profiles': list(p.allowed_profiles.values_list('pk', flat=True))})
        messages.success(request, f'AI policy for {org.name} saved.')
        return redirect('psa_ai:profiles')
    return render(request, 'psa_ai/policy.html', {'form': form, 'organization': org})


# --- technicians' own keys ----------------------------------------------------
# A technician may add a cloud model profile on their own provider account.
# It is usable only by them, only on customers whose AI policy allows
# technicians' own keys (and never under a local-only policy). The key is
# sealed exactly like an administrator's and can't be shown again.

class OwnKeyForm(forms.ModelForm):
    api_key = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False),
                              help_text='Write-only. Leave blank to keep the stored key.')

    class Meta:
        model = AIModelProfile
        fields = ['provider', 'model', 'enabled', 'input_price_per_1k', 'output_price_per_1k', 'max_output_tokens']
        labels = {'input_price_per_1k': 'Input price (1/100 ¢ per 1k tokens)',
                  'output_price_per_1k': 'Output price (1/100 ¢ per 1k tokens)'}

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.fields['provider'].choices = [c for c in AIModelProfile.PROVIDER_CHOICES if c[0] != 'ollama']
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'form-check-input' if isinstance(f.widget, forms.CheckboxInput)
                                      else 'form-select' if isinstance(f.widget, forms.Select)
                                      else 'form-control')

    def clean_model(self):
        import re
        model = (self.cleaned_data.get('model') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,99}', model):
            raise forms.ValidationError('Use the provider\'s model ID, for example claude-haiku-5-5.')
        return model

    def clean(self):
        c = super().clean()
        if not self.instance.pk and not c.get('api_key'):
            self.add_error('api_key', 'A new profile needs its API key.')
        return c


def _own_name(user, model, exclude_pk=None):
    base = f'{user.get_username()} · {model}'[:90]
    name, n = base, 2
    while AIModelProfile.objects.filter(name=name).exclude(pk=exclude_pk).exists():
        name, n = f'{base} ({n})', n + 1
    return name


def _assigned_org_ids(user):
    from django.db.models import Q
    from tech_access.models import AccessAssignment
    return set(AccessAssignment.objects.live().filter(Q(user=user) | Q(group__members=user))
               .values_list('organization_id', flat=True))


@login_required
def own_keys(request):
    from core.ai_gate import ai_features_enabled
    from tech_access.resolver import is_technician
    # Technicians, plus superusers (a key they add is still usable only on
    # tickets where technician access lets them run analysis).
    if not (is_technician(request.user) or request.user.is_superuser):
        raise Http404
    mine = AIModelProfile.objects.filter(credential_owner=AIModelProfile.OWNER_TECHNICIAN, owner_user=request.user)
    edit = mine.filter(pk=request.GET.get('edit') or request.POST.get('pk') or 0).first()
    form = OwnKeyForm(instance=edit)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'delete' and edit:
            AuditLog.log(user=request.user, action='delete', object_type='ai_model_profile', object_id=edit.pk,
                         object_repr=edit.name, description=f'Own AI key {edit.name} deleted')
            edit.delete()
            messages.success(request, 'Profile and key deleted.')
            return redirect(request.path)
        if action == 'save':
            form = OwnKeyForm(request.POST, instance=edit)
            if form.is_valid():
                profile = form.save(commit=False)
                profile.credential_owner, profile.owner_user = AIModelProfile.OWNER_TECHNICIAN, request.user
                profile.owner_organization, profile.base_url = None, ''
                profile.approved_destination, profile.local_approved, profile.economical = '', False, False
                profile.name = _own_name(request.user, profile.model, exclude_pk=profile.pk)
                try:
                    if form.cleaned_data.get('api_key'):
                        profile.set_api_key(form.cleaned_data['api_key'])
                except gateway_keys.GatewayKeyError as e:
                    messages.error(request, str(e))
                    return redirect(request.path)
                created = profile.pk is None
                profile.save()
                AuditLog.log(user=request.user, action='create' if created else 'update',
                             object_type='ai_model_profile', object_id=profile.pk, object_repr=profile.name,
                             description=f'Own AI key {profile.name} saved',
                             extra_data={'provider': profile.provider, 'model': profile.model,
                                         'key_changed': bool(form.cleaned_data.get('api_key'))})
                messages.success(request, f'{profile.name} saved.')
                return redirect(request.path)
    return render(request, 'psa_ai/own_keys.html', {
        'profiles': mine.order_by('name'), 'form': form, 'edit': edit, 'gateway': _status(),
        'ai_enabled': ai_features_enabled(),
        'allowing': Organization.objects.filter(
            pk__in=_assigned_org_ids(request.user), ai_policy__allow_technician_credentials=True,
            ai_policy__local_only=False).order_by('name'),
    })
