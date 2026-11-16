"""The step registry.

Every wizard step is a `Step` subclass registered under a unique key. The
registry maps each session kind to its ordered list of step keys, so another
app can contribute a step after merge without touching this one (see
docs/plans/ONBOARDING_STEPS.md).

A step is *available* when every app it needs is installed (and, for steps that
build on another app's models, `extra_available()` agrees). An unavailable step
is still listed, shown as "Available once <app> is enabled" and can be skipped;
it is never simulated.
"""
from __future__ import annotations

from django import forms
from django.apps import apps


class StepError(Exception):
    """A step could not be applied; the message is shown to the technician."""


class StepForm(forms.Form):
    """Base form: Bootstrap classes on every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            w = field.widget
            css = w.attrs.get('class', '')
            if isinstance(w, forms.CheckboxInput):
                w.attrs['class'] = (css + ' form-check-input').strip()
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs['class'] = (css + ' form-select').strip()
            else:
                w.attrs['class'] = (css + ' form-control').strip()


class Step:
    key = ''
    title = ''
    summary = ''
    #: Apps that must be installed (labels). Missing -> unavailable.
    requires_apps: tuple = ()
    #: Human name of the missing feature for "Available once X is enabled".
    feature_name = ''
    skippable = True
    #: The step acts on a customer, so the session needs a client first.
    needs_client = True
    #: True when applying changes price or contract terms. Such a step only ever
    #: produces or edits a draft (quote / agreement), never active state.
    commercial = False
    form_class = None
    template = 'onboarding/step_form.html'

    # --- availability -----------------------------------------------------
    def is_available(self) -> bool:
        return all(apps.is_installed(a) for a in self.requires_apps) and self.extra_available()

    def extra_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ''
        return f'Available once {self.feature_name or ", ".join(self.requires_apps)} is enabled.'

    # --- state ------------------------------------------------------------
    def is_complete(self, session) -> bool:
        from .models import OnboardingStepState
        return session.step_states.filter(step_key=self.key, status=OnboardingStepState.DONE).exists()

    def blocked_reason(self, session) -> str:
        if self.needs_client and session.client_id is None:
            return 'Create or choose the customer first.'
        return ''

    # --- permissions ------------------------------------------------------
    def permission_denial(self, user, session) -> str:
        """Extra permission of the thing this step changes ('' = allowed).
        The wizard permission itself is checked by the engine."""
        return ''

    # --- form / apply -----------------------------------------------------
    def get_form(self, session, data=None, user=None):
        if self.form_class is None:
            return None
        return self.form_class(data, initial=self.initial(session), **self.form_kwargs(session, user))

    def form_kwargs(self, session, user) -> dict:
        return {}

    def initial(self, session) -> dict:
        return dict(session.step_data(self.key))

    def context(self, session, user=None) -> dict:
        return {}

    def apply(self, session, cleaned, user, request=None) -> str:
        """Apply the answers; return a one-line summary for the audit log."""
        raise NotImplementedError

    def saved_data(self, session, cleaned) -> dict:
        """What is stored on the session for this step (JSON-safe)."""
        from .engine import jsonable
        return jsonable(cleaned)


_STEPS: dict = {}
_KINDS: dict = {}


def register_step(step_cls, kinds=(), after=None, before=None):
    """Register a step class and add it to the given session kinds.

    `after` / `before` name an existing step key to sit next to; otherwise the
    step is appended. Safe to call more than once for the same class."""
    step = step_cls()
    if not step.key:
        raise ValueError('A step needs a key.')
    _STEPS[step.key] = step
    for kind in kinds:
        keys = _KINDS.setdefault(kind, [])
        if step.key in keys:
            continue
        if after in keys:
            keys.insert(keys.index(after) + 1, step.key)
        elif before in keys:
            keys.insert(keys.index(before), step.key)
        else:
            keys.append(step.key)
    return step_cls


def set_kind_steps(kind, keys):
    _KINDS[kind] = list(keys)


def get_step(key):
    return _STEPS.get(key)


def steps_for(kind):
    return [_STEPS[k] for k in _KINDS.get(kind, []) if k in _STEPS]


def all_steps():
    return dict(_STEPS)
