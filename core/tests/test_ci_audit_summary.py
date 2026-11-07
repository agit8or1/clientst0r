"""Run the CI audit-summary tests in the Django suite too (scripts/ci is not an app)."""
import sys
from pathlib import Path

from django.conf import settings

sys.path.insert(0, str(Path(settings.BASE_DIR) / 'scripts' / 'ci'))
from test_pip_audit_summary import SummaryOutcomeTests  # noqa: E402,F401
