"""
Backup management command for Client St0r
Creates encrypted backups of database and media files
"""

import os
import subprocess
import json
import tarfile
import gzip
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from cryptography.fernet import Fernet


class Command(BaseCommand):
    help = 'Create encrypted backup of database and media files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            type=str,
            default='/tmp/clientst0r-backups',
            help='Directory to store backup files'
        )
        parser.add_argument(
            '--encrypt',
            action='store_true',
            help='Encrypt backup file'
        )
        parser.add_argument(
            '--include-media',
            action='store_true',
            default=True,
            help='Include media files in backup'
        )
        parser.add_argument(
            '--compress',
            action='store_true',
            default=True,
            help='Compress backup file'
        )
        parser.add_argument(
            '--retention-days',
            type=int,
            default=30,
            help='Number of days to retain backups'
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f'clientst0r_backup_{timestamp}'

        self.stdout.write(self.style.SUCCESS(f'Starting backup: {backup_name}'))

        try:
            # Create temporary backup directory
            temp_dir = output_dir / f'{backup_name}_temp'
            temp_dir.mkdir(exist_ok=True)

            # Backup database
            self.stdout.write('Backing up database...')
            db_file = self._backup_database(temp_dir)

            # Backup media files if requested
            if options['include_media']:
                self.stdout.write('Backing up media files...')
                self._backup_media(temp_dir)

            # Create backup metadata
            self._create_metadata(temp_dir, timestamp)

            # Create tarball
            self.stdout.write('Creating backup archive...')
            if options['compress']:
                archive_file = output_dir / f'{backup_name}.tar.gz'
                self._create_compressed_archive(temp_dir, archive_file)
            else:
                archive_file = output_dir / f'{backup_name}.tar'
                self._create_archive(temp_dir, archive_file)

            # Encrypt if requested
            if options['encrypt']:
                self.stdout.write('Encrypting backup...')
                encrypted_file = self._encrypt_backup(archive_file)
                archive_file.unlink()  # Remove unencrypted file
                archive_file = encrypted_file

            # Cleanup temp directory
            self._cleanup_temp(temp_dir)

            # Clean old backups
            if options['retention_days'] > 0:
                self._cleanup_old_backups(output_dir, options['retention_days'])

            file_size = archive_file.stat().st_size / (1024 * 1024)  # MB
            self.stdout.write(self.style.SUCCESS(
                f'Backup completed successfully!'
            ))
            self.stdout.write(f'Location: {archive_file}')
            self.stdout.write(f'Size: {file_size:.2f} MB')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Backup failed: {str(e)}'))
            raise CommandError(f'Backup failed: {str(e)}')

    def _backup_database(self, temp_dir):
        """Backup database to SQL file"""
        db_config = settings.DATABASES['default']
        db_file = temp_dir / 'database.sql'

        if db_config['ENGINE'] == 'django.db.backends.mysql':
            cmd = [
                'mysqldump',
                '-h', db_config.get('HOST', 'localhost'),
                '-P', str(db_config.get('PORT', 3306)),
                '-u', db_config['USER'],
                f"--password={db_config['PASSWORD']}",
                '--single-transaction',
                '--quick',
                '--lock-tables=false',
                db_config['NAME']
            ]

            with open(db_file, 'w') as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)

            if result.returncode != 0:
                raise CommandError(f'Database backup failed: {result.stderr.decode()}')

        elif db_config['ENGINE'] == 'django.db.backends.sqlite3':
            import shutil
            shutil.copy2(db_config['NAME'], db_file)

        else:
            raise CommandError(f"Unsupported database engine: {db_config['ENGINE']}")

        return db_file

    def _backup_media(self, temp_dir):
        """Backup media files"""
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            self.stdout.write(self.style.WARNING('Media directory does not exist, skipping'))
            return

        media_backup = temp_dir / 'media'
        media_backup.mkdir(exist_ok=True)

        # Copy media files
        import shutil
        for item in media_root.iterdir():
            if item.is_file():
                shutil.copy2(item, media_backup)
            elif item.is_dir():
                shutil.copytree(item, media_backup / item.name, dirs_exist_ok=True)

    def _create_metadata(self, temp_dir, timestamp):
        """Create backup metadata file"""
        from django import VERSION as DJANGO_VERSION
        import sys

        metadata = {
            'backup_time': timestamp,
            'clientst0r_version': getattr(settings, 'VERSION', 'unknown'),
            'django_version': '.'.join(map(str, DJANGO_VERSION)),
            'python_version': sys.version,
            'database_engine': settings.DATABASES['default']['ENGINE'],
        }

        metadata_file = temp_dir / 'metadata.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

    def _create_archive(self, source_dir, archive_file):
        """Create tar archive"""
        with tarfile.open(archive_file, 'w') as tar:
            tar.add(source_dir, arcname='backup')

    def _create_compressed_archive(self, source_dir, archive_file):
        """Create compressed tar.gz archive"""
        with tarfile.open(archive_file, 'w:gz') as tar:
            tar.add(source_dir, arcname='backup')

    def _encrypt_backup(self, archive_file):
        """Encrypt backup file using Fernet encryption"""
        # Get encryption key from settings
        master_key = settings.APP_MASTER_KEY.encode()
        fernet = Fernet(master_key)

        # Read archive file
        with open(archive_file, 'rb') as f:
            data = f.read()

        # Encrypt
        encrypted_data = fernet.encrypt(data)

        # Write encrypted file
        encrypted_file = archive_file.with_suffix(archive_file.suffix + '.enc')
        with open(encrypted_file, 'wb') as f:
            f.write(encrypted_data)

        return encrypted_file

    def _cleanup_temp(self, temp_dir):
        """Remove temporary backup directory"""
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    def _cleanup_old_backups(self, backup_dir, retention_days):
        """Remove backups older than retention period"""
        import time
        from datetime import timedelta

        cutoff_time = time.time() - (retention_days * 86400)
        removed_count = 0

        for backup_file in backup_dir.glob('clientst0r_backup_*'):
            if backup_file.stat().st_mtime < cutoff_time:
                backup_file.unlink()
                removed_count += 1

        if removed_count > 0:
            self.stdout.write(f'Removed {removed_count} old backup(s)')
