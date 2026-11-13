from django import forms
from django.contrib.auth.models import User

from accounts.models import RoleTemplate
from assets.models import Contact
from core.models import Organization

from .audience import EXCLUDED_ORG_TYPES
from .models import PulseCheck, PulseQuestion

MAX_QUESTIONS = 12


class PulseCheckForm(forms.ModelForm):
    audience_roles = forms.MultipleChoiceField(
        choices=PulseCheck.ROLE_GROUP_CHOICES, required=False,
        widget=forms.CheckboxSelectMultiple, label='Role groups')

    class Meta:
        model = PulseCheck
        fields = ['name', 'intro', 'is_active', 'schedule', 'send_day', 'starts_on', 'response_days',
                  'all_organizations', 'organizations', 'audience', 'audience_roles',
                  'audience_role_templates', 'include_contacts', 'specific_users', 'specific_contacts']
        widgets = {
            'intro': forms.Textarea(attrs={'rows': 3}),
            'starts_on': forms.DateInput(attrs={'type': 'date'}),
            'audience': forms.RadioSelect,
            'organizations': forms.SelectMultiple(attrs={'size': 8}),
            'audience_role_templates': forms.SelectMultiple(attrs={'size': 5}),
            'specific_users': forms.SelectMultiple(attrs={'size': 8}),
            'specific_contacts': forms.SelectMultiple(attrs={'size': 8}),
        }

    def __init__(self, *args, allowed_org_ids=None, **kwargs):
        """`allowed_org_ids`: the organizations this staff member may reach
        (None = all). Choices are narrowed to them, and "all clients" is only
        offered to staff without a client scope."""
        super().__init__(*args, **kwargs)
        self.allowed_org_ids = allowed_org_ids
        orgs = Organization.objects.filter(is_active=True).exclude(
            organization_type__in=EXCLUDED_ORG_TYPES).order_by('name')
        if allowed_org_ids is not None:
            orgs = orgs.filter(pk__in=allowed_org_ids)
        self.fields['organizations'].queryset = orgs
        from psa.visibility import msp_staff_q
        users = (User.objects.filter(is_active=True, email__gt='',
                                     memberships__is_active=True,
                                     memberships__organization__in=orgs)
                 .exclude(pk__in=User.objects.filter(msp_staff_q()))
                 .distinct().order_by('last_name', 'first_name', 'username'))
        self.fields['specific_users'].queryset = users
        self.fields['specific_users'].label_from_instance = (
            lambda u: f'{u.get_full_name() or u.username} <{u.email}>')
        contacts = (Contact.objects.filter(organization__in=orgs, email__gt='')
                    .select_related('organization').order_by('organization__name', 'last_name'))
        self.fields['specific_contacts'].queryset = contacts
        self.fields['specific_contacts'].label_from_instance = (
            lambda c: f'{c.organization.name}: {c.first_name} {c.last_name} <{c.email}>')
        templates = RoleTemplate.objects.all().order_by('name')
        if allowed_org_ids is not None:
            from django.db.models import Q
            templates = templates.filter(Q(organization__isnull=True) | Q(organization_id__in=allowed_org_ids))
        self.fields['audience_role_templates'].queryset = templates
        self.fields['audience_role_templates'].label = 'Named roles'
        if allowed_org_ids is not None:
            self.fields['all_organizations'].disabled = True
            self.fields['all_organizations'].help_text = (
                'Only available to staff who can reach every client.')
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(w, (forms.CheckboxInput,)):
                w.attrs.setdefault('class', 'form-check-input')
            elif isinstance(w, (forms.RadioSelect, forms.CheckboxSelectMultiple)):
                continue
            elif isinstance(w, forms.Select) and not isinstance(w, forms.SelectMultiple):
                w.attrs.setdefault('class', 'form-select')
            else:
                w.attrs.setdefault('class', 'form-control')

    def clean_send_day(self):
        day = self.cleaned_data.get('send_day') or 1
        if not 1 <= day <= 28:
            raise forms.ValidationError('Pick a day from 1 to 28.')
        return day

    def clean_response_days(self):
        days = self.cleaned_data.get('response_days') or 14
        if not 1 <= days <= 90:
            raise forms.ValidationError('Pick 1 to 90 days.')
        return days

    def clean(self):
        data = super().clean()
        if self.allowed_org_ids is not None:
            data['all_organizations'] = False
        if not data.get('all_organizations') and not data.get('organizations'):
            self.add_error('organizations', 'Choose at least one organization, or all clients.')
        aud = data.get('audience')
        if aud == PulseCheck.AUDIENCE_ROLES and not (data.get('audience_roles')
                                                     or data.get('audience_role_templates')):
            self.add_error('audience_roles', 'Choose at least one role group or named role.')
        if aud == PulseCheck.AUDIENCE_SPECIFIC and not (data.get('specific_users')
                                                        or data.get('specific_contacts')):
            self.add_error('specific_users', 'Choose at least one person.')
        return data


def parse_questions(post):
    """Question rows from the form: q_text_N, q_kind_N, q_required_N.
    Returns ``(rows, errors)``; blank rows are dropped."""
    rows, errors = [], []
    kinds = dict(PulseQuestion.KIND_CHOICES)
    for i in range(MAX_QUESTIONS):
        text = (post.get(f'q_text_{i}') or '').strip()
        if not text:
            continue
        kind = post.get(f'q_kind_{i}') or PulseQuestion.KIND_RATING
        if kind not in kinds:
            errors.append(f'Unknown question type for "{text[:40]}".')
            continue
        rows.append({'text': text[:500], 'kind': kind, 'required': post.get(f'q_required_{i}') == 'on'})
    if not rows:
        errors.append('Add at least one question.')
    return rows, errors


def question_rows(check=None, posted=None):
    """Rows to draw in the editor: existing (or posted) questions plus blanks."""
    if posted is not None:
        rows = list(posted)
    elif check is not None and check.pk:
        rows = [{'text': q.text, 'kind': q.kind, 'required': q.required} for q in check.questions.all()]
    else:
        rows = [
            {'text': 'How satisfied are you with our service overall?', 'kind': 'rating', 'required': True},
            {'text': 'How likely are you to recommend us to a colleague?', 'kind': 'nps', 'required': True},
            {'text': 'Is there anything we could do better?', 'kind': 'text', 'required': False},
        ]
    target = min(MAX_QUESTIONS, len(rows) + 3)
    while len(rows) < target:
        rows.append({'text': '', 'kind': 'rating', 'required': True})
    return [dict(r, index=i) for i, r in enumerate(rows[:MAX_QUESTIONS])]
