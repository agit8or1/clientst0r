"""
Bitwarden/Vaultwarden JSON export import utility.
Supports importing password vault data from Bitwarden JSON exports.
"""
import json
import logging
from datetime import datetime
from django.utils import timezone
from django.db import transaction
from .models import Password, PasswordFolder

logger = logging.getLogger('vault')


class BitwardenImporter:
    """Import passwords from Bitwarden JSON export."""

    # Map Bitwarden types to Client St0r types
    TYPE_MAPPING = {
        1: 'website',      # Login
        2: 'other',        # Secure Note
        3: 'credit_card',  # Card
        4: 'other',        # Identity
    }

    # Map Bitwarden field types
    FIELD_TYPE_TEXT = 0
    FIELD_TYPE_HIDDEN = 1
    FIELD_TYPE_BOOLEAN = 2

    def __init__(self, organization, user, folder_prefix=''):
        """
        Initialize importer.

        Args:
            organization: Organization to import passwords into
            user: User performing the import (for created_by)
            folder_prefix: Optional prefix for folder names
        """
        self.organization = organization
        self.user = user
        self.folder_prefix = folder_prefix
        self.folder_map = {}  # Bitwarden folder ID -> Client St0r PasswordFolder
        self.stats = {
            'folders_created': 0,
            'passwords_created': 0,
            'passwords_skipped': 0,
            'passwords_updated': 0,
            'errors': []
        }

    def import_from_json(self, json_data, update_existing=False):
        """
        Import passwords from Bitwarden JSON export.

        Args:
            json_data: Parsed JSON data from Bitwarden export
            update_existing: If True, update existing passwords with same title/username

        Returns:
            dict: Import statistics
        """
        try:
            with transaction.atomic():
                # Import folders first
                if 'folders' in json_data and json_data['folders']:
                    self._import_folders(json_data['folders'])

                # Import items (passwords)
                if 'items' in json_data and json_data['items']:
                    self._import_items(json_data['items'], update_existing)

        except Exception as e:
            logger.error(f"Bitwarden import failed: {str(e)}", exc_info=True)
            self.stats['errors'].append(f"Import failed: {str(e)}")

        return self.stats

    def _import_folders(self, folders):
        """Import Bitwarden folders."""
        for folder_data in folders:
            try:
                folder_id = folder_data.get('id')
                folder_name = folder_data.get('name') or 'Untitled Folder'

                # Add prefix if specified
                if self.folder_prefix:
                    folder_name = f"{self.folder_prefix}{folder_name}"

                # Check if folder exists
                existing_folder = PasswordFolder.objects.filter(
                    organization=self.organization,
                    name=folder_name,
                    parent=None
                ).first()

                if existing_folder:
                    self.folder_map[folder_id] = existing_folder
                else:
                    # Create folder
                    new_folder = PasswordFolder.objects.create(
                        organization=self.organization,
                        name=folder_name,
                        description=f'Imported from Bitwarden on {timezone.now().strftime("%Y-%m-%d")}'
                    )
                    self.folder_map[folder_id] = new_folder
                    self.stats['folders_created'] += 1
                    logger.info(f"Created folder: {folder_name}")

            except Exception as e:
                logger.error(f"Failed to import folder {folder_data.get('name')}: {str(e)}")
                self.stats['errors'].append(f"Folder import error: {str(e)}")

    def _import_items(self, items, update_existing):
        """Import Bitwarden items (passwords)."""
        for item_data in items:
            try:
                # Skip deleted items
                if item_data.get('deletedDate'):
                    self.stats['passwords_skipped'] += 1
                    continue

                # Get item type
                item_type = item_data.get('type', 1)  # Default to Login
                password_type = self.TYPE_MAPPING.get(item_type, 'other')

                # Parse item based on type
                if item_type == 1:  # Login
                    self._import_login_item(item_data, update_existing)
                elif item_type == 2:  # Secure Note
                    self._import_note_item(item_data, update_existing)
                elif item_type == 3:  # Card
                    self._import_card_item(item_data, update_existing)
                elif item_type == 4:  # Identity
                    self._import_identity_item(item_data, update_existing)
                else:
                    logger.warning(f"Unknown item type {item_type}, skipping")
                    self.stats['passwords_skipped'] += 1

            except Exception as e:
                item_name = item_data.get('name', 'Unknown')
                logger.error(f"Failed to import item {item_name}: {str(e)}")
                self.stats['errors'].append(f"Item '{item_name}': {str(e)}")

    def _import_login_item(self, item_data, update_existing):
        """Import a login item."""
        name = item_data.get('name') or 'Untitled'
        login = item_data.get('login', {})

        # Handle null values from Bitwarden export (use 'or' instead of default)
        username = login.get('username') or ''
        password = login.get('password') or ''
        totp = login.get('totp') or ''

        # Get first URI if available
        url = ''
        uris = login.get('uris', [])
        if uris and len(uris) > 0:
            url = uris[0].get('uri') or ''

        # Get folder
        folder = self._get_folder(item_data.get('folderId'))

        # Get notes (handle null values from Bitwarden export)
        notes = item_data.get('notes') or ''

        # Check if password exists
        existing = None
        if update_existing:
            existing = Password.objects.filter(
                organization=self.organization,
                title=name,
                username=username
            ).first()

        if existing:
            # Update existing password
            if password:
                existing.set_password(password)
            if url:
                existing.url = url
            if notes:
                existing.notes = notes
            if folder:
                existing.folder = folder
            if totp:
                existing.otp_secret = totp
                existing.password_type = 'otp'

            # Import custom fields
            self._import_custom_fields(existing, item_data.get('fields', []))

            existing.last_modified_by = self.user
            existing.save()
            self.stats['passwords_updated'] += 1
            logger.info(f"Updated password: {name}")
        else:
            # Create new password
            if not password:
                # Skip items without password
                self.stats['passwords_skipped'] += 1
                return

            new_password = Password(
                organization=self.organization,
                folder=folder,
                title=name,
                username=username,
                url=url,
                notes=notes,
                password_type='otp' if totp else 'website',
                created_by=self.user,
                last_modified_by=self.user
            )
            new_password.set_password(password)

            if totp:
                new_password.set_otp_secret(totp)

            new_password.save()

            # Import custom fields
            self._import_custom_fields(new_password, item_data.get('fields', []))
            new_password.save()

            self.stats['passwords_created'] += 1
            logger.info(f"Created password: {name}")

    def _import_note_item(self, item_data, update_existing):
        """Import a secure note item."""
        name = item_data.get('name') or 'Untitled Note'
        notes = item_data.get('notes') or ''
        folder = self._get_folder(item_data.get('folderId'))

        # Check if exists
        existing = None
        if update_existing:
            existing = Password.objects.filter(
                organization=self.organization,
                title=name,
                password_type='other'
            ).first()

        if existing:
            existing.notes = notes
            if folder:
                existing.folder = folder
            self._import_custom_fields(existing, item_data.get('fields', []))
            existing.last_modified_by = self.user
            existing.save()
            self.stats['passwords_updated'] += 1
        else:
            # Create with dummy password (required field)
            new_note = Password(
                organization=self.organization,
                folder=folder,
                title=name,
                notes=notes,
                password_type='other',
                created_by=self.user,
                last_modified_by=self.user
            )
            new_note.set_password('***')  # Dummy password
            new_note.save()
            self._import_custom_fields(new_note, item_data.get('fields', []))
            new_note.save()
            self.stats['passwords_created'] += 1

    def _import_card_item(self, item_data, update_existing):
        """Import a card item."""
        name = item_data.get('name') or 'Untitled Card'
        card = item_data.get('card', {})
        folder = self._get_folder(item_data.get('folderId'))
        notes = item_data.get('notes') or ''

        # Build custom fields from card data
        custom_fields = {}
        if card.get('cardholderName'):
            custom_fields['Cardholder Name'] = card['cardholderName']
        if card.get('brand'):
            custom_fields['Brand'] = card['brand']
        if card.get('number'):
            custom_fields['Card Number'] = card['number']
        if card.get('expMonth'):
            custom_fields['Expiry Month'] = card['expMonth']
        if card.get('expYear'):
            custom_fields['Expiry Year'] = card['expYear']
        if card.get('code'):
            custom_fields['CVV'] = card['code']

        # Check if exists
        existing = None
        if update_existing:
            existing = Password.objects.filter(
                organization=self.organization,
                title=name,
                password_type='credit_card'
            ).first()

        if existing:
            existing.notes = notes
            if folder:
                existing.folder = folder
            existing.custom_fields.update(custom_fields)
            self._import_custom_fields(existing, item_data.get('fields', []))
            existing.last_modified_by = self.user
            existing.save()
            self.stats['passwords_updated'] += 1
        else:
            new_card = Password(
                organization=self.organization,
                folder=folder,
                title=name,
                notes=notes,
                password_type='credit_card',
                custom_fields=custom_fields,
                created_by=self.user,
                last_modified_by=self.user
            )
            new_card.set_password(card.get('code', '***'))  # Use CVV as password
            new_card.save()
            self._import_custom_fields(new_card, item_data.get('fields', []))
            new_card.save()
            self.stats['passwords_created'] += 1

    def _import_identity_item(self, item_data, update_existing):
        """Import an identity item."""
        name = item_data.get('name') or 'Untitled Identity'
        identity = item_data.get('identity', {})
        folder = self._get_folder(item_data.get('folderId'))
        notes = item_data.get('notes') or ''

        # Build custom fields from identity data
        custom_fields = {}
        for key, value in identity.items():
            if value:
                # Convert camelCase to Title Case
                field_name = ''.join([' ' + c if c.isupper() else c for c in key]).strip().title()
                custom_fields[field_name] = value

        # Check if exists
        existing = None
        if update_existing:
            existing = Password.objects.filter(
                organization=self.organization,
                title=name,
                password_type='other'
            ).first()

        if existing:
            existing.notes = notes
            if folder:
                existing.folder = folder
            existing.custom_fields.update(custom_fields)
            self._import_custom_fields(existing, item_data.get('fields', []))
            existing.last_modified_by = self.user
            existing.save()
            self.stats['passwords_updated'] += 1
        else:
            new_identity = Password(
                organization=self.organization,
                folder=folder,
                title=name,
                notes=notes,
                password_type='other',
                custom_fields=custom_fields,
                created_by=self.user,
                last_modified_by=self.user
            )
            new_identity.set_password('***')  # Dummy password
            new_identity.save()
            self._import_custom_fields(new_identity, item_data.get('fields', []))
            new_identity.save()
            self.stats['passwords_created'] += 1

    def _import_custom_fields(self, password_obj, fields):
        """Import custom fields from Bitwarden item."""
        if not fields:
            return

        for field in fields:
            field_name = field.get('name')
            field_value = field.get('value')
            field_type = field.get('type', self.FIELD_TYPE_TEXT)

            if not field_name:
                continue

            # Convert boolean fields
            if field_type == self.FIELD_TYPE_BOOLEAN:
                field_value = 'Yes' if field_value else 'No'

            # Store in custom_fields JSON
            if not password_obj.custom_fields:
                password_obj.custom_fields = {}

            password_obj.custom_fields[field_name] = field_value

    def _get_folder(self, folder_id):
        """Get Client St0r folder from Bitwarden folder ID."""
        if not folder_id:
            return None
        return self.folder_map.get(folder_id)


def import_bitwarden_json(file_content, organization, user, folder_prefix='', update_existing=False):
    """
    Import Bitwarden JSON export.

    Args:
        file_content: JSON file content (string or bytes)
        organization: Organization to import into
        user: User performing import
        folder_prefix: Optional prefix for folder names
        update_existing: If True, update existing passwords

    Returns:
        dict: Import statistics
    """
    try:
        # Parse JSON
        if isinstance(file_content, bytes):
            file_content = file_content.decode('utf-8')

        json_data = json.loads(file_content)

        # Validate format
        if 'items' not in json_data:
            raise ValueError("Invalid Bitwarden export format: missing 'items' field")

        # Perform import
        importer = BitwardenImporter(organization, user, folder_prefix)
        stats = importer.import_from_json(json_data, update_existing)

        return stats

    except json.JSONDecodeError as e:
        return {
            'folders_created': 0,
            'passwords_created': 0,
            'passwords_skipped': 0,
            'passwords_updated': 0,
            'errors': [f"Invalid JSON format: {str(e)}"]
        }
    except Exception as e:
        logger.error(f"Bitwarden import error: {str(e)}", exc_info=True)
        return {
            'folders_created': 0,
            'passwords_created': 0,
            'passwords_skipped': 0,
            'passwords_updated': 0,
            'errors': [str(e)]
        }
