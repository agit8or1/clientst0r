# Phase 2: Enterprise Security Hardening

## Overview

Phase 2 builds on the security foundation from v2.20.0 with supply chain security, SAST, secrets scanning, and operational hardening.

**Status:** Configuration files committed, requires activation

---

## What Was Implemented

### 1. Dependabot (Automated Dependency Updates)

**File:** `.github/dependabot.yml`

**What It Does:**
- Weekly scans for Python dependency vulnerabilities
- Weekly scans for GitHub Actions updates
- Groups security updates for easier review
- Auto-creates PRs for updates

**Activate:**
```bash
# Already configured! GitHub will automatically start:
# - Scanning dependencies weekly
# - Creating PRs for security updates
# - Grouping related updates
```

**Review PRs:**
- Go to GitHub → Pull Requests
- Review Dependabot PRs
- Merge after testing

---

### 2. Pre-commit Hooks (Local + CI Parity)

**File:** `.pre-commit-config.yaml`

**What It Does:**
- **Ruff**: Fast Python linter + formatter (replaces Black + flake8)
- **Bandit**: Security linter (detects common vulnerabilities)
- **Gitleaks**: Prevents committing secrets

**Install:**
```bash
# Install pre-commit
pip install pre-commit

# Install hooks
pre-commit install

# Run manually
pre-commit run --all-files
```

**What Happens:**
- Every `git commit` runs these checks
- Fails if security issues detected
- Auto-fixes formatting issues
- Blocks commits with secrets

**Example Output:**
```bash
$ git commit -m "Add feature"
ruff....................................Passed
bandit..................................Failed
gitleaks................................Passed

[bandit] Potential SQL injection at core/views.py:42
```

---

### 3. Security Workflow (CI/CD Pipeline)

**File:** `.github/workflows/security.yml`

**What It Does:**
- **Semgrep**: SAST (static analysis) with OWASP Top 10 + Python rules
- **pip-audit**: PyPI vulnerability scanner (redundancy with Snyk)
- **Gitleaks**: Secrets scanner
- **SBOM Generation**: CycloneDX bill of materials

**Runs:**
- Every push to main
- Every pull request
- Weekly schedule (Mondays 06:00 UTC)

**View Results:**
- GitHub → Actions → security workflow
- Fails if vulnerabilities detected

**SBOM Artifact:**
- Download from workflow run
- Use for compliance/audits
- Format: CycloneDX JSON

---

### 4. CodeQL (Deep SAST)

**File:** `.github/workflows/codeql.yml`

**What It Does:**
- GitHub's advanced static analysis
- Detects complex security issues
- Tracks dataflow (e.g., user input → SQL query)

**Runs:**
- Every push to main
- Every pull request
- Weekly schedule (Mondays 07:00 UTC)

**View Results:**
- GitHub → Security → Code scanning alerts
- Integrated with GitHub Security tab

---

### 5. MariaDB Hardening

**Not Yet Configured** (requires manual DB changes)

#### 5A. Least-Privilege DB Users

**Current:** Single DB user with ALL PRIVILEGES

**Recommended:** Separate users for app vs migrations

```sql
-- App runtime user (read/write only)
CREATE USER 'huduglue_app'@'%' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE ON huduglue.* TO 'huduglue_app'@'%';

-- Migrations user (DDL operations)
CREATE USER 'huduglue_migrate'@'%' IDENTIFIED BY 'STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON huduglue.* TO 'huduglue_migrate'@'%';

FLUSH PRIVILEGES;
```

**Update Django:**
```python
# config/settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.getenv('DB_NAME'),
        'USER': os.getenv('DB_USER'),  # Use huduglue_app
        'PASSWORD': os.getenv('DB_PASSWORD'),
        'HOST': os.getenv('DB_HOST'),
        'PORT': os.getenv('DB_PORT', '3306'),
    }
}
```

**For Migrations:**
```bash
# Use migrate user for schema changes
export DB_USER=huduglue_migrate
python manage.py migrate

# Switch back to app user for runtime
export DB_USER=huduglue_app
```

#### 5B. TLS to Database (If Remote)

**Only needed if database is on separate server**

```python
# config/settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        # ... other settings ...
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'charset': 'utf8mb4',
            'ssl': {
                'ca': os.getenv('DB_SSL_CA', '/path/to/ca-cert.pem'),
            }
        }
    }
}
```

**Environment Variable:**
```bash
DB_SSL_CA=/path/to/mysql-ca.pem
```

---

### 6. Pin GitHub Actions (Supply Chain Security)

**Status:** Using version tags (v4, v5)
**Recommended:** Pin to commit SHAs

**Current:**
```yaml
uses: actions/checkout@v4
```

**Hardened:**
```yaml
uses: actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11  # v4.1.1
```

**How to Update:**

1. Find commit SHA:
```bash
# Go to https://github.com/actions/checkout/releases
# Click on tag (e.g., v4.1.1)
# Copy full commit SHA
```

2. Replace all actions:
```bash
# Manually update .github/workflows/*.yml
# Or use tool: https://github.com/mheap/pin-github-action
```

3. Let Dependabot maintain:
- Dependabot will create PRs for SHA updates
- Review and merge

**Benefits:**
- Prevents action hijacking (supply chain attack)
- Immutable reference (SHA can't change)
- Dependabot keeps SHAs updated

---

## Activation Checklist

### Immediate (Already Active)

- ✅ **Dependabot**: Active once files are in repo
- ✅ **Security Workflow**: Runs on next push/PR
- ✅ **CodeQL**: Runs on next push/PR

### Quick Setup (5 minutes)

- [ ] **Install Pre-commit Hooks:**
  ```bash
  pip install pre-commit
  pre-commit install
  pre-commit run --all-files  # Test
  ```

### Manual Configuration (DB Admin)

- [ ] **MariaDB Least-Privilege:**
  - Create `huduglue_app` user (SELECT, INSERT, UPDATE, DELETE)
  - Create `huduglue_migrate` user (ALL PRIVILEGES)
  - Update `DB_USER` environment variable
  - Test migrations and app runtime

- [ ] **MariaDB TLS** (if remote DB):
  - Obtain CA certificate from DB provider
  - Set `DB_SSL_CA` environment variable
  - Test connection

### Optional (Advanced)

- [ ] **Pin GitHub Actions to SHAs:**
  - Replace version tags with commit SHAs
  - Update `.github/workflows/*.yml`
  - Test workflows

- [ ] **CSP Reporting Endpoint:**
  - Implement endpoint for CSP violation reports
  - Set `report-uri` or `report-to` in CSP
  - Monitor for violations

---

## Validation

### Pre-commit Hooks

```bash
# Should pass all checks
pre-commit run --all-files

# Expected output:
# ruff....................................Passed
# bandit..................................Passed
# gitleaks................................Passed
```

### Security Workflow

```bash
# Push to GitHub
git push origin main

# Check Actions tab
# Security workflow should pass
# SBOM artifact should be available
```

### CodeQL

```bash
# Check GitHub Security tab
# Should show "No alerts"
# If alerts present, review and fix
```

---

## Ongoing Operations

### Weekly

- [ ] Review Dependabot PRs
- [ ] Check GitHub Security alerts
- [ ] Review SBOM artifacts

### Monthly

- [ ] Review CodeQL results
- [ ] Update pinned GitHub Actions (if manual)
- [ ] Rotate secrets (if due)

### After Dependency Updates

- [ ] Run `pre-commit run --all-files`
- [ ] Run `python manage.py test`
- [ ] Check security workflow passes

---

## Troubleshooting

### Pre-commit Fails on Bandit

**Error:** `Potential SQL injection at X`

**Fix:** Review code, ensure parameterized queries
```python
# Bad (vulnerable to SQL injection)
User.objects.raw(f"SELECT * FROM users WHERE id = {user_id}")

# Good (parameterized)
User.objects.filter(id=user_id)
```

### Pre-commit Fails on Gitleaks

**Error:** `Detected hardcoded secret at X`

**Fix:** Remove secret, add to `.env` file
```python
# Bad
API_KEY = "sk-ant-12345..."

# Good
API_KEY = os.getenv('API_KEY')
```

### Security Workflow Fails on Semgrep

**Error:** `[OWASP] Potential XSS at X`

**Fix:** Review code, ensure proper escaping
```python
# Bad (XSS vulnerable)
return HttpResponse(user_input)

# Good (auto-escaped)
return render(request, 'template.html', {'data': user_input})
```

### pip-audit Finds Vulnerability

**Error:** `Package X has known vulnerability`

**Fix:** Update package
```bash
pip install --upgrade package-name
pip freeze > requirements.txt
```

---

## Cost Impact

### GitHub Actions (Free Tier)

- **Free:** 2,000 minutes/month
- **Security workflow:** ~5 minutes per run
- **CodeQL:** ~10 minutes per run
- **Expected usage:** ~200 minutes/month (10% of free tier)

### Paid Services (Optional)

- **Snyk**: $0 (free tier) → $99/month (team plan)
- **Semgrep**: Free (OSS rules)
- **pip-audit**: Free
- **Gitleaks**: Free

---

## Security Metrics

| Metric | Before Phase 2 | After Phase 2 |
|--------|----------------|---------------|
| **Dependency Scanning** | Manual (Snyk) | Automated (Dependabot + pip-audit) |
| **SAST** | None | Semgrep + CodeQL + Bandit |
| **Secrets Scanning** | None | Gitleaks (pre-commit + CI) |
| **SBOM** | None | CycloneDX (automated) |
| **Supply Chain** | Version tags | SHA pinning (optional) |
| **DB Security** | Single user | Least-privilege (manual) |

---

## References

- [Semgrep Rules](https://semgrep.dev/explore)
- [CodeQL Docs](https://codeql.github.com/docs/)
- [Dependabot Docs](https://docs.github.com/en/code-security/dependabot)
- [Pre-commit Hooks](https://pre-commit.com/)
- [CycloneDX SBOM](https://cyclonedx.org/)
- [Gitleaks](https://github.com/gitleaks/gitleaks)

---

**Status:** Phase 2 configuration committed, requires activation
**Last Updated:** 2026-01-14
**Version:** 2.20.0+phase2
