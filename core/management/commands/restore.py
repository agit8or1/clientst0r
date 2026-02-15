"""
Restore management command for Client St0r
Restores encrypted backups of database and media files
"""

import os
import subprocess
import json
import tarfile
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from cryptography.fernet import Fernet


class Command(BaseCommand):
    help = 'Restore from encrypted backup file'

    def add_arguments(self, parser):
        parser.add_argument(
            'backup_file',
            type=str,
            help='Path to backup file to restore'
        )
        parser.add_argument(
            '--decrypt',
            action='store_true',
            help='Decrypt backup file before restoring'
        )
        parser.add_argument(
            '--skip-database',
            action='store_true',
            help='Skip database restore'
        )
        parser.add_argument(
            '--skip-media',
            action='store_true',
            help='Skip media files restore'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force restore without confirmation'
        )

    def handle(self, *args, **options):
        backup_file = Path(options['backup_file'])

        if not backup_file.exists():
            raise CommandError(f'Backup file not found: {backup_file}')

        # Safety confirmation
        if not options['force']:
            confirm = input(
                'WARNING: This will overwrite existing data. '
                'Type "yes" to continue: '
            )
            if confirm.lower() != 'yes':
                self.stdout.write('Restore cancelled')
                return

        self.stdout.write(self.style.WARNING('Starting restore process...'))

        try:
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                # Decrypt if needed
                if options['decrypt'] or backup_file.suffix == '.enc':
                    self.stdout.write('Decrypting backup...')
                    decrypted_file = self._decrypt_backup(backup_file, temp_path)
                    backup_file = decrypted_file

                # Extract archive
                self.stdout.write('Extracting backup archive...')
                extract_dir = self._extract_archive(backup_file, temp_path)

                # Read metadata
                metadata = self._read_metadata(extract_dir)
                self.stdout.write(f'Backup created: {metadata.get("backup_time", "unknown")}')
                self.stdout.write(f'Client St0r version: {metadata.get("clientst0r_version", "unknown")}')

                # Restore database
                if not options['skip_database']:
                    self.stdout.write('Restoring database...')
                    self._restore_database(extract_dir)

                # Restore media files
                if not options['skip_media']:
                    self.stdout.write('Restoring media files...')
                    self._restore_media(extract_dir)

            self.stdout.write(self.style.SUCCESS('Restore completed successfully!'))
            self.stdout.write(self.style.WARNING(
                'Please restart the application for changes to take effect.'
            ))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Restore failed: {str(e)}'))
            raise CommandError(f'Restore failed: {str(e)}')

    def _decrypt_backup(self, encrypted_file, temp_dir):
        """Decrypt backup file"""
        # Get encryption key from settings
        master_key = settings.APP_MASTER_KEY.encode()
        fernet = Fernet(master_key)

        # Read encrypted file
        with open(encrypted_file, 'rb') as f:
            encrypted_data = f.read()

        # Decrypt
        try:
            decrypted_data = fernet.decrypt(encrypted_data)
        except Exception as e:
            raise CommandError(f'Decryption failed: {str(e)}. Check your APP_MASTER_KEY.')

        # Write decrypted file
        decrypted_file = temp_dir / 'decrypted_backup.tar.gz'
        with open(decrypted_file, 'wb') as f:
            f.write(decrypted_data)

        return decrypted_file

    def _extract_archive(self, archive_file, temp_dir):
        """Extract tar/tar.gz archive"""
        extract_dir = temp_dir / 'extracted'
        extract_dir.mkdir(exist_ok=True)

        with tarfile.open(archive_file, 'r:*') as tar:
            tar.extractall(extract_dir)

        # Find backup directory (should be named 'backup')
        backup_dir = extract_dir / 'backup'
        if not backup_dir.exists():
            # Try to find it
            subdirs = list(extract_dir.iterdir())
            if subdirs:
                backup_dir = subdirs[0]
            else:
                raise CommandError('Invalid backup archive structure')

        return backup_dir

    def _read_metadata(self, backup_dir):
        """Read backup metadata"""
        metadata_file = backup_dir / 'metadata.json'
        if not metadata_file.exists():
            return {}

        with open(metadata_file, 'r') as f:
            return json.load(f)

    def _restore_database(self, backup_dir):
        """Restore database from SQL file"""
        db_file = backup_dir / 'database.sql'
        if not db_file.exists():
            self.stdout.write(self.style.WARNING('No database backup found, skipping'))
            return

        db_config = settings.DATABASES['default']

        if db_config['ENGINE'] == 'django.db.backends.mysql':
            cmd = [
                'mysql',
                '-h', db_config.get('HOST', 'localhost'),
                '-P', str(db_config.get('PORT', 3306)),
                '-u', db_config['USER'],
                f"--password={db_config['PASSWORD']}",
                db_config['NAME']
            ]

            with open(db_file, 'r') as f:
                result = subprocess.run(cmd, stdin=f, stderr=subprocess.PIPE)

            if result.returncode != 0:
                raise CommandError(f'Database restore failed: {result.stderr.decode()}')

        elif db_config['ENGINE'] == 'django.db.backends.sqlite3':
            import shutil
            # Backup current database
            current_db = Path(db_config['NAME'])
            if current_db.exists():
                backup_db = current_db.with_suffix('.bak')
                shutil.copy2(current_db, backup_db)
                self.stdout.write(f'Current database backed up to: {backup_db}')

            # Restore from backup
            shutil.copy2(db_file, current_db)

        else:
            raise CommandError(f"Unsupported database engine: {db_config['ENGINE']}")

        self.stdout.write(self.style.SUCCESS('Database restored successfully'))

    def _restore_media(self, backup_dir):
        """Restore media files"""
        media_backup = backup_dir / 'media'
        if not media_backup.exists():
            self.stdout.write(self.style.WARNING('No media backup found, skipping'))
            return

        media_root = Path(settings.MEDIA_ROOT)

        # Backup current media
        if media_root.exists():
            import shutil
            backup_media = media_root.parent / f'media_backup_{int(datetime.now().timestamp())}'
            shutil.copytree(media_root, backup_media)
            self.stdout.write(f'Current media backed up to: {backup_media}')

        # Create media root if it doesn't exist
        media_root.mkdir(parents=True, exist_ok=True)

        # Restore media files
        import shutil
        for item in media_backup.iterdir():
            dest = media_root / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)

        self.stdout.write(self.style.SUCCESS('Media files restored successfully'))
