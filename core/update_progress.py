"""
Real-time update progress tracking.
Uses file-based storage to persist across service restarts.
"""
import json
import time
import os
import tempfile
from pathlib import Path
from django.conf import settings

# Cap on retained log lines. Every write rewrites the whole file.
MAX_LOG_LINES = 400


class UpdateProgress:
    """Track and report update progress using file-based storage."""

    def __init__(self, update_id='current'):
        self.update_id = update_id
        # Store progress in /tmp which persists across gunicorn restarts
        self.progress_file = Path(f'/tmp/clientst0r_update_progress_{update_id}.json')

    def start(self):
        """Initialize progress tracking."""
        self.set_progress({
            'status': 'running',
            'current_step': '',
            'steps_completed': [],
            'total_steps': 5,
            'logs': [],
            'started_at': time.time()
        })

    def set_progress(self, data):
        """Write progress atomically.

        `open(path, 'w')` truncates immediately and then streams the JSON out
        in buffered chunks. The last thing an update does is reload gunicorn,
        which kills this process — and if that lands mid-write, the file on
        disk is one 8KB buffer flush with no closing brace. The update has
        succeeded and the progress file says nothing parseable about it.

        Writing to a temporary file in the same directory and renaming over
        the target makes the swap atomic: a reader sees either the whole old
        file or the whole new one, never half of either.
        """
        data = self._trim_logs(data)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self.progress_file.parent),
                prefix=f'.{self.progress_file.name}.', suffix='.tmp')
            with os.fdopen(fd, 'w') as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.progress_file)
            tmp_path = None
        except Exception:
            # Progress reporting is cosmetic; never let it break an update.
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @staticmethod
    def _trim_logs(data, keep=MAX_LOG_LINES):
        """Keep the log list bounded.

        It was unbounded, and every line rewrites the whole file, so a long
        update did O(n^2) work and produced a file large enough that a
        partial write was likely rather than unlucky.
        """
        logs = data.get('logs')
        if isinstance(logs, list) and len(logs) > keep:
            dropped = len(logs) - keep
            data = dict(data)
            data['logs'] = ([{
                'message': f'... {dropped} earlier line(s) trimmed ...',
                'level': 'info',
                'timestamp': time.time(),
            }] + logs[-keep:])
        return data

    def get_progress(self):
        """Get current progress.

        A file that exists but will not parse is reported as `unknown`, not
        `idle`. They are different situations and the front-end has to be able
        to tell them apart: `idle` means no update is running, which is what
        left the progress bar sitting on its last step forever when a
        truncated file was read as "nothing happening".
        """
        if not self.progress_file.exists():
            return self._idle()
        try:
            with open(self.progress_file, 'r') as f:
                return json.load(f)
        except (ValueError, OSError):
            state = self._idle()
            state['status'] = 'unknown'
            state['error'] = ('The progress file could not be read. The update '
                              'itself may well have finished — check the '
                              'version on this page.')
            return state

    @staticmethod
    def _idle():
        return {
            'status': 'idle',
            'current_step': '',
            'steps_completed': [],
            'total_steps': 5,
            'logs': []
        }

    def add_log(self, message, level='info'):
        """Add a log message."""
        progress = self.get_progress()
        progress['logs'].append({
            'message': message,
            'level': level,
            'timestamp': time.time()
        })
        self.set_progress(progress)

    def step_start(self, step_name):
        """Mark a step as starting (single file write)."""
        progress = self.get_progress()
        progress['current_step'] = step_name
        progress['logs'].append({
            'message': f'Starting: {step_name}',
            'level': 'info',
            'timestamp': time.time()
        })
        self.set_progress(progress)

    def step_complete(self, step_name):
        """Mark a step as complete (single file write)."""
        progress = self.get_progress()
        if step_name not in progress.get('steps_completed', []):
            progress['steps_completed'].append(step_name)
        progress['current_step'] = ''
        progress['logs'].append({
            'message': f'Completed: {step_name}',
            'level': 'success',
            'timestamp': time.time()
        })
        self.set_progress(progress)

    def process_log_line(self, message, step_triggers=None):
        """Add a log line and optionally update step state in a single file write.

        step_triggers: list of (marker_substring, 'start'|'complete', step_name)
        """
        progress = self.get_progress()
        progress['logs'].append({
            'message': message,
            'level': 'info',
            'timestamp': time.time()
        })
        if step_triggers:
            for marker, action, step_name in step_triggers:
                if marker in message:
                    if action == 'start':
                        progress['current_step'] = step_name
                    else:
                        if step_name not in progress.get('steps_completed', []):
                            progress.setdefault('steps_completed', []).append(step_name)
                        progress['current_step'] = ''
                    break
        self.set_progress(progress)

    def finish(self, success=True, error=None):
        """Mark update as finished."""
        progress = self.get_progress()
        progress['status'] = 'completed' if success else 'failed'
        progress['current_step'] = ''
        progress['finished_at'] = time.time()
        if error:
            progress['error'] = error
            self.add_log(f"Error: {error}", 'error')
        else:
            self.add_log("Update completed successfully!", 'success')
        self.set_progress(progress)

    def clear(self):
        """Clear progress data."""
        try:
            if self.progress_file.exists():
                self.progress_file.unlink()
        except Exception:
            pass
