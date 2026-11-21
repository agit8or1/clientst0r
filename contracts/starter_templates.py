"""Starter templates and clauses shipped with clientst0r.

SAMPLE LANGUAGE ONLY. These are generic starting points written to be
edited; they are not legal advice and have not been reviewed for any
jurisdiction. Each template opens with a review note in [[double brackets]],
which blocks sending until someone replaces or deletes it.
"""
from __future__ import annotations

REVIEW_NOTE = ('<p>[[SAMPLE LANGUAGE — this is a starting point, not legal advice. Have your own legal counsel '
               'review every section, adapt it to your services and jurisdiction, then delete this note.]]</p>')

# Shown above every sample in the template library and on copies made from one.
SAMPLE_NOTICE = ('Sample wording to start from — not legal advice. Replace it with your own terms and have your '
                 'own legal counsel review the result before you send it to a customer.')


def _s(title, body, type_='text', optional=False, include=True):
    return {'title': title, 'type': type_, 'body': body, 'optional': optional, 'include': include}


PARTIES = _s('Parties and purpose', REVIEW_NOTE + (
    '<p>This agreement is between <strong>{{provider.name}}</strong> ("Provider") and '
    '<strong>{{client.legal_name}}</strong> ("Client"), effective {{contract.effective_date}}.</p>'))
TERM = _s('Term and renewal', (
    '<p>This agreement starts on {{contract.effective_date}} and runs for {{contract.duration_months}} months, '
    'until {{contract.expiration_date}}. {{contract.renewal_terms}}</p>'))
FEES = _s('Fees and payment', '<p>Client pays the fees below. Invoices are due {{pricing.payment_terms}}. '
          'Recurring charges are billed {{pricing.billing_frequency}} in advance.</p>', 'pricing')
RESPONSIBILITIES = _s('Client responsibilities', (
    '<ul><li>Give Provider timely access to systems, sites and people needed to deliver the services.</li>'
    '<li>Keep a named contact available for approvals and escalations.</li>'
    '<li>Maintain vendor support and licensing for covered systems.</li></ul>'))
CONFIDENTIALITY = _s('Confidentiality', (
    '<p>Each party keeps the other\'s non-public information confidential and uses it only to perform this '
    'agreement. This survives the end of the agreement for [[number]] years.</p>'))
TERMINATION = _s('Termination and notice', (
    '<p>Either party may end this agreement with {{contract.notice_period_days}} days\' written notice. Either '
    'party may end it at once if the other materially breaches it and does not cure the breach within 30 days of '
    'notice. Fees for services delivered up to the end date remain due.</p>'))
LIABILITY = _s('Limitation of liability', (
    '<p>[[Describe the limitation of liability that applies to your services — for example a cap equal to the '
    'fees paid in the previous 12 months, and the exclusions you rely on.]]</p>'), optional=True)
GENERAL = _s('General terms', (
    '<p>This agreement, with its exhibits, is the whole agreement on its subject. Changes must be in writing and '
    'signed by both parties. Notices go to the addresses above.</p>'))
SIGNATURES = _s('Signatures', '<p>The parties sign this agreement electronically.</p>', 'signatures')

TEMPLATES = [
    {
        'key': 'managed_services_12m', 'name': 'Managed IT services agreement (sample)', 'kind': 'managed_services',
        'description': 'Sample managed services agreement: scope, service levels, responsibilities, fees, term. '
                       'Sample language — review before use.',
        'defaults': {'term_type': 'annual', 'duration_months': 12, 'notice_period_days': 30, 'payment_terms': 'Net 30',
                     'billing_frequency': 'monthly',
                     'renewal_terms': 'It renews for further 12-month terms unless either party gives notice.'},
        'line_items': [{'description': 'Managed services — per user', 'kind': 'recurring', 'quantity': '25',
                        'unit_price': '[[price]]'},
                       {'description': 'Onboarding and documentation', 'kind': 'one_time', 'quantity': '1',
                        'unit_price': '0'}],
        'sections': [PARTIES,
                     _s('Services and scope', (
                         '<p>Provider delivers the managed IT services listed in the fees table for the users, '
                         'devices and sites of {{client.name}}: monitoring, patching, help-desk support, and '
                         'vendor coordination.</p><p><strong>Deliverables.</strong> [[List the deliverables.]]</p>')),
                     _s('Exclusions', '<p>Not included unless agreed in writing: new projects, hardware, '
                                      'software licences, on-site work outside business hours, and recovery from '
                                      'events outside Provider\'s control.</p>'),
                     _s('Service levels', (
                         '<table><tbody><tr><td data-row="row-1">Priority</td><td data-row="row-1">Response</td>'
                         '<td data-row="row-1">Target resolution</td></tr><tr><td data-row="row-2">Critical</td>'
                         '<td data-row="row-2">1 hour</td><td data-row="row-2">4 hours</td></tr>'
                         '<tr><td data-row="row-3">High</td><td data-row="row-3">4 hours</td>'
                         '<td data-row="row-3">1 business day</td></tr><tr><td data-row="row-4">Normal</td>'
                         '<td data-row="row-4">1 business day</td><td data-row="row-4">5 business days</td></tr>'
                         '</tbody></table><p>Service levels apply during business hours unless stated otherwise.</p>')),
                     RESPONSIBILITIES, FEES, TERM, TERMINATION, CONFIDENTIALITY, LIABILITY, GENERAL, SIGNATURES],
    },
    {
        'key': 'sow', 'name': 'Statement of work / project agreement (sample)', 'kind': 'sow',
        'description': 'Sample statement of work for a fixed project: scope, deliverables, milestones, acceptance. '
                       'Sample language — review before use.',
        'defaults': {'payment_terms': '50% on signature, 50% on acceptance', 'billing_frequency': 'one_time'},
        'line_items': [{'description': 'Project delivery (fixed fee)', 'kind': 'one_time', 'quantity': '1',
                        'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Project scope', '<p>[[Describe the project, its goals and what is in scope.]]</p>'),
                     _s('Deliverables and milestones', '<ol><li>[[Deliverable 1 — target date]]</li>'
                                                       '<li>[[Deliverable 2 — target date]]</li></ol>'),
                     _s('Exclusions and assumptions', '<p>[[List what is out of scope and the assumptions the '
                                                      'price relies on.]]</p>'),
                     _s('Acceptance', '<p>Client reviews each deliverable within 5 business days and either '
                                      'accepts it or lists the specific gaps. Silence after that period counts as '
                                      'acceptance.</p>'),
                     _s('Change requests', '<p>Changes to scope are agreed in writing, with their effect on price '
                                           'and schedule, before work on them starts.</p>'),
                     RESPONSIBILITIES, FEES, TERMINATION, GENERAL, SIGNATURES],
    },
    {
        'key': 'recurring_support', 'name': 'Recurring support agreement (sample)', 'kind': 'recurring_support',
        'description': 'Sample block-of-hours / recurring support agreement. Sample language — review before use.',
        'defaults': {'duration_months': 12, 'notice_period_days': 30, 'billing_frequency': 'monthly',
                     'payment_terms': 'Net 15'},
        'line_items': [{'description': 'Support retainer (10 hours / month)', 'kind': 'recurring', 'quantity': '1',
                        'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Support services', '<p>Provider provides remote and on-site support for the systems of '
                                            '{{client.name}}, up to the hours in the fees table each billing '
                                            'period. Unused hours [[do / do not]] roll over.</p>'),
                     _s('Additional hours', '<p>Work beyond the included hours is billed at [[rate]] per hour, '
                                            'after Client approves it.</p>'),
                     FEES, TERM, TERMINATION, GENERAL, SIGNATURES],
    },
    {
        'key': 'backup_dr', 'name': 'Backup and disaster recovery services (sample)', 'kind': 'backup_dr',
        'description': 'Sample backup and disaster recovery services agreement. Sample language — review before use.',
        'defaults': {'duration_months': 12, 'notice_period_days': 60, 'billing_frequency': 'monthly'},
        'line_items': [{'description': 'Backup — per protected server', 'kind': 'recurring', 'quantity': '1',
                        'unit_price': '[[price]]'},
                       {'description': 'Cloud storage — per TB', 'kind': 'recurring', 'quantity': '1',
                        'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Protected systems', '<p>[[List the servers, workloads and data covered.]]</p>'),
                     _s('Backup schedule and retention', '<ul><li>Frequency: [[daily / hourly]]</li>'
                                                         '<li>Retention: [[30 daily, 12 monthly]]</li>'
                                                         '<li>Off-site copy: [[location]]</li></ul>'),
                     _s('Recovery objectives and testing', '<p>Target recovery point: [[RPO]]. Target recovery '
                                                           'time: [[RTO]]. Provider runs a restore test '
                                                           '[[quarterly]] and reports the result.</p>'),
                     _s('Client responsibilities', '<p>Client tells Provider about new systems that need '
                                                   'protection and keeps the agreed retention requirements up to '
                                                   'date.</p>'),
                     FEES, TERM, TERMINATION, LIABILITY, GENERAL, SIGNATURES],
    },
    {
        'key': 'security', 'name': 'Security services agreement (sample)', 'kind': 'security',
        'description': 'Sample managed security services agreement (EDR, monitoring, awareness training). '
                       'Sample language — review before use.',
        'defaults': {'duration_months': 12, 'notice_period_days': 30, 'billing_frequency': 'monthly'},
        'line_items': [{'description': 'Endpoint detection and response — per device', 'kind': 'recurring',
                        'quantity': '1', 'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Security services', '<p>[[Describe the security services: endpoint protection, '
                                             'monitoring hours, response actions Provider may take, training.]]</p>'),
                     _s('Incident response', '<p>Provider notifies Client\'s named contact of a confirmed '
                                             'incident within [[time]] and follows the agreed response plan.</p>'),
                     _s('No guarantee', '<p>No security service can prevent every attack. Provider uses '
                                        'reasonable care in delivering the services described here.</p>'),
                     FEES, TERM, TERMINATION, CONFIDENTIALITY, LIABILITY, GENERAL, SIGNATURES],
    },
    {
        'key': 'renewal', 'name': 'Contract renewal (sample)', 'kind': 'renewal',
        'description': 'Sample renewal of an existing agreement for a new term. Sample language — review before use.',
        'defaults': {'duration_months': 12},
        'line_items': [],
        'sections': [PARTIES,
                     _s('Renewal', '<p>The parties renew their existing agreement for a further term of '
                                   '{{contract.duration_months}} months from {{contract.effective_date}}, on the same '
                                   'terms except as set out below.</p><p>[[List any changes.]]</p>'),
                     FEES, SIGNATURES],
    },
    {
        'key': 'amendment', 'name': 'Contract amendment / addendum (sample)', 'kind': 'amendment',
        'description': 'Sample amendment changing an existing agreement. Sample language — review before use.',
        'defaults': {},
        'line_items': [],
        'sections': [PARTIES,
                     _s('Amendment', '<p>This amendment changes the agreement between the parties identified '
                                     'above. Except as changed below, that agreement stays in effect.</p>'
                                     '<p>[[Describe each change.]]</p>'),
                     SIGNATURES],
    },
]

TERM_M2M = _s('Term and ending the agreement', (
    '<p>This agreement starts on {{contract.effective_date}} and continues from month to month. Either party may '
    'end it with {{contract.notice_period_days}} days\' written notice; it then ends at the close of the billing '
    'month in which the notice period expires.</p>'))
TERM_FIXED = _s('Term and renewal', (
    '<p>This agreement starts on {{contract.effective_date}} and runs for an initial term of '
    '{{contract.duration_months}} months, until {{contract.expiration_date}}. {{contract.renewal_terms}}</p>'
    '<p>Ending the agreement early: [[Describe what happens if Client ends the agreement before the end of the '
    'initial term — for example, the recurring fees for the rest of the term, or a stated early-termination '
    'fee.]]</p>'))
MANAGED_SCOPE = _s('Services and scope', (
    '<p>Provider delivers the managed IT services listed in the fees table for the users, devices and sites of '
    '{{client.name}}: monitoring, patching, help-desk support, and vendor coordination.</p>'
    '<p><strong>Covered:</strong> [[List the users, devices, sites and applications covered.]]</p>'))
EXCLUSIONS = _s('Exclusions', '<p>Not included unless agreed in writing: new projects, hardware, software '
                              'licences, on-site work outside business hours, and recovery from events outside '
                              'Provider\'s control. Excluded work is quoted separately.</p>')

TEMPLATES += [
    {
        'key': 'msa_month_to_month', 'name': 'Managed services agreement — month-to-month (sample)',
        'kind': 'managed_services',
        'description': 'Sample managed services agreement that runs month to month and ends on notice. '
                       'Sample language — not legal advice; have your counsel review it.',
        'defaults': {'term_type': 'month_to_month', 'notice_period_days': 30, 'payment_terms': 'Net 15',
                     'billing_frequency': 'monthly', 'auto_renew': False},
        'line_items': [{'description': 'Managed services — per user, per month', 'kind': 'recurring',
                        'quantity': '10', 'unit_price': '[[price]]'}],
        'sections': [PARTIES, MANAGED_SCOPE, EXCLUSIONS, RESPONSIBILITIES, FEES, TERM_M2M, CONFIDENTIALITY,
                     LIABILITY, GENERAL, SIGNATURES],
    },
    {
        'key': 'msa_36_month', 'name': 'Managed services agreement — 36-month term (sample)',
        'kind': 'managed_services',
        'description': 'Sample multi-year managed services agreement with a 36-month initial term and renewal. '
                       'Sample language — not legal advice; have your counsel review it.',
        'defaults': {'term_type': 'multi_year', 'duration_months': 36, 'notice_period_days': 90,
                     'payment_terms': 'Net 30', 'billing_frequency': 'monthly', 'auto_renew': True,
                     'renewal_terms': 'After the initial term it renews for further 12-month terms unless either '
                                      'party gives notice before the end of the current term.'},
        'line_items': [{'description': 'Managed services — per user, per month', 'kind': 'recurring',
                        'quantity': '25', 'unit_price': '[[price]]'},
                       {'description': 'Onboarding and documentation', 'kind': 'one_time', 'quantity': '1',
                        'unit_price': '0'}],
        'sections': [PARTIES, MANAGED_SCOPE, EXCLUSIONS,
                     _s('Price changes during the term', '<p>Recurring fees are fixed for the first 12 months. '
                        'After that Provider may adjust them once a year with 60 days\' written notice, by no '
                        'more than [[percent]]%.</p>'),
                     RESPONSIBILITIES, FEES, TERM_FIXED, TERMINATION, CONFIDENTIALITY, LIABILITY, GENERAL,
                     SIGNATURES],
    },
    {
        'key': 'block_hours_prepaid', 'name': 'Block hours / prepaid support agreement (sample)',
        'kind': 'recurring_support',
        'description': 'Sample prepaid block of support hours drawn down as work is done. '
                       'Sample language — not legal advice; have your counsel review it.',
        'defaults': {'term_type': 'annual', 'duration_months': 12, 'notice_period_days': 30,
                     'payment_terms': 'Due on signature', 'billing_frequency': 'one_time'},
        'line_items': [{'description': 'Prepaid support block (hours)', 'kind': 'one_time',
                        'quantity': '1', 'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Prepaid hours', '<p>Client buys a block of [[number]] support hours, paid in advance. '
                                         'Provider deducts time worked in [[15]]-minute increments and reports '
                                         'the remaining balance [[monthly]].</p>'),
                     _s('Expiry and top-ups', '<p>Unused hours expire at the end of the term '
                                              '({{contract.expiration_date}}) [[unless renewed]]. When the balance '
                                              'falls below [[number]] hours Provider offers a new block; work '
                                              'beyond the balance is billed at [[rate]] per hour.</p>'),
                     _s('What the hours cover', '<p>[[List the kinds of work the hours may be used for and any '
                                                'work billed separately.]]</p>'),
                     FEES, TERM_FIXED, TERMINATION, GENERAL, SIGNATURES],
    },
    {
        'key': 'break_fix_tm', 'name': 'Break-fix / time-and-materials terms (sample)', 'kind': 'other',
        'description': 'Sample terms for work requested as needed and billed for the time and materials used. '
                       'Sample language — not legal advice; have your counsel review it.',
        'defaults': {'term_type': 'month_to_month', 'notice_period_days': 0, 'payment_terms': 'Net 15',
                     'billing_frequency': 'one_time'},
        'line_items': [],
        'sections': [PARTIES,
                     _s('Requesting work', '<p>Client requests work by [[phone, e-mail or the support portal]]. '
                                           'Provider confirms the request and an estimate when the work is likely '
                                           'to exceed [[number]] hours.</p>'),
                     _s('Rates', '<p>Labour: [[rate]] per hour during business hours, [[rate]] per hour outside '
                                 'them, billed in [[15]]-minute increments with a [[one]]-hour minimum for on-site '
                                 'visits. Travel: [[describe]].</p>'),
                     _s('Parts and materials', '<p>Parts, licences and materials are billed at cost plus '
                                               '[[percent]]%. Manufacturer warranties pass through to Client.</p>'),
                     _s('No ongoing obligation', '<p>There is no minimum commitment and no recurring fee. Either '
                                                 'party may stop using these terms at any time; work already '
                                                 'done remains payable.</p>'),
                     LIABILITY, GENERAL, SIGNATURES],
    },
    {
        'key': 'msa_with_schedule', 'name': 'Master services agreement with service schedule (sample)',
        'kind': 'managed_services',
        'description': 'Sample master services agreement holding the general terms, with Schedule A describing '
                       'the services; add further schedules as services are added. Sample language — not legal '
                       'advice; have your counsel review it.',
        'defaults': {'term_type': 'annual', 'duration_months': 12, 'notice_period_days': 60,
                     'payment_terms': 'Net 30', 'billing_frequency': 'monthly', 'auto_renew': True,
                     'renewal_terms': 'It renews for further 12-month terms unless either party gives notice.'},
        'line_items': [{'description': 'Schedule A services — per month', 'kind': 'recurring', 'quantity': '1',
                        'unit_price': '[[price]]'}],
        'sections': [PARTIES,
                     _s('Structure of this agreement', '<p>This master services agreement sets the general terms. '
                        'Each schedule signed under it describes particular services, their fees and service '
                        'levels. If a schedule conflicts with these general terms, the schedule wins for its '
                        'services.</p>'),
                     RESPONSIBILITIES, FEES, TERM_FIXED, TERMINATION, CONFIDENTIALITY, LIABILITY, GENERAL,
                     _s('Schedule A — services', '<p><strong>Services:</strong> [[Describe the services.]]</p>'
                        '<p><strong>Service levels:</strong> [[Response and resolution targets.]]</p>'
                        '<p><strong>Fees:</strong> as listed in the fees table above.</p>'),
                     SIGNATURES],
    },
]

CLAUSES = [
    ('Data protection', 'Privacy', '<p>Each party complies with the data protection laws that apply to it. Where '
                                   'Provider processes personal data for Client, it does so only on Client\'s '
                                   'instructions and under a data processing agreement.</p>'),
    ('Non-solicitation', 'Staff', '<p>During this agreement and for 12 months after it, neither party solicits the '
                                  'other\'s employees who worked on the services, without written consent.</p>'),
    ('Price adjustment', 'Fees', '<p>Provider may adjust recurring fees once a year with 60 days\' written notice, '
                                 'by no more than [[percent]]%.</p>'),
    ('Force majeure', 'General', '<p>Neither party is liable for delay caused by events beyond its reasonable '
                                 'control, as long as it notifies the other party and resumes as soon as it can.</p>'),
    ('After-hours support', 'Services', '<p>Support outside business hours is available for critical issues at '
                                        '[[rate]] per hour, with a minimum of one hour.</p>'),
    ('Hardware and software procurement', 'Services', '<p>Provider may buy hardware and software for Client on '
                                                      'request. Title passes to Client on payment; manufacturer '
                                                      'warranties pass through to Client.</p>'),
]


def seed(apps=None, by=None):
    """Create the starter templates and clauses that are missing.

    Idempotent and never overwrites: a sample is identified by its
    `sample_key` (kept when someone renames or edits it), or for rows made
    before keys existed by its original name. One that exists in any form —
    edited, renamed or deactivated — is left exactly as it is; only a sample
    that was deleted is created again."""
    if apps is None:
        from .models import ContractClause, ContractTemplate, ContractTemplateVersion
    else:
        ContractTemplate = apps.get_model('contracts', 'ContractTemplate')
        ContractTemplateVersion = apps.get_model('contracts', 'ContractTemplateVersion')
        ContractClause = apps.get_model('contracts', 'ContractClause')
    if not any(f.name == 'sample_key' for f in ContractTemplate._meta.get_fields()):
        # Migration 0002 on a new install runs before sample_key exists;
        # migration 0004 seeds everything once it does.
        return 0
    from .content import normalize_line_items, normalize_sections
    made = 0
    for t in TEMPLATES:
        starters = ContractTemplate.objects.filter(organization__isnull=True)
        if starters.filter(sample_key=t['key']).exists():
            continue
        legacy = starters.filter(name=t['name'], sample_key='').first()
        if legacy is not None:
            ContractTemplate.objects.filter(pk=legacy.pk).update(sample_key=t['key'])
            continue
        tpl = ContractTemplate.objects.create(organization=None, name=t['name'], kind=t['kind'],
                                              description=t['description'], is_sample=True, sample_key=t['key'])
        items = [dict(li, unit_price='0' if '[[' in str(li.get('unit_price')) else li['unit_price'])
                 for li in t['line_items']]
        ContractTemplateVersion.objects.create(
            template=tpl, version_number=1, note='Shipped sample',
            data={'sections': normalize_sections([dict(s) for s in t['sections']]),
                  'line_items': normalize_line_items(items), 'defaults': t['defaults']})
        made += 1
    for title, cat, body in CLAUSES:
        if not ContractClause.objects.filter(organization__isnull=True, title=title).exists():
            ContractClause.objects.create(organization=None, title=title, category=cat, body=body, is_sample=True)
    return made
