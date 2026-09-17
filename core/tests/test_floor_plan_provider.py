"""Floor-plan generation follows the configured LLM provider.

`AIFloorPlanGenerator.__init__` built `anthropic.Anthropic(api_key=
settings.ANTHROPIC_API_KEY)` and `_get_ai_design` called that client directly,
so an install running Ollama for data residency still sent its building briefs
— dimensions, headcount, department structure, security requirements — to a
third party. The view in front of it also checked `ANTHROPIC_API_KEY`
specifically, telling an Ollama install to add an Anthropic key for a feature
that does not need one.

This was the last AI surface constructing its own provider client; receipt OCR
was the other (v3.17.575).
"""
import ast
import pathlib
from unittest import mock

from django.test import TestCase

from locations.services.ai_floor_plan_generator import AIFloorPlanGenerator


DESIGN_JSON = (
    'Here is your plan: {"rooms": [{"name": "Reception", "type": "reception", '
    '"x": 5, "y": 5, "width": 20, "height": 15, "notes": ""}], '
    '"doors": [], "network": [], "design_notes": "ok"}'
)


class FloorPlanUsesConfiguredProviderTests(TestCase):

    def test_it_asks_the_configured_provider(self):
        provider = mock.Mock()
        provider.generate.return_value = {'success': True, 'content': DESIGN_JSON}
        gen = AIFloorPlanGenerator(provider=provider)

        design = gen._get_ai_design('design me an office')

        provider.generate.assert_called_once()
        self.assertEqual(len(design['rooms']), 1)
        self.assertEqual(design['rooms'][0]['name'], 'Reception')

    def test_the_brief_is_passed_as_the_user_prompt(self):
        provider = mock.Mock()
        provider.generate.return_value = {'success': True, 'content': DESIGN_JSON}
        AIFloorPlanGenerator(provider=provider)._get_ai_design('BRIEF-MARKER')

        args, kwargs = provider.generate.call_args
        self.assertIn('BRIEF-MARKER', args[1])
        self.assertIn('JSON', args[0])  # system prompt asks for JSON

    def test_no_configured_provider_falls_back_rather_than_raising(self):
        """The fallback layout predates this change and is kept."""
        gen = AIFloorPlanGenerator(provider=None)
        design = gen._get_ai_design('anything')
        self.assertEqual(design['design_notes'], 'Basic fallback layout')

    def test_a_provider_failure_falls_back(self):
        provider = mock.Mock()
        provider.generate.return_value = {'success': False, 'error': 'model down'}
        design = AIFloorPlanGenerator(provider=provider)._get_ai_design('x')
        self.assertEqual(design['design_notes'], 'Basic fallback layout')

    def test_unparseable_output_falls_back(self):
        provider = mock.Mock()
        provider.generate.return_value = {'success': True, 'content': 'no json here'}
        design = AIFloorPlanGenerator(provider=provider)._get_ai_design('x')
        self.assertEqual(design['design_notes'], 'Basic fallback layout')

    def test_the_module_no_longer_builds_its_own_anthropic_client(self):
        """Checked against the parsed module so the docstring's history
        explaining the old client does not trip the assertion."""
        src = pathlib.Path(__file__).resolve().parents[2] / (
            'locations/services/ai_floor_plan_generator.py')
        tree = ast.parse(src.read_text())

        attrs = {f'{n.value.id}.{n.attr}' for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        self.assertNotIn('anthropic.Anthropic', attrs)
        self.assertNotIn('settings.ANTHROPIC_API_KEY', attrs)
        self.assertNotIn('settings.CLAUDE_MODEL', attrs)

        imported = {a.name for n in ast.walk(tree)
                    if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn('anthropic', imported)

    def test_no_ai_surface_still_hardcodes_a_provider_client(self):
        """
        The sweep this and v3.17.575 complete. If a new feature constructs its
        own Anthropic client instead of going through the provider layer, this
        is where it shows up.
        """
        root = pathlib.Path(__file__).resolve().parents[2]
        allowed = {
            # The provider layer itself.
            'docs/services/llm_providers.py',
            # Validates an Anthropic API key typed into Settings, so it has to
            # talk to Anthropic specifically — it is not an AI feature routing
            # user data.
            'core/services/api_key_validator.py',
        }
        offenders = []
        for path in root.rglob('*.py'):
            rel = str(path.relative_to(root))
            if rel.startswith(('venv/', '.dev-worktree/')) or '/migrations/' in rel:
                continue
            if rel in allowed or '/tests' in rel or rel.startswith('core/tests'):
                continue
            try:
                tree = ast.parse(path.read_text(errors='ignore'))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and f'{n.value.id}.{n.attr}' == 'anthropic.Anthropic'):
                    offenders.append(rel)
        self.assertEqual(sorted(set(offenders)), [])
