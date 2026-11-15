# Classic dashboard: audit and retirement plan

Status: audit (v3.17.681). The Classic dashboard stays. Nothing here removes it
or changes anyone's saved choice.

## What "Classic" is

* `core.dashboard_views.classic_dashboard`, template
  `templates/core/dashboard_classic.html`. It is the dashboard as it was before
  Phase 67: six count cards, Schedule, Tasks, Monitors and the location map.
* A user reaches it with the "Classic dashboard" button on the new dashboard
  (saved per user in `UserProfile.dashboard_variant = 'classic'`, posted to
  `core:dashboard_variant_save`) or for one view with `?layout=classic`.
* It has no saved layout of its own. It reads no `UserProfile.dashboard_layout`
  and no `core.DashboardRoleDefault`, and switching between the two dashboards
  touches neither (the button writes `dashboard_variant` only).

## Who uses it

Measure on production before deciding anything. Read-only queries:

```python
# python manage.py shell
from django.db.models import Count
from accounts.models import UserProfile
UserProfile.objects.values('dashboard_variant').annotate(n=Count('id'))
# Who, with their role (for the conversation with them):
UserProfile.objects.filter(dashboard_variant='classic').values(
    'user__username', 'user__is_superuser', 'user_type', 'global_role_template__name',
    'user__last_login')
```

```sql
SELECT dashboard_variant, COUNT(*) FROM accounts_userprofile GROUP BY dashboard_variant;
```

`?layout=classic` one-off views are not stored anywhere; count them from the web
server access log (`grep -c 'GET /core/dashboard/?layout=classic'`).

Preview / test databases (synthetic data, v3.17.681): 21 profiles, all
`modern`; no profile has a personal layout yet. These numbers say nothing
about production.

## Feature comparison

| Classic element | New dashboard equivalent | Notes |
|---|---|---|
| 2FA warning banner | `security_2fa` banner widget | Same rule (TOTP or Microsoft MFA sign-in); cannot be hidden or switched off by a role. |
| Passwords count card | `kpi_passwords` | New one is gated by the vault section rule; Classic showed the card (count 0) to users without `vault_view`. |
| Assets count card | `kpi_assets` | Same queryset. |
| Documents count card | `kpi_documents` | Same queryset. |
| Monitors count card | `kpi_monitors` | Adds "N down / N warning". |
| PSA companies card (shown when > 0) | `kpi_psa_companies` | Same rule (hidden at 0). |
| Active PSA tickets card (shown when > 0) | `kpi_psa_tickets` | Same rule. |
| My Work button | Header "My Work" | Same PSA flag. |
| Schedule (next 7 days) | `schedule` | Same `core.dashboard_panels.get_schedule`. |
| Tasks | `tasks` | Same `get_tasks`. |
| Monitors panel (healthy / warning / down) | `monitors` | Adds "Not checked yet". |
| Location map, device layer, satellite, dragging toggle, expand | `map` | Same endpoints and settings; the device layer is offered only to MSP staff the RMM pages admit (Classic showed the button to everyone and the request failed for the rest). Expand is the panel's expand button. |
| Switch to the other dashboard | "Classic dashboard" button / Classic's "New dashboard" button | Both ways. |

Nothing on Classic is missing from the new dashboard. The new dashboard adds the
service-desk figures and queues, SLA overview, workload, trends, approvals,
sales (pipeline, quotes, contract signatures and renewals, won / lost,
activity), manager panels (utilization, billing, reports), RMM alerts, audit
activity, system status, per-user layout and role defaults.

## Differences a Classic user will notice

1. **Default content differs by role.** Classic shows the same six cards to
   everyone. The new dashboard starts from the role's preset (for example an L1
   technician sees their queue and SLA figures, not the Passwords count).
   Everything Classic showed can be added back from Customize, unless the role
   configuration (Settings, Users & Access, Role Dashboards) switches it off.
2. **Cards a user cannot open are gone** rather than showing a link that
   refuses them.
3. **Density.** Compact by default; Comfortable is one click in Customize.
4. **Fixed-height panels on desktop** with internal scrolling, instead of a
   page that grows.

## Workflows to confirm before retirement

* A Classic user who wants "the six cards" gets them in one Customize session
  (or an administrator saves a role default with them).
* Customer users: both dashboards are scoped to the selected customer; the new
  one is covered by `core.tests.test_dashboard_r681.CustomerDashboardIsolationTests`.
* Global View (MSP staff, no customer selected): since v3.17.681 the new
  dashboard has all-clients widgets (`core.dashboard_global`, layout saved in
  `UserProfile.dashboard_global_layout`). Classic users still get the previous
  page (`classic_global_dashboard`, template `core/global_dashboard.html`),
  which now has a "New dashboard" button. Retiring Classic retires that page
  too; compare it with the Global View widgets before step 5.

## Saved-preference compatibility

* `dashboard_variant` is the only Classic preference. Leave the column and its
  values in place until Classic is gone; never delete or rewrite it in a data
  migration without the steps below.
* New-dashboard layouts (`UserProfile.dashboard_layout`) and role defaults
  (`core.DashboardRoleDefault`) are independent of the variant; a user who
  switches back to the new dashboard finds their layout untouched.

## Migration plan (proposed, not started)

1. **Measure** (above) for at least one release cycle. Note who uses Classic and
   their roles.
2. **Offer the equivalent layout.** For roles whose members use Classic, an
   administrator can save a role default listing `kpi_passwords`,
   `kpi_assets`, `kpi_documents`, `kpi_monitors`, `schedule`, `tasks`,
   `monitors`, `map` (Customize, "Save as role default"), or each user saves it
   personally.
3. **Announce** in the release notes and with a dismissible note on Classic,
   one release ahead.
4. **Switch the default, not the choice.** A later release may move Classic
   users to the new dashboard with a reversible data migration that records the
   previous value (for example in an audit row), keeping the Classic button for
   one more release.
5. **Retire.** Remove `classic_dashboard`, its template and the button only
   after step 4 shipped without regressions; keep `?layout=classic` answering
   with the new dashboard (no 404) so bookmarks keep working, and keep
   `dashboard_variant` until a final cleanup release.

Rollback at every step: the variant value is never lost, so restoring the code
restores the dashboard each user had.
