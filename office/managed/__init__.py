"""Managed Local ONLYOFFICE: clientst0r provisions and runs one pinned
ONLYOFFICE Docs container on its own VM through the Office service helper
(deploy/office-helper/clientst0r-office-helper).

    ipc.py        the only way to talk to the helper (Unix socket, fixed
                  operations, no paths/images/commands)
    jobs.py       background lifecycle operations: lock, lease, drain,
                  helper operation, verification, recovery
    provision.py  writes the ONLYOFFICE EditorInstance from the helper's
                  status (URLs, JWT secret) and checks it
    checks.py     setup checks (helper preflight + clientst0r-side
                  reachability in all three directions)

See docs/office/MANAGED_LOCAL.md.
"""
