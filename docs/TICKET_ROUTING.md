# Ticket Routing — admin guide

Ticket Routing decides which queue, team or technician a ticket goes to. It is **optional**, it is **not AI**
(it works with every AI feature switched off), and it is **Off** on fresh installs and on upgraded installs until an
administrator turns it on. With routing Off, email intake, email routing rules, service catalog defaults, manual
assignment and workflow rules behave exactly as they did before.

## Turning it on

1. **Settings → PSA** (`/psa/settings/`, superusers) shows a *Ticket Routing* card: pick the MSP-wide default
   (**Off**, **Suggest only** or **Automatic**) and save. The card links to the full page.
2. **PSA → Ticket Routing** (`/psa/routing/`) holds everything else: reroute options, business hours, customer
   overrides, rules, on-call shifts, Test routing and Triage.
3. Each customer **inherits** the MSP default unless you override it under *Customers* (Inherit / Off / Suggest only /
   Automatic). A customer can also be limited to a list of technicians routing may choose.

| Mode | What happens |
|---|---|
| Off | Nothing. No routing history is written. |
| Suggest only | Routing works out a destination and records it as a suggestion on the ticket (staff only). Nothing changes until a dispatcher clicks **Accept**. |
| Automatic | Routing assigns the ticket and records the rule version, trigger, previous and new assignment and the reason in the ticket's staff-only routing history. |

## Rules

**PSA → Ticket Routing → New rule.** A rule has conditions, a destination and a fallback. Every condition you set
must match; leave one empty to ignore it.

Conditions: customer (the rule's scope), intake source (portal, email, API, monitoring, RMM, anonymous form…),
ticket type, priority, current queue, tags, words in the subject or description, service catalog item, contract
(has one / has none / type), business hours or after hours, and SLA risk (percent of the resolution window used).
Business hours are set on the routing page (days, start, end, time zone); holidays from Resourcing count as after
hours. Site conditions (specific sites, or "has a site" / "has no site") use the site on the ticket.

**Request answers** (up to five per rule) match what the customer entered on a portal request form: equals, does not
equal, is one of, is not one of, is answered, is not answered, contains. Pick the request type under *service* too,
so the question keys mean what you expect; the review step warns about keys no selected form has. An unanswered
question only satisfies "is not answered", "does not equal" and "is not one of". The form builder's **Routing
preview** shows which rule a request with given answers would match for a chosen customer.

Destinations:

| Destination | Result |
|---|---|
| Queue only | Moves the ticket to the queue; nobody is assigned. |
| Named technician | Assigns that technician, if they qualify (see *Candidates*). |
| Team | Sets the ticket's team (a user group) and optionally a queue; nobody is assigned. |
| Round-robin | Each qualifying technician in turn. |
| Skill match | Technicians holding the listed skills (Resourcing → skills, optional minimum level); the least busy wins. |
| Least-loaded | The qualifying technician with the fewest open tickets. |

Round-robin, skill match and least-loaded can be limited to a team and to technicians **on call now**
(**PSA → Ticket Routing → On call**). Unless a rule asks for on-call, people on approved leave or outside their
Resourcing working hours are skipped. On call overrides working hours; leave still excludes someone.

Fallback, when nobody qualifies: put the ticket in a chosen queue (e.g. *Escalations*) unassigned, or leave it
unassigned in **Triage** (`/psa/routing/triage/`). Either way the reason, and every skipped technician with the
reason they were skipped, is recorded.

### Review before saving

Submitting the form shows a plain-language summary ("For tickets from Customer A, arriving by Client Portal: assign it
in turn to each authorized technician in team Helpdesk…"), conflicts, and how the rule interacts with other
automation. Blocking problems (a missing queue, a technician who is not authorized for the customer, an empty team)
stop the rule being activated; it can still be saved inactive. Warnings cover two rules with the same scope and
priority, and a rule that can never win because an earlier rule matches everything it matches.

Every save creates a new **version**. Routing history points at the version that made each decision. Saving,
activating or deactivating a rule never reassigns tickets that already exist.

### Order and precedence

1. **Email routing rules** decide, at intake, which customer an email belongs to and may set queue and priority.
2. **Request type (service catalog) defaults** set queue, priority, type, team and, optionally, a default technician
   on portal requests when the ticket is created. A default technician who may not work for that customer is not
   assigned (an internal note says why). The customer's own urgency answer is recorded on the ticket but never
   changes the priority.
3. **Manual assignment and workflow rules**: a ticket created with an assignee, or assigned by a workflow rule while it
   is saved, keeps that assignee (routing records "already assigned").
4. **Ticket Routing** runs after the ticket is saved: this customer's rules first, then rules for every customer,
   each by priority (lower first); the first rule whose conditions all match wins. A rule that names a queue replaces
   the intake queue; otherwise the queue stays.

The same explanation is on the routing page and, per rule, on the review step.

## When routing runs

- **On creation** — always, when routing is on for the customer. Every intake path counts: email, portal and guided
  requests, the staff form, the API and mobile app, monitoring and security alerts.
- **On customer reply**, **on reopen**, and **once when the SLA reaches N %** — each optional (MSP-wide settings).

On a reroute, a **dispatcher's manual assignment is kept** (default; switch off *Preserve manual assignment* to allow
reroutes to move it), and a current assignee who still qualifies stays. A loop guard limits automatic reroutes per
ticket (default 5).

## Candidates

Only **active MSP technicians** are ever candidates. A technician is skipped, with the reason recorded, when:

- their role gives them no ticket access at that customer (a global role without *View tickets*);
- the customer limits routing to a list they are not on;
- they are contained by theft detection, or explicitly denied at that customer (Technician access);
- they are not in the rule's team, lack a required skill, are not on call (when required), are on leave, or are
  outside their working hours.

Customer users are never candidates.

## What routing will not do

- Change the ticket's customer. The customer is checked first; if it is doubtful (the requester contact or e-mail
  belongs to another customer, or the customer is inactive) the ticket is left unassigned and listed in Triage.
- Reset or touch the SLA clock, due dates or pause time.
- Grant access, memberships or roles.
- Start a remote session or authorise any endpoint action.
- Send anything itself. The normal "ticket assigned to you" notification goes out once when an assignment is applied.

## Duplicates and concurrency

Each routing pass first claims a unique `(ticket, trigger)` record, so a repeated trigger does nothing: a duplicate
e-mail (same Message-ID) creates one ticket, one assignment and one notification. Round-robin turns are reserved
inside the same transaction (row lock on MariaDB/PostgreSQL, write lock on SQLite), so two tickets arriving together
get different technicians.

The email poller now skips an inbound message whose Message-ID it has already processed for that customer. This
applies whether routing is on or off: before, a message fetched twice (for example when marking it read failed)
created a second ticket.

## Test routing

**PSA → Ticket Routing → Test routing** (`/psa/routing/test/`) evaluates an existing ticket you are authorized to see,
or a sample ticket you describe (customer, source, priority, type, queue, service, tags, subject, time). It shows the
mode, the customer check, each rule evaluated and why it did or did not match, the winning rule, eligible and skipped
technicians with reasons, the destination and the reason. It changes no data, uses up no round-robin turn and sends no
notification.

## Suggestions and history

With **Suggest only**, the ticket page (staff only) shows the suggestion with **Accept** and **Dismiss**. Accepting
re-checks that the ticket has not changed and that the technician still qualifies, then applies it. Suggestions waiting
and fallbacks appear in Triage.

The *Routing* panel on the ticket page lists every decision, manual override and suggestion. It is never shown in the
customer portal and is not part of the ticket conversation.

## Permissions

Three role flags (role editor at `/accounts/roles/`, *Ticket Routing* card), all off by default and only effective for MSP technicians;
superusers hold all three:

| Flag | Allows |
|---|---|
| Manage routing settings, rules and on-call | `/psa/routing/` settings, customers, rules, on-call shifts, the Settings → PSA card |
| Test routing | the Test routing page |
| Accept / reject routing suggestions | Accept and Dismiss on tickets |

Built-in Owner, Administrator and IT Manager templates include all three on new installs. Existing installs keep their
roles as they are: grant the flags where you want them. Manual assignment itself still uses the existing assignment
permission.

## Upgrading

The upgrade adds tables (`ticket_routing` app, migration `0001_initial`) and three role flags (`accounts` migration
`0039`). No settings row is created and every flag defaults to off, so routing stays Off until you turn it on.
Workflow rules and raw JSON rules are unchanged; the workflow rule builder now also offers the existing round-robin,
skill-group and least-loaded actions, and opens any rule it cannot show exactly in raw JSON so nothing is lost on save.
