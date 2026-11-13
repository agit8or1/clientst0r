# Pulse checks

Pulse checks are short service-feedback surveys you send to people at your
client organizations: "How are we doing overall?", "How likely are you to
recommend us?", "Anything we could do better?". Send one by hand, or let it
repeat every month or every quarter.

They are separate from the per-ticket satisfaction survey (CSAT), which asks
about one resolved ticket. A pulse check asks about the relationship as a
whole and goes to the people you choose.

## Turning it on

Pulse checks are an optional module and are **off by default**.

1. Go to **Settings → System → Optional modules** (superusers).
2. Turn on **Pulse checks**.

While it is off, the menu entry is hidden, every pulse check page (staff and
portal) answers 404, links already e-mailed stop working, and the scheduled
task sends nothing. Turning it back on brings everything back as it was.

E-mailed links need outgoing e-mail (**Settings → Email / SMTP**). Without
it, sends are still recorded and people with a portal account can answer
from the portal's **Feedback** page; the send page shows how many were
e-mailed.

## Creating a pulse check

MSP staff open **Clients → Pulse Checks → New pulse check**.

- **Name and intro text** — the intro is shown above the questions and in
  the e-mail.
- **Questions** — up to twelve. Types:
  - *Rating 1–5* (poor to excellent)
  - *Likelihood to recommend 0–10* (used for the NPS score)
  - *Yes / no*
  - *Free text*

  Mark each as required or optional. Two to five questions get the most
  answers. Every send keeps a copy of the questions it asked, so editing the
  pulse check later never changes past results.
- **Who it goes to** — see below.
- **Schedule** — *Not repeated* (send by hand), *Monthly* or *Quarterly*, the
  day of the month (1–28; quarterly checks go out in January, April, July and
  October), a start date, and how many days each link stays open (1–90,
  default 14).

Creating and editing a pulse check is recorded in the audit log.

## Choosing the audience

**Organizations:** *All clients* (every active organization except those of
type Internal / Staff or Subcontractor) or the organizations you pick.
Inactive organizations never receive a send.

**People**, always within those organizations:

| Option | Who receives it |
|---|---|
| Everyone with a portal account | Every active member of the organization with an active account and an e-mail address. Tick *Also contacts* to add the organization's contacts that have an e-mail address. |
| Only people with the roles below | Members matching a **role group** — Owners, Managers / administrators (members whose role can administer the organization), Editors, Read-only users — or holding one of the chosen **named roles** as their primary or an additional role. |
| Only the people chosen below | The chosen portal users (at each chosen organization they belong to) and the chosen contacts (at their own organization, if it is chosen). |

Always left out:

- MSP staff, even if they hold a membership at a client;
- anyone who opted out (see below);
- duplicates — each person gets one request per organization; when a portal
  user and a contact share an address, the portal user is kept.

The **Send now** page lists every recipient by organization before anything
is sent.

## Sending

- **By hand:** open the pulse check and click **Send now…**, review the
  recipients, then confirm.
- **On a schedule:** the scheduled task *Pulse Check Scheduled Sends*
  (Settings → Scheduler, hourly) sends each active monthly or quarterly
  pulse check once per period, on or after its day of the month. Running it
  again in the same month or quarter sends nothing more, so it is safe to
  rerun. It can also be run by hand: `python manage.py pulse_send_due`.

Each recipient gets their own link. The link:

- needs no sign-in and opens only that one person's request;
- can be answered once — opening it again shows that it was answered, and
  answers cannot be changed;
- closes when the send's open period ends.

Each send writes audit log entries: one for the whole send and one per
organization.

## Answering in the portal

When the module is on, the customer portal shows a **Feedback** link. Portal
users see their open requests for the customer they are working in, answer
them there, and see what they answered before. They never see anyone else's
requests or answers.

## Opting out

Every e-mail has a "Don't want these feedback requests?" link that stops all
pulse check e-mails for that address. Portal users can also switch them off
and on again on the **Feedback** page. Staff can see the list under
**Pulse Checks → Opt-outs**; only the person can turn requests back on.
Other e-mail (ticket notifications, CSAT) is not affected.

## Results

- **Pulse check page:** response rate, average rating (1–5 questions), NPS
  (−100 to 100: % of 9–10 answers minus % of 0–6 answers), per-question
  results, yes / no share, comments, a per-organization table and a table of
  sends. Filter by organization.
- **Send page:** the same for one send, plus each recipient, whether the
  e-mail went out, and when they answered.
- **Client record:** a *Pulse checks* card with the last six sends that
  reached that client — date, response rate, average rating and NPS.

Only MSP staff see results. Staff limited to some clients see only those
clients' answers, cannot edit or send a pulse check that reaches other
clients, and cannot use *All clients*.

## Reference

| What | Where |
|---|---|
| Switch | `SystemSetting.pulse_enabled` (Settings → System → Optional modules) |
| Staff pages | `/pulse/` (MSP staff only) |
| Portal pages | `/portal/feedback/` |
| E-mailed answer link | `/portal/feedback/r/<token>/` |
| Opt-out link | `/portal/feedback/opt-out/<token>/` |
| Scheduled task | `pulse_send_due` (`python manage.py pulse_send_due`) |
| App | `pulse/` |
