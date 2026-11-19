# Phase 100 — Optional simple PBX appliance (exploratory)

**Priority:** P4 · **Size:** XL if built · **Status:** planned — exploratory · Roadmap:
[Phase 100](../../ROADMAP.md) · Index: [Phases 96–100](README.md)

**This phase is research and a decision gate. It is not to be built until Phase 99 has shipped, has real users,
and the go/no-go criteria in §13 are met.** The shared compatibility and safety requirements in the
[index](README.md) apply to anything that is eventually built.

## 1. Goals and business value

- Give MSPs without a phone system, or small customers of an MSP, an optional, simple PBX that works with
  ClientSt0r out of the box: the MSP supplies SIP trunks, DIDs, extensions, SIP phones and softphones.
- Keep it entirely separate from ClientSt0r: its own VM or container, its own database, voice keeps working when
  ClientSt0r is offline.
- Never write a new SIP or media stack; package a proven open-source engine.
- Avoid the risk of owning telephony (patching, fraud, emergency calling) unless the demand justifies it.

## 2. Research summary

From the PBX research notes (unverified items stay unverified):

- **Engines.** Asterisk is GPLv2 (with a commercial dual license) and has a clear LTS cadence (22 LTS supported to
  2029-10-16). FreeSWITCH is MPL 1.1; its public 1.10 release notes run through August 2024 and its direction is
  tied to a vendor's commercial tier; current status needs verification.
- **Existing distributions** an MSP can already run instead: FreePBX 17 (GPL core with closed commercial modules),
  FusionPBX (FreeSWITCH GUI, MPL), Wazo Platform (GPLv3, regular recent releases). One older distribution's
  maintenance status could not be confirmed and is treated as at risk.
- **Security record.** Asterisk publishes security advisories several times a year (for example a SIP digest-auth
  crash, CVE-2025-57767). An appliance owner must patch OS, engine, PJSIP and GUI on a short clock.
- **Emergency calling (US).** Kari's Law (direct 911 dialing without a prefix, on-site notification) and RAY
  BAUM'S Act section 506 (dispatchable location) apply to multi-line telephone systems; rules in FCC 19-76; check
  47 CFR 9.16 for the current text. Other jurisdictions were not researched.
- **Recording consent.** Most US states are one-party consent, a minority all-party; GDPR treats voice as personal
  data needing a lawful basis. Not legal advice.
- **Resource footprint.** No sourced sizing was found; it must be measured.

## 3. Existing components to reuse

| Need | Reuse |
|---|---|
| ClientSt0r integration | Phase 99 bridge and signed event contract, unchanged; the appliance ships the bridge preinstalled |
| Health monitoring | Phase 99 health fields and the Phase 82 `pbx` event source |
| Business hours | Phase 93 calendars (exported to the appliance as read-only configuration, optional) |
| Packaging experience | Phase 42 Docker image and `docker-entrypoint.sh` patterns; Phase 59 verified updates and signed releases |
| Backups | Phase 94 off-host backup approach (applied to the appliance's own data) |

## 4. New functionality (minimum feature set, if built)

SIP trunks; DID routing; extensions and users; ring groups; sales and support queues; a basic IVR; voicemail;
business hours and holidays; forwarding and transfers; call history; softphone and SIP phone provisioning;
WebRTC where practical; basic reporting; ClientSt0r popups and ticket integration through the Phase 99 bridge;
health monitoring; backup, restore and update.

Explicitly out of scope: full PBX administration parity, a custom SIP stack, call center analytics, billing of
calls, fax.

## 5. Architecture

- A separate appliance image (VM image and container image) containing: Asterisk 22 LTS with PJSIP (recommended
  engine, §6), a minimal configuration service with its own small web UI for the minimum feature set, the Phase 99
  bridge, a firewall and intrusion-prevention layer, and an update agent.
- Configuration is generated from the appliance's own database into engine configuration files; ClientSt0r never
  writes PBX configuration directly. A later option is for ClientSt0r to **link** to the appliance UI with
  single sign-on, not to embed PBX administration.
- Isolation: no shared database, no shared secrets except the bridge token and HMAC secret; the appliance runs and
  routes calls with ClientSt0r unreachable.

## 6. Engine evaluation: Asterisk versus FreeSWITCH

| Criterion | Asterisk 22 LTS | FreeSWITCH |
|---|---|---|
| License | GPLv2 (+ commercial); shipping an image means honoring source-offer obligations | MPL 1.1 (file-level copyleft) |
| Release and support clock | Published LTS to 2029 | 1.10.x public notes through 2024; status to verify |
| Integration with Phase 99 | Same AMI bridge as the MVP | Needs the event-socket adapter (later Phase 99 adapter) |
| Ecosystem and operator familiarity | Largest | Strong in carrier and platform deployments |
| Footprint | Not sourced; measure | Not sourced; measure |

Recommendation if built: Asterisk 22 LTS, because it reuses the Phase 99 adapter and has a known support window.
FreeSWITCH only if measured concurrency needs or licensing require it.

## 7. UI and workflows

- In ClientSt0r: nothing new beyond Phase 99 (the appliance appears as a Phone System connection of platform
  "ClientSt0r PBX appliance"). Possibly a link to the appliance UI.
- In the appliance: a small UI for the minimum feature set, setup wizard for trunk, DIDs, extensions and the
  emergency-calling configuration (§9).

## 8. Proposed data model changes

None in ClientSt0r beyond Phase 99 (a `platform` choice). The appliance has its own schema, out of this
repository's migrations.

## 9. Security and compliance requirements (if built)

- **Toll-fraud prevention by default:** no public SIP or management exposure unless required; IP allowlists and
  intrusion prevention (fail2ban or equivalent); strong unique extension secrets generated by the appliance;
  anonymous and guest SIP disabled; per-extension and per-trunk concurrent-call and spend caps; international and
  premium-rate destinations blocked until explicitly allowed; alerts on after-hours international attempts.
- **Transport:** SIP over TLS and SRTP for phones and trunks where supported; WebRTC with WSS and DTLS-SRTP and a
  browser-trusted certificate; AMI bound to localhost.
- **Emergency calling (US MLTS):** direct 911 dialing without a prefix; on-site notification (email and on-screen);
  per-extension dispatchable location management; documented behavior for remote and softphone users; a clear
  statement of what is not supported outside the US.
- **Updates:** signed update channel; security releases of the engine and PJSIP applied within days; OS patching
  automated; rollback.
- **Recording:** off by default; announcement prompts available; retention settings.
- **Backup and restore:** encrypted configuration and voicemail backups off the appliance; tested restore.

## 10. Backward compatibility

No effect on ClientSt0r installs; the appliance is a separate optional product. Phase 99 works identically with
or without it.

## 11. Migration strategy

Not applicable to ClientSt0r. For the appliance: versioned schema with forward migrations and backups before every
update.

## 12. Feature flags and module defaults

None in ClientSt0r. The appliance is never installed by `install.sh` or the ClientSt0r Docker compose file by
default; at most an optional, separate compose profile.

## 13. Go / no-go criteria

**Go only if all hold:**

1. Phase 99 has shipped with real users on at least one verified platform.
2. Documented demand: MSPs ask for it and the existing distributions (FreePBX, FusionPBX, Wazo) do not fit their
   case. The threshold is an open decision.
3. The patch burden can be staffed: signed updates and security response within days for the engine and PJSIP.
4. Emergency calling scope is built and documented for US multi-line systems, with an explicit statement for other
   jurisdictions, and legal review of liability.
5. Toll-fraud defaults are on out of the box.
6. Licensing review done (GPLv2 source offer, trademarks, exclusion of closed commercial modules).
7. Footprint and call capacity measured on target hardware.

**No-go** if the appliance would need full PBX configuration parity in a custom GUI, or long-term support cannot be
committed.

## 14. Testing strategy (if built)

- Containerized Asterisk tests reusing the Phase 99 CI harness (SIPp calls through trunks, IVR, queues, voicemail).
- Security tests: scans for exposed services, brute-force lockout, destination blocking, spend caps.
- Emergency-calling tests against a test route (never live 911): direct dial without prefix, notification, location
  presentation.
- Update and rollback rehearsals, backup and restore rehearsals.
- Load test to establish the published capacity figures.

## 15. Definition of Done (for the exploratory phase)

- 100.1 research brief updated and verified (engine status, licensing, footprint measured on a test VM).
- 100.2 go/no-go review held and recorded against §13.
- If go: a separate implementation plan with its own phase number; this phase does not itself build the appliance.

## 16. Dependencies and sequence

Requires Phase 99 (shipped and proven); benefits from Phases 93 (calendars), 94 (backups) and 59 (verified
updates). Sequence: 100.1 research refresh and footprint measurement → 100.2 go/no-go review → 100.3 (only on go)
separate implementation plan.

## 17. Limitations and open decisions

- Emergency-calling obligations and liability make this the riskiest item in the roadmap.
- Open decision: go/no-go owner and demand threshold (index item 16).
