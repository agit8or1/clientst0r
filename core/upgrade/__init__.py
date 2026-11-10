"""Install / upgrade hardening.

    channels   which revision Stable and Preview point at (GitHub, cached)
    revision   fetch an exact revision and prove it is the one reviewed
    preflight  checks that must pass before anything changes
    snapshot   pre-upgrade backup (database + media + keys), verify, restore
    journal    what the last upgrade did, so an interrupted one is noticed
    doctor     which migration a failed MySQL/MariaDB upgrade left half done
    apply      the pipeline Settings -> Updates and `manage.py upgrade_apply` run

See docs/UPGRADE_AND_RECOVERY.md.
"""
