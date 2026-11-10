"""Ticket routing (optional).

Decides which queue, team or technician a new or rerouted ticket goes to.
Off by default on fresh installs and upgrades; see docs/TICKET_ROUTING.md.

Module map:
  models.py   settings, rules + immutable rule versions, decisions (history),
              round-robin pointers, on-call shifts
  engine.py   read-only evaluation: customer check, rule matching, candidates
  service.py  the only code that writes: claims, applies, suggests, accepts
  review.py   plain-language summaries, conflict checks, precedence notes
  signals.py  hooks on ticket save (create / reopen / manual override)
"""
