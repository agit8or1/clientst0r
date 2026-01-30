"""
AI-powered documentation generation service using Claude API.
Supports generating documentation from prompts, enhancing existing content,
and using predefined templates with guardrails.
"""

import anthropic
from django.conf import settings
import json


class AIDocumentationGenerator:
    """Service for AI-powered documentation generation and enhancement."""

    def __init__(self):
        """Initialize the Claude API client."""
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured. Please configure in Settings → AI.")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = settings.CLAUDE_MODEL

    def generate_documentation(self, prompt, template_type=None, context=None):
        """
        Generate documentation from a prompt using Claude AI.

        Args:
            prompt: User's description of what to document
            template_type: Optional template type (m365, ad, network, process, etc.)
            context: Optional additional context (existing data, config, etc.)

        Returns:
            dict: Generated documentation with title and content
        """
        # Build system prompt with guardrails
        system_prompt = self._build_system_prompt(template_type)

        # Build user prompt
        user_prompt = self._build_user_prompt(prompt, context)

        try:
            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Parse response
            content = response.content[0].text

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

    def enhance_documentation(self, title, content, enhancement_type='grammar'):
        """
        Enhance existing documentation.

        Args:
            title: Document title
            content: Document content
            enhancement_type: Type of enhancement (grammar, expand, simplify, technical)

        Returns:
            dict: Enhanced documentation
        """
        enhancement_prompts = {
            'grammar': 'Improve grammar, spelling, and punctuation. Maintain the same structure and technical accuracy.',
            'expand': 'Expand the documentation with more details, examples, and best practices. Add missing sections.',
            'simplify': 'Simplify the language for better readability while maintaining technical accuracy.',
            'technical': 'Enhance with more technical details, specifications, and implementation notes.',
            'consistency': 'Improve consistency in terminology, formatting, and structure. Fix any inconsistencies.'
        }

        enhancement_instruction = enhancement_prompts.get(enhancement_type, enhancement_prompts['grammar'])

        system_prompt = """You are a technical documentation expert. Your task is to enhance existing documentation.

Guidelines:
- Preserve all technical accuracy
- Maintain the original intent and structure
- Use clear, professional language
- Follow documentation best practices
- Format using Markdown
- Do not remove important information
- Add value without unnecessary verbosity"""

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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            content_text = response.content[0].text
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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            content_text = response.content[0].text
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

    def _build_system_prompt(self, template_type):
        """Build system prompt with guardrails based on template type."""
        base_prompt = """You are an expert technical documentation writer. Generate clear, comprehensive, and well-structured documentation.

General Guidelines:
- Use professional, clear language
- Structure content with proper headings and sections
- Include examples and use cases where appropriate
- Follow documentation best practices
- Format using Markdown
- Include security considerations and best practices
- Add troubleshooting sections where relevant
- Consider different skill levels (provide both quick start and detailed sections)"""

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

    def _build_user_prompt(self, prompt, context):
        """Build user prompt with context."""
        user_prompt = f"Please create comprehensive technical documentation for the following:\n\n{prompt}"

        if context:
            user_prompt += f"\n\nAdditional Context:\n{context}"

        user_prompt += """\n\nReturn the documentation in JSON format:
{
    "title": "documentation title",
    "content": "markdown formatted documentation content",
    "metadata": {
        "tags": ["relevant", "tags"],
        "category": "suggested category",
        "difficulty": "beginner/intermediate/advanced"
    }
}"""

        return user_prompt

    def _parse_response(self, content):
        """Parse Claude API response, extracting JSON if present."""
        # Try to find JSON in response
        try:
            # Look for JSON block
            if '```json' in content:
                start = content.find('```json') + 7
                end = content.find('```', start)
                json_str = content[start:end].strip()
                return json.loads(json_str)
            elif '{' in content and '}' in content:
                # Try to extract JSON directly
                start = content.find('{')
                end = content.rfind('}') + 1
                json_str = content[start:end]
                return json.loads(json_str)
        except:
            pass

        # Return as plain content if no JSON found
        return {'content': content}


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
