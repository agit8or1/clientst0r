"""
Scheduling forms
"""
from django import forms
from django.contrib.auth.models import User
from .models import ScheduledTask, TaskComment


class ScheduledTaskForm(forms.ModelForm):
    class Meta:
        model = ScheduledTask
        fields = [
            'title', 'description', 'priority', 'due_date',
            'recurrence', 'recurrence_interval_days', 'require_all_signoffs',
            'psa_ticket', 'alert_email', 'alert_sms',
        ]
        widgets = {
            'due_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    # v3.17.535: the lead time is entered as a number plus a unit. It used to be
    # a bare hours field, so a week's notice meant knowing to type 168.
    alert_before_value = forms.IntegerField(
        min_value=0, required=False, initial=24,
        label='Warn before due',
        help_text='How far ahead to start warning. 0 turns the warning off.',
    )
    alert_before_unit = forms.ChoiceField(
        choices=ScheduledTask.ALERT_UNITS, required=False, initial='hours',
        label='Unit',
    )

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('org', None)
        super().__init__(*args, **kwargs)
        if org:
            from integrations.models import PSATicket
            self.fields['psa_ticket'].queryset = PSATicket.objects.filter(
                organization=org
            ).order_by('-external_updated_at')
        else:
            from integrations.models import PSATicket
            self.fields['psa_ticket'].queryset = PSATicket.objects.none()
        self.fields['psa_ticket'].required = False
        self.fields['psa_ticket'].empty_label = '— No linked ticket —'

        # Show the lead time back in the unit it was entered in.
        instance = getattr(self, 'instance', None)
        if instance is not None and instance.pk and not self.is_bound:
            hours = instance.alert_before_hours or 0
            if instance.alert_before_unit == 'days' and hours % 24 == 0:
                self.fields['alert_before_value'].initial = hours // 24
                self.fields['alert_before_unit'].initial = 'days'
            else:
                self.fields['alert_before_value'].initial = hours
                self.fields['alert_before_unit'].initial = 'hours'
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs['class'] = 'form-select'
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            else:
                field.widget.attrs['class'] = 'form-control'


    def save(self, commit=True):
        """Fold the value+unit pair back into the canonical hours field.

        `set_alert_lead` on the model owns the arithmetic so the form, an
        import and the API cannot each get it subtly different.
        """
        task = super().save(commit=False)
        task.set_alert_lead(
            self.cleaned_data.get('alert_before_value') or 0,
            self.cleaned_data.get('alert_before_unit') or 'hours',
        )
        if commit:
            task.save()
            self.save_m2m()
        return task


class TaskSignOffForm(forms.Form):
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        label='Notes (optional)',
        help_text='Optional notes about this sign-off.'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control'


class TaskAssignUsersForm(forms.Form):
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label='Assign To',
    )

    def __init__(self, *args, **kwargs):
        org = kwargs.pop('org', None)
        super().__init__(*args, **kwargs)
        if org:
            from accounts.models import Membership
            user_ids = Membership.objects.filter(
                organization=org,
                is_active=True
            ).values_list('user_id', flat=True)
            self.fields['users'].queryset = User.objects.filter(
                id__in=user_ids, is_active=True
            ).order_by('username')
        else:
            self.fields['users'].queryset = User.objects.filter(
                is_active=True
            ).order_by('username')
