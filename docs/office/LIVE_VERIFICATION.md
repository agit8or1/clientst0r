# Office live verification

`scripts/office/live/run_live_checks.py` checks a **managed local office editor** (Collabora CODE or ONLYOFFICE Docs, installed and run by clientst0r) with a real headless browser. It opens real documents, types into them, saves them and checks what clientst0r stored. It also drives the editor's lifecycle (restart, stop and start, update and rollback, uninstall and reinstall) through clientst0r's own code.

Its results file is the only evidence `mark-tested` accepts. That command lifts the "untested" flag of one release in the helper's release list, and only for the exact image digest that passed.

> **Status: built on the development branch, not yet released, and never run against a real editor.** The harness's own tests run offline: they use fake engines, fake checks and a fake editor page in a real headless Chromium. Whether the selectors, click positions and timings fit the real Collabora and ONLYOFFICE editors only shows on the first real run (see [What only a real run proves](#what-only-a-real-run-proves)).

## Contents

- [Profiles](#profiles)
- [What it checks](#what-it-checks)
- [Safety guards](#safety-guards)
- [Requirements](#requirements)
- [Browser](#browser)
- [Running it on this server (local profile)](#running-it-on-this-server-local-profile)
- [Path mode and host-name mode](#path-mode-and-host-name-mode)
- [Reading the results](#reading-the-results)
- [Marking a release as tested](#marking-a-release-as-tested)
- [Cleaning up](#cleaning-up)
- [VM profile (optional)](#vm-profile-optional)
- [What only a real run proves](#what-only-a-real-run-proves)
- [Extension points for engines](#extension-points-for-engines)
- [Testing the harness](#testing-the-harness)

## Profiles

| Profile | Where | What it may do |
|---|---|---|
| `local` (**default**) | A live clientst0r install, including production, where the managed editor is already installed and healthy | Only things clientst0r itself does to the **office container**: restart, stop and start, update and roll back (when the release list allows), and uninstall with data kept followed by a reinstall. Each one goes through clientst0r's queued operations. It never reboots, never installs Docker, never touches nginx or the firewall, and never stops gunicorn or any other service. |
| `vm` | A disposable VM | Everything above, plus installing from scratch and two steps the operator does by hand: restarting the container engine, and rebooting. The run waits for each, then continues on `resume`. |

## What it checks

In order. Every editing step happens in headless Chromium, on clientst0r's real pages.

| # | Check | What happens | Passes when |
|---|---|---|---|
| 1 | `guard` | The [safety guards](#safety-guards) | All of them hold. Otherwise nothing is created and the exit code is 2. |
| 2 | `fixtures` | Creates the organization "Office Live Check (automated)" and three staff users in it: two editors and one read-only member. Their passwords are random and never shown. | Created |
| 3 | `install` | Reads the helper's status. The `vm` profile installs first, through clientst0r, if nothing is installed. | Installed; the running container is `image@digest` and that digest equals the release-list entry; healthy; the editor instance is open to users. The release, digest, image and URL mode are recorded. |
| 4 | `path_mode_cookies` | Path mode only (see [Path mode](#path-mode-and-host-name-mode)) | nginx clears `Cookie` for every editor path, clientst0r's session cookie is HttpOnly, and the editor frame cannot read it. In host-name mode it is skipped as *not applicable*. |
| 5–7 | `roundtrip_docx`, `_xlsx`, `_pptx` | Creates a blank file through "New document" (office.creation). Opens it from the file page's **Edit** form and types a marker. Clicks clientst0r's **Save now** (force-save) and leaves through **Back**, which closes the session. Reopens the file, types a second marker and saves again. | The indicator goes to "Changes in editor" after typing and to "Saved to clientst0r" after the save. A new revision appears with source `editor_save`. The stored bytes' sha256 equals the revision's checksum. The OOXML contains the typed text. The reopened session starts from the new revision, and the second revision holds both markers. |
| 8 | `readonly` | The read-only member opens the file | The page is read-only: badge shown, no Save button. A hand-posted edit open creates no edit session. ONLYOFFICE's force-save on the view session answers 409. A save into the view session through `office.storage`, the layer every provider uses, is refused with `SessionRevoked`. The revision count does not change. |
| 9 | `concurrent` | Two editors open the same file in two browser contexts and both type | Both sessions are in one editing group (same document key), and one save stores both users' text. |
| 10 | `long_session` | Opens a file, types, waits `--long-minutes` (default 12) with the page open, types again, then saves | The page never shows a failure, the session was renewed (its expiry moved forward), and the delayed save stores both edits. |
| 11 | `restart_persistence` | **Restart** through clientst0r (drain, helper restart, health check and server round trip) | The operation succeeds, every test document keeps its revision and checksum, and editing and saving work afterwards. |
| (vm) | `engine_daemon_restart` | Operator: `sudo systemctl restart docker`, then `resume` | The container comes back healthy by itself and the documents are intact. |
| (vm) | `reboot` | Operator: `sudo reboot`, then `resume` (or the resume unit does it) | The boot id changed, the container is healthy and the documents are intact. |
| 12 | `connectivity` | Opens and saves a file (baseline). Then **Stop** through clientst0r: the drain stores the edit before the container stops. Types and clicks Save while the editor is down. Then **Start**, reopen, type, save. | While down, the page shows "Save failed". The baseline edit is kept. After Start a new save lands. |
| 13 | `maintenance_drain` | Types without saving, then queues **Restart** | The operation passes through `draining`, the unsaved edit becomes a revision while it drains (before the helper restarts the container), and the restart succeeds. |
| 14 | `upgrade_rollback` | Runs only when the release list has at least two entries for the engine and edition, and a newer one in the same compatibility group that this host would install. Otherwise it is **SKIPPED** and the reason is recorded. Update, then check and edit, then Roll back, then check and edit. | Release and digest after the update, a pre-update backup, documents intact, editing works on both releases |
| 15 | `uninstall_reinstall` | Runs only if the installed release could be installed again: the helper would accept it, for example it is tested or `ALLOW_UNTESTED_RELEASES=yes`. Otherwise it is skipped rather than leaving the editor uninstalled. Uninstall, then check, then Install. | The container is gone, secrets and editor data are kept, and the instance is closed to users. Documents are intact before and after. Editing works after the reinstall. |
| 16 | `cleanup` | Deletes the test organization, users, documents, revision files, sessions and quarantine rows | Nothing is left. Audit log entries stay, with names kept. |

Before every step that drains (stop, restart, update, rollback and uninstall), the harness counts real edit sessions again. If a real user opened a document during the run, the step is **skipped** and no real user is ever drained, unless you passed `--i-know-sessions-are-open`.

## Safety guards

**Local profile:**
- `--local-production-run` is required.
- `--confirm-base-url` must equal clientst0r's base URL exactly: the helper's `CLIENTSTOR_URL`, else Settings → site URL.
- The managed engine must be installed, running and healthy. Its editor instance must be enabled and healthy. No managed operation may be active.
- No real edit sessions may be open on the managed editor, unless you pass `--i-know-sessions-are-open`. A real session is one held by anyone other than the harness's own test users. The harness reads only the count, not who holds them or which files.
- A previous run's test organization or users must not exist, unless you use `resume` or `cleanup`.
- `--operator` must name an active superuser. Every operation is queued and audited under that name, and the harness never creates a superuser.
- A browser must be available (not checked by `--dry-run` or `cleanup`).
- An unfinished run blocks a new one: resume it, or clean up first.

**VM profile:** `--i-understand-this-is-disposable` and the root-owned marker `/etc/clientst0r/livecheck-disposable` (`DISPOSABLE=yes`, written by `bootstrap_vm.sh`). The host name, clientst0r's host and the office host must not match any `--production-pattern` or any line of `/etc/clientst0r/livecheck-production-patterns`. If the install looks live (more than 3 organizations, more than 10 users, or any edit session by a non-test user), the run is refused unless you pass `--force-disposable`.

**Always:**
- The harness never calls Docker, never runs anything as root, and never pushes or commits.
- Secrets, tokens, JWTs, session keys and the test passwords are redacted from the state file, results, report and console output.
- The browser gets session cookies only through the worker's stdin.

## Requirements

- clientst0r installed, with the managed engine installed and healthy (Settings → Office Documents → Managed Local).
- An existing superuser account to queue the operations as.
- A Python that can `import playwright` and has Playwright's Chromium (see [Browser](#browser)).
- Time:
  - about 35–60 minutes for the local profile with defaults (12 minutes of it is the long session; each restart, stop/start and reinstall takes a few minutes while the editor starts and is verified);
  - about 20 minutes more if upgrade/rollback runs;
  - the VM profile adds the reboot.
- Disk: screenshots, a few MB.

## Browser

The production venv does **not** need Playwright, and the harness never installs anything. The browser runs in a separate worker process (`livecheck/browser_worker.py`) under any interpreter you name with `--browser-python`. Without that option it tries the app's own Python, then `python3` on `PATH`.

Read-only check of what this host has:

```
/home/administrator/venv/bin/python -c 'import playwright'   # production venv: not installed (leave it so)
python3 -c 'import playwright, importlib.metadata as m; print(m.version("playwright"))'
ls ~/.cache/ms-playwright                                     # chromium-*, chromium_headless_shell-*
```

On the development server (2026-11-13), `python3` (user site of the app user) has Playwright 1.58.0, with Chromium 1208 in `~/.cache/ms-playwright`. The production venv has no Playwright.

If neither is present, the operator sets up a **separate** environment. Never use the app's venv:

```
python3 -m venv ~/.local/share/clientst0r-livecheck-venv
~/.local/share/clientst0r-livecheck-venv/bin/pip install playwright==1.58.0
~/.local/share/clientst0r-livecheck-venv/bin/python -m playwright install chromium
# system libraries, once, as root (on a server that lacks them):
sudo ~/.local/share/clientst0r-livecheck-venv/bin/python -m playwright install-deps chromium
```

Then pass `--browser-python ~/.local/share/clientst0r-livecheck-venv/bin/python`. Use `--chromium /path/to/chrome` for a Chromium of your own.

**How the browser reaches clientst0r:**
- **Default:** the public URL, through the same path users take. TLS terminates upstream.
- `--resolve app.example.com=192.0.2.10`: the browser resolves that host to this address (split DNS).
- `--via-local-nginx http://127.0.0.1`: clientst0r requests go to this host's nginx on port 80 instead. The public `Host` header and `X-Forwarded-Proto: https` are added. Use it only when the public URL is unreachable from the server itself. It is experimental: the editor's WebSocket in host-name mode still uses the public editor host.

## Running it on this server (local profile)

Run as the app user, from the app directory, with the app's Python. Replace `ADMIN` with your superuser and the URL with this site's.

1. Preview. This is read only: it shows the guard's verdict and the plan.

   ```
   cd /home/administrator
   venv/bin/python scripts/office/live/run_live_checks.py run --engine collabora --operator ADMIN \
     --local-production-run --confirm-base-url https://huduglue.agit8or.net/ --dry-run
   ```

2. Run it. Pick a quiet time, because the office editor restarts several times. The rest of clientst0r is not affected.

   ```
   venv/bin/python scripts/office/live/run_live_checks.py run --engine collabora --operator ADMIN \
     --local-production-run --confirm-base-url https://huduglue.agit8or.net/ \
     --browser-python /usr/bin/python3
   ```

   Useful options:

   | Option | What it does |
   |---|---|
   | `--only readonly,concurrent` | Run only these checks; guard, fixtures and cleanup always run. |
   | `--skip long_session` | Leave these checks out. |
   | `--long-minutes 15` | Length of the long session. |
   | `--keep-test-data` | Keep the test organization for inspection; remove it later with `cleanup`. |
   | `--nginx-conf FILE` | The nginx file to read for the path-mode check. |
   | `--headed` | Run the browser with a visible window, on a desktop. |

3. **If it was interrupted** (killed, SSH dropped):

   ```
   venv/bin/python scripts/office/live/run_live_checks.py resume
   ```

   A step that was running when the harness died is marked **failed (interrupted)** and is not re-run blindly. The rest continues, and cleanup runs at the end.

4. **If a managed operation was left active** (rare): look at Settings → Office Documents → Managed Local. The scheduler finishes or recovers it, as it would for an administrator's click.

## Path mode and host-name mode

The harness reads the mode from the configured provider. If the managed instance's browser URL is on clientst0r's own origin, it is **path mode**: for example `https://huduglue.agit8or.net/browser/…` and `/cool/…`, through the existing nginx. A different host name is **host-name mode**.

In path mode the browser sends clientst0r's cookies with every editor request, so the `path_mode_cookies` check requires all of the following:
- **nginx:** every `location` that proxies an editor path (`/browser/`, `/cool/`, `/hosting/discovery`, `/hosting/capabilities`, and the legacy `/loleaflet/` and `/lool/`) sets `proxy_set_header Cookie "";`, and none passes the editor's `Set-Cookie` through. The harness reads the files the engine names, or `--nginx-conf`. It is read only, and an unreadable configuration fails the check: nothing proves the cookie is dropped.
- **browser:** clientst0r's session cookie is `HttpOnly`, and the editor frame's `document.cookie` does not contain it. A readable CSRF cookie is reported as a warning.

## Reading the results

Each run has its own directory, `~/.local/state/clientst0r-livecheck/<run id>/` (mode 0700). It holds:

| File | Contents |
|---|---|
| `state.json` | The resumable state |
| `results.json` | Machine-readable results; the schema is in `livecheck/results.py` |
| `report.md` | Per check: PASS, FAIL or SKIP, the time taken and the detail. Also the clientst0r version, engine version, release, image and digest, plus the evidence: revision numbers, checksums, operation steps and screenshots. |
| `evidence/*.png` | Screenshots |

`results.json` carries `results_sha256`. If the file is edited, `mark-tested` refuses it.

**Overall:**
- `passed`: no check failed and none is pending. Skipped checks are allowed.
- `failed`: at least one check failed.
- `incomplete`: the run stopped part-way, or is waiting for the operator.

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Passed |
| 1 | A check failed |
| 2 | Refused, nothing changed |
| 3 | Waiting for the operator |
| 4 | Incomplete |
| 64 | Bad arguments |

To rewrite the report from the state: `run_live_checks.py report [--run-dir D]`.

## Marking a release as tested

```
python3 scripts/office/live/run_live_checks.py mark-tested --engine collabora \
  --results ~/.local/state/clientst0r-livecheck/<run>/results.json [--allow-skipped upgrade_rollback] [--diff-only]
```

It refuses unless all of these hold:
- the results are unmodified, are not from a dry run, and the overall result is PASSED;
- the engine matches;
- every required check of the profile passed. Two kinds of skip are accepted: a check skipped as *not applicable* (the path-mode check in host-name mode), and a skippable check you name in `--allow-skipped` (`upgrade_rollback`, `engine_daemon_restart`, `reboot`);
- the installed digest equalled the listed digest during the run;
- the repository's release list has an entry with **that id and that exact digest**.

It then changes `'tested': False` to `'tested': True` in that one entry. It adds a comment naming the date, profile, run, clientst0r version, results checksum and any accepted skips, writes the working-tree file, and prints the diff. **It never runs git.** Review it with `git diff` and commit it yourself, normally on a development worktree. Copy the results file there, never edit the release list in the production checkout.

Defaults: the ONLYOFFICE list is `RELEASES` in `deploy/office-helper/clientst0r-office-helper`. For Collabora, `--release-file` and `--release-list` override the defaults (see [Extension points](#extension-points-for-engines)).

## Cleaning up

- After a normal run: nothing to do. The `cleanup` check removes the test data, and the editor is left as it was found: installed, healthy, and on the same release after a rollback.
- After an interrupted run, or with `--keep-test-data`:

  ```
  venv/bin/python scripts/office/live/run_live_checks.py cleanup --operator ADMIN \
    --local-production-run --confirm-base-url https://huduglue.agit8or.net/
  ```

  It removes only the organization "Office Live Check (automated)", the users `livecheck-editor`, `livecheck-editor2` and `livecheck-reader`, and what belongs to them.
- Run directories under `~/.local/state/clientst0r-livecheck/` are kept as evidence. Delete them when you no longer need them.
- VM profile: `sudo bash scripts/office/live/bootstrap_vm.sh --i-understand-this-is-disposable --remove`, then throw the VM away.

## VM profile (optional)

A disposable Ubuntu 24.04 VM with at least 4 vCPU, 8 GB RAM and 40 GB disk.

**DNS and certificate.** You need:
- a name for clientst0r, and a separate one for the editor in host-name mode;
- a certificate for each, for example from `certbot` or your test CA; with a private CA, use `--ca-file` / `PRIVATE_CA=yes` (docs/office/MANAGED_LOCAL.md).

**Steps:**
1. Install clientst0r (`bash install.sh`).
2. Install the managed editor's prerequisites with the product's installer. This is part of what is verified:

   ```
   install-editor.sh --mode managed-local … --install-docker
   ```

3. Bootstrap the VM as root. It never installs Docker, nginx or firewall rules:

   ```
   sudo bash scripts/office/live/bootstrap_vm.sh --i-understand-this-is-disposable --allow-untested \
     --production-pattern '*.yourcompany.com' --browser-deps /path/to/playwright-python \
     --resume-unit <app user> <app dir> <app dir>/venv/bin/python
   ```

4. Run it:

   ```
   run_live_checks.py run --profile vm --i-understand-this-is-disposable --engine collabora --operator ADMIN
   ```

5. At `engine_daemon_restart` and `reboot` the run stops with exit code 3 and prints what to do. Afterwards, `run_live_checks.py resume`. After a reboot the resume unit runs this for you.

## What only a real run proves

**Tested offline** (`office/test_livecheck.py`):
- the guards' refusals;
- the state machine: interruption, the operator hand-over across a "reboot", and resume;
- redaction of the state, results and report;
- `mark-tested` against a synthetic list and against the real helper file in memory;
- CLI validation;
- the nginx cookie rule;
- OOXML text checks;
- the upgrade and reinstall decisions;
- the test data: create, OTP-verified sign-in, cleanup that leaves other organizations and the audit trail alone;
- `run_op`'s drain refusal when a real session appears;
- the browser worker driving a real headless Chromium through a fake file page and editor page: open form, typing, the save indicator, a failed save, read-only, cookie flags, screenshots.

**Only a real run shows:**
- that the selectors, click positions and keys in `engines.py` type into the real Collabora and ONLYOFFICE editors, for each format (the PPTX title placeholder in particular);
- real save timings;
- that the editor shows "Save failed" when it is stopped;
- that drain and verification behave against a real container;
- that the release list has a second entry (upgrade/rollback);
- that the path-mode nginx block clears cookies.

None of this has been run yet.

## Extension points for engines

Everything engine-specific is in `scripts/office/live/livecheck/engines.py`: one class per engine. Points marked `ENGINES-HOOK` are assumptions about the managed Collabora engine, which is being built on its own branch. Confirm them when it lands:

1. **Engine identity.** The helper's `status` names the engine in `config.engine` (or `engine`). The managed `EditorInstance` uses provider `collabora`.
2. **CLI switch.** If `manage.py office_managed` gains `--engine`, the harness passes it automatically (it inspects the command's options).
3. **Release list.** A Python list literal named `COLLABORA_RELEASES` in the helper file. Override with `--release-file` / `--release-list`, or change `CollaboraEngine.release_list_name`.
4. **nginx block.** The file names in `CollaboraEngine.nginx_candidates`. The same-host block must clear `Cookie` on the editor paths.
5. **Connectivity.** If the helper gains a verb that blocks only the container's callbacks to clientst0r (time-bounded, its own firewall rule), switch `check_connectivity` to it. Today the check stops the container through clientst0r.
6. **Browser profile.** `COLLABORA_BROWSER` / `ONLYOFFICE_BROWSER`: frame selector, readiness selectors, click positions per format, keys, and the Save button.

## Testing the harness

```
manage.py test office.test_livecheck
```

The browser-worker test runs only where a Python with Playwright and its Chromium exist. Set `LIVECHECK_SKIP_BROWSER=1` to skip it.
