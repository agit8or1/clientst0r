"""
Country lookup for the GeoIP firewall (v3.17.598).

The firewall used to ask ip-api.com about every request: plain HTTP, 45
requests a minute, no caching. In allowlist mode a failed lookup blocks the
visitor, so ordinary use from an allowed country could trip the rate limit and
get 403s, and anyone on the network path could forge the answer.

Lookups now read a local copy of the free DB-IP "IP to Country Lite" database
(CC BY 4.0, https://db-ip.com), refreshed monthly by `manage.py update_geoip_db`
(which each app update runs). If the file is missing, the old service is still
used, but each answer is cached for a day.
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import tempfile
import threading
from datetime import date
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DOWNLOAD_URL = 'https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz'
ATTRIBUTION_HTML = '<a href="https://db-ip.com" target="_blank" rel="noopener">IP Geolocation by DB-IP</a>'

_lock = threading.Lock()
_reader = None
_reader_mtime = None


def db_path() -> Path:
    return Path(getattr(settings, 'GEOIP_DB_PATH', '') or
                Path(settings.BASE_DIR) / 'data' / 'geoip' / 'dbip-country-lite.mmdb')


def _get_reader():
    """Open the database once per process; reopen when the file is replaced."""
    global _reader, _reader_mtime
    path = db_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    with _lock:
        if _reader is None or mtime != _reader_mtime:
            try:
                import maxminddb
                _reader = maxminddb.open_database(str(path))
                _reader_mtime = mtime
            except Exception as exc:
                logger.warning('GeoIP database %s unreadable: %s', path, exc)
                _reader = None
        return _reader


def _from_record(record):
    country = (record or {}).get('country') or {}
    code = (country.get('iso_code') or '').upper()
    name = (country.get('names') or {}).get('en', '') or code
    return code, name


def lookup(ip: str) -> tuple[str, str]:
    """(ISO country code, English name), or ('', '') when unknown."""
    reader = _get_reader()
    if reader is not None:
        try:
            return _from_record(reader.get(ip))
        except ValueError:
            return '', ''
    return _remote_lookup(ip)


def _remote_lookup(ip: str) -> tuple[str, str]:
    key = f'geoip:remote:{ip}'
    hit = cache.get(key)
    if hit is not None:
        return tuple(hit)
    result = ('', '')
    try:
        response = requests.get(f'http://ip-api.com/json/{ip}',
                                params={'fields': 'status,countryCode,country'}, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success':
                result = (data.get('countryCode', '').upper(), data.get('country', ''))
    except Exception as exc:
        logger.warning('GeoIP lookup failed for %s: %s', ip, exc)
    # Remember failures briefly too, so a struggling service isn't hammered.
    cache.set(key, list(result), 86400 if result[0] else 300)
    return result


def download(today: date | None = None, timeout=120) -> Path:
    """Fetch this month's database (or last month's, early in a month),
    check it, and swap it in atomically. Returns the installed path."""
    import maxminddb

    today = today or date.today()
    last_month = date(today.year - (today.month == 1), (today.month - 2) % 12 + 1, 1)
    target = db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    errors = []
    for month in (today.strftime('%Y-%m'), last_month.strftime('%Y-%m')):
        url = DOWNLOAD_URL.format(month=month)
        fd, tmp = tempfile.mkstemp(prefix='.geoip-', dir=target.parent)
        os.close(fd)
        try:
            with requests.get(url, stream=True, timeout=timeout) as response:
                if response.status_code != 200:
                    errors.append(f'{url}: HTTP {response.status_code}')
                    continue
                response.raw.decode_content = False
                with gzip.GzipFile(fileobj=response.raw) as gz, open(tmp, 'wb') as out:
                    shutil.copyfileobj(gz, out)
            with maxminddb.open_database(tmp) as reader:
                code, _ = _from_record(reader.get('8.8.8.8'))
            if code != 'US':
                errors.append(f'{url}: failed sanity check (8.8.8.8 -> {code!r})')
                continue
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
            return target
        except Exception as exc:
            errors.append(f'{url}: {exc}')
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    raise RuntimeError('; '.join(errors))
