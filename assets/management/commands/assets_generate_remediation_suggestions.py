"""
Phase 17 v11 (v3.17.310): **OPTIONAL AI** remediation suggestion engine.

Heuristic today: scans every active asset for fixable issues and emits
RemediationSuggestion rows. The model + accept() plumbing is shared,
so a real LLM implementation can swap in later.

Heuristics:
  1. Firmware update available (`Asset.has_firmware_update()`) →
     `kind=firmware_update`, severity=medium.
  2. Drift detected (`Asset.detect_drift()` non-empty) →
     `kind=drift`, severity=low.
  3. Health score below 60 → `kind=health`, severity scaled.
  4. Vulnerability affecting the asset → `kind=vulnerability`,
     severity from the CVE.

Gated by `SystemSetting.psa_ai_enabled`.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from assets.models import Asset, RemediationSuggestion, Vulnerability
from core.models import SystemSetting


class Command(BaseCommand):
    help = 'Scan assets for remediation candidates and emit suggestions.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=2000,
                            help='Cap on assets evaluated (default 2000).')

    def handle(self, *args, **options):
        ss = SystemSetting.get_settings()
        if not getattr(ss, 'psa_ai_enabled', False):
            self.stdout.write(self.style.WARNING(
                'psa_ai_enabled is OFF — no suggestions generated.'))
            return

        dry = options['dry_run']
        limit = options['limit']
        assets = list(Asset.objects.all()[:limit])

        # Pre-load active vulnerabilities so we don't query per asset.
        vulns = list(Vulnerability.objects.filter(is_active=True))

        new_count = 0
        for asset in assets:
            generated = self._scan_asset(asset, vulns)
            for sug in generated:
                if dry:
                    self.stdout.write(
                        f'[dry] {asset.name} → {sug["kind"]}: {sug["summary"]}'
                    )
                    continue
                # De-dup by (asset, kind, summary) within pending state
                exists = RemediationSuggestion.objects.filter(
                    asset=asset, kind=sug['kind'],
                    summary=sug['summary'], status='pending',
                ).exists()
                if exists:
                    continue
                RemediationSuggestion.objects.create(
                    asset=asset, organization=asset.organization,
                    kind=sug['kind'], severity=sug['severity'],
                    summary=sug['summary'],
                    rationale=sug.get('rationale', ''),
                    payload=sug.get('payload', {}),
                )
                new_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'{"[dry] " if dry else ""}{new_count} new suggestion(s) recorded.'
        ))

    def _scan_asset(self, asset, vulns):
        """Return a list of suggestion dicts for one asset."""
        out = []
        # 1. Firmware update
        try:
            if asset.has_firmware_update():
                out.append({
                    'kind': 'firmware_update',
                    'severity': 'medium',
                    'summary': f'Firmware update available for {asset.name} '
                               f'({asset.firmware_version} → {asset.firmware_latest})',
                    'rationale': 'Heuristic: firmware_version != firmware_latest',
                    'payload': {
                        'current': asset.firmware_version,
                        'latest': asset.firmware_latest,
                    },
                })
        except Exception:
            pass

        # 2. Drift
        try:
            drift = asset.detect_drift()
            if drift:
                fields = ', '.join(d['field'] for d in drift)
                out.append({
                    'kind': 'drift',
                    'severity': 'low',
                    'summary': f'Configuration drift on {asset.name} ({fields})',
                    'rationale': f'Detected {len(drift)} field(s) drifted from baseline',
                    'payload': {'drift': drift},
                })
        except Exception:
            pass

        # 3. Health-score regression
        try:
            health = asset.health_score()
            if health['score'] < 60:
                if health['score'] < 30:
                    sev = 'high'
                elif health['score'] < 50:
                    sev = 'medium'
                else:
                    sev = 'low'
                out.append({
                    'kind': 'health',
                    'severity': sev,
                    'summary': f'{asset.name} health score is {health["score"]}/100',
                    'rationale': f'Factors: {health["factors"]}',
                    'payload': health,
                })
        except Exception:
            pass

        # 4. Vulnerabilities affecting this asset
        for v in vulns:
            if v.organization_id and v.organization_id != asset.organization_id:
                continue
            if not v.affected_pattern:
                continue
            # Cheap per-asset match using RMMSoftware
            from integrations.models import RMMDevice, RMMSoftware
            sw_qs = RMMSoftware.objects.filter(
                device__linked_asset=asset,
                device__organization_id=asset.organization_id,
                device__ownership_status=RMMDevice.OWNERSHIP_RESOLVED,
                name__icontains=v.affected_pattern,
            )
            if sw_qs.exists():
                out.append({
                    'kind': 'vulnerability',
                    'severity': v.severity,
                    'summary': f'Patch {v.cve_id or v.title} on {asset.name}',
                    'rationale': v.description or '',
                    'payload': {
                        'cve_id': v.cve_id,
                        'fixed_version': v.fixed_version,
                        'cvss_score': str(v.cvss_score) if v.cvss_score else None,
                    },
                })
        return out
