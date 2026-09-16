"""
PSA Manager - Unified interface for PSA ticket operations
"""
import logging

logger = logging.getLogger('integrations')


class PSANoteResult:
    """
    Outcome of one attempt to post a note to a PSA ticket.

    Truthy when the PSA accepted the note, so `if psa_manager.add_ticket_note(...)`
    reads the same as the plain boolean this used to return. `reason` says which
    kind of failure it was, and `detail` is a sentence fit for an audit entry.
    """

    OK = 'ok'
    UNSUPPORTED = 'unsupported'       # provider has no ticket-note API here
    INVALID_TICKET = 'invalid_ticket'  # no ticket, or no connection behind it
    FAILED = 'failed'                  # the PSA rejected it, or was unreachable

    def __init__(self, reason, detail):
        self.reason = reason
        self.detail = detail

    def __bool__(self):
        return self.reason == self.OK

    def __repr__(self):
        return f"<PSANoteResult {self.reason}: {self.detail}>"


class PSAManager:
    """
    Unified manager for PSA ticket operations across different providers.
    """

    def __init__(self):
        self.logger = logging.getLogger('integrations.psa_manager')

    def add_ticket_note(self, ticket, note, internal=False):
        """
        Add a note/comment to a PSA ticket.

        The work is delegated to the provider classes in `integrations.providers`
        rather than reimplemented here. They already hold each vendor's auth
        (HaloPSA's OAuth token exchange among it), decrypt the connection's
        credentials the way the model encrypted them, and validate the
        connection's base URL before anything is sent to it.

        Args:
            ticket: PSATicket instance
            note: Note text to add
            internal: Whether the note is internal/private (default: False)

        Returns:
            PSANoteResult: truthy only if the PSA accepted the note.
        """
        from .providers import PROVIDER_REGISTRY, get_provider

        if not ticket or not ticket.connection:
            self.logger.error("Invalid ticket or connection")
            return PSANoteResult(
                PSANoteResult.INVALID_TICKET,
                "no PSA ticket or no connection behind it",
            )

        connection = ticket.connection
        provider_type = connection.provider_type
        label = ticket.ticket_number or ticket.external_id or f"id={ticket.pk}"

        provider_class = PROVIDER_REGISTRY.get(provider_type)
        if provider_class is None:
            self.logger.warning(f"PSA provider {provider_type} is not registered")
            return PSANoteResult(
                PSANoteResult.UNSUPPORTED,
                f"{provider_type} is not a supported PSA provider",
            )

        if not provider_class.supports_ticket_notes:
            self.logger.warning(f"PSA provider {provider_type} cannot post ticket notes")
            return PSANoteResult(
                PSANoteResult.UNSUPPORTED,
                f"{provider_class.provider_name} does not support posting ticket notes",
            )

        self.logger.info(f"Adding note to {provider_type} ticket {label}")

        try:
            provider = get_provider(connection)
            posted = provider.add_ticket_note(ticket.external_id, note, internal=internal)
        except Exception as e:
            self.logger.error(f"Failed to add note to {provider_type} ticket {label}: {e}")
            return PSANoteResult(PSANoteResult.FAILED, f"{provider_type} error: {e}")

        if posted:
            return PSANoteResult(PSANoteResult.OK, f"note posted to {provider_type} ticket {label}")

        return PSANoteResult(
            PSANoteResult.FAILED,
            f"{provider_type} did not accept the note for ticket {label}",
        )
