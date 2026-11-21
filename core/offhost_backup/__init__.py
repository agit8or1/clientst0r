"""Scheduled, encrypted off-host backups of this install (Phase 94.3, SR-17).

    crypto        backup key, streaming AES-256-GCM (segmented STREAM layout)
    archive       database + uploaded files into a tar.gz, and its checks
    destinations  SFTP (pinned host key) and mounted-directory destinations
    service       run / verify / retention / scheduler tick / health

Not to be confused with backup_monitoring, which watches customers' backups.
See docs/BACKUP_AND_RESTORE.md.
"""
