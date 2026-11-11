# AI Troubleshoot: administrator guide

**OPTIONAL AI.** AI Troubleshoot is off unless the installation's AI master switch (`psa_ai_enabled`, in Settings) is on **and** a customer's AI policy allows it. With AI off, every AI Troubleshoot page and endpoint answers 404, and tickets, devices, RMM panels and support workflows work exactly as they do without AI.

AI Troubleshoot reads what a technician can already see on a ticket or an RMM device, sends a filtered and redacted summary to a model the customer's policy allows, and shows a structured answer: likely causes, read-only diagnostic steps, relevant runbooks and KB articles, suggested approved actions, risk, and a draft customer response. It never runs anything.

## What AI Troubleshoot can and cannot do

| It can | It cannot |
|---|---|
| Read the ticket's subject, description and public conversation, the linked devices' RMM status, active alerts, and completed read-only diagnostics, if the customer's sharing rules allow each of them | Read vault data, internal notes, attachments, raw RMM payloads or remote-session data. These are never included, whatever the settings |
| Suggest read-only diagnostic steps, with optional commands shown as text | Run a command, script or action, or call an RMM or Rem0te |
| Point at KB articles and runbooks the technician may open | Invent a runbook; a reference to one that wasn't offered is dropped |
| Recommend an action the device's RMM advertises **and** the technician may request | Approve anything. "Request…" opens the normal request flow, and the RMM's approvers decide |
| Draft a customer response, shown only to technicians who may draft replies | Post to the ticket or contact the customer |

Each session page keeps four layers apart: **Observations** (what was sent, with source and freshness), **AI inference** (labelled with the model and prompt version), **Technician-requested actions** (a person asked, through the normal flow) and **Verified results** (what the RMM reported in signed status updates).

## Setup

All of this lives under **PSA → AI models** (`/psa/ai/profiles/`). Only superusers can open it.

### 1. Gateway keys

Run `python manage.py ai_gateway_keygen` once. Provider API keys are sealed to the gateway's public key as soon as they are typed, and can't be shown again by any page.

- `AI_GATEWAY_MODE=in_process` (default): the web process opens keys and calls the provider itself.
- `AI_GATEWAY_MODE=worker`: only the `ai_gateway_worker` service (which runs without the vault master key) can open keys. Sessions wait for the worker, and the session page shows progress while they wait.

The gateway calls only fixed provider hosts. It follows no redirects and caps response size. An Ollama address is used only after a protected change approves it (**Propose address**, which a second administrator confirms).

### 2. Model profiles

A profile is one provider and model: Claude (Anthropic), OpenAI, or Ollama (local). It has prices, used for estimates and budgets, and a credential owner:

- **Customer company**: the customer's own key, usable only for that customer.
- **MSP**: your key, usable only for the customers you assign to it.
- **Technician**: one technician's own key (added under **My AI keys**), usable only by them and only where the customer's policy allows technician keys. Never usable under a local-only policy.

A profile is off until you enable it. Marking one **economical** makes it the default when a policy names none.

### 3. Customer AI policies

Without a policy a customer allows no AI. On each customer's policy:

- **Exclude this customer from every AI feature** overrides everything else.
- **AI Troubleshoot**: switch it on, then choose a **primary** and an optional **secondary** model from the allowed profiles.
- **Routing**:
  - *Primary only*
  - *Primary, then secondary* if the primary is unusable or fails
  - *Prefer an approved on-premises model*
  - *Prefer the cheaper*
- **Multi-model analysis** runs both models side by side and lists where they agree and disagree. It needs both models, and technicians need the "Compare models" access.
- **Local only**: the processor and the model must both be on-premises.
- **Usage limits**: runs per day for the customer and per technician.

### 4. Budgets

Every AI feature (ticket analysis, Rem0te jobs, reply drafts, triage and AI Troubleshoot) reserves its worst-case cost before calling a model. Afterwards the reservation is settled to the actual cost, or released if the call fails. A reservation must fit under every ceiling at once, and is taken atomically so concurrent runs can't overshoot:

1. the customer's **daily budget** (cents; 0 = no spend);
2. the customer's **monthly budget** (cents; blank = no monthly ceiling);
3. the **installation-wide monthly cap** for all customers together (**Installation-wide limits** card; blank = no cap). The card and every customer's policy page show this month's usage.

When a ceiling refuses, nothing is sent and the technician sees which limit was reached. When the installation cap is reached, every customer is refused with a message saying so, until next month or until a superuser raises the cap.

### 5. Sharing rules

These are per customer, on the policy page. They are applied before any prompt text exists, and the session page lists what was withheld:

| Rule | Default | When off |
|---|---|---|
| Ticket text | on | Subject, description and conversation are withheld |
| Device data | on | Device status, alerts, diagnostics and device job output are withheld |
| Network identifiers | off | Hostnames, IP and MAC addresses are replaced with placeholders |
| Contact data | off | Requester and contact names are replaced with `[contact]` |
| KB titles | on | No runbooks or KB articles are offered to the model |

Text is also redacted for secrets (passwords, tokens, keys) before it leaves. Device job output a technician added to the ticket is quoted to the model as untrusted data and highlighted on the session page.

### 6. Read-only command allowlist

Suggested diagnostic commands must pass the built-in denylist, which drops anything that changes a system: restarts, deletes, installs, registry and service changes, downloads, elevation, pipes into a shell, and similar. On the **Installation-wide limits** card you can also set an **allowlist**. Once any pattern is set, a command is kept only if it matches one:

```
# one pattern per line; * = anything, ? = one character; case-insensitive
Get-Service *
Get-EventLog -LogName * -Newest *
ipconfig /all
ping -n ? *
df -h*
```

The denylist applies to allowlisted commands too, and a pattern the denylist would always block is refused when you save. Dropped steps are counted in the session's warnings. Commands are only ever shown as text.

## Technician access

Technicians need a technician-access preset at the customer that includes **Analyze ticket** (one model) or **Compare models** (multi-model). For a ticket session they must also be able to work on that ticket. Another customer's ticket, device or session answers 404. Every gate is checked again when a queued run executes, so a demotion, a policy change or a disabled profile stops runs that haven't started yet.

## Runbook and KB matching

The words of the problem (ticket subject, alert text, then the description) are matched locally against the **published** KB articles and runbooks the technician may open:

- the customer's own articles, which need docs access at that customer;
- the global KB, which is MSP staff only.

Drafts, archived items and templates never match. Each candidate is scored by where the words appear: 3 points for the title, 2 for a tag or the category, 1 for the body only. Anything under 2 points is ignored, and the best eight are offered. Only titles reach the model, and only when KB titles are shared. Each one is labelled *customer-visible* (shown in the portal) or *internal only*, and the model is told to mention only customer-visible ones in a customer response.

## Auditing and history

Starting a session and requesting an action are written to the audit log, with the profiles used, the observation digest, and what was withheld and redacted. Sessions appear in the ticket's AI history, subject to the customer's history retention.
