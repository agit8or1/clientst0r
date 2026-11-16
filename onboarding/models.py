"""Customer onboarding and commercial lifecycle sessions.

A session walks one customer (or one change to an existing customer) through
an ordered list of steps. The session keeps each step's saved answers in
`data` and a row per step in OnboardingStepState, so it can be left and
resumed at any time and may be completed only in part.

`organization` is the tenant the session belongs to (the organization the
technician was working in when it was started); `client` is the customer the
session is about. For a new customer `client` is empty until the first step
creates it. Every read goes through onboarding.access.
"""
from django.conf import settings
from django.db import models


class OnboardingSession(models.Model):
    NEW_CUSTOMER = 'new_customer'
    PLAN_CHANGE = 'plan_change'
    ADD_USERS = 'add_users'
    REMOVE_USERS = 'remove_users'
    ADD_DEVICES = 'add_devices'
    REMOVE_DEVICES = 'remove_devices'
    ADD_LOCATION = 'add_location'
    RENEWAL = 'renewal'
    PRICE_INCREASE = 'price_increase'
    OFFBOARDING = 'offboarding'
    KINDS = [
        (NEW_CUSTOMER, 'New customer onboarding'),
        (PLAN_CHANGE, 'Plan change'),
        (ADD_USERS, 'Add users'),
        (REMOVE_USERS, 'Remove users'),
        (ADD_DEVICES, 'Add devices'),
        (REMOVE_DEVICES, 'Remove devices'),
        (ADD_LOCATION, 'Add location'),
        (RENEWAL, 'Renewal'),
        (PRICE_INCREASE, 'Price increase'),
        (OFFBOARDING, 'Offboarding'),
    ]

    DRAFT = 'draft'
    IN_PROGRESS = 'in_progress'
    AWAITING_APPROVAL = 'awaiting_approval'
    AWAITING_SIGNATURE = 'awaiting_signature'
    COMPLETED = 'completed'
    CANCELLED = 'cancelled'
    STATUSES = [
        (DRAFT, 'Draft'), (IN_PROGRESS, 'In progress'), (AWAITING_APPROVAL, 'Awaiting approval'),
        (AWAITING_SIGNATURE, 'Awaiting signature'), (COMPLETED, 'Completed'), (CANCELLED, 'Cancelled'),
    ]
    OPEN_STATUSES = (DRAFT, IN_PROGRESS, AWAITING_APPROVAL, AWAITING_SIGNATURE)

    organization = models.ForeignKey('core.Organization', on_delete=models.CASCADE,
                                     related_name='onboarding_sessions',
                                     help_text='The tenant the session belongs to.')
    client = models.ForeignKey('core.Organization', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='onboarding_sessions_as_client',
                               help_text='The customer. Empty until the first step creates it.')
    kind = models.CharField(max_length=20, choices=KINDS, default=NEW_CUSTOMER)
    status = models.CharField(max_length=20, choices=STATUSES, default=DRAFT, db_index=True)
    title = models.CharField(max_length=255, blank=True)
    data = models.JSONField(default=dict, blank=True, help_text='Saved answers, keyed by step.')
    current_step = models.CharField(max_length=60, blank=True)
    quote = models.ForeignKey('psa.Quote', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                              help_text='The draft quote this session produced.')
    agreement = models.ForeignKey('contracts.ContractDocument', on_delete=models.SET_NULL, null=True,
                                  blank=True, related_name='+',
                                  help_text='The draft agreement (or amendment / renewal) this session produced.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'onboarding_sessions'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['organization', 'status'])]

    def __str__(self):
        return self.display_title

    @property
    def display_title(self):
        if self.title:
            return self.title
        who = self.client.name if self.client_id else (self.data.get('customer', {}).get('name') or 'new customer')
        return f'{self.get_kind_display()}: {who}'

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    def step_data(self, key):
        value = (self.data or {}).get(key)
        return value if isinstance(value, dict) else {}

    def set_step_data(self, key, values):
        data = dict(self.data or {})
        data[key] = values
        self.data = data


class OnboardingStepState(models.Model):
    NOT_STARTED = 'not_started'
    IN_PROGRESS = 'in_progress'
    DONE = 'done'
    SKIPPED = 'skipped'
    BLOCKED = 'blocked'
    STATUSES = [(NOT_STARTED, 'Not started'), (IN_PROGRESS, 'In progress'), (DONE, 'Done'),
                (SKIPPED, 'Skipped'), (BLOCKED, 'Blocked')]

    session = models.ForeignKey(OnboardingSession, on_delete=models.CASCADE, related_name='step_states')
    step_key = models.CharField(max_length=60)
    status = models.CharField(max_length=15, choices=STATUSES, default=NOT_STARTED)
    notes = models.TextField(blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     blank=True, related_name='+')
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'onboarding_step_states'
        constraints = [models.UniqueConstraint(fields=['session', 'step_key'], name='onboarding_one_state_per_step')]

    def __str__(self):
        return f'{self.session_id}:{self.step_key}={self.status}'
