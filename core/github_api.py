"""
GitHub API integration for bug reporting
"""
import requests
import base64
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Exception raised for GitHub API errors"""
    pass


class GitHubIssueCreator:
    """Helper class for creating GitHub issues via API"""

    def __init__(self, token, repo='agit8or1/huduglue'):
        """
        Initialize GitHub issue creator

        Args:
            token: GitHub Personal Access Token
            repo: Repository in format 'owner/repo'
        """
        self.token = token
        self.repo = repo
        self.api_url = f'https://api.github.com/repos/{repo}/issues'

    def validate_token(self):
        """
        Validate the GitHub token

        Returns:
            bool: True if token is valid, False otherwise
        """
        headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'HuduGlue-BugReporter'
        }

        # Test by checking if we can access the repository
        repo_url = f'https://api.github.com/repos/{self.repo}'

        try:
            response = requests.get(repo_url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def create_issue(self, title, body, labels=None):
        """
        Create a GitHub issue

        Args:
            title: Issue title
            body: Issue body (markdown formatted)
            labels: List of label names (default: ['bug', 'user-reported'])

        Returns:
            dict: Issue data with 'number', 'html_url', 'url'

        Raises:
            GitHubAPIError: If issue creation fails
        """
        if labels is None:
            labels = ['bug', 'user-reported']

        headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'HuduGlue-BugReporter'
        }

        data = {
            'title': title,
            'body': body,
            'labels': labels
        }

        try:
            response = requests.post(self.api_url, json=data, headers=headers, timeout=30)

            if response.status_code == 201:
                issue_data = response.json()
                return {
                    'number': issue_data['number'],
                    'html_url': issue_data['html_url'],
                    'url': issue_data['url']
                }
            elif response.status_code == 401:
                raise GitHubAPIError('Invalid GitHub token. Please check your credentials.')
            elif response.status_code == 403:
                raise GitHubAPIError('GitHub API rate limit exceeded or token lacks permissions.')
            elif response.status_code == 404:
                raise GitHubAPIError(f'Repository {self.repo} not found or token lacks access.')
            else:
                error_msg = response.json().get('message', 'Unknown error')
                raise GitHubAPIError(f'GitHub API error: {error_msg}')

        except requests.exceptions.Timeout:
            raise GitHubAPIError('Request to GitHub timed out. Please try again.')
        except requests.exceptions.ConnectionError:
            raise GitHubAPIError('Unable to connect to GitHub. Please check your internet connection.')
        except GitHubAPIError:
            raise
        except Exception as e:
            raise GitHubAPIError(f'Unexpected error: {str(e)}')

    def upload_image_to_issue(self, issue_number, image_data, filename):
        """
        Upload an image as a comment to an existing issue

        Note: GitHub's API doesn't support direct image uploads to issues.
        This creates a comment noting that a screenshot was provided.
        Users can manually upload screenshots by drag-and-drop on GitHub.

        Args:
            issue_number: GitHub issue number
            image_data: Image file content (bytes)
            filename: Original filename

        Raises:
            GitHubAPIError: If comment creation fails
        """
        comment_url = f'{self.api_url}/{issue_number}/comments'

        headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'HuduGlue-BugReporter'
        }

        # Create a comment noting the screenshot
        comment_body = f'📎 **Screenshot attached**: `{filename}`\n\n_Note: Please drag-and-drop the screenshot image into this issue for full display._'

        data = {'body': comment_body}

        try:
            response = requests.post(comment_url, json=data, headers=headers, timeout=30)

            if response.status_code != 201:
                raise GitHubAPIError('Failed to add screenshot reference to issue')

        except requests.exceptions.Timeout:
            raise GitHubAPIError('Request to GitHub timed out while uploading screenshot reference')
        except requests.exceptions.ConnectionError:
            raise GitHubAPIError('Unable to connect to GitHub while uploading screenshot reference')
        except GitHubAPIError:
            raise
        except Exception as e:
            raise GitHubAPIError(f'Unexpected error uploading screenshot reference: {str(e)}')

    def test_connection(self):
        """
        Test if the GitHub token is valid

        Returns:
            tuple: (success: bool, message: str)
        """
        headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'HuduGlue-BugReporter'
        }

        # Test by checking if we can access the repository
        repo_url = f'https://api.github.com/repos/{self.repo}'

        try:
            response = requests.get(repo_url, headers=headers, timeout=10)

            if response.status_code == 200:
                return True, 'GitHub connection successful'
            elif response.status_code == 401:
                return False, 'Invalid GitHub token'
            elif response.status_code == 404:
                return False, f'Repository {self.repo} not found or token lacks access'
            else:
                return False, f'GitHub API returned status {response.status_code}'

        except requests.exceptions.Timeout:
            return False, 'Connection to GitHub timed out'
        except requests.exceptions.ConnectionError:
            return False, 'Unable to connect to GitHub'
        except Exception as e:
            return False, f'Error: {str(e)}'


def format_bug_report_body(description, steps_to_reproduce, system_info, reporter_info):
    """
    Format the bug report body as markdown

    Args:
        description: Bug description
        steps_to_reproduce: Steps to reproduce the bug
        system_info: Dict with system information (version, python, etc.)
        reporter_info: Dict with reporter information (username, email, org)

    Returns:
        str: Formatted markdown body
    """
    body_parts = []

    # Description section
    body_parts.append("## Description")
    body_parts.append(description)
    body_parts.append("")

    # Steps to reproduce (if provided)
    if steps_to_reproduce:
        body_parts.append("## Steps to Reproduce")
        body_parts.append(steps_to_reproduce)
        body_parts.append("")

    # System Information
    body_parts.append("## System Information")
    body_parts.append(f"- **HuduGlue Version**: {system_info.get('version', 'Unknown')}")
    body_parts.append(f"- **Django Version**: {system_info.get('django_version', 'Unknown')}")
    body_parts.append(f"- **Python Version**: {system_info.get('python_version', 'Unknown')}")
    body_parts.append(f"- **Operating System**: {system_info.get('os', 'Unknown')}")
    body_parts.append(f"- **Browser**: {system_info.get('browser', 'Unknown')}")
    body_parts.append(f"- **Timestamp**: {system_info.get('timestamp', 'Unknown')}")
    body_parts.append("")

    # Reporter Information
    body_parts.append("## Reported By")
    body_parts.append(f"- **User**: {reporter_info.get('username', 'Unknown')}")
    if reporter_info.get('email'):
        body_parts.append(f"- **Email**: {reporter_info['email']}")
    if reporter_info.get('organization'):
        body_parts.append(f"- **Organization**: {reporter_info['organization']}")
    body_parts.append("")

    body_parts.append("---")
    body_parts.append("_This bug report was submitted via HuduGlue's built-in bug reporting feature._")

    return "\n".join(body_parts)
