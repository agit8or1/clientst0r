"""Microsoft 365 documents (SharePoint / OneDrive) for an M365Connection.

A separately enabled capability of the existing Microsoft 365 connection.
The tenant-read and mail features keep their client-credentials app token and
its consent; this package never changes them. Documents use delegated sign-in
(authorization code + PKCE) per clientst0r user, so every Graph call runs as
that user and Microsoft's own permissions apply.

    scopes.py    which delegated permissions each mode requests, and why
    http.py      the only way this package reaches Microsoft (fixed hosts,
                 public addresses, TLS verified, sharing endpoints refused)
    oauth.py     PKCE sign-in, token refresh, disconnect
    graph.py     the Graph calls used (drive items, children, upload, content)
    access.py    clientst0r permissions and the allowed-locations rule
    services.py  link, open, create, import a copy, export a copy (audited)

See docs/office/MICROSOFT_365.md.
"""
