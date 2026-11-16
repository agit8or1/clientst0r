# Adding a step to the onboarding wizard

The wizard (`onboarding` app) is a small engine plus a registry of steps. A step is one class; a session kind is
an ordered list of step keys. Another app can contribute a step after merge without editing the wizard.

## The pieces

| File | What it holds |
|---|---|
| `onboarding/registry.py` | `Step` base class, `StepForm`, `register_step()`, `set_kind_steps()` |
| `onboarding/engine.py` | create / apply / skip / reopen / cancel, progress, audit |
| `onboarding/steps/core.py` | the 19 new-customer steps (16 live, plus shared ones) |
| `onboarding/steps/pricing.py` | steps that need the `pricing` app (feature-detected) |
| `onboarding/steps/lifecycle.py` | lifecycle steps: select customer, change details, draft the change |
| `onboarding/access.py` | who may open which session (per organization) |

Session kinds: `new_customer`, `plan_change`, `add_users`, `remove_users`, `add_devices`, `remove_devices`,
`add_location`, `renewal`, `price_increase`, `offboarding`.

## A step

```python
from django import forms
from onboarding.models import OnboardingSession as S
from onboarding.registry import Step, StepError, StepForm, register_step


class LicenseForm(StepForm):                       # StepForm adds the Bootstrap classes
    seats = forms.IntegerField(min_value=0)


class LicensesStep(Step):
    key = 'licenses'                               # unique, slug-safe; also the key of the saved answers
    title = 'Software licenses'
    summary = 'One sentence shown under the title.'
    requires_apps = ('licensing',)                 # missing app => "Available once <feature_name> is enabled."
    feature_name = 'license tracking'
    skippable = True                               # unavailable steps are always skippable
    needs_client = True                            # False for steps that run before the customer exists
    commercial = False                             # True => draft-only badge; see rules below
    form_class = LicenseForm

    def extra_available(self):                     # optional: also require a model/feature
        from django.apps import apps
        try:
            apps.get_model('licensing', 'License')
        except LookupError:
            return False
        return True

    def permission_denial(self, user, session):    # the permission of the thing this step changes
        from onboarding.steps.common import need
        return need(user, session.client, 'licenses_manage', 'managing licenses')

    def apply(self, session, cleaned, user, request=None):
        ...                                        # do the work; raise StepError('...') to show a message
        return 'Recorded 25 seats'                 # one line, written to the audit log


register_step(LicensesStep, kinds=(S.NEW_CUSTOMER,), after='warranty')   # or before='...'
```

Put the module under your app and import it from `AppConfig.ready()` (after `onboarding` has loaded its own
steps). Sessions started before your step existed get its state row on their next load.

## Rules

1. **Feature-detect, never fake.** Use `requires_apps` and/or `extra_available()`. An unavailable step is listed
   with "Available once X is enabled", can be skipped, and refuses to apply. Do not render a form that pretends
   to work.
2. **Commercial changes are drafts.** A step that changes price or contract terms may only create or edit a
   draft (a `contracts.ContractDocument` in draft, or a draft `psa.Quote`). The draft then goes through the
   existing approval and e-signature flows from the `send_approval` step. Never write active prices, plans or
   contract state directly.
3. **Enforce the permission of the thing you change** in `permission_denial()`, on top of the wizard's own
   `manage_customer_onboarding` (checked by the engine for every step). Use the real role flag or the helper
   the owning app already has (`contracts.permissions`, `integrations.ownership.can_manage_platform`).
4. **Idempotent where you can.** A done step can be reopened and applied again; update rather than duplicate.
5. **Stay inside the customer.** Only touch `session.client` and records the user can reach. Do not take
   object ids from the form without filtering the queryset the way the built-in steps do.
6. **Audit.** The engine writes one `AuditLog` row per applied or skipped step from the string you return; do
   not add your own.
7. **Tests.** Add them to your app: apply the step, the unavailable case (patch `django.apps.apps.is_installed`),
   and the permission denial.

## Putting a step into a kind

`register_step(cls, kinds=(...), after='key' | before='key')` inserts into those kinds' lists. The built-in
order is set in `steps/core.py` (`set_kind_steps(S.NEW_CUSTOMER, [...])`) and `steps/lifecycle.py`; to replace
a whole list from another app use `set_kind_steps(kind, keys)`.

## Steps that wait for other branches

Detected today, so they light up without code changes once the app is installed:

| Step | Needs | Notes |
|---|---|---|
| `service_plan`, `add_ons`, `customer_pricing` | `pricing` (`ServicePlan`) | record the selection and feed draft lines; attaching the plan (`ClientServicePlan`) to the customer after signature is not done here |
| `backup_monitoring` | `backup_monitoring` (`BackupConnection`) | pins an existing connection to the customer |
| `payment` (method field only) | `payments` | terms work without it; card / mandate collection stays the customer's setup link |
