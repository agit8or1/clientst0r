"""Reading an edit form's POST without turning a missing field into a clear.

The PSA edit views (contracts, invoices) used to read every field as
``request.POST.get(name) or default``. That conflates three different
submissions:

* the field is **absent** — the form did not render it, a script that builds
  it never ran (issue #147), or another client posted a partial form;
* the field is **present but blank** — the user emptied it on purpose;
* the field is **present but malformed** — ``total_hours=abc``.

Only the second is a request to clear. ``PostedFields`` keeps the record's
current value for the first and third, and notes malformed names so the view
can tell the user what it kept.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils.dateparse import parse_date


class PostedFields:
    def __init__(self, post):
        self.post = post
        self.malformed: list[str] = []

    def has(self, name):
        return name in self.post

    def _raw(self, name):
        return (self.post.get(name) or '').strip()

    def text(self, name, current):
        """Absent → ``current``; present (even blank) → the stripped value."""
        if name not in self.post:
            return current
        return self._raw(name)

    def choice(self, name, current, choices):
        """Absent or not one of ``choices`` → ``current``."""
        if name not in self.post:
            return current
        value = self._raw(name)
        if value in choices:
            return value
        self.malformed.append(name)
        return current

    def decimal(self, name, current, blank=Decimal('0'), minimum=None, maximum=None):
        """Absent → ``current``; blank → ``blank``; malformed or out of range → ``current``."""
        if name not in self.post:
            return current
        raw = self._raw(name)
        if not raw:
            return blank
        try:
            value = Decimal(raw)
        except (InvalidOperation, ValueError):
            self.malformed.append(name)
            return current
        if (not value.is_finite() or (minimum is not None and value < minimum)
                or (maximum is not None and value > maximum)):
            self.malformed.append(name)
            return current
        return value

    def integer(self, name, current, blank=0, minimum=None):
        if name not in self.post:
            return current
        raw = self._raw(name)
        if not raw:
            return blank
        try:
            value = int(raw)
        except ValueError:
            self.malformed.append(name)
            return current
        if minimum is not None and value < minimum:
            self.malformed.append(name)
            return current
        return value

    def date(self, name, current, blank=None):
        """Absent → ``current``; blank → ``blank``; unparseable → ``current``."""
        if name not in self.post:
            return current
        raw = self._raw(name)
        if not raw:
            return blank
        try:
            value = parse_date(raw)
        except ValueError:
            value = None
        if value is None:
            self.malformed.append(name)
            return current
        return value

    def flag(self, name, current, sentinel):
        """A checkbox. An unticked checkbox posts nothing, so absence only
        means "off" when the form's ``sentinel`` hidden field shows the
        checkbox was rendered; without it the current value is kept."""
        if sentinel not in self.post:
            return current
        return self._raw(name).lower() in ('1', 'true', 'on', 'yes')

    def csv_list(self, name, current):
        if name not in self.post:
            return current
        return [s.strip() for s in self._raw(name).split(',') if s.strip()]

    def warn(self, request, what):
        """Tell the user which malformed fields kept their saved value."""
        if self.malformed:
            from django.contrib import messages
            names = ', '.join(sorted(set(n.replace('_', ' ') for n in self.malformed)))
            messages.warning(request, f'{what}: kept the saved value for {names} (the submitted value '
                                      'was not valid).')
