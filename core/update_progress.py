"""
Real-time update progress tracking.
Uses file-based storage to persist across service restarts.
"""
import json
import time
import os
from pathlib import Path
from django.conf import settings


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
        """Update progress data."""
        try:
            with open(self.progress_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            # Fallback to no progress tracking if file write fails
            pass

    def get_progress(self):
        """Get current progress."""
        try:
            if self.progress_file.exists():
                with open(self.progress_file, 'r') as f:
                    return json.load(f)
        except Exception:
            pass

        # Return default if file doesn't exist or can't be read
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
        """Mark a step as starting."""
        progress = self.get_progress()
        progress['current_step'] = step_name
        self.set_progress(progress)
        self.add_log(f"Starting: {step_name}", 'info')

    def step_complete(self, step_name):
        """Mark a step as complete."""
        progress = self.get_progress()
        progress['steps_completed'].append(step_name)
        progress['current_step'] = ''
        self.set_progress(progress)
        self.add_log(f"Completed: {step_name}", 'success')

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
