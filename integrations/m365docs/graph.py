"""The Microsoft Graph calls the documents feature makes, as the signed-in user.

Every request goes through m365docs.http (graph.microsoft.com only, sharing
endpoints refused). IDs from the browser are validated before they are put
into a path, and file names are percent-encoded, so nothing a user types can
change which Graph resource is addressed.

Response shapes follow the Graph v1.0 driveItem / drive / site resources:
    driveItem: {id, name, eTag, size, webUrl, file{mimeType}|folder{childCount},
                parentReference{driveId, id, path}, '@microsoft.graph.downloadUrl'}
    children:  {value: [driveItem], '@odata.nextLink'?}
"""
from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

from . import http, oauth

ITEM_SELECT = 'id,name,eTag,size,webUrl,file,folder,parentReference,lastModifiedDateTime'
MAX_PAGES = 10
_ID_RE = re.compile(r'^[A-Za-z0-9!_.\-]{1,300}$')
_SITE_ID_RE = re.compile(r'^[A-Za-z0-9.,\-]{1,300}$')
_BAD_NAME = re.compile(r'[\x00-\x1f"*:<>?/\\|#%]')


class GraphError(Exception):
    def __init__(self, status, code='', message=''):
        super().__init__(f'Graph {status} {code}: {message}'.strip())
        self.status, self.code, self.message = status, code, message

    @property
    def user_message(self):
        if self.status in (401, 403):
            return ('Microsoft 365 refused access. You may not have access to this file or '
                    'folder any more, or the app lacks the permission for it.')
        if self.status == 404:
            return 'Microsoft 365 could not find the item (moved, deleted or no longer shared).'
        if self.status == 409:
            return 'A file with that name already exists in the folder. Choose another name.'
        if self.status == 413:
            return 'The file is too large to upload this way (limit 250 MB).'
        return f'Microsoft 365 returned an error ({self.status}{" " + self.code if self.code else ""}).'


def valid_id(value) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value) or '..' in value:
        raise ValueError('Invalid Microsoft 365 identifier')
    return value


def valid_site_id(value) -> str:
    if not isinstance(value, str) or not _SITE_ID_RE.match(value) or '..' in value:
        raise ValueError('Invalid SharePoint site identifier')
    return value


def valid_name(name) -> str:
    name = (name or '').strip()
    if not name or len(name) > 250 or _BAD_NAME.search(name) or name.startswith('.') \
            or name.endswith('.') or name.startswith('~$'):
        raise ValueError('That file name cannot be used in OneDrive / SharePoint.')
    return name


def _q(value):
    return quote(value, safe='!')


class GraphClient:
    def __init__(self, grant=None, *, bearer=None):
        self.grant = grant
        self._bearer = bearer
        self._my_drive = None

    @property
    def connection(self):
        return self.grant.connection

    def _token(self):
        return self._bearer or oauth.access_token(self.grant)

    def request(self, method, path, *, params=None, body=None, content_type=None,
                max_bytes=http.DEFAULT_MAX_BYTES, timeout=None):
        url = path if path.startswith('https://') else http.GRAPH_BASE + path
        if params:
            url += ('&' if '?' in url else '?') + urlencode(params, safe='$,@')
        headers = {'Authorization': f'Bearer {self._token()}', 'Accept': 'application/json'}
        if content_type:
            headers['Content-Type'] = content_type
        return http.send(method, url, allowed_hosts={http.GRAPH_HOST}, headers=headers,
                         data=body, max_bytes=max_bytes, timeout=timeout)

    def json(self, method, path, **kw):
        res = self.request(method, path, **kw)
        try:
            payload = json.loads(res.content or b'{}')
        except ValueError:
            payload = {}
        if res.status_code >= 400:
            err = payload.get('error') if isinstance(payload, dict) else None
            err = err if isinstance(err, dict) else {}
            raise GraphError(res.status_code, str(err.get('code', ''))[:100],
                             str(err.get('message', ''))[:300])
        return payload

    # -- drives and items ----------------------------------------------------
    def my_drive(self):
        if self._my_drive is None:
            self._my_drive = self.json('GET', '/me/drive',
                                       params={'$select': 'id,driveType,webUrl,owner,name'})
        return self._my_drive

    def drive(self, drive_id):
        return self.json('GET', f'/drives/{_q(valid_id(drive_id))}',
                         params={'$select': 'id,name,driveType,webUrl'})

    def item(self, drive_id, item_id, select=ITEM_SELECT):
        path = f'/drives/{_q(valid_id(drive_id))}/' + (
            'root' if item_id in ('', 'root', None) else f'items/{_q(valid_id(item_id))}')
        return self.json('GET', path, params={'$select': select} if select else None)

    def children(self, drive_id, item_id):
        path = f'/drives/{_q(valid_id(drive_id))}/' + (
            'root/children' if item_id in ('', 'root', None)
            else f'items/{_q(valid_id(item_id))}/children')
        data = self.json('GET', path, params={'$select': ITEM_SELECT, '$top': '200'})
        items = list(data.get('value', []))
        pages = 1
        while data.get('@odata.nextLink') and pages < MAX_PAGES:
            next_link = data['@odata.nextLink']
            if not http.is_allowed(next_link, {http.GRAPH_HOST}):
                break
            data = self.json('GET', next_link)
            items.extend(data.get('value', []))
            pages += 1
        return items

    # -- sites ----------------------------------------------------------------
    def site(self, site_id):
        return self.json('GET', f'/sites/{_q(valid_site_id(site_id))}',
                         params={'$select': 'id,displayName,webUrl,name'})

    def site_by_path(self, hostname, server_path):
        if not http.valid_sharepoint_host(hostname):
            raise ValueError('Not a SharePoint host')
        server_path = '/' + server_path.strip('/')
        if '..' in server_path or not re.match(r'^[A-Za-z0-9/_\-. ]{1,400}$', server_path):
            raise ValueError('Invalid site path')
        path = f'/sites/{hostname}:{quote(server_path)}'
        return self.json('GET', path, params={'$select': 'id,displayName,webUrl,name'})

    def site_drives(self, site_id):
        data = self.json('GET', f'/sites/{_q(valid_site_id(site_id))}/drives',
                         params={'$select': 'id,name,driveType,webUrl'})
        return list(data.get('value', []))

    # -- writes ---------------------------------------------------------------
    def upload_new(self, drive_id, parent_id, name, data: bytes, mime='application/octet-stream'):
        """Create a file; fails with 409 if the name exists (never replaces)."""
        name = valid_name(name)
        parent = 'root' if parent_id in ('', 'root', None) else f'items/{_q(valid_id(parent_id))}'
        path = (f'/drives/{_q(valid_id(drive_id))}/{parent}:/{quote(name, safe="")}:/content')
        return self.json('PUT', path, params={'@microsoft.graph.conflictBehavior': 'fail'},
                         body=data, content_type=mime)

    def child_by_name(self, drive_id, parent_id, name):
        """The item called `name` directly in the parent folder (path addressing)."""
        name = valid_name(name)
        parent = 'root' if parent_id in ('', 'root', None) else f'items/{_q(valid_id(parent_id))}'
        return self.json('GET', f'/drives/{_q(valid_id(drive_id))}/{parent}:/{quote(name, safe="")}',
                         params={'$select': ITEM_SELECT})

    def ensure_folder(self, drive_id, parent_id, name):
        """The folder `name` in the parent, created when missing. Never renames
        or replaces anything: conflictBehavior=fail, then the existing item is
        read back and must be a folder."""
        name = valid_name(name)
        parent = 'root' if parent_id in ('', 'root', None) else f'items/{_q(valid_id(parent_id))}'
        body = json.dumps({'name': name, 'folder': {},
                           '@microsoft.graph.conflictBehavior': 'fail'}).encode()
        try:
            return self.json('POST', f'/drives/{_q(valid_id(drive_id))}/{parent}/children',
                             body=body, content_type='application/json')
        except GraphError as e:
            if e.status != 409:
                raise
        existing = self.child_by_name(drive_id, parent_id, name)
        if 'folder' not in existing:
            raise GraphError(409, 'nameAlreadyExists', 'A file has the working-copy folder name')
        return existing

    def item_state(self, drive_id, item_id):
        """Change-detection metadata of one item (eTag, cTag, size, last modified)."""
        return self.item(drive_id, item_id,
                         select='id,name,eTag,cTag,size,webUrl,file,parentReference,'
                                'lastModifiedDateTime,lastModifiedBy')

    def delete_item(self, drive_id, item_id, if_match=''):
        """DELETE one item (OneDrive / SharePoint move it to the recycle bin).
        With `if_match` (an eTag) Microsoft refuses with 412 when the item
        changed since. A 404 counts as already gone."""
        path = f'/drives/{_q(valid_id(drive_id))}/items/{_q(valid_id(item_id))}'
        url = http.GRAPH_BASE + path
        headers = {'Authorization': f'Bearer {self._token()}', 'Accept': 'application/json'}
        if if_match:
            headers['If-Match'] = if_match
        res = http.send('DELETE', url, allowed_hosts={http.GRAPH_HOST}, headers=headers)
        if res.status_code in (200, 204, 404):
            return res.status_code != 404
        try:
            err = (json.loads(res.content or b'{}').get('error') or {})
        except (ValueError, AttributeError):
            err = {}
        raise GraphError(res.status_code, str(err.get('code', ''))[:100],
                         str(err.get('message', ''))[:300])

    # -- content --------------------------------------------------------------
    def download(self, drive_id, item_id, max_bytes, allowed_hosts):
        """(metadata, bytes). The pre-authenticated ``downloadUrl`` is fetched
        without the bearer token, and only from the tenant's SharePoint hosts."""
        meta = self.item(drive_id, item_id, select=None)
        if 'file' not in meta:
            raise ValueError('Only files can be imported.')
        size = int(meta.get('size') or 0)
        if size > max_bytes:
            raise ValueError(f'The file is larger than the {max_bytes // (1024 * 1024)} MB limit.')
        url = meta.get('@microsoft.graph.downloadUrl') or ''
        if not url:
            raise GraphError(502, 'noDownloadUrl', 'Graph returned no download URL')
        if not allowed_hosts or not http.is_allowed(url, allowed_hosts):
            raise http.RefusedURL('The download URL is not on this tenant\'s SharePoint host.')
        res = http.send('GET', url, allowed_hosts=allowed_hosts, max_bytes=max_bytes,
                        headers={'Accept': '*/*'}, timeout=120)
        if res.status_code != 200:
            raise GraphError(res.status_code, 'download', 'Download failed')
        return meta, res.content
