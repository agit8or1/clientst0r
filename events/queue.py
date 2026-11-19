"""Queue a changed source row for projection. Never raises: a problem here
must not break the save that triggered it (a ticket, an alert, a sync)."""
import logging

from django.db import transaction

logger = logging.getLogger(__name__)

# Backpressure: above this many waiting items new ones are dropped. Nothing is
# lost — the backstop scan finds new rows and the recheck pass revisits live
# events — it only arrives later.
QUEUE_CAP = 50000


def enqueue(source, source_id):
    if not source_id:
        return

    def _add():
        try:
            from .models import ProjectionQueueItem
            if ProjectionQueueItem.objects.count() >= QUEUE_CAP:
                return
            ProjectionQueueItem.objects.bulk_create(
                [ProjectionQueueItem(source=source, source_id=source_id)], ignore_conflicts=True)
        except Exception:  # noqa: BLE001 — see module docstring
            logger.warning('events: could not queue %s %s', source, source_id, exc_info=True)

    try:
        transaction.on_commit(_add)
    except Exception:  # noqa: BLE001
        logger.warning('events: could not schedule queueing of %s %s', source, source_id, exc_info=True)
