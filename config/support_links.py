"""Where the "Help Us Grow" call to action points.

One place for every destination the support modal offers, so the modal markup
carries no URLs of its own and the same partial can be dropped into another of
our apps by editing this file alone.

Reusing this across apps
------------------------
``PROJECT`` is the only block that is specific to this app. ``NETWORK``,
``GITHUB``, ``SPONSOR`` and ``BUSINESS`` are the shared network and are meant
to be identical everywhere. An install can override any of it without touching
the file by setting ``SUPPORT_LINKS`` in ``config/settings.py`` (or the
environment-driven settings layer) to a dict of the same shape — only the keys
present are replaced, one level deep.

Ground rules for editing
------------------------
* Only confirmed, public URLs. No product site exists for this project yet, so
  ``public_url`` is the public repository — see ``docs/github-about.md``, which
  records that ``clientst0r.mspreboot.com`` has no DNS record.
* ``public_url`` is what gets shared. It must never be the URL of the running
  install: that is a private dashboard, often a tenant hostname, and may carry
  tokens.
* Claim only what is true per project. This project is MIT-licensed, so it may
  be called open source; the others are products and services and are not
  described that way.
* No prices, no licensing claims, no invented features.
"""

from copy import deepcopy

# The public repository for this project. Confirmed: the README badges, the
# release downloads and the bug-report template all point at it.
_REPO = 'https://github.com/agit8or1/clientst0r'

#: Everything the modal needs, as plain data.
DEFAULTS = {
    # ---------------------------------------------------------------- project
    'PROJECT': {
        'name': 'ClientSt0r',
        # Kept to one accurate line — it ends up in the share message, which
        # people paste into their own feeds under their own name.
        # Length matters: the assembled share message has to clear X's 280
        # characters with the URL counted at its shortened 23. Measured at 260.
        'description': (
            'a self-hosted IT documentation and service desk for MSPs '
            '— client assets, runbooks, an encrypted credential vault and '
            'native ticketing, on your own infrastructure'
        ),
        # The canonical public URL to share. Never the current dashboard.
        'public_url': _REPO,
        # Where "Star This Project" goes. Empty string hides that button.
        'repo_url': _REPO,
        'is_open_source': True,
        'license': 'MIT',
    },

    # ---------------------------------------------------------------- network
    # Our other projects. Each one gets a Visit action and its own Share /
    # Copy link action in the modal.
    'NETWORK': [
        {
            'name': 'MSP Reboot',
            'url': 'https://mspreboot.com',
            'description': 'MSP consulting and IT services — the practice behind this project.',
            'icon': 'fas fa-briefcase',
        },
        {
            'name': 'MSPZero',
            'url': 'https://mspzero.com',
            'description': 'Another tool in the works for MSPs and the businesses they look after.',
            'icon': 'fas fa-bolt',
        },
    ],

    # The one-paragraph pitch for the network as a whole, offered as a
    # ready-to-copy message. Wording is fixed on purpose — it is the line we
    # ask people to pass on.
    'NETWORK_MESSAGE': (
        'Know an MSP or business owner looking for useful tools and IT services? '
        'Check out https://mspreboot.com and https://mspzero.com, and pass them '
        'along to someone who could use them.'
    ),

    # ----------------------------------------------------------------- github
    'GITHUB': {
        'org_url': 'https://github.com/agit8or1',
    },

    # ---------------------------------------------------------------- sponsor
    # The verified sponsorship destination that has shipped in this app since
    # before the modal was rebuilt. Set ``url`` to '' and the whole Sponsor
    # Development section is omitted rather than rendered empty.
    'SPONSOR': {
        'url': 'https://github.com/sponsors/agit8or1',
        'label': 'GitHub Sponsors',
    },

    # --------------------------------------------------------------- business
    'BUSINESS': {
        'name': 'MSP Reboot',
        'url': 'https://mspreboot.com',
        'facebook_url': 'https://facebook.com/mspreboot',
    },
}


def _share_message(project):
    """The suggested post. Assembled here so it cannot drift from the URL."""
    return (
        f"Check out {project['name']}: {project['description']}. "
        f"If it looks useful, give it a try and pass it along! "
        f"{project['public_url']}"
    )


def get_support_links():
    """Return the resolved support-link data, applying any settings override.

    Safe to call without Django configured — the override is optional.
    """
    data = deepcopy(DEFAULTS)

    try:
        from django.conf import settings as django_settings
        override = getattr(django_settings, 'SUPPORT_LINKS', None) or {}
    except Exception:
        override = {}

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key].update(value)
        else:
            data[key] = value

    data['SHARE_MESSAGE'] = _share_message(data['PROJECT'])
    return data
