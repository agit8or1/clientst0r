"""
Test organization cascade deletion

This command creates a test organization with sample data,
then deletes it to verify cascade deletion works correctly.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from core.models import Organization, Tag
from assets.models import Asset, Contact
from vault.models import Password
from docs.models import Document, DocumentCategory
from files.models import Attachment
from audit.models import AuditLog
from monitoring.models import WebsiteMonitor
import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile

User = get_user_model()


class Command(BaseCommand):
    help = 'Test organization cascade deletion'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually perform deletion (default is dry-run)'
        )

    def handle(self, *args, **options):
        execute = options['execute']

        if not execute:
            self.stdout.write(
                self.style.WARNING(
                    "🔍 DRY RUN MODE - No actual deletion will occur"
                )
            )
            self.stdout.write(
                "    Use --execute flag to actually test deletion\n"
            )

        # Create test organization
        self.stdout.write("Creating test organization...")

        with transaction.atomic():
            # Get or create test user
            user = User.objects.filter(username='testuser').first()
            if not user:
                user = User.objects.create_user(
                    username='testuser',
                    email='test@example.com',
                    password='testpass123'
                )

            # Create organization
            org = Organization.objects.create(
                name='Test Cascade Deletion Org',
                slug='test-cascade-deletion-org',
                description='Temporary organization for testing cascade deletion'
            )

            # Create related data
            tag = Tag.objects.create(
                organization=org,
                name='Test Tag',
                slug='test-tag'
            )

            contact = Contact.objects.create(
                organization=org,
                first_name='John',
                last_name='Doe',
                email='john@example.com'
            )

            asset1 = Asset.objects.create(
                organization=org,
                name='Test Server',
                asset_type='server',
                serial_number='TEST123456'
            )

            asset2 = Asset.objects.create(
                organization=org,
                name='Test Workstation',
                asset_type='desktop',
                serial_number='TEST789012'
            )

            category = DocumentCategory.objects.create(
                organization=org,
                name='Test Category',
                slug='test-category'
            )

            document = Document.objects.create(
                organization=org,
                category=category,
                title='Test Document',
                slug='test-document',
                body='<p>Test content</p>'
            )

            password = Password.objects.create(
                organization=org,
                title='Test Password',
                username='admin',
                password_type='login'
            )
            password.set_password('TestPass123!')

            monitor = WebsiteMonitor.objects.create(
                organization=org,
                url='https://example.com',
                name='Test Monitor'
            )

            # Create audit logs (should persist with NULL org after deletion)
            audit1 = AuditLog.objects.create(
                organization=org,
                action='create',
                object_type='test',
                description='Test audit log 1',
                user=user,
                username=user.username
            )

            audit2 = AuditLog.objects.create(
                organization=org,
                action='create',
                object_type='test',
                description='Test audit log 2',
                user=user,
                username=user.username
            )

            self.stdout.write(self.style.SUCCESS("✓ Test organization created"))

            # Count records before deletion
            counts_before = {
                'tags': org.tags.count(),
                'contacts': org.contacts.count(),
                'assets': org.assets.count(),
                'documents': org.documents.count(),
                'document_categories': org.document_categories.count(),
                'passwords': org.passwords.count(),
                'website_monitors': org.website_monitors.count(),
                'audit_logs': org.audit_logs.count(),
            }

            self.stdout.write("\n📊 Records created:")
            for model, count in counts_before.items():
                self.stdout.write(f"   • {model}: {count}")

            org_id = org.id
            org_name = org.name

            if not execute:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n⚠️  Would delete organization: {org_name}"
                    )
                )
                self.stdout.write(
                    "    All related records would be cascade deleted"
                )
                self.stdout.write(
                    "    Audit logs would remain with NULL organization"
                )

                # Clean up test org
                org.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        "\n✓ Test organization cleaned up (dry run)"
                    )
                )
                return

        # Execute actual deletion test
        self.stdout.write(
            self.style.WARNING(
                f"\n🗑️  DELETING organization: {org_name}"
            )
        )

        # Delete organization
        org.delete()

        self.stdout.write(self.style.SUCCESS("✓ Organization deleted"))

        # Verify cascades
        self.stdout.write("\n🔍 Verifying cascade deletion...")

        counts_after = {
            'tags': Tag.objects.filter(organization_id=org_id).count(),
            'contacts': Contact.objects.filter(organization_id=org_id).count(),
            'assets': Asset.objects.filter(organization_id=org_id).count(),
            'documents': Document.objects.filter(organization_id=org_id).count(),
            'document_categories': DocumentCategory.objects.filter(organization_id=org_id).count(),
            'passwords': Password.objects.filter(organization_id=org_id).count(),
            'website_monitors': WebsiteMonitor.objects.filter(organization_id=org_id).count(),
        }

        errors = []
        for model, count in counts_after.items():
            if count > 0:
                errors.append(f"{model}: {count} records NOT deleted (expected 0)")
                self.stdout.write(
                    self.style.ERROR(f"   ✗ {model}: {count} records remain")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"   ✓ {model}: All deleted")
                )

        # Verify audit logs remain with NULL organization
        remaining_audits = AuditLog.objects.filter(
            organization__isnull=True,
            object_type='test'
        ).count()

        if remaining_audits >= counts_before['audit_logs']:
            self.stdout.write(
                self.style.SUCCESS(
                    f"   ✓ audit_logs: {remaining_audits} preserved with NULL org"
                )
            )
        else:
            errors.append(f"audit_logs: Only {remaining_audits} preserved, expected {counts_before['audit_logs']}")
            self.stdout.write(
                self.style.ERROR(
                    f"   ✗ audit_logs: Only {remaining_audits} preserved"
                )
            )

        # Clean up test audit logs
        AuditLog.objects.filter(
            organization__isnull=True,
            object_type='test'
        ).delete()

        # Final result
        if errors:
            self.stdout.write(
                self.style.ERROR(
                    f"\n❌ CASCADE DELETION TEST FAILED"
                )
            )
            for error in errors:
                self.stdout.write(f"   • {error}")
            return

        self.stdout.write(
            self.style.SUCCESS(
                "\n✅ CASCADE DELETION TEST PASSED"
            )
        )
        self.stdout.write("   • All related records deleted correctly")
        self.stdout.write("   • Audit logs preserved as expected")
