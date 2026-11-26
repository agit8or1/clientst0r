"""Proxmox Backup Server, over its REST API (/api2/json).

Auth is an API token: ``Authorization: PBSAPIToken=user@realm!tokenname:secret``
(stored sealed as credentials["api_token"]). The token needs Datastore.Audit
(and Sys.Audit for the task list) on the datastores to be monitored.

Mapping:
  * repository  <- GET /status/datastore-usage (total / used / avail, `error`)
  * job + system<- GET /admin/datastore/{store}/groups (one group = one
                   backup job and one protected system, e.g. vm/100)
  * retention   <- GET /config/prune (best effort; needs Datastore.Audit)
  * run         <- GET /nodes/localhost/tasks?typefilter=backup (one task =
                   one run; OK / WARNINGS: n / any other status = failed),
                   sized from the matching snapshot in
                   GET /admin/datastore/{store}/snapshots
"""
from datetime import datetime, timezone
from typing import List, Optional

import requests

from core.safe_http import OutboundPolicy, UnsafeURLError, configured_service_policy, guard_session, validate_url

from .base import BaseBackupProvider, JobInfo, ProviderError, RepositoryInfo, RunInfo

TIMEOUT = 20


def _ts(value) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _retention_text(prune: dict) -> str:
    parts = [f'{k[5:]} {prune[k]}' for k in ('keep-last', 'keep-hourly', 'keep-daily', 'keep-weekly',
                                              'keep-monthly', 'keep-yearly') if prune.get(k) is not None]
    return 'keep ' + ', '.join(parts) if parts else ''


def _refusal(exc) -> str:
    return ('The backup server address is not allowed: ' + str(exc) + '. A server on a private network '
            'needs "Server is on a private network" on the connection.')


class ProxmoxBackupServerProvider(BaseBackupProvider):
    kind = 'pbs'
    label = 'Proxmox Backup Server'

    def _headers(self):
        token = (self.connection.get_credentials() or {}).get('api_token', '')
        if not token:
            raise ProviderError('No API token configured.', 'configuration_error')
        return {'Authorization': f'PBSAPIToken={token}', 'Accept': 'application/json'}

    def _policy(self) -> OutboundPolicy:
        """SR-02: public addresses; a private (LAN) address only when the
        connection is marked as on a private network. Loopback, link-local and
        metadata addresses only with the install-wide
        ALLOW_PRIVATE_IP_INTEGRATIONS opt-in (metadata never)."""
        base = configured_service_policy()
        if getattr(self.connection, 'allow_private_address', False):
            return OutboundPolicy(allow_lan=True, allow_local=base.allow_local, allowed_ports=None)
        return base

    def _get(self, path, params=None):
        base = (self.connection.base_url or '').rstrip('/')
        if not base:
            raise ProviderError('No base URL configured.', 'configuration_error')
        policy = self._policy()
        try:
            validate_url(f'{base}/api2/json{path}', policy)
        except UnsafeURLError as exc:
            raise ProviderError(_refusal(exc), 'configuration_error') from exc
        session = guard_session(requests.Session(), policy)
        session.trust_env = False
        try:
            resp = session.get(f'{base}/api2/json{path}', headers=self._headers(), params=params,
                               timeout=TIMEOUT, verify=self.connection.verify_tls)
        except UnsafeURLError as exc:
            raise ProviderError(_refusal(exc), 'configuration_error') from exc
        except requests.RequestException as exc:
            raise ProviderError(f'Cannot reach {base}: {exc.__class__.__name__}',
                                'timeout' if 'Timeout' in exc.__class__.__name__ else 'endpoint_unavailable') from exc
        if resp.status_code in (401, 403):
            raise ProviderError(f'PBS refused the API token (HTTP {resp.status_code}).',
                                'authentication_failure' if resp.status_code == 401 else 'permission_denied')
        if resp.status_code != 200:
            from events.source_health import classify_status
            raise ProviderError(f'PBS returned HTTP {resp.status_code} for {path}.',
                                classify_status(resp.status_code) or 'invalid_response',
                                retry_after=resp.headers.get('Retry-After'))
        try:
            return resp.json().get('data')
        except ValueError as exc:
            raise ProviderError('PBS returned a response that is not JSON.', 'invalid_response') from exc

    def test_connection(self):
        try:
            data = self._get('/version') or {}
        except ProviderError as exc:
            return {'ok': False, 'message': str(exc)}
        return {'ok': True, 'message': f"Connected to Proxmox Backup Server {data.get('version', '')}".strip()}

    def _stores(self) -> List[dict]:
        return self._get('/status/datastore-usage') or []

    def list_repositories(self) -> List[RepositoryInfo]:
        out = []
        for s in self._stores():
            error = s.get('error')
            out.append(RepositoryInfo(
                external_id=s['store'], name=s['store'],
                total_bytes=s.get('total'), used_bytes=s.get('used'),
                available=not error, message=str(error)[:500] if error else ''))
        return out

    def _prune_by_store(self) -> dict:
        try:
            jobs = self._get('/config/prune') or []
        except ProviderError:
            return {}
        return {j.get('store'): _retention_text(j) for j in jobs if j.get('store')}

    def list_jobs(self) -> List[JobInfo]:
        retention = self._prune_by_store()
        out = []
        for s in self._stores():
            if s.get('error'):
                continue
            store = s['store']
            for g in self._get(f'/admin/datastore/{store}/groups') or []:
                gid = f"{g['backup-type']}/{g['backup-id']}"
                comment = (g.get('comment') or '').strip()
                out.append(JobInfo(
                    external_id=f'{store}:{gid}', name=f'{store}: {gid}' + (f' ({comment})' if comment else ''),
                    system_external_id=gid, system_name=comment or gid,
                    schedule='Set by the backup client (Proxmox VE / proxmox-backup-client)',
                    retention=retention.get(store, '')))
        return out

    def _snapshot_sizes(self) -> dict:
        sizes = {}
        for s in self._stores():
            if s.get('error'):
                continue
            store = s['store']
            try:
                snaps = self._get(f'/admin/datastore/{store}/snapshots') or []
            except ProviderError:
                continue
            for sn in snaps:
                key = f"{store}:{sn['backup-type']}/{sn['backup-id']}"
                sizes.setdefault(key, []).append((sn.get('backup-time') or 0, sn.get('size'),
                                                  (sn.get('verification') or {}).get('state', '')))
        return sizes

    def list_runs(self, since: Optional[datetime] = None) -> List[RunInfo]:
        params = {'typefilter': 'backup', 'limit': 500}
        if since is not None:
            params['since'] = int(since.timestamp())
        tasks = self._get('/nodes/localhost/tasks', params) or []
        return self._runs(tasks, self._snapshot_sizes())

    # Monitoring coverage (82.17). The task list takes since / until and
    # start / limit, so a missed window can be paged through; a page shorter
    # than the limit is the end of the results. Results are not documented as
    # time-ordered, so every timestamp is validated. PBS rotates its task
    # archive by size, so 7 days is the lookback Clientst0r relies on; an
    # older gap is never reported as fully recovered.
    @property
    def history_capability(self):
        from datetime import timedelta
        from events.coverage import HistoryCapability, ORDER_UNORDERED, PAGE_SHORT
        return HistoryCapability(supports_history=True, max_lookback=timedelta(days=7), ordering=ORDER_UNORDERED,
                                 pagination=PAGE_SHORT, page_size=200)

    def fetch_history(self, start, end, token=None, limit=200):
        from events.coverage import HistoryPage
        offset = int(token) if token and str(token).isdigit() else 0
        params = {'typefilter': 'backup', 'since': int(start.timestamp()), 'until': int(end.timestamp()),
                  'start': offset, 'limit': int(limit)}
        tasks = self._get('/nodes/localhost/tasks', params)
        if not isinstance(tasks, list):
            raise ProviderError('PBS returned no task list.', 'invalid_response')
        runs = self._runs(tasks, self._snapshot_sizes() if tasks else {})
        # Short-page detection counts what PBS returned, not the runs kept.
        return HistoryPage(records=runs, next_token=str(offset + len(tasks)) if len(tasks) >= limit else '',
                           exhausted=len(tasks) < limit, raw_count=len(tasks))

    def _runs(self, tasks, sizes):
        out = []
        for t in tasks:
            if t.get('worker_type') != 'backup' or ':' not in (t.get('worker_id') or ''):
                continue
            started = _ts(t.get('starttime'))
            if started is None:
                continue
            finished = _ts(t.get('endtime'))
            raw = (t.get('status') or '').strip()
            message = ''
            if finished is None:
                status = 'running'
            elif raw == 'OK':
                status = 'success'
            elif raw.upper().startswith('WARNINGS'):
                status, message = 'warning', raw
            else:
                status, message = 'failed', raw
            size = None
            if status in ('success', 'warning'):
                # The snapshot is stamped when the backup starts.
                for bt, sz, verification in sizes.get(t['worker_id'], []):
                    if abs(bt - int(t['starttime'])) <= 120:
                        size = sz
                        if verification == 'failed':
                            status, message = 'warning', 'Snapshot verification failed.'
                        break
            gid = t['worker_id'].split(':', 1)[1]
            out.append(RunInfo(
                external_id=t['upid'], job_external_id=t['worker_id'], started_at=started,
                finished_at=finished, status=status, bytes_processed=size, message=message[:2000],
                system_external_id=gid, system_name=gid))
        return out
