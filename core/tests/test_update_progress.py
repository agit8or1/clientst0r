"""The update progress file survives the reload that ends the update.

`set_progress` used `open(path, 'w')`, which truncates immediately and then
streams JSON out in buffered chunks. The last thing an update does is reload
gunicorn, killing the writer — and when that landed mid-write the file on disk
was a single 8KB buffer flush with no closing brace.

`get_progress` caught the parse error and returned `status: 'idle'`, which the
front-end could not tell apart from "no update is running". So the progress bar
sat on "Restart Service" indefinitely while the update had in fact succeeded.
Observed on a real update: 8195 bytes, ending mid-key at `"level"`.
"""
import json
import os
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from core.update_progress import MAX_LOG_LINES, UpdateProgress


class ProgressWriteTests(SimpleTestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = UpdateProgress(update_id='test')
        self.p.progress_file = Path(self.dir) / 'progress.json'

    def test_roundtrip(self):
        self.p.set_progress({'status': 'running', 'logs': [], 'steps_completed': []})
        self.assertEqual(self.p.get_progress()['status'], 'running')

    def test_no_partial_file_is_ever_visible(self):
        """The rename is the point: the target is either the whole old file or
        the whole new one. It must never be readable as half of either."""
        self.p.set_progress({'status': 'running', 'logs': [], 'steps_completed': []})
        for i in range(60):
            self.p.set_progress({
                'status': 'running', 'steps_completed': ['Git Pull'],
                'logs': [{'message': 'x' * 200, 'level': 'info', 'timestamp': i}] * 50,
            })
            with open(self.p.progress_file) as fh:
                json.load(fh)  # raises if a partial write were visible

    def test_no_temp_files_are_left_behind(self):
        for _ in range(5):
            self.p.set_progress({'status': 'running', 'logs': [], 'steps_completed': []})
        leftovers = [f for f in os.listdir(self.dir) if f != 'progress.json']
        self.assertEqual(leftovers, [], f'temp files left behind: {leftovers}')

    def test_logs_are_capped(self):
        """Unbounded logs meant every line rewrote an ever-larger file, which is
        what made a partial write likely rather than unlucky."""
        self.p.set_progress({
            'status': 'running', 'steps_completed': [],
            'logs': [{'message': f'line {i}', 'level': 'info', 'timestamp': i}
                     for i in range(MAX_LOG_LINES * 3)],
        })
        logs = self.p.get_progress()['logs']
        self.assertLessEqual(len(logs), MAX_LOG_LINES + 1)
        self.assertIn('trimmed', logs[0]['message'])
        # The newest lines are the ones worth keeping.
        self.assertIn(f'line {MAX_LOG_LINES * 3 - 1}', logs[-1]['message'])


class ProgressReadTests(SimpleTestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.p = UpdateProgress(update_id='test')
        self.p.progress_file = Path(self.dir) / 'progress.json'

    def test_missing_file_is_idle(self):
        self.assertEqual(self.p.get_progress()['status'], 'idle')

    def test_a_truncated_file_is_unknown_not_idle(self):
        """The exact shape seen in production: valid JSON cut off mid-key.

        Reporting this as 'idle' is what hung the progress bar — the front-end
        read it as "no update running" and kept showing the last step forever.
        """
        truncated = ('{"status": "completed", "current_step": "", '
                     '"steps_completed": ["Git Pull", "Restart Service"], '
                     '"logs": [{"message": "Flowchart", "level"')
        self.p.progress_file.write_text(truncated)
        state = self.p.get_progress()
        self.assertEqual(
            state['status'], 'unknown',
            'an unreadable progress file still reports as idle, which the '
            'front-end cannot distinguish from "nothing is happening"',
        )
        self.assertIn('may well have finished', state['error'])

    def test_garbage_file_is_unknown(self):
        self.p.progress_file.write_text('not json at all')
        self.assertEqual(self.p.get_progress()['status'], 'unknown')
