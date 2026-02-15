# Adding GitHub Actions Workflows

GitHub requires repository admin privileges to add workflow files. Here's how to add them:

## Option 1: Via GitHub Web UI (Easiest)

### Step 1: Add Security Workflow

1. Go to: https://github.com/agit8or1/clientst0r
2. Click: **Add file** → **Create new file**
3. Filename: `.github/workflows/security.yml`
4. Paste this content:

```yaml
name: security

on:
  push:
    branches: [ "main" ]
  pull_request:
  schedule:
    - cron: "0 6 * * 1"  # Mondays 06:00 UTC

permissions:
  contents: read
  security-events: write

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      # Optional but recommended: harden runner network egress
      - name: Harden runner
        uses: step-security/harden-runner@v2
        with:
          egress-policy: audit

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install semgrep pip-audit cyclonedx-bom

      - name: Semgrep (SAST)
        run: |
          semgrep --config p/owasp-top-ten --config p/python --error --metrics=off

      - name: pip-audit (PyPI vuln check)
        run: |
          pip-audit -r requirements.txt

      - name: Gitleaks (secrets scan)
        uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Generate SBOM (CycloneDX)
        run: |
          cyclonedx-py -r -i requirements.txt -o sbom.cdx.json

      - name: Upload SBOM artifact
        uses: actions/upload-artifact@v4
        with:
          name: sbom-cyclonedx
          path: sbom.cdx.json
```

5. Click: **Commit changes** → **Commit directly to the main branch**

### Step 2: Add CodeQL Workflow

1. Click: **Add file** → **Create new file**
2. Filename: `.github/workflows/codeql.yml`
3. Paste this content:

```yaml
name: codeql

on:
  push:
    branches: [ "main" ]
  pull_request:
  schedule:
    - cron: "0 7 * * 1"

permissions:
  security-events: write
  contents: read

jobs:
  analyze:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        language: [ "python" ]
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/analyze@v3
```

4. Click: **Commit changes** → **Commit directly to the main branch**

---

## Option 2: Grant Workflow Scope to PAT

If you want to push workflows from command line:

1. Go to: https://github.com/settings/tokens
2. Find your PAT → Click **Edit**
3. Check: `workflow` scope
4. Click: **Update token**
5. Copy new token
6. Update local git remote:
   ```bash
   git remote set-url origin https://YOUR_NEW_TOKEN@github.com/agit8or1/clientst0r.git
   ```
7. Push workflows:
   ```bash
   cp .github/workflows/security.yml.backup .github/workflows/security.yml
   cp .github/workflows/codeql.yml.backup .github/workflows/codeql.yml
   git add .github/workflows/
   git commit -m "Add security workflows"
   git push origin main
   ```

---

## Verification

After adding workflows:

1. Go to: https://github.com/agit8or1/clientst0r/actions
2. Should see two new workflows:
   - `security` (running)
   - `codeql` (running)
3. Wait for workflows to complete
4. Check results:
   - Green ✓ = All security checks passed
   - Red ✗ = Security issues detected (review and fix)
5. Download SBOM:
   - Click on `security` workflow run
   - Scroll to **Artifacts**
   - Download `sbom-cyclonedx`

---

## Workflow Files Location

The workflow YAML files are saved locally in:
- `.github/workflows/security.yml`
- `.github/workflows/codeql.yml`

They just need to be added to the GitHub repository.

---

## What These Workflows Do

### Security Workflow
- **Semgrep**: SAST with OWASP Top 10 + Python rules
- **pip-audit**: PyPI vulnerability scanner
- **Gitleaks**: Secrets scanner
- **SBOM**: CycloneDX bill of materials

### CodeQL Workflow
- **CodeQL**: GitHub's advanced static analysis
- Detects complex security issues
- Tracks dataflow vulnerabilities

Both run:
- On every push to main
- On every pull request
- Weekly (Mondays at 06:00 and 07:00 UTC)

---

**Status:** Waiting for manual addition to GitHub repo
**Priority:** High (enables automated security scanning)
