"""Built-in support workflows (data, not code).

An administrator can customise any of these (Support workflows → Edit): the
edited copy is stored as a SupportWorkflowDefinition with the same slug and
used instead; "Reset" deletes the copy. New workflows can be added the same
way. engine.validate_definition() checks every definition before it is used.

Shape of a definition:

  name, description
  categories        alert categories it applies to (psa/routing ALERT_CATEGORY_CHOICES)
  freshness_minutes evidence older than this is shown as stale
  evidence          evidence items to gather (engine.EVIDENCE)
  causes            [{text, when}] likely causes, rule-based: `when` is a condition
  remediations      [{action, when, impact}] — `action` is a Rem0te catalog action
                    key ClientSt0r knows (integrations.rem0te.pairing.KNOWN_ACTIONS);
                    it is offered only when the paired Rem0te advertises it and
                    `when` holds. Never a command, script, path or URL.
  manual_steps      what a technician does when no advertised action fits
  verify_within_minutes  how long monitoring has to confirm the outcome
  requires_integration   'backup': offered only with a backup integration

Conditions: {} (always) | {"fact": f, "op": op, "value": v} |
{"all": [...]} | {"any": [...]}. Ops: eq ne gt gte lt lte in truthy falsy missing.

Rem0te's catalog (contract ticket-rmm-v1, Rem0te 0.30) has one action that
can be proposed from a ticket: windows.service.start@1, which starts the
Windows Print Spooler once. windows.update.install@1 is requested only
through Rem0te's staged patching, never directly. So most workflows below
gather evidence, explain likely causes and give manual steps; the
service-stopped workflow can also propose the Spooler start for approval.
"""

STALE = {'fact': 'evidence_stale', 'op': 'truthy'}

BUILTINS = [
    {
        'slug': 'computer-offline',
        'name': 'Computer offline',
        'description': 'A computer stopped checking in.',
        'categories': ['offline'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'device_status', 'site_peers', 'repeat_history'],
        'causes': [
            {'text': 'Several computers at the same site are offline too: likely the site\'s internet, power '
                     'or network, not this computer.', 'when': {'fact': 'site_offline_count', 'op': 'gte', 'value': 2}},
            {'text': 'The computer goes offline repeatedly: check sleep/power settings, a failing network '
                     'adapter or Wi-Fi coverage.', 'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 3}},
            {'text': 'Only this computer is offline: it may be shut down, asleep, restarting after updates, or '
                     'its agent stopped.', 'when': {'fact': 'site_offline_count', 'op': 'lt', 'value': 2}},
            {'text': 'The evidence is old; refresh it before acting.', 'when': STALE},
        ],
        'remediations': [],
        'manual_steps': [
            'Ask the user (or someone on site) whether the computer is on and connected.',
            'If several computers at the site are down, check the site\'s internet link and power first.',
            'Once it is back, check why it went down (Windows event log, last boot time).',
        ],
        'verify_within_minutes': 60,
    },
    {
        'slug': 'disk-nearly-full',
        'name': 'Disk nearly full',
        'description': 'A drive is running out of free space.',
        'categories': ['disk'],
        'freshness_minutes': 60,
        'evidence': ['alert', 'alert_now', 'disk', 'device_status', 'device_inventory', 'repeat_history'],
        'causes': [
            {'text': 'Very little free space left: Windows Update, temp files or user downloads can fail '
                     'outright at this level.', 'when': {'any': [{'fact': 'disk_free_pct', 'op': 'lte', 'value': 5},
                                                                  {'fact': 'disk_free_gb', 'op': 'lte', 'value': 2}]}},
            {'text': 'The alert keeps coming back: something is filling the disk steadily (logs, a sync '
                     'client cache, backups written locally).', 'when': {'any': [
                         {'fact': 'occurrences', 'op': 'gte', 'value': 3},
                         {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}]}},
            {'text': 'Temp files, the Recycle Bin and the Windows Update cache are the usual first things to '
                     'clear.', 'when': {}},
            {'text': 'The evidence is old; refresh it before acting.', 'when': STALE},
        ],
        # Rem0te advertises no disk-cleanup action, so cleanup is a guided manual step.
        'remediations': [],
        'manual_steps': [
            'Run Disk Cleanup (including "Clean up system files") or Storage Sense on the computer.',
            'Empty the Recycle Bin and clear %TEMP% with the user\'s agreement.',
            'Check for large folders (user downloads, sync client caches, local backups) before deleting anything.',
            'If the disk is simply too small, plan a larger drive or move data off it.',
        ],
        'verify_within_minutes': 120,
    },
    {
        'slug': 'service-stopped',
        'name': 'Service stopped',
        'description': 'A monitored Windows service is not running.',
        'categories': ['service'],
        'freshness_minutes': 30,
        'evidence': ['alert', 'alert_now', 'device_status', 'repeat_history'],
        'causes': [
            {'text': 'The Print Spooler stops after a driver crash or a stuck print job.',
             'when': {'fact': 'service_name', 'op': 'eq', 'value': 'spooler'}},
            {'text': 'The service stops repeatedly: look for a crashing dependency or a bad update.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
            {'text': 'It may have been stopped on purpose, or be set to manual start.', 'when': {}},
            {'text': 'The evidence is old; refresh it before acting.', 'when': STALE},
        ],
        'remediations': [
            {'action': 'windows.service.start@1',
             'when': {'fact': 'service_name', 'op': 'eq', 'value': 'spooler'},
             'impact': 'Starts the Print Spooler once. Documents already waiting may print immediately and '
                       'cannot be recalled. It does not change the startup type, so it may stop again after a '
                       'restart. Rem0te checks the service is running 10 and 30 seconds later.'},
        ],
        'manual_steps': [
            'Check the service\'s startup type and recovery settings.',
            'Read the System event log around the time it stopped.',
            'Start it from Services once the cause is understood.',
        ],
        'verify_within_minutes': 30,
    },
    {
        'slug': 'windows-update-failure',
        'name': 'Windows Update failure',
        'description': 'Updates failed to install.',
        'categories': ['windows_update'],
        'freshness_minutes': 24 * 60,
        'evidence': ['alert', 'alert_now', 'patch', 'device_status', 'disk'],
        'causes': [
            {'text': 'Specific updates failed (KB numbers in the evidence).',
             'when': {'fact': 'failed_updates', 'op': 'gte', 'value': 1}},
            {'text': 'A restart is pending; updates often fail until it happens.',
             'when': {'fact': 'reboot_required', 'op': 'truthy'}},
            {'text': 'Low disk space makes updates fail.', 'when': {'fact': 'disk_free_pct', 'op': 'lte', 'value': 10}},
            {'text': 'Patch evidence is stale; a fresh scan is needed.',
             'when': {'any': [{'fact': 'patch_freshness', 'op': 'eq', 'value': 'stale'}, STALE]}},
        ],
        # windows.update.install@1 is requested only through Rem0te's staged patching.
        'remediations': [],
        'manual_steps': [
            'Restart the computer if a restart is pending, then let Windows Update retry.',
            'Install the failed updates through Rem0te\'s staged patching (a ring deployment), which has its '
            'own approval.',
            'If one update keeps failing, check the Windows Update log for its error code.',
        ],
        'verify_within_minutes': 24 * 60,
    },
    {
        'slug': 'high-cpu',
        'name': 'High CPU',
        'description': 'Processor use stayed high.',
        'categories': ['cpu'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'metric', 'device_status', 'repeat_history'],
        'causes': [
            {'text': 'Sustained near 100%: a runaway process, a scan or an update installing.',
             'when': {'fact': 'metric_pct', 'op': 'gte', 'value': 95}},
            {'text': 'Recurring: scheduled work (backups, scans) may be colliding with business hours.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
            {'text': 'The evidence is old; it may already have passed.', 'when': STALE},
        ],
        'remediations': [],
        'manual_steps': ['Find the top process (Task Manager / Resource Monitor) before ending anything.',
                         'Check for antivirus scans or updates running.'],
        'verify_within_minutes': 60,
    },
    {
        'slug': 'high-memory',
        'name': 'High memory',
        'description': 'Memory use stayed high.',
        'categories': ['memory'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'metric', 'device_status', 'device_inventory', 'repeat_history'],
        'causes': [
            {'text': 'Close to exhausted: an application leaking memory, or too many open applications.',
             'when': {'fact': 'metric_pct', 'op': 'gte', 'value': 95}},
            {'text': 'Recurring: the computer may need more memory for its workload.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
            {'text': 'The evidence is old; it may already have passed.', 'when': STALE},
        ],
        'remediations': [],
        'manual_steps': ['Find the process using the most memory and ask the user before closing it.',
                         'A restart clears a leak for now; plan a fix if it recurs.'],
        'verify_within_minutes': 60,
    },
    {
        'slug': 'pending-reboot',
        'name': 'Pending reboot',
        'description': 'The computer needs a restart to finish updates.',
        'categories': ['reboot_pending'],
        'freshness_minutes': 24 * 60,
        'evidence': ['alert', 'alert_now', 'patch', 'device_status'],
        'causes': [
            {'text': 'Updates were installed and need a restart to take effect.',
             'when': {'fact': 'pending_updates', 'op': 'gte', 'value': 0}},
            {'text': 'Some updates failed; a restart may let them finish.',
             'when': {'fact': 'failed_updates', 'op': 'gte', 'value': 1}},
            {'text': 'Patch evidence is stale.', 'when': {'fact': 'patch_freshness', 'op': 'eq', 'value': 'stale'}},
        ],
        # No restart action is in Rem0te's catalog; Rem0te never restarts a computer for updates.
        'remediations': [],
        'manual_steps': ['Agree a restart time with the user and restart the computer.',
                         'Afterwards, check that the restart-pending flag cleared.'],
        'verify_within_minutes': 24 * 60,
    },
    {
        'slug': 'application-failure',
        'name': 'Application failure',
        'description': 'An application crashed or logged errors.',
        'categories': ['application'],
        'freshness_minutes': 60,
        'evidence': ['alert', 'alert_now', 'device_status', 'repeat_history'],
        'causes': [
            {'text': 'Repeated crashes: a bad update to the application or a corrupt profile.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
            {'text': 'A single crash may not need action; confirm with the user.', 'when': {}},
        ],
        'remediations': [],
        'manual_steps': ['Read the Application event log for the faulting module.',
                         'Ask the user what they were doing; check for a recent application update.'],
        'verify_within_minutes': 24 * 60,
    },
    {
        'slug': 'network-connectivity',
        'name': 'Network connectivity',
        'description': 'Network checks failed (DNS, gateway, packet loss).',
        'categories': ['network'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'device_status', 'site_peers', 'repeat_history'],
        'causes': [
            {'text': 'Other computers at the site are affected too: the site network or internet link.',
             'when': {'fact': 'site_offline_count', 'op': 'gte', 'value': 1}},
            {'text': 'Only this computer: its adapter, cable, Wi-Fi or DNS settings.', 'when': {}},
        ],
        'remediations': [],
        'manual_steps': ['Check the computer\'s IP configuration and DNS servers.',
                         'Check the site gateway and switch port.'],
        'verify_within_minutes': 60,
    },
    {
        'slug': 'unresponsive-application',
        'name': 'Unresponsive application',
        'description': 'An application stopped responding.',
        'categories': ['unresponsive_app'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'device_status', 'metric'],
        'causes': [
            {'text': 'High CPU or memory at the same time: the computer itself is overloaded.',
             'when': {'fact': 'metric_pct', 'op': 'gte', 'value': 90}},
            {'text': 'The application is waiting on a network share or server.', 'when': {}},
        ],
        'remediations': [],
        'manual_steps': ['Ask the user before ending the application; unsaved work is lost.',
                         'Check the server or share it depends on.'],
        'verify_within_minutes': 60,
    },
    {
        'slug': 'endpoint-security-alert',
        'name': 'Endpoint security alert',
        'description': 'Antivirus / EDR reported something.',
        'categories': ['security'],
        'freshness_minutes': 15,
        'evidence': ['alert', 'alert_now', 'device_status', 'repeat_history'],
        'causes': [
            {'text': 'Treat as a possible incident until shown otherwise: check what was detected and whether '
                     'it was quarantined.', 'when': {}},
            {'text': 'Repeated detections on one computer suggest it was not cleaned.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
        ],
        # Never disable a defence: Rem0te labels such suggestions blocked.
        'remediations': [],
        'manual_steps': ['Review the detection in the security console; do not disable protection.',
                         'Follow the security incident procedure if anything was not quarantined.'],
        'verify_within_minutes': 24 * 60,
    },
    {
        'slug': 'backup-failure',
        'name': 'Backup failure',
        'description': 'A backup job failed.',
        'categories': ['backup'],
        'requires_integration': 'backup',
        'freshness_minutes': 24 * 60,
        'evidence': ['alert', 'alert_now', 'device_status', 'disk', 'repeat_history'],
        'causes': [
            {'text': 'Failed more than once: the backup has not completed recently; restore points are ageing.',
             'when': {'fact': 'repeat_count_30d', 'op': 'gte', 'value': 2}},
            {'text': 'The destination may be full or unreachable.', 'when': {}},
        ],
        'remediations': [],
        'manual_steps': ['Check the backup job log in the backup product.',
                         'Run the job again once the cause is fixed and confirm it completes.'],
        'verify_within_minutes': 24 * 60,
    },
]
