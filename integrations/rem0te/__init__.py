"""
Rem0te's ticket-rmm-v1 protocol (Ed25519), ClientSt0r side.

Rem0te owns this contract. A vendored, pinned copy of it lives in
`contract/` (schemas, fixtures, README, openapi) with the revision it was
copied from in `contract/PIN.json`; `pin.py` exposes that pin.

  protocol.py   canonical JSON, Ed25519, the four signing strings,
                EdDSA delegation JWS
  schema.py     a JSON-Schema (2020-12 subset) validator for the vendored
                schemas
  identity.py   ClientSt0r's own request and delegation keys
  pairing.py    per-connection Rem0te settings and Check pairing
  client.py     signed requests ClientSt0r sends to Rem0te
  inbound.py    verifying Rem0te's signed requests and events
  jobs.py       analysis jobs: submit, poll, events, inference
  alerts.py     alert events → tickets, ticket links back
  actions.py    catalog action proposals

Other RMM providers keep using the HMAC pairing in psa_ai.services
.integration_auth. A Rem0te connection never does: there is no fallback from
Ed25519 to HMAC anywhere in this package.
"""
