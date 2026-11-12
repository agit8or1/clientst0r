"""The editor provider interface.

A provider connects one kind of editor service (ONLYOFFICE Docs, Collabora
Online) to clientst0r's storage, sessions and tokens. The core never talks to
an editor itself: it asks the provider registered for the instance's
``provider`` key.

Implementations subclass ``EditorProvider`` and register an instance:

    from office.providers import register
    register(MyProvider(), replace=True)

Every method receives model instances, never raw settings. A method that
cannot work because the connector or the instance is not set up raises
``NotConfigured`` with a message an administrator can act on; a capability
the editor lacks raises ``NotSupported``. Neither must ever be swallowed into
a fake success: the UI shows the message on a disabled button instead.

Network access to the editor goes through ``office.net.fetch`` (approved
host only, DNS pinned, TLS verified with the instance CA bundle). Logging goes
through ``office.logging_filters.get_logger('office.<key>')`` (token
redaction). Saves go through ``office.storage.save_or_quarantine``.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class NotConfigured(Exception):
    """The connector or the instance is not ready. Message is shown to admins/users."""


class NotSupported(Exception):
    """The editor (or this version of it) does not offer the capability."""


@dataclass(frozen=True)
class Capabilities:
    """What one instance can do. Built from the detected version / discovery,
    never assumed. Formats are lower-case extensions without the dot."""
    edit_formats: frozenset = frozenset()
    view_formats: frozenset = frozenset()
    convert: frozenset = frozenset()      # {(source_ext, target_ext), ...}; 'pdf' target = export
    coauthoring: bool = False
    comments: bool = False
    review: bool = False
    max_file_mb: int | None = None

    @property
    def export_pdf(self) -> bool:
        return any(dst == 'pdf' for _src, dst in self.convert)

    def can_edit(self, ext) -> bool:
        return ext in self.edit_formats

    def can_view(self, ext) -> bool:
        return ext in self.view_formats or ext in self.edit_formats

    def can_convert(self, src, dst) -> bool:
        return (src, dst) in self.convert

    def can_export_pdf(self, ext) -> bool:
        return (ext, 'pdf') in self.convert

    def to_json(self) -> dict:
        return {
            'edit_formats': sorted(self.edit_formats), 'view_formats': sorted(self.view_formats),
            'convert': sorted([list(p) for p in self.convert]), 'coauthoring': self.coauthoring,
            'comments': self.comments, 'review': self.review, 'max_file_mb': self.max_file_mb,
        }

    @classmethod
    def from_json(cls, data) -> 'Capabilities':
        data = data or {}
        return cls(
            edit_formats=frozenset(data.get('edit_formats') or ()),
            view_formats=frozenset(data.get('view_formats') or ()),
            convert=frozenset(tuple(p) for p in (data.get('convert') or ()) if len(p) == 2),
            coauthoring=bool(data.get('coauthoring')), comments=bool(data.get('comments')),
            review=bool(data.get('review')), max_file_mb=data.get('max_file_mb'))


@dataclass
class HealthResult:
    status: str                       # 'ok' | 'degraded' | 'down'
    detail: str = ''
    version: str = ''
    edition: str = ''
    capabilities: Capabilities | None = None


PASS, FAIL, WARN, NOT_RUN = 'pass', 'fail', 'warn', 'not_run'


@dataclass
class DiagnosticCheck:
    key: str
    label: str
    status: str = NOT_RUN             # pass | fail | warn | not_run
    detail: str = ''                  # what was observed (no secrets, no tokens)
    remedy: str = ''                  # what an administrator should do


@dataclass
class RoundTripReport:
    """Steps of the disposable-document round trip, in order. Providers
    append with ``report.step(key, label, status, detail, remedy)``."""
    steps: list = field(default_factory=list)

    def step(self, key, label, status, detail='', remedy=''):
        check = DiagnosticCheck(key, label, status, detail, remedy)
        self.steps.append(check)
        return check

    @property
    def passed(self):
        return bool(self.steps) and all(s.status == PASS for s in self.steps)


@dataclass
class EditorPage:
    """What ``editor_page_context`` returns; rendered by templates/office/editor.html.

    template      provider template included in the editor area
    context       extra template context for that template
    config        JSON-serialisable dict, emitted with json_script as
                  #office-provider-config (never put secrets in it; a signed
                  token/JWT meant for the browser is fine)
    script_urls   absolute https URLs of the editor's own JS (e.g. api.js);
                  must be on the instance's browser_url origin
    csp           extra CSP sources, {'script-src': [...], 'frame-src': [...],
                  'connect-src': [...], 'form-action': [...]}; each source must
                  be the instance's browser_url origin (others are dropped)
    static_js     paths under /static/ for the provider's own glue script
    """
    template: str = ''
    context: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    script_urls: list = field(default_factory=list)
    csp: dict = field(default_factory=dict)
    static_js: list = field(default_factory=list)


class EditorProvider:
    key = ''
    label = ''

    # -- required -------------------------------------------------------
    def capabilities(self, instance) -> Capabilities:
        """Capabilities of `instance`, normally ``Capabilities.from_json(
        instance.capabilities)`` as stored by the last health check."""
        raise NotConfigured(f'The {self.label or self.key} connector is not installed.')

    def editor_page_context(self, session, request) -> EditorPage:
        """Everything the full-screen editor page needs for `session`.
        Issue tokens with office.tokens.issue(session, ...) here."""
        raise NotConfigured(f'The {self.label or self.key} connector is not installed.')

    def health_check(self, instance) -> HealthResult:
        """Contact the editor (office.net.fetch), detect version/edition and
        capabilities. The core stores the result on the instance."""
        raise NotConfigured(f'The {self.label or self.key} connector is not installed.')

    def diagnostics(self, instance) -> list:
        """Provider checks (TLS/auth/WebSockets/callback or WOPI reachability/
        browser reachability). Return DiagnosticCheck items; mark a check
        NOT_RUN with a remedy rather than guessing."""
        raise NotConfigured(f'The {self.label or self.key} connector is not installed.')

    # -- optional -------------------------------------------------------
    def round_trip(self, instance, session, report: RoundTripReport) -> None:
        """Open/edit/save the disposable document of `session` through the
        real editor and add one step per stage to `report`."""
        raise NotConfigured(f'The {self.label or self.key} connector cannot run a round trip yet.')

    def convert(self, instance, revision, target_ext, *, user=None) -> bytes:
        """Convert a stored revision (office.storage.open_revision) to
        `target_ext` ('docx', 'xlsx', 'pptx' or 'pdf') and return the bytes.
        Only called when capabilities().can_convert(src, target_ext)."""
        raise NotSupported('Conversion is not available.')

    def force_save(self, session) -> bool:
        """Ask the editor to save `session`'s document back to clientst0r now,
        without ending the session (used by ``manage.py office_sessions
        --drain`` before an editor upgrade or provider switch).

        Return True when the editor accepted the request (or had nothing to
        save); the save itself still arrives through the normal callback /
        PutFile path. Raise NotSupported when the editor offers no
        server-side way to request a save (the drain then waits for users to
        close their editors), NotConfigured when the connector is missing."""
        raise NotSupported('This editor cannot be asked to save from the server.')

    def on_session_revoked(self, session) -> None:
        """Called after commit when a session is revoked (permission lost,
        file deleted, admin action). Kick the user out of the editor if the
        service supports it. Must not raise."""
        return None

    def on_session_closed(self, session) -> None:
        """Called after commit when a session ends normally. Must not raise."""
        return None
