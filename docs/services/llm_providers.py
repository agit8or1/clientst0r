"""
Multi-LLM Provider Support for Client St0r
Supports Anthropic Claude, Moonshot AI (Kimi), MiniMax, and OpenAI
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import requests
import json


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


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider."""

    def __init__(self, api_key: str, model: str = 'claude-sonnet-4-5-20250929'):
        self.api_key = api_key
        self.model = model

        # Import anthropic only when this provider is used
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

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

            return {
                'success': True,
                'content': response.content[0].text
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


def get_llm_provider(provider_name: str, **kwargs) -> Optional[LLMProvider]:
    """
    Factory function to get the appropriate LLM provider.

    Args:
        provider_name: Name of the provider ('anthropic', 'moonshot', 'minimax', 'openai')
        **kwargs: Provider-specific configuration (api_key, model, etc.)

    Returns:
        LLMProvider instance or None if provider not found
    """
    providers = {
        'anthropic': AnthropicProvider,
        'moonshot': MoonshotProvider,
        'minimax': MiniMaxProvider,
        'openai': OpenAIProvider,
    }

    provider_class = providers.get(provider_name.lower())
    if provider_class:
        return provider_class(**kwargs)
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
        return (bool(api_key and group_id), 'MiniMax')
    elif provider_name == 'openai':
        api_key = getattr(settings, 'OPENAI_API_KEY', '')
        return (bool(api_key), 'OpenAI')
    else:
        return (False, 'Unknown')
