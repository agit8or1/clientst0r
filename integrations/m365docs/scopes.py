"""Delegated Graph permissions requested for documents, per connection mode.

These are requested only at the per-user "Connect my Microsoft 365 documents"
step (incremental consent). They are never added to the connection's
client-credentials token request, which keeps asking for
``https://graph.microsoft.com/.default`` exactly as before.

Facts come from Microsoft's Graph permissions reference (see
docs/office/MICROSOFT_365.md). ``Files.Read.Selected`` /
``Files.ReadWrite.Selected`` are deliberately not offered: Microsoft says
they are for Office file handlers and "should not be used for directly
calling Microsoft Graph APIs".
"""
GRAPH_RESOURCE = 'https://graph.microsoft.com/'

# The scope the existing tenant-read / mail features use. Listed here only so
# tests can assert it is never part of a documents request.
TENANT_READ_SCOPE = 'https://graph.microsoft.com/.default'

_WHY = {
    'Files.Read': "Read the signed-in user's own files (their OneDrive): list folders, "
                  'read file details and download a copy you ask to import.',
    'Files.ReadWrite': "Read and write the signed-in user's own files: also create new "
                       'files and upload copies you ask to export.',
    'Files.Read.All': 'Read files in SharePoint libraries the signed-in user can already '
                      'open. Microsoft still checks the user\'s own access on every call.',
    'Files.ReadWrite.All': 'Read and write files in SharePoint libraries the signed-in user '
                           'can already edit. Microsoft still checks the user\'s own access.',
    'Sites.Selected': 'Reach only the SharePoint sites a SharePoint administrator has '
                      'granted to this app; within them, the user\'s own access still applies.',
    'offline_access': 'Receive a refresh token so you do not have to sign in again every '
                      'hour. It is stored encrypted and deleted when you disconnect.',
}

# Whether Microsoft requires an administrator to consent to the delegated
# permission (Graph permissions reference). A tenant can still block user
# consent by policy; then an administrator consents once for everyone.
_ADMIN_CONSENT = {
    'Files.Read': False, 'Files.ReadWrite': False, 'Files.Read.All': False,
    'Files.ReadWrite.All': False, 'Sites.Selected': False, 'offline_access': False,
}

NEVER_REQUESTED = ('Files.Read.Selected', 'Files.ReadWrite.Selected')


def short_scopes(access, sharepoint):
    """Permission names (without the Graph resource prefix) for a mode."""
    write = access == 'readwrite'
    out = ['Files.ReadWrite' if write else 'Files.Read']
    if sharepoint == 'all':
        out.append('Files.ReadWrite.All' if write else 'Files.Read.All')
    elif sharepoint == 'selected':
        out.append('Sites.Selected')
    out.append('offline_access')
    return out


def for_connection(connection):
    return short_scopes(connection.docs_access, connection.docs_sharepoint)


def request_scopes(connection):
    """The space-separated ``scope`` parameter sent to Microsoft."""
    return ' '.join(s if s == 'offline_access' else GRAPH_RESOURCE + s
                    for s in for_connection(connection))


def normalise(scope_string):
    """Microsoft's ``scope`` reply → a set of short names."""
    out = set()
    for s in (scope_string or '').split():
        if s.lower().startswith(GRAPH_RESOURCE):
            s = s[len(GRAPH_RESOURCE):]
        out.add(s)
    return out


def missing(connection, granted):
    """Required permissions (except offline_access) not in `granted`."""
    granted_l = {g.lower() for g in granted}
    need = [s for s in for_connection(connection) if s != 'offline_access']
    # A ReadWrite permission also satisfies the matching Read one.
    out = []
    for s in need:
        if s.lower() in granted_l:
            continue
        if s.startswith('Files.Read') and not s.startswith('Files.ReadWrite') and \
                s.replace('Files.Read', 'Files.ReadWrite').lower() in granted_l:
            continue
        out.append(s)
    return out


def describe(connection=None, *, access=None, sharepoint=None):
    """[{scope, type, admin_consent, why}] for the settings page."""
    if connection is not None:
        names = for_connection(connection)
    else:
        names = short_scopes(access or 'read', sharepoint or 'none')
    return [{'scope': n, 'type': 'Delegated', 'admin_consent': _ADMIN_CONSENT[n],
             'why': _WHY[n]} for n in names]


def all_modes():
    """Every mode with its permissions, for the documentation table."""
    out = []
    for access in ('read', 'readwrite'):
        for sp in ('none', 'all', 'selected'):
            out.append({'access': access, 'sharepoint': sp,
                        'scopes': short_scopes(access, sp)})
    return out
