"""One-click support workflows (Phase 7). Not AI: they work with AI off.

For a ticket opened by a monitoring alert: gather authorized read-only
evidence (with its age), show rule-based likely causes, offer only the
Rem0te catalog actions the paired Rem0te advertises, explain their impact,
send a chosen one through the existing fix-referral flow for Rem0te's own
approval, track it, confirm the outcome from subsequent monitoring, and
write the technician's note on the ticket.

  builtins.py   the built-in workflow definitions (data)
  models.py     admin-edited definitions, runs
  engine.py     evidence, causes, remediations, proposals, verification
  receivers.py  alert recovery → outcome verification
  views.py      the ticket's workflow page and the admin page
"""
