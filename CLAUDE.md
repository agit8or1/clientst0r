# Project conventions for AI assistants

This file is loaded automatically by AI assistants (Claude Code etc.) when working in this repo. Conventions below are **mandatory** unless the user explicitly overrides them in the conversation.

## Roadmap discipline

**Every release that adds, extends, or completes a feature MUST update `docs/ROADMAP.md` in the same commit.**

Why: the roadmap is the single source of truth for shipped + in-progress + planned features. It's published in **four** surfaces (in-app HTML at `/core/roadmap/`, About-page card, GitHub, and a polling-friendly JSON feed at `/core/roadmap.json`). If it gets stale, all four surfaces lie.

How (manual sub-bullets):
- Annotate the matching sub-bullet with the version: `*(shipped v3.17.NNN)*` or `*(partial — X shipped v3.17.NNN; Y deferred)*`.
- For new feature requests not on the roadmap yet, ADD them as planned items (not implemented) before / alongside building them.
- The phase record is the only place a status is written: the `## Phase N — …` header plus the `<!-- phase: … -->` line under it (workstream, stage, state, view, deps, next, blocker). The dashboard tables, NOW/NEXT/LATER, blockers and per-phase status lines are generated — run `python3 scripts/roadmap_dashboard.py` after editing; `core.tests.test_roadmap_dashboard` fails when the page is out of date. See "How to update this roadmap" at the end of `docs/ROADMAP.md`.
- When a whole phase completes, move its details verbatim to `docs/ROADMAP_HISTORY.md` and leave the link; never delete history.
- Keep `<a id="phase-N"></a>` above every phase header (GitHub and the in-app page slug headings differently).
- Bump `config/version.py`, write a `CHANGELOG.md` entry, and update `docs/ROADMAP.md` — all in one commit.

How (phase-header status — required for the JSON feed):
- The JSON endpoint at `/core/roadmap.json` parses each `## Phase N — Title ...` header to compute status. Use **one of these** parseable status markers on the header line so the feed updates automatically:
  - `[planned]` — default (or no marker)
  - `[in progress]`
  - `[shipped — v3.17.NNN]` — preferred form for completed phases that mark the version
  - `[complete]` — preferred when the entire phase + all sub-phases are done
  - `**— shipped**` or `**— complete**` (legacy inline form, still parseable)
  - Use exactly these forms (no extra words inside the brackets): the in-app page badges only `[in progress]` verbatim. Partial, Blocked, Deferred and Needs-verification go in the record line as `state=`.
- When a phase **completes**, ALWAYS update the header marker. Otherwise the JSON feed shows it as planned and the website's polling won't reflect reality.
- Sub-phase items (under a phase) carry their own `*(shipped vN.N.N)*` annotations on the bullet — those are visible in the rendered HTML but don't appear in the JSON feed (which is per-phase, not per-bullet).

How (downstream consumers):
- External dashboards / status pages can poll `GET /core/roadmap.json`. Cached server-side; light to call. Response shape: `{generated_at, current_version, phase_count, shipped_count, phases: [{number, title, size, status, version}, ...]}`. Status enum: `planned` / `in_progress` / `shipped` / `complete`.

## Release pattern

Every release commit ships:
1. The actual feature change
2. `config/version.py` bumped (string + patch int both)
3. `CHANGELOG.md` entry at the top with `## [N.N.N] - YYYY-MM-DD`
4. `docs/ROADMAP.md` updated if the release touches a roadmap item
5. `git push origin HEAD:main` from the worktree (not `/home/administrator/`)

The post-commit hook auto-creates the version tag locally; the pre-push hook pushes unpushed tags.

Security labelling: the in-app update badge turns into a red "Security Update" only for a release whose notes have a `### Critical security` heading or whose title starts with "Critical security". Use that only for fixes an administrator should install right away (exploitable without special access, data exposure, authentication bypass). Routine hardening and review fixes go under `### Fixed` or `### Changed`, and release titles describe the change without the word "security" where it would read as an alert.

## Wording for documentation

- **No competitor name-dropping** in roadmap or marketing prose. Don't position the project as "X parity" or "matches Y's wedge". Describe what the product does on its own merits.
- Integration listings (e.g. "We integrate with ConnectWise Manage, Autotask, etc.") ARE factual feature statements — keep those as-is.
- AI-assisted features must be explicitly tagged **OPTIONAL AI** in the roadmap and gated by `psa_ai_enabled`.
- Don't position planned items as fully implemented. Use "planned", "in progress", "extends X (shipped vN.N.N)" markers.

## Standalone operation and optional integration (permanent)

Clientst0r is a complete, independently deployable application. Running it with no RMM, with Rem0te, with another
supported RMM, with several providers, or next to unrelated software are all first-class configurations.

- Never require Rem0te, another MSPZero app, Agit8or Connect, a central server or a shared identity provider for any
  local feature, for install, setup, sign-in, upgrade, backup or restore. Clientst0r keeps its own installer, database,
  local authentication and break-glass recovery, users, customers, roles, settings, API, AI configuration, notifications,
  reports, backups, updates and documentation.
- Don't restrict standalone features to push adoption of Rem0te, and don't degrade other RMM integrations in its favour.
- Standalone UI: no application switcher when no peer is configured, no peer-only widgets, nav sections or empty space,
  no nags, upsells or broken controls. Optional integrations stay discoverable in Administration → Integrations.
- Paired UI shows only capabilities both installed versions support.
- Fault isolation: outbound calls have bounded timeouts, limited retries with backoff, and stay off the page-render path;
  a down, slow, revoked or incompatible peer never blocks local pages; external data shows its last successful sync
  time and is never shown as current or healthy when stale.
- Removing or disabling an integration never deletes local customer data, tickets, documents, billing or audit records.
- Cross-app security: never share cookies or sessions between apps, never trust a peer's customer ID, role or user
  without verification, no arbitrary redirect URLs, no secrets in URLs. Protocol changes go through the integration
  coordination document; never edit the Rem0te repository from here.
- Clientst0r never executes privileged actions in an RMM directly (nor does AI): it requests and records; the RMM
  authorizes and executes.

Details and the test matrix: `docs/ux/STANDALONE_REQUIREMENTS.md`, `docs/ux/CROSS_APP_UX_CONTRACT.md`.

## Shared design system

- The design specification (`docs/ux/SHARED_DESIGN_SYSTEM.md`, `docs/ux/design-tokens.json`, semver) is a
  development-time spec, not a runtime dependency: every app bundles its own CSS, fonts and icons; no CDNs and no assets
  loaded from another app.
- Use semantic tokens instead of hard-coded colours and sizes in new or changed templates; text and UI colour pairs must
  meet WCAG 2.2 AA (`scripts/ux/check_design_tokens.py`, `core/tests/test_design_tokens.py`).
- Changing a token is a spec version change: bump the version in `design-tokens.json` and note it in
  `docs/ux/REM0TE_HANDOFF.md`.
- Never remove an approval, confirmation, step-up or server-side check to save a click.

## Dev workflow

- All edits go through `/home/administrator/.dev-worktree/` on the `dev-work` branch.
- Don't restart gunicorn — the user clicks Apply.
- Don't run destructive git commands (force-push, reset --hard) without explicit user approval.

## Testing

- New models / views / API endpoints need a test in the matching app's `tests.py`.
- Run `manage.py test <app>` before committing — fail fast.
- View tests use `@override_settings(MIDDLEWARE=TEST_MIDDLEWARE, SECURE_SSL_REDIRECT=False)` to dodge the 2FA + HTTPS-redirect middleware.
