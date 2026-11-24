"""
Multi-LLM Provider Support for Clientst0r
Supports Anthropic Claude, Moonshot AI (Kimi), MiniMax, and OpenAI
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import requests
import json

# Ceiling for a single LLM HTTP call. Deliberately below the gunicorn worker
# --timeout (300s) so a slow/stuck model raises a caught Timeout and we return
# a JSON error, instead of the worker being killed and the browser receiving an
# HTML 500 page ("Server returned HTML instead of JSON" — issue #138).
AI_HTTP_TIMEOUT = 280


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        """
        Generate content using the LLM.

        Args:
            system_prompt: System-level instructions
            user_prompt: User's actual prompt
            max_tokens: Maximum tokens to generate

        Returns:
            dict with 'success', 'content', and optionally 'error'
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the current model name."""
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Test the API connection.

        Returns:
            dict with 'success' and 'message' or 'error'
        """
        pass

    def extract_receipt_fields(
        self,
        image_bytes: bytes,
        image_mime: str = 'image/jpeg',
        hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        v3.17.471 — vision extraction of receipt fields.

        Default impl returns success=False so providers that don't
        support vision (Moonshot text, MiniMax text) degrade
        gracefully to the manual entry path on the mobile side.

        Returns:
            {
              'success': True,
              'extracted': {
                'vendor': str|None,
                'amount_total': float|None,
                'amount_tax': float|None,
                'date': 'YYYY-MM-DD'|None,
                'gallons': float|None,
                'cost_per_gallon': float|None,
                'odometer': int|None,
                'category_hint': str|None,
                'line_items': [str, ...],
                'raw_text': str
              }
            }
            or
            {'success': False, 'error': '...', 'raw': '...optional model output...'}
        """
        return {
            'success': False,
            'error': f'{type(self).__name__} does not implement vision extraction.',
        }


# Shared system prompt + JSON schema used by every vision-capable
# implementation below. Keeping them at module scope so they're
# trivially editable when a model gets confused by the wording.
_RECEIPT_SYSTEM_PROMPT = (
    "You are a receipt-extraction service. Look at the image and respond with "
    "ONLY a single JSON object — no preamble, no markdown fences, no commentary. "
    "Use null for any field you cannot read."
)

_RECEIPT_USER_PROMPT = (
    'Extract fields from this receipt. Respond with ONLY this JSON object:\n'
    '{\n'
    '  "vendor": string or null,           // store / shop name on the receipt\n'
    '  "amount_total": number or null,      // total paid, in dollars\n'
    '  "amount_tax": number or null,        // tax portion\n'
    '  "date": "YYYY-MM-DD" or null,        // receipt date, ISO format\n'
    '  "gallons": number or null,           // only for fuel receipts\n'
    '  "cost_per_gallon": number or null,   // only for fuel receipts\n'
    '  "odometer": integer or null,         // mileage if visible on receipt\n'
    '  "category_hint": "fuel"|"maintenance"|"repair"|"insurance"|"registration"|"toll"|"cleaning"|"inspection"|"other" or null,\n'
    '  "line_items": [string, ...] or [],   // brief list of items / services\n'
    '  "raw_text": string                    // full visible text\n'
    '}\n'
    'If the receipt is not legible or not actually a receipt, return all fields as null and raw_text as best-effort.'
)


def _parse_receipt_json(text: str) -> Dict[str, Any]:
    """
    Parse an LLM's JSON output. Tolerates ```json fences, leading/trailing
    whitespace, and small junk before/after the JSON object.
    """
    text = (text or '').strip()
    # Strip markdown fences if model added them
    if text.startswith('```'):
        # Drop the first line ```json (or whatever) and the trailing ```
        lines = text.split('\n')
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        text = '\n'.join(lines).strip()
    # Find the first `{` and last `}` and slice — handles "Here's the JSON: {...}"
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        return {'success': True, 'extracted': json.loads(text)}
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'Model returned non-JSON: {e}',
            'raw': text[:500],
        }


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-5-20250929'):
        self.api_key = api_key
        self.model = model

        # Import anthropic only when this provider is used.
        # Explicit timeout (below the gunicorn worker --timeout) so a stuck
        # request surfaces as a caught error instead of a killed worker (#138).
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=float(AI_HTTP_TIMEOUT))

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Extract text from response, handling different block types (text, thinking, etc.)
            content_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    content_text += block.text
                elif hasattr(block, 'thinking'):
                    # Skip thinking blocks, only use text blocks for output
                    continue

            return {
                'success': True,
                'content': content_text
            }
        except Exception as e:
            # Enhanced error handling for better diagnostics
            error_msg = str(e)
            # Check if it's an API error with status code
            if hasattr(e, 'status_code'):
                error_msg = f"API Error {e.status_code}: {error_msg}"
            return {
                'success': False,
                'error': error_msg
            }

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            # Simple test with minimal tokens
            response = self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Say 'ok'"}
                ]
            )
            return {
                'success': True,
                'message': f'Connected to {self.model} successfully!'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def extract_receipt_fields(self, image_bytes, image_mime='image/jpeg', hint=None):
        """v3.17.471 — Anthropic multimodal vision. All Claude 3+ models support it."""
        import base64
        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        user_blocks = [
            {
                'type': 'image',
                'source': {'type': 'base64', 'media_type': image_mime, 'data': b64},
            },
            {'type': 'text', 'text': (
                _RECEIPT_USER_PROMPT
                + (f'\n\nUser-supplied hint: this is a {hint} receipt.' if hint else '')
            )},
        ]
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=_RECEIPT_SYSTEM_PROMPT,
                messages=[{'role': 'user', 'content': user_blocks}],
            )
            text = ''.join(b.text for b in response.content if hasattr(b, 'text'))
            return _parse_receipt_json(text)
        except Exception as exc:
            error_msg = str(exc)
            if hasattr(exc, 'status_code'):
                error_msg = f'API Error {exc.status_code}: {error_msg}'
            return {'success': False, 'error': error_msg}


class MiniMaxCodingProvider(LLMProvider):
    """MiniMax Coding Plan (M2.5) provider - uses Anthropic-compatible API."""

    def __init__(self, api_key: str, model: str = 'MiniMax-M2.5'):
        self.api_key = api_key
        self.model = model

        # MiniMax Coding Plan uses Anthropic-compatible API
        # Base URL: https://api.minimax.io/anthropic
        import anthropic
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url='https://api.minimax.io/anthropic',
            timeout=float(AI_HTTP_TIMEOUT),  # below gunicorn worker --timeout (#138)
        )

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Extract text from response, handling different block types
            content_text = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    content_text += block.text
                elif hasattr(block, 'thinking'):
                    # Skip thinking blocks, only use text blocks
                    continue

            return {
                'success': True,
                'content': content_text
            }
        except Exception as e:
            # Enhanced error handling for better diagnostics
            error_msg = str(e)
            # Check if it's an API error with status code
            if hasattr(e, 'status_code'):
                error_msg = f"API Error {e.status_code}: {error_msg}"
            # Check if it's a JSON parsing error (HTML response)
            if "Unexpected token" in error_msg or "not valid JSON" in error_msg:
                error_msg = f"MiniMax API returned HTML instead of JSON - likely authentication or API error. Check API key and model name. Original error: {error_msg}"
            return {
                'success': False,
                'error': error_msg
            }

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            # Simple test with minimal tokens
            response = self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[
                    {"role": "user", "content": "Say 'ok'"}
                ]
            )
            # Just check if we got a response (don't need to extract text for test)
            return {
                'success': True,
                'message': f'Connected to MiniMax {self.model} successfully!'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class MoonshotProvider(LLMProvider):
    """Moonshot AI (Kimi) provider."""

    def __init__(self, api_key: str, model: str = 'moonshot-v1-8k'):
        self.api_key = api_key
        self.model = model
        self.base_url = 'https://api.moonshot.cn/v1'

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'max_tokens': max_tokens,
                'temperature': 0.7
            }

            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'content': result['choices'][0]['message']['content']
                }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': '测试'}
                ],
                'max_tokens': 10
            }

            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                return {
                    'success': True,
                    'message': f'Connected to Moonshot {self.model} successfully!'
                }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class MiniMaxProvider(LLMProvider):
    """MiniMax provider."""

    def __init__(self, api_key: str, group_id: str, model: str = 'abab6.5-chat'):
        self.api_key = api_key
        self.group_id = group_id
        self.model = model
        self.base_url = 'https://api.minimax.chat/v1'

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            # MiniMax uses a different message format
            data = {
                'model': self.model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'tokens_to_generate': max_tokens,
                'temperature': 0.7
            }

            response = requests.post(
                f'{self.base_url}/text/chatcompletion_v2?GroupId={self.group_id}',
                headers=headers,
                json=data,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('base_resp', {}).get('status_code') == 0:
                    return {
                        'success': True,
                        'content': result['choices'][0]['message']['content']
                    }
                else:
                    return {
                        'success': False,
                        'error': f"MiniMax error: {result.get('base_resp', {}).get('status_msg', 'Unknown error')}"
                    }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': '测试'}
                ],
                'tokens_to_generate': 10
            }

            response = requests.post(
                f'{self.base_url}/text/chatcompletion_v2?GroupId={self.group_id}',
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('base_resp', {}).get('status_code') == 0:
                    return {
                        'success': True,
                        'message': f'Connected to MiniMax {self.model} successfully!'
                    }
                else:
                    return {
                        'success': False,
                        'error': f"MiniMax error: {result.get('base_resp', {}).get('status_msg', 'Unknown error')}"
                    }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


class OpenAIProvider(LLMProvider):
    """OpenAI provider (for future compatibility)."""

    def __init__(self, api_key: str, model: str = 'gpt-4o'):
        self.api_key = api_key
        self.model = model
        self.base_url = 'https://api.openai.com/v1'

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'max_tokens': max_tokens,
                'temperature': 0.7
            }

            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'content': result['choices'][0]['message']['content']
                }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }

            data = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': 'test'}
                ],
                'max_tokens': 10
            }

            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                return {
                    'success': True,
                    'message': f'Connected to OpenAI {self.model} successfully!'
                }
            else:
                return {
                    'success': False,
                    'error': f'API error: {response.status_code} - {response.text}'
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def extract_receipt_fields(self, image_bytes, image_mime='image/jpeg', hint=None):
        """v3.17.471 — OpenAI vision via data URL. Requires a vision-capable model
        (gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-4-vision-preview).
        Older text-only models will return an error from OpenAI."""
        import base64
        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        data_url = f'data:{image_mime};base64,{b64}'
        user_text = _RECEIPT_USER_PROMPT + (
            f'\n\nUser-supplied hint: this is a {hint} receipt.' if hint else ''
        )
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        body = {
            'model': self.model,
            'max_tokens': 2048,
            'response_format': {'type': 'json_object'},
            'messages': [
                {'role': 'system', 'content': _RECEIPT_SYSTEM_PROMPT},
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': user_text},
                    {'type': 'image_url', 'image_url': {'url': data_url}},
                ]},
            ],
        }
        try:
            resp = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers, json=body, timeout=60,
            )
            if resp.status_code != 200:
                return {
                    'success': False,
                    'error': f'API error: {resp.status_code} - {resp.text[:300]}',
                }
            data = resp.json()
            text = data['choices'][0]['message']['content']
            return _parse_receipt_json(text)
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


class OllamaProvider(LLMProvider):
    """Ollama on-premises LLM provider. No API key required — just a base URL."""

    def __init__(self, base_url: str = 'http://localhost:11434', model: str = 'llama3.2', **kwargs):
        self.base_url = base_url.rstrip('/')
        self.model = model

    def generate(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> Dict[str, Any]:
        try:
            resp = requests.post(
                f'{self.base_url}/api/chat',
                json={
                    'model': self.model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt},
                    ],
                    'stream': False,
                    'options': {'num_predict': max_tokens},
                },
                # Kept below the gunicorn worker --timeout (300s) so a slow
                # model surfaces as this caught Timeout → clean JSON error,
                # rather than the worker being SIGKILLed and the browser
                # getting an HTML 500 ("returned HTML instead of JSON" — #138).
                timeout=AI_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json().get('message', {}).get('content', '')
            return {'success': True, 'content': content}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': f'Cannot reach Ollama at {self.base_url} — is it running?'}
        except requests.exceptions.Timeout:
            return {'success': False, 'error': f'Ollama did not respond within {AI_HTTP_TIMEOUT}s. The model may be too large/slow for this host — try a smaller model or a shorter prompt.'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_model_name(self) -> str:
        return self.model

    def test_connection(self) -> Dict[str, Any]:
        try:
            resp = requests.get(f'{self.base_url}/api/tags', timeout=10)
            resp.raise_for_status()
            models = [m.get('name', '') for m in resp.json().get('models', [])]
            model_list = ', '.join(models[:8]) if models else 'none found'
            return {'success': True, 'message': f'Connected to Ollama. Available models: {model_list}'}
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': f'Cannot reach Ollama at {self.base_url} — ensure Ollama is running and accessible.'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def extract_receipt_fields(self, image_bytes, image_mime='image/jpeg', hint=None):
        """v3.17.471 — Ollama vision. Requires a vision-capable model
        (llava, llava-llama3, llama3.2-vision, bakllava, etc.). Text-only
        models will refuse / hallucinate."""
        import base64
        b64 = base64.standard_b64encode(image_bytes).decode('ascii')
        user_text = _RECEIPT_USER_PROMPT + (
            f'\n\nUser-supplied hint: this is a {hint} receipt.' if hint else ''
        )
        body = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': _RECEIPT_SYSTEM_PROMPT},
                {'role': 'user', 'content': user_text, 'images': [b64]},
            ],
            'stream': False,
            'format': 'json',  # Ollama JSON-mode — forces parseable output
            'options': {'temperature': 0.1, 'num_predict': 2048},
        }
        try:
            resp = requests.post(
                f'{self.base_url}/api/chat', json=body, timeout=120,
            )
            if resp.status_code != 200:
                return {
                    'success': False,
                    'error': f'Ollama HTTP {resp.status_code}: {resp.text[:300]}',
                }
            text = resp.json().get('message', {}).get('content', '')
            return _parse_receipt_json(text)
        except requests.exceptions.ConnectionError:
            return {'success': False, 'error': f'Cannot reach Ollama at {self.base_url}'}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}


def get_llm_provider(provider_name: str, **kwargs) -> Optional[LLMProvider]:
    """
    Factory function to get the appropriate LLM provider.

    Args:
        provider_name: Name of the provider ('anthropic', 'moonshot', 'minimax', 'minimax_coding', 'openai', 'ollama')
        **kwargs: Provider-specific configuration (api_key, model, etc.)

    Returns:
        LLMProvider instance or None if provider not found
    """
    providers = {
        'anthropic': AnthropicProvider,
        'moonshot': MoonshotProvider,
        'minimax': MiniMaxProvider,
        'minimax_coding': MiniMaxCodingProvider,
        'openai': OpenAIProvider,
        'ollama': OllamaProvider,
    }

    provider_class = providers.get(provider_name.lower())
    if provider_class:
        return provider_class(**kwargs)
    return None


def get_configured_provider() -> Optional[LLMProvider]:
    """
    v3.17.471 — return an instantiated LLMProvider built from Django
    settings, or None if the configured provider is missing credentials.

    Mirrors the provider selection in `AIDocumentationGenerator._init_provider`
    so receipt OCR and AI doc generation hit the same backend.
    """
    from django.conf import settings

    provider_name = (getattr(settings, 'LLM_PROVIDER', 'anthropic') or '').lower()

    if provider_name == 'anthropic':
        key = getattr(settings, 'ANTHROPIC_API_KEY', '')
        if not key:
            return None
        return get_llm_provider('anthropic',
            api_key=key,
            model=getattr(settings, 'CLAUDE_MODEL', 'claude-sonnet-4-5-20250929'),
        )

    if provider_name == 'openai':
        key = getattr(settings, 'OPENAI_API_KEY', '')
        if not key:
            return None
        return get_llm_provider('openai',
            api_key=key,
            model=getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini'),
        )

    if provider_name == 'ollama':
        base = getattr(settings, 'OLLAMA_BASE_URL', '')
        if not base:
            return None
        return get_llm_provider('ollama',
            base_url=base,
            model=getattr(settings, 'OLLAMA_MODEL', 'llava'),
        )

    if provider_name == 'moonshot':
        key = getattr(settings, 'MOONSHOT_API_KEY', '')
        if not key:
            return None
        return get_llm_provider('moonshot',
            api_key=key,
            model=getattr(settings, 'MOONSHOT_MODEL', 'moonshot-v1-8k'),
        )

    if provider_name in ('minimax', 'minimax_coding'):
        key = getattr(settings, 'MINIMAX_API_KEY', '')
        if not key:
            return None
        return get_llm_provider(provider_name,
            api_key=key,
            group_id=getattr(settings, 'MINIMAX_GROUP_ID', ''),
            model=getattr(settings, 'MINIMAX_MODEL', 'abab6.5-chat'),
        )

    return None


def is_llm_configured() -> tuple[bool, str]:
    """
    Check if any LLM provider is properly configured.

    Returns:
        tuple: (is_configured: bool, provider_name: str)
    """
    from django.conf import settings

    provider_name = getattr(settings, 'LLM_PROVIDER', 'anthropic').lower()

    # Check if the selected provider has its required credentials
    if provider_name == 'anthropic':
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
        return (bool(api_key), 'Anthropic Claude')
    elif provider_name == 'moonshot':
        api_key = getattr(settings, 'MOONSHOT_API_KEY', '')
        return (bool(api_key), 'Moonshot AI (Kimi)')
    elif provider_name == 'minimax':
        api_key = getattr(settings, 'MINIMAX_API_KEY', '')
        group_id = getattr(settings, 'MINIMAX_GROUP_ID', '')
        return (bool(api_key and group_id), 'MiniMax Chat')
    elif provider_name == 'minimax_coding':
        api_key = getattr(settings, 'MINIMAX_CODING_API_KEY', '')
        return (bool(api_key), 'MiniMax Coding Plan (M2.5)')
    elif provider_name == 'openai':
        api_key = getattr(settings, 'OPENAI_API_KEY', '')
        return (bool(api_key), 'OpenAI')
    elif provider_name == 'ollama':
        base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434')
        return (bool(base_url), 'Ollama (On-Premises)')
    else:
        return (False, 'Unknown')
