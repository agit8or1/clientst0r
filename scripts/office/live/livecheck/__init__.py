"""clientst0r Office live-verification harness (docs/office/LIVE_VERIFICATION.md).

Package layout:

    redact.py          scrub secrets from everything the harness writes
    state.py           the resumable run state (one JSON file per run)
    results.py         results JSON + the markdown report
    safety.py          the local-production and disposable-VM guards
    engines.py         one adapter per managed engine (collabora, onlyoffice)
    fixtures.py        the isolated test organization, users and documents
    ooxml.py           text extraction from DOCX / XLSX / PPTX
    browser.py         client for the browser worker (a separate process)
    browser_worker.py  headless Chromium via Playwright; never imports Django
    checks.py          the checks and the plan per profile
    runner.py          runs the plan, step by step, resumable
    marktested.py      flips a release to tested from a passing results file

Only runner/fixtures/engines/checks import Django; the rest is plain Python
so it can be unit-tested and used from any interpreter.
"""

HARNESS_VERSION = '1'
