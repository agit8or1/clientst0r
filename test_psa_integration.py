#!/usr/bin/env python
"""
Quick test script to verify PSA integration URLs are properly configured
"""
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.urls import reverse, resolve

def test_psa_urls():
    """Test that all PSA integration URLs resolve correctly."""

    urls_to_test = [
        # Connection management
        ('integrations:integration_list', {}),
        ('integrations:integration_create', {}),
        ('integrations:integration_detail', {'pk': 1}),
        ('integrations:integration_edit', {'pk': 1}),
        ('integrations:integration_delete', {'pk': 1}),
        ('integrations:integration_test', {'pk': 1}),
        ('integrations:integration_sync', {'pk': 1}),

        # PSA data views
        ('integrations:psa_companies', {}),
        ('integrations:psa_company_detail', {'pk': 1}),
        ('integrations:psa_contacts', {}),
        ('integrations:psa_contact_detail', {'pk': 1}),
        ('integrations:psa_tickets', {}),
        ('integrations:psa_ticket_detail', {'pk': 1}),
    ]

    print("Testing PSA Integration URL Configuration")
    print("=" * 60)

    passed = 0
    failed = 0

    for url_name, kwargs in urls_to_test:
        try:
            url = reverse(url_name, kwargs=kwargs)
            resolved = resolve(url)
            print(f"✓ {url_name:40} → {url}")
            passed += 1
        except Exception as e:
            print(f"✗ {url_name:40} → ERROR: {e}")
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("\n✓ All PSA integration URLs are configured correctly!")
        return True
    else:
        print(f"\n✗ {failed} URL(s) failed to resolve")
        return False

if __name__ == '__main__':
    success = test_psa_urls()
    sys.exit(0 if success else 1)
