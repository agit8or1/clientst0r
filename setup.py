#!/usr/bin/env python3
"""
Client St0r Installation Setup Script
Creates default organization and initial data
"""
import os
import sys
import django

# Setup Django environment
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User
from core.models import Organization
from django.db import IntegrityError
from django.utils.text import slugify


def setup_organization():
    """Create default organization with user input."""
    print("\n" + "="*60)
    print("  Client St0r - Initial Setup")
    print("="*60 + "\n")

    # Check if organizations already exist
    if Organization.objects.exists():
        print("✓ Organizations already exist in database")
        org = Organization.objects.first()
        print(f"  Default organization: {org.name}")
        return org

    # Ask for business name
    print("Let's create your organization...")
    business_name = input("\nBusiness Name (Organization): ").strip()

    while not business_name:
        print("❌ Business name cannot be empty")
        business_name = input("Business Name (Organization): ").strip()

    # Generate slug
    slug = slugify(business_name)

    # Handle slug conflicts
    if Organization.objects.filter(slug=slug).exists():
        counter = 1
        original_slug = slug
        while Organization.objects.filter(slug=slug).exists():
            slug = f"{original_slug}-{counter}"
            counter += 1

    try:
        org = Organization.objects.create(
            name=business_name,
            slug=slug,
            is_active=True,
        )
        print(f"\n✓ Created organization: {org.name}")
        print(f"  Slug: {org.slug}")
        return org

    except IntegrityError as e:
        print(f"\n❌ Error creating organization: {e}")
        sys.exit(1)


def create_demo_floorplan(org):
    """Create demo office floor plan for organization."""
    from django.core.management import call_command

    print("\n" + "-"*60)
    create_demo = input("Create demo office floor plan? (y/n) [y]: ").strip().lower()

    if create_demo in ['', 'y', 'yes']:
        print("\nCreating demo office floor plan...")
        try:
            call_command('seed_demo_floorplan', '--organization-id', str(org.id))
            print("✓ Demo floor plan created successfully")
        except Exception as e:
            print(f"⚠ Warning: Could not create demo floor plan: {e}")
    else:
        print("Skipped demo floor plan creation")


def main():
    """Main setup function."""
    try:
        # Create organization
        org = setup_organization()

        # Create demo floor plan
        create_demo_floorplan(org)

        print("\n" + "="*60)
        print("  Setup Complete!")
        print("="*60)
        print(f"\nYour organization: {org.name}")
        print(f"Organization slug: {org.slug}")
        print("\nNext steps:")
        print("  1. Create a superuser: python manage.py createsuperuser")
        print("  2. Start the server: python manage.py runserver")
        print("  3. Visit http://localhost:8000/admin")
        print("\n")

    except KeyboardInterrupt:
        print("\n\n❌ Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
