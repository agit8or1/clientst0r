"""
Per-customer AI rules that apply before anything is built for a model:
tenant exclusion and information-sharing rules (AIBusinessPolicy).

Exclusion is also enforced in profiles.profile_refusal — and so inside the
gateway — for every AI path. Sharing rules are applied by
troubleshoot.build_observations while the observation set is being built,
so a withheld field never exists in the prompt text, the stored session or
the audit log.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

EXCLUDED_MESSAGE = 'This customer is excluded from AI features.'


def is_excluded(organization) -> bool:
    from psa_ai.models import AIBusinessPolicy
    return AIBusinessPolicy.objects.filter(organization=organization, ai_excluded=True).exists()


@dataclass(frozen=True)
class SharingRules:
    ticket_text: bool = True
    device_data: bool = True
    network_identifiers: bool = False
    contact_data: bool = False
    kb_titles: bool = True

    def as_dict(self):
        return asdict(self)

    LABELS = {
        'ticket_text': 'Ticket subject, description and public conversation',
        'device_data': 'Device status, OS, alerts and read-only diagnostic output',
        'network_identifiers': 'Hostnames, IP and MAC addresses',
        'contact_data': 'Contact and requester names',
        'kb_titles': 'KB article and runbook titles',
    }


def sharing_rules(policy) -> SharingRules:
    """The policy's rules; without a policy, the most restrictive set."""
    if policy is None:
        return SharingRules(ticket_text=False, device_data=False, network_identifiers=False,
                            contact_data=False, kb_titles=False)
    return SharingRules(ticket_text=policy.share_ticket_text, device_data=policy.share_device_data,
                        network_identifiers=policy.share_network_identifiers,
                        contact_data=policy.share_contact_data, kb_titles=policy.share_kb_titles)
