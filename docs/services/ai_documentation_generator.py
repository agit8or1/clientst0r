"""
AI-powered documentation generation service with multi-LLM provider support.
Supports Anthropic Claude, Moonshot AI (Kimi), MiniMax, and OpenAI.
"""

from django.conf import settings
import json
from .llm_providers import get_llm_provider


class AIDocumentationGenerator:
    """Service for AI-powered documentation generation and enhancement."""

    def __init__(self):
        """Initialize the LLM provider based on settings."""
        # Get provider configuration from settings
        provider_name = getattr(settings, 'LLM_PROVIDER', 'anthropic')

        # Build provider-specific kwargs
        if provider_name == 'anthropic':
            api_key = settings.ANTHROPIC_API_KEY
            model = getattr(settings, 'CLAUDE_MODEL', 'claude-sonnet-4-5-20250929')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured. Please configure in Settings → AI.")
            provider_kwargs = {'api_key': api_key, 'model': model}

        elif provider_name == 'moonshot':
            api_key = getattr(settings, 'MOONSHOT_API_KEY', '')
            model = getattr(settings, 'MOONSHOT_MODEL', 'moonshot-v1-8k')
            if not api_key:
                raise ValueError("MOONSHOT_API_KEY not configured. Please configure in Settings → AI.")
            provider_kwargs = {'api_key': api_key, 'model': model}

        elif provider_name == 'minimax':
            api_key = getattr(settings, 'MINIMAX_API_KEY', '')
            group_id = getattr(settings, 'MINIMAX_GROUP_ID', '')
            model = getattr(settings, 'MINIMAX_MODEL', 'abab6.5-chat')
            if not api_key or not group_id:
                raise ValueError("MINIMAX_API_KEY and MINIMAX_GROUP_ID not configured. Please configure in Settings → AI.")
            provider_kwargs = {'api_key': api_key, 'group_id': group_id, 'model': model}

        elif provider_name == 'minimax_coding':
            api_key = getattr(settings, 'MINIMAX_CODING_API_KEY', '')
            model = getattr(settings, 'MINIMAX_CODING_MODEL', 'MiniMax-M2.5')
            if not api_key:
                raise ValueError("MINIMAX_CODING_API_KEY not configured. Please configure in Settings → AI.")
            provider_kwargs = {'api_key': api_key, 'model': model}

        elif provider_name == 'openai':
            api_key = getattr(settings, 'OPENAI_API_KEY', '')
            model = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
            if not api_key:
                raise ValueError("OPENAI_API_KEY not configured. Please configure in Settings → AI.")
            provider_kwargs = {'api_key': api_key, 'model': model}

        elif provider_name == 'ollama':
            base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434')
            model = getattr(settings, 'OLLAMA_MODEL', 'llama3.2')
            provider_kwargs = {'base_url': base_url, 'model': model}

        else:
            raise ValueError(f"Unknown LLM provider: {provider_name}")

        # Get the provider instance
        self.provider = get_llm_provider(provider_name, **provider_kwargs)
        if not self.provider:
            raise ValueError(f"Failed to initialize {provider_name} provider")

        self.provider_name = provider_name

    def generate_documentation(self, prompt, template_type=None, context=None, output_format='markdown'):
        """
        Generate documentation from a prompt using Claude AI.

        Args:
            prompt: User's description of what to document
            template_type: Optional template type (m365, ad, network, process, etc.)
            context: Optional additional context (existing data, config, etc.)
            output_format: Output format ('markdown' or 'html')

        Returns:
            dict: Generated documentation with title and content
        """
        # Build system prompt with guardrails
        system_prompt = self._build_system_prompt(template_type, output_format)

        # Build user prompt
        user_prompt = self._build_user_prompt(prompt, context, output_format)

        try:
            # Call LLM provider
            response = self.provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=4096
            )

            if not response['success']:
                return response

            # Parse response
            content = response['content']

            # Try to extract JSON if present
            result = self._parse_response(content)

            return {
                'success': True,
                'title': result.get('title', 'Generated Documentation'),
                'content': result.get('content', content),
                'metadata': result.get('metadata', {})
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def enhance_documentation(self, title, content, enhancement_type='grammar', output_format='markdown', custom_prompt=''):
        """
        Enhance existing documentation.

        Args:
            title: Document title
            content: Document content
            enhancement_type: Type of enhancement (grammar, expand, simplify, technical)
            output_format: Output format ('markdown' or 'html')

        Returns:
            dict: Enhanced documentation
        """
        enhancement_prompts = {
            'grammar': 'Improve grammar, spelling, and punctuation. Maintain the same structure and technical accuracy.',
            'expand': 'Expand the documentation with more details, examples, and best practices. Add missing sections.',
            'simplify': 'Simplify the language for better readability while maintaining technical accuracy.',
            'technical': 'Enhance with more technical details, specifications, and implementation notes.',
            'consistency': 'Improve consistency in terminology, formatting, and structure. Fix any inconsistencies.',
            'markdown_to_html': 'Convert this markdown content to well-formatted HTML using Bootstrap 5 classes for styling. Use cards, badges, alerts, styled tables, and Font Awesome icons to make it visually rich.',
        }

        if enhancement_type == 'custom' and custom_prompt:
            enhancement_instruction = custom_prompt
        else:
            enhancement_instruction = enhancement_prompts.get(enhancement_type, enhancement_prompts['grammar'])

        # Build format-specific instructions.
        # For markdown_to_html we want rich new styling; for all other HTML enhancements
        # we must PRESERVE the existing classes/styles — the AI should only touch the
        # text/content, not rebuild the visual structure from scratch.
        if output_format == 'html' and enhancement_type == 'markdown_to_html':
            format_instructions = """- Convert to clean, semantic HTML5
- Use Bootstrap 5 classes for styling (cards, badges, alerts, tables)
- Add color and visual hierarchy with appropriate classes
- Use icons (Font Awesome) where appropriate (e.g., <i class="fas fa-check text-success"></i>)
- Structure with proper sections using <div>, <section>, <article>
- Use styled code blocks: <pre><code class="language-bash">...</code></pre>
- Add callout boxes for important notes: <div class="alert alert-info">...</div>
- Use badges for labels: <span class="badge bg-primary">Important</span>
- Create styled tables: <table class="table table-striped table-hover">"""
        elif output_format == 'html':
            format_instructions = """- Output valid HTML5
- PRESERVE all existing CSS classes, inline styles, Bootstrap classes, and visual formatting exactly as they are
- Do NOT remove, replace, or simplify any existing class attributes or style attributes
- Only modify text content, wording, and structure — never the visual styling
- Use actual newline characters in the HTML source, never the literal string \\n"""
        else:
            format_instructions = "- Format using Markdown"

        system_prompt = f"""You are a technical documentation expert. Your task is to enhance existing documentation.

Guidelines:
- Preserve all technical accuracy
- Maintain the original intent and structure
- Use clear, professional language
- Follow documentation best practices
{format_instructions}
- Do not remove important information
- Add value without unnecessary verbosity
- Make it visually appealing and easy to scan"""

        if output_format == 'html':
            # For HTML, avoid JSON wrapping — HTML attributes contain unescaped quotes
            # that reliably break JSON parsing, causing the raw JSON blob to appear as
            # document content. Return the enhanced HTML directly instead.
            user_prompt = f"""Please enhance this documentation:

Title: {title}

Content:
{content}

Enhancement Type: {enhancement_instruction}

Return ONLY the enhanced HTML content. Do NOT wrap it in JSON. Do NOT use markdown.
Preserve all code blocks and technical content exactly.
Use real newline characters — never the literal two-character sequence backslash-n.
Start your response directly with an HTML tag."""
        else:
            user_prompt = f"""Please enhance this documentation:

Title: {title}

Content:
{content}

Enhancement Type: {enhancement_instruction}

Return the enhanced documentation in this JSON format:
{{
    "title": "enhanced title if needed",
    "content": "enhanced markdown content",
    "changes_made": ["list of key changes made"]
}}"""

        try:
            response = self.provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=8192
            )

            if not response['success']:
                return response

            content_text = response['content']

            if output_format == 'html':
                # AI returns raw HTML directly — no parsing needed
                return {
                    'success': True,
                    'title': title,
                    'content': content_text.strip(),
                    'changes_made': []
                }

            result = self._parse_response(content_text)

            return {
                'success': True,
                'title': result.get('title', title),
                'content': result.get('content', content_text),
                'changes_made': result.get('changes_made', [])
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def generate_asset_documentation(self, asset_data, template_type='server_blueprint', user_notes=''):
        """
        Generate AI documentation for an asset based on a template.

        Args:
            asset_data: dict of asset fields (name, type, hostname, ip, os, cpu, ram, etc.)
            template_type: one of server_blueprint, network_device, workstation, general, security
            user_notes: optional extra context provided by the user

        Returns:
            dict with success, content (HTML), title
        """
        templates = {
            'server_blueprint': {
                'title': 'Server Blueprint',
                'sections': [
                    'Overview — role and purpose of this server in the environment',
                    'Hardware Specifications — CPU, RAM, storage, form factor',
                    'Network Configuration — hostname, IP addresses, DNS, VLANs',
                    'Operating System — OS, version, patch level, key services running',
                    'Installed Software — list all software from installed_software field; include name and version for each',
                    'RMM / Management — remote management tools, agent status',
                    'Backup & Recovery — backup schedule, retention, restore procedure',
                    'Maintenance Windows — patching schedule, planned downtime',
                    'Dependencies — what relies on this server; what this server relies on',
                    'Access & Credentials — who has access (reference vault, do not include passwords)',
                    'Disaster Recovery — RTO/RPO targets, failover steps',
                    'Notes & Known Issues',
                ],
            },
            'network_device': {
                'title': 'Network Device Configuration',
                'sections': [
                    'Device Overview — role (core/distribution/access/edge)',
                    'Hardware — model, firmware version, port count',
                    'Physical Location — rack, floor, building',
                    'Management Access — management IP, protocols (SSH/HTTPS/SNMP)',
                    'Interface Summary — key interfaces, descriptions, speeds',
                    'VLAN Configuration — VLANs trunked/accessed on this device',
                    'Routing — static routes or routing protocols in use',
                    'Security — ACLs, port security, spanning tree settings',
                    'Monitoring & Alerting — SNMP community, syslog destination',
                    'Maintenance — firmware update procedure, config backup location',
                    'Notes & Known Issues',
                ],
            },
            'workstation': {
                'title': 'Workstation / Laptop Setup',
                'sections': [
                    'Device Overview — assigned user, department, purpose',
                    'Hardware — make, model, serial number',
                    'Operating System — OS version, build, last patched',
                    'Software — list all software from installed_software field; include name and version for each',
                    'Network — hostname, IP (DHCP/static), Wi-Fi/wired',
                    'Security — AV, EDR agent, disk encryption status',
                    'User Accounts — local admin, domain join status',
                    'Peripherals — monitors, docking stations, printers',
                    'Backup — OneDrive/backup client status',
                    'Support Notes — known issues, special config',
                ],
            },
            'general': {
                'title': 'Asset Documentation',
                'sections': [
                    'Overview — what this asset is and its role',
                    'Technical Specifications',
                    'Network / Connectivity',
                    'Configuration Details',
                    'Management & Access',
                    'Maintenance',
                    'Notes',
                ],
            },
            'security': {
                'title': 'Security & Compliance Record',
                'sections': [
                    'Asset Overview & Classification',
                    'Network Exposure — open ports, services, internet-facing',
                    'Firewall & ACL Rules',
                    'Authentication & Access Control',
                    'Patching & Vulnerability Status',
                    'Encryption — at-rest and in-transit',
                    'Logging & Monitoring',
                    'Compliance Notes — relevant frameworks (CIS, NIST, ISO)',
                    'Incident History',
                    'Review Schedule',
                ],
            },
        }

        tmpl = templates.get(template_type, templates['general'])
        sections_list = '\n'.join(f'  - {s}' for s in tmpl['sections'])

        # Build asset context string — handle multiline values with indented continuation
        asset_lines = []
        for key, val in asset_data.items():
            if val:
                val_str = str(val)
                if '\n' in val_str:
                    indented = val_str.replace('\n', '\n      ')
                    asset_lines.append(f'  {key}:\n      {indented}')
                else:
                    asset_lines.append(f'  {key}: {val_str}')
        asset_context = '\n'.join(asset_lines) if asset_lines else '  (no data recorded)'

        notes_section = f'\nAdditional context from engineer:\n{user_notes}\n' if user_notes else ''

        system_prompt = """You are a senior IT documentation engineer at an MSP.
Write professional, structured IT documentation using Bootstrap 5 HTML.

Rules:
- Output ONLY valid HTML5 — no JSON wrapper, no markdown, no preamble
- Use Bootstrap 5 classes: cards (card, card-header, card-body), tables (table table-sm table-striped), badges (badge bg-*), alerts (alert alert-)
- Use Font Awesome icons where appropriate (<i class="fas fa-..."></i>)
- For sections with no data, add a placeholder row in muted text so the engineer knows to fill it in
- Do NOT invent specific IP addresses, passwords, or credentials — use [PLACEHOLDER] for unknown values
- Keep it practical: an on-call engineer should be able to use this document to manage the device
- Use real newline characters, never the literal \\n sequence
- Start your response directly with an HTML tag"""

        user_prompt = f"""Generate a {tmpl['title']} document for the following asset.

Asset Data:
{asset_context}
{notes_section}
Document Sections to include:
{sections_list}

For each section:
- Use the asset data above to fill in what is known
- For unknown fields, add a styled placeholder row like: <tr><td>Field Name</td><td class="text-muted fst-italic">[Not recorded — please update]</td></tr>
- Do not skip any section

Return ONLY the HTML content starting with a <div> tag."""

        try:
            response = self.provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=8192
            )

            if not response['success']:
                return response

            doc_title = f'{asset_data.get("name", "Asset")} — {tmpl["title"]}'
            return {
                'success': True,
                'title': doc_title,
                'content': response['content'].strip(),
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    # Sentinel that separates the reformatted document from the gap analysis in
    # review_imported_document's single-call output. An HTML comment so that if
    # it ever leaks into the body, bleach strips it on render.
    REVIEW_GAP_MARKER = '<!--GAP-ANALYSIS-->'

    # Documentation standards the user can target on import. Each maps to extra
    # guidance appended to the review system prompt so the reformatted output
    # matches the expected shape for that kind of document.
    REVIEW_STANDARDS = {
        'general': 'a general MSP IT documentation article — clear overview, then logically grouped detail sections.',
        'process': 'a Standard Operating Procedure (SOP) — purpose/scope, prerequisites, numbered step-by-step instructions, validation, and rollback.',
        'runbook': 'a troubleshooting runbook — problem statement, prerequisites, resolution steps with expected outcomes, and escalation.',
        'network': 'network infrastructure documentation — topology, IP/VLAN scheme, device configs, firewall/security, and change management.',
        'security': 'a security & compliance record — scope/classification, controls, access, patching status, and relevant frameworks.',
        'm365': 'Microsoft 365 / Entra ID documentation — prerequisites (licenses/roles), sync considerations, and security/compliance notes.',
        'ad': 'Active Directory documentation — GPO/OU structure, replication, security groups, and backup/recovery.',
    }

    def review_imported_document(self, title, content, standard='general', output_format='html'):
        """
        Review an imported/extracted document in a single LLM call: reformat it
        to a ClientSt0r documentation standard AND identify gaps for improvement.

        Issue #140. Returns both the cleaned document and a list of gap notes so
        the importer can save the improved body and surface the gaps to the user.

        Args:
            title: Document title (usually derived from the filename).
            content: The raw extracted text of the imported document.
            standard: Key from REVIEW_STANDARDS to target.
            output_format: 'html' (default, Bootstrap 5) or 'markdown'.

        Returns:
            dict: {'success', 'title', 'content', 'gaps': [str, ...]} or
                  {'success': False, 'error': ...}
        """
        standard_desc = self.REVIEW_STANDARDS.get(standard, self.REVIEW_STANDARDS['general'])

        if output_format == 'html':
            format_guide = """- Output clean, semantic HTML5 styled with Bootstrap 5 classes
- Use headings (<h2>/<h3>), styled tables (<table class="table table-sm table-striped">),
  callouts (<div class="alert alert-info">), and badges (<span class="badge bg-primary">)
- Use real newline characters, never the literal two-character sequence backslash-n
- Start the document directly with an HTML tag"""
        else:
            format_guide = '- Output clean Markdown with proper headings, lists, and tables'

        system_prompt = f"""You are a senior IT documentation engineer at an MSP.
You are reviewing a document that was just imported from an external file (Word/PDF).
Your job has two parts.

PART 1 — Reformat the document to match this standard: {standard_desc}
- Preserve ALL technical content, facts, names, IP addresses, commands, and steps exactly
- Do NOT invent details. Where the source is missing information, leave a clearly
  marked placeholder like [PLACEHOLDER — to confirm] rather than guessing
- Fix structure, headings, grammar, and formatting only
{format_guide}

PART 2 — Identify gaps for improvement
- List concrete missing sections, unclear steps, stale/ambiguous content, and
  anything that should be added for this document to meet the standard above

OUTPUT CONTRACT (follow exactly):
1. First output ONLY the reformatted document (no preamble, no code fences).
2. Then output this exact marker on its own line: {self.REVIEW_GAP_MARKER}
3. Then output a Markdown bullet list (one "- " per line) of the gaps you found.
   If there are no meaningful gaps, output the single line: - No significant gaps found."""

        user_prompt = f"""Title: {title}

Imported document content:
{content}

Reformat it and then list the gaps, following the output contract exactly."""

        try:
            response = self.provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=8192,
            )

            if not response['success']:
                return response

            text = (response['content'] or '').strip()

            # Split the reformatted body from the gap analysis on the marker.
            if self.REVIEW_GAP_MARKER in text:
                body_part, gap_part = text.split(self.REVIEW_GAP_MARKER, 1)
            else:
                body_part, gap_part = text, ''

            body_part = body_part.strip()
            # Strip any stray code fences the model may have wrapped the doc in.
            if body_part.startswith('```'):
                lines = body_part.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                body_part = '\n'.join(lines).strip()

            gaps = []
            for line in gap_part.split('\n'):
                line = line.strip()
                # Accept "-", "*", or "•" bullet prefixes.
                if line[:1] in ('-', '*', '•'):
                    line = line[1:].strip()
                    if line:
                        gaps.append(line)

            return {
                'success': True,
                'title': title,
                'content': body_part,
                'gaps': gaps,
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    def validate_documentation(self, content):
        """
        Validate documentation for consistency, completeness, and quality.

        Args:
            content: Documentation content to validate

        Returns:
            dict: Validation results with suggestions
        """
        system_prompt = """You are a technical documentation quality assurance expert.
Review documentation and provide validation feedback.

Check for:
- Completeness (missing sections, incomplete information)
- Consistency (terminology, formatting, structure)
- Clarity (ambiguous statements, unclear instructions)
- Technical accuracy (logical errors, missing steps)
- Best practices (security considerations, error handling)"""

        user_prompt = f"""Please review this documentation and provide validation feedback:

{content}

Return your analysis in JSON format:
{{
    "score": "1-10 quality score",
    "issues": [
        {{"severity": "high/medium/low", "type": "issue type", "description": "issue description", "suggestion": "how to fix"}}
    ],
    "strengths": ["what's good about this documentation"],
    "improvements": ["suggested improvements"]
}}"""

        try:
            response = self.provider.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=4096
            )

            if not response['success']:
                return response

            content_text = response['content']
            result = self._parse_response(content_text)

            return {
                'success': True,
                'validation': result
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def _build_system_prompt(self, template_type, output_format='markdown'):
        """Build system prompt with guardrails based on template type."""

        # Format-specific instructions
        if output_format == 'html':
            format_guide = """- Format using clean, semantic HTML5
- Use Bootstrap 5 classes for styling (cards, badges, alerts, tables)
- Add color and visual hierarchy with appropriate classes
- Use icons (Font Awesome) where appropriate
- Structure with proper sections: <section>, <article>, <header>
- Use styled code blocks: <pre><code class="language-python">...</code></pre>
- Add callout boxes: <div class="alert alert-info">...</div>
- Use badges: <span class="badge bg-primary">Important</span>
- Create styled tables: <table class="table table-striped">"""
        else:
            format_guide = "- Format using Markdown"

        base_prompt = f"""You are an expert technical documentation writer. Generate clear, comprehensive, and well-structured documentation.

General Guidelines:
- Use professional, clear language
- Structure content with proper headings and sections
- Include examples and use cases where appropriate
- Follow documentation best practices
{format_guide}
- Include security considerations and best practices
- Add troubleshooting sections where relevant
- Consider different skill levels (provide both quick start and detailed sections)
- Make it visually appealing and easy to scan"""

        template_prompts = {
            'm365': """
Microsoft 365 / Entra ID Specific Guidelines:
- Include prerequisites (licenses, roles, permissions)
- Document Azure AD/Entra ID sync considerations
- Cover hybrid scenarios (on-prem + cloud)
- Include PowerShell commands where applicable
- Document security and compliance considerations
- Include backup and recovery procedures
- Note sync delays and propagation times
- Cover conditional access policies
- Document MFA requirements""",

            'ad': """
Active Directory Specific Guidelines:
- Document Group Policy requirements
- Include OU structure considerations
- Cover replication and domain controller placement
- Document DNS and network requirements
- Include security group memberships
- Cover delegation and RBAC
- Document backup and recovery procedures
- Include monitoring and maintenance tasks""",

            'network': """
Network Documentation Guidelines:
- Include network diagrams
- Document IP addressing schemes and VLANs
- Cover routing and switching configurations
- Include firewall rules and security policies
- Document VPN and remote access
- Cover monitoring and alerting
- Include disaster recovery procedures
- Document change management procedures""",

            'process': """
Process Documentation Guidelines:
- Start with purpose and scope
- List prerequisites and requirements
- Provide step-by-step instructions
- Include decision points and alternatives
- Add screenshots or diagrams where helpful
- Cover error handling and troubleshooting
- Include success criteria and validation
- Document rollback procedures""",

            'runbook': """
Runbook Guidelines:
- Clear problem statement
- Prerequisites and access requirements
- Step-by-step resolution procedures
- Expected outcomes at each step
- Troubleshooting section
- Escalation procedures
- Related runbooks and documentation
- Change log and version history"""
        }

        if template_type and template_type in template_prompts:
            return base_prompt + "\n" + template_prompts[template_type]

        return base_prompt

    def _build_user_prompt(self, prompt, context, output_format='markdown'):
        """Build user prompt with context."""
        user_prompt = f"Please create comprehensive technical documentation for the following:\n\n{prompt}"

        if context:
            user_prompt += f"\n\nAdditional Context:\n{context}"

        if output_format == 'html':
            user_prompt += """\n\nPlease provide:
1. A clear, descriptive title for this documentation
2. Well-structured HTML content with proper styling

Format your response like this:
TITLE: [Your document title here]

[Your HTML content starts here immediately after the title]

Use proper HTML formatting with Bootstrap 5 classes:
- Use <h1>, <h2>, etc. for headings
- Use <pre><code class="language-xxx"> for code blocks
- Use <div class="alert alert-info"> for callouts
- Use <span class="badge bg-primary"> for labels
- Use <table class="table table-striped"> for tables
- Add <i class="fas fa-icon-name"> for icons where appropriate

Do NOT wrap the response in JSON or code blocks. Provide clean, ready-to-use HTML content."""
        else:
            user_prompt += """\n\nPlease provide:
1. A clear, descriptive title for this documentation
2. Well-structured markdown content with proper headings, sections, and formatting

Format your response like this:
TITLE: [Your document title here]

[Your markdown content starts here immediately after the title]

Use proper markdown formatting:
- Use # for main headings, ## for subheadings, etc.
- Use code blocks with ``` for commands and configuration
- Use bullet points and numbered lists where appropriate
- Include tables where relevant
- Add bold and italic formatting for emphasis

Do NOT wrap the response in JSON or code blocks. Provide clean, ready-to-use markdown content."""

        return user_prompt

    def _parse_response(self, content):
        """Parse Claude API response, extracting title and content or JSON."""
        import re

        # Strategy 1: Try to parse new TITLE: format (clean markdown)
        if 'TITLE:' in content:
            lines = content.split('\n')
            title = None
            content_lines = []
            title_found = False

            for line in lines:
                if line.startswith('TITLE:') and not title_found:
                    title = line.replace('TITLE:', '').strip()
                    title_found = True
                elif title_found and line.strip():  # Skip empty lines after title
                    content_lines.append(line)
                elif title_found:
                    content_lines.append(line)  # Keep empty lines in content

            markdown_content = '\n'.join(content_lines).strip()
            return {
                'title': title or 'Generated Documentation',
                'content': markdown_content,
                'metadata': {}
            }

        # Strategy 2: Try to find JSON in response (for backward compatibility)
        try:
            # Look for JSON in code fence (```json ... ```)
            if '```json' in content.lower():
                match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL | re.IGNORECASE)
                if match:
                    json_str = match.group(1).strip()
                    parsed = json.loads(json_str)
                    # Validate it has expected structure
                    if isinstance(parsed, dict):
                        return parsed

            # Look for JSON in plain code fence (``` ... ```)
            if '```' in content:
                match = re.search(r'```\s*(.*?)\s*```', content, re.DOTALL)
                if match:
                    json_str = match.group(1).strip()
                    # Skip if it starts with a language identifier
                    if not json_str.split('\n')[0].strip().isalpha():
                        try:
                            parsed = json.loads(json_str)
                            if isinstance(parsed, dict):
                                return parsed
                        except Exception:
                            pass

            # Try to extract JSON directly (find first { to last })
            if '{' in content and '}' in content:
                start = content.find('{')
                end = content.rfind('}') + 1
                json_str = content[start:end]
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    return parsed

        except json.JSONDecodeError:
            # JSON parsing failed, content is not valid JSON
            pass
        except Exception:
            # Other errors, fall through to return raw content
            pass

        # No valid format found - return raw content as markdown
        # Clean up any residual code fences or JSON markers
        cleaned_content = content
        cleaned_content = re.sub(r'```json\s*', '', cleaned_content)
        cleaned_content = re.sub(r'```\s*$', '', cleaned_content)
        cleaned_content = cleaned_content.strip()

        return {'content': cleaned_content}


# Predefined templates for common documentation scenarios
DOCUMENTATION_TEMPLATES = {
    'm365': {
        'name': 'Microsoft 365 / Entra ID',
        'description': 'Document M365, Entra ID, user provisioning, and sync processes',
        'icon': 'fa-cloud',
        'example_prompt': 'Document user creation from on-premises Active Directory with M365 sync via Entra ID, including caveats and best practices'
    },
    'ad': {
        'name': 'Active Directory',
        'description': 'Document Active Directory setup, management, and policies',
        'icon': 'fa-sitemap',
        'example_prompt': 'Document Active Directory user account creation, group membership management, and password policies'
    },
    'network': {
        'name': 'Network Infrastructure',
        'description': 'Document network topology, configurations, and security',
        'icon': 'fa-network-wired',
        'example_prompt': 'Document VLAN configuration, firewall rules, and network segmentation strategy'
    },
    'process': {
        'name': 'Business Process',
        'description': 'Document workflows, procedures, and standard operating procedures',
        'icon': 'fa-tasks',
        'example_prompt': 'Document the employee onboarding process including account creation, access provisioning, and equipment setup'
    },
    'runbook': {
        'name': 'Troubleshooting Runbook',
        'description': 'Document troubleshooting procedures and incident response',
        'icon': 'fa-book-medical',
        'example_prompt': 'Document troubleshooting steps for VPN connection failures including common causes and resolutions'
    },
    'security': {
        'name': 'Security Policy',
        'description': 'Document security policies, procedures, and compliance',
        'icon': 'fa-shield-alt',
        'example_prompt': 'Document password policy requirements including complexity, expiration, and MFA enforcement'
    },
    'backup': {
        'name': 'Backup & Recovery',
        'description': 'Document backup procedures and disaster recovery plans',
        'icon': 'fa-hdd',
        'example_prompt': 'Document database backup and recovery procedures including RPO, RTO, and testing schedule'
    },
    'application': {
        'name': 'Application Setup',
        'description': 'Document application installation, configuration, and maintenance',
        'icon': 'fa-cog',
        'example_prompt': 'Document the installation and configuration of our CRM system including prerequisites and setup steps'
    }
}
