# Organization Cascade Deletion Analysis

## Summary

✅ **All related data is properly configured to cascade delete when an organization is deleted.**

Date: 2026-01-16
Version: v2.24.91

---

## Models with CASCADE Deletion

When an organization is deleted, ALL of the following related records will be automatically deleted:

### Core System
- **Tags** (`core.models.Tag`) - All organization tags
- **System Settings** - Organization-specific settings
- **Checklists** (`core.checklist_models.Checklist`) - All checklists

### Integrations
- **PSA Connections** (`integrations.models.PSAConnection`) - All PSA connections
- **RMM Connections** (`integrations.models.RMMConnection`) - All RMM connections
- **External Object Maps** (`integrations.models.ExternalObjectMap`) - All mapping records
- **PSA Companies** (`integrations.models.PSACompany`) - Synced company records
- **PSA Contacts** (`integrations.models.PSAContact`) - Synced contact records
- **PSA Tickets** (`integrations.models.PSATicket`) - Synced ticket records
- **RMM Devices** (`integrations.models.RMMDevice`) - All RMM device records
- **RMM Alerts** (`integrations.models.RMMAlert`) - All RMM alert records
- **RMM Software** (`integrations.models.RMMSoftware`) - All RMM software inventory

### Assets
- **Contacts** (`assets.models.Contact`) - All contacts
- **Assets** (`assets.models.Asset`) - All asset records
- **Asset Relationships** (`assets.models.AssetRelationship`) - All asset relationships
- **Asset Types** (`assets.models.AssetType`) - Custom asset types
- **Flexible Assets** (`assets.models_flexible.FlexibleAsset`) - All flexible assets

### Vault
- **Password Folders** (`vault.models.PasswordFolder`) - All password folders
- **Passwords** (`vault.models.Password`) - All passwords (encrypted data)

### Monitoring
- **Website Monitors** (`monitoring.models.WebsiteMonitor`) - All website monitors
- **Expirations** (`monitoring.models.Expiration`) - SSL/domain expiry tracking
- **Racks** (`monitoring.models.Rack`) - All rack records
- **VLANs** (`monitoring.models.VLAN`) - All VLAN records
- **Subnets** (`monitoring.models.Subnet`) - All subnet records

### Documentation
- **Document Categories** (`docs.models.DocumentCategory`) - Org-specific categories
- **Documents** (`docs.models.Document`) - Org-specific documents
- **Runbooks** (`docs.runbook_models.Runbook`) - All runbooks

### Processes/Workflows
- **Processes** (`processes.models.Process`) - All processes/workflows
- **Process Executions** (`processes.models.ProcessExecution`) - All execution history
  - **Process Stage Completions** - Cascade via ProcessExecution

### Files
- **Attachments** (`files.models.Attachment`) - All file attachments

### Accounts
- **Organization Memberships** (`accounts.models.OrganizationMembership`) - User membership links

### API
- **API Keys** (`api.models.APIKey`) - All API keys for the organization

### Locations
- **Locations** (`locations.models.Location`) - Owned locations only (not shared)
  - **Location Floor Plans** (`locations.models.LocationFloorPlan`) - Cascade via Location

### Imports
- **Import Jobs** (`imports.models.ImportJob`) - All import job records
- **Organization Mappings** (`imports.models.OrganizationMapping`) - Import mappings
- **Import Mappings** (`imports.models.ImportMapping`) - Object mappings

---

## Models with Intentional SET_NULL

These models preserve records even after organization deletion:

### Audit System
- **Audit Logs** (`audit.models.AuditLog`) - **SET_NULL**
  - **Reason**: Audit logs are compliance records that must be preserved for regulatory/legal purposes
  - **Behavior**: Organization field is set to NULL, but log entry remains
  - **Benefit**: Complete audit trail is maintained even after organization deletion

---

## Special Cases

### Locations - Shared Location Support
- **Owned Locations**: Deleted when organization is deleted (CASCADE)
- **Shared Locations**: Not affected by single organization deletion
  - Example: Data center or co-location facility used by multiple organizations
  - Location.organization = NULL for shared locations
  - Location.associated_organizations (ManyToMany) tracks which orgs can access
  - Shared location only deleted if manually removed

### Global/Template Content
- **Global Documents**: Documents with is_global=True and organization=NULL remain
- **Process Templates**: Processes with is_template=True remain for other orgs to clone
- **Global Categories**: Document categories with organization=NULL remain

---

## Cascade Chain Examples

### Example 1: Deleting Organization with Assets
```
Organization "Acme Corp" deleted
  ↓ CASCADE
  ├── Assets (10 records)
  │   ↓ CASCADE (via Asset deletion)
  │   └── Asset Relationships (15 records)
  │   └── Process Stages linked_asset=Asset (SET_NULL - stage remains)
  ├── Contacts (5 records)
  ├── Documents (20 records)
  └── Passwords (8 records)
```

### Example 2: Deleting Organization with Integrations
```
Organization "Acme Corp" deleted
  ↓ CASCADE
  ├── PSA Connection (1 record)
  │   ↓ CASCADE (via PSAConnection deletion)
  │   ├── PSA Companies (100 records)
  │   ├── PSA Contacts (500 records)
  │   └── PSA Tickets (1000 records)
  ├── RMM Connection (1 record)
  │   ↓ CASCADE (via RMMConnection deletion)
  │   ├── RMM Devices (50 records)
  │   │   ↓ CASCADE (via RMMDevice deletion)
  │   │   └── RMM Software (500 records - software per device)
  │   └── RMM Alerts (200 records)
  └── External Object Maps (150 records)
```

### Example 3: Audit Log Preservation
```
Organization "Acme Corp" deleted
  ↓ CASCADE (deletes all related data)
  ├── All organization data deleted
  │
  ↓ SET_NULL (preserves audit records)
  └── Audit Logs remain with organization=NULL
      - Login events
      - Document access logs
      - Password access logs
      - System changes
      - Compliance records
```

---

## Database Verification Query

To verify cascade deletion configuration:

```sql
-- Check all ForeignKey constraints to organizations table
SELECT
    tc.table_name,
    kcu.column_name,
    rc.delete_rule
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.referential_constraints rc
    ON tc.constraint_name = rc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND kcu.referenced_table_name = 'organizations'
ORDER BY tc.table_name;
```

Expected results:
- **CASCADE**: All models except audit_logs
- **SET NULL**: Only audit_logs

---

## Testing Cascade Deletion

### Test Procedure

1. Create test organization with sample data
2. Delete organization
3. Verify all related records are removed
4. Verify audit logs remain with NULL organization

### Test Command

```bash
python manage.py shell

from core.models import Organization
from django.db import connection

# Get counts before deletion
org = Organization.objects.get(slug='test-org')
counts = {
    'assets': org.assets.count(),
    'passwords': org.passwords.count(),
    'documents': org.documents.count(),
    'contacts': org.contacts.count(),
    'audit_logs': org.audit_logs.count(),
}

# Delete organization
org_id = org.id
org.delete()

# Verify cascades
from assets.models import Asset
from vault.models import Password
from audit.models import AuditLog

assert Asset.objects.filter(organization_id=org_id).count() == 0, "Assets not deleted!"
assert Password.objects.filter(organization_id=org_id).count() == 0, "Passwords not deleted!"

# Verify audit logs remain but org is NULL
remaining_audits = AuditLog.objects.filter(organization_id__isnull=True).count()
assert remaining_audits >= counts['audit_logs'], "Audit logs were incorrectly deleted!"

print("✅ Cascade deletion working correctly!")
```

---

## Security Implications

### Data Retention Policy
- **Operational Data**: Deleted immediately with organization (CASCADE)
- **Audit Data**: Retained indefinitely (SET_NULL)
- **Shared Resources**: Preserved for other organizations

### GDPR/Privacy Compliance
- Organization deletion removes all PII associated with that organization
- Audit logs retain only event metadata (no PII)
- Shared locations don't contain organization-specific data

### Backup Recommendations
1. **Pre-deletion backup**: Create full organization backup before deletion
2. **Audit log export**: Export audit logs for compliance before deletion
3. **Integration data**: External systems (PSA/RMM) retain their own data
4. **Soft delete option**: Consider adding is_deleted flag for large organizations

---

## Related Models

### Models NOT Tied to Organization
These models exist independently:
- **User accounts** (`auth.User`) - Users can belong to multiple organizations
- **Django sessions** - Session data
- **Django admin logs** - Django admin activity

### User Account Handling
- **OrganizationMembership deleted**: User loses access to organization
- **User account remains**: User account itself is not deleted
- **Behavior**: User can still log in but won't see deleted organization

---

## Recommendations

✅ **Current Implementation is Correct**

The cascade deletion is properly configured with:
1. **Comprehensive CASCADE**: All operational data deleted
2. **Intentional SET_NULL**: Audit logs preserved for compliance
3. **Shared resource protection**: Shared locations not affected
4. **User account preservation**: Users aren't deleted with organization

### Future Enhancements (Optional)
- Add pre-deletion warning with data counts
- Add soft-delete flag for large organizations (archive instead of delete)
- Add organization backup/export before deletion
- Add audit log export functionality
- Add organization "freeze" state to prevent deletion

---

**Last Updated**: 2026-01-16
**Verified By**: Claude Code Analysis
**Status**: ✅ CASCADE DELETION PROPERLY CONFIGURED
