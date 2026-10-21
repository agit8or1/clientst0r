# Documentation & Knowledge Base

Create, organize, and share technical documentation, runbooks, and network diagrams — with WYSIWYG or Markdown editors and an AI writing assistant.

---

## Overview

| Feature | URL |
|---------|-----|
| Documents | `/docs/` |
| Templates | `/docs/templates/` |
| Knowledge Base | `/docs/kb/` |
| Diagrams | `/docs/diagrams/` |
| AI Assistant | `/docs/ai/assistant/` |

---

## Documents

Documents are rich-content pages scoped to your organization:

| Field | Description |
|-------|-------------|
| **Title** | Document name |
| **Content** | Written in WYSIWYG (Quill) or Markdown |
| **Category** | Organize into folders/categories |
| **Tags** | Free-form labels for search and filtering |
| **Visibility** | Organization-scoped or private |

### Editors

| Editor | Best For |
|--------|----------|
| **WYSIWYG (Quill)** | Formatted docs with images, tables, callouts |
| **Markdown** | Technical docs, runbooks, code snippets |

Switch between editors with the **Editor** selector at the top of the form. Content is preserved when switching.

### Uploading Documents

Upload existing files (PDF, DOCX, etc.) directly at `/docs/upload/`. Uploaded files are linked to your organization, and every download is checked against the document's permissions (only people who can view the document can download its file).

---

## Templates

**Templates** are reusable document skeletons — create a template once, then generate new documents from it instantly.

| Use Case | Example Template |
|----------|-----------------|
| **Runbooks** | "Network Outage Runbook" starter |
| **Client reports** | "Monthly IT Summary" |
| **Onboarding docs** | "New Employee IT Setup" |
| **Change requests** | "Change Request Form" |

Templates support the same WYSIWYG and Markdown editors as documents, and can include default tags and categories.

**Global templates** (shared across all organizations) can be edited or deleted only by MSP staff. Customer users with edit rights manage their own organization's templates.

---

## Knowledge Base

The **Knowledge Base** is a public-within-org article library for reference material:

| Feature | Details |
|---------|---------|
| **URL slugs** | Human-readable URLs (`/docs/kb/my-article/`) |
| **Categories** | Organize articles by topic |
| **Search** | Matches words in titles and bodies |
| **Versioning** | A version is saved on every edit; view, compare and restore versions (see [Document lifecycle](#document-lifecycle)) |
| **Global KB** | Superusers can publish articles visible across all organizations |

### Global Knowledge Base

Global KB articles are written by the MSP and are visible to **MSP staff** in every organization. Customer users don't see them on the staff pages, in the APIs or in the mobile app; articles marked client-visible appear in the customer portal instead. Only MSP staff whose role includes **Edit KB articles**, **Move KB articles** or **Manage KB categories** can change them; the same permissions on a customer's role don't apply to the global KB. Drafts and articles pending review are listed only for staff who can edit them. Useful for:
- Company-wide IT policies
- Standard operating procedures
- Product documentation

---

## Document Lifecycle

| Feature | Details |
|---------|---------|
| **Drafts and publishing** | Publishing needs the View/Publish documents permission for that organization (Publish KB articles for global articles). Without it, new documents, uploads and imports save as drafts. Drafts never appear in document lists, search, exports or the portal. See them at *Docs → Drafts* (`/docs/lifecycle/drafts/`) |
| **Approval** | Documents that require approval go through **Submit for review → Approve** |
| **Owner and review interval** | Set on the document form; the document page shows the owner and next review date, and owners get weekly review reminders |
| **Version history** | Every edit saves a version. Open *History* on a document to view any version, compare two, or restore one. Restores are audited and the replaced content is kept as a version |
| **Archive** | Archived documents are listed at *Docs → Archived* (`/docs/lifecycle/archived/`) and can be unarchived |
| **Template drift** | Documents created from a template remember the template version. Each template lists the documents that are behind it, with a diff of what changed (`/docs/templates/<id>/documents/`). Nothing is overwritten |
| **KB analytics** | MSP staff: *Docs → KB Analytics* (`/docs/lifecycle/analytics/`) shows most viewed, never viewed, past review date, and searches that found nothing. Only zero-result searches are logged (never vault searches), kept for 90 days |

---

## Documentation Readiness

*Docs → Documentation Readiness* (`/readiness/`) checks every customer against standards you
define for what must be documented.

| Feature | Details |
|---------|---------|
| **Standards** | Apply to every customer, every customer of a given type, or customers with assets of a given type. Requirements can cover documents (by tag, category or title), review freshness, owners, required asset fields, contacts with a given role, credential references (metadata only) and asset relationships (`/readiness/standards/`) |
| **Customer score** | Each customer gets a score, a plain explanation of every unmet requirement, a link to fix it, and an owner (`/readiness/customer/<id>/`) |
| **Repair queue** | Everything unmet across customers, in one list (`/readiness/repair/`) |
| **Exceptions** | Per-customer exceptions with a reason and optional expiry; audited |
| **Customer view** | Customer users with View documents see their own customer's page, read-only |
| **Broken relationships** | Links whose target no longer exists or belongs to another customer, with cleanup for staff (`/readiness/relationships/broken/`, or `python manage.py readiness_find_broken_relationships --delete`) |

`python manage.py readiness_seed_samples` adds a sample Microsoft 365 tenant documentation
standard to start from. It is not added automatically.

---

## Network Diagrams

Create interactive network topology diagrams using a drag-and-drop canvas:

| Feature | Details |
|---------|---------|
| **Nodes** | Servers, switches, routers, firewalls, workstations, etc. |
| **Connections** | Labeled links with cable type and speed |
| **Layers** | Physical and logical topology views |
| **Templates** | Start from predefined diagram templates |
| **Export** | PNG, SVG, or JSON |

Diagrams are saved per-organization and can be embedded in documents.

---

## AI Documentation Assistant

The built-in AI assistant helps you write and improve documentation:

| Feature | What It Does |
|---------|-------------|
| **Generate** | Create a document draft from a prompt |
| **Enhance** | Improve clarity, grammar, and completeness of existing content |
| **Validate** | Check a runbook for missing steps or gaps |

> **OPTIONAL AI.** These features are off until an administrator turns on `psa_ai_enabled` and configures a provider in *Settings → AI* (`/core/settings/ai/`): Anthropic, OpenAI, Moonshot, MiniMax, or a local Ollama model.

---

## Categories

Organize both documents and KB articles into hierarchical categories:

- Create at *Docs → Categories → New Category*
- Nest categories up to 3 levels deep
- Filter and browse documents by category
- Categories are organization-scoped

---

*Back to [User Guide](README.md)*
